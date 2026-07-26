from __future__ import annotations

from pcbsmith.generation.aerosense_2f import compose_aerosense_2f
from pcbsmith.kicad.aerosense_2f_board import BACK_PARTS, PLACEMENTS
from pcbsmith.kicad.export_aerosense_2f import INSTANCES, NO_CONNECTS
from pcbsmith.kicad.symbols import load_symbol


def test_aerosense_authority_export_and_placement_have_reference_parity() -> None:
    authority = {
        component.reference for component in compose_aerosense_2f().components
    }
    schematic = {reference for reference, *_rest in INSTANCES}

    assert len(authority) == 100
    assert authority == schematic == set(PLACEMENTS)
    assert BACK_PARTS <= authority


def test_aerosense_schematic_populates_or_marks_every_symbol_pin() -> None:
    incomplete: dict[str, tuple[set[str], set[str]]] = {}
    for reference, library_id, _x, _y, connected in INSTANCES:
        symbol_pins = {pin.number for pin in load_symbol(library_id).pins}
        declared = set(connected)
        no_connects = set(NO_CONNECTS.get(reference, ()))
        missing = symbol_pins - declared - no_connects
        unknown = (declared | no_connects) - symbol_pins
        if missing or unknown:
            incomplete[reference] = (missing, unknown)

    assert incomplete == {}


def test_aerosense_fan_defaults_and_open_drain_parts_are_explicit() -> None:
    circuit = compose_aerosense_2f()
    roles = {component.reference: component.role for component in circuit.components}
    values = {component.reference: component.value for component in circuit.components}

    assert roles["Q1"] == "fan_1_open_drain_pwm"
    assert roles["Q2"] == "fan_2_open_drain_pwm"
    assert values["R11"] == values["R12"] == "100k"
    assert values["R9"] == values["R10"] == "59k 1%"
    assert circuit.intent.assumptions["selected_fan_max_current_a"] == 0.1


def test_aerosense_required_production_test_points_are_explicit() -> None:
    circuit = compose_aerosense_2f()
    roles = {component.reference: component.role for component in circuit.components}

    assert {f"TP{index}" for index in range(1, 8)} <= set(roles)
    assert roles["TP1"] == "vbus_test_point"
    assert roles["TP3"] == "fan1_rail_test_point"
    assert roles["TP6"] == "fan1_tach_test_point"
    assert roles["TP7"] == "fan2_tach_test_point"
