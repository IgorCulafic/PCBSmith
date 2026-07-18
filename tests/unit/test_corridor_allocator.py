from __future__ import annotations

from collections.abc import Mapping

import pytest

import pcbsmith.corridor_allocator as allocator_module
from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_ir import (
    CorridorBudget,
    CorridorCapacityLedger,
    CorridorCell,
    CorridorCostPolicy,
    CorridorFailureReason,
    CorridorGeometryIssue,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPlanResult,
    CorridorPortal,
    CorridorTerminal,
    CorridorViaPolicy,
    CorridorViaPortal,
)


def _line_graph() -> CorridorGraph:
    return CorridorGraph(
        profile_fingerprint="0" * 64,
        layout_geometry_fingerprint="1" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=(
            CorridorCell(
                cell_id="left",
                layer="F.Cu",
                ix=0,
                iy=0,
                bounds_mm=(0.0, 0.0, 1.0, 1.0),
            ),
            CorridorCell(
                cell_id="right",
                layer="F.Cu",
                ix=1,
                iy=0,
                bounds_mm=(1.0, 0.0, 2.0, 1.0),
            ),
        ),
        portals=(
            CorridorPortal(
                resource_id="left-right",
                layer="F.Cu",
                cell_low="left",
                cell_high="right",
                orientation="vertical_cut",
                guaranteed_span_units=2,
                possible_span_units=2,
                verification=CorridorGeometryVerification.EXACT,
            ),
        ),
    )


def _demand(name: str) -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=name,
        net_name=name,
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(
                terminal_id=f"{name}-left",
                candidate_cell_ids=("left",),
            ),
            CorridorTerminal(
                terminal_id=f"{name}-right",
                candidate_cell_ids=("right",),
            ),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )


def test_bottleneck_capacity_fits_exactly_and_one_more_does_not() -> None:
    fits = negotiate_corridor_allocations(
        _line_graph(),
        (_demand("a"), _demand("b")),
    )
    assert fits.guidance_ready is True
    assert fits.failure_reason is None
    assert len(fits.allocations) == 2
    assert fits.resource_overuse == ()

    overloaded = negotiate_corridor_allocations(
        _line_graph(),
        (_demand("a"), _demand("b"), _demand("c")),
    )
    assert overloaded.guidance_ready is False
    assert overloaded.failure_reason is not None
    assert len(overloaded.resource_overuse) == 1
    assert overloaded.resource_overuse[0].resource_id == "left-right"
    assert overloaded.resource_overuse[0].overuse_units == 1


def _quantity_demand(name: str, units: int) -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=name,
        net_name=name,
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id=f"{name}-left", candidate_cell_ids=("left",)),
            CorridorTerminal(terminal_id=f"{name}-right", candidate_cell_ids=("right",)),
        ),
        ordinary_span_units=units,
        effective_clearance_mm=0.1,
    )


def test_heterogeneous_demands_account_exact_physical_span_units() -> None:
    result = negotiate_corridor_allocations(
        _line_graph(),
        (_quantity_demand("fine", 1), _quantity_demand("ordinary", 2)),
        budget=CorridorBudget(
            max_passes=1,
            max_expansions=100,
            max_expansions_per_demand=100,
            max_stagnant_passes=1,
        ),
    )
    assert result.failure_reason is CorridorFailureReason.PASS_BUDGET
    assert result.resource_overuse[0].capacity_units == 2
    assert result.resource_overuse[0].demand_units == 3
    assert result.resource_overuse[0].overuse_units == 1
    assert {
        allocation.demand_id: allocation.portal_claims[0].demand_units
        for allocation in result.allocations
    } == {"fine": 1, "ordinary": 2}


def test_multi_terminal_tree_claims_shared_trunk_once_and_distinct_branches() -> None:
    graph = CorridorGraph(
        profile_fingerprint="0" * 64,
        layout_geometry_fingerprint="1" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=(
            CorridorCell(cell_id="root", layer="F.Cu", ix=0, iy=0, bounds_mm=(0, 0, 1, 1)),
            CorridorCell(cell_id="junction", layer="F.Cu", ix=1, iy=0, bounds_mm=(1, 0, 2, 1)),
            CorridorCell(cell_id="upper", layer="F.Cu", ix=2, iy=1, bounds_mm=(2, 1, 3, 2)),
            CorridorCell(cell_id="lower", layer="F.Cu", ix=2, iy=-1, bounds_mm=(2, -1, 3, 0)),
        ),
        portals=tuple(
            CorridorPortal(
                resource_id=resource_id,
                layer="F.Cu",
                cell_low=cell_low,
                cell_high=cell_high,
                orientation="vertical_cut",
                guaranteed_span_units=2,
                possible_span_units=2,
                verification=CorridorGeometryVerification.EXACT,
            )
            for resource_id, cell_low, cell_high in (
                ("trunk", "root", "junction"),
                ("upper-branch", "junction", "upper"),
                ("lower-branch", "junction", "lower"),
            )
        ),
    )
    demand = CorridorNetDemand(
        demand_id="tree",
        net_name="tree",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=tuple(
            CorridorTerminal(terminal_id=f"tree-{cell_id}", candidate_cell_ids=(cell_id,))
            for cell_id in ("root", "upper", "lower")
        ),
        ordinary_span_units=2,
        effective_clearance_mm=0.1,
    )
    result = negotiate_corridor_allocations(graph, (demand,))
    assert result.guidance_ready is True
    claims = result.allocations[0].portal_claims
    assert tuple(claim.resource_id for claim in claims) == (
        "lower-branch",
        "trunk",
        "upper-branch",
    )
    assert sum(claim.resource_id == "trunk" for claim in claims) == 1
    assert all(claim.demand_units == 2 for claim in claims)


def test_preflight_mixed_mapped_and_unmapped_accounts_for_full_baseline() -> None:
    mapped = _demand("mapped")
    unmapped = CorridorNetDemand(
        demand_id="unmapped",
        net_name="unmapped",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id="unmapped-left", candidate_cell_ids=("missing",)),
            CorridorTerminal(terminal_id="unmapped-right", candidate_cell_ids=("right",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )

    result = negotiate_corridor_allocations(_line_graph(), (mapped, unmapped))

    assert result.failure_reason is CorridorFailureReason.TERMINAL_UNMAPPED
    assert result.allocations == ()
    assert result.unresolved_demand_ids == tuple(sorted(("mapped", "unmapped")))
    assert set(result.unresolved_demand_ids) == set(result.baseline_demand_order)


def test_unknown_terminal_candidates_are_ignored_when_a_valid_cell_remains() -> None:
    partly_mapped = CorridorNetDemand(
        demand_id="partly-mapped",
        net_name="partly-mapped",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(
                terminal_id="partly-mapped-left",
                candidate_cell_ids=("left", "unknown-cell"),
            ),
            CorridorTerminal(
                terminal_id="partly-mapped-right",
                candidate_cell_ids=("right",),
            ),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )
    valid = negotiate_corridor_allocations(_line_graph(), (partly_mapped,))
    assert valid.guidance_ready is True

    all_unknown = partly_mapped.model_copy(
        update={
            "terminals": (
                CorridorTerminal(
                    terminal_id="partly-mapped-left",
                    candidate_cell_ids=("missing-a",),
                ),
                CorridorTerminal(
                    terminal_id="partly-mapped-right",
                    candidate_cell_ids=("missing-b",),
                ),
            )
        }
    )
    invalid = negotiate_corridor_allocations(_line_graph(), (all_unknown,))
    assert invalid.failure_reason is CorridorFailureReason.TERMINAL_UNMAPPED
    assert invalid.unresolved_demand_ids == ("partly-mapped",)


def test_zero_cost_search_refuses_cycle_resources_in_final_tree() -> None:
    cells = tuple(
        CorridorCell(
            cell_id=cell_id,
            layer="F.Cu",
            ix=index,
            iy=0,
            bounds_mm=(float(index), 0.0, float(index + 1), 1.0),
        )
        for index, cell_id in enumerate(("s", "a", "b", "c", "z"))
    )
    graph = CorridorGraph(
        profile_fingerprint="0" * 64,
        layout_geometry_fingerprint="1" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=cells,
        portals=tuple(
            CorridorPortal(
                resource_id=resource_id,
                layer="F.Cu",
                cell_low=cell_low,
                cell_high=cell_high,
                orientation="vertical_cut",
                guaranteed_span_units=1,
                possible_span_units=1,
                verification=CorridorGeometryVerification.EXACT,
            )
            for resource_id, cell_low, cell_high in (
                ("s-a", "s", "a"),
                ("a-b", "a", "b"),
                ("b-c", "b", "c"),
                ("c-a", "c", "a"),
                ("a-z", "a", "z"),
            )
        ),
    )
    demand = CorridorNetDemand(
        demand_id="zero-cycle",
        net_name="zero-cycle",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id="source", candidate_cell_ids=("s",)),
            CorridorTerminal(terminal_id="target", candidate_cell_ids=("z",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )

    result = negotiate_corridor_allocations(
        graph,
        (demand,),
        cost_policy=CorridorCostPolicy(
            channel_step_cost_units=0,
            via_step_cost_units=0,
            present_factor_units=0,
            history_increment_units=0,
        ),
    )

    assert result.guidance_ready is True
    assert tuple(claim.resource_id for claim in result.allocations[0].portal_claims) == (
        "a-z",
        "s-a",
    )


def test_required_via_keeps_via_used_partial_tree_without_artificial_leaf() -> None:
    cells = (
        CorridorCell(cell_id="f0", layer="F.Cu", ix=0, iy=0, bounds_mm=(0, 0, 1, 1)),
        CorridorCell(cell_id="f1", layer="F.Cu", ix=1, iy=0, bounds_mm=(1, 0, 2, 1)),
        CorridorCell(cell_id="b0", layer="B.Cu", ix=0, iy=0, bounds_mm=(0, 0, 1, 1)),
        CorridorCell(cell_id="b1", layer="B.Cu", ix=1, iy=0, bounds_mm=(1, 0, 2, 1)),
    )
    graph = CorridorGraph(
        profile_fingerprint="2" * 64,
        layout_geometry_fingerprint="3" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=cells,
        portals=(
            CorridorPortal(
                resource_id="front-short",
                layer="F.Cu",
                cell_low="f0",
                cell_high="f1",
                orientation="vertical_cut",
                guaranteed_span_units=1,
                possible_span_units=1,
                verification=CorridorGeometryVerification.EXACT,
            ),
            CorridorPortal(
                resource_id="back-terminal",
                layer="B.Cu",
                cell_low="b0",
                cell_high="b1",
                orientation="vertical_cut",
                guaranteed_span_units=1,
                possible_span_units=1,
                verification=CorridorGeometryVerification.EXACT,
            ),
        ),
        via_portals=(
            CorridorViaPortal(
                resource_id="required-via",
                front_cell_id="f0",
                back_cell_id="b0",
                guaranteed_site_count=1,
                possible_site_count=1,
                candidate_sites_mm=((0.5, 0.5),),
                verification=CorridorGeometryVerification.EXACT,
            ),
        ),
    )
    demand = CorridorNetDemand(
        demand_id="required",
        net_name="required",
        width_mm=0.2,
        allowed_layers=("F.Cu", "B.Cu"),
        via_policy=CorridorViaPolicy.REQUIRED,
        terminals=(
            CorridorTerminal(terminal_id="t1-seed", candidate_cell_ids=("f0",)),
            CorridorTerminal(terminal_id="t2-choice", candidate_cell_ids=("f1", "b1")),
            CorridorTerminal(terminal_id="t3-colocated", candidate_cell_ids=("f0",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )

    result = negotiate_corridor_allocations(graph, (demand,))

    assert result.guidance_ready
    allocation = result.allocations[0]
    assert tuple(claim.resource_id for claim in allocation.portal_claims) == ("back-terminal",)
    assert tuple(claim.resource_id for claim in allocation.via_claims) == ("required-via",)
    assert allocation.cell_ids == ("b0", "b1", "f0")
    assert (
        len(allocation.portal_claims) + len(allocation.via_claims) == len(allocation.cell_ids) - 1
    )


def test_attempt_telemetry_records_success_and_zero_work_typed_failure() -> None:
    success = negotiate_corridor_allocations(
        _line_graph(),
        (_demand("a"), _demand("b")),
    )
    routing_pass = success.passes[0]

    assert tuple(item.demand_id for item in routing_pass.demand_attempts) == (
        routing_pass.demand_order
    )
    assert sum(item.expansion_count for item in routing_pass.demand_attempts) == (
        routing_pass.expansion_count
    )
    assert all(item.expansion_count > 0 for item in routing_pass.demand_attempts)

    zero_work = negotiate_corridor_allocations(
        _line_graph(),
        (_demand("a"),),
        budget=CorridorBudget(
            max_passes=1,
            max_expansions=0,
            max_expansions_per_demand=0,
            max_stagnant_passes=1,
        ),
    )
    assert zero_work.failure_reason is CorridorFailureReason.EXPANSION_BUDGET
    assert len(zero_work.passes[0].demand_attempts) == 1
    assert zero_work.passes[0].demand_attempts[0].demand_id == "a"
    assert zero_work.passes[0].demand_attempts[0].expansion_count == 0
    assert zero_work.passes[0].expansion_count == 0


def _colocated_demand(name: str) -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=name,
        net_name=name,
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id=f"{name}-a", candidate_cell_ids=("left",)),
            CorridorTerminal(terminal_id=f"{name}-b", candidate_cell_ids=("left",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )


def test_distinct_colocated_demands_succeed_without_expansions() -> None:
    result = negotiate_corridor_allocations(
        _line_graph(),
        (_colocated_demand("a"), _colocated_demand("b")),
        budget=CorridorBudget(
            max_passes=1,
            max_expansions=0,
            max_expansions_per_demand=0,
            max_stagnant_passes=1,
        ),
    )

    assert result.guidance_ready
    assert result.failure_reason is None
    assert result.resource_overuse == ()
    assert tuple(item.cell_ids for item in result.allocations) == (("left",), ("left",))
    assert tuple(item.expansion_count for item in result.passes[0].demand_attempts) == (0, 0)
    assert result.passes[0].expansion_count == 0


def test_exact_expansion_cap_allows_trailing_colocated_zero_work_demand() -> None:
    routed = _demand("a-route")
    colocated = _colocated_demand("z-colocated")
    probe = negotiate_corridor_allocations(_line_graph(), (routed,))
    exact_expansions = probe.passes[0].expansion_count
    assert exact_expansions > 0

    result = negotiate_corridor_allocations(
        _line_graph(),
        (colocated, routed),
        demand_order=(routed.demand_id, colocated.demand_id),
        budget=CorridorBudget(
            max_passes=1,
            max_expansions=exact_expansions,
            max_expansions_per_demand=exact_expansions,
            max_stagnant_passes=1,
        ),
    )

    assert result.guidance_ready
    attempts = result.passes[0].demand_attempts
    assert tuple(item.demand_id for item in attempts) == ("a-route", "z-colocated")
    assert tuple(item.expansion_count for item in attempts) == (exact_expansions, 0)
    assert result.passes[0].expansion_count == exact_expansions


def test_run_context_fingerprint_separates_identical_pass_state_by_graph_and_budget() -> None:
    graph = _line_graph()
    changed_graph = CorridorGraph.model_validate(
        {**graph.model_dump(), "profile_fingerprint": "2" * 64}
    )
    budget = CorridorBudget(
        max_passes=2,
        max_expansions=100,
        max_expansions_per_demand=100,
        max_stagnant_passes=1,
    )
    changed_budget = CorridorBudget(
        max_passes=3,
        max_expansions=100,
        max_expansions_per_demand=100,
        max_stagnant_passes=1,
    )
    baseline = negotiate_corridor_allocations(graph, (_demand("a"),), budget=budget)
    graph_variant = negotiate_corridor_allocations(
        changed_graph,
        (_demand("a"),),
        budget=budget,
    )
    budget_variant = negotiate_corridor_allocations(
        graph,
        (_demand("a"),),
        budget=changed_budget,
    )
    baseline_pass = baseline.passes[0]
    graph_pass = graph_variant.passes[0]
    budget_pass = budget_variant.passes[0]

    assert baseline_pass.model_dump(exclude={"run_context_fingerprint"}) == (
        graph_pass.model_dump(exclude={"run_context_fingerprint"})
    )
    assert baseline_pass.model_dump(exclude={"run_context_fingerprint"}) == (
        budget_pass.model_dump(exclude={"run_context_fingerprint"})
    )
    assert (
        len(
            {
                baseline_pass.run_context_fingerprint,
                graph_pass.run_context_fingerprint,
                budget_pass.run_context_fingerprint,
            }
        )
        == 3
    )


def test_geometry_budget_precedes_unsupported_issue_on_incomplete_graph() -> None:
    graph = _line_graph()
    unsupported = CorridorGeometryIssue(
        source_id="unsupported",
        verification=CorridorGeometryVerification.UNSUPPORTED,
        reason="opaque geometry",
    )
    incomplete = CorridorGraph.model_validate(
        {
            **graph.model_dump(),
            "geometry_complete": False,
            "issues": (unsupported,),
        }
    )
    complete_with_unsupported = CorridorGraph.model_validate(
        {**graph.model_dump(), "issues": (unsupported,)}
    )

    assert (
        negotiate_corridor_allocations(
            incomplete,
            (_demand("a"),),
        ).failure_reason
        is CorridorFailureReason.GEOMETRY_BUDGET
    )
    assert (
        negotiate_corridor_allocations(
            complete_with_unsupported,
            (_demand("a"),),
        ).failure_reason
        is CorridorFailureReason.UNSUPPORTED_GEOMETRY
    )


def test_baseline_hpwl_ignores_forbidden_layer_and_foreign_owner_candidates() -> None:
    graph = CorridorGraph(
        profile_fingerprint="4" * 64,
        layout_geometry_fingerprint="5" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=(
            CorridorCell(cell_id="left", layer="F.Cu", ix=0, iy=0, bounds_mm=(0, 0, 1, 1)),
            CorridorCell(cell_id="near", layer="F.Cu", ix=1, iy=0, bounds_mm=(1, 0, 2, 1)),
            CorridorCell(cell_id="far", layer="F.Cu", ix=2, iy=0, bounds_mm=(2, 0, 3, 1)),
            CorridorCell(
                cell_id="wrong-layer",
                layer="B.Cu",
                ix=100,
                iy=0,
                bounds_mm=(100, 0, 101, 1),
            ),
            CorridorCell(
                cell_id="foreign-owner",
                layer="F.Cu",
                ix=200,
                iy=0,
                bounds_mm=(200, 0, 201, 1),
                terminal_owner_net_names=("other",),
            ),
        ),
        portals=(
            CorridorPortal(
                resource_id="left-near",
                layer="F.Cu",
                cell_low="left",
                cell_high="near",
                orientation="vertical_cut",
                guaranteed_span_units=4,
                possible_span_units=4,
                verification=CorridorGeometryVerification.EXACT,
            ),
            CorridorPortal(
                resource_id="near-far",
                layer="F.Cu",
                cell_low="near",
                cell_high="far",
                orientation="vertical_cut",
                guaranteed_span_units=4,
                possible_span_units=4,
                verification=CorridorGeometryVerification.EXACT,
            ),
        ),
    )
    short = CorridorNetDemand(
        demand_id="a-short",
        net_name="a-short",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id="a-left", candidate_cell_ids=("left",)),
            CorridorTerminal(
                terminal_id="a-near",
                candidate_cell_ids=("foreign-owner", "near", "wrong-layer"),
            ),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )
    long = CorridorNetDemand(
        demand_id="b-long",
        net_name="b-long",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id="b-left", candidate_cell_ids=("left",)),
            CorridorTerminal(terminal_id="b-far", candidate_cell_ids=("far",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )

    result = negotiate_corridor_allocations(graph, (long, short))

    assert result.guidance_ready
    assert result.baseline_demand_order == ("a-short", "b-long")


def _crossed_alternatives_graph() -> CorridorGraph:
    cells = [
        CorridorCell(cell_id="x", layer="F.Cu", ix=0, iy=0, bounds_mm=(0, 0, 1, 1)),
        CorridorCell(cell_id="y", layer="F.Cu", ix=1, iy=0, bounds_mm=(1, 0, 2, 1)),
    ]
    portals = [
        CorridorPortal(
            resource_id="p",
            layer="F.Cu",
            cell_low="x",
            cell_high="y",
            orientation="vertical_cut",
            guaranteed_span_units=1,
            possible_span_units=1,
            verification=CorridorGeometryVerification.EXACT,
        )
    ]
    for net_name, offset in (("A", 10), ("B", 30)):
        branch = [f"{net_name}-s", *(f"{net_name}-a{i}" for i in range(1, 6)), f"{net_name}-t"]
        cells.extend(
            CorridorCell(
                cell_id=cell_id,
                layer="F.Cu",
                ix=offset + index,
                iy=0,
                bounds_mm=(offset + index, 0, offset + index + 1, 1),
                terminal_owner_net_names=(net_name,),
            )
            for index, cell_id in enumerate(branch)
        )
        portals.extend(
            (
                CorridorPortal(
                    resource_id=f"{net_name}-short-in",
                    layer="F.Cu",
                    cell_low=branch[0],
                    cell_high="x",
                    orientation="vertical_cut",
                    guaranteed_span_units=10,
                    possible_span_units=10,
                    verification=CorridorGeometryVerification.EXACT,
                ),
                CorridorPortal(
                    resource_id=f"{net_name}-short-out",
                    layer="F.Cu",
                    cell_low="y",
                    cell_high=branch[-1],
                    orientation="vertical_cut",
                    guaranteed_span_units=10,
                    possible_span_units=10,
                    verification=CorridorGeometryVerification.EXACT,
                ),
            )
        )
        portals.extend(
            CorridorPortal(
                resource_id=f"{net_name}-alt-{index}",
                layer="F.Cu",
                cell_low=cell_low,
                cell_high=cell_high,
                orientation="vertical_cut",
                guaranteed_span_units=10,
                possible_span_units=10,
                verification=CorridorGeometryVerification.EXACT,
            )
            for index, (cell_low, cell_high) in enumerate(zip(branch, branch[1:], strict=False), 1)
        )
    return CorridorGraph(
        profile_fingerprint="a" * 64,
        layout_geometry_fingerprint="b" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=tuple(cells),
        portals=tuple(portals),
    )


def _crossed_demand(net_name: str) -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=net_name,
        net_name=net_name,
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(
                terminal_id=f"{net_name}-source", candidate_cell_ids=(f"{net_name}-s",)
            ),
            CorridorTerminal(
                terminal_id=f"{net_name}-target", candidate_cell_ids=(f"{net_name}-t",)
            ),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )


_CROSSED_POLICY = CorridorCostPolicy(
    channel_step_cost_units=1,
    via_step_cost_units=5,
    present_factor_units=1,
    present_growth_numerator=2,
    present_growth_denominator=1,
    history_increment_units=4,
)
_CROSSED_BUDGET = CorridorBudget(
    max_passes=8,
    max_expansions=10_000,
    max_expansions_per_demand=1_000,
    max_stagnant_passes=4,
)


def _crossed_result() -> CorridorPlanResult:
    return negotiate_corridor_allocations(
        _crossed_alternatives_graph(),
        (_crossed_demand("B"), _crossed_demand("A")),
        budget=_CROSSED_BUDGET,
        cost_policy=_CROSSED_POLICY,
    )


def test_private_allocator_seam_invokes_injected_search_without_changing_result() -> None:
    calls: list[str] = []

    def recording_searcher(
        demand: CorridorNetDemand,
        graph: allocator_module._GraphIndex,
        ledger: CorridorCapacityLedger,
        history: Mapping[str, int],
        present_factor: int,
        expansion_limit: int,
    ) -> allocator_module._SearchOutcome:
        calls.append(demand.demand_id)
        return allocator_module._search_complete_tree(
            demand,
            graph,
            ledger,
            history,
            present_factor,
            expansion_limit,
        )

    injected = allocator_module._negotiate_corridor_allocations(
        _crossed_alternatives_graph(),
        (_crossed_demand("B"), _crossed_demand("A")),
        searcher=recording_searcher,
        budget=_CROSSED_BUDGET,
        cost_policy=_CROSSED_POLICY,
    )
    default = _crossed_result()

    assert calls == ["A", "B", "A", "B"]
    assert injected == default
    assert injected.semantic_fingerprint() == default.semantic_fingerprint()
    assert tuple(item.semantic_fingerprint() for item in injected.passes) == tuple(
        item.semantic_fingerprint() for item in default.passes
    )


def test_first_order_crossed_alternatives_converges_with_literal_authority() -> None:
    result = _crossed_result()

    assert result.guidance_ready
    assert result.baseline_demand_order == ("A", "B")
    assert len(result.passes) == 2
    assert tuple(item.objective for item in result.passes) == ((0, 1, 1, 1), (0, 0, 0, 0))
    assert tuple(item.expansion_count for item in result.passes) == (15, 16)
    assert sum(item.expansion_count for item in result.passes) == 31
    assert tuple(
        (item.resource_id, item.overuse_units) for item in result.passes[0].resource_overuse
    ) == (("p", 1),)
    assert result.passes[1].resource_overuse == ()
    assert {
        item.demand_id: tuple(claim.resource_id for claim in item.portal_claims)
        for item in result.allocations
    } == {
        "A": tuple(f"A-alt-{index}" for index in range(1, 7)),
        "B": tuple(f"B-alt-{index}" for index in range(1, 7)),
    }
    assert tuple(item.semantic_fingerprint() for item in result.passes) == (
        "0117e3f93c73a4640c30b36e7f75ec0dfb427d8a8ba20d92fc21987cbe851ae4",
        "7396b16d69959670cd0e48ba9a6cd96d232e5c2386bdd6a6701eeaaeee2e7dfa",
    )
    assert (
        result.semantic_fingerprint()
        == "9b498ac064a5f4359dd23f1d02d2ec4184c9de93846064b3cd6c99f038e0a245"
    )


def _cascade_graph() -> CorridorGraph:
    def cell(cell_id: str, ix: int, owner: tuple[str, ...] = ()) -> CorridorCell:
        return CorridorCell(
            cell_id=cell_id,
            layer="F.Cu",
            ix=ix,
            iy=0,
            bounds_mm=(ix, 0, ix + 1, 1),
            terminal_owner_net_names=owner,
        )

    def portal(
        resource_id: str, cell_low: str, cell_high: str, capacity: int = 1
    ) -> CorridorPortal:
        return CorridorPortal(
            resource_id=resource_id,
            layer="F.Cu",
            cell_low=cell_low,
            cell_high=cell_high,
            orientation="vertical_cut",
            guaranteed_span_units=capacity,
            possible_span_units=capacity,
            verification=CorridorGeometryVerification.EXACT,
        )

    cells = [cell("px", 0), cell("py", 1), cell("sx", 2), cell("sy", 3)]
    portals = [portal("p", "px", "py"), portal("s", "sx", "sy")]

    def add_short(net_name: str, left: str, right: str, offset: int) -> None:
        cells.extend(
            (
                cell(f"{net_name}-source", offset, (net_name,)),
                cell(f"{net_name}-target", offset + 9, (net_name,)),
            )
        )
        portals.extend(
            (
                portal(f"{net_name}-short-in", f"{net_name}-source", left, 10),
                portal(f"{net_name}-short-out", right, f"{net_name}-target", 10),
            )
        )

    def add_private_alternative(net_name: str, offset: int) -> None:
        branch = [
            f"{net_name}-source",
            *(f"{net_name}-alt{index}" for index in range(1, 6)),
            f"{net_name}-target",
        ]
        cells.extend(
            cell(cell_id, offset + index, (net_name,))
            for index, cell_id in enumerate(branch[1:-1], 1)
        )
        portals.extend(
            portal(f"{net_name}-alt-edge-{index}", low, high, 10)
            for index, (low, high) in enumerate(zip(branch, branch[1:], strict=False), 1)
        )

    add_short("A", "px", "py", 10)
    cells.extend(cell(f"A-alt{index}", 10 + index, ("A",)) for index in range(1, 4))
    a_alternative = (
        ("A-source", "A-alt1"),
        ("A-alt1", "A-alt2"),
        ("A-alt2", "A-alt3"),
        ("A-alt3", "sx"),
        ("sy", "A-target"),
    )
    portals.extend(
        portal(f"A-alt-edge-{index}", low, high, 10)
        for index, (low, high) in enumerate(a_alternative, 1)
    )
    add_short("B", "px", "py", 30)
    add_private_alternative("B", 30)
    add_short("C", "sx", "sy", 50)
    add_private_alternative("C", 50)
    return CorridorGraph(
        profile_fingerprint="c" * 64,
        layout_geometry_fingerprint="d" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=tuple(cells),
        portals=tuple(portals),
    )


def _cascade_demand(net_name: str) -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=net_name,
        net_name=net_name,
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(
                terminal_id=f"{net_name}-source-terminal",
                candidate_cell_ids=(f"{net_name}-source",),
            ),
            CorridorTerminal(
                terminal_id=f"{net_name}-target-terminal",
                candidate_cell_ids=(f"{net_name}-target",),
            ),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )


def _cascade_result() -> CorridorPlanResult:
    return negotiate_corridor_allocations(
        _cascade_graph(),
        tuple(_cascade_demand(name) for name in ("C", "B", "A")),
        budget=_CROSSED_BUDGET,
        cost_policy=_CROSSED_POLICY,
    )


def test_second_order_cascade_converges_with_literal_authority() -> None:
    result = _cascade_result()

    assert result.guidance_ready
    assert result.baseline_demand_order == ("A", "B", "C")
    assert tuple(item.demand_order for item in result.passes) == (
        ("A", "B", "C"),
        ("A", "B", "C"),
        ("A", "C", "B"),
    )
    assert tuple(item.objective for item in result.passes) == (
        (0, 1, 1, 1),
        (0, 1, 1, 1),
        (0, 0, 0, 0),
    )
    assert tuple(item.expansion_count for item in result.passes) == (22, 25, 24)
    assert sum(item.expansion_count for item in result.passes) == 71
    assert tuple(
        tuple((overuse.resource_id, overuse.overuse_units) for overuse in item.resource_overuse)
        for item in result.passes
    ) == ((("p", 1),), (("s", 1),), ())
    resources = {
        item.demand_id: tuple(claim.resource_id for claim in item.portal_claims)
        for item in result.allocations
    }
    assert resources["A"] == ("A-short-in", "A-short-out", "p")
    assert resources["B"] == tuple(f"B-alt-edge-{index}" for index in range(1, 7))
    assert resources["C"] == tuple(f"C-alt-edge-{index}" for index in range(1, 7))
    assert tuple(item.semantic_fingerprint() for item in result.passes) == (
        "8150b8b639dceabcd9db1f8c11776dc291e66191d7dd9e099834e72f1be134bf",
        "9951589f939d8f5210cf4aa8e775f057f4807be70117399ebcc534d229fdbfeb",
        "f5874b460f240695839263a083b2984b4dcd8fd66fade135fb3991ebc59571ba",
    )
    assert (
        result.semantic_fingerprint()
        == "0daded6ca0969603135d5a64fe2725ba2d0b076a47c15451bc90c94a348cd4bd"
    )


def test_one_less_pass_and_zero_patience_report_exact_initial_overuse() -> None:
    demands = (_crossed_demand("A"), _crossed_demand("B"))
    one_pass = negotiate_corridor_allocations(
        _crossed_alternatives_graph(),
        demands,
        budget=_CROSSED_BUDGET.model_copy(update={"max_passes": 1}),
        cost_policy=_CROSSED_POLICY,
    )
    zero_patience = negotiate_corridor_allocations(
        _crossed_alternatives_graph(),
        demands,
        budget=_CROSSED_BUDGET.model_copy(update={"max_stagnant_passes": 0}),
        cost_policy=_CROSSED_POLICY,
    )

    for result, reason in (
        (one_pass, CorridorFailureReason.PASS_BUDGET),
        (zero_patience, CorridorFailureReason.STAGNATION),
    ):
        assert result.failure_reason is reason
        assert len(result.passes) == 1
        assert result.passes[0].objective == (0, 1, 1, 1)
        assert tuple(
            (item.resource_id, item.overuse_units) for item in result.resource_overuse
        ) == (("p", 1),)


def test_total_and_per_demand_expansion_exhaustion_are_exact() -> None:
    demands = (_crossed_demand("A"), _crossed_demand("B"))
    total = negotiate_corridor_allocations(
        _crossed_alternatives_graph(),
        demands,
        budget=CorridorBudget(
            max_passes=1,
            max_expansions=14,
            max_expansions_per_demand=1_000,
            max_stagnant_passes=1,
        ),
        cost_policy=_CROSSED_POLICY,
    )
    per_demand = negotiate_corridor_allocations(
        _crossed_alternatives_graph(),
        demands,
        budget=CorridorBudget(
            max_passes=1,
            max_expansions=1_000,
            max_expansions_per_demand=7,
            max_stagnant_passes=1,
        ),
        cost_policy=_CROSSED_POLICY,
    )

    for result in (total, per_demand):
        assert result.failure_reason is CorridorFailureReason.EXPANSION_BUDGET
        assert result.unresolved_demand_ids == ("B",)
        assert tuple(item.expansion_count for item in result.passes[0].demand_attempts) == (7, 7)
        assert result.passes[0].expansion_count == 14
        assert tuple(item.demand_id for item in result.allocations) == ("A",)


def test_failed_replacement_restores_old_allocation_and_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_search = allocator_module._search_complete_tree
    calls = 0

    def fail_first_replacement(
        demand: CorridorNetDemand,
        graph: allocator_module._GraphIndex,
        ledger: CorridorCapacityLedger,
        history: Mapping[str, int],
        present_factor: int,
        expansion_limit: int,
    ) -> allocator_module._SearchOutcome:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise allocator_module._SearchFailure(CorridorFailureReason.EXPANSION_BUDGET, 0)
        return real_search(
            demand,
            graph,
            ledger,
            history,
            present_factor,
            expansion_limit,
        )

    monkeypatch.setattr(allocator_module, "_search_complete_tree", fail_first_replacement)
    result = _crossed_result()

    assert result.failure_reason is CorridorFailureReason.EXPANSION_BUDGET
    assert len(result.passes) == 2
    initial, failed_replacement = result.passes
    assert failed_replacement.demand_order == ("A",)
    assert failed_replacement.expansion_count == 0
    assert failed_replacement.allocation_fingerprint == initial.allocation_fingerprint
    assert failed_replacement.ledger_fingerprint == initial.ledger_fingerprint
    assert result.resource_overuse == initial.resource_overuse
    assert {
        item.demand_id: tuple(claim.resource_id for claim in item.portal_claims)
        for item in result.allocations
    } == {
        "A": ("A-short-in", "A-short-out", "p"),
        "B": ("B-short-in", "B-short-out", "p"),
    }


def test_explicit_prefix_then_heuristic_suffix_is_reversal_deterministic() -> None:
    graph = _line_graph().model_copy(
        update={
            "portals": (
                _line_graph()
                .portals[0]
                .model_copy(update={"guaranteed_span_units": 10, "possible_span_units": 10}),
            )
        }
    )
    demands = (_demand("prefix"), _quantity_demand("wide", 2), _demand("narrow"))
    forward = negotiate_corridor_allocations(
        graph,
        demands,
        demand_order=("prefix",),
    )
    reversed_input = negotiate_corridor_allocations(
        graph,
        tuple(reversed(demands)),
        demand_order=("prefix",),
    )

    assert forward.guidance_ready
    assert forward.baseline_demand_order == ("prefix", "wide", "narrow")
    assert reversed_input.semantic_fingerprint() == forward.semantic_fingerprint()
    assert reversed_input.passes == forward.passes
    assert reversed_input.allocations == forward.allocations
