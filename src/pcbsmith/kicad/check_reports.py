"""Strict parsing of retained native check results, without changing raw evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_native_header(data: object, kind: str, input_file: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("KiCad report root must be a JSON object")
    if data.get("$schema") != f"https://schemas.kicad.org/{kind.lower()}.v1.json":
        raise ValueError("Missing or unsupported native KiCad report schema")
    source = data.get("source")
    if not isinstance(source, str) or Path(source).name != input_file.name:
        raise ValueError("KiCad report source does not match the checked input")
    version = data.get("kicad_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("KiCad report is missing its producer version")
    return data


def object_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entries = data.get(key)
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError(f"KiCad report section {key} must be a list of objects")
    return entries


def drc_sections(data: object) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(data, dict):
        raise ValueError("KiCad DRC report root must be a JSON object")
    return {
        key: object_list(data, key)
        for key in ("violations", "unconnected_items", "schematic_parity")
    }


def erc_violations(data: object) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("KiCad ERC report root must be a JSON object")
    sheets = object_list(data, "sheets")
    if not sheets:
        raise ValueError("KiCad ERC report must include at least one evaluated sheet")
    return [entry for sheet in sheets for entry in object_list(sheet, "violations")]
