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

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from uuid import uuid4


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
class PadSpec:
    name: str
    x_mm: float
    y_mm: float
    kind: str
    width_mm: float
    height_mm: float
    drill_mm: float = 0.0


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
    raise FootprintLibraryError(
        f"Only right-angle footprint rotations are supported, not {rotation}."
    )


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
        at = _children(pad, "at")
        size = _children(pad, "size")
        drill_nodes = _children(pad, "drill")
        x_mm = float(_atom(at[0][1])) if at else 0.0
        y_mm = float(_atom(at[0][2])) if at else 0.0
        width = float(_atom(size[0][1])) if size else 0.0
        height = float(_atom(size[0][2])) if size else width
        drill = 0.0
        if drill_nodes:
            drill_values = [
                float(_atom(child))
                for child in drill_nodes[0][1:]
                if not isinstance(child, list) and _is_number(_atom(child))
            ]
            drill = max(drill_values) if drill_values else 0.0
        if kind == "np_thru_hole":
            kind = "tht"
        elif kind == "thru_hole":
            kind = "tht"
        pads.append(
            PadSpec(
                name=name,
                x_mm=x_mm,
                y_mm=y_mm,
                kind=kind,
                width_mm=width,
                height_mm=height,
                drill_mm=drill,
            )
        )

    for shape_name in ("fp_line", "fp_rect", "fp_circle", "fp_poly", "fp_arc"):
        for shape in _children(tree, shape_name):
            layer_nodes = _children(shape, "layer")
            layer = _atom(layer_nodes[0][1]) if layer_nodes else ""
            points = _shape_points(shape)
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
    )


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


# --------------------------------------------------------------------------
# Embedding an imported footprint into a generated board.

_STRIP_TOKENS = {"version", "generator", "generator_version", "embedded_fonts"}


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
) -> str:
    tree = _as_list(_deep_copy(imported.tree))
    tree[1] = QuotedString(imported.library_id)
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
        ["uuid", QuotedString(str(uuid4()))],
        at_clause,
    ]

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
            bound = pad_nets.get(pad_name)
            if bound is not None:
                number, net_name = bound
                child.append(["net", str(number), QuotedString(net_name)])
            child.append(["uuid", QuotedString(str(uuid4()))])
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

    if force_board_only and not _children_named(body, "attr"):
        body.append(["attr", "board_only", "exclude_from_pos_files", "exclude_from_bom"])

    silk_text_nodes: list[SExpr] = [
        _silk_text_node(text, x, y, angle) for text, x, y, angle in extra_silk_texts
    ]
    field_properties: list[SExpr] = [
        _hidden_property(name, field_value) for name, field_value in extra_fields
    ]
    path_clause: list[SExpr] = [["path", QuotedString("/" + uuid_path.strip("/"))]]

    tree[2:] = [*head, *body, *silk_text_nodes, *field_properties, *path_clause]
    return "  " + serialize_sexpr(tree, indent=1)


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


def _silk_text_node(text: str, x: float, y: float, angle: float) -> SList:
    return [
        "fp_text",
        "user",
        QuotedString(text),
        ["at", _fmt(x), _fmt(y), _fmt(angle)],
        ["layer", QuotedString("F.SilkS")],
        ["uuid", QuotedString(str(uuid4()))],
        [
            "effects",
            ["font", ["size", "1", "1"], ["thickness", "0.15"]],
        ],
    ]


def _hidden_property(name: str, value: str) -> SList:
    return [
        "property",
        QuotedString(name),
        QuotedString(value),
        ["at", "0", "0", "0"],
        ["layer", QuotedString("F.Fab")],
        ["hide", "yes"],
        ["uuid", QuotedString(str(uuid4()))],
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
            )
        library[library_id] = spec
    return library
