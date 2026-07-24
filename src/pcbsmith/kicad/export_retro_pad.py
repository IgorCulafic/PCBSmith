"""KiCad schematic export for the Retro-Pad USB macro keyboard."""

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
from pcbsmith.kicad.export_mpu6050 import _no_connect
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.symbols import (
    instance_pin_position,
    load_symbol,
    pin_stub,
    render_symbol_for_schematic,
)
from pcbsmith.rule_profiles import PcbRuleProfile

SUPPORTED_TOPOLOGY_ID = "retro_pad_usb_macro_keyboard"
SUPPORTED_TOPOLOGY_IDS = (
    SUPPORTED_TOPOLOGY_ID,
    "retro_pad_usb_macro_keyboard_3x3",
)

ATMEGA = "MCU_Microchip_ATmega:ATmega32U4-A"
USB_ESD = "Power_Protection:USBLC6-2SC6"
USB_C = "Connector:USB_C_Receptacle_USB2.0_16P"
CONN6 = "Connector_Generic:Conn_02x03_Odd_Even"
CONN4 = "Connector_Generic:Conn_01x04"
SWITCH = "Switch:SW_Push"
DIODE = "Device:D"
ENCODER = "Device:RotaryEncoder_Switch"
CRYSTAL = "Device:Crystal_GND24"
RESISTOR = "Device:R"
CAPACITOR = "Device:C"
POLYFUSE = "Device:Polyfuse"
PWR_FLAG = "power:PWR_FLAG"

J1_PIN_NETS = {
    "A1": "GND",
    "B1": "GND",
    "A12": "GND",
    "B12": "GND",
    "SH": "GND",
    "A4": "VBUS_RAW",
    "A9": "VBUS_RAW",
    "B4": "VBUS_RAW",
    "B9": "VBUS_RAW",
    "A5": "CC1",
    "B5": "CC2",
    "A6": "USB_DP_CONN",
    "B6": "USB_DP_CONN",
    "A7": "USB_DM_CONN",
    "B7": "USB_DM_CONN",
}

U1_PIN_NETS = {
    "1": "LED_DATA_MCU",
    "2": "VCC",
    "3": "USB_DM_MCU",
    "4": "USB_DP_MCU",
    "5": "GND",
    "6": "UCAP",
    "7": "VBUS_RAW",
    "9": "SCK",
    "10": "MOSI",
    "11": "MISO",
    "13": "RESET",
    "14": "VCC",
    "15": "GND",
    "16": "XTAL2",
    "17": "XTAL1",
    "18": "ROW0",
    "19": "ROW1",
    "20": "COL0",
    "21": "COL1",
    "23": "GND",
    "24": "VCC",
    "25": "ENC_A",
    "26": "ENC_B",
    "27": "ENC_SW",
    "33": "HWB",
    "34": "VCC",
    "35": "GND",
    "42": "AREF",
    "43": "GND",
    "44": "VCC",
}

NO_CONNECTS: dict[str, tuple[str, ...]] = {
    "J1": ("A8", "B8"),
    "U1": (
        "8",
        "12",
        "22",
        "28",
        "29",
        "30",
        "31",
        "32",
        "36",
        "37",
        "38",
        "39",
        "40",
        "41",
    ),
    # The last pixel's data output is intentionally unused.
    "D8": ("2",),
}

ROW1_Y = 58.42
ROW2_Y = 127.0
ROW3_Y = 190.5
ROW4_Y = 246.38


def _instances() -> tuple[tuple[str, str, float, float, dict[str, str]], ...]:
    main = (
        ("J1", USB_C, 35.56, ROW1_Y, J1_PIN_NETS),
        (
            "U2",
            USB_ESD,
            81.28,
            ROW1_Y,
            {
                "1": "USB_DP_CONN",
                "6": "USB_DP_PROTECTED",
                "3": "USB_DM_CONN",
                "4": "USB_DM_PROTECTED",
                "2": "GND",
                "5": "VCC",
            },
        ),
        ("R3", RESISTOR, 104.14, ROW1_Y, {"1": "USB_DM_PROTECTED", "2": "USB_DM_MCU"}),
        ("R4", RESISTOR, 124.46, ROW1_Y, {"1": "USB_DP_PROTECTED", "2": "USB_DP_MCU"}),
        ("F1", POLYFUSE, 144.78, ROW1_Y, {"1": "VBUS_RAW", "2": "VCC"}),
        ("U1", ATMEGA, 193.04, ROW1_Y, U1_PIN_NETS),
        ("Y1", CRYSTAL, 251.46, ROW1_Y, {"1": "XTAL1", "2": "GND", "3": "XTAL2", "4": "GND"}),
        (
            "J2",
            CONN6,
            292.10,
            ROW1_Y,
            {
                "1": "MISO",
                "2": "VCC",
                "3": "SCK",
                "4": "MOSI",
                "5": "RESET",
                "6": "GND",
            },
        ),
        (
            "SW5",
            ENCODER,
            330.20,
            ROW1_Y,
            {
                "A": "ENC_A",
                "B": "ENC_B",
                "C": "GND",
                "S1": "GND",
                "S2": "ENC_SW",
            },
        ),
    )

    matrix: list[tuple[str, str, float, float, dict[str, str]]] = []
    key_maps = (
        ("COL0", "ROW0", "KEY1_D"),
        ("COL1", "ROW0", "KEY2_D"),
        ("COL0", "ROW1", "KEY3_D"),
        ("COL1", "ROW1", "KEY4_D"),
    )
    for index, (column, row, intermediate) in enumerate(key_maps, start=1):
        x = 35.56 + (index - 1) * 55.88
        matrix.append((f"SW{index}", SWITCH, x, ROW2_Y, {"1": column, "2": intermediate}))
        matrix.append((f"D{index}", DIODE, x + 22.86, ROW2_Y, {"2": intermediate, "1": row}))

    leds: list[tuple[str, str, float, float, dict[str, str]]] = []
    led_inputs = ("LED_DATA_1", "LED_LINK_1", "LED_LINK_2", "LED_LINK_3")
    led_outputs = ("LED_LINK_1", "LED_LINK_2", "LED_LINK_3", None)
    for offset, index in enumerate(range(5, 9)):
        pin_nets = {
            "1": "VCC",
            "3": "GND",
            "4": led_inputs[offset],
        }
        led_output = led_outputs[offset]
        if led_output is not None:
            pin_nets["2"] = led_output
        leds.append(
            (
                f"D{index}",
                CONN4,
                35.56 + offset * 50.8,
                ROW3_Y,
                pin_nets,
            )
        )

    support_defs = (
        ("R1", RESISTOR, {"1": "CC1", "2": "GND"}),
        ("R2", RESISTOR, {"1": "CC2", "2": "GND"}),
        ("R5", RESISTOR, {"1": "VCC", "2": "RESET"}),
        ("R6", RESISTOR, {"1": "HWB", "2": "GND"}),
        ("R7", RESISTOR, {"1": "LED_DATA_MCU", "2": "LED_DATA_1"}),
        ("R8", RESISTOR, {"1": "VCC", "2": "ENC_A"}),
        ("R9", RESISTOR, {"1": "VCC", "2": "ENC_B"}),
        ("R10", RESISTOR, {"1": "VCC", "2": "ENC_SW"}),
        ("C1", CAPACITOR, {"1": "XTAL1", "2": "GND"}),
        ("C2", CAPACITOR, {"1": "XTAL2", "2": "GND"}),
        ("C3", CAPACITOR, {"1": "UCAP", "2": "GND"}),
        ("C4", CAPACITOR, {"1": "AREF", "2": "GND"}),
        ("C5", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C6", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C7", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C8", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C9", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C10", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C11", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C12", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C13", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C14", CAPACITOR, {"1": "VCC", "2": "GND"}),
        ("C15", CAPACITOR, {"1": "ENC_A", "2": "GND"}),
        ("C16", CAPACITOR, {"1": "ENC_B", "2": "GND"}),
        ("C17", CAPACITOR, {"1": "ENC_SW", "2": "GND"}),
    )
    support = tuple(
        (reference, lib_id, 25.4 + index * 15.24, ROW4_Y, pins)
        for index, (reference, lib_id, pins) in enumerate(support_defs)
    )
    return (*main, *matrix, *leds, *support)


INSTANCES = _instances()
SchematicInstance = tuple[str, str, float, float, dict[str, str]]
_OFFICIAL_LIBS = (
    ATMEGA,
    USB_ESD,
    USB_C,
    CONN6,
    CONN4,
    SWITCH,
    DIODE,
    ENCODER,
    CRYSTAL,
    RESISTOR,
    CAPACITOR,
    POLYFUSE,
    PWR_FLAG,
)


def export_retro_pad_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
    profile: PcbRuleProfile,
    instances: tuple[SchematicInstance, ...] = INSTANCES,
    no_connects: dict[str, tuple[str, ...]] = NO_CONNECTS,
) -> dict[str, str]:
    if circuit.topology.topology_id not in SUPPORTED_TOPOLOGY_IDS:
        raise ValueError("Unsupported circuit for Retro-Pad KiCad export")
    project_name = _validate_project_name(project_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"
    symbol_library = output_dir / "PCBSmith.kicad_sym"
    symbol_table = output_dir / "sym-lib-table"
    project_file.write_text(
        _render_project(min_through_hole_mm=0.3, profile=profile), encoding="utf-8"
    )
    symbol_table.write_text(_render_symbol_table(), encoding="utf-8")
    symbol_library.write_text(_render_empty_library(), encoding="utf-8")
    schematic_file.write_text(
        _render_schematic(
            circuit,
            project_name,
            instances=instances,
            no_connects=no_connects,
        ),
        encoding="utf-8",
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


def _render_schematic(
    circuit: CircuitObject,
    project_name: str,
    *,
    instances: tuple[SchematicInstance, ...] = INSTANCES,
    no_connects: dict[str, tuple[str, ...]] = NO_CONNECTS,
) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }
    symbols: list[str] = []
    wires: list[str] = []
    labels: list[str] = []
    markers: list[str] = []
    for reference, lib_id, x, y, pin_nets in instances:
        value, footprint = fields[reference]
        imported = load_symbol(lib_id)
        symbols.append(
            _symbol(
                lib_id,
                reference,
                value,
                x,
                y,
                project_name,
                exclude_from_sim=True,
                footprint=footprint,
                pin_count=len(imported.pins),
            )
        )
        seen_tips: set[tuple[float, float]] = set()
        for pin_number, net in pin_nets.items():
            tip, endpoint = pin_stub(imported, pin_number, (x, y))
            if tip in seen_tips:
                continue
            seen_tips.add(tip)
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))
        for pin_number in no_connects.get(reference, ()):
            nc_x, nc_y = instance_pin_position(imported, pin_number, (x, y))
            markers.append(_no_connect(nc_x, nc_y))

    flag = load_symbol(PWR_FLAG)
    for index, net in enumerate(("GND", "VCC", "VBUS_RAW"), start=1):
        x = 342.90 + index * 17.78
        symbols.append(
            _symbol(
                PWR_FLAG,
                f"#FLG0{index}",
                "PWR_FLAG",
                x,
                ROW4_Y,
                project_name,
                exclude_from_sim=True,
                footprint="",
                pin_count=1,
                in_bom=False,
                on_board=False,
            )
        )
        tip, _endpoint = pin_stub(flag, "1", (x, ROW4_Y))
        endpoint = (tip[0], tip[1] + 2.54)
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    lib_symbols = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id)) for lib_id in _OFFICIAL_LIBS
    )
    items = "\n".join((*symbols, *wires, *labels, *markers))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {
        stable_kicad_uuid(
            "schematic-root",
            "machine",
            project_name,
            circuit.topology.topology_id,
        )
    })
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
