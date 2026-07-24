"""Retro-Pad USB macro keyboard circuit authority.

The circuit is deliberately explicit about the two points that are easy to
get wrong in this brief: the four keys form a real 2x2 COL-to-ROW matrix with
one diode per key, and the reverse-mount RGB part uses the manufacturer's pin
numbers (1=VDD, 2=DOUT, 3=GND, 4=DIN).  The latter does not match the inherited
pin numbering of KiCad 10's similarly named symbol, so the schematic exporter
uses a four-pin generic graphic with the verified net map.
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

SUPPORTED_TOPOLOGY_ID = "retro_pad_usb_macro_keyboard"

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


ATMEGA = _source(
    "Microchip ATmega16U4/ATmega32U4 datasheet",
    "pp. 3, 30, 258: TQFP pinout, 12-22 pF oscillator guidance, and "
    "USB application with 1 uF UCAP and 22 ohm series resistors",
    source_id="retro-pad-atmega32u4-datasheet",
    sha256="8e8c81dd4119062397bc08d677e7033d7abb4292628414c4e6e0a234cc53203a",
    official_url=(
        "https://ww1.microchip.com/downloads/en/DeviceDoc/"
        "Atmel-7766-8-bit-AVR-ATmega16U4-32U4_Datasheet.pdf"
    ),
)
USB4105 = _source(
    "GCT USB4105 drawing",
    "p. 1: 16-contact USB 2.0 top-mount receptacle pinout and land pattern",
    source_id="retro-pad-gct-usb4105-drawing",
    sha256="fb331fbabee8392ed2937ed757c1610cb0f174b84625147c0b580a18eea8c0e5",
    official_url="https://gct.co/files/drawings/usb4105.pdf",
)
ABM8 = _source(
    "Abracon ABM8 crystal datasheet",
    "pp. 1-2: 16 MHz fundamental crystal, 18 pF load, 70 ohm max ESR, "
    "3.2 x 2.5 mm four-pad package",
    source_id="retro-pad-abm8-16mhz-product",
    sha256="564ac331d8bf38b4ae1222444b0d9cfea3a6ba29148a8be906b2e0ffe40471d8",
    official_url="https://abracon.com/Resonators/abm8.pdf",
)
SK6812 = _source(
    "OPSCO SK6812MINI-E datasheet Rev. 02",
    "pp. 4-5: reverse-mount mechanics; pins 1 VDD, 2 DOUT, 3 GND, "
    "4 DIN; 3.7-5.5 V; 12 mA/channel version",
    source_id="retro-pad-sk6812mini-e-datasheet",
    sha256="164f1e44bdfb408b07642bac9cb95ee43997fa9bdc3434d7815fb37f890a9472",
    official_url=(
        "https://cdn-shop.adafruit.com/product-files/4960/"
        "4960_SK6812MINI-E_REV02_EN.pdf"
    ),
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


def compose_retro_pad() -> CircuitObject:
    """Return the evidence-carrying Retro-Pad circuit object."""
    intent = CircuitIntent(
        raw_request="Retro-Pad USB HID macro keyboard with four keys and EC11",
        intent_id=SUPPORTED_TOPOLOGY_ID,
        status="supported",
        assumptions={
            "vbus_v": 5.0,
            "usb_speed": "full-speed",
            "matrix_rows": 2.0,
            "matrix_columns": 2.0,
            "led_count": 4.0,
            "pcb_layers": 2.0,
            "board_width_mm": 100.0,
        },
    )
    topology = TopologySelection(
        topology_id=SUPPORTED_TOPOLOGY_ID,
        title="ATmega32U4 USB HID, 2x2 diode matrix, EC11, reverse RGB chain",
        status="selected",
        evidence=(*ATMEGA, *USB4105, *ABM8, *SK6812),
        warnings=(
            "The supplied dogbone outline cannot contain holes at literal "
            "bounding-box coordinates (4,4), (96,4), (4,36), (96,36).",
            "SK6812 full-white current exceeds the requested normal operating "
            "budget; firmware must enforce the documented brightness ceiling.",
        ),
    )

    parts: list[ComponentRole] = [
        _part(
            "U1", "native_usb_mcu", "ATmega32U4-AU",
            "Package_QFP:TQFP-44_10x10mm_P0.8mm", ATMEGA,
            symbol_id="stdlib:ATmega32U4-A",
        ),
        _part(
            "U2", "usb_esd_array", "USBLC6-2SC6",
            "Package_TO_SOT_SMD:SOT-23-6_Handsoldering",
            _engineering(
                "USBLC6-2SC6 flow-through ESD array",
                "ST Rev. 7 pin map: I/O1 pins 1/6, GND 2, I/O2 pins 3/4, VBUS 5; "
                "official PDF retrieval remained blocked and is recorded by source intake.",
            ),
            symbol_id="stdlib:USBLC6-2SC6",
            supported=False,
        ),
        _part(
            "J1", "usb_c_receptacle", "USB4105 USB-C 2.0",
            "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
            USB4105, symbol_id="stdlib:USB_C",
        ),
        _part(
            "J2", "avr_isp_header", "AVR-ISP-6",
            "Connector_PinHeader_2.54mm:PinHeader_2x03_P2.54mm_Vertical",
            _engineering("AVR ISP access", "Required to program a blank ATmega32U4."),
            symbol_id="stdlib:AVR_ISP_6",
        ),
        _part(
            "F1", "vbus_polyfuse", "500mA hold",
            "Fuse:Fuse_1206_3216Metric",
            _engineering(
                "USB input resettable fuse",
                "500 mA hold is above the firmware-limited operating current and below "
                "the receptacle rating; confirm exact ordered fuse before production.",
            ),
            symbol_id="stdlib:Polyfuse", supported=False,
        ),
        _part(
            "Y1", "usb_clock_crystal", "ABM8-16.000MHz-18pF",
            "Crystal:Crystal_SMD_Abracon_ABM8G-4Pin_3.2x2.5mm",
            ABM8, symbol_id="stdlib:Crystal_GND24",
        ),
    ]

    for index in range(1, 5):
        parts.extend((
            _part(
                f"SW{index}", "mechanical_key_switch", "Cherry MX compatible",
                "Button_Switch_Keyboard:SW_Cherry_MX_1.00u_PCB",
                _engineering(
                    "PCB-mount Cherry MX compatible switch",
                    "19.05 mm key pitch; switch body may overhang the narrow dogbone neck, "
                    "but every PCB hole and pad must remain on substrate.",
                ),
                symbol_id="stdlib:SW_Push",
            ),
            _part(
                f"D{index}", "matrix_anti_ghosting_diode", "1N4148W",
                "Diode_SMD:D_SOD-123",
                _engineering(
                    "COL-to-ROW matrix diode",
                    "Anode faces the switch/column; cathode faces the row. Scan one row "
                    "low at a time and read columns with pull-ups.",
                ),
                symbol_id="stdlib:D", supported=False,
            ),
        ))

    parts.append(
        _part(
            "SW5", "rotary_encoder_with_push", "EC11E15244B2",
            "Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
            _engineering(
                "Alps EC11E with push switch",
                "Pinned Alps product HTML in private source cache; verify ordered shaft "
                "length and detent/pulse option against EC11E15244B2.",
            ),
            symbol_id="stdlib:RotaryEncoder_Switch", supported=False,
        )
    )
    for index in range(5, 9):
        parts.append(
            _part(
                f"D{index}", "reverse_mount_addressable_rgb", "SK6812MINI-E",
                "LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount",
                SK6812, symbol_id="pcbsmith:SK6812MINI-E-verified",
            )
        )

    resistor_values = {
        "R1": ("cc1_rd", "5.1k"),
        "R2": ("cc2_rd", "5.1k"),
        "R3": ("usb_dm_series", "22R"),
        "R4": ("usb_dp_series", "22R"),
        "R5": ("reset_pullup", "10k"),
        "R6": ("hwb_pulldown", "10k"),
        "R7": ("rgb_data_damping", "330R"),
        "R8": ("encoder_a_pullup", "10k"),
        "R9": ("encoder_b_pullup", "10k"),
        "R10": ("encoder_switch_pullup", "10k"),
    }
    for reference, (role, value) in resistor_values.items():
        evidence = ATMEGA if reference in ("R3", "R4") else _engineering(role, value)
        parts.append(_part(reference, role, value, R0603, evidence, symbol_id="stdlib:R"))

    capacitor_values = {
        "C1": ("crystal_load", "22pF", C0603),
        "C2": ("crystal_load", "22pF", C0603),
        "C3": ("ucap_stabilizer", "1uF", C0805),
        "C4": ("aref_bypass", "100nF", C0603),
        "C5": ("uvcc_bypass", "100nF", C0603),
        "C6": ("vcc_bypass", "100nF", C0603),
        "C7": ("avcc_bypass", "100nF", C0603),
        "C8": ("vcc_bypass", "100nF", C0603),
        "C9": ("mcu_bulk", "10uF", C0805),
        "C10": ("rgb_local_bypass", "100nF", C0603),
        "C11": ("rgb_local_bypass", "100nF", C0603),
        "C12": ("rgb_local_bypass", "100nF", C0603),
        "C13": ("rgb_local_bypass", "100nF", C0603),
        "C14": ("rgb_bulk", "100uF", "Capacitor_SMD:CP_Elec_6.3x5.8"),
        "C15": ("encoder_a_debounce", "10nF", C0603),
        "C16": ("encoder_b_debounce", "10nF", C0603),
        "C17": ("encoder_switch_debounce", "10nF", C0603),
    }
    for reference, (role, value, footprint) in capacitor_values.items():
        evidence = ATMEGA if reference in ("C1", "C2", "C3") else _engineering(role, value)
        parts.append(_part(reference, role, value, footprint, evidence, symbol_id="stdlib:C"))

    nets = (
        "VBUS_RAW", "VCC", "GND", "CC1", "CC2",
        "USB_DM_CONN", "USB_DP_CONN", "USB_DM_PROTECTED", "USB_DP_PROTECTED",
        "USB_DM_MCU", "USB_DP_MCU", "UCAP", "AREF", "RESET", "HWB",
        "XTAL1", "XTAL2", "ROW0", "ROW1", "COL0", "COL1",
        "KEY1_D", "KEY2_D", "KEY3_D", "KEY4_D",
        "ENC_A", "ENC_B", "ENC_SW", "LED_DATA_MCU", "LED_DATA_1",
        "LED_LINK_1", "LED_LINK_2", "LED_LINK_3", "LED_LINK_END",
        "MOSI", "MISO", "SCK",
    )
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=tuple(parts),
        nets=nets,
        math=MathReport(
            status="warning",
            calculations={
                "vbus_v": 5.0,
                "rgb_full_white_current_ma": 4.0 * 3.0 * 12.0,
                "rgb_current_at_25_percent_ma": 4.0 * 3.0 * 12.0 * 0.25,
                "firmware_global_brightness_max_8bit": 64.0,
                "crystal_load_capacitor_pf": 22.0,
                "usb_series_resistance_ohm": 22.0,
            },
            findings=(
                "FIRMWARE CONTRACT: enumerate as a USB HID keyboard, debounce keys and "
                "encoder, scan ROW0/ROW1 one-low-at-a-time, and cap global RGB brightness "
                "at 64/255 unless a higher current budget is deliberately accepted.",
                "The RGB hardware can draw about 144 mA at full white before MCU current; "
                "the requested <150 mA is therefore a normal-mode target, not an absolute maximum.",
                "Program clock fuses for the 16 MHz external crystal and retain ISP access "
                "until the USB bootloader is verified.",
            ),
        ),
    )
