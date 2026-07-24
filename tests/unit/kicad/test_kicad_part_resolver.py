from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.kicad.kicad_part_resolver import (
    format_kicad_part_resolution,
    resolve_kicad_part,
    resolve_kicad_part_from_index_file,
)


def _library_index() -> dict[str, object]:
    return {
        "schema": "pcbsmith-kicad-library-index-v1",
        "symbols": [
            {"id": "Device:R", "library": "Device", "name": "R"},
            {"id": "Device:LED", "library": "Device", "name": "LED"},
            {"id": "power:VCC", "library": "power", "name": "VCC"},
        ],
        "footprints": [
            {
                "id": "Resistor_SMD:R_0603_1608Metric",
                "library": "Resistor_SMD",
                "name": "R_0603_1608Metric",
            },
            {
                "id": "LED_SMD:LED_0603_1608Metric",
                "library": "LED_SMD",
                "name": "LED_0603_1608Metric",
            },
        ],
    }


def test_resolve_kicad_part_finds_bound_symbol_and_footprint() -> None:
    result = resolve_kicad_part("pcbs:resistor_0603", _library_index())

    assert result.available is True
    assert result.symbol_id == "Device:R"
    assert result.footprint_id == "Resistor_SMD:R_0603_1608Metric"
    assert format_kicad_part_resolution(result) == [
        "Catalog entry: pcbs:resistor_0603",
        "Available: yes",
        "Symbol: Device:R (found)",
        "Footprint: Resistor_SMD:R_0603_1608Metric (found)",
        "KiCad part binding available",
    ]


def test_resolve_kicad_part_supports_virtual_power_symbols() -> None:
    result = resolve_kicad_part("pcbs:vcc_power", _library_index())

    assert result.available is True
    assert result.symbol_id == "power:VCC"
    assert result.footprint_id is None
    assert format_kicad_part_resolution(result) == [
        "Catalog entry: pcbs:vcc_power",
        "Available: yes",
        "Symbol: power:VCC (found)",
        "KiCad part binding available",
    ]


def test_resolve_kicad_part_reports_missing_footprint() -> None:
    result = resolve_kicad_part(
        "pcbs:led_0603",
        {
            "schema": "pcbsmith-kicad-library-index-v1",
            "symbols": [{"id": "Device:LED"}],
            "footprints": [],
        },
    )

    assert result.available is False
    assert result.symbol_available is True
    assert result.footprint_available is False
    assert result.message == "KiCad part binding missing"


def test_resolve_kicad_part_rejects_wrong_index_schema() -> None:
    with pytest.raises(ValueError, match="Unsupported KiCad library index schema"):
        resolve_kicad_part("pcbs:resistor_0603", {"schema": "wrong"})


def test_resolve_kicad_part_from_index_file(tmp_path: Path) -> None:
    index_path = tmp_path / "kicad-library-index.json"
    index_path.write_text(json.dumps(_library_index()), encoding="utf-8")

    result = resolve_kicad_part_from_index_file("pcbs:resistor_0603", index_path)

    assert result.available is True
