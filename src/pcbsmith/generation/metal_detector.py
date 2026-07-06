"""Metal detector: exposed PCB spiral coil + common-base Colpitts oscillator.

The sensing element is the board itself: a 20-turn exposed spiral trace
whose inductance comes from the Mohan current-sheet approximation. Metal
near the coil lowers L through eddy currents, raising the oscillation
frequency at FOUT. Detection (frequency measurement and thresholding) is
an external contract, stated as a finding.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.calculators.electronics import (
    solve_colpitts_oscillator,
    solve_pcb_spiral_inductor,
)
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
from pcbsmith.kicad.metal_detector_board import (
    SPIRAL_OUTER_RADIUS,
    SPIRAL_PITCH,
    SPIRAL_TRACE_W,
    SPIRAL_TURNS,
)
from pcbsmith.services.project_io import save_board, save_project, save_schematic

SUPPORTED_TOPOLOGY_ID = "metal_detector_coil"

TANK_C_F = 2.2e-9
BASE_BIAS_OHMS = 47_000.0
EMITTER_OHMS = 1_000.0
OUTPUT_SERIES_OHMS = 1_000.0

DETECTION_FINDING = (
    "Detection contract (NOT verified by this pipeline): FOUT carries the "
    "oscillator frequency; measure it with a counter or MCU input capture. "
    "Metal near the exposed coil lowers its inductance through eddy "
    "currents and RAISES the frequency - a few kHz for a coin at close "
    "range. Ferrites raise L and lower the frequency instead."
)
FINISH_FINDING = (
    "The coil is exposed through a soldermask opening; the fab's surface "
    "finish (HASL/ENIG) will coat it. That does not affect operation but "
    "the copper is unprotected against scratches - specify ENIG for "
    "durability."
)


def compose_metal_detector(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for metal detector composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for metal detector composition")

    supply_v = float(intent.assumptions["supply_voltage_v"])
    coil = solve_pcb_spiral_inductor(
        outer_diameter_m=2 * SPIRAL_OUTER_RADIUS / 1000.0,
        trace_width_m=SPIRAL_TRACE_W / 1000.0,
        trace_gap_m=(SPIRAL_PITCH - SPIRAL_TRACE_W) / 1000.0,
        turns=SPIRAL_TURNS,
    )
    if coil["status"] == "error":
        raise ValueError("; ".join(coil["errors"]))
    inductance_h = float(coil["outputs"]["inductance_h"])
    oscillator = solve_colpitts_oscillator(
        supply_voltage_v=supply_v,
        inductance_h=inductance_h,
        tank_c1_f=TANK_C_F,
        tank_c2_f=TANK_C_F,
        emitter_resistor_ohms=EMITTER_OHMS,
        base_upper_ohms=BASE_BIAS_OHMS,
        base_lower_ohms=BASE_BIAS_OHMS,
    )
    if oscillator["status"] == "error":
        raise ValueError("; ".join(oscillator["errors"]))
    frequency_hz = float(oscillator["outputs"]["frequency_hz"])
    coil_quality = solve_pcb_spiral_inductor(
        outer_diameter_m=2 * SPIRAL_OUTER_RADIUS / 1000.0,
        trace_width_m=SPIRAL_TRACE_W / 1000.0,
        trace_gap_m=(SPIRAL_PITCH - SPIRAL_TRACE_W) / 1000.0,
        turns=SPIRAL_TURNS,
        frequency_hz=frequency_hz,
    )

    formula_evidence = (
        EvidenceRef(
            kind="textbook_formula",
            title="Planar spiral inductance (current-sheet approximation)",
            locator=(
                "Mohan, del Mar Hershenson, Boyd, Lee, IEEE JSSC 34(10) "
                "1999; circle coefficients c1=1.00 c2=2.46 c3=0 c4=0.20"
            ),
        ),
        EvidenceRef(
            kind="textbook_formula",
            title="Colpitts oscillator frequency",
            locator="f = 1 / (2*pi*sqrt(L * C1*C2/(C1+C2)))",
        ),
    )
    bjt_evidence = (
        EvidenceRef(
            kind="engineering_assumption",
            title="2N3904-class NPN small-signal transistor",
            locator=(
                "Generic MMBT3904 assumed (fT ~300 MHz >> 1.1 MHz "
                "oscillation); validate the concrete part's datasheet "
                "before fabrication."
            ),
        ),
    )

    calculations = {
        "supply_voltage_v": supply_v,
        "coil_inductance_h": inductance_h,
        "coil_dc_resistance_ohm": coil["outputs"]["dc_resistance_ohm"],
        "coil_trace_length_m": coil["outputs"]["trace_length_m"],
        "coil_quality_factor": coil_quality["outputs"]["quality_factor"],
        "coil_turns": SPIRAL_TURNS,
        "tank_c1_f": TANK_C_F,
        "tank_c2_f": TANK_C_F,
        "oscillation_frequency_hz": frequency_hz,
        "collector_current_a": oscillator["outputs"]["collector_current_a"],
        "emitter_resistor_ohms": EMITTER_OHMS,
        "base_bias_ohms": BASE_BIAS_OHMS,
        "output_series_ohms": OUTPUT_SERIES_OHMS,
    }
    findings = (
        *(str(w) for w in coil_quality["warnings"]),
        *(str(w) for w in oscillator["warnings"]),
        f"The coil is {SPIRAL_TURNS} exposed turns, "
        f"{coil['outputs']['trace_length_m']:.2f} m of trace, "
        f"{inductance_h * 1e6:.1f} uH with "
        f"{coil['outputs']['dc_resistance_ohm']:.2f} ohm DCR; the tank "
        f"oscillates near {frequency_hz / 1e6:.2f} MHz.",
        DETECTION_FINDING,
        FINISH_FINDING,
    )

    def part(
        reference: str, role: str, symbol: str, value: str, footprint: str,
        status: str = "demo_only",
        evidence: tuple[EvidenceRef, ...] = formula_evidence,
    ) -> ComponentRole:
        return ComponentRole(
            reference=reference,
            role=role,
            symbol_id=symbol,
            value=value,
            support_status=status,
            footprint=footprint,
            evidence=evidence,
        )

    resistor_fp = "Resistor_SMD:R_0603_1608Metric"
    capacitor_fp = "Capacitor_SMD:C_0603_1608Metric"
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=(
            part(
                "P1", "interface_connector", "stdlib:CONN_01X03",
                f"{supply_v:g}V VCC/GND/FOUT",
                "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
            ),
            part(
                "Q1", "oscillator_transistor", "stdlib:NPN", "MMBT3904",
                "Package_TO_SOT_SMD:SOT-23",
                status="needs_datasheet_review", evidence=bjt_evidence,
            ),
            part("R1", "base_bias_upper", "stdlib:R", "47k", resistor_fp),
            part("R2", "base_bias_lower", "stdlib:R", "47k", resistor_fp),
            part("R3", "emitter_resistor", "stdlib:R", "1k", resistor_fp),
            part("R4", "output_series_resistor", "stdlib:R", "1k", resistor_fp),
            part("C1", "tank_capacitor_upper", "stdlib:C", "2.2nF", capacitor_fp),
            part("C2", "tank_capacitor_lower", "stdlib:C", "2.2nF", capacitor_fp),
            part("C3", "output_coupling_capacitor", "stdlib:C", "10nF", capacitor_fp),
            part("C4", "supply_decoupling_capacitor", "stdlib:C", "100nF", capacitor_fp),
            part("C5", "base_bypass_capacitor", "stdlib:C", "100nF", capacitor_fp),
            part(
                "L1", "sensing_coil", "stdlib:L",
                f"{inductance_h * 1e6:.1f}uH PCB spiral",
                "NetTie:NetTie-2_SMD_Pad2.0mm",
            ),
        ),
        nets=("VCC", "GND", "BASE", "EM", "COL", "FO_A", "FOUT"),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=findings,
        ),
    )


def write_metal_detector_project(
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
