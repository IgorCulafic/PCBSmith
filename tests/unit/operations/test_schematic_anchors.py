from __future__ import annotations

from pcbsmith.core.geom import Point, mm_to_nm
from pcbsmith.core.schematic import Schematic, SymbolInstance, Wire
from pcbsmith.knowledge.builtin_library import SYMBOLS
from pcbsmith.operations.schematic_anchors import (
    SchematicAnchorKind,
    nearest_anchor,
    schematic_anchors,
)


def test_schematic_anchors_include_absolute_symbol_pin_positions() -> None:
    schematic = Schematic(
        id="main",
        symbols=(
            SymbolInstance(
                reference="R1",
                symbol_id="stdlib:R",
                value="10k",
                position=Point(x=mm_to_nm(10), y=mm_to_nm(5)),
            ),
        ),
    )

    anchors = schematic_anchors(schematic, SYMBOLS)

    assert [(anchor.id, anchor.kind, anchor.position) for anchor in anchors] == [
        ("R1.1", SchematicAnchorKind.PIN, Point(x=mm_to_nm(4.92), y=mm_to_nm(5))),
        ("R1.2", SchematicAnchorKind.PIN, Point(x=mm_to_nm(15.08), y=mm_to_nm(5))),
    ]


def test_schematic_anchors_apply_symbol_rotation_and_mirroring() -> None:
    schematic = Schematic(
        id="main",
        symbols=(
            SymbolInstance(
                reference="D1",
                symbol_id="stdlib:D",
                value="D",
                position=Point(x=0, y=0),
                rotation_deg=90,
                mirrored_x=True,
            ),
        ),
    )

    anchors = schematic_anchors(schematic, SYMBOLS)

    assert [(anchor.id, anchor.position) for anchor in anchors] == [
        ("D1.1", Point(x=0, y=mm_to_nm(5.08))),
        ("D1.2", Point(x=0, y=-mm_to_nm(5.08))),
    ]


def test_schematic_anchors_include_wire_endpoints_after_pins() -> None:
    schematic = Schematic(
        id="main",
        wires=(
            Wire(
                points=(
                    Point(x=0, y=0),
                    Point(x=mm_to_nm(2.54), y=0),
                    Point(x=mm_to_nm(5.08), y=0),
                )
            ),
        ),
    )

    anchors = schematic_anchors(schematic, SYMBOLS)

    assert [(anchor.id, anchor.kind, anchor.position) for anchor in anchors] == [
        ("wire:0:start", SchematicAnchorKind.WIRE_ENDPOINT, Point(x=0, y=0)),
        (
            "wire:0:end",
            SchematicAnchorKind.WIRE_ENDPOINT,
            Point(x=mm_to_nm(5.08), y=0),
        ),
    ]


def test_nearest_anchor_prefers_pin_over_wire_endpoint_when_distances_tie() -> None:
    schematic = Schematic(
        id="main",
        symbols=(
            SymbolInstance(
                reference="R1",
                symbol_id="stdlib:R",
                value="10k",
                position=Point(x=0, y=0),
            ),
        ),
        wires=(Wire(points=(Point(x=-mm_to_nm(5.08), y=0), Point(x=0, y=0))),),
    )
    anchors = schematic_anchors(schematic, SYMBOLS)

    match = nearest_anchor(Point(x=-mm_to_nm(5.08), y=0), anchors, tolerance_nm=100_000)

    assert match is not None
    assert match.anchor.id == "R1.1"
    assert match.distance_nm == 0


def test_nearest_anchor_returns_none_outside_tolerance() -> None:
    anchors = schematic_anchors(
        Schematic(
            id="main",
            symbols=(
                SymbolInstance(
                    reference="R1",
                    symbol_id="stdlib:R",
                    value="10k",
                    position=Point(x=0, y=0),
                ),
            ),
        ),
        SYMBOLS,
    )

    assert nearest_anchor(Point(x=0, y=0), anchors, tolerance_nm=100_000) is None
