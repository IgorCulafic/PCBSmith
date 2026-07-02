from __future__ import annotations

from pathlib import Path

from pcbsmith.calculators.electronics import solve_lm2596_buck
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

SUPPORTED_TOPOLOGY_ID = "lm2596_buck_regulator"


def compose_lm2596_buck(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for LM2596 buck composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for LM2596 buck composition")

    result = solve_lm2596_buck(
        input_voltage_min_v=float(intent.assumptions["input_voltage_min_v"]),
        input_voltage_nominal_v=float(intent.assumptions["input_voltage_nominal_v"]),
        input_voltage_max_v=float(intent.assumptions["input_voltage_max_v"]),
        output_voltage_v=float(intent.assumptions["output_voltage_v"]),
        load_current_a=float(intent.assumptions["load_current_a"]),
    )
    if result["status"] == "error":
        raise ValueError(
            "LM2596 buck calculator rejected the request: " + "; ".join(result["errors"])
        )
    outputs = result["outputs"]

    datasheet_evidence = (
        EvidenceRef(
            kind="datasheet_procedure",
            title="TI LM2596 datasheet design procedure",
            locator="ai_assets/datasheets/ti-lm2596.pdf",
        ),
    )
    datasheet_example_evidence = (
        EvidenceRef(
            kind="datasheet_example",
            title="TI LM2596 adjustable design example component values",
            locator="ai_assets/datasheets/ti-lm2596.pdf design example",
        ),
    )
    inductance_uh = outputs["selected_inductance_uH"]
    feedback_upper = outputs["selected_feedback_upper_ohms"]
    feedback_lower = outputs["feedback_lower_ohms"]

    calculations = {
        "duty_cycle_nominal": outputs["duty_cycle_nominal"],
        "ripple_current_a": outputs["ripple_current_a"],
        "minimum_inductance_uH": outputs["minimum_inductance_uH"],
        "selected_inductance_uH": inductance_uh,
        "minimum_output_capacitance_uF": outputs["minimum_output_capacitance_uF"],
        "selected_output_capacitance_uF": outputs["selected_output_capacitance_uF"],
        "feedback_lower_ohms": feedback_lower,
        "feedback_upper_ohms": outputs["feedback_upper_ohms"],
        "selected_feedback_upper_ohms": feedback_upper,
        "regulated_output_v": outputs["regulated_output_v"],
        "switching_frequency_hz": outputs["switching_frequency_hz"],
        "input_voltage_nominal_v": float(intent.assumptions["input_voltage_nominal_v"]),
        "load_current_a": float(intent.assumptions["load_current_a"]),
    }
    findings = (
        *(str(warning) for warning in result["warnings"]),
        "Output capacitor uses the datasheet design-example 220uF low-ESR value, "
        "above the capacitive-ripple minimum; ESR selection needs datasheet review.",
        "Closed-loop regulation, transient response, and thermal behaviour are not "
        "verified; the LM2596 has no public SPICE model.",
    )
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=(
            ComponentRole(
                reference="P1",
                role="input_connector",
                symbol_id="stdlib:CONN_01X02",
                value="12V input",
                support_status="demo_only",
                footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
                evidence=datasheet_evidence,
            ),
            ComponentRole(
                reference="CIN",
                role="input_capacitor",
                symbol_id="stdlib:CP",
                value="100uF",
                support_status="needs_datasheet_review",
                footprint="Capacitor_SMD:CP_Elec_8x10",
                evidence=datasheet_example_evidence,
            ),
            ComponentRole(
                reference="U1",
                role="buck_regulator",
                symbol_id="stdlib:LM2596",
                value="LM2596S-ADJ",
                support_status="needs_datasheet_review",
                footprint="Package_TO_SOT_SMD:TO-263-5_TabPin3",
                evidence=datasheet_evidence,
            ),
            ComponentRole(
                reference="D1",
                role="catch_diode",
                symbol_id="stdlib:D_SCHOTTKY",
                value="SS34",
                support_status="needs_datasheet_review",
                footprint="Diode_SMD:D_SMA",
                evidence=datasheet_evidence,
            ),
            ComponentRole(
                reference="L1",
                role="power_inductor",
                symbol_id="stdlib:L",
                value=f"{inductance_uh:g}uH",
                support_status="needs_datasheet_review",
                footprint="Inductor_SMD:L_12x12mm_H8mm",
                evidence=datasheet_evidence,
            ),
            ComponentRole(
                reference="COUT",
                role="output_capacitor",
                symbol_id="stdlib:CP",
                value="220uF",
                support_status="needs_datasheet_review",
                footprint="Capacitor_SMD:CP_Elec_8x10",
                evidence=datasheet_example_evidence,
            ),
            ComponentRole(
                reference="RFB1",
                role="feedback_upper",
                symbol_id="stdlib:R",
                value=f"{feedback_upper / 1000:g}k",
                support_status="demo_only",
                footprint="Resistor_SMD:R_0603_1608Metric",
                evidence=datasheet_evidence,
            ),
            ComponentRole(
                reference="RFB2",
                role="feedback_lower",
                symbol_id="stdlib:R",
                value=f"{feedback_lower / 1000:g}k",
                support_status="demo_only",
                footprint="Resistor_SMD:R_0603_1608Metric",
                evidence=datasheet_evidence,
            ),
            ComponentRole(
                reference="P2",
                role="output_connector",
                symbol_id="stdlib:CONN_01X02",
                value="5V output",
                support_status="demo_only",
                footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
                evidence=datasheet_evidence,
            ),
        ),
        nets=("VIN", "SW", "VOUT", "FB", "GND"),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=findings,
        ),
    )


def write_lm2596_buck_project(
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
