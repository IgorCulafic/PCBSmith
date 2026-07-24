"""Circuit authority for the reduced eight-channel USB protocol analyzer.

The board is deliberately input-only.  It captures eight digital channels in
parallel into RP2040 SRAM and uploads completed captures over USB; it does not
promise indefinite 10--20 MS/s USB streaming.  The 2x10 target header alternates
signals with ground returns and exposes only a protected VTARGET monitor and a
separately conditioned trigger input.
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

SUPPORTED_TOPOLOGY_ID = "protocol_analyzer_8ch_r001"

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"


def _source(
    title: str,
    locator: str,
    *,
    source_id: str,
    sha256: str,
    official_url: str,
) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="manufacturer_document",
            title=title,
            locator=locator,
            source_id=source_id,
            official_url=official_url,
            local_sha256=sha256,
            source_status="pinned",
            locator_status="figure_verified",
            applicability_status="confirmed",
        ),
    )


def _engineering(title: str, locator: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="engineering_assumption",
            title=title,
            locator=locator,
            source_status="unknown",
            locator_status="unverified",
            applicability_status="conditional",
        ),
    )


RP2040 = _source(
    "Hardware design with RP2040",
    "Official minimal-design power, QSPI flash, 12 MHz crystal, USB, and layout guidance.",
    source_id="protocol-analyzer.rp2040.hardware-design.2025",
    sha256="6523a2ebf743fcfbcc69bc3901b24ca3a2d23617d8ee50beb5f606b31134f0b5",
    official_url=(
        "https://pip-assets.raspberrypi.com/categories/814-rp2040/documents/"
        "RP-008279-DS-1-hardware-design-with-rp2040.pdf"
    ),
)
LVC244 = _source(
    "Texas Instruments SN74LVC244A datasheet",
    "Octal 3-state buffer; 1.65--3.6 V supply and 5.5 V-tolerant inputs.",
    source_id="protocol-analyzer.ti.sn74lvc244a.2024",
    sha256="1a0708009bb8423943e886bd4bafa744ffff8d17dabbf8cd07a3862459ce7080",
    official_url="https://www.ti.com/lit/ds/symlink/sn74lvc244a.pdf",
)
INPUT_ESD = _source(
    "Texas Instruments TPD4E05U06 datasheet",
    "Four low-capacitance bidirectional ESD channels in DQA/USON-10.",
    source_id="protocol-analyzer.ti.tpd4e05u06.2021",
    sha256="c167cf1e72a5473a4d2c59b6a3c0251498701da05b7785919b9ceaae3b3e02c6",
    official_url="https://www.ti.com/lit/ds/symlink/tpd4e05u06.pdf",
)
TRIGGER_BUFFER = _source(
    "Texas Instruments SN74LVC1G17 datasheet",
    "Single Schmitt-trigger buffer with 5.5 V-tolerant input at 3.3 V supply.",
    source_id="protocol-analyzer.ti.sn74lvc1g17.2025",
    sha256="2570a9354a9b24e71a2073c0cb8cfafb3895198236eb14eaa21c0bb032d93a83",
    official_url="https://www.ti.com/lit/ds/symlink/sn74lvc1g17.pdf",
)


def _part(
    reference: str,
    role: str,
    value: str,
    footprint: str,
    evidence: tuple[EvidenceRef, ...],
    *,
    symbol_id: str,
    supported: bool = True,
) -> ComponentRole:
    return ComponentRole(
        reference=reference,
        role=role,
        symbol_id=symbol_id,
        value=value,
        support_status="supported" if supported else "needs_datasheet_review",
        footprint=footprint,
        evidence=evidence,
    )


def compose_protocol_analyzer_8ch() -> CircuitObject:
    """Return the complete schematic authority for revision R001."""

    parts: list[ComponentRole] = [
        _part(
            "U1",
            "capture_mcu",
            "RP2040",
            "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm",
            RP2040,
            symbol_id="stdlib:RP2040",
        ),
        _part(
            "U2",
            "qspi_program_flash",
            "W25Q16JVSSIQ 2MiB",
            "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            RP2040,
            symbol_id="stdlib:W25Q16JVSS",
        ),
        _part(
            "U3",
            "usb_to_3v3_ldo",
            "AP2112K-3.3",
            "Package_TO_SOT_SMD:SOT-23-5",
            _engineering("3.3 V regulator", "600 mA LDO; verify ordered MPN and thermal margin."),
            symbol_id="stdlib:AP2112K-3.3",
            supported=False,
        ),
        _part(
            "U4", "eight_channel_input_buffer", "SN74LVC244APWR",
            "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm", LVC244,
            symbol_id="stdlib:74HC244",
        ),
        _part(
            "U6", "channels_0_3_esd", "TPD4E05U06DQAR",
            "Package_SON:USON-10_2.5x1.0mm_P0.5mm", INPUT_ESD,
            symbol_id="stdlib:TPD4E05U06DQA",
        ),
        _part(
            "U7", "channels_4_7_esd", "TPD4E05U06DQAR",
            "Package_SON:USON-10_2.5x1.0mm_P0.5mm", INPUT_ESD,
            symbol_id="stdlib:TPD4E05U06DQA",
        ),
        _part(
            "U8", "usb_esd", "USBLC6-2SC6",
            "Package_TO_SOT_SMD:SOT-23-6", _engineering(
                "USB flow-through ESD",
                "Place directly behind the receptacle before the 27 ohm series resistors.",
            ),
            symbol_id="stdlib:USBLC6-2SC6",
            supported=False,
        ),
        _part(
            "U9", "trigger_schmitt_buffer", "SN74LVC1G17DBVR",
            "Package_TO_SOT_SMD:SOT-23-5", TRIGGER_BUFFER,
            symbol_id="stdlib:74LVC1G17",
        ),
        _part(
            "J1", "usb_c_receptacle", "USB4105 USB-C 2.0",
            "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
            _engineering("USB-C receptacle", "USB 2.0 device-only connector."),
            symbol_id="stdlib:USB_C",
            supported=False,
        ),
        _part(
            "J2", "target_input_header", "2x10 2.54mm",
            "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical",
            _engineering(
                "Input-only target header",
                "Eight channels alternate with GND; pin 17 VTARGET monitor and pin 19 trigger.",
            ),
            symbol_id="stdlib:Conn_02x10",
        ),
        _part(
            "J3", "swd_debug_header", "Cortex SWD 2x5 1.27mm",
            "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical",
            RP2040,
            symbol_id="stdlib:Conn_02x05",
        ),
        _part(
            "Y1", "mcu_crystal", "12MHz ABM8",
            "Crystal:Crystal_SMD_Abracon_ABM8G-4Pin_3.2x2.5mm",
            RP2040, symbol_id="stdlib:Crystal_GND24",
        ),
        _part(
            "SW1", "bootsel_switch", "BOOTSEL",
            "PCBSmith_Protocol:Alps_SKRTLAE010_RightAngle",
            RP2040, symbol_id="stdlib:SW_Push",
        ),
        _part(
            "SW2", "reset_switch", "RESET",
            "PCBSmith_Protocol:Alps_SKRTLAE010_RightAngle",
            RP2040, symbol_id="stdlib:SW_Push",
        ),
        _part(
            "D1", "power_indicator", "GREEN",
            "LED_SMD:LED_0603_1608Metric",
            _engineering("Power indicator", "3.3 V indicator LED."),
            symbol_id="stdlib:LED",
        ),
        _part(
            "D2", "capture_indicator", "AMBER",
            "LED_SMD:LED_0603_1608Metric",
            _engineering("Capture indicator", "Firmware-controlled status LED."),
            symbol_id="stdlib:LED",
        ),
        _part(
            "D3", "trigger_esd", "PESD5V0S1BA",
            "Diode_SMD:D_SOD-323",
            _engineering("Trigger ESD diode", "Bidirectional low-capacitance 5 V line clamp."),
            symbol_id="stdlib:D_TVS",
            supported=False,
        ),
    ]

    resistor_values = {
        "R1": ("cc1_rd", "5.1k"),
        "R2": ("cc2_rd", "5.1k"),
        "R3": ("usb_dm_series", "27R"),
        "R4": ("usb_dp_series", "27R"),
        "R5": ("crystal_series", "1k"),
        "R6": ("bootsel_series", "1k"),
        "R7": ("qspi_ss_pullup", "10k"),
        "R8": ("run_pullup", "10k"),
        "R9": ("power_led_series", "1k"),
        "R10": ("status_led_series", "1k"),
        **{f"R{index + 11}": (f"channel_{index}_series", "33R") for index in range(8)},
        "R19": ("trigger_series", "33R"),
        "R20": ("vtarget_divider_high", "100k 1%"),
        "R21": ("vtarget_divider_low", "56k 1%"),
        "R22": ("trigger_pulldown", "100k"),
    }
    for reference, (role, value) in resistor_values.items():
        evidence = (
            RP2040
            if reference in {"R3", "R4", "R5", "R6", "R7", "R8"}
            else _engineering(role, value)
        )
        parts.append(_part(reference, role, value, R0603, evidence, symbol_id="stdlib:R"))

    capacitor_values = {
        "C1": ("vbus_bulk", "10uF", C0805),
        "C2": ("ldo_input", "1uF", C0805),
        "C3": ("ldo_output", "1uF", C0805),
        "C4": ("3v3_bulk", "10uF", C0805),
        "C5": ("crystal_load", "15pF", C0603),
        "C6": ("crystal_load", "15pF", C0603),
        "C7": ("buffer_u4_bypass", "100nF", C0603),
        "C8": ("buffer_u5_bypass", "100nF", C0603),
        "C9": ("trigger_buffer_bypass", "100nF", C0603),
        **{f"C{index}": ("rp2040_3v3_bypass", "100nF", C0603) for index in range(10, 17)},
        "C17": ("rp2040_1v1_bypass", "1uF", C0603),
        "C18": ("flash_bypass", "100nF", C0603),
        "C19": ("vtarget_filter", "10nF", C0603),
    }
    for reference, (role, value, footprint) in capacitor_values.items():
        parts.append(_part(reference, role, value, footprint, RP2040, symbol_id="stdlib:C"))

    nets = (
        "VBUS", "3V3", "1V1", "GND", "CC1", "CC2", "PWR_LED_K",
        "USB_DP_CONN", "USB_DM_CONN", "USB_DP_ESD", "USB_DM_ESD",
        "USB_DP_MCU", "USB_DM_MCU", "XIN", "XOUT_RAW", "XOUT",
        "RUN", "SWCLK", "SWDIO", "QSPI_SCLK", "QSPI_SD0", "QSPI_SD1",
        "QSPI_SD2", "QSPI_SD3", "QSPI_SS", "BOOT_BTN",
        *(f"CH{index}_RAW" for index in range(8)),
        *(f"CH{index}_IN" for index in range(8)),
        *(f"CH{index}_BUF" for index in range(8)),
        "TRIG_RAW", "TRIG_IN", "TRIG_BUF", "VTARGET_RAW", "VTARGET_ADC",
        "STATUS_GPIO", "STATUS_LED_A",
    )
    return CircuitObject(
        intent=CircuitIntent(
            raw_request=(
                "Reduced 8-channel two-layer USB protocol analyzer for SPI, I2C, "
                "UART, and 1-Wire capture"
            ),
            intent_id=SUPPORTED_TOPOLOGY_ID,
            status="supported",
            assumptions={
                "usb_vbus_v": 5.0,
                "logic_supply_v": 3.3,
                "input_max_v": 5.5,
                "required_sample_rate_msps": 10.0,
                "stretch_sample_rate_msps": 20.0,
                "channel_count": 8.0,
                "capture_buffer_kib": 128.0,
                "pcb_layers": 2.0,
                "board_width_mm": 70.0,
                "board_height_mm": 42.0,
            },
        ),
        topology=TopologySelection(
            topology_id=SUPPORTED_TOPOLOGY_ID,
            title="RP2040 SRAM capture with eight protected LVC-buffered inputs",
            status="selected",
            evidence=(*RP2040, *LVC244, *INPUT_ESD, *TRIGGER_BUFFER),
            warnings=(
                "The 20 MS/s rate is a stretch target until firmware and "
                "signal-integrity measurements pass.",
                "The board is input-only and does not source VTARGET or target I/O.",
                "The USON-10 ESD arrays are not hand-solder-friendly and are an assembly risk.",
            ),
        ),
        components=tuple(parts),
        nets=nets,
        math=MathReport(
            status="warning",
            calculations={
                "capture_buffer_bytes": 131072.0,
                "bytes_per_parallel_sample": 1.0,
                "capture_duration_ms_at_10_msps": 13.1072,
                "capture_duration_ms_at_20_msps": 6.5536,
                "vtarget_adc_v_at_5v": 5.0 * 56.0 / 156.0,
                "vtarget_adc_v_at_5v5": 5.5 * 56.0 / 156.0,
            },
            findings=(
                "Use one PIO state machine plus DMA for synchronous eight-bit samples.",
                "Stop acquisition at the configured trigger/capture depth, then upload over USB.",
                "Measure input threshold, overshoot, maximum reliable sample rate, "
                "and channel skew before claiming performance.",
            ),
        ),
    )
