from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pcbsmith.core.geom import Point


class PinElectricalType(StrEnum):
    PASSIVE = "passive"
    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    POWER_IN = "power_in"
    POWER_OUT = "power_out"
    NO_CONNECT = "no_connect"


class PadShape(StrEnum):
    RECT = "rect"
    ROUND = "round"
    OVAL = "oval"
    CIRCLE = "circle"


class Pin(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: str
    name: str
    position: Point
    electrical_type: PinElectricalType = PinElectricalType.PASSIVE


class Symbol(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    pins: tuple[Pin, ...] = ()
    default_footprint_id: str | None = None

    @field_validator("pins")
    @classmethod
    def pin_numbers_are_unique(cls, pins: tuple[Pin, ...]) -> tuple[Pin, ...]:
        numbers = [pin.number for pin in pins]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Symbol pin numbers must be unique")
        return pins

    def pin_by_number(self, number: str) -> Pin:
        for pin in self.pins:
            if pin.number == number:
                return pin
        raise KeyError(f"Symbol {self.id!r} has no pin {number!r}")


class Pad(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: str
    position: Point
    size_x: int = Field(gt=0)
    size_y: int = Field(gt=0)
    shape: PadShape = PadShape.RECT
    drill: int | None = Field(default=None, gt=0)


class Footprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    pads: tuple[Pad, ...] = ()

    @field_validator("pads")
    @classmethod
    def pad_numbers_are_unique(cls, pads: tuple[Pad, ...]) -> tuple[Pad, ...]:
        numbers = [pad.number for pad in pads]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Footprint pad numbers must be unique")
        return pads

    def pad_by_number(self, number: str) -> Pad:
        for pad in self.pads:
            if pad.number == number:
                return pad
        raise KeyError(f"Footprint {self.id!r} has no pad {number!r}")
