from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_ir import (
    CorridorBudget,
    CorridorCell,
    CorridorGeometryIssue,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPortal,
    CorridorTerminal,
    CorridorViaPolicy,
    CorridorViaPortal,
)
from pcbsmith.corridor_summary import (
    VerifiedCorridorPlanSummary,
    summarize_corridor_plan,
    verify_corridor_plan_summary,
)


def _cell(
    cell_id: str,
    layer: str,
    ix: int,
    owners: tuple[str, ...] = (),
) -> CorridorCell:
    return CorridorCell(
        cell_id=cell_id,
        layer=layer,
        ix=ix,
        iy=0,
        bounds_mm=(float(ix), 0.0, float(ix + 1), 1.0),
        terminal_owner_net_names=owners,
    )


def _demand(
    demand_id: str,
    net_name: str,
    start: str,
    end: str,
    *,
    span_units: int = 1,
    via_policy: CorridorViaPolicy = CorridorViaPolicy.FORBIDDEN,
    layers: tuple[str, ...] = ("F.Cu",),
) -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=demand_id,
        net_name=net_name,
        width_mm=0.2,
        allowed_layers=layers,  # type: ignore[arg-type]
        via_policy=via_policy,
        terminals=(
            CorridorTerminal(terminal_id=f"{demand_id}:start", candidate_cell_ids=(start,)),
            CorridorTerminal(terminal_id=f"{demand_id}:end", candidate_cell_ids=(end,)),
        ),
        ordinary_span_units=span_units,
        effective_clearance_mm=0.1,
    )


def _mixed_graph(*, reverse: bool = False) -> CorridorGraph:
    cells = (
        _cell("front:left", "F.Cu", 0, ("/A",)),
        _cell("front:right", "F.Cu", 1),
        _cell("back:right", "B.Cu", 1, ("/A",)),
    )
    portals = (
        CorridorPortal(
            resource_id="channel:front",
            layer="F.Cu",
            cell_low="front:left",
            cell_high="front:right",
            orientation="vertical_cut",
            guaranteed_span_units=3,
            possible_span_units=3,
            verification=CorridorGeometryVerification.EXACT,
        ),
    )
    vias = (
        CorridorViaPortal(
            resource_id="via:right",
            front_cell_id="front:right",
            back_cell_id="back:right",
            guaranteed_site_count=2,
            possible_site_count=2,
            candidate_sites_mm=((1.5, 0.5), (1.75, 0.5)),
            verification=CorridorGeometryVerification.EXACT,
        ),
    )
    issues = (
        CorridorGeometryIssue(
            source_id="bounded:b",
            layer="B.Cu",
            verification=CorridorGeometryVerification.BOUNDED_APPROXIMATION,
            maximum_error_mm=0.02,
            reason="bounded obstacle edge",
            affected_cell_ids=("back:right",),
        ),
        CorridorGeometryIssue(
            source_id="exact:a",
            layer="F.Cu",
            verification=CorridorGeometryVerification.EXACT,
            reason="retained exact note",
            affected_cell_ids=("front:right",),
        ),
    )
    return CorridorGraph(
        profile_fingerprint="a" * 64,
        layout_geometry_fingerprint="b" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=0.1,
        cells=tuple(reversed(cells)) if reverse else cells,
        portals=tuple(reversed(portals)) if reverse else portals,
        via_portals=tuple(reversed(vias)) if reverse else vias,
        issues=tuple(reversed(issues)) if reverse else issues,
    )


def _mixed_demand() -> CorridorNetDemand:
    return _demand(
        "demand:a",
        "/A",
        "front:left",
        "back:right",
        span_units=2,
        via_policy=CorridorViaPolicy.REQUIRED,
        layers=("F.Cu", "B.Cu"),
    )


def test_empty_and_zero_work_plans_keep_resource_kinds_separate() -> None:
    empty_graph = CorridorGraph(
        profile_fingerprint="0" * 64,
        layout_geometry_fingerprint="1" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
    )
    empty_plan = negotiate_corridor_allocations(empty_graph, ())
    empty = summarize_corridor_plan(empty_graph, (), empty_plan)
    assert empty.guidance_ready
    assert empty.channel_guaranteed_capacity_units == 0
    assert empty.via_guaranteed_capacity_units == 0
    assert empty.channel_committed_demand_units == 0
    assert empty.via_committed_demand_units == 0

    cell = _cell("shared", "F.Cu", 0, ("/ZERO",))
    graph = empty_graph.model_copy(update={"cells": (cell,)})
    demand = _demand("zero", "/ZERO", "shared", "shared")
    plan = negotiate_corridor_allocations(graph, (demand,))
    zero = summarize_corridor_plan(graph, (demand,), plan)
    assert zero.guidance_ready
    assert zero.expansion_count == 0
    assert zero.channel_committed_demand_units == 0
    assert zero.via_committed_demand_units == 0


def test_success_summary_reports_exact_channel_and_via_quantities_and_literal_identity() -> None:
    graph = _mixed_graph()
    demand = _mixed_demand()
    plan = negotiate_corridor_allocations(graph, (demand,))
    summary = summarize_corridor_plan(graph, (demand,), plan)

    assert summary.guidance_ready
    assert summary.failure_reason is None
    assert summary.unresolved_demand_ids == ()
    assert summary.channel_guaranteed_capacity_units == 3
    assert summary.channel_committed_demand_units == 2
    assert summary.channel_total_overflow_units == 0
    assert summary.via_guaranteed_capacity_units == 2
    assert summary.via_committed_demand_units == 1
    assert summary.via_total_overflow_units == 0
    assert summary.pass_count == 1
    assert summary.expansion_count > 0
    assert tuple(issue.source_id for issue in summary.geometry_issues) == (
        "bounded:b",
        "exact:a",
    )
    assert summary.graph_fingerprint == graph.semantic_fingerprint()
    assert summary.plan_fingerprint == plan.semantic_fingerprint()
    assert (
        summary.semantic_fingerprint()
        == "b254e4c0afd7bdb84b8087239a798fd9a41f7516f173373739980fa4d69ef691"
    )


def _overloaded_graph() -> CorridorGraph:
    return CorridorGraph(
        profile_fingerprint="2" * 64,
        layout_geometry_fingerprint="3" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=(
            _cell("a:left", "F.Cu", 0, ("/A",)),
            _cell("left", "F.Cu", 1),
            _cell("right", "F.Cu", 2),
            _cell("a:right", "F.Cu", 3, ("/A",)),
            _cell("b:left", "F.Cu", 4, ("/B",)),
            _cell("b:right", "F.Cu", 5, ("/B",)),
        ),
        portals=(
            CorridorPortal(
                resource_id="a:in",
                layer="F.Cu",
                cell_low="a:left",
                cell_high="left",
                orientation="vertical_cut",
                guaranteed_span_units=10,
                possible_span_units=10,
                verification=CorridorGeometryVerification.EXACT,
            ),
            CorridorPortal(
                resource_id="bottleneck",
                layer="F.Cu",
                cell_low="left",
                cell_high="right",
                orientation="vertical_cut",
                guaranteed_span_units=3,
                possible_span_units=3,
                verification=CorridorGeometryVerification.EXACT,
            ),
            CorridorPortal(
                resource_id="a:out",
                layer="F.Cu",
                cell_low="right",
                cell_high="a:right",
                orientation="vertical_cut",
                guaranteed_span_units=10,
                possible_span_units=10,
                verification=CorridorGeometryVerification.EXACT,
            ),
            CorridorPortal(
                resource_id="b:in",
                layer="F.Cu",
                cell_low="b:left",
                cell_high="left",
                orientation="vertical_cut",
                guaranteed_span_units=10,
                possible_span_units=10,
                verification=CorridorGeometryVerification.EXACT,
            ),
            CorridorPortal(
                resource_id="b:out",
                layer="F.Cu",
                cell_low="right",
                cell_high="b:right",
                orientation="vertical_cut",
                guaranteed_span_units=10,
                possible_span_units=10,
                verification=CorridorGeometryVerification.EXACT,
            ),
        ),
    )


def test_overloaded_summary_reports_channel_overflow_without_via_unit_mixing() -> None:
    graph = _overloaded_graph()
    demands = (
        _demand("a", "/A", "a:left", "a:right", span_units=2),
        _demand("b", "/B", "b:left", "b:right", span_units=2),
    )
    plan = negotiate_corridor_allocations(
        graph,
        demands,
        budget=CorridorBudget(
            max_passes=2,
            max_expansions=100,
            max_expansions_per_demand=20,
            max_stagnant_passes=1,
        ),
    )
    summary = summarize_corridor_plan(graph, demands, plan)

    assert not summary.guidance_ready
    assert summary.channel_guaranteed_capacity_units == 43
    assert summary.channel_committed_demand_units == 12
    assert summary.channel_total_overflow_units == 1
    assert summary.channel_maximum_overflow_units == 1
    assert summary.via_guaranteed_capacity_units == 0
    assert summary.via_committed_demand_units == 0
    assert summary.via_total_overflow_units == 0
    assert summary.via_maximum_overflow_units == 0


def test_unresolved_summary_preserves_typed_plan_failure_and_work_totals() -> None:
    graph = _overloaded_graph()
    demand = _demand("a", "/A", "a:left", "a:right")
    plan = negotiate_corridor_allocations(
        graph,
        (demand,),
        budget=CorridorBudget(
            max_passes=1,
            max_expansions=0,
            max_expansions_per_demand=0,
            max_stagnant_passes=0,
        ),
    )
    summary = summarize_corridor_plan(graph, (demand,), plan)

    assert not summary.guidance_ready
    assert summary.failure_reason is not None
    assert summary.unresolved_demand_ids == ("a",)
    assert summary.pass_count == 1
    assert summary.expansion_count == 0
    assert summary.channel_committed_demand_units == 0


@pytest.mark.parametrize("stale", ["graph", "demand"])
def test_stale_plan_fingerprints_are_rejected(stale: str) -> None:
    graph = _mixed_graph()
    demand = _mixed_demand()
    plan = negotiate_corridor_allocations(graph, (demand,))
    selected_graph = (
        graph.model_copy(update={"layout_geometry_fingerprint": "f" * 64})
        if stale == "graph"
        else graph
    )
    selected_demands = (
        (demand.model_copy(update={"ordinary_span_units": 3}),) if stale == "demand" else (demand,)
    )

    with pytest.raises(ValueError, match=f"{stale} fingerprint is stale"):
        summarize_corridor_plan(selected_graph, selected_demands, plan)


def test_reversed_graph_and_demand_input_order_has_identical_summary() -> None:
    graph = _overloaded_graph()
    demands = (
        _demand("a", "/A", "a:left", "a:right", span_units=2),
        _demand("b", "/B", "b:left", "b:right", span_units=2),
    )
    plan = negotiate_corridor_allocations(graph, demands)
    first = summarize_corridor_plan(graph, demands, plan)
    reversed_summary = summarize_corridor_plan(
        CorridorGraph.model_validate(
            {
                **graph.model_dump(),
                "cells": tuple(reversed(graph.cells)),
                "portals": tuple(reversed(graph.portals)),
            }
        ),
        tuple(reversed(demands)),
        plan,
    )

    assert first == reversed_summary
    assert first.semantic_fingerprint() == reversed_summary.semantic_fingerprint()


def test_verified_summary_replays_roundtrips_and_normalizes_demand_order() -> None:
    graph = _overloaded_graph()
    demands = (
        _demand("a", "/A", "a:left", "a:right", span_units=2),
        _demand("b", "/B", "b:left", "b:right", span_units=2),
    )
    plan = negotiate_corridor_allocations(graph, demands)
    first = verify_corridor_plan_summary(graph, demands, plan)
    reversed_input = verify_corridor_plan_summary(graph, tuple(reversed(demands)), plan)
    restored = VerifiedCorridorPlanSummary.model_validate_json(first.model_dump_json())
    assert first == reversed_input == restored
    assert tuple(demand.demand_id for demand in first.demands) == ("a", "b")
    assert first.summary == summarize_corridor_plan(graph, demands, plan)
    assert first.summary.channel_total_overflow_units == 1


@pytest.mark.parametrize("source", ("summary", "graph", "demand", "plan"))
def test_verified_summary_rejects_tampered_or_stale_nested_authority(
    source: str,
) -> None:
    graph = _mixed_graph()
    demand = _mixed_demand()
    plan = negotiate_corridor_allocations(graph, (demand,))
    verified = verify_corridor_plan_summary(graph, (demand,), plan)
    update: dict[str, object]
    if source == "summary":
        update = {
            "summary": verified.summary.model_copy(update={"channel_committed_demand_units": 99})
        }
    elif source == "graph":
        update = {"graph": graph.model_copy(update={"layout_geometry_fingerprint": "f" * 64})}
    elif source == "demand":
        update = {"demands": (demand.model_copy(update={"ordinary_span_units": 3}),)}
    else:
        update = {"plan": plan.model_copy(update={"graph_fingerprint": "f" * 64})}
    forged = verified.model_copy(update=update)
    with pytest.raises(ValueError, match="stale|source replay"):
        VerifiedCorridorPlanSummary.model_validate_json(forged.model_dump_json())


def test_verified_nested_sources_are_frozen_and_cannot_alias_mutation() -> None:
    graph = _mixed_graph()
    demand = _mixed_demand()
    verified = verify_corridor_plan_summary(
        graph, (demand,), negotiate_corridor_allocations(graph, (demand,))
    )
    before = verified.semantic_fingerprint()
    with pytest.raises(ValidationError, match="frozen_instance"):
        verified.graph.layout_geometry_fingerprint = "f" * 64
    assert verified.semantic_fingerprint() == before
