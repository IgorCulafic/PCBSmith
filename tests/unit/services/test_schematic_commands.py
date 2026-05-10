from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire
from pcbsmith.services.schematic_commands import (
    AddLabelCommand,
    AddWireCommand,
    PlaceSymbolCommand,
    apply_schematic_command,
)


def test_place_symbol_command_generates_reference_and_message() -> None:
    schematic = Schematic(id="main")

    result = apply_schematic_command(
        schematic,
        PlaceSymbolCommand(
            symbol_id="stdlib:R",
            value="10k",
            position=Point(x=0, y=0),
            footprint_id="stdlib:R_0603",
        ),
    )

    assert result.schematic.symbols == (
        SymbolInstance(
            reference="R1",
            symbol_id="stdlib:R",
            value="10k",
            position=Point(x=0, y=0),
            footprint_id="stdlib:R_0603",
        ),
    )
    assert result.messages == ("Placed R1",)


def test_place_symbol_command_continues_existing_reference_numbers() -> None:
    schematic = Schematic(
        id="main",
        symbols=(
            SymbolInstance(
                reference="R4",
                symbol_id="stdlib:R",
                value="1k",
                position=Point(x=0, y=0),
            ),
        ),
    )

    result = apply_schematic_command(
        schematic,
        PlaceSymbolCommand(
            symbol_id="stdlib:R",
            value="10k",
            position=Point(x=2_540_000, y=0),
        ),
    )

    assert [symbol.reference for symbol in result.schematic.symbols] == ["R4", "R5"]


def test_add_wire_command_appends_wire_and_message() -> None:
    schematic = Schematic(id="main")

    result = apply_schematic_command(
        schematic,
        AddWireCommand(points=(Point(x=0, y=0), Point(x=2_540_000, y=0))),
    )

    assert result.schematic.wires == (
        Wire(points=(Point(x=0, y=0), Point(x=2_540_000, y=0))),
    )
    assert result.messages == ("Added wire with 2 points",)


def test_add_label_command_appends_net_label_and_message() -> None:
    schematic = Schematic(id="main")

    result = apply_schematic_command(
        schematic,
        AddLabelCommand(name="LED_A", position=Point(x=27_940_000, y=0)),
    )

    assert result.schematic.labels == (
        NetLabel(name="LED_A", position=Point(x=27_940_000, y=0)),
    )
    assert result.messages == ("Added label LED_A",)
