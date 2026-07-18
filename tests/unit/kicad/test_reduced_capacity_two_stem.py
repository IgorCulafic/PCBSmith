from __future__ import annotations

from collections import deque
from dataclasses import replace

import pytest
from tests.fixtures.routing.reduced_capacity_two_stem import (
    CAPACITY_QUANTUM_MM,
    CLEARANCE_MM,
    COARSE_GRID_MM,
    DEMAND_SPAN_UNITS,
    DETAILED_GRID_MM,
    FOOTPRINT,
    NAMED_PORTAL_RESOURCE_ID,
    NET_NAMES,
    OUTLINE,
    PORTAL_RESIDUAL_UNITS,
    PORTAL_SPAN_UNITS,
    QUANTITY_CAPACITY,
    TERMINAL_FOOTPRINT_SPEC,
    TRACK_WIDTH_MM,
    ReducedCapacityTwoStemBoard,
    make_reduced_capacity_two_stem_board,
)

from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    build_corridor_route_guide,
)
from pcbsmith.corridor_ir import (
    CorridorBudget,
    CorridorGraph,
    CorridorNetDemand,
    CorridorViaPolicy,
)
from pcbsmith.corridor_summary import (
    VerifiedCorridorPlanSummary,
    verify_corridor_plan_summary,
)
from pcbsmith.kicad.board import FOOTPRINT_LIBRARY, BoardLayout, BoardNetlist, TrackSegment
from pcbsmith.kicad.corridor_guidance import project_corridor_route_guide
from pcbsmith.kicad.corridor_planner import build_corridor_graph
from pcbsmith.kicad.negotiated_board import (
    ExactRouteCheckResult,
    board_netlist_fingerprint,
    route_board_corridor_guided,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.kicad.virtual_drc import run_virtual_drc
from pcbsmith.routing_ir import RoutingFailureReason

OFF_CORRIDOR_PENALTY_UNITS = 50
EXPECTED_SOURCE_LAYOUT_FINGERPRINT = (
    "ee1774fc9654c45f6fa57a895309e9bcab8fa9bd5cef7cfcd9c0739acc0f76ef"
)
EXPECTED_NETLIST_FINGERPRINT = "962eeb43315b1ebfe139efc6a787c3a1d76bb503bae804982cf70956c4309c81"
EXPECTED_GRAPH_FINGERPRINT = "2438c4bf884adf4f38d7a36e759ede937618401fc6baed155ed97f851f0faa95"
EXPECTED_PLAN_FINGERPRINT = "8c7908cfa312a708a7bdc113df74cc3258faeea41b230dd569305b27edd85806"
EXPECTED_VERIFIED_SUMMARY_FINGERPRINT = (
    "c56abb45272ac6346474b2bd8cf30716070f714cb23ad3a2bcfc35efd183ca96"
)
EXPECTED_COARSE_GUIDE_FINGERPRINT = (
    "cd2d16bcaedc72e7518be395b49f1ef5fe95137769539c1a44e05cadca564fb6"
)
EXPECTED_PROJECTED_GUIDE_FINGERPRINT = (
    "d706699e16be17fa6c7143d03401bd82391095e89f5df898bce114d3c96cb10d"
)
EXPECTED_GUIDANCE_REPORT_FINGERPRINT = (
    "08ba6e9a47d4ac4dc0ff2af01948d1667c035f04cd211355572e5b5107cf1bd9"
)
EXPECTED_ROUTING_RUN_FINGERPRINT = (
    "7631058f8c0b3a6207587618d69e31f8cb2549268e5a273b30f8f571505567ac"
)
EXPECTED_ROUTED_LAYOUT_FINGERPRINT = (
    "ef1e2ff0b148fb1db38a647781cd4c091bcab4383f32bfb2e9dd7bf7adf535a7"
)
EXPECTED_SEGMENTS = (
    (3.0, 3.0, 5.0, 5.0, "F.Cu", "/STEM_A", 0.6),
    (5.0, 5.0, 5.0, 13.0, "F.Cu", "/STEM_A", 0.6),
    (3.0, 15.0, 5.0, 13.0, "F.Cu", "/STEM_A", 0.6),
    (9.0, 5.0, 11.0, 3.0, "F.Cu", "/STEM_B", 0.6),
    (9.0, 5.0, 9.0, 13.0, "F.Cu", "/STEM_B", 0.6),
    (9.0, 13.0, 11.0, 15.0, "F.Cu", "/STEM_B", 0.6),
)


@pytest.fixture
def stem_board(monkeypatch: pytest.MonkeyPatch) -> ReducedCapacityTwoStemBoard:
    monkeypatch.setitem(FOOTPRINT_LIBRARY, FOOTPRINT, TERMINAL_FOOTPRINT_SPEC)
    return make_reduced_capacity_two_stem_board()


def _build_authority(
    fixture: ReducedCapacityTwoStemBoard,
) -> tuple[CorridorGraph, tuple[CorridorNetDemand, ...]]:
    built = build_corridor_graph(
        fixture.layout,
        fixture.netlist,
        target_nets=NET_NAMES,
        default_width_mm=TRACK_WIDTH_MM,
        coarse_grid_mm=COARSE_GRID_MM,
        capacity_quantum_mm=CAPACITY_QUANTUM_MM,
    )
    assert built.complete
    assert built.planning_supported
    assert built.graph.geometry_complete
    assert built.graph.issues == ()
    assert (len(built.graph.cells), len(built.graph.portals), len(built.graph.via_portals)) == (
        30,
        28,
        11,
    )
    # The generated pad authority is front-copper.  This fixture reviews the
    # corresponding no-via routing intent while retaining the complete graph.
    demands = tuple(
        demand.model_copy(
            update={
                "allowed_layers": ("F.Cu",),
                "via_policy": CorridorViaPolicy.FORBIDDEN,
            }
        )
        for demand in built.demands
    )
    return built.graph, demands


def _portal_interval_and_crossing(
    graph: CorridorGraph, resource_id: str
) -> tuple[tuple[float, float], float]:
    cells = {cell.cell_id: cell for cell in graph.cells}
    portal = next(item for item in graph.portals if item.resource_id == resource_id)
    first = cells[portal.cell_low].bounds_mm
    second = cells[portal.cell_high].bounds_mm
    assert portal.orientation == "horizontal_cut"
    interval = (max(first[0], second[0]), min(first[2], second[2]))
    crossing = max(first[1], second[1])
    return interval, crossing


def _connected(
    segments: tuple[TrackSegment, ...], start: tuple[float, float], end: tuple[float, float]
) -> bool:
    adjacency: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for segment in segments:
        first = (segment.x1, segment.y1)
        second = (segment.x2, segment.y2)
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)
    pending = deque((start,))
    visited = {start}
    while pending:
        point = pending.popleft()
        if point == end:
            return True
        for neighbour in adjacency.get(point, ()):
            if neighbour not in visited:
                visited.add(neighbour)
                pending.append(neighbour)
    return False


def _crosses_physical_stem(segment: TrackSegment) -> bool:
    stem_midline_y = 9.0
    if segment.y1 == segment.y2:
        return segment.y1 == stem_midline_y and not (
            max(segment.x1, segment.x2) < 4.0 or min(segment.x1, segment.x2) > 10.0
        )
    if not min(segment.y1, segment.y2) <= stem_midline_y <= max(segment.y1, segment.y2):
        return False
    fraction = (stem_midline_y - segment.y1) / (segment.y2 - segment.y1)
    crossing_x = segment.x1 + fraction * (segment.x2 - segment.x1)
    return 4.0 <= crossing_x <= 10.0


def _independent_replay_check(
    layout: BoardLayout,
    netlist: BoardNetlist,
    terminal_points: tuple[tuple[str, tuple[float, float], tuple[float, float]], ...],
) -> ExactRouteCheckResult:
    findings = {
        f"virtual-drc:{finding.check}:{finding.message}"
        for finding in run_virtual_drc(layout, netlist)
    }
    if layout.vias:
        findings.add("unexpected-via")
    for net_name, start, end in terminal_points:
        segments = tuple(segment for segment in layout.segments if segment.net_name == net_name)
        if not segments or not _connected(segments, start, end):
            findings.add(f"disconnected:{net_name}")
        if not any(_crosses_physical_stem(segment) for segment in segments):
            findings.add(f"stem-not-crossed:{net_name}")
        if any(segment.layer != "F.Cu" for segment in segments):
            findings.add(f"non-front-copper:{net_name}")
    return ExactRouteCheckResult(
        accepted=not findings,
        checker_id="unit-reduced-capacity-two-stem-replay-v1",
        finding_fingerprints=tuple(findings),
    )


def _reachable_without_named_portal(graph: CorridorGraph, demand: CorridorNetDemand) -> bool:
    cells = {cell.cell_id: cell for cell in graph.cells}
    adjacency = {cell_id: set[str]() for cell_id in cells}
    for portal in graph.portals:
        if portal.layer != "F.Cu" or portal.resource_id == NAMED_PORTAL_RESOURCE_ID:
            continue
        adjacency[portal.cell_low].add(portal.cell_high)
        adjacency[portal.cell_high].add(portal.cell_low)
    starts = set(demand.terminals[0].candidate_cell_ids)
    targets = set(demand.terminals[1].candidate_cell_ids)
    pending = deque(starts)
    visited = set(starts)
    while pending:
        cell_id = pending.popleft()
        if cell_id in targets:
            return True
        for neighbour in adjacency[cell_id]:
            if neighbour not in visited and cells[neighbour].layer == "F.Cu":
                visited.add(neighbour)
                pending.append(neighbour)
    return False


def test_capacity_two_stem_binds_r3_guidance_and_routed_unchecked_r2(
    stem_board: ReducedCapacityTwoStemBoard,
) -> None:
    layout, netlist = stem_board.layout, stem_board.netlist
    assert layout.outline == OUTLINE
    assert stem_board.terminal_points == (
        ("/STEM_A", (3.0, 3.0), (3.0, 15.0)),
        ("/STEM_B", (11.0, 3.0), (11.0, 15.0)),
    )
    assert tuple((net.name, net.nodes) for net in netlist.nets) == (
        ("/STEM_A", (("J1", "1"), ("J2", "1"))),
        ("/STEM_B", (("J3", "1"), ("J4", "1"))),
    )
    assert board_layout_fingerprint(layout) == EXPECTED_SOURCE_LAYOUT_FINGERPRINT
    assert board_netlist_fingerprint(netlist) == EXPECTED_NETLIST_FINGERPRINT

    graph, demands = _build_authority(stem_board)
    repeated_graph, repeated_demands = _build_authority(stem_board)
    assert (graph, demands) == (repeated_graph, repeated_demands)
    assert graph.coarse_grid_mm == COARSE_GRID_MM
    assert graph.capacity_quantum_mm == CAPACITY_QUANTUM_MM
    assert graph.semantic_fingerprint() == EXPECTED_GRAPH_FINGERPRINT
    assert {demand.net_name for demand in demands} == set(NET_NAMES)
    assert all(demand.width_mm == TRACK_WIDTH_MM for demand in demands)
    assert all(demand.effective_clearance_mm == CLEARANCE_MM for demand in demands)
    assert all(demand.ordinary_span_units == DEMAND_SPAN_UNITS for demand in demands)
    assert DEMAND_SPAN_UNITS == int((TRACK_WIDTH_MM + CLEARANCE_MM) / CAPACITY_QUANTUM_MM)

    portal = next(item for item in graph.portals if item.resource_id == NAMED_PORTAL_RESOURCE_ID)
    interval, crossing = _portal_interval_and_crossing(graph, portal.resource_id)
    assert portal.layer == "F.Cu"
    assert interval == (6.0, 8.0)
    assert crossing == 10.0
    assert interval[1] - interval[0] == COARSE_GRID_MM
    assert portal.guaranteed_span_units == PORTAL_SPAN_UNITS
    assert portal.possible_span_units == PORTAL_SPAN_UNITS
    assert PORTAL_SPAN_UNITS == int(COARSE_GRID_MM / CAPACITY_QUANTUM_MM)
    assert PORTAL_SPAN_UNITS // DEMAND_SPAN_UNITS == QUANTITY_CAPACITY
    assert PORTAL_SPAN_UNITS % DEMAND_SPAN_UNITS == PORTAL_RESIDUAL_UNITS

    plan = negotiate_corridor_allocations(graph, demands)
    assert plan == negotiate_corridor_allocations(graph, demands)
    assert plan.guidance_ready
    assert plan.failure_reason is None
    assert plan.resource_overuse == ()
    assert plan.semantic_fingerprint() == EXPECTED_PLAN_FINGERPRINT
    assert len(plan.allocations) == 2
    for allocation in plan.allocations:
        named_claim = next(
            claim
            for claim in allocation.portal_claims
            if claim.resource_id == NAMED_PORTAL_RESOURCE_ID
        )
        assert named_claim.demand_units == DEMAND_SPAN_UNITS
        assert allocation.via_claims == ()

    verified = verify_corridor_plan_summary(graph, demands, plan)
    assert isinstance(verified, VerifiedCorridorPlanSummary)
    assert verified == verify_corridor_plan_summary(graph, demands, plan)
    assert verified.graph == graph
    assert verified.demands == tuple(sorted(demands, key=lambda item: item.demand_id))
    assert verified.plan == plan
    assert verified.summary.guidance_ready
    assert verified.summary.channel_total_overflow_units == 0
    assert verified.semantic_fingerprint() == EXPECTED_VERIFIED_SUMMARY_FINGERPRINT

    coarse_guide = build_corridor_route_guide(
        graph,
        plan,
        off_corridor_penalty_units=OFF_CORRIDOR_PENALTY_UNITS,
    )
    assert coarse_guide is not None
    assert coarse_guide.graph_fingerprint == graph.semantic_fingerprint()
    assert coarse_guide.plan_fingerprint == plan.semantic_fingerprint()
    assert coarse_guide.layout_geometry_fingerprint == graph.layout_geometry_fingerprint
    assert coarse_guide.semantic_fingerprint() == EXPECTED_COARSE_GUIDE_FINGERPRINT
    projected = project_corridor_route_guide(
        coarse_guide,
        graph,
        layout,
        grid_mm=DETAILED_GRID_MM,
    )
    assert projected.source_guide_fingerprint == coarse_guide.semantic_fingerprint()
    assert projected.semantic_fingerprint() == EXPECTED_PROJECTED_GUIDE_FINGERPRINT

    route_kwargs = {
        "corridor_graph": graph,
        "corridor_plan": plan,
        "off_corridor_penalty_units": OFF_CORRIDOR_PENALTY_UNITS,
        "target_nets": NET_NAMES,
        "default_width_mm": TRACK_WIDTH_MM,
        "grid_mm": DETAILED_GRID_MM,
        "max_passes": 4,
        "max_expansions": 20_000,
        "max_expansions_per_net": 10_000,
        "exact_checker": None,
    }
    routed = route_board_corridor_guided(layout, netlist, **route_kwargs)
    repeated = route_board_corridor_guided(layout, netlist, **route_kwargs)
    assert routed == repeated
    assert routed.guidance.disposition is CorridorGuidanceDisposition.APPLIED
    assert routed.guidance.guided_net_names == NET_NAMES
    assert routed.guidance.unguided_net_names == ()
    assert routed.guidance.graph_fingerprint == graph.semantic_fingerprint()
    assert routed.guidance.plan_fingerprint == plan.semantic_fingerprint()
    assert routed.guidance.guide_fingerprint == projected.semantic_fingerprint()
    assert routed.guidance.exact_check_fingerprint is None
    assert routed.guidance.semantic_fingerprint() == EXPECTED_GUIDANCE_REPORT_FINGERPRINT

    route_result = routed.route_result
    run = route_result.run_result
    assert run.success
    assert not run.accepted
    assert run.exact_check_accepted is None
    assert run.failure_reason is None
    assert run.resource_overuse == ()
    assert run.budget.max_expansions == 20_000
    assert run.budget.max_expansions_per_net == 10_000
    assert len(run.passes) == 1
    assert run.passes[0].expansion_count == 734
    assert tuple(
        (item.net_name, item.expansion_count, item.routed) for item in run.passes[0].net_telemetry
    ) == (("/STEM_A", 367, True), ("/STEM_B", 367, True))
    assert route_result.exact_check is None
    assert route_result.exact_check_evidence is None
    assert route_result.checked_netlist is None
    assert route_result.order == NET_NAMES
    assert run.semantic_fingerprint() == EXPECTED_ROUTING_RUN_FINGERPRINT
    assert board_layout_fingerprint(route_result.layout) == EXPECTED_ROUTED_LAYOUT_FINGERPRINT
    assert route_result.layout.vias == ()
    assert (
        tuple(
            (
                segment.x1,
                segment.y1,
                segment.x2,
                segment.y2,
                segment.layer,
                segment.net_name,
                segment.width_mm,
            )
            for segment in route_result.layout.segments
        )
        == EXPECTED_SEGMENTS
    )
    replay = _independent_replay_check(
        route_result.layout,
        netlist,
        stem_board.terminal_points,
    )
    assert replay == ExactRouteCheckResult(
        accepted=True,
        checker_id="unit-reduced-capacity-two-stem-replay-v1",
    )

    one_less_budget = route_board_corridor_guided(
        layout,
        netlist,
        **{**route_kwargs, "max_expansions": 733},
    ).route_result.run_result
    assert not one_less_budget.success
    assert one_less_budget.failure_reason is RoutingFailureReason.EXPANSION_BUDGET
    assert one_less_budget.unresolved_net_names == ("/STEM_B",)
    assert one_less_budget.resource_overuse == ()
    assert len(one_less_budget.passes) == 1
    assert one_less_budget.passes[0].expansion_count == 733
    assert tuple(
        (item.net_name, item.expansion_count, item.routed, item.failure_reason)
        for item in one_less_budget.passes[0].net_telemetry
    ) == (
        ("/STEM_A", 367, True, None),
        ("/STEM_B", 366, False, RoutingFailureReason.EXPANSION_BUDGET),
    )


def test_one_unit_less_capacity_overuses_the_named_stem_portal(
    stem_board: ReducedCapacityTwoStemBoard,
) -> None:
    graph, demands = _build_authority(stem_board)
    reduced_capacity = 2 * DEMAND_SPAN_UNITS - 1
    reduced_portals = tuple(
        portal.model_copy(
            update={
                "guaranteed_span_units": reduced_capacity,
                "possible_span_units": reduced_capacity,
            }
        )
        if portal.resource_id == NAMED_PORTAL_RESOURCE_ID
        else portal
        for portal in graph.portals
    )
    reduced_graph = CorridorGraph.model_validate(
        {**graph.model_dump(mode="python"), "portals": reduced_portals}
    )
    result = negotiate_corridor_allocations(
        reduced_graph,
        demands,
        budget=CorridorBudget(
            max_passes=1,
            max_expansions=1_000_000,
            max_expansions_per_demand=100_000,
            max_stagnant_passes=1,
        ),
    )
    assert not result.guidance_ready
    assert result.failure_reason == "pass_budget"
    assert result.unresolved_demand_ids == ()
    assert len(result.allocations) == 2
    assert len(result.resource_overuse) == 1
    overuse = result.resource_overuse[0]
    assert overuse.resource_id == NAMED_PORTAL_RESOURCE_ID
    assert overuse.capacity_units == reduced_capacity
    assert overuse.demand_units == 2 * DEMAND_SPAN_UNITS
    assert overuse.overuse_units == 1
    assert (
        build_corridor_route_guide(
            reduced_graph,
            result,
            off_corridor_penalty_units=OFF_CORRIDOR_PENALTY_UNITS,
        )
        is None
    )


def test_stale_authority_and_apparent_evasion_fail_closed(
    stem_board: ReducedCapacityTwoStemBoard,
) -> None:
    graph, demands = _build_authority(stem_board)
    plan = negotiate_corridor_allocations(graph, demands)
    verified = verify_corridor_plan_summary(graph, demands, plan)
    coarse_guide = build_corridor_route_guide(
        graph,
        plan,
        off_corridor_penalty_units=OFF_CORRIDOR_PENALTY_UNITS,
    )
    assert coarse_guide is not None

    stale_graph = graph.model_copy(update={"capacity_quantum_mm": 0.2})
    assert (
        build_corridor_route_guide(
            stale_graph,
            plan,
            off_corridor_penalty_units=OFF_CORRIDOR_PENALTY_UNITS,
        )
        is None
    )

    stale_summary = verified.summary.model_copy(
        update={"expansion_count": verified.summary.expansion_count + 1}
    )
    with pytest.raises(ValueError, match="does not match source replay"):
        VerifiedCorridorPlanSummary.model_validate(
            {**verified.model_dump(mode="python"), "summary": stale_summary}
        )

    stale_guide = coarse_guide.model_copy(update={"layout_geometry_fingerprint": "0" * 64})
    with pytest.raises(ValueError, match="layout fingerprint does not match"):
        project_corridor_route_guide(
            stale_guide,
            graph,
            stem_board.layout,
            grid_mm=DETAILED_GRID_MM,
        )

    # Removing the named cut disconnects every front-copper terminal pair;
    # no shorter coarse path can evade the reviewed stem resource.
    assert all(not _reachable_without_named_portal(graph, demand) for demand in demands)

    apparent_evasion = replace(
        stem_board.layout,
        segments=(
            TrackSegment(3.0, 3.0, 3.0, 15.0, "F.Cu", "/STEM_A", TRACK_WIDTH_MM),
            TrackSegment(11.0, 3.0, 11.0, 15.0, "F.Cu", "/STEM_B", TRACK_WIDTH_MM),
        ),
    )
    rejected = _independent_replay_check(
        apparent_evasion,
        stem_board.netlist,
        stem_board.terminal_points,
    )
    assert not rejected.accepted
    assert "stem-not-crossed:/STEM_A" in rejected.finding_fingerprints
    assert "stem-not-crossed:/STEM_B" in rejected.finding_fingerprints
