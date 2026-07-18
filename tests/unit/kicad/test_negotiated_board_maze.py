"""R2.3b board-level proof that ordering alone cannot solve congestion."""

from __future__ import annotations

import itertools
import math
from collections import deque
from collections.abc import Iterable

import pytest

from pcbsmith.kicad.astar_router import route_board
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
)
from pcbsmith.kicad.library import FootprintSpec, PadSpec
from pcbsmith.kicad.negotiated_board import (
    ExactRouteCheckResult,
    NegotiatedBoardRouteResult,
    route_board_negotiated,
)
from pcbsmith.kicad.negotiated_graph import NegotiatedCostPolicy
from pcbsmith.kicad.negotiated_resources import _segment_distance_squared
from pcbsmith.kicad.virtual_drc import _point_seg_distance

GRID_MM = 2.0
TRACK_WIDTH_MM = 0.2
WALL_WIDTH_MM = 0.01
TERMINAL_FOOTPRINT = "Test:NegotiatedMazeTerminal"

# Four corridors are present in this 6x7 cell maze.  The ordinary router's
# locally shortest A corridor blocks both B corridors; the locally shortest B
# corridor likewise blocks both A corridors.  The longer outer A and B
# corridors are disjoint, so a complete solution exists but cannot be reached
# by changing which net is routed first.
FREE_CELLS = frozenset(
    {
        (0, 3),
        (0, 4),
        (0, 5),
        (0, 6),
        (1, 3),
        (1, 4),
        (1, 6),
        (2, 0),
        (2, 1),
        (2, 2),
        (2, 3),
        (2, 6),
        (3, 0),
        (3, 2),
        (3, 3),
        (3, 4),
        (3, 5),
        (3, 6),
        (4, 0),
        (4, 1),
        (4, 2),
        (5, 1),
        (5, 2),
    }
)
TERMINAL_CELLS = {
    "A1": (0, 3),
    "A2": (4, 1),
    "B1": (0, 5),
    "B2": (5, 1),
}
POLICY = NegotiatedCostPolicy(
    length_units_per_grid=1000,
    diagonal_length_units=1414,
    via_cost_units=5000,
    turn_cost_units=100,
    present_factor_units=1000,
    present_growth_numerator=2,
    present_growth_denominator=1,
    history_increment_units=10_000,
)
EXPECTED_PASS_FINGERPRINTS = (
    "6bf59d7fec8031f984f13102bc4a5dd112b53b4dc81c4f212bf13c5fba733a71",
    "1884e9fd36b5af6a57709cf1311e8a7b31d4ec6c4328618bd2c620a1fa67234b",
    "0734b8883000f8c4460be48bdb3e387afd10022bee24a8af28c8bc26fd394161",
)


def _point(cell: tuple[int, int]) -> tuple[float, float]:
    return (2.0 + GRID_MM * cell[0], 2.0 + GRID_MM * cell[1])


@pytest.fixture
def maze_board(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[BoardLayout, BoardNetlist]:
    footprint = FootprintSpec(
        pads=(
            PadSpec(
                "1",
                0.0,
                0.0,
                "smd",
                TRACK_WIDTH_MM,
                TRACK_WIDTH_MM,
                shape="circle",
                layers=("F.Cu", "F.Mask"),
            ),
        ),
        fab_rect=(-0.1, -0.1, 0.1, 0.1),
        silk_rect=None,
        x_min=-0.1,
        x_max=0.1,
        y_min=-0.1,
        y_max=0.1,
        attr="smd",
    )
    monkeypatch.setitem(FOOTPRINT_LIBRARY, TERMINAL_FOOTPRINT, footprint)
    components = tuple(
        BoardComponent(reference, "terminal", TERMINAL_FOOTPRINT, reference.lower())
        for reference in TERMINAL_CELLS
    )
    by_reference = {component.reference: component for component in components}
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet("A", (("A1", "1"), ("A2", "1"))),
            BoardNet("B", (("B1", "1"), ("B2", "1"))),
        ),
    )
    walls: list[TrackSegment] = []
    for cell in itertools.product(range(6), range(7)):
        x, y = _point(cell)
        if cell not in FREE_CELLS:
            walls.append(
                TrackSegment(
                    x,
                    y,
                    x,
                    y,
                    "F.Cu",
                    "~maze-wall",
                    WALL_WIDTH_MM,
                )
            )
        # B.Cu is intentionally unavailable, making this a one-layer capacity
        # proof rather than a test of layer switching.
        walls.append(
            TrackSegment(
                x,
                y,
                x,
                y,
                "B.Cu",
                "~maze-wall",
                WALL_WIDTH_MM,
            )
        )
    layout = BoardLayout(
        placements=tuple(
            (by_reference[reference], _point(cell)[0]) for reference, cell in TERMINAL_CELLS.items()
        ),
        segments=tuple(walls),
        vias=(),
        width_mm=14.0,
        height_mm=16.0,
        part_y_mm=tuple((reference, _point(cell)[1]) for reference, cell in TERMINAL_CELLS.items()),
    )
    return layout, netlist


def _connected(
    segments: Iterable[TrackSegment],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    adjacency: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for segment in segments:
        a = (segment.x1, segment.y1)
        b = (segment.x2, segment.y2)
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    queue = deque([start])
    visited = {start}
    while queue:
        point = queue.popleft()
        if point == end:
            return True
        for neighbour in adjacency.get(point, ()):
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)
    return False


def _exact_checker(
    layout: BoardLayout,
    _netlist: BoardNetlist,
) -> ExactRouteCheckResult:
    findings: set[str] = set()
    routes = {
        net_name: tuple(segment for segment in layout.segments if segment.net_name == net_name)
        for net_name in ("A", "B")
    }
    for net_name, references in {"A": ("A1", "A2"), "B": ("B1", "B2")}.items():
        start = _point(TERMINAL_CELLS[references[0]])
        end = _point(TERMINAL_CELLS[references[1]])
        if not routes[net_name] or not _connected(routes[net_name], start, end):
            findings.add(f"{net_name}:disconnected")
        if any(segment.layer != "F.Cu" for segment in routes[net_name]):
            findings.add(f"{net_name}:wrong-layer")
    required_route_gap = TRACK_WIDTH_MM + 0.2
    for a_segment in routes["A"]:
        for b_segment in routes["B"]:
            if (
                math.sqrt(
                    _segment_distance_squared(
                        (a_segment.x1, a_segment.y1),
                        (a_segment.x2, a_segment.y2),
                        (b_segment.x1, b_segment.y1),
                        (b_segment.x2, b_segment.y2),
                    )
                )
                < required_route_gap - 1e-9
            ):
                findings.add("A-B:copper-clearance")
    required_wall_gap = TRACK_WIDTH_MM / 2 + WALL_WIDTH_MM / 2 + 0.2
    front_walls = (
        segment
        for segment in layout.segments
        if segment.net_name == "~maze-wall" and segment.layer == "F.Cu"
    )
    front_wall_points = tuple((wall.x1, wall.y1) for wall in front_walls)
    for net_name, segments in routes.items():
        for segment in segments:
            if any(
                _point_seg_distance(
                    point,
                    (segment.x1, segment.y1),
                    (segment.x2, segment.y2),
                )
                < required_wall_gap - 1e-9
                for point in front_wall_points
            ):
                findings.add(f"{net_name}:wall-clearance")
    if any(via.net_name in routes for via in layout.vias):
        findings.add("target-via")
    return ExactRouteCheckResult(
        accepted=not findings,
        checker_id="unit-exact-maze-geometry-v1",
        finding_fingerprints=tuple(sorted(findings)),
    )


def _route_negotiated(
    layout: BoardLayout,
    netlist: BoardNetlist,
) -> NegotiatedBoardRouteResult:
    return route_board_negotiated(
        layout,
        netlist,
        target_nets=("B", "A"),
        net_order=("A", "B"),
        grid_mm=GRID_MM,
        default_width_mm=TRACK_WIDTH_MM,
        max_passes=3,
        max_stagnant_passes=2,
        max_expansions=20_000,
        max_expansions_per_net=15_000,
        cost_policy=POLICY,
        exact_checker=_exact_checker,
    )


@pytest.mark.parametrize("order", (("A", "B"), ("B", "A")))
def test_every_legacy_sequential_order_fails(
    maze_board: tuple[BoardLayout, BoardNetlist],
    order: tuple[str, str],
) -> None:
    layout, netlist = maze_board

    result = route_board(
        layout,
        netlist,
        net_order=order,
        max_restarts=0,
        grid_mm=GRID_MM,
        default_width_mm=TRACK_WIDTH_MM,
        max_expansions=20_000,
        max_expansions_per_net=20_000,
    )

    assert tuple(route.net_name for route in result.results) == (order[0],)
    assert result.failed == (order[1],)


def test_negotiated_board_route_converges_and_exact_geometry_accepts(
    maze_board: tuple[BoardLayout, BoardNetlist],
) -> None:
    layout, netlist = maze_board

    first = _route_negotiated(layout, netlist)
    repeated = _route_negotiated(layout, netlist)

    assert first == repeated
    assert first.run_result.semantic_fingerprint() == repeated.run_result.semantic_fingerprint()
    assert first.run_result.success
    assert first.run_result.accepted
    assert first.run_result.exact_check_accepted is True
    assert first.exact_check == ExactRouteCheckResult(
        True,
        "unit-exact-maze-geometry-v1",
    )
    assert first.run_result.resource_overuse == ()
    assert first.run_result.unresolved_net_names == ()
    assert tuple(route.net_name for route in first.results) == ("A", "B")
    assert all(route.segments for route in first.results)
    assert all(not route.vias for route in first.results)
    assert len(first.run_result.passes) == 3
    assert tuple(
        sum(item.overuse_units for item in routing_pass.resource_overuse)
        for routing_pass in first.run_result.passes
    ) == (4, 5, 0)
    assert (
        tuple(routing_pass.semantic_fingerprint() for routing_pass in first.run_result.passes)
        == EXPECTED_PASS_FINGERPRINTS
    )
    assert sum(routing_pass.expansion_count for routing_pass in first.run_result.passes) == 16_427
    assert math.isclose(first.results[0].length_mm, 16.0)
    assert math.isclose(first.results[1].length_mm, 22.0)
