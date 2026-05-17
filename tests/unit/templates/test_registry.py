from __future__ import annotations

import pytest

from pcbsmith.templates import (
    CircuitTemplateUse,
    compose_templates,
    get_template,
    list_templates,
)


def test_list_templates_exposes_ai_friendly_metadata() -> None:
    templates = {template.id: template for template in list_templates()}

    assert {
        "power_input_2pin",
        "decoupling_capacitor",
        "led_string",
        "low_side_mosfet_switch",
        "gpio_led_output",
    }.issubset(templates)
    led_string = templates["led_string"]
    assert led_string.category == "led"
    assert led_string.parameters["led_count"].default == 1
    assert led_string.net_ports["return"].default_net == "GND"
    assert "series-leds" in led_string.tags


def test_get_template_rejects_unknown_template_id() -> None:
    with pytest.raises(ValueError, match="Unknown circuit template"):
        get_template("made_up_template")


def test_compose_templates_reuses_same_template_without_collisions() -> None:
    design = compose_templates(
        "two-led-strings",
        (
            CircuitTemplateUse(template_id="power_input_2pin"),
            CircuitTemplateUse(
                template_id="led_string",
                instance="left",
                params={"led_count": 2},
            ),
            CircuitTemplateUse(
                template_id="led_string",
                instance="right",
                params={"led_count": 2},
            ),
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
    assert len({component.reference for component in design.components}) == len(
        design.components
    )
    assert "LEFT_LED_1" in {net.name for net in design.nets}
    assert "RIGHT_LED_1" in {net.name for net in design.nets}


def test_compose_templates_applies_net_bindings() -> None:
    design = compose_templates(
        "controlled-string",
        (
            CircuitTemplateUse(template_id="low_side_mosfet_switch"),
            CircuitTemplateUse(
                template_id="led_string",
                instance="status",
                net_bindings={"return": "LED_RETURN"},
                params={"led_count": 3, "resistor_value": "680R"},
            ),
        ),
    )

    assert {"CTRL", "LED_RETURN", "GND", "VCC"}.issubset(
        {net.name for net in design.nets}
    )
    assert any(
        component.symbol_id == "stdlib:NMOS"
        and any(pin.net == "LED_RETURN" for pin in component.pins)
        for component in design.components
    )
