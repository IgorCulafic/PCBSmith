"""Replay-bound prefix composition for accepted physical bus-swap plans.

This pure schema-v1 seam classifies every adjacent certified lane boundary,
consumes already-certified pigtail, semantic-via, and physical-swap carriers,
and derives connected ``GridRoutePrefix`` authority.  It performs no search,
occupancy mutation, transaction commit, board materialization, or exact DRC.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.bus_allocator import BusLaneAssignment, BusLayerTransitionEvent
from pcbsmith.bus_geometry import CertifiedLaneGeometry
from pcbsmith.bus_ir import BusBoundary, BusMember
from pcbsmith.kicad.board import TrackSegment, ViaSpec
from pcbsmith.kicad.bus_integration import (
    CertifiedBusPigtail,
    CertifiedBusTransitionVia,
)
from pcbsmith.kicad.bus_physical_swap_plan import (
    BusPhysicalSwapPlanDisposition,
    ReplayBoundBusPhysicalSwapPlan,
)
from pcbsmith.kicad.bus_swap_carrier import BusSwapMemberCarrier
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.routing_ir import RoutingIrModel


class BusPhysicalSwapBoundaryKind(StrEnum):
    DIRECT = "direct"
    SEMANTIC_TRANSITION = "semantic_transition"
    PHYSICAL_SWAP = "physical_swap"


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _prefix_payload(prefix: GridRoutePrefix) -> dict[str, Any]:
    return {
        "net_name": prefix.net_name,
        "grid_mm": prefix.grid_mm,
        "exit_node": prefix.exit_node,
        "covered_pad_anchors": prefix.covered_pad_anchors,
        "segments": [
            {
                "start_mm": (item.x1, item.y1),
                "end_mm": (item.x2, item.y2),
                "layer": item.layer,
                "net_name": item.net_name,
                "width_mm": item.width_mm,
            }
            for item in prefix.segments
        ],
        "vias": [
            {
                "at_mm": (item.x, item.y),
                "net_name": item.net_name,
                "size_mm": item.size_mm,
                "drill_mm": item.drill_mm,
                "front_mask": item.front_mask.value,
                "back_mask": item.back_mask.value,
            }
            for item in prefix.vias
        ],
    }


class BusPhysicalSwapTerminalSourceBinding(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-terminal-source-binding"] = (
        "pcbsmith-bus-physical-swap-terminal-source-binding"
    )
    schema_version: Literal[1] = 1
    member_id: str = Field(min_length=1)
    terminal_id: str = Field(min_length=1)
    physical_pad_source_id: str = Field(min_length=1)


class BusPhysicalSwapCompositionInput(RoutingIrModel):
    """Complete immutable input authority for physical-swap prefix composition."""

    schema_id: Literal["pcbsmith-bus-physical-swap-composition-input"] = (
        "pcbsmith-bus-physical-swap-composition-input"
    )
    schema_version: Literal[1] = 1
    plan: ReplayBoundBusPhysicalSwapPlan
    pigtails: tuple[CertifiedBusPigtail, ...]
    transition_vias: tuple[CertifiedBusTransitionVia, ...] = ()
    terminal_sources: tuple[BusPhysicalSwapTerminalSourceBinding, ...]

    @model_validator(mode="after")
    def authority_is_complete_and_canonical(self) -> Self:
        plan = ReplayBoundBusPhysicalSwapPlan.model_validate_json(self.plan.model_dump_json())
        if plan != self.plan:
            raise ValueError("physical-swap plan changed during exact JSON reconstruction")
        if (
            plan.outcome.disposition is not BusPhysicalSwapPlanDisposition.BUILT
            or plan.outcome.plan is None
        ):
            raise ValueError("physical-swap composition requires a successful built plan")

        pigtails = tuple(sorted(self.pigtails, key=lambda item: (item.member_id, item.terminal_id)))
        if len({item.pigtail_id for item in pigtails}) != len(pigtails) or len(
            {(item.member_id, item.terminal_id) for item in pigtails}
        ) != len(pigtails):
            raise ValueError("composition pigtails must be unique by identity and terminal")
        transitions = tuple(
            sorted(
                self.transition_vias,
                key=lambda item: (
                    item.member_id,
                    item.section_id,
                    item.boundary_id,
                    item.window_id,
                ),
            )
        )
        if len({item.transition_via_id for item in transitions}) != len(transitions) or len(
            {_transition_key(item) for item in transitions}
        ) != len(transitions):
            raise ValueError("composition transition vias must be unique per allocation event")
        sources = tuple(
            sorted(self.terminal_sources, key=lambda item: (item.member_id, item.terminal_id))
        )
        if len({(item.member_id, item.terminal_id) for item in sources}) != len(sources):
            raise ValueError("composition terminal sources must be unique per member terminal")
        if len({item.physical_pad_source_id for item in sources}) != len(sources):
            raise ValueError("composition terminal sources must name unique physical pads")

        authority = plan.replay_input
        required_terminals = {
            (member.member_id, terminal.terminal_id)
            for member in authority.bus.members
            for terminal in member.terminals
        }
        actual_terminals = {(item.member_id, item.terminal_id) for item in sources}
        if actual_terminals != required_terminals:
            raise ValueError("terminal source bindings must exactly cover every bus terminal")
        if {(item.member_id, item.terminal_id) for item in pigtails} != required_terminals:
            raise ValueError("certified pigtails must exactly cover every bus terminal")
        object.__setattr__(self, "pigtails", pigtails)
        object.__setattr__(self, "transition_vias", transitions)
        object.__setattr__(self, "terminal_sources", sources)
        return self


class BusPhysicalSwapBoundaryEvidence(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-boundary-evidence"] = (
        "pcbsmith-bus-physical-swap-boundary-evidence"
    )
    schema_version: Literal[1] = 1
    member_id: str = Field(min_length=1)
    boundary_index: int = Field(ge=0)
    before_section_id: str = Field(min_length=1)
    after_section_id: str = Field(min_length=1)
    before_geometry_id: str = Field(min_length=1)
    after_geometry_id: str = Field(min_length=1)
    before_node: tuple[str, int, int]
    after_node: tuple[str, int, int]
    kind: BusPhysicalSwapBoundaryKind
    allocation_event_fingerprint: str | None = None
    carrier_fingerprint: str | None = None
    carrier_member_fingerprint: str | None = None

    @field_validator(
        "allocation_event_fingerprint",
        "carrier_fingerprint",
        "carrier_member_fingerprint",
    )
    @classmethod
    def optional_fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def classification_has_exact_evidence_shape(self) -> Self:
        fingerprints = (
            self.allocation_event_fingerprint,
            self.carrier_fingerprint,
            self.carrier_member_fingerprint,
        )
        if self.kind is BusPhysicalSwapBoundaryKind.DIRECT and any(fingerprints):
            raise ValueError("direct boundary cannot consume carrier evidence")
        if self.kind is BusPhysicalSwapBoundaryKind.SEMANTIC_TRANSITION and (
            fingerprints[0] is None or fingerprints[1] is None or fingerprints[2] is not None
        ):
            raise ValueError("semantic boundary requires event and via-carrier evidence")
        if self.kind is BusPhysicalSwapBoundaryKind.PHYSICAL_SWAP and any(
            item is None for item in fingerprints
        ):
            raise ValueError("physical boundary requires event, carrier, and member evidence")
        return self


class CertifiedPhysicalSwapBusMemberPrefix(RoutingIrModel):
    """Separate schema-v1 envelope for one physical-swap-aware member prefix."""

    schema_id: Literal["pcbsmith-certified-physical-swap-bus-member-prefix"] = (
        "pcbsmith-certified-physical-swap-bus-member-prefix"
    )
    schema_version: Literal[1] = 1
    replay_plan_fingerprint: str
    plan_input_fingerprint: str
    plan_fingerprint: str
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    active_geometry_ids: tuple[str, ...] = Field(min_length=1)
    boundary_evidence: tuple[BusPhysicalSwapBoundaryEvidence, ...]
    pigtail_fingerprints: tuple[str, ...] = Field(min_length=1)
    transition_event_fingerprints: tuple[str, ...] = ()
    transition_via_fingerprints: tuple[str, ...] = ()
    physical_event_fingerprints: tuple[str, ...] = ()
    physical_carrier_fingerprints: tuple[str, ...] = ()
    physical_member_fingerprints: tuple[str, ...] = ()
    terminal_sources: tuple[tuple[str, str], ...] = Field(min_length=1)
    prefix: GridRoutePrefix
    prefix_fingerprint: str
    composition_fingerprint: str

    @field_validator(
        "replay_plan_fingerprint",
        "plan_input_fingerprint",
        "plan_fingerprint",
        "prefix_fingerprint",
        "composition_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @field_validator(
        "pigtail_fingerprints",
        "transition_event_fingerprints",
        "transition_via_fingerprints",
        "physical_event_fingerprints",
        "physical_carrier_fingerprints",
        "physical_member_fingerprints",
    )
    @classmethod
    def fingerprint_sequences_are_exact(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple(_require_sha256(value, info.field_name) for value in values)

    @model_validator(mode="after")
    def envelope_is_self_consistent(self) -> Self:
        if self.prefix.net_name != self.net_name:
            raise ValueError("physical-swap prefix net ownership is stale")
        if self.prefix_fingerprint != self.prefix.semantic_fingerprint():
            raise ValueError("physical-swap inner prefix fingerprint is stale")
        if len(self.boundary_evidence) != max(0, len(self.active_geometry_ids) - 1):
            raise ValueError("boundary evidence must cover every adjacent active geometry")
        if tuple(item.boundary_index for item in self.boundary_evidence) != tuple(
            range(len(self.boundary_evidence))
        ):
            raise ValueError("boundary evidence order is incomplete or noncanonical")
        if len(self.transition_event_fingerprints) != len(self.transition_via_fingerprints):
            raise ValueError("semantic events and transition carriers must have exact coverage")
        physical_lengths = {
            len(self.physical_event_fingerprints),
            len(self.physical_carrier_fingerprints),
            len(self.physical_member_fingerprints),
        }
        if len(physical_lengths) != 1:
            raise ValueError("physical event, carrier, and member coverage must be exact")
        expected = _member_composition_fingerprint(self)
        if self.composition_fingerprint != expected:
            raise ValueError("physical-swap member composition fingerprint is stale")
        expected_id = f"physical-swap-member-prefix:{self.member_id}:{expected}"
        if self.prefix.alternative_id != expected_id:
            raise ValueError("physical-swap prefix alternative identity is stale")
        return self


class BusPhysicalSwapCompositionCoverage(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-composition-coverage"] = (
        "pcbsmith-bus-physical-swap-composition-coverage"
    )
    schema_version: Literal[1] = 1
    required_pigtails: tuple[str, ...]
    consumed_pigtails: tuple[str, ...]
    required_transition_vias: tuple[str, ...]
    consumed_transition_vias: tuple[str, ...]
    required_physical_memberships: tuple[str, ...]
    consumed_physical_memberships: tuple[str, ...]

    @model_validator(mode="after")
    def all_inputs_are_consumed_exactly_once(self) -> Self:
        if (
            self.required_pigtails != self.consumed_pigtails
            or self.required_transition_vias != self.consumed_transition_vias
            or self.required_physical_memberships != self.consumed_physical_memberships
        ):
            raise ValueError("composition input coverage is missing, duplicate, or unused")
        for values in (
            self.required_pigtails,
            self.required_transition_vias,
            self.required_physical_memberships,
        ):
            if len(set(values)) != len(values):
                raise ValueError("composition coverage identities must be unique")
        return self


class ReplayBoundPhysicalSwapBusPrefixComposition(RoutingIrModel):
    schema_id: Literal["pcbsmith-replay-bound-physical-swap-bus-prefix-composition"] = (
        "pcbsmith-replay-bound-physical-swap-bus-prefix-composition"
    )
    schema_version: Literal[1] = 1
    replay_input: BusPhysicalSwapCompositionInput
    members: tuple[CertifiedPhysicalSwapBusMemberPrefix, ...]
    coverage: BusPhysicalSwapCompositionCoverage
    result_fingerprint: str

    @field_validator("result_fingerprint")
    @classmethod
    def result_fingerprint_is_sha256(cls, value: str) -> str:
        return _require_sha256(value, "result_fingerprint")

    @model_validator(mode="after")
    def result_rederives_exactly(self) -> Self:
        replay_input = BusPhysicalSwapCompositionInput.model_validate_json(
            self.replay_input.model_dump_json()
        )
        members, coverage = _derive_composition(replay_input)
        if (
            replay_input != self.replay_input
            or members != self.members
            or coverage != self.coverage
        ):
            raise ValueError("physical-swap prefix composition does not rederive exactly")
        expected = _result_fingerprint(replay_input, members, coverage)
        if self.result_fingerprint != expected:
            raise ValueError("physical-swap composition result fingerprint is stale")
        return self


def compose_replay_bound_physical_swap_bus_prefixes(
    *,
    plan: ReplayBoundBusPhysicalSwapPlan,
    pigtails: tuple[CertifiedBusPigtail, ...],
    transition_vias: tuple[CertifiedBusTransitionVia, ...],
    terminal_sources: tuple[BusPhysicalSwapTerminalSourceBinding, ...],
) -> ReplayBoundPhysicalSwapBusPrefixComposition:
    """Compose all member prefixes from immutable, already-certified inputs."""

    replay_input = BusPhysicalSwapCompositionInput(
        plan=plan,
        pigtails=pigtails,
        transition_vias=transition_vias,
        terminal_sources=terminal_sources,
    )
    members, coverage = _derive_composition(replay_input)
    return ReplayBoundPhysicalSwapBusPrefixComposition(
        replay_input=replay_input,
        members=members,
        coverage=coverage,
        result_fingerprint=_result_fingerprint(replay_input, members, coverage),
    )


def _derive_composition(
    replay_input: BusPhysicalSwapCompositionInput,
) -> tuple[
    tuple[CertifiedPhysicalSwapBusMemberPrefix, ...],
    BusPhysicalSwapCompositionCoverage,
]:
    authority = replay_input.plan.replay_input
    accepted_plan = replay_input.plan.outcome.plan
    if accepted_plan is None:
        raise ValueError("physical-swap composition requires a retained successful plan")
    members_by_id = {item.member_id: item for item in authority.bus.members}
    pigtails_by_member: dict[str, list[CertifiedBusPigtail]] = {
        member_id: [] for member_id in members_by_id
    }
    for pigtail in replay_input.pigtails:
        if pigtail.member_id not in pigtails_by_member:
            raise ValueError("pigtail references a foreign bus member")
        pigtails_by_member[pigtail.member_id].append(pigtail)
    sources_by_member: dict[str, dict[str, str]] = {member_id: {} for member_id in members_by_id}
    for binding in replay_input.terminal_sources:
        sources_by_member[binding.member_id][binding.terminal_id] = binding.physical_pad_source_id
    transitions_by_member: dict[str, list[CertifiedBusTransitionVia]] = {
        member_id: [] for member_id in members_by_id
    }
    for carrier in replay_input.transition_vias:
        if carrier.member_id not in transitions_by_member:
            raise ValueError("transition via references a foreign bus member")
        transitions_by_member[carrier.member_id].append(carrier)

    physical_candidates: dict[
        tuple[str, str, str, tuple[int, int], tuple[int, int], str],
        tuple[str, str, BusSwapMemberCarrier],
    ] = {}
    required_physical: list[str] = []
    for physical_carrier in accepted_plan.carriers:
        event_fingerprint = physical_carrier.region.swap_event.semantic_fingerprint()
        portals = {item.member_id: item for item in physical_carrier.region.member_portals}
        for member_carrier in physical_carrier.members:
            portal = portals[member_carrier.member_id]
            membership = _physical_membership_identity(
                physical_carrier.carrier_fingerprint,
                member_carrier.member_id,
                member_carrier.semantic_fingerprint(),
            )
            required_physical.append(membership)
            key = (
                member_carrier.member_id,
                portal.incoming_geometry_id,
                portal.outgoing_geometry_id,
                portal.incoming_portal_point,
                portal.outgoing_portal_point,
                physical_carrier.region.swap_event.layer,
            )
            if key in physical_candidates:
                raise ValueError("physical carrier membership has ambiguous boundary authority")
            physical_candidates[key] = (
                event_fingerprint,
                physical_carrier.carrier_fingerprint,
                member_carrier,
            )

    derived_members: list[CertifiedPhysicalSwapBusMemberPrefix] = []
    consumed_physical: list[str] = []
    consumed_transitions: list[str] = []
    consumed_pigtails: list[str] = []
    for member in authority.bus.members:
        wrapper, member_physical, member_transitions, member_pigtails = _compose_member(
            replay_input,
            member,
            tuple(pigtails_by_member[member.member_id]),
            tuple(transitions_by_member[member.member_id]),
            sources_by_member[member.member_id],
            physical_candidates,
        )
        derived_members.append(wrapper)
        consumed_physical.extend(member_physical)
        consumed_transitions.extend(member_transitions)
        consumed_pigtails.extend(member_pigtails)

    coverage = BusPhysicalSwapCompositionCoverage(
        required_pigtails=tuple(
            sorted(item.semantic_fingerprint() for item in replay_input.pigtails)
        ),
        consumed_pigtails=tuple(sorted(consumed_pigtails)),
        required_transition_vias=tuple(
            sorted(item.semantic_fingerprint() for item in replay_input.transition_vias)
        ),
        consumed_transition_vias=tuple(sorted(consumed_transitions)),
        required_physical_memberships=tuple(sorted(required_physical)),
        consumed_physical_memberships=tuple(sorted(consumed_physical)),
    )
    return tuple(derived_members), coverage


def _compose_member(
    replay_input: BusPhysicalSwapCompositionInput,
    member: BusMember,
    pigtails: tuple[CertifiedBusPigtail, ...],
    transition_vias: tuple[CertifiedBusTransitionVia, ...],
    terminal_sources: dict[str, str],
    physical_candidates: dict[
        tuple[str, str, str, tuple[int, int], tuple[int, int], str],
        tuple[str, str, BusSwapMemberCarrier],
    ],
) -> tuple[CertifiedPhysicalSwapBusMemberPrefix, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    authority = replay_input.plan.replay_input
    accepted_plan = replay_input.plan.outcome.plan
    if accepted_plan is None:
        raise ValueError("physical-swap composition requires a retained successful plan")
    assignments, geometries = _member_geometries(replay_input, member)
    lane_segments = _geometry_segments(member, geometries, authority.certificate.grid_mm)
    physical_segments: list[TrackSegment] = []
    physical_vias: list[ViaSpec] = []
    semantic_vias: list[ViaSpec] = []
    evidence: list[BusPhysicalSwapBoundaryEvidence] = []
    consumed_physical: list[str] = []
    consumed_transition: list[str] = []
    transition_event_fps: list[str] = []
    transition_via_fps: list[str] = []
    physical_event_fps: list[str] = []
    physical_carrier_fps: list[str] = []
    physical_member_fps: list[str] = []
    transition_carriers = {_transition_key(item): item for item in transition_vias}

    for index, (before_assignment, after_assignment, before, after) in enumerate(
        zip(assignments[:-1], assignments[1:], geometries[:-1], geometries[1:], strict=True)
    ):
        before_node = (before.layer, *before.exit_portal_point)
        after_node = (after.layer, *after.entry_portal_point)
        event_fp: str | None = None
        carrier_fp: str | None = None
        member_fp: str | None = None
        if before.exit_portal_point == after.entry_portal_point:
            if before.layer == after.layer:
                kind = BusPhysicalSwapBoundaryKind.DIRECT
            else:
                kind = BusPhysicalSwapBoundaryKind.SEMANTIC_TRANSITION
                event = _exact_transition_event(
                    replay_input, member, before_assignment, before, after
                )
                event_fp = event.semantic_fingerprint()
                transition = transition_carriers.get(_transition_key(event))
                if transition is None:
                    raise ValueError("semantic layer change lacks its exact transition carrier")
                _validate_transition_carrier(replay_input, member, event, before, after, transition)
                carrier_fp = transition.semantic_fingerprint()
                consumed_transition.append(carrier_fp)
                transition_event_fps.append(event_fp)
                transition_via_fps.append(carrier_fp)
                semantic_vias.append(
                    ViaSpec(
                        x=transition.point[0] * authority.certificate.grid_mm,
                        y=transition.point[1] * authority.certificate.grid_mm,
                        net_name=member.net_name,
                        size_mm=authority.rule_profile.geometry.routing_via_diameter_mm,
                        drill_mm=authority.rule_profile.geometry.routing_via_drill_mm,
                    )
                )
        else:
            if before.layer != after.layer:
                raise ValueError(
                    "schema-v1 composition does not support changed-point changed-layer boundaries"
                )
            kind = BusPhysicalSwapBoundaryKind.PHYSICAL_SWAP
            key = (
                member.member_id,
                before.centerline_geometry_id,
                after.centerline_geometry_id,
                before.exit_portal_point,
                after.entry_portal_point,
                before.layer,
            )
            matches = tuple(
                value for candidate, value in physical_candidates.items() if candidate == key
            )
            if len(matches) != 1:
                raise ValueError(
                    "changed-point boundary requires exactly one physical carrier member"
                )
            event_fp, carrier_fp, carrier_member = matches[0]
            member_fp = carrier_member.semantic_fingerprint()
            physical_segments.extend(carrier_member.segments)
            physical_vias.extend(carrier_member.vias)
            membership = _physical_membership_identity(carrier_fp, member.member_id, member_fp)
            consumed_physical.append(membership)
            physical_event_fps.append(event_fp)
            physical_carrier_fps.append(carrier_fp)
            physical_member_fps.append(member_fp)
        evidence.append(
            BusPhysicalSwapBoundaryEvidence(
                member_id=member.member_id,
                boundary_index=index,
                before_section_id=before_assignment.section_id,
                after_section_id=after_assignment.section_id,
                before_geometry_id=before.centerline_geometry_id,
                after_geometry_id=after.centerline_geometry_id,
                before_node=before_node,
                after_node=after_node,
                kind=kind,
                allocation_event_fingerprint=event_fp,
                carrier_fingerprint=carrier_fp,
                carrier_member_fingerprint=member_fp,
            )
        )

    if set(transition_carriers) != {
        _transition_key(item)
        for item in authority.allocation.layer_transitions
        if item.member_id == member.member_id
    }:
        raise ValueError("transition carriers must exactly cover member allocation events")
    pigtail_segments, anchors, pigtail_fps = _validated_pigtails(
        replay_input, member, geometries, pigtails, terminal_sources
    )
    segments = (*lane_segments, *physical_segments, *pigtail_segments)
    vias = (*physical_vias, *semantic_vias)
    provisional = GridRoutePrefix(
        alternative_id=f"physical-swap-member-prefix:{member.member_id}:pending",
        net_name=member.net_name,
        grid_mm=authority.certificate.grid_mm,
        exit_node=min(node for _source, node in anchors),
        covered_pad_anchors=anchors,
        segments=segments,
        vias=vias,
    )
    values: dict[str, Any] = {
        "replay_plan_fingerprint": replay_input.plan.semantic_fingerprint(),
        "plan_input_fingerprint": authority.semantic_fingerprint(),
        "plan_fingerprint": accepted_plan.plan_fingerprint,
        "member_id": member.member_id,
        "net_name": member.net_name,
        "active_geometry_ids": tuple(item.centerline_geometry_id for item in geometries),
        "boundary_evidence": tuple(evidence),
        "pigtail_fingerprints": tuple(sorted(pigtail_fps)),
        "transition_event_fingerprints": tuple(transition_event_fps),
        "transition_via_fingerprints": tuple(transition_via_fps),
        "physical_event_fingerprints": tuple(physical_event_fps),
        "physical_carrier_fingerprints": tuple(physical_carrier_fps),
        "physical_member_fingerprints": tuple(physical_member_fps),
        "terminal_sources": tuple(sorted(terminal_sources.items())),
        "prefix": provisional,
        "prefix_fingerprint": provisional.semantic_fingerprint(),
    }
    pending = CertifiedPhysicalSwapBusMemberPrefix.model_construct(
        **values, composition_fingerprint="0" * 64
    )
    composition_fingerprint = _member_composition_fingerprint(pending)
    prefix = GridRoutePrefix(
        alternative_id=(
            f"physical-swap-member-prefix:{member.member_id}:{composition_fingerprint}"
        ),
        net_name=provisional.net_name,
        grid_mm=provisional.grid_mm,
        exit_node=provisional.exit_node,
        covered_pad_anchors=provisional.covered_pad_anchors,
        segments=provisional.segments,
        vias=provisional.vias,
    )
    values["prefix"] = prefix
    values["prefix_fingerprint"] = prefix.semantic_fingerprint()
    values["composition_fingerprint"] = composition_fingerprint
    wrapper = CertifiedPhysicalSwapBusMemberPrefix.model_validate(values)
    return wrapper, tuple(consumed_physical), tuple(consumed_transition), pigtail_fps


def _member_geometries(
    replay_input: BusPhysicalSwapCompositionInput, member: BusMember
) -> tuple[tuple[BusLaneAssignment, ...], tuple[CertifiedLaneGeometry, ...]]:
    authority = replay_input.plan.replay_input
    section_positions = {
        item.section_id: index for index, item in enumerate(authority.certificate.sections)
    }
    assignments = tuple(
        sorted(
            (
                item
                for item in authority.allocation.assignments
                if item.member_id == member.member_id
            ),
            key=lambda item: section_positions[item.section_id],
        )
    )
    if len(assignments) != len(authority.certificate.sections):
        raise ValueError("member assignments must exactly cover certificate sections")
    slots = {
        (section.section_id, slot.slot_id): slot
        for section in authority.certificate.sections
        for slot in section.lane_slots
    }
    geometry_by_id = {
        item.centerline_geometry_id: item for item in authority.lane_geometry_registry.geometries
    }
    geometries: list[CertifiedLaneGeometry] = []
    for assignment in assignments:
        slot = slots.get((assignment.section_id, assignment.slot_id))
        if slot is None:
            raise ValueError("member assignment references an unknown certified slot")
        geometry = geometry_by_id.get(slot.centerline_geometry_id)
        if (
            geometry is None
            or assignment.net_name != member.net_name
            or assignment.layer != slot.layer
            or assignment.layer != geometry.layer
            or geometry.section_id != assignment.section_id
            or geometry.track_width_mm != member.width_mm
        ):
            raise ValueError("member assignment, net, or certified geometry is stale")
        geometries.append(geometry)
    return assignments, tuple(geometries)


def _exact_transition_event(
    replay_input: BusPhysicalSwapCompositionInput,
    member: BusMember,
    before_assignment: BusLaneAssignment,
    before: CertifiedLaneGeometry,
    after: CertifiedLaneGeometry,
) -> BusLayerTransitionEvent:
    authority = replay_input.plan.replay_input
    matches = tuple(
        item
        for item in authority.allocation.layer_transitions
        if item.member_id == member.member_id
        and item.section_id == before_assignment.section_id
        and item.from_layer == before.layer
        and item.to_layer == after.layer
    )
    if len(matches) != 1:
        raise ValueError("layer change requires exactly one allocation transition event")
    event = matches[0]
    section = next(
        item
        for item in authority.certificate.sections
        if item.section_id == before_assignment.section_id
    )
    boundary = next(
        (item for item in authority.bus.boundaries if item.boundary_id == event.boundary_id),
        None,
    )
    if (
        event.window_id not in section.transition_window_ids
        or boundary is None
        or boundary.corridor_portal_id != before.exit_portal_id
        or before.exit_portal_id != after.entry_portal_id
    ):
        raise ValueError("allocation transition event is stale at its certified boundary")
    return event


def _validate_transition_carrier(
    replay_input: BusPhysicalSwapCompositionInput,
    member: BusMember,
    event: BusLayerTransitionEvent,
    before: CertifiedLaneGeometry,
    after: CertifiedLaneGeometry,
    carrier: CertifiedBusTransitionVia,
) -> None:
    authority = replay_input.plan.replay_input
    expected_root = (
        authority.bus.semantic_fingerprint(),
        authority.certificate.semantic_fingerprint(),
        authority.allocation.allocation_fingerprint,
        authority.lane_geometry_registry.semantic_fingerprint(),
    )
    actual_root = (
        carrier.bus_fingerprint,
        carrier.certificate_fingerprint,
        carrier.allocation_fingerprint,
        carrier.geometry_registry_fingerprint,
    )
    if expected_root != actual_root:
        raise ValueError("transition carrier root authority is stale")
    if (
        carrier.member_id != member.member_id
        or carrier.net_name != member.net_name
        or _transition_key(carrier) != _transition_key(event)
        or carrier.before_geometry_id != before.centerline_geometry_id
        or carrier.after_geometry_id != after.centerline_geometry_id
        or carrier.point != before.exit_portal_point
        or carrier.point != after.entry_portal_point
        or carrier.grid_mm != authority.certificate.grid_mm
    ):
        raise ValueError("transition carrier owner, geometry, or endpoint is stale")


def _validated_pigtails(
    replay_input: BusPhysicalSwapCompositionInput,
    member: BusMember,
    geometries: tuple[CertifiedLaneGeometry, ...],
    pigtails: tuple[CertifiedBusPigtail, ...],
    terminal_sources: dict[str, str],
) -> tuple[
    tuple[TrackSegment, ...],
    tuple[tuple[str, tuple[str, int, int]], ...],
    tuple[str, ...],
]:
    authority = replay_input.plan.replay_input
    terminal_ids = {item.terminal_id for item in member.terminals}
    if set(terminal_sources) != terminal_ids:
        raise ValueError("member terminal source bindings are incomplete")
    by_terminal = {item.terminal_id: item for item in pigtails}
    if set(by_terminal) != terminal_ids or len(by_terminal) != len(pigtails):
        raise ValueError("member pigtails must exactly and uniquely cover terminals")
    expected_root = (
        authority.bus.semantic_fingerprint(),
        authority.certificate.semantic_fingerprint(),
        authority.allocation.allocation_fingerprint,
        authority.lane_geometry_registry.semantic_fingerprint(),
    )
    boundary_by_terminal: dict[str, BusBoundary] = {}
    for boundary in authority.bus.boundaries:
        member_ref = next(
            (item for item in boundary.ordered_members if item.member_id == member.member_id),
            None,
        )
        if member_ref is not None:
            for terminal_id in member_ref.terminal_ids:
                if terminal_id in boundary_by_terminal:
                    raise ValueError("member terminal is declared at multiple bus boundaries")
                boundary_by_terminal[terminal_id] = boundary
    segments: list[TrackSegment] = []
    anchors: list[tuple[str, tuple[str, int, int]]] = []
    fingerprints: list[str] = []
    for terminal_id in sorted(terminal_ids):
        carrier = by_terminal[terminal_id]
        terminal_boundary = boundary_by_terminal.get(terminal_id)
        actual_root = (
            carrier.bus_fingerprint,
            carrier.certificate_fingerprint,
            carrier.allocation_fingerprint,
            carrier.geometry_registry_fingerprint,
        )
        portal_candidates = tuple(
            (geometry, kind, point)
            for geometry in geometries
            for kind, portal_id, point in (
                ("entry", geometry.entry_portal_id, geometry.entry_portal_point),
                ("exit", geometry.exit_portal_id, geometry.exit_portal_point),
            )
            if terminal_boundary is not None and portal_id == terminal_boundary.corridor_portal_id
        )
        if len(portal_candidates) != 1:
            raise ValueError("terminal boundary must name exactly one active geometry portal")
        geometry, portal_kind, portal_point = portal_candidates[0]
        if (
            actual_root != expected_root
            or carrier.member_id != member.member_id
            or carrier.net_name != member.net_name
            or terminal_boundary is None
            or carrier.boundary_id != terminal_boundary.boundary_id
            or carrier.assigned_geometry_id != geometry.centerline_geometry_id
            or carrier.portal_kind != portal_kind
            or carrier.portal_point != portal_point
            or carrier.layer != geometry.layer
            or carrier.grid_mm != authority.certificate.grid_mm
            or carrier.physical_pad_source_id != terminal_sources[terminal_id]
        ):
            raise ValueError("pigtail owner, terminal source, geometry, or endpoint is stale")
        segments.extend(
            TrackSegment(
                start[0] * carrier.grid_mm,
                start[1] * carrier.grid_mm,
                end[0] * carrier.grid_mm,
                end[1] * carrier.grid_mm,
                carrier.layer,
                member.net_name,
                member.width_mm,
            )
            for start, end in zip(carrier.points, carrier.points[1:], strict=False)
        )
        anchors.append(
            (
                carrier.physical_pad_source_id,
                (carrier.layer, *carrier.pad_anchor_point),
            )
        )
        fingerprints.append(carrier.semantic_fingerprint())
    return tuple(segments), tuple(anchors), tuple(fingerprints)


def _geometry_segments(
    member: BusMember,
    geometries: tuple[CertifiedLaneGeometry, ...],
    grid_mm: float,
) -> tuple[TrackSegment, ...]:
    return tuple(
        TrackSegment(
            start[0] * grid_mm,
            start[1] * grid_mm,
            end[0] * grid_mm,
            end[1] * grid_mm,
            geometry.layer,
            member.net_name,
            member.width_mm,
        )
        for geometry in geometries
        for start, end in zip(geometry.points, geometry.points[1:], strict=False)
    )


def _transition_key(
    item: BusLayerTransitionEvent | CertifiedBusTransitionVia,
) -> tuple[str, str, str, str, str, str]:
    return (
        item.member_id,
        item.section_id,
        item.boundary_id,
        item.window_id,
        item.from_layer,
        item.to_layer,
    )


def _physical_membership_identity(
    carrier_fingerprint: str, member_id: str, member_fingerprint: str
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-physical-swap-carrier-membership",
            "schema_version": 1,
            "carrier_fingerprint": carrier_fingerprint,
            "member_id": member_id,
            "member_fingerprint": member_fingerprint,
        }
    )


def _member_composition_fingerprint(
    member: CertifiedPhysicalSwapBusMemberPrefix,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-certified-physical-swap-member-prefix-composition",
            "schema_version": 1,
            "replay_plan_fingerprint": member.replay_plan_fingerprint,
            "plan_input_fingerprint": member.plan_input_fingerprint,
            "plan_fingerprint": member.plan_fingerprint,
            "member_id": member.member_id,
            "net_name": member.net_name,
            "active_geometry_ids": member.active_geometry_ids,
            "boundary_evidence": [
                item.model_dump(mode="json") for item in member.boundary_evidence
            ],
            "pigtail_fingerprints": member.pigtail_fingerprints,
            "transition_event_fingerprints": member.transition_event_fingerprints,
            "transition_via_fingerprints": member.transition_via_fingerprints,
            "physical_event_fingerprints": member.physical_event_fingerprints,
            "physical_carrier_fingerprints": member.physical_carrier_fingerprints,
            "physical_member_fingerprints": member.physical_member_fingerprints,
            "terminal_sources": member.terminal_sources,
            "prefix": _prefix_payload(member.prefix),
        }
    )


def _result_fingerprint(
    replay_input: BusPhysicalSwapCompositionInput,
    members: tuple[CertifiedPhysicalSwapBusMemberPrefix, ...],
    coverage: BusPhysicalSwapCompositionCoverage,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-replay-bound-physical-swap-prefix-composition-result",
            "schema_version": 1,
            "input_fingerprint": replay_input.semantic_fingerprint(),
            "member_composition_fingerprints": tuple(
                item.composition_fingerprint for item in members
            ),
            "coverage": coverage.model_dump(mode="json"),
        }
    )
