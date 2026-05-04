from __future__ import annotations

from pcbsmith.services.builtin_library import FOOTPRINTS, SYMBOLS, get_symbol


def test_builtin_library_contains_resistor_led_and_power_symbols() -> None:
    assert "stdlib:R" in SYMBOLS
    assert "stdlib:LED" in SYMBOLS
    assert "stdlib:VCC" in SYMBOLS
    assert "stdlib:GND" in SYMBOLS


def test_builtin_resistor_has_matching_default_footprint() -> None:
    symbol = get_symbol("stdlib:R")
    assert symbol.default_footprint_id == "stdlib:R_0603"
    assert symbol.default_footprint_id in FOOTPRINTS
