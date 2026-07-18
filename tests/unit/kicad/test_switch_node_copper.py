"""R6.6 restricted exact switch-node projected copper-union fixture."""

from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph
from pcbsmith.kicad.switch_node_copper import (
    build_exact_placed_pad_copper,
    build_switch_node_copper_union,
)
from pcbsmith.mask_geometry import Disc, OrientedRect, Point
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.semantic_ir import SemanticVerification
from pcbsmith.sensor_copper_removal_ir import (
    ExactFilledZoneCopper,
    ExactFilledZoneReaderPolicy,
)
from pcbsmith.switch_node_copper_ir import (
    SwitchNodeCopperDeclaration,
    SwitchNodeCopperUnionResult,
)


def _component(reference: str) -> BoardComponent:
    return BoardComponent(reference, "fixture", "Fixture:Pad", f"uuid:{reference}")


def _netlist() -> BoardNetlist:
    components = tuple(_component(item) for item in ("U1", "C1", "X1"))
    return BoardNetlist(
        components=components,
        nets=(BoardNet("SW", (("U1", "1"), ("C1", "1"), ("X1", "1"))),),
    )


def _layout(
    *,
    segments: tuple[TrackSegment, ...] = (),
    vias: tuple[ViaSpec, ...] = (),
    zones: tuple[tuple[str, str, tuple[float, float, float, float]], ...] = (),
) -> BoardLayout:
    canonical_segments = tuple(
        TrackSegment(
            float(item.x1),
            float(item.y1),
            float(item.x2),
            float(item.y2),
            item.layer,
            item.net_name,
            float(item.width_mm),
        )
        for item in segments
    )
    canonical_vias = tuple(
        ViaSpec(
            float(item.x),
            float(item.y),
            item.net_name,
            float(item.size_mm),
            float(item.drill_mm),
            item.front_mask,
            item.back_mask,
        )
        for item in vias
    )
    canonical_zones = tuple(
        (net, layer, tuple(float(value) for value in bounds)) for net, layer, bounds in zones
    )
    return BoardLayout(
        placements=tuple((item, float(index)) for index, item in enumerate(_netlist().components)),
        segments=canonical_segments,
        vias=canonical_vias,
        width_mm=30.0,
        height_mm=20.0,
        zones=canonical_zones,
    )


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _policy() -> ExactFilledZoneReaderPolicy:
    return ExactFilledZoneReaderPolicy(
        policy_id="policy:zone-reader",
        reader_id="qualified-reader",
        reader_version="1",
        project_qualification_record_id="qualification:1",
        project_qualification_artifact_sha256="a" * 64,
        reviewer_record_id="review:1",
        status="active",
    )


def _fill(layout: BoardLayout, geometry=None) -> ExactFilledZoneCopper:
    return ExactFilledZoneCopper.build(
        board_layout_fingerprint=board_layout_fingerprint(layout),
        zone_source_id="zone:0:copper:F.Cu",
        zone_index=0,
        zone_net_name="SW",
        layer="F.Cu",
        geometry=geometry or OrientedRect(center=Point(x_mm=9, y_mm=0), width_mm=22, height_mm=4),
        reader_id="qualified-reader",
        reader_version="1",
        reader_policy=_policy(),
        source_artifact_id="artifact:filled-board",
        source_artifact_sha256="b" * 64,
    )


def _declaration(graph, *, complete: bool = True, **updates) -> SwitchNodeCopperDeclaration:
    fields = {
        "declaration_id": "switch-node:SW",
        "graph_fingerprint": graph.graph_fingerprint,
        "board_layout_snapshot_fingerprint": graph.board_layout_snapshot_fingerprint,
        "board_netlist_snapshot_fingerprint": graph.board_netlist_snapshot_fingerprint,
        "net_names": ("SW",),
        "layers": ("F.Cu",),
        "complete_pad_authority": complete,
        **updates,
    }
    return SwitchNodeCopperDeclaration(**fields)


def _pads(graph, geometries=None):
    compounds = geometries or (_rect(0, -0.5, 1, 0.5),) * 3
    return tuple(
        build_exact_placed_pad_copper(
            component_reference=reference,
            pad_number="1",
            net_name="SW",
            layer="F.Cu",
            graph=graph,
            copper=geometry,
        )
        for reference, geometry in zip(("U1", "C1", "X1"), compounds, strict=True)
    )


def test_zone_contains_pad_track_and_via_and_union_counts_zone_once() -> None:
    layout = _layout(
        segments=(TrackSegment(0, 0, 10, 0, "F.Cu", "SW", 1),),
        vias=(ViaSpec(5, 0, "SW", 1, 0.5),),
        zones=(("SW", "F.Cu", (-2, -2, 20, 2)),),
    )
    graph = build_routed_copper_graph(layout, _netlist(), (), (_fill(layout),))

    result = build_switch_node_copper_union(graph, _declaration(graph), _pads(graph))

    assert result.verification is SemanticVerification.EXACT
    assert result.rational_mm2 is not None
    assert result.rational_mm2.fraction() == 88
    assert result.pi_coefficient_mm2 is not None
    assert result.pi_coefficient_mm2.fraction() == 0
    assert {item.source_kind for item in result.primitives} == {
        "pad",
        "track",
        "via",
        "exact_filled_zone",
    }
    assert (
        sum(item.relation == "curved_primitive_contained_in_rectangle" for item in result.witnesses)
        == 2
    )


def test_disjoint_rectangles_track_and_via_retain_symbolic_pi_sum() -> None:
    layout = _layout(
        segments=(TrackSegment(10, 0, 12, 0, "F.Cu", "SW", 2),),
        vias=(ViaSpec(15, 0, "SW", 2, 1),),
    )
    graph = build_routed_copper_graph(layout, _netlist(), ())
    pads = _pads(
        graph,
        (_rect(0, 0, 0.5, 0.5), _rect(2, 0, 2.5, 0.5), _rect(4, 0, 4.5, 0.5)),
    )

    result = build_switch_node_copper_union(graph, _declaration(graph), pads)

    assert result.verification is SemanticVerification.EXACT
    assert result.rational_mm2.fraction() == Fraction(19, 4)
    assert result.pi_coefficient_mm2.fraction() == 2
    assert any(item.relation == "zero_area_contact_or_disjoint" for item in result.witnesses)


def test_identical_geometry_deduplicates_area_without_dropping_source_coverage() -> None:
    graph = build_routed_copper_graph(_layout(), _netlist(), ())
    result = build_switch_node_copper_union(graph, _declaration(graph), _pads(graph))

    assert result.rational_mm2.fraction() == 1
    assert len(result.source_coverage_ids) == 3
    assert len([item for item in result.primitives if item.source_kind == "pad"]) == 3
    witness = next(
        item for item in result.witnesses if item.relation == "identical_geometry_deduplicated"
    )
    assert len(witness.source_ids) == 3


def test_identical_geometry_on_front_and_back_counts_once_per_physical_layer() -> None:
    graph = build_routed_copper_graph(_layout(), _netlist(), ())
    declaration = _declaration(graph, layers=("B.Cu", "F.Cu"))
    pads = tuple(
        build_exact_placed_pad_copper(
            component_reference=reference,
            pad_number="1",
            net_name="SW",
            layer=layer,
            graph=graph,
            copper=_rect(0, 0, 1, 1),
        )
        for reference, layer in (("U1", "F.Cu"), ("C1", "B.Cu"), ("X1", "B.Cu"))
    )

    result = build_switch_node_copper_union(graph, declaration, pads)

    assert result.rational_mm2.fraction() == 2
    assert tuple(item.layer for item in result.per_layer_areas) == ("B.Cu", "F.Cu")
    assert all(item.rational_mm2.fraction() == 1 for item in result.per_layer_areas)
    assert (
        len(
            [
                item
                for item in result.witnesses
                if item.layer == "B.Cu" and item.relation == "identical_geometry_deduplicated"
            ]
        )
        == 1
    )
    assert not any(
        item.layer == "F.Cu" and item.relation == "identical_geometry_deduplicated"
        for item in result.witnesses
    )


def test_through_via_contributes_its_disc_once_on_each_declared_layer() -> None:
    graph = build_routed_copper_graph(_layout(vias=(ViaSpec(20, 10, "SW", 2, 1),)), _netlist(), ())
    declaration = _declaration(graph, layers=("B.Cu", "F.Cu"))
    pads = tuple(
        build_exact_placed_pad_copper(
            component_reference=reference,
            pad_number="1",
            net_name="SW",
            layer=layer,
            graph=graph,
            copper=geometry,
        )
        for reference, layer, geometry in (
            ("U1", "F.Cu", _rect(0, 0, 1, 1)),
            ("C1", "B.Cu", _rect(3, 0, 4, 1)),
            ("X1", "B.Cu", _rect(6, 0, 7, 1)),
        )
    )

    result = build_switch_node_copper_union(graph, declaration, pads)

    assert result.pi_coefficient_mm2.fraction() == 2
    assert all(item.pi_coefficient_mm2.fraction() == 1 for item in result.per_layer_areas)
    via = next(item for item in result.primitives if item.source_kind == "via")
    assert via.layers == ("B.Cu", "F.Cu")
    assert all(via.primitive_id in item.primitive_ids for item in result.per_layer_areas)


def test_partial_curved_overlap_is_unverified_without_partial_numeric_result() -> None:
    layout = _layout(vias=(ViaSpec(1.25, 0.5, "SW", 1, 0.5),))
    graph = build_routed_copper_graph(layout, _netlist(), ())
    pads = _pads(graph, (_rect(0, 0, 1, 1), _rect(3, 0, 4, 1), _rect(6, 0, 7, 1)))

    result = build_switch_node_copper_union(graph, _declaration(graph), pads)

    assert result.verification is SemanticVerification.UNSUPPORTED
    assert result.rational_mm2 is None
    assert result.pi_coefficient_mm2 is None
    assert any("partial_curved_rectangle_overlap" in item for item in result.unknown_reasons)


def test_missing_pad_authority_is_explicitly_unverified() -> None:
    graph = build_routed_copper_graph(_layout(), _netlist(), ())
    result = build_switch_node_copper_union(
        graph, _declaration(graph, complete=False), _pads(graph)[:1]
    )

    assert result.verification is SemanticVerification.UNSUPPORTED
    assert result.rational_mm2 is None
    assert any(item.startswith("pad_authority_incomplete:") for item in result.unknown_reasons)
    with pytest.raises(ValueError, match="cover every switch-net node"):
        build_switch_node_copper_union(graph, _declaration(graph), _pads(graph)[:1])


def test_unknown_zone_fill_and_unsupported_exact_fill_fail_closed() -> None:
    layout = _layout(zones=(("SW", "F.Cu", (0, 0, 2, 2)),))
    graph = build_routed_copper_graph(layout, _netlist(), ())
    unknown = build_switch_node_copper_union(graph, _declaration(graph), _pads(graph))
    assert unknown.verification is SemanticVerification.UNSUPPORTED
    assert any("zone_intent_without_exact_fill" in item for item in unknown.unknown_reasons)

    unsupported_fill = _fill(
        layout,
        OrientedRect(center=Point(x_mm=1, y_mm=1), width_mm=2, height_mm=2, angle_deg=45),
    )
    filled_graph = build_routed_copper_graph(layout, _netlist(), (), (unsupported_fill,))
    result = build_switch_node_copper_union(
        filled_graph, _declaration(filled_graph), _pads(filled_graph)
    )
    assert result.verification is SemanticVerification.UNSUPPORTED
    assert any("unsupported_exact_fill_geometry" in item for item in result.unknown_reasons)


def test_diagonal_track_and_non_rectangular_pad_are_never_approximated() -> None:
    layout = _layout(segments=(TrackSegment(10, 0, 11, 1, "F.Cu", "SW", 1),))
    graph = build_routed_copper_graph(layout, _netlist(), ())
    triangle = ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=((0, 0), (1, 0), (0, 1))),))
    result = build_switch_node_copper_union(
        graph,
        _declaration(graph),
        _pads(graph, (triangle, _rect(3, 0, 4, 1), _rect(6, 0, 7, 1))),
    )
    assert result.verification is SemanticVerification.UNSUPPORTED
    assert any("diagonal_track" in item for item in result.unknown_reasons)
    assert any("non_rectangular_pad" in item for item in result.unknown_reasons)


def test_wrong_snapshot_net_layer_and_source_identity_reject() -> None:
    graph = build_routed_copper_graph(_layout(), _netlist(), ())
    with pytest.raises(ValueError, match="differs from graph snapshots"):
        build_switch_node_copper_union(
            graph,
            _declaration(graph, board_layout_snapshot_fingerprint="c" * 64),
            _pads(graph),
        )
    foreign = _pads(graph)[0].model_copy(update={"net_name": "FOREIGN"})
    with pytest.raises(ValueError, match="invents a switch-node pad"):
        build_switch_node_copper_union(graph, _declaration(graph, complete=False), (foreign,))
    wrong_layer = _pads(graph)[0].model_copy(update={"layer": "B.Cu"})
    with pytest.raises(ValueError, match="invents a switch-node pad or layer"):
        build_switch_node_copper_union(graph, _declaration(graph, complete=False), (wrong_layer,))
    invented = _pads(graph)[0].model_copy(update={"source_id": "pad:invented"})
    with pytest.raises(ValueError, match="invented or stale"):
        build_switch_node_copper_union(graph, _declaration(graph, complete=False), (invented,))


def test_order_determinism_json_replay_tamper_rejection_and_immutability() -> None:
    layout = _layout(
        segments=(
            TrackSegment(10, 0, 12, 0, "F.Cu", "SW", 1),
            TrackSegment(14, 0, 16, 0, "F.Cu", "SW", 1),
        )
    )
    reverse_layout = _layout(segments=tuple(reversed(layout.segments)))
    first_graph = build_routed_copper_graph(layout, _netlist(), ())
    second_graph = build_routed_copper_graph(reverse_layout, _netlist(), ())
    assert first_graph.graph_fingerprint == second_graph.graph_fingerprint
    first = build_switch_node_copper_union(
        first_graph, _declaration(first_graph), tuple(reversed(_pads(first_graph)))
    )
    second = build_switch_node_copper_union(
        first_graph, _declaration(first_graph), _pads(first_graph)
    )
    assert first.evidence_fingerprint == second.evidence_fingerprint
    assert first.primitives == second.primitives
    replayed = SwitchNodeCopperUnionResult.model_validate_json(first.model_dump_json())
    assert replayed == first

    payload = json.loads(first.model_dump_json())
    tampered = deepcopy(payload)
    tampered["source_coverage_ids"] = tampered["source_coverage_ids"][:-1]
    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        SwitchNodeCopperUnionResult.model_validate(tampered)
    with pytest.raises(ValidationError):
        first.declaration.net_names = ("OTHER",)
    with pytest.raises(ValidationError):
        first.placed_pad_copper[0].source_id = "pad:changed"


def test_disc_fill_supported_when_disjoint_and_scope_makes_no_policy_claim() -> None:
    layout = _layout(zones=(("SW", "F.Cu", (20, 10, 22, 12)),))
    graph = build_routed_copper_graph(
        layout,
        _netlist(),
        (),
        (_fill(layout, Disc(center=Point(x_mm=21, y_mm=11), radius_mm=1)),),
    )
    pads = _pads(graph, (_rect(0, 0, 1, 1), _rect(3, 0, 4, 1), _rect(6, 0, 7, 1)))
    result = build_switch_node_copper_union(graph, _declaration(graph), pads)
    assert result.rational_mm2.fraction() == 3
    assert result.pi_coefficient_mm2.fraction() == 1
    assert result.metric_scope == "restricted_exact_per_layer_planar_copper_union_v1"
    dumped = result.model_dump(mode="json")
    assert "limit" not in dumped and "pass" not in dumped and "thermal" not in dumped
