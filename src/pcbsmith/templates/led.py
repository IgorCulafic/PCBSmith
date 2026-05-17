from __future__ import annotations

from pcbsmith.core.circuit import CircuitComponent, CircuitDesign, CircuitNet, CircuitPin
from pcbsmith.templates._helpers import (
    bound_net,
    design_name,
    int_param,
    internal_net,
    string_param,
)
from pcbsmith.templates.models import (
    CircuitTemplate,
    CircuitTemplateUse,
    ReferenceAllocator,
    TemplateNetPort,
    TemplateParameter,
)

LED_STRING = CircuitTemplate(
    id="led_string",
    title="Series LED string",
    description="One resistor feeding one or more LEDs in series.",
    category="led",
    parameters={
        "led_count": TemplateParameter(
            name="led_count",
            type="integer",
            default=1,
            description="Number of LEDs in the string.",
        ),
        "resistor_value": TemplateParameter(
            name="resistor_value",
            type="string",
            default="330R",
            description="Series resistor value.",
        ),
        "led_value": TemplateParameter(
            name="led_value",
            type="string",
            default="Red LED",
            description="LED value shown in the schematic.",
        ),
    },
    net_ports={
        "vcc": TemplateNetPort(
            name="vcc",
            default_net="VCC",
            role="power",
            description="Positive supply net feeding the resistor.",
        ),
        "return": TemplateNetPort(
            name="return",
            default_net="GND",
            role="return",
            description="Return net for the last LED cathode.",
        ),
    },
    tags=("led", "series-leds", "current-limit", "smd", "template"),
)


def build_led_string(
    use: CircuitTemplateUse,
    allocator: ReferenceAllocator,
) -> CircuitDesign:
    led_count = int_param(use, "led_count", 1, minimum=1)
    vcc = bound_net(use, "vcc", "VCC")
    return_net = bound_net(use, "return", "GND")
    components: list[CircuitComponent] = []
    nets: dict[str, CircuitNet] = {
        vcc: CircuitNet(name=vcc, role="power"),
        return_net: CircuitNet(name=return_net, role="return"),
    }

    previous_net = internal_net(use, "LED_R")
    nets[previous_net] = CircuitNet(name=previous_net, role="led_string")
    components.append(
        CircuitComponent(
            reference=allocator.next("R"),
            symbol_id="stdlib:R",
            value=string_param(use, "resistor_value", "330R"),
            pins=(
                CircuitPin(number="1", net=vcc, role="input"),
                CircuitPin(number="2", net=previous_net, role="output"),
            ),
        )
    )
    for led_index in range(1, led_count + 1):
        next_net = (
            return_net
            if led_index == led_count
            else internal_net(use, f"LED_{led_index}")
        )
        nets.setdefault(next_net, CircuitNet(name=next_net, role="led_string"))
        components.append(
            CircuitComponent(
                reference=allocator.next("LED"),
                symbol_id="stdlib:LED",
                value=string_param(use, "led_value", "Red LED"),
                footprint_id="stdlib:LED_0603",
                pins=(
                    CircuitPin(number="1", net=previous_net, role="anode"),
                    CircuitPin(number="2", net=next_net, role="cathode"),
                ),
            )
        )
        previous_net = next_net

    return CircuitDesign(
        name=design_name(use),
        components=tuple(components),
        nets=tuple(nets.values()),
        notes=(f"Reusable template: led_string ({led_count} LED(s))",),
    )


__all__ = ["LED_STRING", "build_led_string"]
