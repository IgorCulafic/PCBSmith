"""KiCad schematic exporter for the LM2596 buck (label-net style).

Official symbols (hardening plan 6.1): the real
Regulator_Switching:LM2596S-ADJ with its power_in/ON-OFF pin semantics,
Device passives including the polarized bulk capacitors, and power flags
for the externally supplied rails. Converted from the hand-wired ladder
drawing to the label-net style used by every migrated exporter: nets are
declared per pin from a data table, wires attach at measured pin
positions.
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
from pcbsmith.kicad.symbols import (
    load_symbol,
    pin_stub,
    render_symbol_for_schematic,
)

SUPPORTED_TOPOLOGY_ID = "lm2596_buck_regulator"
REQUIRED_COMPONENT_REFERENCES = (
    "P1",
    "CIN",
    "CIN2",
    "U1",
    "D1",
    "L1",
    "COUT",
    "COUT2",
    "RFB1",
    "RFB2",
    "RLED",
    "D2",
    "P2",
)

REGULATOR = "Regulator_Switching:LM2596S-ADJ"
RESISTOR = "Device:R"
CAPACITOR = "Device:C"
CAP_POLARIZED = "Device:C_Polarized"
INDUCTOR = "Device:L"
SCHOTTKY = "Device:D_Schottky"
LED = "Device:LED"
CONNECTOR = "Connector_Generic:Conn_01x02"
FLAG = "power:PWR_FLAG"

# The regulator's pin contract (rule 7.3's single source for this board):
# 1 VIN, 2 OUT -> switch node, 3 GND, 4 FB, 5 ~ON/OFF tied to ground so
# the regulator is always enabled (TI datasheet section 8.4).
U1_PIN_NETS = {"1": "VIN", "2": "SW", "3": "GND", "4": "FB", "5": "GND"}

# Instances: (reference, lib_id, x, y, {pin: net}). Device two-pin parts
# are natively vertical (pin 1 up); the diode and LED are horizontal with
# pin 1 = cathode on the left.
INSTANCES: tuple[tuple[str, str, float, float, dict[str, str]], ...] = (
    ("P1", CONNECTOR, 25.4, 55.88, {"1": "VIN", "2": "GND"}),
    ("CIN", CAP_POLARIZED, 40.64, 55.88, {"1": "VIN", "2": "GND"}),
    ("CIN2", CAPACITOR, 53.34, 55.88, {"1": "VIN", "2": "GND"}),
    ("U1", REGULATOR, 76.2, 55.88, U1_PIN_NETS),
    ("D1", SCHOTTKY, 101.6, 55.88, {"1": "SW", "2": "GND"}),
    ("L1", INDUCTOR, 116.84, 55.88, {"1": "SW", "2": "VOUT"}),
    ("COUT", CAP_POLARIZED, 129.54, 55.88, {"1": "VOUT", "2": "GND"}),
    ("COUT2", CAPACITOR, 142.24, 55.88, {"1": "VOUT", "2": "GND"}),
    ("RFB1", RESISTOR, 154.94, 55.88, {"1": "VOUT", "2": "FB"}),
    ("RFB2", RESISTOR, 167.64, 55.88, {"1": "FB", "2": "GND"}),
    ("RLED", RESISTOR, 180.34, 55.88, {"1": "VOUT", "2": "LEDA"}),
    ("D2", LED, 195.58, 55.88, {"1": "GND", "2": "LEDA"}),
    ("P2", CONNECTOR, 217.17, 55.88, {"1": "VOUT", "2": "GND"}),
)


def export_lm2596_buck_to_kicad(
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
                pin_count=len(imported.pins),
            )
        )
        for pin_number, net in pin_nets.items():
            tip, endpoint = pin_stub(imported, pin_number, (x, y))
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))

    # Power flags: the regulator's VIN and GND pins are power_in and the
    # connectors are passive, so ERC needs explicit source markers.
    flag = load_symbol(FLAG)
    for index, net in enumerate(("VIN", "GND")):
        x = 30.48 + index * 12.7
        symbols.append(
            _symbol(
                FLAG, f"#FLG0{index + 1}", "PWR_FLAG", x, 86.36,
                project_name, exclude_from_sim=True,
                in_bom=False, on_board=False, pin_count=1,
            )
        )
        tip, _out = pin_stub(flag, "1", (x, 86.36))
        endpoint = (tip[0], tip[1] + 2.54)
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    lib_symbols = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id))
        for lib_id in (
            RESISTOR, CAPACITOR, CAP_POLARIZED, INDUCTOR, SCHOTTKY, LED,
            REGULATOR, CONNECTOR, FLAG,
        )
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
  (paper "A3")

  (lib_symbols
{lib_symbols}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
