"""Bind saved native plane topology to the routed graph, without plane path metrics."""

from __future__ import annotations

import hashlib
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from pcbsmith.copper_layers import CopperLayer
from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM, BoardLayout, BoardNetlist
from pcbsmith.kicad.copper_layers import saved_copper_layers
from pcbsmith.kicad.final_fill_adapter import KiCadFinalFillSnapshot, _parse_zone_intents
from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFinalFillConnectivityObservation,
    classify_final_fill_reachability,
)
from pcbsmith.kicad.library import _atom, _children, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.placement_readback import _net_name
from pcbsmith.routed_copper_graph_ir import (
    CopperTerminalAnchorBinding,
    NativeFilledCopperInput,
    fingerprint,
)

NodeKey = tuple[str, str, Decimal, Decimal]
ORIGIN = Decimal(str(BOARD_SHEET_ORIGIN_MM))


def retain_native_fill(
    board: Path, snapshot: KiCadFinalFillSnapshot, contacts: KiCadFinalFillConnectivityObservation
) -> NativeFilledCopperInput:
    result = NativeFilledCopperInput(
        board_text=board.read_bytes().decode("utf-8"),
        snapshot_json=snapshot.model_dump_json(),
        contacts_json=contacts.model_dump_json(),
    )
    read_native_fill(result)
    return result


def read_native_fill(
    evidence: NativeFilledCopperInput,
) -> tuple[KiCadFinalFillSnapshot, KiCadFinalFillConnectivityObservation]:
    snapshot = KiCadFinalFillSnapshot.model_validate_json(evidence.snapshot_json)
    contacts = KiCadFinalFillConnectivityObservation.model_validate_json(evidence.contacts_json)
    digest = hashlib.sha256(evidence.board_text.encode("utf-8")).hexdigest()
    if digest != snapshot.filled_board_sha256 or digest != contacts.board_sha256:
        raise ValueError("native plane evidence targets another saved board")
    if snapshot.stale_fill or not snapshot.refilled_by_kicad or not snapshot.zone_intent_unchanged:
        raise ValueError("native plane graph requires unchanged, fresh native fill")
    if contacts.region_contact_graph is None:
        raise ValueError("native plane graph requires a complete native contact inventory")
    tree = parse_sexpr(evidence.board_text)
    actual_zones = _parse_zone_intents(tree)
    if actual_zones != snapshot.zones:
        raise ValueError("native plane snapshot differs from saved zone intent")
    actual_regions = {
        f"{zone.zone_id}:filled:{index}": serialize_sexpr(polygon)
        for zone, node in zip(actual_zones, _children(tree, "zone"), strict=True)
        for index, polygon in enumerate(_children(node, "filled_polygon"))
    }
    if actual_regions != {r.region_id: r.canonical_filled_polygon_sexpr for r in snapshot.regions}:
        raise ValueError("native plane snapshot differs from saved filled polygons")
    if {z.zone_id for z in snapshot.zones} != {r.zone_id for r in snapshot.regions}:
        raise ValueError("native plane graph has a zone without final filled copper")
    # This replays exact region identities and the whole contact graph; no source is inferred.
    classify_final_fill_reachability(snapshot, contacts, declared_source_pad_ids=())
    return snapshot, contacts


def _child(node: Any, name: str) -> Any:
    found = _children(node, name)
    if len(found) != 1:
        raise ValueError(f"native plane binding requires one {name} field")
    return found[0]


def _point(node: Any, name: str) -> tuple[Decimal, Decimal]:
    field = _child(node, name)
    return Decimal(_atom(field[1])) - ORIGIN, Decimal(_atom(field[2])) - ORIGIN


def _net(node: Any, names: dict[str, str]) -> str:
    value = _net_name(_child(node, "net"), names)
    if not value:
        raise ValueError("native conductor has no resolved net name")
    return value


def _item_points(
    text: str,
    layout: BoardLayout,
    netlist: BoardNetlist,
    anchors: tuple[CopperTerminalAnchorBinding, ...],
    layers: tuple[CopperLayer, ...],
) -> dict[str, dict[str, NodeKey]]:
    from pcbsmith.production_decoupling import native_terminal_anchors_from_text

    tree = parse_sexpr(text)
    if saved_copper_layers(tree) != layers:
        raise ValueError("native plane stack differs from routed graph")
    if (
        tuple(sorted(native_terminal_anchors_from_text(text, netlist), key=lambda a: a.anchor_id))
        != anchors
    ):
        raise ValueError("native plane terminal geometry differs from graph anchors")
    if _children(tree, "arc"):
        raise ValueError("native plane graph does not qualify arc path metrics")
    names = {_atom(n[1]): _atom(n[2]) for n in _children(tree, "net") if len(n) >= 3}
    items: dict[str, dict[str, NodeKey]] = {}
    tracks = set()
    for node in _children(tree, "segment"):
        net, layer = _net(node, names), _atom(_child(node, "layer")[1])
        a, b = _point(node, "start"), _point(node, "end")
        width = Decimal(_atom(_child(node, "width")[1]))
        tracks.add((net, layer, tuple(sorted((a, b))), width))
        items["PCB_TRACK:" + _atom(_child(node, "uuid")[1])] = {layer: (net, layer, *a)}
    expected_tracks = {
        (
            s.net_name,
            s.layer,
            tuple(
                sorted(
                    (
                        (Decimal(str(s.x1)), Decimal(str(s.y1))),
                        (Decimal(str(s.x2)), Decimal(str(s.y2))),
                    )
                )
            ),
            Decimal(str(s.width_mm)),
        )
        for s in layout.segments
    }
    if tracks != expected_tracks or len(tracks) != len(_children(tree, "segment")):
        raise ValueError("native plane track inventory differs from routed layout")
    vias = set()
    for node in _children(tree, "via"):
        net = _net(node, names)
        point = _point(node, "at")
        vias.add(
            (
                net,
                point,
                Decimal(_atom(_child(node, "size")[1])),
                Decimal(_atom(_child(node, "drill")[1])),
            )
        )
        if tuple(_atom(v) for v in _child(node, "layers")[1:]) != ("F.Cu", "B.Cu"):
            raise ValueError("native plane graph supports ordinary through vias only")
        items["PCB_VIA:" + _atom(_child(node, "uuid")[1])] = {
            layer: (net, layer, *point) for layer in layers
        }
    expected_vias = {
        (
            v.net_name,
            (Decimal(str(v.x)), Decimal(str(v.y))),
            Decimal(str(v.size_mm)),
            Decimal(str(v.drill_mm)),
        )
        for v in layout.vias
    }
    if vias != expected_vias or len(vias) != len(_children(tree, "via")):
        raise ValueError("native plane via inventory differs from routed layout")
    by_id = {a.anchor_id: a for a in anchors}
    counts: dict[tuple[str, str], int] = {}
    for fp in _children(tree, "footprint"):
        props = {_atom(p[1]): _atom(p[2]) for p in _children(fp, "property")}
        for pad in _children(fp, "pad"):
            if _atom(pad[2]) == "np_thru_hole" or not _children(pad, "net"):
                continue
            key = props["Reference"], _atom(pad[1])
            number = counts.get(key, 0) + 1
            counts[key] = number
            suffix = "" if number == 1 else f":instance-{number}"
            anchor = by_id.get(f"pad:{key[0]}:{key[1]}" + suffix)
            if anchor is None:
                raise ValueError("native plane pad is absent from terminal inventory")
            span = layers if anchor.through_hole_diameter_mm is not None else (anchor.layer,)
            items["pad:" + _atom(_child(pad, "uuid")[1])] = {
                layer: (anchor.net_name, layer, anchor.x_mm, anchor.y_mm) for layer in span
            }
    return items


def native_fill_graph_edges(
    evidence: NativeFilledCopperInput,
    layout: BoardLayout,
    netlist: BoardNetlist,
    anchors: tuple[CopperTerminalAnchorBinding, ...],
    layers: tuple[CopperLayer, ...],
) -> tuple[set[NodeKey], list[Any]]:
    """Return topology-only edges; their endpoint coordinates are not a current path."""
    snapshot, contacts = read_native_fill(evidence)
    graph = contacts.region_contact_graph
    assert graph is not None
    if len(snapshot.zones) != len(layout.zones):
        raise ValueError("native plane inventory differs from routed layout")
    expected_zones = []
    for net, layer, bounds in layout.zones:
        left, top, right, bottom = (Decimal(str(v)) + ORIGIN for v in bounds)
        expected_zones.append(
            (net, layer, frozenset(((left, top), (right, top), (right, bottom), (left, bottom))))
        )
    if any(
        len(z.outline_point_loops) != 1 or len(z.outline_point_loops[0]) != 4
        for z in snapshot.zones
    ):
        raise ValueError("native plane graph requires rectangular zone intent")
    actual_zones = [
        (z.net_name, z.layer, frozenset((p.x_mm, p.y_mm) for p in z.outline_point_loops[0]))
        for z in snapshot.zones
    ]
    if Counter(expected_zones) != Counter(actual_zones):
        raise ValueError("native plane net/layer/outline differs from routed layout")
    items = _item_points(evidence.board_text, layout, netlist, anchors, layers)
    components = {i: c for c in graph.item_components for i in c.item_ids}
    if set(components) != set(items):
        raise ValueError("native plane contact inventory omits or invents copper items")
    for identity, component in components.items():
        if any(point[0] != component.net_name for point in items[identity].values()):
            raise ValueError("native plane component crosses saved net identity")
    digest = fingerprint(contacts.model_dump(mode="json"))
    points: dict[str, NodeKey] = {}
    keys: set[NodeKey] = set()
    edges: list[Any] = []

    def connect(source: str, a: NodeKey, b: NodeKey) -> None:
        if a == b:
            return
        key = fingerprint([source, a, b, digest])
        edges.append(
            ("native-fill-edge:" + key, source, "exact_zone_fill", a, b, None, None, digest)
        )
        keys.update((a, b))

    for region in contacts.records:
        assert region.outline_nm is not None
        x, y = region.outline_nm[0]
        centre = (
            region.net_name,
            region.layer,
            Decimal(x) / 1_000_000 - ORIGIN,
            Decimal(y) / 1_000_000 - ORIGIN,
        )
        points[region.region_id] = centre
        keys.add(centre)
        # Full native item components also cover width-based contacts that an
        # endpoint/centreline graph cannot infer. These edges stay non-metric.
        connected = {i for direct in region.direct_contact_ids for i in components[direct].item_ids}
        for identity in sorted(connected):
            candidates = items[identity]
            target = candidates.get(region.layer, next(iter(candidates.values())))
            connect(region.region_id + ":" + identity, centre, target)
    for a, b in graph.region_contacts:
        connect("native-zone-contact:" + fingerprint([a, b]), points[a], points[b])
    return keys, edges


__all__ = ["retain_native_fill", "read_native_fill", "native_fill_graph_edges"]
