from __future__ import annotations

import pytest

from pcbsmith.operations.circuit_composer import (
    CircuitBlockUse,
    compose_circuit_blocks,
)


def test_compose_circuit_blocks_combines_reusable_blocks() -> None:
    design = compose_circuit_blocks(
        "basic-led-controller",
        (
            CircuitBlockUse(name="power_input_2pin"),
            CircuitBlockUse(name="decoupling_capacitor"),
            CircuitBlockUse(name="low_side_mosfet_switch"),
            CircuitBlockUse(
                name="led_string",
                instance="status",
                net_bindings={"return": "LED_RETURN"},
                params={"led_count": 3, "resistor_value": "680R"},
            ),
        ),
    )

    references = [component.reference for component in design.components]
    assert references == ["J1", "C1", "J2", "Q1", "R1", "LED1", "LED2", "LED3"]
    assert {"VCC", "GND", "CTRL", "LED_RETURN"}.issubset(
        {net.name for net in design.nets}
    )
    assert len(references) == len(set(references))


def test_compose_circuit_blocks_can_reuse_same_block_multiple_times() -> None:
    design = compose_circuit_blocks(
        "two-led-strings",
        (
            CircuitBlockUse(name="power_input_2pin"),
            CircuitBlockUse(name="led_string", instance="left", params={"led_count": 2}),
            CircuitBlockUse(name="led_string", instance="right", params={"led_count": 2}),
        ),
    )

    assert [component.reference for component in design.components] == [
        "J1",
        "R1",
        "LED1",
        "LED2",
        "R2",
        "LED3",
        "LED4",
    ]
    assert "LEFT_LED_1" in {net.name for net in design.nets}
    assert "RIGHT_LED_1" in {net.name for net in design.nets}


def test_compose_circuit_blocks_rejects_unknown_block() -> None:
    with pytest.raises(ValueError, match="Unknown circuit block"):
        compose_circuit_blocks(
            "bad",
            (CircuitBlockUse(name="imaginary_block"),),
        )


def test_compose_circuit_blocks_rejects_invalid_led_count() -> None:
    with pytest.raises(ValueError, match="led_count"):
        compose_circuit_blocks(
            "bad",
            (CircuitBlockUse(name="led_string", params={"led_count": 0}),),
        )
