"""KiCad schematic export for the thermometer display (label-net style).

All-official symbols across all 63 parts (USB-C receptacle, the
ESP32-C3-WROOM-02 module, SHT31-DIS, 74HC595, AP2112K-3.3, Device
passives, Polyfuse, TestPoint). Four rows on A2: the ICs/connectors
with wide slots, the support passives, then the 16 series resistors
and 16 mercury LEDs. Stacked pins (the USB receptacle's four VBUS pins
share one position, as do its grounds and the module's ground pad) get
ONE stub per position - KiCad connects every stacked pin at that
point. Deliberate no-connects carry native markers.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

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
from pcbsmith.kicad.export_mpu6050 import _no_connect
from pcbsmith.kicad.symbols import (
    instance_pin_position,
    load_symbol,
    pin_stub,
    render_symbol_for_schematic,
)

SUPPORTED_TOPOLOGY_ID = "thermometer_env_display"

USB_C = "Connector:USB_C_Receptacle_USB2.0_16P"
ESP32 = "RF_Module:ESP32-C3-WROOM-02"
HC595 = "74xx:74HC595"
SHT31 = "Sensor_Humidity:SHT31-DIS"
AP2112 = "Regulator_Linear:AP2112K-3.3"
RESISTOR = "Device:R"
CAPACITOR = "Device:C"
LED = "Device:LED"
POLYFUSE = "Device:Polyfuse"
CONN4 = "Connector_Generic:Conn_01x04"
TESTPOINT = "Connector:TestPoint"
PWR_FLAG = "power:PWR_FLAG"

LED_COUNT = 16

# USB receptacle: the 16-pin USB 2.0 part ties both sides' D+/D-
# together on the connector; SBU pins are deliberate no-connects.
J1_PIN_NETS = {
    "A1": "GND", "B1": "GND", "A12": "GND", "B12": "GND", "SH": "GND",
    "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
    "A5": "CC1", "B5": "CC2",
    "A6": "DP", "B6": "DP", "A7": "DM", "B7": "DM",
}

# Module pin map per the datasheet (p10-11) and the GPIO budget:
# I2C1 (sensor + TEMP OLED) on IO4/IO5, I2C2 (HUM OLED) on IO6/IO7,
# 74HC595 chain on IO10/IO0/IO1 with OE on IO3, straps pulled up.
U1_PIN_NETS = {
    "1": "VCC", "2": "EN",
    "3": "SDA1", "4": "SCL1", "5": "SDA2", "6": "SCL2",
    "7": "IO8", "9": "GND", "10": "SER",
    "13": "DM", "14": "DP", "15": "OE", "16": "IO2",
    "17": "RCLK", "18": "SRCLK", "19": "GND",
}

# 74HC595 per the datasheet pin table (p3): U2 drives LEDs 1-8 and
# cascades QH' -> U3.SER for LEDs 9-16.
U2_PIN_NETS = {
    "14": "SER", "11": "SRCLK", "12": "RCLK", "13": "OE",
    "10": "VCC", "16": "VCC", "8": "GND", "9": "CAS",
    "15": "SEG1", "1": "SEG2", "2": "SEG3", "3": "SEG4",
    "4": "SEG5", "5": "SEG6", "6": "SEG7", "7": "SEG8",
}
U3_PIN_NETS = {
    "14": "CAS", "11": "SRCLK", "12": "RCLK", "13": "OE",
    "10": "VCC", "16": "VCC", "8": "GND",
    "15": "SEG9", "1": "SEG10", "2": "SEG11", "3": "SEG12",
    "4": "SEG13", "5": "SEG14", "6": "SEG15", "7": "SEG16",
}

# SHT31 (Table 7 p8): ADDR low = 0x44, R and EP to VSS, ALERT and
# nRESET deliberately floating.
U4_PIN_NETS = {
    "1": "SDA1", "2": "GND", "4": "SCL1", "5": "VCC",
    "7": "GND", "8": "GND", "9": "GND",
}

U5_PIN_NETS = {"1": "VBUSF", "2": "GND", "3": "VBUSF", "5": "VCC"}

NO_CONNECTS: dict[str, tuple[str, ...]] = {
    "J1": ("A8", "B8"),          # SBU1/SBU2 unused in USB 2.0
    "U1": ("8", "11", "12"),     # IO9 strap (internal pull-up), UART
    "U3": ("9",),                # end of the cascade
    "U4": ("3", "6"),            # ALERT / nRESET float per Table 7
    "U5": ("4",),                # package NC
}

ROW1_Y = 60.96
ROW2_Y = 137.16
ROW3_Y = 190.5
ROW4_Y = 243.84


def _row(y: float, start_x: float, entries: list[tuple[str, str, dict[str, str]]],
         pitch: float = 17.78) -> list[tuple[str, str, float, float, dict[str, str]]]:
    return [
        (reference, lib, start_x + index * pitch, y, pins)
        for index, (reference, lib, pins) in enumerate(entries)
    ]


def _instances() -> tuple[tuple[str, str, float, float, dict[str, str]], ...]:
    big = [
        ("J1", USB_C, 33.02, J1_PIN_NETS),
        ("U1", ESP32, 78.74, U1_PIN_NETS),
        ("U2", HC595, 119.38, U2_PIN_NETS),
        ("U3", HC595, 160.02, U3_PIN_NETS),
        ("U4", SHT31, 195.58, U4_PIN_NETS),
        ("U5", AP2112, 220.98, U5_PIN_NETS),
        ("J2", CONN4, 246.38, {"1": "GND", "2": "VCC", "3": "SCL1", "4": "SDA1"}),
        ("J3", CONN4, 269.24, {"1": "GND", "2": "VCC", "3": "SCL2", "4": "SDA2"}),
        ("F1", POLYFUSE, 289.56, {"1": "VBUS", "2": "VBUSF"}),
        ("TP1", TESTPOINT, 307.34, {"1": "VCC"}),
        ("TP2", TESTPOINT, 325.12, {"1": "GND"}),
    ]
    row1 = [
        (reference, lib, x, ROW1_Y, pins) for reference, lib, x, pins in big
    ]
    support = _row(ROW2_Y, 25.4, [
        ("RCC1", RESISTOR, {"1": "CC1", "2": "GND"}),
        ("RCC2", RESISTOR, {"1": "CC2", "2": "GND"}),
        ("C5", CAPACITOR, {"1": "VBUSF", "2": "GND"}),
        ("C6", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("R17", RESISTOR, {"1": "VCC", "2": "PWLED"}),
        ("D17", LED, {"2": "PWLED", "1": "GND"}),
        ("C1", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C2", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("REN1", RESISTOR, {"1": "VCC", "2": "EN"}),
        ("CEN1", CAPACITOR, {"1": "EN", "2": "GND"}),
        ("RS1", RESISTOR, {"1": "VCC", "2": "IO2"}),
        ("RS2", RESISTOR, {"1": "VCC", "2": "IO8"}),
        ("ROE1", RESISTOR, {"1": "VCC", "2": "OE"}),
        ("C3", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C4", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C7", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("RI1", RESISTOR, {"1": "VCC", "2": "SDA1"}),
        ("RI2", RESISTOR, {"1": "VCC", "2": "SCL1"}),
        ("RI3", RESISTOR, {"1": "VCC", "2": "SDA2"}),
        ("RI4", RESISTOR, {"1": "VCC", "2": "SCL2"}),
    ])
    resistors = _row(ROW3_Y, 25.4, [
        (f"R{index}", RESISTOR, {"1": f"SEG{index}", "2": f"LK{index}"})
        for index in range(1, LED_COUNT + 1)
    ])
    leds = _row(ROW4_Y, 25.4, [
        (f"D{index}", LED, {"2": f"LK{index}", "1": "GND"})
        for index in range(1, LED_COUNT + 1)
    ])
    return (*row1, *support, *resistors, *leds)


INSTANCES = _instances()

_OFFICIAL_LIBS = (
    USB_C, ESP32, HC595, SHT31, AP2112, RESISTOR, CAPACITOR, LED,
    POLYFUSE, CONN4, TESTPOINT, PWR_FLAG,
)


def export_thermometer_to_kicad(
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
    markers: list[str] = []

    for reference, lib_id, x, y, pin_nets in INSTANCES:
        value, footprint = fields[reference]
        imported = load_symbol(lib_id)
        symbols.append(
            _symbol(
                lib_id, reference, value, x, y, project_name,
                exclude_from_sim=True, footprint=footprint,
                pin_count=len(imported.pins),
                in_bom=not reference.startswith("TP"),
            )
        )
        seen_tips: set[tuple[float, float]] = set()
        for pin_number, net in pin_nets.items():
            tip, endpoint = pin_stub(imported, pin_number, (x, y))
            if tip in seen_tips:
                continue  # stacked pin: one stub serves them all
            seen_tips.add(tip)
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))
        for pin_number in NO_CONNECTS.get(reference, ()):
            nc_x, nc_y = instance_pin_position(imported, pin_number, (x, y))
            markers.append(_no_connect(nc_x, nc_y))

    # ERC power sources: GND has only power_in sinks, and the LDO's
    # VIN needs a driver on the fused VBUS node. VCC is driven by the
    # LDO's power_out, VBUS has no power_in pins.
    flag = load_symbol(PWR_FLAG)
    for index, net in enumerate(("GND", "VBUSF")):
        x = 347.98 + index * 17.78
        symbols.append(
            _symbol(
                PWR_FLAG, f"#FLG0{index + 1}", "PWR_FLAG", x, ROW1_Y,
                project_name, exclude_from_sim=True, footprint="",
                pin_count=1, in_bom=False, on_board=False,
            )
        )
        tip, _out = pin_stub(flag, "1", (x, ROW1_Y))
        endpoint = (tip[0], tip[1] + 2.54)
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    lib_symbols = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id))
        for lib_id in _OFFICIAL_LIBS
    )
    items = "\n".join((*symbols, *wires, *labels, *markers))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {uuid4()})
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
