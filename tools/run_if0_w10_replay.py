"""Replay IF0 authority gates against the frozen W10 proof pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from pcbsmith.automatic_review_gate import ProductionMarkingAudit, qualify_automatic_review
from pcbsmith.kicad.final_fill_adapter import KiCadFinalFillSnapshot
from pcbsmith.kicad.final_fill_connectivity import KiCadFinalFillConnectivityObservation
from pcbsmith.kicad.final_fill_thermal import KiCadThermalSpokeAudit
from pcbsmith.kicad.model_preflight import ModelRequirement, preflight_board_models
from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report, inspect_saved_board_routing
from pcbsmith.kicad.validate import run_kicad_drc, run_kicad_erc
from pcbsmith.power_topology_ir import BoardPowerTopology
from pcbsmith.pre_route_integrity import inspect_pre_route_integrity
from pcbsmith.review.visual_package import VisualReviewManifest
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.whole_board_qualification_adapter import qualify_production_board


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_pre_route_context(case: Path, output: Path) -> tuple[Path, Path]:
    project = next(case.glob("*.kicad_pro"))
    schematic = next(case.glob("*.kicad_sch"))
    placement = next(case.glob("*-placement.kicad_pcb"))
    output.mkdir(parents=True, exist_ok=False)
    board_copy = output / f"{project.stem}.kicad_pcb"
    schematic_copy = output / schematic.name
    shutil.copy2(placement, board_copy)
    shutil.copy2(schematic, schematic_copy)
    shutil.copy2(project, output / project.name)
    for name in ("sym-lib-table", "PCBSmith.kicad_sym"):
        source = case / name
        if source.exists():
            shutil.copy2(source, output / name)
    return board_copy, schematic_copy


def _case(root: Path, case: Path, output: Path) -> dict[str, object]:
    case_id = case.name
    contract_path = case / "case-contract.json"
    contract = json.loads(contract_path.read_text("utf-8"))
    source_placement = case / contract["placement_board"]
    source_placement_before = _sha(source_placement)
    if source_placement_before != contract["placement_board_sha256"]:
        raise ValueError(f"{case_id}: frozen placement no longer matches its contract")
    retained = root / "qualification" / case_id
    pre_route_dir = output / "pre-route-context"
    placement_board, placement_schematic = _copy_pre_route_context(case, pre_route_dir)
    erc = run_kicad_erc(placement_schematic, report_name="if0-erc.json")
    drc = run_kicad_drc(placement_board, schematic_parity=True)
    if erc.erc_report is None or drc.drc_report is None:
        raise RuntimeError(f"{case_id}: KiCad did not retain pre-route reports")
    pre_route = inspect_pre_route_integrity(
        board_file=placement_board,
        schematic_file=placement_schematic,
        erc_report=Path(erc.erc_report),
        drc_report=Path(drc.drc_report),
    )
    _write(output / "pre-route-integrity.json", pre_route)

    final_board = next((retained / "final-revision").glob("*.kicad_pcb"))
    final_sha = _sha(final_board)
    manifest = VisualReviewManifest.model_validate_json(
        (retained / "visual-package/review/manifest.json").read_text("utf-8")
    )
    marking = ProductionMarkingAudit.model_validate_json(
        (retained / "marking-audit.json").read_text("utf-8")
    )
    inventory_payload = json.loads((retained / "marking-inventory.json").read_text("utf-8"))
    references = tuple(sorted(inventory_payload["footprint_refs"]))
    model = preflight_board_models(
        final_board,
        requirements=tuple(
            ModelRequirement(
                reference=reference,
                accepted_classifications=(
                    "exact_package",
                    "complete_module",
                    "connector_only",
                ),
            )
            for reference in references
        ),
    )
    manifest = manifest.model_copy(
        update={
            "model_preflight_status": model.status,
            "package_status": (
                manifest.package_status if model.status == "passed" else "generation_failed"
            ),
        }
    )
    automatic = qualify_automatic_review(
        manifest=manifest,
        manifest_fingerprint=fingerprint(manifest.model_dump(mode="json", by_alias=True)),
        marking_audit=marking,
    )
    topology = BoardPowerTopology.build(
        topology_id=f"{case_id}-if0-unresolved",
        board_sha256=final_sha,
        fabrication_profile_sha256=_sha(contract_path),
        applicability="unresolved",
        applicability_rationale=(
            "The frozen proof contract has power semantics, but W10 did not compile "
            "revision-bound terminals, regions, paths, and return relationships."
        ),
        terminals=(),
        regions=(),
        paths=(),
        return_relationships=(),
    )
    fill = KiCadFinalFillSnapshot.model_validate_json(
        (retained / "final-fill-snapshot.json").read_text("utf-8")
    )
    connectivity = KiCadFinalFillConnectivityObservation.model_validate_json(
        (retained / "connectivity-observation.json").read_text("utf-8")
    )
    thermal = KiCadThermalSpokeAudit.model_validate_json(
        (retained / "thermal-spoke-audit.json").read_text("utf-8")
    )
    final_drc = inspect_kicad_drc_report(retained / "drc-report.json")
    qualification = qualify_production_board(
        case_id=f"{case_id}-if0-replay",
        refilled_board_sha256=final_sha,
        drc_evidence=final_drc,
        drc_board_sha256=final_sha,
        routing_evidence=inspect_saved_board_routing(final_board),
        fill_snapshot=fill,
        fill_connectivity=connectivity,
        thermal_audit=thermal,
        topology=topology,
        current_paths=(),
        fabrication_profile=None,
        reference_continuity=None,
        automatic_review=automatic,
        craft=None,
    )
    for name, value in (
        ("effective-review-manifest.json", manifest),
        ("model-preflight.json", model),
        ("automatic-review.json", automatic),
        ("topology-applicability.json", topology),
        ("whole-board-qualification.json", qualification),
    ):
        _write(output / name, value)
    gates = {item.gate_id: item.disposition.value for item in qualification.gates}
    return {
        "case_id": case_id,
        "source_placement_sha256": _sha(source_placement),
        "source_placement_contract_sha256": contract["placement_board_sha256"],
        "source_placement_unchanged": _sha(source_placement) == source_placement_before,
        "replay_placement_sha256_after_kicad": _sha(placement_board),
        "pre_route_accepted": pre_route.accepted,
        "pre_route_blockers": list(pre_route.blockers),
        "model_preflight_status": model.status,
        "model_required_reference_count": len(model.required_references),
        "visual_package_status": manifest.package_status,
        "automatic_review_accepted": automatic.accepted,
        "automatic_review_blockers": list(automatic.blocker_ids),
        "topology_applicability": topology.applicability,
        "gate_dispositions": gates,
        "release_qualified": qualification.release_qualified,
        "release_blockers": list(qualification.blocker_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = tuple(
        _case(root, case, output / case.name)
        for case in sorted((root / "boards").iterdir())
        if case.is_dir()
    )
    summary = {
        "schema": "pcbsmith-if0-w10-replay-v1",
        "case_count": len(rows),
        "pre_route_accepted_count": sum(row["pre_route_accepted"] for row in rows),
        "automatic_review_accepted_count": sum(row["automatic_review_accepted"] for row in rows),
        "model_preflight_passed_count": sum(
            row["model_preflight_status"] == "passed" for row in rows
        ),
        "release_qualified_count": sum(row["release_qualified"] for row in rows),
        "cases": rows,
        "interpretation": (
            "IF0 replays frozen W10 placement/final revisions. It does not repair or regenerate "
            "the boards; KiCad operates only on copied placement context. A failed replay is the "
            "expected proof that pending inspection, empty model requirements, "
            "ERC/parity findings, "
            "and unresolved topology can no longer become positive workflow evidence."
        ),
    }
    _write(output / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
