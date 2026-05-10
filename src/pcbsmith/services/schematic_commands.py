from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import Schematic, SymbolInstance, Wire

_REFERENCE_PATTERN = re.compile(r"^([A-Z]+)([0-9]+)$")
_PREFIX_BY_SYMBOL = {
    "stdlib:R": "R",
    "stdlib:C": "C",
    "stdlib:D": "D",
    "stdlib:LED": "LED",
    "stdlib:SW_PUSH": "SW",
    "stdlib:SW_SPST": "SW",
    "stdlib:VCC": "PWR",
    "stdlib:GND": "PWR",
    "stdlib:CONN_01X02": "J",
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


SchematicCommand = PlaceSymbolCommand | AddWireCommand


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


def _next_reference(schematic: Schematic, symbol_id: str) -> str:
    prefix = _PREFIX_BY_SYMBOL.get(symbol_id, "U")
    used = [
        int(match.group(2))
        for symbol in schematic.symbols
        if (match := _REFERENCE_PATTERN.match(symbol.reference)) and match.group(1) == prefix
    ]
    return f"{prefix}{max(used, default=0) + 1}"


__all__ = [
    "AddWireCommand",
    "PlaceSymbolCommand",
    "SchematicCommand",
    "SchematicCommandResult",
    "apply_schematic_command",
]
