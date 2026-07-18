"""KiCad schematic export for the 555 servo tester.

All-official symbols (Timer:NE555P, Transistor_BJT:BC547,
Switch:SW_Push, Device passives, TestPoint), label-net style: one
instance table drives symbol placement, pin stubs, and net labels.
The NE555P's VCC/GND pins are power_in, so PWR_FLAG instances mark
the sources for ERC.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    KICAD_SYMBOL_LIBRARY_VERSION,
    _label,
    _render_project,
    _render_symbol_table,
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

SUPPORTED_TOPOLOGY_ID = "servo_555_tester"

NE555 = "Timer:NE555P"
BC547 = "Transistor_BJT:BC547"
SW_PUSH = "Switch:SW_Push"
RESISTOR = "Device:R"
CAPACITOR = "Device:C"
CAP_POLARIZED = "Device:C_Polarized"
TESTPOINT = "Connector:TestPoint"
CONN2 = "Connector_Generic:Conn_01x02"
CONN3 = "Connector_Generic:Conn_01x03"
PWR_FLAG = "power:PWR_FLAG"

# NE555P per SLFS022 pin functions; astable wiring per section 6.3.2
# with TRIG tied to THRES, RESET tied to VCC, CONT bypassed.
U1_PIN_NETS = {
    "1": "GND", "2": "THR", "3": "OUT", "4": "VCC",
    "5": "CTRL", "6": "THR", "7": "DIS", "8": "VCC",
}

ROW_Y = 55.88

INSTANCES: tuple[tuple[str, str, float, dict[str, str]], ...] = (
    ("J1", CONN2, 20.32, {"1": "VCC", "2": "GND"}),
    ("U1", NE555, 40.64, U1_PIN_NETS),
    ("R1", RESISTOR, 60.96, {"1": "VCC", "2": "DIS"}),
    ("R2", RESISTOR, 78.74, {"1": "DIS", "2": "FWDM"}),
    ("SW1", SW_PUSH, 96.52, {"1": "FWDM", "2": "THR"}),
    ("R3", RESISTOR, 114.3, {"1": "DIS", "2": "REVM"}),
    ("SW2", SW_PUSH, 132.08, {"1": "REVM", "2": "THR"}),
    ("C1", CAPACITOR, 149.86, {"1": "THR", "2": "GND"}),
    ("C2", CAPACITOR, 167.64, {"1": "CTRL", "2": "GND"}),
    ("C3", CAPACITOR, 185.42, {"1": "VCC", "2": "GND"}),
    ("C4", CAP_POLARIZED, 203.2, {"1": "VCC", "2": "GND"}),
    ("R4", RESISTOR, 220.98, {"1": "OUT", "2": "BASE"}),
    ("Q1", BC547, 238.76, {"1": "SIG", "2": "BASE", "3": "GND"}),
    ("R5", RESISTOR, 256.54, {"1": "VCC", "2": "SIG"}),
    ("J2", CONN3, 274.32, {"1": "GND", "2": "VCC", "3": "SIG"}),
    ("TP1", TESTPOINT, 292.1, {"1": "VCC"}),
    ("TP2", TESTPOINT, 309.88, {"1": "GND"}),
    ("TP3", TESTPOINT, 327.66, {"1": "OUT"}),
    ("TP4", TESTPOINT, 345.44, {"1": "SIG"}),
)

_OFFICIAL_LIBS = (
    NE555, BC547, SW_PUSH, RESISTOR, CAPACITOR, CAP_POLARIZED,
    TESTPOINT, CONN2, CONN3, PWR_FLAG,
)


def export_servo555_to_kicad(
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
    symbol_library = output_dir / "PCBSmith.kicad_sym"
    symbol_table = output_dir / "sym-lib-table"

    project_file.write_text(_render_project(), encoding="utf-8")
    symbol_table.write_text(_render_symbol_table(), encoding="utf-8")
    symbol_library.write_text(_render_empty_library(), encoding="utf-8")
    schematic_file.write_text(
        _render_schematic(circuit, project_name), encoding="utf-8"
    )
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
        "symbol_library": str(symbol_library),
    }


def _render_empty_library() -> str:
    return f"""(kicad_symbol_lib
  (version {KICAD_SYMBOL_LIBRARY_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
)
"""


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }

    symbols: list[str] = []
    wires: list[str] = []
    labels: list[str] = []

    for reference, lib_id, x, pin_nets in INSTANCES:
        value, footprint = fields[reference]
        imported = load_symbol(lib_id)
        symbols.append(
            _symbol(
                lib_id, reference, value, x, ROW_Y, project_name,
                exclude_from_sim=True, footprint=footprint,
                pin_count=len(imported.pins),
                # Test points carry exclude-from-BOM in their official
                # footprints; the symbol instance must match (parity).
                in_bom=not reference.startswith("TP"),
            )
        )
        for pin_number, net in pin_nets.items():
            tip, endpoint = pin_stub(imported, pin_number, (x, ROW_Y))
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))

    # ERC power sources: the NE555P's VCC/GND pins are power_in.
    flag = load_symbol(PWR_FLAG)
    for index, net in enumerate(("VCC", "GND")):
        x = 363.22 + index * 17.78
        symbols.append(
            _symbol(
                PWR_FLAG, f"#FLG0{index + 1}", "PWR_FLAG", x, ROW_Y,
                project_name, exclude_from_sim=True, footprint="",
                pin_count=1, in_bom=False, on_board=False,
            )
        )
        tip, _out = pin_stub(flag, "1", (x, ROW_Y))
        endpoint = (tip[0], tip[1] + 2.54)
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    lib_symbols = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id))
        for lib_id in _OFFICIAL_LIBS
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
  (paper "A2")

  (lib_symbols
{lib_symbols}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
