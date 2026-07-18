"""KiCad schematic exporter for the metal detector (label-net style).

First adopter of OFFICIAL KiCad symbols (hardening plan 6.1): every
symbol - including the exact MMBT3904 - is embedded verbatim from the
official libraries, and every wire attaches at the measured pin position
instead of hand-computed offsets.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    _label,
    _render_project,
    _symbol,
    _validate_project_name,
    _wire,
)
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.metal_detector_board import P1_PIN_NETS
from pcbsmith.kicad.symbols import (
    instance_pin_position,
    load_symbol,
    pin_stub_outward,
    render_symbol_for_schematic,
)

SUPPORTED_TOPOLOGY_ID = "metal_detector_coil"

STUB = 2.54

RESISTOR = "Device:R"
CAPACITOR = "Device:C"
INDUCTOR = "Device:L"
TRANSISTOR = "Transistor_BJT:MMBT3904"
CONNECTOR = "Connector_Generic:Conn_01x03"

# Instances: (reference, lib_id, x, y, {pin: net}). Device passives are
# natively vertical (pin 1 up); net pairs read (top, bottom).
Q1_PIN_NETS = {"1": "BASE", "2": "EM", "3": "COL"}
INSTANCES: tuple[tuple[str, str, float, float, dict[str, str]], ...] = (
    (
        "P1", CONNECTOR, 25.4, 55.88,
        {str(i + 1): net for i, net in enumerate(P1_PIN_NETS)},
    ),
    ("Q1", TRANSISTOR, 58.42, 55.88, Q1_PIN_NETS),
    ("R1", RESISTOR, 78.74, 55.88, {"1": "VCC", "2": "BASE"}),
    ("R2", RESISTOR, 91.44, 55.88, {"1": "BASE", "2": "GND"}),
    ("C5", CAPACITOR, 104.14, 55.88, {"1": "BASE", "2": "GND"}),
    ("L1", INDUCTOR, 116.84, 55.88, {"1": "VCC", "2": "COL"}),
    ("C1", CAPACITOR, 132.08, 55.88, {"1": "COL", "2": "EM"}),
    ("C2", CAPACITOR, 144.78, 55.88, {"1": "EM", "2": "GND"}),
    ("R3", RESISTOR, 157.48, 55.88, {"1": "EM", "2": "GND"}),
    ("C4", CAPACITOR, 195.58, 55.88, {"1": "VCC", "2": "GND"}),
    ("C3", CAPACITOR, 182.88, 55.88, {"1": "COL", "2": "FO_A"}),
    ("R4", RESISTOR, 170.18, 55.88, {"1": "FO_A", "2": "FOUT"}),
)


def export_metal_detector_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for KiCad export")
    project_name = _validate_project_name(project_name)

    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"

    project_file.write_text(_render_project(), encoding="utf-8")
    schematic_file.write_text(_render_schematic(circuit, project_name), encoding="utf-8")
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
    }


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }

    symbols: list[str] = []
    wires: list[str] = []
    labels: list[str] = []
    for reference, lib_id, x, y, pin_nets in INSTANCES:
        value, footprint = fields[reference]
        imported = load_symbol(lib_id)
        symbols.append(
            _symbol(
                lib_id, reference, value, x, y, project_name,
                exclude_from_sim=True, footprint=footprint,
                # The coil exists only as copper; its net-tie footprint is
                # BOM-excluded and the symbol must match (parity).
                in_bom="NetTie" not in footprint,
                pin_count=len(imported.pins),
            )
        )
        for pin_number, net in pin_nets.items():
            tip = instance_pin_position(imported, pin_number, (x, y))
            out_x, out_y = pin_stub_outward(imported, pin_number)
            end = (tip[0] + out_x * STUB, tip[1] + out_y * STUB)
            wires.append(_wire(tip, end))
            labels.append(_label(net, end[0], end[1]))

    lib_symbols = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id))
        for lib_id in (RESISTOR, CAPACITOR, INDUCTOR, TRANSISTOR, CONNECTOR)
    )
    items = "\n".join((*symbols, *wires, *labels))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {stable_kicad_uuid(
      "schematic-root",
      "machine",
      project_name,
      circuit.topology.topology_id,
  )})
  (paper "A4")

  (lib_symbols
{lib_symbols}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
