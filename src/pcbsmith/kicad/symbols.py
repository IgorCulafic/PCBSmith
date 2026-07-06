"""Official-KiCad-symbol library: parse, flatten, measure, and embed.

The schematic-side twin of ``library.py`` (hardening plan 6.1). Symbols
come verbatim from the official ``.kicad_sym`` libraries (vendored under
``ai_assets/kicad_symbols``, falling back to the installed share), so
generated schematics carry real pin names, numbers, and drawings instead
of hand-drawn boxes.

Derived symbols (``extends``) are flattened the way KiCad embeds them: the
parent's drawing and pins under the child's name, with the child's
properties winning. Pin positions are measured so exporters can attach
wires at the true connection points ("no assumed geometry").

Symbol coordinates are y-UP; schematic sheet coordinates are y-DOWN. The
helpers here do that flip so exporters never think about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from pcbsmith.kicad.library import (
    FootprintLibraryError,
    QuotedString,
    SList,
    _atom,
    _children,
    parse_sexpr,
    serialize_sexpr,
)

VENDORED_DIR = Path(__file__).resolve().parents[3] / "ai_assets" / "kicad_symbols"
INSTALLED_SHARE_DIRS = (
    Path(r"C:\Program Files\KiCad\10.0\share\kicad\symbols"),
    Path(r"C:\Program Files\KiCad\9.0\share\kicad\symbols"),
)


class SymbolLibraryError(FootprintLibraryError):
    pass


@dataclass(frozen=True)
class SymbolPin:
    number: str
    name: str
    x_mm: float  # connection point, symbol coords (y up)
    y_mm: float
    angle_deg: float  # 0 points right (into the body from a left-side pin)
    length_mm: float
    electrical_type: str


@dataclass(frozen=True)
class ImportedSymbol:
    lib_id: str
    pins: tuple[SymbolPin, ...]
    tree: SList = field(hash=False, compare=False, default_factory=list)

    def pin(self, number: str) -> SymbolPin:
        for pin in self.pins:
            if pin.number == number:
                return pin
        raise KeyError(number)


# ---------------------------------------------------------------------------
# Extraction: pull one symbol's text out of a big library without a full
# parse (Device.kicad_sym is megabytes). Quote-aware brace matching.


def _extract_symbol_text(library_text: str, name: str) -> str | None:
    needle = f'(symbol "{name}"'
    start = 0
    while True:
        start = library_text.find(needle, start)
        if start == -1:
            return None
        # Must be a TOP-LEVEL symbol (depth 1): heuristically require the
        # match to start at a line whose indent is one tab/two spaces or
        # less; sub-symbols are nested deeper and their names carry _N_N.
        line_start = library_text.rfind("\n", 0, start) + 1
        indent = start - line_start
        if indent > 2:
            start += 1
            continue
        depth = 0
        index = start
        length = len(library_text)
        while index < length:
            char = library_text[index]
            if char == '"':
                index += 1
                while index < length and library_text[index] != '"':
                    index += 2 if library_text[index] == "\\" else 1
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return library_text[start : index + 1]
            index += 1
        raise SymbolLibraryError(f"Unbalanced symbol node for {name}.")


@cache
def _library_text(library: str) -> str:
    for share in INSTALLED_SHARE_DIRS:
        candidate = share / f"{library}.kicad_sym"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise SymbolLibraryError(f"Symbol library {library} was not found.")


def _vendored_file(lib_id: str) -> Path:
    library, name = lib_id.split(":", 1)
    safe = name.replace("/", "_")
    return VENDORED_DIR / f"{library}__{safe}.kicad_sym"


def _symbol_tree(lib_id: str) -> SList:
    """The flattened symbol node for a lib id, vendored or installed."""
    vendored = _vendored_file(lib_id)
    if vendored.exists():
        wrapper = parse_sexpr(vendored.read_text(encoding="utf-8"))
        symbols = _children(wrapper, "symbol")
        if not symbols:
            raise SymbolLibraryError(f"Vendored file for {lib_id} has no symbol.")
        return symbols[0]
    library, name = lib_id.split(":", 1)
    text = _extract_symbol_text(_library_text(library), name)
    if text is None:
        raise SymbolLibraryError(f"Symbol {lib_id} was not found.")
    tree = parse_sexpr(text)
    extends = _children(tree, "extends")
    if extends:
        parent_name = _atom(extends[0][1])
        parent_text = _extract_symbol_text(_library_text(library), parent_name)
        if parent_text is None:
            raise SymbolLibraryError(
                f"{lib_id} extends {parent_name}, which was not found."
            )
        tree = _flatten(tree, parse_sexpr(parent_text), name, parent_name)
    return tree


def _flatten(child: SList, parent: SList, name: str, parent_name: str) -> SList:
    """Flatten a derived symbol the way KiCad embeds it: the parent's body
    under the child's name, with the child's properties overriding."""
    merged: SList = ["symbol", QuotedString(name)]
    child_properties = {
        _atom(node[1]): node for node in _children(child, "property")
    }
    used: set[str] = set()
    for node in parent[2:]:
        if not isinstance(node, list):
            merged.append(node)
            continue
        head = node[0]
        head_name = head if isinstance(head, str) else None
        if head_name == "property":
            prop_name = _atom(node[1])
            if prop_name in child_properties:
                merged.append(child_properties[prop_name])
                used.add(prop_name)
                continue
        if head_name == "symbol":
            # Sub-unit drawings: rename PARENT_U_S -> CHILD_U_S.
            sub = [element for element in node]
            sub_name = _atom(sub[1])
            if sub_name.startswith(parent_name):
                sub[1] = QuotedString(name + sub_name[len(parent_name):])
            merged.append(sub)
            continue
        merged.append(node)
    for prop_name, node in child_properties.items():
        if prop_name not in used:
            merged.append(node)
    return merged


def _measure_pins(tree: SList) -> tuple[SymbolPin, ...]:
    pins: list[SymbolPin] = []
    for sub in _children(tree, "symbol"):
        for pin in _children(sub, "pin"):
            electrical = _atom(pin[1])
            at = _children(pin, "at")[0]
            length_nodes = _children(pin, "length")
            name_nodes = _children(pin, "name")
            number_nodes = _children(pin, "number")
            pins.append(
                SymbolPin(
                    number=_atom(number_nodes[0][1]) if number_nodes else "",
                    name=_atom(name_nodes[0][1]) if name_nodes else "",
                    x_mm=float(_atom(at[1])),
                    y_mm=float(_atom(at[2])),
                    angle_deg=float(_atom(at[3])) if len(at) > 3 else 0.0,
                    length_mm=(
                        float(_atom(length_nodes[0][1])) if length_nodes else 0.0
                    ),
                    electrical_type=electrical,
                )
            )
    return tuple(pins)


@cache
def load_symbol(lib_id: str) -> ImportedSymbol:
    tree = _symbol_tree(lib_id)
    return ImportedSymbol(lib_id=lib_id, pins=_measure_pins(tree), tree=tree)


def vendor_symbol(lib_id: str) -> Path:
    """Copy the flattened symbol into ai_assets so builds never depend on
    the installed share. Idempotent."""
    target = _vendored_file(lib_id)
    if target.exists():
        return target
    tree = _symbol_tree(lib_id)
    wrapper: SList = [
        "kicad_symbol_lib",
        ["version", "20241209"],
        ["generator", QuotedString("PCBSmith-vendor")],
        tree,
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize_sexpr(wrapper) + "\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Rendering and instance geometry.


def render_symbol_for_schematic(imported: ImportedSymbol) -> str:
    """The lib_symbols entry: the flattened symbol under its full lib id
    (sub-units keep bare names, matching KiCad's own embedding)."""
    tree = [element for element in imported.tree]
    tree[1] = QuotedString(imported.lib_id)
    return "  " + serialize_sexpr(tree, indent=1)


def instance_pin_position(
    imported: ImportedSymbol,
    number: str,
    at: tuple[float, float],
) -> tuple[float, float]:
    """The wire connection point of a pin for an instance placed at ``at``
    with rotation 0. Symbol y is up; sheet y is down."""
    pin = imported.pin(number)
    return (round(at[0] + pin.x_mm, 4), round(at[1] - pin.y_mm, 4))


def pin_stub_outward(
    imported: ImportedSymbol, number: str
) -> tuple[float, float]:
    """Unit vector pointing AWAY from the body in sheet coords - the
    direction a label-net stub wire should leave the pin."""
    import math

    pin = imported.pin(number)
    radians = math.radians(pin.angle_deg)
    # Pin angle points INTO the body from the connection point (y up).
    return (round(-math.cos(radians), 6), round(math.sin(radians), 6))
