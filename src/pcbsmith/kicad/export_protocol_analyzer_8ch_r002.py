"""Uncrowded R002 schematic layout for the eight-channel protocol analyzer."""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_protocol_analyzer_8ch import (
    INSTANCES,
    SchematicInstance,
    export_protocol_analyzer_8ch_to_kicad,
)
from pcbsmith.rule_profiles import PcbRuleProfile

R002_SCHEMATIC_POSITIONS: dict[str, tuple[float, float]] = {
    # USB and power entry.
    "J1": (25.0, 45.0),
    "U8": (70.0, 45.0),
    "R3": (95.0, 35.0),
    "R4": (95.0, 55.0),
    "U3": (125.0, 45.0),
    "R1": (150.0, 35.0),
    "R2": (150.0, 55.0),
    "C1": (175.0, 30.0),
    "C2": (190.0, 30.0),
    "C3": (175.0, 60.0),
    "C4": (190.0, 60.0),
    "D1": (215.0, 40.0),
    "R9": (235.0, 40.0),
    # MCU, clock, flash, recovery, debug, and status.
    "U1": (280.0, 90.0),
    "U2": (360.0, 50.0),
    "Y1": (220.0, 85.0),
    "R5": (245.0, 85.0),
    "C5": (220.0, 110.0),
    "C6": (245.0, 110.0),
    "SW1": (350.0, 90.0),
    "R6": (375.0, 90.0),
    "R7": (375.0, 75.0),
    "SW2": (350.0, 115.0),
    "R8": (375.0, 115.0),
    "J3": (350.0, 145.0),
    "R10": (350.0, 165.0),
    "D2": (380.0, 165.0),
    # Target connector and ordered input corridor.
    "J2": (25.0, 210.0),
    "U6": (70.0, 192.0),
    "U7": (70.0, 230.0),
    "R11": (110.0, 185.0),
    "R12": (135.0, 185.0),
    "R13": (160.0, 185.0),
    "R14": (185.0, 185.0),
    "R15": (110.0, 225.0),
    "R16": (135.0, 225.0),
    "R17": (160.0, 225.0),
    "R18": (185.0, 225.0),
    "U4": (235.0, 210.0),
    "C7": (235.0, 180.0),
    "C8": (255.0, 180.0),
    # Trigger and target-voltage monitor.
    "D3": (285.0, 195.0),
    "R19": (310.0, 195.0),
    "R22": (310.0, 215.0),
    "U9": (345.0, 195.0),
    "C9": (345.0, 220.0),
    "R20": (370.0, 235.0),
    "R21": (395.0, 235.0),
    "C19": (395.0, 255.0),
    # Distributed bypass row.
    "C10": (25.0, 270.0),
    "C11": (50.0, 270.0),
    "C12": (75.0, 270.0),
    "C13": (100.0, 270.0),
    "C14": (125.0, 270.0),
    "C15": (150.0, 270.0),
    "C16": (175.0, 270.0),
    "C17": (200.0, 270.0),
    "C18": (225.0, 270.0),
}


def _r002_instances() -> tuple[SchematicInstance, ...]:
    refs = {reference for reference, *_rest in INSTANCES}
    if refs != set(R002_SCHEMATIC_POSITIONS):
        missing = sorted(refs - set(R002_SCHEMATIC_POSITIONS))
        extra = sorted(set(R002_SCHEMATIC_POSITIONS) - refs)
        raise ValueError(f"R002 schematic position mismatch: missing={missing}, extra={extra}")
    return tuple(
        (
            reference,
            lib_id,
            round(R002_SCHEMATIC_POSITIONS[reference][0] / 2.54) * 2.54,
            round(R002_SCHEMATIC_POSITIONS[reference][1] / 2.54) * 2.54,
            pin_nets,
        )
        for reference, lib_id, _x, _y, pin_nets in INSTANCES
    )


R002_INSTANCES = _r002_instances()

# Explicit text anchors keep the component identity outside dense symbol bodies.
# Positions are on the 2.54 mm schematic grid and do not affect connectivity.
R002_PROPERTY_POSITIONS = {
    "J1": ((25.4, 20.32), (25.4, 76.20)),
    "J2": ((25.4, 185.42), (25.4, 238.76)),
    "J3": ((350.52, 132.08), (350.52, 157.48)),
    "U2": ((360.68, 33.02), (360.68, 68.58)),
    "U4": ((236.22, 190.50), (236.22, 231.14)),
    "U6": ((71.12, 177.80), (71.12, 205.74)),
    "U7": ((71.12, 215.90), (71.12, 243.84)),
    "U8": ((71.12, 30.48), (71.12, 60.96)),
}


def export_protocol_analyzer_8ch_r002_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
    profile: PcbRuleProfile,
) -> dict[str, str]:
    """Export R002 with spread pin labels and separated functional sections."""

    return export_protocol_analyzer_8ch_to_kicad(
        circuit,
        output_dir,
        project_name=project_name,
        profile=profile,
        instances=R002_INSTANCES,
        spread_pin_label_references=frozenset(
            {"J2", "J3", "U1", "U2", "U4", "U6", "U7", "U8"}
        ),
        spread_pin_label_distance_mm=10.16,
        stagger_vertical_label_references=frozenset({"J1", "U1"}),
        property_positions=R002_PROPERTY_POSITIONS,
    )
