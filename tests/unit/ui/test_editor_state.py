from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import Junction, NetLabel, NoConnect, Schematic
from pcbsmith.ui.editor_state import EditorState


def test_place_resistors_generates_references_and_schematic() -> None:
    state = EditorState.blank("main")

    state = state.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    state = state.place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))

    schematic = state.to_schematic()

    assert [symbol.reference for symbol in schematic.symbols] == ["R1", "R2"]
    assert [symbol.symbol_id for symbol in schematic.symbols] == ["stdlib:R", "stdlib:R"]
    assert [symbol.value for symbol in schematic.symbols] == ["10k", "1k"]


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
