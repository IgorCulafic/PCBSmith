from __future__ import annotations

import math
from dataclasses import replace
from functools import lru_cache
from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_bus_physical_swap_composition import _inputs

from pcbsmith.kicad import bus_candidate
from pcbsmith.kicad.astar_router import RouteResult, RoutingError
from pcbsmith.kicad.bus_candidate import (
    BusCandidateBudget,
    BusCandidateCallerOveruseMode,
    BusCandidateFailureReason,
    BusCandidatePolicy,
    _build_bus_candidate_from_prefixes,
)
from pcbsmith.kicad.bus_physical_swap_candidate import (
    BusPhysicalSwapCandidateClearanceGroup,
    BusPhysicalSwapCandidateHistoryEntry,
    BusPhysicalSwapCandidateReplayInput,
    ReplayBoundPhysicalSwapBusCandidate,
    _success_bindings,
    build_replay_bound_physical_swap_bus_candidate,
)
from pcbsmith.kicad.bus_physical_swap_composition import (
    ReplayBoundPhysicalSwapBusPrefixComposition,
    compose_replay_bound_physical_swap_bus_prefixes,
)
from pcbsmith.kicad.negotiated_graph import NegotiatedCostPolicy
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
    capsule_segment_claims,
    symmetric_halo_radius,
    via_claims,
)
from pcbsmith.routing_ir import RoutingFailureReason

_BUDGET = BusCandidateBudget(
    max_members=3,
    max_expansions_per_member=100,
    max_total_expansions=300,
)


@lru_cache(maxsize=1)
def _composition() -> ReplayBoundPhysicalSwapBusPrefixComposition:
    plan, pigtails, transitions, sources = _inputs(False, True)
    return compose_replay_bound_physical_swap_bus_prefixes(
        plan=plan,
        pigtails=pigtails,
        transition_vias=transitions,
        terminal_sources=sources,
    )


def _ledger() -> OccupancyLedger:
    authority = _composition().replay_input.plan.replay_input
    return OccupancyLedger(authority.initial_claims)


def _candidate(**updates: Any) -> ReplayBoundPhysicalSwapBusCandidate:
    values: dict[str, Any] = {
        "composition": _composition(),
        "caller_ledger": _ledger(),
        "budget": _BUDGET,
    }
    values.update(updates)
    return build_replay_bound_physical_swap_bus_candidate(**values)


@lru_cache(maxsize=1)
def _successful_candidate_state() -> tuple[
    ReplayBoundPhysicalSwapBusCandidate,
    tuple[tuple[NetResourceClaims, ...], str],
    tuple[tuple[NetResourceClaims, ...], str],
]:
    ledger = _ledger()
    before = ledger.committed_claims(), ledger.semantic_fingerprint()
    result = _candidate(caller_ledger=ledger)
    after = ledger.committed_claims(), ledger.semantic_fingerprint()
    return result, before, after


def _successful_candidate() -> ReplayBoundPhysicalSwapBusCandidate:
    return _successful_candidate_state()[0]


def _install_router(
    monkeypatch: pytest.MonkeyPatch,
    expansions: dict[str, int] | None = None,
) -> None:
    fixed_expansions = expansions or {"/D0": 2, "/D1": 3, "/D2": 4}

    def fake_route(*args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        net_name = args[2]
        needed = fixed_expansions[net_name]
        limit = kwargs["max_expansions"]
        if needed > limit:
            raise RoutingError(
                "fixed expansion limit exhausted",
                reason=RoutingFailureReason.EXPANSION_BUDGET,
                expansion_count=limit,
            )
        prefix = kwargs["route_prefix"]
        profile = kwargs["profile"]
        grid_mm = kwargs["grid_mm"]
        width_mm = kwargs["track_width_mm"]
        clearance = profile.fab_spacing.minimum_copper_clearance_mm
        track_halo = symmetric_halo_radius(width_mm, clearance)
        via_halo = symmetric_halo_radius(profile.geometry.routing_via_diameter_mm, clearance)
        resources: set[RoutingResourceKey] = set()
        for segment in prefix.segments:
            resources.update(
                capsule_segment_claims(
                    "ordinary",
                    segment.layer,
                    (segment.x1, segment.y1),
                    (segment.x2, segment.y2),
                    grid_mm,
                    track_halo,
                )
            )
        for via in prefix.vias:
            resources.update(
                via_claims(
                    "ordinary",
                    round(via.x / grid_mm),
                    round(via.y / grid_mm),
                    grid_mm,
                    via_halo,
                )
            )
        length = sum(
            math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1)
            for segment in prefix.segments
        )
        return NegotiatedGridRoute(
            result=RouteResult(
                net_name=net_name,
                segments=prefix.segments,
                vias=prefix.vias,
                length_mm=length,
                expansion_count=needed,
            ),
            claims=NetResourceClaims(net_name, frozenset(resources)),
            base_cost_units=1,
            congestion_cost_units=0,
            prefix_alternative_id=prefix.alternative_id,
            prefix_fingerprint=prefix.semantic_fingerprint(),
        )

    monkeypatch.setattr(bus_candidate, "route_net_negotiated_candidate", fake_route)


def test_truthful_success_binds_all_physical_prefixes_and_preserves_foreign_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    result, before, after = _successful_candidate_state()

    assert result.candidate_result.success
    assert result.candidate_result.bundle is not None
    assert result.bundle_fingerprint == result.candidate_result.bundle.semantic_fingerprint()
    assert tuple(item.member_id for item in result.member_bindings) == (
        "m0",
        "m1",
        "m2",
    )
    prefixes = {item.member_id: item for item in result.replay_input.composition.members}
    routes = result.candidate_result.bundle.by_net()
    m0 = routes["/D0"]
    assert len(prefixes["m0"].prefix.vias) == 4
    assert all(via in m0.result.vias for via in prefixes["m0"].prefix.vias)
    for binding in result.member_bindings:
        prefix = prefixes[binding.member_id]
        route = routes[binding.net_name]
        assert binding.prefix_alternative_id == prefix.prefix.alternative_id
        assert binding.prefix_fingerprint == prefix.prefix_fingerprint
        assert route.prefix_alternative_id == prefix.prefix.alternative_id
        assert route.prefix_fingerprint == prefix.prefix_fingerprint
        assert all(segment in route.result.segments for segment in prefix.prefix.segments)
    assert before == after
    assert before[0][0].net_name == "/FOREIGN"
    assert (
        ReplayBoundPhysicalSwapBusCandidate.model_validate_json(result.model_dump_json()) == result
    )


def test_candidate_input_order_repeat_and_clearance_authority_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    first_resource = RoutingResourceKey("ordinary", "F.Cu", "cell", 31, 30)
    second_resource = RoutingResourceKey("ordinary", "F.Cu", "cell", 32, 30)
    group = BusPhysicalSwapCandidateClearanceGroup(
        nets_a=("/D2", "/D1"),
        nets_b=("/D0",),
        minimum_clearance_mm=0.8,
        exempt_component_refs=("U2", "U1"),
    )
    first = _candidate(
        history={first_resource: 2, second_resource: 3},
        clearance_groups=(group,),
    )
    repeated = _candidate(
        history={second_resource: 3, first_resource: 2},
        clearance_groups=(
            BusPhysicalSwapCandidateClearanceGroup(
                nets_a=("/D1", "/D2"),
                nets_b=("/D0",),
                minimum_clearance_mm=0.8,
                exempt_component_refs=("U1", "U2"),
            ),
        ),
    )

    assert first == repeated
    assert first.result_fingerprint == repeated.result_fingerprint
    with pytest.raises(ValidationError, match="duplicate declarations"):
        BusPhysicalSwapCandidateReplayInput(
            composition=_composition(),
            budget=_BUDGET,
            clearance_groups=(group, group),
        )
    for invalid in (float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            BusPhysicalSwapCandidateClearanceGroup(
                nets_a=("/D0",),
                nets_b=("/D1",),
                minimum_clearance_mm=invalid,
            )


@pytest.mark.parametrize(
    ("budget", "reason", "failed_member", "expansions"),
    (
        (
            BusCandidateBudget(
                max_members=2,
                max_expansions_per_member=100,
                max_total_expansions=300,
            ),
            BusCandidateFailureReason.MEMBER_BUDGET,
            None,
            0,
        ),
        (
            BusCandidateBudget(
                max_members=3,
                max_expansions_per_member=1,
                max_total_expansions=300,
            ),
            BusCandidateFailureReason.PER_MEMBER_EXPANSION_BUDGET,
            "m0",
            1,
        ),
        (
            BusCandidateBudget(
                max_members=3,
                max_expansions_per_member=100,
                max_total_expansions=8,
            ),
            BusCandidateFailureReason.TOTAL_EXPANSION_BUDGET,
            "m2",
            8,
        ),
    ),
)
def test_one_less_member_per_member_and_total_budgets_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    budget: BusCandidateBudget,
    reason: BusCandidateFailureReason,
    failed_member: str | None,
    expansions: int,
) -> None:
    _install_router(monkeypatch)
    result = _candidate(budget=budget)

    assert not result.candidate_result.success
    assert result.candidate_result.failure_reason is reason
    assert result.candidate_result.failed_member_id == failed_member
    assert result.candidate_result.expansion_count == expansions
    assert result.bundle_fingerprint is None
    assert result.member_bindings == ()


def _kernel(
    *,
    ledger: OccupancyLedger,
    layout: Any | None = None,
    policy: BusCandidatePolicy | None = None,
):
    composition = _composition()
    authority = composition.replay_input.plan.replay_input
    prefixes = {item.member_id: item.prefix for item in composition.members}
    fingerprints = {item.member_id: item.prefix_fingerprint for item in composition.members}
    return _build_bus_candidate_from_prefixes(
        static_layout=layout or authority.layout,
        netlist=authority.netlist,
        bus=authority.bus,
        allocation=authority.allocation,
        prefixes_by_member=prefixes,
        prefix_fingerprints_by_member=fingerprints,
        caller_ledger=ledger,
        budget=_BUDGET,
        policy=policy or BusCandidatePolicy(),
        history=None,
        present_factor_units=0,
        cost_policy=NegotiatedCostPolicy(),
        profile=authority.rule_profile,
        clearance_groups=(),
    )


def test_target_copper_claims_and_caller_overuse_modes_remain_truthful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    composition = _composition()
    authority = composition.replay_input.plan.replay_input
    target_layout = replace(
        authority.layout,
        segments=(composition.members[0].prefix.segments[0],),
    )
    target_copper = _kernel(ledger=_ledger(), layout=target_layout)
    target_claims = _kernel(
        ledger=OccupancyLedger(
            (
                NetResourceClaims(
                    "/D0",
                    frozenset({RoutingResourceKey("ordinary", "F.Cu", "cell", 40, 40)}),
                ),
            )
        )
    )
    shared = RoutingResourceKey("ordinary", "F.Cu", "cell", 41, 41)
    overused = OccupancyLedger(
        (
            NetResourceClaims("/X", frozenset({shared})),
            NetResourceClaims("/Y", frozenset({shared})),
        )
    )
    strict = _kernel(ledger=overused)
    preserve = _kernel(
        ledger=overused,
        policy=BusCandidatePolicy(
            caller_overuse_mode=(BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION)
        ),
    )

    assert target_copper.failure_reason is BusCandidateFailureReason.STATIC_TARGET_COPPER
    assert target_claims.failure_reason is BusCandidateFailureReason.CALLER_MEMBER_CLAIMS
    assert strict.failure_reason is BusCandidateFailureReason.CALLER_OVERUSE
    assert strict.resource_overuse
    assert preserve.complete and not preserve.success
    assert preserve.failure_reason is BusCandidateFailureReason.FINAL_OVERUSE
    assert preserve.bundle is not None


def test_wrong_caller_ledger_is_rejected_before_routing() -> None:
    with pytest.raises(ValueError, match="exactly equal"):
        _candidate(caller_ledger=OccupancyLedger())


def test_missing_duplicate_or_member_swapped_physical_prefixes_reject() -> None:
    composition = _composition()
    member_mutations = (
        composition.members[:-1],
        (*composition.members, composition.members[0]),
        tuple(reversed(composition.members)),
    )
    for members in member_mutations:
        changed = composition.model_copy(update={"members": members})
        with pytest.raises(ValidationError):
            BusPhysicalSwapCandidateReplayInput(
                composition=changed,
                budget=_BUDGET,
            )


def test_history_cost_policy_profile_and_clearance_tamper_fail_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    result = _successful_candidate()
    resource = RoutingResourceKey("ordinary", "F.Cu", "cell", 33, 30)
    group = BusPhysicalSwapCandidateClearanceGroup(
        nets_a=("/D0",),
        nets_b=("/D1",),
        minimum_clearance_mm=0.9,
    )
    input_updates = (
        {"history": (BusPhysicalSwapCandidateHistoryEntry(resource=resource, value=1),)},
        {
            "cost_policy": replace(
                result.replay_input.cost_policy,
                via_cost_units=result.replay_input.cost_policy.via_cost_units + 1,
            )
        },
        {
            "policy": BusCandidatePolicy(
                caller_overuse_mode=(BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION)
            )
        },
        {"present_factor_units": 1},
        {"clearance_groups": (group,)},
    )
    changed_inputs = tuple(
        result.replay_input.model_copy(update=update) for update in input_updates
    )
    assert all(
        item.semantic_fingerprint() != result.replay_input.semantic_fingerprint()
        for item in changed_inputs
    )
    combined_input = result.replay_input.model_copy(
        update={key: value for update in input_updates for key, value in update.items()}
    )
    with pytest.raises(ValidationError):
        ReplayBoundPhysicalSwapBusCandidate.model_validate_json(
            result.model_copy(update={"replay_input": combined_input}).model_dump_json()
        )

    composition = result.replay_input.composition
    plan = composition.replay_input.plan
    stale_authority = plan.replay_input.model_copy(
        update={
            "rule_profile": plan.replay_input.rule_profile.model_copy(
                update={"profile_id": "profile:stale"}
            )
        }
    )
    stale_plan = plan.model_copy(update={"replay_input": stale_authority})
    stale_composition_input = composition.replay_input.model_copy(update={"plan": stale_plan})
    stale_composition = composition.model_copy(update={"replay_input": stale_composition_input})
    with pytest.raises(ValidationError):
        BusPhysicalSwapCandidateReplayInput(
            composition=stale_composition,
            budget=_BUDGET,
        )


def test_route_bundle_binding_and_wrapper_fingerprint_tamper_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    result = _successful_candidate()
    candidate = result.candidate_result
    assert candidate.bundle is not None
    route = candidate.bundle.member_routes[0]
    route_index = candidate.bundle.member_routes.index(route)

    omitted_result = replace(route.result, segments=route.result.segments[1:])
    omitted_route = replace(route, result=omitted_result)
    omitted_routes = list(candidate.bundle.member_routes)
    omitted_routes[route_index] = omitted_route
    omitted_bundle = candidate.bundle.model_copy(update={"member_routes": tuple(omitted_routes)})
    omitted_candidate = candidate.model_copy(update={"bundle": omitted_bundle})
    with pytest.raises(ValueError, match="omits or replaces"):
        _success_bindings(result.replay_input, omitted_candidate)

    replacement = replace(
        route.result.segments[0],
        width_mm=route.result.segments[0].width_mm + 0.01,
    )
    replaced_result = replace(
        route.result,
        segments=(replacement, *route.result.segments[1:]),
    )
    replaced_route = replace(route, result=replaced_result)
    replaced_routes = list(candidate.bundle.member_routes)
    replaced_routes[route_index] = replaced_route
    replaced_bundle = candidate.bundle.model_copy(update={"member_routes": tuple(replaced_routes)})
    with pytest.raises(ValueError, match="omits or replaces"):
        _success_bindings(
            result.replay_input,
            candidate.model_copy(update={"bundle": replaced_bundle}),
        )

    wrong_prefix_route = replace(route, prefix_alternative_id="prefix:wrong")
    wrong_prefix_routes = list(candidate.bundle.member_routes)
    wrong_prefix_routes[route_index] = wrong_prefix_route
    wrong_prefix_bundle = candidate.bundle.model_copy(
        update={"member_routes": tuple(wrong_prefix_routes)}
    )
    with pytest.raises(ValueError, match="prefix identity"):
        _success_bindings(
            result.replay_input,
            candidate.model_copy(update={"bundle": wrong_prefix_bundle}),
        )

    wrapper_updates: tuple[dict[str, Any], ...] = (
        {"candidate_result_fingerprint": "0" * 64},
        {"bundle_fingerprint": "0" * 64},
        {"member_bindings": result.member_bindings[:-1]},
        {"result_fingerprint": "0" * 64},
        {"candidate_result": omitted_candidate},
    )
    for update in wrapper_updates[:-1]:
        with pytest.raises(ValueError):
            result.model_copy(update=update).candidate_replays_and_binds_exactly()
    with pytest.raises(ValidationError):
        ReplayBoundPhysicalSwapBusCandidate.model_validate_json(
            result.model_copy(update=wrapper_updates[-1]).model_dump_json()
        )
