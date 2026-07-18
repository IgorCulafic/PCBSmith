from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest
from tests.unit.kicad.test_rule_profiles import qualified_values

from pcbsmith.corridor_ir import CorridorGeometryVerification
from pcbsmith.hole_geometry import HoleGeometry, HolePlating, HoleShape
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardCutoutPolygon,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.corridor_planner import (
    CorridorGraphBuildBudget,
    CorridorGraphBuildFailure,
    OpaqueGraphicsPolicy,
    build_corridor_graph,
)
from pcbsmith.kicad.library import (
    CustomPadSource,
    FootprintSpec,
    PadSourceAnchor,
    PadSpec,
)
from pcbsmith.kicad.negotiated_resources import build_pairwise_clearance_domains
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    InsulationProfile,
    OrdinaryClearanceRequirement,
)


def _empty_layout(
    *,
    outline: tuple[tuple[float, float], ...] | None = None,
    graphics: tuple[str, ...] = (),
) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=10.0,
        height_mm=10.0,
        outline=outline,
        graphics=graphics,
    )


def _footprint(*pads: PadSpec) -> FootprintSpec:
    return FootprintSpec(
        pads=tuple(pads),
        fab_rect=(-1.0, -1.0, 1.0, 1.0),
        silk_rect=None,
        x_min=-1.0,
        x_max=1.0,
        y_min=-1.0,
        y_max=1.0,
        attr="through_hole" if any(pad.hole is not None for pad in pads) else "smd",
    )


def _two_terminal_board(
    monkeypatch: pytest.MonkeyPatch,
    *,
    flipped_second: bool = False,
    segments: tuple[TrackSegment, ...] = (),
    vias: tuple[ViaSpec, ...] = (),
    zones: tuple[tuple[str, str, tuple[float, float, float, float]], ...] = (),
) -> tuple[BoardLayout, BoardNetlist]:
    from pcbsmith.kicad import board as board_module

    pad = PadSpec(
        name="1",
        x_mm=0.0,
        y_mm=0.0,
        kind="smd",
        width_mm=0.8,
        height_mm=0.8,
        shape="circle",
    )
    monkeypatch.setitem(board_module.FOOTPRINT_LIBRARY, "Test:OnePad", _footprint(pad))
    first = BoardComponent("J1", "PAD", "Test:OnePad", "component-j1")
    second = BoardComponent("J2", "PAD", "Test:OnePad", "component-j2")
    layout = BoardLayout(
        placements=((first, 3.0), (second, 7.0)),
        segments=segments,
        vias=vias,
        width_mm=10.0,
        height_mm=10.0,
        parts_row_y_mm=5.0,
        zones=zones,
        part_flip=("J2",) if flipped_second else (),
    )
    netlist = BoardNetlist(
        components=(first, second),
        nets=(BoardNet("/TARGET", (("J1", "1"), ("J2", "1"))),),
    )
    return layout, netlist


def _multinet_board(
    monkeypatch: pytest.MonkeyPatch,
    terminal_counts: dict[str, int],
) -> tuple[BoardLayout, BoardNetlist]:
    """Create compact, independently routable one-pad components for each net."""
    from pcbsmith.kicad import board as board_module

    pad = PadSpec(
        name="1",
        x_mm=0.0,
        y_mm=0.0,
        kind="smd",
        width_mm=0.8,
        height_mm=0.8,
        shape="circle",
    )
    monkeypatch.setitem(board_module.FOOTPRINT_LIBRARY, "Test:OnePad", _footprint(pad))
    components: list[BoardComponent] = []
    placements: list[tuple[BoardComponent, float]] = []
    nets: list[BoardNet] = []
    x_mm = 2.0
    for net_name, count in sorted(terminal_counts.items()):
        pins: list[tuple[str, str]] = []
        for index in range(count):
            ref = f"{net_name}{index + 1}"
            component = BoardComponent(ref, "PAD", "Test:OnePad", f"component-{ref}")
            components.append(component)
            placements.append((component, x_mm))
            pins.append((ref, "1"))
            x_mm += 2.0
        nets.append(BoardNet(net_name, tuple(pins)))
        x_mm += 1.0
    return (
        BoardLayout(
            placements=tuple(placements),
            segments=(),
            vias=(),
            width_mm=max(10.0, x_mm + 1.0),
            height_mm=10.0,
            parts_row_y_mm=5.0,
        ),
        BoardNetlist(tuple(components), tuple(nets)),
    )


def _profile_with_pairwise(
    *requirements: OrdinaryClearanceRequirement,
):
    return DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"pairwise_clearances": requirements}
            )
        }
    )


def _hole_board(
    monkeypatch: pytest.MonkeyPatch,
    *,
    shape: HoleShape,
    width: float,
    height: float,
    rotation: float,
    x: float = 5.0,
    y: float = 5.0,
    plated: bool = False,
) -> tuple[BoardLayout, BoardNetlist]:
    from pcbsmith.kicad import board as board_module

    hole = PadSpec(
        name="1" if plated else "",
        x_mm=0.0,
        y_mm=0.0,
        kind="tht" if plated else "npth",
        width_mm=width,
        height_mm=height,
        hole=HoleGeometry(
            shape=shape,
            width_mm=width,
            height_mm=height,
            rotation_deg=rotation,
            plating=HolePlating.PLATED if plated else HolePlating.NON_PLATED,
        ),
    )
    monkeypatch.setitem(board_module.FOOTPRINT_LIBRARY, "Test:Hole", _footprint(hole))
    component = BoardComponent("H1", "HOLE", "Test:Hole", "hole-1")
    return (
        BoardLayout(
            placements=((component, x),),
            segments=(),
            vias=(),
            width_mm=10.0,
            height_mm=10.0,
            parts_row_y_mm=y,
        ),
        BoardNetlist((component,), ()),
    )


def _board_with_fixed_pad(
    monkeypatch: pytest.MonkeyPatch,
    pad: PadSpec,
) -> tuple[BoardLayout, BoardNetlist]:
    from pcbsmith.kicad import board as board_module

    terminal = PadSpec(
        name="1",
        x_mm=0.0,
        y_mm=0.0,
        kind="smd",
        width_mm=0.8,
        height_mm=0.8,
        shape="circle",
    )
    monkeypatch.setitem(board_module.FOOTPRINT_LIBRARY, "Test:OnePad", _footprint(terminal))
    monkeypatch.setitem(board_module.FOOTPRINT_LIBRARY, "Test:FixedPad", _footprint(pad))
    first = BoardComponent("J1", "PAD", "Test:OnePad", "component-j1")
    second = BoardComponent("J2", "PAD", "Test:OnePad", "component-j2")
    fixed = BoardComponent("U1", "FIXED", "Test:FixedPad", "component-u1")
    return (
        BoardLayout(
            placements=((first, 2.0), (fixed, 5.0), (second, 8.0)),
            segments=(),
            vias=(),
            width_mm=10.0,
            height_mm=10.0,
            parts_row_y_mm=5.0,
        ),
        BoardNetlist(
            components=(first, second),
            nets=(BoardNet("/TARGET", (("J1", "1"), ("J2", "1"))),),
        ),
    )


def _roundrect_pad(**changes: object) -> PadSpec:
    values: dict[str, object] = {
        "name": "1",
        "x_mm": 0.0,
        "y_mm": 0.0,
        "kind": "smd",
        "width_mm": 1.6,
        "height_mm": 1.0,
        "shape": "roundrect",
        "source_anchor": PadSourceAnchor(
            x_mm=0.0,
            y_mm=0.0,
            width_mm=1.6,
            height_mm=1.0,
        ),
        "layers": ("F.Cu", "F.Mask", "F.Paste"),
        "roundrect_rratio": 0.25,
    }
    values.update(changes)
    return PadSpec(**values)  # type: ignore[arg-type]


def test_empty_rectangle_has_hand_counted_cells_portals_and_center_vias() -> None:
    result = build_corridor_graph(
        _empty_layout(),
        BoardNetlist(components=(), nets=()),
        coarse_grid_mm=2.0,
        capacity_quantum_mm=0.01,
    )

    assert result.complete
    assert result.graph.geometry_complete
    assert result.planning_supported
    assert result.failure_reason is None
    assert len(result.graph.cells) == 18
    assert len(result.graph.portals) == 24
    assert len(result.graph.via_portals) == 9
    assert {portal.guaranteed_span_units for portal in result.graph.portals} == {200}
    assert result.graph.semantic_fingerprint() == (
        "ddd06605a21b1dc348b702cccba94a18d7a01d7be2b51121f09ff25e2f363444"
    )
    assert result.semantic_fingerprint() == (
        "1cb79808fb91e578cbeca85f151e798732fee7a64f99437a6ee35a1f7842d70e"
    )


def test_outline_winding_and_rotation_have_identical_semantics() -> None:
    outline = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    rotated_reversed = ((10.0, 10.0), (10.0, 0.0), (0.0, 0.0), (0.0, 10.0))

    one = build_corridor_graph(
        _empty_layout(outline=outline),
        BoardNetlist(components=(), nets=()),
    )
    two = build_corridor_graph(
        _empty_layout(outline=rotated_reversed),
        BoardNetlist(components=(), nets=()),
    )

    assert one.graph == two.graph
    assert one.semantic_fingerprint() == two.semantic_fingerprint()


def test_opaque_graphics_require_explicit_non_edge_cuts_assertion() -> None:
    rejected = build_corridor_graph(
        _empty_layout(graphics=("(gr_line (layer F.SilkS))",)),
        BoardNetlist(components=(), nets=()),
    )
    asserted = build_corridor_graph(
        _empty_layout(graphics=("(gr_line (layer F.SilkS))",)),
        BoardNetlist(components=(), nets=()),
        graphics_policy=OpaqueGraphicsPolicy.ASSERT_NON_EDGE_CUTS,
    )

    assert rejected.complete
    assert not rejected.planning_supported
    assert rejected.failure_reason is CorridorGraphBuildFailure.UNSUPPORTED_GEOMETRY
    assert asserted.planning_supported
    assert rejected.graph.layout_geometry_fingerprint != asserted.graph.layout_geometry_fingerprint


def test_geometry_budget_never_returns_complete_or_plannable_output() -> None:
    result = build_corridor_graph(
        _empty_layout(),
        BoardNetlist(components=(), nets=()),
        budget=CorridorGraphBuildBudget(max_cells=17, max_portals=100),
    )

    assert not result.complete
    assert not result.graph.geometry_complete
    assert not result.planning_supported
    assert result.failure_reason is CorridorGraphBuildFailure.GEOMETRY_BUDGET
    assert result.graph.cells == ()


def test_concave_notch_removes_false_bounding_box_cells_and_portals() -> None:
    outline = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 2.0),
        (4.0, 2.0),
        (4.0, 8.0),
        (10.0, 8.0),
        (10.0, 10.0),
        (0.0, 10.0),
    )
    result = build_corridor_graph(
        _empty_layout(outline=outline),
        BoardNetlist(components=(), nets=()),
        coarse_grid_mm=2.0,
    )

    assert result.planning_supported
    assert all(not (cell.ix >= 2 and 1 <= cell.iy <= 3) for cell in result.graph.cells)
    cell_ids = {cell.cell_id for cell in result.graph.cells}
    assert all(
        portal.cell_low in cell_ids and portal.cell_high in cell_ids
        for portal in result.graph.portals
    )


def test_target_routes_are_stripped_and_target_pads_map_physical_terminals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_track = TrackSegment(2.5, 5.0, 7.5, 5.0, "F.Cu", "/TARGET", 1.8)
    routed, netlist = _two_terminal_board(monkeypatch, segments=(target_track,))
    bare = replace(routed, segments=())

    with_route = build_corridor_graph(routed, netlist)
    without_route = build_corridor_graph(bare, netlist)

    assert with_route.graph == without_route.graph
    assert len(with_route.demands) == 1
    demand = with_route.demands[0]
    assert len(demand.terminals) == 2
    assert all(terminal.candidate_cell_ids for terminal in demand.terminals)
    assert {
        owner for cell in with_route.graph.cells for owner in cell.terminal_owner_net_names
    } == {"/TARGET"}


def test_front_smd_ownership_is_layer_correct_and_back_flip_maps_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _two_terminal_board(monkeypatch, flipped_second=True)
    result = build_corridor_graph(layout, netlist)
    cells = {cell.cell_id: cell for cell in result.graph.cells}
    terminals = result.demands[0].terminals

    assert {cells[cell_id].layer for cell_id in terminals[0].candidate_cell_ids} == {"F.Cu"}
    assert {cells[cell_id].layer for cell_id in terminals[1].candidate_cell_ids} == {"B.Cu"}


def test_fixed_track_via_and_zone_block_only_declared_copper_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _two_terminal_board(
        monkeypatch,
        segments=(TrackSegment(5.0, 3.0, 5.0, 3.0, "F.Cu", "/FIXED", 0.8),),
        vias=(ViaSpec(5.0, 7.0, "/FIXED", size_mm=0.8, drill_mm=0.4),),
        zones=(("/FIXED", "B.Cu", (2.4, 2.4, 3.6, 3.6)),),
    )
    result = build_corridor_graph(layout, netlist)
    keys = {(cell.layer, cell.ix, cell.iy) for cell in result.graph.cells}

    assert ("F.Cu", 2, 1) not in keys
    assert ("B.Cu", 2, 1) in keys
    assert ("B.Cu", 1, 1) not in keys
    assert ("F.Cu", 1, 1) in keys
    assert ("F.Cu", 2, 3) not in keys and ("B.Cu", 2, 3) not in keys


def test_target_zone_is_typed_unsupported_and_never_plannable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _two_terminal_board(
        monkeypatch,
        zones=(("/TARGET", "F.Cu", (4.4, 4.4, 5.6, 5.6)),),
    )
    result = build_corridor_graph(layout, netlist)

    assert result.complete
    assert not result.planning_supported
    assert result.failure_reason is CorridorGraphBuildFailure.UNSUPPORTED_GEOMETRY
    assert any("target-net zone" in issue.reason for issue in result.graph.issues)


def test_roundrect_bbox_is_bounded_plannable_and_retains_strict_error_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pad = _roundrect_pad()
    layout, netlist = _board_with_fixed_pad(monkeypatch, pad)

    result = build_corridor_graph(layout, netlist, coarse_grid_mm=1.0)

    assert result.complete
    assert result.planning_supported
    assert result.failure_reason is None
    issue = next(item for item in result.graph.issues if item.source_id == "pad:U1:0")
    assert issue.verification is CorridorGeometryVerification.BOUNDED_APPROXIMATION
    assert issue.layer == "F.Cu"
    assert issue.maximum_error_mm is not None
    with localcontext() as context:
        context.prec = 80
        exact_corner_error = Decimal("0.25") * (context.sqrt(Decimal(2)) - Decimal(1))
    assert Decimal(str(issue.maximum_error_mm)) > exact_corner_error
    assert issue.maximum_error_mm == pytest.approx(float(exact_corner_error), rel=1e-14)
    assert "full source bounding rectangle" in issue.reason
    assert len(result.demands) == 1


def test_roundrect_bbox_never_opens_capacity_relative_to_its_enclosing_rectangle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rounded_layout, netlist = _board_with_fixed_pad(monkeypatch, _roundrect_pad())
    rounded = build_corridor_graph(rounded_layout, netlist, coarse_grid_mm=1.0)
    rectangular_layout, rectangular_netlist = _board_with_fixed_pad(
        monkeypatch,
        _roundrect_pad(shape="rect", roundrect_rratio=None),
    )
    rectangular = build_corridor_graph(
        rectangular_layout,
        rectangular_netlist,
        coarse_grid_mm=1.0,
    )

    rounded_cells = {(item.layer, item.ix, item.iy) for item in rounded.graph.cells}
    rectangular_cells = {
        (item.layer, item.ix, item.iy) for item in rectangular.graph.cells
    }
    assert rounded_cells == rectangular_cells
    assert {
        (item.layer, item.cell_low, item.cell_high, item.guaranteed_span_units)
        for item in rounded.graph.portals
    } == {
        (item.layer, item.cell_low, item.cell_high, item.guaranteed_span_units)
        for item in rectangular.graph.portals
    }


def test_vendored_resistor_roundrect_source_is_plannable_as_bounded_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pad = FOOTPRINT_LIBRARY["Resistor_SMD:R_0603_1608Metric"].pads[0]
    assert pad.shape == "roundrect"
    assert pad.source_anchor is not None
    assert pad.roundrect_rratio is not None
    layout, netlist = _board_with_fixed_pad(monkeypatch, pad)

    result = build_corridor_graph(layout, netlist, coarse_grid_mm=1.0)

    assert result.planning_supported
    issue = next(item for item in result.graph.issues if item.source_id == "pad:U1:0")
    assert issue.verification is CorridorGeometryVerification.BOUNDED_APPROXIMATION
    assert issue.maximum_error_mm is not None


@pytest.mark.parametrize(
    "pad",
    (
        _roundrect_pad(roundrect_rratio=None),
        _roundrect_pad(roundrect_rratio=-0.1),
        _roundrect_pad(roundrect_rratio=0.6),
        _roundrect_pad(roundrect_rratio=float("nan")),
        _roundrect_pad(source_anchor=None),
        _roundrect_pad(
            source_anchor=PadSourceAnchor(
                x_mm=0.0,
                y_mm=0.0,
                width_mm=1.5,
                height_mm=1.0,
            )
        ),
    ),
)
def test_missing_invalid_or_stale_roundrect_source_remains_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    pad: PadSpec,
) -> None:
    layout, netlist = _board_with_fixed_pad(monkeypatch, pad)

    result = build_corridor_graph(layout, netlist, coarse_grid_mm=1.0)

    assert result.complete
    assert not result.planning_supported
    assert result.failure_reason is CorridorGraphBuildFailure.UNSUPPORTED_GEOMETRY
    issue = next(item for item in result.graph.issues if item.source_id == "pad:U1:0")
    assert issue.verification is CorridorGeometryVerification.UNSUPPORTED
    assert issue.maximum_error_mm is None


def test_chamfered_roundrect_custom_and_unknown_pads_remain_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pads = (
        _roundrect_pad(chamfer_ratio=0.2, chamfer_positions=("top_left",)),
        _roundrect_pad(
            shape="custom",
            roundrect_rratio=None,
            custom_source=CustomPadSource(
                canonical_clauses=("(options (anchor rect))", "(primitives)"),
                unsupported_reason="synthetic custom pad",
            ),
        ),
        _roundrect_pad(shape="trapezoid", roundrect_rratio=None),
    )
    for pad in pads:
        layout, netlist = _board_with_fixed_pad(monkeypatch, pad)
        result = build_corridor_graph(layout, netlist, coarse_grid_mm=1.0)
        assert result.complete
        assert not result.planning_supported
        assert result.failure_reason is CorridorGraphBuildFailure.UNSUPPORTED_GEOMETRY
        issue = next(item for item in result.graph.issues if item.source_id == "pad:U1:0")
        assert issue.verification is CorridorGeometryVerification.UNSUPPORTED
        assert issue.maximum_error_mm is None


@pytest.mark.parametrize(
    ("shape", "width", "height", "rotation"),
    ((HoleShape.ROUND, 1.2, 1.2, 0.0), (HoleShape.OVAL, 2.4, 0.8, 45.0)),
)
def test_npth_round_and_rotated_oval_holes_block_both_layers(
    monkeypatch: pytest.MonkeyPatch,
    shape: HoleShape,
    width: float,
    height: float,
    rotation: float,
) -> None:
    layout, netlist = _hole_board(
        monkeypatch, shape=shape, width=width, height=height, rotation=rotation
    )
    result = build_corridor_graph(layout, netlist)
    keys = {(cell.layer, cell.ix, cell.iy) for cell in result.graph.cells}

    assert ("F.Cu", 2, 2) not in keys
    assert ("B.Cu", 2, 2) not in keys


def test_plated_tht_pad_and_hole_block_both_copper_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _hole_board(
        monkeypatch,
        shape=HoleShape.ROUND,
        width=1.2,
        height=1.2,
        rotation=0.0,
        plated=True,
    )
    result = build_corridor_graph(layout, netlist)
    keys = {(cell.layer, cell.ix, cell.iy) for cell in result.graph.cells}

    assert ("F.Cu", 2, 2) not in keys
    assert ("B.Cu", 2, 2) not in keys


def test_profile_edge_copper_hole_via_and_width_inputs_change_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _two_terminal_board(
        monkeypatch,
        segments=(TrackSegment(4.1, 3.0, 4.1, 3.0, "F.Cu", "/FIXED", 0.2),),
    )
    baseline = build_corridor_graph(layout, netlist, net_widths={"/TARGET": 0.3})
    edge_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"profile_id": "edge", "minimum_copper_to_edge_mm": 2.1}
            )
        }
    )
    copper_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"profile_id": "copper", "minimum_copper_clearance_mm": 1.0}
            )
        }
    )
    via_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "geometry": DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
                update={"profile_id": "large-via", "routing_via_diameter_mm": 5.0}
            )
        }
    )
    changed = (
        build_corridor_graph(layout, netlist, profile=edge_profile),
        build_corridor_graph(layout, netlist, profile=copper_profile),
        build_corridor_graph(layout, netlist, profile=via_profile),
        build_corridor_graph(layout, netlist, net_widths={"/TARGET": 0.9}),
    )

    assert all(item.semantic_fingerprint() != baseline.semantic_fingerprint() for item in changed)
    assert len(changed[0].graph.cells) < len(baseline.graph.cells)
    assert len(changed[2].graph.via_portals) < len(baseline.graph.via_portals)
    assert changed[3].demands[0].ordinary_span_units > baseline.demands[0].ordinary_span_units

    hole_layout, hole_netlist = _hole_board(
        monkeypatch,
        shape=HoleShape.ROUND,
        width=0.2,
        height=0.2,
        rotation=0.0,
        x=4.1,
        y=3.0,
    )
    small_hole = build_corridor_graph(hole_layout, hole_netlist)
    hole_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"profile_id": "hole", "minimum_hole_to_copper_mm": 1.0}
            )
        }
    )
    large_hole = build_corridor_graph(hole_layout, hole_netlist, profile=hole_profile)
    assert len(large_hole.graph.cells) < len(small_hole.graph.cells)


def test_target_selection_is_order_independent_and_unknown_names_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _two_terminal_board(monkeypatch)
    one = build_corridor_graph(layout, netlist, target_nets=("/TARGET", "/UNKNOWN"))
    two = build_corridor_graph(layout, netlist, target_nets=("/UNKNOWN", "/TARGET"))

    assert one == two
    assert one.semantic_fingerprint() == two.semantic_fingerprint()


def test_donut_cutout_blocks_both_layers_and_all_through_sites() -> None:
    cutout = BoardCutoutPolygon(points=((4.6, 4.6), (7.4, 4.6), (7.4, 7.4), (4.6, 7.4)))
    layout = BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=12.0,
        height_mm=12.0,
        cutouts=(cutout,),
    )
    result = build_corridor_graph(layout, BoardNetlist(components=(), nets=()), coarse_grid_mm=2.0)
    keys = {(cell.layer, cell.ix, cell.iy) for cell in result.graph.cells}
    cells = {cell.cell_id: cell for cell in result.graph.cells}
    via_keys = {
        (cells[portal.front_cell_id].ix, cells[portal.front_cell_id].iy)
        for portal in result.graph.via_portals
    }

    for ix in (2, 3):
        for iy in (2, 3):
            assert ("F.Cu", ix, iy) not in keys
            assert ("B.Cu", ix, iy) not in keys
            assert (ix, iy) not in via_keys


def test_concave_cutout_scan_conversion_matches_hand_classification() -> None:
    cutout = BoardCutoutPolygon(
        points=(
            (4.6, 4.6),
            (9.4, 4.6),
            (9.4, 9.4),
            (7.4, 9.4),
            (7.4, 7.4),
            (4.6, 7.4),
        )
    )
    layout = BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=14.0,
        height_mm=14.0,
        cutouts=(cutout,),
    )
    result = build_corridor_graph(layout, BoardNetlist(components=(), nets=()), coarse_grid_mm=2.0)
    front_keys = {(cell.ix, cell.iy) for cell in result.graph.cells if cell.layer == "F.Cu"}

    assert (2, 2) not in front_keys
    assert (3, 3) not in front_keys
    assert (4, 4) not in front_keys
    assert (2, 4) in front_keys


def test_two_cutouts_are_order_invariant_and_corridor_portals_stay_distinct() -> None:
    left = BoardCutoutPolygon(points=((4.6, 4.6), (5.4, 4.6), (5.4, 7.4), (4.6, 7.4)))
    right = BoardCutoutPolygon(points=((8.6, 4.6), (9.4, 4.6), (9.4, 7.4), (8.6, 7.4)))
    base = BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=14.0,
        height_mm=12.0,
        cutouts=(left, right),
    )
    reversed_layout = replace(base, cutouts=(right, left))

    one = build_corridor_graph(base, BoardNetlist(components=(), nets=()))
    two = build_corridor_graph(reversed_layout, BoardNetlist(components=(), nets=()))

    assert one == two
    resource_ids = {portal.resource_id for portal in one.graph.portals}
    assert len(resource_ids) == len(one.graph.portals)
    assert {portal.guaranteed_span_units for portal in one.graph.portals} == {200}


def test_cutout_and_edge_clearance_change_graph_identity_and_capacity() -> None:
    cutout = BoardCutoutPolygon(points=((4.6, 4.6), (7.4, 4.6), (7.4, 7.4), (4.6, 7.4)))
    bare = BoardLayout(placements=(), segments=(), vias=(), width_mm=12.0, height_mm=12.0)
    holed = replace(bare, cutouts=(cutout,))
    wide_edge_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={
                    "profile_id": "cutout-edge",
                    "minimum_copper_to_edge_mm": 1.1,
                }
            )
        }
    )

    bare_result = build_corridor_graph(bare, BoardNetlist(components=(), nets=()))
    holed_result = build_corridor_graph(holed, BoardNetlist(components=(), nets=()))
    wide_result = build_corridor_graph(
        holed,
        BoardNetlist(components=(), nets=()),
        profile=wide_edge_profile,
    )

    assert bare_result.graph.layout_geometry_fingerprint != (
        holed_result.graph.layout_geometry_fingerprint
    )
    assert len(holed_result.graph.cells) < len(bare_result.graph.cells)
    assert len(wide_result.graph.cells) < len(holed_result.graph.cells)


def test_cutout_tip_near_middle_of_cell_edge_is_clearance_blocked() -> None:
    cutout = BoardCutoutPolygon(points=((4.4, 3.0), (5.5, 2.5), (5.5, 3.5)))
    layout = BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=10.0,
        height_mm=10.0,
        cutouts=(cutout,),
    )
    result = build_corridor_graph(
        layout,
        BoardNetlist(components=(), nets=()),
        coarse_grid_mm=2.0,
    )

    keys = {(cell.layer, cell.ix, cell.iy) for cell in result.graph.cells}
    assert ("F.Cu", 1, 1) not in keys
    assert ("B.Cu", 1, 1) not in keys


def test_pairwise_clearance_inflates_only_demands_with_active_counterparts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _multinet_board(monkeypatch, {"A": 2, "B": 2, "C": 2})
    requirement = OrdinaryClearanceRequirement(
        requirement_id="a-to-b",
        nets_a=("A",),
        nets_b=("B",),
        minimum_clearance_mm=0.7,
    )
    profile = _profile_with_pairwise(requirement)

    result = build_corridor_graph(layout, netlist, profile=profile)
    demands = {demand.net_name: demand for demand in result.demands}
    domain = build_pairwise_clearance_domains(profile.profile_id, (requirement,))[0]

    assert {name: demand.effective_clearance_mm for name, demand in demands.items()} == {
        "A": 0.7,
        "B": 0.7,
        "C": profile.fab_spacing.minimum_copper_clearance_mm,
    }
    assert demands["A"].pairwise_domain_ids == (domain.domain_id,)
    assert demands["B"].pairwise_domain_ids == (domain.domain_id,)
    assert demands["C"].pairwise_domain_ids == ()


def test_pairwise_groups_never_join_same_side_or_activate_without_two_terminal_counterpart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirement = OrdinaryClearanceRequirement(
        requirement_id="group-to-b",
        nets_a=("A1", "A2"),
        nets_b=("B",),
        minimum_clearance_mm=0.8,
    )
    profile = _profile_with_pairwise(requirement)
    complete_layout, complete_netlist = _multinet_board(monkeypatch, {"A1": 2, "A2": 2, "B": 2})
    absent = build_corridor_graph(
        complete_layout,
        complete_netlist,
        profile=profile,
        target_nets=("A1", "A2"),
    )
    short_layout, short_netlist = _multinet_board(monkeypatch, {"A1": 2, "A2": 2, "B": 1})
    short = build_corridor_graph(
        short_layout,
        short_netlist,
        profile=profile,
        target_nets=("A1", "A2", "B"),
    )

    for result in (absent, short):
        demands = {demand.net_name: demand for demand in result.demands}
        assert set(demands) == {"A1", "A2"}
        assert all(
            demand.effective_clearance_mm == profile.fab_spacing.minimum_copper_clearance_mm
            for demand in demands.values()
        )
        assert all(demand.pairwise_domain_ids == () for demand in demands.values())


def test_overlapping_pairwise_domains_retain_all_ids_and_use_maximum_clearance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _multinet_board(monkeypatch, {"A": 2, "B": 2, "C": 2})
    a_b = OrdinaryClearanceRequirement(
        requirement_id="a-to-b",
        nets_a=("A",),
        nets_b=("B",),
        minimum_clearance_mm=0.7,
    )
    a_c = OrdinaryClearanceRequirement(
        requirement_id="a-to-c",
        nets_a=("A",),
        nets_b=("C",),
        minimum_clearance_mm=0.9,
    )
    profile = _profile_with_pairwise(a_b, a_c)
    expected = build_pairwise_clearance_domains(profile.profile_id, (a_b, a_c))
    expected_by_net = {
        net_name: tuple(domain.domain_id for domain in expected if domain.applies_to(net_name))
        for net_name in ("A", "B", "C")
    }

    result = build_corridor_graph(layout, netlist, profile=profile)
    demands = {demand.net_name: demand for demand in result.demands}

    assert demands["A"].effective_clearance_mm == 0.9
    assert demands["B"].effective_clearance_mm == 0.7
    assert demands["C"].effective_clearance_mm == 0.9
    assert {name: demand.pairwise_domain_ids for name, demand in demands.items()} == expected_by_net
    assert len(demands["A"].pairwise_domain_ids) == 2


def test_pairwise_selectors_and_component_exemptions_do_not_narrow_coarse_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _multinet_board(monkeypatch, {"A": 2, "B": 2})
    requirement = OrdinaryClearanceRequirement(
        requirement_id="qualified-only-at-detail",
        nets_a=("A",),
        nets_b=("B",),
        minimum_clearance_mm=0.75,
        mask_states_a=("fully_exposed",),
        mask_states_b=("masked",),
        roles_a=("via_land",),
        roles_b=("component_termination",),
        exempt_component_refs=("A1", "B2"),
        rule_ids=("selector-bearing-rule",),
    )
    profile = _profile_with_pairwise(requirement)

    result = build_corridor_graph(layout, netlist, profile=profile)
    demands = {demand.net_name: demand for demand in result.demands}
    domain = build_pairwise_clearance_domains(profile.profile_id, (requirement,))[0]

    assert {demand.effective_clearance_mm for demand in demands.values()} == {0.75}
    assert all(demand.pairwise_domain_ids == (domain.domain_id,) for demand in demands.values())


def test_only_qualified_air_clearance_affects_demands_not_creepage_or_review_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _multinet_board(monkeypatch, {"A": 2, "B": 2})
    values = qualified_values()
    barrier = values["barriers"][0].model_copy(
        update={
            "barrier_id": "a-to-b-safety",
            "nets_a": ("A",),
            "nets_b": ("B",),
            "required_clearance_mm": 0.8,
            "required_creepage_mm": 6.4,
        }
    )
    values["barriers"] = (barrier,)
    qualified = InsulationProfile.model_validate(values)
    qualified_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(update={"insulation": qualified})

    qualified_result = build_corridor_graph(layout, netlist, profile=qualified_profile)
    qualified_demands = {demand.net_name: demand for demand in qualified_result.demands}

    assert {demand.effective_clearance_mm for demand in qualified_demands.values()} == {0.8}
    assert {demand.ordinary_span_units for demand in qualified_demands.values()} == {120}
    assert all(len(demand.pairwise_domain_ids) == 1 for demand in qualified_demands.values())

    for status in ("incomplete", "review_required"):
        review_profile = qualified_profile.model_copy(
            update={"insulation": qualified.model_copy(update={"status": status})}
        )
        review_result = build_corridor_graph(layout, netlist, profile=review_profile)
        assert all(
            demand.effective_clearance_mm == review_profile.fab_spacing.minimum_copper_clearance_mm
            for demand in review_result.demands
        )
        assert all(demand.pairwise_domain_ids == () for demand in review_result.demands)


def test_caller_clearance_groups_are_deduplicated_canonical_and_order_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _multinet_board(monkeypatch, {"A": 2, "B": 2, "C": 2})
    a_b = (("A", "A"), ("B", "B"), 0.75, ("J2", "J1", "J1"))
    a_c = (("A",), ("C",), 0.85, ())
    duplicated = (a_b, a_c, a_b)
    canonical_reordered = (a_c, (("A",), ("B",), 0.75, ("J1", "J2")))

    one = build_corridor_graph(layout, netlist, clearance_groups=duplicated)
    two = build_corridor_graph(layout, netlist, clearance_groups=canonical_reordered)

    assert one == two
    assert one.semantic_fingerprint() == two.semantic_fingerprint()
    demands = {demand.net_name: demand for demand in one.demands}
    assert len(demands["A"].pairwise_domain_ids) == 2
    assert len(demands["B"].pairwise_domain_ids) == 1
    assert len(demands["C"].pairwise_domain_ids) == 1


def test_pairwise_span_ceiling_is_exact_on_quantum_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _multinet_board(monkeypatch, {"A": 2, "B": 2})
    requirement = OrdinaryClearanceRequirement(
        requirement_id="exact-boundary",
        nets_a=("A",),
        nets_b=("B",),
        minimum_clearance_mm=0.7,
    )
    result = build_corridor_graph(
        layout,
        netlist,
        profile=_profile_with_pairwise(requirement),
        default_width_mm=0.3,
        capacity_quantum_mm=0.1,
    )

    assert all(demand.effective_clearance_mm == 0.7 for demand in result.demands)
    assert {demand.ordinary_span_units for demand in result.demands} == {10}
