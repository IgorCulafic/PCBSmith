"""Official-KiCad-footprint library: parse, measure, and embed `.kicad_mod`.

The geometry PCBSmith places and routes against comes from the official KiCad
footprint files (vendored under ``ai_assets/kicad_footprints``, falling back
to the installed share directory). The same parsed tree is embedded verbatim
into generated boards — with position, reference, net, and parity clauses
injected — so boards carry the real pads, silkscreen (including polarity
marks), courtyards, and 3D model references instead of hand-drawn
approximations. See docs/pcb-design-rules.md section 8.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from uuid import UUID

from pcbsmith.hole_geometry import HoleGeometry, HolePlating, HoleShape
from pcbsmith.kicad.identity import stable_kicad_uuid


class FootprintLibraryError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Minimal s-expression layer. Atoms stay verbatim strings so numbers survive
# a parse/serialize round trip unchanged; quoted strings keep a marker.


@dataclass
class QuotedString:
    value: str


SExpr = list["SExpr"] | QuotedString | str
SList = list[SExpr]


def parse_sexpr(text: str) -> SList:
    tokens = _tokenize(text)
    index = 0

    def parse_node() -> SExpr:
        nonlocal index
        token = tokens[index]
        index += 1
        if token == "(":
            node: SList = []
            while tokens[index] != ")":
                node.append(parse_node())
            index += 1
            return node
        if token == ")":
            raise FootprintLibraryError("Unbalanced ')' in s-expression.")
        if isinstance(token, QuotedString):
            return token
        return str(token)

    node = parse_node()
    if index != len(tokens):
        raise FootprintLibraryError("Trailing tokens after s-expression.")
    if not isinstance(node, list):
        raise FootprintLibraryError("Expected a list at the top level.")
    return node


def _tokenize(text: str) -> list[str | QuotedString]:
    tokens: list[str | QuotedString] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in " \t\r\n":
            index += 1
        elif char in "()":
            tokens.append(char)
            index += 1
        elif char == '"':
            index += 1
            chars: list[str] = []
            while index < length and text[index] != '"':
                if text[index] == "\\" and index + 1 < length:
                    chars.append(text[index + 1])
                    index += 2
                else:
                    chars.append(text[index])
                    index += 1
            if index >= length:
                raise FootprintLibraryError("Unterminated string in s-expression.")
            index += 1
            tokens.append(QuotedString("".join(chars)))
        else:
            start = index
            while index < length and text[index] not in ' \t\r\n()"':
                index += 1
            tokens.append(text[start:index])
    return tokens


def serialize_sexpr(node: SExpr, indent: int = 0) -> str:
    if isinstance(node, QuotedString):
        escaped = node.value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(node, str):
        return node
    pad = "  " * indent
    inner_pad = "  " * (indent + 1)
    if not any(isinstance(child, list) for child in node):
        return "(" + " ".join(serialize_sexpr(child) for child in node) + ")"
    parts = ["("]
    head: list[str] = []
    children = list(node)
    while children and not isinstance(children[0], list):
        head.append(serialize_sexpr(children.pop(0)))
    parts[0] += " ".join(head)
    for child in children:
        parts.append(inner_pad + serialize_sexpr(child, indent + 1))
    parts.append(pad + ")")
    return "\n".join(parts)


def _atom(node: SExpr) -> str:
    if isinstance(node, QuotedString):
        return node.value
    if isinstance(node, str):
        return node
    raise FootprintLibraryError(f"Expected an atom, got a list: {node!r}")


def _children(node: SList, name: str) -> list[SList]:
    return [
        child
        for child in node
        if isinstance(child, list) and child and _safe_head(child) == name
    ]


def _safe_head(node: SList) -> str | None:
    head = node[0]
    if isinstance(head, str):
        return head
    if isinstance(head, QuotedString):
        return head.value
    return None


# --------------------------------------------------------------------------
# Geometry specs used by the placer/router/preview.


@dataclass(frozen=True)
class PadSourceAnchor:
    """Unmodified KiCad pad anchor before any routing-bbox folding."""

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class CustomPadSource:
    """Canonical custom-pad source retained for a future exact parser.

    The current routing model folds custom primitives into a bounding box.
    Keeping the geometry-affecting source clauses separate prevents a later
    mask checker from accidentally treating that box as an exact aperture.
    """

    canonical_clauses: tuple[str, ...]
    unsupported_reason: str


@dataclass(frozen=True)
class PadSpec:
    name: str
    x_mm: float
    y_mm: float
    kind: str
    width_mm: float
    height_mm: float
    drill_mm: float = 0.0
    # The pad's own rotation within the footprint (third `at` element).
    # QFN side pads carry 90 here; ignoring it mis-orients the pad body.
    angle_deg: float = 0.0
    # KiCad pad shape ("circle", "oval", "rect", "roundrect", ...).
    # Rect-family corners stick out past the stadium model; the router
    # inflates them as obstacles (kicad-cli DRC caught the corner cuts).
    # Canonical physical drill/slot geometry. ``drill_mm`` remains the
    # max-axis compatibility projection until every consumer is migrated.
    hole: HoleGeometry | None = None

    def __post_init__(self) -> None:
        if self.hole is None and self.drill_mm > 0:
            plating = (
                HolePlating.PLATED
                if self.kind in {"tht", "thru_hole"}
                else HolePlating.NON_PLATED
            )
            object.__setattr__(
                self,
                "hole",
                HoleGeometry(
                    shape=HoleShape.ROUND,
                    width_mm=self.drill_mm,
                    height_mm=self.drill_mm,
                    rotation_deg=self.angle_deg,
                    plating=plating,
                ),
            )
        elif self.hole is not None:
            if self.drill_mm > 0 and not math.isclose(
                self.drill_mm,
                self.hole.major_mm,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError("drill_mm must equal the hole's maximum axis")
            object.__setattr__(self, "drill_mm", self.hole.major_mm)
    shape: str = ""
    # Source fields are defaulted so manually constructed/legacy PadSpecs keep
    # their existing meaning. An empty layer tuple means unknown/unparsed,
    # not "no layers"; parser-created specs always preserve the source clause.
    source_anchor: PadSourceAnchor | None = None
    layers: tuple[str, ...] = ()
    roundrect_rratio: float | None = None
    chamfer_ratio: float | None = None
    chamfer_positions: tuple[str, ...] = ()
    solder_mask_margin_mm: float | None = None
    solder_mask_margin_ratio: float | None = None
    custom_source: CustomPadSource | None = None


@dataclass(frozen=True)
class SilkLine:
    """A silkscreen line in footprint-local mm (used by the review plot)."""

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class SilkText:
    """A small mark text (for example "+" / "-") on F.SilkS, local mm."""

    text: str
    x: float
    y: float


@dataclass(frozen=True)
class FootprintSpec:
    pads: tuple[PadSpec, ...]
    fab_rect: tuple[float, float, float, float]
    silk_rect: tuple[float, float, float, float] | None
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    attr: str
    is_connector: bool = False
    silk_marks: tuple[SilkLine | SilkText, ...] = ()
    board_only: bool = False
    # Convex hull of the F.CrtYd layer when the footprint draws one; None
    # means the footprint has no courtyard layer and callers must
    # approximate. A hull (not a bbox) because rounded courtyards such as
    # TO-92 or radial-can circles would otherwise false-positive at the
    # corners against KiCad's exact-shape check.
    courtyard_hull: tuple[tuple[float, float], ...] | None = None
    # Convex hull of the F.Fab body drawing (circles sampled); the
    # silkscreen outline sits just outside it, so it is the honest
    # underestimating proxy for silk-vs-part checks.
    fab_hull: tuple[tuple[float, float], ...] | None = None
    # Default Reference label placement from the footprint file:
    # (local x, local y, font size). None when the file hides it.
    reference_label: tuple[float, float, float] | None = None

    def pads_named(self, name: str) -> tuple[PadSpec, ...]:
        matches = tuple(pad for pad in self.pads if pad.name == name)
        if not matches:
            raise KeyError(name)
        return matches


def rotate_offset(dx: float, dy: float, rotation: float) -> tuple[float, float]:
    """Rotate a footprint-local offset by the KiCad footprint rotation.

    KiCad rotations are counter-clockwise on screen; board coordinates have
    y pointing down, so +90 maps (right, down) to (up, right). Verified live
    against KiCad DRC parity (a wrong transform strands every rotated pad).
    """
    normalized = rotation % 360
    if normalized == 0:
        return (dx, dy)
    if normalized == 90:
        return (dy, -dx)
    if normalized == 180:
        return (-dx, -dy)
    if normalized == 270:
        return (-dy, dx)
    # Arbitrary angles (e.g. tangent-following art placements) use the same
    # convention: counter-clockwise on screen with y pointing down.
    radians = math.radians(normalized)
    cos_r, sin_r = math.cos(radians), math.sin(radians)
    return (dx * cos_r + dy * sin_r, -dx * sin_r + dy * cos_r)


# --------------------------------------------------------------------------
# Loading and measuring official footprints.

VENDORED_DIR = Path(__file__).resolve().parents[3] / "ai_assets" / "kicad_footprints"
INSTALLED_SHARE_DIRS = (
    Path(r"C:\Program Files\KiCad\10.0\share\kicad\footprints"),
    Path(r"C:\Program Files\KiCad\9.0\share\kicad\footprints"),
)
BODY_MARGIN_MM = 0.4


@dataclass(frozen=True)
class ImportedFootprint:
    library_id: str
    spec: FootprintSpec
    source_file: Path
    tree: SList = field(hash=False, compare=False, default_factory=list)


CUSTOM_PAD_MASK_UNSUPPORTED_REASON = (
    "custom pad mask geometry requires exact anchor/primitive union parsing"
)


def _optional_float_clause(node: SList, name: str) -> float | None:
    clauses = _children(node, name)
    if not clauses:
        return None
    clause = clauses[0]
    if len(clause) < 2 or isinstance(clause[1], list):
        raise FootprintLibraryError(f"Malformed {name} clause: {clause!r}")
    return float(_atom(clause[1]))


def _custom_pad_source(pad: SList) -> CustomPadSource:
    geometry_clauses = [
        child
        for child in pad
        if isinstance(child, list) and _safe_head(child) in {"options", "primitives"}
    ]
    return CustomPadSource(
        canonical_clauses=tuple(serialize_sexpr(clause) for clause in geometry_clauses),
        unsupported_reason=CUSTOM_PAD_MASK_UNSUPPORTED_REASON,
    )


def _footprint_file(library_id: str) -> Path:
    try:
        library, name = library_id.split(":", 1)
    except ValueError as exc:
        raise FootprintLibraryError(
            f"Footprint id must be 'Library:Name', got {library_id!r}."
        ) from exc
    vendored = VENDORED_DIR / f"{library}__{name}.kicad_mod"
    if vendored.exists():
        return vendored
    for share in INSTALLED_SHARE_DIRS:
        candidate = share / f"{library}.pretty" / f"{name}.kicad_mod"
        if candidate.exists():
            return candidate
    raise FootprintLibraryError(
        f"Footprint {library_id} not found. Vendor it into {VENDORED_DIR} or "
        "install the KiCad footprint libraries."
    )


@cache
def load_footprint(library_id: str) -> ImportedFootprint:
    source = _footprint_file(library_id)
    tree = parse_sexpr(source.read_text(encoding="utf-8"))
    if _safe_head(tree) != "footprint":
        raise FootprintLibraryError(f"{source} is not a footprint file.")
    spec = _measure(tree, library_id)
    return ImportedFootprint(
        library_id=library_id, spec=spec, source_file=source, tree=tree
    )


def _measure(tree: SList, library_id: str) -> FootprintSpec:
    pads: list[PadSpec] = []
    silk_lines: list[SilkLine] = []
    courtyard: list[tuple[float, float]] = []
    fab_points: list[tuple[float, float]] = []
    attr = "smd"
    board_only = False

    for attr_node in _children(tree, "attr"):
        flags = [_atom(child) for child in attr_node[1:] if not isinstance(child, list)]
        if "through_hole" in flags:
            attr = "through_hole"
        if "board_only" in flags:
            board_only = True

    for pad in _children(tree, "pad"):
        name = _atom(pad[1])
        kind = _atom(pad[2])
        pad_shape = _atom(pad[3]) if not isinstance(pad[3], list) else ""
        at = _children(pad, "at")
        size = _children(pad, "size")
        drill_nodes = _children(pad, "drill")
        x_mm = float(_atom(at[0][1])) if at else 0.0
        y_mm = float(_atom(at[0][2])) if at else 0.0
        angle_deg = (
            float(_atom(at[0][3]))
            if at and len(at[0]) > 3 and not isinstance(at[0][3], list)
            else 0.0
        )
        width = float(_atom(size[0][1])) if size else 0.0
        height = float(_atom(size[0][2])) if size else width
        source_anchor = PadSourceAnchor(
            x_mm=x_mm,
            y_mm=y_mm,
            width_mm=width,
            height_mm=height,
        )
        layer_names = tuple(
            _atom(layer)
            for layers_node in _children(pad, "layers")
            for layer in layers_node[1:]
            if not isinstance(layer, list)
        )
        roundrect_rratio = _optional_float_clause(pad, "roundrect_rratio")
        chamfer_ratio = _optional_float_clause(pad, "chamfer_ratio")
        chamfer_positions = tuple(
            _atom(position)
            for chamfer_node in _children(pad, "chamfer")
            for position in chamfer_node[1:]
            if not isinstance(position, list)
        )
        solder_mask_margin = _optional_float_clause(pad, "solder_mask_margin")
        solder_mask_margin_ratio = _optional_float_clause(
            pad, "solder_mask_margin_ratio"
        )
        custom_source = _custom_pad_source(pad) if pad_shape == "custom" else None
        hole = (
            _parse_hole_geometry(drill_nodes[0], kind, angle_deg)
            if drill_nodes
            else None
        )
        drill = hole.major_mm if hole is not None else 0.0
        if kind == "np_thru_hole":
            # Keep NPTH distinct: no copper, but the HOLE is a physical
            # obstacle (kicad-cli hole_clearance caught routed tracks
            # crossing the USB-C shell holes the collapsed "tht" hid).
            kind = "npth"
        elif kind == "thru_hole":
            kind = "tht"
        if pad_shape == "custom":
            # A custom pad's (size w h) is only its ANCHOR; the copper
            # is the primitives. Model the true extents or every
            # consumer under-sizes the pad (the SHT31 EP is 1.0x1.7 but
            # anchors at 1.0x1.0 - kicad-cli caught a via parked on the
            # unmodelled lobe).
            extent = _custom_pad_extents(pad, width, height)
            if extent is not None:
                (min_x, min_y, max_x, max_y) = extent
                offset_x = (min_x + max_x) / 2
                offset_y = (min_y + max_y) / 2
                theta = math.radians(angle_deg)
                # Pad-local -> footprint frame (KiCad CCW, y down).
                x_mm += offset_x * math.cos(theta) + offset_y * math.sin(theta)
                y_mm += -offset_x * math.sin(theta) + offset_y * math.cos(theta)
                width = max_x - min_x
                height = max_y - min_y
        pads.append(
            PadSpec(
                name=name,
                x_mm=x_mm,
                y_mm=y_mm,
                kind=kind,
                width_mm=width,
                height_mm=height,
                drill_mm=drill,
                angle_deg=angle_deg,
                hole=hole,
                shape=pad_shape,
                source_anchor=source_anchor,
                layers=layer_names,
                roundrect_rratio=roundrect_rratio,
                chamfer_ratio=chamfer_ratio,
                chamfer_positions=chamfer_positions,
                solder_mask_margin_mm=solder_mask_margin,
                solder_mask_margin_ratio=solder_mask_margin_ratio,
                custom_source=custom_source,
            )
        )

    for shape_name in ("fp_line", "fp_rect", "fp_circle", "fp_poly", "fp_arc"):
        for shape in _children(tree, shape_name):
            layer_nodes = _children(shape, "layer")
            layer = _atom(layer_nodes[0][1]) if layer_nodes else ""
            points = _shape_points(shape)
            if shape_name == "fp_circle":
                # A circle parses as (end, center); its extent is the
                # center plus/minus the radius, not those two points —
                # radial-cap courtyards degenerate to a line otherwise.
                # Courtyards and fab bodies get a dense ring so the
                # convex hull tracks the curve; other layers only need
                # the bounding corners.
                samples = 24 if layer in ("F.CrtYd", "F.Fab") else 2
                points = _circle_extent_points(shape, points, samples)
            elif shape_name == "fp_rect" and len(points) == 2:
                # A rect parses as its two DIAGONAL corners; the convex
                # hull of those is a line, so an fp_rect-drawn courtyard
                # was silently discarded (len<3) and the virtual check
                # went blind — terminal blocks, D9 discs, and solder-wire
                # pads all draw their F.CrtYd this way (caught live by
                # kicad-cli on the compacted flyback). Expand to all
                # four corners.
                (x1, y1), (x2, y2) = points
                points = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            if layer == "F.CrtYd":
                courtyard.extend(points)
            elif layer == "F.Fab":
                fab_points.extend(points)
            elif layer == "F.SilkS" and shape_name in ("fp_line", "fp_rect"):
                if shape_name == "fp_line" and len(points) == 2:
                    (x1, y1), (x2, y2) = points
                    silk_lines.append(SilkLine(x1=x1, y1=y1, x2=x2, y2=y2))
                elif shape_name == "fp_rect" and len(points) == 2:
                    (x1, y1), (x2, y2) = points
                    silk_lines.extend(
                        (
                            SilkLine(x1=x1, y1=y1, x2=x2, y2=y1),
                            SilkLine(x1=x2, y1=y1, x2=x2, y2=y2),
                            SilkLine(x1=x2, y1=y2, x2=x1, y2=y2),
                            SilkLine(x1=x1, y1=y2, x2=x1, y2=y1),
                        )
                    )

    extent_points = courtyard or [
        point
        for pad in pads
        for point in (
            (pad.x_mm - pad.width_mm / 2, pad.y_mm - pad.height_mm / 2),
            (pad.x_mm + pad.width_mm / 2, pad.y_mm + pad.height_mm / 2),
        )
    ]
    if not extent_points:
        raise FootprintLibraryError(f"{library_id} has no measurable geometry.")
    xs = [x for x, _ in extent_points]
    ys = [y for _, y in extent_points]
    margin = 0.0 if courtyard else BODY_MARGIN_MM

    fab_xs = [x for x, _ in fab_points] or xs
    fab_ys = [y for _, y in fab_points] or ys

    courtyard_hull = _convex_hull(courtyard) if courtyard else None
    if courtyard_hull is not None and len(courtyard_hull) < 3:
        courtyard_hull = None  # a line or point constrains nothing
    fab_hull = _convex_hull(fab_points) if fab_points else None
    if fab_hull is not None and len(fab_hull) < 3:
        fab_hull = None

    reference_label = None
    for prop in _children(tree, "property"):
        if _atom(prop[1]) != "Reference":
            continue
        hidden = any(
            _safe_head(child) == "hide" and _atom(child[1]) == "yes"
            for child in prop
            if isinstance(child, list) and len(child) > 1
        )
        ats = _children(prop, "at")
        if hidden or not ats:
            continue
        font_size = 1.27
        for effects in _children(prop, "effects"):
            for font in _children(effects, "font"):
                for size_node in _children(font, "size"):
                    font_size = float(_atom(size_node[1]))
        reference_label = (
            float(_atom(ats[0][1])),
            float(_atom(ats[0][2])),
            font_size,
        )

    return FootprintSpec(
        pads=tuple(pads),
        fab_rect=(min(fab_xs), min(fab_ys), max(fab_xs), max(fab_ys)),
        silk_rect=None,
        x_min=min(xs) - margin,
        x_max=max(xs) + margin,
        y_min=min(ys) - margin,
        y_max=max(ys) + margin,
        attr=attr,
        is_connector=library_id.startswith("Connector_"),
        silk_marks=tuple(silk_lines),
        board_only=board_only,
        courtyard_hull=courtyard_hull,
        fab_hull=fab_hull,
        reference_label=reference_label,
    )


def _custom_pad_extents(
    pad: SList, anchor_width: float, anchor_height: float
) -> tuple[float, float, float, float] | None:
    """Pad-local bbox of a custom pad's copper primitives, unioned with
    the anchor shape. Arcs contribute start/mid/end (honest under- not
    over-estimate between samples); stroke widths widen the bbox."""
    points: list[tuple[float, float]] = []
    stroke = 0.0
    for group in _children(pad, "primitives"):
        for name in ("gr_poly", "gr_rect", "gr_line", "gr_arc", "gr_circle"):
            for prim in _children(group, name):
                prim_points = _shape_points(prim)
                if name == "gr_circle":
                    prim_points = _circle_extent_points(prim, prim_points)
                points.extend(prim_points)
                for width_node in _children(prim, "width"):
                    stroke = max(stroke, float(_atom(width_node[1])))
                for stroke_node in _children(prim, "stroke"):
                    for width_node in _children(stroke_node, "width"):
                        stroke = max(stroke, float(_atom(width_node[1])))
    if not points:
        return None
    points.extend(
        [
            (-anchor_width / 2, -anchor_height / 2),
            (anchor_width / 2, anchor_height / 2),
        ]
    )
    half = stroke / 2
    return (
        min(x for x, _y in points) - half,
        min(y for _x, y in points) - half,
        max(x for x, _y in points) + half,
        max(y for _x, y in points) + half,
    )


def _circle_extent_points(
    shape: SList, points: list[tuple[float, float]], samples: int = 2
) -> list[tuple[float, float]]:
    centers = _children(shape, "center")
    ends = _children(shape, "end")
    if not centers or not ends:
        return points
    cx = float(_atom(centers[0][1]))
    cy = float(_atom(centers[0][2]))
    ex = float(_atom(ends[0][1]))
    ey = float(_atom(ends[0][2]))
    radius = math.hypot(ex - cx, ey - cy)
    if samples <= 2:
        return [(cx - radius, cy - radius), (cx + radius, cy + radius)]
    return [
        (
            cx + radius * math.cos(2 * math.pi * step / samples),
            cy + radius * math.sin(2 * math.pi * step / samples),
        )
        for step in range(samples)
    ]


def _convex_hull(
    points: list[tuple[float, float]]
) -> tuple[tuple[float, float], ...]:
    """Monotone-chain convex hull (CCW), degenerate inputs passed through."""
    unique = sorted(set(points))
    if len(unique) <= 2:
        return tuple(unique)

    def cross(o: tuple[float, float], a: tuple[float, float],
              b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def _shape_points(shape: SList) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for key in ("start", "end", "mid", "center"):
        for node in _children(shape, key):
            points.append((float(_atom(node[1])), float(_atom(node[2]))))
    for pts in _children(shape, "pts"):
        for xy in _children(pts, "xy"):
            points.append((float(_atom(xy[1])), float(_atom(xy[2]))))
    return points


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True

def _parse_hole_geometry(
    drill_node: SList,
    pad_kind: str,
    angle_deg: float,
) -> HoleGeometry:
    """Preserve KiCad ``drill`` axes and metadata before pad-kind folding."""
    atoms = [
        _atom(child)
        for child in drill_node[1:]
        if not isinstance(child, list)
    ]
    shape = HoleShape.OVAL if atoms and atoms[0] == "oval" else HoleShape.ROUND
    dimensions = [float(atom) for atom in atoms if _is_number(atom)]
    needed = 2 if shape is HoleShape.OVAL else 1
    if len(dimensions) < needed:
        raise FootprintLibraryError(
            f"Malformed {shape.value} drill geometry: {drill_node!r}"
        )
    width = dimensions[0]
    height = dimensions[1] if shape is HoleShape.OVAL else width
    offset_nodes = _children(drill_node, "offset")
    offset_x = float(_atom(offset_nodes[0][1])) if offset_nodes else 0.0
    offset_y = float(_atom(offset_nodes[0][2])) if offset_nodes else 0.0
    plating = (
        HolePlating.PLATED
        if pad_kind == "thru_hole"
        else HolePlating.NON_PLATED
    )
    return HoleGeometry(
        shape=shape,
        width_mm=width,
        height_mm=height,
        rotation_deg=angle_deg,
        plating=plating,
        offset_x_mm=offset_x,
        offset_y_mm=offset_y,
    )


# --------------------------------------------------------------------------
# Embedding an imported footprint into a generated board.

_STRIP_TOKENS = {
    "version",
    "generator",
    "generator_version",
    "embedded_fonts",
    "uuid",
    "tstamp",
}


def render_embedded_footprint(
    imported: ImportedFootprint,
    *,
    reference: str,
    value: str,
    x_mm: float,
    y_mm: float,
    rotation: float,
    uuid_path: str,
    pad_nets: dict[str, tuple[int, str]],
    extra_fields: tuple[tuple[str, str], ...] = (),
    extra_silk_texts: tuple[tuple[str, float, float, float], ...] = (),
    force_board_only: bool = False,
    flip: bool = False,
    hide_reference: bool = False,
    reference_at: tuple[float, float, float] | None = None,
    identity_occurrence: int = 0,
) -> str:
    tree = _as_list(_deep_copy(imported.tree))
    tree[1] = QuotedString(imported.library_id)
    footprint_uuid = stable_kicad_uuid(
        "board-footprint",
        uuid_path.strip("/"),
        reference,
        str(identity_occurrence),
    )
    if flip:
        _flip_tree(tree)
    body = [
        child
        for child in tree[2:]
        if not (isinstance(child, list) and _safe_head(child) in _STRIP_TOKENS)
    ]

    at_clause: list[SExpr] = ["at", _fmt(x_mm), _fmt(y_mm)]
    if rotation:
        at_clause.append(_fmt(rotation))
    head: list[SExpr] = [
        ["uuid", QuotedString(footprint_uuid)],
        at_clause,
    ]

    pad_occurrences: dict[str, int] = {}
    for child in body:
        if isinstance(child, list) and _safe_head(child) == "property":
            prop_name = _atom(child[1])
            if prop_name == "Reference":
                child[2] = QuotedString(reference)
                if hide_reference:
                    child.append(["hide", "yes"])
                elif force_board_only:
                    # Mounting holes need no visible label; the library text
                    # sits above the hole and crossed the board edge.
                    child.append(["hide", "yes"])
            elif prop_name == "Value":
                child[2] = QuotedString(value)
        if isinstance(child, list) and _safe_head(child) == "attr" and force_board_only:
            flags = [_atom(flag) for flag in child[1:] if not isinstance(flag, list)]
            if "board_only" not in flags:
                child.insert(1, "board_only")
        if isinstance(child, list) and _safe_head(child) == "pad":
            pad_name = _atom(child[1])
            pad_occurrence = pad_occurrences.get(pad_name, 0)
            pad_occurrences[pad_name] = pad_occurrence + 1
            bound = pad_nets.get(pad_name)
            if bound is not None:
                _number, net_name = bound
                # KiCad 10's canonical board grammar binds every board item,
                # including pads, by net name.  It still accepts the legacy
                # numbered pad form, but rewrites it to this named-only form
                # on save.
                child.append(["net", QuotedString(net_name)])
            _set_uuid(
                child,
                stable_kicad_uuid(
                    "board-footprint-child",
                    footprint_uuid,
                    "pad",
                    pad_name,
                    str(pad_occurrence),
                ),
            )
            if rotation:
                _add_rotation(child, rotation)
        if (
            rotation
            and isinstance(child, list)
            and _safe_head(child) in ("property", "fp_text")
        ):
            # KiCad board files store pad and text angles as TOTAL angles
            # (footprint + local); rotating the footprint without adjusting
            # them leaves pads physically unrotated (live DRC shorted every
            # neighbouring pin of a rotated TO-263 before this fix).
            _add_rotation(child, rotation)

    if reference_at is not None:
        # Move the reference label to a caller-chosen footprint-local spot
        # (dense layouts park labels clear of neighbours). The angle is a
        # TOTAL angle like every board-file text angle: 0 keeps it upright.
        for child in body:
            if isinstance(child, list) and _safe_head(child) == "property":
                if _atom(child[1]) == "Reference":
                    for at in _children(child, "at"):
                        at[1:] = [
                            _fmt(reference_at[0]),
                            _fmt(reference_at[1]),
                            _fmt(reference_at[2]),
                        ]

    _ensure_board_standard_properties(body, rotation)
    standard_field_values = {
        name: field_value
        for name, field_value in extra_fields
        if name in {"Datasheet", "Description"}
    }
    for child in body:
        if (
            isinstance(child, list)
            and _safe_head(child) == "property"
            and len(child) > 2
            and _atom(child[1]) in standard_field_values
        ):
            child[2] = QuotedString(standard_field_values[_atom(child[1])])

    if force_board_only and not _children_named(body, "attr"):
        body.append(["attr", "board_only", "exclude_from_pos_files", "exclude_from_bom"])

    silk_text_nodes: list[SExpr] = [
        _silk_text_node(
            text,
            x,
            y,
            angle,
            stable_kicad_uuid(
                "board-footprint-child",
                footprint_uuid,
                "extra-silk",
                str(index),
            ),
        )
        for index, (text, x, y, angle) in enumerate(extra_silk_texts)
    ]
    field_properties: list[SExpr] = [
        _hidden_property(
            name,
            field_value,
            stable_kicad_uuid(
                "board-footprint-child",
                footprint_uuid,
                "extra-field",
                name,
                str(index),
            ),
        )
        for index, (name, field_value) in enumerate(extra_fields)
        if name not in {"Reference", "Value", "Footprint", "Datasheet", "Description"}
    ]
    final_children = [*body, *silk_text_nodes, *field_properties]
    _assign_footprint_child_uuids(final_children, footprint_uuid=footprint_uuid)
    path_clause: list[SExpr] = [
        ["path", QuotedString(_stable_schematic_path(uuid_path, footprint_uuid))]
    ]

    tree[2:] = [*head, *final_children, *path_clause]
    return "  " + serialize_sexpr(tree, indent=1)


def _ensure_board_standard_properties(body: SList, rotation: float) -> None:
    """Emit standard empty fields that KiCad otherwise creates with UUID4s."""
    property_names = {
        _atom(child[1])
        for child in body
        if isinstance(child, list)
        and _safe_head(child) == "property"
        and len(child) > 1
    }
    insertion = next(
        (
            index + 1
            for index, child in enumerate(body)
            if isinstance(child, list)
            and _safe_head(child) == "property"
            and len(child) > 1
            and _atom(child[1]) == "Value"
        ),
        len(body),
    )
    missing: list[SExpr] = []
    for name in ("Datasheet", "Description"):
        if name in property_names:
            continue
        missing.append(
            [
                "property",
                QuotedString(name),
                QuotedString(""),
                ["at", "0", "0", _fmt(rotation % 360)],
                ["layer", QuotedString("F.Fab")],
                ["hide", "yes"],
                ["effects", ["font", ["size", "1.27", "1.27"]]],
            ]
        )
    body[insertion:insertion] = missing


def _set_uuid(node: SList, value: str) -> None:
    """Replace every legacy identity clause on one KiCad object with one UUID."""
    node[:] = [
        child
        for child in node
        if not (
            isinstance(child, list)
            and child
            and _safe_head(child) in {"uuid", "tstamp"}
        )
    ]
    node.append(["uuid", QuotedString(value)])


_FOOTPRINT_IDENTITY_HEADS = frozenset(
    {
        "property",
        "fp_arc",
        "fp_bezier",
        "fp_circle",
        "fp_curve",
        "fp_line",
        "fp_poly",
        "fp_rect",
        "fp_text",
        "fp_text_box",
        "group",
        "pad",
        "zone",
    }
)


def _identityless_copy(node: SList) -> SList:
    """Copy one object while removing identity clauses at every depth."""
    copied: SList = []
    for child in node:
        if isinstance(child, list):
            if child and _safe_head(child) in {"uuid", "tstamp"}:
                continue
            copied.append(_identityless_copy(child))
        elif isinstance(child, QuotedString):
            copied.append(QuotedString(child.value))
        else:
            copied.append(child)
    return copied


def _assign_footprint_child_uuids(
    children: SList,
    *,
    footprint_uuid: str,
) -> None:
    """Assign every placed footprint object a final-semantic UUID5.

    KiCad 10 creates UUID4 values when old or externally generated footprint
    properties and graphics omit identities.  The occurrence index keeps
    byte-identical duplicate objects distinct without depending on source
    library UUIDs, which may themselves collide between placed instances.
    """
    occurrences: dict[tuple[str, str], int] = {}
    for child in children:
        if not isinstance(child, list) or not child:
            continue
        child_head = _safe_head(child)
        if child_head not in _FOOTPRINT_IDENTITY_HEADS:
            continue
        semantic = serialize_sexpr(_identityless_copy(child))
        identity = (child_head, semantic)
        occurrence = occurrences.get(identity, 0)
        occurrences[identity] = occurrence + 1
        _set_uuid(
            child,
            stable_kicad_uuid(
                "board-footprint-child-v2",
                footprint_uuid,
                child_head,
                semantic,
                str(occurrence),
            ),
        )


def _stable_schematic_path(uuid_path: str, footprint_uuid: str) -> str:
    """Return a KiCad-valid deterministic schematic instance path.

    Real schematic paths already consist of UUID atoms and must remain intact
    for schematic-parity checks.  Synthetic/fallback path atoms are encoded
    independently so KiCad does not replace them with random UUID4 values on
    save.
    """
    atoms = tuple(atom for atom in uuid_path.strip("/").split("/") if atom)
    if not atoms:
        return "/" + stable_kicad_uuid(
            "board-footprint-path-v1", footprint_uuid, "0", "empty"
        )
    stable_atoms: list[str] = []
    for index, atom in enumerate(atoms):
        try:
            stable_atoms.append(str(UUID(atom)))
        except ValueError:
            stable_atoms.append(
                stable_kicad_uuid(
                    "board-footprint-path-v1",
                    footprint_uuid,
                    str(index),
                    atom,
                )
            )
    return "/" + "/".join(stable_atoms)


def _add_rotation(node: SList, rotation: float) -> None:
    for at in _children(node, "at"):
        while len(at) < 4:
            at.append("0")
        at[3] = _fmt((float(_atom(at[3])) + rotation) % 360)


_COORD_HEADS = ("at", "start", "end", "center", "mid", "xy")


def _flip_tree(tree: SList) -> None:
    """Mirror a footprint tree onto the back side, KiCad-file style: negate
    x coordinates and angles, swap F./B. layer names, and mark text mirrored.
    Board files store BACK footprints in this flipped representation."""
    head = _safe_head(tree)
    if head == "layer" and len(tree) >= 2:
        tree[1] = QuotedString(_swap_layer(_atom(tree[1])))
        return
    if head == "layers":
        for index in range(1, len(tree)):
            if not isinstance(tree[index], list):
                tree[index] = QuotedString(_swap_layer(_atom(tree[index])))
        return
    if head in _COORD_HEADS and len(tree) >= 3:
        x_atom = tree[1]
        if not isinstance(x_atom, list):
            tree[1] = _fmt(-float(_atom(x_atom)))
        if head == "at" and len(tree) >= 4 and not isinstance(tree[3], list):
            tree[3] = _fmt((-float(_atom(tree[3]))) % 360)
        return
    if head in ("property", "fp_text"):
        for child in tree:
            if isinstance(child, list) and _safe_head(child) == "effects":
                child.append(["justify", "mirror"])
                break
    for child in tree:
        if isinstance(child, list):
            _flip_tree(child)


def _swap_layer(name: str) -> str:
    if name.startswith("F."):
        return "B." + name[2:]
    if name.startswith("B."):
        return "F." + name[2:]
    return name


def _children_named(nodes: SList, name: str) -> list[SList]:
    return [
        node
        for node in nodes
        if isinstance(node, list) and node and _safe_head(node) == name
    ]


def _silk_text_node(
    text: str,
    x: float,
    y: float,
    angle: float,
    uuid_value: str,
) -> SList:
    return [
        "fp_text",
        "user",
        QuotedString(text),
        ["at", _fmt(x), _fmt(y), _fmt(angle)],
        ["layer", QuotedString("F.SilkS")],
        ["uuid", QuotedString(uuid_value)],
        [
            "effects",
            ["font", ["size", "1", "1"], ["thickness", "0.15"]],
        ],
    ]


def _hidden_property(name: str, value: str, uuid_value: str) -> SList:
    return [
        "property",
        QuotedString(name),
        QuotedString(value),
        ["at", "0", "0", "0"],
        ["layer", QuotedString("F.Fab")],
        ["hide", "yes"],
        ["uuid", QuotedString(uuid_value)],
        [
            "effects",
            ["font", ["size", "0.5", "0.5"], ["thickness", "0.06"]],
        ],
    ]


def _as_list(node: SExpr) -> SList:
    if not isinstance(node, list):
        raise FootprintLibraryError("Expected a list node.")
    return node


def _deep_copy(node: SExpr) -> SExpr:
    if isinstance(node, list):
        return [_deep_copy(child) for child in node]
    if isinstance(node, QuotedString):
        return QuotedString(node.value)
    return node


def _fmt(value: float) -> str:
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"


# --------------------------------------------------------------------------
# The footprint library used by the board generator.

LIBRARY_FOOTPRINT_IDS = (
    "Resistor_SMD:R_0603_1608Metric",
    "Capacitor_SMD:C_0603_1608Metric",
    "Capacitor_SMD:CP_Elec_8x10",
    "LED_SMD:LED_0603_1608Metric",
    "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    "Package_TO_SOT_SMD:TO-263-5_TabPin3",
    "Diode_SMD:D_SMA",
    "Inductor_SMD:L_12x12mm_H8mm",
    "MountingHole:MountingHole_3.2mm_M3",
    "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm",
    "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
    "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    "Package_TO_SOT_SMD:SOT-23",
    "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
    "NetTie:NetTie-2_SMD_Pad2.0mm",
    # Offline flyback (mains) parts.
    "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-2-5.08_1x02_P5.08mm_Horizontal",
    "Resistor_THT:R_Axial_DIN0414_L11.9mm_D4.5mm_P15.24mm_Horizontal",
    "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal",
    "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm",
    "Capacitor_THT:C_Disc_D9.0mm_W5.0mm_P10.00mm",
    "Varistor:RV_Disc_D7mm_W3.5mm_P5mm",
    "Package_SO:SOIC-8_5.3x6.2mm_P1.27mm",
    "Package_DIP:DIP-4_W7.62mm",
    "Transformer_THT:Transformer_Breve_TEZ-22x24",
    # Flyback r002 (FLBACK-001 reference-driven front end).
    "Diode_THT:Diode_Bridge_DIP-4_W7.62mm_P5.08mm",
    "Capacitor_THT:C_Rect_L18.0mm_W7.0mm_P15.00mm_FKS3_FKP3",
    "Connector_Wire:SolderWire-2.5sqmm_1x01_D2.4mm_OD3.6mm",
    "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm",
    # 555 servo tester (beginner THT board).
    "Package_DIP:DIP-8_W7.62mm_Socket",
    "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
    "Capacitor_THT:C_Disc_D4.7mm_W2.5mm_P5.00mm",
    "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm",
    "Package_TO_SOT_THT:TO-92_Inline",
    "Button_Switch_THT:SW_PUSH_6mm",
    # Thermometer display (SHT31 + ESP32-C3, USB-C powered).
    "RF_Module:ESP32-C3-WROOM-02",
    "Sensor_Humidity:Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm",
    "Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
    "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
    "Package_TO_SOT_SMD:SOT-23-5",
    "LED_SMD:LED_0805_2012Metric",
    "Capacitor_SMD:C_0805_2012Metric",
    "Fuse:Fuse_1206_3216Metric",
)

# The pin header doubles as the off-board power connector; PCBSmith wires the
# positive rail to pin 1, so the connector gains "+" / "-" marks on top of
# the library silk (rule 8.2). The official 1x02 vertical header stacks its
# pads in y (pin 1 on top), so the marks sit above and below the column.
_CONNECTOR_EXTRA_MARKS: dict[str, tuple[SilkLine | SilkText, ...]] = {
    "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical": (
        SilkText(text="+", x=0.0, y=-3.9),
        SilkText(text="-", x=0.0, y=4.94),
    ),
    "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical": (
        SilkText(text="+", x=0.0, y=-3.9),
    ),
    "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical": (
        SilkText(text="+", x=0.0, y=-3.9),
    ),
}

# Mounting holes exist only on the board; the attr keeps schematic parity
# checks from reporting them as missing from the netlist.
_BOARD_ONLY_IDS = frozenset({"MountingHole:MountingHole_3.2mm_M3"})


def build_footprint_library() -> dict[str, FootprintSpec]:
    library: dict[str, FootprintSpec] = {}
    for library_id in LIBRARY_FOOTPRINT_IDS:
        imported = load_footprint(library_id)
        spec = imported.spec
        extra = _CONNECTOR_EXTRA_MARKS.get(library_id)
        board_only = spec.board_only or library_id in _BOARD_ONLY_IDS
        if extra or board_only != spec.board_only:
            marks = (*spec.silk_marks, *(extra or ()))
            text_ys = [mark.y for mark in (extra or ()) if isinstance(mark, SilkText)]
            spec = FootprintSpec(
                pads=spec.pads,
                fab_rect=spec.fab_rect,
                silk_rect=spec.silk_rect,
                x_min=spec.x_min,
                x_max=spec.x_max,
                y_min=min((spec.y_min, *[y - 0.8 for y in text_ys])),
                y_max=max((spec.y_max, *[y + 0.8 for y in text_ys])),
                attr=spec.attr,
                is_connector=spec.is_connector,
                silk_marks=marks,
                board_only=board_only,
                courtyard_hull=spec.courtyard_hull,
                fab_hull=spec.fab_hull,
                reference_label=spec.reference_label,
            )
        library[library_id] = spec
    return library
