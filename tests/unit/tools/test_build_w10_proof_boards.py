from __future__ import annotations

from tools.build_w10_proof_boards import CASES, _placement_only_text


def test_w10_proof_pair_is_materially_different() -> None:
    assert tuple(case.case_id for case in CASES) == ("W10A", "W10B")
    assert CASES[0].required_refdes_refs == (
        "J1",
        "U1",
        "R1",
        "R2",
        "C1",
        "C2",
        "C3",
        "R3",
        "LED1",
    )
    assert CASES[1].required_refdes_refs == (
        "J1",
        "J2",
        "U1",
        "L1",
        "D1",
        "CIN",
        "COUT",
        "RFB1",
        "RFB2",
    )
    assert CASES[0].expected_current_paths == ()
    assert len(CASES[1].expected_current_paths) == 2
    assert max(CASES[0].net_widths_mm.values()) == 0.5
    assert max(CASES[1].net_widths_mm.values()) == 1.0


def test_placement_only_board_strips_all_route_carriers() -> None:
    board = """(kicad_pcb
      (version 20240108)
      (generator pcbnew)
      (net 0 \"\")
      (net 1 \"GND\")
      (footprint \"Test:Part\" (layer \"F.Cu\"))
      (segment (start 1 1) (end 2 2) (width 0.3) (layer \"F.Cu\") (net 1))
      (via (at 2 2) (size 0.8) (drill 0.4) (layers \"F.Cu\" \"B.Cu\") (net 1))
      (zone (net 1) (net_name \"GND\") (layer \"F.Cu\")
        (polygon (pts (xy 0 0) (xy 3 0) (xy 3 3))))
    )"""

    placement = _placement_only_text(board)

    assert "(footprint" in placement
    assert '(net 1 "GND")' in placement
    assert "(segment" not in placement
    assert "(via" not in placement
    assert "(zone" not in placement
