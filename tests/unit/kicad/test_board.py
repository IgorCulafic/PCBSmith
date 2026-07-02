from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardGenerationError,
    BoardNet,
    BoardNetlist,
    parse_board_netlist,
    render_board,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.kicad.validate import run_kicad_drc

SAMPLE_NETLIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components>
    <comp ref="P1">
      <value>5V input</value>
      <footprint>Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical</footprint>
      <tstamps>aaaaaaaa-1111-2222-3333-444444444444</tstamps>
    </comp>
    <comp ref="R1">
      <value>10k</value>
      <footprint>Resistor_SMD:R_0603_1608Metric</footprint>
      <fields>
        <field name="Footprint">Resistor_SMD:R_0603_1608Metric</field>
        <field name="Datasheet">~</field>
      </fields>
      <tstamps>bbbbbbbb-1111-2222-3333-444444444444</tstamps>
    </comp>
    <comp ref="D1">
      <value>Red LED</value>
      <footprint>LED_SMD:LED_0603_1608Metric</footprint>
      <fields>
        <field name="Sim.Device">D</field>
      </fields>
      <tstamps>cccccccc-1111-2222-3333-444444444444</tstamps>
    </comp>
    <comp ref="RLOAD">
      <value>10k</value>
      <tstamps>dddddddd-1111-2222-3333-444444444444</tstamps>
    </comp>
    <comp ref="#GND01">
      <value>0</value>
      <footprint>ShouldBe:Skipped</footprint>
    </comp>
  </components>
  <nets>
    <net code="1" name="/VIN">
      <node ref="P1" pin="1"/>
      <node ref="R1" pin="1"/>
    </net>
    <net code="2" name="0">
      <node ref="P1" pin="2"/>
      <node ref="D1" pin="2"/>
      <node ref="RLOAD" pin="2"/>
    </net>
    <net code="3" name="/MID">
      <node ref="R1" pin="2"/>
      <node ref="D1" pin="1"/>
    </net>
    <net code="4" name="/UNPLACED">
      <node ref="RLOAD" pin="1"/>
    </net>
  </nets>
</export>
"""


def test_parse_board_netlist_filters_components_and_nodes() -> None:
    netlist = parse_board_netlist(SAMPLE_NETLIST_XML)

    references = [component.reference for component in netlist.components]
    assert references == ["P1", "R1", "D1"]
    assert netlist.components[2].fields == (("Sim.Device", "D"),)
    net_names = [net.name for net in netlist.nets]
    assert net_names == ["/MID", "/VIN", "0"]
    zero_net = next(net for net in netlist.nets if net.name == "0")
    assert ("RLOAD", "2") not in zero_net.nodes
    assert ("P1", "2") in zero_net.nodes


def test_parse_board_netlist_rejects_empty_component_list() -> None:
    with pytest.raises(BoardGenerationError):
        parse_board_netlist("<export><components/><nets/></export>")


def test_render_board_produces_footprints_tracks_and_outline() -> None:
    netlist = parse_board_netlist(SAMPLE_NETLIST_XML)

    text = render_board(netlist)

    assert text.startswith("(kicad_pcb")
    assert '(net 0 "")' in text
    assert '(net 2 "/VIN")' in text
    assert text.count("(footprint ") == 3
    assert '(path "/bbbbbbbb-1111-2222-3333-444444444444")' in text
    assert '(property "Sim.Device" "D"' in text
    assert '(layer "Edge.Cuts")' in text
    # Three nets with two or more placed pads: each pad gets a drop plus a via,
    # and each net one backside lane segment.
    assert text.count("(via ") == 6
    assert text.count('(layer "B.Cu")') == 3


def test_render_board_rejects_unknown_footprint() -> None:
    netlist = BoardNetlist(
        components=(
            BoardComponent(
                reference="U1",
                value="LM2596",
                footprint="Package_TO_SOT_SMD:TO-263-5",
                uuid_path="u1",
            ),
        ),
        nets=(),
    )

    with pytest.raises(BoardGenerationError, match="TO-263-5"):
        render_board(netlist)


def test_render_board_rejects_unknown_pad_name() -> None:
    netlist = BoardNetlist(
        components=(
            BoardComponent(
                reference="R1",
                value="10k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                uuid_path="r1",
            ),
        ),
        nets=(BoardNet(name="/X", nodes=(("R1", "1"), ("R1", "3"))),),
    )

    with pytest.raises(BoardGenerationError, match="no pad named '3'"):
        render_board(netlist)


def _drc_report_file(command: Sequence[str]) -> Path:
    return Path(command[command.index("--output") + 1])


def test_run_kicad_drc_unavailable_without_cli(tmp_path: Path) -> None:
    board = tmp_path / "Board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")

    report = run_kicad_drc(board, finder=lambda: None)

    assert report.status == "unavailable"
    assert report.board_file == str(board)


def test_run_kicad_drc_passes_with_clean_report(tmp_path: Path) -> None:
    board = tmp_path / "Board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = _drc_report_file(command)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(
                {"violations": [], "unconnected_items": [], "schematic_parity": []}
            ),
            encoding="utf-8",
        )
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = run_kicad_drc(
        board,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "passed"
    assert "--schematic-parity" in report.command
    assert report.findings == ()


def test_run_kicad_drc_reports_violations_and_unconnected(tmp_path: Path) -> None:
    board = tmp_path / "Board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = _drc_report_file(command)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(
                {
                    "violations": [
                        {"severity": "error", "description": "Clearance violation"}
                    ],
                    "unconnected_items": [
                        {"severity": "error", "description": "Missing connection"}
                    ],
                    "schematic_parity": [],
                }
            ),
            encoding="utf-8",
        )
        return KiCadProcessResult(command=tuple(command), returncode=5, stdout="", stderr="")

    report = run_kicad_drc(
        board,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == (
        "violations/error: Clearance violation",
        "unconnected_items/error: Missing connection",
    )
