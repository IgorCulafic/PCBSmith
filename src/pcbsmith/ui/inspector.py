from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.selection import SelectionKey, parse_index_key


class InspectorWidget(QWidget):
    symbol_field_changed = Signal(tuple)
    label_text_changed = Signal(tuple)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._selection: SelectionKey | None = None

        self.item_type_label = QLabel("No selection", self)
        self.reference_edit = QLineEdit(self)
        self.value_edit = QLineEdit(self)
        self.rotation_edit = QLineEdit(self)
        self.footprint_edit = QLineEdit(self)
        self.label_edit = QLineEdit(self)
        self.position_label = QLabel("", self)
        self.diagnostic_label = QLabel("", self)

        layout = QFormLayout(self)
        layout.addRow("Type", self.item_type_label)
        layout.addRow("Reference", self.reference_edit)
        layout.addRow("Value", self.value_edit)
        layout.addRow("Rotation", self.rotation_edit)
        layout.addRow("Footprint", self.footprint_edit)
        layout.addRow("Label", self.label_edit)
        layout.addRow("Position", self.position_label)
        layout.addRow("Diagnostics", self.diagnostic_label)

        self.reference_edit.editingFinished.connect(self.commit_reference_edit)
        self.value_edit.editingFinished.connect(self.commit_value_edit)
        self.rotation_edit.editingFinished.connect(self.commit_rotation_edit)
        self.footprint_edit.editingFinished.connect(self.commit_footprint_edit)
        self.label_edit.editingFinished.connect(self.commit_label_edit)

        self._set_all_enabled(False)

    def show_selection(self, state: EditorState, selection: SelectionKey | None) -> None:
        self._selection = None
        self._set_all_enabled(False)
        self._clear_fields()

        if selection is None:
            self.item_type_label.setText("No selection")
            return

        if selection.kind == "symbol":
            symbol = next(
                (item for item in state.symbols if item.reference == selection.key),
                None,
            )
            if symbol is None:
                self.item_type_label.setText("No selection")
                return

            self._selection = selection
            self.item_type_label.setText("Symbol")
            self.reference_edit.setText(symbol.reference)
            self.value_edit.setText(symbol.value)
            self.rotation_edit.setText(str(symbol.rotation_deg))
            self.footprint_edit.setText(symbol.footprint_id or "")
            self.position_label.setText(_format_position(symbol.position))
            self.reference_edit.setEnabled(True)
            self.value_edit.setEnabled(True)
            self.rotation_edit.setEnabled(True)
            self.footprint_edit.setEnabled(True)
            return

        if selection.kind == "label":
            index = _valid_index(selection, len(state.labels))
            if index is None:
                self.item_type_label.setText("No selection")
                return

            label = state.labels[index]
            self._selection = selection
            self.item_type_label.setText("Net label")
            self.label_edit.setText(label.name)
            self.position_label.setText(_format_position(label.position))
            self.label_edit.setEnabled(True)
            return

        if selection.kind == "wire":
            index = _valid_index(selection, len(state.wires))
            if index is None:
                self.item_type_label.setText("No selection")
                return

            self._selection = selection
            self.item_type_label.setText("Wire")
            self.diagnostic_label.setText("Derived net diagnostics pending")
            return

        if selection.kind == "no_connect":
            index = _valid_index(selection, len(state.no_connects))
            if index is None:
                self.item_type_label.setText("No selection")
                return

            self._selection = selection
            self.item_type_label.setText("No connect")
            self.position_label.setText(_format_position(state.no_connects[index].position))
            return

        self.item_type_label.setText("No selection")

    def commit_reference_edit(self) -> None:
        self._emit_symbol_field("reference", self.reference_edit.text())

    def commit_value_edit(self) -> None:
        self._emit_symbol_field("value", self.value_edit.text())

    def commit_rotation_edit(self) -> None:
        self._emit_symbol_field("rotation", self.rotation_edit.text())

    def commit_footprint_edit(self) -> None:
        self._emit_symbol_field("footprint", self.footprint_edit.text())

    def commit_label_edit(self) -> None:
        if self._selection is None or self._selection.kind != "label":
            return
        self.label_text_changed.emit((self._selection, self.label_edit.text()))

    def _emit_symbol_field(self, field: str, value: str) -> None:
        if self._selection is None or self._selection.kind != "symbol":
            return
        self.symbol_field_changed.emit((self._selection, field, value))

    def _set_all_enabled(self, enabled: bool) -> None:
        for edit in (
            self.reference_edit,
            self.value_edit,
            self.rotation_edit,
            self.footprint_edit,
            self.label_edit,
        ):
            edit.setEnabled(enabled)

    def _clear_fields(self) -> None:
        self.item_type_label.setText("")
        self.reference_edit.clear()
        self.value_edit.clear()
        self.rotation_edit.clear()
        self.footprint_edit.clear()
        self.label_edit.clear()
        self.position_label.setText("")
        self.diagnostic_label.setText("")


def _valid_index(selection: SelectionKey, length: int) -> int | None:
    try:
        index = parse_index_key(selection)
    except ValueError:
        return None
    if index >= length:
        return None
    return index


def _format_position(position: Point) -> str:
    return f"{position.x}, {position.y}"


__all__ = ["InspectorWidget"]
