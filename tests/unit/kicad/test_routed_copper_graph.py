"""R6.3 firing fixture for replay-bound routed copper graphs and paths."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
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
from pcbsmith.kicad.routed_copper_graph import (
    build_routed_copper_graph,
    resolve_copper_path,
)
from pcbsmith.mask_geometry import OrientedRect, Point
from pcbsmith.routed_copper_graph_ir import (
    CopperTerminalAnchorBinding,
    DeclaredCopperPathSelection,
    ResolvedCopperPathResult,
    RoutedCopperGraphResult,
)
from pcbsmith.semantic_ir import SemanticVerification
from pcbsmith.sensor_copper_removal_ir import (
    ExactFilledZoneCopper,
    ExactFilledZoneReaderPolicy,
)


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value="fixture",
        footprint="Fixture:Pad",
        uuid_path=f"uuid:{reference}",
    )


def _netlist() -> BoardNetlist:
    components = tuple(_component(item) for item in ("U1", "C1", "X1", "G1", "G2"))
    return BoardNetlist(
        components=components,
        nets=(
            BoardNet(name="VDD", nodes=(("U1", "1"), ("C1", "1"), ("X1", "1"))),
            BoardNet(name="GND", nodes=(("G1", "1"), ("G2", "1"))),
        ),
    )


def _anchors(
    *,
    start: tuple[str, str, str, str, str] = ("start", "pad:U1:1", "U1", "1", "VDD"),
    end: tuple[str, str, str, str, str] = ("end", "pad:C1:1", "C1", "1", "VDD"),
    start_point: tuple[str, str, str] = ("F.Cu", "0", "0"),
    end_point: tuple[str, str, str] = ("B.Cu", "10", "0"),
) -> tuple[CopperTerminalAnchorBinding, ...]:
    return (
        CopperTerminalAnchorBinding(
            anchor_id=start[0],
            physical_pad_source_id=start[1],
            component_reference=start[2],
            pad_number=start[3],
            net_name=start[4],
            layer=start_point[0],
            x_mm=start_point[1],
            y_mm=start_point[2],
        ),
        CopperTerminalAnchorBinding(
            anchor_id=end[0],
            physical_pad_source_id=end[1],
            component_reference=end[2],
            pad_number=end[3],
            net_name=end[4],
            layer=end_point[0],
            x_mm=end_point[1],
            y_mm=end_point[2],
        ),
    )


def _layout(
    *,
    segments: tuple[TrackSegment, ...] | None = None,
    vias: tuple[ViaSpec, ...] | None = None,
    zones: tuple[tuple[str, str, tuple[float, float, float, float]], ...] = (),
) -> BoardLayout:
    return BoardLayout(
        placements=tuple(
            (item, float(index * 2)) for index, item in enumerate(_netlist().components)
        ),
        segments=segments
        if segments is not None
        else (
            TrackSegment(0.0, 0.0, 5.0, 0.0, "F.Cu", "VDD", 0.2),
            TrackSegment(5.0, 0.0, 10.0, 0.0, "B.Cu", "VDD", 0.15),
        ),
        vias=vias if vias is not None else (ViaSpec(5.0, 0.0, "VDD", 0.6, 0.3),),
        width_mm=20.0,
        height_mm=10.0,
        parts_row_y_mm=2.0,
        zones=zones,
    )


def _selection(graph: RoutedCopperGraphResult, edges: tuple[str, ...] | None = None, **updates):
    fields = {
        "selection_id": "selection:vdd-source-to-cap",
        "graph_fingerprint": graph.graph_fingerprint,
        "net_name": "VDD",
        "start_anchor_id": "start",
        "end_anchor_id": "end",
        "ordered_edge_ids": edges,
        **updates,
    }
    return DeclaredCopperPathSelection(**fields)


def test_exact_two_layer_path_retains_via_width_sources_and_rational_length() -> None:
    layout = _layout()
    graph = build_routed_copper_graph(layout, _netlist(), _anchors())

    result = resolve_copper_path(graph, _selection(graph))

    assert result.connectivity_state == "connected"
    assert result.verification is SemanticVerification.EXACT
    assert result.via_count == 1
    assert len(result.via_source_ids) == 1
    assert result.via_source_ids[0].startswith("via:")
    assert result.minimum_width_mm == Decimal("0.15")
    assert len(result.neck_edge_ids) == 1
    assert result.exact_rational_planar_length_mm is not None
    assert result.exact_rational_planar_length_mm.fraction() == Fraction(10)
    assert result.radical_length_terms[0].squarefree_radicand == 1
    assert result.radical_length_terms[0].coefficient_mm.fraction() == 10
    assert tuple(item.kind for item in graph.edges).count("track") == 2
    assert tuple(item.kind for item in graph.edges).count("via") == 1


def test_terminal_anchor_requires_exact_netlist_node_and_nearest_is_not_substituted() -> None:
    layout = _layout()
    wrong_nearest = _anchors(
        start=("start", "pad:X1:1", "X1", "1", "VDD"),
        start_point=("F.Cu", "0.1", "0"),
    )
    graph = build_routed_copper_graph(layout, _netlist(), wrong_nearest)
    result = resolve_copper_path(graph, _selection(graph))
    assert result.connectivity_state == "unverified"
    assert any("anchor_on_track_interior" in item for item in result.unknown_reasons)
    retained_start = next(item for item in graph.terminal_anchors if item.anchor_id == "start")
    assert retained_start.physical_pad_source_id == "pad:X1:1"

    invalid = _anchors(start=("start", "pad:U1:9", "U1", "9", "VDD"))
    with pytest.raises(ValueError, match="exact BoardNetlist net node"):
        build_routed_copper_graph(layout, _netlist(), invalid)


def test_net_ownership_and_foreign_net_explicit_edge_reject() -> None:
    layout = _layout(
        segments=(
            *_layout().segments,
            TrackSegment(0.0, 5.0, 10.0, 5.0, "F.Cu", "GND", 0.2),
        )
    )
    graph = build_routed_copper_graph(layout, _netlist(), _anchors())
    foreign = next(item.edge_id for item in graph.edges if item.net_name == "GND")

    with pytest.raises(ValueError, match="foreign-net"):
        resolve_copper_path(graph, _selection(graph, (foreign,)))


def test_disconnected_path_is_exact_without_zone_intent() -> None:
    layout = _layout(segments=(), vias=())
    graph = build_routed_copper_graph(layout, _netlist(), _anchors())
    result = resolve_copper_path(graph, _selection(graph))

    assert result.connectivity_state == "disconnected"
    assert result.verification is SemanticVerification.EXACT
    assert result.ordered_edge_ids == ()
    assert result.minimum_width_mm is None


def test_via_diameter_is_not_mixed_into_minimum_track_width() -> None:
    layout = _layout(vias=(ViaSpec(5.0, 0.0, "VDD", 0.05, 0.02),))
    result = resolve_copper_path(
        build_routed_copper_graph(layout, _netlist(), _anchors()),
        _selection(build_routed_copper_graph(layout, _netlist(), _anchors())),
    )
    assert result.via_count == 1
    assert result.minimum_width_mm == Decimal("0.15")
    via_edge = next(item for item in result.graph.edges if item.kind == "via")
    assert via_edge.width_mm is None
    assert via_edge.via_size_mm == Decimal("0.05")
    assert all(
        next(edge for edge in result.graph.edges if edge.edge_id == edge_id).kind == "track"
        for edge_id in result.neck_edge_ids
    )


@pytest.mark.parametrize(
    ("segments", "reason"),
    (
        (
            (
                TrackSegment(0.0, 0.0, 10.0, 0.0, "F.Cu", "VDD", 0.2),
                TrackSegment(5.0, 0.0, 5.0, 3.0, "F.Cu", "VDD", 0.2),
            ),
            "track_t_junction",
        ),
        (
            (
                TrackSegment(0.0, 0.0, 10.0, 0.0, "F.Cu", "VDD", 0.2),
                TrackSegment(5.0, -2.0, 5.0, 2.0, "F.Cu", "VDD", 0.2),
            ),
            "track_crossing",
        ),
        (
            (
                TrackSegment(0.0, 0.0, 7.0, 0.0, "F.Cu", "VDD", 0.2),
                TrackSegment(5.0, 0.0, 10.0, 0.0, "F.Cu", "VDD", 0.2),
            ),
            "collinear_track_overlap",
        ),
    ),
)
def test_nonendpoint_track_contacts_fail_closed_as_unverified(
    segments: tuple[TrackSegment, ...], reason: str
) -> None:
    layout = _layout(segments=segments, vias=())
    anchors = _anchors(end_point=("F.Cu", "10", "0"))
    graph = build_routed_copper_graph(layout, _netlist(), anchors)
    result = resolve_copper_path(graph, _selection(graph))
    assert any(item.reason == reason for item in graph.unverified_contacts)
    assert result.connectivity_state == "unverified"
    assert any(reason in item for item in result.unknown_reasons)


def test_anchor_on_track_interior_is_explicitly_unverified() -> None:
    layout = _layout(
        segments=(TrackSegment(0.0, 0.0, 10.0, 0.0, "F.Cu", "VDD", 0.2),),
        vias=(),
    )
    anchors = _anchors(start_point=("F.Cu", "5", "0"), end_point=("F.Cu", "10", "0"))
    graph = build_routed_copper_graph(layout, _netlist(), anchors)
    result = resolve_copper_path(graph, _selection(graph))
    assert graph.unverified_contacts[0].reason == "anchor_on_track_interior"
    assert result.connectivity_state == "unverified"
    assert result.ordered_edge_ids == ()


def test_via_on_track_interior_is_explicitly_unverified() -> None:
    layout = _layout(
        segments=(
            TrackSegment(0.0, 0.0, 10.0, 0.0, "F.Cu", "VDD", 0.2),
            TrackSegment(5.0, 0.0, 10.0, 0.0, "B.Cu", "VDD", 0.2),
        ),
        vias=(ViaSpec(5.0, 0.0, "VDD", 0.6, 0.3),),
    )
    graph = build_routed_copper_graph(layout, _netlist(), _anchors())
    result = resolve_copper_path(graph, _selection(graph))
    assert any(item.reason == "via_on_track_interior" for item in graph.unverified_contacts)
    assert result.connectivity_state == "unverified"


def test_branched_path_requires_explicit_contiguous_selection() -> None:
    segments = (
        TrackSegment(0.0, 0.0, 5.0, 0.0, "F.Cu", "VDD", 0.2),
        TrackSegment(5.0, 0.0, 10.0, 0.0, "F.Cu", "VDD", 0.2),
        TrackSegment(0.0, 0.0, 5.0, 3.0, "F.Cu", "VDD", 0.2),
        TrackSegment(5.0, 3.0, 10.0, 0.0, "F.Cu", "VDD", 0.2),
    )
    layout = _layout(segments=segments, vias=())
    anchors = _anchors(end_point=("F.Cu", "10", "0"))
    graph = build_routed_copper_graph(layout, _netlist(), anchors)

    with pytest.raises(ValueError, match="multiple copper paths"):
        resolve_copper_path(graph, _selection(graph))

    bottom_edges = tuple(
        item.edge_id
        for item in graph.edges
        if item.kind == "track"
        and next(node for node in graph.nodes if node.node_id == item.start_node_id).y_mm == 0
        and next(node for node in graph.nodes if node.node_id == item.end_node_id).y_mm == 0
    )
    # Derive the actual traversal order from the start node, independent of edge-ID sorting.
    start_node = next(node.node_id for node in graph.nodes if "start" in node.anchor_ids)
    first = next(
        edge
        for edge in graph.edges
        if edge.edge_id in bottom_edges and start_node in {edge.start_node_id, edge.end_node_id}
    )
    second = next(edge for edge in graph.edges if edge.edge_id in bottom_edges and edge != first)
    result = resolve_copper_path(graph, _selection(graph, (first.edge_id, second.edge_id)))
    assert result.connectivity_state == "connected"

    with pytest.raises(ValueError, match="noncontiguous"):
        resolve_copper_path(graph, _selection(graph, (second.edge_id, first.edge_id)))


def test_diagonal_path_retains_canonical_combined_radical_not_float_length() -> None:
    layout = _layout(
        segments=(
            TrackSegment(0.0, 0.0, 1.0, 1.0, "F.Cu", "VDD", 0.2),
            TrackSegment(1.0, 1.0, 2.0, 2.0, "F.Cu", "VDD", 0.2),
        ),
        vias=(),
    )
    anchors = _anchors(end_point=("F.Cu", "2", "2"))
    result = resolve_copper_path(
        build_routed_copper_graph(layout, _netlist(), anchors),
        _selection(build_routed_copper_graph(layout, _netlist(), anchors)),
    )

    assert result.exact_rational_planar_length_mm is None
    assert len(result.radical_length_terms) == 1
    assert result.radical_length_terms[0].squarefree_radicand == 2
    assert result.radical_length_terms[0].coefficient_mm.fraction() == 2
    track_edges = [item for item in result.graph.edges if item.kind == "track"]
    assert all(
        item.planar_squared_length.fraction() == 2
        for item in track_edges
        if item.planar_squared_length
    )


def _reader_policy(status: str = "active") -> ExactFilledZoneReaderPolicy:
    return ExactFilledZoneReaderPolicy(
        policy_id="policy:zone-reader",
        reader_id="kicad-final-fill-reader",
        reader_version="1",
        project_qualification_record_id="qualification:zone-reader",
        project_qualification_artifact_sha256="a" * 64,
        reviewer_record_id="review:zone-reader",
        status=status,
    )


def _exact_fill(layout: BoardLayout) -> ExactFilledZoneCopper:
    return ExactFilledZoneCopper.build(
        board_layout_fingerprint=board_layout_fingerprint(layout),
        zone_source_id="zone:0:copper:F.Cu",
        zone_index=0,
        zone_net_name="VDD",
        layer="F.Cu",
        geometry=OrientedRect(center=Point(x_mm=5.0, y_mm=0.0), width_mm=12.0, height_mm=2.0),
        reader_id="kicad-final-fill-reader",
        reader_version="1",
        reader_policy=_reader_policy(),
        source_artifact_id="artifact:filled-board",
        source_artifact_sha256="b" * 64,
    )


def test_exact_fill_proves_connectivity_but_never_fabricates_path_length() -> None:
    layout = _layout(segments=(), vias=(), zones=(("VDD", "F.Cu", (-1.0, -1.0, 11.0, 1.0)),))
    anchors = _anchors(end_point=("F.Cu", "10", "0"))
    graph = build_routed_copper_graph(layout, _netlist(), anchors, (_exact_fill(layout),))
    result = resolve_copper_path(graph, _selection(graph))

    assert len(graph.edges) == 1
    assert graph.edges[0].kind == "exact_zone_fill"
    assert graph.edges[0].planar_squared_length is None
    assert result.connectivity_state == "unverified"
    assert result.exact_rational_planar_length_mm is None
    assert "exact_zone_connectivity_has_no_trace_length_authority" in result.unknown_reasons


def test_zone_intent_without_final_fill_makes_scope_unverified_not_zero_length() -> None:
    layout = _layout(segments=(), vias=(), zones=(("VDD", "F.Cu", (-1.0, -1.0, 11.0, 1.0)),))
    anchors = _anchors(end_point=("F.Cu", "10", "0"))
    result = resolve_copper_path(
        build_routed_copper_graph(layout, _netlist(), anchors),
        _selection(build_routed_copper_graph(layout, _netlist(), anchors)),
    )

    assert result.connectivity_state == "unverified"
    assert result.verification is SemanticVerification.UNSUPPORTED
    assert result.exact_rational_planar_length_mm is None
    assert any("zone_intent_without_exact_fill" in item for item in result.unknown_reasons)


def test_layout_order_reversal_has_deterministic_graph_and_path_authority() -> None:
    layout = _layout()
    reversed_layout = _layout(
        segments=tuple(reversed(layout.segments)), vias=tuple(reversed(layout.vias))
    )
    first = build_routed_copper_graph(layout, _netlist(), tuple(reversed(_anchors())))
    second = build_routed_copper_graph(reversed_layout, _netlist(), _anchors())

    assert first.nodes == second.nodes
    assert first.edges == second.edges
    assert first.terminal_anchors == second.terminal_anchors
    assert first.graph_fingerprint == second.graph_fingerprint
    first_path = resolve_copper_path(first, _selection(first))
    second_path = resolve_copper_path(second, _selection(second))
    assert first_path.ordered_edge_ids == second_path.ordered_edge_ids
    assert first_path.radical_length_terms == second_path.radical_length_terms


def test_reverse_terminal_selection_reverses_nodes_but_preserves_physical_evidence() -> None:
    graph = build_routed_copper_graph(_layout(), _netlist(), _anchors())
    forward = resolve_copper_path(graph, _selection(graph))
    reverse = resolve_copper_path(
        graph,
        _selection(graph, start_anchor_id="end", end_anchor_id="start"),
    )
    assert reverse.ordered_node_ids == tuple(reversed(forward.ordered_node_ids))
    assert reverse.ordered_edge_ids == tuple(reversed(forward.ordered_edge_ids))
    assert reverse.via_source_ids == forward.via_source_ids
    assert reverse.radical_length_terms == forward.radical_length_terms


def test_stale_selection_edge_layout_netlist_anchor_via_fill_and_result_tamper_reject() -> None:
    graph = build_routed_copper_graph(_layout(), _netlist(), _anchors())
    result = resolve_copper_path(graph, _selection(graph))
    assert RoutedCopperGraphResult.model_validate_json(graph.model_dump_json()) == graph
    assert ResolvedCopperPathResult.model_validate_json(result.model_dump_json()) == result

    stale_selection = _selection(graph).model_copy(update={"graph_fingerprint": "c" * 64})
    with pytest.raises(ValueError, match="stale for this graph"):
        resolve_copper_path(graph, stale_selection)
    with pytest.raises(ValueError, match="absent or foreign-net"):
        resolve_copper_path(graph, _selection(graph, ("edge:missing",)))

    graph_payload = graph.model_dump(mode="json")
    for field, mutate in (
        (
            "board_layout_snapshot_json",
            lambda value: value.replace('"width_mm":20.0', '"width_mm":21.0'),
        ),
        (
            "board_netlist_snapshot_json",
            lambda value: value.replace('"value":"fixture"', '"value":"changed"', 1),
        ),
    ):
        payload = deepcopy(graph_payload)
        payload[field] = mutate(payload[field])
        with pytest.raises(ValidationError):
            RoutedCopperGraphResult.model_validate(payload)
    via_payload = deepcopy(graph_payload)
    parsed_layout = json.loads(via_payload["board_layout_snapshot_json"])
    parsed_layout["vias"][0]["x"] = 5.1
    via_payload["board_layout_snapshot_json"] = json.dumps(
        parsed_layout,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    with pytest.raises(ValidationError):
        RoutedCopperGraphResult.model_validate(via_payload)
    for field in ("terminal_anchors", "edges", "nodes", "graph_fingerprint", "result_fingerprint"):
        payload = deepcopy(graph_payload)
        if field in {"graph_fingerprint", "result_fingerprint"}:
            payload[field] = "c" * 64
        elif field == "terminal_anchors":
            payload[field][0]["x_mm"] = "0.1"
        elif field == "edges":
            payload[field][0]["source_id"] = "tampered"
        else:
            payload[field][0]["x_mm"] = "0.1"
        with pytest.raises(ValidationError):
            RoutedCopperGraphResult.model_validate(payload)

    result_payload = result.model_dump(mode="json")
    for field in (
        "via_count",
        "minimum_width_mm",
        "ordered_source_ids",
        "evidence_fingerprint",
        "result_fingerprint",
    ):
        payload = deepcopy(result_payload)
        if field in {"evidence_fingerprint", "result_fingerprint"}:
            payload[field] = "c" * 64
        elif field == "via_count":
            payload[field] = 0
        elif field == "minimum_width_mm":
            payload[field] = "9"
        else:
            payload[field] = list(reversed(payload[field]))
        with pytest.raises(ValidationError):
            ResolvedCopperPathResult.model_validate(payload)

    zone_layout = _layout(segments=(), vias=(), zones=(("VDD", "F.Cu", (-1.0, -1.0, 11.0, 1.0)),))
    fill_payload = _exact_fill(zone_layout).model_dump(mode="json")
    fill_payload["reader_policy"]["policy_id"] = "tampered"
    with pytest.raises(ValidationError):
        ExactFilledZoneCopper.model_validate(fill_payload)


def test_input_layout_netlist_and_anchor_values_are_not_mutated() -> None:
    layout = _layout()
    netlist = _netlist()
    anchors = _anchors()
    before = (repr(layout), repr(netlist), tuple(item.model_dump_json() for item in anchors))
    graph = build_routed_copper_graph(layout, netlist, anchors)
    resolve_copper_path(graph, _selection(graph))
    after = (repr(layout), repr(netlist), tuple(item.model_dump_json() for item in anchors))
    assert after == before
