"""Deterministic generated carriers for certified bus layer-transition events.

The R4.2c4d adapter declares only certified transition sites.  Physical via
diameter, drill, and mask intent remain the responsibility of the existing
member-prefix composer and active rule profile.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    BusLaneAssignment,
    BusLayerTransitionEvent,
)
from pcbsmith.bus_geometry import (
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
)
from pcbsmith.bus_ir import (
    BusGroup,
    BusMember,
    CertifiedCorridorSection,
    CorridorCapacityCertificate,
)
from pcbsmith.kicad.bus_integration import CertifiedBusTransitionVia
from pcbsmith.kicad.negotiated_resources import OccupancyLedger
from pcbsmith.routing_ir import RoutingIrModel
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _profile_fingerprint(profile: PcbRuleProfile) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-transition-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


def _event_id(event: BusLayerTransitionEvent) -> str:
    return json.dumps(
        [
            event.member_id,
            event.section_id,
            event.boundary_id,
            event.window_id,
            event.from_layer,
            event.to_layer,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


class BusTransitionFailureReason(StrEnum):
    INVALID_AUTHORITY = "invalid_authority"
    MEMBER_BUDGET = "member_budget"
    EVENT_BUDGET = "event_budget"
    SWAP_GEOMETRY_UNSUPPORTED = "swap_geometry_unsupported"
    EVENT_MEMBER_BINDING = "event_member_binding"
    SECTION_BINDING = "section_binding"
    BOUNDARY_BINDING = "boundary_binding"
    WINDOW_BINDING = "window_binding"
    ASSIGNMENT_BINDING = "assignment_binding"
    GEOMETRY_BINDING = "geometry_binding"
    LAYER_BINDING = "layer_binding"
    PORTAL_BINDING = "portal_binding"
    DUPLICATE_SAME_NET_SITE = "duplicate_same_net_site"


class BusTransitionBudget(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-transition-budget"] = "pcbsmith-bus-transition-budget"
    schema_version: Literal[1] = 1
    max_members: int = Field(ge=0)
    max_events: int = Field(ge=0)


class BusTransitionInputBinding(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-transition-input-binding"] = (
        "pcbsmith-bus-transition-input-binding"
    )
    schema_version: Literal[1] = 1
    canonical_payload_json: str = Field(min_length=2)

    @model_validator(mode="after")
    def payload_is_canonical(self) -> Self:
        try:
            payload = json.loads(self.canonical_payload_json)
        except json.JSONDecodeError as error:
            raise ValueError("transition input binding is not valid JSON") from error
        if not isinstance(payload, dict) or payload.get("schema_id") != (
            "pcbsmith-generated-bus-transition-inputs"
        ):
            raise ValueError("transition input binding schema is invalid")
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if canonical != self.canonical_payload_json:
            raise ValueError("transition input binding JSON is not canonical")
        return self


class BusTransitionEventTelemetry(RoutingIrModel):
    event_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    net_name: str | None = None
    work_count: Literal[1] = 1
    generated: bool
    carrier_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_reason: BusTransitionFailureReason | None = None

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        if self.generated:
            if (
                self.net_name is None
                or self.carrier_fingerprint is None
                or self.failure_reason is not None
            ):
                raise ValueError("generated transition telemetry is incomplete")
        elif self.carrier_fingerprint is not None or self.failure_reason is None:
            raise ValueError("failed transition telemetry requires only a typed failure")
        return self


class BusTransitionGenerationResult(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-transition-generation-result"] = (
        "pcbsmith-bus-transition-generation-result"
    )
    schema_version: Literal[1] = 1
    success: bool
    bus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    certificate_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    geometry_registry_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_binding: BusTransitionInputBinding
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: BusTransitionBudget
    event_order: tuple[str, ...]
    telemetry: tuple[BusTransitionEventTelemetry, ...] = ()
    event_work_count: int = Field(ge=0)
    carriers: tuple[CertifiedBusTransitionVia, ...] = ()
    failure_reason: BusTransitionFailureReason | None = None
    failed_event_id: str | None = None
    caller_ledger_before_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    caller_ledger_after_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def outcome_is_canonical_and_nested(self) -> Self:
        if self.input_fingerprint != self.input_binding.semantic_fingerprint():
            raise ValueError("transition input fingerprint is stale")
        if self.caller_ledger_before_fingerprint != self.caller_ledger_after_fingerprint:
            raise ValueError("transition carrier generation cannot mutate caller state")
        if tuple(sorted(set(self.event_order))) != self.event_order:
            raise ValueError("transition event order must be canonical and unique")
        attempted = tuple(item.event_id for item in self.telemetry)
        if attempted != self.event_order[: len(attempted)]:
            raise ValueError("transition telemetry must be an attempted-order prefix")
        if self.event_work_count != sum(item.work_count for item in self.telemetry):
            raise ValueError("transition event work must equal retained telemetry")
        if (
            tuple(
                sorted(
                    self.carriers,
                    key=lambda item: (
                        _event_id(
                            BusLayerTransitionEvent(
                                section_id=item.section_id,
                                boundary_id=item.boundary_id,
                                window_id=item.window_id,
                                member_id=item.member_id,
                                from_layer=item.from_layer,
                                to_layer=item.to_layer,
                            )
                        ),
                        item.transition_via_id,
                    ),
                )
            )
            != self.carriers
        ):
            raise ValueError("transition carriers must be canonical")
        carrier_fingerprints: set[str] = set()
        for carrier in self.carriers:
            if CertifiedBusTransitionVia.model_validate_json(carrier.model_dump_json()) != carrier:
                raise ValueError("transition carrier failed nested revalidation")
            actual = (
                carrier.bus_fingerprint,
                carrier.certificate_fingerprint,
                carrier.allocation_fingerprint,
                carrier.geometry_registry_fingerprint,
            )
            expected = (
                self.bus_fingerprint,
                self.certificate_fingerprint,
                self.allocation_fingerprint,
                self.geometry_registry_fingerprint,
            )
            if actual != expected:
                raise ValueError("transition carrier root authority is stale")
            carrier_fingerprints.add(carrier.semantic_fingerprint())
        generated = {item.carrier_fingerprint for item in self.telemetry if item.generated}
        if generated != carrier_fingerprints:
            raise ValueError("transition telemetry does not exactly bind carriers")
        if self.success:
            if (
                self.failure_reason is not None
                or self.failed_event_id is not None
                or len(self.telemetry) != len(self.event_order)
                or not all(item.generated for item in self.telemetry)
            ):
                raise ValueError("successful transition generation is incoherent")
        elif self.failure_reason is None:
            raise ValueError("failed transition generation requires a typed reason")
        elif self.telemetry and self.failed_event_id != self.telemetry[-1].event_id:
            raise ValueError("failed transition identity must match final telemetry")
        elif not self.telemetry and self.failed_event_id is not None:
            raise ValueError("preflight transition failure cannot name unattempted work")
        return self

    def semantic_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


@dataclass(frozen=True)
class _Context:
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    registry: CertifiedLaneGeometryRegistry
    profile: PcbRuleProfile
    input_binding: BusTransitionInputBinding
    budget: BusTransitionBudget
    event_order: tuple[str, ...]
    caller_ledger: OccupancyLedger
    ledger_before: str


def _input_binding(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    registry: CertifiedLaneGeometryRegistry,
    profile: PcbRuleProfile,
    caller_ledger: OccupancyLedger,
    budget: BusTransitionBudget,
) -> BusTransitionInputBinding:
    payload = {
        "schema_id": "pcbsmith-generated-bus-transition-inputs",
        "schema_version": 1,
        "bus_fingerprint": bus.semantic_fingerprint(),
        "certificate_fingerprint": certificate.semantic_fingerprint(),
        "allocation_fingerprint": allocation.allocation_fingerprint,
        "geometry_registry_fingerprint": registry.semantic_fingerprint(),
        "profile": profile.model_dump(mode="json"),
        "caller_ledger_fingerprint": caller_ledger.semantic_fingerprint(),
        "budget": budget.model_dump(mode="json"),
    }
    return BusTransitionInputBinding(
        canonical_payload_json=json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def _result(
    context: _Context,
    *,
    success: bool,
    telemetry: tuple[BusTransitionEventTelemetry, ...] = (),
    carriers: tuple[CertifiedBusTransitionVia, ...] = (),
    failure_reason: BusTransitionFailureReason | None = None,
    failed_event_id: str | None = None,
) -> BusTransitionGenerationResult:
    return BusTransitionGenerationResult(
        success=success,
        bus_fingerprint=context.bus.semantic_fingerprint(),
        certificate_fingerprint=context.certificate.semantic_fingerprint(),
        allocation_fingerprint=context.allocation.allocation_fingerprint,
        geometry_registry_fingerprint=context.registry.semantic_fingerprint(),
        profile_fingerprint=_profile_fingerprint(context.profile),
        input_binding=context.input_binding,
        input_fingerprint=context.input_binding.semantic_fingerprint(),
        budget=context.budget,
        event_order=context.event_order,
        telemetry=telemetry,
        event_work_count=len(telemetry),
        carriers=tuple(
            sorted(
                carriers,
                key=lambda item: (
                    _event_id(
                        BusLayerTransitionEvent(
                            section_id=item.section_id,
                            boundary_id=item.boundary_id,
                            window_id=item.window_id,
                            member_id=item.member_id,
                            from_layer=item.from_layer,
                            to_layer=item.to_layer,
                        )
                    ),
                    item.transition_via_id,
                ),
            )
        ),
        failure_reason=failure_reason,
        failed_event_id=failed_event_id,
        caller_ledger_before_fingerprint=context.ledger_before,
        caller_ledger_after_fingerprint=context.caller_ledger.semantic_fingerprint(),
    )


def _failed_attempt(
    context: _Context,
    event: BusLayerTransitionEvent,
    reason: BusTransitionFailureReason,
    telemetry: list[BusTransitionEventTelemetry],
    carriers: list[CertifiedBusTransitionVia],
    member: BusMember | None,
) -> BusTransitionGenerationResult:
    identity = _event_id(event)
    telemetry.append(
        BusTransitionEventTelemetry(
            event_id=identity,
            member_id=event.member_id,
            net_name=None if member is None else member.net_name,
            generated=False,
            failure_reason=reason,
        )
    )
    return _result(
        context,
        success=False,
        telemetry=tuple(telemetry),
        carriers=tuple(carriers),
        failure_reason=reason,
        failed_event_id=identity,
    )


def _canonical_models_are_live(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    registry: CertifiedLaneGeometryRegistry,
    profile: PcbRuleProfile,
) -> bool:
    try:
        return (
            BusGroup.model_validate_json(bus.model_dump_json()) == bus
            and CorridorCapacityCertificate.model_validate_json(certificate.model_dump_json())
            == certificate
            and BusLaneAllocationResult.model_validate_json(allocation.model_dump_json())
            == allocation
            and CertifiedLaneGeometryRegistry.model_validate_json(registry.model_dump_json())
            == registry
            and PcbRuleProfile.model_validate_json(profile.model_dump_json()) == profile
        )
    except (TypeError, ValueError):
        return False


def _assignment_geometry(
    assignment: BusLaneAssignment,
    section: CertifiedCorridorSection,
    registry_by_id: dict[str, CertifiedLaneGeometry],
) -> tuple[CertifiedLaneGeometry | None, bool]:
    slot = next(
        (item for item in section.lane_slots if item.slot_id == assignment.slot_id),
        None,
    )
    if slot is None or assignment.layer != slot.layer or assignment.order_index != slot.order_index:
        return None, False
    return registry_by_id.get(slot.centerline_geometry_id), True


def generate_certified_bus_transition_vias(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    geometry_registry: CertifiedLaneGeometryRegistry,
    caller_ledger: OccupancyLedger,
    budget: BusTransitionBudget,
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> BusTransitionGenerationResult:
    """Generate exactly one pure carrier per certified allocation transition."""

    fixed_events = tuple(sorted(allocation.layer_transitions, key=_event_id))
    ledger_before = caller_ledger.semantic_fingerprint()
    input_binding = _input_binding(
        bus,
        certificate,
        allocation,
        geometry_registry,
        profile,
        caller_ledger,
        budget,
    )
    context = _Context(
        bus,
        certificate,
        allocation,
        geometry_registry,
        profile,
        input_binding,
        budget,
        tuple(_event_id(event) for event in fixed_events),
        caller_ledger,
        ledger_before,
    )
    if not _canonical_models_are_live(
        bus,
        certificate,
        allocation,
        geometry_registry,
        profile,
    ):
        return _result(
            context,
            success=False,
            failure_reason=BusTransitionFailureReason.INVALID_AUTHORITY,
        )
    bus_fp = bus.semantic_fingerprint()
    certificate_fp = certificate.semantic_fingerprint()
    if (
        bus.rule_profile_id != profile.profile_id
        or not allocation.success
        or allocation.bus_fingerprint != bus_fp
        or allocation.certificate_fingerprint != certificate_fp
        or geometry_registry.certificate_fingerprint != certificate_fp
        or geometry_registry.allocation_fingerprint != allocation.allocation_fingerprint
        or geometry_registry.grid_mm != certificate.grid_mm
    ):
        return _result(
            context,
            success=False,
            failure_reason=BusTransitionFailureReason.INVALID_AUTHORITY,
        )

    if allocation.swaps:
        return _result(
            context,
            success=False,
            failure_reason=BusTransitionFailureReason.SWAP_GEOMETRY_UNSUPPORTED,
        )

    event_members = {event.member_id for event in fixed_events}
    if len(event_members) > budget.max_members:
        return _result(
            context,
            success=False,
            failure_reason=BusTransitionFailureReason.MEMBER_BUDGET,
        )
    if len(fixed_events) > budget.max_events:
        return _result(
            context,
            success=False,
            failure_reason=BusTransitionFailureReason.EVENT_BUDGET,
        )

    section_by_id = {section.section_id: section for section in certificate.sections}
    section_position = {
        section.section_id: index for index, section in enumerate(certificate.sections)
    }
    member_by_id = {member.member_id: member for member in bus.members}
    boundary_by_id = {boundary.boundary_id: boundary for boundary in bus.boundaries}
    geometry_by_id = {
        geometry.centerline_geometry_id: geometry for geometry in geometry_registry.geometries
    }
    slot_by_key = {
        (section.section_id, slot.slot_id): slot
        for section in certificate.sections
        for slot in section.lane_slots
    }
    expected_geometry_ids: set[str] = set()
    for assignment in allocation.assignments:
        slot = slot_by_key.get((assignment.section_id, assignment.slot_id))
        if slot is None:
            return _result(
                context,
                success=False,
                failure_reason=BusTransitionFailureReason.ASSIGNMENT_BINDING,
            )
        expected_geometry_ids.add(slot.centerline_geometry_id)
    if set(geometry_by_id) != expected_geometry_ids:
        return _result(
            context,
            success=False,
            failure_reason=BusTransitionFailureReason.GEOMETRY_BINDING,
        )

    assignments_by_member: dict[str, list[BusLaneAssignment]] = {}
    for assignment in allocation.assignments:
        assignments_by_member.setdefault(assignment.member_id, []).append(assignment)
    for assignments in assignments_by_member.values():
        assignments.sort(key=lambda item: section_position.get(item.section_id, -1))

    telemetry: list[BusTransitionEventTelemetry] = []
    carriers: list[CertifiedBusTransitionVia] = []
    occupied_same_net_sites: set[tuple[str, tuple[int, int]]] = set()
    for event in fixed_events:
        member = member_by_id.get(event.member_id)
        if member is None:
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.EVENT_MEMBER_BINDING,
                telemetry,
                carriers,
                None,
            )
        before_section = section_by_id.get(event.section_id)
        before_position = section_position.get(event.section_id)
        if before_section is None or before_position is None:
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.SECTION_BINDING,
                telemetry,
                carriers,
                member,
            )
        if event.window_id not in before_section.transition_window_ids or (
            bus.layer_policy.via_policy.transition_window_ids
            and event.window_id not in bus.layer_policy.via_policy.transition_window_ids
        ):
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.WINDOW_BINDING,
                telemetry,
                carriers,
                member,
            )
        boundary = boundary_by_id.get(event.boundary_id)
        if boundary is None:
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.BOUNDARY_BINDING,
                telemetry,
                carriers,
                member,
            )

        member_assignments = assignments_by_member.get(event.member_id, [])
        before_index = next(
            (
                index
                for index, assignment in enumerate(member_assignments)
                if assignment.section_id == event.section_id
            ),
            None,
        )
        if before_index is None or before_index + 1 >= len(member_assignments):
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.ASSIGNMENT_BINDING,
                telemetry,
                carriers,
                member,
            )
        before_assignment = member_assignments[before_index]
        after_assignment = member_assignments[before_index + 1]
        if (
            before_assignment.member_id != member.member_id
            or after_assignment.member_id != member.member_id
            or before_assignment.net_name != member.net_name
            or after_assignment.net_name != member.net_name
            or section_position.get(after_assignment.section_id) != before_position + 1
        ):
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.ASSIGNMENT_BINDING,
                telemetry,
                carriers,
                member,
            )
        after_section = section_by_id.get(after_assignment.section_id)
        if after_section is None:
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.SECTION_BINDING,
                telemetry,
                carriers,
                member,
            )
        before, before_slot_valid = _assignment_geometry(
            before_assignment,
            before_section,
            geometry_by_id,
        )
        after, after_slot_valid = _assignment_geometry(
            after_assignment,
            after_section,
            geometry_by_id,
        )
        if (
            not before_slot_valid
            or not after_slot_valid
            or before is None
            or after is None
            or before.section_id != before_section.section_id
            or after.section_id != after_section.section_id
            or before.track_width_mm != member.width_mm
            or after.track_width_mm != member.width_mm
            or before.entry_portal_id != before_section.entry_portal_id
            or before.exit_portal_id != before_section.exit_portal_id
            or after.entry_portal_id != after_section.entry_portal_id
            or after.exit_portal_id != after_section.exit_portal_id
        ):
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.GEOMETRY_BINDING,
                telemetry,
                carriers,
                member,
            )
        if (
            event.from_layer != before_assignment.layer
            or event.to_layer != after_assignment.layer
            or before.layer != before_assignment.layer
            or after.layer != after_assignment.layer
            or event.from_layer == event.to_layer
        ):
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.LAYER_BINDING,
                telemetry,
                carriers,
                member,
            )
        if (
            boundary.corridor_portal_id != before_section.exit_portal_id
            or boundary.corridor_portal_id != after_section.entry_portal_id
            or before.exit_portal_id != after.entry_portal_id
        ):
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.BOUNDARY_BINDING,
                telemetry,
                carriers,
                member,
            )
        if before.exit_portal_point != after.entry_portal_point:
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.PORTAL_BINDING,
                telemetry,
                carriers,
                member,
            )

        point = before.exit_portal_point
        site = (member.net_name, point)
        if site in occupied_same_net_sites:
            return _failed_attempt(
                context,
                event,
                BusTransitionFailureReason.DUPLICATE_SAME_NET_SITE,
                telemetry,
                carriers,
                member,
            )
        occupied_same_net_sites.add(site)
        carrier_binding = {
            "schema_id": "pcbsmith-generated-bus-transition-via",
            "schema_version": 1,
            "event_id": _event_id(event),
            "before_geometry_id": before.centerline_geometry_id,
            "after_geometry_id": after.centerline_geometry_id,
            "point": point,
        }
        carrier = CertifiedBusTransitionVia(
            transition_via_id=(
                f"generated-transition-via:{member.member_id}:{_fingerprint(carrier_binding)}"
            ),
            bus_fingerprint=bus_fp,
            certificate_fingerprint=certificate_fp,
            allocation_fingerprint=allocation.allocation_fingerprint,
            geometry_registry_fingerprint=geometry_registry.semantic_fingerprint(),
            member_id=member.member_id,
            net_name=member.net_name,
            section_id=event.section_id,
            boundary_id=event.boundary_id,
            window_id=event.window_id,
            from_layer=event.from_layer,
            to_layer=event.to_layer,
            before_geometry_id=before.centerline_geometry_id,
            after_geometry_id=after.centerline_geometry_id,
            grid_mm=certificate.grid_mm,
            point=point,
        )
        carriers.append(carrier)
        telemetry.append(
            BusTransitionEventTelemetry(
                event_id=_event_id(event),
                member_id=member.member_id,
                net_name=member.net_name,
                generated=True,
                carrier_fingerprint=carrier.semantic_fingerprint(),
            )
        )

    return _result(
        context,
        success=True,
        telemetry=tuple(telemetry),
        carriers=tuple(carriers),
    )
