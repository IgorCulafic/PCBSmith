from __future__ import annotations

from PySide6.QtGui import QKeySequence

from pcbsmith.core.geom import Point
from pcbsmith.services import project_io
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.main_window import MainWindow
from pcbsmith.ui.schematic_scene import SchematicScene
from pcbsmith.ui.selection import SelectionKey


def test_scene_renders_labels_and_no_connects() -> None:
    state = (
        EditorState.blank("main")
        .add_label("VIN", Point(x=0, y=0))
        .add_no_connect(Point(x=2_540_000, y=0))
    )
    scene = SchematicScene()

    scene.load_editor_state(state)

    assert [item.label.name for item in scene.label_items()] == ["VIN"]
    assert [item.no_connect.position for item in scene.no_connect_items()] == [
        Point(x=2_540_000, y=0)
    ]


def test_scene_applies_move_delete_and_rotate_commands() -> None:
    scene = SchematicScene()
    scene.place_resistor(Point(x=0, y=0))

    scene.move_selection(SelectionKey("symbol", "R1"), Point(x=2_540_000, y=0))
    scene.rotate_selection(SelectionKey("symbol", "R1"), 90)

    symbol = scene.editor_state.to_schematic().symbols[0]
    assert symbol.position == Point(x=2_540_000, y=0)
    assert symbol.rotation_deg == 90

    scene.delete_selection(SelectionKey("symbol", "R1"))

    assert scene.editor_state.to_schematic().symbols == ()


def test_scene_tools_place_label_and_no_connect() -> None:
    scene = SchematicScene()

    scene.set_tool("label")
    scene.handle_canvas_click(Point(x=0, y=0))
    scene.set_tool("no_connect")
    scene.handle_canvas_click(Point(x=2_540_000, y=0))

    schematic = scene.editor_state.to_schematic()
    assert [label.name for label in schematic.labels] == ["NET"]
    assert [marker.position for marker in schematic.no_connects] == [
        Point(x=2_540_000, y=0)
    ]


def test_scene_selected_key_returns_none_for_multiple_selected_items() -> None:
    scene = SchematicScene()
    scene.place_resistor(Point(x=0, y=0))
    scene.place_resistor(Point(x=2_540_000, y=0))

    for item in scene.symbol_items():
        item.setSelected(True)

    assert scene.selected_key() is None


def test_scene_undo_redo_tracks_edit_commands() -> None:
    scene = SchematicScene()
    scene.place_resistor(Point(x=0, y=0))
    scene.move_selection(SelectionKey("symbol", "R1"), Point(x=2_540_000, y=0))

    scene.undo()
    assert scene.editor_state.to_schematic().symbols[0].position == Point(x=0, y=0)

    scene.redo()
    assert scene.editor_state.to_schematic().symbols[0].position == Point(
        x=2_540_000, y=0
    )


def test_load_editor_state_resets_history() -> None:
    scene = SchematicScene()
    scene.place_resistor(Point(x=0, y=0))

    scene.load_editor_state(EditorState.blank("replacement"))

    assert not scene.can_undo
    assert not scene.can_redo


def test_scene_commits_dragged_symbol_position_to_state_and_history() -> None:
    scene = SchematicScene()
    symbol_item = scene.place_resistor(Point(x=0, y=0))
    symbol_item.setSelected(True)
    symbol_item.setPos(2_540_000, 0)

    scene.commit_selected_item_position()

    assert scene.editor_state.to_schematic().symbols[0].position == Point(
        x=2_540_000,
        y=0,
    )
    assert scene.selected_key() == SelectionKey("symbol", "R1")

    scene.undo()

    assert scene.editor_state.to_schematic().symbols[0].position == Point(x=0, y=0)


def test_scene_restores_dragged_item_when_snap_keeps_same_position() -> None:
    scene = SchematicScene()
    symbol_item = scene.place_resistor(Point(x=0, y=0))
    symbol_item.setSelected(True)
    symbol_item.setPos(100_000, 0)

    scene.commit_selected_item_position()

    assert scene.editor_state.to_schematic().symbols[0].position == Point(x=0, y=0)
    assert symbol_item.pos().x() == 0
    assert symbol_item.pos().y() == 0
    assert scene.selected_key() == SelectionKey("symbol", "R1")


def test_scene_commits_dragged_label_and_no_connect_positions() -> None:
    scene = SchematicScene()
    scene.set_tool("label")
    scene.handle_canvas_click(Point(x=0, y=0))
    scene.set_tool("no_connect")
    scene.handle_canvas_click(Point(x=5_080_000, y=0))

    label_item = scene.label_items()[0]
    label_item.setSelected(True)
    label_item.setPos(2_540_000, 0)
    scene.commit_selected_item_position()

    scene.clearSelection()
    no_connect_item = scene.no_connect_items()[0]
    no_connect_item.setSelected(True)
    no_connect_item.setPos(7_620_000, 0)
    scene.commit_selected_item_position()

    schematic = scene.editor_state.to_schematic()
    assert schematic.labels[0].position == Point(x=2_540_000, y=0)
    assert schematic.no_connects[0].position == Point(x=7_620_000, y=0)


def test_main_window_has_inspector_and_edit_actions(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.inspector_dock.windowTitle() == "Inspector"
    action_texts = {action.text() for action in window.schematic_toolbar.actions()}
    assert {
        "Select",
        "Label",
        "No Connect",
        "Undo",
        "Redo",
        "Delete",
        "Rotate",
    }.issubset(action_texts)


def test_main_window_undo_redo_actions_update_scene(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))

    window.undo()
    assert window.scene.editor_state.to_schematic().symbols == ()

    window.redo()
    assert [
        symbol.reference
        for symbol in window.scene.editor_state.to_schematic().symbols
    ] == ["R1"]


def test_main_window_registers_shortcut_actions_and_toolbar_tools(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    window_actions = {action.text(): action for action in window.actions()}
    assert window_actions["Undo"] is window.undo_action
    assert window_actions["Redo"] is window.redo_action
    assert window_actions["Delete"] is window.delete_action
    assert window_actions["Rotate"] is window.rotate_action
    assert window.delete_action.shortcut() == QKeySequence(
        QKeySequence.StandardKey.Delete
    )
    assert window.rotate_action.shortcut() == QKeySequence("Ctrl+R")

    toolbar_actions = {
        action.text(): action for action in window.schematic_toolbar.actions()
    }
    toolbar_actions["Label"].trigger()
    window.scene.handle_canvas_click(Point(x=0, y=0))
    toolbar_actions["No Connect"].trigger()
    window.scene.handle_canvas_click(Point(x=2_540_000, y=0))

    schematic = window.scene.editor_state.to_schematic()
    assert [label.name for label in schematic.labels] == ["NET"]
    assert [marker.position for marker in schematic.no_connects] == [
        Point(x=2_540_000, y=0)
    ]


def test_main_window_applies_symbol_inspector_edits(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))
    window.scene.symbol_items()[0].setSelected(True)
    window.refresh_inspector()

    window.apply_symbol_field_change((SelectionKey("symbol", "R1"), "value", "4.7k"))
    assert window.scene.selected_key() == SelectionKey("symbol", "R1")
    assert window.inspector.item_type_label.text() == "Symbol"
    assert window.inspector.value_edit.text() == "4.7k"

    window.apply_symbol_field_change(
        (SelectionKey("symbol", "R1"), "footprint", "R_0603")
    )

    symbol = window.scene.editor_state.to_schematic().symbols[0]
    assert symbol.value == "4.7k"
    assert symbol.footprint_id == "R_0603"


def test_main_window_rejects_duplicate_reference_from_inspector(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))
    window.scene.place_resistor(Point(x=2_540_000, y=0))
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]

    window.apply_symbol_field_change((SelectionKey("symbol", "R2"), "reference", "R1"))

    assert errors == ["Duplicate reference designator: R1"]
    assert [
        symbol.reference
        for symbol in window.scene.editor_state.to_schematic().symbols
    ] == ["R1", "R2"]


def test_main_window_applies_label_text_edits(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.set_tool("label")
    window.scene.handle_canvas_click(Point(x=0, y=0))

    window.apply_label_text_change((SelectionKey("label", "0"), "VIN"))

    assert [label.name for label in window.scene.editor_state.to_schematic().labels] == [
        "VIN"
    ]


def test_main_window_restores_selection_after_reference_rename(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))
    window.scene.symbol_items()[0].setSelected(True)
    window.refresh_inspector()

    window.apply_symbol_field_change(
        (SelectionKey("symbol", "R1"), "reference", "R10")
    )

    assert window.scene.selected_key() == SelectionKey("symbol", "R10")
    assert window.inspector.item_type_label.text() == "Symbol"
    assert window.inspector.reference_edit.text() == "R10"


def test_main_window_rejects_non_cardinal_rotation_from_inspector(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]

    window.apply_symbol_field_change((SelectionKey("symbol", "R1"), "rotation", "45"))

    assert errors == ["Invalid rotation: 45"]
    assert window.scene.editor_state.to_schematic().symbols[0].rotation_deg == 0


def test_gui_saves_and_reopens_labels_and_no_connects(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    project_dir = tmp_path / "demo"
    project_io.create_project(project_dir, "Demo")

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_dir)
    window.scene.set_tool("label")
    window.scene.handle_canvas_click(Point(x=0, y=0))
    window.apply_label_text_change((SelectionKey("label", "0"), "VIN"))
    window.scene.set_tool("no_connect")
    window.scene.handle_canvas_click(Point(x=2_540_000, y=0))
    window.save_project()

    reopened = MainWindow()
    qtbot.addWidget(reopened)
    reopened.open_project(project_dir)

    schematic = reopened.scene.editor_state.to_schematic()
    assert [(label.name, label.position) for label in schematic.labels] == [
        ("VIN", Point(x=0, y=0))
    ]
    assert [marker.position for marker in schematic.no_connects] == [
        Point(x=2_540_000, y=0)
    ]
