from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.kicad.routing_evidence import (
    RoutingArtifactState,
    inspect_kicad_drc_report,
    inspect_saved_board_routing,
)


def _board_text(*, routed: bool, named_nets: bool = False) -> str:
    net_declaration = "" if named_nets else '(net 1 "SIG")'
    pad_net = '(net "SIG")' if named_nets else '(net 1 "SIG")'
    segment_net = '(net "SIG")' if named_nets else "(net 1)"
    segment = (
        f"""
  (segment
    (start 1 1)
    (end 5 1)
    (width 0.25)
    (layer "F.Cu")
    {segment_net}
  )
"""
        if routed
        else ""
    )
    return f"""(kicad_pcb
  (version 20260206)
  {net_declaration}
  (footprint "Test:A"
    (layer "F.Cu")
    (at 1 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") {pad_net})
  )
  (footprint "Test:B"
    (layer "F.Cu")
    (at 5 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") {pad_net})
  )
  {segment}
)
"""


def test_saved_board_without_segments_is_explicitly_placement_only(
    tmp_path: Path,
) -> None:
    board = tmp_path / "candidate.kicad_pcb"
    board.write_text(_board_text(routed=False), encoding="utf-8")

    evidence = inspect_saved_board_routing(board)

    assert evidence.state is RoutingArtifactState.PLACEMENT_ONLY
    assert evidence.segment_count == 0
    assert evidence.via_count == 0
    assert evidence.routable_net_count == 1
    assert evidence.copper_carrier_net_coverage == 0.0
    assert evidence.uncovered_net_names == ("SIG",)


def test_saved_board_with_every_routable_net_carried_is_only_a_routed_candidate(
    tmp_path: Path,
) -> None:
    board = tmp_path / "candidate.kicad_pcb"
    board.write_text(_board_text(routed=True), encoding="utf-8")

    evidence = inspect_saved_board_routing(board)

    assert evidence.state is RoutingArtifactState.ROUTED_CANDIDATE
    assert evidence.segment_count == 1
    assert evidence.segment_net_count == 1
    assert evidence.track_net_coverage == 1.0


def test_kicad_10_name_based_net_references_are_supported(tmp_path: Path) -> None:
    board = tmp_path / "candidate.kicad_pcb"
    board.write_text(
        _board_text(routed=True, named_nets=True),
        encoding="utf-8",
    )

    evidence = inspect_saved_board_routing(board)

    assert evidence.state is RoutingArtifactState.ROUTED_CANDIDATE
    assert evidence.declared_net_count == 1
    assert evidence.routable_net_count == 1


def test_drc_evidence_counts_every_authoritative_section(tmp_path: Path) -> None:
    report = tmp_path / "drc.json"
    report.write_text(
        json.dumps(
            {
                "violations": [{"description": "clearance"}],
                "unconnected_items": [{"description": "missing"}],
                "schematic_parity": [],
            }
        ),
        encoding="utf-8",
    )

    evidence = inspect_kicad_drc_report(report)

    assert not evidence.clean
    assert evidence.violation_count == 1
    assert evidence.unconnected_item_count == 1
    assert evidence.schematic_parity_count == 0
