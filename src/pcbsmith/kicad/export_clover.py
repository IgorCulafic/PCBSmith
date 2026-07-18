"""KiCad schematic exporter for the clover tilt indicator (label-net style).

Official symbols throughout (hardening plan 6.1): the real
Sensor_Motion:MPU-6050 and MCU_Microchip_ATtiny:ATtiny84A-SS, Device
passives, and power flags for the ICs' power_in pins. Wires attach at
measured pin positions; the MCU's unused bidirectional pins carry
explicit no-connect markers.
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
from pcbsmith.kicad.export_mpu6050 import _no_connect
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.symbols import (
    instance_pin_position,
    load_symbol,
    pin_stub,
    render_symbol_for_schematic,
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
U2_PIN_NETS = {
    1: "VDD", 6: "INT", 7: "SDA", 9: "SCL",
    10: "LEAF_NE", 11: "LEAF_SE", 12: "LEAF_SW", 13: "LEAF_NW",
    14: "GND",
}
U2_NC_PINS = (2, 3, 4, 5, 8)
# The auxiliary I2C master bus is unused on this board; the datasheet
# permits leaving AUX_DA/AUX_CL floating when no external sensor hangs
# off the MPU.
U1_NC_PINS = (6, 7)

U1_AT = (63.5, 63.5)
U2_AT = (127.0, 63.5)

MPU = "Sensor_Motion:MPU-6050"
MCU = "MCU_Microchip_ATtiny:ATtiny84A-SS"
RESISTOR = "Device:R"
CAPACITOR = "Device:C"
LED = "Device:LED"
CONNECTOR = "Connector_Generic:Conn_01x02"
FLAG = "power:PWR_FLAG"

# Vertical two-pin columns: (ref, lib_id, x, top net, bottom net).
PASSIVE_COLUMNS = (
    ("C1", CAPACITOR, 30.48, "REGOUT", "GND"),
    ("C2", CAPACITOR, 43.18, "VDD", "GND"),
    ("C3", CAPACITOR, 55.88, "CPOUT", "GND"),
    ("C4", CAPACITOR, 68.58, "VDD", "GND"),
    ("C5", CAPACITOR, 81.28, "VDD", "GND"),
    ("R1", RESISTOR, 93.98, "VDD", "SDA"),
    ("R2", RESISTOR, 106.68, "VDD", "SCL"),
    ("R3", RESISTOR, 119.38, "LEAF_NE", "LEAF_NE_A"),
    ("R4", RESISTOR, 132.08, "LEAF_NW", "LEAF_NW_A"),
    ("R5", RESISTOR, 144.78, "LEAF_SW", "LEAF_SW_A"),
    ("R6", RESISTOR, 157.48, "LEAF_SE", "LEAF_SE_A"),
)
# Horizontal LEDs: (ref, x, cathode net, anode net). Device:LED pin 1 is
# the cathode on the left.
LED_ROW = (
    ("D1", 177.8, "GND", "LEAF_NE_A"),
    ("D2", 198.12, "GND", "LEAF_NW_A"),
    ("D3", 218.44, "GND", "LEAF_SW_A"),
    ("D4", 238.76, "GND", "LEAF_SE_A"),
)
PASSIVE_Y = 111.76
LED_Y = 111.76


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

    def sym(
        lib: str, reference: str, x: float, y: float, *, pin_count: int,
        in_bom: bool = True, on_board: bool = True, value: str | None = None,
    ) -> str:
        default_value, footprint = fields.get(reference, ("", ""))
        return _symbol(
            lib, reference, value or default_value, x, y, project_name,
            exclude_from_sim=True, footprint=footprint,
            in_bom=in_bom, on_board=on_board, pin_count=pin_count,
        )

    mpu = load_symbol(MPU)
    mcu = load_symbol(MCU)
    resistor = load_symbol(RESISTOR)
    capacitor = load_symbol(CAPACITOR)
    led = load_symbol(LED)
    connector = load_symbol(CONNECTOR)
    flag = load_symbol(FLAG)

    symbols: list[str] = [
        sym(CONNECTOR, "P1", 25.4, 55.88, pin_count=2),
        sym(MPU, "U1", *U1_AT, pin_count=24),
        sym(MCU, "U2", *U2_AT, pin_count=14),
    ]
    wires: list[str] = []
    labels: list[str] = []
    no_connects: list[str] = []

    for index, net in enumerate(("VDD", "GND")):
        tip, endpoint = pin_stub(connector, str(index + 1), (25.4, 55.88))
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    for pin_number, net in U1_PIN_NETS.items():
        tip, endpoint = pin_stub(mpu, str(pin_number), U1_AT)
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    for pin_number, net in U2_PIN_NETS.items():
        tip, endpoint = pin_stub(mcu, str(pin_number), U2_AT)
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))
    for nc_pin in U2_NC_PINS:
        tip = instance_pin_position(mcu, str(nc_pin), U2_AT)
        no_connects.append(_no_connect(*tip))
    for nc_pin in U1_NC_PINS:
        tip = instance_pin_position(mpu, str(nc_pin), U1_AT)
        no_connects.append(_no_connect(*tip))

    for reference, lib, x, top_net, bottom_net in PASSIVE_COLUMNS:
        imported = capacitor if lib == CAPACITOR else resistor
        symbols.append(sym(lib, reference, x, PASSIVE_Y, pin_count=2))
        for pin_name, net in (("1", top_net), ("2", bottom_net)):
            tip, endpoint = pin_stub(imported, pin_name, (x, PASSIVE_Y))
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))

    for reference, x, cathode_net, anode_net in LED_ROW:
        symbols.append(sym(LED, reference, x, LED_Y, pin_count=2))
        for pin_name, net in (("1", cathode_net), ("2", anode_net)):
            tip, endpoint = pin_stub(led, pin_name, (x, LED_Y))
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))

    # Power flags: both ICs declare power_in pins; the header is passive.
    for index, net in enumerate(("VDD", "GND")):
        x = 30.48 + index * 12.7
        symbols.append(
            sym(FLAG, f"#FLG0{index + 1}", x, 137.16,
                pin_count=1, in_bom=False, on_board=False, value="PWR_FLAG")
        )
        tip, _out = pin_stub(flag, "1", (x, 137.16))
        endpoint = (tip[0], tip[1] + 2.54)
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    lib_symbols = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id))
        for lib_id in (RESISTOR, CAPACITOR, LED, MPU, MCU, CONNECTOR, FLAG)
    )
    items = "\n".join((*symbols, *wires, *labels, *no_connects))
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
