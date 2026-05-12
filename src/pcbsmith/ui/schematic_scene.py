from __future__ import annotations

import sys
from typing import cast

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsSceneMouseEvent

from pcbsmith.core.catalog import CatalogEntry
from pcbsmith.core.geom import Point, mm_to_nm, snap
from pcbsmith.core.schematic import SymbolInstance
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.services.schematic_anchors import nearest_anchor, schematic_anchors
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.history import EditHistory
from pcbsmith.ui.items import NetLabelItem, NoConnectItem, SymbolItem, WireItem
from pcbsmith.ui.schematic_view import GRID_NM
from pcbsmith.ui.selection import SelectionKey

ToolName = str
ANCHOR_SNAP_TOLERANCE_NM = mm_to_nm(1.5)


class SchematicScene(QGraphicsScene):
    _app: QApplication | None = None
    _tools = frozenset(("select", "place_resistor", "place_catalog", "wire", "label", "no_connect"))

    def __init__(self, parent: QObject | None = None) -> None:
        if QApplication.instance() is None:
            SchematicScene._app = QApplication(sys.argv[:1])

        super().__init__(parent)
        self._editor_state = EditorState.blank("main")
        self._history = EditHistory(self._editor_state)
        self._symbol_items: list[SymbolItem] = []
        self._wire_items: list[WireItem] = []
        self._label_items: list[NetLabelItem] = []
        self._no_connect_items: list[NoConnectItem] = []
        self._tool: ToolName = "select"
        self._pending_wire_start: Point | None = None
        self._armed_catalog_entry: CatalogEntry | None = None
        self._placement_preview: SymbolItem | None = None
        self._wire_stroke_width = 4

    @property
    def editor_state(self) -> EditorState:
        return self._editor_state

    @property
    def can_undo(self) -> bool:
        return self._history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._history.can_redo

    def _render_editor_state(self, state: EditorState) -> None:
        self.clear()
        self._editor_state = state
        self._pending_wire_start = None
        self._placement_preview = None
        self._symbol_items = [SymbolItem(symbol) for symbol in state.symbols]
        self._wire_items = [
            WireItem(wire, index, self._wire_stroke_width) for index, wire in enumerate(state.wires)
        ]
        self._label_items = [NetLabelItem(label, index) for index, label in enumerate(state.labels)]
        self._no_connect_items = [
            NoConnectItem(no_connect, index) for index, no_connect in enumerate(state.no_connects)
        ]

        for item in (
            *self._wire_items,
            *self._symbol_items,
            *self._label_items,
            *self._no_connect_items,
        ):
            self.addItem(item)

    def load_editor_state(self, state: EditorState) -> None:
        self._history.reset(state)
        self._render_editor_state(state)

    def symbol_items(self) -> tuple[SymbolItem, ...]:
        return tuple(self._symbol_items)

    def wire_items(self) -> tuple[WireItem, ...]:
        return tuple(self._wire_items)

    def label_items(self) -> tuple[NetLabelItem, ...]:
        return tuple(self._label_items)

    def no_connect_items(self) -> tuple[NoConnectItem, ...]:
        return tuple(self._no_connect_items)

    def select_key(self, selection: SelectionKey | None) -> None:
        self.clearSelection()
        if selection is None:
            return

        for item in (
            *self._wire_items,
            *self._symbol_items,
            *self._label_items,
            *self._no_connect_items,
        ):
            selection_key = getattr(item, "selection_key", None)
            if selection_key is not None and selection_key() == selection:
                item.setSelected(True)
                return

    def apply_editor_state(self, state: EditorState) -> None:
        committed = self._history.commit(state)
        self._render_editor_state(committed)

    def update_symbol(
        self,
        reference: str,
        *,
        new_reference: str | None = None,
        value: str | None = None,
        rotation_deg: int | None = None,
        footprint_id: str | None = None,
    ) -> None:
        self.apply_editor_state(
            self._editor_state.update_symbol(
                reference,
                new_reference=new_reference,
                value=value,
                rotation_deg=rotation_deg,
                footprint_id=footprint_id,
            )
        )

    def update_label(
        self,
        index: int,
        *,
        name: str | None = None,
        position: Point | None = None,
    ) -> None:
        self.apply_editor_state(
            self._editor_state.update_label(index, name=name, position=position)
        )

    def undo(self) -> None:
        self._render_editor_state(self._history.undo())

    def redo(self) -> None:
        self._render_editor_state(self._history.redo())

    def set_tool(self, tool: ToolName) -> None:
        if tool not in self._tools:
            raise ValueError(f"Unknown schematic tool: {tool}")

        self._tool = tool
        if tool != "place_catalog":
            self._armed_catalog_entry = None
            self._clear_placement_preview()
        self._pending_wire_start = None

    def current_tool(self) -> ToolName:
        return self._tool

    def wire_stroke_width(self) -> int:
        return self._wire_stroke_width

    def set_wire_stroke_width(self, width: int) -> None:
        if width < 1:
            raise ValueError("Wire width must be at least 1")
        self._wire_stroke_width = width
        self._render_editor_state(self._editor_state)

    def arm_catalog_entry(self, entry: CatalogEntry) -> None:
        self._tool = "place_catalog"
        self._armed_catalog_entry = entry
        self._pending_wire_start = None
        self._clear_placement_preview()

    def armed_catalog_entry_id(self) -> str | None:
        if self._armed_catalog_entry is None:
            return None
        return self._armed_catalog_entry.id

    def cancel_active_tool(self) -> None:
        self._tool = "select"
        self._armed_catalog_entry = None
        self._pending_wire_start = None
        self._clear_placement_preview()

    def handle_canvas_click(self, position: Point) -> None:
        if self._tool == "place_resistor":
            self.place_resistor(position)
            return

        if self._tool == "place_catalog" and self._armed_catalog_entry is not None:
            entry = self._armed_catalog_entry
            self.place_catalog_entry(entry, position)
            self.cancel_active_tool()
            return

        if self._tool == "wire":
            snapped_position = self._snap_wire_position(position)
            if self._pending_wire_start is None:
                self._pending_wire_start = snapped_position
                return

            self.add_wire_path(self._route_wire_points(self._pending_wire_start, snapped_position))
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
            footprint_id="stdlib:R_0603",
        )
        self.apply_editor_state(state)
        return self._symbol_items[-1]

    def place_catalog_entry(self, entry: CatalogEntry, position: Point) -> SymbolItem:
        state = self._editor_state.place_symbol(
            entry.symbol_id,
            entry.variant.default_value or entry.family.name,
            snap(position, GRID_NM),
            footprint_id=entry.footprint_id,
        )
        self.apply_editor_state(state)
        return self._symbol_items[-1]

    def add_wire(self, start: Point, end: Point) -> WireItem:
        state = self._editor_state.add_wire((snap(start, GRID_NM), snap(end, GRID_NM)))
        self.apply_editor_state(state)
        return self._wire_items[-1]

    def add_wire_path(self, points: tuple[Point, ...]) -> WireItem:
        state = self._editor_state.add_wire(points)
        self.apply_editor_state(state)
        return self._wire_items[-1]

    def _route_wire_points(self, start: Point, end: Point) -> tuple[Point, ...]:
        dx = end.x - start.x
        dy = end.y - start.y
        if dx == 0 or dy == 0 or abs(dx) == abs(dy):
            return (start, end)

        step = min(abs(dx), abs(dy))
        diagonal = Point(
            x=start.x + (step if dx > 0 else -step),
            y=start.y + (step if dy > 0 else -step),
        )
        return (start, diagonal, end)

    def _snap_wire_position(self, position: Point) -> Point:
        match = nearest_anchor(
            position,
            schematic_anchors(self._editor_state.to_schematic(), SYMBOLS),
            tolerance_nm=ANCHOR_SNAP_TOLERANCE_NM,
        )
        if match is not None:
            return match.anchor.position
        return snap(position, GRID_NM)

    def move_selection(self, selection: SelectionKey, position: Point) -> None:
        state = self._editor_state.move_item(selection, snap(position, GRID_NM))
        self.apply_editor_state(state)

    def commit_selected_item_position(self) -> None:
        selection = self.selected_key()
        if selection is None or selection.kind == "wire":
            return

        selected = self.selectedItems()
        if len(selected) != 1:
            return

        position = selected[0].pos()
        snapped_position = snap(
            Point(x=int(position.x()), y=int(position.y())),
            GRID_NM,
        )
        state = self._editor_state.move_item(selection, snapped_position)
        if state != self._editor_state:
            self.apply_editor_state(state)
        else:
            selected[0].setPos(snapped_position.x, snapped_position.y)
        self.select_key(selection)

    def delete_selection(self, selection: SelectionKey) -> None:
        state = self._editor_state.delete_item(selection)
        self.apply_editor_state(state)

    def rotate_selection(self, selection: SelectionKey, delta_deg: int = 90) -> None:
        if selection.kind != "symbol":
            raise ValueError(f"Cannot rotate {selection.kind}")

        state = self._editor_state.rotate_symbol(selection.key, delta_deg)
        self.apply_editor_state(state)

    def mirror_selection_horizontally(self, selection: SelectionKey) -> None:
        if selection.kind != "symbol":
            raise ValueError(f"Cannot mirror {selection.kind}")

        state = self._editor_state.mirror_symbol_horizontally(selection.key)
        self.apply_editor_state(state)
        self.select_key(selection)

    def _clear_placement_preview(self) -> None:
        if self._placement_preview is None:
            return

        self.removeItem(self._placement_preview)
        self._placement_preview = None

    def _update_placement_preview(self, position: Point) -> None:
        if self._armed_catalog_entry is None:
            self._clear_placement_preview()
            return

        snapped_position = snap(position, GRID_NM)
        if self._placement_preview is None:
            entry = self._armed_catalog_entry
            symbol = SymbolInstance(
                reference="PLACE",
                symbol_id=entry.symbol_id,
                value=entry.variant.default_value or entry.family.name,
                position=snapped_position,
                footprint_id=entry.footprint_id,
            )
            self._placement_preview = SymbolItem(symbol)
            self._placement_preview.setOpacity(0.55)
            self._placement_preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.addItem(self._placement_preview)

        self._placement_preview.setPos(snapped_position.x, snapped_position.y)

    def selected_key(self) -> SelectionKey | None:
        selected = self.selectedItems()
        if len(selected) != 1:
            return None

        item = selected[0]
        selection_key = getattr(item, "selection_key", None)
        if not callable(selection_key):
            return None
        return cast(SelectionKey, selection_key())

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._tool != "select":
            scene_pos = event.scenePos()
            self.handle_canvas_click(Point(x=int(scene_pos.x()), y=int(scene_pos.y())))
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._tool == "place_catalog":
            scene_pos = event.scenePos()
            self._update_placement_preview(Point(x=int(scene_pos.x()), y=int(scene_pos.y())))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "select":
            self.commit_selected_item_position()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_active_tool()
            event.accept()
            return

        super().keyPressEvent(event)


__all__ = ["ANCHOR_SNAP_TOLERANCE_NM", "SchematicScene"]
