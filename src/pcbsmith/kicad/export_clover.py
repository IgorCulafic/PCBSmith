"""KiCad schematic exporter for the clover tilt indicator (label-net style)."""

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
    _led_symbol_drawing,
    _library_property,
    _render_project,
    _render_symbol_table,
    _render_two_pin_box_library_symbol,
    _resistor_symbol_drawing,
    _symbol,
    _validate_project_name,
    _wire,
)
from pcbsmith.kicad.export_mpu6050 import (
    _no_connect,
    _render_mpu6050_library_symbol,
    render_connector_library_symbol,
)

SUPPORTED_TOPOLOGY_ID = "clover_tilt_indicator"

# MPU-6050 pin nets on this board (AD0 hard-tied low: address 0x68).
U1_PIN_NETS = {
    1: "GND", 8: "VDD", 9: "GND", 10: "REGOUT", 11: "GND", 12: "INT",
    13: "VDD", 18: "GND", 20: "CPOUT", 23: "SCL", 24: "SDA",
}
# ATtiny84A SOIC-14: 1 VCC, 14 GND, USI SDA=PA6(7) SCL=PA4(9), leaves on
# PA0..PA3 (13..10), INT on PA7 (6). RESET (4) relies on its internal
# pull-up (finding); 2/3/5/8 unused.
ATTINY84_PIN_NAMES = {
    1: "VCC", 2: "PB0", 3: "PB1", 4: "PB3/RST", 5: "PB2", 6: "PA7",
    7: "PA6/SDA", 8: "PA5", 9: "PA4/SCL", 10: "PA3", 11: "PA2",
    12: "PA1", 13: "PA0", 14: "GND",
}
U2_PIN_NETS = {
    1: "VDD", 6: "INT", 7: "SDA", 9: "SCL",
    10: "LEAF_NE", 11: "LEAF_SE", 12: "LEAF_SW", 13: "LEAF_NW",
    14: "GND",
}

U1_X, U1_Y = 63.5, 63.5
U2_X, U2_Y = 127.0, 63.5
STUB = 5.08


def export_clover_to_kicad(
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


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }

    def sym(lib: str, reference: str, x: float, y: float, rotation: int = 0) -> str:
        value, footprint = fields[reference]
        return _symbol(
            lib, reference, value, x, y, project_name,
            rotation=rotation, exclude_from_sim=True, footprint=footprint,
        )

    symbols = [
        sym("PCBSmith:CONN_01X02", "P1", 25.4, 55.88),
        sym("PCBSmith:MPU6050", "U1", U1_X, U1_Y),
        sym("PCBSmith:ATTINY84", "U2", U2_X, U2_Y),
    ]
    wires: list[str] = []
    labels: list[str] = []
    no_connects: list[str] = []

    for index, connector_net in enumerate(("VDD", "GND")):
        y = 55.88 - index * 2.54
        wires.append(_wire((25.4, y), (25.4 + STUB, y)))
        labels.append(_label(connector_net, 25.4 + STUB, y))

    # MPU-6050 (24-pin, two columns; geometry mirrors export_mpu6050).
    for pin in range(1, 25):
        if pin <= 12:
            x, y, stub = U1_X - 12.7, 48.26 - 15.24 + pin * 2.54 + 15.24, -STUB
            y = U1_Y - (15.24 - pin * 2.54)
        else:
            x, stub = U1_X + 12.7, STUB
            y = U1_Y + (15.24 - (pin - 13) * 2.54) - 30.48 + 30.48
            y = U1_Y - (-15.24 + (pin - 13) * 2.54)
        net = U1_PIN_NETS.get(pin)
        if net is None:
            no_connects.append(_no_connect(x, y))
            continue
        wires.append(_wire((x, y), (x + stub, y)))
        labels.append(_label(net, x + stub, y))

    # ATtiny84A (14-pin, two columns: 1-7 left top-down, 8-14 right bottom-up).
    for pin in range(1, 15):
        if pin <= 7:
            x, stub = U2_X - 12.7, -STUB
            y = U2_Y - (8.89 - pin * 2.54)
        else:
            x, stub = U2_X + 12.7, STUB
            y = U2_Y - (-8.89 + (pin - 8) * 2.54)
        net = U2_PIN_NETS.get(pin)
        if net is None:
            no_connects.append(_no_connect(x, y))
            continue
        wires.append(_wire((x, y), (x + stub, y)))
        labels.append(_label(net, x + stub, y))

    # Passives (vertical, label-net): (ref, lib, x, top net, bottom net).
    passives = (
        ("C1", "PCBSmith:C", 30.48, "REGOUT", "GND"),
        ("C2", "PCBSmith:C", 38.1, "VDD", "GND"),
        ("C3", "PCBSmith:C", 45.72, "CPOUT", "GND"),
        ("C4", "PCBSmith:C", 53.34, "VDD", "GND"),
        ("C5", "PCBSmith:C", 60.96, "VDD", "GND"),
        ("R1", "PCBSmith:R", 68.58, "VDD", "SDA"),
        ("R2", "PCBSmith:R", 76.2, "VDD", "SCL"),
        ("R3", "PCBSmith:R", 88.9, "LEAF_NE", "LEAF_NE_A"),
        ("R4", "PCBSmith:R", 96.52, "LEAF_NW", "LEAF_NW_A"),
        ("R5", "PCBSmith:R", 104.14, "LEAF_SW", "LEAF_SW_A"),
        ("R6", "PCBSmith:R", 111.76, "LEAF_SE", "LEAF_SE_A"),
        ("D1", "PCBSmith:LED", 88.9, "LEAF_NE_A", "GND"),
        ("D2", "PCBSmith:LED", 96.52, "LEAF_NW_A", "GND"),
        ("D3", "PCBSmith:LED", 104.14, "LEAF_SW_A", "GND"),
        ("D4", "PCBSmith:LED", 111.76, "LEAF_SE_A", "GND"),
    )
    for reference, lib, x, top_net, bottom_net in passives:
        y_center = 95.25 if not reference.startswith("D") else 116.84
        symbols.append(sym(lib, reference, x, y_center, rotation=270))
        top_tip = y_center - STUB
        bottom_tip = y_center + STUB
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
  (paper "A3")

  (lib_symbols
{_render_library_symbols(name_prefix="PCBSmith:")}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


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
            _render_two_pin_box_library_symbol(
                f"{name_prefix}LED",
                reference="D",
                value="LED",
                description="Leaf LED",
                drawing=_led_symbol_drawing(),
                pin_length_mm="3.81",
                pin_one_at="right",
            ),
            _render_mpu6050_library_symbol(f"{name_prefix}MPU6050"),
            _render_attiny84_library_symbol(f"{name_prefix}ATTINY84"),
            render_connector_library_symbol(f"{name_prefix}CONN_01X02", pin_count=2),
        )
    )


def _render_attiny84_library_symbol(name: str) -> str:
    pins: list[str] = []
    for pin in range(1, 8):
        local_y = 8.89 - pin * 2.54
        pins.append(
            _generic_pin(str(pin), ATTINY84_PIN_NAMES[pin], -12.7, local_y, 0, "2.54")
        )
    for pin in range(8, 15):
        local_y = -8.89 + (pin - 8) * 2.54
        pins.append(
            _generic_pin(str(pin), ATTINY84_PIN_NAMES[pin], 12.7, local_y, 180, "2.54")
        )
    rendered = "\n".join(pins)
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
    {_library_property("Reference", "U", 0, 11.43)}
    {_library_property("Value", "ATtiny84A", 0, -12.7)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", "AVR 8-bit MCU, SOIC-14", 0, 0, hidden=True)}
    (symbol "ATTINY84_0_1"
      (rectangle
        (start -10.16 10.16)
        (end 10.16 -11.43)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type background)
        )
      )
    )
    (symbol "ATTINY84_1_1"
{rendered}
    )
  )"""
