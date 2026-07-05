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
    # Three netlist parts plus four corner mounting holes (rule 5.1).
    assert text.count("(footprint ") == 7
    assert text.count("MountingHole") >= 4
    assert '(path "/bbbbbbbb-1111-2222-3333-444444444444")' in text
    assert '(property "Sim.Device" "D"' in text
    assert '(layer "Edge.Cuts")' in text
    # Three nets with two or more placed pads: each pad gets a drop plus a via,
    # and each net one backside lane segment.
    assert text.count("(via ") == 6
    assert text.count('(layer "B.Cu")') == 3


def test_connector_is_placed_first_even_when_listed_last() -> None:
    from pcbsmith.kicad.board import _place_components

    netlist = BoardNetlist(
        components=(
            BoardComponent(
                reference="R1",
                value="10k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                uuid_path="r1",
            ),
            BoardComponent(
                reference="P1",
                value="5V input",
                footprint=(
                    "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
                ),
                uuid_path="p1",
            ),
        ),
        nets=(),
    )

    placements = _place_components(netlist.components)

    references = [component.reference for component, _ in placements]
    assert references == ["P1", "R1"]
    anchors = {component.reference: anchor for component, anchor in placements}
    assert anchors["P1"] < anchors["R1"]


def test_row_order_minimises_net_span() -> None:
    from pcbsmith.kicad.board import _place_components

    def _smd(reference: str) -> BoardComponent:
        return BoardComponent(
            reference=reference,
            value=reference,
            footprint="Resistor_SMD:R_0603_1608Metric",
            uuid_path=reference.lower(),
        )

    connector = BoardComponent(
        reference="P1",
        value="in",
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        uuid_path="p1",
    )
    # Signal chain P1 -> RB -> RA, listed alphabetically (RA before RB).
    nets = (
        BoardNet(name="/IN", nodes=(("P1", "1"), ("RB", "1"))),
        BoardNet(name="/MID", nodes=(("RB", "2"), ("RA", "1"))),
    )

    placements = _place_components((_smd("RA"), _smd("RB"), connector), nets)

    references = [component.reference for component, _ in placements]
    assert references == ["P1", "RB", "RA"]


def test_connector_pads_hug_the_board_corner() -> None:
    from pcbsmith.kicad.board import CONNECTOR_EDGE_PAD_OFFSET_MM, _place_components

    connector = BoardComponent(
        reference="P1",
        value="in",
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        uuid_path="p1",
    )

    placements = _place_components((connector,), ())

    _, anchor_x = placements[0]
    assert anchor_x == CONNECTOR_EDGE_PAD_OFFSET_MM


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


def test_power_nets_route_wide_and_to263_tab_shares_its_pin_column() -> None:
    from pcbsmith.kicad.board import (
        POWER_TRACK_WIDTH_MM,
        SIGNAL_TRACK_WIDTH_MM,
        compute_board_layout,
    )

    netlist = BoardNetlist(
        components=(
            BoardComponent(
                reference="U1",
                value="LM2596S-ADJ",
                footprint="Package_TO_SOT_SMD:TO-263-5_TabPin3",
                uuid_path="u1",
            ),
            BoardComponent(
                reference="D1",
                value="SS34",
                footprint="Diode_SMD:D_SMA",
                uuid_path="d1",
            ),
            BoardComponent(
                reference="RFB1",
                value="3.74k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                uuid_path="rfb1",
            ),
        ),
        nets=(
            BoardNet(name="/SW", nodes=(("U1", "2"), ("D1", "2"))),
            BoardNet(name="/GND", nodes=(("U1", "3"), ("D1", "1"))),
            BoardNet(name="/FB", nodes=(("U1", "4"), ("RFB1", "1"))),
        ),
    )

    layout = compute_board_layout(netlist, frozenset({"SW", "GND"}))

    widths = {
        segment.net_name: segment.width_mm
        for segment in layout.segments
    }
    assert widths["/SW"] == POWER_TRACK_WIDTH_MM
    assert widths["/GND"] == POWER_TRACK_WIDTH_MM
    assert widths["/FB"] == SIGNAL_TRACK_WIDTH_MM
    # The tab (second pad "3") shares its column with pin 3, so GND gets one
    # drop for that column plus one for the diode anode: two GND vias total.
    gnd_vias = [via for via in layout.vias if via.net_name == "/GND"]
    assert len(gnd_vias) == 2
    # The GND drop in the shared column starts at the tab (topmost pad).
    spec = layout.placements[0][0]
    assert spec.reference in {"U1", "D1", "RFB1"}
    # TO-263 depth pushes the parts row below the minimum.
    assert layout.parts_row_y_mm > 4.5


def test_plot_board_review_writes_png(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from pcbsmith.kicad.preview import plot_board_review

    netlist = parse_board_netlist(SAMPLE_NETLIST_XML)
    output = tmp_path / "review.png"

    plot_board_review(netlist, output)

    assert output.exists()
    assert output.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


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
