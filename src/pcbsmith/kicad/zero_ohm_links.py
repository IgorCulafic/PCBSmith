"""Source-bound zero-ohm crossover insertion for the native revision owner.

Only two-pad SMD resistor templates and flat, label-connected schematics are
supported. Copper is partitioned geometrically and the schematic is updated
from the resulting pad membership. Native ERC/DRC remains mandatory.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from pcbsmith.kicad.library import QuotedString as Q
from pcbsmith.kicad.library import SExpr, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.native_edits import atom, child, children, reference
from pcbsmith.semantic_ir import SemanticIrModel


class ZeroOhmLink(SemanticIrModel):
    reference: str = Field(pattern=r"^R[1-9][0-9]*$")
    template_reference: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    position_mm: tuple[float, float]
    axis_screen_deg: float
    schematic_position_mm: tuple[float, float]
    keep_pad: tuple[str, str]


def _number(value: SExpr) -> float:
    return float(atom(value))


def _num(v: float) -> str:
    if not math.isfinite(v):
        raise ValueError("Non-finite jumper geometry")
    return f"{v:.6f}".rstrip("0").rstrip(".") or "0"


def _walk(n: SExpr) -> Iterator[list[SExpr]]:
    if isinstance(n, list):
        yield n
        for c in n[1:]:
            yield from _walk(c)


def _ids(n: list[SExpr], seed: str) -> None:
    for i, c in enumerate(_walk(n)):
        if c and c[0] == "uuid":
            c[1] = Q(str(uuid5(NAMESPACE_URL, seed + str(i))))


def _property(n: list[SExpr], key: str, value: str) -> None:
    matches = [p for p in children(n, "property") if atom(p[1]) == key]
    if matches:
        matches[0][2] = Q(value)


def pad_geometry(fp: list[SExpr], p: list[SExpr]) -> BaseGeometry:
    at = child(fp, "at")
    pa = child(p, "at")
    x, y = map(_number, at[1:3])
    px, py = map(_number, pa[1:3])
    a = math.radians(-_number(at[3]) if len(at) > 3 else 0)
    center = (x + px * math.cos(a) - py * math.sin(a), y + px * math.sin(a) + py * math.cos(a))
    w, h = map(_number, child(p, "size")[1:3])
    if atom(p[3]) not in {"rect", "roundrect"}:
        raise ValueError("Crossover partition requires rectangular SMD pads")
    r = min(w, h) * _number(child(p, "roundrect_rratio")[1]) if atom(p[3]) == "roundrect" else 0
    g = (
        box(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r).buffer(r)
        if r
        else box(-w / 2, -h / 2, w / 2, h / 2)
    )
    return translate(rotate(g, -_number(pa[3]) if len(pa) > 3 else 0, origin=(0, 0)), *center)


def _schematic_labels(tree: list[SExpr]) -> dict[tuple[str, str], list[list[SExpr]]]:
    """Resolve flat 0-degree symbol pins through their actual wire graph."""
    wires = children(tree, "wire")
    labels = children(tree, "label")
    libs = {atom(s[1]): s for s in children(child(tree, "lib_symbols"), "symbol")}
    result = {}
    for symbol in children(tree, "symbol"):
        at = child(symbol, "at")
        if _number(at[3]) != 0:
            raise ValueError("Crossover schematic adapter requires zero-degree symbols")
        ref = reference(symbol)
        lib = libs[atom(child(symbol, "lib_id")[1])]
        for pin in [p for unit in children(lib, "symbol") for p in children(unit, "pin")]:
            p = child(pin, "at")
            point = Point(_number(at[1]) + _number(p[1]), _number(at[2]) - _number(p[2]))
            connected = {
                i
                for i, w in enumerate(wires)
                if LineString(
                    [tuple(map(_number, q[1:3])) for q in children(child(w, "pts"), "xy")]
                ).distance(point)
                < 1e-5
            }
            # Label stubs may comprise several segments; join by shared geometry.
            for _ in range(len(wires)):
                old = set(connected)
                for i, w in enumerate(wires):
                    g = LineString(
                        [tuple(map(_number, q[1:3])) for q in children(child(w, "pts"), "xy")]
                    )
                    if any(
                        g.distance(
                            LineString(
                                [
                                    tuple(map(_number, q[1:3]))
                                    for q in children(child(wires[j], "pts"), "xy")
                                ]
                            )
                        )
                        < 1e-5
                        for j in old
                    ):
                        connected.add(i)
                if connected == old:
                    break
            found = [
                label
                for label in labels
                if any(
                    LineString(
                        [
                            tuple(map(_number, q[1:3]))
                            for q in children(child(wires[j], "pts"), "xy")
                        ]
                    ).distance(Point(*map(_number, child(label, "at")[1:3])))
                    < 1e-5
                    for j in connected
                )
            ]
            if found:
                result[(str(ref), atom(child(pin, "number")[1]))] = found
    return result


def plan_zero_ohm_links(
    source: Path, payload: bytes, links: tuple[ZeroOhmLink, ...]
) -> tuple[bytes, dict[str, bytes], list[dict[str, Any]]]:
    tree = parse_sexpr(payload.decode())
    sch = parse_sexpr(source.with_suffix(".kicad_sch").read_text(encoding="utf-8"))
    if children(tree, "via") or children(tree, "arc") or children(tree, "zone"):
        raise ValueError("Crossover insertion supports front-only straight copper without zones")
    fps = {reference(f): f for f in children(tree, "footprint")}
    symbols = {reference(s): s for s in children(sch, "symbol")}
    label_map = _schematic_labels(sch)
    made = []
    for link in links:
        if link.reference in fps or link.reference in symbols:
            raise ValueError("Jumper reference already exists")
        template = fps[link.template_reference]
        fp = copy.deepcopy(template)
        pads = children(fp, "pad")
        if (
            len(pads) != 2
            or {atom(p[1]) for p in pads} != {"1", "2"}
            or any(atom(p[2]) != "smd" for p in pads)
        ):
            raise ValueError("Jumper template must have exactly two SMD pads")
        if atom(child(fp, "layer")[1]) != "F.Cu":
            raise ValueError("Jumper must use F.Cu")
        at = child(fp, "at")
        old_angle = _number(at[3]) if len(at) > 3 else 0
        angle = -link.axis_screen_deg
        for member in fp:
            if isinstance(member, list) and member and member[0] in {"pad", "property", "fp_text"}:
                for pa in children(member, "at"):
                    pa[3:] = [_num((_number(pa[3]) if len(pa) > 3 else 0) + angle - old_angle)]
        at[1:] = [*map(_num, link.position_mm), _num(angle)]
        _ids(fp, link.semantic_fingerprint() + "fp")
        _property(fp, "Reference", link.reference)
        _property(fp, "Value", "0R")
        _property(fp, "MPN", "1206 zero-ohm jumper")
        _property(fp, "Design_role", "crossover-link")
        for pad in pads:
            child(pad, "net")[1:] = [Q(link.net_name)]
        # Remove only the inline copper between the jumper lands.
        centers = [pad_geometry(fp, p).centroid for p in pads]
        axis = LineString([(p.x, p.y) for p in centers])
        hit = 0
        for seg in list(children(tree, "segment")):
            if atom(child(seg, "net")[1]) != link.net_name:
                continue
            a = tuple(map(_number, child(seg, "start")[1:3]))
            b = tuple(map(_number, child(seg, "end")[1:3]))
            line = LineString([a, b])
            if line.distance(Point(link.position_mm)) > 1e-5:
                continue
            if max(line.distance(p) for p in centers) > 1e-5:
                raise ValueError("Jumper pads must be inline with one existing segment")
            width = _number(child(seg, "width")[1])
            land_width = _number(child(pads[0], "size")[1])
            trim = max(0, (width - land_width) / 2)
            unit = (
                (centers[1].x - centers[0].x) / axis.length,
                (centers[1].y - centers[0].y) / axis.length,
            )
            cut = LineString(
                [
                    (centers[0].x - trim * unit[0], centers[0].y - trim * unit[1]),
                    (centers[1].x + trim * unit[0], centers[1].y + trim * unit[1]),
                ]
            ).buffer(1e-7, cap_style="flat")
            pieces = line.difference(cut)
            if not hasattr(pieces, "geoms") or len(pieces.geoms) != 2:
                raise ValueError("Jumper insertion must split one track into two")
            tree.remove(seg)
            for i, g in enumerate(pieces.geoms):
                s = copy.deepcopy(seg)
                _ids(s, link.semantic_fingerprint() + "segment" + str(i))
                child(s, "start")[1:] = list(map(_num, g.coords[0]))
                child(s, "end")[1:] = list(map(_num, g.coords[-1]))
                tree.append(s)
            hit += 1
        if hit != 1:
            raise ValueError("Jumper must split exactly one source segment")
        symbol = copy.deepcopy(symbols[link.template_reference])
        _ids(symbol, link.semantic_fingerprint() + "symbol")
        old = tuple(map(_number, child(symbol, "at")[1:3]))
        dx, dy = link.schematic_position_mm[0] - old[0], link.schematic_position_mm[1] - old[1]
        for n in _walk(symbol):
            if n and n[0] == "at":
                n[1:3] = [_num(_number(n[1]) + dx), _num(_number(n[2]) + dy)]
            if n and n[0] == "reference":
                n[1] = Q(link.reference)
        _property(symbol, "Reference", link.reference)
        _property(symbol, "Value", "0R")
        _property(symbol, "MPN", "1206 zero-ohm jumper")
        _property(symbol, "Design_role", "crossover-link")
        path = child(fp, "path")
        path[1] = Q("/" + atom(child(symbol, "uuid")[1]))
        tree.append(fp)
        sch.append(symbol)
        fps[link.reference] = fp
        symbols[link.reference] = symbol
        # Clone the template's actual two labelled wire stubs, preserving their geometry.
        for pin in ("1", "2"):
            templabels = label_map[(link.template_reference, pin)]
            if len(templabels) != 1:
                raise ValueError("Jumper template requires one label per pin")
            label = copy.deepcopy(templabels[0])
            la = child(label, "at")
            oldp = Point(*map(_number, la[1:3]))
            la[1:3] = [_num(_number(la[1]) + dx), _num(_number(la[2]) + dy)]
            _ids(label, link.semantic_fingerprint() + "label" + pin)
            sch.append(label)
            attached = [
                w
                for w in children(sch, "wire")
                if LineString(
                    [tuple(map(_number, q[1:3])) for q in children(child(w, "pts"), "xy")]
                ).distance(oldp)
                < 1e-5
            ]
            if len(attached) != 1:
                raise ValueError("Jumper template requires a single label stub")
            wire = copy.deepcopy(attached[0])
            _ids(wire, link.semantic_fingerprint() + "wire" + pin)
            for q in children(child(wire, "pts"), "xy"):
                q[1:3] = [_num(_number(q[1]) + dx), _num(_number(q[2]) + dy)]
            sch.append(wire)
            label_map[(link.reference, pin)] = [label]
        made.append(
            dict(reference=link.reference, position_mm=link.position_mm, source_net=link.net_name)
        )
    # Partition each split net, keeping its designated source terminal's net name.
    for net in sorted({link_item.net_name for link_item in links}):
        items: list[tuple[BaseGeometry, list[SExpr], tuple[str, str] | None]] = []
        for fp in children(tree, "footprint"):
            for p in children(fp, "pad"):
                if atom(child(p, "net")[-1]) == net:
                    items.append((pad_geometry(fp, p), p, (str(reference(fp)), atom(p[1]))))
        for seg in children(tree, "segment"):
            if atom(child(seg, "net")[1]) == net:
                g = LineString(
                    [tuple(map(_number, child(seg, k)[1:3])) for k in ("start", "end")]
                ).buffer(_number(child(seg, "width")[1]) / 2)
                items.append((g, seg, None))
        union = unary_union([g for g, _, _ in items])
        groups = list(union.geoms) if hasattr(union, "geoms") else [union]
        keep = {link_item.keep_pad for link_item in links if link_item.net_name == net}
        if len(keep) != 1:
            raise ValueError("Split net must have one designated source terminal")
        source_pad = next(g for g, _, ref in items if ref in keep)
        main = next(g for g in groups if g.intersects(source_pad))
        others = sorted([g for g in groups if g is not main], key=lambda g: g.bounds)
        if len(others) != sum(link_item.net_name == net for link_item in links):
            raise ValueError("Link cuts did not produce the expected connected net partitions")
        for g, n, ref in items:
            group = next(h for h in groups if h.intersects(g))
            name = net if group is main else net + "_LINK" + str(others.index(group) + 1)
            child(n, "net")[1:] = [Q(name)]
            if ref:
                if ref not in label_map:
                    raise ValueError(f"No schematic label for split terminal {ref}")
                for label in label_map[ref]:
                    label[1] = Q(name.removeprefix("/"))
    # Each jumper must connect two distinct partitions of its original net.
    for link in links:
        names = [atom(child(p, "net")[-1]) for p in children(fps[link.reference], "pad")]
        if len(set(names)) != 2:
            raise ValueError("Jumper terminals were not separated")
    return (
        (serialize_sexpr(tree) + "\n").encode(),
        {source.with_suffix(".kicad_sch").name: (serialize_sexpr(sch) + "\n").encode()},
        made,
    )
