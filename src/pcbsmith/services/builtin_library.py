from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Footprint, Pad, PadShape, Pin, PinElectricalType, Symbol

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
}


def get_symbol(symbol_id: str) -> Symbol:
    return SYMBOLS[symbol_id]


def get_footprint(footprint_id: str) -> Footprint:
    return FOOTPRINTS[footprint_id]
