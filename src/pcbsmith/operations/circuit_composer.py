from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.circuit import (
    CircuitComponent,
    CircuitDesign,
    CircuitNet,
    CircuitPin,
    compose_circuit_designs,
)

CircuitBlockParam = str | int | float | bool


class CircuitBlockUse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    instance: str = ""
    net_bindings: dict[str, str] = Field(default_factory=dict)
    params: dict[str, CircuitBlockParam] = Field(default_factory=dict)


class _ReferenceAllocator:
    def __init__(self) -> None:
        self._next_by_prefix: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        next_number = self._next_by_prefix.get(prefix, 0) + 1
        self._next_by_prefix[prefix] = next_number
        return f"{prefix}{next_number}"


_BlockFactory = Callable[[CircuitBlockUse, _ReferenceAllocator], CircuitDesign]


def compose_circuit_blocks(
    name: str,
    blocks: tuple[CircuitBlockUse, ...],
) -> CircuitDesign:
    allocator = _ReferenceAllocator()
    designs: list[CircuitDesign] = []
    for block in blocks:
        try:
            factory = _BLOCK_FACTORIES[block.name]
        except KeyError as exc:
            raise ValueError(f"Unknown circuit block: {block.name}") from exc
        designs.append(factory(block, allocator))
    return compose_circuit_designs(name, *designs)


def _power_input_2pin(
    block: CircuitBlockUse,
    allocator: _ReferenceAllocator,
) -> CircuitDesign:
    vcc = _bound_net(block, "vcc", "VCC")
    gnd = _bound_net(block, "gnd", "GND")
    return CircuitDesign(
        name=_block_design_name(block),
        components=(
            CircuitComponent(
                reference=allocator.next("J"),
                symbol_id="stdlib:CONN_01X02",
                value=_string_param(block, "value", "Power input"),
                pins=(
                    CircuitPin(number="1", net=vcc, role="power_in"),
                    CircuitPin(number="2", net=gnd, role="power_return"),
                ),
            ),
        ),
        nets=(CircuitNet(name=vcc, role="power"), CircuitNet(name=gnd, role="return")),
        notes=("Reusable block: power_input_2pin",),
    )


def _decoupling_capacitor(
    block: CircuitBlockUse,
    allocator: _ReferenceAllocator,
) -> CircuitDesign:
    vcc = _bound_net(block, "vcc", "VCC")
    gnd = _bound_net(block, "gnd", "GND")
    return CircuitDesign(
        name=_block_design_name(block),
        components=(
            CircuitComponent(
                reference=allocator.next("C"),
                symbol_id="stdlib:C",
                value=_string_param(block, "value", "100nF"),
                pins=(
                    CircuitPin(number="1", net=vcc, role="power"),
                    CircuitPin(number="2", net=gnd, role="return"),
                ),
            ),
        ),
        nets=(CircuitNet(name=vcc, role="power"), CircuitNet(name=gnd, role="return")),
        notes=("Reusable block: decoupling_capacitor",),
    )


def _low_side_mosfet_switch(
    block: CircuitBlockUse,
    allocator: _ReferenceAllocator,
) -> CircuitDesign:
    control = _bound_net(block, "control", "CTRL")
    switched_return = _bound_net(block, "switched_return", "LED_RETURN")
    gnd = _bound_net(block, "gnd", "GND")
    components = [
        CircuitComponent(
            reference=allocator.next("J"),
            symbol_id="stdlib:CONN_01X02",
            value=_string_param(block, "control_value", "CTRL IN"),
            pins=(
                CircuitPin(number="1", net=control, role="control_in"),
                CircuitPin(number="2", net=gnd, role="control_return"),
            ),
        ),
        CircuitComponent(
            reference=allocator.next("Q"),
            symbol_id="stdlib:NMOS",
            value=_string_param(block, "value", "Low-side switch"),
            pins=(
                CircuitPin(number="1", net=control, role="gate"),
                CircuitPin(number="2", net=switched_return, role="drain"),
                CircuitPin(number="3", net=gnd, role="source"),
            ),
        ),
    ]
    return CircuitDesign(
        name=_block_design_name(block),
        components=tuple(components),
        nets=(
            CircuitNet(name=control, role="control"),
            CircuitNet(name=switched_return, role="switched_return"),
            CircuitNet(name=gnd, role="return"),
        ),
        notes=("Reusable block: low_side_mosfet_switch",),
    )


def _led_string(
    block: CircuitBlockUse,
    allocator: _ReferenceAllocator,
) -> CircuitDesign:
    led_count = _int_param(block, "led_count", 1, minimum=1)
    vcc = _bound_net(block, "vcc", "VCC")
    return_net = _bound_net(block, "return", "GND")
    components: list[CircuitComponent] = []
    nets: dict[str, CircuitNet] = {
        vcc: CircuitNet(name=vcc, role="power"),
        return_net: CircuitNet(name=return_net, role="return"),
    }

    previous_net = _internal_net(block, "LED_R")
    nets[previous_net] = CircuitNet(name=previous_net, role="led_string")
    components.append(
        CircuitComponent(
            reference=allocator.next("R"),
            symbol_id="stdlib:R",
            value=_string_param(block, "resistor_value", "330R"),
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
            else _internal_net(block, f"LED_{led_index}")
        )
        nets.setdefault(next_net, CircuitNet(name=next_net, role="led_string"))
        components.append(
            CircuitComponent(
                reference=allocator.next("LED"),
                symbol_id="stdlib:LED",
                value=_string_param(block, "led_value", "Red LED"),
                footprint_id="stdlib:LED_0603",
                pins=(
                    CircuitPin(number="1", net=previous_net, role="anode"),
                    CircuitPin(number="2", net=next_net, role="cathode"),
                ),
            )
        )
        previous_net = next_net

    return CircuitDesign(
        name=_block_design_name(block),
        components=tuple(components),
        nets=tuple(nets.values()),
        notes=(f"Reusable block: led_string ({led_count} LED(s))",),
    )


def _gpio_led_output(
    block: CircuitBlockUse,
    allocator: _ReferenceAllocator,
) -> CircuitDesign:
    signal = _bound_net(block, "signal", "GPIO")
    gnd = _bound_net(block, "gnd", "GND")
    mid = _internal_net(block, "GPIO_LED")
    return CircuitDesign(
        name=_block_design_name(block),
        components=(
            CircuitComponent(
                reference=allocator.next("R"),
                symbol_id="stdlib:R",
                value=_string_param(block, "resistor_value", "330R"),
                pins=(
                    CircuitPin(number="1", net=signal, role="input"),
                    CircuitPin(number="2", net=mid, role="output"),
                ),
            ),
            CircuitComponent(
                reference=allocator.next("LED"),
                symbol_id="stdlib:LED",
                value=_string_param(block, "led_value", "Red LED"),
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
        notes=("Reusable block: gpio_led_output",),
    )


def _bound_net(block: CircuitBlockUse, local_name: str, default: str) -> str:
    return block.net_bindings.get(local_name, default)


def _internal_net(block: CircuitBlockUse, local_name: str) -> str:
    instance = _safe_instance(block.instance or block.name)
    return f"{instance}_{local_name.upper()}"


def _block_design_name(block: CircuitBlockUse) -> str:
    if block.instance:
        return f"{block.name}:{block.instance}"
    return block.name


def _safe_instance(instance: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", instance).strip("_").upper()
    return safe or "BLOCK"


def _string_param(block: CircuitBlockUse, key: str, default: str) -> str:
    value = block.params.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a string")
    return str(value)


def _int_param(
    block: CircuitBlockUse,
    key: str,
    default: int,
    *,
    minimum: int,
) -> int:
    value = block.params.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    return parsed


_BLOCK_FACTORIES: Mapping[str, _BlockFactory] = {
    "power_input_2pin": _power_input_2pin,
    "decoupling_capacitor": _decoupling_capacitor,
    "low_side_mosfet_switch": _low_side_mosfet_switch,
    "led_string": _led_string,
    "gpio_led_output": _gpio_led_output,
}


__all__ = [
    "CircuitBlockUse",
    "compose_circuit_blocks",
]
