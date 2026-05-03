from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.core.geom import Point
from pcbsmith.core.library import (
    Footprint,
    Pad,
    PadShape,
    Pin,
    PinElectricalType,
    Symbol,
)


def test_symbol_pin_lookup_by_number() -> None:
    symbol = Symbol(
        id="stdlib:R",
        name="Resistor",
        pins=[
            Pin(number="1", name="A", position=Point(x=0, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="B", position=Point(x=10, y=0), electrical_type=PinElectricalType.PASSIVE),
        ],
    )
    assert symbol.pin_by_number("2").name == "B"


def test_symbol_rejects_duplicate_pin_numbers() -> None:
    with pytest.raises(ValidationError):
        Symbol(
            id="bad:dup",
            name="Bad",
            pins=[
                Pin(number="1", name="A", position=Point(x=0, y=0), electrical_type=PinElectricalType.PASSIVE),
                Pin(number="1", name="B", position=Point(x=1, y=0), electrical_type=PinElectricalType.PASSIVE),
            ],
        )


def test_footprint_pad_lookup_by_number() -> None:
    footprint = Footprint(
        id="stdlib:R_0603",
        name="R_0603",
        pads=[
            Pad(number="1", position=Point(x=-500_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
            Pad(number="2", position=Point(x=500_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
        ],
    )
    assert footprint.pad_by_number("1").position.x == -500_000
