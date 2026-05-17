from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from pcbsmith.kicad.kicad_library_index import KICAD_LIBRARY_INDEX_SCHEMA
from pcbsmith.knowledge.component_catalog import builtin_catalog, entry_by_id


class KiCadPartResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: str
    available: bool
    symbol_id: str | None
    symbol_available: bool
    footprint_id: str | None
    footprint_available: bool
    model_3d_path: str | None
    message: str


def resolve_kicad_part_from_index_file(
    entry_id: str,
    library_index_path: Path,
) -> KiCadPartResolution:
    library_index = json.loads(library_index_path.read_text(encoding="utf-8"))
    if not isinstance(library_index, dict):
        raise ValueError(f"Expected KiCad library index JSON object: {library_index_path}")
    return resolve_kicad_part(entry_id, library_index)


def resolve_kicad_part(
    entry_id: str,
    library_index: dict[str, Any],
) -> KiCadPartResolution:
    if library_index.get("schema") != KICAD_LIBRARY_INDEX_SCHEMA:
        raise ValueError(f"Unsupported KiCad library index schema: {library_index.get('schema')}")

    entry = entry_by_id(builtin_catalog(), entry_id)
    if entry.kicad is None:
        return KiCadPartResolution(
            entry_id=entry.id,
            available=False,
            symbol_id=None,
            symbol_available=False,
            footprint_id=None,
            footprint_available=False,
            model_3d_path=None,
            message="catalog entry has no KiCad binding",
        )

    symbols = _ids(library_index.get("symbols", []))
    footprints = _ids(library_index.get("footprints", []))
    symbol_available = entry.kicad.symbol_id in symbols
    footprint_available = (
        True if entry.kicad.footprint_id is None else entry.kicad.footprint_id in footprints
    )
    available = symbol_available and footprint_available
    return KiCadPartResolution(
        entry_id=entry.id,
        available=available,
        symbol_id=entry.kicad.symbol_id,
        symbol_available=symbol_available,
        footprint_id=entry.kicad.footprint_id,
        footprint_available=footprint_available,
        model_3d_path=entry.kicad.model_3d_path,
        message="KiCad part binding available" if available else "KiCad part binding missing",
    )


def format_kicad_part_resolution(result: KiCadPartResolution) -> list[str]:
    lines = [
        f"Catalog entry: {result.entry_id}",
        f"Available: {'yes' if result.available else 'no'}",
        f"Symbol: {result.symbol_id or '(none)'} ({_status(result.symbol_available)})",
    ]
    if result.footprint_id is not None:
        lines.append(
            f"Footprint: {result.footprint_id} ({_status(result.footprint_available)})"
        )
    if result.model_3d_path is not None:
        lines.append(f"3D model: {result.model_3d_path}")
    lines.append(result.message)
    return lines


def _ids(entries: object) -> set[str]:
    if not isinstance(entries, list):
        return set()
    return {
        entry["id"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }


def _status(value: bool) -> str:
    return "found" if value else "missing"


__all__ = [
    "KiCadPartResolution",
    "format_kicad_part_resolution",
    "resolve_kicad_part",
    "resolve_kicad_part_from_index_file",
]
