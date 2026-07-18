"""Certified ordered-bus pigtail and transition-prefix composition.

R4.2c1 is deliberately pure: it validates caller-supplied exact pigtail copper
and declared transition vias, then composes one complete ``GridRoutePrefix``.
It performs no search, occupancy mutation, board materialization, or exact DRC.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeAlias

from pydantic import Field, StrictInt, field_validator, model_validator

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    BusLaneAssignment,
    BusLayerTransitionEvent,
)
from pcbsmith.bus_geometry import (
    CertifiedBusTrunkRealization,
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
    RealizedCertifiedTrunk,
)
from pcbsmith.bus_ir import BusGroup, BusLayer, BusMember, CorridorCapacityCertificate
from pcbsmith.kicad.board import TrackSegment, ViaSpec
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.routing_ir import RoutingIrModel
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

LatticePoint: TypeAlias = tuple[StrictInt, StrictInt]
PortalKind = Literal["entry", "exit"]
BusPrefixAuthorityKind = Literal["same_layer_trunk", "transition_fragments"]


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


def _require_identity(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a canonical non-empty identity")
    return value


def _canonical_identity_tuple(
    values: Sequence[str],
    field_name: str,
    *,
    preserve_order: bool,
) -> tuple[str, ...]:
    canonical = tuple(values) if preserve_order else tuple(sorted(values))
    if not canonical:
        raise ValueError(f"{field_name} must be non-empty")
    if len(set(canonical)) != len(canonical):
        raise ValueError(f"{field_name} must contain unique identities")
    for value in canonical:
        _require_identity(value, field_name)
    return canonical


def _canonical_fingerprint_tuple(
    values: Sequence[str],
    field_name: str,
) -> tuple[str, ...]:
    canonical = tuple(sorted(values))
    if len(set(canonical)) != len(canonical):
        raise ValueError(f"{field_name} must contain unique fingerprints")
    return tuple(_require_sha256(value, field_name) for value in canonical)


def _prefix_copper_payload(prefix: GridRoutePrefix) -> dict[str, Any]:
    return {
        "net_name": prefix.net_name,
        "grid_mm": prefix.grid_mm,
        "exit_node": prefix.exit_node,
        "covered_pad_anchors": prefix.covered_pad_anchors,
        "segments": [
            {
                "start_mm": (segment.x1, segment.y1),
                "end_mm": (segment.x2, segment.y2),
                "layer": segment.layer,
                "net_name": segment.net_name,
                "width_mm": segment.width_mm,
            }
            for segment in prefix.segments
        ],
        "vias": [
            {
                "at_mm": (via.x, via.y),
                "net_name": via.net_name,
                "size_mm": via.size_mm,
                "drill_mm": via.drill_mm,
                "front_mask": via.front_mask.value,
                "back_mask": via.back_mask.value,
            }
            for via in prefix.vias
        ],
    }


def _certified_prefix_composition_fingerprint(
    *,
    bus_fingerprint: str,
    certificate_fingerprint: str,
    allocation_fingerprint: str,
    geometry_registry_fingerprint: str,
    member_id: str,
    net_name: str,
    active_geometry_ids: Sequence[str],
    authority_kind: BusPrefixAuthorityKind,
    authority_geometry_fingerprint: str,
    authority_claims_fingerprint: str | None,
    pigtail_fingerprints: Sequence[str],
    transition_via_fingerprints: Sequence[str],
    terminal_pad_sources: Sequence[tuple[str, str]],
    prefix: GridRoutePrefix,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-certified-bus-member-prefix-composition",
            "schema_version": 1,
            "bus_fingerprint": bus_fingerprint,
            "certificate_fingerprint": certificate_fingerprint,
            "allocation_fingerprint": allocation_fingerprint,
            "geometry_registry_fingerprint": geometry_registry_fingerprint,
            "member_id": member_id,
            "net_name": net_name,
            "active_geometry_ids": tuple(active_geometry_ids),
            "authority_kind": authority_kind,
            "authority_geometry_fingerprint": authority_geometry_fingerprint,
            "authority_claims_fingerprint": authority_claims_fingerprint,
            "pigtail_fingerprints": tuple(pigtail_fingerprints),
            "transition_via_fingerprints": tuple(transition_via_fingerprints),
            "terminal_pad_sources": tuple(terminal_pad_sources),
            "prefix": _prefix_copper_payload(prefix),
        }
    )


class CertifiedBusPigtail(RoutingIrModel):
    """One exact same-layer physical-pad-to-assigned-portal pigtail."""

    schema_id: Literal["pcbsmith-certified-bus-pigtail"] = "pcbsmith-certified-bus-pigtail"
    schema_version: Literal[1] = 1
    pigtail_id: str = Field(min_length=1)
    bus_fingerprint: str
    certificate_fingerprint: str
    allocation_fingerprint: str
    geometry_registry_fingerprint: str
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    terminal_id: str = Field(min_length=1)
    boundary_id: str = Field(min_length=1)
    assigned_geometry_id: str = Field(min_length=1)
    portal_kind: PortalKind
    physical_pad_source_id: str = Field(min_length=1)
    grid_mm: float = Field(gt=0)
    layer: BusLayer
    pad_anchor_point: LatticePoint
    portal_point: LatticePoint
    points: tuple[LatticePoint, ...] = Field(min_length=2)

    @field_validator(
        "bus_fingerprint",
        "certificate_fingerprint",
        "allocation_fingerprint",
        "geometry_registry_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def path_is_exact_and_connected(self) -> CertifiedBusPigtail:
        if not math.isfinite(self.grid_mm):
            raise ValueError("pigtail grid_mm must be finite and positive")
        for field_name in (
            "pigtail_id",
            "member_id",
            "net_name",
            "terminal_id",
            "boundary_id",
            "assigned_geometry_id",
            "physical_pad_source_id",
        ):
            _require_identity(getattr(self, field_name), field_name)
        if self.points[0] != self.pad_anchor_point:
            raise ValueError("pigtail must start at its physical pad anchor")
        if self.points[-1] != self.portal_point:
            raise ValueError("pigtail must end at its assigned portal point")
        if any(coordinate < 0 for point in self.points for coordinate in point):
            raise ValueError("pigtail lattice points must be non-negative")
        if len(set(self.points)) != len(self.points):
            raise ValueError("pigtail lattice points must be unique")
        previous_direction: tuple[int, int] | None = None
        for start, end in zip(self.points, self.points[1:], strict=False):
            direction = _segment_direction(start, end)
            if direction == previous_direction:
                raise ValueError("pigtail cannot contain redundant collinear vertices")
            previous_direction = direction
        return self


class CertifiedBusTransitionVia(RoutingIrModel):
    """One exact via-site declaration bound to one allocation transition event."""

    schema_id: Literal["pcbsmith-certified-bus-transition-via"] = (
        "pcbsmith-certified-bus-transition-via"
    )
    schema_version: Literal[1] = 1
    transition_via_id: str = Field(min_length=1)
    bus_fingerprint: str
    certificate_fingerprint: str
    allocation_fingerprint: str
    geometry_registry_fingerprint: str
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    boundary_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    from_layer: BusLayer
    to_layer: BusLayer
    before_geometry_id: str = Field(min_length=1)
    after_geometry_id: str = Field(min_length=1)
    grid_mm: float = Field(gt=0)
    point: LatticePoint

    @field_validator(
        "bus_fingerprint",
        "certificate_fingerprint",
        "allocation_fingerprint",
        "geometry_registry_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def declaration_is_exact(self) -> CertifiedBusTransitionVia:
        if not math.isfinite(self.grid_mm):
            raise ValueError("transition-via grid_mm must be finite and positive")
        if self.from_layer == self.to_layer:
            raise ValueError("transition via requires distinct layers")
        if any(coordinate < 0 for coordinate in self.point):
            raise ValueError("transition via point must be a non-negative lattice cell")
        for field_name in (
            "transition_via_id",
            "member_id",
            "net_name",
            "section_id",
            "boundary_id",
            "window_id",
            "before_geometry_id",
            "after_geometry_id",
        ):
            _require_identity(getattr(self, field_name), field_name)
        return self


class CertifiedBusMemberPrefix(RoutingIrModel):
    """Self-validating authority envelope for one complete member prefix."""

    schema_id: Literal["pcbsmith-certified-bus-member-prefix"] = (
        "pcbsmith-certified-bus-member-prefix"
    )
    schema_version: Literal[1] = 1
    bus_fingerprint: str
    certificate_fingerprint: str
    allocation_fingerprint: str
    geometry_registry_fingerprint: str
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    active_geometry_ids: tuple[str, ...] = Field(min_length=1)
    authority_kind: BusPrefixAuthorityKind
    authority_geometry_fingerprint: str
    authority_claims_fingerprint: str | None = None
    pigtail_fingerprints: tuple[str, ...] = Field(min_length=1)
    transition_via_fingerprints: tuple[str, ...] = ()
    terminal_pad_sources: tuple[tuple[str, str], ...] = Field(min_length=1)
    prefix: GridRoutePrefix
    prefix_fingerprint: str
    composition_fingerprint: str

    @field_validator(
        "bus_fingerprint",
        "certificate_fingerprint",
        "allocation_fingerprint",
        "geometry_registry_fingerprint",
        "authority_geometry_fingerprint",
        "authority_claims_fingerprint",
        "prefix_fingerprint",
        "composition_fingerprint",
    )
    @classmethod
    def wrapper_fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def binding_is_canonical_and_self_consistent(self) -> CertifiedBusMemberPrefix:
        _require_identity(self.member_id, "member_id")
        _require_identity(self.net_name, "net_name")
        active_geometry_ids = _canonical_identity_tuple(
            self.active_geometry_ids,
            "active_geometry_ids",
            preserve_order=True,
        )
        pigtail_fingerprints = _canonical_fingerprint_tuple(
            self.pigtail_fingerprints,
            "pigtail_fingerprints",
        )
        transition_via_fingerprints = _canonical_fingerprint_tuple(
            self.transition_via_fingerprints,
            "transition_via_fingerprints",
        )
        terminal_pad_sources = tuple(sorted(self.terminal_pad_sources))
        if len({terminal_id for terminal_id, _source_id in terminal_pad_sources}) != len(
            terminal_pad_sources
        ):
            raise ValueError("terminal pad-source bindings must be unique per terminal")
        if len({source_id for _terminal_id, source_id in terminal_pad_sources}) != len(
            terminal_pad_sources
        ):
            raise ValueError("terminal pad-source bindings must use unique physical sources")
        for terminal_id, source_id in terminal_pad_sources:
            _require_identity(terminal_id, "terminal pad-source terminal_id")
            _require_identity(source_id, "terminal pad-source source_id")
        if len(pigtail_fingerprints) != len(terminal_pad_sources):
            raise ValueError("one certified pigtail must bind every terminal pad source")
        covered_source_ids = {source_id for source_id, _node in self.prefix.covered_pad_anchors}
        if covered_source_ids != {source_id for _terminal_id, source_id in terminal_pad_sources}:
            raise ValueError("terminal pad sources must equal the inner covered pad anchors")
        if len(self.prefix.vias) != len(transition_via_fingerprints):
            raise ValueError("inner transition vias must equal their certified carriers")
        if self.authority_kind == "same_layer_trunk":
            if self.authority_claims_fingerprint is None:
                raise ValueError("same-layer trunk authority requires its claims fingerprint")
            if transition_via_fingerprints:
                raise ValueError("same-layer trunk authority cannot contain transition vias")
        else:
            if self.authority_claims_fingerprint is not None:
                raise ValueError("transition-fragment authority has no complete trunk claims")
            if not transition_via_fingerprints:
                raise ValueError("transition-fragment authority requires transition via carriers")
        if self.prefix.net_name != self.net_name:
            raise ValueError("certified member prefix net does not match its inner prefix")

        object.__setattr__(self, "active_geometry_ids", active_geometry_ids)
        object.__setattr__(self, "pigtail_fingerprints", pigtail_fingerprints)
        object.__setattr__(
            self,
            "transition_via_fingerprints",
            transition_via_fingerprints,
        )
        object.__setattr__(self, "terminal_pad_sources", terminal_pad_sources)
        expected_composition = _certified_prefix_composition_fingerprint(
            bus_fingerprint=self.bus_fingerprint,
            certificate_fingerprint=self.certificate_fingerprint,
            allocation_fingerprint=self.allocation_fingerprint,
            geometry_registry_fingerprint=self.geometry_registry_fingerprint,
            member_id=self.member_id,
            net_name=self.net_name,
            active_geometry_ids=active_geometry_ids,
            authority_kind=self.authority_kind,
            authority_geometry_fingerprint=self.authority_geometry_fingerprint,
            authority_claims_fingerprint=self.authority_claims_fingerprint,
            pigtail_fingerprints=pigtail_fingerprints,
            transition_via_fingerprints=transition_via_fingerprints,
            terminal_pad_sources=terminal_pad_sources,
            prefix=self.prefix,
        )
        if self.composition_fingerprint != expected_composition:
            raise ValueError("certified member prefix composition fingerprint is invalid")
        expected_alternative_id = f"bus-member-prefix:{self.member_id}:{expected_composition}"
        if self.prefix.alternative_id != expected_alternative_id:
            raise ValueError("inner prefix alternative identity does not match its composition")
        if self.prefix_fingerprint != self.prefix.semantic_fingerprint():
            raise ValueError("inner prefix semantic fingerprint is invalid")
        return self

    def require_authority(
        self,
        bus: BusGroup,
        certificate: CorridorCapacityCertificate,
        allocation: BusLaneAllocationResult,
        registry: CertifiedLaneGeometryRegistry,
    ) -> None:
        """Require exact live R4 authorities and assigned geometry identities."""

        expected = (
            bus.semantic_fingerprint(),
            certificate.semantic_fingerprint(),
            allocation.allocation_fingerprint,
            registry.semantic_fingerprint(),
        )
        actual = (
            self.bus_fingerprint,
            self.certificate_fingerprint,
            self.allocation_fingerprint,
            self.geometry_registry_fingerprint,
        )
        if actual != expected:
            raise ValueError("certified member prefix authority binding is stale")
        if allocation.bus_fingerprint != expected[0]:
            raise ValueError("lane allocation bus fingerprint is stale")
        if allocation.certificate_fingerprint != expected[1]:
            raise ValueError("lane allocation certificate fingerprint is stale")
        if registry.certificate_fingerprint != expected[1]:
            raise ValueError("lane geometry registry certificate fingerprint is stale")
        if registry.allocation_fingerprint != allocation.allocation_fingerprint:
            raise ValueError("lane geometry registry allocation fingerprint is stale")
        member = next((item for item in bus.members if item.member_id == self.member_id), None)
        if member is None or member.net_name != self.net_name:
            raise ValueError("certified member prefix references a foreign member or net")
        terminal_ids = {terminal.terminal_id for terminal in member.terminals}
        if terminal_ids != {terminal_id for terminal_id, _source_id in self.terminal_pad_sources}:
            raise ValueError("certified member prefix terminal binding is stale")
        if self.prefix.grid_mm != certificate.grid_mm:
            raise ValueError("certified member prefix grid does not match its certificate")
        member_transitions = tuple(
            item for item in allocation.layer_transitions if item.member_id == self.member_id
        )
        expected_authority_kind: BusPrefixAuthorityKind = (
            "transition_fragments" if member_transitions else "same_layer_trunk"
        )
        if self.authority_kind != expected_authority_kind:
            raise ValueError("certified member prefix authority kind is stale")
        if len(self.transition_via_fingerprints) != len(member_transitions):
            raise ValueError("certified member prefix transition binding is stale")
        slot_by_key = {
            (section.section_id, slot.slot_id): slot
            for section in certificate.sections
            for slot in section.lane_slots
        }
        assignments = tuple(
            sorted(
                (item for item in allocation.assignments if item.member_id == self.member_id),
                key=lambda item: _section_index(certificate, item.section_id),
            )
        )
        try:
            expected_geometry_ids = tuple(
                slot_by_key[(item.section_id, item.slot_id)].centerline_geometry_id
                for item in assignments
            )
        except KeyError as error:
            raise ValueError(
                "lane assignment references an unknown certificate section or slot"
            ) from error
        if expected_geometry_ids != self.active_geometry_ids:
            raise ValueError("certified member prefix active geometry binding is stale")
        registry_geometry_ids = {
            geometry.centerline_geometry_id for geometry in registry.geometries
        }
        if not set(expected_geometry_ids).issubset(registry_geometry_ids):
            raise ValueError("certified member prefix geometry is absent from the registry")


def compose_member_route_prefix(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    geometry_registry: CertifiedLaneGeometryRegistry,
    same_layer_trunk_realization: CertifiedBusTrunkRealization | None,
    member_id: str,
    pigtails: Sequence[CertifiedBusPigtail],
    transition_vias: Sequence[CertifiedBusTransitionVia],
    physical_pad_sources_by_terminal: Mapping[str, str],
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> CertifiedBusMemberPrefix:
    """Compose and self-bind one complete, connected member prefix."""

    member_id = _require_identity(member_id, "member_id")
    member_by_id = {member.member_id: member for member in bus.members}
    member = member_by_id.get(member_id)
    if member is None:
        raise ValueError("prefix member is not declared by the bus")
    corridor_transitions_forbidden = bus.layer_policy.via_policy.mode in {
        "forbidden",
        "escape_only",
    }
    has_member_transition_event = any(
        event.member_id == member_id for event in allocation.layer_transitions
    )
    if corridor_transitions_forbidden and (
        has_member_transition_event or transition_vias
    ):
        raise ValueError(
            "bus via policy forbids corridor transition events and carriers"
        )
    _validate_root_bindings(
        bus,
        certificate,
        allocation,
        geometry_registry,
        profile,
    )
    terminal_by_id = {terminal.terminal_id: terminal for terminal in member.terminals}
    source_map = dict(physical_pad_sources_by_terminal)
    if set(source_map) != set(terminal_by_id):
        raise ValueError("physical pad source map must exactly cover member terminals")
    if any(not source_id or source_id != source_id.strip() for source_id in source_map.values()):
        raise ValueError("physical pad source identities must be canonical and non-empty")
    if len(set(source_map.values())) != len(source_map):
        raise ValueError("physical pad source identities must be unique per member")

    active_assignments, active_geometries = _active_member_geometry(
        certificate,
        allocation,
        geometry_registry,
        member,
        profile,
    )
    active_geometry_ids = tuple(geometry.centerline_geometry_id for geometry in active_geometries)
    geometry_by_id = {
        geometry.centerline_geometry_id: geometry for geometry in geometry_registry.geometries
    }
    expected_transition_events = tuple(
        event for event in allocation.layer_transitions if event.member_id == member_id
    )
    _validate_transition_topology(
        bus,
        certificate,
        active_assignments,
        active_geometries,
        expected_transition_events,
    )
    if expected_transition_events:
        if same_layer_trunk_realization is not None:
            raise ValueError(
                "transition-bearing member must use certified section fragments, not a "
                "complete trunk realization"
            )
        trunk_segments = _certified_fragment_segments(
            member,
            active_geometries,
            certificate.grid_mm,
        )
        authority_kind: BusPrefixAuthorityKind = "transition_fragments"
        authority_geometry_fingerprint = _fragment_geometry_fingerprint(
            member,
            active_geometries,
            trunk_segments,
        )
        authority_claims_fingerprint = None
    else:
        if same_layer_trunk_realization is None:
            raise ValueError("same-layer member requires a certified complete trunk realization")
        _validate_realization_bindings(
            bus,
            certificate,
            allocation,
            geometry_registry,
            same_layer_trunk_realization,
            profile,
        )
        trunk = _member_trunk(same_layer_trunk_realization, member_id)
        _validate_trunk(member, trunk, active_geometries, certificate.grid_mm)
        trunk_segments = trunk.result.segments
        authority_kind = "same_layer_trunk"
        authority_geometry_fingerprint = trunk.geometry_fingerprint
        authority_claims_fingerprint = trunk.claims_fingerprint

    pigtails_by_terminal: dict[str, CertifiedBusPigtail] = {}
    for pigtail in pigtails:
        if pigtail.terminal_id in pigtails_by_terminal:
            raise ValueError("member pigtails must be unique per terminal")
        pigtails_by_terminal[pigtail.terminal_id] = pigtail
    if set(pigtails_by_terminal) != set(terminal_by_id):
        raise ValueError("member pigtails must exactly cover required terminals")
    if len({item.physical_pad_source_id for item in pigtails}) != len(pigtails):
        raise ValueError("member pigtails must cover unique physical pads")

    boundary_by_id = {boundary.boundary_id: boundary for boundary in bus.boundaries}
    pigtail_segments: list[TrackSegment] = []
    covered_anchors: list[tuple[str, tuple[str, int, int]]] = []
    for terminal_id in sorted(terminal_by_id):
        pigtail = pigtails_by_terminal[terminal_id]
        _validate_carrier_bindings(
            pigtail,
            bus,
            certificate,
            allocation,
            geometry_registry,
            member,
        )
        if pigtail.physical_pad_source_id != source_map[terminal_id]:
            raise ValueError("pigtail physical pad source does not match its terminal binding")
        geometry = geometry_by_id.get(pigtail.assigned_geometry_id)
        if geometry is None or geometry.centerline_geometry_id not in active_geometry_ids:
            raise ValueError("pigtail references a lane not assigned to its member")
        boundary = boundary_by_id.get(pigtail.boundary_id)
        if boundary is None:
            raise ValueError("pigtail references an unknown bus boundary")
        member_ref = next(
            (item for item in boundary.ordered_members if item.member_id == member_id),
            None,
        )
        if member_ref is None or terminal_id not in member_ref.terminal_ids:
            raise ValueError("pigtail terminal is not declared at its bus boundary")
        expected_portal_id, expected_portal_point = _geometry_portal(
            geometry,
            pigtail.portal_kind,
        )
        if boundary.corridor_portal_id != expected_portal_id:
            raise ValueError("pigtail boundary does not own the assigned lane portal")
        if pigtail.portal_point != expected_portal_point:
            raise ValueError("pigtail endpoint does not match the assigned lane portal")
        if pigtail.layer != geometry.layer:
            raise ValueError("pigtail layer does not match the assigned lane portal")
        pigtail_segments.extend(_pigtail_segments(pigtail, member.width_mm))
        covered_anchors.append(
            (
                pigtail.physical_pad_source_id,
                (pigtail.layer, *pigtail.pad_anchor_point),
            )
        )

    emitted_vias = _transition_via_specs(
        bus,
        certificate,
        allocation,
        geometry_registry,
        member,
        active_assignments,
        active_geometries,
        transition_vias,
        profile,
    )
    segments = (*trunk_segments, *pigtail_segments)
    bus_fingerprint = bus.semantic_fingerprint()
    certificate_fingerprint = certificate.semantic_fingerprint()
    registry_fingerprint = geometry_registry.semantic_fingerprint()
    pigtail_fingerprints = tuple(sorted(item.semantic_fingerprint() for item in pigtails))
    transition_via_fingerprints = tuple(
        sorted(item.semantic_fingerprint() for item in transition_vias)
    )
    terminal_pad_sources = tuple(sorted(source_map.items()))
    provisional_prefix = GridRoutePrefix(
        alternative_id=f"bus-member-prefix:{member.member_id}:pending",
        net_name=member.net_name,
        grid_mm=certificate.grid_mm,
        exit_node=min(node for _source_id, node in covered_anchors),
        covered_pad_anchors=tuple(covered_anchors),
        segments=segments,
        vias=emitted_vias,
    )
    composition_fingerprint = _certified_prefix_composition_fingerprint(
        bus_fingerprint=bus_fingerprint,
        certificate_fingerprint=certificate_fingerprint,
        allocation_fingerprint=allocation.allocation_fingerprint,
        geometry_registry_fingerprint=registry_fingerprint,
        member_id=member.member_id,
        net_name=member.net_name,
        active_geometry_ids=active_geometry_ids,
        authority_kind=authority_kind,
        authority_geometry_fingerprint=authority_geometry_fingerprint,
        authority_claims_fingerprint=authority_claims_fingerprint,
        pigtail_fingerprints=pigtail_fingerprints,
        transition_via_fingerprints=transition_via_fingerprints,
        terminal_pad_sources=terminal_pad_sources,
        prefix=provisional_prefix,
    )
    prefix = GridRoutePrefix(
        alternative_id=(f"bus-member-prefix:{member.member_id}:{composition_fingerprint}"),
        net_name=provisional_prefix.net_name,
        grid_mm=provisional_prefix.grid_mm,
        exit_node=provisional_prefix.exit_node,
        covered_pad_anchors=provisional_prefix.covered_pad_anchors,
        segments=provisional_prefix.segments,
        vias=provisional_prefix.vias,
    )
    return CertifiedBusMemberPrefix(
        bus_fingerprint=bus_fingerprint,
        certificate_fingerprint=certificate_fingerprint,
        allocation_fingerprint=allocation.allocation_fingerprint,
        geometry_registry_fingerprint=registry_fingerprint,
        member_id=member.member_id,
        net_name=member.net_name,
        active_geometry_ids=active_geometry_ids,
        authority_kind=authority_kind,
        authority_geometry_fingerprint=authority_geometry_fingerprint,
        authority_claims_fingerprint=authority_claims_fingerprint,
        pigtail_fingerprints=pigtail_fingerprints,
        transition_via_fingerprints=transition_via_fingerprints,
        terminal_pad_sources=terminal_pad_sources,
        prefix=prefix,
        prefix_fingerprint=prefix.semantic_fingerprint(),
        composition_fingerprint=composition_fingerprint,
    )


def _validate_root_bindings(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    registry: CertifiedLaneGeometryRegistry,
    profile: PcbRuleProfile,
) -> None:
    bus_fingerprint = bus.semantic_fingerprint()
    certificate_fingerprint = certificate.semantic_fingerprint()
    if bus.rule_profile_id != profile.profile_id:
        raise ValueError("bus rule profile does not match the prefix profile")
    if not allocation.success:
        raise ValueError("member prefix requires a successful lane allocation")
    if allocation.bus_fingerprint != bus_fingerprint:
        raise ValueError("lane allocation bus fingerprint is stale")
    if allocation.certificate_fingerprint != certificate_fingerprint:
        raise ValueError("lane allocation certificate fingerprint is stale")
    if registry.certificate_fingerprint != certificate_fingerprint:
        raise ValueError("lane geometry registry certificate fingerprint is stale")
    if registry.allocation_fingerprint != allocation.allocation_fingerprint:
        raise ValueError("lane geometry registry allocation fingerprint is stale")
    if registry.grid_mm != certificate.grid_mm:
        raise ValueError("lane geometry registry grid does not match the certificate")
    expected_geometry_ids = {
        slot.centerline_geometry_id
        for assignment in allocation.assignments
        for section in certificate.sections
        if section.section_id == assignment.section_id
        for slot in section.lane_slots
        if slot.slot_id == assignment.slot_id
    }
    registry_geometry_ids = {geometry.centerline_geometry_id for geometry in registry.geometries}
    if registry_geometry_ids != expected_geometry_ids:
        raise ValueError("lane geometry registry must exactly cover assigned centerlines")


def _active_member_geometry(
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    registry: CertifiedLaneGeometryRegistry,
    member: BusMember,
    profile: PcbRuleProfile,
) -> tuple[tuple[BusLaneAssignment, ...], tuple[CertifiedLaneGeometry, ...]]:
    if member.width_mm < profile.geometry.minimum_trace_width_mm:
        raise ValueError("bus member width is below the active profile minimum")
    section_by_id = {section.section_id: section for section in certificate.sections}
    slot_by_key = {
        (section.section_id, slot.slot_id): slot
        for section in certificate.sections
        for slot in section.lane_slots
    }
    geometry_by_id = {geometry.centerline_geometry_id: geometry for geometry in registry.geometries}
    assignments = tuple(
        sorted(
            (item for item in allocation.assignments if item.member_id == member.member_id),
            key=lambda item: _section_index(certificate, item.section_id),
        )
    )
    if not assignments:
        raise ValueError("prefix member has no active lane assignments")
    if len({item.section_id for item in assignments}) != len(assignments):
        raise ValueError("member lane assignments must be unique per active section")

    geometries: list[CertifiedLaneGeometry] = []
    for assignment in assignments:
        section = section_by_id.get(assignment.section_id)
        slot = slot_by_key.get((assignment.section_id, assignment.slot_id))
        if section is None or slot is None:
            raise ValueError("lane assignment references an unknown certificate section or slot")
        if assignment.net_name != member.net_name:
            raise ValueError("lane assignment net does not match its bus member")
        if assignment.layer != slot.layer or assignment.order_index != slot.order_index:
            raise ValueError("lane assignment does not match its certified slot")
        if member.width_mm > slot.maximum_track_width_mm:
            raise ValueError("bus member width exceeds its certified lane slot")
        geometry = geometry_by_id.get(slot.centerline_geometry_id)
        if geometry is None:
            raise ValueError("assigned lane geometry is absent from the registry")
        if geometry.section_id != section.section_id:
            raise ValueError("lane geometry section does not match its assignment")
        if geometry.layer != assignment.layer:
            raise ValueError("lane geometry layer does not match its assignment")
        if geometry.track_width_mm != member.width_mm:
            raise ValueError("lane geometry width does not match its bus member")
        if (
            geometry.entry_portal_id != section.entry_portal_id
            or geometry.exit_portal_id != section.exit_portal_id
        ):
            raise ValueError("lane geometry portal identities do not match its section")
        geometries.append(geometry)
    return assignments, tuple(geometries)


def _validate_transition_topology(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    assignments: Sequence[BusLaneAssignment],
    geometries: Sequence[CertifiedLaneGeometry],
    events: Sequence[BusLayerTransitionEvent],
) -> None:
    if bus.layer_policy.via_policy.mode in {"forbidden", "escape_only"} and events:
        raise ValueError("bus via policy forbids corridor transition events")
    boundary_by_portal = {boundary.corridor_portal_id: boundary for boundary in bus.boundaries}
    section_by_id = {section.section_id: section for section in certificate.sections}
    expected_event_sections: set[str] = set()
    for before_assignment, after_assignment, before, after in zip(
        assignments[:-1],
        assignments[1:],
        geometries[:-1],
        geometries[1:],
        strict=True,
    ):
        if (
            before.exit_portal_id != after.entry_portal_id
            or before.exit_portal_point != after.entry_portal_point
        ):
            raise ValueError("member centerline fragments are discontinuous between sections")
        if before.layer != after.layer:
            expected_event_sections.add(before_assignment.section_id)
            if _section_index(certificate, after_assignment.section_id) != (
                _section_index(certificate, before_assignment.section_id) + 1
            ):
                raise ValueError("transition-bearing member active sections must be adjacent")

    if len(events) != len(expected_event_sections):
        raise ValueError("allocation transitions must exactly cover member layer changes")
    if len({event.section_id for event in events}) != len(events):
        raise ValueError("allocation transitions must be unique per member section")
    for event in events:
        if event.section_id not in expected_event_sections:
            raise ValueError("allocation transition does not bind a member layer change")
        position = next(
            index
            for index, assignment in enumerate(assignments)
            if assignment.section_id == event.section_id
        )
        before = geometries[position]
        after = geometries[position + 1]
        section = section_by_id[event.section_id]
        boundary = boundary_by_portal.get(before.exit_portal_id)
        if (
            boundary is None
            or boundary.boundary_id != event.boundary_id
            or event.window_id not in section.transition_window_ids
            or event.from_layer != before.layer
            or event.to_layer != after.layer
        ):
            raise ValueError("allocation transition authority does not match its section boundary")


def _certified_fragment_segments(
    member: BusMember,
    geometries: Sequence[CertifiedLaneGeometry],
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


def _fragment_geometry_fingerprint(
    member: BusMember,
    geometries: Sequence[CertifiedLaneGeometry],
    segments: Sequence[TrackSegment],
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-certified-member-section-fragments",
            "schema_version": 1,
            "member_id": member.member_id,
            "net_name": member.net_name,
            "centerline_geometry_ids": [geometry.centerline_geometry_id for geometry in geometries],
            "segments": [
                {
                    "x1": segment.x1,
                    "y1": segment.y1,
                    "x2": segment.x2,
                    "y2": segment.y2,
                    "layer": segment.layer,
                    "net_name": segment.net_name,
                    "width_mm": segment.width_mm,
                }
                for segment in segments
            ],
        }
    )


def _validate_realization_bindings(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    registry: CertifiedLaneGeometryRegistry,
    realization: CertifiedBusTrunkRealization,
    profile: PcbRuleProfile,
) -> None:
    if realization.bus_fingerprint != bus.semantic_fingerprint():
        raise ValueError("trunk realization bus fingerprint is stale")
    if realization.certificate_fingerprint != certificate.semantic_fingerprint():
        raise ValueError("trunk realization certificate fingerprint is stale")
    if realization.allocation_fingerprint != allocation.allocation_fingerprint:
        raise ValueError("trunk realization allocation fingerprint is stale")
    if realization.registry_fingerprint != registry.semantic_fingerprint():
        raise ValueError("trunk realization geometry registry fingerprint is stale")
    if realization.profile_fingerprint != _realization_profile_fingerprint(profile):
        raise ValueError("trunk realization profile fingerprint is stale")


def _realization_profile_fingerprint(profile: PcbRuleProfile) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-realization-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


def _validate_carrier_bindings(
    carrier: CertifiedBusPigtail | CertifiedBusTransitionVia,
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    registry: CertifiedLaneGeometryRegistry,
    member: BusMember,
) -> None:
    expected = (
        bus.semantic_fingerprint(),
        certificate.semantic_fingerprint(),
        allocation.allocation_fingerprint,
        registry.semantic_fingerprint(),
    )
    actual = (
        carrier.bus_fingerprint,
        carrier.certificate_fingerprint,
        carrier.allocation_fingerprint,
        carrier.geometry_registry_fingerprint,
    )
    if actual != expected:
        raise ValueError("certified bus carrier fingerprint binding is stale")
    if carrier.member_id != member.member_id or carrier.net_name != member.net_name:
        raise ValueError("certified bus carrier member or net binding is wrong")
    if carrier.grid_mm != certificate.grid_mm:
        raise ValueError("certified bus carrier grid does not match the certificate")


def _member_trunk(
    realization: CertifiedBusTrunkRealization,
    member_id: str,
) -> RealizedCertifiedTrunk:
    matches = tuple(item for item in realization.trunks if item.member_id == member_id)
    if len(matches) != 1:
        raise ValueError("trunk realization must contain exactly one selected member trunk")
    return matches[0]


def _validate_trunk(
    member: BusMember,
    trunk: RealizedCertifiedTrunk,
    geometries: Sequence[CertifiedLaneGeometry],
    grid_mm: float,
) -> None:
    geometry_ids = tuple(item.centerline_geometry_id for item in geometries)
    if trunk.centerline_geometry_ids != geometry_ids:
        raise ValueError("member trunk does not bind its active assigned lane geometries")
    if trunk.result.net_name != member.net_name or trunk.claims.net_name != member.net_name:
        raise ValueError("member trunk net ownership is wrong")
    if trunk.result.vias:
        raise ValueError("certified trunk input cannot pre-materialize transition vias")
    expected_segments = tuple(
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
    if trunk.result.segments != expected_segments:
        raise ValueError("member trunk geometry differs from its certified centerlines")
    expected_length_mm = sum(
        math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1)
        for segment in expected_segments
    )
    if trunk.result.length_mm != expected_length_mm:
        raise ValueError("member trunk length differs from its certified centerlines")
    expected_geometry_fingerprint = _fingerprint(
        {
            "schema_id": "pcbsmith-certified-member-trunk-geometry",
            "schema_version": 1,
            "member_id": member.member_id,
            "centerline_geometry_ids": geometry_ids,
            "net_name": trunk.result.net_name,
            "segments": [
                {
                    "x1": segment.x1,
                    "y1": segment.y1,
                    "x2": segment.x2,
                    "y2": segment.y2,
                    "layer": segment.layer,
                    "net_name": segment.net_name,
                    "width_mm": segment.width_mm,
                }
                for segment in expected_segments
            ],
            "vias": [],
            "length_mm": expected_length_mm,
        }
    )
    if trunk.geometry_fingerprint != expected_geometry_fingerprint:
        raise ValueError("member trunk geometry fingerprint is invalid")
    expected_claims_fingerprint = _fingerprint(
        {
            "schema_id": "pcbsmith-certified-member-trunk-claims",
            "schema_version": 1,
            "net_name": trunk.claims.net_name,
            "resource_ids": sorted(resource.resource_id for resource in trunk.claims.resources),
        }
    )
    if trunk.claims_fingerprint != expected_claims_fingerprint:
        raise ValueError("member trunk claims fingerprint is invalid")


def _geometry_portal(
    geometry: CertifiedLaneGeometry,
    portal_kind: PortalKind,
) -> tuple[str, LatticePoint]:
    if portal_kind == "entry":
        return geometry.entry_portal_id, geometry.entry_portal_point
    return geometry.exit_portal_id, geometry.exit_portal_point


def _pigtail_segments(
    pigtail: CertifiedBusPigtail,
    width_mm: float,
) -> tuple[TrackSegment, ...]:
    return tuple(
        TrackSegment(
            start[0] * pigtail.grid_mm,
            start[1] * pigtail.grid_mm,
            end[0] * pigtail.grid_mm,
            end[1] * pigtail.grid_mm,
            pigtail.layer,
            pigtail.net_name,
            width_mm,
        )
        for start, end in zip(pigtail.points, pigtail.points[1:], strict=False)
    )


def _transition_via_specs(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    registry: CertifiedLaneGeometryRegistry,
    member: BusMember,
    assignments: Sequence[Any],
    geometries: Sequence[CertifiedLaneGeometry],
    carriers: Sequence[CertifiedBusTransitionVia],
    profile: PcbRuleProfile,
) -> tuple[ViaSpec, ...]:
    expected_events = tuple(
        item for item in allocation.layer_transitions if item.member_id == member.member_id
    )
    carrier_by_key: dict[tuple[str, str, str, str, str], CertifiedBusTransitionVia] = {}
    for carrier in carriers:
        key = _transition_key(carrier)
        if key in carrier_by_key:
            raise ValueError("transition vias must be unique per allocation event")
        carrier_by_key[key] = carrier
    expected_by_key = {_transition_key(event): event for event in expected_events}
    if set(carrier_by_key) != set(expected_by_key):
        raise ValueError("transition vias must exactly cover declared allocation events")

    section_positions = {
        section.section_id: index for index, section in enumerate(certificate.sections)
    }
    geometry_by_section = {
        assignment.section_id: geometry
        for assignment, geometry in zip(assignments, geometries, strict=True)
    }
    vias: list[ViaSpec] = []
    for key in sorted(expected_by_key):
        event = expected_by_key[key]
        carrier = carrier_by_key[key]
        _validate_carrier_bindings(
            carrier,
            bus,
            certificate,
            allocation,
            registry,
            member,
        )
        before = geometry_by_section.get(event.section_id)
        before_position = section_positions.get(event.section_id)
        if before is None or before_position is None:
            raise ValueError("transition event does not bind an active member section")
        following_sections = tuple(
            section.section_id
            for section in certificate.sections[before_position + 1 :]
            if section.section_id in geometry_by_section
        )
        if not following_sections:
            raise ValueError("transition event has no following active member section")
        after = geometry_by_section[following_sections[0]]
        if (
            carrier.from_layer != event.from_layer
            or carrier.to_layer != event.to_layer
            or carrier.from_layer != before.layer
            or carrier.to_layer != after.layer
        ):
            raise ValueError("transition via layer binding is wrong")
        if (
            carrier.before_geometry_id != before.centerline_geometry_id
            or carrier.after_geometry_id != after.centerline_geometry_id
        ):
            raise ValueError("transition via assigned geometry binding is wrong")
        if carrier.point != before.exit_portal_point or carrier.point != after.entry_portal_point:
            raise ValueError("transition via must occupy the shared assigned portal point")
        boundary = next(
            (item for item in bus.boundaries if item.boundary_id == event.boundary_id),
            None,
        )
        if boundary is None or boundary.corridor_portal_id != before.exit_portal_id:
            raise ValueError("transition event boundary does not bind the shared portal")
        vias.append(
            ViaSpec(
                x=carrier.point[0] * certificate.grid_mm,
                y=carrier.point[1] * certificate.grid_mm,
                net_name=member.net_name,
                size_mm=profile.geometry.routing_via_diameter_mm,
                drill_mm=profile.geometry.routing_via_drill_mm,
            )
        )
    expected_via_count = next(
        (item.via_count for item in allocation.via_counts if item.member_id == member.member_id),
        0,
    )
    if len(vias) != expected_via_count:
        raise ValueError("emitted transition via count does not match the allocation")
    return tuple(vias)


def _transition_key(
    item: BusLayerTransitionEvent | CertifiedBusTransitionVia,
) -> tuple[str, str, str, str, str]:
    return (
        item.section_id,
        item.boundary_id,
        item.window_id,
        item.from_layer,
        item.to_layer,
    )


def _section_index(certificate: CorridorCapacityCertificate, section_id: str) -> int:
    for index, section in enumerate(certificate.sections):
        if section.section_id == section_id:
            return index
    raise ValueError("lane assignment references an unknown certificate section")


def _segment_direction(start: LatticePoint, end: LatticePoint) -> tuple[int, int]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        raise ValueError("pigtail segments must have positive length")
    if dx != 0 and dy != 0 and abs(dx) != abs(dy):
        raise ValueError("pigtail segments must be horizontal, vertical, or 45-degree")
    return ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
