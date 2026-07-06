from __future__ import annotations

from pcbsmith.kicad.board_diff import (
    PlacementEdit,
    diff_placements,
    load_layout_snapshot,
    parse_board_placements,
    write_layout_snapshot,
)

BOARD = '''(kicad_pcb
  (footprint "Resistor_SMD:R_0603_1608Metric"
    (layer "F.Cu")
    (at 30.0 40.0 90)
    (property "Reference" "R1" (at 0 0 0))
    (property "Description" "res (with parens)" (at 0 0 0))
  )
  (footprint "LED_SMD:LED_0603_1608Metric"
    (layer "B.Cu")
    (at 50.0 40.0)
    (property "Reference" "D1" (at 0 0 0))
  )
)
'''


def test_parse_and_diff_and_snapshot(tmp_path) -> None:
    generated = parse_board_placements(BOARD)
    assert generated["R1"] == (30.0, 40.0, 90.0, "F.Cu")
    assert generated["D1"] == (50.0, 40.0, 0.0, "B.Cu")

    edited = dict(generated)
    edited["D1"] = (50.0, 33.5, 0.0, "B.Cu")
    edits = diff_placements(generated, edited)
    assert len(edits) == 1
    assert "D1" in edits[0].describe()
    assert "-6.50" in edits[0].describe()

    # No-op diffs stay empty (float noise below tolerance ignored).
    same = dict(generated)
    same["R1"] = (30.001, 40.0, 90.0, "F.Cu")
    assert diff_placements(generated, same) == ()

    snapshot = write_layout_snapshot(generated, tmp_path / "layout.json")
    assert load_layout_snapshot(snapshot) == generated


def test_added_and_removed_parts_are_reported() -> None:
    generated = parse_board_placements(BOARD)
    edited = {"R1": generated["R1"]}
    edits = diff_placements(generated, edited)
    assert any("removed" in edit.describe() for edit in edits)
    assert isinstance(edits[0], PlacementEdit)
