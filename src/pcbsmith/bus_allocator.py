"""Deterministic semantic bus-lane allocation over certified corridor sections."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from pcbsmith.bus_ir import (
    BusBoundary,
    BusGroup,
    BusLayer,
    BusMember,
    BusSwapWindow,
    CertifiedCorridorSection,
    CorridorCapacityCertificate,
)
from pcbsmith.routing_ir import RoutingIrModel


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


class BusAllocationFailureReason(StrEnum):
    CERTIFICATE_BOUNDARY_MISMATCH = "certificate_boundary_mismatch"
    ACTIVATION_BOUNDARY_INVALID = "activation_boundary_invalid"
    TAP_OR_ACTIVATION_UNSUPPORTED = "tap_or_activation_unsupported"
    INTERIOR_PERMUTATION_UNSUPPORTED = "interior_permutation_unsupported"
    WHOLE_BUNDLE_REVERSAL_FORBIDDEN = "whole_bundle_reversal_forbidden"
    SWAP_WINDOW_UNAVAILABLE = "swap_window_unavailable"
    VIA_POLICY_INCOMPATIBLE = "via_policy_incompatible"
    CAPACITY_INSUFFICIENT = "capacity_insufficient"
    NO_COMPATIBLE_LANE_BLOCK = "no_compatible_lane_block"
    STATE_BUDGET = "state_budget"


class BusAllocationBudget(RoutingIrModel):
    max_states: StrictInt = Field(ge=0)


class BusLaneAssignment(RoutingIrModel):
    section_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    layer: BusLayer
    order_index: int = Field(ge=0)


class BusActivationEvent(RoutingIrModel):
    boundary_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    kind: Literal["activate", "deactivate"]
    terminal_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def terminal_id_set_is_canonical(self) -> Self:
        terminal_ids = tuple(sorted(set(self.terminal_ids)))
        if len(terminal_ids) != len(self.terminal_ids) or any(not item for item in terminal_ids):
            raise ValueError("activation terminal IDs must be unique and non-empty")
        object.__setattr__(self, "terminal_ids", terminal_ids)
        return self


class BusSwapEvent(RoutingIrModel):
    section_id: str = Field(min_length=1)
    exit_boundary_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    sequence_index: int = Field(ge=0)
    order_index: int = Field(ge=0)
    first_member_id: str = Field(min_length=1)
    second_member_id: str = Field(min_length=1)
    layer: BusLayer

    @model_validator(mode="after")
    def members_are_distinct(self) -> Self:
        if self.first_member_id == self.second_member_id:
            raise ValueError("a swap event requires two distinct members")
        return self


class BusLayerTransitionEvent(RoutingIrModel):
    section_id: str = Field(min_length=1)
    boundary_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    from_layer: BusLayer
    to_layer: BusLayer

    @model_validator(mode="after")
    def layers_change(self) -> Self:
        if self.from_layer == self.to_layer:
            raise ValueError("a layer-transition event requires distinct layers")
        return self


class BusMemberViaCount(RoutingIrModel):
    member_id: str = Field(min_length=1)
    via_count: int = Field(ge=0)


def bus_lane_assignments_fingerprint(assignments: tuple[BusLaneAssignment, ...]) -> str:
    canonical = tuple(sorted(assignments, key=lambda item: (item.section_id, item.member_id)))
    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-lane-assignments",
            "schema_version": 1,
            "assignments": [item.model_dump(mode="json") for item in canonical],
        }
    )


def bus_lane_allocation_fingerprint(
    *,
    bus_fingerprint: str,
    certificate_fingerprint: str,
    normalized_boundary_orders: tuple[tuple[str, ...], ...],
    assignments: tuple[BusLaneAssignment, ...],
    activations: tuple[BusActivationEvent, ...] = (),
    swaps: tuple[BusSwapEvent, ...] = (),
    layer_transitions: tuple[BusLayerTransitionEvent, ...] = (),
    via_counts: tuple[BusMemberViaCount, ...] = (),
    permutation_boundary_ids: tuple[str, ...] = (),
) -> str:
    canonical_assignments = tuple(
        sorted(assignments, key=lambda item: (item.section_id, item.member_id))
    )
    canonical_activations = tuple(
        sorted(activations, key=lambda item: (item.boundary_id, item.member_id, item.kind))
    )
    canonical_swaps = tuple(
        sorted(swaps, key=lambda item: (item.section_id, item.sequence_index, item.window_id))
    )
    canonical_transitions = tuple(
        sorted(layer_transitions, key=lambda item: (item.section_id, item.member_id))
    )
    canonical_vias = tuple(sorted(via_counts, key=lambda item: item.member_id))
    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-lane-allocation-decision",
            "schema_version": 2,
            "bus_fingerprint": _require_sha256(bus_fingerprint, "bus_fingerprint"),
            "certificate_fingerprint": _require_sha256(
                certificate_fingerprint, "certificate_fingerprint"
            ),
            "normalized_boundary_orders": normalized_boundary_orders,
            "permutation_boundary_ids": tuple(sorted(permutation_boundary_ids)),
            "assignments": [item.model_dump(mode="json") for item in canonical_assignments],
            "activations": [item.model_dump(mode="json") for item in canonical_activations],
            "swaps": [item.model_dump(mode="json") for item in canonical_swaps],
            "layer_transitions": [item.model_dump(mode="json") for item in canonical_transitions],
            "via_counts": [item.model_dump(mode="json") for item in canonical_vias],
        }
    )


class BusLaneAllocationResult(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-lane-allocation"] = "pcbsmith-bus-lane-allocation"
    schema_version: Literal[2] = 2
    success: bool
    failure_reason: BusAllocationFailureReason | None = None
    bus_fingerprint: str
    certificate_fingerprint: str
    budget: BusAllocationBudget
    state_count: int = Field(ge=0)
    reversal_count: int = Field(ge=0)
    swap_count: int = Field(ge=0)
    activation_count: int = Field(ge=0)
    layer_transition_count: int = Field(ge=0)
    normalized_boundary_orders: tuple[tuple[str, ...], ...]
    permutation_boundary_ids: tuple[str, ...] = ()
    assignments: tuple[BusLaneAssignment, ...] = ()
    activations: tuple[BusActivationEvent, ...] = ()
    swaps: tuple[BusSwapEvent, ...] = ()
    layer_transitions: tuple[BusLayerTransitionEvent, ...] = ()
    via_counts: tuple[BusMemberViaCount, ...] = ()
    allocation_fingerprint: str

    @field_validator("bus_fingerprint", "certificate_fingerprint", "allocation_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_is_coherent(self) -> Self:
        assignments = tuple(
            sorted(self.assignments, key=lambda item: (item.section_id, item.member_id))
        )
        activations = tuple(
            sorted(self.activations, key=lambda item: (item.boundary_id, item.member_id, item.kind))
        )
        swaps = tuple(
            sorted(
                self.swaps, key=lambda item: (item.section_id, item.sequence_index, item.window_id)
            )
        )
        transitions = tuple(
            sorted(self.layer_transitions, key=lambda item: (item.section_id, item.member_id))
        )
        via_counts = tuple(sorted(self.via_counts, key=lambda item: item.member_id))
        permutation_ids = tuple(sorted(set(self.permutation_boundary_ids)))
        if len({(item.section_id, item.member_id) for item in assignments}) != len(assignments):
            raise ValueError("lane assignments must be unique per section and member")
        if any(
            any(not member_id for member_id in order) or len(set(order)) != len(order)
            for order in self.normalized_boundary_orders
        ):
            raise ValueError("normalized boundary orders require unique non-empty member IDs")
        if len(permutation_ids) != len(self.permutation_boundary_ids) or any(
            not item for item in permutation_ids
        ):
            raise ValueError("permutation boundary IDs must be unique and non-empty")
        if len({(item.boundary_id, item.member_id) for item in activations}) != len(activations):
            raise ValueError("activation events must be unique per boundary and member")
        if len({(item.section_id, item.sequence_index) for item in swaps}) != len(swaps):
            raise ValueError("swap sequence indexes must be unique within each section")
        if len({(item.section_id, item.member_id) for item in transitions}) != len(transitions):
            raise ValueError("layer transitions must be unique per section and member")
        if len({item.member_id for item in via_counts}) != len(via_counts):
            raise ValueError("via counts must be unique per member")
        if (
            self.swap_count != len(swaps)
            or self.activation_count != len(activations)
            or self.layer_transition_count != len(transitions)
        ):
            raise ValueError("telemetry counts must match their records")
        derived_vias: dict[str, int] = {}
        for transition in transitions:
            derived_vias[transition.member_id] = derived_vias.get(transition.member_id, 0) + 1
        if any(item.via_count != derived_vias.get(item.member_id, 0) for item in via_counts):
            raise ValueError("via counts must match semantic layer transitions")
        expected = bus_lane_allocation_fingerprint(
            bus_fingerprint=self.bus_fingerprint,
            certificate_fingerprint=self.certificate_fingerprint,
            normalized_boundary_orders=self.normalized_boundary_orders,
            assignments=assignments,
            activations=activations,
            swaps=swaps,
            layer_transitions=transitions,
            via_counts=via_counts,
            permutation_boundary_ids=permutation_ids,
        )
        if self.allocation_fingerprint != expected:
            raise ValueError("allocation_fingerprint must match the complete allocation decision")
        if self.state_count > self.budget.max_states:
            raise ValueError("lane allocation exceeds its fixed state budget")
        if self.success:
            if self.failure_reason is not None or not assignments:
                raise ValueError("successful lane allocation requires assignments and no failure")
        elif self.failure_reason is None or assignments or swaps or transitions or via_counts:
            raise ValueError(
                "failed allocation requires a typed failure and no selected lane state"
            )
        for name, value in (
            ("assignments", assignments),
            ("activations", activations),
            ("swaps", swaps),
            ("layer_transitions", transitions),
            ("via_counts", via_counts),
            ("permutation_boundary_ids", permutation_ids),
        ):
            object.__setattr__(self, name, value)
        return self


@dataclass(frozen=True)
class _CandidateBlock:
    start_index: int
    assignments: tuple[BusLaneAssignment, ...]
    nonpreferred_count: int


@dataclass(frozen=True)
class _SwapStep:
    window_id: str
    order_index: int
    first_member_id: str
    second_member_id: str
    allowed_layers: tuple[BusLayer, ...]


@dataclass(frozen=True)
class _OrderTransitionPlan:
    kind: Literal["same", "reversal", "permutation", "swaps"]
    swaps: tuple[_SwapStep, ...] = ()


@dataclass(frozen=True)
class _PartialState:
    assignments: tuple[BusLaneAssignment, ...]
    member_layers: tuple[tuple[str, BusLayer], ...]
    via_counts: tuple[tuple[str, int], ...]
    swaps: tuple[BusSwapEvent, ...]
    layer_transitions: tuple[BusLayerTransitionEvent, ...]
    previous_start_index: int | None
    lateral_shift: int
    nonpreferred_count: int


DEFAULT_BUS_ALLOCATION_BUDGET = BusAllocationBudget(max_states=100_000)


def allocate_bus_lanes(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    *,
    budget: BusAllocationBudget = DEFAULT_BUS_ALLOCATION_BUDGET,
) -> BusLaneAllocationResult:
    """Allocate certified semantic lanes; detailed copper is deferred to R4.2."""
    bus_fingerprint = bus.semantic_fingerprint()
    certificate_fingerprint = certificate.semantic_fingerprint()
    orders = tuple(_normalized_boundary_order(boundary) for boundary in bus.boundaries)
    activations: tuple[BusActivationEvent, ...] = ()
    permutation_boundary_ids: tuple[str, ...] = ()
    reversal_count = 0

    def failure(
        reason: BusAllocationFailureReason, state_count: int = 0
    ) -> BusLaneAllocationResult:
        allocation_fingerprint = bus_lane_allocation_fingerprint(
            bus_fingerprint=bus_fingerprint,
            certificate_fingerprint=certificate_fingerprint,
            normalized_boundary_orders=orders,
            assignments=(),
            activations=activations,
            permutation_boundary_ids=permutation_boundary_ids,
        )
        return BusLaneAllocationResult(
            success=False,
            failure_reason=reason,
            bus_fingerprint=bus_fingerprint,
            certificate_fingerprint=certificate_fingerprint,
            budget=budget,
            state_count=state_count,
            reversal_count=reversal_count,
            swap_count=0,
            activation_count=len(activations),
            layer_transition_count=0,
            normalized_boundary_orders=orders,
            permutation_boundary_ids=permutation_boundary_ids,
            activations=activations,
            allocation_fingerprint=allocation_fingerprint,
        )

    expected_portals = (
        certificate.sections[0].entry_portal_id,
        *(section.exit_portal_id for section in certificate.sections),
    )
    actual_portals = tuple(boundary.corridor_portal_id for boundary in bus.boundaries)
    if len(bus.boundaries) != len(certificate.sections) + 1 or actual_portals != expected_portals:
        return failure(BusAllocationFailureReason.CERTIFICATE_BOUNDARY_MISMATCH)
    member_by_id = {member.member_id: member for member in bus.members}
    section_orders: list[tuple[str, ...]] = []
    section_exit_orders: list[tuple[str, ...]] = []
    for section_index in range(len(certificate.sections)):
        entry_order = orders[section_index]
        exit_order = orders[section_index + 1]
        common_ids = frozenset(entry_order) & frozenset(exit_order)
        section_orders.append(tuple(item for item in entry_order if item in common_ids))
        section_exit_orders.append(tuple(item for item in exit_order if item in common_ids))
    if not any(section_orders):
        return failure(BusAllocationFailureReason.TAP_OR_ACTIVATION_UNSUPPORTED)
    if any(
        len(section.lane_slots) < len(section_orders[index])
        for index, section in enumerate(certificate.sections)
    ):
        return failure(BusAllocationFailureReason.CAPACITY_INSUFFICIENT)
    activation_result = _activation_events(bus, orders, member_by_id)
    if activation_result is None:
        return failure(BusAllocationFailureReason.ACTIVATION_BOUNDARY_INVALID)
    activations = activation_result

    state_count = 0
    transition_plans: list[_OrderTransitionPlan] = []
    permutation_ids: list[str] = []
    allowed_permutations = dict(bus.permutation_policy.allowed_boundary_permutations)
    for section_index, section in enumerate(certificate.sections):
        previous_order = orders[section_index]
        following_order = orders[section_index + 1]
        previous_common = section_orders[section_index]
        following_common = section_exit_orders[section_index]
        if previous_common == following_common:
            transition_plans.append(_OrderTransitionPlan(kind="same"))
            continue
        membership_changed = frozenset(previous_order) != frozenset(following_order)
        if (
            not membership_changed
            and len(previous_common) > 1
            and following_common == tuple(reversed(previous_common))
        ):
            reversal_count += 1
            if not bus.permutation_policy.allow_whole_bundle_reversal:
                return failure(BusAllocationFailureReason.WHOLE_BUNDLE_REVERSAL_FORBIDDEN)
            transition_plans.append(_OrderTransitionPlan(kind="reversal"))
            continue
        following_boundary = bus.boundaries[section_index + 1]
        allowed_permutation = allowed_permutations.get(following_boundary.boundary_id)
        if (
            allowed_permutation is not None
            and _normalize_order(allowed_permutation, following_boundary) == following_order
        ):
            permutation_ids.append(following_boundary.boundary_id)
            transition_plans.append(_OrderTransitionPlan(kind="permutation"))
            continue
        eligible_windows = _eligible_swap_windows(bus, section)
        if not eligible_windows:
            reason = (
                BusAllocationFailureReason.SWAP_WINDOW_UNAVAILABLE
                if any(
                    window.corridor_region_id == section.section_id
                    for window in bus.permutation_policy.swap_windows
                )
                else BusAllocationFailureReason.INTERIOR_PERMUTATION_UNSUPPORTED
            )
            return failure(reason, state_count)
        swap_plan, expansions, exhausted = _plan_adjacent_swaps(
            previous_common,
            following_common,
            eligible_windows,
            max_expansions=budget.max_states - state_count,
        )
        state_count += expansions
        if exhausted:
            return failure(BusAllocationFailureReason.STATE_BUDGET, state_count)
        if swap_plan is None:
            return failure(BusAllocationFailureReason.INTERIOR_PERMUTATION_UNSUPPORTED, state_count)
        transition_plans.append(_OrderTransitionPlan(kind="swaps", swaps=swap_plan))
    permutation_boundary_ids = tuple(sorted(permutation_ids))

    allowed_layers = frozenset(bus.layer_policy.allowed_layers)
    preferred_layers = frozenset(bus.layer_policy.preferred_layers)
    initial_vias = tuple((member.member_id, 0) for member in bus.members)
    states: tuple[_PartialState, ...] = (
        _PartialState(
            assignments=(),
            member_layers=(),
            via_counts=initial_vias,
            swaps=(),
            layer_transitions=(),
            previous_start_index=None,
            lateral_shift=0,
            nonpreferred_count=0,
        ),
    )
    for section_index, section in enumerate(certificate.sections):
        blocks = _compatible_blocks(
            section, section_orders[section_index], member_by_id, allowed_layers, preferred_layers
        )
        if not blocks:
            return failure(BusAllocationFailureReason.NO_COMPATIBLE_LANE_BLOCK, state_count)
        next_states: list[_PartialState] = []
        via_rejected = False
        swap_rejected = False
        for partial in states:
            for block in blocks:
                if state_count >= budget.max_states:
                    return failure(BusAllocationFailureReason.STATE_BUDGET, state_count)
                state_count += 1
                layer_result = _apply_layer_transition(
                    bus, certificate, section_index, tuple(section_orders), partial, block
                )
                if layer_result is None:
                    via_rejected = True
                    continue
                layers, next_via_counts, transition_events = layer_result
                swap_events = _materialize_swap_events(
                    section,
                    bus.boundaries[section_index + 1],
                    transition_plans[section_index],
                    block,
                )
                if swap_events is None:
                    swap_rejected = True
                    continue
                shift = (
                    0
                    if partial.previous_start_index is None
                    else abs(block.start_index - partial.previous_start_index)
                )
                next_states.append(
                    _PartialState(
                        assignments=(*partial.assignments, *block.assignments),
                        member_layers=layers,
                        via_counts=next_via_counts,
                        swaps=(*partial.swaps, *swap_events),
                        layer_transitions=(*partial.layer_transitions, *transition_events),
                        previous_start_index=block.start_index,
                        lateral_shift=partial.lateral_shift + shift,
                        nonpreferred_count=partial.nonpreferred_count + block.nonpreferred_count,
                    )
                )
        if not next_states:
            if via_rejected:
                return failure(BusAllocationFailureReason.VIA_POLICY_INCOMPATIBLE, state_count)
            if swap_rejected:
                return failure(BusAllocationFailureReason.SWAP_WINDOW_UNAVAILABLE, state_count)
            return failure(BusAllocationFailureReason.NO_COMPATIBLE_LANE_BLOCK, state_count)
        states = tuple(next_states)

    selected = min(
        states,
        key=lambda state: (
            len(state.swaps),
            len(state.layer_transitions),
            state.lateral_shift,
            state.nonpreferred_count,
            tuple(
                (item.section_id, item.member_id, item.slot_id, item.layer, item.order_index)
                for item in sorted(
                    state.assignments, key=lambda item: (item.section_id, item.member_id)
                )
            ),
        ),
    )
    assignments = tuple(selected.assignments)
    swaps = tuple(selected.swaps)
    transitions = tuple(selected.layer_transitions)
    via_count_records = tuple(
        BusMemberViaCount(member_id=member_id, via_count=count)
        for member_id, count in selected.via_counts
    )
    allocation_fingerprint = bus_lane_allocation_fingerprint(
        bus_fingerprint=bus_fingerprint,
        certificate_fingerprint=certificate_fingerprint,
        normalized_boundary_orders=orders,
        assignments=assignments,
        activations=activations,
        swaps=swaps,
        layer_transitions=transitions,
        via_counts=via_count_records,
        permutation_boundary_ids=permutation_boundary_ids,
    )
    return BusLaneAllocationResult(
        success=True,
        bus_fingerprint=bus_fingerprint,
        certificate_fingerprint=certificate_fingerprint,
        budget=budget,
        state_count=state_count,
        reversal_count=reversal_count,
        swap_count=len(swaps),
        activation_count=len(activations),
        layer_transition_count=len(transitions),
        normalized_boundary_orders=orders,
        permutation_boundary_ids=permutation_boundary_ids,
        assignments=assignments,
        activations=activations,
        swaps=swaps,
        layer_transitions=transitions,
        via_counts=via_count_records,
        allocation_fingerprint=allocation_fingerprint,
    )


def _normalized_boundary_order(boundary: BusBoundary) -> tuple[str, ...]:
    return _normalize_order(
        tuple(member.member_id for member in boundary.ordered_members), boundary
    )


def _normalize_order(order: tuple[str, ...], boundary: BusBoundary) -> tuple[str, ...]:
    return order if boundary.orientation == "forward" else tuple(reversed(order))


def _activation_events(
    bus: BusGroup,
    orders: tuple[tuple[str, ...], ...],
    member_by_id: dict[str, BusMember],
) -> tuple[BusActivationEvent, ...] | None:
    events: list[BusActivationEvent] = []
    for boundary_index in range(1, len(bus.boundaries)):
        previous_ids = frozenset(orders[boundary_index - 1])
        current_ids = frozenset(orders[boundary_index])
        previous_refs = {
            item.member_id: item for item in bus.boundaries[boundary_index - 1].ordered_members
        }
        current_refs = {
            item.member_id: item for item in bus.boundaries[boundary_index].ordered_members
        }
        for member_id in sorted(current_ids - previous_ids):
            terminal_ids = current_refs[member_id].terminal_ids
            roles = {
                terminal.role
                for terminal in member_by_id[member_id].terminals
                if terminal.terminal_id in terminal_ids
            }
            if not terminal_ids or not roles & {"source", "tap"}:
                return None
            events.append(
                BusActivationEvent(
                    boundary_id=bus.boundaries[boundary_index].boundary_id,
                    member_id=member_id,
                    kind="activate",
                    terminal_ids=terminal_ids,
                )
            )
        for member_id in sorted(previous_ids - current_ids):
            terminal_ids = previous_refs[member_id].terminal_ids
            roles = {
                terminal.role
                for terminal in member_by_id[member_id].terminals
                if terminal.terminal_id in terminal_ids
            }
            if not terminal_ids or not roles & {"sink", "tap"}:
                return None
            events.append(
                BusActivationEvent(
                    boundary_id=bus.boundaries[boundary_index - 1].boundary_id,
                    member_id=member_id,
                    kind="deactivate",
                    terminal_ids=terminal_ids,
                )
            )
    return tuple(events)


def _eligible_swap_windows(
    bus: BusGroup, section: CertifiedCorridorSection
) -> tuple[BusSwapWindow, ...]:
    certified_ids = frozenset(section.swap_window_ids)
    return tuple(
        window
        for window in bus.permutation_policy.swap_windows
        if window.corridor_region_id == section.section_id and window.window_id in certified_ids
    )


def _plan_adjacent_swaps(
    source: tuple[str, ...],
    target: tuple[str, ...],
    windows: tuple[BusSwapWindow, ...],
    *,
    max_expansions: int,
) -> tuple[tuple[_SwapStep, ...] | None, int, bool]:
    if frozenset(source) != frozenset(target):
        return None, 0, False
    if source == target:
        return (), 0, False
    windows = tuple(sorted(windows, key=lambda item: item.window_id))
    counts = tuple(0 for _ in windows)
    queue: deque[tuple[tuple[str, ...], tuple[int, ...], tuple[_SwapStep, ...]]] = deque(
        ((source, counts, ()),)
    )
    seen = {(source, counts)}
    target_position = {member_id: index for index, member_id in enumerate(target)}
    expansions = 0
    while queue:
        order, used_counts, steps = queue.popleft()
        for order_index in range(len(order) - 1):
            first, second = order[order_index : order_index + 2]
            if target_position[first] < target_position[second]:
                continue
            pair = tuple(sorted((first, second)))
            for window_index, window in enumerate(windows):
                if (
                    pair not in window.allowed_adjacent_pairs
                    or used_counts[window_index] >= window.maximum_swaps
                ):
                    continue
                if expansions >= max_expansions:
                    return None, expansions, True
                expansions += 1
                new_order = list(order)
                new_order[order_index], new_order[order_index + 1] = second, first
                new_counts = list(used_counts)
                new_counts[window_index] += 1
                step = _SwapStep(
                    window_id=window.window_id,
                    order_index=order_index,
                    first_member_id=first,
                    second_member_id=second,
                    allowed_layers=window.allowed_layers,
                )
                candidate_order, candidate_counts = tuple(new_order), tuple(new_counts)
                candidate_steps = (*steps, step)
                if candidate_order == target:
                    return candidate_steps, expansions, False
                key = (candidate_order, candidate_counts)
                if key not in seen:
                    seen.add(key)
                    queue.append((candidate_order, candidate_counts, candidate_steps))
    return None, expansions, False


def _apply_layer_transition(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    section_index: int,
    section_orders: tuple[tuple[str, ...], ...],
    partial: _PartialState,
    block: _CandidateBlock,
) -> (
    tuple[
        tuple[tuple[str, BusLayer], ...],
        tuple[tuple[str, int], ...],
        tuple[BusLayerTransitionEvent, ...],
    ]
    | None
):
    previous_layers = dict(partial.member_layers)
    current_layers = {item.member_id: item.layer for item in block.assignments}
    combined_layers = {**previous_layers, **current_layers}
    if section_index == 0:
        return tuple(sorted(combined_layers.items())), partial.via_counts, ()
    common_ids = frozenset(section_orders[section_index - 1]) & frozenset(
        section_orders[section_index]
    )
    changed_ids = tuple(
        sorted(
            member_id
            for member_id in common_ids
            if previous_layers[member_id] != current_layers[member_id]
        )
    )
    if not changed_ids:
        return tuple(sorted(combined_layers.items())), partial.via_counts, ()
    policy = bus.layer_policy.via_policy
    previous_section = certificate.sections[section_index - 1]
    if policy.mode in {"forbidden", "escape_only"}:
        return None
    if policy.mode in {"declared_transition_windows", "synchronous"}:
        window_ids = tuple(
            sorted(
                frozenset(previous_section.transition_window_ids)
                & frozenset(policy.transition_window_ids)
            )
        )
    else:
        window_ids = tuple(sorted(previous_section.transition_window_ids))
    if not window_ids or (policy.mode == "synchronous" and frozenset(changed_ids) != common_ids):
        return None
    via_counts = dict(partial.via_counts)
    for member_id in changed_ids:
        via_counts[member_id] += 1
        if via_counts[member_id] > policy.maximum_vias_per_member:
            return None
    if policy.maximum_via_count_spread is not None:
        values = tuple(via_counts.values())
        if max(values) - min(values) > policy.maximum_via_count_spread:
            return None
    events = tuple(
        BusLayerTransitionEvent(
            section_id=previous_section.section_id,
            boundary_id=bus.boundaries[section_index].boundary_id,
            window_id=window_ids[0],
            member_id=member_id,
            from_layer=previous_layers[member_id],
            to_layer=current_layers[member_id],
        )
        for member_id in changed_ids
    )
    return tuple(sorted(combined_layers.items())), tuple(sorted(via_counts.items())), events


def _materialize_swap_events(
    section: CertifiedCorridorSection,
    exit_boundary: BusBoundary,
    transition_plan: _OrderTransitionPlan,
    block: _CandidateBlock,
) -> tuple[BusSwapEvent, ...] | None:
    layers = {item.member_id: item.layer for item in block.assignments}
    events: list[BusSwapEvent] = []
    for sequence_index, step in enumerate(transition_plan.swaps):
        first_layer, second_layer = layers[step.first_member_id], layers[step.second_member_id]
        if first_layer != second_layer or first_layer not in step.allowed_layers:
            return None
        events.append(
            BusSwapEvent(
                section_id=section.section_id,
                exit_boundary_id=exit_boundary.boundary_id,
                window_id=step.window_id,
                sequence_index=sequence_index,
                order_index=step.order_index,
                first_member_id=step.first_member_id,
                second_member_id=step.second_member_id,
                layer=first_layer,
            )
        )
    return tuple(events)


def _compatible_blocks(
    section: CertifiedCorridorSection,
    order: tuple[str, ...],
    member_by_id: dict[str, BusMember],
    allowed_layers: frozenset[BusLayer],
    preferred_layers: frozenset[BusLayer],
) -> tuple[_CandidateBlock, ...]:
    if not order:
        return (_CandidateBlock(start_index=0, assignments=(), nonpreferred_count=0),)
    blocks: list[_CandidateBlock] = []
    for start in range(len(section.lane_slots) - len(order) + 1):
        slots = section.lane_slots[start : start + len(order)]
        assignments: list[BusLaneAssignment] = []
        nonpreferred = 0
        compatible = True
        for member_id, slot in zip(order, slots, strict=True):
            member = member_by_id[member_id]
            if (
                slot.layer not in allowed_layers
                or member.width_mm > slot.maximum_track_width_mm
                or "ordinary" not in slot.supported_clearance_domain_ids
            ):
                compatible = False
                break
            if preferred_layers and slot.layer not in preferred_layers:
                nonpreferred += 1
            assignments.append(
                BusLaneAssignment(
                    section_id=section.section_id,
                    member_id=member_id,
                    net_name=member.net_name,
                    slot_id=slot.slot_id,
                    layer=slot.layer,
                    order_index=slot.order_index,
                )
            )
        if compatible:
            blocks.append(
                _CandidateBlock(
                    start_index=start,
                    assignments=tuple(assignments),
                    nonpreferred_count=nonpreferred,
                )
            )
    return tuple(blocks)
