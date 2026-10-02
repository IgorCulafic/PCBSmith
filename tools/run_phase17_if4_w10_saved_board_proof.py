"""Run real saved-board selected-segment repairs on the clean W10 pair."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

from pcbsmith.kicad.library import QuotedString, SExpr, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.validate import run_kicad_drc
from pcbsmith.local_routing_repair import (
    RoutingCandidateMetrics,
    RoutingRepairRegion,
    SelectedRoutingDomain,
    run_local_routing_repair,
)
from pcbsmith.saved_board_routing_evidence import (
    evaluate_saved_routing_candidate,
    extract_saved_routing_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments" / "phase17-w10-upstream-repair-v10-2026-08-20" / "boards"
OUTPUT = ROOT / "experiments" / "phase17-if4-w10-saved-board-proof-v2-2026-08-20"

CASES = (
    (
        "W10A-ne555-status-pulser",
        "W10A_NE555_Status_Pulser.kicad_pcb",
        "CTRL",
        "segment:6fa76cc4-b533-4d56-b07d-02d6f5052871",
        0.3,
    ),
    (
        "W10B-12v-to-5v-buck",
        "W10B_12V_to_5V_Buck.kicad_pcb",
        "FB",
        "segment:9cbbc634-68c8-45d8-84a0-b98ee764dadb",
        0.3,
    ),
)


def _head(node: object) -> str:
    if not isinstance(node, list) or not node:
        return ""
    value = node[0]
    return value.value if isinstance(value, QuotedString) else str(value)


def _child_atom(node: list[SExpr], name: str) -> str | None:
    child = next((item for item in node if _head(item) == name), None)
    if child is None or len(child) < 2:
        return None
    value = child[1]
    return value.value if isinstance(value, QuotedString) else str(value)


def _remove_route_object(board: Path, object_id: str) -> list[SExpr]:
    kind, uuid = object_id.split(":", maxsplit=1)
    root = parse_sexpr(board.read_text(encoding="utf-8"))
    removed = [
        deepcopy(item) for item in root if _head(item) == kind and _child_atom(item, "uuid") == uuid
    ]
    if len(removed) != 1:
        raise ValueError(f"expected one route object {object_id}, found {len(removed)}")
    root[:] = [
        item for item in root if not (_head(item) == kind and _child_atom(item, "uuid") == uuid)
    ]
    board.write_text(serialize_sexpr(root) + "\n", encoding="utf-8")
    return removed[0]


def _restore_route_object(board: Path, route_object: list[SExpr]) -> None:
    root = parse_sexpr(board.read_text(encoding="utf-8"))
    root.append(deepcopy(route_object))
    board.write_text(serialize_sexpr(root) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _region(index: int) -> RoutingRepairRegion:
    margin = 0.5 + (index * 15.0)
    return RoutingRepairRegion(
        x_min_mm=50 - margin,
        y_min_mm=25 - margin,
        x_max_mm=50 + margin,
        y_max_mm=25 + margin,
        expansion_index=index,
    )


def _metrics_for_region(
    metrics: RoutingCandidateMetrics, region: RoutingRepairRegion, suffix: str
) -> RoutingCandidateMetrics:
    return metrics.model_copy(
        update={"region": region, "candidate_id": f"{metrics.candidate_id}-{suffix}"}
    )


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"proof output already exists: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    summaries: list[dict[str, object]] = []
    for case, board_name, net_name, mutable_id, width_mm in CASES:
        case_output = OUTPUT / case
        fault_dir = case_output / "fault-source"
        restored_dir = case_output / "restored-candidate"
        shutil.copytree(SOURCE / case, fault_dir)
        fault_board = fault_dir / board_name
        removed = _remove_route_object(fault_board, mutable_id)
        fault_drc = run_kicad_drc(fault_board, schematic_parity=True)

        shutil.copytree(fault_dir, restored_dir)
        restored_board = restored_dir / board_name
        _restore_route_object(restored_board, removed)
        restored_drc = run_kicad_drc(restored_board, schematic_parity=True)

        source_snapshot = extract_saved_routing_snapshot(fault_board)
        protected = tuple((item.object_id, item.content_sha256) for item in source_snapshot.objects)
        domain = SelectedRoutingDomain(
            domain_id=f"{case}:{net_name}:single-segment-open",
            net_names=(net_name,),
            mutable_object_ids=(mutable_id,),
            protected_object_fingerprints=protected,
            initial_region=_region(0),
            maximum_expansions=1,
        )
        fault_metrics = evaluate_saved_routing_candidate(
            source_board=fault_board,
            candidate_board=fault_board,
            domain=domain,
            region=domain.initial_region,
            drc_report=Path(fault_drc.drc_report),
            required_widths_mm={net_name: width_mm},
            return_failure_count=0,
            candidate_id="fault-retained",
            engine_id="saved-board-readback",
            retained_directory=str(fault_dir.relative_to(ROOT)),
        )
        restored_metrics = evaluate_saved_routing_candidate(
            source_board=fault_board,
            candidate_board=restored_board,
            domain=domain,
            region=domain.initial_region,
            drc_report=Path(restored_drc.drc_report),
            required_widths_mm={net_name: width_mm},
            return_failure_count=0,
            candidate_id="exact-segment-restoration",
            engine_id="saved-board-declared-delta",
            retained_directory=str(restored_dir.relative_to(ROOT)),
        )

        run = run_local_routing_repair(
            domain,
            producer=lambda region, fault=fault_metrics, restored=restored_metrics: (
                _metrics_for_region(
                    fault if region.expansion_index == 0 else restored,
                    region,
                    str(region.expansion_index),
                ),
            ),
            expansion_margin_mm=15.0,
        )
        clean_original = SOURCE / case / board_name
        clean_snapshot = extract_saved_routing_snapshot(clean_original)
        fault_snapshot = extract_saved_routing_snapshot(fault_board)
        restored_snapshot = extract_saved_routing_snapshot(restored_board)
        summaries.append(
            {
                "case": case,
                "net": net_name,
                "mutable_object_id": mutable_id,
                "clean_original_sha256": _sha256(clean_original),
                "fault_source_sha256": _sha256(fault_board),
                "restored_candidate_sha256": _sha256(restored_board),
                "restored_byte_matches_clean_original": (
                    _sha256(restored_board) == _sha256(clean_original)
                ),
                "restored_route_objects_match_clean_original": (
                    restored_snapshot.objects == clean_snapshot.objects
                ),
                "restored_non_routing_matches_fault_source": (
                    restored_snapshot.non_routing_sha256 == fault_snapshot.non_routing_sha256
                ),
                "fault_drc_status": fault_drc.status,
                "fault_open_count": fault_metrics.open_count,
                "restored_drc_status": restored_drc.status,
                "restored_metrics": restored_metrics.model_dump(mode="json"),
                "local_run": run.model_dump(mode="json"),
                "selected_after_expansion": run.selected_candidate_id,
                "accepted": (
                    run.accepted
                    and restored_metrics.hard_clean
                    and restored_snapshot.objects == clean_snapshot.objects
                    and restored_snapshot.non_routing_sha256 == fault_snapshot.non_routing_sha256
                ),
            }
        )
    payload = {
        "schema_id": "pcbsmith-phase17-if4-w10-saved-board-proof",
        "schema_version": 1,
        "cases": summaries,
        "all_cases_accepted": all(item["accepted"] for item in summaries),
        "boundary": (
            "The candidate producer restores a known removed segment. This proves bounded "
            "saved-board mutation, protected readback, region expansion, and exact gates; it "
            "does not claim general novel-route synthesis."
        ),
    }
    (OUTPUT / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if payload["all_cases_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
