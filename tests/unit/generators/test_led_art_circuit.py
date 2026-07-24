from __future__ import annotations

from pcbsmith.generators.led_art import LedArtSpec, build_led_art_plan_for_topology
from pcbsmith.generators.led_art_circuit import led_art_plan_to_circuit_design


def test_led_art_5v_circuit_contains_input_resistors_and_leds() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="V"), "5v_one_per_led")

    circuit = led_art_plan_to_circuit_design(plan, control_mode="none")

    assert circuit.name == "V LED art"
    assert any(component.reference == "J1" for component in circuit.components)
    assert sum(1 for component in circuit.components if component.symbol_id == "stdlib:R") == len(
        plan.strings
    )
    assert sum(1 for component in circuit.components if component.symbol_id == "stdlib:LED") == len(
        plan.pixels
    )
    assert {"VCC", "GND"}.issubset({net.name for net in circuit.nets})


def test_led_art_12v_circuit_groups_series_leds_behind_one_resistor() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="I"), "12v_dense")

    circuit = led_art_plan_to_circuit_design(plan, control_mode="none")

    resistor_count = sum(
        1 for component in circuit.components if component.symbol_id == "stdlib:R"
    )
    led_count = sum(1 for component in circuit.components if component.symbol_id == "stdlib:LED")
    assert resistor_count == len(plan.strings)
    assert led_count == len(plan.pixels)
    assert resistor_count < led_count


def test_led_art_mosfet_control_adds_switching_component_and_control_net() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="I"), "5v_one_per_led")

    circuit = led_art_plan_to_circuit_design(plan, control_mode="low_side_mosfet")

    assert any(
        component.reference == "Q1" and component.symbol_id == "stdlib:NMOS"
        for component in circuit.components
    )
    assert any(
        component.reference == "J2"
        and component.symbol_id == "stdlib:CONN_01X02"
        and any(pin.net == "CTRL" for pin in component.pins)
        for component in circuit.components
    )
    assert "CTRL" in {net.name for net in circuit.nets}
    assert "LED_RETURN" in {net.name for net in circuit.nets}
