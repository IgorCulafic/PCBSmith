"""Vector floorplan evidence over the existing concept geometry and native layout."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.kicad.concept_review import ConceptReview, _render_svg, _transform
from pcbsmith.kicad.library import _atom, _children, load_footprint, parse_sexpr
from pcbsmith.kicad.native_edits import child, reference
from pcbsmith.operations.file_transaction import atomic_write

if TYPE_CHECKING:
    from pcbsmith.production_readiness import PredesignReadinessBundle

FILES = ("floorplan.json", "floorplan.svg", "floorplan.png", "floorplan-review.json")
NS = "http://www.w3.org/2000/svg"


class FloorplanCorridor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=60)
    references: tuple[str, str]
    purpose: Literal["signal", "return", "access"]
    width_mm: float = Field(gt=0)


def geometry_identity(concept: ConceptReview) -> dict[str, Any]:
    return {
        "project_id": concept.project_id,
        "outline": concept.outline,
        "parts": [
            {
                "reference": r.item.item_id,
                "side": r.item.side,
                "footprint": r.item.footprint_id,
                "at": r.item.anchor_mm,
                "rotation": r.item.rotation_deg % 360,
                "envelope": r.envelope,
            }
            for r in concept.items
        ],
    }


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def floorplan_layout(concept: ConceptReview) -> dict[str, Any]:
    x0, y0, x1, y1 = concept.board_bounds_mm
    if abs(x0) > 1e-6 or abs(y0) > 1e-6 or any(r.item.kind != "footprint" for r in concept.items):
        raise ValueError("generic floorplan adapter requires zero-origin footprint placement")
    return {
        "width_mm": x1,
        "height_mm": y1,
        "placements": {
            r.item.item_id: (*r.item.anchor_mm, r.item.rotation_deg) for r in concept.items
        },
    }


def render_floorplan(
    concept: ConceptReview, roles: dict[str, str], corridors: tuple[FloorplanCorridor, ...]
) -> str:
    """Reuse concept substrate/courtyards; add measured pad markers and planning intent."""
    if set(roles) != {r.item.item_id for r in concept.items}:
        raise ValueError("floorplan roles must cover the exact concept item set")
    svg = ET.fromstring(_render_svg(concept, "front"))
    x, y, width, height = map(float, svg.attrib["viewBox"].split())
    panel_x = x + width + 3
    width += 94
    height = max(height, 29 + len(roles) * 3.2 + len(corridors) * 4)
    svg.set("viewBox", f"{x:g} {y:g} {width:g} {height:g}")
    svg.set("width", "1440")
    svg.set("height", str(round(1440 * height / width)))
    svg.set("data-coordinate-unit", "mm")
    # Expand the background to include the planning key.
    rect = svg.find(f"{{{NS}}}rect")
    if rect is not None:
        rect.set("width", str(width))
        rect.set("height", str(height))

    def element(name: str, attrs: dict[str, str], text: str | None = None) -> ET.Element:
        node = ET.SubElement(svg, f"{{{NS}}}{name}", attrs)
        node.text = text
        return node

    def label(
        xp: float, yp: float, text: str, size: float = 1.9, fill: str = "#e6edf3"
    ) -> ET.Element:
        return element(
            "text",
            {
                "x": str(xp),
                "y": str(yp),
                "font-size": str(size),
                "font-family": "Arial, sans-serif",
                "fill": fill,
            },
            text,
        )

    refs = {r.item.item_id: r.item for r in concept.items}
    for corridor in corridors:
        if any(r not in refs for r in corridor.references):
            raise ValueError("corridor references an absent component")
        a, b = (refs[r].anchor_mm for r in corridor.references)
        element(
            "line",
            {
                "x1": str(a[0]),
                "y1": str(a[1]),
                "x2": str(b[0]),
                "y2": str(b[1]),
                "stroke": "#69d2e7" if corridor.purpose != "return" else "#ffbe79",
                "stroke-width": str(corridor.width_mm),
                "stroke-opacity": "0.22",
                "data-purpose": corridor.purpose,
                "data-name": corridor.name,
            },
        )
    for result in concept.items:
        item = result.item
        if item.footprint_id and item.side == "front":
            fp = load_footprint(
                item.footprint_id,
                source_file=Path(result.footprint_source_file)
                if result.footprint_source_file
                else None,
            ).spec
            for pad in fp.pads:
                px, py = _transform((pad.x_mm, pad.y_mm), item.anchor_mm, item.rotation_deg)
                element(
                    "circle",
                    {
                        "cx": str(px),
                        "cy": str(py),
                        "r": str(max(0.25, min(pad.width_mm, pad.height_mm) / 3)),
                        "fill": "#ffd166" if pad.name == "1" else "#d9e3e8",
                    },
                )
        px, py = item.anchor_mm
        dx, dy = _transform((3, 0), (px, py), item.rotation_deg)
        element(
            "line",
            {
                "x1": str(px),
                "y1": str(py),
                "x2": str(dx),
                "y2": str(dy),
                "stroke": "#ff869a",
                "stroke-width": "0.35",
            },
        )
    _, _, board_width, board_height = concept.board_bounds_mm
    label(1, -1.7, f"{board_width:g} x {board_height:g} mm | top view | origin 0,0", 1.6)
    label(panel_x, y + 5, "VECTOR FLOORPLAN", 2.7)
    label(panel_x, y + 9, "Geometry and intent before PCB placement", 1.7)
    label(panel_x, y + 13, "Gold: pad 1 | pink: local +X direction", 1.6)
    for index, ref in enumerate(roles):
        # Wrapping long roles is intentionally kept in the retained JSON/report.
        label(panel_x, y + 19 + index * 3.2, f"{ref}  {roles[ref][:65]}", 1.7)
    baseline = y + 23 + len(roles) * 3.2
    for index, corridor in enumerate(corridors):
        label(
            panel_x,
            baseline + index * 4,
            f"{corridor.purpose}: {corridor.references[0]} -> {corridor.references[1]}",
            1.6,
        )
    label(panel_x, y + height - 3, "Planning corridors are not copper or electrical proof.", 1.5)
    return ET.tostring(svg, encoding="unicode")


def write_floorplan(
    concept: ConceptReview,
    output: Path,
    roles: dict[str, str],
    corridors: tuple[FloorplanCorridor, ...] = (),
) -> dict[str, Any]:
    import resvg_py

    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in FILES):
        raise ValueError("floorplan output already exists; preserve the reviewed revision")
    svg = render_floorplan(concept, roles, corridors).encode()
    png = resvg_py.svg_to_bytes(svg_string=svg.decode())
    manifest = {
        "schema": "pcbsmith-vector-floorplan-v1",
        "geometry": geometry_identity(concept),
        "geometry_sha256": digest(geometry_identity(concept)),
        "layout_input": floorplan_layout(concept),
        "roles": roles,
        "corridors": [c.model_dump(mode="json") for c in corridors],
        "svg_sha256": hashlib.sha256(svg).hexdigest(),
        "png_sha256": hashlib.sha256(png).hexdigest(),
    }
    atomic_write(output / FILES[0], (json.dumps(manifest, indent=2) + "\n").encode())
    atomic_write(output / FILES[1], svg)
    atomic_write(output / FILES[2], png)
    return manifest


def review_floorplan(
    root: Path, concept: ConceptReview, assertion: dict[str, Any]
) -> dict[str, Any]:
    manifest = json.loads((root / FILES[0]).read_text(encoding="utf-8"))
    if (
        assertion.get("floorplan_sha256")
        != hashlib.sha256((root / FILES[0]).read_bytes()).hexdigest()
    ):
        raise ValueError("floorplan review targets missing/stale floorplan identity")
    if assertion.get("inspected") is not True or assertion.get("presented") is not True:
        raise ValueError("floorplan must be inspected and its preview presented")
    if any(
        not isinstance(assertion.get(k), str) or not assertion[k].strip()
        for k in ("reviewer_id", "rationale", "presentation_reference", "corridor_rationale")
    ):
        raise ValueError("floorplan review needs reviewer, rationale and presentation reference")
    _validate_manifest(root, concept, manifest)
    return assertion


def _validate_manifest(root: Path, concept: ConceptReview, manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != "pcbsmith-vector-floorplan-v1":
        raise ValueError("unsupported floorplan schema")
    if manifest["geometry_sha256"] != digest(geometry_identity(concept)):
        raise ValueError("floorplan geometry differs from approved concept")
    if digest(manifest["geometry"]) != manifest["geometry_sha256"]:
        raise ValueError("floorplan geometry payload changed")
    if digest(manifest["layout_input"]) != digest(floorplan_layout(concept)):
        raise ValueError("floorplan layout is not derived from the concept")
    svg = render_floorplan(
        concept,
        manifest["roles"],
        tuple(FloorplanCorridor.model_validate(c) for c in manifest["corridors"]),
    ).encode()
    if (root / FILES[1]).read_bytes() != svg or hashlib.sha256(svg).hexdigest() != manifest[
        "svg_sha256"
    ]:
        raise ValueError("floorplan SVG differs from exact replay")
    import resvg_py

    actual_png = (root / FILES[2]).read_bytes()
    if hashlib.sha256(actual_png).hexdigest() != manifest[
        "png_sha256"
    ] or actual_png != resvg_py.svg_to_bytes(svg_string=svg.decode()):
        raise ValueError("floorplan preview changed or differs from SVG replay")


def require_floorplan(bundle: PredesignReadinessBundle, root: Path) -> dict[str, Any]:
    # Retention and hashes use the existing readiness evidence mechanism.
    for name in FILES:
        binding = bundle.evidence_files.get("floorplan." + name)
        if binding is None or binding.relative_path != name:
            raise ValueError("new PCB placement requires a retained, reviewed vector floorplan")
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != binding.sha256:
            raise ValueError("floorplan evidence changed")
    assertion = json.loads((root / FILES[3]).read_text(encoding="utf-8"))
    review_floorplan(root, bundle.approval.concept_review, assertion)
    return cast(
        dict[str, Any], json.loads((root / FILES[0]).read_text(encoding="utf-8"))["layout_input"]
    )


def require_native_floorplan(board: Path, layout: dict[str, Any], *, origin_mm: float) -> None:
    require_native_floorplan_text(board.read_text(encoding="utf-8"), layout, origin_mm=origin_mm)


def require_native_floorplan_text(
    payload: str, layout: dict[str, Any], *, origin_mm: float
) -> None:
    """Check a planned native delta before writing the candidate."""
    tree = parse_sexpr(payload)
    footprints = _children(tree, "footprint")
    if len(footprints) != len(layout["placements"]):
        raise ValueError("native footprint count differs from floorplan")
    seen = set()
    for fp in footprints:
        ref = reference(fp)
        if ref not in layout["placements"] or ref in seen:
            raise ValueError("native component identity differs from floorplan")
        seen.add(ref)
        coords = [float(_atom(x)) for x in child(fp, "at")[1:]]
        wanted = layout["placements"][ref]
        angle = coords[2] if len(coords) == 3 else 0
        if (
            abs(coords[0] - origin_mm - wanted[0]) > 5.1e-4
            or abs(coords[1] - origin_mm - wanted[1]) > 5.1e-4
            or abs((angle - wanted[2] + 180) % 360 - 180) > 1e-4
            or _atom(child(fp, "layer")[1]) != "F.Cu"
        ):
            raise ValueError(f"native placement differs from floorplan: {ref}")
    # The generic adapter currently owns a rectangular zero-origin board outline.
    lines = [n for n in _children(tree, "gr_line") if _atom(child(n, "layer")[1]) == "Edge.Cuts"]
    corners = [
        (origin_mm, origin_mm),
        (origin_mm + layout["width_mm"], origin_mm),
        (origin_mm + layout["width_mm"], origin_mm + layout["height_mm"]),
        (origin_mm, origin_mm + layout["height_mm"]),
    ]

    def edge(a: Sequence[float], b: Sequence[float]) -> tuple[tuple[float, ...], ...]:
        return tuple(sorted((tuple(round(v, 4) for v in a), tuple(round(v, 4) for v in b))))

    actual = [
        edge(
            [float(_atom(v)) for v in child(n, "start")[1:]],
            [float(_atom(v)) for v in child(n, "end")[1:]],
        )
        for n in lines
    ]
    rectangles = [
        n for n in _children(tree, "gr_rect") if _atom(child(n, "layer")[1]) == "Edge.Cuts"
    ]
    if len(rectangles) == 1 and not actual:
        rect = rectangles[0]
        sx, sy = (float(_atom(v)) for v in child(rect, "start")[1:])
        ex, ey = (float(_atom(v)) for v in child(rect, "end")[1:])
        points = [(sx, sy), (ex, sy), (ex, ey), (sx, ey)]
        actual = [edge(points[i], points[(i + 1) % 4]) for i in range(4)]
    elif rectangles:
        raise ValueError("native outline has unexpected extra geometry")
    if any(
        _atom(child(n, "layer")[1]) == "Edge.Cuts"
        for kind in ("gr_poly", "gr_arc", "gr_circle")
        for n in _children(tree, kind)
    ):
        raise ValueError("native outline has unsupported extra geometry")
    expected = [edge(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    if sorted(actual) != sorted(expected):
        raise ValueError("native outline differs from floorplan")
