"""Freeze a real 40-board W4 placement-versus-routing correlation report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pcbsmith.placement_correlation import (
    PlacementCongestionObservation,
    rank_aggregate_congestion,
    spearman_rank_correlation,
)

TIER_ORDINAL = {
    "introductory": 1,
    "moderate": 2,
    "mixed-power": 3,
    "dense": 4,
    "stress": 5,
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def build_report(corpus: Path) -> dict[str, Any]:
    matrix_path = corpus / "case-matrix.json"
    evidence_root = corpus / "failure-placement-gate-v1"
    placement_path = evidence_root / "summary-placement.json"
    routed_path = evidence_root / "summary-routed.json"
    matrix = {item["case_id"]: item for item in _load(matrix_path)}
    placement = {item["case_id"]: item for item in _load(placement_path)["cases"]}
    routed = {item["case_id"]: item for item in _load(routed_path)["cases"]}
    if set(matrix) != set(placement) or set(matrix) != set(routed):
        raise ValueError("corpus matrix, placement evidence and routed evidence disagree")

    observations: list[PlacementCongestionObservation] = []
    sources: list[dict[str, str]] = []
    for case_id in sorted(matrix):
        case = matrix[case_id]
        placement_case = placement[case_id]
        routed_case = routed[case_id]
        observation_path = (
            evidence_root / placement_case["run_revision"] / "physical-observation.json"
        )
        physical = _load(observation_path)
        metrics = physical["placement_metrics"]
        board = case["board"]
        area = float(board["width_mm"]) * float(board["height_mm"])
        difficulty = case["difficulty"]
        observations.append(
            PlacementCongestionObservation(
                case_id=case_id,
                tier_ordinal=TIER_ORDINAL[difficulty],
                estimated_crossing_count=int(metrics["estimated_crossing_count"]),
                estimated_unrouted_corridor_count=int(metrics["estimated_unrouted_corridor_count"]),
                maximum_pads_per_5mm_cell=int(metrics["maximum_pads_per_5mm_cell"]),
                manhattan_length_density_mm_per_mm2=(
                    float(metrics["total_manhattan_corridor_length_mm"]) / area
                ),
                routed_repair_work_items=int(routed_case["manual_repair_work_item_count"]),
            )
        )
        sources.append(
            {
                "case_id": case_id,
                "physical_observation": observation_path.relative_to(corpus).as_posix(),
                "physical_observation_sha256": _sha256(observation_path),
            }
        )

    values = tuple(observations)
    aggregate = rank_aggregate_congestion(values)
    tier = tuple(float(item.tier_ordinal) for item in values)
    outcome = tuple(float(item.routed_repair_work_items) for item in values)
    aggregate_corr = spearman_rank_correlation(aggregate, outcome)
    tier_corr = spearman_rank_correlation(tier, outcome)

    moderate_indices = tuple(
        index
        for index, item in enumerate(values)
        if matrix[item.case_id]["difficulty"] == "moderate"
    )
    moderate_aggregate = tuple(aggregate[index] for index in moderate_indices)
    moderate_outcome = tuple(outcome[index] for index in moderate_indices)
    moderate_tier = tuple(tier[index] for index in moderate_indices)
    moderate_corr = spearman_rank_correlation(moderate_aggregate, moderate_outcome)
    moderate_tier_corr = spearman_rank_correlation(moderate_tier, moderate_outcome)

    stronger = (
        aggregate_corr is not None
        and tier_corr is not None
        and abs(aggregate_corr) > abs(tier_corr)
        and moderate_corr is not None
        and moderate_corr > 0
        and moderate_tier_corr is None
    )
    rows = []
    for item, score in zip(values, aggregate, strict=True):
        rows.append(
            {
                **item.__dict__,
                "difficulty": matrix[item.case_id]["difficulty"],
                "placement_congestion_rank_aggregate": round(score, 6),
            }
        )
    return {
        "schema": "pcbsmith-w4-placement-correlation-v1",
        "acceptance_boundary": (
            "Retrospective evidence for estimator discrimination only. This is not routing, "
            "manufacturability, electrical, or release proof and does not authorize a scalar "
            "placement objective. Production candidate selection remains Pareto-gated."
        ),
        "predictor_freeze": {
            "inputs": [
                "estimated_crossing_count",
                "estimated_unrouted_corridor_count",
                "maximum_pads_per_5mm_cell",
                "total_manhattan_corridor_length_mm / board_area_mm2",
            ],
            "aggregation": "arithmetic mean of within-cohort average ranks; no fitted weights",
            "outcome_not_used_to_fit_predictor": True,
        },
        "outcome": "routed manual_repair_work_item_count from the retained transactional run",
        "source_hashes": {
            "case_matrix_sha256": _sha256(matrix_path),
            "placement_summary_sha256": _sha256(placement_path),
            "routed_summary_sha256": _sha256(routed_path),
        },
        "case_source_bindings": sources,
        "results": {
            "case_count": len(values),
            "placement_estimator_spearman": _rounded(aggregate_corr),
            "simple_tier_spearman": _rounded(tier_corr),
            "moderate_case_count": len(moderate_indices),
            "moderate_placement_estimator_spearman": _rounded(moderate_corr),
            "moderate_simple_tier_spearman": _rounded(moderate_tier_corr),
            "estimator_stronger_than_simple_tier": stronger,
        },
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.corpus.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["results"], indent=2, sort_keys=True))
    return 0 if report["results"]["estimator_stronger_than_simple_tier"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
