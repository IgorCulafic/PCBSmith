from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Pin, PinElectricalType, Symbol
from pcbsmith.core.netops import derive_netlist
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire


def test_derive_netlist_connects_pin_tips_through_wire() -> None:
    symbols = {
        "stdlib:R": Symbol(
            id="stdlib:R",
            name="Resistor",
            pins=[
                Pin(number="1", name="A", position=Point(x=0, y=0), electrical_type=PinElectricalType.PASSIVE),
                Pin(number="2", name="B", position=Point(x=10, y=0), electrical_type=PinElectricalType.PASSIVE),
            ],
        )
    }
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(reference="R1", symbol_id="stdlib:R", value="10k", position=Point(x=0, y=0)),
            SymbolInstance(reference="R2", symbol_id="stdlib:R", value="20k", position=Point(x=100, y=0)),
        ],
        wires=[Wire(points=[Point(x=10, y=0), Point(x=100, y=0)])],
        labels=[NetLabel(name="OUT", position=Point(x=50, y=0))],
    )
    netlist = derive_netlist(schematic, symbols)
    assert netlist.net_by_name("OUT").pins == frozenset({("R1", "2"), ("R2", "1")})


def test_derive_netlist_raises_for_unknown_symbol() -> None:
    schematic = Schematic(
        id="main",
        symbols=[SymbolInstance(reference="U1", symbol_id="missing:part", value="IC", position=Point(x=0, y=0))],
    )
    try:
        derive_netlist(schematic, {})
    except KeyError as exc:
        assert "missing:part" in str(exc)
    else:
        raise AssertionError("unknown symbols should fail")
