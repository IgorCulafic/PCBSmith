"""Project-local KiCad footprint-library authority.

Generated boards embed their footprint geometry, but a schematic footprint link
is only authoritative when it names a configured library entry. This module
packages the exact generated geometry into a project-local ``.pretty`` library
and writes the matching ``fp-lib-table``.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TypeGuard

from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr, serialize_sexpr

PCBSMITH_FOOTPRINT_LIBRARY_NAME = "PCBSmith"
PCBSMITH_FOOTPRINT_LIBRARY_DIR_NAME = "PCBSmith.pretty"
PCBSMITH_FOOTPRINT_TABLE_FILE_NAME = "fp-lib-table"


def project_local_footprint_id(footprint_name: str) -> str:
    """Return a stable qualified ID for a PCBSmith-owned footprint."""

    if ":" in footprint_name:
        return footprint_name
    return f"{PCBSMITH_FOOTPRINT_LIBRARY_NAME}:{footprint_name}"


def render_pcbs_kicad_footprint_table() -> str:
    return f'''(fp_lib_table
  (version 7)
  (lib
    (name "{PCBSMITH_FOOTPRINT_LIBRARY_NAME}")
    (type "KiCad")
    (uri "${{KIPRJMOD}}/{PCBSMITH_FOOTPRINT_LIBRARY_DIR_NAME}")
    (options "")
    (descr "PCBSmith generated footprints")
  )
)
'''


def write_project_local_footprint_library(
    project_dir: Path,
    board_file: Path,
) -> tuple[Path, ...]:
    """Package all qualified PCBSmith footprints embedded in ``board_file``."""

    board = parse_sexpr(board_file.read_text(encoding="utf-8"))
    modules: dict[str, str] = {}
    for child in board:
        if not _is_named_list(child, "footprint") or len(child) < 2:
            continue
        footprint_id = _atom(child[1])
        prefix = f"{PCBSMITH_FOOTPRINT_LIBRARY_NAME}:"
        if not footprint_id.startswith(prefix):
            continue
        module_name = footprint_id[len(prefix) :]
        rendered = _render_library_module(child, module_name)
        prior = modules.setdefault(module_name, rendered)
        if prior != rendered:
            raise ValueError(
                f"Generated footprint {footprint_id!r} has inconsistent embedded geometry"
            )

    library_dir = project_dir / PCBSMITH_FOOTPRINT_LIBRARY_DIR_NAME
    library_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for module_name, rendered in sorted(modules.items()):
        module_file = library_dir / f"{module_name}.kicad_mod"
        module_file.write_text(rendered, encoding="utf-8")
        written.append(module_file)

    table_file = project_dir / PCBSMITH_FOOTPRINT_TABLE_FILE_NAME
    table_file.write_text(render_pcbs_kicad_footprint_table(), encoding="utf-8")
    return tuple(written)


def _render_library_module(source: SList, module_name: str) -> str:
    module = deepcopy(source)
    module[1] = QuotedString(module_name)
    module = [
        child
        for child in module
        if not (isinstance(child, list) and child and _atom(child[0]) in {"at", "uuid", "path"})
    ]
    module.insert(2, ["version", "20241229"])
    module.insert(3, ["generator", QuotedString("PCBSmith")])
    _normalize_module_tree(module, module_name=module_name)
    return serialize_sexpr(module) + "\n"


def _normalize_module_tree(node: SList, *, module_name: str) -> None:
    retained: list[SExpr] = []
    for child in node:
        if isinstance(child, list) and child:
            head = _atom(child[0])
            if head in {"uuid", "net"}:
                continue
            if head == "property" and len(child) >= 3:
                property_name = _atom(child[1])
                if property_name == "PCBSmith_Mating":
                    continue
                if property_name == "Reference":
                    child[2] = QuotedString("REF**")
                    _set_property_at(child, x="0", y="-2")
                elif property_name == "Value":
                    child[2] = QuotedString(module_name)
                    _set_property_at(child, x="0", y="2")
            _normalize_module_tree(child, module_name=module_name)
        retained.append(child)
    node[:] = retained


def _set_property_at(property_node: SList, *, x: str, y: str) -> None:
    for child in property_node:
        if _is_named_list(child, "at"):
            child[:] = ["at", x, y, "0"]
            return


def _is_named_list(node: SExpr, name: str) -> TypeGuard[SList]:
    return isinstance(node, list) and bool(node) and _atom(node[0]) == name


def _atom(node: SExpr) -> str:
    if isinstance(node, QuotedString):
        return node.value
    if isinstance(node, str):
        return node
    raise ValueError(f"Expected KiCad atom, got {node!r}")


__all__ = [
    "PCBSMITH_FOOTPRINT_LIBRARY_DIR_NAME",
    "PCBSMITH_FOOTPRINT_LIBRARY_NAME",
    "PCBSMITH_FOOTPRINT_TABLE_FILE_NAME",
    "project_local_footprint_id",
    "render_pcbs_kicad_footprint_table",
    "write_project_local_footprint_library",
]
