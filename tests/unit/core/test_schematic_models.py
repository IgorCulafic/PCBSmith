from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire


def test_schematic_rejects_duplicate_references() -> None:
    first = SymbolInstance(
        reference="R1",
        symbol_id="stdlib:R",
        value="10k",
        position=Point(x=0, y=0),
    )
    second = SymbolInstance(
        reference="R1",
        symbol_id="stdlib:R",
        value="1k",
        position=Point(x=1, y=0),
    )
    try:
        Schematic(id="main", symbols=[first, second])
    except ValueError as exc:
        assert "Duplicate reference" in str(exc)
    else:
        raise AssertionError("duplicate references should fail")


def test_schematic_accepts_wires_and_labels() -> None:
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="R1",
                symbol_id="stdlib:R",
                value="10k",
                position=Point(x=0, y=0),
            )
        ],
        wires=[Wire(points=[Point(x=0, y=0), Point(x=100, y=0)])],
        labels=[NetLabel(name="VIN", position=Point(x=0, y=0))],
    )
    assert schematic.labels[0].name == "VIN"
