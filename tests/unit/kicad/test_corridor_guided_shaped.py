from __future__ import annotations

from collections import deque

import pytest

from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_guidance import build_corridor_route_guide
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
)
from pcbsmith.kicad.corridor_guidance import project_corridor_route_guide
from pcbsmith.kicad.corridor_planner import build_corridor_graph
from pcbsmith.kicad.library import FootprintSpec, PadSpec
from pcbsmith.kicad.negotiated_board import (
    ExactRouteCheckResult,
    route_board_corridor_guided,
)
from pcbsmith.kicad.virtual_drc import run_virtual_drc

FOOTPRINT = "Test:CorridorShapedTerminal"
NET_NAME = "/SHAPED"
GRID_MM = 1.0
COARSE_GRID_MM = 2.0
TRACK_WIDTH_MM = 0.4
START = (3.0, 8.0)
END = (13.0, 8.0)
OUTLINE = (
    (0.0, 0.0),
    (16.0, 0.0),
    (16.0, 10.0),
    (10.0, 10.0),
    (10.0, 6.0),
    (6.0, 6.0),
    (6.0, 10.0),
    (0.0, 10.0),
)
EXPECTED_GRAPH_FINGERPRINT = "8a6e6749acba33d8c139c3deac1eb2413c28df0b2a2194956ab9d40e358e9740"
EXPECTED_PLAN_FINGERPRINT = "56871d128305dfc53955fababd0555258d2f5d642fbb7cc7811f86675839b446"
EXPECTED_PLAN_PASS_FINGERPRINT = "4fc1076fecca0a072e544f45d55b0b9c0d387812c651dbafeddf0b92a29202fc"
EXPECTED_PROJECTED_GUIDE_FINGERPRINT = (
    "1c88a0f729d602e34580218313bd81ba6aba8f9b5cd43753b196fe0f6dd408fa"
)
EXPECTED_GUIDANCE_REPORT_FINGERPRINT = (
    "fb7c790aec4571e208872af9b7679938b5eaf8e94cf5310c3446fb09518165c7"
)
EXPECTED_ROUTING_RUN_FINGERPRINT = (
    "ab558b43e41c8750fc63da33fd65f5d64c6cc10e7c7472309fe60e6a0dbba65e"
)
EXPECTED_ROUTING_PASS_FINGERPRINT = (
    "e538f9b7d73f140caf1239767115bcb89811c3c3f4e6afdb420102fbdfe0799c"
)
EXPECTED_EXACT_CHECK_FINGERPRINT = (
    "a6531f621010be6c390766141ea9e4312670aac301f6681a104e55192794081e"
)
EXPECTED_SEGMENTS = (
    (3.0, 7.0, 3.0, 8.0, "F.Cu", NET_NAME, TRACK_WIDTH_MM),
    (3.0, 7.0, 5.0, 5.0, "F.Cu", NET_NAME, TRACK_WIDTH_MM),
    (5.0, 5.0, 11.0, 5.0, "F.Cu", NET_NAME, TRACK_WIDTH_MM),
    (11.0, 5.0, 13.0, 7.0, "F.Cu", NET_NAME, TRACK_WIDTH_MM),
    (13.0, 7.0, 13.0, 8.0, "F.Cu", NET_NAME, TRACK_WIDTH_MM),
)


@pytest.fixture
def shaped_board(monkeypatch: pytest.MonkeyPatch) -> tuple[BoardLayout, BoardNetlist]:
    pad = PadSpec(
        name="1",
        x_mm=0.0,
        y_mm=0.0,
        kind="smd",
        width_mm=0.8,
        height_mm=0.8,
        shape="circle",
        layers=("F.Cu", "F.Mask"),
    )
    monkeypatch.setitem(
        FOOTPRINT_LIBRARY,
        FOOTPRINT,
        FootprintSpec(
            pads=(pad,),
            fab_rect=(-0.4, -0.4, 0.4, 0.4),
            silk_rect=None,
            x_min=-0.4,
            x_max=0.4,
            y_min=-0.4,
            y_max=0.4,
            attr="smd",
        ),
    )
    left = BoardComponent("J1", "TERMINAL", FOOTPRINT, "shaped-j1")
    right = BoardComponent("J2", "TERMINAL", FOOTPRINT, "shaped-j2")
    layout = BoardLayout(
        placements=((left, START[0]), (right, END[0])),
        segments=(),
        vias=(),
        width_mm=16.0,
        height_mm=10.0,
        outline=OUTLINE,
        part_y_mm=(("J1", START[1]), ("J2", END[1])),
    )
    netlist = BoardNetlist(
        components=(left, right),
        nets=(BoardNet(NET_NAME, (("J1", "1"), ("J2", "1"))),),
    )
    return layout, netlist


def _connected(segments: tuple[TrackSegment, ...]) -> bool:
    adjacency: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for segment in segments:
        first = (segment.x1, segment.y1)
        second = (segment.x2, segment.y2)
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)
    pending = deque([START])
    visited = {START}
    while pending:
        point = pending.popleft()
        if point == END:
            return True
        for neighbour in adjacency.get(point, ()):
            if neighbour not in visited:
                visited.add(neighbour)
                pending.append(neighbour)
    return False


def _exact_checker(layout: BoardLayout, netlist: BoardNetlist) -> ExactRouteCheckResult:
    findings = {
        f"virtual-drc:{finding.check}:{finding.message}"
        for finding in run_virtual_drc(layout, netlist)
    }
    target_segments = tuple(segment for segment in layout.segments if segment.net_name == NET_NAME)
    if not target_segments or not _connected(target_segments):
        findings.add("target-disconnected")
    if not any(
        min(segment.x1, segment.x2) <= 8.0 <= max(segment.x1, segment.x2)
        and max(segment.y1, segment.y2) <= 5.5
        for segment in target_segments
    ):
        findings.add("lower-bottleneck-not-crossed")
    return ExactRouteCheckResult(
        accepted=not findings,
        checker_id="unit-shaped-corridor-virtual-geometry-v1",
        finding_fingerprints=tuple(findings),
    )


def test_real_shaped_corridor_plan_guides_detailed_route_deterministically(
    shaped_board: tuple[BoardLayout, BoardNetlist],
) -> None:
    layout, netlist = shaped_board
    first_build = build_corridor_graph(
        layout,
        netlist,
        target_nets=(NET_NAME,),
        default_width_mm=TRACK_WIDTH_MM,
        coarse_grid_mm=COARSE_GRID_MM,
    )
    repeated_build = build_corridor_graph(
        layout,
        netlist,
        target_nets=(NET_NAME,),
        default_width_mm=TRACK_WIDTH_MM,
        coarse_grid_mm=COARSE_GRID_MM,
    )

    assert first_build == repeated_build
    assert first_build.complete
    assert first_build.planning_supported
    assert len(first_build.demands) == 1
    assert first_build.graph.semantic_fingerprint() == EXPECTED_GRAPH_FINGERPRINT
    plan = negotiate_corridor_allocations(first_build.graph, first_build.demands)
    repeated_plan = negotiate_corridor_allocations(first_build.graph, first_build.demands)
    assert plan == repeated_plan
    assert plan.guidance_ready
    assert plan.resource_overuse == ()
    assert plan.semantic_fingerprint() == EXPECTED_PLAN_FINGERPRINT
    assert len(plan.passes) == 1
    assert plan.passes[0].semantic_fingerprint() == EXPECTED_PLAN_PASS_FINGERPRINT
    assert plan.passes[0].expansion_count == 29

    coarse_guide = build_corridor_route_guide(
        first_build.graph,
        plan,
        off_corridor_penalty_units=50,
    )
    assert coarse_guide is not None
    projected = project_corridor_route_guide(
        coarse_guide,
        first_build.graph,
        layout,
        grid_mm=GRID_MM,
    )
    assert projected.semantic_fingerprint() == EXPECTED_PROJECTED_GUIDE_FINGERPRINT
    first = route_board_corridor_guided(
        layout,
        netlist,
        corridor_graph=first_build.graph,
        corridor_plan=plan,
        off_corridor_penalty_units=50,
        target_nets=(NET_NAME,),
        default_width_mm=TRACK_WIDTH_MM,
        grid_mm=GRID_MM,
        max_passes=4,
        max_expansions=10_000,
        max_expansions_per_net=10_000,
        exact_checker=_exact_checker,
    )
    repeated = route_board_corridor_guided(
        layout,
        netlist,
        corridor_graph=first_build.graph,
        corridor_plan=plan,
        off_corridor_penalty_units=50,
        target_nets=(NET_NAME,),
        default_width_mm=TRACK_WIDTH_MM,
        grid_mm=GRID_MM,
        max_passes=4,
        max_expansions=10_000,
        max_expansions_per_net=10_000,
        exact_checker=_exact_checker,
    )

    assert first == repeated
    assert first.route_result.run_result.success
    assert first.route_result.run_result.accepted
    assert first.route_result.exact_check == ExactRouteCheckResult(
        accepted=True,
        checker_id="unit-shaped-corridor-virtual-geometry-v1",
    )
    assert first.guidance.guided_net_names == (NET_NAME,)
    assert first.guidance.guide_fingerprint == projected.semantic_fingerprint()
    assert first.guidance.semantic_fingerprint() == EXPECTED_GUIDANCE_REPORT_FINGERPRINT
    assert first.guidance.exact_check_fingerprint == EXPECTED_EXACT_CHECK_FINGERPRINT
    assert len(first.route_result.results) == 1
    assert first.route_result.results[0].segments
    assert _connected(first.route_result.results[0].segments)
    assert first.route_result.results[0].vias == ()
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
            for segment in first.route_result.results[0].segments
        )
        == EXPECTED_SEGMENTS
    )
    assert first.route_result.run_result.semantic_fingerprint() == EXPECTED_ROUTING_RUN_FINGERPRINT
    assert len(first.route_result.run_result.passes) == 1
    assert (
        first.route_result.run_result.passes[0].semantic_fingerprint()
        == EXPECTED_ROUTING_PASS_FINGERPRINT
    )
    assert first.route_result.run_result.passes[0].expansion_count == 4_876
