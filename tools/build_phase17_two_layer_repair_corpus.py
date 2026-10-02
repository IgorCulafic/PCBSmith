"""Build the eight-case two-layer topology-placement repair corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from pcbsmith.kicad.board import render_board_from_layout
from pcbsmith.kicad.routing_benchmark_corpus import (
    case_layout,
    case_netlist,
    register_benchmark_footprints,
)
from pcbsmith.kicad.routing_real_test_corpus import build_real_test_cases
from pcbsmith.kicad.two_layer_topology_placement import (
    build_two_layer_critical_preroutes,
    build_two_layer_series_escape_preroutes,
    propose_two_layer_topology_placement,
)
from pcbsmith.prototypes.kicad_project import render_kicad_project_file

REPRESENTATIVE_CASES = (
    "RT01",
    "RT10",
    "RT17",
    "RT24",
    "RT31",
    "RT35",
    "RT37",
    "RT40",
)


def _slug(value: str) -> str:
    characters = "".join(character.lower() if character.isalnum() else " " for character in value)
    return "-".join(characters.split())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_corpus(
    output_root: Path,
    route_feedback: dict[str, frozenset[str]] | None = None,
) -> dict[str, object]:
    register_benchmark_footprints()
    output_root.mkdir(parents=True, exist_ok=True)
    original_by_id = {case.case_id: case for case in build_real_test_cases()}
    records: list[dict[str, object]] = []
    repaired_records: list[dict[str, object]] = []

    for case_id in REPRESENTATIVE_CASES:
        original = original_by_id[case_id]
        proposal = propose_two_layer_topology_placement(original)
        updated_placements = tuple(
            replace(
                placement,
                x_mm=proposal.poses[placement.reference][0],
                y_mm=proposal.poses[placement.reference][1],
                rotation_deg=proposal.poses[placement.reference][2],
            )
            for placement in original.placements
        )
        repaired = replace(
            original,
            placements=updated_placements,
            design_note=(
                f"{original.design_note} Two-layer topology-derived placement seed; "
                "pending R5 legalization/routability and routed-board acceptance."
            ),
            tags=(*original.tags, "two-layer-topology-repair-v1"),
        )
        repaired_records.append(repaired.record())
        project_name = f"{case_id}-{_slug(original.title)}"
        case_dir = output_root / "boards" / project_name
        case_dir.mkdir(parents=True, exist_ok=True)
        reserved_segments, reserved_vias = build_two_layer_critical_preroutes(repaired, proposal)
        base_layout = replace(
            case_layout(repaired),
            segments=reserved_segments,
            vias=reserved_vias,
            zones=(proposal.ground_zone,),
        )
        feedback_targets = (
            route_feedback.get(case_id, frozenset()) if route_feedback is not None else None
        )
        series_segments, series_escape_evidence = build_two_layer_series_escape_preroutes(
            repaired,
            base_layout,
            case_netlist(repaired),
            target_net_names=feedback_targets,
        )
        layout = replace(
            base_layout,
            segments=(*base_layout.segments, *series_segments),
        )
        board = case_dir / f"{project_name}-placement.kicad_pcb"
        project = case_dir / f"{project_name}.kicad_pro"
        board.write_text(render_board_from_layout(case_netlist(repaired), layout), encoding="utf-8")
        project.write_text(render_kicad_project_file(project_name), encoding="utf-8")
        _write_json(case_dir / "case-contract.json", repaired.record())
        _write_json(case_dir / "two-layer-placement-evidence.json", asdict(proposal.evidence))
        _write_json(
            case_dir / "two-layer-series-escape-evidence.json", asdict(series_escape_evidence)
        )
        record = {
            "case_id": case_id,
            "title": original.title,
            "status": "topology_seed_pending_r5",
            "layers": 2,
            "four_layer_escalation_allowed": False,
            "placement_board": board.relative_to(output_root).as_posix(),
            "placement_board_sha256": _sha256(board),
            "project_file": project.relative_to(output_root).as_posix(),
            "project_file_sha256": _sha256(project),
            "evidence": (case_dir / "two-layer-placement-evidence.json")
            .relative_to(output_root)
            .as_posix(),
            "reserved_local_segment_count": len(reserved_segments),
            "reserved_ground_via_count": len(reserved_vias),
            "accepted_series_escape_count": series_escape_evidence.accepted_count,
            "rejected_series_escape_count": series_escape_evidence.rejected_count,
            "reserved_series_segment_count": len(series_segments),
            "feedback_target_nets": (
                sorted(feedback_targets) if feedback_targets is not None else None
            ),
            "series_escape_evidence": (
                (case_dir / "two-layer-series-escape-evidence.json")
                .relative_to(output_root)
                .as_posix()
            ),
        }
        records.append(record)

    protocol = {
        "schema": "pcbsmith-two-layer-placement-repair-corpus-v1",
        "source_corpus": "experiments/phase17-real-test-40-2026-08-16",
        "case_ids": list(REPRESENTATIVE_CASES),
        "layers": 2,
        "four_layer_escalation_allowed": False,
        "home_fabrication_constraint": "Two copper layers are a fixed user requirement.",
        "reference_strategy": "Reserve a B.Cu GND zone before detailed routing.",
        "terminal_escape_strategy": (
            "Pad-pitch-derived 0.30-0.50 mm 0603/IC neck-downs, then declared bulk net width; "
            "1.40/0.60 mm GND vias support home drilling; bounded obstacle-aware F.Cu "
            "U1-to-series escapes are transactionally accepted before bulk routing."
        ),
        "series_escape_selection": (
            "prior-route-feedback-only" if route_feedback is not None else "speculative-all"
        ),
        "current_stage": "Topology-derived candidate zero; R5 and routing are not yet accepted.",
        "acceptance_order": [
            "topology relationship evidence",
            "R5 legalization and routability",
            "exact KiCad placement/read-back review",
            "Freerouting candidate",
            "KiCad connectivity and DRC",
            "reference-continuity and visual craft review",
        ],
    }
    _write_json(output_root / "protocol.json", protocol)
    _write_json(output_root / "case-matrix.json", repaired_records)
    summary = {
        "schema": "pcbsmith-two-layer-placement-repair-summary-v1",
        "case_count": len(records),
        "status": "placement_candidates_only",
        "cases": records,
    }
    _write_json(output_root / "generation-summary.json", summary)
    manifest = []
    for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
        if path.name == "artifact-manifest.json":
            continue
        manifest.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    _write_json(output_root / "artifact-manifest.json", {"files": manifest})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--route-feedback", type=Path)
    args = parser.parse_args()
    route_feedback = None
    if args.route_feedback is not None:
        payload = json.loads(args.route_feedback.read_text(encoding="utf-8"))
        if payload.get("schema") != "pcbsmith-two-layer-series-escape-feedback-v1":
            raise ValueError("unsupported route-feedback schema")
        targets = payload.get("targets")
        if not isinstance(targets, dict):
            raise TypeError("route-feedback targets must be an object")
        route_feedback = {
            str(case_id): frozenset(str(net_name) for net_name in net_names)
            for case_id, net_names in targets.items()
            if isinstance(net_names, list)
        }
    print(json.dumps(build_corpus(args.output, route_feedback), indent=2))


if __name__ == "__main__":
    main()
