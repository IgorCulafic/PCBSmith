from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Pin, PinElectricalType, Symbol
from pcbsmith.core.schematic import NoConnect, Schematic, SymbolInstance, Wire
from pcbsmith.services.erc import run_erc


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


def test_erc_reports_unconnected_pin() -> None:
    symbols = {"stdlib:R": _resistor_symbol()}
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
        wires=[Wire(points=[Point(x=0, y=0), Point(x=-20, y=0)])],
    )

    issues = run_erc(schematic, symbols)

    assert any(issue.code == "ERC001" and issue.where == "R1.2" for issue in issues)


def test_erc_does_not_report_no_connect_pin_type() -> None:
    symbols = {
        "test:NC": Symbol(
            id="test:NC",
            name="No connect",
            pins=[
                Pin(
                    number="1",
                    name="NC",
                    position=Point(x=0, y=0),
                    electrical_type=PinElectricalType.NO_CONNECT,
                )
            ],
        )
    }
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="X1",
                symbol_id="test:NC",
                value="NC",
                position=Point(x=0, y=0),
            )
        ],
    )

    issues = run_erc(schematic, symbols)

    assert issues == []


def test_erc_does_not_report_pin_with_no_connect_marker() -> None:
    symbols = {"stdlib:R": _resistor_symbol()}
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
        wires=[Wire(points=[Point(x=0, y=0), Point(x=-20, y=0)])],
        no_connects=[NoConnect(position=Point(x=10, y=0))],
    )

    issues = run_erc(schematic, symbols)

    assert not any(issue.code == "ERC001" and issue.where == "R1.2" for issue in issues)


def test_erc_reports_power_output_conflict() -> None:
    symbols = {
        "stdlib:PWR": Symbol(
            id="stdlib:PWR",
            name="Power",
            pins=[
                Pin(
                    number="1",
                    name="PWR",
                    position=Point(x=0, y=0),
                    electrical_type=PinElectricalType.POWER_OUT,
                )
            ],
        )
    }
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(
                reference="P1",
                symbol_id="stdlib:PWR",
                value="PWR",
                position=Point(x=0, y=0),
            ),
            SymbolInstance(
                reference="P2",
                symbol_id="stdlib:PWR",
                value="PWR",
                position=Point(x=100, y=0),
            ),
        ],
        wires=[Wire(points=[Point(x=0, y=0), Point(x=100, y=0)])],
    )

    issues = run_erc(schematic, symbols)

    assert any(issue.code == "ERC002" for issue in issues)
