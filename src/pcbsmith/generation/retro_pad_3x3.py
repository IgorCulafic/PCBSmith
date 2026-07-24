"""Evidence-carrying circuit authority for the rectangular 3x3 Retro-Pad."""

from __future__ import annotations

from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    MathReport,
    TopologySelection,
)
from pcbsmith.generation.retro_pad import (
    ATMEGA,
    C0603,
    SK6812,
    USB4105,
    _engineering,
    _part,
    compose_retro_pad,
)

SUPPORTED_TOPOLOGY_ID = "retro_pad_usb_macro_keyboard_3x3"


def compose_retro_pad_3x3() -> CircuitObject:
    """Return the rectangular nine-key USB macro-pad circuit object."""
    base = compose_retro_pad()
    retained = tuple(
        component
        for component in base.components
        if component.reference in {
            "U1", "U2", "J1", "J2", "F1", "Y1",
            *(f"R{index}" for index in range(1, 11)),
            *(f"C{index}" for index in range(1, 10)),
        }
    )
    expanded = list(retained)
    for index in range(1, 10):
        expanded.extend(
            (
                _part(
                    f"SW{index}",
                    "mechanical_key_switch",
                    "Cherry MX compatible",
                    "Button_Switch_Keyboard:SW_Cherry_MX_1.00u_PCB",
                    _engineering(
                        "PCB-mount Cherry MX compatible switch",
                        "19.05 mm orthogonal key pitch on a rectangular board.",
                    ),
                    symbol_id="stdlib:SW_Push",
                ),
                _part(
                    f"D{index}",
                    "matrix_anti_ghosting_diode",
                    "1N4148W",
                    "Diode_SMD:D_SOD-123",
                    _engineering(
                        "COL-to-ROW matrix diode",
                        "Anode faces the switch/column; cathode faces the row.",
                    ),
                    symbol_id="stdlib:D",
                    supported=False,
                ),
            )
        )
    expanded.append(
        _part(
            "SW10",
            "rotary_encoder_with_push",
            "EC11E15244B2",
            "Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
            _engineering(
                "Alps EC11E with push switch",
                "Verify the ordered shaft length and detent/pulse option.",
            ),
            symbol_id="stdlib:RotaryEncoder_Switch",
            supported=False,
        )
    )
    for index in range(10, 19):
        expanded.append(
            _part(
                f"D{index}",
                "reverse_mount_addressable_rgb",
                "SK6812MINI-E",
                "LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount",
                SK6812,
                symbol_id="pcbsmith:SK6812MINI-E-verified",
            )
        )
    for index in range(10, 19):
        expanded.append(
            _part(
                f"C{index}",
                "rgb_local_bypass",
                "100nF",
                C0603,
                _engineering("RGB local bypass", "One 100 nF capacitor per pixel."),
                symbol_id="stdlib:C",
            )
        )
    expanded.append(
        _part(
            "C19",
            "rgb_bulk",
            "100uF",
            "Capacitor_SMD:CP_Elec_6.3x5.8",
            _engineering("RGB bulk capacitance", "Local 5 V LED-chain reservoir."),
            symbol_id="stdlib:C",
        )
    )
    for index, net in enumerate(("ENC_A", "ENC_B", "ENC_SW"), start=20):
        expanded.append(
            _part(
                f"C{index}",
                f"{net.lower()}_debounce",
                "10nF",
                C0603,
                _engineering("Encoder debounce", f"10 nF from {net} to ground."),
                symbol_id="stdlib:C",
            )
        )

    nets = (
        "VBUS_RAW", "VCC", "GND", "CC1", "CC2",
        "USB_DM_CONN", "USB_DP_CONN", "USB_DM_PROTECTED", "USB_DP_PROTECTED",
        "USB_DM_MCU", "USB_DP_MCU", "UCAP", "AREF", "RESET", "HWB",
        "XTAL1", "XTAL2",
        *(f"ROW{index}" for index in range(3)),
        *(f"COL{index}" for index in range(3)),
        *(f"KEY{index}_D" for index in range(1, 10)),
        "ENC_A", "ENC_B", "ENC_SW", "LED_DATA_MCU", "LED_DATA_1",
        *(f"LED_LINK_{index}" for index in range(1, 9)),
        "MOSI", "MISO", "SCK",
    )
    return CircuitObject(
        intent=CircuitIntent(
            raw_request=(
                "Rectangular Retro-Pad USB HID with a centered 3x3 key matrix "
                "and an upper-right EC11 encoder"
            ),
            intent_id=SUPPORTED_TOPOLOGY_ID,
            status="supported",
            assumptions={
                "vbus_v": 5.0,
                "usb_speed": "full-speed",
                "matrix_rows": 3.0,
                "matrix_columns": 3.0,
                "led_count": 9.0,
                "pcb_layers": 2.0,
                "board_width_mm": 120.0,
                "board_height_mm": 100.0,
            },
        ),
        topology=TopologySelection(
            topology_id=SUPPORTED_TOPOLOGY_ID,
            title="ATmega32U4 USB HID, 3x3 diode matrix, EC11, reverse RGB chain",
            status="selected",
            evidence=(*ATMEGA, *USB4105, *SK6812),
            warnings=(
                "Nine RGB pixels exceed a conservative USB current budget at full white; "
                "firmware must enforce the documented brightness ceiling.",
            ),
        ),
        components=tuple(expanded),
        nets=nets,
        math=MathReport(
            status="warning",
            calculations={
                "vbus_v": 5.0,
                "rgb_full_white_current_ma": 9.0 * 3.0 * 12.0,
                "rgb_current_at_25_percent_ma": 9.0 * 3.0 * 12.0 * 0.25,
                "firmware_global_brightness_max_8bit": 64.0,
                "key_pitch_mm": 19.05,
            },
            findings=(
                "Scan one matrix row low at a time and read all three columns with pull-ups.",
                "Cap global RGB brightness at 64/255 unless the USB power budget is revised.",
                "Keep ISP access until USB bootloader operation is verified.",
            ),
        ),
    )
