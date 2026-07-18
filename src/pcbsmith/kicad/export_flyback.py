"""KiCad schematic exporter for the offline flyback (label-net style).

Official symbols where the library has them (Device passives, PC817,
power flag); custom evidence-backed symbols where it does not: the
UCC28881 (pin table from the fetched TI datasheet p3 - SOIC-7, leads 6/7
physically absent for drain creepage) and the LMV431 (SOT-23 pins 1=K
2=REF 3=A per SNVS041 p3, cross-checked against the official TI DBZ
family convention). The custom transformer's symbol pins are numbered
1/4/5/8 to match the TEZ land pattern rows so schematic parity and the
physical isolation split agree by construction.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    KICAD_SYMBOL_LIBRARY_VERSION,
    _generic_pin,
    _label,
    _library_property,
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

SUPPORTED_TOPOLOGY_ID = "offline_flyback_3v3"

RESISTOR = "Device:R"
CAPACITOR = "Device:C"
CAP_POLARIZED = "Device:C_Polarized"
DIODE = "Device:D"
SCHOTTKY = "Device:D_Schottky"
VARISTOR = "Device:Varistor"
OPTO = "Isolator:PC817"
CONNECTOR = "Connector_Generic:Conn_01x02"
CONNECTOR_1P = "Connector_Generic:Conn_01x01"
BRIDGE = "Device:D_Bridge_+-AA"
TESTPOINT = "Connector:TestPoint"

UCC28881 = "PCBSmith:UCC28881"
LMV431 = "PCBSmith:LMV431"
TRANSFORMER = "PCBSmith:FLYBACK_TRANSFORMER"

# UCC28881 pin nets (datasheet p3: GND 1, GND 2, FB 3, VDD 4, HVIN 5,
# DRAIN 8; leads 6/7 absent).
U1_PIN_NETS = {"1": "HVM", "2": "HVM", "3": "FB", "4": "VDD", "5": "HVP", "8": "SW"}
# Transformer pads match the TEZ rows: primary 1(dot)/4, secondary 5/8(dot).
T1_PIN_NETS = {"1": "HVP", "4": "SW", "5": "SEC", "8": "GNDS"}
# LMV431 SOT-23: 1=K 2=REF 3=A.
U3_PIN_NETS = {"1": "OPK", "2": "FBS", "3": "GNDS"}
# PC817: 1=anode 2=cathode (LED, secondary side), 3=emitter 4=collector.
U2_PIN_NETS = {"1": "LEDA", "2": "OPK", "3": "FB", "4": "VDD"}

ROW_Y = 55.88

# (reference, lib_id, x, {pin: net}) - two-pin Device parts read (top,
# bottom); diodes/LED horizontals read (K left, A right).
INSTANCES: tuple[tuple[str, str, float, dict[str, str]], ...] = (
    ("J1", CONNECTOR, 20.32, {"1": "L", "2": "N"}),
    ("RF1", RESISTOR, 38.1, {"1": "L", "2": "ACL"}),
    ("RV1", VARISTOR, 55.88, {"1": "ACL", "2": "N"}),
    ("CX1", CAPACITOR, 73.66, {"1": "ACL", "2": "N"}),
    ("CY2", CAPACITOR, 91.44, {"1": "ACL", "2": "EARTH"}),
    ("CY3", CAPACITOR, 109.22, {"1": "N", "2": "EARTH"}),
    ("E1", CONNECTOR_1P, 127, {"1": "EARTH"}),
    ("BR1", BRIDGE, 144.78, {"1": "HVP", "2": "HVM", "3": "ACL", "4": "N"}),
    ("CB1", CAP_POLARIZED, 162.56, {"1": "HVP", "2": "HVM"}),
    ("D5", DIODE, 180.34, {"1": "HVP", "2": "HVM"}),
    ("U1", UCC28881, 198.12, U1_PIN_NETS),
    ("CV1", CAPACITOR, 215.9, {"1": "VDD", "2": "HVM"}),
    ("RC1", RESISTOR, 233.68, {"1": "HVP", "2": "CLAMP"}),
    ("CC1", CAPACITOR, 251.46, {"1": "HVP", "2": "CLAMP"}),
    ("D6", DIODE, 269.24, {"1": "CLAMP", "2": "SW"}),
    ("T1", TRANSFORMER, 287.02, T1_PIN_NETS),
    ("D7", SCHOTTKY, 304.8, {"1": "3V3", "2": "SEC"}),
    ("CO1", CAP_POLARIZED, 322.58, {"1": "3V3", "2": "GNDS"}),
    ("CO2", CAPACITOR, 340.36, {"1": "3V3", "2": "GNDS"}),
    ("U2", OPTO, 358.14, U2_PIN_NETS),
    ("U3", LMV431, 375.92, U3_PIN_NETS),
    ("RFB1", RESISTOR, 393.7, {"1": "3V3", "2": "FBS"}),
    ("RFB2", RESISTOR, 411.48, {"1": "FBS", "2": "GNDS"}),
    ("RO1", RESISTOR, 429.26, {"1": "3V3", "2": "LEDA"}),
    ("RO2", RESISTOR, 447.04, {"1": "LEDA", "2": "OPK"}),
    ("RP1", RESISTOR, 464.82, {"1": "FB", "2": "HVM"}),
    ("CY1", CAPACITOR, 482.6, {"1": "HVM", "2": "GNDS"}),
    ("TP1", TESTPOINT, 500.38, {"1": "HVP"}),
    ("TP2", TESTPOINT, 518.16, {"1": "GNDS"}),
    ("CF1", CAPACITOR, 535.94, {"1": "3V3", "2": "FBS"}),
    ("J2", CONNECTOR, 553.72, {"1": "3V3", "2": "GNDS"}),
)


def export_flyback_to_kicad(
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
    symbol_library.write_text(_render_symbol_library(), encoding="utf-8")
    schematic_file.write_text(_render_schematic(circuit, project_name), encoding="utf-8")
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
        "symbol_library": str(symbol_library),
    }


_CUSTOM_SYMBOLS = (
    (UCC28881, "700V 225mA offline switcher (TI, SOIC-7)"),
    (LMV431, "1.24V low-voltage shunt reference (TI, SOT-23)"),
    (TRANSFORMER, "Custom flyback transformer, TEZ-22 land"),
)


def _render_symbol_library() -> str:
    entries = (chr(10) + chr(10)).join(
        _custom_symbol_library_entry(lib.split(":")[-1], description)
        for lib, description in _CUSTOM_SYMBOLS
    )
    return f"""(kicad_symbol_lib
  (version {KICAD_SYMBOL_LIBRARY_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
{entries}
)
"""


def _custom_pin_positions(lib: str) -> dict[str, tuple[float, float, float]]:
    """(x, y-up, outward angle) per pin for the custom symbols."""
    if not lib.startswith("PCBSmith:"):
        lib = f"PCBSmith:{lib}"
    if lib == UCC28881:
        return {
            "1": (-10.16, 3.81, 180.0), "2": (-10.16, 1.27, 180.0),
            "3": (-10.16, -1.27, 180.0), "4": (-10.16, -3.81, 180.0),
            "5": (10.16, 3.81, 0.0), "8": (10.16, -3.81, 0.0),
        }
    if lib == LMV431:
        return {
            "1": (0.0, 5.08, 90.0),    # cathode up
            "2": (-5.08, 0.0, 180.0),  # REF left
            "3": (0.0, -5.08, 270.0),  # anode down
        }
    if lib == TRANSFORMER:
        return {
            "1": (-7.62, 5.08, 180.0), "4": (-7.62, -5.08, 180.0),
            "5": (7.62, 5.08, 0.0), "8": (7.62, -5.08, 0.0),
        }
    raise KeyError(lib)


def _custom_symbol_library_entry(lib: str, description: str) -> str:
    bare = lib.split(":")[-1]
    if not lib.startswith("PCBSmith:"):
        lib = f"PCBSmith:{lib}"
    pins = []
    names = {
        UCC28881: {"1": "GND", "2": "GND", "3": "FB", "4": "VDD",
                    "5": "HVIN", "8": "DRAIN"},
        LMV431: {"1": "K", "2": "REF", "3": "A"},
        TRANSFORMER: {"1": "PRI_DOT", "4": "PRI", "5": "SEC", "8": "SEC_DOT"},
    }[lib]
    for number, (x, y, angle) in _custom_pin_positions(lib).items():
        # Library pins point INTO the body: rotate the outward angle 180.
        pins.append(
            _generic_pin(number, names[number], x, y, int(angle + 180) % 360, "2.54")
        )
    rendered = "\n".join(pins)
    return f"""  (symbol "{lib}"
    (pin_numbers
      (hide no)
    )
    (pin_names
      (offset 0.762)
    )
    (exclude_from_sim yes)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", "U", 0, 8.89)}
    {_library_property("Value", bare, 0, -8.89)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", description, 0, 0, hidden=True)}
    (symbol "{bare}_0_1"
      (rectangle
        (start -7.62 7.62)
        (end 7.62 -7.62)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type background)
        )
      )
    )
    (symbol "{bare}_1_1"
{rendered}
    )
  )"""


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }

    symbols: list[str] = []
    wires: list[str] = []
    labels: list[str] = []
    custom_libs = {UCC28881, LMV431, TRANSFORMER}
    for reference, lib_id, x, pin_nets in INSTANCES:
        value, footprint = fields[reference]
        if lib_id in custom_libs:
            positions = _custom_pin_positions(lib_id)
            pin_count = len(positions)
        else:
            imported = load_symbol(lib_id)
            pin_count = len(imported.pins)
        symbols.append(
            _symbol(
                lib_id, reference, value, x, ROW_Y, project_name,
                exclude_from_sim=True, footprint=footprint,
                pin_count=pin_count,
                pin_numbers=tuple(pin_nets) if lib_id in custom_libs else None,
                # Bare pads (test points, wire pads) carry
                # exclude-from-BOM in their official footprints; the
                # symbol instance must match or parity fails.
                in_bom=reference not in ("TP1", "TP2", "E1"),
            )
        )
        for pin_number, net in pin_nets.items():
            if lib_id in custom_libs:
                px, py, angle = positions[pin_number]
                tip = (x + px, ROW_Y - py)
                import math as _math

                radians = _math.radians(angle)
                endpoint = (
                    round(tip[0] + 2.54 * _math.cos(radians), 4),
                    round(tip[1] - 2.54 * _math.sin(radians), 4),
                )
            else:
                tip, endpoint = pin_stub(imported, pin_number, (x, ROW_Y))
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))

    official = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id))
        for lib_id in (
            RESISTOR, CAPACITOR, CAP_POLARIZED, DIODE, SCHOTTKY, VARISTOR,
            OPTO, CONNECTOR, CONNECTOR_1P, BRIDGE, TESTPOINT,
        )
    )
    custom = chr(10).join(
        _custom_symbol_library_entry(lib, description)
        for lib, description in _CUSTOM_SYMBOLS
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
{official}
{custom}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
