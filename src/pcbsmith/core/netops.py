from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Symbol
from pcbsmith.core.schematic import Schematic

PinRef = tuple[str, str]
Anchor = tuple[int, int]
Segment = tuple[Anchor, Anchor]


class NetlistDerivationError(ValueError):
    """Raised when a schematic cannot be safely converted to a netlist."""


class Net(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    pins: frozenset[PinRef]


class Netlist(BaseModel):
    model_config = ConfigDict(frozen=True)

    nets: tuple[Net, ...]

    def net_by_name(self, name: str) -> Net:
        for net in self.nets:
            if net.name == name:
                return net
        raise KeyError(name)


@dataclass
class UnionFind:
    parent: dict[Hashable, Hashable]
    rank: dict[Hashable, int]

    def __init__(self) -> None:
        self.parent = {}
        self.rank = {}

    def add(self, item: Hashable) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0

    def find(self, item: Hashable) -> Hashable:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: Hashable, right: Hashable) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            self.parent[left_root] = right_root
        elif self.rank[left_root] > self.rank[right_root]:
            self.parent[right_root] = left_root
        else:
            self.parent[right_root] = left_root
            self.rank[left_root] += 1


def _anchor(point: Point) -> Anchor:
    return (point.x, point.y)


def _rotate_offset(point: Point, rotation_deg: int) -> Anchor:
    rotation = rotation_deg % 360
    if rotation == 0:
        return (point.x, point.y)
    if rotation == 90:
        return (-point.y, point.x)
    if rotation == 180:
        return (-point.x, -point.y)
    if rotation == 270:
        return (point.y, -point.x)
    msg = (
        f"Unsupported symbol rotation {rotation_deg}; "
        "expected one of 0, 90, 180, or 270 degrees"
    )
    raise NetlistDerivationError(msg)


def _pin_tip(
    instance_position: Point,
    pin_position: Point,
    rotation_deg: int,
) -> Anchor:
    pin_x, pin_y = _rotate_offset(pin_position, rotation_deg)
    return (instance_position.x + pin_x, instance_position.y + pin_y)


def _point_on_segment(point: Anchor, start: Anchor, end: Anchor) -> bool:
    px, py = point
    sx, sy = start
    ex, ey = end
    cross = (px - sx) * (ey - sy) - (py - sy) * (ex - sx)
    if cross != 0:
        return False
    return min(sx, ex) <= px <= max(sx, ex) and min(sy, ey) <= py <= max(sy, ey)


def derive_netlist(schematic: Schematic, symbols: dict[str, Symbol]) -> Netlist:
    uf = UnionFind()
    pin_at_anchor: dict[Anchor, list[PinRef]] = defaultdict(list)
    label_at_anchor: dict[Anchor, list[str]] = defaultdict(list)
    conductor_anchors: set[Anchor] = set()
    wire_segments: list[Segment] = []
    wire_vertices: set[Anchor] = set()

    for instance in schematic.symbols:
        symbol = symbols[instance.symbol_id]
        for pin in symbol.pins:
            anchor = _pin_tip(instance.position, pin.position, instance.rotation_deg)
            uf.add(anchor)
            pin_at_anchor[anchor].append((instance.reference, pin.number))

    for wire in schematic.wires:
        wire_anchors = [_anchor(point) for point in wire.points]
        conductor_anchors.update(wire_anchors)
        wire_vertices.update(wire_anchors)
        for anchor in wire_anchors:
            uf.add(anchor)
        for start, end in zip(wire_anchors, wire_anchors[1:], strict=False):
            wire_segments.append((start, end))
            uf.union(start, end)

    for anchor in wire_vertices:
        for start, end in wire_segments:
            if _point_on_segment(anchor, start, end):
                uf.union(anchor, start)

    for pin_anchor in pin_at_anchor:
        for start, end in wire_segments:
            if _point_on_segment(pin_anchor, start, end):
                uf.union(start, pin_anchor)

    for junction in schematic.junctions:
        anchor = _anchor(junction.position)
        conductor_anchors.add(anchor)
        uf.add(anchor)
        for start, end in wire_segments:
            if _point_on_segment(anchor, start, end):
                uf.union(anchor, start)

    for label in schematic.labels:
        anchor = _anchor(label.position)
        conductor_anchors.add(anchor)
        uf.add(anchor)
        label_at_anchor[anchor].append(label.name)
        for start, end in wire_segments:
            if _point_on_segment(anchor, start, end):
                uf.union(anchor, start)

    grouped_pins: dict[Hashable, set[PinRef]] = defaultdict(set)
    grouped_names: dict[Hashable, list[str]] = defaultdict(list)
    for anchor, anchor_pins in pin_at_anchor.items():
        grouped_pins[uf.find(anchor)].update(anchor_pins)
    for anchor, names in label_at_anchor.items():
        grouped_names[uf.find(anchor)].extend(names)

    conductor_roots = {uf.find(anchor) for anchor in conductor_anchors}

    labelled_pins: dict[str, set[PinRef]] = defaultdict(set)
    nets: list[Net] = []
    unnamed_index = 1
    for _root, net_names in grouped_names.items():
        distinct_names = sorted(set(net_names))
        if len(distinct_names) > 1:
            labels = ", ".join(distinct_names)
            raise NetlistDerivationError(f"Conflicting net labels: {labels}")

    for root, net_pins in grouped_pins.items():
        if not net_pins:
            continue
        net_names = sorted(set(grouped_names.get(root, [])))
        if root not in conductor_roots and len(net_pins) == 1:
            continue
        if net_names:
            labelled_pins[net_names[0]].update(net_pins)
            continue
        nets.append(Net(name=f"N${unnamed_index}", pins=frozenset(net_pins)))
        unnamed_index += 1

    for name, net_pins in labelled_pins.items():
        nets.append(Net(name=name, pins=frozenset(net_pins)))

    return Netlist(nets=tuple(sorted(nets, key=lambda net: net.name)))
