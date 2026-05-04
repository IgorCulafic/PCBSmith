from __future__ import annotations

from pcbsmith.services.builtin_library import (
    FOOTPRINTS,
    SYMBOLS,
    get_footprint,
    get_symbol,
)


def test_builtin_library_contains_required_symbols() -> None:
    assert {
        "stdlib:R",
        "stdlib:C",
        "stdlib:LED",
        "stdlib:VCC",
        "stdlib:GND",
        "stdlib:CONN_01X02",
    } <= SYMBOLS.keys()


def test_symbol_default_footprints_exist() -> None:
    for symbol in SYMBOLS.values():
        if symbol.default_footprint_id is None:
            continue

        assert symbol.default_footprint_id in FOOTPRINTS


def test_symbol_pin_numbers_match_default_footprint_pad_numbers() -> None:
    for symbol in SYMBOLS.values():
        if symbol.default_footprint_id is None:
            continue

        footprint = FOOTPRINTS[symbol.default_footprint_id]
        assert sorted(pin.number for pin in symbol.pins) == sorted(
            pad.number for pad in footprint.pads
        )


def test_power_symbols_do_not_have_default_footprints() -> None:
    assert get_symbol("stdlib:VCC").default_footprint_id is None
    assert get_symbol("stdlib:GND").default_footprint_id is None


def test_get_footprint_returns_expected_footprint() -> None:
    footprint = get_footprint("stdlib:R_0603")

    assert footprint.id == "stdlib:R_0603"
    assert footprint.name == "R_0603"
