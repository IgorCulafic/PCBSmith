from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.geom import Point


class Layer(StrEnum):
    F_CU = "F.Cu"
    B_CU = "B.Cu"
    F_SILK = "F.SilkS"
    B_SILK = "B.SilkS"
    EDGE_CUTS = "Edge.Cuts"


class FootprintInstance(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference: str
    footprint_id: str
    position: Point
    rotation_deg: int = 0


class Trace(BaseModel):
    model_config = ConfigDict(frozen=True)

    net_name: str
    layer: Layer
    points: tuple[Point, ...] = Field(min_length=2)
    width: int


class Via(BaseModel):
    model_config = ConfigDict(frozen=True)

    net_name: str
    position: Point
    drill: int
    diameter: int


class Zone(BaseModel):
    model_config = ConfigDict(frozen=True)

    net_name: str
    layer: Layer
    outline: tuple[Point, ...] = Field(min_length=3)


class Board(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    footprints: tuple[FootprintInstance, ...] = ()
    traces: tuple[Trace, ...] = ()
    vias: tuple[Via, ...] = ()
    zones: tuple[Zone, ...] = ()
