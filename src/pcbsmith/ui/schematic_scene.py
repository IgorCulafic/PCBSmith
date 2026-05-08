from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsSceneMouseEvent

from pcbsmith.core.geom import Point, snap
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.items import NetLabelItem, NoConnectItem, SymbolItem, WireItem
from pcbsmith.ui.schematic_view import GRID_NM
from pcbsmith.ui.selection import SelectionKey

ToolName = str


class SchematicScene(QGraphicsScene):
    _app: QApplication | None = None
    _tools = frozenset(("select", "place_resistor", "wire", "label", "no_connect"))

    def __init__(self, parent: QObject | None = None) -> None:
        if QApplication.instance() is None:
            SchematicScene._app = QApplication(sys.argv[:1])

        super().__init__(parent)
        self._editor_state = EditorState.blank("main")
        self._symbol_items: list[SymbolItem] = []
        self._wire_items: list[WireItem] = []
        self._label_items: list[NetLabelItem] = []
        self._no_connect_items: list[NoConnectItem] = []
        self._tool: ToolName = "select"
        self._pending_wire_start: Point | None = None

    @property
    def editor_state(self) -> EditorState:
        return self._editor_state

    def load_editor_state(self, state: EditorState) -> None:
        self.clear()
        self._editor_state = state
        self._pending_wire_start = None
        self._symbol_items = [SymbolItem(symbol) for symbol in state.symbols]
        self._wire_items = [
            WireItem(wire, index) for index, wire in enumerate(state.wires)
        ]
        self._label_items = [
            NetLabelItem(label, index) for index, label in enumerate(state.labels)
        ]
        self._no_connect_items = [
            NoConnectItem(no_connect, index)
            for index, no_connect in enumerate(state.no_connects)
        ]

        for item in (
            *self._wire_items,
            *self._symbol_items,
            *self._label_items,
            *self._no_connect_items,
        ):
            self.addItem(item)

    def symbol_items(self) -> tuple[SymbolItem, ...]:
        return tuple(self._symbol_items)

    def wire_items(self) -> tuple[WireItem, ...]:
        return tuple(self._wire_items)

    def label_items(self) -> tuple[NetLabelItem, ...]:
        return tuple(self._label_items)

    def no_connect_items(self) -> tuple[NoConnectItem, ...]:
        return tuple(self._no_connect_items)

    def apply_editor_state(self, state: EditorState) -> None:
        self.load_editor_state(state)

    def set_tool(self, tool: ToolName) -> None:
        if tool not in self._tools:
            raise ValueError(f"Unknown schematic tool: {tool}")

        self._tool = tool
        self._pending_wire_start = None

    def handle_canvas_click(self, position: Point) -> None:
        if self._tool == "place_resistor":
            self.place_resistor(position)
            return

        if self._tool == "wire":
            snapped_position = snap(position, GRID_NM)
            if self._pending_wire_start is None:
                self._pending_wire_start = snapped_position
                return

            self.add_wire(self._pending_wire_start, snapped_position)
            self._pending_wire_start = None
            return

        if self._tool == "label":
            state = self._editor_state.add_label("NET", snap(position, GRID_NM))
            self.apply_editor_state(state)
            return

        if self._tool == "no_connect":
            state = self._editor_state.add_no_connect(snap(position, GRID_NM))
            self.apply_editor_state(state)

    def place_resistor(self, position: Point, value: str = "10k") -> SymbolItem:
        state = self._editor_state.place_symbol(
            "stdlib:R",
            value,
            snap(position, GRID_NM),
        )
        self.apply_editor_state(state)
        return self._symbol_items[-1]

    def add_wire(self, start: Point, end: Point) -> WireItem:
        state = self._editor_state.add_wire((snap(start, GRID_NM), snap(end, GRID_NM)))
        self.apply_editor_state(state)
        return self._wire_items[-1]

    def move_selection(self, selection: SelectionKey, position: Point) -> None:
        state = self._editor_state.move_item(selection, snap(position, GRID_NM))
        self.apply_editor_state(state)

    def delete_selection(self, selection: SelectionKey) -> None:
        state = self._editor_state.delete_item(selection)
        self.apply_editor_state(state)

    def rotate_selection(self, selection: SelectionKey, delta_deg: int = 90) -> None:
        if selection.kind != "symbol":
            raise ValueError(f"Cannot rotate {selection.kind}")

        state = self._editor_state.rotate_symbol(selection.key, delta_deg)
        self.apply_editor_state(state)

    def selected_key(self) -> SelectionKey | None:
        selected = self.selectedItems()
        if len(selected) != 1:
            return None

        item = selected[0]
        selection_key = getattr(item, "selection_key", None)
        if selection_key is None:
            return None
        return selection_key()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._tool != "select":
            scene_pos = event.scenePos()
            self.handle_canvas_click(Point(x=int(scene_pos.x()), y=int(scene_pos.y())))
            event.accept()
            return

        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.set_tool("select")
            event.accept()
            return

        super().keyPressEvent(event)


__all__ = ["SchematicScene"]
