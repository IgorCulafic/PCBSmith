from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Footprint, Pad, PadShape, Pin, PinElectricalType, Symbol


def _two_pin_symbol(
    *,
    id: str,
    name: str,
    default_footprint_id: str,
    pin_1: str = "A",
    pin_2: str = "B",
) -> Symbol:
    return Symbol(
        id=id,
        name=name,
        default_footprint_id=default_footprint_id,
        pins=[
            Pin(
                number="1",
                name=pin_1,
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name=pin_2,
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    )


def _two_pad_smd_footprint(
    *,
    id: str,
    name: str,
    pitch_mm: float,
    pad_x: int,
    pad_y: int,
) -> Footprint:
    return Footprint(
        id=id,
        name=name,
        pads=[
            Pad(
                number="1",
                position=Point.from_mm(-pitch_mm / 2, 0),
                size_x=pad_x,
                size_y=pad_y,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(pitch_mm / 2, 0),
                size_x=pad_x,
                size_y=pad_y,
                shape=PadShape.RECT,
            ),
        ],
    )


SYMBOLS: dict[str, Symbol] = {
    "stdlib:R": Symbol(
        id="stdlib:R",
        name="Resistor",
        default_footprint_id="stdlib:R_0603",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="B",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:C": Symbol(
        id="stdlib:C",
        name="Capacitor",
        default_footprint_id="stdlib:C_0603",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="B",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:LED": Symbol(
        id="stdlib:LED",
        name="LED",
        default_footprint_id="stdlib:LED_0603",
        pins=[
            Pin(
                number="1",
                name="K",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="A",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:D": Symbol(
        id="stdlib:D",
        name="Diode",
        default_footprint_id="stdlib:D_0603",
        pins=[
            Pin(
                number="1",
                name="K",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="A",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:SW_PUSH": Symbol(
        id="stdlib:SW_PUSH",
        name="Push Button",
        default_footprint_id="stdlib:SW_PUSH_TH",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="B",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:SW_SPST": Symbol(
        id="stdlib:SW_SPST",
        name="Switch SPST",
        default_footprint_id="stdlib:SW_SPST_TH",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="B",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:VCC": Symbol(
        id="stdlib:VCC",
        name="Power Flag VCC",
        pins=[
            Pin(
                number="1",
                name="VCC",
                position=Point(x=0, y=0),
                electrical_type=PinElectricalType.POWER_OUT,
            ),
        ],
    ),
    "stdlib:GND": Symbol(
        id="stdlib:GND",
        name="Power Flag GND",
        pins=[
            Pin(
                number="1",
                name="GND",
                position=Point(x=0, y=0),
                electrical_type=PinElectricalType.POWER_OUT,
            ),
        ],
    ),
    "stdlib:CONN_01X02": Symbol(
        id="stdlib:CONN_01X02",
        name="Connector 1x02",
        default_footprint_id="stdlib:PinHeader_1x02_P2.54mm",
        pins=[
            Pin(
                number="1",
                name="Pin_1",
                position=Point(x=0, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="Pin_2",
                position=Point(x=0, y=2_540_000),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:CONN_01X06": Symbol(
        id="stdlib:CONN_01X06",
        name="Connector 1x06",
        default_footprint_id="stdlib:PinHeader_1x06_P2.54mm",
        pins=tuple(
            Pin(
                number=str(number),
                name=f"Pin_{number}",
                position=Point(x=0, y=(number - 1) * 2_540_000),
                electrical_type=PinElectricalType.PASSIVE,
            )
            for number in range(1, 7)
        ),
    ),
    "stdlib:BATTERY_CELL": Symbol(
        id="stdlib:BATTERY_CELL",
        name="Battery Cell",
        default_footprint_id="stdlib:BATTERY_CR2032_SMD",
        pins=[
            Pin(
                number="1",
                name="+",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="-",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:D_ZENER": Symbol(
        id="stdlib:D_ZENER",
        name="Zener Diode",
        default_footprint_id="stdlib:D_ZENER_0603",
        pins=[
            Pin(
                number="1",
                name="K",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="A",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:L": Symbol(
        id="stdlib:L",
        name="Inductor",
        default_footprint_id="stdlib:L_0603",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="B",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:FUSE": Symbol(
        id="stdlib:FUSE",
        name="Fuse",
        default_footprint_id="stdlib:FUSE_0603",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="B",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:D_SCHOTTKY": _two_pin_symbol(
        id="stdlib:D_SCHOTTKY",
        name="Schottky Diode",
        default_footprint_id="stdlib:D_SOD323",
        pin_1="K",
        pin_2="A",
    ),
    "stdlib:CRYSTAL": _two_pin_symbol(
        id="stdlib:CRYSTAL",
        name="Crystal",
        default_footprint_id="stdlib:CRYSTAL_3225",
        pin_1="1",
        pin_2="2",
    ),
    "stdlib:LDR": Symbol(
        id="stdlib:LDR",
        name="Photoresistor",
        default_footprint_id="stdlib:LDR_TH",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point(x=-5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="B",
                position=Point(x=5_080_000, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:POT": Symbol(
        id="stdlib:POT",
        name="Potentiometer",
        default_footprint_id="stdlib:POT_3PIN",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point.from_mm(-5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="W",
                position=Point.from_mm(0, -5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="B",
                position=Point.from_mm(5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:NMOS": Symbol(
        id="stdlib:NMOS",
        name="N-channel MOSFET",
        default_footprint_id="stdlib:NMOS_POWER",
        pins=[
            Pin(
                number="1",
                name="G",
                position=Point.from_mm(-5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="D",
                position=Point.from_mm(5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="S",
                position=Point.from_mm(0, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:AMS1117": Symbol(
        id="stdlib:AMS1117",
        name="AMS1117 Linear Regulator",
        default_footprint_id="stdlib:SOT223_REG",
        pins=[
            Pin(
                number="1",
                name="GND",
                position=Point.from_mm(-5.08, -2.54),
                electrical_type=PinElectricalType.POWER_IN,
            ),
            Pin(
                number="2",
                name="OUT",
                position=Point.from_mm(5.08, 0),
                electrical_type=PinElectricalType.POWER_OUT,
            ),
            Pin(
                number="3",
                name="IN",
                position=Point.from_mm(-5.08, 2.54),
                electrical_type=PinElectricalType.POWER_IN,
            ),
        ],
    ),
    "stdlib:ATTINY85": Symbol(
        id="stdlib:ATTINY85",
        name="ATtiny85",
        default_footprint_id="stdlib:SOIC8",
        pins=[
            Pin(
                number="1",
                name="RESET/PB5",
                position=Point.from_mm(-7.62, 5.08),
                electrical_type=PinElectricalType.BIDIRECTIONAL,
            ),
            Pin(
                number="2",
                name="PB3",
                position=Point.from_mm(-7.62, 2.54),
                electrical_type=PinElectricalType.BIDIRECTIONAL,
            ),
            Pin(
                number="3",
                name="PB4",
                position=Point.from_mm(-7.62, 0),
                electrical_type=PinElectricalType.BIDIRECTIONAL,
            ),
            Pin(
                number="4",
                name="GND",
                position=Point.from_mm(-7.62, -2.54),
                electrical_type=PinElectricalType.POWER_IN,
            ),
            Pin(
                number="5",
                name="PB0",
                position=Point.from_mm(7.62, -2.54),
                electrical_type=PinElectricalType.BIDIRECTIONAL,
            ),
            Pin(
                number="6",
                name="PB1",
                position=Point.from_mm(7.62, 0),
                electrical_type=PinElectricalType.BIDIRECTIONAL,
            ),
            Pin(
                number="7",
                name="PB2",
                position=Point.from_mm(7.62, 2.54),
                electrical_type=PinElectricalType.BIDIRECTIONAL,
            ),
            Pin(
                number="8",
                name="VCC",
                position=Point.from_mm(7.62, 5.08),
                electrical_type=PinElectricalType.POWER_IN,
            ),
        ],
    ),
    "stdlib:NPN_BJT": Symbol(
        id="stdlib:NPN_BJT",
        name="NPN BJT",
        default_footprint_id="stdlib:BJT_SOT23",
        pins=[
            Pin(
                number="1",
                name="B",
                position=Point.from_mm(-5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="C",
                position=Point.from_mm(5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="E",
                position=Point.from_mm(0, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:PNP_BJT": Symbol(
        id="stdlib:PNP_BJT",
        name="PNP BJT",
        default_footprint_id="stdlib:BJT_SOT23",
        pins=[
            Pin(
                number="1",
                name="B",
                position=Point.from_mm(-5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="C",
                position=Point.from_mm(5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="E",
                position=Point.from_mm(0, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:BUZZER": Symbol(
        id="stdlib:BUZZER",
        name="Buzzer",
        default_footprint_id="stdlib:BUZZER_TH",
        pins=[
            Pin(
                number="1",
                name="+",
                position=Point.from_mm(-5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="-",
                position=Point.from_mm(5.08, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:LM393": Symbol(
        id="stdlib:LM393",
        name="LM393 Comparator",
        default_footprint_id="stdlib:SOIC8",
        pins=[
            Pin(
                number="1",
                name="OUT_A",
                position=Point.from_mm(-7.62, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="IN-_A",
                position=Point.from_mm(-7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="IN+_A",
                position=Point.from_mm(-7.62, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="4",
                name="GND",
                position=Point.from_mm(-7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="5",
                name="IN+_B",
                position=Point.from_mm(7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="6",
                name="IN-_B",
                position=Point.from_mm(7.62, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="7",
                name="OUT_B",
                position=Point.from_mm(7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="8",
                name="VCC",
                position=Point.from_mm(7.62, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:LM358": Symbol(
        id="stdlib:LM358",
        name="LM358 Op Amp",
        default_footprint_id="stdlib:SOIC8",
        pins=[
            Pin(
                number="1",
                name="OUT_A",
                position=Point.from_mm(-7.62, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="IN-_A",
                position=Point.from_mm(-7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="IN+_A",
                position=Point.from_mm(-7.62, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="4",
                name="GND",
                position=Point.from_mm(-7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="5",
                name="IN+_B",
                position=Point.from_mm(7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="6",
                name="IN-_B",
                position=Point.from_mm(7.62, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="7",
                name="OUT_B",
                position=Point.from_mm(7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="8",
                name="VCC",
                position=Point.from_mm(7.62, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:NE555": Symbol(
        id="stdlib:NE555",
        name="NE555 Timer",
        default_footprint_id="stdlib:SOIC8",
        pins=[
            Pin(
                number="1",
                name="GND",
                position=Point.from_mm(-7.62, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="TRIG",
                position=Point.from_mm(-7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="OUT",
                position=Point.from_mm(7.62, -5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="4",
                name="RESET",
                position=Point.from_mm(-7.62, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="5",
                name="CTRL",
                position=Point.from_mm(-7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="6",
                name="THRESH",
                position=Point.from_mm(7.62, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="7",
                name="DISCH",
                position=Point.from_mm(7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="8",
                name="VCC",
                position=Point.from_mm(7.62, 5.08),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:RELAY_SPDT": Symbol(
        id="stdlib:RELAY_SPDT",
        name="Relay SPDT",
        default_footprint_id="stdlib:RELAY_SPDT_TH",
        pins=[
            Pin(
                number="1",
                name="COIL_A",
                position=Point.from_mm(-7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="COIL_B",
                position=Point.from_mm(-7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="COM",
                position=Point.from_mm(7.62, 0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="4",
                name="NC",
                position=Point.from_mm(7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="5",
                name="NO",
                position=Point.from_mm(7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
    "stdlib:TRANSFORMER": Symbol(
        id="stdlib:TRANSFORMER",
        name="Transformer",
        default_footprint_id="stdlib:TRANSFORMER_TH",
        pins=[
            Pin(
                number="1",
                name="PRI_A",
                position=Point.from_mm(-7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="PRI_B",
                position=Point.from_mm(-7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="3",
                name="SEC_A",
                position=Point.from_mm(7.62, -2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="4",
                name="SEC_B",
                position=Point.from_mm(7.62, 2.54),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    ),
}

FOOTPRINTS: dict[str, Footprint] = {
    "stdlib:R_0603": Footprint(
        id="stdlib:R_0603",
        name="R_0603",
        pads=[
            Pad(
                number="1",
                position=Point(x=-800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point(x=800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ],
    ),
    "stdlib:C_0603": Footprint(
        id="stdlib:C_0603",
        name="C_0603",
        pads=[
            Pad(
                number="1",
                position=Point(x=-800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point(x=800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ],
    ),
    "stdlib:LED_0603": Footprint(
        id="stdlib:LED_0603",
        name="LED_0603",
        pads=[
            Pad(
                number="1",
                position=Point(x=-800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point(x=800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ],
    ),
    "stdlib:D_0603": Footprint(
        id="stdlib:D_0603",
        name="D_0603",
        pads=[
            Pad(
                number="1",
                position=Point(x=-800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point(x=800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ],
    ),
    "stdlib:D_ZENER_0603": Footprint(
        id="stdlib:D_ZENER_0603",
        name="D_ZENER_0603",
        pads=[
            Pad(
                number="1",
                position=Point(x=-800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point(x=800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ],
    ),
    "stdlib:L_0603": Footprint(
        id="stdlib:L_0603",
        name="L_0603",
        pads=[
            Pad(
                number="1",
                position=Point(x=-800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point(x=800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ],
    ),
    "stdlib:FUSE_0603": Footprint(
        id="stdlib:FUSE_0603",
        name="FUSE_0603",
        pads=[
            Pad(
                number="1",
                position=Point(x=-800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point(x=800_000, y=0),
                size_x=800_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ],
    ),
    "stdlib:R_0805": _two_pad_smd_footprint(
        id="stdlib:R_0805",
        name="R_0805",
        pitch_mm=2.0,
        pad_x=1_200_000,
        pad_y=1_400_000,
    ),
    "stdlib:C_0805": _two_pad_smd_footprint(
        id="stdlib:C_0805",
        name="C_0805",
        pitch_mm=2.0,
        pad_x=1_180_000,
        pad_y=1_450_000,
    ),
    "stdlib:LED_0805": _two_pad_smd_footprint(
        id="stdlib:LED_0805",
        name="LED_0805",
        pitch_mm=2.0,
        pad_x=1_150_000,
        pad_y=1_400_000,
    ),
    "stdlib:D_SOD323": _two_pad_smd_footprint(
        id="stdlib:D_SOD323",
        name="D_SOD323",
        pitch_mm=2.4,
        pad_x=900_000,
        pad_y=1_000_000,
    ),
    "stdlib:CRYSTAL_3225": Footprint(
        id="stdlib:CRYSTAL_3225",
        name="CRYSTAL_3225",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-1.2, 0),
                size_x=1_000_000,
                size_y=1_400_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(1.2, 0),
                size_x=1_000_000,
                size_y=1_400_000,
                shape=PadShape.RECT,
            ),
        ),
    ),
    "stdlib:LDR_TH": Footprint(
        id="stdlib:LDR_TH",
        name="LDR_TH",
        pads=[
            Pad(
                number="1",
                position=Point.from_mm(-2.54, 0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=900_000,
            ),
            Pad(
                number="2",
                position=Point.from_mm(2.54, 0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=900_000,
            ),
        ],
    ),
    "stdlib:SW_PUSH_TH": Footprint(
        id="stdlib:SW_PUSH_TH",
        name="SW_PUSH_TH",
        pads=[
            Pad(
                number="1",
                position=Point(x=-2_540_000, y=0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
            Pad(
                number="2",
                position=Point(x=2_540_000, y=0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
        ],
    ),
    "stdlib:SW_PUSH_SMD": Footprint(
        id="stdlib:SW_PUSH_SMD",
        name="SW_PUSH_SMD",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-2.25, 0),
                size_x=1_500_000,
                size_y=1_800_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(2.25, 0),
                size_x=1_500_000,
                size_y=1_800_000,
                shape=PadShape.RECT,
            ),
        ),
    ),
    "stdlib:SW_SPST_TH": Footprint(
        id="stdlib:SW_SPST_TH",
        name="SW_SPST_TH",
        pads=[
            Pad(
                number="1",
                position=Point(x=-2_540_000, y=0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
            Pad(
                number="2",
                position=Point(x=2_540_000, y=0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
        ],
    ),
    "stdlib:PinHeader_1x02_P2.54mm": Footprint(
        id="stdlib:PinHeader_1x02_P2.54mm",
        name="PinHeader_1x02_P2.54mm",
        pads=[
            Pad(
                number="1",
                position=Point(x=0, y=0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
            Pad(
                number="2",
                position=Point(x=0, y=2_540_000),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
        ],
    ),
    "stdlib:PinHeader_1x06_P2.54mm": Footprint(
        id="stdlib:PinHeader_1x06_P2.54mm",
        name="PinHeader_1x06_P2.54mm",
        pads=tuple(
            Pad(
                number=str(number),
                position=Point(x=0, y=(number - 1) * 2_540_000),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            )
            for number in range(1, 7)
        ),
    ),
    "stdlib:SOIC8": Footprint(
        id="stdlib:SOIC8",
        name="SOIC8",
        pads=tuple(
            Pad(
                number=str(number),
                position=Point.from_mm(x_mm, y_mm),
                size_x=700_000,
                size_y=1_200_000,
                shape=PadShape.RECT,
            )
            for number, x_mm, y_mm in (
                (1, -3.0, -1.425),
                (2, -3.0, -0.475),
                (3, -3.0, 0.475),
                (4, -3.0, 1.425),
                (5, 3.0, 1.425),
                (6, 3.0, 0.475),
                (7, 3.0, -0.475),
                (8, 3.0, -1.425),
            )
        ),
    ),
    "stdlib:POT_3PIN": Footprint(
        id="stdlib:POT_3PIN",
        name="POT_3PIN",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-2.54, 1.7),
                size_x=1_400_000,
                size_y=1_400_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(0, 1.7),
                size_x=1_400_000,
                size_y=1_400_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="3",
                position=Point.from_mm(2.54, 1.7),
                size_x=1_400_000,
                size_y=1_400_000,
                shape=PadShape.RECT,
            ),
        ),
    ),
    "stdlib:POT_3PIN_TH": Footprint(
        id="stdlib:POT_3PIN_TH",
        name="POT_3PIN_TH",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-2.54, 0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
            Pad(
                number="2",
                position=Point.from_mm(0, 0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
            Pad(
                number="3",
                position=Point.from_mm(2.54, 0),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
        ),
    ),
    "stdlib:NMOS_SOT23": Footprint(
        id="stdlib:NMOS_SOT23",
        name="NMOS_SOT23",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-0.95, 1.1),
                size_x=700_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(0.95, 1.1),
                size_x=700_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="3",
                position=Point.from_mm(0, -1.1),
                size_x=900_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ),
    ),
    "stdlib:BJT_SOT23": Footprint(
        id="stdlib:BJT_SOT23",
        name="BJT_SOT23",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-0.95, 1.1),
                size_x=700_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(0.95, 1.1),
                size_x=700_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="3",
                position=Point.from_mm(0, -1.1),
                size_x=900_000,
                size_y=900_000,
                shape=PadShape.RECT,
            ),
        ),
    ),
    "stdlib:BUZZER_TH": Footprint(
        id="stdlib:BUZZER_TH",
        name="BUZZER_TH",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-3.8, 0),
                size_x=1_900_000,
                size_y=1_900_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
            Pad(
                number="2",
                position=Point.from_mm(3.8, 0),
                size_x=1_900_000,
                size_y=1_900_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            ),
        ),
    ),
    "stdlib:TerminalBlock_1x02_P5.00mm": Footprint(
        id="stdlib:TerminalBlock_1x02_P5.00mm",
        name="TerminalBlock_1x02_P5.00mm",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(0, 0),
                size_x=2_000_000,
                size_y=2_000_000,
                shape=PadShape.CIRCLE,
                drill=1_100_000,
            ),
            Pad(
                number="2",
                position=Point.from_mm(5, 0),
                size_x=2_000_000,
                size_y=2_000_000,
                shape=PadShape.CIRCLE,
                drill=1_100_000,
            ),
        ),
    ),
    "stdlib:NMOS_POWER": Footprint(
        id="stdlib:NMOS_POWER",
        name="NMOS_POWER",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-2, 1.3),
                size_x=1_200_000,
                size_y=1_400_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(0, -1.5),
                size_x=3_000_000,
                size_y=1_700_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="3",
                position=Point.from_mm(2, 1.3),
                size_x=1_400_000,
                size_y=1_400_000,
                shape=PadShape.RECT,
            ),
        ),
    ),
    "stdlib:SOT223_REG": Footprint(
        id="stdlib:SOT223_REG",
        name="SOT223_REG",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-2.3, 3.15),
                size_x=1_200_000,
                size_y=1_700_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(0, -3.15),
                size_x=3_300_000,
                size_y=2_000_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="3",
                position=Point.from_mm(2.3, 3.15),
                size_x=1_200_000,
                size_y=1_700_000,
                shape=PadShape.RECT,
            ),
        ),
    ),
    "stdlib:BATTERY_CR2032_SMD": Footprint(
        id="stdlib:BATTERY_CR2032_SMD",
        name="BATTERY_CR2032_SMD",
        pads=(
            Pad(
                number="1",
                position=Point.from_mm(-6, 0),
                size_x=3_000_000,
                size_y=4_000_000,
                shape=PadShape.RECT,
            ),
            Pad(
                number="2",
                position=Point.from_mm(6, 0),
                size_x=3_000_000,
                size_y=4_000_000,
                shape=PadShape.RECT,
            ),
        ),
    ),
    "stdlib:RELAY_SPDT_TH": Footprint(
        id="stdlib:RELAY_SPDT_TH",
        name="RELAY_SPDT_TH",
        pads=tuple(
            Pad(
                number=str(number),
                position=Point.from_mm(x_mm, y_mm),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            )
            for number, x_mm, y_mm in (
                (1, -5.08, -2.54),
                (2, -5.08, 2.54),
                (3, 5.08, 0),
                (4, 5.08, -2.54),
                (5, 5.08, 2.54),
            )
        ),
    ),
    "stdlib:TRANSFORMER_TH": Footprint(
        id="stdlib:TRANSFORMER_TH",
        name="TRANSFORMER_TH",
        pads=tuple(
            Pad(
                number=str(number),
                position=Point.from_mm(x_mm, y_mm),
                size_x=1_700_000,
                size_y=1_700_000,
                shape=PadShape.CIRCLE,
                drill=1_000_000,
            )
            for number, x_mm, y_mm in (
                (1, -5.08, -2.54),
                (2, -5.08, 2.54),
                (3, 5.08, -2.54),
                (4, 5.08, 2.54),
            )
        ),
    ),
}


def get_symbol(symbol_id: str) -> Symbol:
    return SYMBOLS[symbol_id]


def get_footprint(footprint_id: str) -> Footprint:
    return FOOTPRINTS[footprint_id]
