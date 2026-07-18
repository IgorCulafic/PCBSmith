"""Replay-bound physical validation for a successful cost-aware LCS plan.

This adapter consumes the cost planner's decision directly.  It deliberately
does not translate that decision through the older lexical LCS planner: two
maximum-stay decisions may be different while both are internally valid.
The result is validation authority only, never copper, route, board, commit,
or exact-check authority.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    BusLaneAssignment,
    BusLayerTransitionEvent,
    allocate_bus_lanes,
)
from pcbsmith.bus_lcs_cost_plan import BusLcsCostPlanResult, plan_bus_lcs_cost
from pcbsmith.kicad.bus_integration import (
    CertifiedBusMemberPrefix,
    CertifiedBusTransitionVia,
)
from pcbsmith.kicad.bus_transition_replay import BusTransitionReplayResult
from pcbsmith.routing_ir import RoutingIrModel


class BusLcsCostPhysicalFailureReason(StrEnum):
    """Typed terminal outcomes for this validation boundary."""

    COST_PLAN = "cost_plan"
    MEMBER_BINDING = "member_binding"
    AUTHORITY_BINDING = "authority_binding"
    ALLOCATION = "allocation"
    LANE_CLAIM = "lane_claim"
    LANE_CAPABILITY = "lane_capability"
    TRANSITION = "transition"
    MISSING_SOURCE_TRANSITION = "missing_source_transition"
    MISSING_TARGET_TRANSITION = "missing_target_transition"
    LAYER = "layer"
    PHYSICAL_CARRIER = "physical_carrier"
    PREFIX = "prefix"
    VIA_POLICY = "via_policy"
    BUDGET = "budget"


class BusLcsCostPhysicalBudget(RoutingIrModel):
    """Separate fixed limits for lane-claim and member validation work."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-physical-budget"] = (
        "pcbsmith-bus-lcs-cost-physical-budget"
    )
    schema_version: Literal[1] = 1
    max_assignment_validations: StrictInt = Field(ge=0)
    max_member_validations: StrictInt = Field(ge=0)


class _PrefixRoot(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-lcs-cost-prefix-root"] = "pcbsmith-bus-lcs-cost-prefix-root"
    schema_version: Literal[1] = 1
    prefix_fingerprints: tuple[str, ...]


def _prefix_root_fingerprint(prefixes: tuple[CertifiedBusMemberPrefix, ...]) -> str:
    return _PrefixRoot(
        prefix_fingerprints=tuple(item.semantic_fingerprint() for item in prefixes)
    ).semantic_fingerprint()


class BusLcsCostPhysicalInput(RoutingIrModel):
    """Complete immutable input; plan input is the sole semantic policy source."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-physical-input"] = (
        "pcbsmith-bus-lcs-cost-physical-input"
    )
    schema_version: Literal[1] = 1
    cost_plan: BusLcsCostPlanResult
    allocation: BusLaneAllocationResult
    transition_authority: BusTransitionReplayResult
    prefixes: tuple[CertifiedBusMemberPrefix, ...]
    budget: BusLcsCostPhysicalBudget
    cost_plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    transition_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prefix_root_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def retained_authority_is_exact(self) -> Self:
        prefixes = tuple(sorted(self.prefixes, key=lambda item: item.member_id))
        if len({item.member_id for item in prefixes}) != len(prefixes):
            raise ValueError("prefix authority must be unique per member")
        reparsed = (
            BusLcsCostPlanResult.model_validate_json(self.cost_plan.model_dump_json()),
            BusLaneAllocationResult.model_validate_json(self.allocation.model_dump_json()),
            BusTransitionReplayResult.model_validate_json(
                self.transition_authority.model_dump_json()
            ),
            BusLcsCostPhysicalBudget.model_validate_json(self.budget.model_dump_json()),
        )
        if reparsed != (
            self.cost_plan,
            self.allocation,
            self.transition_authority,
            self.budget,
        ) or any(
            CertifiedBusMemberPrefix.model_validate_json(item.model_dump_json()) != item
            for item in prefixes
        ):
            raise ValueError("cost physical authority failed exact JSON reconstruction")
        expected = (
            self.cost_plan.semantic_fingerprint(),
            self.allocation.allocation_fingerprint,
            self.transition_authority.semantic_fingerprint(),
            _prefix_root_fingerprint(prefixes),
            self.budget.semantic_fingerprint(),
        )
        actual = (
            self.cost_plan_fingerprint,
            self.allocation_fingerprint,
            self.transition_fingerprint,
            self.prefix_root_fingerprint,
            self.budget_fingerprint,
        )
        if actual != expected:
            raise ValueError("cost physical input contains a stale retained fingerprint")
        object.__setattr__(self, "prefixes", prefixes)
        return self


class BusLcsCostPhysicalMemberAuthority(RoutingIrModel):
    """Replayed physical authority retained for one target-ordered member."""

    member_id: str = Field(min_length=1)
    stationary: bool
    assignments: tuple[BusLaneAssignment, ...] = Field(min_length=1)
    transition_events: tuple[BusLayerTransitionEvent, ...] = ()
    transition_carrier_fingerprints: tuple[str, ...] = ()
    prefix_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    via_count: int = Field(ge=0)


class _Outcome(RoutingIrModel):
    success: bool
    failure_reason: BusLcsCostPhysicalFailureReason | None = None
    failed_member_id: str | None = None
    failed_assignment_key: tuple[str, str] | None = None
    budget_phase: Literal["assignment", "member"] | None = None
    assignment_validation_count: int = Field(ge=0)
    member_validation_count: int = Field(ge=0)
    member_authorities: tuple[BusLcsCostPhysicalMemberAuthority, ...] = ()


class BusLcsCostPhysicalResult(RoutingIrModel):
    """Fully replayed bridge result with deliberately restricted authority."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-physical-result"] = (
        "pcbsmith-bus-lcs-cost-physical-result"
    )
    schema_version: Literal[1] = 1
    algorithm_id: Literal["pcbsmith-bus-lcs-cost-physical-validation-v1"] = (
        "pcbsmith-bus-lcs-cost-physical-validation-v1"
    )
    authority_scope: Literal["cost-plan-to-physical-realization-only"] = (
        "cost-plan-to-physical-realization-only"
    )
    excluded_authority: Literal["no-copper-route-board-commit-or-exact-authority"] = (
        "no-copper-route-board-commit-or-exact-authority"
    )
    realization_input: BusLcsCostPhysicalInput
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    success: bool
    failure_reason: BusLcsCostPhysicalFailureReason | None = None
    failed_member_id: str | None = None
    failed_assignment_key: tuple[str, str] | None = None
    budget_phase: Literal["assignment", "member"] | None = None
    assignment_validation_count: int = Field(ge=0)
    member_validation_count: int = Field(ge=0)
    member_authorities: tuple[BusLcsCostPhysicalMemberAuthority, ...] = ()

    @model_validator(mode="after")
    def retained_result_matches_complete_replay(self) -> Self:
        if self.input_fingerprint != self.realization_input.semantic_fingerprint():
            raise ValueError("cost physical result input fingerprint is stale")
        replayed = _validate(self.realization_input)
        actual = (
            self.success,
            self.failure_reason,
            self.failed_member_id,
            self.failed_assignment_key,
            self.budget_phase,
            self.assignment_validation_count,
            self.member_validation_count,
            self.member_authorities,
        )
        expected = (
            replayed.success,
            replayed.failure_reason,
            replayed.failed_member_id,
            replayed.failed_assignment_key,
            replayed.budget_phase,
            replayed.assignment_validation_count,
            replayed.member_validation_count,
            replayed.member_authorities,
        )
        if actual != expected:
            raise ValueError("cost physical result does not match complete validation replay")
        return self


def _failure(
    reason: BusLcsCostPhysicalFailureReason,
    *,
    failed_member_id: str | None = None,
    failed_assignment_key: tuple[str, str] | None = None,
    budget_phase: Literal["assignment", "member"] | None = None,
    assignment_count: int = 0,
    member_count: int = 0,
    authorities: tuple[BusLcsCostPhysicalMemberAuthority, ...] = (),
) -> _Outcome:
    return _Outcome(
        success=False,
        failure_reason=reason,
        failed_member_id=failed_member_id,
        failed_assignment_key=failed_assignment_key,
        budget_phase=budget_phase,
        assignment_validation_count=assignment_count,
        member_validation_count=member_count,
        member_authorities=authorities,
    )


def _normalized_order(plan: BusLcsCostPlanResult, boundary_index: int) -> tuple[str, ...]:
    boundary = plan.plan_input.bus.boundaries[boundary_index]
    order = tuple(item.member_id for item in boundary.ordered_members)
    return order if boundary.orientation == "forward" else tuple(reversed(order))


def _preflight(value: BusLcsCostPhysicalInput) -> BusLcsCostPhysicalFailureReason | None:
    plan = value.cost_plan
    authority = plan.plan_input
    bus = authority.bus
    certificate = authority.certificate
    profile = authority.rule_profile
    if not plan.success or plan_bus_lcs_cost(authority) != plan:
        return BusLcsCostPhysicalFailureReason.COST_PLAN
    member_ids = {item.member_id for item in bus.members}
    target_ids = tuple(item.member_id for item in authority.target_boundary if item.active)
    if set(target_ids) != member_ids or {item.member_id for item in value.prefixes} != member_ids:
        return BusLcsCostPhysicalFailureReason.MEMBER_BINDING
    allocation = value.allocation
    if (
        not allocation.success
        or allocation.bus_fingerprint != bus.semantic_fingerprint()
        or allocation.certificate_fingerprint != certificate.semantic_fingerprint()
        or allocation.normalized_boundary_orders
        != tuple(_normalized_order(plan, index) for index in range(len(bus.boundaries)))
    ):
        return BusLcsCostPhysicalFailureReason.AUTHORITY_BINDING
    try:
        replayed_allocation = allocate_bus_lanes(bus, certificate, budget=allocation.budget)
    except (TypeError, ValueError):
        return BusLcsCostPhysicalFailureReason.AUTHORITY_BINDING
    if replayed_allocation != allocation:
        return BusLcsCostPhysicalFailureReason.ALLOCATION
    transition = value.transition_authority
    replay_input = transition.replay_input
    if (
        replay_input.bus != bus
        or replay_input.certificate != certificate
        or replay_input.allocation != allocation
        or replay_input.profile != profile
        or not transition.generation_result.success
    ):
        return BusLcsCostPhysicalFailureReason.TRANSITION
    return None


def _expected_assignments(
    plan: BusLcsCostPlanResult,
) -> tuple[tuple[tuple[str, str], BusLaneAssignment], ...] | None:
    members = {item.member_id: item for item in plan.plan_input.bus.members}
    expected: list[tuple[tuple[str, str], BusLaneAssignment]] = []
    seen: set[tuple[str, str]] = set()
    for claim in plan.lane_claims:
        lengths = (len(claim.member_ids), len(claim.slot_ids), len(claim.order_indices))
        if len(set(lengths)) != 1:
            return None
        for member_id, slot_id, order_index in zip(
            claim.member_ids, claim.slot_ids, claim.order_indices, strict=True
        ):
            key = (claim.section_id, member_id)
            member = members.get(member_id)
            if key in seen or member is None:
                return None
            seen.add(key)
            expected.append(
                (
                    key,
                    BusLaneAssignment(
                        section_id=claim.section_id,
                        member_id=member_id,
                        net_name=member.net_name,
                        slot_id=slot_id,
                        layer=claim.layer,
                        order_index=order_index,
                    ),
                )
            )
    return tuple(expected)


def _validate(value: BusLcsCostPhysicalInput) -> _Outcome:
    preflight = _preflight(value)
    if preflight is not None:
        return _failure(preflight)
    plan = value.cost_plan
    authority = plan.plan_input
    bus = authority.bus
    certificate = authority.certificate
    allocation = value.allocation
    expected_pairs = _expected_assignments(plan)
    if expected_pairs is None:
        return _failure(BusLcsCostPhysicalFailureReason.LANE_CLAIM)
    actual = {(item.section_id, item.member_id): item for item in allocation.assignments}
    expected_keys = {key for key, _assignment in expected_pairs}
    if set(actual) != expected_keys:
        return _failure(BusLcsCostPhysicalFailureReason.LANE_CLAIM)

    slots = {
        (section.section_id, slot.slot_id): slot
        for section in certificate.sections
        for slot in section.lane_slots
    }
    capabilities = {item.member_id: item for item in authority.outlier_capabilities}
    assignment_work = 0
    for key, expected in expected_pairs:
        if assignment_work >= value.budget.max_assignment_validations:
            return _failure(
                BusLcsCostPhysicalFailureReason.BUDGET,
                failed_member_id=key[1],
                failed_assignment_key=key,
                budget_phase="assignment",
                assignment_count=assignment_work,
            )
        assignment_work += 1
        item = actual[key]
        slot = slots.get((item.section_id, item.slot_id))
        capability = capabilities[item.member_id]
        if item != expected:
            return _failure(
                BusLcsCostPhysicalFailureReason.LANE_CLAIM,
                failed_member_id=item.member_id,
                failed_assignment_key=key,
                assignment_count=assignment_work,
            )
        if (
            slot is None
            or slot.layer != item.layer
            or slot.order_index != item.order_index
            or next(member for member in bus.members if member.member_id == item.member_id).width_mm
            > slot.maximum_track_width_mm
            or not set(capability.required_clearance_domain_ids).issubset(
                slot.supported_clearance_domain_ids
            )
        ):
            return _failure(
                BusLcsCostPhysicalFailureReason.LANE_CAPABILITY,
                failed_member_id=item.member_id,
                failed_assignment_key=key,
                assignment_count=assignment_work,
            )

    section_ids = tuple(item.section_id for item in certificate.sections)
    section_index = {item: index for index, item in enumerate(section_ids)}
    assignments_by_member: dict[str, list[BusLaneAssignment]] = {}
    for assignment in allocation.assignments:
        assignments_by_member.setdefault(assignment.member_id, []).append(assignment)
    events_by_member: dict[str, list[BusLayerTransitionEvent]] = {}
    for event in allocation.layer_transitions:
        events_by_member.setdefault(event.member_id, []).append(event)
    carriers_by_member: dict[str, list[CertifiedBusTransitionVia]] = {}
    for carrier in value.transition_authority.generation_result.carriers:
        carriers_by_member.setdefault(carrier.member_id, []).append(carrier)
    prefixes = {item.member_id: item for item in value.prefixes}
    planned_vias = {item.member_id: item.via_count for item in plan.via_counts}
    allocation_vias = {item.member_id: item.via_count for item in allocation.via_counts}
    stationary = {item.member_id for item in plan.stay_layer_members}
    outliers = {item.member_id: item for item in plan.outlier_plans}
    target_ids = tuple(item.member_id for item in authority.target_boundary if item.active)
    authorities: list[BusLcsCostPhysicalMemberAuthority] = []
    member_work = 0

    for member_id in target_ids:
        if member_work >= value.budget.max_member_validations:
            return _failure(
                BusLcsCostPhysicalFailureReason.BUDGET,
                failed_member_id=member_id,
                budget_phase="member",
                assignment_count=assignment_work,
                member_count=member_work,
                authorities=tuple(authorities),
            )
        member_work += 1
        member_assignments = tuple(
            sorted(
                assignments_by_member.get(member_id, ()),
                key=lambda item: section_index[item.section_id],
            )
        )
        events = tuple(
            sorted(
                events_by_member.get(member_id, ()),
                key=lambda item: section_index[item.section_id],
            )
        )
        carriers = tuple(
            sorted(
                carriers_by_member.get(member_id, ()),
                key=lambda item: (section_index[item.section_id], item.transition_via_id),
            )
        )
        prefix = prefixes[member_id]
        try:
            prefix.require_authority(
                bus,
                certificate,
                allocation,
                value.transition_authority.replay_input.geometry_registry,
            )
        except (TypeError, ValueError):
            return _failure(
                BusLcsCostPhysicalFailureReason.PREFIX,
                failed_member_id=member_id,
                assignment_count=assignment_work,
                member_count=member_work,
                authorities=tuple(authorities),
            )
        carrier_fps = tuple(sorted(item.semantic_fingerprint() for item in carriers))
        actual_vias = allocation_vias.get(member_id, 0)
        expected_vias = planned_vias.get(member_id)
        if (
            expected_vias is None
            or actual_vias != expected_vias
            or len(events) != actual_vias
            or len(carriers) != actual_vias
            or len(prefix.prefix.vias) != actual_vias
            or tuple(prefix.transition_via_fingerprints) != carrier_fps
        ):
            return _failure(
                BusLcsCostPhysicalFailureReason.PHYSICAL_CARRIER,
                failed_member_id=member_id,
                assignment_count=assignment_work,
                member_count=member_work,
                authorities=tuple(authorities),
            )
        if member_id in stationary:
            if (
                events
                or carriers
                or any(item.layer != authority.policy.base_layer for item in member_assignments)
            ):
                return _failure(
                    BusLcsCostPhysicalFailureReason.LAYER,
                    failed_member_id=member_id,
                    assignment_count=assignment_work,
                    member_count=member_work,
                    authorities=tuple(authorities),
                )
        else:
            outlier = outliers.get(member_id)
            capability = capabilities[member_id]
            if (
                outlier is None
                or outlier.capability_fingerprint != capability.semantic_fingerprint()
                or outlier.assigned_outlier_layer != capability.assigned_outlier_layer
                or outlier.physical_via_count != capability.physical_via_count
            ):
                return _failure(
                    BusLcsCostPhysicalFailureReason.AUTHORITY_BINDING,
                    failed_member_id=member_id,
                    assignment_count=assignment_work,
                    member_count=member_work,
                    authorities=tuple(authorities),
                )
            inner = set(outlier.inner_section_ids)
            if any(
                (item.section_id in inner and item.layer != outlier.assigned_outlier_layer)
                or (item.section_id not in inner and item.layer != authority.policy.base_layer)
                for item in member_assignments
            ):
                return _failure(
                    BusLcsCostPhysicalFailureReason.LAYER,
                    failed_member_id=member_id,
                    assignment_count=assignment_work,
                    member_count=member_work,
                    authorities=tuple(authorities),
                )
            source_events = tuple(
                item
                for item in events
                if item.section_id == outlier.source_bracketing_section_id
                and item.window_id == outlier.source_transition_window_id
                and item.from_layer == authority.policy.base_layer
                and item.to_layer == outlier.assigned_outlier_layer
            )
            target_events = tuple(
                item
                for item in events
                if item.section_id == outlier.target_bracketing_section_id
                and item.window_id == outlier.target_transition_window_id
                and item.from_layer == outlier.assigned_outlier_layer
                and item.to_layer == authority.policy.base_layer
            )
            if len(source_events) != 1:
                return _failure(
                    BusLcsCostPhysicalFailureReason.MISSING_SOURCE_TRANSITION,
                    failed_member_id=member_id,
                    assignment_count=assignment_work,
                    member_count=member_work,
                    authorities=tuple(authorities),
                )
            if len(target_events) != 1:
                return _failure(
                    BusLcsCostPhysicalFailureReason.MISSING_TARGET_TRANSITION,
                    failed_member_id=member_id,
                    assignment_count=assignment_work,
                    member_count=member_work,
                    authorities=tuple(authorities),
                )
            event_keys = {
                (item.section_id, item.boundary_id, item.window_id, item.from_layer, item.to_layer)
                for item in events
            }
            carrier_keys = {
                (item.section_id, item.boundary_id, item.window_id, item.from_layer, item.to_layer)
                for item in carriers
            }
            if event_keys != carrier_keys:
                return _failure(
                    BusLcsCostPhysicalFailureReason.PHYSICAL_CARRIER,
                    failed_member_id=member_id,
                    assignment_count=assignment_work,
                    member_count=member_work,
                    authorities=tuple(authorities),
                )
        authorities.append(
            BusLcsCostPhysicalMemberAuthority(
                member_id=member_id,
                stationary=member_id in stationary,
                assignments=member_assignments,
                transition_events=events,
                transition_carrier_fingerprints=carrier_fps,
                prefix_fingerprint=prefix.semantic_fingerprint(),
                via_count=actual_vias,
            )
        )

    counts = tuple(allocation_vias.get(item, 0) for item in target_ids)
    via_policy = bus.layer_policy.via_policy
    if (
        set(planned_vias) != set(target_ids)
        or set(allocation_vias) != set(target_ids)
        or max(counts, default=0) > authority.policy.maximum_vias_per_member
        or max(counts, default=0) > via_policy.maximum_vias_per_member
        or max(counts, default=0) - min(counts, default=0)
        > authority.policy.maximum_via_count_spread
        or (
            via_policy.maximum_via_count_spread is not None
            and max(counts, default=0) - min(counts, default=0)
            > via_policy.maximum_via_count_spread
        )
        or (via_policy.mode in {"forbidden", "escape_only"} and any(counts))
    ):
        return _failure(
            BusLcsCostPhysicalFailureReason.VIA_POLICY,
            assignment_count=assignment_work,
            member_count=member_work,
            authorities=tuple(authorities),
        )
    return _Outcome(
        success=True,
        assignment_validation_count=assignment_work,
        member_validation_count=member_work,
        member_authorities=tuple(authorities),
    )


def validate_bus_lcs_cost_physical_realization(
    cost_plan: BusLcsCostPlanResult,
    allocation: BusLaneAllocationResult,
    transition_authority: BusTransitionReplayResult,
    prefixes: tuple[CertifiedBusMemberPrefix, ...],
    budget: BusLcsCostPhysicalBudget,
) -> BusLcsCostPhysicalResult:
    """Validate supplied authority without mutating any caller-owned model."""

    callers = (cost_plan, allocation, transition_authority, budget, *prefixes)
    before = tuple(item.model_dump_json() for item in callers)
    canonical_prefixes = tuple(sorted(prefixes, key=lambda item: item.member_id))
    realization_input = BusLcsCostPhysicalInput(
        cost_plan=cost_plan,
        allocation=allocation,
        transition_authority=transition_authority,
        prefixes=canonical_prefixes,
        budget=budget,
        cost_plan_fingerprint=cost_plan.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        transition_fingerprint=transition_authority.semantic_fingerprint(),
        prefix_root_fingerprint=_prefix_root_fingerprint(canonical_prefixes),
        budget_fingerprint=budget.semantic_fingerprint(),
    )
    outcome = _validate(realization_input)
    if before != tuple(item.model_dump_json() for item in callers):
        raise RuntimeError("cost physical validation mutated caller authority")
    return BusLcsCostPhysicalResult(
        realization_input=realization_input,
        input_fingerprint=realization_input.semantic_fingerprint(),
        success=outcome.success,
        failure_reason=outcome.failure_reason,
        failed_member_id=outcome.failed_member_id,
        failed_assignment_key=outcome.failed_assignment_key,
        budget_phase=outcome.budget_phase,
        assignment_validation_count=outcome.assignment_validation_count,
        member_validation_count=outcome.member_validation_count,
        member_authorities=outcome.member_authorities,
    )
