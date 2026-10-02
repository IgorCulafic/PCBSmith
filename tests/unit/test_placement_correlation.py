from __future__ import annotations

import pytest

from pcbsmith.placement_correlation import (
    PlacementCongestionObservation,
    rank_aggregate_congestion,
    spearman_rank_correlation,
)


def _observation(case_id: str, value: int, *, tier: int = 1) -> PlacementCongestionObservation:
    return PlacementCongestionObservation(
        case_id=case_id,
        tier_ordinal=tier,
        estimated_crossing_count=value,
        estimated_unrouted_corridor_count=value,
        maximum_pads_per_5mm_cell=value,
        manhattan_length_density_mm_per_mm2=float(value),
        routed_repair_work_items=value,
    )


def test_rank_aggregate_uses_placement_columns_without_outcome_weight_fitting() -> None:
    observations = (_observation("a", 1), _observation("b", 3), _observation("c", 2))
    assert rank_aggregate_congestion(observations) == (1.0, 3.0, 2.0)


def test_spearman_handles_ties_and_constant_tier_as_uninformative() -> None:
    assert spearman_rank_correlation((1.0, 2.0, 3.0), (10.0, 20.0, 30.0)) == pytest.approx(1.0)
    assert spearman_rank_correlation((1.0, 1.0, 1.0), (10.0, 20.0, 30.0)) is None


def test_correlation_rejects_mismatched_or_empty_vectors() -> None:
    with pytest.raises(ValueError):
        spearman_rank_correlation((), ())
    with pytest.raises(ValueError):
        spearman_rank_correlation((1.0,), (1.0, 2.0))
