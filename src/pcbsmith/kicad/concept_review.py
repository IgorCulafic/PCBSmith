"""Dimensionally authoritative pre-design concept examination and overlays."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.kicad.library import FootprintSpec, load_footprint, rotate_offset

Point = tuple[float, float]
ReviewStatus = Literal["comfortable", "tight", "conflict", "engineering_selection"]

STATUS_COLORS = {
    "comfortable": "#31c96b",
    "tight": "#f3c344",
    "conflict": "#ef5350",
    "engineering_selection": "#42a5f5",
}


class ConceptItem(BaseModel):
    """One exact proposed feature or component anchor in board coordinates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    label: str
    side: Literal["front", "back", "both"]
    kind: Literal["footprint", "mounting_hole", "rectangle", "aperture"]
    anchor_mm: Point
    rotation_deg: float = 0.0
    footprint_id: str | None = None
    size_mm: tuple[float, float] | None = None
    diameter_mm: float | None = Field(default=None, gt=0)
    containment: Literal["courtyard", "body", "pads_and_holes", "shape", "none"] = "shape"
    body_overhang_allowed: bool = False
    requirement_resolution: Literal["explicit", "derived", "assumed", "engineering"]
    note: str = ""


class ConceptItemResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item: ConceptItem
    status: ReviewStatus
    contained: bool
    minimum_edge_clearance_mm: float
    envelope: tuple[Point, ...]
    footprint_source_file: str | None = None
    message: str


class ConceptReview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-concept-review-v1"] = "pcbsmith-concept-review-v1"
    project_id: str
    outline: tuple[Point, ...]
    outline_sha256: str
    board_bounds_mm: tuple[float, float, float, float]
    outcome: Literal["blocked", "needs_user_decision", "ready_for_approval"]
    items: tuple[ConceptItemResult, ...]
    hard_conflicts: tuple[str, ...]
    assumptions: tuple[str, ...]
    view_conventions: tuple[str, ...] = (
        "front: component side viewed from above in board coordinates",
        "back: solder side viewed from below; horizontal axis is mirrored",
    )


def examine_concept(
    project_id: str,
    outline: tuple[Point, ...],
    items: tuple[ConceptItem, ...],
    *,
    tight_clearance_mm: float = 0.5,
    hard_conflicts: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
) -> ConceptReview:
    """Evaluate proposed envelopes against the real traced substrate."""

    try:
        from shapely.geometry import Polygon  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - dependency contract
        raise RuntimeError("Install the artwork extra: pip install 'pcbsmith[artwork]'.") from exc

    board = Polygon(outline)
    if not board.is_valid or board.is_empty or board.area <= 0:
        raise ValueError("concept outline must be a valid positive-area polygon")
    identities = tuple(item.item_id for item in items)
    if len(set(identities)) != len(identities):
        raise ValueError("concept item_id values must be unique")

    results: list[ConceptItemResult] = []
    for item in items:
        shape, source = _item_shape(item)
        contained = item.containment == "none" or board.covers(shape)
        clearance = (
            float(shape.distance(board.boundary))
            if contained
            else -_outside_excursion_mm(shape, board)
        )
        status: ReviewStatus
        if not contained:
            if item.body_overhang_allowed:
                status = "tight"
                message = "Envelope overhangs the substrate under an explicit overhang allowance."
            else:
                status = "conflict"
                message = "Required envelope is not contained by the traced board substrate."
        elif clearance < tight_clearance_mm:
            status = "tight"
            message = f"Contained, but only {clearance:.3f} mm from the board edge."
        elif item.requirement_resolution == "engineering":
            status = "engineering_selection"
            message = (
                "Geometry is feasible; placement is an engineering proposal awaiting approval."
            )
        else:
            status = "comfortable"
            message = f"Contained with {clearance:.3f} mm minimum edge clearance."
        results.append(
            ConceptItemResult(
                item=item,
                status=status,
                contained=contained,
                minimum_edge_clearance_mm=round(clearance, 4),
                envelope=_polygon_points(shape),
                footprint_source_file=source,
                message=message,
            )
        )

    if hard_conflicts or any(item.status == "conflict" for item in results):
        outcome = "blocked"
    elif any(item.status in {"tight", "engineering_selection"} for item in results):
        outcome = "needs_user_decision"
    else:
        outcome = "ready_for_approval"
    bounds = tuple(round(float(value), 4) for value in board.bounds)
    canonical_outline = tuple((round(x, 4), round(y, 4)) for x, y in outline)
    outline_hash = hashlib.sha256(
        json.dumps(canonical_outline, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ConceptReview(
        project_id=project_id,
        outline=canonical_outline,
        outline_sha256=outline_hash,
        board_bounds_mm=(bounds[0], bounds[1], bounds[2], bounds[3]),
        outcome=outcome,
        items=tuple(results),
        hard_conflicts=hard_conflicts,
        assumptions=assumptions,
    )


def write_concept_review_package(review: ConceptReview, output_dir: Path) -> tuple[Path, ...]:
    """Write JSON, Markdown, and deterministic front/back SVG+PNG evidence."""

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    json_file = output_dir / "concept-review.json"
    json_file.write_text(review.model_dump_json(indent=2), encoding="utf-8")
    written.append(json_file)
    for side in ("front", "back"):
        svg_file = output_dir / f"engineering-overlay-{side}.svg"
        png_file = output_dir / f"engineering-overlay-{side}.png"
        svg_text = _render_svg(review, side)
        svg_file.write_text(svg_text, encoding="utf-8")
        try:
            import resvg_py
        except ImportError as exc:  # pragma: no cover - dependency contract
            raise RuntimeError("Install the review extra: pip install 'pcbsmith[review]'.") from exc
        png_file.write_bytes(resvg_py.svg_to_bytes(svg_string=svg_text))
        written.extend((svg_file, png_file))
    report_file = output_dir / "concept-review.md"
    report_file.write_text(_render_markdown(review), encoding="utf-8")
    written.append(report_file)
    manifest = {
        "schema": "pcbsmith-concept-review-package-v1",
        "project_id": review.project_id,
        "outcome": review.outcome,
        "files": [
            {
                "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in written
        ],
    }
    manifest_file = output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    written.append(manifest_file)
    return tuple(written)


def _item_shape(item: ConceptItem) -> tuple[Any, str | None]:
    from shapely.geometry import Point as ShapePoint
    from shapely.geometry import Polygon

    if item.kind == "mounting_hole":
        if item.diameter_mm is None:
            raise ValueError(f"{item.item_id} requires diameter_mm")
        return ShapePoint(*item.anchor_mm).buffer(item.diameter_mm / 2, quad_segs=32), None
    if item.kind in {"rectangle", "aperture"}:
        if item.size_mm is None:
            raise ValueError(f"{item.item_id} requires size_mm")
        return Polygon(_rotated_rectangle(item.anchor_mm, item.size_mm, item.rotation_deg)), None
    if item.footprint_id is None:
        raise ValueError(f"{item.item_id} requires footprint_id")
    imported = load_footprint(item.footprint_id)
    spec = imported.spec
    if item.containment == "pads_and_holes":
        shapes = tuple(
            _pad_shape(spec, index, item.anchor_mm, item.rotation_deg)
            for index in range(len(spec.pads))
        )
        if not shapes:
            raise ValueError(f"{item.footprint_id} has no pads or holes")
        from shapely.ops import unary_union  # type: ignore[import-untyped]

        shape = unary_union(shapes)
    else:
        local = _footprint_hull(spec, item.containment)
        shape = Polygon(
            tuple(_transform(point, item.anchor_mm, item.rotation_deg) for point in local)
        )
    return shape, str(imported.source_file.resolve())


def _footprint_hull(spec: FootprintSpec, purpose: str) -> tuple[Point, ...]:
    if purpose == "body" and spec.fab_hull:
        return spec.fab_hull
    if purpose == "courtyard" and spec.courtyard_hull:
        return spec.courtyard_hull
    if purpose not in {"body", "courtyard"}:
        raise ValueError(f"unsupported footprint containment {purpose!r}")
    return (
        (spec.x_min, spec.y_min),
        (spec.x_max, spec.y_min),
        (spec.x_max, spec.y_max),
        (spec.x_min, spec.y_max),
    )


def _pad_shape(spec: FootprintSpec, index: int, anchor: Point, rotation: float) -> Any:
    from shapely.geometry import Polygon

    pad = spec.pads[index]
    width = pad.width_mm
    height = pad.height_mm
    points: tuple[Point, ...]
    if pad.shape in {"circle", "oval"}:
        points = tuple(
            (
                pad.x_mm + width / 2 * math.cos(2 * math.pi * sample / 32),
                pad.y_mm + height / 2 * math.sin(2 * math.pi * sample / 32),
            )
            for sample in range(32)
        )
    else:
        points = _rotated_rectangle((pad.x_mm, pad.y_mm), (width, height), pad.angle_deg)
    return Polygon(tuple(_transform(point, anchor, rotation) for point in points))


def _transform(point: Point, anchor: Point, rotation: float) -> Point:
    dx, dy = rotate_offset(point[0], point[1], rotation)
    return (anchor[0] + dx, anchor[1] + dy)


def _rotated_rectangle(
    anchor: Point, size: tuple[float, float], rotation: float
) -> tuple[Point, ...]:
    half_x, half_y = size[0] / 2, size[1] / 2
    return tuple(
        (anchor[0] + dx, anchor[1] + dy)
        for dx, dy in (
            rotate_offset(-half_x, -half_y, rotation),
            rotate_offset(half_x, -half_y, rotation),
            rotate_offset(half_x, half_y, rotation),
            rotate_offset(-half_x, half_y, rotation),
        )
    )


def _polygon_points(shape: Any) -> tuple[Point, ...]:
    polygon = shape.convex_hull
    return tuple(
        (round(float(x), 4), round(float(y), 4)) for x, y in tuple(polygon.exterior.coords)[:-1]
    )


def _outside_excursion_mm(shape: Any, board: Any) -> float:
    """Return the farthest sampled boundary excursion beyond *board* in millimetres."""

    from shapely.geometry import Point as ShapePoint

    def boundary_points(geometry: Any) -> tuple[Point, ...]:
        if hasattr(geometry, "geoms"):
            return tuple(
                point
                for child in geometry.geoms
                for point in boundary_points(child)
            )
        exterior = getattr(geometry, "exterior", None)
        if exterior is None:
            coordinates = getattr(geometry, "coords", ())
            return tuple((float(x), float(y)) for x, y in coordinates)
        rings = (exterior, *getattr(geometry, "interiors", ()))
        return tuple(
            (float(x), float(y))
            for ring in rings
            for x, y in ring.coords
        )

    points = boundary_points(shape)
    if not points:
        return float(shape.distance(board))
    return max(float(ShapePoint(point).distance(board)) for point in points)


def _render_svg(review: ConceptReview, side: Literal["front", "back"]) -> str:
    min_x, min_y, max_x, max_y = review.board_bounds_mm
    visible_items = tuple(
        result for result in review.items if result.item.side in {side, "both"}
    )
    rendered_x = tuple(
        point[0] for result in visible_items for point in result.envelope
    )
    rendered_y = tuple(
        point[1] for result in visible_items for point in result.envelope
    )
    content_min_x = min((min_x, *rendered_x))
    content_min_y = min((min_y, *rendered_y))
    content_max_x = max((max_x, *rendered_x))
    content_max_y = max((max_y, *rendered_y))
    padding = 5.0
    title_y = content_max_y + 5.5
    legend_y = title_y + 4.5
    view_min_x = content_min_x - padding
    view_min_y = content_min_y - padding
    view_max_x = max(content_max_x, content_min_x + 70.0) + padding
    view_max_y = legend_y + 4.0
    width = view_max_x - view_min_x
    height = view_max_y - view_min_y
    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": "3840",
            "height": str(round(3840 * height / width)),
            "viewBox": f"{view_min_x} {view_min_y} {width} {height}",
        },
    )
    ET.SubElement(
        svg,
        "rect",
        {
            "x": str(view_min_x),
            "y": str(view_min_y),
            "width": str(width),
            "height": str(height),
            "fill": "#101418",
        },
    )

    def view(point: Point) -> Point:
        return (min_x + max_x - point[0], point[1]) if side == "back" else point

    outline = " ".join(f"{x:.4f},{y:.4f}" for x, y in map(view, review.outline))
    ET.SubElement(
        svg,
        "polygon",
        {"points": outline, "fill": "#182b22", "stroke": "#d9e3e8", "stroke-width": "0.35"},
    )
    for result in visible_items:
        points = " ".join(f"{x:.4f},{y:.4f}" for x, y in map(view, result.envelope))
        color = STATUS_COLORS[result.status]
        ET.SubElement(
            svg,
            "polygon",
            {
                "points": points,
                "fill": color,
                "fill-opacity": "0.22",
                "stroke": color,
                "stroke-width": "0.35",
                "stroke-dasharray": "1.2 0.6" if result.status != "comfortable" else "none",
            },
        )
        label_x, label_y = view(result.item.anchor_mm)
        if result.item.label:
            text = ET.SubElement(
                svg,
                "text",
                {
                    "x": f"{label_x:.3f}",
                    "y": f"{label_y:.3f}",
                    "fill": "#f4f7f8",
                    "font-size": "1.65",
                    "font-family": "Arial, sans-serif",
                    "text-anchor": "middle",
                    "dominant-baseline": "central",
                },
            )
            text.text = result.item.label
    title = ET.SubElement(
        svg,
        "text",
        {
            "x": str(content_min_x),
            "y": f"{title_y:.3f}",
            "fill": "#f4f7f8",
            "font-size": "1.6",
            "font-family": "Arial, sans-serif",
        },
    )
    title.text = f"{review.project_id} | {side.upper()} | {review.outcome}"
    for index, (status, color) in enumerate(STATUS_COLORS.items()):
        x = content_min_x + index * 18.0
        ET.SubElement(
            svg,
            "rect",
            {
                "x": str(x),
                "y": str(legend_y - 1.8),
                "width": "2.0",
                "height": "2.0",
                "fill": color,
            },
        )
        label = ET.SubElement(
            svg,
            "text",
            {
                "x": str(x + 3.4),
                "y": str(legend_y),
                "fill": "#d9e3e8",
                "font-size": "1.1",
                "font-family": "Arial, sans-serif",
            },
        )
        label.text = status.replace("_", " ")
    return ET.tostring(svg, encoding="unicode")


def _render_markdown(review: ConceptReview) -> str:
    lines = [
        f"# {review.project_id} deterministic concept review",
        "",
        f"Outcome: **{review.outcome}**",
        "",
        "This is a feasibility and placement record, not a routed PCB or fabrication approval.",
        "",
        "## Items",
        "",
        "| Item | Side | Status | Edge clearance | Result |",
        "|---|---|---:|---:|---|",
    ]
    for result in review.items:
        item_label = result.item.label or result.item.item_id
        lines.append(
            f"| {item_label} | {result.item.side} | {result.status} | "
            f"{result.minimum_edge_clearance_mm:.4f} mm | {result.message} |"
        )
    lines.extend(("", "## Hard conflicts", ""))
    lines.extend(f"- {item}" for item in review.hard_conflicts or ("None recorded.",))
    lines.extend(("", "## Assumptions and engineering selections", ""))
    lines.extend(f"- {item}" for item in review.assumptions or ("None recorded.",))
    lines.extend(("", "## View conventions", ""))
    lines.extend(f"- {item}" for item in review.view_conventions)
    lines.append("")
    return "\n".join(lines)
