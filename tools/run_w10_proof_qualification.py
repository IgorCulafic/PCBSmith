"""Qualify the frozen W10 proof pair against exact saved-board evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from pcbsmith.automatic_review_gate import (
    CANONICAL_FINAL_ARTIFACT_IDS,
    qualify_automatic_review,
)
from pcbsmith.kicad.cli import find_kicad_cli, run_kicad_process
from pcbsmith.kicad.final_fill_adapter import parse_kicad_final_fill_snapshot
from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFinalFillConnectivityObservation,
    classify_final_fill_reachability,
)
from pcbsmith.kicad.final_fill_thermal import audit_kicad_thermal_spokes
from pcbsmith.kicad.model_preflight import preflight_board_models
from pcbsmith.kicad.routing_evidence import (
    inspect_kicad_drc_report,
    inspect_saved_board_routing,
)
from pcbsmith.kicad.validate import run_kicad_drc, run_kicad_erc
from pcbsmith.production_marking_adapter import (
    ProductionMarkingRequirements,
    audit_kicad_production_markings,
    inspect_saved_board_markings,
)
from pcbsmith.review.visual_package import (
    RenderProfile,
    ReviewArtifact,
    ReviewFeatures,
    VisualReviewManifest,
    generate_visual_review_package,
)
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.whole_board_qualification_adapter import qualify_production_board


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_project_context(case_dir: Path, output: Path, board_source: Path) -> tuple[Path, Path]:
    project = next(case_dir.glob("*.kicad_pro"))
    schematic = next(case_dir.glob("*.kicad_sch"))
    output.mkdir(parents=True, exist_ok=False)
    board = output / f"{project.stem}.kicad_pcb"
    shutil.copy2(board_source, board)
    for source in (project, schematic, case_dir / "sym-lib-table", case_dir / "PCBSmith.kicad_sym"):
        if source.exists():
            shutil.copy2(source, output / source.name)
    return board, output / schematic.name


def _missing_manifest(board: Path, error: str) -> VisualReviewManifest:
    board_sha = _sha(board)
    return VisualReviewManifest(
        schema_id="pcbsmith-visual-review-manifest-v1",
        render_profile=RenderProfile(),
        stage="final",
        board_file=str(board.resolve()),
        board_sha256=board_sha,
        copper_sha256=board_sha,
        kicad_version="unavailable:review-generation-failed",
        renderer_version="unavailable:review-generation-failed",
        model_preflight_status="unavailable:not-retained",
        package_status="generation_failed",
        artifacts=tuple(
            ReviewArtifact(
                artifact_id=artifact_id,
                category="canonical-final",
                relative_path=f"missing/{artifact_id.replace(':', '-')}.png",
                media_type="image/png",
                required=True,
                state="missing",
            )
            for artifact_id in CANONICAL_FINAL_ARTIFACT_IDS
        ),
        findings=(f"review generation failed: {error}",),
    )


def _qualify_case(
    case_dir: Path, output: Path, *, kicad_python: Path, bridge: Path
) -> dict[str, object]:
    contract_path = case_dir / "case-contract.json"
    contract = json.loads(contract_path.read_text("utf-8"))
    case_id = str(contract["case_id"])
    attempt = case_dir / "external" / "freerouting-v2.3.0" / "attempt-01"
    route_evidence = json.loads((attempt / "route-evidence.json").read_text("utf-8"))
    routed_candidates = tuple(attempt.glob("*-freerouting.kicad_pcb"))
    if len(routed_candidates) != 1:
        raise ValueError(f"{case_id}: expected one routed candidate")
    routed = routed_candidates[0]
    if _sha(routed) != route_evidence["routed_board_sha256"]:
        raise ValueError(f"{case_id}: routed candidate hash differs from retained evidence")

    final_dir = output / "final-revision"
    final_board, final_schematic = _copy_project_context(case_dir, final_dir, routed)
    pre_refill = output / "pre-refill-routed.kicad_pcb"
    shutil.copy2(routed, pre_refill)

    erc_report = run_kicad_erc(final_schematic)
    drc_report = run_kicad_drc(final_board, schematic_parity=True)
    drc_path = Path(drc_report.drc_report)
    erc_path = Path(erc_report.erc_report)
    final_sha = _sha(final_board)

    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad CLI unavailable during W10 qualification")
    version_result = run_kicad_process((install.path, "--version"))
    kicad_version = version_result.stdout.strip() or f"unavailable:{install.source}"
    snapshot = parse_kicad_final_fill_snapshot(
        pre_refill,
        final_board,
        kicad_version=kicad_version,
        refilled_by_kicad=True,
    )

    connectivity_path = output / "connectivity-observation.json"
    bridge_process = subprocess.run(
        (str(kicad_python), str(bridge), str(final_board), str(connectivity_path)),
        capture_output=True,
        check=False,
        timeout=120,
    )
    (output / "connectivity-bridge.stdout.log").write_bytes(bridge_process.stdout)
    (output / "connectivity-bridge.stderr.log").write_bytes(bridge_process.stderr)
    if bridge_process.returncode != 0 or not connectivity_path.exists():
        raise RuntimeError(f"{case_id}: final-fill bridge failed ({bridge_process.returncode})")
    observation = KiCadFinalFillConnectivityObservation.model_validate_json(
        connectivity_path.read_text("utf-8")
    )
    classified = classify_final_fill_reachability(
        snapshot,
        observation,
        declared_source_pad_ids=(),
    )
    thermal = audit_kicad_thermal_spokes(
        observation,
        drc_path,
        drc_report_board_sha256=final_sha,
    )

    model_preflight = preflight_board_models(final_board)
    features = ReviewFeatures(
        declared_classes=(
            ("power_ground", "high_current")
            if contract.get("expected_current_paths")
            else ("power_ground",)
        )
    )
    review_error: str | None = None
    try:
        manifest = generate_visual_review_package(
            board_file=final_board,
            output_dir=output / "visual-package",
            stage="final",
            features=features,
            model_preflight=model_preflight,
            source_revision=route_evidence["routed_board_sha256"],
        )
    except Exception as exc:  # retain a fail-closed manifest and continue all gates
        review_error = f"{type(exc).__name__}: {exc}"
        manifest = _missing_manifest(final_board, review_error)
        _write_json(output / "visual-package" / "review" / "manifest.json", manifest)

    inventory = inspect_saved_board_markings(final_board)
    requirements = ProductionMarkingRequirements.build(
        board_sha256=final_sha,
        source_authority_sha256=_sha(contract_path),
        declaration_complete=True,
        required_refdes_refs=inventory.footprint_refs,
        required_polarity_refs=tuple(contract.get("required_polarity_refs", ())),
        required_connector_mating_refs=tuple(contract.get("required_connector_mating_refs", ())),
    )
    marking = audit_kicad_production_markings(
        inventory=inventory,
        requirements=requirements,
        drc_report=drc_path,
        drc_report_board_sha256=final_sha,
    )
    manifest_fingerprint = fingerprint(manifest.model_dump(mode="json", by_alias=True))
    automatic_review = qualify_automatic_review(
        manifest=manifest,
        manifest_fingerprint=manifest_fingerprint,
        marking_audit=marking,
    )
    qualification = qualify_production_board(
        case_id=case_id,
        refilled_board_sha256=final_sha,
        drc_evidence=inspect_kicad_drc_report(drc_path),
        drc_board_sha256=final_sha,
        routing_evidence=inspect_saved_board_routing(final_board),
        fill_snapshot=classified,
        fill_connectivity=observation,
        thermal_audit=thermal,
        topology=None,
        current_paths=(),
        fabrication_profile=None,
        reference_continuity=None,
        automatic_review=automatic_review,
        craft=None,
    )

    retained = {
        "erc-report.json": json.loads(erc_path.read_text("utf-8")),
        "drc-report.json": json.loads(drc_path.read_text("utf-8")),
        "final-fill-snapshot.json": classified,
        "thermal-spoke-audit.json": thermal,
        "model-preflight.json": model_preflight,
        "marking-inventory.json": inventory,
        "marking-requirements.json": requirements,
        "marking-audit.json": marking,
        "automatic-review.json": automatic_review,
        "whole-board-qualification.json": qualification,
    }
    for name, value in retained.items():
        _write_json(output / name, value)

    gates = {item.gate_id: item.disposition.value for item in qualification.gates}
    return {
        "case_id": case_id,
        "final_board": str(final_board.resolve()),
        "final_board_sha256": final_sha,
        "source_routed_board_sha256": route_evidence["routed_board_sha256"],
        "source_mutated": _sha(routed) != route_evidence["routed_board_sha256"],
        "erc_status": erc_report.status,
        "erc_finding_count": len(erc_report.findings),
        "erc_findings": list(erc_report.findings),
        "drc_status": drc_report.status,
        "drc_finding_count": len(drc_report.findings),
        "drc_findings": list(drc_report.findings),
        "route_width_intent_accepted": bool(
            route_evidence["widths"]["report"]["width_intent_accepted"]
        ),
        "route_segment_count": route_evidence["geometry"]["segment_count"],
        "route_via_count": route_evidence["geometry"]["via_count"],
        "zone_count": len(classified.zones),
        "filled_region_count": len(classified.regions),
        "thermal_disposition": thermal.disposition.value,
        "marking_finding_count": len(marking.finding_ids),
        "marking_unverified_check_ids": list(marking.unverified_check_ids),
        "visual_package_status": manifest.package_status,
        "visual_generation_error": review_error,
        "required_visuals_generated": automatic_review.visual_package_complete,
        "gate_dispositions": gates,
        "release_qualified": qualification.release_qualified,
        "release_blockers": list(qualification.blocker_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--kicad-python",
        type=Path,
        default=Path("C:/Program Files/KiCad/10.0/bin/python.exe"),
    )
    parser.add_argument(
        "--bridge",
        type=Path,
        default=Path("tools/kicad_final_fill_connectivity_bridge.py"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    qualification_root = root / "qualification"
    if qualification_root.exists():
        raise FileExistsError(f"qualification output already exists: {qualification_root}")
    qualification_root.mkdir(parents=True)
    rows = []
    for case_dir in sorted((root / "boards").iterdir()):
        if case_dir.is_dir():
            rows.append(
                _qualify_case(
                    case_dir,
                    qualification_root / case_dir.name,
                    kicad_python=args.kicad_python.resolve(),
                    bridge=args.bridge.resolve(),
                )
            )
    summary = {
        "schema": "pcbsmith-phase17-w10-proof-qualification-v1",
        "case_count": len(rows),
        "release_qualified_count": sum(row["release_qualified"] for row in rows),
        "erc_clean_count": sum(row["erc_status"] == "passed" for row in rows),
        "drc_clean_count": sum(row["drc_status"] == "passed" for row in rows),
        "visual_complete_count": sum(row["required_visuals_generated"] for row in rows),
        "source_mutation_count": sum(row["source_mutated"] for row in rows),
        "cases": rows,
        "qualification_boundary": (
            "Two new two-layer proof revisions, exact post-router saved boards, KiCad ERC/DRC "
            "and parity, W3 fill/thermal, W9 marking, canonical review generation, and W7 "
            "fail-closed composition. Missing topology, current, craft, or semantic marking "
            "authority remains a blocker and is not inferred from clean routing."
        ),
    }
    _write_json(qualification_root / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["release_qualified_count"] == summary["case_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
