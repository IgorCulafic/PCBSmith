"""Replay-bound realization of one certified physical bus swap region.

The schema-v1 carrier is deliberately narrow: one adjacent semantic swap on a
two-layer board, one stationary member, and one bridge member using exactly two
through vias.  Search never leaves the region's explicit lattice authority.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from enum import StrEnum
from fractions import Fraction
from functools import cmp_to_key
from math import gcd
from typing import Any, Literal, Self, cast

from pydantic import Field, StrictInt, field_serializer, model_validator

from pcbsmith.kicad.astar_router import merge_collinear_segments
from pcbsmith.kicad.board import TrackSegment, ViaSpec
from pcbsmith.kicad.bus_metrics import AlgebraicGridLength, MetricAuthority
from pcbsmith.kicad.bus_physical_swap import CertifiedBusSwapRegion, LayerGridNode
from pcbsmith.kicad.negotiated_grid import GridClaimDomain, grid_claim_domains_for_net
from pcbsmith.kicad.negotiated_resources import (
    LayerName,
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
    capsule_segment_claims,
    union_net_resource_claims,
    via_claims,
)
from pcbsmith.routing_ir import RoutingIrModel


class BusSwapCarrierDisposition(StrEnum):
    GENERATED = "generated"
    FAILED = "failed"


class BusSwapCarrierFailureReason(StrEnum):
    STATIC_OBSTACLE_AUTHORITY = "static_obstacle_authority"
    CANDIDATE_BUDGET = "candidate_budget"
    EXPANSION_BUDGET = "expansion_budget"
    NO_GRAPH_PATH = "no_graph_path"
    POLICY_VIOLATION = "policy_violation"
    RESOURCE_CONFLICT = "resource_conflict"
    KEEP_IN_CONFLICT = "keep_in_conflict"


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resource_payload(resource: RoutingResourceKey) -> dict[str, Any]:
    return {
        "domain_id": resource.domain_id,
        "layer": resource.layer,
        "kind": resource.kind,
        "ix0": resource.ix0,
        "iy0": resource.iy0,
        "ix1": resource.ix1,
        "iy1": resource.iy1,
    }


def _claim_payload(claim: NetResourceClaims) -> dict[str, Any]:
    return {
        "net_name": claim.net_name,
        "resources": [_resource_payload(item) for item in sorted(claim.resources)],
    }


def _segment_key(segment: TrackSegment) -> tuple[object, ...]:
    first = (segment.x1, segment.y1)
    second = (segment.x2, segment.y2)
    low, high = sorted((first, second))
    return (
        segment.net_name,
        segment.layer,
        segment.width_mm,
        low[0],
        low[1],
        high[0],
        high[1],
    )


def _via_key(via: ViaSpec) -> tuple[object, ...]:
    return (
        via.net_name,
        via.x,
        via.y,
        via.size_mm,
        via.drill_mm,
        via.front_mask,
        via.back_mask,
    )


class BusSwapMemberCarrier(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-swap-member-carrier"] = (
        "pcbsmith-bus-swap-member-carrier"
    )
    schema_version: Literal[1] = 1
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    role: Literal["stationary", "bridge"]
    path_nodes: tuple[LayerGridNode, ...] = Field(min_length=2)
    segments: tuple[TrackSegment, ...] = Field(min_length=1)
    vias: tuple[ViaSpec, ...] = ()
    claims: NetResourceClaims

    @field_serializer("claims")
    def serialize_claims(self, claim: NetResourceClaims) -> dict[str, Any]:
        return _claim_payload(claim)

    @model_validator(mode="after")
    def geometry_is_canonical(self) -> Self:
        if self.net_name != self.claims.net_name:
            raise ValueError("member carrier and resource claims must have one owner")
        segments = tuple(sorted(self.segments, key=_segment_key))
        vias = tuple(sorted(self.vias, key=_via_key))
        if len(set(map(_segment_key, segments))) != len(segments):
            raise ValueError("member carrier contains duplicate segments")
        if len(set(map(_via_key, vias))) != len(vias):
            raise ValueError("member carrier contains duplicate vias")
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "vias", vias)
        return self


class BusSwapConnectivityEvidence(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-swap-connectivity-evidence"] = (
        "pcbsmith-bus-swap-connectivity-evidence"
    )
    schema_version: Literal[1] = 1
    member_paths: tuple[tuple[str, tuple[LayerGridNode, ...]], ...]
    bridge_vertical_transition_count: Literal[2] = 2
    stationary_vertical_transition_count: Literal[0] = 0


class BusSwapBoundaryContainmentWitness(RoutingIrModel):
    """Exact nearest-boundary proof for one emitted copper primitive."""

    schema_id: Literal["pcbsmith-bus-swap-boundary-containment-witness"] = (
        "pcbsmith-bus-swap-boundary-containment-witness"
    )
    schema_version: Literal[1] = 1
    primitive_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    primitive_kind: Literal["track_capsule", "via_circle"]
    polygon_edge_index: StrictInt = Field(ge=0)
    centerline_inside_keep_in: bool
    centerline_distance_squared_numerator: StrictInt = Field(ge=0)
    centerline_distance_squared_denominator: StrictInt = Field(ge=1)
    required_radius_squared_numerator: StrictInt = Field(ge=0)
    required_radius_squared_denominator: StrictInt = Field(ge=1)
    passed: bool

    @model_validator(mode="after")
    def exact_fraction_and_disposition_are_coherent(self) -> Self:
        for numerator_name, denominator_name in (
            (
                "centerline_distance_squared_numerator",
                "centerline_distance_squared_denominator",
            ),
            (
                "required_radius_squared_numerator",
                "required_radius_squared_denominator",
            ),
        ):
            numerator = getattr(self, numerator_name)
            denominator = getattr(self, denominator_name)
            if gcd(numerator, denominator) != 1:
                raise ValueError("containment witness fractions must be reduced")
        distance_squared = Fraction(
            self.centerline_distance_squared_numerator,
            self.centerline_distance_squared_denominator,
        )
        radius_squared = Fraction(
            self.required_radius_squared_numerator,
            self.required_radius_squared_denominator,
        )
        expected = self.centerline_inside_keep_in and distance_squared >= radius_squared
        if self.passed != expected:
            raise ValueError("containment witness disposition differs from exact fractions")
        return self


class BusSwapContainmentEvidence(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-swap-containment-evidence"] = (
        "pcbsmith-bus-swap-containment-evidence"
    )
    schema_version: Literal[1] = 1
    allowed_node_count: int = Field(ge=1)
    used_node_count: int = Field(ge=1)
    all_nodes_declared: Literal[True] = True
    all_transitions_declared: Literal[True] = True
    all_nodes_inside_keep_in: Literal[True] = True
    primitive_witnesses: tuple[BusSwapBoundaryContainmentWitness, ...] = Field(
        min_length=1
    )

    @model_validator(mode="after")
    def witnesses_are_canonical_and_all_pass(self) -> Self:
        ids = tuple(item.primitive_id for item in self.primitive_witnesses)
        if len(set(ids)) != len(ids) or ids != tuple(sorted(ids)):
            raise ValueError("containment primitive witnesses must be unique and canonical")
        if any(not item.passed for item in self.primitive_witnesses):
            raise ValueError("certified containment evidence cannot retain a failed primitive")
        return self


class BusSwapClearanceEvidence(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-swap-clearance-evidence"] = (
        "pcbsmith-bus-swap-clearance-evidence"
    )
    schema_version: Literal[1] = 1
    claim_domain_ids_by_net: tuple[tuple[str, tuple[str, ...]], ...]
    generated_claims: tuple[NetResourceClaims, ...]
    capacity_one_conflicts: tuple[str, ...] = ()

    @field_serializer("generated_claims")
    def serialize_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [_claim_payload(item) for item in claims]


class BusSwapObstacleEvidence(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-swap-obstacle-evidence"] = (
        "pcbsmith-bus-swap-obstacle-evidence"
    )
    schema_version: Literal[1] = 1
    static_obstacle_fingerprint: str
    initial_occupancy_fingerprint: str
    foreign_net_names: tuple[str, ...]
    required_static_claims: tuple[NetResourceClaims, ...]
    initial_occupancy_covers_static_copper: Literal[True] = True
    conflict_resource_ids: tuple[str, ...] = ()

    @field_serializer("required_static_claims")
    def serialize_required_static_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [_claim_payload(item) for item in claims]


class CertifiedBusSwapCarrier(RoutingIrModel):
    """Exact copper and evidence for one accepted certified swap region."""

    schema_id: Literal["pcbsmith-certified-bus-swap-carrier"] = (
        "pcbsmith-certified-bus-swap-carrier"
    )
    schema_version: Literal[1] = 1
    region: CertifiedBusSwapRegion
    initial_claims: tuple[NetResourceClaims, ...]
    initial_occupancy_fingerprint: str
    bridge_member_id: str
    stationary_member_id: str
    via_cells: tuple[tuple[int, int], tuple[int, int]]
    members: tuple[BusSwapMemberCarrier, BusSwapMemberCarrier]
    path_length: AlgebraicGridLength
    resulting_maximum_combined_via_count: int = Field(ge=0)
    resulting_combined_via_count_spread: int = Field(ge=0)
    connectivity_evidence: BusSwapConnectivityEvidence
    containment_evidence: BusSwapContainmentEvidence
    clearance_evidence: BusSwapClearanceEvidence
    obstacle_evidence: BusSwapObstacleEvidence
    geometry_fingerprint: str
    carrier_fingerprint: str

    @field_serializer("initial_claims")
    def serialize_initial_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [_claim_payload(item) for item in claims]

    @model_validator(mode="after")
    def carrier_is_exactly_reconstructible(self) -> Self:
        region = self.region.require_authority()
        canonical_initial = tuple(sorted(self.initial_claims, key=lambda item: item.net_name))
        if len({item.net_name for item in canonical_initial}) != len(canonical_initial):
            raise ValueError("initial occupancy contains duplicate net identities")
        if tuple(self.initial_claims) != canonical_initial:
            object.__setattr__(self, "initial_claims", canonical_initial)
        initial_ledger = OccupancyLedger(canonical_initial)
        if initial_ledger.semantic_fingerprint() != self.initial_occupancy_fingerprint:
            raise ValueError("carrier initial occupancy fingerprint is stale")

        event_members = {
            region.swap_event.first_member_id,
            region.swap_event.second_member_id,
        }
        if {self.bridge_member_id, self.stationary_member_id} != event_members:
            raise ValueError("carrier roles do not cover the exact swap-event members")
        by_member = {item.member_id: item for item in self.members}
        if set(by_member) != event_members or len(by_member) != 2:
            raise ValueError("carrier must retain exactly both swap-event member fragments")
        bridge = by_member[self.bridge_member_id]
        stationary = by_member[self.stationary_member_id]
        if bridge.role != "bridge" or stationary.role != "stationary":
            raise ValueError("carrier member roles are stale")
        if len(bridge.vias) != 2 or stationary.vias:
            raise ValueError("schema-v1 carrier requires exactly two bridge vias and no others")
        if self.via_cells[0] == self.via_cells[1]:
            raise ValueError("bridge via cells must be distinct")

        expected_members = tuple(
            sorted(
                (
                    _member_from_path(
                        region,
                        stationary.member_id,
                        "stationary",
                        stationary.path_nodes,
                    ),
                    _member_from_path(region, bridge.member_id, "bridge", bridge.path_nodes),
                ),
                key=lambda item: item.member_id,
            )
        )
        if tuple(sorted(self.members, key=lambda item: item.member_id)) != expected_members:
            raise ValueError("carrier geometry or claims do not rederive from retained paths")
        object.__setattr__(self, "members", expected_members)

        derived = _derive_carrier_evidence(region, canonical_initial, expected_members)
        connectivity, containment, clearance, obstacle = derived
        if (
            self.connectivity_evidence != connectivity
            or self.containment_evidence != containment
            or self.clearance_evidence != clearance
            or self.obstacle_evidence != obstacle
        ):
            raise ValueError("carrier evidence does not rederive exactly")
        if clearance.capacity_one_conflicts or obstacle.conflict_resource_ids:
            raise ValueError("a certified carrier cannot retain resource conflicts")

        path_length = _path_length(region, expected_members)
        if self.path_length != path_length:
            raise ValueError("carrier path-length witness is stale")
        maximum, spread, violations = _policy_score(region, self.bridge_member_id)
        if violations:
            raise ValueError("carrier violates physical or bus via policy")
        if (
            maximum != self.resulting_maximum_combined_via_count
            or spread != self.resulting_combined_via_count_spread
        ):
            raise ValueError("carrier combined via accounting is stale")
        via_cells = tuple(
            first[1:]
            for first, second in zip(
                bridge.path_nodes, bridge.path_nodes[1:], strict=False
            )
            if first[0] != second[0]
        )
        if via_cells != self.via_cells:
            raise ValueError("carrier via-cell authority is stale")

        expected_geometry = _geometry_fingerprint(expected_members)
        if self.geometry_fingerprint != expected_geometry:
            raise ValueError("carrier geometry fingerprint is stale")
        expected_carrier = _fingerprint(
            {
                "schema_id": "pcbsmith-certified-bus-swap-carrier-decision",
                "schema_version": 1,
                "carrier": self.model_dump(
                    mode="json", exclude={"carrier_fingerprint"}
                ),
            }
        )
        if self.carrier_fingerprint != expected_carrier:
            raise ValueError("carrier fingerprint is stale")
        return self


class BusSwapCandidateAttempt(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-swap-candidate-attempt"] = (
        "pcbsmith-bus-swap-candidate-attempt"
    )
    schema_version: Literal[1] = 1
    candidate_index: int = Field(ge=0)
    bridge_member_id: str = Field(min_length=1)
    stationary_member_id: str = Field(min_length=1)
    via_cells: tuple[tuple[int, int], tuple[int, int]]
    legal: bool
    failure_reason: BusSwapCarrierFailureReason | None
    expansion_count: int = Field(ge=0)
    claims_built: bool
    policy_violation_count: int = Field(ge=0)
    resulting_maximum_combined_via_count: int = Field(ge=0)
    resulting_combined_via_count_spread: int = Field(ge=0)
    path_length: AlgebraicGridLength | None = None
    geometry_fingerprint: str | None = None
    conflict_resource_ids: tuple[str, ...] = ()
    containment_witnesses: tuple[BusSwapBoundaryContainmentWitness, ...] = ()

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        if self.legal != (self.failure_reason is None):
            raise ValueError("candidate legality and failure reason differ")
        if self.legal and (not self.claims_built or self.path_length is None):
            raise ValueError("a legal candidate requires complete claims and length evidence")
        if self.claims_built != (self.geometry_fingerprint is not None):
            raise ValueError("claim construction and geometry fingerprint must agree")
        witness_ids = tuple(item.primitive_id for item in self.containment_witnesses)
        if len(set(witness_ids)) != len(witness_ids) or witness_ids != tuple(
            sorted(witness_ids)
        ):
            raise ValueError("candidate containment witnesses must be unique and canonical")
        has_failed_containment = any(
            not item.passed for item in self.containment_witnesses
        )
        if (
            self.failure_reason is BusSwapCarrierFailureReason.KEEP_IN_CONFLICT
        ) != has_failed_containment:
            raise ValueError("keep-in failure must equal exact failed containment evidence")
        return self


class BusSwapCarrierGenerationOutcome(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-swap-carrier-outcome"] = (
        "pcbsmith-bus-swap-carrier-outcome"
    )
    schema_version: Literal[1] = 1
    disposition: BusSwapCarrierDisposition
    failure_reason: BusSwapCarrierFailureReason | None
    attempted_candidates: tuple[BusSwapCandidateAttempt, ...]
    carrier: CertifiedBusSwapCarrier | None
    outcome_fingerprint: str

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        generated = self.disposition is BusSwapCarrierDisposition.GENERATED
        if generated != (self.carrier is not None) or generated == (
            self.failure_reason is not None
        ):
            raise ValueError("carrier outcome disposition is incoherent")
        if tuple(item.candidate_index for item in self.attempted_candidates) != tuple(
            range(len(self.attempted_candidates))
        ):
            raise ValueError("candidate attempt indices must be consecutive")
        expected = _fingerprint(
            {
                "schema_id": "pcbsmith-bus-swap-carrier-outcome-decision",
                "schema_version": 1,
                "outcome": self.model_dump(mode="json", exclude={"outcome_fingerprint"}),
            }
        )
        if self.outcome_fingerprint != expected:
            raise ValueError("carrier outcome fingerprint is stale")
        return self


class ReplayBoundCertifiedBusSwapCarrier(RoutingIrModel):
    """Complete input snapshot plus a carrier outcome proven by exact replay."""

    schema_id: Literal["pcbsmith-replay-bound-bus-swap-carrier"] = (
        "pcbsmith-replay-bound-bus-swap-carrier"
    )
    schema_version: Literal[1] = 1
    region: CertifiedBusSwapRegion
    initial_claims: tuple[NetResourceClaims, ...]
    initial_occupancy_fingerprint: str
    outcome: BusSwapCarrierGenerationOutcome

    @field_serializer("initial_claims")
    def serialize_initial_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [_claim_payload(item) for item in claims]

    @model_validator(mode="after")
    def outcome_replays_exactly(self) -> Self:
        region = self.region.require_authority()
        claims = tuple(sorted(self.initial_claims, key=lambda item: item.net_name))
        if len({item.net_name for item in claims}) != len(claims):
            raise ValueError("initial occupancy contains duplicate net identities")
        event_nets = {
            member.net_name
            for member in region.bus.members
            if member.member_id
            in {region.swap_event.first_member_id, region.swap_event.second_member_id}
        }
        if event_nets & {item.net_name for item in claims}:
            raise ValueError("initial occupancy must be foreign to the swap-event members")
        ledger = OccupancyLedger(claims)
        fingerprint = ledger.semantic_fingerprint()
        if fingerprint != self.initial_occupancy_fingerprint:
            raise ValueError("initial occupancy fingerprint is stale")
        replayed = _generate_outcome(region, claims, fingerprint)
        if replayed != self.outcome:
            raise ValueError("retained physical-swap outcome does not equal exact replay")
        object.__setattr__(self, "initial_claims", claims)
        return self


def generate_certified_bus_swap_carrier(
    region: CertifiedBusSwapRegion,
    initial_occupancy: OccupancyLedger,
) -> ReplayBoundCertifiedBusSwapCarrier:
    """Generate one isolated, replay-bound carrier without mutating the caller ledger."""

    claims_before = initial_occupancy.committed_claims()
    fingerprint_before = initial_occupancy.semantic_fingerprint()
    region = region.require_authority()
    outcome = _generate_outcome(region, claims_before, fingerprint_before)
    if (
        initial_occupancy.committed_claims() != claims_before
        or initial_occupancy.semantic_fingerprint() != fingerprint_before
    ):
        raise RuntimeError("physical-swap carrier generation mutated caller occupancy")
    return ReplayBoundCertifiedBusSwapCarrier(
        region=region,
        initial_claims=claims_before,
        initial_occupancy_fingerprint=fingerprint_before,
        outcome=outcome,
    )


def _generate_outcome(
    region: CertifiedBusSwapRegion,
    initial_claims: tuple[NetResourceClaims, ...],
    initial_fingerprint: str,
) -> BusSwapCarrierGenerationOutcome:
    candidates = tuple(
        (bridge, stationary, first, second)
        for bridge, stationary in (
            tuple(sorted((region.swap_event.first_member_id, region.swap_event.second_member_id))),
            tuple(
                reversed(
                    sorted(
                        (
                            region.swap_event.first_member_id,
                            region.swap_event.second_member_id,
                        )
                    )
                )
            ),
        )
        for first in region.allowed_via_cells
        for second in region.allowed_via_cells
        if first != second
    )
    budget = region.physical_policy.budget
    static_claims, static_supported = _static_obstacle_claims(region)
    if not static_supported or not _claims_cover(initial_claims, static_claims):
        return _outcome(
            disposition=BusSwapCarrierDisposition.FAILED,
            failure_reason=BusSwapCarrierFailureReason.STATIC_OBSTACLE_AUTHORITY,
            attempts=(),
            carrier=None,
        )
    if len(candidates) > budget.max_candidates_per_event:
        return _outcome(
            disposition=BusSwapCarrierDisposition.FAILED,
            failure_reason=BusSwapCarrierFailureReason.CANDIDATE_BUDGET,
            attempts=(),
            carrier=None,
        )

    attempts: list[BusSwapCandidateAttempt] = []
    legal: list[tuple[BusSwapCandidateAttempt, CertifiedBusSwapCarrier]] = []
    for index, (bridge, stationary, first, second) in enumerate(candidates):
        attempt, carrier = _attempt_candidate(
            region,
            initial_claims,
            initial_fingerprint,
            index,
            bridge,
            stationary,
            first,
            second,
        )
        attempts.append(attempt)
        if carrier is not None:
            legal.append((attempt, carrier))
    if legal:
        carrier = min(legal, key=cmp_to_key(_compare_legal_candidates))[1]
        return _outcome(
            disposition=BusSwapCarrierDisposition.GENERATED,
            failure_reason=None,
            attempts=tuple(attempts),
            carrier=carrier,
        )
    reasons = {item.failure_reason for item in attempts}
    if BusSwapCarrierFailureReason.EXPANSION_BUDGET in reasons:
        failure = BusSwapCarrierFailureReason.EXPANSION_BUDGET
    elif BusSwapCarrierFailureReason.RESOURCE_CONFLICT in reasons:
        failure = BusSwapCarrierFailureReason.RESOURCE_CONFLICT
    elif BusSwapCarrierFailureReason.POLICY_VIOLATION in reasons:
        failure = BusSwapCarrierFailureReason.POLICY_VIOLATION
    elif BusSwapCarrierFailureReason.KEEP_IN_CONFLICT in reasons:
        failure = BusSwapCarrierFailureReason.KEEP_IN_CONFLICT
    else:
        failure = BusSwapCarrierFailureReason.NO_GRAPH_PATH
    return _outcome(
        disposition=BusSwapCarrierDisposition.FAILED,
        failure_reason=failure,
        attempts=tuple(attempts),
        carrier=None,
    )


def _attempt_candidate(
    region: CertifiedBusSwapRegion,
    initial_claims: tuple[NetResourceClaims, ...],
    initial_fingerprint: str,
    index: int,
    bridge_member_id: str,
    stationary_member_id: str,
    first_via: tuple[int, int],
    second_via: tuple[int, int],
) -> tuple[BusSwapCandidateAttempt, CertifiedBusSwapCarrier | None]:
    maximum, spread, violations = _policy_score(region, bridge_member_id)
    if violations:
        return (
            _attempt(
                index, bridge_member_id, stationary_member_id, first_via, second_via,
                False, BusSwapCarrierFailureReason.POLICY_VIOLATION, 0, False,
                violations, maximum, spread,
            ),
            None,
        )
    portals = {item.member_id: item for item in region.member_portals}
    event_layer = region.swap_event.layer
    bridge_layer = region.bridge_layer
    domains_by_member = {
        member.member_id: grid_claim_domains_for_net(
            member.net_name, member.width_mm, region.rule_profile
        )
        for member in region.bus.members
        if member.member_id in {bridge_member_id, stationary_member_id}
    }
    foreign = OccupancyLedger(initial_claims)
    used = 0
    bridge_parts: list[tuple[LayerGridNode, ...]] = []
    for start, end in (
        (
            (event_layer, *portals[bridge_member_id].incoming_portal_point),
            (event_layer, *first_via),
        ),
        ((bridge_layer, *first_via), (bridge_layer, *second_via)),
        (
            (event_layer, *second_via),
            (event_layer, *portals[bridge_member_id].outgoing_portal_point),
        ),
    ):
        part, used, reason, conflict_ids = _search_path(
            region,
            start,
            end,
            domains_by_member[bridge_member_id],
            foreign,
            used,
        )
        if reason is not None:
            return (
                _attempt(
                    index, bridge_member_id, stationary_member_id, first_via, second_via,
                    False,
                    reason,
                    used,
                    False,
                    violations,
                    maximum,
                    spread,
                    conflict_resource_ids=conflict_ids,
                ),
                None,
            )
        if part is None:
            raise RuntimeError("successful swap path search returned no path")
        bridge_parts.append(part)
    bridge_path = (
        *bridge_parts[0],
        (bridge_layer, *first_via),
        *bridge_parts[1][1:],
        (event_layer, *second_via),
        *bridge_parts[2][1:],
    )
    if len(set(bridge_path)) != len(bridge_path):
        return (
            _attempt(
                index,
                bridge_member_id,
                stationary_member_id,
                first_via,
                second_via,
                False,
                BusSwapCarrierFailureReason.NO_GRAPH_PATH,
                used,
                False,
                violations,
                maximum,
                spread,
            ),
            None,
        )
    bridge_member = _member_from_path(region, bridge_member_id, "bridge", bridge_path)
    bridge_occupancy = OccupancyLedger((*initial_claims, bridge_member.claims))
    stationary_path, used, reason, conflict_ids = _search_path(
        region,
        (event_layer, *portals[stationary_member_id].incoming_portal_point),
        (event_layer, *portals[stationary_member_id].outgoing_portal_point),
        domains_by_member[stationary_member_id],
        bridge_occupancy,
        used,
    )
    if reason is not None:
        partial_geometry_fingerprint = _geometry_fingerprint((bridge_member,))
        return (
            _attempt(
                index,
                bridge_member_id,
                stationary_member_id,
                first_via,
                second_via,
                False,
                reason,
                used,
                True,
                violations,
                maximum,
                spread,
                geometry_fingerprint=partial_geometry_fingerprint,
                conflict_resource_ids=conflict_ids,
            ),
            None,
        )
    if stationary_path is None:
        raise RuntimeError("successful stationary path search returned no path")
    stationary_member = _member_from_path(
        region, stationary_member_id, "stationary", stationary_path
    )
    members = tuple(sorted((stationary_member, bridge_member), key=lambda item: item.member_id))
    containment_witnesses = _copper_keep_in_witnesses(region, members)
    geometry_fingerprint = _geometry_fingerprint(members)
    length = _path_length(region, members)
    if any(not item.passed for item in containment_witnesses):
        return (
            _attempt(
                index,
                bridge_member_id,
                stationary_member_id,
                first_via,
                second_via,
                False,
                BusSwapCarrierFailureReason.KEEP_IN_CONFLICT,
                used,
                True,
                violations,
                maximum,
                spread,
                length,
                geometry_fingerprint,
                containment_witnesses=containment_witnesses,
            ),
            None,
        )
    connectivity, containment, clearance, obstacle = _derive_carrier_evidence(
        region, initial_claims, members
    )
    if clearance.capacity_one_conflicts or obstacle.conflict_resource_ids:
        return (
            _attempt(
                index, bridge_member_id, stationary_member_id, first_via, second_via,
                False, BusSwapCarrierFailureReason.RESOURCE_CONFLICT, used, True,
                violations, maximum, spread, length, geometry_fingerprint,
                clearance.capacity_one_conflicts,
                containment_witnesses,
            ),
            None,
        )
    values: dict[str, Any] = {
        "region": region,
        "initial_claims": initial_claims,
        "initial_occupancy_fingerprint": initial_fingerprint,
        "bridge_member_id": bridge_member_id,
        "stationary_member_id": stationary_member_id,
        "via_cells": (first_via, second_via),
        "members": members,
        "path_length": length,
        "resulting_maximum_combined_via_count": maximum,
        "resulting_combined_via_count_spread": spread,
        "connectivity_evidence": connectivity,
        "containment_evidence": containment,
        "clearance_evidence": clearance,
        "obstacle_evidence": obstacle,
        "geometry_fingerprint": geometry_fingerprint,
    }
    payload = CertifiedBusSwapCarrier.model_construct(
        **values, carrier_fingerprint="0" * 64
    ).model_dump(mode="json", exclude={"carrier_fingerprint"})
    values["carrier_fingerprint"] = _fingerprint(
        {
            "schema_id": "pcbsmith-certified-bus-swap-carrier-decision",
            "schema_version": 1,
            "carrier": payload,
        }
    )
    carrier = CertifiedBusSwapCarrier.model_validate(values)
    return (
        _attempt(
            index, bridge_member_id, stationary_member_id, first_via, second_via,
            True, None, used, True, violations, maximum, spread, length,
            geometry_fingerprint,
            containment_witnesses=containment_witnesses,
        ),
        carrier,
    )


def _search_path(
    region: CertifiedBusSwapRegion,
    start: LayerGridNode,
    end: LayerGridNode,
    domains: tuple[GridClaimDomain, ...],
    foreign: OccupancyLedger,
    used: int,
) -> tuple[
    tuple[LayerGridNode, ...] | None,
    int,
    BusSwapCarrierFailureReason | None,
    tuple[str, ...],
]:
    if start not in region.allowed_nodes or end not in region.allowed_nodes or start[0] != end[0]:
        return None, used, BusSwapCarrierFailureReason.NO_GRAPH_PATH, ()
    adjacency: dict[LayerGridNode, list[LayerGridNode]] = {
        node: [] for node in region.allowed_nodes if node[0] == start[0]
    }
    for first, second in region.allowed_transitions:
        if first[0] == second[0] == start[0]:
            adjacency[first].append(second)
            adjacency[second].append(first)
    pending: list[tuple[int, tuple[LayerGridNode, ...], LayerGridNode]] = [(0, (start,), start)]
    best: dict[LayerGridNode, int] = {start: 0}
    conflict_ids: set[str] = set()
    maximum = region.physical_policy.budget.max_expansions_per_candidate
    while pending:
        if used >= maximum:
            return None, used, BusSwapCarrierFailureReason.EXPANSION_BUDGET, tuple(
                sorted(conflict_ids)
            )
        distance, path, current = heapq.heappop(pending)
        used += 1
        if current == end:
            return path, used, None, ()
        if distance != best.get(current):
            continue
        for neighbour in sorted(adjacency[current]):
            resources: set[RoutingResourceKey] = set()
            for domain in domains:
                resources.update(
                    capsule_segment_claims(
                        domain.domain_id,
                        current[0],
                        (
                            current[1] * region.certificate.grid_mm,
                            current[2] * region.certificate.grid_mm,
                        ),
                        (
                            neighbour[1] * region.certificate.grid_mm,
                            neighbour[2] * region.certificate.grid_mm,
                        ),
                        region.certificate.grid_mm,
                        domain.track_halo_radius_mm,
                    )
                )
            blocked = {
                item
                for item in resources
                if foreign.demand_without(item, "__candidate__")
            }
            if blocked:
                conflict_ids.update(item.resource_id for item in blocked)
                continue
            following = distance + 1
            if following < best.get(neighbour, 2**63 - 1):
                best[neighbour] = following
                heapq.heappush(pending, (following, (*path, neighbour), neighbour))
    reason = (
        BusSwapCarrierFailureReason.RESOURCE_CONFLICT
        if conflict_ids
        else BusSwapCarrierFailureReason.NO_GRAPH_PATH
    )
    return None, used, reason, tuple(sorted(conflict_ids))


def _member_from_path(
    region: CertifiedBusSwapRegion,
    member_id: str,
    role: Literal["stationary", "bridge"],
    path: tuple[LayerGridNode, ...],
) -> BusSwapMemberCarrier:
    member = next(item for item in region.bus.members if item.member_id == member_id)
    portal = next(item for item in region.member_portals if item.member_id == member_id)
    expected_start = (region.swap_event.layer, *portal.incoming_portal_point)
    expected_end = (region.swap_event.layer, *portal.outgoing_portal_point)
    if path[0] != expected_start or path[-1] != expected_end:
        raise ValueError("carrier path endpoints differ from certified member portals")
    if len(set(path)) != len(path):
        raise ValueError("carrier path cannot repeat a lattice node")
    vertical_positions = tuple(
        index
        for index, (first, second) in enumerate(
            zip(path, path[1:], strict=False)
        )
        if first[0] != second[0]
    )
    if role == "stationary":
        if vertical_positions or any(node[0] != region.swap_event.layer for node in path):
            raise ValueError("stationary carrier member must remain on the event layer")
    else:
        if len(vertical_positions) != 2:
            raise ValueError("bridge carrier member requires exactly two layer transitions")
        first_vertical, second_vertical = vertical_positions
        if any(
            node[0] != region.swap_event.layer
            for node in (*path[: first_vertical + 1], *path[second_vertical + 1 :])
        ) or any(
            node[0] != region.bridge_layer
            for node in path[first_vertical + 1 : second_vertical + 1]
        ):
            raise ValueError("bridge carrier layer sequence is not event-bridge-event")
    raw_segments: list[TrackSegment] = []
    vias: list[ViaSpec] = []
    grid = region.certificate.grid_mm

    def coordinate(value: int) -> float:
        return float(Fraction(str(grid)) * value)

    for first, second in zip(path, path[1:], strict=False):
        if first[0] != second[0]:
            if first[1:] != second[1:]:
                raise ValueError("carrier layer transition moved between lattice cells")
            vias.append(
                ViaSpec(
                    x=coordinate(first[1]),
                    y=coordinate(first[2]),
                    net_name=member.net_name,
                    size_mm=region.rule_profile.geometry.routing_via_diameter_mm,
                    drill_mm=region.rule_profile.geometry.routing_via_drill_mm,
                )
            )
        else:
            raw_segments.append(
                TrackSegment(
                    x1=coordinate(first[1]),
                    y1=coordinate(first[2]),
                    x2=coordinate(second[1]),
                    y2=coordinate(second[2]),
                    layer=first[0],
                    net_name=member.net_name,
                    width_mm=member.width_mm,
                )
            )
    segments = merge_collinear_segments(raw_segments)
    domains = grid_claim_domains_for_net(member.net_name, member.width_mm, region.rule_profile)
    claim_parts: list[NetResourceClaims] = []
    for domain in domains:
        resources: set[RoutingResourceKey] = set()
        for segment in segments:
            resources.update(
                capsule_segment_claims(
                    domain.domain_id,
                    cast(LayerName, segment.layer),
                    (segment.x1, segment.y1),
                    (segment.x2, segment.y2),
                    grid,
                    domain.track_halo_radius_mm,
                )
            )
        for via in vias:
            resources.update(
                via_claims(
                    domain.domain_id,
                    round(via.x / grid),
                    round(via.y / grid),
                    grid,
                    domain.via_halo_radius_mm,
                )
            )
        claim_parts.append(NetResourceClaims(member.net_name, frozenset(resources)))
    claims = union_net_resource_claims(member.net_name, *claim_parts)
    return BusSwapMemberCarrier(
        member_id=member_id,
        net_name=member.net_name,
        role=role,
        path_nodes=path,
        segments=segments,
        vias=tuple(vias),
        claims=claims,
    )


def _derive_carrier_evidence(
    region: CertifiedBusSwapRegion,
    initial_claims: tuple[NetResourceClaims, ...],
    members: tuple[BusSwapMemberCarrier, ...],
) -> tuple[
    BusSwapConnectivityEvidence,
    BusSwapContainmentEvidence,
    BusSwapClearanceEvidence,
    BusSwapObstacleEvidence,
]:
    allowed_nodes = set(region.allowed_nodes)
    allowed_edges = set(region.allowed_transitions)
    used_nodes = {node for member in members for node in member.path_nodes}
    used_edges = {
        (first, second) if first < second else (second, first)
        for member in members
        for first, second in zip(
            member.path_nodes, member.path_nodes[1:], strict=False
        )
    }
    if not used_nodes <= allowed_nodes or not used_edges <= allowed_edges:
        raise ValueError("carrier path leaves its explicit region graph")
    containment_witnesses = _copper_keep_in_witnesses(region, members)
    if any(not item.passed for item in containment_witnesses):
        raise ValueError("carrier copper leaves its certified keep-in")
    connectivity = BusSwapConnectivityEvidence(
        member_paths=tuple((item.member_id, item.path_nodes) for item in members),
    )
    containment = BusSwapContainmentEvidence(
        allowed_node_count=len(allowed_nodes),
        used_node_count=len(used_nodes),
        primitive_witnesses=containment_witnesses,
    )
    ledger = OccupancyLedger(initial_claims)
    for member in members:
        ledger.commit(member.claims)
    conflicts = tuple(item.resource_id for item in ledger.overuse())
    generated_claims = tuple(item.claims for item in members)
    domain_ids = tuple(
        (
            item.net_name,
            tuple(sorted({resource.domain_id for resource in item.claims.resources})),
        )
        for item in members
    )
    clearance = BusSwapClearanceEvidence(
        claim_domain_ids_by_net=domain_ids,
        generated_claims=generated_claims,
        capacity_one_conflicts=conflicts,
    )
    initial = OccupancyLedger(initial_claims)
    required_static, supported = _static_obstacle_claims(region)
    if not supported or not _claims_cover(initial_claims, required_static):
        raise ValueError("initial occupancy does not cover exact static copper claims")
    obstacle = BusSwapObstacleEvidence(
        static_obstacle_fingerprint=region.certificate.static_obstacle_fingerprint,
        initial_occupancy_fingerprint=initial.semantic_fingerprint(),
        foreign_net_names=tuple(item.net_name for item in initial_claims),
        required_static_claims=required_static,
        conflict_resource_ids=conflicts,
    )
    return connectivity, containment, clearance, obstacle


def _path_length(
    region: CertifiedBusSwapRegion,
    members: tuple[BusSwapMemberCarrier, ...],
) -> AlgebraicGridLength:
    orthogonal = 0
    diagonal = 0
    for member in members:
        for first, second in zip(
            member.path_nodes, member.path_nodes[1:], strict=False
        ):
            if first[0] != second[0]:
                continue
            dx, dy = abs(first[1] - second[1]), abs(first[2] - second[2])
            diagonal += dx == 1 and dy == 1
            orthogonal += dx + dy == 1
    value = region.certificate.grid_mm * (orthogonal + diagonal * math.sqrt(2))
    return AlgebraicGridLength(
        authority=MetricAuthority.EXACT,
        grid_mm=region.certificate.grid_mm,
        orthogonal_grid_units=orthogonal,
        diagonal_grid_units=diagonal,
        value_mm=value,
    )


RationalPoint = tuple[Fraction, Fraction]


def _copper_keep_in_witnesses(
    region: CertifiedBusSwapRegion,
    members: tuple[BusSwapMemberCarrier, ...],
) -> tuple[BusSwapBoundaryContainmentWitness, ...]:
    """Build exact rational capsule/circle containment witnesses."""

    grid = Fraction(str(region.certificate.grid_mm))
    polygon = tuple((grid * x, grid * y) for x, y in region.keep_in_polygon)
    witnesses: list[BusSwapBoundaryContainmentWitness] = []
    for member in members:
        for index, segment in enumerate(member.segments):
            witnesses.append(
                _rational_boundary_witness(
                    primitive_id=f"{member.member_id}:track:{index:04d}",
                    member_id=member.member_id,
                    primitive_kind="track_capsule",
                    start=(Fraction(str(segment.x1)), Fraction(str(segment.y1))),
                    end=(Fraction(str(segment.x2)), Fraction(str(segment.y2))),
                    radius=Fraction(str(segment.width_mm)) / 2,
                    polygon=polygon,
                )
            )
        for index, via in enumerate(member.vias):
            point = (Fraction(str(via.x)), Fraction(str(via.y)))
            witnesses.append(
                _rational_boundary_witness(
                    primitive_id=f"{member.member_id}:via:{index:04d}",
                    member_id=member.member_id,
                    primitive_kind="via_circle",
                    start=point,
                    end=point,
                    radius=Fraction(str(via.size_mm)) / 2,
                    polygon=polygon,
                )
            )
    return tuple(sorted(witnesses, key=lambda item: item.primitive_id))


def _exact_boundary_witness(
    *,
    primitive_id: str,
    member_id: str,
    primitive_kind: Literal["track_capsule", "via_circle"],
    start: tuple[float, float],
    end: tuple[float, float],
    radius_mm: float,
    polygon: tuple[tuple[float, float], ...],
) -> BusSwapBoundaryContainmentWitness:
    """Test seam: interpret serialized decimal dimensions as exact rationals."""

    return _rational_boundary_witness(
        primitive_id=primitive_id,
        member_id=member_id,
        primitive_kind=primitive_kind,
        start=(Fraction(str(start[0])), Fraction(str(start[1]))),
        end=(Fraction(str(end[0])), Fraction(str(end[1]))),
        radius=Fraction(str(radius_mm)),
        polygon=tuple(
            (Fraction(str(point[0])), Fraction(str(point[1]))) for point in polygon
        ),
    )


def _rational_boundary_witness(
    *,
    primitive_id: str,
    member_id: str,
    primitive_kind: Literal["track_capsule", "via_circle"],
    start: RationalPoint,
    end: RationalPoint,
    radius: Fraction,
    polygon: tuple[RationalPoint, ...],
) -> BusSwapBoundaryContainmentWitness:
    if radius < 0 or len(polygon) < 3:
        raise ValueError("containment witness requires a non-negative radius and polygon")
    edges = tuple(zip(polygon, (*polygon[1:], polygon[0]), strict=True))
    distances = tuple(
        (
            _rational_segment_distance_squared(start, end, edge_start, edge_end),
            index,
        )
        for index, (edge_start, edge_end) in enumerate(edges)
    )
    distance_squared, edge_index = min(distances)
    inside = _rational_point_in_polygon(start, polygon) and _rational_point_in_polygon(
        end, polygon
    )
    radius_squared = radius * radius
    return BusSwapBoundaryContainmentWitness(
        primitive_id=primitive_id,
        member_id=member_id,
        primitive_kind=primitive_kind,
        polygon_edge_index=edge_index,
        centerline_inside_keep_in=inside,
        centerline_distance_squared_numerator=distance_squared.numerator,
        centerline_distance_squared_denominator=distance_squared.denominator,
        required_radius_squared_numerator=radius_squared.numerator,
        required_radius_squared_denominator=radius_squared.denominator,
        passed=inside and distance_squared >= radius_squared,
    )


def _rational_point_in_polygon(
    point: RationalPoint, polygon: tuple[RationalPoint, ...]
) -> bool:
    x, y = point
    inside = False
    for first, second in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
        if _rational_cross(first, second, point) == 0 and _rational_on_segment(
            first, point, second
        ):
            return True
        x1, y1 = first
        x2, y2 = second
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if crossing_x > x:
                inside = not inside
    return inside


def _rational_segment_distance_squared(
    a: RationalPoint,
    b: RationalPoint,
    c: RationalPoint,
    d: RationalPoint,
) -> Fraction:
    if _rational_segments_intersect(a, b, c, d):
        return Fraction(0)
    return min(
        _rational_point_segment_distance_squared(a, c, d),
        _rational_point_segment_distance_squared(b, c, d),
        _rational_point_segment_distance_squared(c, a, b),
        _rational_point_segment_distance_squared(d, a, b),
    )


def _rational_cross(
    first: RationalPoint,
    second: RationalPoint,
    third: RationalPoint,
) -> Fraction:
    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])


def _rational_segments_intersect(
    a: RationalPoint,
    b: RationalPoint,
    c: RationalPoint,
    d: RationalPoint,
) -> bool:
    ab_c, ab_d = _rational_cross(a, b, c), _rational_cross(a, b, d)
    cd_a, cd_b = _rational_cross(c, d, a), _rational_cross(c, d, b)
    if ab_c * ab_d < 0 and cd_a * cd_b < 0:
        return True
    return (
        (ab_c == 0 and _rational_on_segment(a, c, b))
        or (ab_d == 0 and _rational_on_segment(a, d, b))
        or (cd_a == 0 and _rational_on_segment(c, a, d))
        or (cd_b == 0 and _rational_on_segment(c, b, d))
    )


def _rational_on_segment(
    first: RationalPoint, point: RationalPoint, second: RationalPoint
) -> bool:
    return (
        min(first[0], second[0]) <= point[0] <= max(first[0], second[0])
        and min(first[1], second[1]) <= point[1] <= max(first[1], second[1])
    )


def _rational_point_segment_distance_squared(
    point: RationalPoint,
    start: RationalPoint,
    end: RationalPoint,
) -> Fraction:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        offset_x = point[0] - start[0]
        offset_y = point[1] - start[1]
        return offset_x * offset_x + offset_y * offset_y
    projection_numerator = (point[0] - start[0]) * dx + (
        point[1] - start[1]
    ) * dy
    if projection_numerator <= 0:
        offset_x = point[0] - start[0]
        offset_y = point[1] - start[1]
        return offset_x * offset_x + offset_y * offset_y
    if projection_numerator >= length_squared:
        offset_x = point[0] - end[0]
        offset_y = point[1] - end[1]
        return offset_x * offset_x + offset_y * offset_y
    cross = _rational_cross(start, end, point)
    return cross * cross / length_squared


def _static_obstacle_claims(
    region: CertifiedBusSwapRegion,
) -> tuple[tuple[NetResourceClaims, ...], bool]:
    """Raster exact neutral static copper into the same R2 claim domains."""

    profile = region.rule_profile
    grid = region.certificate.grid_mm
    resources_by_net: dict[str, set[RoutingResourceKey]] = {}
    for segment in region.layout.segments:
        domains = grid_claim_domains_for_net(segment.net_name, segment.width_mm, profile)
        resources = resources_by_net.setdefault(segment.net_name, set())
        for domain in domains:
            resources.update(
                capsule_segment_claims(
                    domain.domain_id,
                    cast(LayerName, segment.layer),
                    (segment.x1, segment.y1),
                    (segment.x2, segment.y2),
                    grid,
                    domain.track_halo_radius_mm,
                )
            )
    for via in region.layout.vias:
        if not (
            Fraction(str(via.size_mm))
            == Fraction(str(profile.geometry.routing_via_diameter_mm))
            and Fraction(str(via.drill_mm))
            == Fraction(str(profile.geometry.routing_via_drill_mm))
        ):
            return (), False
        rational_grid = Fraction(str(grid))
        x_grid = Fraction(str(via.x)) / rational_grid
        y_grid = Fraction(str(via.y)) / rational_grid
        if x_grid.denominator != 1 or y_grid.denominator != 1:
            return (), False
        domains = grid_claim_domains_for_net(
            via.net_name, profile.geometry.minimum_trace_width_mm, profile
        )
        resources = resources_by_net.setdefault(via.net_name, set())
        for domain in domains:
            resources.update(
                via_claims(
                    domain.domain_id,
                    x_grid.numerator,
                    y_grid.numerator,
                    grid,
                    domain.via_halo_radius_mm,
                )
            )
    return (
        tuple(
            NetResourceClaims(net_name, frozenset(resources_by_net[net_name]))
            for net_name in sorted(resources_by_net)
        ),
        True,
    )


def _claims_cover(
    initial_claims: tuple[NetResourceClaims, ...],
    required_claims: tuple[NetResourceClaims, ...],
) -> bool:
    supplied = {item.net_name: item.resources for item in initial_claims}
    return all(
        item.resources <= supplied.get(item.net_name, frozenset())
        for item in required_claims
    )


def _policy_score(region: CertifiedBusSwapRegion, bridge_member_id: str) -> tuple[int, int, int]:
    semantic = {item.member_id: item.via_count for item in region.allocation.via_counts}
    physical = {member_id: 0 for member_id in semantic}
    physical[bridge_member_id] = 2
    combined = {member_id: semantic[member_id] + physical[member_id] for member_id in semantic}
    maximum = max(combined.values(), default=0)
    spread = maximum - min(combined.values(), default=0)
    policy = region.physical_policy
    bus_policy = region.bus.layer_policy.via_policy
    violations = sum(
        (
            physical[bridge_member_id] > policy.maximum_physical_vias_per_member,
            maximum > policy.maximum_combined_vias_per_member,
            spread > policy.maximum_combined_via_count_spread,
            maximum > bus_policy.maximum_vias_per_member,
            bus_policy.maximum_via_count_spread is not None
            and spread > bus_policy.maximum_via_count_spread,
        )
    )
    return maximum, spread, violations


def _geometry_fingerprint(members: tuple[BusSwapMemberCarrier, ...]) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-swap-carrier-geometry",
            "schema_version": 1,
            "members": [item.model_dump(mode="json") for item in members],
        }
    )


def _compare_legal_candidates(
    first: tuple[BusSwapCandidateAttempt, CertifiedBusSwapCarrier],
    second: tuple[BusSwapCandidateAttempt, CertifiedBusSwapCarrier],
) -> int:
    first_attempt, _ = first
    second_attempt, _ = second
    leading_first = (
        first_attempt.policy_violation_count,
        first_attempt.resulting_maximum_combined_via_count,
        first_attempt.resulting_combined_via_count_spread,
    )
    leading_second = (
        second_attempt.policy_violation_count,
        second_attempt.resulting_maximum_combined_via_count,
        second_attempt.resulting_combined_via_count_spread,
    )
    if leading_first != leading_second:
        return -1 if leading_first < leading_second else 1
    if first_attempt.path_length is None or second_attempt.path_length is None:
        raise RuntimeError("legal physical-swap candidate lacks a path-length witness")
    length_order = _compare_exact_grid_lengths(
        first_attempt.path_length, second_attempt.path_length
    )
    if length_order:
        return length_order
    trailing_first = (
        first_attempt.expansion_count,
        first_attempt.bridge_member_id,
        first_attempt.via_cells,
        first_attempt.geometry_fingerprint or "",
    )
    trailing_second = (
        second_attempt.expansion_count,
        second_attempt.bridge_member_id,
        second_attempt.via_cells,
        second_attempt.geometry_fingerprint or "",
    )
    return (trailing_first > trailing_second) - (trailing_first < trailing_second)


def _compare_exact_grid_lengths(
    first: AlgebraicGridLength, second: AlgebraicGridLength
) -> int:
    """Compare equal-grid ``a + b*sqrt(2)`` witnesses without floats."""

    if Fraction(str(first.grid_mm)) != Fraction(str(second.grid_mm)):
        raise ValueError("physical-swap candidates must use one certified grid")
    rational = first.orthogonal_grid_units - second.orthogonal_grid_units
    radical = first.diagonal_grid_units - second.diagonal_grid_units
    if rational == 0:
        return (radical > 0) - (radical < 0)
    if radical == 0 or (rational > 0) == (radical > 0):
        return (rational > 0) - (rational < 0)
    squared_difference = rational * rational - 2 * radical * radical
    if rational > 0:
        return (squared_difference > 0) - (squared_difference < 0)
    return (squared_difference < 0) - (squared_difference > 0)


def _attempt(
    index: int,
    bridge: str,
    stationary: str,
    first: tuple[int, int],
    second: tuple[int, int],
    legal: bool,
    reason: BusSwapCarrierFailureReason | None,
    expansions: int,
    claims_built: bool,
    violations: int,
    maximum: int,
    spread: int,
    length: AlgebraicGridLength | None = None,
    geometry_fingerprint: str | None = None,
    conflict_resource_ids: tuple[str, ...] = (),
    containment_witnesses: tuple[BusSwapBoundaryContainmentWitness, ...] = (),
) -> BusSwapCandidateAttempt:
    return BusSwapCandidateAttempt(
        candidate_index=index,
        bridge_member_id=bridge,
        stationary_member_id=stationary,
        via_cells=(first, second),
        legal=legal,
        failure_reason=reason,
        expansion_count=expansions,
        claims_built=claims_built,
        policy_violation_count=violations,
        resulting_maximum_combined_via_count=maximum,
        resulting_combined_via_count_spread=spread,
        path_length=length,
        geometry_fingerprint=geometry_fingerprint,
        conflict_resource_ids=tuple(sorted(set(conflict_resource_ids))),
        containment_witnesses=tuple(
            sorted(containment_witnesses, key=lambda item: item.primitive_id)
        ),
    )


def _outcome(
    *,
    disposition: BusSwapCarrierDisposition,
    failure_reason: BusSwapCarrierFailureReason | None,
    attempts: tuple[BusSwapCandidateAttempt, ...],
    carrier: CertifiedBusSwapCarrier | None,
) -> BusSwapCarrierGenerationOutcome:
    values: dict[str, Any] = {
        "disposition": disposition,
        "failure_reason": failure_reason,
        "attempted_candidates": attempts,
        "carrier": carrier,
    }
    payload = BusSwapCarrierGenerationOutcome.model_construct(
        **values, outcome_fingerprint="0" * 64
    ).model_dump(mode="json", exclude={"outcome_fingerprint"})
    values["outcome_fingerprint"] = _fingerprint(
        {
            "schema_id": "pcbsmith-bus-swap-carrier-outcome-decision",
            "schema_version": 1,
            "outcome": payload,
        }
    )
    return BusSwapCarrierGenerationOutcome.model_validate(values)
