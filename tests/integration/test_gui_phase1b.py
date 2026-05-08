from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
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
