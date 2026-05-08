from __future__ import annotations

import sys

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QGraphicsScene

from pcbsmith.core.geom import Point, snap
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.items import SymbolItem, WireItem
from pcbsmith.ui.schematic_view import GRID_NM


class SchematicScene(QGraphicsScene):
    _app: QApplication | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        if QApplication.instance() is None:
            SchematicScene._app = QApplication(sys.argv[:1])

        super().__init__(parent)
        self._editor_state = EditorState.blank("main")
        self._symbol_items: list[SymbolItem] = []
        self._wire_items: list[WireItem] = []

    @property
    def editor_state(self) -> EditorState:
        return self._editor_state

    def load_editor_state(self, state: EditorState) -> None:
        self.clear()
        self._editor_state = state
        self._symbol_items = [SymbolItem(symbol) for symbol in state.symbols]
        self._wire_items = [WireItem(wire) for wire in state.wires]

        for item in (*self._wire_items, *self._symbol_items):
            self.addItem(item)

    def symbol_items(self) -> tuple[SymbolItem, ...]:
        return tuple(self._symbol_items)

    def wire_items(self) -> tuple[WireItem, ...]:
        return tuple(self._wire_items)

    def place_resistor(self, position: Point, value: str = "10k") -> SymbolItem:
        state = self._editor_state.place_symbol(
            "stdlib:R",
            value,
            snap(position, GRID_NM),
        )
        self.load_editor_state(state)
        return self._symbol_items[-1]

    def add_wire(self, start: Point, end: Point) -> WireItem:
        state = self._editor_state.add_wire((snap(start, GRID_NM), snap(end, GRID_NM)))
        self.load_editor_state(state)
        return self._wire_items[-1]


__all__ = ["SchematicScene"]
