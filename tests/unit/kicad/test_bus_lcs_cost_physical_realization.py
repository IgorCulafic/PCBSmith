from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_bus_lcs_physical_realization import _Fixture, _fixture

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    bus_lane_allocation_fingerprint,
)
from pcbsmith.bus_lcs import BusLcsBoundaryMember
from pcbsmith.bus_lcs_cost_plan import (
    BusLcsCostBudget,
    BusLcsCostPlanResult,
    BusLcsCostPolicy,
    BusLcsMemberOutlierCapability,
    build_bus_lcs_cost_plan_input,
    plan_bus_lcs_cost,
)
from pcbsmith.bus_lcs_outliers import BusLcsOutlierPlanInput, plan_bus_lcs_outliers
from pcbsmith.kicad.bus_lcs_cost_physical_realization import (
    BusLcsCostPhysicalBudget,
    BusLcsCostPhysicalFailureReason,
    BusLcsCostPhysicalResult,
    validate_bus_lcs_cost_physical_realization,
)
from pcbsmith.kicad.bus_lcs_physical_realization import (
    bus_lcs_physical_profile_fingerprint,
)
from pcbsmith.kicad.bus_transition_replay import (
    BusTransitionReplayResult,
    generate_replay_bound_bus_transition_vias,
)
from pcbsmith.kicad.negotiated_resources import OccupancyLedger
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

SOURCE = ("a", "m", "z")
TARGET = ("m", "a", "z")


def _capability(member_id: str, cost: int) -> BusLcsMemberOutlierCapability:
    return BusLcsMemberOutlierCapability(
        member_id=member_id,
        assigned_outlier_layer="B.Cu",
        inner_section_ids=("s1", "s2"),
        source_transition_window_id="window:source",
        target_transition_window_id="window:target",
        source_pad_access_layers=("F.Cu",),
        target_pad_access_layers=("F.Cu",),
        source_transition_cost_units=cost,
        target_transition_cost_units=0,
        via_cost_units=0,
        physical_via_count=2,
        required_clearance_domain_ids=("ordinary", "sensitive"),
        rule_profile_fingerprint=bus_lcs_physical_profile_fingerprint(DEFAULT_PCB_RULE_PROFILE),
    )


def _cost_plan(fixture: _Fixture) -> BusLcsCostPlanResult:
    plan_input = build_bus_lcs_cost_plan_input(
        bus=fixture.bus,
        certificate=fixture.certificate,
        rule_profile=DEFAULT_PCB_RULE_PROFILE,
        source_boundary=tuple(BusLcsBoundaryMember(member_id=item, active=True) for item in SOURCE),
        target_boundary=tuple(BusLcsBoundaryMember(member_id=item, active=True) for item in TARGET),
        outlier_capabilities=(
            _capability("z", 9),
            _capability("m", 9),
            _capability("a", 1),
        ),
        policy=BusLcsCostPolicy(
            base_layer="F.Cu",
            permitted_outlier_layers=("B.Cu",),
            maximum_vias_per_member=2,
            maximum_via_count_spread=2,
        ),
        budget=BusLcsCostBudget(max_dp_cells=9, max_candidates=10_000),
    )
    result = plan_bus_lcs_cost(plan_input)
    assert result.success
    return result


def _authorities() -> tuple[_Fixture, BusLcsCostPlanResult]:
    fixture = _fixture(
        outlier_member="a",
        source_order=SOURCE,
        target_order=TARGET,
    )
    return fixture, _cost_plan(fixture)


def _result(
    fixture: _Fixture,
    plan: BusLcsCostPlanResult,
    *,
    allocation: BusLaneAllocationResult | None = None,
    transition: BusTransitionReplayResult | None = None,
    prefixes=None,
    assignments: int = 12,
    members: int = 3,
) -> BusLcsCostPhysicalResult:
    return validate_bus_lcs_cost_physical_realization(
        plan,
        fixture.allocation if allocation is None else allocation,
        fixture.transition if transition is None else transition,
        fixture.prefixes if prefixes is None else prefixes,
        BusLcsCostPhysicalBudget(
            max_assignment_validations=assignments,
            max_member_validations=members,
        ),
    )


def _coherent_allocation_update(
    allocation: BusLaneAllocationResult,
    **updates: object,
) -> BusLaneAllocationResult:
    candidate = allocation.model_copy(update=updates)
    fingerprint = bus_lane_allocation_fingerprint(
        bus_fingerprint=candidate.bus_fingerprint,
        certificate_fingerprint=candidate.certificate_fingerprint,
        normalized_boundary_orders=candidate.normalized_boundary_orders,
        assignments=candidate.assignments,
        activations=candidate.activations,
        swaps=candidate.swaps,
        layer_transitions=candidate.layer_transitions,
        via_counts=candidate.via_counts,
        permutation_boundary_ids=candidate.permutation_boundary_ids,
    )
    return BusLaneAllocationResult.model_validate(
        candidate.model_copy(update={"allocation_fingerprint": fingerprint}).model_dump()
    )


def test_cost_choice_differs_from_legacy_lexical_and_bridge_follows_cost() -> None:
    fixture, plan = _authorities()
    legacy = plan_bus_lcs_outliers(
        BusLcsOutlierPlanInput(
            source_member_order=SOURCE,
            target_member_order=TARGET,
            max_dp_cells=9,
        )
    )

    result = _result(fixture, plan)

    assert tuple(item.member_id for item in legacy.stationary_members) == ("a", "z")
    assert tuple(item.member_id for item in legacy.outlier_members) == ("m",)
    assert tuple(item.member_id for item in plan.stay_layer_members) == ("m", "z")
    assert tuple(item.member_id for item in plan.outlier_plans) == ("a",)
    assert result.success
    assert tuple(item.member_id for item in result.member_authorities) == TARGET
    assert [item.member_id for item in result.member_authorities if not item.stationary] == ["a"]
    assert result.authority_scope == "cost-plan-to-physical-realization-only"
    assert result.excluded_authority == "no-copper-route-board-commit-or-exact-authority"


def test_section_entry_order_claims_exactly_equal_replayed_allocation() -> None:
    fixture, plan = _authorities()
    claimed = {
        (claim.section_id, member_id): (slot_id, claim.layer, order_index)
        for claim in plan.lane_claims
        for member_id, slot_id, order_index in zip(
            claim.member_ids, claim.slot_ids, claim.order_indices, strict=True
        )
    }
    allocated = {
        (item.section_id, item.member_id): (item.slot_id, item.layer, item.order_index)
        for item in fixture.allocation.assignments
    }

    assert claimed == allocated
    assert (
        tuple(
            member_id
            for claim in plan.lane_claims
            if claim.section_id == "s0"
            for member_id in claim.member_ids
        )
        == SOURCE
    )


@pytest.mark.parametrize("remove", [True, False])
def test_missing_and_extra_allocation_are_rejected_by_exact_replay(remove: bool) -> None:
    fixture, plan = _authorities()
    assignments = list(fixture.allocation.assignments)
    if remove:
        assignments.pop()
    else:
        assignments.append(assignments[0].model_copy(update={"member_id": "extra"}))
    altered = _coherent_allocation_update(
        fixture.allocation,
        assignments=tuple(assignments),
    )

    result = _result(fixture, plan, allocation=altered)

    assert result.failure_reason is BusLcsCostPhysicalFailureReason.ALLOCATION
    assert result.assignment_validation_count == result.member_validation_count == 0


def test_stale_allocation_binding_fails_before_validation_work() -> None:
    fixture, plan = _authorities()
    altered = _coherent_allocation_update(
        fixture.allocation,
        bus_fingerprint="0" * 64,
    )

    result = _result(fixture, plan, allocation=altered)

    assert result.failure_reason is BusLcsCostPhysicalFailureReason.AUTHORITY_BINDING
    assert result.assignment_validation_count == result.member_validation_count == 0


@pytest.mark.parametrize("field", ["slot_id", "layer", "order_index"])
def test_slot_layer_and_order_tamper_are_rejected_by_allocation_replay(field: str) -> None:
    fixture, plan = _authorities()
    assignments = list(fixture.allocation.assignments)
    replacement: object = {
        "slot_id": "slot:stale",
        "layer": "B.Cu" if assignments[0].layer == "F.Cu" else "F.Cu",
        "order_index": assignments[0].order_index + 20,
    }[field]
    assignments[0] = assignments[0].model_copy(update={field: replacement})
    altered = _coherent_allocation_update(
        fixture.allocation,
        assignments=tuple(assignments),
    )

    assert _result(fixture, plan, allocation=altered).failure_reason is (
        BusLcsCostPhysicalFailureReason.ALLOCATION
    )


def test_transition_window_carrier_and_profile_tamper_cannot_enter_envelope() -> None:
    fixture, plan = _authorities()
    payload = json.loads(fixture.transition.model_dump_json())
    payload["generation_result"]["carriers"][0]["window_id"] = "window:stale"
    with pytest.raises(ValidationError):
        BusTransitionReplayResult.model_validate(payload)


def test_valid_but_wrong_transition_profile_and_authority_fail_typed_preflight() -> None:
    fixture, plan = _authorities()
    wrong_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "geometry": DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
                update={"outer_copper_thickness_um": 34.0}
            )
        }
    )
    wrong_transition = generate_replay_bound_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        OccupancyLedger(),
        fixture.transition.replay_input.budget,
        profile=wrong_profile,
    )
    assert wrong_transition.generation_result.success

    result = _result(fixture, plan, transition=wrong_transition)

    assert result.failure_reason is BusLcsCostPhysicalFailureReason.TRANSITION
    assert result.assignment_validation_count == result.member_validation_count == 0

    payload = json.loads(fixture.transition.model_dump_json())
    payload["replay_input"]["profile"]["profile_id"] = "stale-profile"
    with pytest.raises(ValidationError):
        BusTransitionReplayResult.model_validate(payload)


def test_missing_prefix_and_stale_prefix_are_rejected() -> None:
    fixture, plan = _authorities()
    missing = _result(fixture, plan, prefixes=fixture.prefixes[:-1])
    assert missing.failure_reason is BusLcsCostPhysicalFailureReason.MEMBER_BINDING

    payload = json.loads(fixture.prefixes[0].model_dump_json())
    payload["allocation_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError):
        type(fixture.prefixes[0]).model_validate(payload)

    stale_fixture = _fixture()
    stale = _result(fixture, plan, prefixes=stale_fixture.prefixes)
    assert stale.failure_reason is BusLcsCostPhysicalFailureReason.PREFIX


def test_assignment_and_member_budgets_stop_before_next_work_unit() -> None:
    fixture, plan = _authorities()
    zero = _result(fixture, plan, assignments=0)
    assignment_short = _result(fixture, plan, assignments=11)
    member_zero = _result(fixture, plan, members=0)
    member_short = _result(fixture, plan, members=2)

    assert (zero.budget_phase, zero.assignment_validation_count) == ("assignment", 0)
    assert (assignment_short.budget_phase, assignment_short.assignment_validation_count) == (
        "assignment",
        11,
    )
    assert (member_zero.budget_phase, member_zero.member_validation_count) == ("member", 0)
    assert (member_short.budget_phase, member_short.member_validation_count) == ("member", 2)
    assert len(member_short.member_authorities) == 2
    assert all(
        item.failure_reason is BusLcsCostPhysicalFailureReason.BUDGET
        for item in (zero, assignment_short, member_zero, member_short)
    )


def test_json_roundtrip_result_replay_tamper_order_and_immutability() -> None:
    fixture, plan = _authorities()
    before = tuple(
        item.model_dump_json()
        for item in (plan, fixture.allocation, fixture.transition, *fixture.prefixes)
    )
    forward = _result(fixture, plan)
    reversed_prefixes = _result(fixture, plan, prefixes=tuple(reversed(fixture.prefixes)))

    assert BusLcsCostPhysicalResult.model_validate_json(forward.model_dump_json()) == forward
    assert reversed_prefixes.semantic_json() == forward.semantic_json()
    assert before == tuple(
        item.model_dump_json()
        for item in (plan, fixture.allocation, fixture.transition, *fixture.prefixes)
    )
    payload = json.loads(forward.model_dump_json())
    payload["member_validation_count"] -= 1
    with pytest.raises(ValidationError):
        BusLcsCostPhysicalResult.model_validate(payload)


def test_cost_plan_tamper_and_failed_plan_are_not_physical_authority() -> None:
    fixture, plan = _authorities()
    payload = json.loads(plan.model_dump_json())
    payload["stay_count"] -= 1
    with pytest.raises(ValidationError):
        BusLcsCostPlanResult.model_validate(payload)

    failed_input = plan.plan_input.model_copy(
        update={"budget": BusLcsCostBudget(max_dp_cells=0, max_candidates=10_000)}
    )
    failed_input = failed_input.model_copy(
        update={"budget_fingerprint": failed_input.budget.semantic_fingerprint()}
    )
    failed_plan = plan_bus_lcs_cost(failed_input)
    assert not failed_plan.success
    assert _result(fixture, failed_plan).failure_reason is BusLcsCostPhysicalFailureReason.COST_PLAN
