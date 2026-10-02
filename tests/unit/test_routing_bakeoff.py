from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.routing_candidate_transaction import (
    RoutingCandidateTransactionStatus,
)
from pcbsmith.routing_bakeoff import (
    RoutingBakeoffCase,
    RoutingBakeoffObservation,
    RoutingBakeoffReport,
)
from pcbsmith.routing_ir import (
    PartialCandidateStatus,
    RouteTerminationState,
)


def _case(case_id: str, board_sha256: str) -> RoutingBakeoffCase:
    return RoutingBakeoffCase(
        case_id=case_id,
        board_variant=case_id,
        board_sha256=board_sha256,
        request_fingerprint=(case_id[-1] * 64),
        input_snapshot_fingerprint=((case_id[-1].upper().casefold()) * 64),
    )


def _observation(
    *,
    case_id: str,
    engine_id: str,
    repeat_index: int,
    geometry: str,
    completed: bool = True,
) -> RoutingBakeoffObservation:
    return RoutingBakeoffObservation.build(
        case_id=case_id,
        engine_id=engine_id,
        engine_version="fixture-1",
        repeat_index=repeat_index,
        transaction_status=(
            RoutingCandidateTransactionStatus.ACCEPTED
            if completed
            else RoutingCandidateTransactionStatus.REJECTED
        ),
        partial_status=(
            PartialCandidateStatus.COMPLETE
            if completed
            else PartialCandidateStatus.FAILED_NO_DELTA
        ),
        termination_state=(
            RouteTerminationState.COMPLETED
            if completed
            else RouteTerminationState.FAILED
        ),
        geometry_fingerprint=geometry,
        unresolved_net_names=() if completed else ("/SIG",),
        kicad_violation_count=0 if completed else None,
        kicad_unconnected_count=0 if completed else None,
        kicad_parity_count=0 if completed else None,
        semantic_readback_accepted=True if completed else None,
        protected_object_change_count=0,
        added_trace_count=2,
        added_via_count=0,
        removed_trace_count=0,
        removed_via_count=0,
        added_routed_length_mm=20.0,
        detour_ratio=1.1,
        runtime_seconds=1.0,
        unsupported_constraint_ids=(),
        manual_repair_actions=0,
        visual_review_finding_ids=(),
        blocker_kinds=(),
    )


def _observations(
    cases: tuple[RoutingBakeoffCase, ...],
    engines: tuple[str, ...],
) -> tuple[RoutingBakeoffObservation, ...]:
    return tuple(
        _observation(
            case_id=case.case_id,
            engine_id=engine,
            repeat_index=repeat,
            geometry=("a" if engine == engines[0] else "b") * 64,
        )
        for case in cases
        for engine in engines
        for repeat in range(2)
    )


def test_one_board_matrix_can_prove_eligibility_but_not_a_winner() -> None:
    cases = (_case("case-a", "1" * 64),)
    engines = ("engine-a", "engine-b")
    observations = _observations(cases, engines)

    report = RoutingBakeoffReport.build(
        cases=cases,
        expected_engine_ids=engines,
        required_repeats=2,
        observations=observations,
    )

    assert report.matrix_complete
    assert all(item.eligible for item in report.eligibility)
    assert report.recommended_engine_id is None
    assert "one board cannot support a comparative winner" in report.blockers

    with pytest.raises(ValidationError, match="one board"):
        RoutingBakeoffReport.build(
            cases=cases,
            expected_engine_ids=engines,
            required_repeats=2,
            observations=observations,
            recommended_engine_id="engine-a",
        )


def test_two_distinct_board_variants_can_carry_an_explicit_eligible_recommendation() -> None:
    cases = (
        _case("case-a", "1" * 64),
        _case("case-b", "2" * 64),
    )
    engines = ("engine-a", "engine-b")

    report = RoutingBakeoffReport.build(
        cases=cases,
        expected_engine_ids=engines,
        required_repeats=2,
        observations=_observations(cases, engines),
        recommended_engine_id="engine-a",
    )

    assert report.matrix_complete
    assert report.recommended_engine_id == "engine-a"
    assert "one board cannot support a comparative winner" not in report.blockers


def test_nondeterministic_geometry_blocks_h1_eligibility() -> None:
    cases = (_case("case-a", "1" * 64),)
    engines = ("engine-a",)
    observations = (
        _observation(
            case_id="case-a",
            engine_id="engine-a",
            repeat_index=0,
            geometry="a" * 64,
        ),
        _observation(
            case_id="case-a",
            engine_id="engine-a",
            repeat_index=1,
            geometry="b" * 64,
        ),
    )

    report = RoutingBakeoffReport.build(
        cases=cases,
        expected_engine_ids=engines,
        required_repeats=2,
        observations=observations,
    )

    assert report.matrix_complete
    assert not report.eligibility[0].eligible
    assert "candidate deltas are not repeatable" in report.eligibility[0].blockers[0]
    assert "no engine currently satisfies H1 eligibility" in report.blockers


def test_missing_matrix_rows_are_retained_as_incomplete_not_silently_ignored() -> None:
    cases = (_case("case-a", "1" * 64),)
    engines = ("engine-a", "engine-missing")
    observations = tuple(
        _observation(
            case_id="case-a",
            engine_id="engine-a",
            repeat_index=repeat,
            geometry="a" * 64,
        )
        for repeat in range(2)
    )

    report = RoutingBakeoffReport.build(
        cases=cases,
        expected_engine_ids=engines,
        required_repeats=2,
        observations=observations,
    )

    assert not report.matrix_complete
    missing = next(
        item for item in report.eligibility if item.engine_id == "engine-missing"
    )
    assert not missing.eligible
    assert "engine has no retained observations" in missing.blockers
