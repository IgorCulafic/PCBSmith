"""KiCad 10 schematic/project export for AeroSense-2F R001."""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.generation.aerosense_2f import SUPPORTED_TOPOLOGY_ID
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
TUSB320 = "Interface_USB:TUSB320"
CONN6 = "Connector_Generic:Conn_01x06"
USB_ESD = "Power_Protection:USBLC6-2SC6"
SHT4X = "Sensor_Humidity:SHT4x"
TVS = "Device:D_TVS"
CC_ESD = "Power_Protection:TPD2EUSB30"
SD_ESD = "Power_Protection:TPD4E05U06DQA"
USB_C = "Connector:USB_C_Receptacle_USB2.0_16P"
MICROSD = "Connector:Micro_SD_Card_Det_Hirose_DM3AT"
CONN4 = "Connector_Generic:Conn_01x04"
CONN6_2ROW = "Connector_Generic:Conn_02x03_Odd_Even"
CRYSTAL = "Device:Crystal_GND24"
FERRITE = "Device:FerriteBead"
NMOS = "Transistor_FET:2N7002"
LED = "Device:LED"
SWITCH = "Switch:SW_Push"
RESISTOR = "Device:R"
CAPACITOR = "Device:C"
PWR_FLAG = "power:PWR_FLAG"
TEST_POINT = "Connector:TestPoint"

SchematicInstance = tuple[str, str, float, float, dict[str, str]]

U1_PIN_NETS = {
    "1": "3V3",
    "10": "3V3",
    "22": "3V3",
    "33": "3V3",
    "42": "3V3",
    "49": "3V3",
    "23": "1V1",
    "50": "1V1",
    "43": "ADC_3V3",
    "44": "3V3",
    "45": "1V1",
    "48": "3V3",
    "19": "GND",
    "57": "GND",
    "20": "XIN",
    "21": "XOUT_RAW",
    "24": "SWCLK",
    "25": "SWDIO",
    "26": "RUN",
    "2": "I2C_SDA",
    "3": "I2C_SCL",
    "4": "SD_MISO",
    "5": "SD_CS_MCU",
    "6": "SD_SCLK_MCU",
    "7": "SD_MOSI_MCU",
    "8": "FAN1_EN",
    "9": "FAN2_EN",
    "11": "FAN1_PWM_GPIO",
    "12": "FAN2_PWM_GPIO",
    "13": "FAN1_TACH",
    "14": "FAN2_TACH",
    "15": "FAN1_FAULT_N",
    "16": "FAN2_FAULT_N",
    "17": "TYPEC_OUT1",
    "18": "TYPEC_OUT2",
    "27": "SW_MODE",
    "28": "SW_SELECT",
    "29": "SW_LOG",
    "30": "LED_PWR_A",
    "31": "LED_FAULT_A",
    "32": "LED_LOG_A",
    "34": "SD_DETECT",
    "35": "OLED_RESET",
    "46": "USB_DM_MCU",
    "47": "USB_DP_MCU",
    "51": "QSPI_SD3",
    "52": "QSPI_SCLK",
    "53": "QSPI_SD0",
    "54": "QSPI_SD2",
    "55": "QSPI_SD1",
    "56": "QSPI_SS",
}

NO_CONNECTS: dict[str, tuple[str, ...]] = {
    "J1": ("A8", "B8"),
    "DS1": ("2",),
    "J3": ("1", "8"),
    "U1": ("36", "37", "38", "39", "40", "41"),
    "U3": ("4",),
    "U4": ("5", "6", "9"),
    "U11": ("6", "7", "9", "10"),
    "J6": ("6",),
}


def _instances() -> tuple[SchematicInstance, ...]:
    items: list[SchematicInstance] = [
        (
            "J1",
            USB_C,
            25.4,
            40.64,
            {
                "A1": "GND",
                "A12": "GND",
                "B1": "GND",
                "B12": "GND",
                "SH": "GND",
                "A4": "VBUS",
                "A9": "VBUS",
                "B4": "VBUS",
                "B9": "VBUS",
                "A5": "CC1",
                "B5": "CC2",
                "A6": "USB_DP_CONN",
                "B6": "USB_DP_CONN",
                "A7": "USB_DM_CONN",
                "B7": "USB_DM_CONN",
            },
        ),
        (
            "U7",
            USB_ESD,
            68.58,
            40.64,
            {
                "1": "USB_DP_CONN",
                "6": "USB_DP_ESD",
                "3": "USB_DM_CONN",
                "4": "USB_DM_ESD",
                "2": "GND",
                "5": "VBUS",
            },
        ),
        ("R1", RESISTOR, 91.44, 33.02, {"1": "USB_DM_ESD", "2": "USB_DM_MCU"}),
        ("R2", RESISTOR, 91.44, 48.26, {"1": "USB_DP_ESD", "2": "USB_DP_MCU"}),
        ("U9", TVS, 116.84, 27.94, {"1": "GND", "2": "VBUS"}),
        (
            "U10",
            CC_ESD,
            116.84,
            43.18,
            {"1": "CC1", "2": "CC2", "3": "GND"},
        ),
        (
            "U4",
            TUSB320,
            157.48,
            40.64,
            {
                "1": "CC1",
                "2": "CC2",
                "3": "GND",
                "4": "VBUS_DET",
                "7": "TYPEC_OUT1",
                "8": "TYPEC_OUT2",
                "10": "GND",
                "11": "GND",
                "12": "3V3",
            },
        ),
        ("R6", RESISTOR, 190.50, 25.40, {"1": "3V3", "2": "TYPEC_OUT1"}),
        ("R7", RESISTOR, 190.50, 40.64, {"1": "3V3", "2": "TYPEC_OUT2"}),
        ("R8", RESISTOR, 190.50, 55.88, {"1": "VBUS", "2": "VBUS_DET"}),
        ("C17", CAPACITOR, 218.44, 40.64, {"1": "3V3", "2": "GND"}),
        (
            "U3",
            LDO,
            251.46,
            40.64,
            {"1": "VBUS", "2": "GND", "3": "VBUS", "5": "3V3"},
        ),
        ("C1", CAPACITOR, 279.40, 27.94, {"1": "VBUS", "2": "GND"}),
        ("C2", CAPACITOR, 299.72, 27.94, {"1": "VBUS", "2": "GND"}),
        ("C3", CAPACITOR, 320.04, 27.94, {"1": "3V3", "2": "GND"}),
        ("C28", CAPACITOR, 340.36, 27.94, {"1": "3V3", "2": "GND"}),
        ("U1", RP2040, 147.32, 109.22, U1_PIN_NETS),
        (
            "U2",
            FLASH,
            228.60,
            91.44,
            {
                "1": "QSPI_SS",
                "2": "QSPI_SD1",
                "3": "QSPI_SD2",
                "4": "GND",
                "5": "QSPI_SD0",
                "6": "QSPI_SCLK",
                "7": "QSPI_SD3",
                "8": "3V3",
            },
        ),
        ("R4", RESISTOR, 261.62, 83.82, {"1": "3V3", "2": "QSPI_SS"}),
        ("C14", CAPACITOR, 261.62, 99.06, {"1": "3V3", "2": "GND"}),
        ("Y1", CRYSTAL, 50.80, 93.98, {"1": "XIN", "2": "GND", "3": "XOUT", "4": "GND"}),
        ("R3", RESISTOR, 76.20, 93.98, {"1": "XOUT_RAW", "2": "XOUT"}),
        ("C15", CAPACITOR, 50.80, 114.30, {"1": "XIN", "2": "GND"}),
        ("C16", CAPACITOR, 76.20, 114.30, {"1": "XOUT", "2": "GND"}),
        ("FB1", FERRITE, 294.64, 83.82, {"1": "3V3", "2": "ADC_3V3"}),
        ("C13", CAPACITOR, 320.04, 83.82, {"1": "ADC_3V3", "2": "GND"}),
        ("R5", RESISTOR, 294.64, 104.14, {"1": "3V3", "2": "RUN"}),
        ("SW4", SWITCH, 294.64, 121.92, {"1": "BOOT_BTN", "2": "GND"}),
        ("R34", RESISTOR, 271.78, 121.92, {"1": "QSPI_SS", "2": "BOOT_BTN"}),
        ("SW5", SWITCH, 320.04, 121.92, {"1": "RUN", "2": "GND"}),
        (
            "J6",
            CONN6_2ROW,
            355.60,
            101.60,
            {
                "1": "3V3",
                "2": "SWDIO",
                "3": "GND",
                "4": "SWCLK",
                "5": "RUN",
            },
        ),
        (
            "DS1",
            CONN6,
            25.40,
            177.80,
            {
                "1": "3V3",
                "3": "GND",
                "4": "OLED_RESET",
                "5": "I2C_SCL",
                "6": "I2C_SDA",
            },
        ),
        ("C27", CAPACITOR, 53.34, 177.80, {"1": "3V3", "2": "GND"}),
        (
            "U8",
            SHT4X,
            88.90,
            177.80,
            {"1": "I2C_SDA", "2": "I2C_SCL", "3": "3V3", "4": "GND"},
        ),
        ("C24", CAPACITOR, 116.84, 177.80, {"1": "3V3", "2": "GND"}),
        (
            "J3",
            MICROSD,
            167.64,
            177.80,
            {
                "2": "SD_CS_CARD",
                "3": "SD_MOSI_CARD",
                "4": "3V3",
                "5": "SD_SCLK_CARD",
                "6": "GND",
                "7": "SD_MISO",
                "9": "GND",
                "10": "SD_DETECT",
                "SH": "GND",
            },
        ),
        (
            "U11",
            SD_ESD,
            218.44,
            177.80,
            {
                "1": "SD_CS_CARD",
                "2": "SD_MOSI_CARD",
                "3": "GND",
                "4": "SD_SCLK_CARD",
                "5": "SD_MISO",
                "8": "GND",
            },
        ),
        ("R29", RESISTOR, 254.00, 157.48, {"1": "3V3", "2": "SD_CS_CARD"}),
        ("R30", RESISTOR, 254.00, 175.26, {"1": "SD_CS_MCU", "2": "SD_CS_CARD"}),
        ("R31", RESISTOR, 254.00, 193.04, {"1": "SD_MOSI_MCU", "2": "SD_MOSI_CARD"}),
        ("R32", RESISTOR, 254.00, 210.82, {"1": "SD_SCLK_MCU", "2": "SD_SCLK_CARD"}),
        ("R33", RESISTOR, 284.48, 162.56, {"1": "3V3", "2": "SD_DETECT"}),
        ("C25", CAPACITOR, 284.48, 177.80, {"1": "3V3", "2": "GND"}),
        ("C26", CAPACITOR, 304.80, 177.80, {"1": "3V3", "2": "GND"}),
    ]

    for channel, y in ((1, 238.76), (2, 294.64)):
        switch_ref = f"U{channel + 4}"
        fan_ref = f"J{channel + 3}"
        q_ref = f"Q{channel}"
        suffix = str(channel)
        items.extend(
            [
                (
                    switch_ref,
                    CONN6,
                    55.88,
                    y,
                    {
                        "1": "VBUS",
                        "2": "GND",
                        "3": f"FAN{suffix}_EN",
                        "4": f"FAN{suffix}_FAULT_N",
                        "5": f"FAN{suffix}_ILIM",
                        "6": f"FAN{suffix}_5V",
                    },
                ),
                (
                    f"R{8 + channel}",
                    RESISTOR,
                    83.82,
                    y - 10.16,
                    {"1": f"FAN{suffix}_ILIM", "2": "GND"},
                ),
                (
                    f"R{10 + channel}",
                    RESISTOR,
                    104.14,
                    y,
                    {"1": f"FAN{suffix}_EN", "2": "GND"},
                ),
                (
                    f"R{12 + channel}",
                    RESISTOR,
                    83.82,
                    y + 10.16,
                    {"1": "3V3", "2": f"FAN{suffix}_FAULT_N"},
                ),
                (
                    fan_ref,
                    CONN4,
                    127.00,
                    y,
                    {
                        "1": "GND",
                        "2": f"FAN{suffix}_5V",
                        "3": f"FAN{suffix}_TACH_RAW",
                        "4": f"FAN{suffix}_PWM",
                    },
                ),
                (
                    f"C{17 + channel}",
                    CAPACITOR,
                    157.48,
                    y - 15.24,
                    {"1": "VBUS", "2": "GND"},
                ),
                (
                    f"C{19 + channel}",
                    CAPACITOR,
                    175.26,
                    y - 5.08,
                    {"1": f"FAN{suffix}_5V", "2": "GND"},
                ),
                (
                    f"C{21 + channel}",
                    CAPACITOR,
                    157.48,
                    y + 5.08,
                    {"1": f"FAN{suffix}_5V", "2": "GND"},
                ),
                (
                    f"R{14 + channel}",
                    RESISTOR,
                    190.50,
                    y - 10.16,
                    {"1": "3V3", "2": f"FAN{suffix}_TACH_RAW"},
                ),
                (
                    f"R{16 + channel}",
                    RESISTOR,
                    190.50,
                    y,
                    {"1": f"FAN{suffix}_TACH_RAW", "2": f"FAN{suffix}_TACH"},
                ),
                (
                    f"C{28 + channel}",
                    CAPACITOR,
                    190.50,
                    y + 10.16,
                    {"1": f"FAN{suffix}_TACH", "2": "GND"},
                ),
                (
                    f"R{18 + channel}",
                    RESISTOR,
                    226.06,
                    y - 10.16,
                    {"1": f"FAN{suffix}_PWM_GPIO", "2": f"FAN{suffix}_PWM_GATE"},
                ),
                (
                    f"R{20 + channel}",
                    RESISTOR,
                    226.06,
                    y,
                    {"1": f"FAN{suffix}_PWM_GATE", "2": "GND"},
                ),
                (
                    q_ref,
                    NMOS,
                    261.62,
                    y,
                    {
                        "1": f"FAN{suffix}_PWM_GATE",
                        "2": "GND",
                        "3": f"FAN{suffix}_PWM",
                    },
                ),
            ]
        )

    for index, x in enumerate((25.40, 73.66, 121.92), start=1):
        switch_net = ("SW_MODE", "SW_SELECT", "SW_LOG")[index - 1]
        items.extend(
            [
                (f"SW{index}", SWITCH, x, 355.60, {"1": switch_net, "2": "GND"}),
                (
                    f"R{22 + index}",
                    RESISTOR,
                    x,
                    370.84,
                    {"1": "3V3", "2": switch_net},
                ),
            ]
        )
    for index, x in enumerate((190.50, 238.76, 287.02), start=1):
        led_net = ("LED_PWR_A", "LED_FAULT_A", "LED_LOG_A")[index - 1]
        items.extend(
            [
                (
                    f"R{25 + index}",
                    RESISTOR,
                    x,
                    355.60,
                    {"1": led_net, "2": f"LED{index}_ANODE"},
                ),
                (
                    f"D{index}",
                    LED,
                    x + 25.40,
                    355.60,
                    {"2": f"LED{index}_ANODE", "1": "GND"},
                ),
            ]
        )

    test_points = (
        ("TP1", "VBUS"),
        ("TP2", "3V3"),
        ("TP3", "FAN1_5V"),
        ("TP4", "FAN2_5V"),
        ("TP5", "GND"),
        ("TP6", "FAN1_TACH"),
        ("TP7", "FAN2_TACH"),
    )
    for offset, (reference, net) in enumerate(test_points):
        items.append(
            (
                reference,
                TEST_POINT,
                314.96,
                149.86 + offset * 15.24,
                {"1": net},
            )
        )

    bypass_nets = {
        **{f"C{index}": "3V3" for index in range(4, 12)},
        "C12": "1V1",
    }
    for offset, (reference, net) in enumerate(bypass_nets.items()):
        x = 25.40 + (offset % 5) * 35.56
        y = 142.24 + (offset // 5) * 17.78
        items.append((reference, CAPACITOR, x, y, {"1": net, "2": "GND"}))
    return tuple(items)


INSTANCES = _instances()
_OFFICIAL_LIBS = tuple(
    dict.fromkeys(
        (
            *(instance[1] for instance in INSTANCES),
            PWR_FLAG,
        )
    )
)


def export_aerosense_2f_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
    profile: PcbRuleProfile,
) -> dict[str, str]:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for AeroSense-2F KiCad export")
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
        _render_schematic(circuit, project_name),
        encoding="utf-8",
    )
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
    symbols: list[str] = []
    wires: list[str] = []
    labels: list[str] = []
    markers: list[str] = []
    for reference, lib_id, x, y, pin_nets in INSTANCES:
        value, footprint = fields[reference]
        imported = load_symbol(lib_id)
        is_test_point = reference.startswith("TP")
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
                reference_at=((x - 5.08, y) if is_test_point else (x, y - 2.54)),
                value_at=((x + 12.70, y) if is_test_point else (x, y + 2.54)),
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
        for pin_number in NO_CONNECTS.get(reference, ()):
            nc_x, nc_y = instance_pin_position(imported, pin_number, (x, y))
            markers.append(_no_connect(nc_x, nc_y))

    flag = load_symbol(PWR_FLAG)
    for index, net in enumerate(("VBUS", "ADC_3V3", "GND"), start=1):
        x = 342.90
        y = 330.20 + index * 12.70
        symbols.append(
            _symbol(
                PWR_FLAG,
                f"#FLG0{index}",
                "PWR_FLAG",
                x,
                y,
                project_name,
                exclude_from_sim=True,
                footprint="",
                pin_count=1,
                in_bom=False,
                on_board=False,
                value_at=(x + 10.16, y),
            )
        )
        tip, endpoint = pin_stub(flag, "1", (x, y))
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
