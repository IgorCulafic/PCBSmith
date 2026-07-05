"""MPU-6050 IMU breakout composition.

Circuit per the datasheet's typical operating circuit (PS-MPU-6000A-00 rev
3.4, section 7.2, p22): REGOUT 0.1uF, VDD bypass 0.1uF, CPOUT 2.2nF, VLOGIC
10nF (VLOGIC tied to VDD on a 3.3 V system), plus I2C pullups sized by the
deterministic calculator and an AD0 pulldown selecting address 0x68. CLKIN
and FSYNC tie to GND per section 7.1; RESV pins stay unconnected.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.calculators.electronics import solve_i2c_pullup
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

SUPPORTED_TOPOLOGY_ID = "mpu6050_imu"

DATASHEET = "ai_assets/datasheets/mpu6050.pdf"


def compose_mpu6050(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for MPU-6050 composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for MPU-6050 composition")

    supply_v = float(intent.assumptions["supply_voltage_v"])
    result = solve_i2c_pullup(
        supply_voltage_v=supply_v,
        bus_capacitance_pf=float(intent.assumptions["i2c_bus_capacitance_pf"]),
        rise_time_ns=float(intent.assumptions["i2c_rise_time_ns"]),
    )
    if result["status"] == "error":
        raise ValueError(
            "I2C pullup calculator rejected the request: " + "; ".join(result["errors"])
        )
    pullup_ohms = float(result["outputs"]["selected_ohms"])

    circuit_evidence = (
        EvidenceRef(
            kind="datasheet_procedure",
            title="MPU-6050 typical operating circuit",
            locator=f"{DATASHEET} p22 section 7.2",
        ),
    )
    pin_evidence = (
        EvidenceRef(
            kind="datasheet_fact",
            title="MPU-6050 pin out and signal description",
            locator=f"{DATASHEET} p21 section 7.1",
        ),
    )
    calculations = {
        "supply_voltage_v": supply_v,
        "i2c_pullup_minimum_ohms": result["outputs"]["minimum_ohms"],
        "i2c_pullup_maximum_ohms": result["outputs"]["maximum_ohms"],
        "i2c_pullup_selected_ohms": pullup_ohms,
        "i2c_bus_capacitance_pf": float(intent.assumptions["i2c_bus_capacitance_pf"]),
    }
    findings = (
        *(str(warning) for warning in result["warnings"]),
        "VLOGIC is tied to VDD (permitted: VLOGIC = 1.8V+/-5% or VDD, datasheet "
        "p12); AD0 pulls low, so the I2C address is 0x68.",
        "Datasheet gyroscope operating current is 3.6 mA (p10); the supply pin "
        "carries no simulated load because the sensor core has no SPICE model.",
    )

    def cap(reference: str, role: str, value: str) -> ComponentRole:
        return ComponentRole(
            reference=reference,
            role=role,
            symbol_id="stdlib:C",
            value=value,
            support_status="needs_datasheet_review",
            footprint="Capacitor_SMD:C_0603_1608Metric",
            evidence=circuit_evidence,
        )

    def resistor(reference: str, role: str) -> ComponentRole:
        return ComponentRole(
            reference=reference,
            role=role,
            symbol_id="stdlib:R",
            value=f"{pullup_ohms / 1000:g}k",
            support_status="demo_only",
            footprint="Resistor_SMD:R_0603_1608Metric",
            evidence=circuit_evidence,
        )

    return CircuitObject(
        intent=intent,
        topology=topology,
        components=(
            ComponentRole(
                reference="P1",
                role="io_connector",
                symbol_id="stdlib:CONN_01X04",
                value=f"{supply_v:g}V I2C",
                support_status="demo_only",
                footprint=(
                    "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
                ),
                evidence=pin_evidence,
            ),
            ComponentRole(
                reference="U1",
                role="imu_sensor",
                symbol_id="stdlib:MPU6050",
                value="MPU-6050",
                support_status="needs_datasheet_review",
                footprint="Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm",
                evidence=(*circuit_evidence, *pin_evidence),
            ),
            cap("C1", "regout_filter_capacitor", "100nF"),
            cap("C2", "vdd_bypass_capacitor", "100nF"),
            cap("C3", "charge_pump_capacitor", "2.2nF"),
            cap("C4", "vlogic_bypass_capacitor", "10nF"),
            resistor("R1", "i2c_sda_pullup"),
            resistor("R2", "i2c_scl_pullup"),
            resistor("R3", "address_select_pulldown"),
        ),
        nets=("VDD", "GND", "SDA", "SCL", "AD0", "REGOUT", "CPOUT"),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=findings,
        ),
    )


def write_mpu6050_project(
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
