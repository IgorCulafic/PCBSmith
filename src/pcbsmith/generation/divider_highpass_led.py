from __future__ import annotations

from pcbsmith.calculators.passive import (
    led_current_limit,
    rc_highpass_cutoff_hz,
    voltage_divider,
)
from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)


def compose_divider_highpass_led(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported intent for divider/high-pass/LED composition")
    if topology.topology_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported topology for divider/high-pass/LED composition")

    divider = voltage_divider(
        input_voltage_v=5.0,
        r_top_ohms=10_000.0,
        r_bottom_ohms=10_000.0,
    )
    led = led_current_limit(
        supply_voltage_v=5.0,
        led_forward_voltage_v=2.0,
        resistor_ohms=680.0,
    )
    calculations = {
        "divider_output_voltage_v": divider["output_voltage_v"],
        "divider_current_ma": divider["divider_current_ma"],
        "highpass_cutoff_hz": rc_highpass_cutoff_hz(r_ohms=10_000.0, c_farads=100e-9),
        "led_nominal_current_ma": led["led_current_ma"],
        "led_resistor_power_w": led["resistor_power_w"],
    }
    demo_evidence = (
        EvidenceRef(
            kind="assumption",
            title="Generic passive SMD roles",
            locator="0603 R/C/LED are demo bindings until KiCad/library evidence is restored.",
        ),
    )
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=(
            ComponentRole(
                reference="R1",
                role="divider_top",
                symbol_id="stdlib:R",
                value="10k",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
            ComponentRole(
                reference="R2",
                role="divider_bottom",
                symbol_id="stdlib:R",
                value="10k",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
            ComponentRole(
                reference="C1",
                role="highpass_series_capacitor",
                symbol_id="stdlib:C",
                value="100nF",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
            ComponentRole(
                reference="R3",
                role="led_current_limit",
                symbol_id="stdlib:R",
                value="680R",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
            ComponentRole(
                reference="D1",
                role="indicator_led",
                symbol_id="stdlib:LED",
                value="Generic red LED",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
        ),
        nets=("VIN", "DIV_OUT", "HP_OUT", "LED_K", "GND"),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=(
                "LED after AC coupling is signal-dependent; deterministic LED current is only a nominal rail-reference check.",
                "Generic LED/passive bindings are demo-only until backed by real KiCad library and datasheet evidence.",
            ),
        ),
    )
