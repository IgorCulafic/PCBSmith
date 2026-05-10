from __future__ import annotations

import re
from dataclasses import dataclass, replace

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import Junction, NetLabel, NoConnect, Schematic, SymbolInstance, Wire
from pcbsmith.ui.selection import SelectionKey, parse_index_key

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

    def move_item(self, selection: SelectionKey, position: Point) -> EditorState:
        if selection.kind == "symbol":
            symbols = []
            found = False
            for symbol in self.symbols:
                if symbol.reference == selection.key:
                    found = True
                    symbols.append(symbol.model_copy(update={"position": position}))
                else:
                    symbols.append(symbol)
            if not found:
                raise ValueError(f"Unknown symbol reference: {selection.key}")
            return replace(self, symbols=tuple(symbols))

        if selection.kind == "label":
            index = self._validated_index(selection, len(self.labels))
            labels = list(self.labels)
            labels[index] = labels[index].model_copy(update={"position": position})
            return replace(self, labels=tuple(labels))

        if selection.kind == "no_connect":
            index = self._validated_index(selection, len(self.no_connects))
            no_connects = list(self.no_connects)
            no_connects[index] = no_connects[index].model_copy(update={"position": position})
            return replace(self, no_connects=tuple(no_connects))

        raise ValueError(f"Cannot move {selection.kind}")

    def delete_item(self, selection: SelectionKey) -> EditorState:
        if selection.kind == "symbol":
            if not any(symbol.reference == selection.key for symbol in self.symbols):
                raise ValueError(f"Unknown symbol reference: {selection.key}")
            return replace(
                self,
                symbols=tuple(
                    symbol for symbol in self.symbols if symbol.reference != selection.key
                ),
            )

        if selection.kind == "wire":
            index = self._validated_index(selection, len(self.wires))
            return replace(
                self,
                wires=tuple(
                    wire for item_index, wire in enumerate(self.wires) if item_index != index
                ),
            )

        if selection.kind == "label":
            index = self._validated_index(selection, len(self.labels))
            return replace(
                self,
                labels=tuple(
                    label for item_index, label in enumerate(self.labels) if item_index != index
                ),
            )

        if selection.kind == "no_connect":
            index = self._validated_index(selection, len(self.no_connects))
            return replace(
                self,
                no_connects=tuple(
                    marker
                    for item_index, marker in enumerate(self.no_connects)
                    if item_index != index
                ),
            )

        raise ValueError(f"Unknown selection kind: {selection.kind}")

    def rotate_symbol(self, reference: str, delta_deg: int) -> EditorState:
        symbols = []
        found = False
        for symbol in self.symbols:
            if symbol.reference == reference:
                found = True
                symbols.append(
                    symbol.model_copy(
                        update={"rotation_deg": (symbol.rotation_deg + delta_deg) % 360}
                    )
                )
            else:
                symbols.append(symbol)
        if not found:
            raise ValueError(f"Unknown symbol reference: {reference}")
        return replace(self, symbols=tuple(symbols))

    def mirror_symbol_horizontally(self, reference: str) -> EditorState:
        symbols = []
        found = False
        for symbol in self.symbols:
            if symbol.reference == reference:
                found = True
                symbols.append(
                    symbol.model_copy(update={"mirrored_x": not symbol.mirrored_x})
                )
            else:
                symbols.append(symbol)
        if not found:
            raise ValueError(f"Unknown symbol reference: {reference}")
        return replace(self, symbols=tuple(symbols))

    def update_symbol(
        self,
        reference: str,
        *,
        new_reference: str | None = None,
        value: str | None = None,
        rotation_deg: int | None = None,
        footprint_id: str | None = None,
    ) -> EditorState:
        replacement_reference = new_reference or reference
        if replacement_reference != reference and any(
            symbol.reference == replacement_reference for symbol in self.symbols
        ):
            raise ValueError(f"Duplicate reference designator: {replacement_reference}")

        symbols = []
        found = False
        for symbol in self.symbols:
            if symbol.reference == reference:
                found = True
                updates: dict[str, object] = {"reference": replacement_reference}
                if value is not None:
                    updates["value"] = value
                if rotation_deg is not None:
                    updates["rotation_deg"] = rotation_deg
                if footprint_id is not None:
                    updates["footprint_id"] = footprint_id or None
                symbols.append(symbol.model_copy(update=updates))
            else:
                symbols.append(symbol)
        if not found:
            raise ValueError(f"Unknown symbol reference: {reference}")
        return replace(self, symbols=tuple(symbols))

    def add_label(self, name: str, position: Point) -> EditorState:
        if not name.strip():
            raise ValueError("Net label cannot be empty")
        return replace(self, labels=(*self.labels, NetLabel(name=name.strip(), position=position)))

    def update_label(
        self,
        index: int,
        *,
        name: str | None = None,
        position: Point | None = None,
    ) -> EditorState:
        if index < 0 or index >= len(self.labels):
            raise ValueError(f"Unknown label index: {index}")

        updates: dict[str, object] = {}
        if name is not None:
            if not name.strip():
                raise ValueError("Net label cannot be empty")
            updates["name"] = name.strip()
        if position is not None:
            updates["position"] = position

        labels = list(self.labels)
        labels[index] = labels[index].model_copy(update=updates)
        return replace(self, labels=tuple(labels))

    def add_no_connect(self, position: Point) -> EditorState:
        return replace(self, no_connects=(*self.no_connects, NoConnect(position=position)))

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

    def _validated_index(self, selection: SelectionKey, length: int) -> int:
        index = parse_index_key(selection)
        if index >= length:
            raise ValueError(f"Unknown {selection.kind} key: {selection.key}")
        return index
