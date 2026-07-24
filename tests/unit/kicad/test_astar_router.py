"""Grid A* router (Track 8.2 / plan 2.3): routes are verifier-clean."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.unit.kicad.test_flyback_board import _routed as flyback_routed

from pcbsmith.kicad.astar_router import (
    GridRouter,
    RoutingError,
    clearance_groups_from_spec,
    route_board,
    route_net,
    strip_net,
    with_route,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardCutoutPolygon,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.layout_score import score_layout
from pcbsmith.kicad.virtual_drc import (
    _PhysicalSourceRole,
    _Stadium,
    run_virtual_drc,
)
from pcbsmith.routing_ir import RoutingFailureReason
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

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


def test_detours_around_internal_board_cutout() -> None:
    layout, netlist = _fixture()
    cutout = BoardCutoutPolygon(
        points=((14.0, 4.0), (16.0, 4.0), (16.0, 8.0), (14.0, 8.0))
    )
    layout = replace(layout, cutouts=(cutout,))

    result = route_net(layout, netlist, "/SIG")

    assert result.segments
    assert any(abs(segment.y1 - 6.0) > 2.0 for segment in result.segments)
    assert run_virtual_drc(with_route(layout, result), netlist) == ()
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


def test_spec_adapter_excludes_legacy_isolation_barrier() -> None:
    ordinary = ("project gap", ("/A",), ("/B",), 1.25, ("U1",))
    spec = DesignChecksSpec(
        isolation_barrier=(15.0, 9.0, ("/A",), ("/B",), ("T1",)),
        net_group_clearances=(ordinary,),
    )

    assert clearance_groups_from_spec(spec) == (
        (("/A",), ("/B",), 1.25, ("U1",)),
    )

def test_router_blocks_foreign_via_drill_by_hole_profile_spacing() -> None:
    layout = BoardLayout(
        placements=(),
        segments=(),
        vias=(
            ViaSpec(
                x=5.0,
                y=5.0,
                net_name="/FOREIGN",
                size_mm=0.4,
                drill_mm=0.36,
            ),
        ),
        width_mm=10.0,
        height_mm=10.0,
    )
    netlist = BoardNetlist(
        components=(),
        nets=(
            BoardNet(name="/SIG", nodes=()),
            BoardNet(name="/FOREIGN", nodes=()),
        ),
    )
    cell = (28, 25)  # (5.6, 5.0) on the default 0.2 mm grid
    ordinary = GridRouter(
        layout,
        netlist,
        net_name="/SIG",
        track_width_mm=0.2,
    )
    assert cell not in ordinary.blocked["F.Cu"]

    spacing = DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
        update={"minimum_hole_to_copper_mm": 0.4}
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={"fab_spacing": spacing}
    )
    strict = GridRouter(
        layout,
        netlist,
        net_name="/SIG",
        track_width_mm=0.2,
        profile=profile,
    )
    assert cell in strict.blocked["F.Cu"]


def test_route_run_telemetry_and_fingerprint_are_deterministic() -> None:
    layout, netlist = _fixture()

    first = route_board(layout, netlist)
    second = route_board(layout, netlist)

    assert first.run_result.semantic_fingerprint() == second.run_result.semantic_fingerprint()
    assert first.run_result == second.run_result
    assert first.results[0].expansion_count > 0
    assert first.results[0].expansion_count == second.results[0].expansion_count
    assert first.run_result.passes[0].expansion_count == first.results[0].expansion_count


def test_tiny_expansion_cap_is_a_typed_terminal_failure() -> None:
    layout, netlist = _fixture()

    with pytest.raises(RoutingError) as caught:
        route_net(layout, netlist, "/SIG", max_expansions=0)
    assert caught.value.reason is RoutingFailureReason.EXPANSION_BUDGET
    assert caught.value.expansion_count == 0

    outcome = route_board(
        layout,
        netlist,
        max_expansions=0,
        max_expansions_per_net=0,
    )
    assert outcome.failed == ("/SIG",)
    assert outcome.run_result.failure_reason is RoutingFailureReason.EXPANSION_BUDGET
    assert outcome.run_result.passes[0].net_telemetry[0].expansion_count == 0


def test_unroutable_board_has_typed_result_without_overuse_claims() -> None:
    walls = (
        TrackSegment(
            x1=15.0,
            y1=0.8,
            x2=15.0,
            y2=11.2,
            layer="F.Cu",
            net_name="/WALL",
            width_mm=0.4,
        ),
        TrackSegment(
            x1=15.0,
            y1=0.8,
            x2=15.0,
            y2=11.2,
            layer="B.Cu",
            net_name="/WALL",
            width_mm=0.4,
        ),
    )
    layout, netlist = _fixture(walls)

    outcome = route_board(layout, netlist, max_restarts=0)

    assert outcome.failed == ("/SIG",)
    assert outcome.run_result.failure_reason is RoutingFailureReason.UNROUTABLE
    assert outcome.run_result.unresolved_net_names == ("/SIG",)
    assert outcome.run_result.resource_overuse == ()
    assert outcome.run_result.passes[-1].resource_overuse == ()
    assert outcome.run_result.passes[-1].net_telemetry[-1].exact_check_accepted is None


def test_pass_budget_is_distinct_and_preserves_legacy_fields() -> None:
    layout, netlist = _fixture()

    exhausted = route_board(layout, netlist, max_passes=0)
    assert exhausted.failed == ("/SIG",)
    assert exhausted.order == ("/SIG",)
    assert exhausted.restarts == 0
    assert exhausted.run_result.failure_reason is RoutingFailureReason.PASS_BUDGET
    assert exhausted.run_result.passes == ()

    success = route_board(layout, netlist)
    assert success.failed == ()
    assert success.order == ("/SIG",)
    assert success.restarts == 0
    assert success.run_result.success
    assert success.run_result.exact_check_accepted is None
    assert not success.run_result.accepted
    assert success.run_result.unresolved_net_names == ()
    assert success.run_result.resource_overuse == ()
    assert success.run_result.failure_reason is None


def test_router_source_selection_and_through_layers_ignore_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pcbsmith.kicad import astar_router

    layout, netlist = _fixture()
    baseline = route_net(layout, netlist, "/SIG")
    original_collect = astar_router._collect_items

    def relabel(
        layout_arg: BoardLayout,
        netlist_arg: BoardNetlist,
        *,
        cover_rect_pads: bool = False,
        profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    ) -> list[_Stadium]:
        return [
            replace(item, label=f"misleading diagnostic {index}")
            for index, item in enumerate(
                original_collect(
                    layout_arg,
                    netlist_arg,
                    cover_rect_pads=cover_rect_pads,
                    profile=profile,
                )
            )
        ]

    monkeypatch.setattr(astar_router, "_collect_items", relabel)
    assert route_net(layout, netlist, "/SIG") == baseline

    header = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    components = (
        BoardComponent("P1", "header", header, "p1"),
        BoardComponent("P2", "header", header, "p2"),
    )
    through_netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet(name="/SIG", nodes=(("P1", "1"), ("P2", "1"))),
            BoardNet(name="/A", nodes=(("P1", "2"),)),
            BoardNet(name="/B", nodes=(("P2", "2"),)),
        ),
    )
    through_layout = BoardLayout(
        placements=((components[0], 5.0), (components[1], 25.0)),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
        part_y_mm=(("P1", 6.0), ("P2", 6.0)),
    )
    router = GridRouter(
        through_layout,
        through_netlist,
        net_name="/SIG",
        track_width_mm=0.3,
    )
    pads = [
        item
        for item in router.own_items
        if item.source_role is _PhysicalSourceRole.PAD
    ]
    assert pads
    assert all(router._is_through(pad) for pad in pads)
    assert all(
        {layer for layer, *_ in router._pad_nodes(pad)} == {"F.Cu", "B.Cu"}
        for pad in pads
    )
