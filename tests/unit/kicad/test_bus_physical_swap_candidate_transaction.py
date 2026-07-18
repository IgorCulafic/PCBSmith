"""Focused tests for physical-swap candidate atomic replacement."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_physical_swap_candidate as candidate_fixtures

from pcbsmith.kicad.astar_router import RouteResult
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.bus_physical_swap_candidate_transaction import (
    ReplayBoundPhysicalSwapBusRouteBundle,
    ReplayBoundPhysicalSwapBusTransactionResult,
    _validate_route_authority,
    bind_replay_bound_physical_swap_bus_candidate,
    commit_replay_bound_physical_swap_bus_candidate,
)
from pcbsmith.kicad.bus_transaction import (
    BusRouteStateSnapshot,
    BusRouteTransactionCoordinator,
    bus_route_map_fingerprint,
)
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.routing_ir import ResourceOveruseSummary


@pytest.fixture(autouse=True)
def _deterministic_router(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate_fixtures._install_router(monkeypatch)


@lru_cache(maxsize=1)
def _authority() -> ReplayBoundPhysicalSwapBusRouteBundle:
    return bind_replay_bound_physical_swap_bus_candidate(candidate_fixtures._successful_candidate())


def _foreign_route(authority: ReplayBoundPhysicalSwapBusRouteBundle) -> NegotiatedGridRoute:
    plan_input = authority.candidate.replay_input.composition.replay_input.plan.replay_input
    assert len(plan_input.initial_claims) == 1
    claim = plan_input.initial_claims[0]
    segment = TrackSegment(
        30.0,
        30.0,
        31.0,
        30.0,
        "F.Cu",
        claim.net_name,
        0.2,
    )
    return NegotiatedGridRoute(
        result=RouteResult(
            net_name=claim.net_name,
            segments=(segment,),
            vias=(),
            length_mm=1.0,
            expansion_count=0,
        ),
        claims=claim,
        base_cost_units=1,
        congestion_cost_units=0,
    )


def _routes(authority: ReplayBoundPhysicalSwapBusRouteBundle) -> dict[str, NegotiatedGridRoute]:
    routes = {
        route.result.net_name: replace(
            route,
            base_cost_units=route.base_cost_units + 100,
        )
        for route in authority.bundle.member_routes
    }
    foreign = _foreign_route(authority)
    routes[foreign.result.net_name] = foreign
    return routes


def _coordinator(
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
) -> BusRouteTransactionCoordinator:
    routes = _routes(authority)
    return BusRouteTransactionCoordinator(
        OccupancyLedger(route.claims for route in routes.values()),
        routes,
    )


def _state(coordinator: BusRouteTransactionCoordinator) -> tuple[Any, ...]:
    return (
        coordinator.ledger.committed_claims(),
        coordinator.ledger.semantic_fingerprint(),
        bus_route_map_fingerprint(coordinator.routes_by_net),
        dict(coordinator.routes_by_net),
    )


def test_truthful_physical_candidate_replaces_once_and_preserves_foreign_state() -> None:
    authority = _authority()
    authority_before = authority.model_dump_json()
    coordinator = _coordinator(authority)
    foreign = coordinator.routes_by_net["/FOREIGN"]
    foreign_claims = coordinator.ledger.claims_for("/FOREIGN")

    result = commit_replay_bound_physical_swap_bus_candidate(coordinator, authority)

    assert coordinator.routes_by_net == {
        "/FOREIGN": foreign,
        **authority.bundle.by_net(),
    }
    assert coordinator.ledger.claims_for("/FOREIGN") == foreign_claims
    assert result.telemetry.after_state.routes == tuple(
        coordinator.routes_by_net[name] for name in sorted(coordinator.routes_by_net)
    )
    m0_prefix = authority.candidate.replay_input.composition.members[0].prefix
    after_routes = {route.result.net_name: route for route in result.telemetry.after_state.routes}
    assert len(m0_prefix.vias) == 4
    assert all(via in after_routes["/D0"].result.vias for via in m0_prefix.vias)
    assert authority.model_dump_json() == authority_before
    assert (
        ReplayBoundPhysicalSwapBusRouteBundle.model_validate_json(authority.model_dump_json())
        == authority
    )
    assert (
        ReplayBoundPhysicalSwapBusTransactionResult.model_validate_json(result.model_dump_json())
        == result
    )


@pytest.mark.parametrize(
    "mutation",
    ("missing_member", "extra_claim", "extra_route", "wrong_initial"),
)
def test_missing_extra_or_shadow_state_rejects_before_candidate_release(
    mutation: str,
) -> None:
    authority = _authority()
    routes = _routes(authority)
    claims = {name: route.claims for name, route in routes.items()}
    if mutation == "missing_member":
        routes.pop("/D2")
        claims.pop("/D2")
    elif mutation == "extra_claim":
        claims["/SHADOW"] = NetResourceClaims(
            "/SHADOW",
            frozenset({RoutingResourceKey("ordinary", "F.Cu", "cell", 50, 50)}),
        )
    elif mutation == "extra_route":
        routes["/SHADOW"] = replace(
            routes["/FOREIGN"],
            result=replace(routes["/FOREIGN"].result, net_name="/SHADOW"),
            claims=NetResourceClaims(
                "/SHADOW",
                frozenset({RoutingResourceKey("ordinary", "F.Cu", "cell", 51, 51)}),
            ),
        )
    else:
        changed_claim = NetResourceClaims(
            "/FOREIGN",
            frozenset({RoutingResourceKey("ordinary", "F.Cu", "cell", 52, 52)}),
        )
        claims["/FOREIGN"] = changed_claim
        routes["/FOREIGN"] = replace(routes["/FOREIGN"], claims=changed_claim)
    coordinator = BusRouteTransactionCoordinator(
        OccupancyLedger(tuple(claims.values())),
        routes,
    )
    before = _state(coordinator)

    with pytest.raises(ValueError):
        commit_replay_bound_physical_swap_bus_candidate(coordinator, authority)

    assert coordinator.last_attempt is None
    assert _state(coordinator) == before


def test_authority_candidate_bundle_member_and_fingerprint_tamper_fail_closed() -> None:
    authority = _authority()
    first_binding = authority.member_bindings[0]
    mutations = (
        {"bundle_fingerprint": "0" * 64},
        {"member_bindings": authority.member_bindings[1:]},
        {
            "member_bindings": (
                first_binding.model_copy(update={"route_fingerprint": "0" * 64}),
                *authority.member_bindings[1:],
            )
        },
        {"authority_fingerprint": "0" * 64},
    )
    for update in mutations:
        with pytest.raises(ValueError):
            _validate_route_authority(authority.model_copy(update=update))

    stale_candidate = authority.candidate.model_copy(update={"bundle_fingerprint": "0" * 64})
    with pytest.raises(ValidationError):
        ReplayBoundPhysicalSwapBusRouteBundle.model_validate_json(
            authority.model_copy(update={"candidate": stale_candidate}).model_dump_json()
        )


def test_transaction_result_rejects_state_fingerprint_and_overuse_tamper() -> None:
    authority = _authority()
    result = commit_replay_bound_physical_swap_bus_candidate(
        _coordinator(authority),
        authority,
    )
    fake_overuse = ResourceOveruseSummary(
        resource_id="ordinary:F.Cu:cell:1:1:0:0",
        resource_kind="other",
        capacity_units=1,
        demand_units=2,
        overuse_units=1,
        net_names=("/D0", "/D1"),
    )
    changed_telemetry = result.telemetry.model_copy(update={"capacity_overuse": (fake_overuse,)})
    with pytest.raises(ValueError, match="overuse"):
        result.model_copy(
            update={"telemetry": changed_telemetry}
        ).committed_state_is_exactly_bound()
    with pytest.raises(ValueError, match="fingerprint"):
        result.model_copy(
            update={"result_fingerprint": "0" * 64}
        ).committed_state_is_exactly_bound()

    routes = {route.result.net_name: route for route in result.telemetry.after_state.routes}
    changed = replace(routes["/FOREIGN"], base_cost_units=99)
    routes["/FOREIGN"] = changed
    claims = OccupancyLedger(route.claims for route in routes.values())
    changed_state = BusRouteStateSnapshot.from_state(claims, routes)
    stale_telemetry = result.telemetry.model_copy(
        update={
            "after_state": changed_state,
            "ledger_after_fingerprint": changed_state.ledger_fingerprint,
            "route_map_after_fingerprint": changed_state.route_map_fingerprint,
        }
    )
    with pytest.raises(ValueError, match="exact physical replacement"):
        result.model_copy(update={"telemetry": stale_telemetry}).committed_state_is_exactly_bound()
