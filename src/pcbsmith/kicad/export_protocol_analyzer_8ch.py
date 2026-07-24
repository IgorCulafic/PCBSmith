"""KiCad schematic export for the reduced eight-channel protocol analyzer."""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.generation.protocol_analyzer_8ch import SUPPORTED_TOPOLOGY_ID
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

RP2040 = "MCU_RaspberryPi:RP2040"
FLASH = "Memory_Flash:W25Q16JVSS"
LDO = "Regulator_Linear:AP2112K-3.3"
BUFFER8 = "74xx:74HC244"
BUFFER1 = "74xGxx:74LVC1G17"
INPUT_ESD = "Power_Protection:TPD4E05U06DQA"
USB_ESD = "Power_Protection:USBLC6-2SC6"
USB_C = "Connector:USB_C_Receptacle_USB2.0_16P"
CONN20 = "Connector_Generic:Conn_02x10_Odd_Even"
CONN10 = "Connector_Generic:Conn_02x05_Odd_Even"
CRYSTAL = "Device:Crystal_GND24"
RESISTOR = "Device:R"
CAPACITOR = "Device:C"
SWITCH = "Switch:SW_Push"
LED = "Device:LED"
TVS = "Device:D_TVS"
PWR_FLAG = "power:PWR_FLAG"

SchematicInstance = tuple[str, str, float, float, dict[str, str]]

U1_PIN_NETS = {
    "1": "3V3", "10": "3V3", "22": "3V3", "33": "3V3", "42": "3V3",
    "43": "3V3", "44": "3V3", "48": "3V3", "49": "3V3",
    "23": "1V1", "45": "1V1", "50": "1V1",
    "19": "GND", "57": "GND",
    "20": "XIN", "21": "XOUT_RAW",
    "24": "SWCLK", "25": "SWDIO", "26": "RUN",
    "27": "STATUS_GPIO", "31": "TRIG_BUF",
    "32": "CH7_BUF", "34": "CH6_BUF", "35": "CH5_BUF", "36": "CH4_BUF",
    "37": "CH3_BUF", "38": "CH2_BUF", "39": "CH1_BUF", "40": "CH0_BUF",
    "41": "VTARGET_ADC",
    "46": "USB_DM_MCU", "47": "USB_DP_MCU",
    "51": "QSPI_SD3", "52": "QSPI_SCLK", "53": "QSPI_SD0",
    "54": "QSPI_SD2", "55": "QSPI_SD1", "56": "QSPI_SS",
}

NO_CONNECTS: dict[str, tuple[str, ...]] = {
    "J1": ("A8", "B8"),
    "J3": ("6", "7", "8"),
    "U1": (
        "2", "3", "4", "5", "6", "7", "8", "9",
        "11", "12", "13", "14", "15", "16", "17", "18",
        "28", "29", "30",
    ),
    "U3": ("4",),
    "U6": ("6", "7", "9", "10"),
    "U7": ("6", "7", "9", "10"),
    "U9": ("1",),
}


def _buffer_pin_nets() -> dict[str, str]:
    result = {"1": "GND", "19": "GND", "10": "GND", "20": "3V3"}
    for channel, input_pin, output_pin in (
        (0, "2", "18"), (1, "4", "16"), (2, "6", "14"), (3, "8", "12"),
        (4, "17", "3"), (5, "15", "5"), (6, "13", "7"), (7, "11", "9"),
    ):
        result[input_pin] = f"CH{channel}_IN"
        result[output_pin] = f"CH{channel}_BUF"
    return result


def _instances() -> tuple[SchematicInstance, ...]:
    primary: list[SchematicInstance] = [
        (
            "J1", USB_C, 25.4, 45.72,
            {
                "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND",
                "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
                "A5": "CC1", "B5": "CC2",
                "A6": "USB_DP_CONN", "B6": "USB_DP_CONN",
                "A7": "USB_DM_CONN", "B7": "USB_DM_CONN",
            },
        ),
        (
            "U8", USB_ESD, 68.58, 45.72,
            {
                "1": "USB_DP_CONN", "6": "USB_DP_ESD",
                "3": "USB_DM_CONN", "4": "USB_DM_ESD",
                "2": "GND", "5": "VBUS",
            },
        ),
        ("R3", RESISTOR, 91.44, 35.56, {"1": "USB_DM_ESD", "2": "USB_DM_MCU"}),
        ("R4", RESISTOR, 91.44, 55.88, {"1": "USB_DP_ESD", "2": "USB_DP_MCU"}),
        ("U3", LDO, 119.38, 45.72, {"1": "VBUS", "2": "GND", "3": "VBUS", "5": "3V3"}),
        ("R1", RESISTOR, 144.78, 35.56, {"1": "CC1", "2": "GND"}),
        ("R2", RESISTOR, 144.78, 55.88, {"1": "CC2", "2": "GND"}),
        ("C1", CAPACITOR, 165.10, 35.56, {"1": "VBUS", "2": "GND"}),
        ("C2", CAPACITOR, 180.34, 35.56, {"1": "VBUS", "2": "GND"}),
        ("C3", CAPACITOR, 195.58, 35.56, {"1": "3V3", "2": "GND"}),
        ("C4", CAPACITOR, 210.82, 35.56, {"1": "3V3", "2": "GND"}),
        ("D1", LED, 231.14, 45.72, {"2": "3V3", "1": "PWR_LED_K"}),
        ("R9", RESISTOR, 251.46, 45.72, {"1": "PWR_LED_K", "2": "GND"}),
        ("U1", RP2040, 121.92, 111.76, U1_PIN_NETS),
        (
            "U2", FLASH, 198.12, 91.44,
            {
                "1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "4": "GND",
                "5": "QSPI_SD0", "6": "QSPI_SCLK", "7": "QSPI_SD3", "8": "3V3",
            },
        ),
        ("Y1", CRYSTAL, 55.88, 91.44, {"1": "XIN", "2": "GND", "3": "XOUT", "4": "GND"}),
        ("R5", RESISTOR, 78.74, 91.44, {"1": "XOUT_RAW", "2": "XOUT"}),
        ("C5", CAPACITOR, 45.72, 111.76, {"1": "XIN", "2": "GND"}),
        ("C6", CAPACITOR, 66.04, 111.76, {"1": "XOUT", "2": "GND"}),
        ("SW1", SWITCH, 210.82, 111.76, {"1": "BOOT_BTN", "2": "GND"}),
        ("R6", RESISTOR, 231.14, 101.60, {"1": "QSPI_SS", "2": "BOOT_BTN"}),
        ("R7", RESISTOR, 231.14, 121.92, {"1": "3V3", "2": "QSPI_SS"}),
        ("SW2", SWITCH, 210.82, 137.16, {"1": "RUN", "2": "GND"}),
        ("R8", RESISTOR, 231.14, 137.16, {"1": "3V3", "2": "RUN"}),
        (
            "J3", CONN10, 266.70, 111.76,
            {
                "1": "3V3", "2": "SWDIO", "3": "GND", "4": "SWCLK",
                "5": "GND", "9": "GND", "10": "RUN",
            },
        ),
        ("R10", RESISTOR, 266.70, 137.16, {"1": "STATUS_GPIO", "2": "STATUS_LED_A"}),
        ("D2", LED, 292.10, 137.16, {"2": "STATUS_LED_A", "1": "GND"}),
        (
            "J2", CONN20, 25.40, 203.20,
            {
                "1": "CH0_RAW", "2": "GND", "3": "CH1_RAW", "4": "GND",
                "5": "CH2_RAW", "6": "GND", "7": "CH3_RAW", "8": "GND",
                "9": "CH4_RAW", "10": "GND", "11": "CH5_RAW", "12": "GND",
                "13": "CH6_RAW", "14": "GND", "15": "CH7_RAW", "16": "GND",
                "17": "VTARGET_RAW", "18": "GND", "19": "TRIG_RAW", "20": "GND",
            },
        ),
        (
            "U6", INPUT_ESD, 66.04, 187.96,
            {
                "1": "CH0_RAW", "2": "CH1_RAW", "3": "GND",
                "4": "CH2_RAW", "5": "CH3_RAW", "8": "GND",
            },
        ),
        (
            "U7", INPUT_ESD, 66.04, 218.44,
            {
                "1": "CH4_RAW", "2": "CH5_RAW", "3": "GND",
                "4": "CH6_RAW", "5": "CH7_RAW", "8": "GND",
            },
        ),
        ("U4", BUFFER8, 198.12, 203.20, _buffer_pin_nets()),
        ("D3", TVS, 91.44, 243.84, {"1": "TRIG_RAW", "2": "GND"}),
        ("R19", RESISTOR, 111.76, 243.84, {"1": "TRIG_RAW", "2": "TRIG_IN"}),
        ("R22", RESISTOR, 132.08, 254.00, {"1": "TRIG_RAW", "2": "GND"}),
        ("U9", BUFFER1, 157.48, 243.84, {"2": "TRIG_IN", "3": "GND", "4": "TRIG_BUF", "5": "3V3"}),
        ("R20", RESISTOR, 198.12, 243.84, {"1": "VTARGET_RAW", "2": "VTARGET_ADC"}),
        ("R21", RESISTOR, 223.52, 243.84, {"1": "VTARGET_ADC", "2": "GND"}),
        ("C19", CAPACITOR, 248.92, 243.84, {"1": "VTARGET_ADC", "2": "GND"}),
    ]
    for index in range(8):
        x = 101.60 + (index % 4) * 20.32
        y = 177.80 if index < 4 else 213.36
        primary.append(
            (
                f"R{index + 11}", RESISTOR, x, y,
                {"1": f"CH{index}_RAW", "2": f"CH{index}_IN"},
            )
        )
    bypass_nets = {
        "C7": "3V3", "C8": "3V3", "C9": "3V3",
        **{f"C{index}": "3V3" for index in range(10, 17)},
        "C17": "1V1", "C18": "3V3",
    }
    for offset, (reference, net) in enumerate(bypass_nets.items()):
        primary.append(
            (
                reference, CAPACITOR,
                25.40 + offset * 17.78, 281.94,
                {"1": net, "2": "GND"},
            )
        )
    return tuple(primary)


INSTANCES = _instances()
_OFFICIAL_LIBS = (
    RP2040, FLASH, LDO, BUFFER8, BUFFER1, INPUT_ESD, USB_ESD, USB_C,
    CONN20, CONN10, CRYSTAL, RESISTOR, CAPACITOR, SWITCH, LED, TVS, PWR_FLAG,
)


def export_protocol_analyzer_8ch_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
    profile: PcbRuleProfile,
    instances: tuple[SchematicInstance, ...] = INSTANCES,
    spread_pin_label_references: frozenset[str] = frozenset(),
    spread_pin_label_distance_mm: float = 5.08,
    stagger_vertical_label_references: frozenset[str] = frozenset(),
    property_positions: dict[
        str, tuple[tuple[float, float], tuple[float, float]]
    ] | None = None,
) -> dict[str, str]:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for protocol-analyzer KiCad export")
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
    symbol_library.write_text(
        f"""(kicad_symbol_lib
  (version {KICAD_SYMBOL_LIBRARY_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
)
""",
        encoding="utf-8",
    )
    schematic_file.write_text(
        _render_schematic(
            circuit,
            project_name,
            instances=instances,
            spread_pin_label_references=spread_pin_label_references,
            spread_pin_label_distance_mm=spread_pin_label_distance_mm,
            stagger_vertical_label_references=stagger_vertical_label_references,
            property_positions=property_positions,
        ),
        encoding="utf-8",
    )
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
        "symbol_library": str(symbol_library),
    }


def _render_schematic(
    circuit: CircuitObject,
    project_name: str,
    *,
    instances: tuple[SchematicInstance, ...] = INSTANCES,
    spread_pin_label_references: frozenset[str] = frozenset(),
    spread_pin_label_distance_mm: float = 5.08,
    stagger_vertical_label_references: frozenset[str] = frozenset(),
    property_positions: dict[
        str, tuple[tuple[float, float], tuple[float, float]]
    ] | None = None,
) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }
    symbols: list[str] = []
    wires: list[str] = []
    labels: list[str] = []
    markers: list[str] = []
    property_positions = property_positions or {}
    for reference, lib_id, x, y, pin_nets in instances:
        value, footprint = fields[reference]
        imported = load_symbol(lib_id)
        reference_at, value_at = property_positions.get(
            reference,
            ((x, y - 2.54), (x, y + 2.54)),
        )
        symbols.append(
            _symbol(
                lib_id, reference, value, x, y, project_name,
                exclude_from_sim=True, footprint=footprint, pin_count=len(imported.pins),
                reference_at=reference_at,
                value_at=value_at,
            )
        )
        seen_tips: set[tuple[float, float]] = set()
        pin_records: list[
            tuple[tuple[float, float], tuple[float, float], str]
        ] = []
        for pin_number, net in pin_nets.items():
            tip, endpoint = pin_stub(imported, pin_number, (x, y))
            if tip in seen_tips:
                continue
            seen_tips.add(tip)
            pin_records.append((tip, endpoint, net))
        vertical_index = 0
        for tip, endpoint, net in pin_records:
            dx = endpoint[0] - tip[0]
            dy = endpoint[1] - tip[1]
            label_at = endpoint
            if reference in spread_pin_label_references and abs(dx) >= abs(dy):
                sign = 1 if dx >= 0 else -1
                label_at = (
                    endpoint[0] + sign * spread_pin_label_distance_mm,
                    endpoint[1],
                )
            elif (
                reference in stagger_vertical_label_references
                and abs(dy) > abs(dx)
            ):
                # Keep the wire collinear with the pin while alternating two
                # extra lengths. This separates repeated power labels without
                # introducing the crossing/dogleg risk of arbitrary spreading.
                sign = 1 if dy >= 0 else -1
                extra = 5.08 + (vertical_index % 4) * 2.54
                label_at = (endpoint[0], endpoint[1] + sign * extra)
                vertical_index += 1
            wires.append(_wire(tip, endpoint))
            if label_at != endpoint:
                wires.append(_wire(endpoint, label_at))
            labels.append(_label(net, *label_at))
        for pin_number in NO_CONNECTS.get(reference, ()):
            nc_x, nc_y = instance_pin_position(imported, pin_number, (x, y))
            markers.append(_no_connect(nc_x, nc_y))

    flag = load_symbol(PWR_FLAG)
    for index, net in enumerate(("VBUS", "GND"), start=1):
        x = 320.04 + index * 30.48
        y = 281.94
        symbols.append(
            _symbol(
                PWR_FLAG, f"#FLG0{index}", "PWR_FLAG", x, y, project_name,
                exclude_from_sim=True, footprint="", pin_count=1,
                in_bom=False, on_board=False,
                value_at=(x, y + 10.16),
            )
        )
        tip, _endpoint = pin_stub(flag, "1", (x, y))
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
  (uuid {stable_kicad_uuid("schematic-root", "machine", project_name, SUPPORTED_TOPOLOGY_ID)})
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
