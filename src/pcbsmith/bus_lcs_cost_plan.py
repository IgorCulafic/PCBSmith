"""Bounded cost-aware layer planning for disordered ordered-bus members.

This companion chooses a stationary common subsequence and reserves only
certificate-declared lane slots for its complement.  A successful result is a
planning constraint; it is not an allocation, physical carrier, route, board,
or exact-check authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from pcbsmith.bus_ir import BusGroup, BusLayer, CorridorCapacityCertificate
from pcbsmith.bus_lcs import BusLcsBoundaryMember, BusLcsStayMember
from pcbsmith.kicad.bus_lcs_physical_realization import (
    bus_lcs_physical_profile_fingerprint,
)
from pcbsmith.routing_ir import RoutingIrModel
from pcbsmith.rule_profiles import PcbRuleProfile


class BusLcsCostFailureReason(StrEnum):
    """Typed terminal outcomes for bounded planning."""

    MEMBER_SET_MISMATCH = "member_set_mismatch"
    ACTIVITY_MISMATCH = "activity_mismatch"
    MEMBER_BINDING = "member_binding"
    AUTHORITY_BINDING = "authority_binding"
    DP_BUDGET = "dp_budget"
    CANDIDATE_BUDGET = "candidate_budget"
    MINIMUM_STAY = "minimum_stay"
    OUTLIER_CAPABILITY = "outlier_capability"
    OUTLIER_LAYER = "outlier_layer"
    MISSING_SOURCE_TRANSITION = "missing_source_transition"
    MISSING_TARGET_TRANSITION = "missing_target_transition"
    LANE_CAPACITY = "lane_capacity"
    LANE_CAPABILITY = "lane_capability"
    VIA_POLICY = "via_policy"


class BusLcsCostBudget(RoutingIrModel):
    """Fixed work limits, checked before each unit of work."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-budget"] = "pcbsmith-bus-lcs-cost-budget"
    schema_version: Literal[1] = 1
    max_dp_cells: StrictInt = Field(ge=0)
    max_candidates: StrictInt = Field(ge=0)


class BusLcsCostPolicy(RoutingIrModel):
    """Layer, via, and minimum-stationary constraints for one plan."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-policy"] = "pcbsmith-bus-lcs-cost-policy"
    schema_version: Literal[1] = 1
    base_layer: BusLayer
    permitted_outlier_layers: tuple[BusLayer, ...] = Field(min_length=1)
    maximum_vias_per_member: StrictInt = Field(ge=0)
    maximum_via_count_spread: StrictInt = Field(ge=0)
    minimum_stay_count: StrictInt = Field(default=0, ge=0)
    minimum_stay_fraction: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def declarations_are_canonical(self) -> Self:
        layers = tuple(sorted(set(self.permitted_outlier_layers)))
        if len(layers) != len(self.permitted_outlier_layers) or self.base_layer in layers:
            raise ValueError("outlier layers must be unique and exclude the base layer")
        if not math.isfinite(self.minimum_stay_fraction):
            raise ValueError("minimum_stay_fraction must be finite")
        object.__setattr__(self, "permitted_outlier_layers", layers)
        return self


class BusLcsMemberOutlierCapability(RoutingIrModel):
    """Complete declared authority for using one member as an outlier."""

    member_id: str = Field(min_length=1)
    assigned_outlier_layer: BusLayer | None
    inner_section_ids: tuple[str, ...] = ()
    source_transition_window_id: str | None
    target_transition_window_id: str | None
    source_pad_access_layers: tuple[BusLayer, ...] = ()
    target_pad_access_layers: tuple[BusLayer, ...] = ()
    source_transition_cost_units: StrictInt = Field(ge=0)
    target_transition_cost_units: StrictInt = Field(ge=0)
    via_cost_units: StrictInt = Field(ge=0)
    physical_via_count: StrictInt = Field(ge=0)
    required_clearance_domain_ids: tuple[str, ...] = Field(min_length=1)
    rule_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_transition_window_id", "target_transition_window_id")
    @classmethod
    def optional_identity_is_nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("transition window IDs must be nonblank when supplied")
        return value

    @model_validator(mode="after")
    def set_like_declarations_are_canonical(self) -> Self:
        for name in ("source_pad_access_layers", "target_pad_access_layers"):
            values = getattr(self, name)
            canonical = tuple(sorted(set(values)))
            if len(canonical) != len(values):
                raise ValueError(f"{name} must contain unique layers")
            object.__setattr__(self, name, canonical)
        domains = tuple(sorted(set(self.required_clearance_domain_ids)))
        if len(domains) != len(self.required_clearance_domain_ids) or any(
            not item.strip() for item in domains
        ):
            raise ValueError("clearance domains must be unique and nonblank")
        if len(set(self.inner_section_ids)) != len(self.inner_section_ids) or any(
            not item.strip() for item in self.inner_section_ids
        ):
            raise ValueError("inner section IDs must be unique and nonblank")
        object.__setattr__(self, "required_clearance_domain_ids", domains)
        return self

    @property
    def total_cost_units(self) -> int:
        return (
            self.source_transition_cost_units
            + self.target_transition_cost_units
            + self.via_cost_units
        )


class _CapabilityRoot(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-lcs-cost-capabilities"] = "pcbsmith-bus-lcs-cost-capabilities"
    schema_version: Literal[1] = 1
    capabilities: tuple[BusLcsMemberOutlierCapability, ...]


class _BoundaryRoot(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-lcs-cost-boundaries"] = "pcbsmith-bus-lcs-cost-boundaries"
    schema_version: Literal[1] = 1
    source_boundary: tuple[BusLcsBoundaryMember, ...]
    target_boundary: tuple[BusLcsBoundaryMember, ...]


class BusLcsCostPlanInput(RoutingIrModel):
    """Complete immutable replay envelope for cost-aware planning."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-plan-input"] = "pcbsmith-bus-lcs-cost-plan-input"
    schema_version: Literal[1] = 1
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    rule_profile: PcbRuleProfile
    source_boundary: tuple[BusLcsBoundaryMember, ...]
    target_boundary: tuple[BusLcsBoundaryMember, ...]
    outlier_capabilities: tuple[BusLcsMemberOutlierCapability, ...]
    policy: BusLcsCostPolicy
    budget: BusLcsCostBudget
    bus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    certificate_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability_root_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    boundary_root_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def retained_authority_is_exact_and_canonical(self) -> Self:
        for name, boundary in (
            ("source_boundary", self.source_boundary),
            ("target_boundary", self.target_boundary),
        ):
            member_ids = tuple(item.member_id for item in boundary)
            if len(member_ids) != len(set(member_ids)):
                raise ValueError(f"{name} member IDs must be unique")
        capabilities = tuple(sorted(self.outlier_capabilities, key=lambda item: item.member_id))
        if len({item.member_id for item in capabilities}) != len(capabilities):
            raise ValueError("outlier capabilities must be unique per member")
        expected = (
            self.bus.semantic_fingerprint(),
            self.certificate.semantic_fingerprint(),
            bus_lcs_physical_profile_fingerprint(self.rule_profile),
            _CapabilityRoot(capabilities=capabilities).semantic_fingerprint(),
            _BoundaryRoot(
                source_boundary=self.source_boundary,
                target_boundary=self.target_boundary,
            ).semantic_fingerprint(),
            self.policy.semantic_fingerprint(),
            self.budget.semantic_fingerprint(),
        )
        actual = (
            self.bus_fingerprint,
            self.certificate_fingerprint,
            self.rule_profile_fingerprint,
            self.capability_root_fingerprint,
            self.boundary_root_fingerprint,
            self.policy_fingerprint,
            self.budget_fingerprint,
        )
        if actual != expected:
            raise ValueError("cost-plan input contains a stale retained fingerprint")
        reparsed = (
            BusGroup.model_validate_json(self.bus.model_dump_json()),
            CorridorCapacityCertificate.model_validate_json(self.certificate.model_dump_json()),
            PcbRuleProfile.model_validate_json(self.rule_profile.model_dump_json()),
            BusLcsCostPolicy.model_validate_json(self.policy.model_dump_json()),
            BusLcsCostBudget.model_validate_json(self.budget.model_dump_json()),
        )
        if reparsed != (
            self.bus,
            self.certificate,
            self.rule_profile,
            self.policy,
            self.budget,
        ):
            raise ValueError("cost-plan authority failed exact JSON reconstruction")
        object.__setattr__(self, "outlier_capabilities", capabilities)
        return self


def build_bus_lcs_cost_plan_input(
    *,
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    rule_profile: PcbRuleProfile,
    source_boundary: tuple[BusLcsBoundaryMember, ...],
    target_boundary: tuple[BusLcsBoundaryMember, ...],
    outlier_capabilities: tuple[BusLcsMemberOutlierCapability, ...],
    policy: BusLcsCostPolicy,
    budget: BusLcsCostBudget,
) -> BusLcsCostPlanInput:
    """Build an input with every retained fingerprint under the v1 namespaces."""

    capabilities = tuple(sorted(outlier_capabilities, key=lambda item: item.member_id))
    return BusLcsCostPlanInput(
        bus=bus,
        certificate=certificate,
        rule_profile=rule_profile,
        source_boundary=source_boundary,
        target_boundary=target_boundary,
        outlier_capabilities=capabilities,
        policy=policy,
        budget=budget,
        bus_fingerprint=bus.semantic_fingerprint(),
        certificate_fingerprint=certificate.semantic_fingerprint(),
        rule_profile_fingerprint=bus_lcs_physical_profile_fingerprint(rule_profile),
        capability_root_fingerprint=_CapabilityRoot(
            capabilities=capabilities
        ).semantic_fingerprint(),
        boundary_root_fingerprint=_BoundaryRoot(
            source_boundary=source_boundary,
            target_boundary=target_boundary,
        ).semantic_fingerprint(),
        policy_fingerprint=policy.semantic_fingerprint(),
        budget_fingerprint=budget.semantic_fingerprint(),
    )


class BusLcsCostOutlierPlan(RoutingIrModel):
    """One target-ordered planned layer excursion."""

    member_id: str = Field(min_length=1)
    source_index: int = Field(ge=0)
    target_index: int = Field(ge=0)
    assigned_outlier_layer: BusLayer
    inner_section_ids: tuple[str, ...] = Field(min_length=1)
    source_bracketing_section_id: str = Field(min_length=1)
    source_transition_window_id: str = Field(min_length=1)
    target_bracketing_section_id: str = Field(min_length=1)
    target_transition_window_id: str = Field(min_length=1)
    transition_cost_units: int = Field(ge=0)
    via_cost_units: int = Field(ge=0)
    total_cost_units: int = Field(ge=0)
    physical_via_count: int = Field(ge=0)
    required_clearance_domain_ids: tuple[str, ...] = Field(min_length=1)
    capability_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class BusLcsPlannedLaneClaim(RoutingIrModel):
    """One contiguous target-relative slot block; no allocation authority."""

    section_id: str = Field(min_length=1)
    layer: BusLayer
    member_ids: tuple[str, ...] = Field(min_length=1)
    slot_ids: tuple[str, ...] = Field(min_length=1)
    order_indices: tuple[int, ...] = Field(min_length=1)


class BusLcsPlannedViaCount(RoutingIrModel):
    member_id: str = Field(min_length=1)
    via_count: int = Field(ge=0)


@dataclass(frozen=True)
class _SelectionState:
    last_target_index: int
    stay_count: int
    outlier_cost: int
    minimum_outlier_vias: int | None
    maximum_outlier_vias: int | None
    sequence: tuple[tuple[int, int, str], ...]

    @property
    def key(self) -> tuple[int, int, int, int | None, int | None]:
        return (
            self.last_target_index,
            self.stay_count,
            self.outlier_cost,
            self.minimum_outlier_vias,
            self.maximum_outlier_vias,
        )


@dataclass(frozen=True)
class _Outcome:
    success: bool
    failure_reason: BusLcsCostFailureReason | None = None
    failed_member_id: str | None = None
    stay_layer_members: tuple[BusLcsStayMember, ...] = ()
    outlier_plans: tuple[BusLcsCostOutlierPlan, ...] = ()
    lane_claims: tuple[BusLcsPlannedLaneClaim, ...] = ()
    via_counts: tuple[BusLcsPlannedViaCount, ...] = ()
    stay_count: int = 0
    stay_fraction: float = 0.0
    total_outlier_cost_units: int = 0
    maximum_member_via_count: int = 0
    via_count_spread: int = 0
    dp_cells_evaluated: int = 0
    candidates_evaluated: int = 0


def _normalized_order(bus: BusGroup, boundary_index: int) -> tuple[str, ...]:
    boundary = bus.boundaries[boundary_index]
    order = tuple(item.member_id for item in boundary.ordered_members)
    return order if boundary.orientation == "forward" else tuple(reversed(order))


def _preflight(value: BusLcsCostPlanInput) -> BusLcsCostFailureReason | None:
    source_ids = {item.member_id for item in value.source_boundary}
    target_ids = {item.member_id for item in value.target_boundary}
    if source_ids != target_ids:
        return BusLcsCostFailureReason.MEMBER_SET_MISMATCH
    source_activity = {item.member_id: item.active for item in value.source_boundary}
    target_activity = {item.member_id: item.active for item in value.target_boundary}
    if source_activity != target_activity:
        return BusLcsCostFailureReason.ACTIVITY_MISMATCH
    declared = {item.member_id for item in value.bus.members}
    if source_ids != declared:
        return BusLcsCostFailureReason.MEMBER_BINDING
    active_source = tuple(item.member_id for item in value.source_boundary if item.active)
    active_target = tuple(item.member_id for item in value.target_boundary if item.active)
    if active_source != _normalized_order(value.bus, 0) or active_target != _normalized_order(
        value.bus, -1
    ):
        return BusLcsCostFailureReason.ACTIVITY_MISMATCH
    if {item.member_id for item in value.outlier_capabilities} != set(active_source):
        return BusLcsCostFailureReason.MEMBER_BINDING
    expected_portals = (
        value.certificate.sections[0].entry_portal_id,
        *(item.exit_portal_id for item in value.certificate.sections),
    )
    actual_portals = tuple(item.corridor_portal_id for item in value.bus.boundaries)
    if (
        len(value.bus.boundaries) != len(value.certificate.sections) + 1
        or expected_portals != actual_portals
        or value.bus.rule_profile_id != value.rule_profile.profile_id
        or value.certificate.rule_profile_fingerprint != value.rule_profile_fingerprint
        or value.policy.base_layer not in value.bus.layer_policy.allowed_layers
        or not set(value.policy.permitted_outlier_layers).issubset(
            value.bus.layer_policy.allowed_layers
        )
    ):
        return BusLcsCostFailureReason.AUTHORITY_BINDING
    return None


def _capability_failure(
    value: BusLcsCostPlanInput,
    capability: BusLcsMemberOutlierCapability | None,
) -> BusLcsCostFailureReason | None:
    if capability is None:
        return BusLcsCostFailureReason.OUTLIER_CAPABILITY
    if (
        capability.rule_profile_fingerprint != value.rule_profile_fingerprint
        or value.policy.base_layer not in capability.source_pad_access_layers
        or value.policy.base_layer not in capability.target_pad_access_layers
    ):
        return BusLcsCostFailureReason.OUTLIER_CAPABILITY
    layer = capability.assigned_outlier_layer
    if layer is None or layer not in value.policy.permitted_outlier_layers:
        return BusLcsCostFailureReason.OUTLIER_LAYER
    section_ids = tuple(item.section_id for item in value.certificate.sections)
    section_index = {item: index for index, item in enumerate(section_ids)}
    try:
        indices = tuple(section_index[item] for item in capability.inner_section_ids)
    except KeyError:
        return BusLcsCostFailureReason.OUTLIER_LAYER
    if (
        not indices
        or indices != tuple(range(indices[0], indices[-1] + 1))
        or indices[0] == 0
        or indices[-1] == len(section_ids) - 1
    ):
        return BusLcsCostFailureReason.OUTLIER_LAYER
    source_window = capability.source_transition_window_id
    if (
        source_window is None
        or source_window not in value.certificate.sections[indices[0] - 1].transition_window_ids
    ):
        return BusLcsCostFailureReason.MISSING_SOURCE_TRANSITION
    target_window = capability.target_transition_window_id
    if (
        target_window is None
        or target_window not in value.certificate.sections[indices[-1]].transition_window_ids
    ):
        return BusLcsCostFailureReason.MISSING_TARGET_TRANSITION
    via_policy = value.bus.layer_policy.via_policy
    if (
        capability.physical_via_count < 2
        or capability.physical_via_count > via_policy.maximum_vias_per_member
        or capability.physical_via_count > value.policy.maximum_vias_per_member
        or via_policy.mode in {"forbidden", "escape_only"}
    ):
        return BusLcsCostFailureReason.VIA_POLICY
    if via_policy.mode in {"declared_transition_windows", "synchronous"} and not {
        source_window,
        target_window,
    }.issubset(via_policy.transition_window_ids):
        return BusLcsCostFailureReason.VIA_POLICY
    return None


def _with_candidate(
    states: dict[tuple[int, int, int, int | None, int | None], _SelectionState],
    candidate: _SelectionState,
) -> None:
    retained = states.get(candidate.key)
    if retained is None or _lexical_sequence_key(candidate.sequence) < _lexical_sequence_key(
        retained.sequence
    ):
        states[candidate.key] = candidate


def _lexical_sequence_key(
    sequence: tuple[tuple[int, int, str], ...],
) -> tuple[tuple[str, ...], tuple[tuple[int, int, str], ...]]:
    """Compare semantic member IDs before deterministic physical-index residuals."""

    return (tuple(item[2] for item in sequence), sequence)


def _selection_score(state: _SelectionState) -> tuple[object, ...]:
    if state.maximum_outlier_vias is None:
        maximum = 0
        spread = 0
    else:
        maximum = state.maximum_outlier_vias
        minimum = 0 if state.stay_count else state.minimum_outlier_vias
        assert minimum is not None
        spread = maximum - minimum
    return (
        -state.stay_count,
        state.outlier_cost,
        maximum,
        spread,
        *_lexical_sequence_key(state.sequence),
    )


def _outlier_plan(
    value: BusLcsCostPlanInput,
    capability: BusLcsMemberOutlierCapability,
    source_index: int,
    target_index: int,
) -> BusLcsCostOutlierPlan:
    section_ids = tuple(item.section_id for item in value.certificate.sections)
    section_index = {item: index for index, item in enumerate(section_ids)}
    first = section_index[capability.inner_section_ids[0]]
    last = section_index[capability.inner_section_ids[-1]]
    assert capability.assigned_outlier_layer is not None
    assert capability.source_transition_window_id is not None
    assert capability.target_transition_window_id is not None
    return BusLcsCostOutlierPlan(
        member_id=capability.member_id,
        source_index=source_index,
        target_index=target_index,
        assigned_outlier_layer=capability.assigned_outlier_layer,
        inner_section_ids=capability.inner_section_ids,
        source_bracketing_section_id=section_ids[first - 1],
        source_transition_window_id=capability.source_transition_window_id,
        target_bracketing_section_id=section_ids[last],
        target_transition_window_id=capability.target_transition_window_id,
        transition_cost_units=(
            capability.source_transition_cost_units + capability.target_transition_cost_units
        ),
        via_cost_units=capability.via_cost_units,
        total_cost_units=capability.total_cost_units,
        physical_via_count=capability.physical_via_count,
        required_clearance_domain_ids=capability.required_clearance_domain_ids,
        capability_fingerprint=capability.semantic_fingerprint(),
    )


def _plan(value: BusLcsCostPlanInput) -> _Outcome:
    preflight = _preflight(value)
    if preflight is not None:
        return _Outcome(success=False, failure_reason=preflight)
    source = tuple(
        (index, item.member_id) for index, item in enumerate(value.source_boundary) if item.active
    )
    target = tuple(
        (index, item.member_id) for index, item in enumerate(value.target_boundary) if item.active
    )
    cells = 0
    # The rectangular table is intentionally computed independently of the
    # candidate frontier so its fixed work accounting remains n*m.
    previous = [0] * (len(target) + 1)
    for _, source_member_id in source:
        current = [0]
        for target_offset, (_, target_member_id) in enumerate(target, start=1):
            if cells >= value.budget.max_dp_cells:
                return _Outcome(
                    success=False,
                    failure_reason=BusLcsCostFailureReason.DP_BUDGET,
                    dp_cells_evaluated=cells,
                )
            cells += 1
            length = max(previous[target_offset], current[target_offset - 1])
            if source_member_id == target_member_id:
                length = max(length, previous[target_offset - 1] + 1)
            current.append(length)
        previous = current

    capabilities = {item.member_id: item for item in value.outlier_capabilities}
    capability_failures = {
        member_id: _capability_failure(value, capabilities.get(member_id))
        for _, member_id in source
    }
    target_indices = {member_id: index for index, member_id in target}
    states: dict[tuple[int, int, int, int | None, int | None], _SelectionState] = {
        (-1, 0, 0, None, None): _SelectionState(-1, 0, 0, None, None, ())
    }
    candidates = 0
    for source_index, member_id in source:
        next_states: dict[tuple[int, int, int, int | None, int | None], _SelectionState] = {}
        target_index = target_indices[member_id]
        capability = capabilities.get(member_id)
        for state in sorted(states.values(), key=lambda item: (item.key, item.sequence)):
            if target_index > state.last_target_index:
                if candidates >= value.budget.max_candidates:
                    return _Outcome(
                        success=False,
                        failure_reason=BusLcsCostFailureReason.CANDIDATE_BUDGET,
                        dp_cells_evaluated=cells,
                        candidates_evaluated=candidates,
                    )
                candidates += 1
                _with_candidate(
                    next_states,
                    _SelectionState(
                        target_index,
                        state.stay_count + 1,
                        state.outlier_cost,
                        state.minimum_outlier_vias,
                        state.maximum_outlier_vias,
                        state.sequence + ((source_index, target_index, member_id),),
                    ),
                )
            if candidates >= value.budget.max_candidates:
                return _Outcome(
                    success=False,
                    failure_reason=BusLcsCostFailureReason.CANDIDATE_BUDGET,
                    dp_cells_evaluated=cells,
                    candidates_evaluated=candidates,
                )
            candidates += 1
            if capability_failures[member_id] is None:
                assert capability is not None
                vias = capability.physical_via_count
                _with_candidate(
                    next_states,
                    _SelectionState(
                        state.last_target_index,
                        state.stay_count,
                        state.outlier_cost + capability.total_cost_units,
                        (
                            vias
                            if state.minimum_outlier_vias is None
                            else min(state.minimum_outlier_vias, vias)
                        ),
                        (
                            vias
                            if state.maximum_outlier_vias is None
                            else max(state.maximum_outlier_vias, vias)
                        ),
                        state.sequence,
                    ),
                )
        states = next_states
        if not states:
            return _Outcome(
                success=False,
                failure_reason=capability_failures.get(member_id)
                or BusLcsCostFailureReason.OUTLIER_CAPABILITY,
                failed_member_id=member_id,
                dp_cells_evaluated=cells,
                candidates_evaluated=candidates,
            )

    selected = min(states.values(), key=_selection_score)
    stay_members = tuple(
        BusLcsStayMember(source_index=s, target_index=t, member_id=member_id)
        for s, t, member_id in selected.sequence
    )
    stay_ids = {item.member_id for item in stay_members}
    source_indices = {member_id: index for index, member_id in source}
    outlier_plans = tuple(
        _outlier_plan(
            value,
            capabilities[member_id],
            source_indices[member_id],
            target_index,
        )
        for target_index, member_id in target
        if member_id not in stay_ids
    )
    active_count = len(source)
    stay_fraction = selected.stay_count / active_count if active_count else 1.0
    required_stay = max(
        value.policy.minimum_stay_count,
        math.ceil(value.policy.minimum_stay_fraction * active_count),
    )
    base_outcome = _Outcome(
        success=False,
        stay_layer_members=stay_members,
        outlier_plans=outlier_plans,
        stay_count=selected.stay_count,
        stay_fraction=stay_fraction,
        total_outlier_cost_units=sum(item.total_cost_units for item in outlier_plans),
        dp_cells_evaluated=cells,
        candidates_evaluated=candidates,
    )
    if selected.stay_count < required_stay:
        return replace(
            base_outcome,
            failure_reason=BusLcsCostFailureReason.MINIMUM_STAY,
        )

    via_counts = tuple(
        BusLcsPlannedViaCount(
            member_id=member_id,
            via_count=(0 if member_id in stay_ids else capabilities[member_id].physical_via_count),
        )
        for _, member_id in target
    )
    counts = tuple(item.via_count for item in via_counts)
    maximum_vias = max(counts, default=0)
    spread = maximum_vias - min(counts, default=0)
    via_policy = value.bus.layer_policy.via_policy
    base_outcome = replace(
        base_outcome,
        via_counts=via_counts,
        maximum_member_via_count=maximum_vias,
        via_count_spread=spread,
    )
    if (
        maximum_vias > value.policy.maximum_vias_per_member
        or maximum_vias > via_policy.maximum_vias_per_member
        or spread > value.policy.maximum_via_count_spread
        or (
            via_policy.maximum_via_count_spread is not None
            and spread > via_policy.maximum_via_count_spread
        )
        or (via_policy.mode in {"forbidden", "escape_only"} and maximum_vias > 0)
    ):
        return replace(
            base_outcome,
            failure_reason=BusLcsCostFailureReason.VIA_POLICY,
        )

    members = {item.member_id: item for item in value.bus.members}
    outlier_by_id = {item.member_id: item for item in outlier_plans}
    lane_claims: list[BusLcsPlannedLaneClaim] = []
    for section_offset, section in enumerate(value.certificate.sections):
        # Lane claims are physical section-entry claims.  Selection remains
        # target-relative, but the lane allocator assigns each section in its
        # normalized entry-boundary order, which may differ before a declared
        # permutation boundary.
        section_member_order = _normalized_order(value.bus, section_offset)
        desired: dict[BusLayer, list[str]] = {}
        for member_id in section_member_order:
            outlier = outlier_by_id.get(member_id)
            layer = (
                outlier.assigned_outlier_layer
                if outlier is not None and section.section_id in outlier.inner_section_ids
                else value.policy.base_layer
            )
            desired.setdefault(layer, []).append(member_id)
        for layer in sorted(desired):
            member_ids = tuple(desired[layer])
            block_size = len(member_ids)
            layer_slots = tuple(item for item in section.lane_slots if item.layer == layer)
            contiguous_layer_block = False
            selected_slots = None
            for start in range(len(section.lane_slots) - block_size + 1):
                if candidates >= value.budget.max_candidates:
                    return replace(
                        base_outcome,
                        failure_reason=BusLcsCostFailureReason.CANDIDATE_BUDGET,
                        lane_claims=tuple(lane_claims),
                        candidates_evaluated=candidates,
                    )
                candidates += 1
                slots = section.lane_slots[start : start + block_size]
                if any(item.layer != layer for item in slots):
                    continue
                contiguous_layer_block = True
                compatible = True
                for member_id, slot in zip(member_ids, slots, strict=True):
                    domains = capabilities[member_id].required_clearance_domain_ids
                    if members[member_id].width_mm > slot.maximum_track_width_mm or not set(
                        domains
                    ).issubset(slot.supported_clearance_domain_ids):
                        compatible = False
                        break
                if compatible:
                    selected_slots = slots
                    break
            if selected_slots is None:
                reason = (
                    BusLcsCostFailureReason.LANE_CAPACITY
                    if len(layer_slots) < block_size or not contiguous_layer_block
                    else BusLcsCostFailureReason.LANE_CAPABILITY
                )
                return replace(
                    base_outcome,
                    failure_reason=reason,
                    lane_claims=tuple(lane_claims),
                    candidates_evaluated=candidates,
                )
            lane_claims.append(
                BusLcsPlannedLaneClaim(
                    section_id=section.section_id,
                    layer=layer,
                    member_ids=member_ids,
                    slot_ids=tuple(item.slot_id for item in selected_slots),
                    order_indices=tuple(item.order_index for item in selected_slots),
                )
            )
    return replace(
        base_outcome,
        success=True,
        lane_claims=tuple(lane_claims),
        candidates_evaluated=candidates,
    )


class _PlanFingerprintRoot(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-lcs-cost-plan-decision"] = (
        "pcbsmith-bus-lcs-cost-plan-decision"
    )
    schema_version: Literal[1] = 1
    input_fingerprint: str
    success: bool
    failure_reason: BusLcsCostFailureReason | None
    failed_member_id: str | None
    stay_layer_members: tuple[BusLcsStayMember, ...]
    outlier_plans: tuple[BusLcsCostOutlierPlan, ...]
    lane_claims: tuple[BusLcsPlannedLaneClaim, ...]
    via_counts: tuple[BusLcsPlannedViaCount, ...]
    dp_cells_evaluated: int
    candidates_evaluated: int


def _plan_fingerprint(input_fingerprint: str, outcome: _Outcome) -> str:
    return _PlanFingerprintRoot(
        input_fingerprint=input_fingerprint,
        success=outcome.success,
        failure_reason=outcome.failure_reason,
        failed_member_id=outcome.failed_member_id,
        stay_layer_members=outcome.stay_layer_members,
        outlier_plans=outcome.outlier_plans,
        lane_claims=outcome.lane_claims,
        via_counts=outcome.via_counts,
        dp_cells_evaluated=outcome.dp_cells_evaluated,
        candidates_evaluated=outcome.candidates_evaluated,
    ).semantic_fingerprint()


class BusLcsCostPlanResult(RoutingIrModel):
    """Replay-bound planning result with no route or board authority."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-plan-result"] = "pcbsmith-bus-lcs-cost-plan-result"
    schema_version: Literal[1] = 1
    algorithm_id: Literal["pcbsmith-bus-lcs-cost-frontier-dp-v1"] = (
        "pcbsmith-bus-lcs-cost-frontier-dp-v1"
    )
    authority_scope: Literal["cost-aware-layer-planning-only"] = "cost-aware-layer-planning-only"
    plan_input: BusLcsCostPlanInput
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    success: bool
    failure_reason: BusLcsCostFailureReason | None = None
    failed_member_id: str | None = None
    stay_layer_members: tuple[BusLcsStayMember, ...] = ()
    outlier_plans: tuple[BusLcsCostOutlierPlan, ...] = ()
    lane_claims: tuple[BusLcsPlannedLaneClaim, ...] = ()
    via_counts: tuple[BusLcsPlannedViaCount, ...] = ()
    stay_count: int = Field(ge=0)
    stay_fraction: float = Field(ge=0.0, le=1.0)
    total_outlier_cost_units: int = Field(ge=0)
    maximum_member_via_count: int = Field(ge=0)
    via_count_spread: int = Field(ge=0)
    dp_cells_evaluated: int = Field(ge=0)
    candidates_evaluated: int = Field(ge=0)

    @model_validator(mode="after")
    def retained_result_matches_complete_replay(self) -> Self:
        if self.input_fingerprint != self.plan_input.semantic_fingerprint():
            raise ValueError("cost-plan result input fingerprint is stale")
        replayed = _plan(self.plan_input)
        expected = (
            replayed.success,
            replayed.failure_reason,
            replayed.failed_member_id,
            replayed.stay_layer_members,
            replayed.outlier_plans,
            replayed.lane_claims,
            replayed.via_counts,
            replayed.stay_count,
            replayed.stay_fraction,
            replayed.total_outlier_cost_units,
            replayed.maximum_member_via_count,
            replayed.via_count_spread,
            replayed.dp_cells_evaluated,
            replayed.candidates_evaluated,
        )
        actual = (
            self.success,
            self.failure_reason,
            self.failed_member_id,
            self.stay_layer_members,
            self.outlier_plans,
            self.lane_claims,
            self.via_counts,
            self.stay_count,
            self.stay_fraction,
            self.total_outlier_cost_units,
            self.maximum_member_via_count,
            self.via_count_spread,
            self.dp_cells_evaluated,
            self.candidates_evaluated,
        )
        if actual != expected:
            raise ValueError("cost-plan result does not match complete replay")
        if self.plan_fingerprint != _plan_fingerprint(self.input_fingerprint, replayed):
            raise ValueError("cost-plan decision fingerprint is stale")
        return self


def plan_bus_lcs_cost(plan_input: BusLcsCostPlanInput) -> BusLcsCostPlanResult:
    """Choose and capacity-plan a bounded LCS without claiming physical success."""

    before = plan_input.model_dump_json()
    outcome = _plan(plan_input)
    if plan_input.model_dump_json() != before:
        raise RuntimeError("cost-aware LCS planning mutated caller authority")
    input_fingerprint = plan_input.semantic_fingerprint()
    return BusLcsCostPlanResult(
        plan_input=plan_input,
        input_fingerprint=input_fingerprint,
        plan_fingerprint=_plan_fingerprint(input_fingerprint, outcome),
        success=outcome.success,
        failure_reason=outcome.failure_reason,
        failed_member_id=outcome.failed_member_id,
        stay_layer_members=outcome.stay_layer_members,
        outlier_plans=outcome.outlier_plans,
        lane_claims=outcome.lane_claims,
        via_counts=outcome.via_counts,
        stay_count=outcome.stay_count,
        stay_fraction=outcome.stay_fraction,
        total_outlier_cost_units=outcome.total_outlier_cost_units,
        maximum_member_via_count=outcome.maximum_member_via_count,
        via_count_spread=outcome.via_count_spread,
        dp_cells_evaluated=outcome.dp_cells_evaluated,
        candidates_evaluated=outcome.candidates_evaluated,
    )
