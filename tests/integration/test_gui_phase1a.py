from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.schematic_scene import SchematicScene


def test_gui_entrypoint_imports() -> None:
    from pcbsmith.ui.app import main

    assert callable(main)


def test_scene_renders_symbols_and_wires() -> None:
    state = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))
        .add_wire((Point(x=5_080_000, y=0), Point(x=15_240_000, y=0)))
    )
    scene = SchematicScene()

    scene.load_editor_state(state)

    assert len(scene.symbol_items()) == 2
    assert len(scene.wire_items()) == 1


def test_scene_represents_bent_wire_segments() -> None:
    start = Point(x=0, y=0)
    bend = Point(x=5_080_000, y=0)
    end = Point(x=5_080_000, y=5_080_000)
    state = EditorState.blank("main").add_wire((start, bend, end))
    scene = SchematicScene()

    scene.load_editor_state(state)

    wire_item = scene.wire_items()[0]
    assert wire_item.segments() == ((start, bend), (bend, end))
