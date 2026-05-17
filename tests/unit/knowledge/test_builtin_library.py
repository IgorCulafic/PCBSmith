from __future__ import annotations

from pcbsmith.knowledge.builtin_library import (
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
        "stdlib:D",
        "stdlib:SW_PUSH",
        "stdlib:SW_SPST",
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


def test_basic_component_symbols_have_expected_pins_and_defaults() -> None:
    diode = get_symbol("stdlib:D")
    push_button = get_symbol("stdlib:SW_PUSH")
    switch = get_symbol("stdlib:SW_SPST")

    assert diode.name == "Diode"
    assert diode.default_footprint_id == "stdlib:D_0603"
    assert [(pin.number, pin.name, pin.position.x, pin.position.y) for pin in diode.pins] == [
        ("1", "K", -5_080_000, 0),
        ("2", "A", 5_080_000, 0),
    ]
    assert push_button.default_footprint_id == "stdlib:SW_PUSH_TH"
    assert switch.default_footprint_id == "stdlib:SW_SPST_TH"
    assert [pin.name for pin in push_button.pins] == ["A", "B"]
    assert [pin.name for pin in switch.pins] == ["A", "B"]


def test_basic_component_footprints_contain_expected_pads() -> None:
    diode = get_footprint("stdlib:D_0603")
    push_button = get_footprint("stdlib:SW_PUSH_TH")
    switch = get_footprint("stdlib:SW_SPST_TH")

    assert diode.name == "D_0603"
    assert [(pad.number, pad.position.x, pad.position.y) for pad in diode.pads] == [
        ("1", -800_000, 0),
        ("2", 800_000, 0),
    ]
    assert push_button.name == "SW_PUSH_TH"
    assert switch.name == "SW_SPST_TH"
    assert [pad.number for pad in push_button.pads] == ["1", "2"]
    assert [pad.number for pad in switch.pads] == ["1", "2"]
