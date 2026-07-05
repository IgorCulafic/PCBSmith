"""KiCad schematic exporter for the MPU-6050 IMU breakout.

Uses label-net style: every used pin gets a short stub wire ending in a net
label (labels join nets without drawn routing, and rule 7.2 requires every
net to be labelled anyway); every unused pin gets an explicit no-connect
marker so ERC accounts for all 24 QFN pins.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    KICAD_SYMBOL_LIBRARY_VERSION,
    _capacitor_symbol_drawing,
    _generic_pin,
    _label,
    _library_property,
    _render_project,
    _render_symbol_table,
    _render_two_pin_box_library_symbol,
    _resistor_symbol_drawing,
    _symbol,
    _validate_project_name,
    _wire,
)

SUPPORTED_TOPOLOGY_ID = "mpu6050_imu"

# Pin map from the datasheet (PS-MPU-6000A-00 rev 3.4, section 7.1, p21).
MPU6050_PIN_NAMES = {
    1: "CLKIN",
    6: "AUX_DA",
    7: "AUX_CL",
    8: "VLOGIC",
    9: "AD0",
    10: "REGOUT",
    11: "FSYNC",
    12: "INT",
    13: "VDD",
    18: "GND",
    19: "RESV",
    20: "CPOUT",
    21: "RESV",
    22: "RESV",
    23: "SCL",
    24: "SDA",
}
# Net bound to each used pin; everything else gets a no-connect marker.
MPU6050_PIN_NETS = {
    1: "GND",     # CLKIN: connect to GND if unused (p21)
    8: "VDD",     # VLOGIC tied to VDD (p12: 1.8V+/-5% or VDD)
    9: "AD0",
    10: "REGOUT",
    11: "GND",    # FSYNC: connect to GND if unused (p21)
    13: "VDD",
    18: "GND",
    20: "CPOUT",
    23: "SCL",
    24: "SDA",
}

U1_X = 88.9
U1_Y = 63.5
U1_TIP_DX = 12.7
STUB_MM = 5.08


def export_mpu6050_to_kicad(
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


def _pin_position(pin: int) -> tuple[float, float, str]:
    """Sheet position of a U1 pin tip and which side it exits."""
    if pin <= 12:
        return (U1_X - U1_TIP_DX, 48.26 + pin * 2.54, "left")
    return (U1_X + U1_TIP_DX, 78.74 - (pin - 13) * 2.54, "right")


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }

    def sym(lib: str, reference: str, x: float, y: float, rotation: int = 0) -> str:
        value, footprint = fields[reference]
        return _symbol(
            lib,
            reference,
            value,
            x,
            y,
            project_name,
            rotation=rotation,
            exclude_from_sim=True,
            footprint=footprint,
        )

    symbols = [
        sym("PCBSmith:CONN_01X04", "P1", 30.48, 71.12),
        sym("PCBSmith:MPU6050", "U1", U1_X, U1_Y),
    ]
    wires: list[str] = []
    labels: list[str] = []
    no_connects: list[str] = []

    # Connector pins stack upward from the anchor: pin 1 (VDD) lowest.
    connector_nets = ("VDD", "GND", "SCL", "SDA")
    for index, connector_net in enumerate(connector_nets):
        y = 71.12 - index * 2.54
        wires.append(_wire((30.48, y), (30.48 + STUB_MM, y)))
        labels.append(_label(connector_net, 30.48 + STUB_MM, y))

    for pin in range(1, 25):
        x, y, side = _pin_position(pin)
        net: str | None = MPU6050_PIN_NETS.get(pin)
        if net is None:
            no_connects.append(_no_connect(x, y))
            continue
        stub = -STUB_MM if side == "left" else STUB_MM
        wires.append(_wire((x, y), (x + stub, y)))
        labels.append(_label(net, x + stub, y))

    # Support passives: vertical two-pin parts, top pin to the signal net,
    # bottom pin to GND (rotation 270 puts symbol pin 1 on top for R/C).
    passives = (
        ("C1", "PCBSmith:C", 35.56, "REGOUT", "GND"),
        ("C2", "PCBSmith:C", 43.18, "VDD", "GND"),
        ("C3", "PCBSmith:C", 50.8, "CPOUT", "GND"),
        ("C4", "PCBSmith:C", 58.42, "VDD", "GND"),
        ("R1", "PCBSmith:R", 110.49, "VDD", "SDA"),
        ("R2", "PCBSmith:R", 118.11, "VDD", "SCL"),
        ("R3", "PCBSmith:R", 125.73, "AD0", "GND"),
    )
    passive_y = 95.25
    for reference, lib, x, top_net, bottom_net in passives:
        symbols.append(sym(lib, reference, x, passive_y, rotation=270))
        top_tip = passive_y - STUB_MM
        bottom_tip = passive_y + STUB_MM
        wires.append(_wire((x, top_tip), (x, top_tip - 2.54)))
        labels.append(_label(top_net, x, top_tip - 2.54))
        wires.append(_wire((x, bottom_tip), (x, bottom_tip + 2.54)))
        labels.append(_label(bottom_net, x, bottom_tip + 2.54))

    items = "\n".join((*symbols, *wires, *labels, *no_connects))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {uuid4()})
  (paper "A4")

  (lib_symbols
{_render_library_symbols(name_prefix="PCBSmith:")}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def _no_connect(x: float, y: float) -> str:
    return f"""  (no_connect
    (at {x:g} {y:g})
    (uuid "{uuid4()}")
  )"""


def _render_symbol_library() -> str:
    return f"""(kicad_symbol_lib
  (version {KICAD_SYMBOL_LIBRARY_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
{_render_library_symbols(name_prefix="")}
)
"""


def _render_library_symbols(*, name_prefix: str) -> str:
    return "\n\n".join(
        (
            _render_two_pin_box_library_symbol(
                f"{name_prefix}R",
                reference="R",
                value="R",
                description="Generic resistor",
                drawing=_resistor_symbol_drawing(),
                pin_length_mm="2.54",
            ),
            _render_two_pin_box_library_symbol(
                f"{name_prefix}C",
                reference="C",
                value="C",
                description="Ceramic capacitor",
                drawing=_capacitor_symbol_drawing(),
                pin_length_mm="4.318",
            ),
            _render_mpu6050_library_symbol(f"{name_prefix}MPU6050"),
            _render_connector_01x04_library_symbol(f"{name_prefix}CONN_01X04"),
        )
    )


def _render_mpu6050_library_symbol(name: str) -> str:
    pins: list[str] = []
    for pin in range(1, 13):
        # Left column, pin 1 at the top; symbol y axis points up.
        local_y = 15.24 - pin * 2.54
        pins.append(
            _generic_pin(str(pin), MPU6050_PIN_NAMES.get(pin, "NC"), -12.7, local_y, 0, "2.54")
        )
    for pin in range(13, 25):
        # Right column, pin 13 at the bottom (counter-clockwise QFN order).
        local_y = -15.24 + (pin - 13) * 2.54
        pins.append(
            _generic_pin(str(pin), MPU6050_PIN_NAMES.get(pin, "NC"), 12.7, local_y, 180, "2.54")
        )
    rendered_pins = "\n".join(pins)
    return f"""  (symbol "{name}"
    (pin_numbers
      (hide no)
    )
    (pin_names
      (offset 0.762)
    )
    (exclude_from_sim yes)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", "U", 0, 17.78)}
    {_library_property("Value", "MPU-6050", 0, -19.05)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", "InvenSense 6-axis IMU, I2C", 0, 0, hidden=True)}
    (symbol "MPU6050_0_1"
      (rectangle
        (start -10.16 16.51)
        (end 10.16 -17.78)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type background)
        )
      )
    )
    (symbol "MPU6050_1_1"
{rendered_pins}
    )
  )"""


def _render_connector_01x04_library_symbol(name: str) -> str:
    pins = "\n".join(
        _generic_pin(str(pin), f"Pin_{pin}", 0, (pin - 1) * 2.54, 0, "2.54")
        for pin in range(1, 5)
    )
    return f"""  (symbol "{name}"
    (pin_numbers
      (hide no)
    )
    (pin_names
      (offset 0.762)
    )
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", "J", 3.81, -2.54)}
    {_library_property("Value", "Conn_01x04", 3.81, 10.16)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", "Generic four-pin connector", 0, 0, hidden=True)}
    (symbol "CONN_01X04_0_1"
      (rectangle
        (start 1.27 -1.27)
        (end 5.08 8.89)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )
    (symbol "CONN_01X04_1_1"
{pins}
    )
  )"""
