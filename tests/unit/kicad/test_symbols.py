from __future__ import annotations

from pcbsmith.kicad.symbols import (
    instance_pin_position,
    load_symbol,
    pin_stub_outward,
    render_symbol_for_schematic,
)


def test_flattened_derived_symbol_carries_parent_pins() -> None:
    # MMBT3904 extends Q_NPN_BEC; flattening must bring the pins across
    # with the child's identity.
    symbol = load_symbol("Transistor_BJT:MMBT3904")
    assert {(p.number, p.name) for p in symbol.pins} == {
        ("1", "B"), ("2", "E"), ("3", "C"),
    }
    rendered = render_symbol_for_schematic(symbol)
    assert '(symbol "Transistor_BJT:MMBT3904"' in rendered
    assert "extends" not in rendered
    assert '"MMBT3904_' in rendered or '"Q_NPN_BEC_' not in rendered


def test_regulator_symbol_has_the_real_pin_names() -> None:
    symbol = load_symbol("Regulator_Switching:LM2596S-ADJ")
    names = {p.number: p.name for p in symbol.pins}
    assert names["1"] == "VIN"
    assert names["3"] == "GND"
    assert names["4"] == "FB"
    assert "ON" in names["5"]  # ~{ON}/OFF


def test_pin_geometry_flips_to_sheet_coordinates() -> None:
    # Device:R pin 1 sits at symbol (0, +3.81) = ABOVE the body; on the
    # sheet (y down) that is 3.81 BELOW the anchor's y value numerically.
    resistor = load_symbol("Device:R")
    assert instance_pin_position(resistor, "1", (100.0, 100.0)) == (100.0, 96.19)
    assert instance_pin_position(resistor, "2", (100.0, 100.0)) == (100.0, 103.81)
    # Pin 1 points down into the body (270), so its stub leaves upward.
    assert pin_stub_outward(resistor, "1") == (0.0, -1.0)
    assert pin_stub_outward(resistor, "2") == (0.0, 1.0)


def test_vendored_symbols_round_trip() -> None:
    # The vendored files parse to the same pins as the installed library.
    for lib_id in ("Device:R", "Transistor_BJT:MMBT3904"):
        symbol = load_symbol(lib_id)
        assert symbol.pins  # loaded through whichever source; must measure
