from __future__ import annotations

import pytest

from pcbsmith.board_revision import BoardRevisionRequest
from pcbsmith.kicad.no_connect_repair import plan_no_connect_repair


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    board = tmp_path / "fixture.kicad_pcb"
    board.write_text("""(kicad_pcb
      (footprint "Test:Pad" (uuid "fp") (at 5 5) (layer "F.Cu")
        (property "Reference" "J1")
        (pad "1" thru_hole circle (at 0 0) (size 2.5 2.5) (drill 1)
          (layers "*.Cu" "*.Mask") (uuid "pad") (net "unconnected-(J1-Pad1)"))))""")
    xml = tmp_path / "fixture.xml"
    xml.write_text("""<export><nets><net name="unconnected-(J1-Pad1)">
      <node ref="J1" pin="1" pintype="passive+no_connect"/>
      </net></nets></export>""")
    monkeypatch.setattr("pcbsmith.kicad.no_connect_repair.export_kicad_netlist_xml", lambda _: xml)
    return board, xml


def test_only_binding_changes_and_source_is_preserved(fixture):
    board, _ = fixture
    before = board.read_bytes()
    payload, plan = plan_no_connect_repair(board, (("J1", "1"),), 1)
    assert board.read_bytes() == before
    assert b"(drill 1)" in payload and b"(size 2.5 2.5)" in payload
    assert b"(net " not in payload
    assert plan["changed_ids"] == ["fp"]
    assert plan["generator_invocations"] == plan["router_invocations"] == 0


@pytest.mark.parametrize(
    "fault",
    [
        "connected",
        "different_net",
        "locked",
        "duplicate_pad",
        "routed",
        "duplicate_terminal",
        "budget",
    ],
)
def test_unsafe_or_ambiguous_repair_is_rejected(fixture, fault):
    board, xml = fixture
    if fault == "connected":
        xml.write_text(xml.read_text().replace("passive+no_connect", "passive"))
    elif fault == "different_net":
        board.write_text(board.read_text().replace("unconnected-(J1-Pad1)", "/SIGNAL"))
    elif fault == "locked":
        board.write_text(board.read_text().replace('(uuid "fp")', '(uuid "fp") locked'))
    elif fault == "duplicate_pad":
        board.write_text(
            board.read_text().replace(
                '(property "Reference" "J1")', '(property "Reference" "J1") (pad "1")'
            )
        )
    elif fault == "routed":
        board.write_text(board.read_text().replace("(kicad_pcb", "(kicad_pcb (segment)"))
    elif fault == "duplicate_terminal":
        xml.write_text(
            xml.read_text().replace(
                "</nets>", '<net name="/OTHER"><node ref="J1" pin="1"/></net></nets>'
            )
        )
    before = board.read_bytes()
    with pytest.raises(ValueError):
        plan_no_connect_repair(board, (("J1", "1"),), 0 if fault == "budget" else 1)
    assert board.read_bytes() == before


@pytest.mark.parametrize("stage", ["routed", "unrouted_annotations", "unrouted_placement"])
def test_no_connect_request_cannot_use_another_stage(stage):
    with pytest.raises(ValueError, match="separate unrouted terminal scope"):
        BoardRevisionRequest(
            source_inputs={"board": "0" * 64},
            rationale="fixture",
            no_connect_terminals=(("J1", "1"),),
            validation_stage=stage,
        )
