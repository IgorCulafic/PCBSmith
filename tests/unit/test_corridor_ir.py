from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from pcbsmith.corridor_ir import (
    CorridorAllocation,
    CorridorBudget,
    CorridorCapacityLedger,
    CorridorCell,
    CorridorCostPolicy,
    CorridorDemandAttemptTelemetry,
    CorridorDemandClaims,
    CorridorDemandKind,
    CorridorFailureReason,
    CorridorGeometryIssue,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPassTelemetry,
    CorridorPlanResult,
    CorridorPortal,
    CorridorResourceCapacity,
    CorridorResourceClaim,
    CorridorTerminal,
    CorridorViaPolicy,
    CorridorViaPortal,
    corridor_allocations_fingerprint,
)
from pcbsmith.routing_ir import ResourceOveruseSummary


def _digest(character: str) -> str:
    return character * 64


def _capacity(
    resource_id: str,
    units: int,
    kind: str = "channel",
) -> CorridorResourceCapacity:
    return CorridorResourceCapacity(
        resource_id=resource_id,
        resource_kind=kind,
        capacity_units=units,
    )


def _claim(
    resource_id: str,
    units: int,
    kind: str = "channel",
) -> CorridorResourceClaim:
    return CorridorResourceClaim(
        resource_id=resource_id,
        resource_kind=kind,
        demand_units=units,
    )


def _bundle(
    demand_id: str,
    net_name: str,
    *claims: CorridorResourceClaim,
) -> CorridorDemandClaims:
    return CorridorDemandClaims(
        demand_id=demand_id,
        net_name=net_name,
        claims=claims,
    )


def _cell(cell_id: str, layer: str, ix: int) -> CorridorCell:
    return CorridorCell(
        cell_id=cell_id,
        layer=layer,
        ix=ix,
        iy=0,
        bounds_mm=(float(ix), 0.0, float(ix + 1), 1.0),
    )


def _graph(*, reverse: bool = False) -> CorridorGraph:
    front_a = _cell("front-a", "F.Cu", 0)
    front_b = _cell("front-b", "F.Cu", 1)
    back_a = _cell("back-a", "B.Cu", 0)
    portal = CorridorPortal(
        resource_id="channel:front-a-front-b",
        layer="F.Cu",
        cell_low="front-a",
        cell_high="front-b",
        orientation="vertical_cut",
        guaranteed_span_units=99,
        possible_span_units=100,
        verification=CorridorGeometryVerification.EXACT,
    )
    via = CorridorViaPortal(
        resource_id="via:front-a-back-a",
        front_cell_id="front-a",
        back_cell_id="back-a",
        guaranteed_site_count=1,
        possible_site_count=1,
        candidate_sites_mm=((0.5, 0.5),),
        verification=CorridorGeometryVerification.EXACT,
    )
    issue_a = CorridorGeometryIssue(
        source_id="bounded-a",
        layer="F.Cu",
        verification=CorridorGeometryVerification.BOUNDED_APPROXIMATION,
        maximum_error_mm=0.01,
        reason="fixture envelope",
        affected_cell_ids=("front-b", "front-a"),
    )
    issue_b = CorridorGeometryIssue(
        source_id="unsupported-b",
        layer="B.Cu",
        verification=CorridorGeometryVerification.UNSUPPORTED,
        reason="fixture opaque source",
    )
    cells: tuple[CorridorCell, ...] = (front_a, front_b, back_a)
    issues: tuple[CorridorGeometryIssue, ...] = (issue_a, issue_b)
    if reverse:
        cells = tuple(reversed(cells))
        issues = tuple(reversed(issues))
    return CorridorGraph(
        profile_fingerprint=_digest("a"),
        layout_geometry_fingerprint=_digest("b"),
        coarse_grid_mm=1.0,
        capacity_quantum_mm=0.01,
        cells=cells,
        portals=(portal,),
        via_portals=(via,),
        issues=issues,
    )


def test_mixed_capacity_and_heterogeneous_quantities_are_accounted_exactly() -> None:
    ledger = CorridorCapacityLedger(
        (
            _capacity("stem", 10),
            _capacity("layer-change", 2, "via_site"),
        )
    )
    ledger.commit(
        _bundle(
            "demand-a",
            "/A",
            _claim("stem", 6),
            _claim("layer-change", 1, "via_site"),
        )
    )
    ledger.commit(
        _bundle(
            "demand-b",
            "/B",
            _claim("stem", 5),
            _claim("layer-change", 1, "via_site"),
        )
    )

    assert ledger.projected_overuse("demand-b", _claim("stem", 4)) == 0
    assert ledger.projected_overuse("demand-b", _claim("stem", 5)) == 1
    assert ledger.overuse() == (
        ResourceOveruseSummary(
            resource_id="stem",
            resource_kind="channel",
            capacity_units=10,
            demand_units=11,
            overuse_units=1,
            net_names=("/A", "/B"),
        ),
    )


def test_repeated_identical_claim_is_canonical_but_distinct_edges_remain() -> None:
    stem = _claim("stem", 7)
    branch = _claim("branch", 7)
    claims = _bundle("demand-a", "/A", branch, stem, stem)

    assert claims.claims == (branch, stem)
    assert claims.semantic_json() == _bundle("demand-a", "/A", stem, branch).semantic_json()

    with pytest.raises(ValidationError, match="unequal content"):
        _bundle("demand-a", "/A", _claim("stem", 7), _claim("stem", 8))


def test_whole_demand_rip_up_restore_and_replace_are_transactional() -> None:
    ledger = CorridorCapacityLedger((_capacity("stem", 10), _capacity("alternate", 10)))
    old = _bundle("demand-a", "/A", _claim("stem", 8))
    other = _bundle("demand-b", "/B", _claim("stem", 4))
    ledger.commit(old)
    ledger.commit(other)
    overused_fingerprint = ledger.semantic_fingerprint()
    assert ledger.overuse()[0].overuse_units == 2

    removed = ledger.rip_up("demand-a")
    assert removed == old
    assert ledger.claims_for("demand-a") == ()
    assert ledger.overuse() == ()

    assert removed is not None
    ledger.restore(removed)
    assert ledger.semantic_fingerprint() == overused_fingerprint

    replacement = _bundle("demand-a", "/A", _claim("alternate", 8))
    ledger.commit(replacement)
    assert ledger.claims_for("demand-a") == replacement.claims
    assert ledger.overuse() == ()
    assert ledger.rip_up("missing") is None


def test_channel_and_via_site_units_may_not_share_one_resource_identity() -> None:
    with pytest.raises(ValueError, match="unequal content"):
        CorridorCapacityLedger(
            (
                _capacity("shared", 3, "channel"),
                _capacity("shared", 3, "via_site"),
            )
        )

    ledger = CorridorCapacityLedger((_capacity("shared", 3, "channel"),))
    with pytest.raises(ValueError, match="mixes channel capacity with via_site demand"):
        ledger.commit(_bundle("demand-a", "/A", _claim("shared", 1, "via_site")))
    assert ledger.committed_claims() == ()

    with pytest.raises(ValidationError, match="portal claims require channel"):
        CorridorAllocation(
            demand_id="demand-a",
            net_name="/A",
            portal_claims=(_claim("via", 1, "via_site"),),
            base_cost_units=0,
            congestion_cost_units=0,
        )


def test_unknown_resource_rejection_does_not_mutate_existing_state() -> None:
    ledger = CorridorCapacityLedger(
        (_capacity("known", 2),),
        (_bundle("demand-a", "/A", _claim("known", 1)),),
    )
    before = ledger.semantic_fingerprint()

    with pytest.raises(KeyError, match="unknown corridor resource"):
        ledger.commit(_bundle("demand-b", "/B", _claim("unknown", 1)))

    assert ledger.semantic_fingerprint() == before


def test_duplicate_demand_ids_are_canonical_or_fail_when_unequal() -> None:
    capacity = _capacity("portal", 10)
    original = _bundle("demand-a", "/A", _claim("portal", 4))
    duplicate = _bundle("demand-a", "/A", _claim("portal", 4))
    ledger = CorridorCapacityLedger((capacity,), (original, duplicate))

    assert ledger.committed_claims() == (original,)
    with pytest.raises(ValueError, match="duplicate demand claims identity"):
        CorridorCapacityLedger(
            (capacity,),
            (original, _bundle("demand-a", "/A", _claim("portal", 5))),
        )

    before = ledger.semantic_fingerprint()
    with pytest.raises(ValueError, match="cannot change its owning net"):
        ledger.commit(_bundle("demand-a", "/OTHER", _claim("portal", 4)))
    assert ledger.semantic_fingerprint() == before


def test_capacity_and_claim_input_order_have_one_semantic_fingerprint() -> None:
    capacities = (_capacity("a", 10), _capacity("b", 2, "via_site"))
    claims = (
        _bundle("demand-a", "/A", _claim("a", 3), _claim("b", 1, "via_site")),
        _bundle("demand-b", "/B", _claim("a", 4)),
    )
    first = CorridorCapacityLedger(capacities, claims)
    second = CorridorCapacityLedger(
        tuple(reversed(capacities)),
        tuple(
            CorridorDemandClaims(
                demand_id=item.demand_id,
                net_name=item.net_name,
                claims=tuple(reversed(item.claims)),
            )
            for item in reversed(claims)
        ),
    )

    assert first.capacities() == second.capacities()
    assert first.committed_claims() == second.committed_claims()
    assert first.semantic_fingerprint() == second.semantic_fingerprint()


def test_cell_terminal_owners_are_canonical_fingerprinted_and_nonempty() -> None:
    first = CorridorCell(
        cell_id="owned",
        layer="F.Cu",
        ix=0,
        iy=0,
        bounds_mm=(0.0, 0.0, 1.0, 1.0),
        terminal_owner_net_names=("/B", "/A", "/A"),
    )
    reversed_input = CorridorCell(
        cell_id="owned",
        layer="F.Cu",
        ix=0,
        iy=0,
        bounds_mm=(0.0, 0.0, 1.0, 1.0),
        terminal_owner_net_names=("/A", "/B"),
    )

    assert first.terminal_owner_net_names == ("/A", "/B")
    assert first == reversed_input
    assert first.semantic_fingerprint() == reversed_input.semantic_fingerprint()
    with pytest.raises(ValidationError, match="terminal_owner_net_names"):
        CorridorCell(
            cell_id="bad-owner",
            layer="F.Cu",
            ix=0,
            iy=0,
            bounds_mm=(0.0, 0.0, 1.0, 1.0),
            terminal_owner_net_names=("",),
        )


def test_graph_and_demand_collections_have_canonical_semantics() -> None:
    first = _graph()
    second = _graph(reverse=True)
    assert first == second
    assert first.semantic_fingerprint() == second.semantic_fingerprint()
    assert first.schema_id == "pcbsmith-corridor-graph"
    assert first.schema_version == 1

    terminals = (
        CorridorTerminal(terminal_id="pad-b", candidate_cell_ids=("front-b",)),
        CorridorTerminal(terminal_id="pad-a", candidate_cell_ids=("front-b", "front-a")),
    )
    demand = CorridorNetDemand(
        demand_id="demand-a",
        net_name="/A",
        kind=CorridorDemandKind.AREA,
        width_mm=0.3,
        allowed_layers=("F.Cu", "B.Cu", "F.Cu"),
        via_policy=CorridorViaPolicy.ALLOWED,
        terminals=terminals,
        ordinary_span_units=50,
        effective_clearance_mm=0.2,
        pairwise_domain_ids=("pair-b", "pair-a", "pair-a"),
    )
    reversed_demand = CorridorNetDemand.model_validate(
        {
            **demand.model_dump(),
            "allowed_layers": tuple(reversed(demand.allowed_layers)),
            "terminals": tuple(reversed(demand.terminals)),
            "pairwise_domain_ids": tuple(reversed(demand.pairwise_domain_ids)),
        }
    )
    assert demand == reversed_demand
    assert demand.semantic_fingerprint() == reversed_demand.semantic_fingerprint()


def test_duplicate_graph_ids_reject_unequal_content_and_mixed_resource_kind() -> None:
    graph = _graph()
    first_cell = graph.cells[0]
    unequal_cell = CorridorCell(
        cell_id=first_cell.cell_id,
        layer=first_cell.layer,
        ix=99,
        iy=0,
        bounds_mm=(99.0, 0.0, 100.0, 1.0),
    )
    with pytest.raises(ValidationError, match="duplicate cell identity"):
        CorridorGraph.model_validate({**graph.model_dump(), "cells": (*graph.cells, unequal_cell)})

    mixed_via = CorridorViaPortal(
        resource_id=graph.portals[0].resource_id,
        front_cell_id="front-a",
        back_cell_id="back-a",
        guaranteed_site_count=1,
        possible_site_count=1,
        candidate_sites_mm=((0.5, 0.5),),
        verification=CorridorGeometryVerification.EXACT,
    )
    with pytest.raises(ValidationError, match="mixes channel and via-site"):
        CorridorGraph.model_validate({**graph.model_dump(), "via_portals": (mixed_via,)})


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CorridorGeometryIssue(
            source_id="x",
            verification=CorridorGeometryVerification.BOUNDED_APPROXIMATION,
            reason="missing bound",
        ),
        lambda: CorridorGeometryIssue(
            source_id="x",
            verification=CorridorGeometryVerification.UNSUPPORTED,
            maximum_error_mm=0.1,
            reason="unsupported with bound",
        ),
        lambda: CorridorPortal(
            resource_id="p",
            layer="F.Cu",
            cell_low="a",
            cell_high="b",
            orientation="vertical_cut",
            guaranteed_span_units=1,
            possible_span_units=1,
            verification=CorridorGeometryVerification.UNSUPPORTED,
        ),
        lambda: CorridorViaPortal(
            resource_id="v",
            front_cell_id="front",
            back_cell_id="back",
            guaranteed_site_count=0,
            possible_site_count=0,
            verification=CorridorGeometryVerification.BOUNDED_APPROXIMATION,
        ),
    ],
)
def test_incoherent_verification_metadata_fails_closed(factory: object) -> None:
    with pytest.raises(ValidationError):
        factory()  # type: ignore[operator]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_geometry_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        CorridorCell(
            cell_id="bad",
            layer="F.Cu",
            ix=0,
            iy=0,
            bounds_mm=(0.0, 0.0, value, 1.0),
        )
    with pytest.raises(ValidationError):
        CorridorViaPortal(
            resource_id="bad-via",
            front_cell_id="front",
            back_cell_id="back",
            guaranteed_site_count=0,
            possible_site_count=0,
            candidate_sites_mm=((value, 0.0),),
            verification=CorridorGeometryVerification.EXACT,
        )


def test_negative_capacity_and_nonpositive_claim_quantities_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _capacity("bad", -1)
    for value in (0, -1):
        with pytest.raises(ValidationError):
            _claim("bad", value)


def test_exactly_one_excess_unit_produces_exactly_one_overuse_unit() -> None:
    ledger = CorridorCapacityLedger((_capacity("portal", 100),))
    ledger.commit(_bundle("a", "/A", _claim("portal", 40)))
    ledger.commit(_bundle("b", "/B", _claim("portal", 61)))

    summary = ledger.overuse()[0]
    assert summary.capacity_units == 100
    assert summary.demand_units == 101
    assert summary.overuse_units == 1


def test_versioned_plan_models_are_frozen_and_canonical() -> None:
    ledger_fingerprint = CorridorCapacityLedger((_capacity("portal", 10),)).semantic_fingerprint()
    allocation = CorridorAllocation(
        demand_id="demand-a",
        net_name="/A",
        cell_ids=("b", "a", "a"),
        portal_claims=(_claim("portal", 5),),
        base_cost_units=10,
        congestion_cost_units=0,
    )
    policy = CorridorCostPolicy()
    routing_pass = CorridorPassTelemetry(
        pass_index=0,
        demand_order=("demand-a",),
        demand_attempts=(CorridorDemandAttemptTelemetry(demand_id="demand-a", expansion_count=3),),
        expansion_count=3,
        objective=(0, 0, 0, 0),
        history_fingerprint=_digest("c"),
        ledger_fingerprint=ledger_fingerprint,
        allocation_fingerprint=corridor_allocations_fingerprint((allocation,)),
        run_context_fingerprint=_digest("e"),
        present_factor_units=policy.present_factor_units,
    )
    result = CorridorPlanResult(
        guidance_ready=True,
        graph_fingerprint=_graph().semantic_fingerprint(),
        demand_fingerprint=_digest("d"),
        cost_policy_fingerprint=policy.semantic_fingerprint(),
        baseline_demand_order=("demand-a",),
        allocations=(allocation,),
        passes=(routing_pass,),
        budget=CorridorBudget(
            max_passes=2,
            max_expansions=10,
            max_expansions_per_demand=10,
            max_stagnant_passes=1,
        ),
    )

    assert result.schema_id == "pcbsmith-corridor-plan"
    assert result.schema_version == 1
    assert result.allocations[0].cell_ids == ("a", "b")
    assert len(result.semantic_fingerprint()) == 64
    with pytest.raises(ValidationError, match="frozen"):
        result.guidance_ready = False  # type: ignore[misc]

    with pytest.raises(ValidationError, match="typed failure reason"):
        CorridorPlanResult(
            guidance_ready=False,
            graph_fingerprint=_digest("a"),
            demand_fingerprint=_digest("b"),
            cost_policy_fingerprint=policy.semantic_fingerprint(),
            budget=result.budget,
        )

    failed = CorridorPlanResult(
        guidance_ready=False,
        failure_reason=CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
        graph_fingerprint=_digest("a"),
        demand_fingerprint=_digest("b"),
        cost_policy_fingerprint=policy.semantic_fingerprint(),
        budget=result.budget,
    )
    assert not failed.guidance_ready


def test_cost_policy_is_strict_frozen_and_fingerprinted() -> None:
    policy = CorridorCostPolicy()

    assert len(policy.semantic_fingerprint()) == 64
    assert policy == CorridorCostPolicy()
    with pytest.raises(ValidationError, match="frozen"):
        policy.present_factor_units = 2  # type: ignore[misc]
    with pytest.raises(ValidationError, match="extra"):
        CorridorCostPolicy(unknown=1)  # type: ignore[call-arg]
    for value in (True, 1.5, -1):
        with pytest.raises(ValidationError):
            CorridorCostPolicy(present_factor_units=value)
    with pytest.raises(ValidationError):
        CorridorCostPolicy(present_growth_denominator=0)


def test_geometry_completeness_is_fingerprinted() -> None:
    complete = _graph()
    partial = CorridorGraph(
        **{
            **complete.model_dump(),
            "geometry_complete": False,
        }
    )

    assert complete.geometry_complete
    assert not partial.geometry_complete
    assert complete.semantic_fingerprint() != partial.semantic_fingerprint()


def test_ledger_is_not_a_frozen_dataclass_but_models_are_immutable() -> None:
    capacity = _capacity("portal", 1)
    with pytest.raises((ValidationError, FrozenInstanceError), match="frozen"):
        capacity.capacity_units = 2  # type: ignore[misc]


def _empty_corridor_pass(pass_index: int, *, stagnant: bool = False) -> CorridorPassTelemetry:
    return CorridorPassTelemetry(
        pass_index=pass_index,
        demand_order=(),
        demand_attempts=(),
        expansion_count=0,
        objective=(0, 0, 0, 0),
        history_fingerprint=_digest("a"),
        ledger_fingerprint=CorridorCapacityLedger(()).semantic_fingerprint(),
        allocation_fingerprint=corridor_allocations_fingerprint(()),
        run_context_fingerprint=_digest("b"),
        present_factor_units=0,
        stagnant=stagnant,
    )


def test_pass_objective_must_equal_unresolved_and_overuse_summary() -> None:
    with pytest.raises(ValidationError, match="objective must match"):
        CorridorPassTelemetry(
            pass_index=0,
            demand_order=("demand-a",),
            demand_attempts=(
                CorridorDemandAttemptTelemetry(demand_id="demand-a", expansion_count=0),
            ),
            expansion_count=0,
            unresolved_demand_ids=("demand-a",),
            objective=(0, 0, 0, 0),
            history_fingerprint=_digest("a"),
            ledger_fingerprint=CorridorCapacityLedger(()).semantic_fingerprint(),
            allocation_fingerprint=corridor_allocations_fingerprint(()),
            run_context_fingerprint=_digest("b"),
            present_factor_units=0,
        )


def test_plan_allocated_and_unresolved_ids_are_disjoint_and_cover_baseline() -> None:
    allocation = CorridorAllocation(
        demand_id="demand-a",
        net_name="/A",
        base_cost_units=0,
        congestion_cost_units=0,
    )
    common = {
        "guidance_ready": False,
        "failure_reason": CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
        "graph_fingerprint": _digest("a"),
        "demand_fingerprint": _digest("b"),
        "cost_policy_fingerprint": CorridorCostPolicy().semantic_fingerprint(),
        "baseline_demand_order": ("demand-a",),
        "budget": CorridorBudget(
            max_passes=0,
            max_expansions=0,
            max_expansions_per_demand=0,
            max_stagnant_passes=0,
        ),
    }
    with pytest.raises(ValidationError, match="must be disjoint"):
        CorridorPlanResult(
            **common,
            allocations=(allocation,),
            unresolved_demand_ids=("demand-a",),
        )
    with pytest.raises(ValidationError, match="must cover baseline"):
        CorridorPlanResult(**common)


@pytest.mark.parametrize("stagnant_count, budget_count", [(1, 0), (2, 1)])
def test_plan_rejects_consecutive_stagnation_beyond_budget(
    stagnant_count: int,
    budget_count: int,
) -> None:
    passes = tuple(_empty_corridor_pass(index, stagnant=True) for index in range(stagnant_count))
    with pytest.raises(ValidationError, match="stagnant passes exceed"):
        CorridorPlanResult(
            guidance_ready=False,
            failure_reason=CorridorFailureReason.STAGNATION,
            graph_fingerprint=_digest("a"),
            demand_fingerprint=_digest("b"),
            cost_policy_fingerprint=CorridorCostPolicy().semantic_fingerprint(),
            passes=passes,
            budget=CorridorBudget(
                max_passes=stagnant_count,
                max_expansions=0,
                max_expansions_per_demand=0,
                max_stagnant_passes=budget_count,
            ),
        )


def test_pass_attempt_telemetry_enforces_order_totals_sha_and_per_demand_budget() -> None:
    allocations = (
        CorridorAllocation(
            demand_id="demand-a",
            net_name="/A",
            base_cost_units=0,
            congestion_cost_units=0,
        ),
        CorridorAllocation(
            demand_id="demand-b",
            net_name="/B",
            base_cost_units=0,
            congestion_cost_units=0,
        ),
    )
    common = {
        "pass_index": 0,
        "demand_order": ("demand-a", "demand-b"),
        "demand_attempts": (
            CorridorDemandAttemptTelemetry(demand_id="demand-a", expansion_count=1),
            CorridorDemandAttemptTelemetry(demand_id="demand-b", expansion_count=2),
        ),
        "expansion_count": 3,
        "objective": (0, 0, 0, 0),
        "history_fingerprint": _digest("a"),
        "ledger_fingerprint": CorridorCapacityLedger(()).semantic_fingerprint(),
        "allocation_fingerprint": corridor_allocations_fingerprint(allocations),
        "run_context_fingerprint": _digest("b"),
        "present_factor_units": 0,
    }
    routing_pass = CorridorPassTelemetry(**common)

    with pytest.raises(ValidationError, match="exactly match demand_order"):
        CorridorPassTelemetry(
            **{
                **common,
                "demand_attempts": tuple(reversed(routing_pass.demand_attempts)),
            }
        )
    with pytest.raises(ValidationError, match="must sum to pass expansion_count"):
        CorridorPassTelemetry(**{**common, "expansion_count": 4})
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        CorridorPassTelemetry(**{**common, "run_context_fingerprint": "A" * 64})

    with pytest.raises(ValidationError, match="per-demand budget"):
        CorridorPlanResult(
            guidance_ready=False,
            failure_reason=CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
            graph_fingerprint=_digest("c"),
            demand_fingerprint=_digest("d"),
            cost_policy_fingerprint=CorridorCostPolicy().semantic_fingerprint(),
            baseline_demand_order=("demand-a", "demand-b"),
            allocations=allocations,
            passes=(routing_pass,),
            budget=CorridorBudget(
                max_passes=1,
                max_expansions=3,
                max_expansions_per_demand=1,
                max_stagnant_passes=1,
            ),
        )
