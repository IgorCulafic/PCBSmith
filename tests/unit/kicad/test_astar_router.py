"""Grid A* router (Track 8.2 / plan 2.3): routes are verifier-clean."""

from __future__ import annotations

from tests.unit.kicad.test_flyback_board import _netlist as flyback_netlist

from pcbsmith.kicad.astar_router import (
    clearance_groups_from_spec,
    route_net,
    strip_net,
    with_route,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
)
from pcbsmith.kicad.flyback_board import compute_flyback_board_layout
from pcbsmith.kicad.layout_score import score_layout
from pcbsmith.kicad.virtual_drc import run_virtual_drc

RESISTOR = "Resistor_SMD:R_0603_1608Metric"


def _fixture(
    wall_segments: tuple[TrackSegment, ...] = (),
) -> tuple[BoardLayout, BoardNetlist]:
    netlist = BoardNetlist(
        components=(
            BoardComponent(reference="R1", value="1k", footprint=RESISTOR,
                           uuid_path="r1"),
            BoardComponent(reference="R2", value="1k", footprint=RESISTOR,
                           uuid_path="r2"),
        ),
        nets=(
            BoardNet(name="/SIG", nodes=(("R1", "2"), ("R2", "1"))),
            BoardNet(name="/A", nodes=(("R1", "1"),)),
            BoardNet(name="/B", nodes=(("R2", "2"),)),
        ),
    )
    layout = BoardLayout(
        placements=((netlist.components[0], 5.0), (netlist.components[1], 25.0)),
        segments=wall_segments,
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
        part_y_mm=(("R1", 6.0), ("R2", 6.0)),
    )
    return layout, netlist


def test_routes_straight_when_clear() -> None:
    layout, netlist = _fixture()
    result = route_net(layout, netlist, "/SIG")
    assert result.vias == ()
    # Pads are ~18.5mm apart; a clean route stays close to that.
    assert result.length_mm < 22.0
    routed = with_route(layout, result)
    assert run_virtual_drc(routed, netlist) == ()


def test_detours_around_a_partial_wall() -> None:
    # A foreign trace blocks the direct corridor's lower half.
    wall = TrackSegment(x1=15.0, y1=1.0, x2=15.0, y2=8.0,
                        layer="F.Cu", net_name="/WALL", width_mm=0.4)
    layout, netlist = _fixture((wall,))
    result = route_net(layout, netlist, "/SIG")
    routed = with_route(layout, result)
    assert run_virtual_drc(routed, netlist) == ()
    # It had to go around: meaningfully longer than the straight shot.
    assert result.length_mm > 22.0
    assert result.vias == ()  # the top gap is cheaper than two vias


def test_full_wall_forces_vias_to_the_back() -> None:
    # Inside the edge-clearance band, but its inflation plus the edge
    # margin still seals the front layer end to end.
    wall = TrackSegment(x1=15.0, y1=0.8, x2=15.0, y2=11.2,
                        layer="F.Cu", net_name="/WALL", width_mm=0.4)
    layout, netlist = _fixture((wall,))
    result = route_net(layout, netlist, "/SIG")
    routed = with_route(layout, result)
    assert run_virtual_drc(routed, netlist) == ()
    assert len(result.vias) == 2  # down under the wall and back up
    layers = {seg.layer for seg in result.segments}
    assert layers == {"F.Cu", "B.Cu"}


def test_reroutes_flyback_fb_net_verifier_clean() -> None:
    """The head-to-head: strip the hand-routed FB net from the real
    flyback board and let the router redo it against all remaining
    copper. The scorer - including the isolation rules - is the judge."""
    from tests.unit.kicad.test_flyback_board import _spec

    netlist = flyback_netlist()
    hand = compute_flyback_board_layout(netlist)
    hand_fb_length = sum(
        ((seg.x1 - seg.x2) ** 2 + (seg.y1 - seg.y2) ** 2) ** 0.5
        for seg in hand.segments
        if seg.net_name == "/FB"
    )
    stripped = strip_net(hand, "/FB")
    result = route_net(
        stripped, netlist, "/FB",
        clearance_groups=clearance_groups_from_spec(_spec()),
    )
    routed = with_route(stripped, result)
    score = score_layout(routed, netlist, _spec())
    assert score.is_viable, (
        score.virtual_drc_findings[:5] or score.blocker_findings[:5]
    )
    # Within striking distance of the hand route (the router pays a
    # Manhattan tax; anything close to par is a win for an MVP).
    assert result.length_mm < hand_fb_length * 1.6


def test_beats_hand_route_on_flyback_vdd() -> None:
    """Live measurement locked in as a regression: the MVP router found
    a via-free VDD route shorter than the hand-crafted one."""
    from tests.unit.kicad.test_flyback_board import _spec

    netlist = flyback_netlist()
    hand = compute_flyback_board_layout(netlist)
    hand_length = sum(
        ((seg.x1 - seg.x2) ** 2 + (seg.y1 - seg.y2) ** 2) ** 0.5
        for seg in hand.segments
        if seg.net_name == "/VDD"
    )
    hand_vias = sum(1 for via in hand.vias if via.net_name == "/VDD")
    stripped = strip_net(hand, "/VDD")
    result = route_net(
        stripped, netlist, "/VDD",
        clearance_groups=clearance_groups_from_spec(_spec()),
    )
    routed = with_route(stripped, result)
    score = score_layout(routed, netlist, _spec())
    assert score.is_viable
    assert result.length_mm < hand_length
    assert len(result.vias) < hand_vias
