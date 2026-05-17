from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.core.board import Board, BoardText, Layer, Trace
from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire

_REFERENCE_PATTERN = re.compile(r"^([A-Z]+)([0-9]+)$")
_PREFIX_BY_SYMBOL = {
    "stdlib:R": "R",
    "stdlib:C": "C",
    "stdlib:D": "D",
    "stdlib:D_ZENER": "D",
    "stdlib:L": "L",
    "stdlib:FUSE": "F",
    "stdlib:LDR": "R",
    "stdlib:LED": "LED",
    "stdlib:SW_PUSH": "SW",
    "stdlib:SW_SPST": "SW",
    "stdlib:VCC": "PWR",
    "stdlib:GND": "PWR",
    "stdlib:CONN_01X02": "J",
    "stdlib:POT": "RV",
    "stdlib:NMOS": "Q",
    "stdlib:NE555": "U",
    "stdlib:RELAY_SPDT": "K",
    "stdlib:TRANSFORMER": "T",
}


class PlaceSymbolCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["place_symbol"] = "place_symbol"
    symbol_id: str
    value: str
    position: Point
    rotation_deg: int = 0
    footprint_id: str | None = None


class AddWireCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["add_wire"] = "add_wire"
    points: tuple[Point, ...] = Field(min_length=2)


class AddLabelCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["add_label"] = "add_label"
    name: str
    position: Point


class RouteSegmentCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["route_segment"] = "route_segment"
    net_name: str
    layer: Layer
    points: tuple[Point, ...] = Field(min_length=2)
    width: int = Field(gt=0)

    @model_validator(mode="after")
    def only_front_copper_for_now(self) -> RouteSegmentCommand:
        if self.layer != Layer.F_CU:
            raise ValueError(f"{self.layer} routing is not enabled yet")
        return self


class PlaceTextCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["place_text"] = "place_text"
    text: str
    layer: Layer
    position: Point
    rotation_deg: int = 0
    size: int = Field(default=1_500_000, gt=0)
    thickness: int = Field(default=150_000, gt=0)

    @model_validator(mode="after")
    def only_silkscreen_text_for_now(self) -> PlaceTextCommand:
        if self.layer not in {Layer.F_SILK, Layer.B_SILK}:
            raise ValueError(f"{self.layer} text is not enabled yet")
        return self


SchematicCommand = PlaceSymbolCommand | AddWireCommand | AddLabelCommand
BoardCommand = RouteSegmentCommand | PlaceTextCommand
PlanCommand = SchematicCommand | BoardCommand


class SchematicCommandResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schematic: Schematic
    messages: tuple[str, ...] = ()


def apply_schematic_command(
    schematic: Schematic,
    command: SchematicCommand,
) -> SchematicCommandResult:
    if isinstance(command, PlaceSymbolCommand):
        return _place_symbol(schematic, command)
    if isinstance(command, AddWireCommand):
        return _add_wire(schematic, command)
    if isinstance(command, AddLabelCommand):
        return _add_label(schematic, command)


def apply_board_command(
    board: Board,
    command: BoardCommand,
) -> Board:
    if isinstance(command, RouteSegmentCommand):
        trace = Trace(
            net_name=command.net_name,
            layer=command.layer,
            points=command.points,
            width=command.width,
        )
        return board.model_copy(update={"traces": (*board.traces, trace)})
    if isinstance(command, PlaceTextCommand):
        text = BoardText(
            text=command.text,
            layer=command.layer,
            position=command.position,
            rotation_deg=command.rotation_deg,
            size=command.size,
            thickness=command.thickness,
        )
        return board.model_copy(update={"texts": (*board.texts, text)})


def _place_symbol(
    schematic: Schematic,
    command: PlaceSymbolCommand,
) -> SchematicCommandResult:
    reference = _next_reference(schematic, command.symbol_id)
    symbol = SymbolInstance(
        reference=reference,
        symbol_id=command.symbol_id,
        value=command.value,
        position=command.position,
        rotation_deg=command.rotation_deg,
        footprint_id=command.footprint_id,
    )
    updated = schematic.model_copy(update={"symbols": (*schematic.symbols, symbol)})
    return SchematicCommandResult(schematic=updated, messages=(f"Placed {reference}",))


def _add_wire(schematic: Schematic, command: AddWireCommand) -> SchematicCommandResult:
    wire = Wire(points=command.points)
    updated = schematic.model_copy(update={"wires": (*schematic.wires, wire)})
    return SchematicCommandResult(
        schematic=updated,
        messages=(f"Added wire with {len(command.points)} points",),
    )


def _add_label(schematic: Schematic, command: AddLabelCommand) -> SchematicCommandResult:
    label = NetLabel(name=command.name, position=command.position)
    updated = schematic.model_copy(update={"labels": (*schematic.labels, label)})
    return SchematicCommandResult(
        schematic=updated,
        messages=(f"Added label {command.name}",),
    )


def _next_reference(schematic: Schematic, symbol_id: str) -> str:
    prefix = _PREFIX_BY_SYMBOL.get(symbol_id, "U")
    used = [
        int(match.group(2))
        for symbol in schematic.symbols
        if (match := _REFERENCE_PATTERN.match(symbol.reference)) and match.group(1) == prefix
    ]
    return f"{prefix}{max(used, default=0) + 1}"


__all__ = [
    "AddLabelCommand",
    "AddWireCommand",
    "BoardCommand",
    "PlaceSymbolCommand",
    "PlaceTextCommand",
    "PlanCommand",
    "RouteSegmentCommand",
    "SchematicCommand",
    "SchematicCommandResult",
    "apply_board_command",
    "apply_schematic_command",
]
