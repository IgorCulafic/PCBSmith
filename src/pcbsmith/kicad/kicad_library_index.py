from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

KICAD_LIBRARY_INDEX_SCHEMA = "pcbsmith-kicad-library-index-v1"

_TOP_LEVEL_SYMBOL_PATTERN = re.compile(r'^\t\(symbol\s+"([^"]+)"')


class KiCadLibraryRoots(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbols_dir: Path
    footprints_dir: Path
    source: str


def kicad_library_roots_from_cli(cli_path: Path) -> KiCadLibraryRoots:
    install_root = cli_path.parent.parent
    return KiCadLibraryRoots(
        symbols_dir=install_root / "share" / "kicad" / "symbols",
        footprints_dir=install_root / "share" / "kicad" / "footprints",
        source="kicad-cli layout",
    )


def default_kicad_library_root_candidates() -> tuple[Path, ...]:
    return (
        Path("C:/Program Files/KiCad/10.0/share/kicad"),
        Path("C:/Program Files/KiCad/9.0/share/kicad"),
        Path("C:/Program Files/KiCad/8.0/share/kicad"),
        Path.home() / "scoop" / "apps" / "kicad" / "current" / "share" / "kicad",
    )


def find_kicad_library_roots(
    cli_path: Path | None = None,
    *,
    candidate_roots: Sequence[Path] | None = None,
    exists: Callable[[Path], bool] = Path.exists,
) -> KiCadLibraryRoots | None:
    candidates: list[tuple[Path, str]] = []
    if cli_path is not None:
        cli_roots = kicad_library_roots_from_cli(cli_path)
        candidates.append((cli_roots.symbols_dir.parent, cli_roots.source))

    candidates.extend(
        (candidate, "known library path")
        for candidate in (candidate_roots or default_kicad_library_root_candidates())
    )

    for root, source in candidates:
        symbols_dir = root / "symbols"
        footprints_dir = root / "footprints"
        if exists(symbols_dir) and exists(footprints_dir):
            return KiCadLibraryRoots(
                symbols_dir=symbols_dir,
                footprints_dir=footprints_dir,
                source=source,
            )
    return None


def build_kicad_library_index(
    *,
    symbols_dir: Path,
    footprints_dir: Path,
    symbol_libraries: tuple[str, ...],
    footprint_libraries: tuple[str, ...],
) -> dict[str, Any]:
    symbols = _symbol_entries(symbols_dir, symbol_libraries)
    footprints = _footprint_entries(footprints_dir, footprint_libraries)
    return {
        "schema": KICAD_LIBRARY_INDEX_SCHEMA,
        "symbols_dir": str(symbols_dir),
        "footprints_dir": str(footprints_dir),
        "symbols": symbols,
        "footprints": footprints,
        "symbol_count": len(symbols),
        "footprint_count": len(footprints),
    }


def write_kicad_library_index(
    output_path: Path,
    *,
    symbols_dir: Path,
    footprints_dir: Path,
    symbol_libraries: tuple[str, ...],
    footprint_libraries: tuple[str, ...],
) -> None:
    index = build_kicad_library_index(
        symbols_dir=symbols_dir,
        footprints_dir=footprints_dir,
        symbol_libraries=symbol_libraries,
        footprint_libraries=footprint_libraries,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def _symbol_entries(
    symbols_dir: Path,
    libraries: tuple[str, ...],
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for library in libraries:
        library_path = symbols_dir / f"{library}.kicad_sym"
        for name in _read_symbol_names(library_path):
            entries.append({"library": library, "name": name, "id": f"{library}:{name}"})
    return sorted(entries, key=lambda entry: (entry["library"], entry["name"]))


def _read_symbol_names(library_path: Path) -> list[str]:
    if not library_path.exists():
        return []
    names: list[str] = []
    for line in library_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _TOP_LEVEL_SYMBOL_PATTERN.match(line)
        if match is not None:
            names.append(match.group(1))
    return names


def _footprint_entries(
    footprints_dir: Path,
    libraries: tuple[str, ...],
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for library in libraries:
        library_dir = footprints_dir / f"{library}.pretty"
        if not library_dir.exists():
            continue
        for footprint_path in sorted(library_dir.glob("*.kicad_mod")):
            name = footprint_path.stem
            entries.append({"library": library, "name": name, "id": f"{library}:{name}"})
    return entries


__all__ = [
    "KICAD_LIBRARY_INDEX_SCHEMA",
    "KiCadLibraryRoots",
    "build_kicad_library_index",
    "default_kicad_library_root_candidates",
    "find_kicad_library_roots",
    "kicad_library_roots_from_cli",
    "write_kicad_library_index",
]
