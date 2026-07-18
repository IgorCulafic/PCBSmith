from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType

import pytest

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
from pcbsmith.kicad.astar_router import RouteResult
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.bus_transaction import BusRouteBundle, bus_route_map_fingerprint
from pcbsmith.kicad.group_negotiation import (
    BusGroupCandidate,
    GroupCandidateContext,
    GroupCandidateFailure,
    GroupCandidateOutcome,
    GroupNegotiationBudget,
    GroupNegotiationTargetRef,
    GroupRunDisposition,
    GroupTargetKind,
    OrdinaryGroupCandidate,
    negotiate_route_groups,
)
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.routing_ir import RoutingFailureReason


def _resource(ix: int, *, domain: str = "ordinary") -> RoutingResourceKey:
    return RoutingResourceKey(domain, "F.Cu", "cell", ix, 1)


def _route(
    net_name: str,
    *resources: RoutingResourceKey,
    base_cost: int = 1,
) -> NegotiatedGridRoute:
    return NegotiatedGridRoute(
        result=RouteResult(
            net_name=net_name,
            segments=(TrackSegment(0.0, 0.0, 1.0, 0.0, "F.Cu", net_name, 0.2),),
            vias=(),
            length_mm=1.0,
            expansion_count=base_cost,
        ),
        claims=NetResourceClaims(net_name, frozenset(resources)),
        base_cost_units=base_cost,
        congestion_cost_units=0,
    )


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
                    member_id=item.member_id,
                    terminal_ids=(f"{item.member_id}:{role}",),
                )
                for item in members
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
        tuple(item.member_id for item in boundary.ordered_members)
        for boundary in bus.boundaries
    )
    bus_fp = bus.semantic_fingerprint()
    certificate_fp = "c" * 64
    return BusLaneAllocationResult(
        success=True,
        bus_fingerprint=bus_fp,
        certificate_fingerprint=certificate_fp,
        budget=BusAllocationBudget(max_states=10),
        state_count=1,
        reversal_count=0,
        swap_count=0,
        activation_count=0,
        layer_transition_count=0,
        normalized_boundary_orders=orders,
        assignments=assignments,
        allocation_fingerprint=bus_lane_allocation_fingerprint(
            bus_fingerprint=bus_fp,
            certificate_fingerprint=certificate_fp,
            normalized_boundary_orders=orders,
            assignments=assignments,
        ),
    )


def _targets(
    bus: BusGroup, allocation: BusLaneAllocationResult
) -> tuple[GroupNegotiationTargetRef, GroupNegotiationTargetRef, GroupNegotiationTargetRef]:
    return (
        GroupNegotiationTargetRef(
            target_id="bus",
            kind=GroupTargetKind.BUS,
            net_names=("/B", "/A"),
            bus_fingerprint=bus.semantic_fingerprint(),
            allocation_fingerprint=allocation.allocation_fingerprint,
        ),
        GroupNegotiationTargetRef(
            target_id="n1", kind=GroupTargetKind.ORDINARY, net_names=("/N1",)
        ),
        GroupNegotiationTargetRef(
            target_id="n2", kind=GroupTargetKind.ORDINARY, net_names=("/N2",)
        ),
    )


def _state() -> tuple[
    BusGroup,
    BusLaneAllocationResult,
    tuple[GroupNegotiationTargetRef, ...],
    OccupancyLedger,
    dict[str, NegotiatedGridRoute],
]:
    bus = _bus()
    allocation = _allocation(bus)
    targets = _targets(bus, allocation)
    routes = {
        "/A": _route("/A", _resource(101)),
        "/B": _route("/B", _resource(102)),
        "/N1": _route("/N1", _resource(103)),
        "/N2": _route("/N2", _resource(104)),
    }
    return bus, allocation, targets, OccupancyLedger(
        route.claims for route in routes.values()
    ), routes


def _bundle(
    bus: BusGroup,
    allocation: BusLaneAllocationResult,
    a: RoutingResourceKey,
    b: RoutingResourceKey,
) -> BusRouteBundle:
    return BusRouteBundle(
        bus=bus,
        allocation=allocation,
        member_routes=(_route("/B", b), _route("/A", a)),
    )


def _budget(
    *, passes: int = 4, expansions: int = 100, per_target: int = 10, stagnant: int = 2
) -> GroupNegotiationBudget:
    return GroupNegotiationBudget(
        max_passes=passes,
        max_expansions=expansions,
        max_expansions_per_target=per_target,
        max_stagnant_passes=stagnant,
    )


def test_bus_and_ordinary_targets_negotiate_from_overuse_to_zero() -> None:
    bus, allocation, targets, ledger, routes = _state()
    x, y, z, w = (_resource(index) for index in range(1, 5))
    calls: list[tuple[int, str]] = []
    cost_contexts: list[tuple[int, int, int]] = []

    def search(context: GroupCandidateContext) -> BusGroupCandidate | OrdinaryGroupCandidate:
        calls.append((context.pass_index, context.target.target_id))
        cost_contexts.append(
            (context.pass_index, context.present_factor_units, sum(context.history.values()))
        )
        if context.target.target_id == "bus":
            # Pass zero deliberately conflicts.  The complete overused bundle
            # must still install so later present/history negotiation can move it.
            pair = (x, y) if context.pass_index == 0 else (z, w)
            return BusGroupCandidate(context.target, _bundle(bus, allocation, *pair), 2)
        resource = x if context.target.target_id == "n1" else y
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], resource), 1
        )

    result = negotiate_route_groups(targets, ledger, routes, search, budget=_budget())

    assert result.success
    assert len(result.passes) == 2
    assert len(result.passes[0].resource_overuse) == 2
    assert result.passes[0].objective == (0, 2, 2, 1)
    assert result.resource_overuse == ()
    assert calls == [(0, "bus"), (0, "n1"), (0, "n2"), (1, "bus"), (1, "n1"), (1, "n2")]
    assert result.passes[1].route_order == ("bus", "n1", "n2")
    assert cost_contexts[:3] == [(0, 1, 0)] * 3
    assert cost_contexts[3:] == [(1, 2, 8)] * 3


def test_bus_callback_is_once_per_target_and_never_once_per_member() -> None:
    bus, allocation, targets, ledger, routes = _state()
    seen: list[tuple[str, tuple[str, ...]]] = []

    def search(context: GroupCandidateContext) -> BusGroupCandidate | OrdinaryGroupCandidate:
        seen.append((context.target.target_id, context.target.net_names))
        if context.target.kind is GroupTargetKind.BUS:
            return BusGroupCandidate(
                context.target,
                _bundle(bus, allocation, _resource(1), _resource(2)),
                1,
            )
        ix = 3 if context.target.target_id == "n1" else 4
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], _resource(ix)), 1
        )

    result = negotiate_route_groups(targets, ledger, routes, search, budget=_budget())

    assert result.success
    assert seen == [("bus", ("/A", "/B")), ("n1", ("/N1",)), ("n2", ("/N2",))]


def test_late_typed_failure_restores_the_complete_previous_bus_candidate() -> None:
    bus, allocation, targets, ledger, routes = _state()
    shared = _resource(1)
    pass_zero_bus: BusRouteBundle | None = None

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        nonlocal pass_zero_bus
        if context.target.target_id == "bus":
            if context.pass_index == 1:
                return GroupCandidateFailure(
                    context.target, RoutingFailureReason.UNROUTABLE, 1, "late_bus_failure"
                )
            pass_zero_bus = _bundle(bus, allocation, shared, _resource(2))
            return BusGroupCandidate(context.target, pass_zero_bus, 1)
        resource = shared if context.target.target_id == "n1" else _resource(3)
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], resource), 1
        )

    ledger_before = ledger.semantic_fingerprint()
    routes_before = bus_route_map_fingerprint(routes)
    result = negotiate_route_groups(targets, ledger, routes, search, budget=_budget())

    assert not result.success
    assert result.failure_reason is RoutingFailureReason.UNROUTABLE
    assert result.disposition is GroupRunDisposition.ROLLED_BACK
    assert pass_zero_bus is not None
    assert result.bundle_map() == {}
    assert result.route_map() == routes
    assert result.final_ledger_fingerprint == ledger_before
    assert result.final_route_map_fingerprint == routes_before
    failed = result.passes[-1].attempts[-1]
    assert failed.ledger_before_fingerprint == failed.ledger_after_fingerprint


def test_callback_exception_restores_private_attempt_and_never_mutates_caller() -> None:
    bus, allocation, targets, ledger, routes = _state()
    ledger_before = ledger.semantic_fingerprint()
    routes_before = bus_route_map_fingerprint(routes)
    observed: list[tuple[OccupancyLedger, str]] = []

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        if context.pass_index == 1 and context.target.target_id == "bus":
            observed.append((context.ledger, context.ledger.semantic_fingerprint()))
            raise RuntimeError("scripted search fault")
        if context.target.kind is GroupTargetKind.BUS:
            return BusGroupCandidate(
                context.target,
                _bundle(bus, allocation, _resource(1), _resource(2)),
                1,
            )
        return OrdinaryGroupCandidate(
            context.target,
            _route(context.target.net_names[0], _resource(1)),
            1,
        )

    with pytest.raises(RuntimeError, match="scripted search fault"):
        negotiate_route_groups(targets, ledger, routes, search, budget=_budget())

    private_ledger, during_search = observed[0]
    assert private_ledger.semantic_fingerprint() != during_search
    assert private_ledger.semantic_fingerprint() == ledger_before
    assert ledger.semantic_fingerprint() == ledger_before
    assert bus_route_map_fingerprint(routes) == routes_before


def test_pairwise_domains_at_same_cell_remain_distinct_resources() -> None:
    _bus_value, _allocation_value, targets, ledger, routes = _state()
    ordinary = _resource(1)
    pairwise = _resource(1, domain="pairwise:a:b")

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        if context.target.kind is GroupTargetKind.BUS:
            bus, allocation = _bus_value, _allocation_value
            return BusGroupCandidate(
                context.target,
                BusRouteBundle(
                    bus=bus,
                    allocation=allocation,
                    member_routes=(
                        _route("/A", ordinary, pairwise),
                        _route("/B", _resource(2)),
                    ),
                ),
                1,
            )
        resources = (ordinary, pairwise) if context.target.target_id == "n1" else (_resource(3),)
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], *resources), 1
        )

    result = negotiate_route_groups(
        targets, ledger, routes, search, budget=_budget(passes=1, stagnant=1)
    )

    assert not result.success
    assert result.disposition is GroupRunDisposition.BUDGET_EXHAUSTED
    assert result.objective == (0, 2, 2, 1)
    assert {item.resource_id for item in result.resource_overuse} == {
        ordinary.resource_id,
        pairwise.resource_id,
    }


def test_zero_and_one_less_work_budgets_are_terminal_and_fixed() -> None:
    bus, allocation, targets, ledger, routes = _state()
    calls = 0

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if context.target.kind is GroupTargetKind.BUS:
            return BusGroupCandidate(
                context.target,
                _bundle(bus, allocation, _resource(1), _resource(2)),
                2,
            )
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], _resource(3)), 2
        )

    zero = negotiate_route_groups(
        targets, ledger, routes, search, budget=_budget(passes=0)
    )
    assert zero.failure_reason is RoutingFailureReason.PASS_BUDGET
    assert calls == 0

    ledger_before = ledger.semantic_fingerprint()
    routes_before = bus_route_map_fingerprint(routes)
    with pytest.raises(ValueError, match="reported 2 expansions"):
        negotiate_route_groups(
            targets,
            ledger,
            routes,
            search,
            budget=_budget(expansions=1, per_target=1),
        )
    assert ledger.semantic_fingerprint() == ledger_before
    assert bus_route_map_fingerprint(routes) == routes_before


def test_stagnation_budget_stops_repeated_overuse() -> None:
    bus, allocation, targets, ledger, routes = _state()
    shared = _resource(1)

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        if context.target.kind is GroupTargetKind.BUS:
            return BusGroupCandidate(
                context.target, _bundle(bus, allocation, shared, _resource(2)), 1
            )
        resource = shared if context.target.target_id == "n1" else _resource(3)
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], resource), 1
        )

    result = negotiate_route_groups(
        targets, ledger, routes, search, budget=_budget(passes=8, stagnant=1)
    )

    assert result.failure_reason is RoutingFailureReason.STAGNATION
    assert len(result.passes) == 2
    assert result.passes[-1].stagnant


def test_reversed_target_and_route_construction_has_identical_run_fingerprint() -> None:
    bus, allocation, targets, ledger, routes = _state()

    def make_search() -> Callable[[GroupCandidateContext], GroupCandidateOutcome]:
        def search(context: GroupCandidateContext) -> GroupCandidateOutcome:
            if context.target.kind is GroupTargetKind.BUS:
                return BusGroupCandidate(
                    context.target,
                    _bundle(bus, allocation, _resource(1), _resource(2)),
                    1,
                )
            ix = 3 if context.target.target_id == "n1" else 4
            return OrdinaryGroupCandidate(
                context.target, _route(context.target.net_names[0], _resource(ix)), 1
            )

        return search

    forward = negotiate_route_groups(targets, ledger, routes, make_search(), budget=_budget())
    reverse_ledger = OccupancyLedger(
        route.claims for route in reversed(tuple(routes.values()))
    )
    reverse = negotiate_route_groups(
        tuple(reversed(targets)),
        reverse_ledger,
        dict(reversed(tuple(routes.items()))),
        make_search(),
        budget=_budget(),
    )

    assert forward.semantic_fingerprint() == reverse.semantic_fingerprint()
    assert (
        forward.semantic_fingerprint()
        == "34a6702d29cd054593ccf8a34ef9123a7e88fe79b7709cb08623e9b4d6f0a7a4"
    )



def test_empty_external_target_state_is_populated_by_pass_zero() -> None:
    bus, allocation, targets, _ledger, _routes = _state()
    ledger = OccupancyLedger()
    routes: dict[str, NegotiatedGridRoute] = {}

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        if context.target.kind is GroupTargetKind.BUS:
            return BusGroupCandidate(
                context.target, _bundle(bus, allocation, _resource(1), _resource(2)), 0
            )
        ix = 3 if context.target.target_id == "n1" else 4
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], _resource(ix)), 0
        )

    result = negotiate_route_groups(targets, ledger, routes, search, budget=_budget())

    assert result.success
    assert set(result.route_map()) == {"/A", "/B", "/N1", "/N2"}
    assert result.unresolved_target_ids == ()
    assert ledger.committed_claims() == ()
    assert routes == {}


def test_zero_expansion_caps_still_allow_genuine_zero_work_candidates() -> None:
    bus, allocation, targets, _ledger, _routes = _state()
    seen_caps: list[tuple[int, int]] = []

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        seen_caps.append((context.remaining_expansions, context.maximum_attempt_expansions))
        if context.target.kind is GroupTargetKind.BUS:
            return BusGroupCandidate(
                context.target, _bundle(bus, allocation, _resource(1), _resource(2)), 0
            )
        ix = 3 if context.target.target_id == "n1" else 4
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], _resource(ix)), 0
        )

    result = negotiate_route_groups(
        targets,
        OccupancyLedger(),
        {},
        search,
        budget=_budget(expansions=0, per_target=0),
    )

    assert result.success
    assert result.total_expansions == 0
    assert seen_caps == [(0, 0), (0, 0), (0, 0)]


def test_conflict_score_uses_overuse_units_once_per_resource_per_target() -> None:
    bus, allocation, targets, _ledger, _routes = _state()
    shared = _resource(1)
    background_collision = _resource(2)
    background = _route("/FIXED", background_collision)
    ledger = OccupancyLedger((background.claims,))
    routes = {"/FIXED": background}

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        if context.pass_index == 0:
            if context.target.kind is GroupTargetKind.BUS:
                # Three owners on one key means overuse_units=2.  Both bus members
                # count as one target for ordering, not two independent moves.
                return BusGroupCandidate(
                    context.target,
                    BusRouteBundle(
                        bus=bus,
                        allocation=allocation,
                        member_routes=(
                            _route("/A", shared),
                            _route("/B", shared),
                        ),
                    ),
                    0,
                )
            resource = shared if context.target.target_id == "n1" else background_collision
            return OrdinaryGroupCandidate(
                context.target, _route(context.target.net_names[0], resource), 0
            )
        if context.target.kind is GroupTargetKind.BUS:
            return BusGroupCandidate(
                context.target, _bundle(bus, allocation, _resource(10), _resource(11)), 0
            )
        ix = 12 if context.target.target_id == "n1" else 13
        return OrdinaryGroupCandidate(
            context.target, _route(context.target.net_names[0], _resource(ix)), 0
        )

    result = negotiate_route_groups(
        targets,
        ledger,
        routes,
        search,
        budget=_budget(),
        baseline_order=("n2", "bus", "n1"),
    )

    assert result.success
    assert result.passes[0].objective == (0, 3, 2, 2)
    assert result.passes[1].route_order == ("bus", "n1", "n2")


def test_partial_pass_reports_unresolved_targets_in_objective() -> None:
    bus, allocation, targets, _ledger, _routes = _state()

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        if context.target.kind is GroupTargetKind.BUS:
            return BusGroupCandidate(
                context.target, _bundle(bus, allocation, _resource(1), _resource(2)), 0
            )
        return GroupCandidateFailure(
            context.target, RoutingFailureReason.UNROUTABLE, 0, "scripted_failure"
        )

    result = negotiate_route_groups(
        targets, OccupancyLedger(), {}, search, budget=_budget()
    )

    assert result.failure_reason is RoutingFailureReason.UNROUTABLE
    assert result.disposition is GroupRunDisposition.ROLLED_BACK
    assert result.passes[0].unresolved_target_ids == ("n1", "n2")
    assert result.passes[0].objective == (2, 0, 0, 0)
    assert result.unresolved_target_ids == ("bus", "n1", "n2")
    assert result.objective == (3, 0, 0, 0)



@pytest.mark.parametrize("raise_after_mutation", (False, True))
def test_callback_cannot_mutate_caller_owned_state(raise_after_mutation: bool) -> None:
    bus, allocation, targets, ledger, routes = _state()
    ledger_before = ledger.semantic_fingerprint()
    routes_before = bus_route_map_fingerprint(routes)
    old_routes = dict(routes)
    evil = _route("/EVIL", _resource(999))

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        ledger.commit(evil.claims)
        routes["/EVIL"] = evil
        if raise_after_mutation:
            raise LookupError("mutation then callback failure")
        return BusGroupCandidate(
            context.target, _bundle(bus, allocation, _resource(1), _resource(2)), 0
        )

    with pytest.raises(RuntimeError, match="mutated caller-owned"):
        negotiate_route_groups(targets, ledger, routes, search, budget=_budget())

    assert ledger.semantic_fingerprint() == ledger_before
    assert bus_route_map_fingerprint(routes) == routes_before
    assert routes == old_routes



def test_ledger_only_mutation_with_immutable_unchanged_route_map_restores_exactly() -> None:
    bus, allocation, targets, ledger, routes = _state()
    ledger_before = ledger.semantic_fingerprint()
    read_only_routes = MappingProxyType(routes)
    evil = _route("/EVIL", _resource(1001))

    def search(context: GroupCandidateContext):  # type: ignore[no-untyped-def]
        ledger.commit(evil.claims)
        return BusGroupCandidate(
            context.target, _bundle(bus, allocation, _resource(1), _resource(2)), 0
        )

    with pytest.raises(RuntimeError, match="mutated caller-owned") as caught:
        negotiate_route_groups(
            targets, ledger, read_only_routes, search, budget=_budget()
        )

    assert "restoration was not possible" not in str(caught.value)
    assert ledger.semantic_fingerprint() == ledger_before
    assert read_only_routes == routes
