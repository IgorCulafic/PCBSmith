"""555 servo driver/tester composition.

The circuit is the 555-timer-circuits.com SERVO TESTER, which the
instructable "Drive Servos With a 555 Timer IC" reproduces: a 555
astable whose charge path (33k) always runs, but whose timing branch
only completes while one of two momentary buttons is held - FORWARD
through 68k, REVERSE through 10k. A BC547 inverts pin 3 so the servo
sees a positive pulse equal to the astable's LOW time. Both branches
sit OUTSIDE the 0.9-2.1ms proportional window on purpose: this is an
end-stop driver/tester.

Board-level additions beyond the source (each carried as a finding):
VCC bypass at the 555 (SLFS022 p18 demands it anyway), bulk
electrolytic at the servo header for stall spikes, screw-terminal
power entry, test pads, and mounting holes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pcbsmith.calculators.electronics import solve_555_servo_tester
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
from pcbsmith.reporting.review_pack import TestStep
from pcbsmith.services.project_io import save_board, save_project, save_schematic

SUPPORTED_TOPOLOGY_ID = "servo_555_tester"

SOURCE_LOCATOR = (
    "555-timer-circuits.com SERVO TESTER schematic (reproduced by "
    "instructables.com/Drive-Servos-with-a-555-timer-IC)"
)

CAPACITOR_DISCREPANCY_FINDING = (
    "UNCERTAIN SOURCE VALUE: the original schematic shows 10n on the "
    "555 CONT pin (pin 5); the instructable's parts list says '2 - 100n "
    "capacitors'. This board follows the SCHEMATIC (10n) - the pin-5 "
    "bypass is non-critical and either value works (SLFS022 p18 "
    "recommends 0.01uF)."
)

END_STOP_FINDING = (
    "BEHAVIOUR: FORWARD produces ~4.7ms pulses at ~85Hz and REVERSE "
    "~0.69ms at ~272Hz - both outside the 0.9-2.1ms proportional "
    "window, so the servo slams to its end stops while a button is "
    "held. That matches the source project's intent (drive/test, not "
    "proportional control); the source's pot variant is the "
    "proportional circuit."
)

AXIAL = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"
DISC = "Capacitor_THT:C_Disc_D4.7mm_W2.5mm_P5.00mm"


def _source(title: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="reference_design", title=title, locator=SOURCE_LOCATOR
        ),
    )


def _assumption(title: str, locator: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(kind="engineering_assumption", title=title, locator=locator),
    )


def _resistor(
    reference: str, role: str, value: str,
    evidence: tuple[EvidenceRef, ...],
) -> ComponentRole:
    return ComponentRole(
        reference=reference, role=role, symbol_id="stdlib:R", value=value,
        support_status="needs_datasheet_review", footprint=AXIAL,
        evidence=evidence,
    )


def _capacitor(
    reference: str, role: str, value: str, footprint: str,
    evidence: tuple[EvidenceRef, ...],
) -> ComponentRole:
    return ComponentRole(
        reference=reference, role=role, symbol_id="stdlib:C", value=value,
        support_status="needs_datasheet_review", footprint=footprint,
        evidence=evidence,
    )


def compose_servo555(
    intent: CircuitIntent, topology: TopologySelection
) -> CircuitObject:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for servo555 composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for servo555 composition")

    design = solve_555_servo_tester(
        vcc_v=float(intent.assumptions["supply_voltage_v"]),
    )
    if design["status"] == "error":
        raise ValueError("; ".join(design["errors"]))
    out = design["outputs"]

    components = (
        ComponentRole(
            reference="J1", role="power_input_terminal",
            symbol_id="stdlib:CONN_01X02", value="5-6V DC IN",
            support_status="needs_datasheet_review",
            footprint=(
                "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-2-5.08"
                "_1x02_P5.08mm_Horizontal"
            ),
            evidence=_assumption(
                "Screw-terminal power entry",
                "Prompt requirement; the source uses a bare 6V pack.",
            ),
        ),
        ComponentRole(
            reference="U1", role="timer_ic",
            symbol_id="stdlib:NE555", value="NE555 (socketed)",
            support_status="supported",
            footprint="Package_DIP:DIP-8_W7.62mm_Socket",
            evidence=(
                EvidenceRef(
                    kind="datasheet_fact",
                    title="NE555 astable timing and supply range",
                    locator=(
                        "SLFS022 (ai_assets/datasheets/ne555.pdf) section "
                        "6.3.2 p12 eq 1-3; VCC 4.5-16V p3"
                    ),
                ),
            ),
        ),
        _resistor("R1", "timing_charge_resistor", "33k", _source(
            "Charge resistor VCC -> DISCH",
        )),
        _resistor("R2", "forward_branch_resistor", "68k", _source(
            "FORWARD button branch DISCH -> THRES",
        )),
        _resistor("R3", "reverse_branch_resistor", "10k", _source(
            "REVERSE button branch DISCH -> THRES",
        )),
        _resistor("R4", "base_resistor", "1k", _source(
            "555 OUT -> BC547 base",
        )),
        _resistor("R5", "collector_pullup", "4.7k", _source(
            "Servo-signal pull-up to VCC",
        )),
        _capacitor("C1", "timing_capacitor", "100n", DISC, _source(
            "Astable timing capacitor at THRES/TRIG",
        )),
        _capacitor("C2", "control_bypass_capacitor", "10n", DISC, (
            EvidenceRef(
                kind="reference_design",
                title="CONT pin bypass - VALUE FLAGGED",
                locator=(
                    f"{SOURCE_LOCATOR}; schematic shows 10n, the "
                    "instructable parts list says 100n - see the "
                    "uncertain-value finding"
                ),
            ),
        )),
        _capacitor("C3", "vcc_bypass_capacitor", "100n", DISC, (
            EvidenceRef(
                kind="datasheet_fact",
                title="VCC bypass capacitor",
                locator="SLFS022 p18: bypass highly recommended",
            ),
        )),
        ComponentRole(
            reference="C4", role="servo_bulk_capacitor",
            symbol_id="stdlib:CP", value="470uF 16V",
            support_status="needs_datasheet_review",
            footprint="Capacitor_THT:CP_Radial_D8.0mm_P3.50mm",
            evidence=_assumption(
                "Bulk reservoir at the servo header",
                "Prompt requirement (220-470uF): buffers servo stall/"
                "start spikes so the 555 supply stays clean.",
            ),
        ),
        ComponentRole(
            reference="Q1", role="signal_inverter_transistor",
            symbol_id="stdlib:NPN", value="BC547",
            support_status="needs_datasheet_review",
            footprint="Package_TO_SOT_THT:TO-92_Inline",
            evidence=_source("Inverting output stage"),
        ),
        ComponentRole(
            reference="SW1", role="forward_button",
            symbol_id="stdlib:SW_PUSH", value="FORWARD",
            support_status="needs_datasheet_review",
            footprint="Button_Switch_THT:SW_PUSH_6mm",
            evidence=_source("Momentary FORWARD control"),
        ),
        ComponentRole(
            reference="SW2", role="reverse_button",
            symbol_id="stdlib:SW_PUSH", value="REVERSE",
            support_status="needs_datasheet_review",
            footprint="Button_Switch_THT:SW_PUSH_6mm",
            evidence=_source("Momentary REVERSE control"),
        ),
        ComponentRole(
            reference="J2", role="servo_header",
            symbol_id="stdlib:CONN_01X03", value="GND/+V_SERVO/SIGNAL",
            support_status="needs_datasheet_review",
            footprint=(
                "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
            ),
            evidence=_assumption(
                "Standard 3-pin servo header",
                "Hobby convention: centre pin power so a reversed plug "
                "cannot swap VCC and GND.",
            ),
        ),
        *(
            ComponentRole(
                reference=f"TP{index}", role="test_point",
                symbol_id="stdlib:TESTPOINT", value=label,
                support_status="needs_datasheet_review",
                footprint="TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm",
                evidence=_assumption(
                    f"Test pad {label}", "Prompt requirement.",
                ),
            )
            for index, label in (
                (1, "TP_VCC"), (2, "TP_GND"),
                (3, "TP_555_OUT"), (4, "TP_SERVO_SIGNAL"),
            )
        ),
    )

    findings = (
        *(str(w) for w in design["warnings"]),
        CAPACITOR_DISCREPANCY_FINDING,
        END_STOP_FINDING,
        "ADDITIONS beyond the source (per the design prompt): screw "
        "terminal, VCC bypass, 470uF servo reservoir, test pads, "
        "mounting holes. The source breadboard has none of these.",
        "The BC547 pinout caution from the source ('be sure to look up "
        "your transistor') is resolved by the official TO-92 footprint "
        "and the KiCad BC547 symbol (1=C, 2=B, 3=E).",
    )

    calculations = {
        "forward_servo_pulse_ms": out["forward"]["servo_pulse_ms"],
        "forward_frame_rate_hz": out["forward"]["frame_rate_hz"],
        "reverse_servo_pulse_ms": out["reverse"]["servo_pulse_ms"],
        "reverse_frame_rate_hz": out["reverse"]["frame_rate_hz"],
        "base_current_ma": out["base_current_ma"],
        "forced_beta": out["forced_beta"],
        "output_high_v": out["output_high_v"],
    }
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=components,
        nets=(
            "VCC", "GND", "DIS", "THR", "CTRL", "OUT", "BASE", "SIG",
            "FWDM", "REVM",
        ),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=findings,
        ),
    )


def write_servo555_project(
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


def servo555_test_steps(outputs: dict[str, Any]) -> tuple[TestStep, ...]:
    """Bench plan from the calculator's design point."""
    forward = outputs["forward"]
    reverse = outputs["reverse"]
    return (
        TestStep(
            name="Visual + polarity",
            procedure=(
                "Check the electrolytic and power-input polarity marks; "
                "verify the BC547 flat face matches the silkscreen and "
                "the 555 notch matches the socket."
            ),
            expected="Marks match; no bridges",
            safety="Unpowered.",
        ),
        TestStep(
            name="Pre-power resistance",
            procedure="Meter +V to GND at the power terminal.",
            expected="No short; rises as the 470uF charges",
            safety="Unpowered.",
        ),
        TestStep(
            name="Idle state",
            procedure=(
                "Apply 6V from a current-limited supply (0.3A limit), "
                "no servo, no buttons pressed. Probe TP_SERVO_SIGNAL."
            ),
            expected=(
                "Quiescent current a few mA; the signal pad sits HIGH "
                "(pulled to VCC through 4k7) with no pulse train"
            ),
            safety="Current-limit the first power-up.",
        ),
        TestStep(
            name="FORWARD pulses",
            procedure="Hold FORWARD; scope TP_SERVO_SIGNAL.",
            expected=(
                f"~{forward['servo_pulse_ms']:g}ms positive pulses at "
                f"~{forward['frame_rate_hz']:g}Hz"
            ),
        ),
        TestStep(
            name="REVERSE pulses",
            procedure="Hold REVERSE; scope TP_SERVO_SIGNAL.",
            expected=(
                f"~{reverse['servo_pulse_ms']:g}ms positive pulses at "
                f"~{reverse['frame_rate_hz']:g}Hz"
            ),
        ),
        TestStep(
            name="Servo drive",
            procedure=(
                "Connect an SG90-class servo; hold each button in turn."
            ),
            expected=(
                "Servo runs to one end stop on FORWARD and the other on "
                "REVERSE (end-stop tester by design)"
            ),
            safety="Servo stall draws ~0.7A; supply must source 1A.",
        ),
    )
