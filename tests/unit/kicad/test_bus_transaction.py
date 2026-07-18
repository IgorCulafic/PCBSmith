from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.bus_allocator import (
    BusAllocationBudget,
    BusLaneAllocationResult,
    BusLaneAssignment,
    bus_lane_allocation_fingerprint,
)
from pcbsmith.bus_ir import (
    BoundaryMemberRef,
    BusBoundary,
    BusGroup,
    BusLayerPolicy,
    BusMember,
    BusPermutationPolicy,
    BusTerminalRef,
    BusViaPolicy,
)
from pcbsmith.kicad.astar_router import RouteResult, RoutingError
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.bus_transaction import (
    BusRouteBundle,
    BusRouteStateSnapshot,
    BusRouteTransactionCoordinator,
    BusRouteTransactionTelemetry,
    BusTransactionDisposition,
    BusTransactionFailureKind,
    bus_route_map_fingerprint,
)
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.routing_ir import RoutingFailureReason


def _member(member_id: str, net_name: str) -> BusMember:
    return BusMember(
        member_id=member_id,
        net_name=net_name,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net_name,
                component_ref="U1",
                pad_number="1",
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net_name,
                component_ref="U2",
                pad_number="1",
                role="sink",
            ),
        ),
        width_mm=0.2,
    )


def _bus() -> BusGroup:
    members = (_member("a", "/A"), _member("b", "/B"))

    def boundary(boundary_id: str, role: str) -> BusBoundary:
        return BusBoundary(
            boundary_id=boundary_id,
            corridor_portal_id=f"portal:{boundary_id}",
            orientation="forward",
            ordered_members=tuple(
                BoundaryMemberRef(
                    member_id=member.member_id,
                    terminal_ids=(f"{member.member_id}:{role}",),
                )
                for member in members
            ),
        )

    return BusGroup(
        bus_id="pair",
        members=members,
        boundaries=(boundary("entry", "source"), boundary("exit", "sink")),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        rule_profile_id="default-two-layer",
    )


def _allocation(bus: BusGroup) -> BusLaneAllocationResult:
    assignments = tuple(
        BusLaneAssignment(
            section_id="trunk",
            member_id=member.member_id,
            net_name=member.net_name,
            slot_id=f"lane:{index}",
            layer="F.Cu",
            order_index=index,
        )
        for index, member in enumerate(bus.members)
    )
    orders = tuple(
        tuple(item.member_id for item in boundary.ordered_members) for boundary in bus.boundaries
    )
    bus_fingerprint = bus.semantic_fingerprint()
    certificate_fingerprint = "c" * 64
    return BusLaneAllocationResult(
        success=True,
        bus_fingerprint=bus_fingerprint,
        certificate_fingerprint=certificate_fingerprint,
        budget=BusAllocationBudget(max_states=10),
        state_count=1,
        reversal_count=0,
        swap_count=0,
        activation_count=0,
        layer_transition_count=0,
        normalized_boundary_orders=orders,
        assignments=assignments,
        allocation_fingerprint=bus_lane_allocation_fingerprint(
            bus_fingerprint=bus_fingerprint,
            certificate_fingerprint=certificate_fingerprint,
            normalized_boundary_orders=orders,
            assignments=assignments,
        ),
    )


def _resource(ix: int) -> RoutingResourceKey:
    return RoutingResourceKey("ordinary", "F.Cu", "cell", ix, 1)


def _route(
    net_name: str,
    ix: int,
    *,
    resource: RoutingResourceKey | None = None,
    geometry_net_name: str | None = None,
) -> NegotiatedGridRoute:
    claims = NetResourceClaims(net_name, frozenset((resource or _resource(ix),)))
    return NegotiatedGridRoute(
        result=RouteResult(
            net_name=net_name,
            segments=(
                TrackSegment(
                    float(ix),
                    1.0,
                    float(ix + 1),
                    1.0,
                    "F.Cu",
                    geometry_net_name or net_name,
                    0.2,
                ),
            ),
            vias=(),
            length_mm=1.0,
            expansion_count=ix,
        ),
        claims=claims,
        base_cost_units=ix,
        congestion_cost_units=0,
    )


def _state() -> tuple[
    BusGroup,
    BusLaneAllocationResult,
    OccupancyLedger,
    dict[str, NegotiatedGridRoute],
]:
    bus = _bus()
    allocation = _allocation(bus)
    routes = {"/A": _route("/A", 1), "/B": _route("/B", 2)}
    ledger = OccupancyLedger(route.claims for route in routes.values())
    return bus, allocation, ledger, routes


def _bundle(
    bus: BusGroup,
    allocation: BusLaneAllocationResult,
    *routes: NegotiatedGridRoute,
) -> BusRouteBundle:
    return BusRouteBundle(bus=bus, allocation=allocation, member_routes=routes)


def test_successful_group_replacement_removes_every_old_only_claim() -> None:
    bus, allocation, ledger, route_map = _state()
    old_resources = frozenset(
        resource for route in route_map.values() for resource in route.claims.resources
    )
    replacement = _bundle(bus, allocation, _route("/B", 12), _route("/A", 11))
    coordinator = BusRouteTransactionCoordinator(ledger, route_map)

    committed = coordinator.replace(bus, allocation, lambda: replacement)

    assert committed == replacement
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.disposition is BusTransactionDisposition.COMMITTED
    assert coordinator.last_attempt.capacity_overuse == ()
    assert not any(
        resource in old_resources
        for claims in ledger.committed_claims()
        for resource in claims.resources
    )
    assert route_map == replacement.by_net()
    assert (
        committed.semantic_fingerprint()
        == "8e137ab2503406ca2983a7f0bc17b43fefa0ce003951e55f88ae14ec3eac121e"
    )


def test_late_follower_routing_failure_restores_every_route_claim_and_fingerprint() -> None:
    bus, allocation, ledger, route_map = _state()
    coordinator = BusRouteTransactionCoordinator(ledger, route_map)
    ledger_before = ledger.semantic_fingerprint()
    route_map_before = bus_route_map_fingerprint(route_map)
    old_routes = dict(route_map)

    def fail_after_first_member() -> BusRouteBundle:
        assert all(not ledger.claims_for(net_name).resources for net_name in ("/A", "/B"))
        _route("/A", 11)
        raise RoutingError(
            "late follower failed",
            reason=RoutingFailureReason.EXPANSION_BUDGET,
            expansion_count=37,
        )

    with pytest.raises(RoutingError, match="late follower"):
        coordinator.replace(bus, allocation, fail_after_first_member)

    assert ledger.semantic_fingerprint() == ledger_before
    assert bus_route_map_fingerprint(route_map) == route_map_before
    assert route_map == old_routes
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.disposition is BusTransactionDisposition.ROLLED_BACK
    assert coordinator.last_attempt.failure_kind is BusTransactionFailureKind.ROUTING_ERROR
    assert coordinator.last_attempt.routing_failure_reason is RoutingFailureReason.EXPANSION_BUDGET
    assert coordinator.last_attempt.expansion_count == 37


def test_arbitrary_exception_rolls_back_before_propagation() -> None:
    bus, allocation, ledger, route_map = _state()
    coordinator = BusRouteTransactionCoordinator(ledger, route_map)
    ledger_before = ledger.semantic_fingerprint()
    route_map_before = bus_route_map_fingerprint(route_map)

    def explode() -> BusRouteBundle:
        raise RuntimeError("injected search bug")

    with pytest.raises(RuntimeError, match="injected search bug"):
        coordinator.replace(bus, allocation, explode)

    assert ledger.semantic_fingerprint() == ledger_before
    assert bus_route_map_fingerprint(route_map) == route_map_before
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.failure_kind is BusTransactionFailureKind.EXCEPTION


@pytest.mark.parametrize(
    "routes",
    (
        (_route("/A", 1), _route("/A", 2)),
        (_route("/A", 1), _route("/FOREIGN", 2)),
        (_route("/A", 1, geometry_net_name="/FOREIGN"), _route("/B", 2)),
    ),
    ids=("duplicate", "foreign-route", "foreign-geometry"),
)
def test_bundle_rejects_duplicate_or_foreign_member_nets(
    routes: tuple[NegotiatedGridRoute, NegotiatedGridRoute],
) -> None:
    bus = _bus()
    allocation = _allocation(bus)

    with pytest.raises(ValidationError, match="unique|exactly one route|copper geometry"):
        _bundle(bus, allocation, *routes)


def test_committed_claim_conflict_is_visible_but_is_not_called_acceptance() -> None:
    bus, allocation, ledger, route_map = _state()
    shared = _resource(20)
    replacement = _bundle(
        bus,
        allocation,
        _route("/A", 11, resource=shared),
        _route("/B", 12, resource=shared),
    )
    coordinator = BusRouteTransactionCoordinator(ledger, route_map)

    coordinator.replace(bus, allocation, lambda: replacement)

    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.disposition is BusTransactionDisposition.COMMITTED
    assert len(coordinator.last_attempt.capacity_overuse) == 1
    conflict = coordinator.last_attempt.capacity_overuse[0]
    assert conflict.net_names == ("/A", "/B")
    assert conflict.overuse_units == 1
    assert not hasattr(coordinator.last_attempt, "accepted")


def test_bundle_ledger_and_route_map_fingerprints_ignore_member_input_order() -> None:
    bus = _bus()
    allocation = _allocation(bus)
    first = _route("/A", 1)
    second = _route("/B", 2)
    forward = _bundle(bus, allocation, first, second)
    reverse = _bundle(bus, allocation, second, first)
    forward_ledger = OccupancyLedger((first.claims, second.claims))
    reverse_ledger = OccupancyLedger((second.claims, first.claims))

    assert forward == reverse
    assert forward.member_routes == (first, second)
    assert forward.semantic_fingerprint() == reverse.semantic_fingerprint()
    assert forward_ledger.semantic_fingerprint() == reverse_ledger.semantic_fingerprint()
    assert bus_route_map_fingerprint({"/A": first, "/B": second}) == (
        bus_route_map_fingerprint({"/B": second, "/A": first})
    )


def test_committed_telemetry_retains_complete_before_and_after_states() -> None:
    bus, allocation, ledger, route_map = _state()
    before_routes = dict(route_map)
    replacement = _bundle(bus, allocation, _route("/A", 11), _route("/B", 12))
    coordinator = BusRouteTransactionCoordinator(ledger, route_map)

    coordinator.replace(bus, allocation, lambda: replacement)

    assert coordinator.last_attempt is not None
    telemetry = coordinator.last_attempt
    assert telemetry.before_state.routes == tuple(before_routes[name] for name in ("/A", "/B"))
    assert telemetry.before_state.claims == tuple(
        before_routes[name].claims for name in ("/A", "/B")
    )
    assert telemetry.after_state.routes == replacement.member_routes
    assert telemetry.after_state.claims == tuple(
        replacement.by_net()[name].claims for name in ("/A", "/B")
    )
    assert telemetry.before_state != telemetry.after_state
    assert (
        BusRouteTransactionTelemetry.model_validate_json(telemetry.model_dump_json()) == telemetry
    )


def test_rolled_back_telemetry_retains_exact_equal_complete_states() -> None:
    bus, allocation, ledger, route_map = _state()
    coordinator = BusRouteTransactionCoordinator(ledger, route_map)

    with pytest.raises(RuntimeError, match="stop"):
        coordinator.replace(bus, allocation, lambda: (_ for _ in ()).throw(RuntimeError("stop")))

    assert coordinator.last_attempt is not None
    telemetry = coordinator.last_attempt
    assert telemetry.before_state == telemetry.after_state
    assert telemetry.before_state.routes == tuple(route_map[name] for name in ("/A", "/B"))
    assert telemetry.before_state.claims == ledger.committed_claims()


def test_transaction_snapshots_retain_foreign_routes_and_claims() -> None:
    bus, allocation, ledger, route_map = _state()
    foreign = _route("/FOREIGN", 40)
    route_map["/FOREIGN"] = foreign
    ledger.commit(foreign.claims)
    replacement = _bundle(bus, allocation, _route("/A", 11), _route("/B", 12))
    coordinator = BusRouteTransactionCoordinator(ledger, route_map)

    coordinator.replace(bus, allocation, lambda: replacement)

    assert coordinator.last_attempt is not None
    before = coordinator.last_attempt.before_state
    after = coordinator.last_attempt.after_state
    assert tuple(route.result.net_name for route in before.routes) == ("/A", "/B", "/FOREIGN")
    assert tuple(route.result.net_name for route in after.routes) == ("/A", "/B", "/FOREIGN")
    assert before.routes[-1] == after.routes[-1] == foreign
    assert before.claims[-1] == after.claims[-1] == foreign.claims


def test_route_state_json_roundtrip_and_input_order_are_exact() -> None:
    _, _, ledger, route_map = _state()
    forward = BusRouteStateSnapshot.from_state(ledger, route_map)
    reverse = BusRouteStateSnapshot(
        routes=tuple(reversed(forward.routes)),
        claims=tuple(reversed(forward.claims)),
        route_map_fingerprint=forward.route_map_fingerprint,
        ledger_fingerprint=forward.ledger_fingerprint,
    )

    reconstructed = BusRouteStateSnapshot.model_validate_json(forward.model_dump_json())

    assert reverse == forward == reconstructed
    assert reverse.semantic_json() == forward.semantic_json()


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    (
        (("routes", 0, "result", "segments", 0, "net_name"), "/FOREIGN", "geometry"),
        (("claims", 0, "net_name"), "/FOREIGN", "net sets"),
        (("route_map_fingerprint",), "0" * 64, "route-map fingerprint"),
        (("ledger_fingerprint",), "0" * 64, "ledger fingerprint"),
    ),
    ids=("nested-geometry", "nested-claim-owner", "stale-route-map", "stale-ledger"),
)
def test_route_state_rejects_nested_tamper_and_stale_fingerprints(
    path: tuple[str | int, ...],
    replacement: str,
    message: str,
) -> None:
    _, _, ledger, route_map = _state()
    payload = BusRouteStateSnapshot.from_state(ledger, route_map).model_dump(mode="json")
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]

    with pytest.raises(ValidationError, match=message):
        BusRouteStateSnapshot.model_validate(payload)


def test_state_builder_rejects_route_map_key_incoherence() -> None:
    route = _route("/A", 1)
    ledger = OccupancyLedger((route.claims,))

    with pytest.raises(ValueError, match="keys must match"):
        BusRouteStateSnapshot.from_state(ledger, {"/WRONG": route})


@pytest.mark.parametrize("duplicate_field", ("routes", "claims"))
def test_route_state_rejects_duplicate_route_or_claim_nets(duplicate_field: str) -> None:
    _, _, ledger, route_map = _state()
    payload = BusRouteStateSnapshot.from_state(ledger, route_map).model_dump(mode="json")
    payload[duplicate_field].append(payload[duplicate_field][0])

    with pytest.raises(ValidationError, match=f"duplicate {duplicate_field[:-1]}"):
        BusRouteStateSnapshot.model_validate(payload)


def test_route_state_rejects_route_claim_different_from_retained_claim() -> None:
    _, _, ledger, route_map = _state()
    payload = BusRouteStateSnapshot.from_state(ledger, route_map).model_dump(mode="json")
    payload["claims"][0]["resources"][0]["ix0"] = 99

    with pytest.raises(ValidationError, match="retained claims must equal"):
        BusRouteStateSnapshot.model_validate(payload)


def test_telemetry_rejects_fingerprint_fields_stale_against_snapshots() -> None:
    bus, allocation, ledger, route_map = _state()
    state = BusRouteStateSnapshot.from_state(ledger, route_map)

    with pytest.raises(ValidationError, match="must equal retained state snapshots"):
        BusRouteTransactionTelemetry(
            bus_id=bus.bus_id,
            bus_fingerprint=bus.semantic_fingerprint(),
            allocation_fingerprint=allocation.allocation_fingerprint,
            disposition=BusTransactionDisposition.COMMITTED,
            old_bundle_fingerprint=_bundle(
                bus, allocation, *route_map.values()
            ).semantic_fingerprint(),
            candidate_bundle_fingerprint="a" * 64,
            before_state=state,
            after_state=state,
            ledger_before_fingerprint="0" * 64,
            ledger_after_fingerprint=state.ledger_fingerprint,
            route_map_before_fingerprint=state.route_map_fingerprint,
            route_map_after_fingerprint=state.route_map_fingerprint,
        )


def test_rollback_telemetry_compares_complete_snapshots_not_only_fingerprint_fields() -> None:
    bus, allocation, ledger, route_map = _state()
    before = BusRouteStateSnapshot.from_state(ledger, route_map)
    invalid_after = BusRouteStateSnapshot.model_construct(
        schema_id=before.schema_id,
        schema_version=before.schema_version,
        routes=(_route("/A", 99), before.routes[1]),
        claims=before.claims,
        route_map_fingerprint=before.route_map_fingerprint,
        ledger_fingerprint=before.ledger_fingerprint,
    )

    telemetry = BusRouteTransactionTelemetry.model_construct(
        bus_id=bus.bus_id,
        bus_fingerprint=bus.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        disposition=BusTransactionDisposition.ROLLED_BACK,
        old_bundle_fingerprint=_bundle(bus, allocation, *route_map.values()).semantic_fingerprint(),
        before_state=before,
        after_state=invalid_after,
        ledger_before_fingerprint=before.ledger_fingerprint,
        ledger_after_fingerprint=before.ledger_fingerprint,
        route_map_before_fingerprint=before.route_map_fingerprint,
        route_map_after_fingerprint=before.route_map_fingerprint,
        failure_kind=BusTransactionFailureKind.EXCEPTION,
        failure_type="builtins.RuntimeError",
    )

    with pytest.raises(ValueError, match="restore the complete route state"):
        telemetry.outcome_is_coherent()
