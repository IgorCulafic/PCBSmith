"""Pear LED-ring board: three drive nets, one resistor+LED branch per unit.

The unit count per ring comes from the board geometry (units are pitched
along the ring paths), so the composition asks the board module how many
branches each ring carries.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.calculators.electronics import solve_led_series_string
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
from pcbsmith.kicad.pear_board import ring_unit_counts
from pcbsmith.services.project_io import save_board, save_project, save_schematic

SUPPORTED_TOPOLOGY_ID = "pear_led_rings"

DRIVE_FINDING = (
    "Drive contract (NOT verified by this pipeline): each ring net L1..L3 "
    "is switched externally at the supply voltage through P1; there is no "
    "on-board driver. All branches of a ring light together."
)


def compose_pear(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for pear composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for pear composition")

    supply_v = float(intent.assumptions["supply_voltage_v"])
    led = solve_led_series_string(
        supply_voltage_v=supply_v,
        led_forward_voltage_v=float(intent.assumptions["led_forward_voltage_v"]),
        target_current_a=float(intent.assumptions["led_target_current_a"]),
        led_count=1,
    )
    if led["status"] == "error":
        raise ValueError("; ".join(led["errors"]))
    led_ohms = float(led["outputs"]["selected_resistor_ohms"])

    counts = ring_unit_counts()
    total = sum(counts)
    per_ring_current = [
        count * float(led["outputs"]["current_with_selected_a"]) for count in counts
    ]

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
    resistor_evidence = (
        EvidenceRef(
            kind="textbook_formula",
            title="LED series resistor sizing",
            locator="R = (Vsupply - Vf) / I, nearest E24",
        ),
    )

    calculations = {
        "supply_voltage_v": supply_v,
        "led_resistor_ohms": led["outputs"]["resistor_ohms"],
        "led_selected_resistor_ohms": led_ohms,
        "led_current_a": led["outputs"]["current_with_selected_a"],
        "led_forward_voltage_v": float(intent.assumptions["led_forward_voltage_v"]),
        "ring1_led_count": counts[0],
        "ring2_led_count": counts[1],
        "ring3_led_count": counts[2],
        "ring1_current_a": round(per_ring_current[0], 4),
        "ring2_current_a": round(per_ring_current[1], 4),
        "ring3_current_a": round(per_ring_current[2], 4),
    }
    findings = (
        *(str(w) for w in led["warnings"]),
        f"{total} LED branches across three rings; ring supply currents are "
        f"{per_ring_current[0] * 1000:.0f}/{per_ring_current[1] * 1000:.0f}/"
        f"{per_ring_current[2] * 1000:.0f} mA - size the external driver "
        "accordingly.",
        DRIVE_FINDING,
    )

    components: list[ComponentRole] = [
        ComponentRole(
            reference="P1",
            role="drive_connector",
            symbol_id="stdlib:CONN_01X04",
            value=f"{supply_v:g}V GND/L3/L2/L1",
            support_status="demo_only",
            footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
            evidence=resistor_evidence,
        ),
    ]
    unit = 0
    nets: list[str] = ["GND", "L1", "L2", "L3"]
    for ring, count in enumerate(counts):
        for _ in range(count):
            unit += 1
            components.append(
                ComponentRole(
                    reference=f"R{unit}",
                    role=f"ring{ring + 1}_series_resistor",
                    symbol_id="stdlib:R",
                    value=(
                        f"{led_ohms:g}"
                        if led_ohms < 1000
                        else f"{led_ohms / 1000:g}k"
                    ),
                    support_status="demo_only",
                    footprint="Resistor_SMD:R_0603_1608Metric",
                    evidence=resistor_evidence,
                )
            )
            components.append(
                ComponentRole(
                    reference=f"D{unit}",
                    role=f"ring{ring + 1}_led",
                    symbol_id="stdlib:LED",
                    value="Green LED",
                    support_status="needs_datasheet_review",
                    footprint="LED_SMD:LED_0603_1608Metric",
                    evidence=led_evidence,
                )
            )
            nets.append(f"D{unit}_A")

    return CircuitObject(
        intent=intent,
        topology=topology,
        components=tuple(components),
        nets=tuple(nets),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=findings,
        ),
    )


def write_pear_project(
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
