"""Readable schematic authority for the rectangular 3x3 Retro-Pad."""

from __future__ import annotations

from pcbsmith.kicad.export_retro_pad import (
    ATMEGA,
    CAPACITOR,
    CONN4,
    CONN6,
    CRYSTAL,
    DIODE,
    ENCODER,
    J1_PIN_NETS,
    POLYFUSE,
    RESISTOR,
    SWITCH,
    USB_C,
    USB_ESD,
    SchematicInstance,
)

U1_PIN_NETS_3X3 = {
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
    "20": "ROW2",
    "21": "COL0",
    "23": "GND",
    "24": "VCC",
    "25": "ENC_A",
    "26": "ENC_B",
    "27": "ENC_SW",
    "28": "COL1",
    "29": "COL2",
    "33": "HWB",
    "34": "VCC",
    "35": "GND",
    "42": "AREF",
    "43": "GND",
    "44": "VCC",
}

NO_CONNECTS_3X3: dict[str, tuple[str, ...]] = {
    "J1": ("A8", "B8"),
    "U1": (
        "8", "12", "22", "30", "31", "32",
        "36", "37", "38", "39", "40", "41",
    ),
    "D18": ("2",),
}


def retro_pad_3x3_schematic_instances() -> tuple[SchematicInstance, ...]:
    instances: list[SchematicInstance] = [
        ("J1", USB_C, 35.56, 50.80, J1_PIN_NETS),
        (
            "U2", USB_ESD, 78.74, 50.80,
            {
                "1": "USB_DP_CONN", "6": "USB_DP_PROTECTED",
                "3": "USB_DM_CONN", "4": "USB_DM_PROTECTED",
                "2": "GND", "5": "VCC",
            },
        ),
        ("R3", RESISTOR, 104.14, 43.18, {"1": "USB_DM_PROTECTED", "2": "USB_DM_MCU"}),
        ("R4", RESISTOR, 104.14, 58.42, {"1": "USB_DP_PROTECTED", "2": "USB_DP_MCU"}),
        ("F1", POLYFUSE, 132.08, 50.80, {"1": "VBUS_RAW", "2": "VCC"}),
        ("U1", ATMEGA, 193.04, 50.80, U1_PIN_NETS_3X3),
        ("Y1", CRYSTAL, 251.46, 50.80, {"1": "XTAL1", "2": "GND", "3": "XTAL2", "4": "GND"}),
        (
            "J2", CONN6, 294.64, 50.80,
            {"1": "MISO", "2": "VCC", "3": "SCK", "4": "MOSI", "5": "RESET", "6": "GND"},
        ),
        (
            "SW10", ENCODER, 330.20, 96.52,
            {"A": "ENC_A", "B": "ENC_B", "C": "GND", "S1": "GND", "S2": "ENC_SW"},
        ),
    ]

    for row in range(3):
        for column in range(3):
            index = row * 3 + column + 1
            x = 40.64 + column * 101.60
            y = 127.00 + row * 35.56
            intermediate = f"KEY{index}_D"
            instances.append(
                (f"SW{index}", SWITCH, x, y, {"1": f"COL{column}", "2": intermediate})
            )
            instances.append(
                (f"D{index}", DIODE, x + 27.94, y, {"2": intermediate, "1": f"ROW{row}"})
            )

    led_inputs = ("LED_DATA_1", *(f"LED_LINK_{index}" for index in range(1, 9)))
    led_outputs = (*(f"LED_LINK_{index}" for index in range(1, 9)), None)
    for offset, index in enumerate(range(10, 19)):
        row, column = divmod(offset, 3)
        pins = {"1": "VCC", "3": "GND", "4": led_inputs[offset]}
        led_output = led_outputs[offset]
        if led_output is not None:
            pins["2"] = led_output
        instances.append(
            (f"D{index}", CONN4, 40.64 + column * 101.60, 246.38 + row * 27.94, pins)
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
        *( (f"C{index}", CAPACITOR, {"1": "VCC", "2": "GND"}) for index in range(5, 20) ),
        ("C20", CAPACITOR, {"1": "ENC_A", "2": "GND"}),
        ("C21", CAPACITOR, {"1": "ENC_B", "2": "GND"}),
        ("C22", CAPACITOR, {"1": "ENC_SW", "2": "GND"}),
    )
    for offset, (reference, lib_id, pins) in enumerate(support_defs):
        row, column = divmod(offset, 10)
        instances.append(
            (reference, lib_id, 30.48 + column * 33.02, 342.90 + row * 30.48, pins)
        )
    return tuple(instances)


RETRO_PAD_3X3_SCHEMATIC_INSTANCES = retro_pad_3x3_schematic_instances()
