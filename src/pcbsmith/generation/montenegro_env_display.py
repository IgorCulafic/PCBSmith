"""Circuit authority for the Montenegro environment-display art board.

This is deliberately a two-layer presentation prototype.  The LED border and
display are visible from the front; the controller, protection, regulator,
sensor support circuitry, and service controls live on the back.
"""

from __future__ import annotations

from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)

SUPPORTED_TOPOLOGY_ID = "montenegro_env_display_r001"
LED_COUNT = 35
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"


def _source(
    title: str,
    url: str,
    locator: str,
    *,
    status: str = "confirmed",
) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="manufacturer_document",
            title=title,
            locator=locator,
            official_url=url,
            source_status="unpinned",
            locator_status="figure_verified",
            applicability_status=status,
        ),
    )


ESP32 = _source(
    "ESP32-S3-WROOM-1 datasheet",
    "https://documentation.espressif.com/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf",
    "Module dimensions, supply, native USB, pinout, and PCB-antenna land pattern.",
)
ESP32_LAYOUT = _source(
    "ESP32-S3 hardware design guidelines",
    "https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/pcb-layout-design.html",
    "Module placement, antenna keepout, power, USB, and decoupling guidance.",
)
SHT45 = _source(
    "Sensirion SHT4x datasheet and design-in resources",
    "https://sensirion.com/products/catalog/SHT45",
    "SHT45-AD1B package, I2C interface, accuracy, and design-in documents.",
)
OLED = _source(
    "Waveshare 1.5inch RGB OLED Module",
    "https://www.waveshare.com/wiki/1.5inch_RGB_OLED_Module",
    "SSD1351, 128x128, 4-wire SPI, 3.3/5 V, 7-pin PH2.0 interface.",
    status="conditional",
)
USB = _source(
    "GCT USB4105 drawing",
    "https://gct.co/connector/usb4105",
    "USB4105-GF-A 16-contact top-mount USB Type-C receptacle.",
)


def _part(
    reference: str,
    role: str,
    value: str,
    footprint: str,
    symbol_id: str,
    evidence: tuple[EvidenceRef, ...] = (),
) -> ComponentRole:
    return ComponentRole(
        reference=reference,
        role=role,
        symbol_id=symbol_id,
        value=value,
        footprint=footprint,
        support_status="supported",
        evidence=evidence,
    )


def compose_montenegro_env_display() -> CircuitObject:
    components: list[ComponentRole] = [
        _part(
            "U1",
            "wifi_usb_mcu_module",
            "ESP32-S3-WROOM-1-N8",
            "PCBSmith_Montenegro:ESP32-S3-WROOM-1_HomeFab",
            "stdlib:ESP32-S3-WROOM-1",
            (*ESP32, *ESP32_LAYOUT),
        ),
        _part(
            "U2",
            "3v3_linear_regulator",
            "NCP1117-3.3",
            "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            "stdlib:NCP1117-3.3_SOT223",
        ),
        _part(
            "U3",
            "usb_data_esd",
            "USBLC6-2SC6",
            "Package_TO_SOT_SMD:SOT-23-6",
            "stdlib:USBLC6-2SC6",
            USB,
        ),
        _part(
            "U4",
            "temperature_humidity_sensor",
            "SHT45-AD1B-R3",
            "Sensor_Humidity:Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_NoCentralPad",
            "stdlib:SHT4x",
            SHT45,
        ),
        _part(
            "U5",
            "led_data_level_shifter",
            "SN74AHCT1G125DBVR",
            "Package_TO_SOT_SMD:SOT-23-5",
            "stdlib:74AHCT1G125",
        ),
        _part(
            "J1",
            "usb_c_power_and_data",
            "USB4105-GF-A",
            "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
            "stdlib:USB_C_Receptacle_USB2.0_16P",
            USB,
        ),
        _part(
            "J2",
            "oled_module_cable",
            "Waveshare 1.5in SSD1351 OLED PH2.0",
            "Connector_JST:JST_PH_S7B-PH-SM4-TB_1x07-1MP_P2.00mm_Horizontal",
            "stdlib:Conn_01x07",
            OLED,
        ),
        _part(
            "F1",
            "usb_input_resettable_fuse",
            "3.0A polyfuse",
            "Fuse:Fuse_1206_3216Metric",
            "stdlib:Polyfuse",
        ),
        _part(
            "SW1",
            "boot_service_button",
            "BOOT",
            "Button_Switch_SMD:SW_SPST_B3U-1000P",
            "stdlib:SW_Push",
        ),
        _part(
            "SW2",
            "reset_service_button",
            "RESET",
            "Button_Switch_SMD:SW_SPST_B3U-1000P",
            "stdlib:SW_Push",
        ),
    ]
    resistor_values = {
        "R1": "5.1k CC1 Rd",
        "R2": "5.1k CC2 Rd",
        "R3": "22R USB D-",
        "R4": "22R USB D+",
        "R5": "10k EN pull-up",
        "R6": "4.7k SDA pull-up",
        "R7": "4.7k SCL pull-up",
        "R8": "100R LED data series",
        "R9": "10k BOOT pull-up",
    }
    for reference, value in resistor_values.items():
        components.append(_part(reference, value.lower(), value, R0603, "stdlib:R"))

    capacitor_values = {
        "C1": ("10u regulator input", C1210),
        "C2": ("10u regulator output", C1210),
        "C3": ("1u EN delay", C0603),
        "C4": ("100n ESP32 local", C0603),
        "C5": ("100n SHT45 local", C0603),
        "C6": ("100n level shifter local", C0603),
        "C7": ("100u LED bulk", C1210),
    }
    for reference, (value, footprint) in capacitor_values.items():
        components.append(_part(reference, value.lower(), value, footprint, "stdlib:C"))
    for index in range(LED_COUNT):
        reference = f"C{index + 8}"
        components.append(
            _part(
                reference,
                f"led_{index + 1}_local_decoupling",
                "100n",
                C0603,
                "stdlib:C",
            )
        )
    for index in range(1, LED_COUNT + 1):
        components.append(
            _part(
                f"D{index}",
                f"border_rgb_led_{index}",
                "WS2812B",
                "LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm",
                "stdlib:WS2812B",
            )
        )

    nets = {
        "VBUS_RAW",
        "+5V",
        "+3V3",
        "GND",
        "USB_D+_CONN",
        "USB_D-_CONN",
        "USB_D+_ESD",
        "USB_D-_ESD",
        "ESP_EN",
        "ESP_BOOT",
        "I2C_SDA",
        "I2C_SCL",
        "OLED_MOSI",
        "OLED_SCLK",
        "OLED_CS",
        "OLED_DC",
        "OLED_RST",
        "LED_DATA_3V3",
        "LED_DATA_5V",
    }
    nets.update(f"LED_CHAIN_{index:02d}" for index in range(1, LED_COUNT))
    full_white_current_a = LED_COUNT * 0.060
    logic_peak_current_a = 0.56
    total_peak_current_a = full_white_current_a + logic_peak_current_a
    math = MathReport(
        status="warning",
        calculations={
            "led_count": float(LED_COUNT),
            "led_worst_case_current_a": full_white_current_a,
            "logic_and_display_peak_current_a": logic_peak_current_a,
            "total_worst_case_current_a": total_peak_current_a,
            "usb_c_design_supply_a": 3.0,
            "supply_margin_a": 3.0 - total_peak_current_a,
            "ldo_worst_case_dissipation_w": (5.0 - 3.3) * logic_peak_current_a,
        },
        findings=(
            "The 3 A supply contract leaves little worst-case margin; firmware must "
            "start with a brightness cap when attached to an unknown USB host.",
            "The linear regulator can dissipate about 0.95 W at the conservative "
            "logic/display peak; copper spreading and thermal verification are "
            "release gates.",
            "The Waveshare display mounting and cable envelope remain conditional "
            "on the vendor mechanical drawing and a physical fit check.",
        ),
    )
    intent = CircuitIntent(
        raw_request=(
            "Montenegro-shaped two-layer presentation board with an RGB LED border, "
            "central image-capable OLED, SHT45, and ESP32-S3."
        ),
        intent_id="montenegro-env-display-r001",
        status="supported",
        assumptions={
            "board_width_mm": 150.0,
            "board_height_mm_approx": 178.0,
            "layer_count": 2.0,
            "led_count": float(LED_COUNT),
            "supply_voltage_v": 5.0,
            "supply_current_a": 3.0,
            "display_width_mm": 44.5,
            "display_height_mm": 37.0,
            "prototype_only": True,
        },
    )
    topology = TopologySelection(
        topology_id=SUPPORTED_TOPOLOGY_ID,
        title="Two-layer Montenegro ESP32-S3 environment display",
        status="selected",
        evidence=(*ESP32, *ESP32_LAYOUT, *SHT45, *OLED, *USB),
        warnings=(
            "The supplied stock silhouette is a visual reference, not licensed or "
            "geodetic manufacturing authority.",
            "A physical OLED-module fit check and measured thermal test remain "
            "mandatory before fabrication release.",
        ),
    )
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=tuple(components),
        nets=tuple(sorted(nets)),
        math=math,
    )
