"""Human-readable schematic for the 555 servo tester (Track 9.1 pilot).

The drawing follows the conventions the user asked for: VCC rail along
the top, GND rail along the bottom, the 555 drawn centrally with the
timing network hanging off its left-side pins, signal flow left to
right (power entry -> 555 -> inverter -> servo header), real drawn
wires with junction dots. Connectivity is NOT hand-trusted: the spec is
validated against ``export_servo555.INSTANCES`` — the same pin->net
table that generates the machine schematic — so the two drawings are
one truth, and the authority pipeline re-proves it live with kicad-cli
ERC plus netlist-export equality.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    _render_project,
    _validate_project_name,
)
from pcbsmith.kicad.export_servo555 import (
    BC547,
    CAP_POLARIZED,
    CAPACITOR,
    CONN2,
    CONN3,
    INSTANCES,
    NE555,
    RESISTOR,
    SUPPORTED_TOPOLOGY_ID,
    SW_PUSH,
    TESTPOINT,
)
from pcbsmith.kicad.reader_schematic import (
    ReaderFlag,
    ReaderInstance,
    ReaderSpec,
    render_reader_schematic,
)

# The machine schematic's pin->net table is the single source of truth.
PIN_NETS: dict[str, dict[str, str]] = {
    reference: dict(pin_nets) for reference, _lib, _x, pin_nets in INSTANCES
}

VCC_RAIL_Y = 25.4
GND_RAIL_Y = 127.0

SERVO555_READER_SPEC = ReaderSpec(
    instances=(
        # Power entry, west; pins face the board edge (left), the rails
        # wrap around to the top and bottom. Text positions are chosen
        # clear of the drawn wires (checked against the rendered SVG).
        ReaderInstance(
            "J1", CONN2, (27.94, 63.5),
            reference_at=(30.48, 58.42), value_at=(31.75, 71.12),
        ),
        # The 555 central; timing pins (TRIG/THRES/DISCH) on its left.
        ReaderInstance(
            "U1", NE555, (86.36, 76.2),
            reference_at=(82.55, 60.96), value_at=(86.36, 88.9),
        ),
        ReaderInstance(
            "R1", RESISTOR, (63.5, 40.64),
            reference_at=(66.68, 39.37), value_at=(66.68, 41.91),
        ),
        ReaderInstance(
            "R2", RESISTOR, (48.26, 58.42),
            reference_at=(45.09, 57.15), value_at=(44.45, 59.69),
        ),
        ReaderInstance(
            "SW1", SW_PUSH, (53.34, 66.04),
            reference_at=(53.34, 69.85), value_at=(53.34, 72.39),
        ),
        ReaderInstance(
            "R3", RESISTOR, (33.02, 58.42),
            reference_at=(29.85, 57.15), value_at=(29.21, 59.69),
        ),
        ReaderInstance(
            "SW2", SW_PUSH, (38.1, 73.66),
            reference_at=(38.1, 77.47), value_at=(38.1, 80.01),
        ),
        ReaderInstance(
            "C1", CAPACITOR, (71.12, 100.33),
            reference_at=(75.57, 99.06), value_at=(75.57, 101.6),
        ),
        ReaderInstance(
            "C2", CAPACITOR, (104.14, 68.58),
            reference_at=(107.95, 67.31), value_at=(107.95, 69.85),
        ),
        # Output stage: OUT -> R4 -> Q1 inverter -> servo header east.
        ReaderInstance(
            "R4", RESISTOR, (116.84, 76.2), rotation=90,
            reference_at=(116.84, 72.39), value_at=(116.84, 80.01),
        ),
        ReaderInstance(
            "Q1", BC547, (130.81, 76.2),
            reference_at=(136.53, 73.66), value_at=(138.43, 80.01),
        ),
        ReaderInstance(
            "R5", RESISTOR, (133.35, 55.88),
            reference_at=(137.16, 54.61), value_at=(137.8, 57.15),
        ),
        # Rail-to-rail decoupling between the inverter and the header.
        ReaderInstance(
            "C4", CAP_POLARIZED, (152.4, 76.2),
            reference_at=(148.59, 73.66), value_at=(146.05, 83.82),
        ),
        ReaderInstance(
            "C3", CAPACITOR, (162.56, 76.2),
            reference_at=(165.74, 73.66), value_at=(166.37, 78.74),
        ),
        ReaderInstance(
            "J2", CONN3, (228.6, 76.2),
            reference_at=(228.6, 69.85), value_at=(228.6, 85.09),
        ),
        ReaderInstance(
            "TP1", TESTPOINT, (146.05, 22.86), in_bom=False,
            reference_at=(146.05, 20.32), value_at=(146.05, 17.78),
        ),
        ReaderInstance(
            "TP2", TESTPOINT, (146.05, 124.46), in_bom=False,
            reference_at=(141.61, 123.19), value_at=(146.05, 130.81),
        ),
        ReaderInstance(
            "TP3", TESTPOINT, (99.06, 73.66), in_bom=False,
            reference_at=(95.25, 72.39), value_at=(97.79, 66.04),
        ),
        ReaderInstance(
            "TP4", TESTPOINT, (203.2, 60.96), in_bom=False,
            reference_at=(199.39, 59.69), value_at=(203.2, 55.88),
        ),
    ),
    wires=(
        # Supply rails. The renderer splits them at every tap and adds
        # the junction dots.
        ((17.78, VCC_RAIL_Y), (220.98, VCC_RAIL_Y)),
        ((15.24, GND_RAIL_Y), (215.9, GND_RAIL_Y)),
        # J1 power entry wraps to the rails around the sheet edge.
        ((22.86, 63.5), (17.78, 63.5)),
        ((17.78, 63.5), (17.78, VCC_RAIL_Y)),
        ((22.86, 66.04), (15.24, 66.04)),
        ((15.24, 66.04), (15.24, GND_RAIL_Y)),
        # ERC power flags.
        ((33.02, 22.86), (33.02, VCC_RAIL_Y)),
        ((33.02, 124.46), (33.02, GND_RAIL_Y)),
        # R1: VCC -> DIS charge resistor.
        ((63.5, 36.83), (63.5, VCC_RAIL_Y)),
        ((63.5, 44.45), (63.5, 50.8)),
        # DIS bus feeding both timing branches and the DISCH pin.
        ((33.02, 50.8), (63.5, 50.8)),
        ((63.5, 50.8), (72.39, 50.8)),
        ((72.39, 50.8), (72.39, 73.66)),
        ((72.39, 73.66), (76.2, 73.66)),
        # FORWARD branch: R2 into SW1.
        ((48.26, 54.61), (48.26, 50.8)),
        ((48.26, 62.23), (48.26, 66.04)),
        # REVERSE branch: R3 into SW2.
        ((33.02, 54.61), (33.02, 50.8)),
        ((33.02, 62.23), (33.02, 73.66)),
        # THR trunk: both switches, TRIG, THRES, and the timing cap.
        ((71.12, 66.04), (71.12, 96.52)),
        ((58.42, 66.04), (71.12, 66.04)),
        ((43.18, 73.66), (71.12, 73.66)),
        ((76.2, 81.28), (71.12, 81.28)),
        ((76.2, 78.74), (71.12, 78.74)),
        ((71.12, 104.14), (71.12, GND_RAIL_Y)),
        # RESET strapped high beside the chip.
        ((76.2, 71.12), (73.66, 71.12)),
        ((73.66, 71.12), (73.66, VCC_RAIL_Y)),
        # 555 supply pins.
        ((88.9, 66.04), (88.9, VCC_RAIL_Y)),
        ((86.36, 86.36), (86.36, GND_RAIL_Y)),
        # CONT bypass over the chip's shoulder into C2.
        ((86.36, 66.04), (86.36, 63.5)),
        ((86.36, 63.5), (104.14, 63.5)),
        ((104.14, 63.5), (104.14, 64.77)),
        ((104.14, 72.39), (104.14, GND_RAIL_Y)),
        # OUT -> R4 -> BASE -> Q1.
        ((96.52, 76.2), (113.03, 76.2)),
        ((99.06, 73.66), (99.06, 76.2)),
        ((120.65, 76.2), (125.73, 76.2)),
        # Collector pull-up and the SIG run to the servo header.
        ((133.35, 52.07), (133.35, VCC_RAIL_Y)),
        ((133.35, 59.69), (133.35, 71.12)),
        ((133.35, 63.5), (218.44, 63.5)),
        ((218.44, 63.5), (218.44, 78.74)),
        ((218.44, 78.74), (223.52, 78.74)),
        ((203.2, 60.96), (203.2, 63.5)),
        ((133.35, 81.28), (133.35, GND_RAIL_Y)),
        # Decoupling columns.
        ((152.4, 72.39), (152.4, VCC_RAIL_Y)),
        ((152.4, 80.01), (152.4, GND_RAIL_Y)),
        ((162.56, 72.39), (162.56, VCC_RAIL_Y)),
        ((162.56, 80.01), (162.56, GND_RAIL_Y)),
        # Test points hang off their nets.
        ((146.05, 22.86), (146.05, VCC_RAIL_Y)),
        ((146.05, 124.46), (146.05, GND_RAIL_Y)),
        # Servo header supply pins.
        ((220.98, VCC_RAIL_Y), (220.98, 76.2)),
        ((220.98, 76.2), (223.52, 76.2)),
        ((223.52, 73.66), (215.9, 73.66)),
        ((215.9, 73.66), (215.9, GND_RAIL_Y)),
    ),
    labels=(
        ("VCC", (104.14, VCC_RAIL_Y)),
        ("GND", (96.52, GND_RAIL_Y)),
        ("THR", (71.12, 91.44)),
        ("DIS", (55.88, 50.8)),
        ("FWDM", (48.26, 63.5)),
        ("REVM", (33.02, 68.58)),
        ("CTRL", (95.25, 63.5)),
        ("OUT", (107.95, 76.2)),
        ("BASE", (123.19, 76.2)),
        ("SIG", (172.72, 63.5)),
    ),
    flags=(
        ReaderFlag("#FLG01", (33.02, 22.86), "VCC"),
        ReaderFlag("#FLG02", (33.02, 124.46), "GND"),
    ),
    paper="A4",
)


def export_servo555_reader_schematic(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    """Write ``<name>-reader.kicad_sch`` (+ project file) next to the
    machine schematic. Raises if the drawing's wire connectivity does
    not reproduce the machine pin->net table."""
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for KiCad export")
    project_name = _validate_project_name(project_name) + "-reader"

    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"
    project_file.write_text(_render_project(), encoding="utf-8")
    schematic_file.write_text(
        render_reader_schematic(
            circuit,
            SERVO555_READER_SPEC,
            project_name=project_name,
            pin_nets=PIN_NETS,
        ),
        encoding="utf-8",
    )
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
    }
