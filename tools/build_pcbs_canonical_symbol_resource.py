"""Build the vendored canonical KiCad-10 symbol subset used by W10."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr, serialize_sexpr

SOURCES = {
    "K10_R": ("Device", "R"),
    "K10_C": ("Device", "C"),
    "K10_D_SCHOTTKY": ("Device", "D_Schottky"),
    "K10_L": ("Device", "L"),
    "K10_LED": ("Device", "LED"),
    "K10_CONN_01X02": ("Connector_Generic", "Conn_01x02"),
    "K10_NE555D": ("Timer", "NE555D"),
    # The ADJ entry inherits identical drawing/pin geometry from LM2596S-12.
    # A flattened, renamed base is vendored so schematic caches do not depend
    # on inheritance resolution or the host's library revision.
    "K10_LM2596S_ADJ": ("Regulator_Switching", "LM2596S-12"),
}


def build_resource(symbols_dir: Path) -> str:
    parsed: dict[str, SList] = {}
    rendered: list[str] = []
    for target_name, (library_name, source_name) in SOURCES.items():
        library = parsed.setdefault(
            library_name,
            parse_sexpr((symbols_dir / f"{library_name}.kicad_sym").read_text(encoding="utf-8")),
        )
        source = deepcopy(_symbol(library, source_name))
        _rename_symbol_tree(source, source_name=source_name, target_name=target_name)
        if target_name == "K10_LM2596S_ADJ":
            _set_property(source, "Value", "LM2596S-ADJ")
            _set_property(
                source,
                "Description",
                "Adjustable 3A Step-Down Voltage Regulator, TO-263",
            )
            _set_property(
                source,
                "ki_keywords",
                "Step-Down Voltage Regulator Adjustable 3A",
            )
        rendered.append(serialize_sexpr(source))
    return (
        '(kicad_symbol_lib\n  (version 20251024)\n  (generator "PCBSmith")\n'
        '  (generator_version "0.1")\n' + "\n".join(rendered) + "\n)\n"
    )


def _symbol(root: SList, name: str) -> SList:
    return next(
        child
        for child in root
        if isinstance(child, list)
        and len(child) >= 2
        and _atom(child[0]) == "symbol"
        and _atom(child[1]) == name
    )


def _rename_symbol_tree(node: SList, *, source_name: str, target_name: str) -> None:
    if node and _atom(node[0]) == "symbol" and len(node) >= 2:
        name = _atom(node[1])
        if name == source_name or name.startswith(f"{source_name}_"):
            node[1] = QuotedString(target_name + name[len(source_name) :])
    for child in node:
        if not isinstance(child, list) or not child:
            continue
        if _atom(child[0]) == "symbol" and len(child) >= 2:
            name = _atom(child[1])
            if name == source_name or name.startswith(f"{source_name}_"):
                child[1] = QuotedString(target_name + name[len(source_name) :])
        _rename_symbol_tree(child, source_name=source_name, target_name=target_name)


def _set_property(symbol: SList, name: str, value: str) -> None:
    field = next(
        child
        for child in symbol
        if isinstance(child, list)
        and len(child) >= 3
        and _atom(child[0]) == "property"
        and _atom(child[1]) == name
    )
    field[2] = QuotedString(value)


def _atom(value: SExpr) -> str:
    if isinstance(value, QuotedString):
        return value.value
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_resource(args.symbols_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
