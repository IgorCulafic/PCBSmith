from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.kicad.validate import run_kicad_drc
from pcbsmith.placement_repair_transaction import (
    PlacementPose,
    extract_placement_snapshot,
    run_placement_repair_transaction,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments" / "phase17-w10-upstream-repair-v10-2026-08-20" / "boards"
OUTPUT = ROOT / "experiments" / "phase17-if3-placement-proof-v2-2026-08-20"


def _snap(value_mm: float) -> float:
    return round(round(value_mm / 0.25) * 0.25, 3)


def _targets(board: Path, references: tuple[str, ...]) -> tuple[PlacementPose, ...]:
    snapshot = extract_placement_snapshot(board)
    poses = {item.reference: item for item in snapshot.poses}
    selected = [poses[reference] for reference in references]
    center_x = sum(item.x_mm for item in selected) / len(selected)
    center_y = sum(item.y_mm for item in selected) / len(selected)
    return tuple(
        PlacementPose(
            reference=item.reference,
            x_mm=_snap(item.x_mm + (center_x - item.x_mm) * 0.15),
            y_mm=_snap(item.y_mm + (center_y - item.y_mm) * 0.15),
            rotation_deg=item.rotation_deg,
            side=item.side,
        )
        for item in selected
    )


def _placement_drc(candidate: Path) -> tuple[str, ...]:
    report = run_kicad_drc(candidate, schematic_parity=False)
    report_path = Path(report.drc_report)
    if not report_path.exists():
        return ("placement_drc_report_missing",)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    violations = payload.get("violations")
    if not isinstance(violations, list):
        return ("placement_drc_violations_malformed",)
    return tuple(
        f"placement_drc:{item.get('type', 'unknown')}:{item.get('description', 'violation')}"
        for item in violations
    )


def main() -> int:
    cases = (
        (
            "W10A-ne555-status-pulser",
            "W10A-ne555-status-pulser-placement.kicad_pcb",
            ("U1", "R1", "R2", "R3", "C1", "C2", "C3"),
        ),
        (
            "W10B-12v-to-5v-buck",
            "W10B-12v-to-5v-buck-placement.kicad_pcb",
            ("U1", "D1", "L1", "CIN", "COUT", "RFB1", "RFB2"),
        ),
    )
    summaries: list[dict[str, object]] = []
    for case, filename, references in cases:
        board = SOURCE / case / filename
        result = run_placement_repair_transaction(
            source_board=board,
            target_poses=_targets(board, references),
            retained_root=OUTPUT / case / "candidates",
            minimum_anchor_spacing_mm=2.0,
            exact_validator=_placement_drc,
            placement_grid_mm=0.25,
        )
        retained_board = Path(result.retained_board)
        drc = json.loads(
            (retained_board.parent / ".pcbsmith" / "kicad" / "drc.json").read_text(encoding="utf-8")
        )
        summaries.append(
            {
                "case": case,
                "source_board_sha256": result.before.board_sha256,
                "candidate_board_sha256": result.after.board_sha256,
                "before_topology_cost": result.before.topology_cost,
                "after_topology_cost": result.after.topology_cost,
                "improvement_percent": round(
                    100
                    * (result.before.topology_cost - result.after.topology_cost)
                    / result.before.topology_cost,
                    3,
                ),
                "changed_references": list(result.changed_references),
                "protected_reference_count": len(result.protected_references),
                "accepted": result.accepted,
                "blockers": list(result.blockers),
                "placement_drc_violation_count": len(drc["violations"]),
                "expected_unrouted_item_count": len(drc["unconnected_items"]),
                "retained_board": str(retained_board.relative_to(ROOT)),
                "project_library_retained": (
                    retained_board.parent.joinpath("fp-lib-table").exists()
                    and retained_board.parent.joinpath("PCBSmith.pretty").is_dir()
                ),
                "before_view": [item.model_dump(mode="json") for item in result.before.poses],
                "after_view": [item.model_dump(mode="json") for item in result.after.poses],
            }
        )
    payload = {
        "schema_id": "pcbsmith-phase17-if3-placement-proof",
        "schema_version": 2,
        "cases": summaries,
        "all_candidates_accepted": all(item["accepted"] for item in summaries),
        "conclusion": (
            "W10 placement-only cluster candidates are evaluated with retained project-local "
            "libraries and real KiCad placement DRC. Unconnected items are recorded as the "
            "expected pre-route state, not accepted as routed-board evidence."
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if payload["all_candidates_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
