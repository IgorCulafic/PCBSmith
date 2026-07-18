from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pcbsmith.bus_lcs import BusLcsSelectionState
from pcbsmith.bus_lcs_outliers import (
    BusLcsOutlierPlanInput,
    BusLcsOutlierPlanResult,
    plan_bus_lcs_outliers,
)


def _plan_input(
    source: tuple[str, ...],
    target: tuple[str, ...],
    *,
    max_dp_cells: int | None = None,
) -> BusLcsOutlierPlanInput:
    return BusLcsOutlierPlanInput(
        source_member_order=source,
        target_member_order=target,
        max_dp_cells=(len(source) * len(target) if max_dp_cells is None else max_dp_cells),
    )


def _stationary(
    result: BusLcsOutlierPlanResult,
) -> tuple[tuple[int, int, str], ...]:
    return tuple(
        (member.source_index, member.target_index, member.member_id)
        for member in result.stationary_members
    )


def _outliers(
    result: BusLcsOutlierPlanResult,
) -> tuple[tuple[int, int, str], ...]:
    return tuple(
        (member.source_index, member.target_index, member.member_id)
        for member in result.outlier_members
    )


def test_empty_orders_complete_without_work_or_outliers() -> None:
    result = plan_bus_lcs_outliers(_plan_input((), ()))

    assert result.lcs_result.state is BusLcsSelectionState.SELECTED
    assert result.lcs_result.dp_cells_evaluated == 0
    assert result.stationary_members == ()
    assert result.outlier_members == ()


def test_equal_orders_make_every_member_stationary() -> None:
    result = plan_bus_lcs_outliers(_plan_input(("z", "a", "m"), ("z", "a", "m")))

    assert _stationary(result) == ((0, 0, "z"), (1, 1, "a"), (2, 2, "m"))
    assert result.outlier_members == ()
    assert result.lcs_result.dp_cells_evaluated == 9


def test_reversal_keeps_tie_broken_stationary_member_and_target_orders_outliers() -> None:
    result = plan_bus_lcs_outliers(_plan_input(("a", "b", "c"), ("c", "b", "a")))

    assert _stationary(result) == ((0, 2, "a"),)
    assert _outliers(result) == ((2, 0, "c"), (1, 1, "b"))


def test_equal_length_lcs_tie_uses_exact_core_result() -> None:
    result = plan_bus_lcs_outliers(_plan_input(("a", "b"), ("b", "a")))

    assert _stationary(result) == ((0, 1, "a"),)
    assert _outliers(result) == ((1, 0, "b"),)
    assert result.stationary_members == result.lcs_result.stay_layer_members


def test_exact_budget_completes_and_one_less_stops_without_partial_classification() -> None:
    exact = plan_bus_lcs_outliers(
        _plan_input(("a", "b"), ("b", "a"), max_dp_cells=4)
    )
    one_less = plan_bus_lcs_outliers(
        _plan_input(("a", "b"), ("b", "a"), max_dp_cells=3)
    )

    assert exact.lcs_result.state is BusLcsSelectionState.SELECTED
    assert exact.lcs_result.dp_cells_evaluated == 4
    assert one_less.lcs_result.state is BusLcsSelectionState.DP_BUDGET
    assert one_less.lcs_result.dp_cells_evaluated == 3
    assert one_less.stationary_members == ()
    assert one_less.outlier_members == ()


def test_zero_budget_stops_before_first_cell() -> None:
    result = plan_bus_lcs_outliers(
        _plan_input(("a",), ("a",), max_dp_cells=0)
    )

    assert result.lcs_result.state is BusLcsSelectionState.DP_BUDGET
    assert result.lcs_result.dp_cells_evaluated == 0


def test_member_set_mismatch_is_retained_without_inventing_outliers() -> None:
    result = plan_bus_lcs_outliers(_plan_input(("a", "b"), ("a", "c")))

    assert result.lcs_result.state is BusLcsSelectionState.MEMBER_SET_MISMATCH
    assert result.stationary_members == ()
    assert result.outlier_members == ()
    assert result.lcs_result.dp_cells_evaluated == 0


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (("a", "a"), ("a",)),
        (("a",), ("a", "a")),
        (("",), ("",)),
        ((" ",), (" ",)),
    ],
)
def test_orders_require_unique_nonblank_member_ids(
    source: tuple[str, ...],
    target: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        _plan_input(source, target)


def test_json_round_trip_and_reversed_input_have_distinct_authority() -> None:
    forward_input = _plan_input(("a", "b", "c"), ("a", "c", "b"))
    reverse_input = _plan_input(tuple(reversed(forward_input.source_member_order)), ("a", "c", "b"))
    forward = plan_bus_lcs_outliers(forward_input)
    reverse = plan_bus_lcs_outliers(reverse_input)
    restored = BusLcsOutlierPlanResult.model_validate_json(forward.model_dump_json())

    assert restored == forward
    assert restored.semantic_fingerprint() == forward.semantic_fingerprint()
    assert reverse.input_fingerprint != forward.input_fingerprint
    assert reverse.stationary_members != forward.stationary_members


@pytest.mark.parametrize(
    "mutation",
    ["input_fingerprint", "nested_lcs", "stationary", "outlier"],
)
def test_nested_result_tamper_is_rejected(mutation: str) -> None:
    result = plan_bus_lcs_outliers(_plan_input(("a", "b"), ("b", "a")))
    payload = json.loads(result.model_dump_json())
    if mutation == "input_fingerprint":
        payload["input_fingerprint"] = "0" * 64
    elif mutation == "nested_lcs":
        payload["lcs_result"]["dp_cells_evaluated"] = 0
    elif mutation == "stationary":
        payload["stationary_members"] = []
    else:
        payload["outlier_members"][0]["target_index"] = 1

    with pytest.raises(ValidationError):
        BusLcsOutlierPlanResult.model_validate(payload)


def test_nested_order_tamper_is_rejected_by_complete_replay_binding() -> None:
    result = plan_bus_lcs_outliers(_plan_input(("a", "b"), ("b", "a")))
    payload = json.loads(result.model_dump_json())
    payload["plan_input"]["target_member_order"] = ["a", "b"]

    with pytest.raises(ValidationError):
        BusLcsOutlierPlanResult.model_validate(payload)


def test_caller_owned_lists_are_detached_and_later_mutation_cannot_change_result() -> None:
    source = ["a", "b", "c"]
    target = ["a", "c", "b"]
    plan_input = BusLcsOutlierPlanInput.model_validate(
        {
            "source_member_order": source,
            "target_member_order": target,
            "max_dp_cells": 9,
        }
    )
    result = plan_bus_lcs_outliers(plan_input)
    before = result.model_dump_json()

    source.reverse()
    target.clear()

    assert result.model_dump_json() == before
    assert result.plan_input.source_member_order == ("a", "b", "c")
    assert result.plan_input.target_member_order == ("a", "c", "b")


def test_result_exposes_sequence_telemetry_only() -> None:
    fields = set(BusLcsOutlierPlanResult.model_fields)

    assert "layer" not in fields
    assert "via" not in fields
    assert "route" not in fields
    assert "transition" not in fields
    assert "capacity" not in fields
    assert BusLcsOutlierPlanResult.model_fields["authority_scope"].default == (
        "sequence-telemetry-only"
    )
