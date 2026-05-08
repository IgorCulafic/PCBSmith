from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.inspector import InspectorWidget
from pcbsmith.ui.selection import SelectionKey


def test_inspector_shows_symbol_fields(qtbot) -> None:  # type: ignore[no-untyped-def]
    state = EditorState.blank("main").place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    inspector = InspectorWidget()
    qtbot.addWidget(inspector)

    inspector.show_selection(state, SelectionKey("symbol", "R1"))

    assert inspector.reference_edit.text() == "R1"
    assert inspector.value_edit.text() == "10k"
    assert inspector.item_type_label.text() == "Symbol"


def test_inspector_emits_symbol_update(qtbot) -> None:  # type: ignore[no-untyped-def]
    state = EditorState.blank("main").place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    inspector = InspectorWidget()
    qtbot.addWidget(inspector)
    updates: list[tuple[SelectionKey, str, str]] = []
    inspector.symbol_field_changed.connect(updates.append)
    inspector.show_selection(state, SelectionKey("symbol", "R1"))

    inspector.value_edit.setText("4.7k")
    inspector.commit_value_edit()

    assert updates == [(SelectionKey("symbol", "R1"), "value", "4.7k")]


def test_inspector_does_not_emit_for_missing_symbol(
    qtbot,
) -> None:  # type: ignore[no-untyped-def]
    inspector = InspectorWidget()
    qtbot.addWidget(inspector)
    updates: list[tuple[SelectionKey, str, str]] = []
    inspector.symbol_field_changed.connect(updates.append)

    inspector.show_selection(EditorState.blank("main"), SelectionKey("symbol", "R1"))
    inspector.value_edit.setText("4.7k")
    inspector.commit_value_edit()

    assert inspector.item_type_label.text() == "No selection"
    assert updates == []


def test_inspector_shows_empty_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    inspector = InspectorWidget()
    qtbot.addWidget(inspector)

    inspector.show_selection(EditorState.blank("main"), None)

    assert inspector.item_type_label.text() == "No selection"
