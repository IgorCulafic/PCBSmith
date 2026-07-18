"""Replay-bound physical authority for an existing LCS outlier allocation.

This companion validates already selected semantic allocation, transition, and
member-prefix authorities.  It does not choose an LCS, allocate lanes, generate
copper, commit a route, or claim that one legal realization is better than
another.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    BusLaneAssignment,
    BusLayerTransitionEvent,
    allocate_bus_lanes,
)
from pcbsmith.bus_ir import BusGroup, BusLayer, CorridorCapacityCertificate
from pcbsmith.bus_lcs import BusLcsSelectionState
from pcbsmith.bus_lcs_outliers import BusLcsOutlierPlanResult, plan_bus_lcs_outliers
from pcbsmith.kicad.bus_integration import (
    CertifiedBusMemberPrefix,
    CertifiedBusTransitionVia,
)
from pcbsmith.kicad.bus_transition_replay import BusTransitionReplayResult
from pcbsmith.routing_ir import RoutingIrModel
from pcbsmith.rule_profiles import PcbRuleProfile


class BusLcsPhysicalFailureReason(StrEnum):
    """Typed terminal outcomes for ordinary physical infeasibility."""

    SEQUENCE_BINDING = "sequence_binding"
    MEMBER_BINDING = "member_binding"
    AUTHORITY_BINDING = "authority_binding"
    ALLOCATION = "allocation"
    TRANSITION = "transition"
    MISSING_SOURCE_TRANSITION = "missing_source_transition"
    MISSING_TARGET_TRANSITION = "missing_target_transition"
    LAYER = "layer"
    LANE_CAPABILITY = "lane_capability"
    LANE_CAPACITY = "lane_capacity"
    VIA_POLICY = "via_policy"
    PHYSICAL_CARRIER = "physical_carrier"
    BUDGET = "budget"


class BusLcsPhysicalBudget(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-lcs-physical-budget"] = "pcbsmith-bus-lcs-physical-budget"
    schema_version: Literal[1] = 1
    max_member_validations: StrictInt = Field(ge=0)


class BusLcsOutlierLayerBinding(RoutingIrModel):
    """Declared inner-layer interval and its two boundary windows."""

    member_id: str = Field(min_length=1)
    inner_section_ids: tuple[str, ...] = Field(min_length=1)
    source_transition_window_id: str = Field(min_length=1)
    target_transition_window_id: str = Field(min_length=1)

    @field_validator("inner_section_ids")
    @classmethod
    def section_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("inner section IDs must be unique and nonblank")
        return value


class BusLcsPhysicalPolicy(RoutingIrModel):
    """Explicit layer and clearance authority for physical validation."""

    schema_id: Literal["pcbsmith-bus-lcs-physical-policy"] = "pcbsmith-bus-lcs-physical-policy"
    schema_version: Literal[1] = 1
    base_layer: BusLayer
    outlier_layers: tuple[BusLayer, ...] = Field(min_length=1)
    member_clearance_domains: tuple[tuple[str, tuple[str, ...]], ...]
    outlier_bindings: tuple[BusLcsOutlierLayerBinding, ...] = ()
    maximum_vias_per_member: StrictInt = Field(ge=0)
    maximum_via_count_spread: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def declarations_are_canonical(self) -> Self:
        layers = tuple(sorted(set(self.outlier_layers)))
        if len(layers) != len(self.outlier_layers) or self.base_layer in layers:
            raise ValueError("outlier layers must be unique and exclude the base layer")
        domains: list[tuple[str, tuple[str, ...]]] = []
        for member_id, member_domains in self.member_clearance_domains:
            canonical_domains = tuple(sorted(set(member_domains)))
            if (
                not member_id.strip()
                or not canonical_domains
                or any(not item.strip() for item in canonical_domains)
                or len(canonical_domains) != len(member_domains)
            ):
                raise ValueError("member clearance declarations must be unique and nonblank")
            domains.append((member_id, canonical_domains))
        domains.sort(key=lambda item: item[0])
        bindings = tuple(sorted(self.outlier_bindings, key=lambda item: item.member_id))
        if len({item[0] for item in domains}) != len(domains):
            raise ValueError("clearance declarations must be unique per member")
        if len({item.member_id for item in bindings}) != len(bindings):
            raise ValueError("outlier bindings must be unique per member")
        object.__setattr__(self, "outlier_layers", layers)
        object.__setattr__(self, "member_clearance_domains", tuple(domains))
        object.__setattr__(self, "outlier_bindings", bindings)
        return self


class BusLcsPhysicalInput(RoutingIrModel):
    """Complete immutable replay envelope for validation only.

    The certificate's board-geometry and static-obstacle fingerprints remain
    predecessor authority.  This slice has no board snapshot and therefore
    neither recomputes nor claims to re-prove either fingerprint.
    """

    schema_id: Literal["pcbsmith-bus-lcs-physical-input"] = "pcbsmith-bus-lcs-physical-input"
    schema_version: Literal[1] = 1
    sequence_plan: BusLcsOutlierPlanResult
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    transition_authority: BusTransitionReplayResult
    prefixes: tuple[CertifiedBusMemberPrefix, ...]
    rule_profile: PcbRuleProfile
    policy: BusLcsPhysicalPolicy
    budget: BusLcsPhysicalBudget
    sequence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    bus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    certificate_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    transition_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prefix_root_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def retained_fingerprints_are_exact(self) -> Self:
        prefixes = tuple(sorted(self.prefixes, key=lambda item: item.member_id))
        if len({item.member_id for item in prefixes}) != len(prefixes):
            raise ValueError("prefix authority must be unique per member")
        reparsed = (
            BusLcsOutlierPlanResult.model_validate_json(self.sequence_plan.model_dump_json()),
            BusGroup.model_validate_json(self.bus.model_dump_json()),
            CorridorCapacityCertificate.model_validate_json(self.certificate.model_dump_json()),
            BusLaneAllocationResult.model_validate_json(self.allocation.model_dump_json()),
            BusTransitionReplayResult.model_validate_json(
                self.transition_authority.model_dump_json()
            ),
            PcbRuleProfile.model_validate_json(self.rule_profile.model_dump_json()),
            BusLcsPhysicalPolicy.model_validate_json(self.policy.model_dump_json()),
            BusLcsPhysicalBudget.model_validate_json(self.budget.model_dump_json()),
        )
        retained = (
            self.sequence_plan,
            self.bus,
            self.certificate,
            self.allocation,
            self.transition_authority,
            self.rule_profile,
            self.policy,
            self.budget,
        )
        if reparsed != retained or any(
            CertifiedBusMemberPrefix.model_validate_json(item.model_dump_json()) != item
            for item in prefixes
        ):
            raise ValueError("LCS physical authority failed exact JSON reconstruction")
        expected = (
            self.sequence_plan.semantic_fingerprint(),
            self.bus.semantic_fingerprint(),
            self.certificate.semantic_fingerprint(),
            self.allocation.allocation_fingerprint,
            self.transition_authority.semantic_fingerprint(),
            _prefix_root_fingerprint(prefixes),
            bus_lcs_physical_profile_fingerprint(self.rule_profile),
            self.policy.semantic_fingerprint(),
            self.budget.semantic_fingerprint(),
        )
        actual = (
            self.sequence_fingerprint,
            self.bus_fingerprint,
            self.certificate_fingerprint,
            self.allocation_fingerprint,
            self.transition_fingerprint,
            self.prefix_root_fingerprint,
            self.rule_profile_fingerprint,
            self.policy_fingerprint,
            self.budget_fingerprint,
        )
        if actual != expected:
            raise ValueError("LCS physical input contains a stale retained fingerprint")
        object.__setattr__(self, "prefixes", prefixes)
        return self


class BusLcsPhysicalMemberAuthority(RoutingIrModel):
    """Exact retained lane, transition, and prefix claims for one member."""

    member_id: str = Field(min_length=1)
    stationary: bool
    assignments: tuple[BusLaneAssignment, ...] = Field(min_length=1)
    transition_events: tuple[BusLayerTransitionEvent, ...] = ()
    transition_carrier_fingerprints: tuple[str, ...] = ()
    prefix_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    via_count: int = Field(ge=0)


class BusLcsPhysicalResult(RoutingIrModel):
    """Physical-realization authority, never route or board authority."""

    schema_id: Literal["pcbsmith-bus-lcs-physical-result"] = "pcbsmith-bus-lcs-physical-result"
    schema_version: Literal[1] = 1
    algorithm_id: Literal["pcbsmith-bus-lcs-physical-validation-v1"] = (
        "pcbsmith-bus-lcs-physical-validation-v1"
    )
    authority_scope: Literal["physical-realization-only"] = "physical-realization-only"
    realization_input: BusLcsPhysicalInput
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    success: bool
    failure_reason: BusLcsPhysicalFailureReason | None = None
    failed_member_id: str | None = None
    member_validation_count: int = Field(ge=0)
    member_authorities: tuple[BusLcsPhysicalMemberAuthority, ...] = ()

    @model_validator(mode="after")
    def outcome_matches_complete_replay(self) -> Self:
        if self.input_fingerprint != self.realization_input.semantic_fingerprint():
            raise ValueError("physical result input fingerprint is stale")
        replayed = _validate(self.realization_input)
        actual = (
            self.success,
            self.failure_reason,
            self.failed_member_id,
            self.member_validation_count,
            self.member_authorities,
        )
        expected = (
            replayed.success,
            replayed.failure_reason,
            replayed.failed_member_id,
            replayed.member_validation_count,
            replayed.member_authorities,
        )
        if actual != expected:
            raise ValueError("physical result does not match complete validation replay")
        return self


class _Outcome(RoutingIrModel):
    success: bool
    failure_reason: BusLcsPhysicalFailureReason | None = None
    failed_member_id: str | None = None
    member_validation_count: int = Field(ge=0)
    member_authorities: tuple[BusLcsPhysicalMemberAuthority, ...] = ()


def _prefix_root_fingerprint(prefixes: tuple[CertifiedBusMemberPrefix, ...]) -> str:
    return _PrefixRoot(
        prefixes=tuple(item.semantic_fingerprint() for item in prefixes)
    ).semantic_fingerprint()


class _PrefixRoot(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-lcs-prefix-root"] = "pcbsmith-bus-lcs-prefix-root"
    schema_version: Literal[1] = 1
    prefixes: tuple[str, ...]


class _ProfileRoot(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-lcs-physical-profile"] = "pcbsmith-bus-lcs-physical-profile"
    schema_version: Literal[1] = 1
    profile: PcbRuleProfile


def bus_lcs_physical_profile_fingerprint(profile: PcbRuleProfile) -> str:
    """Fingerprint the exact profile under this adapter's versioned namespace."""

    return _ProfileRoot(profile=profile).semantic_fingerprint()


def _failure(
    reason: BusLcsPhysicalFailureReason,
    *,
    count: int = 0,
    member_id: str | None = None,
    authorities: tuple[BusLcsPhysicalMemberAuthority, ...] = (),
) -> _Outcome:
    return _Outcome(
        success=False,
        failure_reason=reason,
        failed_member_id=member_id,
        member_validation_count=count,
        member_authorities=authorities,
    )


def _normalized_order(bus: BusGroup, boundary_index: int) -> tuple[str, ...]:
    boundary = bus.boundaries[boundary_index]
    order = tuple(item.member_id for item in boundary.ordered_members)
    return order if boundary.orientation == "forward" else tuple(reversed(order))


def _preflight(value: BusLcsPhysicalInput) -> BusLcsPhysicalFailureReason | None:
    sequence = value.sequence_plan
    if (
        plan_bus_lcs_outliers(sequence.plan_input) != sequence
        or sequence.lcs_result.state is not BusLcsSelectionState.SELECTED
    ):
        return BusLcsPhysicalFailureReason.SEQUENCE_BINDING
    declared = {item.member_id for item in value.bus.members}
    source = sequence.plan_input.source_member_order
    target = sequence.plan_input.target_member_order
    if (
        set(source) != declared
        or set(target) != declared
        or source != _normalized_order(value.bus, 0)
        or target != _normalized_order(value.bus, -1)
    ):
        return BusLcsPhysicalFailureReason.MEMBER_BINDING
    if (
        not value.allocation.success
        or value.allocation.bus_fingerprint != value.bus_fingerprint
        or value.allocation.certificate_fingerprint != value.certificate_fingerprint
        or tuple(value.allocation.normalized_boundary_orders)
        != tuple(_normalized_order(value.bus, index) for index in range(len(value.bus.boundaries)))
    ):
        return BusLcsPhysicalFailureReason.AUTHORITY_BINDING
    if (
        value.bus.rule_profile_id != value.rule_profile.profile_id
        or value.transition_authority.replay_input.profile != value.rule_profile
        or value.certificate.rule_profile_fingerprint
        != bus_lcs_physical_profile_fingerprint(value.rule_profile)
    ):
        return BusLcsPhysicalFailureReason.AUTHORITY_BINDING
    try:
        replayed_allocation = allocate_bus_lanes(
            value.bus, value.certificate, budget=value.allocation.budget
        )
    except (TypeError, ValueError):
        return BusLcsPhysicalFailureReason.AUTHORITY_BINDING
    if replayed_allocation != value.allocation:
        return BusLcsPhysicalFailureReason.ALLOCATION
    transition = value.transition_authority
    replay_input = transition.replay_input
    if (
        replay_input.bus != value.bus
        or replay_input.certificate != value.certificate
        or replay_input.allocation != value.allocation
        or not transition.generation_result.success
    ):
        return BusLcsPhysicalFailureReason.TRANSITION
    if set(dict(value.policy.member_clearance_domains)) != declared:
        return BusLcsPhysicalFailureReason.MEMBER_BINDING
    outlier_ids = {item.member_id for item in sequence.outlier_members}
    if {item.member_id for item in value.policy.outlier_bindings} != outlier_ids:
        return BusLcsPhysicalFailureReason.MEMBER_BINDING
    if {item.member_id for item in value.prefixes} != declared:
        return BusLcsPhysicalFailureReason.PHYSICAL_CARRIER
    if value.policy.base_layer not in value.bus.layer_policy.allowed_layers or not set(
        value.policy.outlier_layers
    ).issubset(value.bus.layer_policy.allowed_layers):
        return BusLcsPhysicalFailureReason.LAYER
    return None


def _validate(value: BusLcsPhysicalInput) -> _Outcome:
    preflight = _preflight(value)
    if preflight is not None:
        return _failure(preflight)

    members = {item.member_id: item for item in value.bus.members}
    prefixes = {item.member_id: item for item in value.prefixes}
    clearances = dict(value.policy.member_clearance_domains)
    bindings = {item.member_id: item for item in value.policy.outlier_bindings}
    stationary = {item.member_id for item in value.sequence_plan.stationary_members}
    section_ids = tuple(item.section_id for item in value.certificate.sections)
    section_index = {item: index for index, item in enumerate(section_ids)}
    slots = {
        (section.section_id, slot.slot_id): slot
        for section in value.certificate.sections
        for slot in section.lane_slots
    }
    assignments_by_member: dict[str, list[BusLaneAssignment]] = {}
    for assignment in value.allocation.assignments:
        assignments_by_member.setdefault(assignment.member_id, []).append(assignment)
    events_by_member: dict[str, list[BusLayerTransitionEvent]] = {}
    for event in value.allocation.layer_transitions:
        events_by_member.setdefault(event.member_id, []).append(event)
    carriers_by_member: dict[str, list[CertifiedBusTransitionVia]] = {}
    for carrier in value.transition_authority.generation_result.carriers:
        carriers_by_member.setdefault(carrier.member_id, []).append(carrier)
    via_counts = {item.member_id: item.via_count for item in value.allocation.via_counts}
    authorities: list[BusLcsPhysicalMemberAuthority] = []
    work = 0

    # Target order is deliberately preserved; member IDs are never sorted here.
    for member_id in value.sequence_plan.plan_input.target_member_order:
        if work >= value.budget.max_member_validations:
            return _failure(
                BusLcsPhysicalFailureReason.BUDGET,
                count=work,
                member_id=member_id,
                authorities=tuple(authorities),
            )
        work += 1
        member = members[member_id]
        assignments = tuple(
            sorted(
                assignments_by_member.get(member_id, ()),
                key=lambda item: section_index.get(item.section_id, -1),
            )
        )
        if (
            len(assignments) != len(section_ids)
            or tuple(item.section_id for item in assignments) != section_ids
            or len({item.slot_id for item in assignments}) != len(assignments)
        ):
            return _failure(
                BusLcsPhysicalFailureReason.LANE_CAPACITY,
                count=work,
                member_id=member_id,
                authorities=tuple(authorities),
            )
        for assignment in assignments:
            slot = slots.get((assignment.section_id, assignment.slot_id))
            if (
                slot is None
                or assignment.net_name != member.net_name
                or assignment.layer != slot.layer
                or assignment.order_index != slot.order_index
                or member.width_mm > slot.maximum_track_width_mm
                or not set(clearances[member_id]).issubset(slot.supported_clearance_domain_ids)
            ):
                return _failure(
                    BusLcsPhysicalFailureReason.LANE_CAPABILITY,
                    count=work,
                    member_id=member_id,
                    authorities=tuple(authorities),
                )

        member_events = tuple(
            sorted(
                events_by_member.get(member_id, ()),
                key=lambda item: section_index.get(item.section_id, -1),
            )
        )
        member_carriers = tuple(
            sorted(
                carriers_by_member.get(member_id, ()),
                key=lambda item: (section_index.get(item.section_id, -1), item.transition_via_id),
            )
        )
        prefix = prefixes[member_id]
        try:
            prefix.require_authority(
                value.bus,
                value.certificate,
                value.allocation,
                value.transition_authority.replay_input.geometry_registry,
            )
        except (TypeError, ValueError):
            return _failure(
                BusLcsPhysicalFailureReason.PHYSICAL_CARRIER,
                count=work,
                member_id=member_id,
                authorities=tuple(authorities),
            )
        carrier_fps = tuple(sorted(item.semantic_fingerprint() for item in member_carriers))
        if (
            tuple(prefix.transition_via_fingerprints) != carrier_fps
            or len(prefix.prefix.vias) != len(member_carriers)
            or len(member_events) != len(member_carriers)
            or via_counts.get(member_id, 0) != len(member_carriers)
        ):
            return _failure(
                BusLcsPhysicalFailureReason.PHYSICAL_CARRIER,
                count=work,
                member_id=member_id,
                authorities=tuple(authorities),
            )

        if member_id in stationary:
            if (
                member_events
                or member_carriers
                or any(item.layer != value.policy.base_layer for item in assignments)
            ):
                return _failure(
                    BusLcsPhysicalFailureReason.LAYER,
                    count=work,
                    member_id=member_id,
                    authorities=tuple(authorities),
                )
        else:
            binding = bindings[member_id]
            try:
                inner_indices = tuple(section_index[item] for item in binding.inner_section_ids)
            except KeyError:
                return _failure(
                    BusLcsPhysicalFailureReason.LAYER,
                    count=work,
                    member_id=member_id,
                    authorities=tuple(authorities),
                )
            if (
                inner_indices != tuple(range(inner_indices[0], inner_indices[-1] + 1))
                or inner_indices[0] == 0
                or inner_indices[-1] == len(section_ids) - 1
            ):
                return _failure(
                    BusLcsPhysicalFailureReason.LAYER,
                    count=work,
                    member_id=member_id,
                    authorities=tuple(authorities),
                )
            inner = set(binding.inner_section_ids)
            if any(
                (item.section_id in inner and item.layer not in value.policy.outlier_layers)
                or (item.section_id not in inner and item.layer != value.policy.base_layer)
                for item in assignments
            ):
                return _failure(
                    BusLcsPhysicalFailureReason.LAYER,
                    count=work,
                    member_id=member_id,
                    authorities=tuple(authorities),
                )
            source_section = section_ids[inner_indices[0] - 1]
            target_section = section_ids[inner_indices[-1]]
            source_events = tuple(
                item
                for item in member_events
                if item.section_id == source_section
                and item.window_id == binding.source_transition_window_id
                and item.from_layer == value.policy.base_layer
                and item.to_layer in value.policy.outlier_layers
            )
            target_events = tuple(
                item
                for item in member_events
                if item.section_id == target_section
                and item.window_id == binding.target_transition_window_id
                and item.from_layer in value.policy.outlier_layers
                and item.to_layer == value.policy.base_layer
            )
            if len(source_events) != 1:
                return _failure(
                    BusLcsPhysicalFailureReason.MISSING_SOURCE_TRANSITION,
                    count=work,
                    member_id=member_id,
                    authorities=tuple(authorities),
                )
            if len(target_events) != 1:
                return _failure(
                    BusLcsPhysicalFailureReason.MISSING_TARGET_TRANSITION,
                    count=work,
                    member_id=member_id,
                    authorities=tuple(authorities),
                )
            carrier_keys = {
                (item.section_id, item.boundary_id, item.window_id, item.from_layer, item.to_layer)
                for item in member_carriers
            }
            event_keys = {
                (item.section_id, item.boundary_id, item.window_id, item.from_layer, item.to_layer)
                for item in member_events
            }
            if carrier_keys != event_keys:
                return _failure(
                    BusLcsPhysicalFailureReason.PHYSICAL_CARRIER,
                    count=work,
                    member_id=member_id,
                    authorities=tuple(authorities),
                )

        authorities.append(
            BusLcsPhysicalMemberAuthority(
                member_id=member_id,
                stationary=member_id in stationary,
                assignments=assignments,
                transition_events=member_events,
                transition_carrier_fingerprints=carrier_fps,
                prefix_fingerprint=prefix.semantic_fingerprint(),
                via_count=via_counts.get(member_id, 0),
            )
        )

    # Contiguous compatible lane blocks are checked independently per section/layer.
    for section in value.certificate.sections:
        by_layer: dict[str, list[int]] = {}
        for assignment in value.allocation.assignments:
            if assignment.section_id == section.section_id:
                by_layer.setdefault(assignment.layer, []).append(assignment.order_index)
        if any(
            tuple(sorted(indices)) != tuple(range(min(indices), max(indices) + 1))
            for indices in by_layer.values()
        ):
            return _failure(
                BusLcsPhysicalFailureReason.LANE_CAPACITY,
                count=work,
                authorities=tuple(authorities),
            )

    policy = value.bus.layer_policy.via_policy
    counts = tuple(via_counts.get(item.member_id, 0) for item in value.bus.members)
    if (
        set(via_counts) != set(members)
        or any(item > policy.maximum_vias_per_member for item in counts)
        or any(item > value.policy.maximum_vias_per_member for item in counts)
        or (policy.mode in {"forbidden", "escape_only"} and any(counts))
        or (
            policy.maximum_via_count_spread is not None
            and max(counts) - min(counts) > policy.maximum_via_count_spread
        )
        or max(counts) - min(counts) > value.policy.maximum_via_count_spread
    ):
        return _failure(
            BusLcsPhysicalFailureReason.VIA_POLICY,
            count=work,
            authorities=tuple(authorities),
        )
    return _Outcome(
        success=True,
        member_validation_count=work,
        member_authorities=tuple(authorities),
    )


def validate_bus_lcs_physical_realization(
    sequence_plan: BusLcsOutlierPlanResult,
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    transition_authority: BusTransitionReplayResult,
    prefixes: tuple[CertifiedBusMemberPrefix, ...],
    rule_profile: PcbRuleProfile,
    policy: BusLcsPhysicalPolicy,
    budget: BusLcsPhysicalBudget,
) -> BusLcsPhysicalResult:
    """Validate supplied physical authority without mutating caller objects."""

    caller_json = tuple(
        item.model_dump_json()
        for item in (
            sequence_plan,
            bus,
            certificate,
            allocation,
            transition_authority,
            rule_profile,
            policy,
            budget,
            *prefixes,
        )
    )
    canonical_prefixes = tuple(sorted(prefixes, key=lambda item: item.member_id))
    realization_input = BusLcsPhysicalInput(
        sequence_plan=sequence_plan,
        bus=bus,
        certificate=certificate,
        allocation=allocation,
        transition_authority=transition_authority,
        prefixes=canonical_prefixes,
        rule_profile=rule_profile,
        policy=policy,
        budget=budget,
        sequence_fingerprint=sequence_plan.semantic_fingerprint(),
        bus_fingerprint=bus.semantic_fingerprint(),
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        transition_fingerprint=transition_authority.semantic_fingerprint(),
        prefix_root_fingerprint=_prefix_root_fingerprint(canonical_prefixes),
        rule_profile_fingerprint=bus_lcs_physical_profile_fingerprint(rule_profile),
        policy_fingerprint=policy.semantic_fingerprint(),
        budget_fingerprint=budget.semantic_fingerprint(),
    )
    outcome = _validate(realization_input)
    if caller_json != tuple(
        item.model_dump_json()
        for item in (
            sequence_plan,
            bus,
            certificate,
            allocation,
            transition_authority,
            rule_profile,
            policy,
            budget,
            *prefixes,
        )
    ):
        raise RuntimeError("LCS physical validation mutated caller authority")
    return BusLcsPhysicalResult(
        realization_input=realization_input,
        input_fingerprint=realization_input.semantic_fingerprint(),
        success=outcome.success,
        failure_reason=outcome.failure_reason,
        failed_member_id=outcome.failed_member_id,
        member_validation_count=outcome.member_validation_count,
        member_authorities=outcome.member_authorities,
    )
