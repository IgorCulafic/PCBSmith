from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pcbsmith.bus_lcs import (
    BusLcsBoundaryMember,
    BusLcsSelectionInput,
    BusLcsSelectionResult,
    BusLcsSelectionState,
    select_bus_lcs,
)


def _boundary(*entries: str | tuple[str, bool]) -> tuple[BusLcsBoundaryMember, ...]:
    return tuple(
        BusLcsBoundaryMember(
            member_id=entry if isinstance(entry, str) else entry[0],
            active=True if isinstance(entry, str) else entry[1],
        )
        for entry in entries
    )


def _selection_input(
    source: tuple[BusLcsBoundaryMember, ...],
    target: tuple[BusLcsBoundaryMember, ...],
    *,
    max_dp_cells: int | None = None,
) -> BusLcsSelectionInput:
    active_source = sum(member.active for member in source)
    active_target = sum(member.active for member in target)
    return BusLcsSelectionInput(
        source_boundary=source,
        target_boundary=target,
        max_dp_cells=(active_source * active_target if max_dp_cells is None else max_dp_cells),
    )


def _triples(result: BusLcsSelectionResult) -> tuple[tuple[int, int, str], ...]:
    return tuple(
        (member.source_index, member.target_index, member.member_id)
        for member in result.stay_layer_members
    )


def test_identical_four_members_select_all_with_exact_indices() -> None:
    boundary = _boundary("d0", "d1", "d2", "d3")

    result = select_bus_lcs(_selection_input(boundary, boundary))

    assert result.state is BusLcsSelectionState.SELECTED
    assert _triples(result) == (
        (0, 0, "d0"),
        (1, 1, "d1"),
        (2, 2, "d2"),
        (3, 3, "d3"),
    )
    assert result.dp_cells_evaluated == 16


def test_one_displaced_member_selects_deterministic_three() -> None:
    result = select_bus_lcs(
        _selection_input(
            _boundary("a", "b", "c", "d"),
            _boundary("a", "c", "d", "b"),
        )
    )

    assert _triples(result) == ((0, 0, "a"), (2, 1, "c"), (3, 2, "d"))
    # This sequence telemetry deliberately contains no physical outlier plan.
    assert "outlier" not in BusLcsSelectionResult.model_fields
    assert "via" not in BusLcsSelectionResult.model_fields
    assert "layer" not in BusLcsSelectionResult.model_fields


def test_equal_length_choice_uses_lexicographically_smallest_entire_index_tuple() -> None:
    # LCS candidates (0,1,"a") and (1,0,"b") have equal cardinality.
    result = select_bus_lcs(_selection_input(_boundary("a", "b"), _boundary("b", "a")))

    assert _triples(result) == ((0, 1, "a"),)


def test_lexical_member_ids_do_not_replace_physical_sequence_order() -> None:
    source = _boundary("lane_z", "lane_a", "lane_m")
    result = select_bus_lcs(_selection_input(source, source))

    assert _triples(result) == (
        (0, 0, "lane_z"),
        (1, 1, "lane_a"),
        (2, 2, "lane_m"),
    )


@pytest.mark.parametrize(
    ("source", "target", "state"),
    [
        (
            _boundary("a", "b"),
            _boundary("a", "c"),
            BusLcsSelectionState.MEMBER_SET_MISMATCH,
        ),
        (
            _boundary("a", ("b", True)),
            _boundary("a", ("b", False)),
            BusLcsSelectionState.ACTIVITY_MISMATCH,
        ),
    ],
)
def test_member_and_activity_mismatch_do_no_dp_work(
    source: tuple[BusLcsBoundaryMember, ...],
    target: tuple[BusLcsBoundaryMember, ...],
    state: BusLcsSelectionState,
) -> None:
    result = select_bus_lcs(_selection_input(source, target, max_dp_cells=100))

    assert result.state is state
    assert result.dp_cells_evaluated == 0
    assert result.stay_layer_members == ()


def test_inactive_members_are_not_selected_but_indices_remain_full_boundary_indices() -> None:
    source = _boundary(("tap", False), "a", "b")
    target = _boundary("b", ("tap", False), "a")

    result = select_bus_lcs(_selection_input(source, target))

    assert result.state is BusLcsSelectionState.SELECTED
    assert _triples(result) == ((1, 2, "a"),)
    assert result.dp_cells_evaluated == 4


def test_zero_budget_checks_before_first_cell() -> None:
    result = select_bus_lcs(_selection_input(_boundary("a"), _boundary("a"), max_dp_cells=0))

    assert result.state is BusLcsSelectionState.DP_BUDGET
    assert result.dp_cells_evaluated == 0
    assert result.stay_layer_members == ()


def test_exact_budget_completes_and_one_less_stops_exactly() -> None:
    source = _boundary("a", "b", "c")
    target = _boundary("b", "a", "c")

    exact = select_bus_lcs(_selection_input(source, target, max_dp_cells=9))
    one_less = select_bus_lcs(_selection_input(source, target, max_dp_cells=8))

    assert exact.state is BusLcsSelectionState.SELECTED
    assert exact.dp_cells_evaluated == 9
    assert one_less.state is BusLcsSelectionState.DP_BUDGET
    assert one_less.dp_cells_evaluated == 8
    assert one_less.stay_layer_members == ()


@pytest.mark.parametrize("member_id", ["", " ", "\t"])
def test_blank_member_ids_are_rejected(member_id: str) -> None:
    with pytest.raises(ValidationError):
        BusLcsBoundaryMember(member_id=member_id, active=True)


@pytest.mark.parametrize("boundary_name", ["source_boundary", "target_boundary"])
def test_duplicate_member_ids_are_rejected(boundary_name: str) -> None:
    payload = {
        "source_boundary": _boundary("a", "b"),
        "target_boundary": _boundary("a", "b"),
        "max_dp_cells": 4,
    }
    payload[boundary_name] = _boundary("a", "a")

    with pytest.raises(ValidationError, match="member_id values must be unique"):
        BusLcsSelectionInput(**payload)


def test_reversing_order_changes_input_fingerprint_and_selected_indices() -> None:
    source = _boundary("z", "a", "m")
    forward = select_bus_lcs(_selection_input(source, source))
    reversed_source = tuple(reversed(source))
    reverse = select_bus_lcs(_selection_input(reversed_source, source))

    assert forward.input_fingerprint != reverse.input_fingerprint
    assert _triples(forward) != _triples(reverse)


def test_result_round_trip_replays_complete_input_and_is_repeatable() -> None:
    selection_input = _selection_input(
        _boundary("a", "b", "c"),
        _boundary("b", "a", "c"),
    )

    first = select_bus_lcs(selection_input)
    second = select_bus_lcs(selection_input)
    restored = BusLcsSelectionResult.model_validate_json(first.model_dump_json())

    assert restored == first == second
    assert restored.semantic_fingerprint() == first.semantic_fingerprint()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("input_fingerprint", "0" * 64),
        ("state", BusLcsSelectionState.DP_BUDGET),
        ("stay_layer_members", []),
        ("dp_cells_evaluated", 0),
    ],
)
def test_result_tamper_is_rejected(field: str, replacement: object) -> None:
    result = select_bus_lcs(_selection_input(_boundary("a", "b"), _boundary("a", "b")))
    payload = json.loads(result.model_dump_json())
    payload[field] = replacement

    with pytest.raises(ValidationError):
        BusLcsSelectionResult.model_validate(payload)


def test_embedded_ordered_input_tamper_is_rejected_by_replay_binding() -> None:
    result = select_bus_lcs(_selection_input(_boundary("a", "b"), _boundary("a", "b")))
    payload = json.loads(result.model_dump_json())
    payload["selection_input"]["target_boundary"] = list(
        reversed(payload["selection_input"]["target_boundary"])
    )

    with pytest.raises(ValidationError):
        BusLcsSelectionResult.model_validate(payload)
