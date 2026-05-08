from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.schematic_scene import SchematicScene


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
