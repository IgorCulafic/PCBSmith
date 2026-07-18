"""Exact replay derivation for the retained routed-copper graph."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from typing import Any

from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment, ViaSpec
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.mask_geometry import Disc, OrientedRect
from pcbsmith.routed_copper_graph_ir import (
    CopperRadicalLengthTerm,
    CopperTerminalAnchorBinding,
    DeclaredCopperPathSelection,
    ExactRational,
    ResolvedCopperPathResult,
    RoutedCopperEdge,
    RoutedCopperGraphResult,
    RoutedCopperNode,
    RoutedCopperUnknownZoneReason,
    RoutedCopperUnverifiedContact,
    canonical_decimal,
    fingerprint,
)
from pcbsmith.semantic_ir import SemanticVerification
from pcbsmith.sensor_copper_removal_ir import ExactFilledZoneCopper

NodeKey = tuple[str, str, Decimal, Decimal]


def _decimal(value: float) -> Decimal:
    return canonical_decimal(Decimal(str(value)), "coordinate")


def _node_id(key: NodeKey) -> str:
    net, layer, x_value, y_value = key
    return f"node:{fingerprint([net, layer, str(x_value), str(y_value)])}"


def _source_id(kind: str, payload: Any) -> str:
    return f"{kind}:{fingerprint(payload)}"


def _node_key(net: str, layer: str, x_value: float | Decimal, y_value: float | Decimal) -> NodeKey:
    x_decimal = _decimal(x_value) if isinstance(x_value, float) else x_value
    y_decimal = _decimal(y_value) if isinstance(y_value, float) else y_value
    return net, layer, x_decimal, y_decimal


def _squared(first: NodeKey, second: NodeKey) -> Fraction:
    dx = Fraction(first[2]) - Fraction(second[2])
    dy = Fraction(first[3]) - Fraction(second[3])
    return dx * dx + dy * dy


def _qpoint(key: NodeKey) -> tuple[Fraction, Fraction]:
    return Fraction(key[2]), Fraction(key[3])


def _cross(first: tuple[Fraction, Fraction], second: tuple[Fraction, Fraction]) -> Fraction:
    return first[0] * second[1] - first[1] * second[0]


def _subtract(
    first: tuple[Fraction, Fraction], second: tuple[Fraction, Fraction]
) -> tuple[Fraction, Fraction]:
    return first[0] - second[0], first[1] - second[1]


def _strictly_on_segment(
    point: tuple[Fraction, Fraction],
    start: tuple[Fraction, Fraction],
    end: tuple[Fraction, Fraction],
) -> bool:
    if _cross(_subtract(point, start), _subtract(end, start)) != 0:
        return False
    return point not in {start, end} and all(
        min(first, second) <= value <= max(first, second)
        for value, first, second in zip(point, start, end, strict=True)
    )


def _segment_contact(
    first_start: tuple[Fraction, Fraction],
    first_end: tuple[Fraction, Fraction],
    second_start: tuple[Fraction, Fraction],
    second_end: tuple[Fraction, Fraction],
) -> tuple[str, tuple[Fraction, Fraction]] | None:
    first_vector = _subtract(first_end, first_start)
    second_vector = _subtract(second_end, second_start)
    offset = _subtract(second_start, first_start)
    denominator = _cross(first_vector, second_vector)
    if denominator == 0:
        if _cross(offset, first_vector) != 0:
            return None
        shared = tuple(
            sorted(
                point
                for point in {first_start, first_end, second_start, second_end}
                if all(
                    min(a, b) <= value <= max(a, b)
                    for value, a, b in zip(point, first_start, first_end, strict=True)
                )
                and all(
                    min(a, b) <= value <= max(a, b)
                    for value, a, b in zip(point, second_start, second_end, strict=True)
                )
            )
        )
        if len(shared) >= 2 and shared[0] != shared[-1]:
            return "collinear_track_overlap", shared[0]
        return None
    first_parameter = _cross(offset, second_vector) / denominator
    second_parameter = _cross(offset, first_vector) / denominator
    if not (0 <= first_parameter <= 1 and 0 <= second_parameter <= 1):
        return None
    point = (
        first_start[0] + first_parameter * first_vector[0],
        first_start[1] + first_parameter * first_vector[1],
    )
    first_endpoint = first_parameter in {0, 1}
    second_endpoint = second_parameter in {0, 1}
    if first_endpoint and second_endpoint:
        return None
    return (
        "track_t_junction" if first_endpoint or second_endpoint else "track_crossing",
        point,
    )


def _contact_issue(
    *,
    net_name: str,
    layer: str,
    source_ids: tuple[str, ...],
    point: tuple[Fraction, Fraction],
    reason: str,
) -> RoutedCopperUnverifiedContact:
    payload = [net_name, layer, sorted(source_ids), str(point[0]), str(point[1]), reason]
    return RoutedCopperUnverifiedContact(
        issue_id=f"contact:{fingerprint(payload)}",
        net_name=net_name,
        layer=layer,
        source_ids=source_ids,
        x=ExactRational.build(point[0]),
        y=ExactRational.build(point[1]),
        reason=reason,
    )


def _validate_anchors(
    anchors: Sequence[CopperTerminalAnchorBinding], netlist: BoardNetlist
) -> tuple[CopperTerminalAnchorBinding, ...]:
    retained = tuple(
        sorted(
            (
                CopperTerminalAnchorBinding.model_validate_json(item.model_dump_json())
                for item in anchors
            ),
            key=lambda item: item.anchor_id,
        )
    )
    if len({item.anchor_id for item in retained}) != len(retained):
        raise ValueError("terminal anchor identities must be unique")
    if len({item.physical_pad_source_id for item in retained}) != len(retained):
        raise ValueError("terminal physical pad source identities must be unique")
    component_references = tuple(item.reference for item in netlist.components)
    if len(component_references) != len(set(component_references)):
        raise ValueError("BoardNetlist component references must be unique")
    net_names = tuple(item.name for item in netlist.nets)
    if len(net_names) != len(set(net_names)):
        raise ValueError("BoardNetlist net names must be unique")
    all_nodes = tuple(node for net in netlist.nets for node in net.nodes)
    if len(all_nodes) != len(set(all_nodes)):
        raise ValueError("BoardNetlist physical nodes must belong to exactly one net")
    components = set(component_references)
    net_nodes = {item.name: set(item.nodes) for item in netlist.nets}
    for item in retained:
        if item.component_reference not in components:
            raise ValueError("terminal anchor component is absent from BoardNetlist")
        if (item.component_reference, item.pad_number) not in net_nodes.get(item.net_name, set()):
            raise ValueError("terminal anchor does not match an exact BoardNetlist net node")
    return retained


def _validate_fills(
    fills: Sequence[ExactFilledZoneCopper], layout: BoardLayout
) -> tuple[ExactFilledZoneCopper, ...]:
    retained = tuple(
        sorted(
            (ExactFilledZoneCopper.model_validate_json(item.model_dump_json()) for item in fills),
            key=lambda item: item.zone_source_id,
        )
    )
    if len({item.zone_source_id for item in retained}) != len(retained):
        raise ValueError("exact filled-zone source identities must be unique")
    layout_fp = board_layout_fingerprint(layout)
    for item in retained:
        if item.board_layout_fingerprint != layout_fp or item.zone_index >= len(layout.zones):
            raise ValueError("exact filled-zone record is stale for this BoardLayout")
        net_name, layer, _rectangle = layout.zones[item.zone_index]
        if (
            item.zone_source_id != f"zone:{item.zone_index}:copper:{layer}"
            or item.zone_net_name != net_name
            or item.layer != layer
        ):
            raise ValueError("exact filled-zone record has wrong source/net/layer")
    return retained


def _track_payload(item: TrackSegment) -> dict[str, str]:
    endpoints = sorted(
        (
            (str(_decimal(item.x1)), str(_decimal(item.y1))),
            (str(_decimal(item.x2)), str(_decimal(item.y2))),
        )
    )
    return {
        "net": item.net_name,
        "layer": item.layer,
        "width": str(_decimal(item.width_mm)),
        "a": ",".join(endpoints[0]),
        "b": ",".join(endpoints[1]),
    }


def _via_payload(item: ViaSpec) -> dict[str, str]:
    return {
        "net": item.net_name,
        "x": str(_decimal(item.x)),
        "y": str(_decimal(item.y)),
        "size": str(_decimal(item.size_mm)),
        "drill": str(_decimal(item.drill_mm)),
        "front_mask": item.front_mask.value,
        "back_mask": item.back_mask.value,
    }


def _point_in_supported_fill(fill: ExactFilledZoneCopper, key: NodeKey) -> bool | None:
    x_value, y_value = Fraction(key[2]), Fraction(key[3])
    geometry = fill.geometry
    if isinstance(geometry, OrientedRect) and geometry.angle_deg == 0.0:
        cx, cy = Fraction(str(geometry.center.x_mm)), Fraction(str(geometry.center.y_mm))
        half_w = Fraction(str(geometry.width_mm)) / 2
        half_h = Fraction(str(geometry.height_mm)) / 2
        return cx - half_w <= x_value <= cx + half_w and cy - half_h <= y_value <= cy + half_h
    if isinstance(geometry, Disc):
        cx, cy = Fraction(str(geometry.center.x_mm)), Fraction(str(geometry.center.y_mm))
        radius = Fraction(str(geometry.radius_mm))
        return (x_value - cx) ** 2 + (y_value - cy) ** 2 <= radius * radius
    return None


def rederive_routed_copper_graph(
    board_layout_snapshot_json: str,
    board_netlist_snapshot_json: str,
    terminal_anchors: Sequence[CopperTerminalAnchorBinding],
    exact_filled_zones: Sequence[ExactFilledZoneCopper] = (),
) -> dict[str, Any]:
    layout = parse_canonical_board_layout_snapshot(board_layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(board_netlist_snapshot_json)
    anchors = _validate_anchors(terminal_anchors, netlist)
    fills = _validate_fills(exact_filled_zones, layout)
    known_nets = {item.name for item in netlist.nets}
    node_anchors: dict[NodeKey, list[str]] = defaultdict(list)
    keys: set[NodeKey] = set()
    for anchor in anchors:
        key = _node_key(anchor.net_name, anchor.layer, anchor.x_mm, anchor.y_mm)
        keys.add(key)
        node_anchors[key].append(anchor.anchor_id)
    raw_edges: list[
        tuple[str, str, str, NodeKey, NodeKey, Decimal | None, Fraction | None, str | None]
    ] = []
    seen_sources: set[str] = set()
    track_records: list[tuple[str, NodeKey, NodeKey]] = []
    for segment in layout.segments:
        if segment.net_name not in known_nets or segment.layer not in {"F.Cu", "B.Cu"}:
            raise ValueError("track segment net/layer is absent from routed graph authority")
        first = _node_key(segment.net_name, segment.layer, segment.x1, segment.y1)
        second = _node_key(segment.net_name, segment.layer, segment.x2, segment.y2)
        if first == second:
            raise ValueError("zero-length retained track segment is not a graph edge")
        source = _source_id("track", _track_payload(segment))
        if source in seen_sources:
            raise ValueError("duplicate physical track geometry has ambiguous source identity")
        seen_sources.add(source)
        keys.update((first, second))
        track_records.append((source, first, second))
        raw_edges.append(
            (
                source,
                source,
                "track",
                first,
                second,
                _decimal(segment.width_mm),
                _squared(first, second),
                None,
            )
        )
    via_records: list[tuple[str, NodeKey, NodeKey]] = []
    for via in layout.vias:
        if via.net_name not in known_nets:
            raise ValueError("via net is absent from routed graph authority")
        first = _node_key(via.net_name, "F.Cu", via.x, via.y)
        second = _node_key(via.net_name, "B.Cu", via.x, via.y)
        source = _source_id("via", _via_payload(via))
        if source in seen_sources:
            raise ValueError("duplicate physical via geometry has ambiguous source identity")
        seen_sources.add(source)
        keys.update((first, second))
        via_records.append((source, first, second))
        raw_edges.append(
            (source, source, "via", first, second, _decimal(via.size_mm), Fraction(0), None)
        )
    contacts: list[RoutedCopperUnverifiedContact] = []
    for anchor in anchors:
        anchor_key = _node_key(anchor.net_name, anchor.layer, anchor.x_mm, anchor.y_mm)
        for source, first, second in track_records:
            if first[:2] == anchor_key[:2] and _strictly_on_segment(
                _qpoint(anchor_key), _qpoint(first), _qpoint(second)
            ):
                contacts.append(
                    _contact_issue(
                        net_name=anchor.net_name,
                        layer=anchor.layer,
                        source_ids=(anchor.physical_pad_source_id, source),
                        point=_qpoint(anchor_key),
                        reason="anchor_on_track_interior",
                    )
                )
    for via_source, front, back in via_records:
        for via_key in (front, back):
            for track_source, first, second in track_records:
                if first[:2] == via_key[:2] and _strictly_on_segment(
                    _qpoint(via_key), _qpoint(first), _qpoint(second)
                ):
                    contacts.append(
                        _contact_issue(
                            net_name=via_key[0],
                            layer=via_key[1],
                            source_ids=(via_source, track_source),
                            point=_qpoint(via_key),
                            reason="via_on_track_interior",
                        )
                    )
    for index, (first_source, first_start, first_end) in enumerate(track_records):
        for second_source, second_start, second_end in track_records[index + 1 :]:
            if first_start[:2] != second_start[:2]:
                continue
            contact = _segment_contact(
                _qpoint(first_start),
                _qpoint(first_end),
                _qpoint(second_start),
                _qpoint(second_end),
            )
            if contact is not None:
                reason, point = contact
                contacts.append(
                    _contact_issue(
                        net_name=first_start[0],
                        layer=first_start[1],
                        source_ids=(first_source, second_source),
                        point=point,
                        reason=reason,
                    )
                )
    fill_by_id = {item.zone_source_id: item for item in fills}
    unknown: list[RoutedCopperUnknownZoneReason] = []
    for index, (net_name, layer, _rectangle) in enumerate(layout.zones):
        source = f"zone:{index}:copper:{layer}"
        fill = fill_by_id.get(source)
        if fill is None:
            unknown.append(
                RoutedCopperUnknownZoneReason(
                    zone_source_id=source,
                    net_name=net_name,
                    layer=layer,
                    reason="zone_intent_without_exact_fill",
                )
            )
            continue
        candidates = sorted(key for key in keys if key[0] == net_name and key[1] == layer)
        containment = [(key, _point_in_supported_fill(fill, key)) for key in candidates]
        if any(value is None for _, value in containment):
            unknown.append(
                RoutedCopperUnknownZoneReason(
                    zone_source_id=source,
                    net_name=net_name,
                    layer=layer,
                    reason="exact_fill_geometry_not_supported_for_point_connectivity",
                )
            )
            continue
        inside = [key for key, value in containment if value]
        for first_index, first in enumerate(inside):
            for second in inside[first_index + 1 :]:
                edge_payload = [source, _node_id(first), _node_id(second)]
                edge_id = _source_id("zone-edge", edge_payload)
                raw_edges.append(
                    (
                        edge_id,
                        source,
                        "exact_zone_fill",
                        first,
                        second,
                        None,
                        None,
                        fill.final_fill_record_sha256,
                    )
                )
    nodes = tuple(
        sorted(
            (
                RoutedCopperNode(
                    node_id=_node_id(key),
                    net_name=key[0],
                    layer=key[1],
                    x_mm=key[2],
                    y_mm=key[3],
                    anchor_ids=tuple(node_anchors.get(key, ())),
                )
                for key in keys
            ),
            key=lambda item: item.node_id,
        )
    )
    edges = []
    for edge_id, source, kind, first, second, width, squared, fill_hash in raw_edges:
        start, end = sorted((_node_id(first), _node_id(second)))
        edges.append(
            RoutedCopperEdge(
                edge_id=edge_id,
                source_id=source,
                kind=kind,
                net_name=first[0],
                start_node_id=start,
                end_node_id=end,
                width_mm=width if kind == "track" else None,
                via_size_mm=width if kind == "via" else None,
                planar_squared_length=None if squared is None else ExactRational.build(squared),
                final_fill_record_sha256=fill_hash,
            )
        )
    canonical_edges = tuple(sorted(edges, key=lambda item: item.edge_id))
    if len({item.edge_id for item in canonical_edges}) != len(canonical_edges):
        raise ValueError("derived copper edge identities are not unique")
    layout_fp = board_layout_snapshot_fingerprint(board_layout_snapshot_json)
    netlist_fp = board_netlist_snapshot_fingerprint(board_netlist_snapshot_json)
    unknown_tuple = tuple(sorted(unknown, key=lambda item: item.zone_source_id))
    contact_tuple = tuple(sorted(contacts, key=lambda item: item.issue_id))
    if len({item.issue_id for item in contact_tuple}) != len(contact_tuple):
        raise ValueError("derived unverified contact identities are not unique")
    graph_fp = fingerprint(
        {
            "anchors": [item.model_dump(mode="json") for item in anchors],
            "fills": [item.model_dump(mode="json") for item in fills],
            "nodes": [item.model_dump(mode="json") for item in nodes],
            "edges": [item.model_dump(mode="json") for item in canonical_edges],
            "unknown": [item.model_dump(mode="json") for item in unknown_tuple],
            "unverified_contacts": [item.model_dump(mode="json") for item in contact_tuple],
        }
    )
    return {
        "board_layout_snapshot_fingerprint": layout_fp,
        "board_netlist_snapshot_fingerprint": netlist_fp,
        "terminal_anchors": anchors,
        "exact_filled_zones": fills,
        "nodes": nodes,
        "edges": canonical_edges,
        "unknown_zone_reasons": unknown_tuple,
        "unverified_contacts": contact_tuple,
        "graph_fingerprint": graph_fp,
    }


def build_routed_copper_graph(
    layout: BoardLayout,
    netlist: BoardNetlist,
    terminal_anchors: Sequence[CopperTerminalAnchorBinding],
    exact_filled_zones: Sequence[ExactFilledZoneCopper] = (),
) -> RoutedCopperGraphResult:
    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    derived = rederive_routed_copper_graph(
        layout_json, netlist_json, terminal_anchors, exact_filled_zones
    )
    fields = {
        "board_layout_snapshot_json": layout_json,
        "board_netlist_snapshot_json": netlist_json,
        **derived,
    }
    provisional = RoutedCopperGraphResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return RoutedCopperGraphResult(**fields, result_fingerprint=result_fp)


def _find_path(
    start: str,
    end: str,
    adjacency: dict[str, list[tuple[str, str]]],
    *,
    excluded_edge_id: str | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    stack = [start]
    parent: dict[str, tuple[str, str] | None] = {start: None}
    while stack:
        node = stack.pop()
        if node == end:
            break
        for next_node, edge_id in reversed(sorted(adjacency.get(node, ()))):
            if edge_id == excluded_edge_id or next_node in parent:
                continue
            parent[next_node] = node, edge_id
            stack.append(next_node)
    if end not in parent:
        return None
    reversed_nodes = [end]
    reversed_edges: list[str] = []
    current = end
    while current != start:
        previous = parent[current]
        if previous is None:
            raise ValueError("path predecessor chain ended before its declared start")
        current, edge_id = previous
        reversed_nodes.append(current)
        reversed_edges.append(edge_id)
    return tuple(reversed(reversed_nodes)), tuple(reversed(reversed_edges))


def _unique_path(
    start: str, end: str, adjacency: dict[str, list[tuple[str, str]]]
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    candidate = _find_path(start, end, adjacency)
    if candidate is None:
        return None
    for edge_id in candidate[1]:
        if _find_path(start, end, adjacency, excluded_edge_id=edge_id) is not None:
            raise ValueError("branched/multiple copper paths require exact ordered edge selection")
    return candidate


def _factor_radical(squared: Fraction) -> tuple[int, Fraction]:
    if squared <= 0:
        raise ValueError("radical factor requires positive squared length")
    integer = squared.numerator * squared.denominator
    outside = 1
    divisor = 2
    while divisor * divisor <= integer:
        square = divisor * divisor
        while integer % square == 0:
            integer //= square
            outside *= divisor
        divisor += 1
    return integer, Fraction(outside, squared.denominator)


def rederive_copper_path(
    graph_result: RoutedCopperGraphResult,
    selection: DeclaredCopperPathSelection,
) -> dict[str, Any]:
    graph = RoutedCopperGraphResult.model_validate_json(graph_result.model_dump_json())
    retained = DeclaredCopperPathSelection.model_validate_json(selection.model_dump_json())
    if retained.graph_fingerprint != graph.graph_fingerprint:
        raise ValueError("declared copper path selection is stale for this graph")
    anchors = {item.anchor_id: item for item in graph.terminal_anchors}
    if retained.start_anchor_id not in anchors or retained.end_anchor_id not in anchors:
        raise ValueError("declared copper path references an absent terminal anchor")
    start_anchor, end_anchor = anchors[retained.start_anchor_id], anchors[retained.end_anchor_id]
    if start_anchor.net_name != retained.net_name or end_anchor.net_name != retained.net_name:
        raise ValueError("declared copper path terminal belongs to another net")
    node_by_anchor = {
        anchor_id: node.node_id for node in graph.nodes for anchor_id in node.anchor_ids
    }
    start, end = node_by_anchor[retained.start_anchor_id], node_by_anchor[retained.end_anchor_id]
    edge_map = {item.edge_id: item for item in graph.edges}
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in graph.edges:
        if edge.net_name == retained.net_name:
            adjacency[edge.start_node_id].append((edge.end_node_id, edge.edge_id))
            adjacency[edge.end_node_id].append((edge.start_node_id, edge.edge_id))
    if retained.ordered_edge_ids is None:
        path = _unique_path(start, end, adjacency)
        nodes, edge_ids = path if path is not None else ((start,), ())
    else:
        current = start
        nodes_list = [start]
        for edge_id in retained.ordered_edge_ids:
            selected_edge = edge_map.get(edge_id)
            if selected_edge is None or selected_edge.net_name != retained.net_name:
                raise ValueError("explicit copper path contains absent or foreign-net edge")
            if current == selected_edge.start_node_id:
                current = selected_edge.end_node_id
            elif current == selected_edge.end_node_id:
                current = selected_edge.start_node_id
            else:
                raise ValueError("explicit copper path edge order is noncontiguous")
            nodes_list.append(current)
        if current != end:
            raise ValueError("explicit copper path does not terminate at declared end anchor")
        nodes, edge_ids = tuple(nodes_list), retained.ordered_edge_ids
    chosen = tuple(edge_map[item] for item in edge_ids)
    relevant_unknown = tuple(
        f"{item.zone_source_id}:{item.reason}"
        for item in graph.unknown_zone_reasons
        if item.net_name == retained.net_name
    )
    contact_unknown = tuple(
        f"{item.issue_id}:{item.reason}"
        for item in graph.unverified_contacts
        if item.net_name == retained.net_name
    )
    selected_zone = any(item.kind == "exact_zone_fill" for item in chosen)
    extra_unknown = (
        ("exact_zone_connectivity_has_no_trace_length_authority",) if selected_zone else ()
    )
    unknown_reasons = tuple(sorted((*relevant_unknown, *contact_unknown, *extra_unknown)))
    if unknown_reasons:
        state, verification = "unverified", SemanticVerification.UNSUPPORTED
    elif chosen:
        state, verification = "connected", SemanticVerification.EXACT
    else:
        state, verification = "disconnected", SemanticVerification.EXACT
    vias = tuple(item for item in chosen if item.kind == "via")
    widths = tuple(
        item.width_mm for item in chosen if item.kind == "track" and item.width_mm is not None
    )
    minimum = min(widths) if widths else None
    necks = tuple(
        item.edge_id
        for item in chosen
        if item.kind == "track" and minimum is not None and item.width_mm == minimum
    )
    radical_coefficients: dict[int, Fraction] = defaultdict(Fraction)
    for item in chosen:
        if item.kind != "track" or item.planar_squared_length is None:
            continue
        squared = item.planar_squared_length.fraction()
        if squared > 0:
            radicand, coefficient = _factor_radical(squared)
            radical_coefficients[radicand] += coefficient
    terms = tuple(
        CopperRadicalLengthTerm(
            squarefree_radicand=radicand,
            coefficient_mm=ExactRational.build(coefficient),
        )
        for radicand, coefficient in sorted(radical_coefficients.items())
    )
    rational_length = (
        ExactRational.build(radical_coefficients.get(1, Fraction(0)))
        if chosen
        and not unknown_reasons
        and not selected_zone
        and set(radical_coefficients).issubset({1})
        else None
    )
    source_ids = tuple(item.source_id for item in chosen)
    evidence_fp = fingerprint(
        {
            "selection": retained.model_dump(mode="json"),
            "state": state,
            "nodes": nodes,
            "edges": edge_ids,
            "sources": source_ids,
            "unknown": unknown_reasons,
            "terms": [item.model_dump(mode="json") for item in terms],
        }
    )
    return {
        "connectivity_state": state,
        "verification": verification,
        "ordered_edge_ids": edge_ids,
        "ordered_node_ids": nodes,
        "ordered_source_ids": source_ids,
        "via_count": len(vias),
        "via_source_ids": tuple(item.source_id for item in vias),
        "minimum_width_mm": minimum,
        "neck_edge_ids": necks,
        "radical_length_terms": terms,
        "exact_rational_planar_length_mm": rational_length,
        "unknown_reasons": unknown_reasons,
        "evidence_fingerprint": evidence_fp,
    }


def resolve_copper_path(
    graph: RoutedCopperGraphResult, selection: DeclaredCopperPathSelection
) -> ResolvedCopperPathResult:
    derived = rederive_copper_path(graph, selection)
    fields = {"graph": graph, "selection": selection, **derived}
    provisional = ResolvedCopperPathResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return ResolvedCopperPathResult(**fields, result_fingerprint=result_fp)
