"""Leakage-resistant correlation helpers for placement congestion evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class PlacementCongestionObservation:
    case_id: str
    tier_ordinal: int
    estimated_crossing_count: int
    estimated_unrouted_corridor_count: int
    maximum_pads_per_5mm_cell: int
    manhattan_length_density_mm_per_mm2: float
    routed_repair_work_items: int


def _average_ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    """Return ascending 1-based ranks with average ranks for ties."""

    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average = ((index + 1) + end) / 2.0
        for original_index, _value in ordered[index:end]:
            ranks[original_index] = average
        index = end
    return tuple(ranks)


def rank_aggregate_congestion(
    observations: tuple[PlacementCongestionObservation, ...],
) -> tuple[float, ...]:
    """Aggregate placement-only indicators without fitted outcome weights.

    This scalar is for retrospective correlation only. Placement selection keeps
    the underlying objectives separate and uses Pareto dominance.
    """

    if not observations:
        raise ValueError("placement correlation requires observations")
    columns = (
        tuple(float(item.estimated_crossing_count) for item in observations),
        tuple(float(item.estimated_unrouted_corridor_count) for item in observations),
        tuple(float(item.maximum_pads_per_5mm_cell) for item in observations),
        tuple(item.manhattan_length_density_mm_per_mm2 for item in observations),
    )
    ranked_columns = tuple(_average_ranks(column) for column in columns)
    return tuple(
        sum(column[index] for column in ranked_columns) / len(ranked_columns)
        for index in range(len(observations))
    )


def spearman_rank_correlation(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    if len(left) != len(right) or not left:
        raise ValueError("correlation vectors must have the same non-zero length")
    left_rank = _average_ranks(left)
    right_rank = _average_ranks(right)
    left_mean = sum(left_rank) / len(left_rank)
    right_mean = sum(right_rank) / len(right_rank)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left_rank, right_rank, strict=True)
    )
    left_ss = sum((value - left_mean) ** 2 for value in left_rank)
    right_ss = sum((value - right_mean) ** 2 for value in right_rank)
    if left_ss == 0 or right_ss == 0:
        return None
    return numerator / sqrt(left_ss * right_ss)


__all__ = [
    "PlacementCongestionObservation",
    "rank_aggregate_congestion",
    "spearman_rank_correlation",
]
