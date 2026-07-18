from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import cast

import pytest
from pydantic import ValidationError

from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    CorridorGuidanceReport,
)
from pcbsmith.kicad.board import BoardLayout, BoardNet, BoardNetlist, TrackSegment
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.kicad.placement_detail import PlacementDetailRun
from pcbsmith.kicad.placement_exact import (
    PlacementExactInput,
    evaluate_placement_exact,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.placement_detail_ir import (
    PlacementCandidateDetailRecord,
    PlacementDetailBudget,
    PlacementDetailRunResult,
    PlacementDetailSelectionPolicy,
    PlacementDetailState,
    PlacementMarginRank,
    PlacementParetoEvidence,
    PlacementR2Policy,
    PlacementSelectionReason,
)
from pcbsmith.placement_exact_ir import (
    PlacementExactBudget,
    PlacementExactDisposition,
    PlacementExactPolicy,
    PlacementExactRunResult,
    PlacementFinalState,
)
from pcbsmith.routing_ir import (
    RoutingBudget,
    RoutingFailureReason,
    RoutingRunResult,
)

CHECKER_ID = "fixture-exact-checker-v1"
FINDING_A = hashlib.sha256(b"finding-a").hexdigest()
FINDING_B = hashlib.sha256(b"finding-b").hexdigest()


def _fp(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _route_geometry_fingerprint(layout: BoardLayout) -> str:
    return _fp(
        {
            "schema_id": "pcbsmith-placement-detail-route-geometry",
            "schema_version": 1,
            "segments": [asdict(item) for item in layout.segments if item.net_name == "A"],
            "vias": [asdict(item) for item in layout.vias if item.net_name == "A"],
        }
    )


def _routing_budget() -> RoutingBudget:
    return RoutingBudget(
        max_passes=4,
        max_expansions=20,
        max_expansions_per_net=10,
        max_stagnant_passes=2,
        max_exact_check_rejections=0,
    )


def _layout(index: int, *, routed: bool) -> BoardLayout:
    fixed = TrackSegment(0.0, 1.0, 1.0, 1.0, "B.Cu", "FIXED", 0.3)
    target = TrackSegment(
        2.0,
        float(index + 2),
        3.0,
        float(index + 2),
        "F.Cu",
        "A",
        0.2,
    )
    return BoardLayout(
        placements=(),
        segments=(fixed, target) if routed else (fixed,),
        vias=(),
        width_mm=10.0,
        height_mm=10.0,
        outline=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
    )


def _detail_record(
    candidate_fingerprint: str,
    layout: BoardLayout,
    *,
    success: bool,
) -> PlacementCandidateDetailRecord:
    routing = RoutingRunResult(
        producer="r5.5-fixture-r2",
        budget=_routing_budget(),
        success=success,
        failure_reason=None if success else RoutingFailureReason.UNROUTABLE,
        route_order=("A",),
        unresolved_net_names=() if success else ("A",),
    )
    guidance = CorridorGuidanceReport(
        disposition=CorridorGuidanceDisposition.ABSENT,
        unguided_net_names=("A",),
        routing_run_fingerprint=routing.semantic_fingerprint(),
    )
    return PlacementCandidateDetailRecord(
        candidate_fingerprint=candidate_fingerprint,
        detail_input_fingerprint=hashlib.sha256(
            f"detail-input:{candidate_fingerprint}".encode()
        ).hexdigest(),
        selected=True,
        state=(
            PlacementDetailState.ROUTED_UNCHECKED
            if success
            else PlacementDetailState.ROUTING_FAILED
        ),
        r3_evaluations_consumed=0,
        r2_evaluations_consumed=1,
        guidance=guidance,
        routing_run=routing,
        materialized_layout_fingerprint=board_layout_fingerprint(layout),
        route_geometry_fingerprint=_route_geometry_fingerprint(layout),
        algorithmic_success=success,
        zero_overuse=True,
        routed_unchecked=success,
    )


def _detail_run(outcomes: tuple[bool, ...]) -> PlacementDetailRun:
    policy = PlacementDetailSelectionPolicy(coarse_failure_exploration_quota=0)
    budget = PlacementDetailBudget(
        max_selected_candidates=len(outcomes),
        max_corridor_evaluations=0,
        max_routing_evaluations=len(outcomes),
    )
    r2_policy = PlacementR2Policy(
        target_nets=("A",),
        max_passes=4,
        max_expansions=20,
        max_expansions_per_net=10,
        max_stagnant_passes=2,
    )
    layouts = tuple(_layout(index, routed=success) for index, success in enumerate(outcomes))
    fingerprints = tuple(
        hashlib.sha256(f"candidate:{index}".encode()).hexdigest() for index in range(len(outcomes))
    )
    records = tuple(
        _detail_record(fingerprint, layout, success=success)
        for fingerprint, layout, success in zip(fingerprints, layouts, outcomes, strict=True)
    )
    pareto = tuple(
        PlacementParetoEvidence(
            candidate_fingerprint=fingerprint,
            primary_vector=(0, 0, 1, 1, 0, 0, 0, 0, 0),
            hpwl_total_um=0,
            minimum_margin_rank=PlacementMarginRank.UNKNOWN,
            minimum_terminal_margin_um=None,
            portal_overflow_bucket=1,
            base_candidate=index == 0,
            coarse_failure=False,
            pareto_front_index=0,
            selected=True,
            selection_reason=(
                PlacementSelectionReason.BASE if index == 0 else PlacementSelectionReason.FRONT_FILL
            ),
        )
        for index, fingerprint in enumerate(fingerprints)
    )
    components = {
        "input_catalog_fingerprint": hashlib.sha256(b"detail-catalog").hexdigest(),
        "selection_policy_fingerprint": policy.semantic_fingerprint(),
        "budget_fingerprint": budget.semantic_fingerprint(),
        "r2_policy_fingerprint": r2_policy.semantic_fingerprint(),
        "profile_fingerprint": hashlib.sha256(b"profile").hexdigest(),
    }
    result = PlacementDetailRunResult(
        **components,
        input_fingerprint=_fp(
            {
                "schema_id": "pcbsmith-placement-detail-input",
                "schema_version": 1,
                **components,
            }
        ),
        selection_policy=policy,
        budget=budget,
        r2_policy=r2_policy,
        pareto_evidence=pareto,
        selected_candidate_fingerprints=fingerprints,
        candidate_records=records,
        corridor_evaluations_consumed=0,
        routing_evaluations_consumed=len(records),
    )
    return PlacementDetailRun(
        result=result,
        routed_layouts=tuple(zip(fingerprints, layouts, strict=True)),
    )


def _netlists(detail_run: PlacementDetailRun) -> dict[str, BoardNetlist]:
    return {
        item.candidate_fingerprint: BoardNetlist(components=(), nets=())
        for item in detail_run.result.candidate_records
        if item.routed_unchecked
    }


class _Checker:
    def __init__(
        self,
        *,
        accepted: bool,
        findings: tuple[str, ...] = (),
        checker_id: str = CHECKER_ID,
        error: Exception | None = None,
    ) -> None:
        self.accepted = accepted
        self.findings = findings
        self.checker_id = checker_id
        self.error = error
        self.calls: list[tuple[BoardLayout, BoardNetlist]] = []

    def __call__(
        self,
        layout: BoardLayout,
        netlist: BoardNetlist,
    ) -> ExactRouteCheckResult:
        self.calls.append((layout, netlist))
        if self.error is not None:
            raise self.error
        return ExactRouteCheckResult(
            accepted=self.accepted,
            checker_id=self.checker_id,
            finding_fingerprints=self.findings,
        )


def _run(
    detail_run: PlacementDetailRun,
    *,
    checker: _Checker | None,
    max_checks: int,
):
    return evaluate_placement_exact(
        detail_run,
        netlists_by_candidate_fingerprint=_netlists(detail_run),
        policy=PlacementExactPolicy(checker_id=CHECKER_ID),
        budget=PlacementExactBudget(max_exact_checks=max_checks),
        checker=checker,
    )


def test_algorithmic_r2_failure_never_invokes_checker() -> None:
    detail = _detail_run((False, True))
    checker = _Checker(accepted=True)
    result = _run(detail, checker=checker, max_checks=2)
    failed = next(
        item
        for item in result.result.candidate_records
        if not item.detail_record.algorithmic_success
    )
    assert len(checker.calls) == 1
    assert failed.disposition is PlacementExactDisposition.NOT_ELIGIBLE
    assert failed.final_state is PlacementFinalState.ROUTING_FAILED
    assert failed.exact_checks_consumed == 0 and failed.exact_report is None


def test_missing_checker_remains_routed_unchecked_and_not_accepted() -> None:
    detail = _detail_run((True,))
    result = _run(detail, checker=None, max_checks=1)
    record = result.result.candidate_records[0]
    assert record.disposition is PlacementExactDisposition.CHECKER_UNAVAILABLE
    assert record.final_state is PlacementFinalState.ROUTED_UNCHECKED
    assert record.detail_record.algorithmic_success
    assert not record.accepted and result.result.accepted_candidate_fingerprints == ()


def test_exact_rejection_retains_r2_and_binds_checker_findings() -> None:
    detail = _detail_run((True,))
    detail_record = detail.result.candidate_records[0]
    checker = _Checker(accepted=False, findings=(FINDING_B, FINDING_A))
    result = _run(detail, checker=checker, max_checks=1)
    record = result.result.candidate_records[0]
    assert record.final_state is PlacementFinalState.EXACT_REJECTED
    assert record.disposition is PlacementExactDisposition.EXACT_REJECTED
    assert not record.accepted
    assert record.detail_record == detail_record
    assert record.detail_record.routing_run == detail_record.routing_run
    assert record.exact_report is not None
    assert record.exact_report.checker_id == CHECKER_ID
    assert record.exact_report.finding_fingerprints == (FINDING_A, FINDING_B)


def test_exact_acceptance_is_the_only_accepted_state() -> None:
    detail = _detail_run((True,))
    accepted = _run(detail, checker=_Checker(accepted=True), max_checks=1)
    record = accepted.result.candidate_records[0]
    assert record.final_state is PlacementFinalState.ACCEPTED
    assert record.disposition is PlacementExactDisposition.EXACT_ACCEPTED
    assert record.accepted
    assert accepted.result.accepted_candidate_fingerprints == (record.candidate_fingerprint,)
    assert (
        accepted.result.semantic_fingerprint()
        == "7008bd61ca40c0f751fd3d0fdb6ab6247479c0dbca902af6d534bfb6d2a24c2e"
    )
    assert (
        record.semantic_fingerprint()
        == "3a6e524c7a7b467097062d89b09fdfe9bb1c3c83a0cb5c398353184f55ff9f6c"
    )
    assert (
        record.exact_input_fingerprint
        == "0129b8c1c2bcfb244e8de3064693fada28a9d3e35d03d24a180c4547ea411380"
    )
    assert record.exact_report is not None
    assert (
        record.exact_report.semantic_fingerprint()
        == "f0edf1c751890cc26205afb21c1cf80401fc52bb6d856023b1a8b1d4ba1600bc"
    )
    assert (
        accepted.result.exact_input_catalog_fingerprint
        == "6ace3aec7ea653b3bd29b99fce842d80a232ec624b8dc525e5f3dee79cfcb2e6"
    )


def test_zero_and_one_less_exact_budgets_are_truthful() -> None:
    detail = _detail_run((True, True))
    zero_checker = _Checker(accepted=True)
    zero = _run(detail, checker=zero_checker, max_checks=0)
    assert zero_checker.calls == []
    assert {item.disposition for item in zero.result.candidate_records} == {
        PlacementExactDisposition.BUDGET_EXHAUSTED
    }
    assert all(
        item.final_state is PlacementFinalState.ROUTED_UNCHECKED
        for item in zero.result.candidate_records
    )

    one_checker = _Checker(accepted=True)
    one = _run(detail, checker=one_checker, max_checks=1)
    assert len(one_checker.calls) == 1
    assert one.result.exact_checks_consumed == 1
    assert tuple(item.disposition for item in one.result.candidate_records) == (
        PlacementExactDisposition.EXACT_ACCEPTED,
        PlacementExactDisposition.BUDGET_EXHAUSTED,
    )


def test_mismatched_layout_checker_id_and_forged_report_are_rejected() -> None:
    detail = _detail_run((True, True))
    first_record = detail.result.candidate_records[0]
    wrong_layout = detail.routed_layouts[1][1]
    assert first_record.routing_run is not None
    assert first_record.route_geometry_fingerprint is not None
    assert first_record.materialized_layout_fingerprint is not None
    with pytest.raises(ValueError, match="materialized layout fingerprint"):
        PlacementExactInput(
            candidate_fingerprint=first_record.candidate_fingerprint,
            detail_record_fingerprint=first_record.semantic_fingerprint(),
            routing_run_fingerprint=first_record.routing_run.semantic_fingerprint(),
            route_geometry_fingerprint=first_record.route_geometry_fingerprint,
            materialized_layout_fingerprint=first_record.materialized_layout_fingerprint,
            netlist_fingerprint=hashlib.sha256(b"netlist").hexdigest(),
            layout=wrong_layout,
            netlist=BoardNetlist(components=(), nets=()),
        )
    with pytest.raises(ValueError, match="report ID"):
        _run(
            detail,
            checker=_Checker(accepted=True, checker_id="other-checker"),
            max_checks=2,
        )

    valid = _run(
        _detail_run((True,)),
        checker=_Checker(accepted=True),
        max_checks=1,
    )
    record = valid.result.candidate_records[0]
    assert record.exact_report is not None
    forged_report = record.exact_report.model_copy(
        update={"materialized_layout_fingerprint": "0" * 64}
    )
    forged_record = record.model_copy(update={"exact_report": forged_report})
    forged_result = valid.result.model_copy(update={"candidate_records": (forged_record,)})
    with pytest.raises(ValidationError, match="routed geometry/layout"):
        PlacementExactRunResult.model_validate_json(forged_result.model_dump_json())


def test_changing_findings_changes_only_exact_and_final_evidence() -> None:
    detail = _detail_run((True,))
    first = _run(
        detail,
        checker=_Checker(accepted=False, findings=(FINDING_A,)),
        max_checks=1,
    )
    second = _run(
        detail,
        checker=_Checker(accepted=False, findings=(FINDING_B,)),
        max_checks=1,
    )
    first_record = first.result.candidate_records[0]
    second_record = second.result.candidate_records[0]
    assert first.result.detail_result == second.result.detail_result == detail.result
    assert first_record.detail_record == second_record.detail_record
    assert first_record.detail_record.routing_run == second_record.detail_record.routing_run
    assert first_record.exact_input_fingerprint == second_record.exact_input_fingerprint
    assert first_record.exact_report != second_record.exact_report
    assert first.result.semantic_fingerprint() != second.result.semantic_fingerprint()


def test_checker_exception_is_typed_without_fabricated_report() -> None:
    detail = _detail_run((True,))
    checker = _Checker(accepted=True, error=RuntimeError("checker crashed"))
    first = _run(detail, checker=checker, max_checks=1)
    second = _run(
        detail,
        checker=_Checker(accepted=True, error=RuntimeError("checker crashed")),
        max_checks=1,
    )
    record = first.result.candidate_records[0]
    assert record.disposition is PlacementExactDisposition.CHECKER_ERROR
    assert record.final_state is PlacementFinalState.ROUTED_UNCHECKED
    assert record.exact_report is None and record.checker_error_fingerprint is not None
    assert not record.accepted
    assert first.result == second.result


@pytest.mark.parametrize("behavior", ("raise", "wrong-return", "wrong-id"))
def test_checker_mutation_is_detected_on_every_exit_and_source_is_unchanged(
    behavior: str,
) -> None:
    detail = _detail_run((True,))
    original_layout = detail.routed_layouts[0][1]
    original_fingerprint = board_layout_fingerprint(original_layout)

    def mutating_checker(layout: BoardLayout, netlist: BoardNetlist) -> ExactRouteCheckResult:
        del netlist
        added = TrackSegment(4.0, 4.0, 5.0, 4.0, "F.Cu", "A", 0.2)
        object.__setattr__(layout, "segments", (*layout.segments, added))
        if behavior == "raise":
            raise RuntimeError("mutated then crashed")
        if behavior == "wrong-return":
            return cast(ExactRouteCheckResult, object())
        return ExactRouteCheckResult(
            accepted=True,
            checker_id="wrong-checker",
            finding_fingerprints=(),
        )

    with pytest.raises(ValueError, match="mutated the materialized R5.4 layout"):
        _run(detail, checker=mutating_checker, max_checks=1)
    assert board_layout_fingerprint(original_layout) == original_fingerprint
    assert detail.routed_layouts[0][1] == original_layout


@pytest.mark.parametrize("behavior", ("accept", "raise"))
def test_checker_netlist_mutation_is_detected_and_source_is_unchanged(
    behavior: str,
) -> None:
    detail = _detail_run((True,))
    candidate = detail.result.candidate_records[0].candidate_fingerprint
    source_netlist = BoardNetlist(components=(), nets=())

    def mutating_checker(layout: BoardLayout, netlist: BoardNetlist) -> ExactRouteCheckResult:
        del layout
        object.__setattr__(netlist, "nets", (BoardNet(name="A", nodes=()),))
        if behavior == "raise":
            raise RuntimeError("mutated netlist then crashed")
        return ExactRouteCheckResult(accepted=True, checker_id=CHECKER_ID, finding_fingerprints=())

    with pytest.raises(ValueError, match="mutated the bound R5.4 netlist"):
        evaluate_placement_exact(
            detail,
            netlists_by_candidate_fingerprint={candidate: source_netlist},
            policy=PlacementExactPolicy(checker_id=CHECKER_ID),
            budget=PlacementExactBudget(max_exact_checks=1),
            checker=mutating_checker,
        )
    assert source_netlist == BoardNetlist(components=(), nets=())


def test_input_order_and_nested_authority_tampering_are_stable() -> None:
    detail = _detail_run((True, True))
    checker = _Checker(accepted=True)
    first = evaluate_placement_exact(
        detail,
        netlists_by_candidate_fingerprint=_netlists(detail),
        policy=PlacementExactPolicy(checker_id=CHECKER_ID),
        budget=PlacementExactBudget(max_exact_checks=2),
        checker=checker,
    )
    reversed_netlists = dict(reversed(tuple(_netlists(detail).items())))
    second = evaluate_placement_exact(
        detail,
        netlists_by_candidate_fingerprint=reversed_netlists,
        policy=PlacementExactPolicy(checker_id=CHECKER_ID),
        budget=PlacementExactBudget(max_exact_checks=2),
        checker=_Checker(accepted=True),
    )
    assert first.result == second.result
    record = first.result.candidate_records[0]
    forged = record.model_copy(update={"exact_input_fingerprint": "0" * 64})
    forged_result = first.result.model_copy(
        update={"candidate_records": (forged, *first.result.candidate_records[1:])}
    )
    with pytest.raises(ValidationError, match="exact input fingerprint is stale"):
        PlacementExactRunResult.model_validate_json(forged_result.model_dump_json())

    stale_disposition = record.model_copy(
        update={
            "exact_report": None,
            "exact_checks_consumed": 0,
            "checker_call_index": None,
            "exact_input_fingerprint": None,
            "accepted": False,
            "disposition": PlacementExactDisposition.BUDGET_EXHAUSTED,
            "final_state": PlacementFinalState.ROUTED_UNCHECKED,
        }
    )
    stale_result = first.result.model_copy(
        update={
            "candidate_records": (
                stale_disposition,
                *first.result.candidate_records[1:],
            ),
            "exact_checks_consumed": 1,
            "accepted_candidate_fingerprints": (
                first.result.candidate_records[1].candidate_fingerprint,
            ),
        }
    )
    with pytest.raises(ValidationError, match="skipped before exhaustion"):
        PlacementExactRunResult.model_validate_json(stale_result.model_dump_json())
