"""Restricted exact planar-union metric for declared switch-node copper."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from pcbsmith.kicad.board_serialization import (
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.mask_geometry import Disc, OrientedRect
from pcbsmith.placement_geometry import ExactPlanarCompound
from pcbsmith.routed_copper_graph_ir import ExactRational, RoutedCopperGraphResult, fingerprint
from pcbsmith.semantic_ir import SemanticVerification
from pcbsmith.switch_node_copper_ir import (
    ExactCopperCapsule,
    ExactCopperDisc,
    ExactCopperRectangle,
    ExactPlacedPadCopper,
    SwitchNodeCopperDeclaration,
    SwitchNodeCopperLayerArea,
    SwitchNodeCopperPrimitive,
    SwitchNodeCopperUnionResult,
    SwitchNodeCopperUnionWitness,
)


def _q(value: float) -> Fraction:
    return Fraction(str(value))


def _rat(value: Fraction) -> ExactRational:
    return ExactRational.build(value)


def _rectangle(
    min_x: Fraction, min_y: Fraction, max_x: Fraction, max_y: Fraction
) -> ExactCopperRectangle:
    return ExactCopperRectangle(
        min_x_mm=_rat(min_x),
        min_y_mm=_rat(min_y),
        max_x_mm=_rat(max_x),
        max_y_mm=_rat(max_y),
    )


def _compound_rectangles(compound: ExactPlanarCompound) -> tuple[ExactCopperRectangle, ...] | None:
    rectangles: list[ExactCopperRectangle] = []
    for polygon in compound.polygons:
        if polygon.holes or len(polygon.outer) != 4:
            return None
        points = {(_q(x), _q(y)) for x, y in polygon.outer}
        xs = sorted({point[0] for point in points})
        ys = sorted({point[1] for point in points})
        if (
            len(xs) != 2
            or len(ys) != 2
            or points
            != {
                (xs[0], ys[0]),
                (xs[0], ys[1]),
                (xs[1], ys[0]),
                (xs[1], ys[1]),
            }
        ):
            return None
        rectangles.append(_rectangle(xs[0], ys[0], xs[1], ys[1]))
    return tuple(rectangles)


def exact_placed_pad_source_id(
    *,
    component_reference: str,
    pad_number: str,
    net_name: str,
    layer: str,
    graph_fingerprint: str,
    board_layout_snapshot_fingerprint: str,
    board_netlist_snapshot_fingerprint: str,
    copper: ExactPlanarCompound,
) -> str:
    """Derive the non-inventable identity of one explicit placed-pad record."""

    return "pad:" + fingerprint(
        {
            "component_reference": component_reference,
            "pad_number": pad_number,
            "net_name": net_name,
            "layer": layer,
            "graph_fingerprint": graph_fingerprint,
            "board_layout_snapshot_fingerprint": board_layout_snapshot_fingerprint,
            "board_netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint,
            "copper_fingerprint": copper.semantic_fingerprint(),
        }
    )


def build_exact_placed_pad_copper(
    *,
    component_reference: str,
    pad_number: str,
    net_name: str,
    layer: str,
    graph: RoutedCopperGraphResult,
    copper: ExactPlanarCompound,
) -> ExactPlacedPadCopper:
    source_id = exact_placed_pad_source_id(
        component_reference=component_reference,
        pad_number=pad_number,
        net_name=net_name,
        layer=layer,
        graph_fingerprint=graph.graph_fingerprint,
        board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
        copper=copper,
    )
    return ExactPlacedPadCopper(
        source_id=source_id,
        component_reference=component_reference,
        pad_number=pad_number,
        net_name=net_name,
        layer=layer,
        graph_fingerprint=graph.graph_fingerprint,
        board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
        copper=copper,
    )


def _primitive(
    *,
    source_id: str,
    source_kind: str,
    net_name: str,
    layers: tuple[str, ...],
    geometry: ExactCopperRectangle | ExactCopperDisc | ExactCopperCapsule,
    authority_fingerprint: str,
) -> SwitchNodeCopperPrimitive:
    if isinstance(geometry, ExactCopperRectangle):
        kind = "rectangle"
    elif isinstance(geometry, ExactCopperDisc):
        kind = "disc"
    else:
        kind = "capsule"
    primitive_fp = fingerprint({"kind": kind, "geometry": geometry.model_dump(mode="json")})
    primitive_id = "primitive:" + fingerprint(
        {
            "source_id": source_id,
            "source_kind": source_kind,
            "net_name": net_name,
            "layers": tuple(sorted(layers)),
            "source_authority_fingerprint": authority_fingerprint,
            "primitive_fingerprint": primitive_fp,
        }
    )
    return SwitchNodeCopperPrimitive(
        primitive_id=primitive_id,
        source_id=source_id,
        source_kind=source_kind,
        net_name=net_name,
        layers=layers,
        geometry_kind=kind,
        rectangle=geometry if isinstance(geometry, ExactCopperRectangle) else None,
        disc=geometry if isinstance(geometry, ExactCopperDisc) else None,
        capsule=geometry if isinstance(geometry, ExactCopperCapsule) else None,
        source_authority_fingerprint=authority_fingerprint,
        primitive_fingerprint=primitive_fp,
    )


def _witness(
    layer: str,
    relation: str,
    sources: Sequence[str],
    primitive_fingerprints: Sequence[str],
    predicate: str,
) -> SwitchNodeCopperUnionWitness:
    payload = [layer, relation, sorted(sources), sorted(primitive_fingerprints), predicate]
    return SwitchNodeCopperUnionWitness(
        witness_id="union-witness:" + fingerprint(payload),
        layer=layer,
        relation=relation,
        source_ids=tuple(sources),
        primitive_fingerprints=tuple(primitive_fingerprints),
        exact_predicate=predicate,
    )


def _rect_bounds(rectangle: ExactCopperRectangle) -> tuple[Fraction, Fraction, Fraction, Fraction]:
    return (
        rectangle.min_x_mm.fraction(),
        rectangle.min_y_mm.fraction(),
        rectangle.max_x_mm.fraction(),
        rectangle.max_y_mm.fraction(),
    )


def _rectangle_union_area(rectangles: Sequence[ExactCopperRectangle]) -> Fraction:
    if not rectangles:
        return Fraction(0)
    bounds = [_rect_bounds(item) for item in rectangles]
    xs = sorted({value for rect in bounds for value in (rect[0], rect[2])})
    area = Fraction(0)
    for left, right in zip(xs, xs[1:], strict=False):
        intervals = sorted(
            (bottom, top) for min_x, bottom, max_x, top in bounds if min_x < right and max_x > left
        )
        if not intervals:
            continue
        union_y = Fraction(0)
        current_bottom, current_top = intervals[0]
        for bottom, top in intervals[1:]:
            if bottom <= current_top:
                current_top = max(current_top, top)
            else:
                union_y += current_top - current_bottom
                current_bottom, current_top = bottom, top
        union_y += current_top - current_bottom
        area += (right - left) * union_y
    return area


def _interval_gap(first: tuple[Fraction, Fraction], second: tuple[Fraction, Fraction]) -> Fraction:
    if first[1] < second[0]:
        return second[0] - first[1]
    if second[1] < first[0]:
        return first[0] - second[1]
    return Fraction(0)


def _disc_contained_in_rect(disc: ExactCopperDisc, rectangle: ExactCopperRectangle) -> bool:
    x, y, radius = (
        disc.center_x_mm.fraction(),
        disc.center_y_mm.fraction(),
        disc.radius_mm.fraction(),
    )
    min_x, min_y, max_x, max_y = _rect_bounds(rectangle)
    return (
        min_x <= x - radius and x + radius <= max_x and min_y <= y - radius and y + radius <= max_y
    )


def _capsule_bounds(capsule: ExactCopperCapsule) -> tuple[Fraction, Fraction, Fraction, Fraction]:
    x1, y1, x2, y2, radius = (
        capsule.start_x_mm.fraction(),
        capsule.start_y_mm.fraction(),
        capsule.end_x_mm.fraction(),
        capsule.end_y_mm.fraction(),
        capsule.radius_mm.fraction(),
    )
    return min(x1, x2) - radius, min(y1, y2) - radius, max(x1, x2) + radius, max(y1, y2) + radius


def _capsule_contained_in_rect(
    capsule: ExactCopperCapsule, rectangle: ExactCopperRectangle
) -> bool:
    min_x, min_y, max_x, max_y = _capsule_bounds(capsule)
    rmin_x, rmin_y, rmax_x, rmax_y = _rect_bounds(rectangle)
    return rmin_x <= min_x and max_x <= rmax_x and rmin_y <= min_y and max_y <= rmax_y


def _disc_rect_disjoint(disc: ExactCopperDisc, rectangle: ExactCopperRectangle) -> bool:
    x, y, radius = (
        disc.center_x_mm.fraction(),
        disc.center_y_mm.fraction(),
        disc.radius_mm.fraction(),
    )
    min_x, min_y, max_x, max_y = _rect_bounds(rectangle)
    dx = _interval_gap((x, x), (min_x, max_x))
    dy = _interval_gap((y, y), (min_y, max_y))
    return dx * dx + dy * dy >= radius * radius


def _capsule_rect_disjoint(capsule: ExactCopperCapsule, rectangle: ExactCopperRectangle) -> bool:
    x1, y1, x2, y2, radius = (
        capsule.start_x_mm.fraction(),
        capsule.start_y_mm.fraction(),
        capsule.end_x_mm.fraction(),
        capsule.end_y_mm.fraction(),
        capsule.radius_mm.fraction(),
    )
    min_x, min_y, max_x, max_y = _rect_bounds(rectangle)
    dx = _interval_gap((min(x1, x2), max(x1, x2)), (min_x, max_x))
    dy = _interval_gap((min(y1, y2), max(y1, y2)), (min_y, max_y))
    return dx * dx + dy * dy >= radius * radius


def _segment_intervals(
    capsule: ExactCopperCapsule,
) -> tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction]]:
    x1, y1, x2, y2 = (
        capsule.start_x_mm.fraction(),
        capsule.start_y_mm.fraction(),
        capsule.end_x_mm.fraction(),
        capsule.end_y_mm.fraction(),
    )
    return (min(x1, x2), max(x1, x2)), (min(y1, y2), max(y1, y2))


def _curves_disjoint(
    first: ExactCopperDisc | ExactCopperCapsule,
    second: ExactCopperDisc | ExactCopperCapsule,
) -> bool:
    if isinstance(first, ExactCopperDisc):
        first_x = (first.center_x_mm.fraction(), first.center_x_mm.fraction())
        first_y = (first.center_y_mm.fraction(), first.center_y_mm.fraction())
        first_radius = first.radius_mm.fraction()
    else:
        first_x, first_y = _segment_intervals(first)
        first_radius = first.radius_mm.fraction()
    if isinstance(second, ExactCopperDisc):
        second_x = (second.center_x_mm.fraction(), second.center_x_mm.fraction())
        second_y = (second.center_y_mm.fraction(), second.center_y_mm.fraction())
        second_radius = second.radius_mm.fraction()
    else:
        second_x, second_y = _segment_intervals(second)
        second_radius = second.radius_mm.fraction()
    dx = _interval_gap(first_x, second_x)
    dy = _interval_gap(first_y, second_y)
    radius = first_radius + second_radius
    return dx * dx + dy * dy >= radius * radius


def _curve_area(
    geometry: ExactCopperDisc | ExactCopperCapsule,
) -> tuple[Fraction, Fraction]:
    radius = geometry.radius_mm.fraction()
    if isinstance(geometry, ExactCopperDisc):
        return Fraction(0), radius * radius
    x_interval, y_interval = _segment_intervals(geometry)
    length = (x_interval[1] - x_interval[0]) + (y_interval[1] - y_interval[0])
    return length * 2 * radius, radius * radius


def _evaluate_layer_union(
    layer: str,
    primitives: Sequence[SwitchNodeCopperPrimitive],
    initial_unknown: Sequence[str],
) -> tuple[SwitchNodeCopperLayerArea, tuple[SwitchNodeCopperUnionWitness, ...]]:
    layer_primitives = tuple(item for item in primitives if layer in item.layers)
    by_geometry: dict[str, list[SwitchNodeCopperPrimitive]] = {}
    for item in layer_primitives:
        by_geometry.setdefault(item.primitive_fingerprint, []).append(item)
    witnesses: list[SwitchNodeCopperUnionWitness] = []
    representatives: list[SwitchNodeCopperPrimitive] = []
    for primitive_fp, group in sorted(by_geometry.items()):
        representatives.append(group[0])
        if len(group) > 1:
            witnesses.append(
                _witness(
                    layer,
                    "identical_geometry_deduplicated",
                    [item.source_id for item in group],
                    [primitive_fp],
                    "canonical geometry fingerprints are exactly equal on this copper layer",
                )
            )
    rectangle_primitives = [item for item in representatives if item.rectangle is not None]
    for item in rectangle_primitives:
        witnesses.append(
            _witness(
                layer,
                "rectangle_sweep_member",
                (item.source_id,),
                (item.primitive_fingerprint,),
                "exact rational x-slab and merged-y-interval sweep on this copper layer",
            )
        )
    rational_area = _rectangle_union_area(
        [item.rectangle for item in rectangle_primitives if item.rectangle is not None]
    )
    pi_area = Fraction(0)
    unknown = list(initial_unknown)
    contributing_curves: list[SwitchNodeCopperPrimitive] = []
    curved = [item for item in representatives if item.disc is not None or item.capsule is not None]
    for item in curved:
        curve_geometry = item.disc if item.disc is not None else item.capsule
        if curve_geometry is None:
            raise AssertionError("curved primitive unexpectedly lacks geometry")
        containing = next(
            (
                rectangle
                for rectangle in rectangle_primitives
                if rectangle.rectangle is not None
                and (
                    _disc_contained_in_rect(curve_geometry, rectangle.rectangle)
                    if isinstance(curve_geometry, ExactCopperDisc)
                    else _capsule_contained_in_rect(curve_geometry, rectangle.rectangle)
                )
            ),
            None,
        )
        if containing is not None:
            witnesses.append(
                _witness(
                    layer,
                    "curved_primitive_contained_in_rectangle",
                    (item.source_id, containing.source_id),
                    (item.primitive_fingerprint, containing.primitive_fingerprint),
                    "exact rational curved extent is contained in one same-layer rectangle",
                )
            )
            continue
        overlap = False
        for rectangle in rectangle_primitives:
            if rectangle.rectangle is None:
                continue
            disjoint = (
                _disc_rect_disjoint(curve_geometry, rectangle.rectangle)
                if isinstance(curve_geometry, ExactCopperDisc)
                else _capsule_rect_disjoint(curve_geometry, rectangle.rectangle)
            )
            if not disjoint:
                unknown.append(
                    f"{item.source_id}:{rectangle.source_id}:partial_curved_rectangle_overlap"
                )
                overlap = True
                break
            witnesses.append(
                _witness(
                    layer,
                    "zero_area_contact_or_disjoint",
                    (item.source_id, rectangle.source_id),
                    (item.primitive_fingerprint, rectangle.primitive_fingerprint),
                    "exact rational squared distance is at least squared radius on this layer",
                )
            )
        if overlap:
            continue
        for previous in contributing_curves:
            other = previous.disc if previous.disc is not None else previous.capsule
            if other is None or not _curves_disjoint(curve_geometry, other):
                unknown.append(f"{item.source_id}:{previous.source_id}:partial_curved_overlap")
                overlap = True
                break
            witnesses.append(
                _witness(
                    layer,
                    "zero_area_contact_or_disjoint",
                    (item.source_id, previous.source_id),
                    (item.primitive_fingerprint, previous.primitive_fingerprint),
                    "exact rational centerline distance is at least radius sum on this layer",
                )
            )
        if overlap:
            continue
        rational_add, pi_add = _curve_area(curve_geometry)
        rational_area += rational_add
        pi_area += pi_add
        contributing_curves.append(item)
    unknown_tuple = tuple(sorted(set(unknown)))
    witness_tuple = tuple(sorted(witnesses, key=lambda item: item.witness_id))
    verification = (
        SemanticVerification.EXACT if not unknown_tuple else SemanticVerification.UNSUPPORTED
    )
    area = SwitchNodeCopperLayerArea(
        layer=layer,
        verification=verification,
        rational_mm2=_rat(rational_area) if not unknown_tuple else None,
        pi_coefficient_mm2=_rat(pi_area) if not unknown_tuple else None,
        primitive_ids=tuple(item.primitive_id for item in layer_primitives),
        witness_ids=tuple(item.witness_id for item in witness_tuple),
        unknown_reasons=unknown_tuple,
    )
    return area, witness_tuple


def rederive_switch_node_copper_union(
    graph_result: RoutedCopperGraphResult,
    declaration: SwitchNodeCopperDeclaration,
    placed_pad_copper: Sequence[ExactPlacedPadCopper],
) -> dict[str, Any]:
    graph = RoutedCopperGraphResult.model_validate_json(graph_result.model_dump_json())
    declared = SwitchNodeCopperDeclaration.model_validate_json(declaration.model_dump_json())
    pads = tuple(
        sorted(
            (
                ExactPlacedPadCopper.model_validate_json(item.model_dump_json())
                for item in placed_pad_copper
            ),
            key=lambda item: item.source_id,
        )
    )
    if declared.graph_fingerprint != graph.graph_fingerprint:
        raise ValueError("switch-node declaration is stale for the routed-copper graph")
    if (
        declared.board_layout_snapshot_fingerprint != graph.board_layout_snapshot_fingerprint
        or declared.board_netlist_snapshot_fingerprint != graph.board_netlist_snapshot_fingerprint
    ):
        raise ValueError("switch-node declaration differs from graph snapshots")
    netlist = parse_canonical_board_netlist_snapshot(graph.board_netlist_snapshot_json)
    known_nets = {item.name for item in netlist.nets}
    if not set(declared.net_names).issubset(known_nets):
        raise ValueError("switch-node declaration names a net absent from the retained netlist")

    expected_nodes: set[tuple[str, str, str]] = set()
    node_owner: dict[tuple[str, str], str] = {}
    for net in netlist.nets:
        if net.name not in declared.net_names:
            continue
        for reference, pad_number in net.nodes:
            node = (reference, pad_number, net.name)
            owner = node_owner.setdefault((reference, pad_number), net.name)
            if owner != net.name or node in expected_nodes:
                raise ValueError(
                    "switch-node netlist has duplicate or ambiguous physical pad nodes"
                )
            expected_nodes.add(node)
    seen_nodes: set[tuple[str, str, str]] = set()
    seen_sources: set[str] = set()
    for pad in pads:
        if (
            pad.graph_fingerprint != graph.graph_fingerprint
            or pad.board_layout_snapshot_fingerprint != graph.board_layout_snapshot_fingerprint
            or pad.board_netlist_snapshot_fingerprint != graph.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("placed-pad copper record differs from graph snapshots")
        node = (pad.component_reference, pad.pad_number, pad.net_name)
        if node not in expected_nodes or pad.layer not in declared.layers:
            raise ValueError("placed-pad copper record invents a switch-node pad or layer")
        if node in seen_nodes or pad.source_id in seen_sources:
            raise ValueError("placed-pad copper node and source identities must be unique")
        expected_source = exact_placed_pad_source_id(
            component_reference=pad.component_reference,
            pad_number=pad.pad_number,
            net_name=pad.net_name,
            layer=pad.layer,
            graph_fingerprint=pad.graph_fingerprint,
            board_layout_snapshot_fingerprint=pad.board_layout_snapshot_fingerprint,
            board_netlist_snapshot_fingerprint=pad.board_netlist_snapshot_fingerprint,
            copper=pad.copper,
        )
        if pad.source_id != expected_source:
            raise ValueError("placed-pad copper source identity is invented or stale")
        seen_nodes.add(node)
        seen_sources.add(pad.source_id)
    if declared.complete_pad_authority and seen_nodes != expected_nodes:
        raise ValueError("complete pad authority must cover every switch-net node exactly once")

    primitives: list[SwitchNodeCopperPrimitive] = []
    unknown_by_layer: dict[str, list[str]] = {layer: [] for layer in declared.layers}
    all_source_ids: set[str] = set(seen_sources)
    for pad in pads:
        pad_rectangles = _compound_rectangles(pad.copper)
        if pad_rectangles is None:
            unknown_by_layer[pad.layer].append(
                f"{pad.source_id}:unsupported_non_rectangular_pad_geometry"
            )
            continue
        pad_authority = fingerprint(pad.model_dump(mode="json"))
        for rectangle in pad_rectangles:
            primitives.append(
                _primitive(
                    source_id=pad.source_id,
                    source_kind="pad",
                    net_name=pad.net_name,
                    layers=(pad.layer,),
                    geometry=rectangle,
                    authority_fingerprint=pad_authority,
                )
            )

    nodes = {item.node_id: item for item in graph.nodes}
    graph_edges = [
        item
        for item in graph.edges
        if item.kind in {"track", "via"} and item.net_name in declared.net_names
    ]
    for edge in graph_edges:
        first, second = nodes[edge.start_node_id], nodes[edge.end_node_id]
        if edge.kind == "track":
            if first.layer not in declared.layers:
                continue
            if edge.source_id in all_source_ids:
                raise ValueError("switch-node copper source identities collide")
            all_source_ids.add(edge.source_id)
            if first.x_mm != second.x_mm and first.y_mm != second.y_mm:
                unknown_by_layer[first.layer].append(
                    f"{edge.source_id}:diagonal_track_capsule_not_supported"
                )
                continue
            if edge.width_mm is None:
                raise ValueError("replay-valid track edge unexpectedly lacks width")
            endpoints = sorted(
                (
                    (Fraction(first.x_mm), Fraction(first.y_mm)),
                    (Fraction(second.x_mm), Fraction(second.y_mm)),
                )
            )
            track_geometry = ExactCopperCapsule(
                start_x_mm=_rat(endpoints[0][0]),
                start_y_mm=_rat(endpoints[0][1]),
                end_x_mm=_rat(endpoints[1][0]),
                end_y_mm=_rat(endpoints[1][1]),
                radius_mm=_rat(Fraction(edge.width_mm) / 2),
            )
            primitives.append(
                _primitive(
                    source_id=edge.source_id,
                    source_kind="track",
                    net_name=edge.net_name,
                    layers=(first.layer,),
                    geometry=track_geometry,
                    authority_fingerprint=fingerprint(edge.model_dump(mode="json")),
                )
            )
        else:
            included_layers = tuple(
                sorted(set(declared.layers).intersection({first.layer, second.layer}))
            )
            if not included_layers:
                continue
            if edge.source_id in all_source_ids:
                raise ValueError("switch-node copper source identities collide")
            all_source_ids.add(edge.source_id)
            if edge.via_size_mm is None:
                raise ValueError("replay-valid via edge unexpectedly lacks diameter")
            via_geometry = ExactCopperDisc(
                center_x_mm=_rat(Fraction(first.x_mm)),
                center_y_mm=_rat(Fraction(first.y_mm)),
                radius_mm=_rat(Fraction(edge.via_size_mm) / 2),
            )
            primitives.append(
                _primitive(
                    source_id=edge.source_id,
                    source_kind="via",
                    net_name=edge.net_name,
                    layers=included_layers,
                    geometry=via_geometry,
                    authority_fingerprint=fingerprint(edge.model_dump(mode="json")),
                )
            )

    for fill in graph.exact_filled_zones:
        if fill.zone_net_name not in declared.net_names or fill.layer not in declared.layers:
            continue
        if fill.zone_source_id in all_source_ids:
            raise ValueError("switch-node copper source identities collide")
        all_source_ids.add(fill.zone_source_id)
        fill_geometry: ExactCopperRectangle | ExactCopperDisc | None = None
        if isinstance(fill.geometry, OrientedRect) and fill.geometry.angle_deg in {
            0.0,
            90.0,
            180.0,
            270.0,
        }:
            cx, cy = _q(fill.geometry.center.x_mm), _q(fill.geometry.center.y_mm)
            width, height = _q(fill.geometry.width_mm), _q(fill.geometry.height_mm)
            if fill.geometry.angle_deg in {90.0, 270.0}:
                width, height = height, width
            half_width, half_height = width / 2, height / 2
            fill_geometry = _rectangle(
                cx - half_width, cy - half_height, cx + half_width, cy + half_height
            )
        elif isinstance(fill.geometry, Disc):
            fill_geometry = ExactCopperDisc(
                center_x_mm=_rat(_q(fill.geometry.center.x_mm)),
                center_y_mm=_rat(_q(fill.geometry.center.y_mm)),
                radius_mm=_rat(_q(fill.geometry.radius_mm)),
            )
        if fill_geometry is None:
            unknown_by_layer[fill.layer].append(
                f"{fill.zone_source_id}:unsupported_exact_fill_geometry"
            )
            continue
        primitives.append(
            _primitive(
                source_id=fill.zone_source_id,
                source_kind="exact_filled_zone",
                net_name=fill.zone_net_name,
                layers=(fill.layer,),
                geometry=fill_geometry,
                authority_fingerprint=fill.final_fill_record_sha256,
            )
        )
    for reason in graph.unknown_zone_reasons:
        if reason.net_name in declared.net_names and reason.layer in declared.layers:
            all_source_ids.add(reason.zone_source_id)
            unknown_by_layer[reason.layer].append(f"{reason.zone_source_id}:{reason.reason}")
    if not declared.complete_pad_authority:
        missing = sorted(expected_nodes - seen_nodes)
        for layer in declared.layers:
            unknown_by_layer[layer].append("pad_authority_incomplete:" + fingerprint(missing))

    primitive_tuple = tuple(sorted(primitives, key=lambda item: item.primitive_id))
    if len({item.primitive_id for item in primitive_tuple}) != len(primitive_tuple):
        raise ValueError("derived per-source primitive identities must be unique")

    layer_records: list[SwitchNodeCopperLayerArea] = []
    witnesses: list[SwitchNodeCopperUnionWitness] = []
    for layer in declared.layers:
        area, layer_witnesses = _evaluate_layer_union(
            layer, primitive_tuple, unknown_by_layer[layer]
        )
        layer_records.append(area)
        witnesses.extend(layer_witnesses)
    per_layer_areas = tuple(sorted(layer_records, key=lambda item: item.layer))
    witness_tuple = tuple(sorted(witnesses, key=lambda item: item.witness_id))
    if len({item.witness_id for item in witness_tuple}) != len(witness_tuple):
        raise ValueError("derived copper-union witness identities are not unique")
    unknown_tuple = tuple(
        sorted({reason for item in per_layer_areas for reason in item.unknown_reasons})
    )
    verification = (
        SemanticVerification.EXACT if not unknown_tuple else SemanticVerification.UNSUPPORTED
    )
    rational_result = (
        _rat(
            sum(
                (
                    item.rational_mm2.fraction()
                    for item in per_layer_areas
                    if item.rational_mm2 is not None
                ),
                Fraction(0),
            )
        )
        if not unknown_tuple
        else None
    )
    pi_result = (
        _rat(
            sum(
                (
                    item.pi_coefficient_mm2.fraction()
                    for item in per_layer_areas
                    if item.pi_coefficient_mm2 is not None
                ),
                Fraction(0),
            )
        )
        if not unknown_tuple
        else None
    )
    source_coverage = tuple(sorted(all_source_ids))
    evidence_fp = fingerprint(
        {
            "declaration": declared.model_dump(mode="json"),
            "pads": [item.model_dump(mode="json") for item in pads],
            "primitives": [item.model_dump(mode="json") for item in primitive_tuple],
            "witnesses": [item.model_dump(mode="json") for item in witness_tuple],
            "per_layer_areas": [item.model_dump(mode="json") for item in per_layer_areas],
            "verification": verification.value,
            "rational_mm2": None
            if rational_result is None
            else rational_result.model_dump(mode="json"),
            "pi_coefficient_mm2": None if pi_result is None else pi_result.model_dump(mode="json"),
            "unknown_reasons": unknown_tuple,
            "source_coverage_ids": source_coverage,
        }
    )
    return {
        "placed_pad_copper": pads,
        "primitives": primitive_tuple,
        "witnesses": witness_tuple,
        "per_layer_areas": per_layer_areas,
        "verification": verification,
        "rational_mm2": rational_result,
        "pi_coefficient_mm2": pi_result,
        "unknown_reasons": unknown_tuple,
        "source_coverage_ids": source_coverage,
        "evidence_fingerprint": evidence_fp,
    }


def build_switch_node_copper_union(
    graph: RoutedCopperGraphResult,
    declaration: SwitchNodeCopperDeclaration,
    placed_pad_copper: Sequence[ExactPlacedPadCopper],
) -> SwitchNodeCopperUnionResult:
    derived = rederive_switch_node_copper_union(graph, declaration, placed_pad_copper)
    fields = {"graph": graph, "declaration": declaration, **derived}
    provisional = SwitchNodeCopperUnionResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return SwitchNodeCopperUnionResult(**fields, result_fingerprint=result_fp)
