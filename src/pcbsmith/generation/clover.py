"""Four-leaf-clover tilt indicator: MPU-6050 + ATtiny84A + 4 leaf LEDs.

The MPU-6050 is a sensor, not a driver: tilt-to-LED behaviour requires the
on-board MCU to read the accelerometer over I2C and drive one GPIO per leaf.
That firmware contract is stated as a finding — this pipeline verifies the
hardware (connectivity, bus conditioning, LED bias), never the program.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.calculators.electronics import solve_i2c_pullup, solve_led_series_string
from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)
from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic
from pcbsmith.services.project_io import save_board, save_project, save_schematic

SUPPORTED_TOPOLOGY_ID = "clover_tilt_indicator"

LEAF_NETS = ("LEAF_NE", "LEAF_NW", "LEAF_SW", "LEAF_SE")

FIRMWARE_FINDING = (
    "Firmware contract (NOT verified by this pipeline): U2 reads the "
    "MPU-6050 accelerometer at I2C address 0x68 (AD0 tied low), computes the "
    "downhill direction from the X/Y gravity components, and drives exactly "
    "one of LEAF_NE/NW/SW/SE (PA0..PA3) high; INT (PA7) may be used for "
    "data-ready. U2's RESET pin relies on its internal pull-up - add a 10k "
    "pull-up and an ISP header before production programming."
)


def compose_clover(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for clover composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for clover composition")

    supply_v = float(intent.assumptions["supply_voltage_v"])
    pullup = solve_i2c_pullup(
        supply_voltage_v=supply_v,
        bus_capacitance_pf=float(intent.assumptions["i2c_bus_capacitance_pf"]),
        rise_time_ns=float(intent.assumptions["i2c_rise_time_ns"]),
    )
    if pullup["status"] == "error":
        raise ValueError("; ".join(pullup["errors"]))
    led = solve_led_series_string(
        supply_voltage_v=supply_v,
        led_forward_voltage_v=float(intent.assumptions["led_forward_voltage_v"]),
        target_current_a=float(intent.assumptions["led_target_current_a"]),
        led_count=1,
    )
    if led["status"] == "error":
        raise ValueError("; ".join(led["errors"]))
    pullup_ohms = float(pullup["outputs"]["selected_ohms"])
    led_ohms = float(led["outputs"]["selected_resistor_ohms"])

    mpu_evidence = (
        EvidenceRef(
            kind="datasheet_procedure",
            title="MPU-6050 typical operating circuit",
            locator="ai_assets/datasheets/mpu6050.pdf p22 section 7.2",
        ),
    )
    mcu_evidence = (
        EvidenceRef(
            kind="datasheet_fact",
            title="ATtiny84A operating voltage and I/O current",
            locator=(
                "ai_assets/datasheets/attiny84a.pdf p1 (1.8-5.5V), p174 "
                "(40 mA abs max per pin; IOL=5mA characterized at VCC=3V)"
            ),
        ),
    )
    led_evidence = (
        EvidenceRef(
            kind="datasheet_fact",
            title="Kingbright APT1608SGC green LED forward voltage",
            locator=(
                "ai_assets/datasheets/apt1608sgc.pdf p2-3 (Kingbright "
                "APT1608SGC: VF typ 2.2V max 2.5V @20mA; IF max 25mA; "
                "sha256 3256acec755bc198...)"
            ),
        ),
    )

    calculations = {
        "supply_voltage_v": supply_v,
        "i2c_pullup_selected_ohms": pullup_ohms,
        "led_resistor_ohms": led["outputs"]["resistor_ohms"],
        "led_selected_resistor_ohms": led_ohms,
        "led_current_a": led["outputs"]["current_with_selected_a"],
        "led_forward_voltage_v": float(intent.assumptions["led_forward_voltage_v"]),
    }
    findings = (
        *(str(w) for w in pullup["warnings"]),
        *(str(w) for w in led["warnings"]),
        "LED current is set to 5 mA to stay inside the ATtiny84A's "
        "characterized IOL=5mA @ VCC=3V output-low condition (p174).",
        FIRMWARE_FINDING,
    )

    def cap(reference: str, role: str, value: str) -> ComponentRole:
        return ComponentRole(
            reference=reference,
            role=role,
            symbol_id="stdlib:C",
            value=value,
            support_status="needs_datasheet_review",
            footprint="Capacitor_SMD:C_0603_1608Metric",
            evidence=mpu_evidence,
        )

    def resistor(reference: str, role: str, ohms: float) -> ComponentRole:
        return ComponentRole(
            reference=reference,
            role=role,
            symbol_id="stdlib:R",
            value=f"{ohms:g}" if ohms < 1000 else f"{ohms / 1000:g}k",
            support_status="demo_only",
            footprint="Resistor_SMD:R_0603_1608Metric",
            evidence=mpu_evidence,
        )

    leds = tuple(
        ComponentRole(
            reference=f"D{index + 1}",
            role=f"leaf_led_{LEAF_NETS[index][5:].lower()}",
            symbol_id="stdlib:LED",
            value="Green LED",
            support_status="needs_datasheet_review",
            footprint="LED_SMD:LED_0603_1608Metric",
            evidence=led_evidence,
        )
        for index in range(4)
    )
    leaf_resistors = tuple(
        resistor(f"R{index + 3}", f"leaf_resistor_{LEAF_NETS[index][5:].lower()}", led_ohms)
        for index in range(4)
    )

    return CircuitObject(
        intent=intent,
        topology=topology,
        components=(
            ComponentRole(
                reference="P1",
                role="power_connector",
                symbol_id="stdlib:CONN_01X02",
                value=f"{supply_v:g}V",
                support_status="demo_only",
                footprint=(
                    "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
                ),
                evidence=mpu_evidence,
            ),
            ComponentRole(
                reference="U1",
                role="imu_sensor",
                symbol_id="stdlib:MPU6050",
                value="MPU-6050",
                support_status="needs_datasheet_review",
                footprint="Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm",
                evidence=mpu_evidence,
            ),
            ComponentRole(
                reference="U2",
                role="mcu",
                symbol_id="stdlib:ATTINY84",
                value="ATtiny84A",
                support_status="needs_datasheet_review",
                footprint="Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
                evidence=mcu_evidence,
            ),
            cap("C1", "regout_filter_capacitor", "100nF"),
            cap("C2", "vdd_bypass_capacitor", "100nF"),
            cap("C3", "charge_pump_capacitor", "2.2nF"),
            cap("C4", "vlogic_bypass_capacitor", "10nF"),
            cap("C5", "mcu_bypass_capacitor", "100nF"),
            resistor("R1", "i2c_sda_pullup", pullup_ohms),
            resistor("R2", "i2c_scl_pullup", pullup_ohms),
            *leaf_resistors,
            *leds,
        ),
        nets=(
            "VDD", "GND", "SDA", "SCL", "INT", "REGOUT", "CPOUT",
            *LEAF_NETS,
            *(f"{net}_A" for net in LEAF_NETS),
        ),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=findings,
        ),
    )


def write_clover_project(
    circuit: CircuitObject,
    project_dir: Path,
    *,
    project_name: str,
) -> None:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for project generation")
    project = Project(name=project_name)
    save_project(project_dir, project)
    save_schematic(project_dir, project.schematics[0], Schematic(id="main"))
    save_board(project_dir, project.boards[0], Board(id="main"))
