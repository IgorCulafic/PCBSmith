from __future__ import annotations

import pytest

from pcbsmith.core import netops
from pcbsmith.core.geom import Point
from pcbsmith.core.library import Pin, PinElectricalType, Symbol
from pcbsmith.core.schematic import Junction, NetLabel, Schematic, SymbolInstance, Wire


def _resistor_symbol() -> Symbol:
    return Symbol(
        id="stdlib:R",
        name="Resistor",
        pins=[
            Pin(
                number="1",
                name="A",
                position=Point(x=0, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="B",
                position=Point(x=10, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    )


def _symbols() -> dict[str, Symbol]:
    return {"stdlib:R": _resistor_symbol()}


def _terminal_symbol() -> Symbol:
    return Symbol(
        id="test:T",
        name="Terminal",
        pins=[
            Pin(
                number="1",
                name="T",
                position=Point(x=0, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            )
        ],
    )


def _offset_pin_symbol() -> Symbol:
    return Symbol(
        id="test:OFFSET",
        name="OffsetPin",
        pins=[
            Pin(
                number="1",
                name="T",
                position=Point(x=10, y=0),
                electrical_type=PinElectricalType.PASSIVE,
            )
        ],
    )


def test_derive_netlist_connects_pin_tips_through_wire() -> None:
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="R1",
                symbol_id="stdlib:R",
                value="10k",
                position=Point(x=0, y=0),
            ),
            SymbolInstance(
                reference="R2",
                symbol_id="stdlib:R",
                value="20k",
                position=Point(x=100, y=0),
            ),
        ],
        wires=[Wire(points=[Point(x=10, y=0), Point(x=100, y=0)])],
        labels=[NetLabel(name="OUT", position=Point(x=50, y=0))],
    )
    netlist = netops.derive_netlist(schematic, _symbols())
    assert netlist.net_by_name("OUT").pins == frozenset({("R1", "2"), ("R2", "1")})


def test_derive_netlist_raises_for_unknown_symbol() -> None:
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="U1",
                symbol_id="missing:part",
                value="IC",
                position=Point(x=0, y=0),
            )
        ],
    )
    try:
        netops.derive_netlist(schematic, {})
    except KeyError as exc:
        assert "missing:part" in str(exc)
    else:
        raise AssertionError("unknown symbols should fail")


def test_derive_netlist_raises_for_conflicting_labels() -> None:
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
        wires=[Wire(points=[Point(x=0, y=0), Point(x=10, y=0)])],
        labels=[
            NetLabel(name="IN", position=Point(x=0, y=0)),
            NetLabel(name="OUT", position=Point(x=10, y=0)),
        ],
    )

    with pytest.raises(netops.NetlistDerivationError, match="IN.*OUT"):
        netops.derive_netlist(schematic, _symbols())


def test_derive_netlist_excludes_unconnected_floating_pins() -> None:
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
    )

    netlist = netops.derive_netlist(schematic, _symbols())

    assert netlist.nets == ()


def test_derive_netlist_preserves_single_pin_labelled_net() -> None:
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
        labels=[NetLabel(name="TEST", position=Point(x=0, y=0))],
    )

    netlist = netops.derive_netlist(schematic, _symbols())

    assert netlist.net_by_name("TEST").pins == frozenset({("R1", "1")})


def test_derive_netlist_connects_wire_endpoint_to_segment_t() -> None:
    symbols = {"test:T": _terminal_symbol()}
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="J1",
                symbol_id="test:T",
                value="test",
                position=Point(x=0, y=0),
            ),
            SymbolInstance(
                reference="J2",
                symbol_id="test:T",
                value="test",
                position=Point(x=100, y=0),
            ),
            SymbolInstance(
                reference="J3",
                symbol_id="test:T",
                value="test",
                position=Point(x=50, y=40),
            ),
        ],
        wires=[
            Wire(points=[Point(x=0, y=0), Point(x=100, y=0)]),
            Wire(points=[Point(x=50, y=40), Point(x=50, y=0)]),
        ],
        labels=[NetLabel(name="BUS", position=Point(x=20, y=0))],
    )

    netlist = netops.derive_netlist(schematic, symbols)

    assert netlist.net_by_name("BUS").pins == frozenset(
        {("J1", "1"), ("J2", "1"), ("J3", "1")}
    )


def test_derive_netlist_keeps_mid_segment_crossings_separate() -> None:
    symbols = {"test:T": _terminal_symbol()}
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="J1",
                symbol_id="test:T",
                value="test",
                position=Point(x=0, y=0),
            ),
            SymbolInstance(
                reference="J2",
                symbol_id="test:T",
                value="test",
                position=Point(x=100, y=0),
            ),
            SymbolInstance(
                reference="J3",
                symbol_id="test:T",
                value="test",
                position=Point(x=50, y=-50),
            ),
            SymbolInstance(
                reference="J4",
                symbol_id="test:T",
                value="test",
                position=Point(x=50, y=50),
            ),
        ],
        wires=[
            Wire(points=[Point(x=0, y=0), Point(x=100, y=0)]),
            Wire(points=[Point(x=50, y=-50), Point(x=50, y=50)]),
        ],
        labels=[
            NetLabel(name="H", position=Point(x=20, y=0)),
            NetLabel(name="V", position=Point(x=50, y=-20)),
        ],
    )

    netlist = netops.derive_netlist(schematic, symbols)

    assert netlist.net_by_name("H").pins == frozenset({("J1", "1"), ("J2", "1")})
    assert netlist.net_by_name("V").pins == frozenset({("J3", "1"), ("J4", "1")})


def test_derive_netlist_connects_mid_segment_crossing_with_junction() -> None:
    symbols = {"test:T": _terminal_symbol()}
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="J1",
                symbol_id="test:T",
                value="test",
                position=Point(x=0, y=0),
            ),
            SymbolInstance(
                reference="J2",
                symbol_id="test:T",
                value="test",
                position=Point(x=100, y=0),
            ),
            SymbolInstance(
                reference="J3",
                symbol_id="test:T",
                value="test",
                position=Point(x=50, y=-50),
            ),
            SymbolInstance(
                reference="J4",
                symbol_id="test:T",
                value="test",
                position=Point(x=50, y=50),
            ),
        ],
        wires=[
            Wire(points=[Point(x=0, y=0), Point(x=100, y=0)]),
            Wire(points=[Point(x=50, y=-50), Point(x=50, y=50)]),
        ],
        junctions=[Junction(position=Point(x=50, y=0))],
        labels=[NetLabel(name="X", position=Point(x=20, y=0))],
    )

    netlist = netops.derive_netlist(schematic, symbols)

    assert netlist.net_by_name("X").pins == frozenset(
        {("J1", "1"), ("J2", "1"), ("J3", "1"), ("J4", "1")}
    )


def test_derive_netlist_honors_180_degree_symbol_rotation() -> None:
    symbols = {
        "test:OFFSET": _offset_pin_symbol(),
        "test:T": _terminal_symbol(),
    }
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="J1",
                symbol_id="test:OFFSET",
                value="test",
                position=Point(x=10, y=0),
                rotation_deg=180,
            ),
            SymbolInstance(
                reference="J2",
                symbol_id="test:T",
                value="test",
                position=Point(x=10, y=0),
            ),
        ],
        wires=[Wire(points=[Point(x=0, y=0), Point(x=10, y=0)])],
        labels=[NetLabel(name="ROT", position=Point(x=5, y=0))],
    )

    netlist = netops.derive_netlist(schematic, symbols)

    assert netlist.net_by_name("ROT").pins == frozenset({("J1", "1"), ("J2", "1")})


def test_derive_netlist_raises_for_unsupported_symbol_rotation() -> None:
    symbols = {"test:T": _terminal_symbol()}
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="J1",
                symbol_id="test:T",
                value="test",
                position=Point(x=0, y=0),
                rotation_deg=45,
            )
        ],
    )

    with pytest.raises(netops.NetlistDerivationError, match="rotation"):
        netops.derive_netlist(schematic, symbols)
