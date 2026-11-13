"""Single-sheet functional presentation, compiled against real native pin positions.

This is a pure schematic renderer, not a circuit designer or PCB routing owner.
Wiring is explicit; the existing native netlist closure remains authoritative.
"""

from __future__ import annotations

import json
import math
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.kicad.export_divider_highpass_led import _label, _wire
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import _children, parse_sexpr, serialize_sexpr

Position = tuple[float, float]
Terminal = tuple[str, str]
Point = tuple[int, int]


class _Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SchematicBlock(_Intent):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    members: tuple[str, ...] = Field(min_length=1)
    bounds_mm: tuple[float, float, float, float]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        x1, y1, x2, y2 = self.bounds_mm
        if not (10 <= x1 < x2 <= 410 and 30 <= y1 < y2 <= 270):
            raise ValueError("Blocks must fit the usable A3 sheet (10,30)-(410,270)")
        if x2 - x1 < 35 or y2 - y1 < 35:
            raise ValueError("Block is too small for its title, explanation and circuit")
        if not self.title.strip() or not self.explanation.strip() or "\n" in self.title:
            raise ValueError("Provide a single-line title and a nonblank explanation")
        if len(set(self.members)) != len(self.members):
            raise ValueError("Duplicate block member")
        if len(self.title) * 1.5 > x2 - x1 - 5.08:
            raise ValueError("Block title exceeds available width")
        return self


class SchematicWire(_Intent):
    start: Terminal
    end: Terminal
    via_mm: tuple[Position, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.start == self.end:
            raise ValueError("Wire endpoints must be different terminals")
        for point in self.via_mm:
            if any(abs(v / 1.27 - round(v / 1.27)) > 1e-7 for v in point):
                raise ValueError("Schematic wire waypoints must use the 1.27 mm grid")
        return self


class SchematicPresentation(_Intent):
    blocks: tuple[SchematicBlock, ...] = Field(min_length=1)
    wires: tuple[SchematicWire, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Duplicate schematic block id")
        members = [ref for b in self.blocks for ref in b.members]
        if len(set(members)) != len(members):
            raise ValueError("Each component must belong to exactly one block")
        for a, b in combinations(self.blocks, 2):
            ax, ay, bx, by = a.bounds_mm
            cx, cy, dx, dy = b.bounds_mm
            if max(ax, cx) <= min(bx, dx) and max(ay, cy) <= min(by, dy):
                raise ValueError("Schematic blocks must not overlap or touch")
        return self


@dataclass(frozen=True)
class PlacedPin:
    at: Position
    stub_end: Position
    net: str | None


@dataclass(frozen=True)
class CompiledPresentation:
    items: tuple[str, ...]
    power_anchors: dict[str, Position]


def placed_pin(
    origin: Position, offset: Position, pin_angle: float, rotation: int, net: str | None
) -> PlacedPin:
    """KiCad symbol Y is up; sheet Y is down. Rotate in symbol coordinates."""
    angle = math.radians(rotation)
    x, y = offset
    at = (
        round(origin[0] + x * math.cos(angle) - y * math.sin(angle), 5),
        round(origin[1] - x * math.sin(angle) - y * math.cos(angle), 5),
    )
    direction = math.radians(pin_angle + rotation)
    return PlacedPin(
        at,
        (
            round(at[0] - 5.08 * math.cos(direction), 5),
            round(at[1] + 5.08 * math.sin(direction), 5),
        ),
        net,
    )


def _point(position: Position) -> Point:
    return round(position[0] * 100_000), round(position[1] * 100_000)


def _mm(point: Point) -> Position:
    return point[0] / 100_000, point[1] / 100_000


def _on(point: Point, a: Point, b: Point) -> bool:
    return min(a[0], b[0]) <= point[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= point[1] <= max(
        a[1], b[1]
    )


def _intersections(a: Point, b: Point, c: Point, d: Point) -> set[Point]:
    # All segments are orthogonal. Collinear overlaps return their boundaries.
    if (a[0] == b[0]) == (c[0] == d[0]):
        return {p for p in (a, b, c, d) if _on(p, a, b) and _on(p, c, d)}
    p = (a[0], c[1]) if a[0] == b[0] else (c[0], a[1])
    return {p} if _on(p, a, b) and _on(p, c, d) else set()


def _notes(block: SchematicBlock) -> tuple[str, float]:
    width = min(72, int((block.bounds_mm[2] - block.bounds_mm[0] - 5.08) / 1.2))
    lines = [
        line
        for paragraph in block.explanation.splitlines()
        for line in (textwrap.wrap(paragraph, width=width) or [""])
    ]
    return "\n".join(lines), block.bounds_mm[1] + 9 + len(lines) * 3.0


def compile_presentation(
    presentation: SchematicPresentation,
    pins: dict[Terminal, PlacedPin],
    component_positions: dict[str, Position],
    *,
    identity: str,
    page_notes_bottom: float = 25,
) -> CompiledPresentation:
    """Reject ambiguity before writing any project files; emit actual KiCad wires.

    Deliberately conservative: different-net wire crossings are unsupported in
    this first slice, even when KiCad could represent a crossing without a dot.
    """
    membership = {ref: b for b in presentation.blocks for ref in b.members}
    if set(membership) != set(component_positions):
        raise ValueError("Block membership must cover exactly the project components")
    for block in presentation.blocks:
        if block.bounds_mm[1] <= page_notes_bottom:
            raise ValueError("Block overlaps the page title/notes")
        _, bottom = _notes(block)
        for ref in block.members:
            x, y = component_positions[ref]
            x1, _, x2, y2 = block.bounds_mm
            if not (x1 + 5.08 <= x <= x2 - 5.08 and bottom + 12.7 <= y <= y2 - 5.08):
                raise ValueError(f"{ref}: component overlaps block annotations or boundary")

    segments: list[tuple[str, Point, Point]] = []
    wired: set[Terminal] = set()

    def add_path(net: str, points: tuple[Position, ...], block: SchematicBlock) -> None:
        x1, _, x2, y2 = block.bounds_mm
        _, bottom = _notes(block)
        for x, y in points:
            if not (x1 + 1.27 <= x <= x2 - 1.27 and bottom <= y <= y2 - 1.27):
                raise ValueError(f"{block.id}: wiring overlaps annotations or leaves its block")
        for a, b in zip(points, points[1:], strict=False):
            p, q = _point(a), _point(b)
            if p == q or (p[0] != q[0] and p[1] != q[1]):
                raise ValueError("Schematic paths require nonzero orthogonal segments")
            segments.append((net, p, q))

    for wire in presentation.wires:
        if wire.start not in pins or wire.end not in pins:
            raise ValueError("Schematic wire refers to an unknown terminal")
        start, end = pins[wire.start], pins[wire.end]
        if start.net is None or start.net != end.net:
            raise ValueError("Schematic wire must join declared terminals on the same net")
        block = membership[wire.start[0]]
        if block != membership[wire.end[0]]:
            raise ValueError("Use net labels for interfaces between functional blocks")
        path = (start.at, *wire.via_mm, end.at)
        add_path(start.net, path, block)
        for pin, neighbor in ((start, path[1]), (end, path[-2])):
            outward = (pin.stub_end[0] - pin.at[0], pin.stub_end[1] - pin.at[1])
            step = (neighbor[0] - pin.at[0], neighbor[1] - pin.at[1])
            if sum(a * b for a, b in zip(outward, step, strict=True)) <= 0:
                raise ValueError("Wires must leave terminals in the pin's outward direction")
        wired.update((wire.start, wire.end))

    for terminal, pin in pins.items():
        if terminal not in wired and pin.net is not None:
            add_path(pin.net, (pin.at, pin.stub_end), membership[terminal[0]])

    # Split at pins and same-net intersections so T branches get real junctions.
    cuts = [{a, b} for _, a, b in segments]
    for i, (net, a, b) in enumerate(segments):
        for terminal, pin in pins.items():
            point = _point(pin.at)
            if _on(point, a, b):
                if pin.net != net:
                    raise ValueError(f"Wire contacts a different net or NC pin: {terminal}")
                cuts[i].add(point)
        for j in range(i):
            other, c, d = segments[j]
            crossings = _intersections(a, b, c, d)
            if crossings and net != other:
                raise ValueError(f"Different-net schematic wires cross or touch: {net}, {other}")
            cuts[i].update(crossings)
            cuts[j].update(crossings)

    edges: set[tuple[str, Point, Point]] = set()
    graph: dict[tuple[str, Point], set[Point]] = defaultdict(set)
    for (net, _, _), points in zip(segments, cuts, strict=True):
        ordered = sorted(points)
        for a, b in zip(ordered, ordered[1:], strict=False):
            edges.add((net, a, b))
            graph[net, a].add(b)
            graph[net, b].add(a)

    clusters: dict[tuple[str, Point], int] = {}
    roots: list[tuple[str, Point]] = []
    for key in sorted(graph):
        if key in clusters:
            continue
        roots.append(key)
        pending = [key]
        while pending:
            node = pending.pop()
            if node in clusters:
                continue
            clusters[node] = len(roots) - 1
            pending.extend((node[0], p) for p in graph[node] if (node[0], p) not in clusters)

    local_clusters: dict[tuple[str, str], set[int]] = defaultdict(set)
    for terminal, pin in pins.items():
        if pin.net is not None:
            local_clusters[membership[terminal[0]].id, pin.net].add(
                clusters[pin.net, _point(pin.at)]
            )
    if any(len(groups) != 1 for groups in local_clusters.values()):
        raise ValueError("Same-net pins within a block must have connected local wiring")

    items = [_wire(_mm(a), _mm(b)) for _, a, b in sorted(edges)]
    anchors: dict[str, Position] = {}
    pin_points = {_point(pin.at) for pin in pins.values()}
    for index, (net, _root) in enumerate(roots):
        # A stub must terminate at its label, not leave a dangling tail beyond
        # a label placed on the pin. KiCad ERC checks this separately from nets.
        endpoints = sorted(
            point
            for (name, point), neighbors in graph.items()
            if name == net
            and clusters[name, point] == index
            and len(neighbors) == 1
            and point not in pin_points
        )
        candidates = {
            point for (name, point) in graph if name == net and clusters[name, point] == index
        }
        for name, a, b in edges:
            if name == net and clusters[name, a] == index:
                midpoint = tuple(
                    round((v + w) / 2 / 127_000) * 127_000 for v, w in zip(a, b, strict=True)
                )
                candidate = (midpoint[0], midpoint[1])
                if _on(candidate, a, b):
                    candidates.add(candidate)
        # Prefer open wire space over placing net text on a component pin/body.
        label_point = max(
            sorted(candidates),
            key=lambda p: min((p[0] - pin[0]) ** 2 + (p[1] - pin[1]) ** 2 for pin in pin_points),
        )
        for point in endpoints or [label_point]:
            label = parse_sexpr(_label(net, *_mm(point)))
            _children(label, "effects")[0].append(["justify", "left", "bottom"])
            items.append(serialize_sexpr(label))
            anchors.setdefault(net, _mm(point))
    for (net, point), neighbors in sorted(graph.items()):
        if len(neighbors) >= 3:
            x, y = _mm(point)
            uid = stable_kicad_uuid(identity, "junction", net, str(point))
            items.append(f'(junction (at {x:g} {y:g}) (diameter 0) (color 0 0 0 0) (uuid "{uid}"))')

    for block in presentation.blocks:
        x1, y1, x2, y2 = block.bounds_mm
        uid = stable_kicad_uuid(identity, "block", block.id)
        items.append(
            f"(polyline (pts (xy {x1:g} {y1:g}) (xy {x2:g} {y1:g}) "
            f"(xy {x2:g} {y2:g}) (xy {x1:g} {y2:g}) (xy {x1:g} {y1:g})) "
            f'(stroke (width 0.254) (type default)) (fill (type none)) (uuid "{uid}"))'
        )
        for role, text, y, size in (
            ("title", block.title, y1 + 2.54, 2.0),
            ("explanation", _notes(block)[0], y1 + 7.62, 1.5),
        ):
            uid = stable_kicad_uuid(identity, "block", block.id, role)
            items.append(
                f"(text {json.dumps(text, ensure_ascii=False)} (at {x1 + 2.54:g} {y:g} 0) "
                f"(effects (font (size {size} {size})) (justify left top)) "
                f'(uuid "{uid}"))'
            )
    return CompiledPresentation(tuple(items), anchors)
