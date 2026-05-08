from __future__ import annotations

import re
from dataclasses import dataclass, replace

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import Junction, NetLabel, NoConnect, Schematic, SymbolInstance, Wire

_REFERENCE_PATTERN = re.compile(r"^([A-Z]+)([0-9]+)$")
_PREFIX_BY_SYMBOL = {
    "stdlib:R": "R",
    "stdlib:C": "C",
    "stdlib:LED": "LED",
    "stdlib:VCC": "PWR",
    "stdlib:GND": "PWR",
    "stdlib:CONN_01X02": "J",
}


@dataclass(frozen=True)
class EditorState:
    schematic_id: str
    symbols: tuple[SymbolInstance, ...] = ()
    wires: tuple[Wire, ...] = ()
    junctions: tuple[Junction, ...] = ()
    labels: tuple[NetLabel, ...] = ()
    no_connects: tuple[NoConnect, ...] = ()

    @classmethod
    def blank(cls, schematic_id: str) -> EditorState:
        return cls(schematic_id=schematic_id)

    @classmethod
    def from_schematic(cls, schematic: Schematic) -> EditorState:
        return cls(
            schematic_id=schematic.id,
            symbols=tuple(schematic.symbols),
            wires=tuple(schematic.wires),
            junctions=tuple(schematic.junctions),
            labels=tuple(schematic.labels),
            no_connects=tuple(schematic.no_connects),
        )

    def place_symbol(
        self,
        symbol_id: str,
        value: str,
        position: Point,
        rotation_deg: int = 0,
        footprint_id: str | None = None,
    ) -> EditorState:
        symbol = SymbolInstance(
            reference=self._next_reference(symbol_id),
            symbol_id=symbol_id,
            value=value,
            position=position,
            rotation_deg=rotation_deg,
            footprint_id=footprint_id,
        )
        return replace(self, symbols=(*self.symbols, symbol))

    def add_wire(self, points: tuple[Point, ...]) -> EditorState:
        return replace(self, wires=(*self.wires, Wire(points=points)))

    def to_schematic(self) -> Schematic:
        return Schematic(
            id=self.schematic_id,
            symbols=self.symbols,
            wires=self.wires,
            junctions=self.junctions,
            labels=self.labels,
            no_connects=self.no_connects,
        )

    def _next_reference(self, symbol_id: str) -> str:
        prefix = _PREFIX_BY_SYMBOL.get(symbol_id, "U")
        used = [
            int(match.group(2))
            for symbol in self.symbols
            if (match := _REFERENCE_PATTERN.match(symbol.reference)) and match.group(1) == prefix
        ]
        return f"{prefix}{max(used, default=0) + 1}"
