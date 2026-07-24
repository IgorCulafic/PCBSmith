from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.core.geom import Point


class SymbolInstance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    symbol_id: str
    value: str
    position: Point
    rotation_deg: int = 0
    footprint_id: str | None = None
    mirrored_x: bool = False


class Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    points: tuple[Point, ...] = Field(min_length=2)


class Junction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    position: Point


class NetLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    position: Point


class NoConnect(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    position: Point


class Schematic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    symbols: tuple[SymbolInstance, ...] = ()
    wires: tuple[Wire, ...] = ()
    junctions: tuple[Junction, ...] = ()
    labels: tuple[NetLabel, ...] = ()
    no_connects: tuple[NoConnect, ...] = ()

    @model_validator(mode="after")
    def references_are_unique(self) -> Schematic:
        references = [symbol.reference for symbol in self.symbols]
        if len(references) != len(set(references)):
            raise ValueError("Duplicate reference designator in schematic")
        return self
