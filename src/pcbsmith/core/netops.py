from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Hashable

from pydantic import BaseModel, ConfigDict

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Symbol
from pcbsmith.core.schematic import Schematic

PinRef = tuple[str, str]
Anchor = tuple[int, int]


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


def _pin_tip(instance_position: Point, pin_position: Point) -> Anchor:
    return (instance_position.x + pin_position.x, instance_position.y + pin_position.y)


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
    label_at_anchor: dict[Anchor, str] = {}

    for instance in schematic.symbols:
        symbol = symbols[instance.symbol_id]
        for pin in symbol.pins:
            anchor = _pin_tip(instance.position, pin.position)
            uf.add(anchor)
            pin_at_anchor[anchor].append((instance.reference, pin.number))

    for wire in schematic.wires:
        wire_anchors = [_anchor(point) for point in wire.points]
        for anchor in wire_anchors:
            uf.add(anchor)
        for start, end in zip(wire_anchors, wire_anchors[1:]):
            uf.union(start, end)
            for pin_anchor in pin_at_anchor:
                if _point_on_segment(pin_anchor, start, end):
                    uf.union(start, pin_anchor)

    for junction in schematic.junctions:
        anchor = _anchor(junction.position)
        uf.add(anchor)
        for wire in schematic.wires:
            wire_anchors = [_anchor(point) for point in wire.points]
            for start, end in zip(wire_anchors, wire_anchors[1:]):
                if _point_on_segment(anchor, start, end):
                    uf.union(anchor, start)

    for label in schematic.labels:
        anchor = _anchor(label.position)
        uf.add(anchor)
        label_at_anchor[anchor] = label.name
        for wire in schematic.wires:
            wire_anchors = [_anchor(point) for point in wire.points]
            for start, end in zip(wire_anchors, wire_anchors[1:]):
                if _point_on_segment(anchor, start, end):
                    uf.union(anchor, start)

    grouped_pins: dict[Hashable, set[PinRef]] = defaultdict(set)
    grouped_names: dict[Hashable, list[str]] = defaultdict(list)
    for anchor, pins in pin_at_anchor.items():
        grouped_pins[uf.find(anchor)].update(pins)
    for anchor, name in label_at_anchor.items():
        grouped_names[uf.find(anchor)].append(name)

    nets: list[Net] = []
    unnamed_index = 1
    for root, pins in grouped_pins.items():
        if not pins:
            continue
        names = sorted(set(grouped_names.get(root, [])))
        name = names[0] if names else f"N${unnamed_index}"
        if not names:
            unnamed_index += 1
        nets.append(Net(name=name, pins=frozenset(pins)))

    return Netlist(nets=tuple(sorted(nets, key=lambda net: net.name)))
