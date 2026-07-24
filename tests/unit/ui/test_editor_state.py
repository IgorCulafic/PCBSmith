from __future__ import annotations

import pytest

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import Junction, NetLabel, NoConnect, Schematic
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.selection import SelectionKey


def test_place_resistors_generates_references_and_schematic() -> None:
    state = EditorState.blank("main")

    state = state.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    state = state.place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))

    schematic = state.to_schematic()

    assert [symbol.reference for symbol in schematic.symbols] == ["R1", "R2"]
    assert [symbol.symbol_id for symbol in schematic.symbols] == ["stdlib:R", "stdlib:R"]
    assert [symbol.value for symbol in schematic.symbols] == ["10k", "1k"]


def test_place_symbol_uses_prefix_for_new_basic_symbols() -> None:
    state = EditorState.blank("main")

    state = state.place_symbol(
        "stdlib:D",
        "D",
        Point(x=0, y=0),
        footprint_id="stdlib:D_0603",
    )
    state = state.place_symbol(
        "stdlib:SW_PUSH",
        "Button",
        Point(x=2_540_000, y=0),
        footprint_id="stdlib:SW_PUSH_TH",
    )
    state = state.place_symbol(
        "stdlib:SW_SPST",
        "Switch",
        Point(x=5_080_000, y=0),
        footprint_id="stdlib:SW_SPST_TH",
    )

    assert [symbol.reference for symbol in state.symbols] == ["D1", "SW1", "SW2"]


def test_add_wire_round_trips_through_schematic() -> None:
    schematic = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))
        .add_wire((Point(x=5_080_000, y=0), Point(x=15_240_000, y=0)))
        .to_schematic()
    )

    restored = EditorState.from_schematic(schematic).to_schematic()

    assert restored == schematic


def test_load_existing_references_continues_counter() -> None:
    state = EditorState.from_schematic(
        Schematic(
            id="main",
            symbols=(
                EditorState.blank("main")
                .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
                .to_schematic()
                .symbols[0],
            ),
        )
    )

    updated = state.place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))

    assert [symbol.reference for symbol in updated.to_schematic().symbols] == ["R1", "R2"]


def test_round_trip_preserves_non_rendered_schematic_fields() -> None:
    schematic = Schematic(
        id="main",
        junctions=(Junction(position=Point(x=1, y=2)),),
        labels=(NetLabel(name="VIN", position=Point(x=3, y=4)),),
        no_connects=(NoConnect(position=Point(x=5, y=6)),),
    )

    restored = EditorState.from_schematic(schematic).to_schematic()

    assert restored == schematic


def test_move_symbol_updates_position_without_dropping_other_fields() -> None:
    state = EditorState.blank("main").place_symbol("stdlib:R", "10k", Point(x=0, y=0))

    moved = state.move_item(SelectionKey("symbol", "R1"), Point(x=2_540_000, y=0))

    schematic = moved.to_schematic()
    assert schematic.symbols[0].position == Point(x=2_540_000, y=0)
    assert schematic.symbols[0].reference == "R1"


def test_delete_symbol_removes_selected_symbol() -> None:
    state = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=2_540_000, y=0))
    )

    updated = state.delete_item(SelectionKey("symbol", "R1"))

    assert [symbol.reference for symbol in updated.to_schematic().symbols] == ["R2"]


def test_rotate_symbol_uses_right_angle_steps() -> None:
    state = EditorState.blank("main").place_symbol("stdlib:R", "10k", Point(x=0, y=0))

    updated = state.rotate_symbol("R1", 90)

    assert updated.to_schematic().symbols[0].rotation_deg == 90


def test_edit_symbol_rejects_duplicate_reference() -> None:
    state = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=2_540_000, y=0))
    )

    with pytest.raises(ValueError, match="Duplicate reference"):
        state.update_symbol("R2", new_reference="R1")


def test_add_rename_and_delete_net_label() -> None:
    state = EditorState.blank("main").add_label("VIN", Point(x=0, y=0))

    renamed = state.update_label(0, name="VOUT")
    deleted = renamed.delete_item(SelectionKey("label", "0"))

    assert renamed.to_schematic().labels == (
        NetLabel(name="VOUT", position=Point(x=0, y=0)),
    )
    assert deleted.to_schematic().labels == ()


def test_add_and_delete_no_connect() -> None:
    state = EditorState.blank("main").add_no_connect(Point(x=0, y=0))

    deleted = state.delete_item(SelectionKey("no_connect", "0"))

    assert state.to_schematic().no_connects == (NoConnect(position=Point(x=0, y=0)),)
    assert deleted.to_schematic().no_connects == ()
