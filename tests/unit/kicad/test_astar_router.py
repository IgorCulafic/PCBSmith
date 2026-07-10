"""Grid A* router (Track 8.2 / plan 2.3): routes are verifier-clean."""

from __future__ import annotations

from tests.unit.kicad.test_flyback_board import _routed as flyback_routed

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
    # It had to go around: meaningfully longer than the straight shot
    # (~18.5mm); diagonal moves make the detour tighter than Manhattan.
    assert result.length_mm > 19.5
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
    """Strip the FB net from the real (automation-routed) flyback board
    and let the router redo it against all remaining copper. The
    scorer - including the isolation rules - is the judge."""
    from tests.unit.kicad.test_flyback_board import _spec

    netlist, hand = flyback_routed()
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


def test_reroutes_flyback_vdd_at_parity() -> None:
    """r003 is already automation-routed, so the old beats-the-hand-
    layout assertion has no hand baseline left. What must still hold:
    stripping /VDD from the FINISHED board (all other copper as
    obstacles) and re-routing it stays viable and lands near the
    production route's cost - rip-up-and-reroute is the search's
    fundamental move."""
    from tests.unit.kicad.test_flyback_board import _spec

    netlist, production = flyback_routed()
    production_length = sum(
        ((seg.x1 - seg.x2) ** 2 + (seg.y1 - seg.y2) ** 2) ** 0.5
        for seg in production.segments
        if seg.net_name == "/VDD"
    )
    production_vias = sum(
        1 for via in production.vias if via.net_name == "/VDD"
    )
    stripped = strip_net(production, "/VDD")
    result = route_net(
        stripped, netlist, "/VDD",
        clearance_groups=clearance_groups_from_spec(_spec()),
    )
    routed = with_route(stripped, result)
    score = score_layout(routed, netlist, _spec())
    assert score.is_viable
    # The in-order production route had less copper to dodge; the
    # reroute against the full board may pay a small detour tax.
    assert result.length_mm < production_length * 1.3
    assert len(result.vias) <= production_vias + 1


def test_routes_entire_flyback_board_from_bare_placements() -> None:
    """The full-board regression: every net of the real flyback routed
    from bare placements with the PRODUCTION widths and clearance
    groups. Must pass the whole spec (isolation included) and
    reproduce the production layout's routing cost - this is exactly
    how compute_flyback_board_layout builds r003, so the reroute is a
    determinism/parity check, not a competition."""
    from tests.unit.kicad.test_flyback_board import _spec

    from pcbsmith.kicad.astar_router import route_board
    from pcbsmith.kicad.flyback_board import FLYBACK_NET_WIDTHS, SIG_W

    netlist, production = flyback_routed()
    bare = production.__class__(
        **{
            **{
                key: getattr(production, key)
                for key in production.__dataclass_fields__
            },
            "segments": (),
            "vias": (),
        }
    )
    outcome = route_board(
        bare, netlist,
        net_widths=FLYBACK_NET_WIDTHS,
        default_width_mm=SIG_W,
        clearance_groups=clearance_groups_from_spec(_spec()),
    )
    assert outcome.failed == ()
    score = score_layout(outcome.layout, netlist, _spec())
    assert score.is_viable, (
        score.virtual_drc_findings[:5] or score.blocker_findings[:5]
    )
    production_score = score_layout(production, netlist, _spec())
    assert score.sort_key() == production_score.sort_key()


def test_merge_collinear_segments_unifies_runs_and_keeps_junctions() -> None:
    from pcbsmith.kicad.astar_router import merge_collinear_segments

    def seg(x1, y1, x2, y2, layer="F.Cu", net="/A", width=0.4):
        return TrackSegment(x1=x1, y1=y1, x2=x2, y2=y2, layer=layer,
                            net_name=net, width_mm=width)

    merged = merge_collinear_segments((
        seg(0, 0, 2, 0),          # run pieces, one reversed, one
        seg(3, 0, 2, 0),          # overlapping
        seg(2.5, 0, 5, 0),
        seg(2, 0, 2, 4),          # T-junction branch: different line
        seg(0, 5, 2, 7),          # diagonal run split in two
        seg(2, 7, 4, 9),
        seg(1, 1, 1, 1),          # zero-length sliver: dropped
        seg(0, 0, 2, 0, layer="B.Cu"),  # other layer stays separate
    ))
    by_layer = {}
    for s in merged:
        by_layer.setdefault(s.layer, []).append(s)
    assert len(by_layer["B.Cu"]) == 1
    front = by_layer["F.Cu"]
    assert len(front) == 3  # one x-run, the branch, one diagonal
    spans = sorted(
        (min(s.x1, s.x2), max(s.x1, s.x2), min(s.y1, s.y2), max(s.y1, s.y2))
        for s in front
    )
    assert (0.0, 5.0, 0.0, 0.0) in spans      # merged x-run 0..5
    assert (2.0, 2.0, 0.0, 4.0) in spans      # junction branch intact
    assert (0.0, 4.0, 5.0, 9.0) in spans      # merged diagonal


def test_prune_redundant_segments_drops_only_contained_copper() -> None:
    from pcbsmith.kicad.astar_router import prune_redundant_segments

    def seg(x1, y1, x2, y2, width=0.4):
        return TrackSegment(x1=x1, y1=y1, x2=x2, y2=y2, layer="F.Cu",
                            net_name="/A", width_mm=width)

    trunk = seg(0.0, 0.0, 20.0, 0.0, width=1.2)
    contained = seg(5.0, 0.1, 12.0, 0.1, width=0.3)
    # Same width, offset: the copper areas overlap but neither
    # contains the other - pruning must keep it.
    sibling = seg(0.0, 0.2, 20.0, 0.2, width=1.2)
    kept = prune_redundant_segments((trunk, contained, sibling), ())
    assert contained not in kept
    assert trunk in kept
    assert sibling in kept


def test_router_output_carries_no_redundant_or_acute_copper() -> None:
    """Rules 11.1/11.2 hold on the router's own output by construction:
    the fixture route must pass the new checks."""
    from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks

    layout, netlist = _fixture()
    result = route_net(layout, netlist, "/SIG")
    routed = with_route(layout, result)
    report = run_design_checks(routed, netlist, DesignChecksSpec())
    assert not [
        f for f in report.findings if f.rule in ("11.1", "11.2")
    ]


def test_smoothing_straightens_the_clear_fixture() -> None:
    # With nothing in the way, the smoothed route is ONE straight
    # segment plus at most the two pad-entry stubs - no grid wander.
    layout, netlist = _fixture()
    result = route_net(layout, netlist, "/SIG")
    long_segments = [
        s for s in result.segments
        if ((s.x1 - s.x2) ** 2 + (s.y1 - s.y2) ** 2) ** 0.5 > 0.5
    ]
    assert len(long_segments) == 1
