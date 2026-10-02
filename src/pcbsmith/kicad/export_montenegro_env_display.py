"""KiCad 10 schematic/project export for Montenegro Environment Display R001."""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.generation.montenegro_env_display import LED_COUNT, SUPPORTED_TOPOLOGY_ID
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
from pcbsmith.kicad.montenegro_env_display_board import MONTENEGRO_RULE_PROFILE
from pcbsmith.kicad.symbols import (
    instance_pin_position,
    load_symbol,
    pin_stub,
    render_symbol_for_schematic,
)

ESP32_SYMBOL = "RF_Module:ESP32-S3-WROOM-1"
USB_SYMBOL = "Connector:USB_C_Receptacle_USB2.0_16P"
ESD_SYMBOL = "Power_Protection:USBLC6-2SC6"
REGULATOR_SYMBOL = "Regulator_Linear:NCP1117-3.3_SOT223"
SHT45_SYMBOL = "Sensor_Humidity:SHT4x"
SHIFTER_SYMBOL = "74xGxx:74AHCT1G125"
OLED_CONNECTOR_SYMBOL = "Connector_Generic:Conn_01x07"
FUSE_SYMBOL = "Device:Polyfuse"
BUTTON_SYMBOL = "Switch:SW_Push"
RESISTOR_SYMBOL = "Device:R"
CAPACITOR_SYMBOL = "Device:C"
LED_SYMBOL = "LED:WS2812B"
POWER_FLAG_SYMBOL = "power:PWR_FLAG"

U1_PIN_NETS = {
    "1": "GND",
    "2": "+3V3",
    "3": "ESP_EN",
    "4": "LED_DATA_3V3",
    "12": "I2C_SDA",
    "13": "USB_D-_MCU",
    "14": "USB_D+_MCU",
    "17": "I2C_SCL",
    "18": "OLED_CS",
    "19": "OLED_MOSI",
    "20": "OLED_SCLK",
    "21": "OLED_DC",
    "22": "OLED_RST",
    "27": "ESP_BOOT",
    "40": "GND",
    "41": "GND",
}
U1_NC_PINS = tuple(str(index) for index in range(1, 42) if str(index) not in U1_PIN_NETS)

PIN_NETS: dict[str, dict[str, str]] = {
    "J1": {
        "A1": "GND",
        "A4": "VBUS_RAW",
        "A5": "CC1",
        "A6": "USB_D+_CONN",
        "A7": "USB_D-_CONN",
        "A9": "VBUS_RAW",
        "A12": "GND",
        "B1": "GND",
        "B4": "VBUS_RAW",
        "B5": "CC2",
        "B6": "USB_D+_CONN",
        "B7": "USB_D-_CONN",
        "B9": "VBUS_RAW",
        "B12": "GND",
        "SH": "GND",
    },
    "F1": {"1": "VBUS_RAW", "2": "+5V"},
    "U2": {"1": "GND", "2": "+3V3", "3": "+5V"},
    "U3": {
        "1": "USB_D+_CONN",
        "2": "GND",
        "3": "USB_D-_CONN",
        "4": "USB_D-_ESD",
        "5": "VBUS_RAW",
        "6": "USB_D+_ESD",
    },
    "U4": {"1": "I2C_SDA", "2": "I2C_SCL", "3": "+3V3", "4": "GND"},
    "U5": {
        "1": "GND",
        "2": "LED_DATA_3V3",
        "3": "GND",
        "4": "LED_DATA_5V_PRE",
        "5": "+5V",
    },
    "J2": {
        "1": "+3V3",
        "2": "GND",
        "3": "OLED_MOSI",
        "4": "OLED_SCLK",
        "5": "OLED_CS",
        "6": "OLED_DC",
        "7": "OLED_RST",
    },
    "SW1": {"1": "ESP_BOOT", "2": "GND"},
    "SW2": {"1": "ESP_EN", "2": "GND"},
    "R1": {"1": "CC1", "2": "GND"},
    "R2": {"1": "CC2", "2": "GND"},
    "R3": {"1": "USB_D-_ESD", "2": "USB_D-_MCU"},
    "R4": {"1": "USB_D+_ESD", "2": "USB_D+_MCU"},
    "R5": {"1": "+3V3", "2": "ESP_EN"},
    "R6": {"1": "+3V3", "2": "I2C_SDA"},
    "R7": {"1": "+3V3", "2": "I2C_SCL"},
    "R8": {"1": "LED_DATA_5V_PRE", "2": "LED_DATA_5V"},
    "R9": {"1": "+3V3", "2": "ESP_BOOT"},
    "C1": {"1": "+5V", "2": "GND"},
    "C2": {"1": "+3V3", "2": "GND"},
    "C3": {"1": "ESP_EN", "2": "GND"},
    "C4": {"1": "+3V3", "2": "GND"},
    "C5": {"1": "+3V3", "2": "GND"},
    "C6": {"1": "+5V", "2": "GND"},
    "C7": {"1": "+5V", "2": "GND"},
    "U1": U1_PIN_NETS,
}

for index in range(1, LED_COUNT + 1):
    data_in = "LED_DATA_5V" if index == 1 else f"LED_CHAIN_{index - 1:02d}"
    PIN_NETS[f"D{index}"] = {"1": "+5V", "3": "GND", "4": data_in}
    if index < LED_COUNT:
        PIN_NETS[f"D{index}"]["2"] = f"LED_CHAIN_{index:02d}"
    PIN_NETS[f"C{index + 7}"] = {"1": "+5V", "2": "GND"}

NO_CONNECTS = {
    "J1": ("A8", "B8"),
    "U1": U1_NC_PINS,
    f"D{LED_COUNT}": ("2",),
}


def export_montenegro_env_display_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for Montenegro environment display export")
    project_name = _validate_project_name(project_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"
    project_file.write_text(_render_project(profile=MONTENEGRO_RULE_PROFILE), encoding="utf-8")
    schematic_file.write_text(_render_schematic(circuit, project_name), encoding="utf-8")
    return {"project_file": str(project_file), "schematic_file": str(schematic_file)}


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }

    def symbol(
        lib_id: str,
        reference: str,
        x: float,
        y: float,
        *,
        pin_count: int,
        rotation: int = 0,
        in_bom: bool = True,
        on_board: bool = True,
        value: str | None = None,
    ) -> str:
        default_value, footprint = fields.get(reference, ("", ""))
        return _symbol(
            lib_id,
            reference,
            value or default_value,
            x,
            y,
            project_name,
            rotation=rotation,
            exclude_from_sim=True,
            footprint=footprint,
            in_bom=in_bom,
            on_board=on_board,
            pin_count=pin_count,
        )

    imported = {
        lib_id: load_symbol(lib_id)
        for lib_id in (
            ESP32_SYMBOL,
            USB_SYMBOL,
            ESD_SYMBOL,
            REGULATOR_SYMBOL,
            SHT45_SYMBOL,
            SHIFTER_SYMBOL,
            OLED_CONNECTOR_SYMBOL,
            FUSE_SYMBOL,
            BUTTON_SYMBOL,
            RESISTOR_SYMBOL,
            CAPACITOR_SYMBOL,
            LED_SYMBOL,
            POWER_FLAG_SYMBOL,
        )
    }
    placements: list[tuple[str, str, float, float, int]] = [
        ("J1", USB_SYMBOL, 25.4, 38.1, 0),
        ("U3", ESD_SYMBOL, 71.12, 38.1, 0),
        ("F1", FUSE_SYMBOL, 111.76, 30.48, 0),
        ("U2", REGULATOR_SYMBOL, 147.32, 38.1, 0),
        ("U1", ESP32_SYMBOL, 91.44, 91.44, 0),
        ("U4", SHT45_SYMBOL, 172.72, 83.82, 0),
        ("U5", SHIFTER_SYMBOL, 223.52, 83.82, 0),
        ("J2", OLED_CONNECTOR_SYMBOL, 279.4, 83.82, 0),
        ("SW1", BUTTON_SYMBOL, 330.2, 76.2, 0),
        ("SW2", BUTTON_SYMBOL, 330.2, 91.44, 0),
    ]
    passive_positions = {
        "R1": (50.8, 25.4),
        "R2": (63.5, 25.4),
        "R3": (88.9, 25.4),
        "R4": (101.6, 25.4),
        "R5": (127.0, 66.04),
        "R6": (160.02, 66.04),
        "R7": (172.72, 66.04),
        "R8": (248.92, 83.82),
        "R9": (342.9, 76.2),
        "C1": (127.0, 48.26),
        "C2": (167.64, 48.26),
        "C3": (139.7, 66.04),
        "C4": (116.84, 91.44),
        "C5": (190.5, 83.82),
        "C6": (236.22, 66.04),
        "C7": (111.76, 48.26),
    }
    for reference, (x, y) in passive_positions.items():
        lib_id = RESISTOR_SYMBOL if reference.startswith("R") else CAPACITOR_SYMBOL
        placements.append((reference, lib_id, x, y, 0))

    symbols: list[str] = []
    wires: list[str] = []
    labels: list[str] = []
    no_connects: list[str] = []

    for reference, lib_id, x, y, rotation in placements:
        symbols.append(
            symbol(
                lib_id,
                reference,
                x,
                y,
                pin_count=len(imported[lib_id].pins),
                rotation=rotation,
            )
        )
        for pin_number, net in PIN_NETS[reference].items():
            tip, endpoint = pin_stub(imported[lib_id], pin_number, (x, y), rotation)
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))
        for pin_number in NO_CONNECTS.get(reference, ()):
            point = instance_pin_position(imported[lib_id], pin_number, (x, y))
            no_connects.append(_no_connect(*point))

    # Four uncluttered rows of nine LED/capacitor subcircuits.
    for index in range(1, LED_COUNT + 1):
        row = (index - 1) // 9
        column = (index - 1) % 9
        x = 35.56 + column * 38.1
        y = 147.32 + row * 58.42
        reference = f"D{index}"
        symbols.append(symbol(LED_SYMBOL, reference, x, y, pin_count=4))
        for pin_number, net in PIN_NETS[reference].items():
            tip, endpoint = pin_stub(imported[LED_SYMBOL], pin_number, (x, y))
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))

        for pin_number in NO_CONNECTS.get(reference, ()):
            point = instance_pin_position(imported[LED_SYMBOL], pin_number, (x, y))
            no_connects.append(_no_connect(*point))
        cap_reference = f"C{index + 7}"
        cap_at = (x, y + 20.32)
        symbols.append(symbol(CAPACITOR_SYMBOL, cap_reference, *cap_at, pin_count=2))
        for pin_number, net in PIN_NETS[cap_reference].items():
            tip, endpoint = pin_stub(imported[CAPACITOR_SYMBOL], pin_number, cap_at)
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))

    for index, net in enumerate(("VBUS_RAW", "+5V", "GND"), start=1):
        x = 381.0 + (index - 1) * 30.48
        y = 38.1
        reference = f"#FLG0{index}"
        symbols.append(
            symbol(
                POWER_FLAG_SYMBOL,
                reference,
                x,
                y,
                pin_count=1,
                in_bom=False,
                on_board=False,
                value="PWR_FLAG",
            )
        )
        tip, endpoint = pin_stub(imported[POWER_FLAG_SYMBOL], "1", (x, y))
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    library_ids = tuple(imported)
    lib_symbols = "\n".join(render_symbol_for_schematic(imported[lib_id]) for lib_id in library_ids)
    items = "\n".join((*symbols, *wires, *labels, *no_connects))
    root_uuid = stable_kicad_uuid(
        "schematic-root", "machine", project_name, circuit.topology.topology_id
    )
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {root_uuid})
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
