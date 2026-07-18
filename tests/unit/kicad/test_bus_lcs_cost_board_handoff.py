"""Fail-closed tests for the accepted cost-aware board-layout handoff."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_lcs_cost_replay_checked_commit as cost_fixtures
from tests.unit.kicad import test_bus_replay_checked_commit as checked_fixtures

from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
)
from pcbsmith.kicad.bus_lcs_cost_board_handoff import (
    BusLcsCostAcceptedBoardLayoutHandoff,
    consume_accepted_bus_lcs_cost_board_layout,
)
from pcbsmith.kicad.bus_lcs_cost_replay_checked_commit import (
    BusLcsCostReplayCheckedCommitResult,
    commit_bus_lcs_cost_replay_exact,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint


def _checked_result(accepted: bool | None) -> BusLcsCostReplayCheckedCommitResult:
    authority = cost_fixtures._authority()
    coordinator = checked_fixtures._coordinator(authority.route_authority)
    return commit_bus_lcs_cost_replay_exact(
        coordinator,
        authority,
        exact_checker=None if accepted is None else checked_fixtures._checker(accepted),
    )


def test_accepted_handoff_roundtrips_deterministically_and_retains_exact_layout() -> None:
    checked_authority = _checked_result(True)
    nested_layout = checked_authority.checked_result.checked_result.materialized_layout
    assert nested_layout is not None

    first = consume_accepted_bus_lcs_cost_board_layout(checked_authority)
    second = consume_accepted_bus_lcs_cost_board_layout(checked_authority)

    assert first == second
    assert first.semantic_json() == second.semantic_json()
    assert first.semantic_fingerprint() == second.semantic_fingerprint()
    assert first.checked_authority == checked_authority
    assert first.authority_scope == "accepted-cost-aware-neutral-board-layout-only"
    assert first.excluded_claims == (
        "saved_kicad_artifact",
        "rendered_kicad_board",
        "filesystem_write",
        "manufacturability",
        "verification_beyond_retained_exact_checker",
        "alternate_candidate_selection",
    )
    assert first.layout == nested_layout
    assert first.layout is not nested_layout
    assert first.board_layout_snapshot_json == canonical_board_layout_snapshot_json(nested_layout)
    assert first.board_layout_snapshot_fingerprint == board_layout_snapshot_fingerprint(
        first.board_layout_snapshot_json
    )
    assert first.board_layout_fingerprint == board_layout_fingerprint(nested_layout)
    assert (
        BusLcsCostAcceptedBoardLayoutHandoff.model_validate_json(first.model_dump_json()) == first
    )


@pytest.mark.parametrize("accepted", [False, None])
def test_rejected_and_missing_checker_results_cannot_yield_a_layout(
    accepted: bool | None,
) -> None:
    with pytest.raises(ValueError, match="accepted committed transaction"):
        consume_accepted_bus_lcs_cost_board_layout(_checked_result(accepted))


def test_uncommitted_accepted_result_fails_closed_during_exact_revalidation() -> None:
    result = _checked_result(True)
    replay_checked = result.checked_result
    forged_ordinary = replay_checked.checked_result.model_copy(update={"committed": False})
    forged_replay_checked = replay_checked.model_copy(update={"checked_result": forged_ordinary})
    forged = result.model_copy(update={"checked_result": forged_replay_checked})

    with pytest.raises(ValidationError, match="committed"):
        consume_accepted_bus_lcs_cost_board_layout(forged)


def test_nested_materialized_layout_tamper_fails_closed() -> None:
    result = _checked_result(True)
    replay_checked = result.checked_result
    ordinary = replay_checked.checked_result
    assert ordinary.materialized_layout is not None
    changed_layout = replace(
        ordinary.materialized_layout,
        width_mm=ordinary.materialized_layout.width_mm + 1.0,
    )
    forged_ordinary = ordinary.model_copy(update={"materialized_layout": changed_layout})
    forged_replay_checked = replay_checked.model_copy(update={"checked_result": forged_ordinary})
    forged = result.model_copy(update={"checked_result": forged_replay_checked})

    with pytest.raises(ValidationError, match="exact evidence"):
        consume_accepted_bus_lcs_cost_board_layout(forged)


def test_nested_layout_fingerprint_tamper_fails_closed() -> None:
    result = _checked_result(True)
    replay_checked = result.checked_result
    ordinary = replay_checked.checked_result
    assert ordinary.exact_check_evidence is not None
    changed_evidence = copy.copy(ordinary.exact_check_evidence)
    object.__setattr__(changed_evidence, "materialized_layout_fingerprint", "0" * 64)
    forged_ordinary = ordinary.model_copy(update={"exact_check_evidence": changed_evidence})
    forged_replay_checked = replay_checked.model_copy(update={"checked_result": forged_ordinary})
    forged = result.model_copy(update={"checked_result": forged_replay_checked})

    with pytest.raises(ValidationError, match="exact evidence"):
        consume_accepted_bus_lcs_cost_board_layout(forged)


@pytest.mark.parametrize(
    ("field_name", "changed"),
    [
        ("board_layout_snapshot_fingerprint", "0" * 64),
        ("board_layout_fingerprint", "f" * 64),
    ],
)
def test_handoff_fingerprint_tamper_is_rejected(
    field_name: str,
    changed: str,
) -> None:
    handoff = consume_accepted_bus_lcs_cost_board_layout(_checked_result(True))
    payload = handoff.model_dump(mode="json")
    payload[field_name] = changed

    with pytest.raises(ValidationError, match="fingerprint is stale"):
        BusLcsCostAcceptedBoardLayoutHandoff.model_validate(payload)


def test_handoff_and_exposed_layout_are_immutable() -> None:
    handoff = consume_accepted_bus_lcs_cost_board_layout(_checked_result(True))

    with pytest.raises(ValidationError, match="frozen"):
        handoff.board_layout_fingerprint = "0" * 64
    with pytest.raises(FrozenInstanceError):
        handoff.layout.width_mm = handoff.layout.width_mm + 1.0
