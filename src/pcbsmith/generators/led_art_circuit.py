from __future__ import annotations

from typing import Literal

from pcbsmith.core.circuit import CircuitComponent, CircuitDesign, CircuitNet, CircuitPin
from pcbsmith.generators.led_art import LedArtPlan

LedArtControlMode = Literal["none", "low_side_mosfet"]


def led_art_plan_to_circuit_design(
    plan: LedArtPlan,
    *,
    control_mode: LedArtControlMode = "none",
) -> CircuitDesign:
    components: list[CircuitComponent] = [
        CircuitComponent(
            reference="J1",
            symbol_id="stdlib:CONN_01X02",
            value=f"{plan.electrical.supply_voltage_v:g}V IN",
            pins=(
                CircuitPin(number="1", net="VCC", role="power_in"),
                CircuitPin(number="2", net="GND", role="power_return"),
            ),
        )
    ]
    nets: dict[str, CircuitNet] = {
        "VCC": CircuitNet(name="VCC", role="power"),
        "GND": CircuitNet(name="GND", role="return"),
    }
    return_net = "GND"
    if control_mode == "low_side_mosfet":
        return_net = "LED_RETURN"
        nets["LED_RETURN"] = CircuitNet(name="LED_RETURN", role="switched_return")
        nets["CTRL"] = CircuitNet(name="CTRL", role="control")
        components.extend(
            (
                CircuitComponent(
                    reference="J2",
                    symbol_id="stdlib:CONN_01X02",
                    value="CTRL IN",
                    pins=(
                        CircuitPin(number="1", net="CTRL", role="control_in"),
                        CircuitPin(number="2", net="GND", role="control_return"),
                    ),
                ),
                CircuitComponent(
                    reference="Q1",
                    symbol_id="stdlib:NMOS",
                    value="Low-side switch",
                    pins=(
                        CircuitPin(number="1", net="CTRL", role="gate"),
                        CircuitPin(number="2", net="LED_RETURN", role="drain"),
                        CircuitPin(number="3", net="GND", role="source"),
                    ),
                ),
            )
        )

    pixel_by_ref = {pixel.led_ref: pixel for pixel in plan.pixels}
    for string in plan.strings:
        previous_net = f"STR{string.index}_R"
        nets[previous_net] = CircuitNet(name=previous_net, role="led_string")
        components.append(
            CircuitComponent(
                reference=string.resistor_ref,
                symbol_id="stdlib:R",
                value=f"{string.resistor_value_ohms}R",
                pins=(
                    CircuitPin(number="1", net="VCC", role="input"),
                    CircuitPin(number="2", net=previous_net, role="output"),
                ),
            )
        )
        for led_offset, led_ref in enumerate(string.led_refs, start=1):
            is_last_led = led_offset == len(string.led_refs)
            next_net = return_net if is_last_led else f"STR{string.index}_{led_offset}"
            nets.setdefault(next_net, CircuitNet(name=next_net, role="led_string"))
            pixel_by_ref[led_ref]
            components.append(
                CircuitComponent(
                    reference=led_ref,
                    symbol_id="stdlib:LED",
                    value="Red LED",
                    footprint_id="stdlib:LED_0603",
                    pins=(
                        CircuitPin(number="1", net=previous_net, role="anode"),
                        CircuitPin(number="2", net=next_net, role="cathode"),
                    ),
                )
            )
            previous_net = next_net

    return CircuitDesign(
        name=f"{plan.electrical.text} LED art",
        components=tuple(components),
        nets=tuple(nets.values()),
        notes=(
            f"LED art topology: {plan.electrical.grouping_strategy}",
            f"LED count: {len(plan.pixels)}",
            f"String count: {len(plan.strings)}",
        ),
    )


__all__ = ["LedArtControlMode", "led_art_plan_to_circuit_design"]
