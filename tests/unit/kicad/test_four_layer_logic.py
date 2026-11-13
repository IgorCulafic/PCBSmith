"""Four-layer software contracts; none of these fixtures qualifies a physical PCB."""

from dataclasses import replace

import pytest
from tests.unit.kicad.test_routing_external_adapters import _layout, _request
from tests.unit.kicad.test_routing_net_constraints import DSN

from pcbsmith.copper_layers import ordered_copper_layers, routing_copper_layers, via_copper_span
from pcbsmith.kicad.astar_router import routing_copper_layers as legacy_routing_layers
from pcbsmith.kicad.board import BoardNetlist, TrackSegment, ViaSpec, render_board_from_layout
from pcbsmith.kicad.copper_layers import saved_copper_layers
from pcbsmith.kicad.freerouting_production import (
    constrain_freerouting_dsn,
    read_single_sided_routes,
)
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.placement_readback import extract_kicad_board_readback
from pcbsmith.kicad.virtual_drc import _collect_items
from pcbsmith.manufacturing_release import _require_copper_gerbers, _require_copper_stackup
from pcbsmith.review.visual_package import _two_d_profiles
from pcbsmith.routing_ir import RouteRequest
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
LAYER_TABLE = (
    '(layers (0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal))'
)


def four_layer_profile():
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={"copper_layer_count": 4, "inner_copper_thickness_um": 35}
    )
    return DEFAULT_PCB_RULE_PROFILE.model_copy(update={"geometry": geometry})


def four_layer_request(**updates):
    return RouteRequest.model_validate(
        {**_request(_layout()).model_dump(), "allowed_layers": LAYERS, **updates}
    )


def four_layer_dsn():
    return DSN.replace(
        "(layer B.Cu", "(layer In1.Cu (type signal)) (layer In2.Cu (type signal)) (layer B.Cu"
    )


@pytest.mark.parametrize("count", [0, 3, 6, True])
def test_unsupported_layer_counts_fail(count):
    with pytest.raises(ValueError, match="one, two, or four"):
        routing_copper_layers(count)


def test_stack_order_and_via_span_are_not_alphabetical():
    assert ordered_copper_layers(sorted(LAYERS)) == LAYERS
    assert via_copper_span(LAYERS, "F.Cu", "B.Cu") == LAYERS
    assert via_copper_span(LAYERS, "In2.Cu", "In1.Cu") == LAYERS[1:3]
    with pytest.raises(ValueError, match="incomplete"):
        ordered_copper_layers(("F.Cu", "In1.Cu"))
    with pytest.raises(ValueError, match="native A"):
        legacy_routing_layers(four_layer_profile())


def test_serialization_and_readback_retain_unused_inner_layers():
    text = render_board_from_layout(BoardNetlist((), ()), _layout(), profile=four_layer_profile())
    assert saved_copper_layers(parse_sexpr(text)) == LAYERS
    stripped = text.replace('    (1 "In1.Cu" signal)\n', "").replace(
        '    (2 "In2.Cu" signal)\n', ""
    )
    assert (
        extract_kicad_board_readback(text).layers != extract_kicad_board_readback(stripped).layers
    )
    # KiCad 10 uses different numeric IDs: the copper names are authoritative.
    renumbered = (
        text.replace('(31 "B.Cu"', '(2 "B.Cu"')
        .replace('(1 "In1.Cu"', '(4 "In1.Cu"')
        .replace('(2 "In2.Cu"', '(6 "In2.Cu"')
    )
    assert saved_copper_layers(parse_sexpr(renumbered)) == LAYERS


def test_dsn_retains_four_layers_and_through_via_copper():
    request = four_layer_request()
    result = constrain_freerouting_dsn(four_layer_dsn(), _layout(), request, 1)
    tree = parse_sexpr(result.decode())
    structure = _children(tree, "structure")[0]
    assert tuple(_atom(n[1]) for n in _children(structure, "layer")) == LAYERS
    via = _children(_children(tree, "library")[0], "padstack")[0]
    assert _atom(via[1]) == "Via[0-3]_600:300_um"
    assert tuple(_atom(n[1][1]) for n in _children(via, "shape")) == LAYERS
    with pytest.raises(ValueError, match="physical stack order"):
        constrain_freerouting_dsn(four_layer_dsn(), _layout(), _request(_layout()), 1)
    with pytest.raises(ValueError, match="physical stack order"):
        constrain_freerouting_dsn(DSN, _layout(), request, 1)


def test_native_import_retains_inner_track_and_rejects_forbidden_via_span(tmp_path):
    source, routed = tmp_path / "source.kicad_pcb", tmp_path / "routed.kicad_pcb"
    base = "(kicad_pcb " + LAYER_TABLE + ' (net 1 "/SIG") '
    source.write_text(base + ")")
    routed.write_text(
        base + '(segment (start 21 21) (end 23 21) (width 0.4) (layer "In1.Cu") (net 1)) '
        '(via (at 23 21) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1)))'
    )
    layout = read_single_sided_routes(routed, source, _layout(), four_layer_request())
    assert layout.segments[0].layer == "In1.Cu" and len(layout.vias) == 1
    restricted = four_layer_request(
        net_layer_constraints=[
            dict(
                constraint_id="no-in2",
                net_names=["/SIG"],
                allowed_layers=["F.Cu", "In1.Cu", "B.Cu"],
                allow_vias=True,
            )
        ]
    )
    with pytest.raises(ValueError, match="per-net"):
        read_single_sided_routes(routed, source, _layout(), restricted)


def test_inner_copper_sees_through_via_obstacles():
    layout = replace(
        _layout(),
        vias=(ViaSpec(5, 5, "/VIA"),),
        segments=(TrackSegment(4, 5, 6, 5, "In1.Cu", "/SIG", 0.4),),
    )
    items = _collect_items(layout, BoardNetlist((), ()), profile=four_layer_profile())
    via_layers = {item.layer for item in items if item.net == "/VIA"}
    assert via_layers == set(LAYERS)


def test_visual_profiles_include_separate_inner_views_and_combined_stack():
    profiles = {row[1]: row for row in _two_d_profiles(LAYERS)}
    assert profiles["inner-1-copper"][2] == ("In1.Cu", "Edge.Cuts")
    assert profiles["inner-2-copper"][2] == ("In2.Cu", "Edge.Cuts")
    assert profiles["combined-copper"][2] == (*LAYERS, "Edge.Cuts")
    assert all(not profiles[name][4] for name in ("inner-1-copper", "inner-2-copper"))


def test_gerber_coverage_requires_each_layer_once_by_x2_attribute(tmp_path):
    files = []
    for index, side in enumerate(("Top", "Inr", "Inr", "Bot"), start=1):
        path = tmp_path / f"arbitrary-{index}.gbr"
        path.write_text(f"%TF.FileFunction,Copper,L{index},{side}*%\nM02*\n")
        files.append(path)
    _require_copper_gerbers(files, LAYERS)
    for incomplete in (files[:1] + files[2:], [*files, files[1]]):
        with pytest.raises(ValueError, match="coverage"):
            _require_copper_gerbers(incomplete, LAYERS)
    combined = tmp_path / "not-four-separate-layers.gbr"
    combined.write_text("".join(path.read_text() for path in files))
    with pytest.raises(ValueError, match="separate files"):
        _require_copper_gerbers([combined], LAYERS)


def test_two_layer_fabrication_profile_cannot_export_four_layer_board(tmp_path):
    from tests.unit.test_manufacturing_release import _profile

    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb " + LAYER_TABLE + ")")
    with pytest.raises(ValueError, match="stackup copper order"):
        _require_copper_stackup(board, _profile())
    assert _require_copper_stackup(board, _profile(4)) == LAYERS


def test_candidate_validator_checks_intermediate_via_layers():
    from tests.unit.test_routing_candidate_ir import _complete_candidate
    from tests.unit.test_routing_candidate_ir import _request as ir_request

    from pcbsmith.routing_ir import RouteViaDelta, validate_route_candidate_result

    request = RouteRequest.model_validate(
        {
            **ir_request().model_dump(),
            "allowed_layers": LAYERS,
            "net_layer_constraints": [
                dict(
                    constraint_id="outer-only",
                    net_names=["/SIG"],
                    allowed_layers=["F.Cu", "B.Cu"],
                    allow_vias=True,
                )
            ],
        }
    )
    technology = request.via_technologies[0]
    candidate = _complete_candidate(request).model_copy(
        update={
            "via_deltas": (
                RouteViaDelta(
                    mutation_id="extra",
                    operation="add",
                    object_id="extra",
                    after=dict(
                        net_name="/SIG",
                        position=dict(x_mm=3, y_mm=3),
                        **technology.model_dump(exclude={"constraint_id"}),
                    ),
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="per-net"):
        validate_route_candidate_result(request, candidate)


@pytest.mark.parametrize("two_sided", [False, True])
def test_surface_laser_cam_cannot_silently_omit_inner_layers(tmp_path, two_sided):
    from pcbsmith.laser_artwork import verify_actual_copper_isolation

    board = tmp_path / "four.kicad_pcb"
    board.write_text("(kicad_pcb " + LAYER_TABLE + ")")
    with pytest.raises(ValueError, match="multilayer CAM unsupported"):
        verify_actual_copper_isolation(
            board,
            b"",
            minimum_clearance_mm=0.2,
            minimum_edge_clearance_mm=0.2,
            two_sided=two_sided,
        )
