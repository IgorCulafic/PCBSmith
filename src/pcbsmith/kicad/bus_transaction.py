"""Atomic whole-bus route replacement over the negotiated occupancy ledger.

This module deliberately contains no geometry search.  It binds complete R4
bus/allocation decisions to complete R2 member routes and provides the group
transaction that a later bus router can call after producing a candidate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, MutableMapping
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_serializer, field_validator, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_ir import BusGroup
from pcbsmith.kicad.astar_router import RoutingError
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import NetResourceClaims, OccupancyLedger
from pcbsmith.routing_ir import ResourceOveruseSummary, RoutingFailureReason, RoutingIrModel


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def _route_payload(route: NegotiatedGridRoute) -> dict[str, Any]:
    return {
        "net_name": route.result.net_name,
        "segments": [
            {
                "start_mm": (segment.x1, segment.y1),
                "end_mm": (segment.x2, segment.y2),
                "layer": segment.layer,
                "net_name": segment.net_name,
                "width_mm": segment.width_mm,
            }
            for segment in route.result.segments
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
            for via in route.result.vias
        ],
        "length_mm": route.result.length_mm,
        "expansion_count": route.result.expansion_count,
        "claim_resource_ids": sorted(resource.resource_id for resource in route.claims.resources),
        "base_cost_units": route.base_cost_units,
        "congestion_cost_units": route.congestion_cost_units,
        "guidance_cost_units": route.guidance_cost_units,
        "prefix_alternative_id": route.prefix_alternative_id,
        "prefix_fingerprint": route.prefix_fingerprint,
    }


def negotiated_grid_route_fingerprint(route: NegotiatedGridRoute) -> str:
    """Fingerprint one complete detailed member route and its resource claim."""

    return _fingerprint(
        {
            "schema_id": "pcbsmith-negotiated-grid-route",
            "schema_version": 1,
            "route": _route_payload(route),
        }
    )


def bus_route_map_fingerprint(routes_by_net: Mapping[str, NegotiatedGridRoute]) -> str:
    """Fingerprint a complete caller-owned route map independent of input order."""

    entries: list[dict[str, str]] = []
    for net_name in sorted(routes_by_net):
        route = routes_by_net[net_name]
        if net_name != route.result.net_name or net_name != route.claims.net_name:
            raise ValueError("route-map keys must match route and claim net ownership")
        entries.append(
            {
                "net_name": net_name,
                "route_fingerprint": negotiated_grid_route_fingerprint(route),
            }
        )
    return _fingerprint(
        {
            "schema_id": "pcbsmith-negotiated-route-map",
            "schema_version": 1,
            "routes": entries,
        }
    )


def _claim_payload(claim: NetResourceClaims) -> dict[str, Any]:
    return {
        "net_name": claim.net_name,
        "resources": [
            {
                "domain_id": resource.domain_id,
                "layer": resource.layer,
                "kind": resource.kind,
                "ix0": resource.ix0,
                "iy0": resource.iy0,
                "ix1": resource.ix1,
                "iy1": resource.iy1,
            }
            for resource in sorted(claim.resources)
        ],
    }


def _complete_route_payload(route: NegotiatedGridRoute) -> dict[str, Any]:
    return {
        "result": {
            "net_name": route.result.net_name,
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
                for segment in route.result.segments
            ],
            "vias": [
                {
                    "x": via.x,
                    "y": via.y,
                    "net_name": via.net_name,
                    "size_mm": via.size_mm,
                    "drill_mm": via.drill_mm,
                    "front_mask": via.front_mask.value,
                    "back_mask": via.back_mask.value,
                }
                for via in route.result.vias
            ],
            "length_mm": route.result.length_mm,
            "expansion_count": route.result.expansion_count,
        },
        "claims": _claim_payload(route.claims),
        "base_cost_units": route.base_cost_units,
        "congestion_cost_units": route.congestion_cost_units,
        "guidance_cost_units": route.guidance_cost_units,
        "prefix_alternative_id": route.prefix_alternative_id,
        "prefix_fingerprint": route.prefix_fingerprint,
    }


class BusRouteStateSnapshot(RoutingIrModel):
    """Complete reconstructible route-map and occupancy state at one boundary."""

    schema_id: Literal["pcbsmith-bus-route-state-snapshot"] = (
        "pcbsmith-bus-route-state-snapshot"
    )
    schema_version: Literal[1] = 1
    routes: tuple[NegotiatedGridRoute, ...]
    claims: tuple[NetResourceClaims, ...]
    route_map_fingerprint: str
    ledger_fingerprint: str

    @field_validator("route_map_fingerprint", "ledger_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @field_serializer("routes")
    def serialize_routes(self, routes: tuple[NegotiatedGridRoute, ...]) -> list[dict[str, Any]]:
        return [_complete_route_payload(route) for route in routes]

    @field_serializer("claims")
    def serialize_claims(self, claims: tuple[NetResourceClaims, ...]) -> list[dict[str, Any]]:
        return [_claim_payload(claim) for claim in claims]

    @model_validator(mode="after")
    def state_is_complete_and_reconstructible(self) -> Self:
        route_names = tuple(route.result.net_name for route in self.routes)
        claim_names = tuple(claim.net_name for claim in self.claims)
        if len(set(route_names)) != len(route_names):
            raise ValueError("route state contains duplicate route net identities")
        if len(set(claim_names)) != len(claim_names):
            raise ValueError("route state contains duplicate claim net identities")

        routes_by_net: dict[str, NegotiatedGridRoute] = {}
        for route in self.routes:
            net_name = route.result.net_name
            if route.claims.net_name != net_name:
                raise ValueError("route state route and claim ownership must match")
            if any(segment.net_name != net_name for segment in route.result.segments) or any(
                via.net_name != net_name for via in route.result.vias
            ):
                raise ValueError("route state copper geometry must match its route net")
            routes_by_net[net_name] = route
        claims_by_net = {claim.net_name: claim for claim in self.claims}
        if set(routes_by_net) != set(claims_by_net):
            raise ValueError("route state route and claim net sets must be equal")
        if any(
            route.claims != claims_by_net[net_name]
            for net_name, route in routes_by_net.items()
        ):
            raise ValueError("route state retained claims must equal every route claim")

        canonical_routes = tuple(routes_by_net[name] for name in sorted(routes_by_net))
        canonical_claims = tuple(claims_by_net[name] for name in sorted(claims_by_net))
        reconstructed_route_fingerprint = bus_route_map_fingerprint(routes_by_net)
        reconstructed_ledger_fingerprint = OccupancyLedger(
            canonical_claims
        ).semantic_fingerprint()
        if self.route_map_fingerprint != reconstructed_route_fingerprint:
            raise ValueError("route state route-map fingerprint is stale")
        if self.ledger_fingerprint != reconstructed_ledger_fingerprint:
            raise ValueError("route state ledger fingerprint is stale")
        object.__setattr__(self, "routes", canonical_routes)
        object.__setattr__(self, "claims", canonical_claims)
        return self

    @classmethod
    def from_state(
        cls,
        ledger: OccupancyLedger,
        routes_by_net: Mapping[str, NegotiatedGridRoute],
    ) -> BusRouteStateSnapshot:
        """Capture and JSON-reconstruct one complete caller state."""

        for key, route in routes_by_net.items():
            if key != route.result.net_name or key != route.claims.net_name:
                raise ValueError("route-map keys must match route and claim net ownership")
        snapshot = cls(
            routes=tuple(routes_by_net.values()),
            claims=ledger.committed_claims(),
            route_map_fingerprint=bus_route_map_fingerprint(routes_by_net),
            ledger_fingerprint=ledger.semantic_fingerprint(),
        )
        reconstructed = cls.model_validate_json(snapshot.model_dump_json())
        if reconstructed != snapshot:
            raise ValueError("route state failed exact JSON reconstruction")
        return reconstructed


class BusRouteBundle(RoutingIrModel):
    """One complete, immutable detailed-route candidate for every bus member."""

    bus: BusGroup
    allocation: BusLaneAllocationResult
    member_routes: tuple[NegotiatedGridRoute, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def binding_is_complete_and_coherent(self) -> Self:
        if not self.allocation.success:
            raise ValueError("a bus route bundle requires a successful lane allocation")
        if self.allocation.bus_fingerprint != self.bus.semantic_fingerprint():
            raise ValueError("lane allocation must bind the exact bus fingerprint")

        member_by_net = {member.net_name: member for member in self.bus.members}
        member_by_id = {member.member_id: member for member in self.bus.members}
        routes_by_net: dict[str, NegotiatedGridRoute] = {}
        for route in self.member_routes:
            net_name = route.result.net_name
            if net_name in routes_by_net:
                raise ValueError("bus bundle route nets must be unique")
            if route.claims.net_name != net_name:
                raise ValueError("bus bundle route and claim ownership must match")
            if any(segment.net_name != net_name for segment in route.result.segments) or any(
                via.net_name != net_name for via in route.result.vias
            ):
                raise ValueError("all bus bundle copper geometry must belong to its member net")
            if (route.prefix_alternative_id is None) != (route.prefix_fingerprint is None):
                raise ValueError("bus bundle prefix identity must be complete or absent")
            routes_by_net[net_name] = route
        if set(routes_by_net) != set(member_by_net):
            raise ValueError("bus bundle must contain exactly one route for every member net")

        assigned_member_ids: set[str] = set()
        for assignment in self.allocation.assignments:
            member = member_by_id.get(assignment.member_id)
            if member is None or member.net_name != assignment.net_name:
                raise ValueError("lane assignment references a foreign member or net")
            assigned_member_ids.add(member.member_id)
        if assigned_member_ids != set(member_by_id):
            raise ValueError("lane allocation must assign every bus member")

        object.__setattr__(
            self,
            "member_routes",
            tuple(routes_by_net[net_name] for net_name in sorted(routes_by_net)),
        )
        return self

    def semantic_fingerprint(self) -> str:
        """Fingerprint the complete bus/allocation/route binding."""

        return _fingerprint(
            {
                "schema_id": "pcbsmith-bus-route-bundle",
                "schema_version": 1,
                "bus_fingerprint": self.bus.semantic_fingerprint(),
                "allocation_fingerprint": self.allocation.allocation_fingerprint,
                "allocation_result_fingerprint": self.allocation.semantic_fingerprint(),
                "member_routes": [
                    {
                        "net_name": route.result.net_name,
                        "route_fingerprint": negotiated_grid_route_fingerprint(route),
                    }
                    for route in self.member_routes
                ],
            }
        )

    def by_net(self) -> dict[str, NegotiatedGridRoute]:
        return {route.result.net_name: route for route in self.member_routes}


class BusTransactionDisposition(StrEnum):
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


class BusTransactionFailureKind(StrEnum):
    ROUTING_ERROR = "routing_error"
    VALIDATION_ERROR = "validation_error"
    EXCEPTION = "exception"


class BusRouteTransactionTelemetry(RoutingIrModel):
    """Deterministic audit record for one committed or rolled-back attempt."""

    schema_id: Literal["pcbsmith-bus-route-transaction-telemetry"] = (
        "pcbsmith-bus-route-transaction-telemetry"
    )
    schema_version: Literal[2] = 2
    bus_id: str = Field(min_length=1)
    bus_fingerprint: str
    allocation_fingerprint: str
    disposition: BusTransactionDisposition
    old_bundle_fingerprint: str
    candidate_bundle_fingerprint: str | None = None
    before_state: BusRouteStateSnapshot
    after_state: BusRouteStateSnapshot
    ledger_before_fingerprint: str
    ledger_after_fingerprint: str
    route_map_before_fingerprint: str
    route_map_after_fingerprint: str
    capacity_overuse: tuple[ResourceOveruseSummary, ...] = ()
    failure_kind: BusTransactionFailureKind | None = None
    failure_type: str | None = None
    routing_failure_reason: RoutingFailureReason | None = None
    expansion_count: int = Field(default=0, ge=0)

    @field_validator(
        "bus_fingerprint",
        "allocation_fingerprint",
        "old_bundle_fingerprint",
        "candidate_bundle_fingerprint",
        "ledger_before_fingerprint",
        "ledger_after_fingerprint",
        "route_map_before_fingerprint",
        "route_map_after_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        overuse = tuple(sorted(self.capacity_overuse, key=lambda item: item.resource_id))
        if (
            self.ledger_before_fingerprint != self.before_state.ledger_fingerprint
            or self.route_map_before_fingerprint != self.before_state.route_map_fingerprint
            or self.ledger_after_fingerprint != self.after_state.ledger_fingerprint
            or self.route_map_after_fingerprint != self.after_state.route_map_fingerprint
        ):
            raise ValueError("transaction fingerprints must equal retained state snapshots")
        if self.disposition is BusTransactionDisposition.COMMITTED:
            if self.candidate_bundle_fingerprint is None or self.failure_kind is not None:
                raise ValueError("committed transaction requires a candidate and no failure")
            if self.failure_type is not None or self.routing_failure_reason is not None:
                raise ValueError("committed transaction cannot retain failure details")
        else:
            if self.failure_kind is None or not self.failure_type:
                raise ValueError("rolled-back transaction requires typed failure telemetry")
            if self.ledger_before_fingerprint != self.ledger_after_fingerprint:
                raise ValueError("rolled-back transaction must restore the exact ledger")
            if self.route_map_before_fingerprint != self.route_map_after_fingerprint:
                raise ValueError("rolled-back transaction must restore the exact route map")
            if self.before_state != self.after_state:
                raise ValueError("rolled-back transaction must restore the complete route state")
            if overuse:
                raise ValueError("rolled-back telemetry reports the restored state, not candidates")
        if self.failure_kind is BusTransactionFailureKind.ROUTING_ERROR:
            if self.routing_failure_reason is None:
                raise ValueError("routing-error telemetry requires a routing failure reason")
        elif self.routing_failure_reason is not None or self.expansion_count:
            raise ValueError("only routing errors may report routing work or failure reason")
        object.__setattr__(self, "capacity_overuse", overuse)
        return self


class BusRouteTransactionCoordinator:
    """Replace all bus member routes as one ledger/route-map transaction.

    A committed candidate may still contain capacity overuse.  Commit records
    only transactional state; it is not an exact-check or acceptance verdict.
    """

    def __init__(
        self,
        ledger: OccupancyLedger,
        routes_by_net: MutableMapping[str, NegotiatedGridRoute],
    ) -> None:
        self.ledger = ledger
        self.routes_by_net = routes_by_net
        self.last_attempt: BusRouteTransactionTelemetry | None = None

    def replace(
        self,
        bus: BusGroup,
        allocation: BusLaneAllocationResult,
        search: Callable[[], BusRouteBundle],
    ) -> BusRouteBundle:
        """Rip up a complete old bundle and commit a complete replacement.

        ``RoutingError`` and all ordinary exceptions are re-raised after every
        old member route and claim has been restored.  ``last_attempt`` retains
        the deterministic rollback telemetry for the caller.
        """

        old_bundle = self._current_bundle(bus, allocation)
        old_routes = old_bundle.by_net()
        for net_name, route in old_routes.items():
            if self.ledger.claims_for(net_name) != route.claims:
                raise ValueError("ledger claims must equal every current bus member route claim")

        before_state = BusRouteStateSnapshot.from_state(self.ledger, self.routes_by_net)
        ledger_before = before_state.ledger_fingerprint
        route_map_before = before_state.route_map_fingerprint
        old_bundle_fingerprint = old_bundle.semantic_fingerprint()
        member_nets = tuple(sorted(old_routes))
        for net_name in member_nets:
            self.ledger.rip_up(net_name)
            del self.routes_by_net[net_name]

        candidate: BusRouteBundle | None = None
        candidate_fingerprint: str | None = None
        try:
            candidate = search()
            candidate_fingerprint = candidate.semantic_fingerprint()
            self._require_candidate_binding(candidate, bus, allocation)
            for route in candidate.member_routes:
                self.ledger.commit(route.claims)
                self.routes_by_net[route.result.net_name] = route
        except Exception as error:
            for net_name in member_nets:
                self.ledger.rip_up(net_name)
                self.routes_by_net.pop(net_name, None)
            for net_name in member_nets:
                route = old_routes[net_name]
                self.ledger.restore(route.claims)
                self.routes_by_net[net_name] = route
            self.last_attempt = self._rollback_telemetry(
                bus,
                allocation,
                error,
                old_bundle_fingerprint=old_bundle_fingerprint,
                candidate_fingerprint=candidate_fingerprint,
                before_state=before_state,
            )
            raise

        assert candidate is not None
        after_state = BusRouteStateSnapshot.from_state(self.ledger, self.routes_by_net)
        self.last_attempt = BusRouteTransactionTelemetry(
            bus_id=bus.bus_id,
            bus_fingerprint=bus.semantic_fingerprint(),
            allocation_fingerprint=allocation.allocation_fingerprint,
            disposition=BusTransactionDisposition.COMMITTED,
            old_bundle_fingerprint=old_bundle_fingerprint,
            candidate_bundle_fingerprint=candidate_fingerprint,
            before_state=before_state,
            after_state=after_state,
            ledger_before_fingerprint=ledger_before,
            ledger_after_fingerprint=after_state.ledger_fingerprint,
            route_map_before_fingerprint=route_map_before,
            route_map_after_fingerprint=after_state.route_map_fingerprint,
            capacity_overuse=self.ledger.overuse(),
        )
        return candidate

    def _current_bundle(
        self,
        bus: BusGroup,
        allocation: BusLaneAllocationResult,
    ) -> BusRouteBundle:
        routes: list[NegotiatedGridRoute] = []
        missing: list[str] = []
        for member in bus.members:
            route = self.routes_by_net.get(member.net_name)
            if route is None:
                missing.append(member.net_name)
            else:
                routes.append(route)
        if missing:
            raise ValueError(
                f"current bus route map is incomplete for nets {tuple(sorted(missing))!r}"
            )
        return BusRouteBundle(bus=bus, allocation=allocation, member_routes=tuple(routes))

    @staticmethod
    def _require_candidate_binding(
        candidate: BusRouteBundle,
        bus: BusGroup,
        allocation: BusLaneAllocationResult,
    ) -> None:
        if candidate.bus.semantic_fingerprint() != bus.semantic_fingerprint():
            raise ValueError("candidate bundle binds a different bus")
        if candidate.allocation.semantic_fingerprint() != allocation.semantic_fingerprint():
            raise ValueError("candidate bundle binds a different lane allocation")

    def _rollback_telemetry(
        self,
        bus: BusGroup,
        allocation: BusLaneAllocationResult,
        error: Exception,
        *,
        old_bundle_fingerprint: str,
        candidate_fingerprint: str | None,
        before_state: BusRouteStateSnapshot,
    ) -> BusRouteTransactionTelemetry:
        if isinstance(error, RoutingError):
            failure_kind = BusTransactionFailureKind.ROUTING_ERROR
            routing_reason = error.reason
            expansion_count = error.expansion_count
        elif isinstance(error, (TypeError, ValueError)):
            failure_kind = BusTransactionFailureKind.VALIDATION_ERROR
            routing_reason = None
            expansion_count = 0
        else:
            failure_kind = BusTransactionFailureKind.EXCEPTION
            routing_reason = None
            expansion_count = 0
        after_state = BusRouteStateSnapshot.from_state(self.ledger, self.routes_by_net)
        return BusRouteTransactionTelemetry(
            bus_id=bus.bus_id,
            bus_fingerprint=bus.semantic_fingerprint(),
            allocation_fingerprint=allocation.allocation_fingerprint,
            disposition=BusTransactionDisposition.ROLLED_BACK,
            old_bundle_fingerprint=old_bundle_fingerprint,
            candidate_bundle_fingerprint=candidate_fingerprint,
            before_state=before_state,
            after_state=after_state,
            ledger_before_fingerprint=before_state.ledger_fingerprint,
            ledger_after_fingerprint=after_state.ledger_fingerprint,
            route_map_before_fingerprint=before_state.route_map_fingerprint,
            route_map_after_fingerprint=after_state.route_map_fingerprint,
            failure_kind=failure_kind,
            failure_type=f"{type(error).__module__}.{type(error).__qualname__}",
            routing_failure_reason=routing_reason,
            expansion_count=expansion_count,
        )
