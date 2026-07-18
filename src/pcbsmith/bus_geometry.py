"""Pure realization of certified ordered-bus lane centerlines.

This slice consumes an already successful R4 lane allocation.  It emits only
certified trunk copper: no pad pigtails, vias, search, or board mutation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from typing import Any, Literal, TypeAlias, cast

from pydantic import Field, StrictInt, field_validator, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult, BusLaneAssignment
from pcbsmith.bus_ir import BusGroup, BusLayer, CorridorCapacityCertificate
from pcbsmith.kicad.astar_router import RouteResult
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.negotiated_grid import GridClaimDomain, grid_claim_domains_for_net
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    PairwiseClearanceDomain,
    RoutingResourceKey,
    capsule_segment_claims,
)
from pcbsmith.routing_ir import RoutingIrModel
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

GridPoint: TypeAlias = tuple[StrictInt, StrictInt]
EscapeGraphTransition: TypeAlias = tuple[GridPoint, GridPoint]
_KEEP_IN_SCHEMA_ID = "pcbsmith-certified-lane-keep-in"
_KEEP_IN_SCHEMA_VERSION = 1


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


def certified_keep_in_fingerprint(
    grid_mm: float,
    polygon: Sequence[GridPoint],
) -> str:
    """Fingerprint one ordered lattice keep-in polygon."""
    if not math.isfinite(grid_mm) or grid_mm <= 0:
        raise ValueError("grid_mm must be finite and positive")
    return _fingerprint(
        {
            "schema_id": _KEEP_IN_SCHEMA_ID,
            "schema_version": _KEEP_IN_SCHEMA_VERSION,
            "grid_mm": grid_mm,
            "polygon": tuple(tuple(point) for point in polygon),
        }
    )


class CertifiedLaneGeometry(RoutingIrModel):
    """One allocation-specific certified lane centerline on an exact lattice."""

    schema_id: Literal["pcbsmith-certified-lane-geometry"] = "pcbsmith-certified-lane-geometry"
    schema_version: Literal[1] = 1
    centerline_geometry_id: str = Field(min_length=1)
    certificate_fingerprint: str
    section_id: str = Field(min_length=1)
    layer: BusLayer
    track_width_mm: float = Field(gt=0)
    grid_mm: float = Field(gt=0)
    entry_portal_id: str = Field(min_length=1)
    exit_portal_id: str = Field(min_length=1)
    entry_portal_point: GridPoint
    exit_portal_point: GridPoint
    points: tuple[GridPoint, ...] = Field(min_length=2)
    keep_in_polygon: tuple[GridPoint, ...] = Field(min_length=3)
    keep_in_fingerprint: str

    @field_validator("certificate_fingerprint", "keep_in_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def geometry_is_exact_and_bound(self) -> CertifiedLaneGeometry:
        if not math.isfinite(self.grid_mm) or not math.isfinite(self.track_width_mm):
            raise ValueError("lane grid and width must be finite and positive")
        if self.entry_portal_id == self.exit_portal_id:
            raise ValueError("lane geometry requires distinct entry and exit portals")
        if self.points[0] != self.entry_portal_point:
            raise ValueError("centerline must start at its entry portal point")
        if self.points[-1] != self.exit_portal_point:
            raise ValueError("centerline must end at its exit portal point")
        if len(set(self.points)) != len(self.points):
            raise ValueError("centerline points must be unique")
        if len(set(self.keep_in_polygon)) != len(self.keep_in_polygon):
            raise ValueError("keep-in polygon vertices must be unique and not repeat closure")
        _validate_simple_supported_polygon(self.keep_in_polygon)
        if _twice_polygon_area(self.keep_in_polygon) == 0:
            raise ValueError("keep-in polygon must have non-zero area")
        expected_keep_in = certified_keep_in_fingerprint(
            self.grid_mm,
            self.keep_in_polygon,
        )
        if self.keep_in_fingerprint != expected_keep_in:
            raise ValueError("keep_in_fingerprint must match the exact keep-in polygon")
        directions: list[tuple[int, int]] = []
        for start, end in zip(self.points, self.points[1:], strict=False):
            direction = _segment_direction(start, end)
            if directions and direction == directions[-1]:
                raise ValueError("centerline cannot contain redundant collinear vertices")
            directions.append(direction)
            if not _segment_inside_polygon(start, end, self.keep_in_polygon):
                raise ValueError("centerline leaves its certified keep-in polygon")
        return self


class CertifiedLaneGeometryRegistry(RoutingIrModel):
    """Canonical allocation-bound registry keyed by centerline geometry ID."""

    schema_id: Literal["pcbsmith-certified-lane-geometry-registry"] = (
        "pcbsmith-certified-lane-geometry-registry"
    )
    schema_version: Literal[1] = 1
    certificate_fingerprint: str
    allocation_fingerprint: str
    grid_mm: float = Field(gt=0)
    geometries: tuple[CertifiedLaneGeometry, ...] = Field(min_length=1)

    @field_validator("certificate_fingerprint", "allocation_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def registry_is_canonical_and_coherent(self) -> CertifiedLaneGeometryRegistry:
        if not math.isfinite(self.grid_mm):
            raise ValueError("registry grid_mm must be finite and positive")
        geometries = tuple(sorted(self.geometries, key=lambda item: item.centerline_geometry_id))
        geometry_ids = tuple(item.centerline_geometry_id for item in geometries)
        if len(set(geometry_ids)) != len(geometry_ids):
            raise ValueError("centerline geometry identities must be unique")
        for geometry in geometries:
            if geometry.certificate_fingerprint != self.certificate_fingerprint:
                raise ValueError("lane geometry certificate fingerprint is stale")
            if geometry.grid_mm != self.grid_mm:
                raise ValueError("lane geometry grid does not match its registry")
        object.__setattr__(self, "geometries", geometries)
        return self


class CertifiedBusEscapeRegion(RoutingIrModel):
    """Exact schema-v1 same-layer lattice graph for one assigned terminal portal."""

    schema_id: Literal["pcbsmith-certified-bus-escape-region"] = (
        "pcbsmith-certified-bus-escape-region"
    )
    schema_version: Literal[1] = 1
    routing_mode: Literal["same_layer_only"] = "same_layer_only"
    region_id: str = Field(min_length=1)
    bus_fingerprint: str
    certificate_fingerprint: str
    allocation_fingerprint: str
    lane_geometry_registry_fingerprint: str
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    terminal_id: str = Field(min_length=1)
    boundary_id: str = Field(min_length=1)
    assigned_geometry_id: str = Field(min_length=1)
    portal_kind: Literal["entry", "exit"]
    portal_id: str = Field(min_length=1)
    portal_point: GridPoint
    layer: BusLayer
    grid_mm: float = Field(gt=0)
    allowed_track_nodes: tuple[GridPoint, ...] = Field(min_length=1)
    allowed_track_transitions: tuple[EscapeGraphTransition, ...] = ()
    allowed_via_cells: tuple[GridPoint, ...] = ()

    @field_validator(
        "bus_fingerprint",
        "certificate_fingerprint",
        "allocation_fingerprint",
        "lane_geometry_registry_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def graph_is_canonical_and_connected(self) -> CertifiedBusEscapeRegion:
        if not math.isfinite(self.grid_mm):
            raise ValueError("escape-region grid_mm must be finite and positive")
        if self.allowed_via_cells:
            raise ValueError("schema-v1 escape regions are same-layer only and forbid via cells")
        nodes = tuple(sorted(self.allowed_track_nodes))
        if any(coordinate < 0 for point in (*nodes, self.portal_point) for coordinate in point):
            raise ValueError("escape-region lattice nodes and portal must be non-negative")
        if len(set(nodes)) != len(nodes):
            raise ValueError("escape-region allowed nodes must be unique")
        if self.portal_point not in nodes:
            raise ValueError("escape-region portal point must be an allowed node")
        transitions: list[EscapeGraphTransition] = []
        for first, second in self.allowed_track_transitions:
            if first not in nodes or second not in nodes:
                raise ValueError("escape transition endpoints must be allowed nodes")
            if max(abs(first[0] - second[0]), abs(first[1] - second[1])) != 1:
                raise ValueError("escape transitions must join adjacent lattice nodes")
            transitions.append((first, second) if first < second else (second, first))
        canonical = tuple(sorted(transitions))
        if len(set(canonical)) != len(canonical):
            raise ValueError("escape-region transitions must be unique")
        adjacency: dict[GridPoint, set[GridPoint]] = {node: set() for node in nodes}
        for first, second in canonical:
            adjacency[first].add(second)
            adjacency[second].add(first)
        reached = {self.portal_point}
        pending = [self.portal_point]
        while pending:
            current = pending.pop()
            for neighbour in adjacency[current]:
                if neighbour not in reached:
                    reached.add(neighbour)
                    pending.append(neighbour)
        if reached != set(nodes):
            raise ValueError("escape-region graph must be connected to its portal")
        object.__setattr__(self, "allowed_track_nodes", nodes)
        object.__setattr__(self, "allowed_track_transitions", canonical)
        return self


class CertifiedBusEscapeGraphRegistry(RoutingIrModel):
    """Immutable canonical authority covering every declared bus terminal exactly once."""

    schema_id: Literal["pcbsmith-certified-bus-escape-graph-registry"] = (
        "pcbsmith-certified-bus-escape-graph-registry"
    )
    schema_version: Literal[1] = 1
    routing_mode: Literal["same_layer_only"] = "same_layer_only"
    bus_fingerprint: str
    certificate_fingerprint: str
    allocation_fingerprint: str
    lane_geometry_registry_fingerprint: str
    grid_mm: float = Field(gt=0)
    regions: tuple[CertifiedBusEscapeRegion, ...] = Field(min_length=1)

    @field_validator(
        "bus_fingerprint",
        "certificate_fingerprint",
        "allocation_fingerprint",
        "lane_geometry_registry_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def registry_is_canonical(self) -> CertifiedBusEscapeGraphRegistry:
        regions = tuple(sorted(self.regions, key=lambda item: item.region_id))
        if len({item.region_id for item in regions}) != len(regions):
            raise ValueError("escape-region identities must be unique")
        if len({(item.member_id, item.terminal_id) for item in regions}) != len(regions):
            raise ValueError("escape graph requires one region per member terminal")
        for region in regions:
            if region.bus_fingerprint != self.bus_fingerprint:
                raise ValueError("escape-region bus fingerprint is stale")
            if region.certificate_fingerprint != self.certificate_fingerprint:
                raise ValueError("escape-region certificate fingerprint is stale")
            if region.allocation_fingerprint != self.allocation_fingerprint:
                raise ValueError("escape-region allocation fingerprint is stale")
            if region.lane_geometry_registry_fingerprint != self.lane_geometry_registry_fingerprint:
                raise ValueError("escape-region lane geometry registry fingerprint is stale")
            if region.grid_mm != self.grid_mm:
                raise ValueError("escape-region grid does not match its registry")
        object.__setattr__(self, "regions", regions)
        return self

    def require_authority(
        self,
        bus: BusGroup,
        certificate: CorridorCapacityCertificate,
        allocation: BusLaneAllocationResult,
        lane_registry: CertifiedLaneGeometryRegistry,
    ) -> None:
        bus_fp, certificate_fp = bus.semantic_fingerprint(), certificate.semantic_fingerprint()
        if (self.bus_fingerprint, self.certificate_fingerprint, self.allocation_fingerprint) != (
            bus_fp,
            certificate_fp,
            allocation.allocation_fingerprint,
        ):
            raise ValueError("escape-graph root authority is stale")
        if self.lane_geometry_registry_fingerprint != lane_registry.semantic_fingerprint():
            raise ValueError("escape-graph lane geometry registry fingerprint is stale")
        if (
            not allocation.success
            or allocation.bus_fingerprint != bus_fp
            or allocation.certificate_fingerprint != certificate_fp
        ):
            raise ValueError("escape-graph allocation authority is stale or unsuccessful")
        if (
            lane_registry.certificate_fingerprint != certificate_fp
            or lane_registry.allocation_fingerprint != allocation.allocation_fingerprint
        ):
            raise ValueError("escape-graph lane registry authority is stale")
        if self.grid_mm != certificate.grid_mm or lane_registry.grid_mm != certificate.grid_mm:
            raise ValueError("escape-graph grid does not match its certificate")
        expected = {(m.member_id, t.terminal_id) for m in bus.members for t in m.terminals}
        if {(r.member_id, r.terminal_id) for r in self.regions} != expected:
            raise ValueError("escape graph must exactly cover declared member terminals")
        members = {item.member_id: item for item in bus.members}
        boundaries = {item.boundary_id: item for item in bus.boundaries}
        geometries = {item.centerline_geometry_id: item for item in lane_registry.geometries}
        assigned = {
            (assignment.member_id, slot.centerline_geometry_id)
            for assignment in allocation.assignments
            for section in certificate.sections
            if section.section_id == assignment.section_id
            for slot in section.lane_slots
            if slot.slot_id == assignment.slot_id
        }
        for region in self.regions:
            member = members[region.member_id]
            if region.net_name != member.net_name:
                raise ValueError("escape-region net binding is stale")
            boundary = boundaries.get(region.boundary_id)
            ref = (
                None
                if boundary is None
                else next(
                    (x for x in boundary.ordered_members if x.member_id == region.member_id), None
                )
            )
            if ref is None or region.terminal_id not in ref.terminal_ids:
                raise ValueError("escape-region terminal is not declared at its boundary")
            if (region.member_id, region.assigned_geometry_id) not in assigned:
                raise ValueError("escape-region geometry is not assigned to its member")
            geometry = geometries.get(region.assigned_geometry_id)
            if geometry is None:
                raise ValueError("escape-region geometry is absent from the lane registry")
            portal_id, portal_point = (
                (geometry.entry_portal_id, geometry.entry_portal_point)
                if region.portal_kind == "entry"
                else (geometry.exit_portal_id, geometry.exit_portal_point)
            )
            if (
                boundary is None
                or boundary.corridor_portal_id != portal_id
                or region.portal_id != portal_id
                or region.portal_point != portal_point
                or region.layer != geometry.layer
            ):
                raise ValueError("escape-region portal does not match its assigned lane")
        revalidated = CertifiedBusEscapeGraphRegistry.model_validate_json(self.model_dump_json())
        if revalidated != self:
            raise ValueError("escape-graph registry must be canonical")


@dataclass(frozen=True)
class RealizedCertifiedTrunk:
    """One complete member trunk plus its exact R2 resource claims."""

    member_id: str
    centerline_geometry_ids: tuple[str, ...]
    result: RouteResult
    claims: NetResourceClaims
    geometry_fingerprint: str
    claims_fingerprint: str

    def __post_init__(self) -> None:
        if not self.member_id or not self.centerline_geometry_ids:
            raise ValueError("realized trunk identities must be non-empty")
        if self.result.net_name != self.claims.net_name:
            raise ValueError("realized trunk route and claims must have one owner")
        if self.result.vias:
            raise ValueError("certified trunk realization cannot contain vias")
        if any(segment.net_name != self.result.net_name for segment in self.result.segments):
            raise ValueError("certified trunk segments must have the route owner")
        _require_sha256(self.geometry_fingerprint, "geometry_fingerprint")
        _require_sha256(self.claims_fingerprint, "claims_fingerprint")
        expected_geometry = _route_geometry_fingerprint(
            self.member_id,
            self.centerline_geometry_ids,
            self.result,
        )
        if self.geometry_fingerprint != expected_geometry:
            raise ValueError("geometry_fingerprint must match the realized trunk geometry")
        if self.claims_fingerprint != _claims_fingerprint(self.claims):
            raise ValueError("claims_fingerprint must match the realized trunk claims")


@dataclass(frozen=True)
class CertifiedBusTrunkRealization:
    """Deterministic pure output of certified trunk realization."""

    bus_fingerprint: str
    certificate_fingerprint: str
    allocation_fingerprint: str
    registry_fingerprint: str
    profile_fingerprint: str
    trunks: tuple[RealizedCertifiedTrunk, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "bus_fingerprint",
            "certificate_fingerprint",
            "allocation_fingerprint",
            "registry_fingerprint",
            "profile_fingerprint",
        ):
            _require_sha256(cast(str, getattr(self, field_name)), field_name)
        canonical = tuple(sorted(self.trunks, key=lambda item: item.member_id))
        if len({item.member_id for item in canonical}) != len(canonical):
            raise ValueError("realized member trunks must be unique")
        object.__setattr__(self, "trunks", canonical)

    def semantic_fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema_id": "pcbsmith-certified-bus-trunk-realization",
                "schema_version": 1,
                "bus_fingerprint": self.bus_fingerprint,
                "certificate_fingerprint": self.certificate_fingerprint,
                "allocation_fingerprint": self.allocation_fingerprint,
                "registry_fingerprint": self.registry_fingerprint,
                "profile_fingerprint": self.profile_fingerprint,
                "trunks": [
                    {
                        "member_id": trunk.member_id,
                        "centerline_geometry_ids": trunk.centerline_geometry_ids,
                        "geometry_fingerprint": trunk.geometry_fingerprint,
                        "claims_fingerprint": trunk.claims_fingerprint,
                    }
                    for trunk in self.trunks
                ],
            }
        )


def realize_certified_trunks(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    geometry_registry: CertifiedLaneGeometryRegistry,
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    pairwise_domains: Sequence[PairwiseClearanceDomain] | None = None,
    claim_domains_by_net: Mapping[str, Sequence[GridClaimDomain]] | None = None,
) -> CertifiedBusTrunkRealization:
    """Realize every exact certified lane trunk without pads, vias, or search."""

    return _realize_certified_trunks_for_members(
        bus,
        certificate,
        allocation,
        geometry_registry,
        tuple(member.member_id for member in bus.members),
        profile=profile,
        pairwise_domains=pairwise_domains,
        claim_domains_by_net=claim_domains_by_net,
    )


def realize_certified_trunk_subset(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    geometry_registry: CertifiedLaneGeometryRegistry,
    member_ids: Sequence[str],
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    pairwise_domains: Sequence[PairwiseClearanceDomain] | None = None,
    claim_domains_by_net: Mapping[str, Sequence[GridClaimDomain]] | None = None,
) -> CertifiedBusTrunkRealization:
    """Realize one explicit canonical same-layer member subset without search."""

    requested = tuple(member_ids)
    canonical = tuple(sorted(set(requested)))
    if not requested:
        raise ValueError("certified trunk subset cannot be empty")
    if canonical != requested:
        raise ValueError("certified trunk subset must be canonical and unique")
    declared = {member.member_id for member in bus.members}
    if not set(canonical).issubset(declared):
        raise ValueError("certified trunk subset references an unknown bus member")
    return _realize_certified_trunks_for_members(
        bus,
        certificate,
        allocation,
        geometry_registry,
        canonical,
        profile=profile,
        pairwise_domains=pairwise_domains,
        claim_domains_by_net=claim_domains_by_net,
    )


def _realize_certified_trunks_for_members(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    geometry_registry: CertifiedLaneGeometryRegistry,
    selected_member_ids: tuple[str, ...],
    *,
    profile: PcbRuleProfile,
    pairwise_domains: Sequence[PairwiseClearanceDomain] | None,
    claim_domains_by_net: Mapping[str, Sequence[GridClaimDomain]] | None,
) -> CertifiedBusTrunkRealization:
    """Shared exact realization implementation for a validated member selection."""

    bus_fingerprint = bus.semantic_fingerprint()
    certificate_fingerprint = certificate.semantic_fingerprint()
    if bus.rule_profile_id != profile.profile_id:
        raise ValueError("bus rule profile does not match the realization profile")
    if not allocation.success:
        raise ValueError("certified trunks require a successful lane allocation")
    if allocation.bus_fingerprint != bus_fingerprint:
        raise ValueError("lane allocation bus fingerprint is stale")
    if allocation.certificate_fingerprint != certificate_fingerprint:
        raise ValueError("lane allocation certificate fingerprint is stale")
    if geometry_registry.certificate_fingerprint != certificate_fingerprint:
        raise ValueError("lane geometry registry certificate fingerprint is stale")
    if geometry_registry.allocation_fingerprint != allocation.allocation_fingerprint:
        raise ValueError("lane geometry registry allocation fingerprint is stale")
    if geometry_registry.grid_mm != certificate.grid_mm:
        raise ValueError("lane geometry registry grid does not match the certificate")

    member_by_id = {member.member_id: member for member in bus.members}
    selected_members = tuple(member_by_id[member_id] for member_id in selected_member_ids)
    section_by_id = {section.section_id: section for section in certificate.sections}
    slot_by_key = {
        (section.section_id, slot.slot_id): slot
        for section in certificate.sections
        for slot in section.lane_slots
    }
    assignments = allocation.assignments
    expected_assignment_keys = {
        (section.section_id, member_ref.member_id)
        for section, boundary in zip(
            certificate.sections,
            bus.boundaries[:-1],
            strict=True,
        )
        for member_ref in boundary.ordered_members
    }
    actual_assignment_keys = {
        (assignment.section_id, assignment.member_id) for assignment in assignments
    }
    if actual_assignment_keys != expected_assignment_keys:
        raise ValueError("lane allocation does not cover every active member and section exactly")

    assignment_bindings: dict[tuple[str, str], tuple[BusLaneAssignment, str]] = {}
    expected_geometry_ids: set[str] = set()
    for assignment in assignments:
        member = member_by_id.get(assignment.member_id)
        section = section_by_id.get(assignment.section_id)
        slot = slot_by_key.get((assignment.section_id, assignment.slot_id))
        if member is None or section is None or slot is None:
            raise ValueError("lane assignment references unknown bus or certificate identity")
        if assignment.net_name != member.net_name:
            raise ValueError("lane assignment net does not match its bus member")
        if assignment.layer != slot.layer or assignment.order_index != slot.order_index:
            raise ValueError("lane assignment does not match its certified slot")
        geometry_id = slot.centerline_geometry_id
        if geometry_id in expected_geometry_ids:
            raise ValueError("assigned certificate centerline identities must be unique")
        expected_geometry_ids.add(geometry_id)
        assignment_bindings[(assignment.section_id, assignment.member_id)] = (
            assignment,
            geometry_id,
        )

    geometry_by_id = {item.centerline_geometry_id: item for item in geometry_registry.geometries}
    if set(geometry_by_id) != expected_geometry_ids:
        raise ValueError("lane geometry registry must exactly cover assigned centerlines")

    active_nets = {member.net_name for member in selected_members}
    if claim_domains_by_net is not None and set(claim_domains_by_net) != active_nets:
        raise ValueError("explicit grid claim domains must exactly cover active bus nets")

    domains_by_net: dict[str, tuple[GridClaimDomain, ...]] = {}
    for member in selected_members:
        if member.width_mm < profile.geometry.minimum_trace_width_mm:
            raise ValueError("bus member width is below the active fabrication profile minimum")
        canonical_domains = grid_claim_domains_for_net(
            member.net_name,
            member.width_mm,
            profile,
            pairwise_domains=pairwise_domains,
        )
        if claim_domains_by_net is not None:
            asserted_domains = tuple(claim_domains_by_net[member.net_name])
            if (
                len(asserted_domains) != len(set(asserted_domains))
                or tuple(sorted(asserted_domains)) != canonical_domains
            ):
                raise ValueError(
                    "explicit grid claim domains must exactly match canonical derived domains"
                )
        domains_by_net[member.net_name] = canonical_domains

    section_order = {
        section.section_id: index for index, section in enumerate(certificate.sections)
    }
    assignments_by_member: dict[str, list[BusLaneAssignment]] = {
        member.member_id: [] for member in bus.members
    }
    for assignment in assignments:
        assignments_by_member[assignment.member_id].append(assignment)
    for member_assignments in assignments_by_member.values():
        member_assignments.sort(key=lambda item: section_order[item.section_id])

    trunks: list[RealizedCertifiedTrunk] = []
    for member in selected_members:
        member_assignments = assignments_by_member[member.member_id]
        if not member_assignments:
            raise ValueError("every declared bus member requires at least one active section")
        segments: list[TrackSegment] = []
        geometry_ids: list[str] = []
        previous_exit: GridPoint | None = None
        previous_layer: BusLayer | None = None
        for assignment in member_assignments:
            _, geometry_id = assignment_bindings[(assignment.section_id, member.member_id)]
            geometry = geometry_by_id[geometry_id]
            section = section_by_id[assignment.section_id]
            slot = slot_by_key[(assignment.section_id, assignment.slot_id)]
            if geometry.section_id != section.section_id:
                raise ValueError("lane geometry section does not match its assignment")
            if geometry.layer != assignment.layer:
                raise ValueError("lane geometry layer does not match its assignment")
            if geometry.track_width_mm != member.width_mm:
                raise ValueError("lane geometry width does not match its bus member")
            if member.width_mm > slot.maximum_track_width_mm:
                raise ValueError("bus member width exceeds its certified lane slot")
            if (
                geometry.entry_portal_id != section.entry_portal_id
                or geometry.exit_portal_id != section.exit_portal_id
            ):
                raise ValueError("lane geometry portal identities do not match its section")
            if previous_exit is not None and geometry.entry_portal_point != previous_exit:
                raise ValueError("member centerlines are discontinuous between sections")
            if previous_layer is not None and geometry.layer != previous_layer:
                raise ValueError(
                    "member centerline changes layer without a realized transition via"
                )
            previous_exit = geometry.exit_portal_point
            previous_layer = geometry.layer
            geometry_ids.append(geometry_id)
            for start, end in zip(geometry.points, geometry.points[1:], strict=False):
                segments.append(
                    TrackSegment(
                        x1=start[0] * certificate.grid_mm,
                        y1=start[1] * certificate.grid_mm,
                        x2=end[0] * certificate.grid_mm,
                        y2=end[1] * certificate.grid_mm,
                        layer=geometry.layer,
                        net_name=member.net_name,
                        width_mm=member.width_mm,
                    )
                )
        resources: set[RoutingResourceKey] = set()
        for segment in segments:
            for domain in domains_by_net[member.net_name]:
                resources.update(
                    capsule_segment_claims(
                        domain.domain_id,
                        cast(BusLayer, segment.layer),
                        (segment.x1, segment.y1),
                        (segment.x2, segment.y2),
                        certificate.grid_mm,
                        domain.track_halo_radius_mm,
                    )
                )
        claims = NetResourceClaims(member.net_name, frozenset(resources))
        route = RouteResult(
            net_name=member.net_name,
            segments=tuple(segments),
            vias=(),
            length_mm=sum(
                math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1) for segment in segments
            ),
        )
        trunks.append(
            RealizedCertifiedTrunk(
                member_id=member.member_id,
                centerline_geometry_ids=tuple(geometry_ids),
                result=route,
                claims=claims,
                geometry_fingerprint=_route_geometry_fingerprint(
                    member.member_id,
                    tuple(geometry_ids),
                    route,
                ),
                claims_fingerprint=_claims_fingerprint(claims),
            )
        )

    for first, second in combinations(trunks, 2):
        overlap = first.claims.resources & second.claims.resources
        if overlap:
            first_resource = min(overlap).resource_id
            raise ValueError(
                "foreign bus members overlap negotiated routing resources: "
                f"{first.member_id}, {second.member_id}, {first_resource}"
            )

    return CertifiedBusTrunkRealization(
        bus_fingerprint=bus_fingerprint,
        certificate_fingerprint=certificate_fingerprint,
        allocation_fingerprint=allocation.allocation_fingerprint,
        registry_fingerprint=geometry_registry.semantic_fingerprint(),
        profile_fingerprint=_profile_fingerprint(profile),
        trunks=tuple(trunks),
    )


def _route_geometry_fingerprint(
    member_id: str,
    geometry_ids: tuple[str, ...],
    route: RouteResult,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-certified-member-trunk-geometry",
            "schema_version": 1,
            "member_id": member_id,
            "centerline_geometry_ids": geometry_ids,
            "net_name": route.net_name,
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
                for segment in route.segments
            ],
            "vias": [],
            "length_mm": route.length_mm,
        }
    )


def _claims_fingerprint(claims: NetResourceClaims) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-certified-member-trunk-claims",
            "schema_version": 1,
            "net_name": claims.net_name,
            "resource_ids": sorted(resource.resource_id for resource in claims.resources),
        }
    )


def _profile_fingerprint(profile: PcbRuleProfile) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-realization-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


def _segment_direction(start: GridPoint, end: GridPoint) -> tuple[int, int]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        raise ValueError("centerline segments must have positive length")
    if dx != 0 and dy != 0 and abs(dx) != abs(dy):
        raise ValueError("centerline segments must be horizontal, vertical, or 45-degree")
    return ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))


def _twice_polygon_area(polygon: Sequence[GridPoint]) -> int:
    return sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(
            polygon,
            (*polygon[1:], polygon[0]),
            strict=True,
        )
    )


def _segment_inside_polygon(
    start: GridPoint,
    end: GridPoint,
    polygon: Sequence[GridPoint],
) -> bool:
    _segment_direction(start, end)
    parameters = {Fraction(0), Fraction(1)}
    for edge_start, edge_end in _polygon_edges(polygon):
        parameters.update(_segment_intersection_parameters(start, end, edge_start, edge_end))
    ordered = sorted(parameters)
    probes = set(ordered)
    probes.update((low + high) / 2 for low, high in zip(ordered, ordered[1:], strict=False))
    return all(
        _point_in_polygon_inclusive(_point_at_parameter(start, end, parameter), polygon)
        for parameter in probes
    )


def _point_in_polygon_inclusive(
    point: tuple[Fraction, Fraction],
    polygon: Sequence[GridPoint],
) -> bool:
    for start, end in _polygon_edges(polygon):
        if _point_on_segment(point, start, end):
            return True
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if (current[1] > point[1]) != (previous[1] > point[1]):
            intersection_x = (previous[0] - current[0]) * (point[1] - current[1]) / (
                previous[1] - current[1]
            ) + current[0]
            if point[0] < intersection_x:
                inside = not inside
        previous = current
    return inside


def _point_on_segment(
    point: tuple[Fraction, Fraction],
    start: GridPoint,
    end: GridPoint,
) -> bool:
    cross = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (
        point[0] - start[0]
    )
    return (
        cross == 0
        and min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
        and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
    )


def _polygon_edges(
    polygon: Sequence[GridPoint],
) -> tuple[tuple[GridPoint, GridPoint], ...]:
    return tuple(zip(polygon, (*polygon[1:], polygon[0]), strict=True))


def _validate_simple_supported_polygon(polygon: Sequence[GridPoint]) -> None:
    edges = _polygon_edges(polygon)
    for start, end in edges:
        try:
            _segment_direction(start, end)
        except ValueError as error:
            raise ValueError(
                "keep-in polygon edges must be horizontal, vertical, or 45-degree"
            ) from error
    edge_count = len(edges)
    for first_index, first in enumerate(edges):
        for second_index in range(first_index + 1, edge_count):
            second = edges[second_index]
            parameters = _segment_intersection_parameters(*first, *second)
            adjacent = second_index == first_index + 1 or (
                first_index == 0 and second_index == edge_count - 1
            )
            if not parameters:
                if adjacent:
                    raise ValueError("keep-in polygon boundary must be connected")
                continue
            if not adjacent:
                raise ValueError("keep-in polygon must be simple and non-self-intersecting")
            expected = first[0] if first_index == 0 and second_index == edge_count - 1 else first[1]
            intersection_points = {
                _point_at_parameter(first[0], first[1], parameter) for parameter in parameters
            }
            expected_point = (Fraction(expected[0]), Fraction(expected[1]))
            if intersection_points != {expected_point}:
                raise ValueError("keep-in polygon must be simple and non-self-intersecting")


def _segment_intersection_parameters(
    first_start: GridPoint,
    first_end: GridPoint,
    second_start: GridPoint,
    second_end: GridPoint,
) -> set[Fraction]:
    first_delta = (
        first_end[0] - first_start[0],
        first_end[1] - first_start[1],
    )
    second_delta = (
        second_end[0] - second_start[0],
        second_end[1] - second_start[1],
    )
    offset = (
        second_start[0] - first_start[0],
        second_start[1] - first_start[1],
    )
    denominator = _cross(first_delta, second_delta)
    if denominator != 0:
        first_parameter = Fraction(_cross(offset, second_delta), denominator)
        second_parameter = Fraction(_cross(offset, first_delta), denominator)
        if 0 <= first_parameter <= 1 and 0 <= second_parameter <= 1:
            return {first_parameter}
        return set()
    if _cross(offset, first_delta) != 0:
        return set()
    axis = 0 if first_delta[0] != 0 else 1
    start_parameter = Fraction(
        second_start[axis] - first_start[axis],
        first_delta[axis],
    )
    end_parameter = Fraction(
        second_end[axis] - first_start[axis],
        first_delta[axis],
    )
    low = max(Fraction(0), min(start_parameter, end_parameter))
    high = min(Fraction(1), max(start_parameter, end_parameter))
    if low > high:
        return set()
    return {low, high}


def _cross(first: tuple[int, int], second: tuple[int, int]) -> int:
    return first[0] * second[1] - first[1] * second[0]


def _point_at_parameter(
    start: GridPoint,
    end: GridPoint,
    parameter: Fraction,
) -> tuple[Fraction, Fraction]:
    return (
        Fraction(start[0]) + parameter * (end[0] - start[0]),
        Fraction(start[1]) + parameter * (end[1] - start[1]),
    )
