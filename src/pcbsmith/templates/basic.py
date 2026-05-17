from __future__ import annotations

from pcbsmith.core.circuit import CircuitComponent, CircuitDesign, CircuitNet, CircuitPin
from pcbsmith.templates._helpers import bound_net, design_name, internal_net, string_param
from pcbsmith.templates.models import (
    CircuitTemplate,
    CircuitTemplateUse,
    ReferenceAllocator,
    TemplateNetPort,
    TemplateParameter,
)

POWER_INPUT_2PIN = CircuitTemplate(
    id="power_input_2pin",
    title="Two-pin power input",
    description="Two-pin connector carrying VCC and GND into a circuit.",
    category="power",
    parameters={
        "value": TemplateParameter(
            name="value",
            type="string",
            default="Power input",
            description="Connector value shown in the schematic.",
        ),
    },
    net_ports={
        "vcc": TemplateNetPort(
            name="vcc",
            default_net="VCC",
            role="power",
            description="Positive supply net.",
        ),
        "gnd": TemplateNetPort(
            name="gnd",
            default_net="GND",
            role="return",
            description="Ground or return net.",
        ),
    },
    tags=("connector", "power", "input", "template"),
)

DECOUPLING_CAPACITOR = CircuitTemplate(
    id="decoupling_capacitor",
    title="Decoupling capacitor",
    description="Capacitor between a supply net and return net.",
    category="power",
    parameters={
        "value": TemplateParameter(
            name="value",
            type="string",
            default="100nF",
            description="Capacitance value.",
        ),
    },
    net_ports={
        "vcc": POWER_INPUT_2PIN.net_ports["vcc"],
        "gnd": POWER_INPUT_2PIN.net_ports["gnd"],
    },
    tags=("capacitor", "decoupling", "power", "smd"),
)

LOW_SIDE_MOSFET_SWITCH = CircuitTemplate(
    id="low_side_mosfet_switch",
    title="Low-side MOSFET switch",
    description="N-channel MOSFET low-side switch with an external control connector.",
    category="switching",
    parameters={
        "value": TemplateParameter(
            name="value",
            type="string",
            default="Low-side switch",
            description="MOSFET value shown in the schematic.",
        ),
        "control_value": TemplateParameter(
            name="control_value",
            type="string",
            default="CTRL IN",
            description="Control connector value shown in the schematic.",
        ),
    },
    net_ports={
        "control": TemplateNetPort(
            name="control",
            default_net="CTRL",
            role="control",
            description="Gate/control input net.",
        ),
        "switched_return": TemplateNetPort(
            name="switched_return",
            default_net="LED_RETURN",
            role="switched_return",
            description="Load return switched by the MOSFET drain.",
        ),
        "gnd": POWER_INPUT_2PIN.net_ports["gnd"],
    },
    tags=("mosfet", "switch", "low-side", "control"),
)

GPIO_LED_OUTPUT = CircuitTemplate(
    id="gpio_led_output",
    title="GPIO LED output",
    description="Current-limited LED output driven by a signal net.",
    category="led",
    parameters={
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
        "signal": TemplateNetPort(
            name="signal",
            default_net="GPIO",
            role="signal",
            description="Signal net that drives the LED string.",
        ),
        "gnd": POWER_INPUT_2PIN.net_ports["gnd"],
    },
    tags=("gpio", "led", "current-limit", "smd"),
)


def build_power_input_2pin(
    use: CircuitTemplateUse,
    allocator: ReferenceAllocator,
) -> CircuitDesign:
    vcc = bound_net(use, "vcc", "VCC")
    gnd = bound_net(use, "gnd", "GND")
    return CircuitDesign(
        name=design_name(use),
        components=(
            CircuitComponent(
                reference=allocator.next("J"),
                symbol_id="stdlib:CONN_01X02",
                value=string_param(use, "value", "Power input"),
                pins=(
                    CircuitPin(number="1", net=vcc, role="power_in"),
                    CircuitPin(number="2", net=gnd, role="power_return"),
                ),
            ),
        ),
        nets=(CircuitNet(name=vcc, role="power"), CircuitNet(name=gnd, role="return")),
        notes=("Reusable template: power_input_2pin",),
    )


def build_decoupling_capacitor(
    use: CircuitTemplateUse,
    allocator: ReferenceAllocator,
) -> CircuitDesign:
    vcc = bound_net(use, "vcc", "VCC")
    gnd = bound_net(use, "gnd", "GND")
    return CircuitDesign(
        name=design_name(use),
        components=(
            CircuitComponent(
                reference=allocator.next("C"),
                symbol_id="stdlib:C",
                value=string_param(use, "value", "100nF"),
                pins=(
                    CircuitPin(number="1", net=vcc, role="power"),
                    CircuitPin(number="2", net=gnd, role="return"),
                ),
            ),
        ),
        nets=(CircuitNet(name=vcc, role="power"), CircuitNet(name=gnd, role="return")),
        notes=("Reusable template: decoupling_capacitor",),
    )


def build_low_side_mosfet_switch(
    use: CircuitTemplateUse,
    allocator: ReferenceAllocator,
) -> CircuitDesign:
    control = bound_net(use, "control", "CTRL")
    switched_return = bound_net(use, "switched_return", "LED_RETURN")
    gnd = bound_net(use, "gnd", "GND")
    return CircuitDesign(
        name=design_name(use),
        components=(
            CircuitComponent(
                reference=allocator.next("J"),
                symbol_id="stdlib:CONN_01X02",
                value=string_param(use, "control_value", "CTRL IN"),
                pins=(
                    CircuitPin(number="1", net=control, role="control_in"),
                    CircuitPin(number="2", net=gnd, role="control_return"),
                ),
            ),
            CircuitComponent(
                reference=allocator.next("Q"),
                symbol_id="stdlib:NMOS",
                value=string_param(use, "value", "Low-side switch"),
                pins=(
                    CircuitPin(number="1", net=control, role="gate"),
                    CircuitPin(number="2", net=switched_return, role="drain"),
                    CircuitPin(number="3", net=gnd, role="source"),
                ),
            ),
        ),
        nets=(
            CircuitNet(name=control, role="control"),
            CircuitNet(name=switched_return, role="switched_return"),
            CircuitNet(name=gnd, role="return"),
        ),
        notes=("Reusable template: low_side_mosfet_switch",),
    )


def build_gpio_led_output(
    use: CircuitTemplateUse,
    allocator: ReferenceAllocator,
) -> CircuitDesign:
    signal = bound_net(use, "signal", "GPIO")
    gnd = bound_net(use, "gnd", "GND")
    mid = internal_net(use, "GPIO_LED")
    return CircuitDesign(
        name=design_name(use),
        components=(
            CircuitComponent(
                reference=allocator.next("R"),
                symbol_id="stdlib:R",
                value=string_param(use, "resistor_value", "330R"),
                pins=(
                    CircuitPin(number="1", net=signal, role="input"),
                    CircuitPin(number="2", net=mid, role="output"),
                ),
            ),
            CircuitComponent(
                reference=allocator.next("LED"),
                symbol_id="stdlib:LED",
                value=string_param(use, "led_value", "Red LED"),
                footprint_id="stdlib:LED_0603",
                pins=(
                    CircuitPin(number="1", net=mid, role="anode"),
                    CircuitPin(number="2", net=gnd, role="cathode"),
                ),
            ),
        ),
        nets=(
            CircuitNet(name=signal, role="signal"),
            CircuitNet(name=mid, role="led_string"),
            CircuitNet(name=gnd, role="return"),
        ),
        notes=("Reusable template: gpio_led_output",),
    )


__all__ = [
    "DECOUPLING_CAPACITOR",
    "GPIO_LED_OUTPUT",
    "LOW_SIDE_MOSFET_SWITCH",
    "POWER_INPUT_2PIN",
    "build_decoupling_capacitor",
    "build_gpio_led_output",
    "build_low_side_mosfet_switch",
    "build_power_input_2pin",
]
