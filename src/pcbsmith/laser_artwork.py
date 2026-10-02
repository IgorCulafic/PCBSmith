"""Source-bound copper removal artwork; not manufacturing approval.

Accept only KiCad's unshifted black polygon/line SVG subset. Unsupported geometry
fails closed. Boolean subtraction produces removal contours, never a background
rectangle hidden by white copper shapes. Curved strokes are polygonized within
0.002 mm; native plot vertices retain their precision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pcbsmith.kicad.cli import find_kicad_cli, run_kicad_process
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.project_dependencies import native_project_hashes


def _paths(data: str) -> list[tuple[list[tuple[float, float]], bool]]:
    tokens = re.findall(r"[MLZmlz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", data)
    remainder = re.sub(r"[MLZmlz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?|[\s,]", "", data)
    if remainder or any(t in {"m", "l", "z"} for t in tokens):
        raise ValueError("unsupported native SVG path command")
    result = []
    points: list[tuple[float, float]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "M":
            if points:
                result.append((points, False))
            points = []
            index += 1
        elif token == "L":
            if not points:
                raise ValueError("line without move")
            index += 1
        elif token == "Z":
            result.append((points, True))
            points = []
            index += 1
        else:
            if index + 1 >= len(tokens):
                raise ValueError("incomplete SVG coordinate")
            points.append((float(token), float(tokens[index + 1])))
            index += 2
    if points:
        result.append((points, False))
    return result


def removal_svg(
    native_svg: bytes,
    bounds: tuple[float, float, float, float],
    *,
    floating_clearance_mm: float | None = None,
    retained_edge_clearance_mm: float = 0.0,
    full_clear_regions_mm: tuple[tuple[float, float, float, float], ...] = (),
    mirror_x: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    from shapely import make_valid, union_all
    from shapely.affinity import scale, translate
    from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box
    from shapely.geometry.base import BaseGeometry

    root = ET.fromstring(native_svg)
    if root.attrib.get("viewBox", "").split()[:2] != ["0.0000", "0.0000"]:
        raise ValueError("native SVG must use the unshifted page coordinate system")
    shapes: list[BaseGeometry] = []

    def visit(node: ET.Element, inherited: dict[str, str]) -> None:
        style = dict(inherited)
        style.update(
            dict(
                item.strip().split(":", 1)
                for item in node.get("style", "").split(";")
                if ":" in item
            )
        )
        transform = node.get("transform", "").strip()
        if transform not in {"", "translate(0 0) scale(1 1)"}:
            raise ValueError("transformed SVG requires a dedicated converter")
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "path":
            subpaths = _paths(node.attrib["d"])
            fill = style.get("fill", "black")
            stroke = style.get("stroke", "none")
            for key in ("opacity", "fill-opacity", "stroke-opacity"):
                if float(style.get(key, "1")) != 1:
                    raise ValueError("transparent copper artwork is unsupported")
            if fill != "none":
                if fill not in {"black", "#000000"} or style.get("fill-rule") != "evenodd":
                    raise ValueError("only native black even-odd copper polygons are supported")
                shape: BaseGeometry = GeometryCollection()
                for points, closed in subpaths:
                    if not closed or len(points) < 3:
                        raise ValueError("unclosed copper polygon")
                    shape = shape.symmetric_difference(make_valid(Polygon(points)))
                shapes.append(shape)
            if stroke != "none":
                if stroke not in {"black", "#000000"}:
                    raise ValueError("nonblack copper stroke")
                width = float(style.get("stroke-width", "0"))
                if (
                    width <= 0
                    or width > 5
                    or style.get("stroke-linecap") != "round"
                    or style.get("stroke-linejoin") != "round"
                ):
                    raise ValueError("unsupported copper stroke width or cap")
                for points, closed in subpaths:
                    if closed:
                        points = [*points, points[0]]
                    shapes.append(LineString(points).buffer(width / 2, quad_segs=64))
        elif tag == "circle":
            import math

            if (
                style.get("fill") not in {"black", "#000000"}
                or style.get("stroke", "none") != "none"
            ):
                raise ValueError("Only solid black native copper circles are supported")
            if any(
                float(style.get(k, "1")) != 1 for k in ("opacity", "fill-opacity", "stroke-opacity")
            ):
                raise ValueError("Transparent copper circles are unsupported")
            cx, cy, radius = (float(node.attrib[k]) for k in ("cx", "cy", "r"))
            if not all(math.isfinite(v) for v in (cx, cy, radius)) or not 0 < radius <= 20:
                raise ValueError("Unsupported native copper circle geometry")
            shapes.append(Point(cx, cy).buffer(radius, quad_segs=128))
        elif tag not in {"svg", "g", "title", "desc"}:
            raise ValueError("unsupported native copper SVG element: " + tag)
        for child in node:
            visit(child, style)

    visit(root, {})
    if not shapes:
        raise ValueError("no native copper found")
    x0, y0, x1, y1 = bounds
    if not x0 < x1 or not y0 < y1:
        raise ValueError("empty board boundary")
    board = box(*bounds)
    copper = union_all(shapes).intersection(board)
    # Regions use board-local coordinates before any rear-side flip. Remove
    # only extra floating background here, never functional native copper.
    clear_regions = []
    for region in full_clear_regions_mm:
        import math

        if len(region) != 4 or not all(math.isfinite(v) for v in region):
            raise ValueError("Full-clear regions require four finite board-local coordinates")
        a, b, c, d = region
        if not 0 <= a < c <= x1 - x0 or not 0 <= b < d <= y1 - y0:
            raise ValueError("Full-clear region lies outside the board or is empty")
        clear_regions.append(box(a + x0, b + y0, c + x0, d + y0))
    floating: BaseGeometry = GeometryCollection()
    if floating_clearance_mm is not None:
        import math

        if not math.isfinite(floating_clearance_mm) or floating_clearance_mm < 0.3:
            raise ValueError("floating copper requires at least 0.3mm isolation")
        # CAM-only unconnected copper reduces ablation. Never joins CAD nets.
        pockets: BaseGeometry = board.difference(copper).buffer(
            -(floating_clearance_mm + 0.002), quad_segs=64
        )
        if not math.isfinite(retained_edge_clearance_mm) or retained_edge_clearance_mm < 0:
            raise ValueError("retained copper edge clearance must be finite and non-negative")
        if retained_edge_clearance_mm:
            pockets = pockets.intersection(board.buffer(-retained_edge_clearance_mm))
        from shapely import get_parts

        pieces = list(get_parts(pockets))
        floating = union_all([p for p in pieces if isinstance(p, Polygon) and p.area >= 1.0])
        if clear_regions:
            floating = floating.difference(union_all(clear_regions))
            floating = union_all(
                [p for p in get_parts(floating) if isinstance(p, Polygon) and p.area >= 1.0]
            )
        if not floating.is_empty and (
            floating.intersects(copper) or floating.distance(copper) < floating_clearance_mm
        ):
            raise ValueError("CAM retained copper violates electrical isolation")
    final_copper = copper.union(floating)
    removed = translate(board.difference(final_copper), xoff=-x0, yoff=-y0)
    if mirror_x:
        removed = scale(removed, xfact=-1, yfact=1, origin=((x1 - x0) / 2, 0))
    if isinstance(removed, Polygon):
        polygons = [removed]
    elif isinstance(removed, MultiPolygon):
        polygons = list(removed.geoms)
    else:
        raise ValueError("empty or nonpolygon removal geometry")
    commands = []
    for polygon in polygons:
        if polygon.geom_type != "Polygon":
            raise ValueError("nonpolygon removal geometry")
        for ring in [polygon.exterior, *polygon.interiors]:
            points = list(ring.coords)
            commands.append("M " + " L ".join(f"{x:.6f},{y:.6f}" for x, y in points[:-1]) + " Z")
    width, height = x1 - x0, y1 - y0
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}mm" height="{height:g}mm" '
        f'viewBox="0 0 {width:g} {height:g}">'
        "<title>Black filled regions remove copper; component-side view; 1:1</title>"
        f'<path fill="#000000" fill-rule="evenodd" stroke="none" d="{" ".join(commands)}"/></svg>\n'
    )
    report: dict[str, Any] = {
        "width_mm": width,
        "height_mm": height,
        "removed_area_mm2": removed.area,
        "retained_area_mm2": final_copper.area,
        "cad_copper_area_mm2": copper.area,
        "cam_floating_copper_area_mm2": floating.area,
        "cam_floating_clearance_mm": floating_clearance_mm,
        "cam_retained_edge_clearance_mm": retained_edge_clearance_mm,
        "cam_retained_edge_isolation_verified": floating.is_empty
        or floating.distance(board.boundary) >= retained_edge_clearance_mm - 1e-9,
        "cam_floating_isolation_verified": floating.is_empty
        or floating.distance(copper) >= (floating_clearance_mm or 0),
        "cam_floating_policy": (
            "Additional isolated unused copper; no electrical connection; areas below 1mm2 removed"
        ),
        "removed_fraction": removed.area / board.area,
        "stroke_polygonization_error_bound_mm": 0.002,
        "orientation": "component-side; not mirrored",
        "polarity": "black fill removes copper",
    }
    if full_clear_regions_mm:
        report["full_clear_regions_mm"] = [list(v) for v in full_clear_regions_mm]
    if mirror_x:
        svg = svg.replace("component-side view", "rear-side view; flipped left-right")
        report["orientation"] = "rear-side; mirrored X around board centre; flip left-right"
        report["mirror_x"] = True
    return svg.encode(), report


def verify_actual_copper_isolation(
    board: Path,
    removal: bytes,
    *,
    minimum_clearance_mm: float,
    minimum_edge_clearance_mm: float,
    two_sided: bool = False,
    copper_layer: str = "F.Cu",
    mirror_x: bool = False,
) -> dict[str, Any]:
    """Conservative native-copper check for straight tracks and simple front SMD pads.

    Every circular arc is enclosed by a circumscribed polygon: buffer radius
    r/cos(pi/(4*64)) has inradius r. Distance to this superset is a lower bound
    on distance to actual copper. Native SVG tessellation is never the authority.
    Unsupported copper is a blocker, not an assumed empty region.
    """
    import math

    from shapely import get_parts, union_all
    from shapely.affinity import rotate, scale, translate
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.geometry.base import BaseGeometry

    if any(
        not math.isfinite(v) or v < 0 for v in (minimum_clearance_mm, minimum_edge_clearance_mm)
    ):
        raise ValueError("Actual copper isolation requires finite nonnegative minima")
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    if copper_layer not in {"F.Cu", "B.Cu"} or (copper_layer == "B.Cu" and not two_sided):
        raise ValueError("Rear copper requires explicit two-sided CAM")
    if mirror_x and copper_layer != "B.Cu":
        raise ValueError("Mirroring is only supported for rear copper")
    shapes = []
    error_bound = 0.0
    factor = 1 / math.cos(math.pi / 256)

    def numbers(node: list[Any], key: str) -> list[float]:
        entries = _children(node, key)
        if not entries or any(isinstance(v, list) for v in entries[0][1:]):
            raise ValueError("Unsupported nested or absent native geometry: " + key)
        values = [float(_atom(v)) for v in entries[0][1:]]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Nonfinite native copper geometry")
        return values

    def rounded(core: Any, radius: float) -> Any:
        nonlocal error_bound
        if radius < 0:
            raise ValueError("Invalid copper radius")
        error_bound = max(error_bound, radius * (factor - 1))
        return core.buffer(radius * factor, quad_segs=64) if radius else core

    def layer(node: list[Any]) -> str:
        values = _children(node, "layer")
        return _atom(values[0][1]) if values else ""

    def removed_layers(node: list[Any]) -> bool:
        values = _children(node, "remove_unused_layers")
        return bool(values and (len(values[0]) != 2 or _atom(values[0][1]) != "no"))

    if two_sided:
        layer_tables = _children(tree, "layers")
        if layer_tables:
            copper_names = {
                _atom(v[1])
                for v in layer_tables[0][1:]
                if isinstance(v, list) and _atom(v[1]).endswith(".Cu")
            }
            if copper_names != {"F.Cu", "B.Cu"}:
                raise ValueError("Two-sided CAM requires exactly F.Cu and B.Cu")

    if any(
        _children(tree, kind) for kind in (("arc", "zone") if two_sided else ("via", "arc", "zone"))
    ):
        raise ValueError("Actual copper isolation supports straight tracks without vias/arcs/zones")
    for node in tree:
        if not isinstance(node, list) or not node:
            continue
        if layer(node).endswith(".Cu") and node[0] not in {"segment", "footprint"}:
            raise ValueError("Unsupported native copper graphic")
    for segment in _children(tree, "segment"):
        if layer(segment) not in ({"F.Cu", "B.Cu"} if two_sided else {"F.Cu"}):
            raise ValueError("Actual copper isolation requires front copper")
        if layer(segment) != copper_layer:
            continue
        width = numbers(segment, "width")[0]
        if width <= 0:
            raise ValueError("Invalid copper width")
        shapes.append(
            rounded(LineString([numbers(segment, "start"), numbers(segment, "end")]), width / 2)
        )
    for via in _children(tree, "via"):
        layers = [_atom(v) for v in _children(via, "layers")[0][1:]]
        if (
            layers != ["F.Cu", "B.Cu"]
            or any(_atom(v) in {"blind", "micro"} for v in via[1:] if not isinstance(v, list))
            or _children(via, "padstack")
            or removed_layers(via)
        ):
            raise ValueError("Only ordinary through vias with full lands are supported")
        size, drill = numbers(via, "size")[0], numbers(via, "drill")[0]
        if not 0 < drill < size:
            raise ValueError("Invalid plated via annulus")
        shapes.append(rounded(Point(numbers(via, "at")[:2]), size / 2))
    for footprint in _children(tree, "footprint"):
        if layer(footprint) != "F.Cu":
            raise ValueError("Actual copper isolation requires front footprints")
        at = numbers(footprint, "at")
        rotation = at[2] if len(at) > 2 else 0
        for child in footprint:
            if (
                isinstance(child, list)
                and child
                and child[0] != "pad"
                and layer(child).endswith(".Cu")
            ):
                raise ValueError("Unsupported footprint copper graphic")
        for pad in _children(footprint, "pad"):
            layers = [_atom(v) for v in _children(pad, "layers")[0][1:]]
            kind = _atom(pad[3])
            plated = two_sided and _atom(pad[2]) == "thru_hole" and "*.Cu" in layers
            front_smd = (
                _atom(pad[2]) == "smd"
                and "F.Cu" in layers
                and not any(v in layers for v in ("B.Cu", "*.Cu"))
            )
            if not (front_smd or plated):
                raise ValueError("Actual copper isolation requires front SMD pads")
            if _children(pad, "padstack") or removed_layers(pad):
                raise ValueError("Custom or removed pad layers are unsupported")
            if kind not in {"rect", "roundrect", "circle", "oval"} or (
                _children(pad, "drill") and not plated
            ):
                raise ValueError("Unsupported actual copper pad shape")
            w, h = numbers(pad, "size")
            if min(w, h) <= 0:
                raise ValueError("Invalid copper pad size")
            if plated:
                pad_drill = numbers(pad, "drill")
                if len(pad_drill) != 1 or not 0 < pad_drill[0] < min(w, h):
                    raise ValueError(
                        "Only centered round plated drills with positive annulus are supported"
                    )
            if front_smd and copper_layer == "B.Cu":
                continue
            if kind == "circle":
                if w != h:
                    raise ValueError("Invalid circular pad")
                shape = rounded(Point(0, 0), w / 2)
            elif kind == "oval":
                r = min(w, h) / 2
                shape = rounded(LineString([(-w / 2 + r, -h / 2 + r), (w / 2 - r, h / 2 - r)]), r)
            else:
                ratio = numbers(pad, "roundrect_rratio")[0] if kind == "roundrect" else 0
                if not 0 <= ratio <= 0.5:
                    raise ValueError("Invalid rounded pad radius")
                r = min(w, h) * ratio
                if r == min(w, h) / 2 and r:
                    core: BaseGeometry = (
                        Point(0, 0)
                        if w == h
                        else LineString([(-w / 2 + r, -h / 2 + r), (w / 2 - r, h / 2 - r)])
                    )
                else:
                    core = box(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r)
                shape = rounded(core, r)
            local = numbers(pad, "at")
            center = rotate(Point(local[:2]), -rotation, origin=(0, 0))
            angle = local[2] if len(local) > 2 else 0
            shapes.append(
                translate(
                    rotate(shape, -angle, origin=(0, 0)),
                    xoff=at[0] + center.x,
                    yoff=at[1] + center.y,
                )
            )
    edges = [n for n in tree if isinstance(n, list) and n and layer(n) == "Edge.Cuts"]
    if len(edges) != 1 or edges[0][0] != "gr_rect" or not shapes:
        raise ValueError("Actual copper isolation requires copper and one rectangular outline")
    x0, y0 = numbers(edges[0], "start")
    x1, y1 = numbers(edges[0], "end")
    if not x0 < x1 or not y0 < y1:
        raise ValueError("Invalid isolation outline")
    outline = box(x0, y0, x1, y1)
    root = ET.fromstring(removal)
    if any(
        node.get("transform") or node.tag.rsplit("}", 1)[-1] not in {"svg", "title", "path"}
        for node in root.iter()
    ):
        raise ValueError("Isolation artwork contains unsupported transforms or elements")
    if (
        root.get("viewBox") != f"0 0 {x1 - x0:g} {y1 - y0:g}"
        or root.get("width") != f"{x1 - x0:g}mm"
        or root.get("height") != f"{y1 - y0:g}mm"
    ):
        raise ValueError("Actual isolation SVG dimensions differ from native outline")
    paths = list(root.iter("{http://www.w3.org/2000/svg}path"))
    if (
        len(paths) != 1
        or paths[0].get("fill") != "#000000"
        or paths[0].get("fill-rule") != "evenodd"
        or paths[0].get("stroke") != "none"
    ):
        raise ValueError("Actual isolation requires explicit black even-odd removal geometry")
    removed: BaseGeometry = Polygon()
    for points, closed in _paths(paths[0].attrib["d"]):
        polygon = Polygon(points)
        if not closed or not polygon.is_valid:
            raise ValueError("Invalid isolation contour")
        removed = removed.symmetric_difference(polygon)
    if mirror_x:
        removed = scale(removed, xfact=-1, yfact=1, origin=((x1 - x0) / 2, 0))
    removed = translate(removed, xoff=x0, yoff=y0)
    retained = outline.difference(removed)
    actual_outer = union_all(shapes)
    # Retain the existing 0.02 mm CAM shape-comparison tolerance separately;
    # it never reduces the required circuit-to-floating separation.
    if not retained.buffer(0.02).covers(actual_outer):
        raise ValueError("Isolation artwork omits native circuit copper")
    parts = list(get_parts(retained))
    circuit = union_all([v for v in parts if v.intersects(actual_outer)])
    if not actual_outer.buffer(0.02).covers(circuit):
        raise ValueError("Retained background joins native circuit copper")
    floating = union_all([v for v in parts if not v.intersects(actual_outer)])
    gap = None if floating.is_empty else floating.distance(actual_outer)
    edge = retained.distance(outline.boundary)
    # 1 nm accounts only for floating-point/serialized coordinates, not shape tolerance.
    if gap is not None and gap + 1e-9 < minimum_clearance_mm:
        raise ValueError(f"Actual copper isolation {gap:.9f}mm is below {minimum_clearance_mm:g}mm")
    if edge + 1e-9 < minimum_edge_clearance_mm:
        raise ValueError("Actual retained copper violates reviewed edge clearance")
    report = {
        "method": "native-straight-track-simple-smd-circumscribed-v1",
        "board_sha256": hashlib.sha256(board.read_bytes()).hexdigest(),
        "removal_svg_sha256": hashlib.sha256(removal).hexdigest(),
        "minimum_required_clearance_mm": minimum_clearance_mm,
        "minimum_required_edge_clearance_mm": minimum_edge_clearance_mm,
        "actual_clearance_lower_bound_mm": gap,
        "retained_edge_clearance_mm": edge,
        "circular_enclosure_max_error_mm": error_bound,
        "circuit_shape_comparison_tolerance_mm": 0.02,
        "physical_qualification": "not_established",
    }
    if two_sided:
        report.update(
            {
                "method": "native-two-layer-straight-track-simple-pad-through-via-v1",
                "copper_layer": copper_layer,
                "mirror_x": mirror_x,
                "drill_policy": "Solid land enclosure; holes supplied as separate drills",
            }
        )
    return report


def export_laser_artwork(
    board: Path,
    output: Path,
    *,
    floating_clearance_mm: float | None = None,
    retained_edge_clearance_mm: float = 0.0,
    two_sided: bool = False,
    copper_layer: str = "F.Cu",
    mirror_x: bool = False,
    full_clear_regions_mm: tuple[tuple[float, float, float, float], ...] = (),
) -> dict[str, Any]:
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    if output.exists():
        raise ValueError("laser artwork output must be fresh")
    if type(two_sided) is not bool or type(mirror_x) is not bool:
        raise ValueError("Two-sided and mirror options must be explicit booleans")
    inputs = native_project_hashes(board)
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    if copper_layer not in {"F.Cu", "B.Cu"} or (copper_layer == "B.Cu" and not two_sided):
        raise ValueError("Rear copper requires explicit two-sided CAM")
    if mirror_x and copper_layer != "B.Cu":
        raise ValueError("Mirroring is only supported for rear copper")
    if _children(tree, "via") and not two_sided:
        raise ValueError("single-sided laser export rejects vias")
    for head in ("segment", "arc", "zone"):
        for item in _children(tree, head):
            if _atom(_children(item, "layer")[0][1]) not in (
                {"F.Cu", "B.Cu"} if two_sided else {"F.Cu"}
            ):
                raise ValueError("single-sided laser export rejects rear copper")
    for footprint in _children(tree, "footprint"):
        for pad in _children(footprint, "pad"):
            layers = [_atom(v) for v in _children(pad, "layers")[0][1:]]
            plated = two_sided and _atom(pad[2]) == "thru_hole" and "*.Cu" in layers
            if not plated and (_atom(pad[2]) != "smd" or "F.Cu" not in layers or "B.Cu" in layers):
                raise ValueError("laser export requires front SMD pads only")
    edges = [
        n
        for n in tree
        if isinstance(n, list)
        and n
        and str(n[0]).startswith("gr_")
        and any(_atom(v[1]) == "Edge.Cuts" for v in _children(n, "layer"))
    ]
    if len(edges) != 1 or edges[0][0] != "gr_rect":
        raise ValueError("laser export currently requires a rectangular board outline")
    bounds = tuple(
        float(_atom(v)) for key in ("start", "end") for v in _children(edges[0], key)[0][1:]
    )
    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad is unavailable")
    output.mkdir(parents=True)
    zones = _children(tree, "zone")
    if zones:
        from pcbsmith.kicad.native_zone_edits import refill_native_edit

        ids = tuple(_atom(_children(z, "uuid")[0][1]) for z in zones)
        filled, _ = refill_native_edit(board, output / "fill-check", ids)
        if filled != board.read_bytes():
            raise ValueError("saved copper fill is stale; finish routing validation before export")
    native = output / "native-copper.svg"
    result = run_kicad_process(
        (
            install.path,
            "pcb",
            "export",
            "svg",
            "--black-and-white",
            "--page-size-mode",
            "0",
            "--exclude-drawing-sheet",
            "--layers",
            copper_layer,
            "--mode-single",
            "--scale",
            "1",
            "--drill-shape-opt",
            "0",
            "--output",
            native,
            board,
        )
    )
    (output / "native-process.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    if result.returncode or not native.is_file():
        raise RuntimeError("native copper SVG export failed")
    if native_project_hashes(board) != inputs:
        raise ValueError("native source changed during export")
    payload, report = removal_svg(
        native.read_bytes(),
        (bounds[0], bounds[1], bounds[2], bounds[3]),
        floating_clearance_mm=floating_clearance_mm,
        retained_edge_clearance_mm=retained_edge_clearance_mm,
        full_clear_regions_mm=full_clear_regions_mm,
        mirror_x=mirror_x,
    )
    if two_sided:
        # This also rejects unsupported layer stacks, slots and hidden copper
        # before any result can be used as a delivered CAM artifact.
        report["native_geometry_check"] = verify_actual_copper_isolation(
            board,
            payload,
            minimum_clearance_mm=0,
            minimum_edge_clearance_mm=0,
            two_sided=True,
            copper_layer=copper_layer,
            mirror_x=mirror_x,
        )
        report.update({"two_sided": True, "copper_layer": copper_layer, "mirror_x": mirror_x})
    target = output / "copper-removal.svg"
    target.write_bytes(payload)
    report.update(
        {
            "source_inputs": inputs,
            "native_svg_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
            "removal_svg_sha256": hashlib.sha256(payload).hexdigest(),
            "status": "inspection_artwork_not_manufacturing_approval",
            "limitations": [
                "Requires exact board acceptance and visual CAM inspection before use.",
                "Laser settings, substrate damage and achieved isolation are unqualified.",
            ],
        }
    )
    (output / "artwork.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def export_laser_variants(board: Path, output: Path, variants: dict[str, Any]) -> dict[str, Any]:
    """One declared export operation with a finite set of CAM comparisons."""
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    if not 1 <= len(variants) <= 8 or output.exists():
        raise ValueError("CAM comparison requires 1..8 variants and a fresh output directory")
    allowed = {
        "floating_clearance_mm",
        "retained_edge_clearance_mm",
        "two_sided",
        "copper_layer",
        "mirror_x",
        "full_clear_regions_mm",
    }
    for name, options in variants.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name) or not isinstance(options, dict):
            raise ValueError("Invalid CAM variant name/options")
        if set(options) - allowed:
            raise ValueError("Unknown CAM variant option")
    inputs = native_project_hashes(board)
    output.mkdir(parents=True)
    results = {}
    for name, options in variants.items():
        results[name] = export_laser_artwork(board, output / name, **options)
        if native_project_hashes(board) != inputs:
            raise ValueError("Native source changed during CAM comparison")
    manifest = {"source_inputs": inputs, "variants": results}
    (output / "variants.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    from pcbsmith.board_job import require_worker

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retain-floating-copper", type=float, metavar="CLEARANCE_MM")
    parser.add_argument("--retained-edge-clearance", type=float, default=0.0)
    parser.add_argument("--two-sided", action="store_true")
    parser.add_argument("--copper-layer", choices=("F.Cu", "B.Cu"), default="F.Cu")
    parser.add_argument("--mirror-x", action="store_true")
    parser.add_argument("--full-clear-region", nargs=4, type=float, action="append", default=[])
    parser.add_argument(
        "--variants", type=Path, help="JSON map of 1..8 explicitly planned variants"
    )
    args = parser.parse_args()
    require_worker("pcbsmith.laser_artwork", sys.argv[1:])
    if args.variants:
        if any(
            option in {arg.split("=", 1)[0] for arg in sys.argv[1:]}
            for option in (
                "--retain-floating-copper",
                "--retained-edge-clearance",
                "--two-sided",
                "--copper-layer",
                "--mirror-x",
                "--full-clear-region",
            )
        ):
            parser.error("Variant-file options cannot be mixed with per-export options")
        print(
            json.dumps(
                export_laser_variants(
                    args.board, args.output, json.loads(args.variants.read_bytes())
                ),
                indent=2,
            )
        )
        return
    print(
        json.dumps(
            export_laser_artwork(
                args.board,
                args.output,
                floating_clearance_mm=args.retain_floating_copper,
                retained_edge_clearance_mm=args.retained_edge_clearance,
                two_sided=args.two_sided,
                copper_layer=args.copper_layer,
                mirror_x=args.mirror_x,
                full_clear_regions_mm=tuple(tuple(v) for v in args.full_clear_region),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
