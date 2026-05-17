from __future__ import annotations

from collections.abc import Mapping

from pcbsmith.core.circuit import CircuitDesign, compose_circuit_designs
from pcbsmith.templates.basic import (
    DECOUPLING_CAPACITOR,
    GPIO_LED_OUTPUT,
    LOW_SIDE_MOSFET_SWITCH,
    POWER_INPUT_2PIN,
    build_decoupling_capacitor,
    build_gpio_led_output,
    build_low_side_mosfet_switch,
    build_power_input_2pin,
)
from pcbsmith.templates.led import LED_STRING, build_led_string
from pcbsmith.templates.models import (
    CircuitTemplate,
    CircuitTemplateBuilder,
    CircuitTemplateUse,
    ReferenceAllocator,
)

_TEMPLATES: dict[str, CircuitTemplate] = {
    template.id: template
    for template in (
        POWER_INPUT_2PIN,
        DECOUPLING_CAPACITOR,
        LED_STRING,
        LOW_SIDE_MOSFET_SWITCH,
        GPIO_LED_OUTPUT,
    )
}

_BUILDERS: Mapping[str, CircuitTemplateBuilder] = {
    "power_input_2pin": build_power_input_2pin,
    "decoupling_capacitor": build_decoupling_capacitor,
    "led_string": build_led_string,
    "low_side_mosfet_switch": build_low_side_mosfet_switch,
    "gpio_led_output": build_gpio_led_output,
}


def list_templates() -> tuple[CircuitTemplate, ...]:
    return tuple(_TEMPLATES[key] for key in sorted(_TEMPLATES))


def get_template(template_id: str) -> CircuitTemplate:
    try:
        return _TEMPLATES[template_id]
    except KeyError as exc:
        raise ValueError(f"Unknown circuit template: {template_id}") from exc


def compose_templates(
    name: str,
    uses: tuple[CircuitTemplateUse, ...],
) -> CircuitDesign:
    allocator = ReferenceAllocator()
    designs: list[CircuitDesign] = []
    for use in uses:
        get_template(use.template_id)
        designs.append(_BUILDERS[use.template_id](use, allocator))
    return compose_circuit_designs(name, *designs)


__all__ = ["compose_templates", "get_template", "list_templates"]
