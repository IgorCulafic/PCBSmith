from __future__ import annotations

import json

from pcbsmith.rules.kicad_board_policy import (
    KiCadBoardPolicySeverity,
    inspect_kicad_board_policy,
    write_kicad_board_policy_report,
)


def test_kicad_board_policy_flags_route_style_width_and_via_in_smd_pad(tmp_path) -> None:  # type: ignore[no-untyped-def]
    board_text = """
  (net 1 "VCC")
  (footprint "PCBSmith_R_0603_REAL"
    (layer "F.Cu")
    (at 10 10)
    (attr smd)
    (pad "1" smd roundrect
      (at 0 0)
      (size 1 1)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (net 1 "VCC")
    )
  )
  (segment
    (start 0 0)
    (end 10 3)
    (width 0.3)
    (layer "F.Cu")
    (net 1)
  )
  (segment
    (start 10 3)
    (end 20 3)
    (width 0.8)
    (layer "F.Cu")
    (net 1)
  )
  (via
    (at 10 10)
    (size 0.8)
    (drill 0.4)
    (layers "F.Cu" "B.Cu")
    (net 1)
  )
"""

    report = inspect_kicad_board_policy(board_text)

    assert [(finding.severity, finding.code) for finding in report.findings] == [
        (KiCadBoardPolicySeverity.WARNING, "non_preferred_trace_angle"),
        (KiCadBoardPolicySeverity.WARNING, "inconsistent_trace_width"),
        (KiCadBoardPolicySeverity.ERROR, "via_in_smd_pad_keepout"),
    ]
    assert report.exit_code == 1

    output_path = tmp_path / "kicad-board-policy.json"
    write_kicad_board_policy_report(report, output_path)
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-kicad-board-policy-v1"
    assert data["summary"] == {
        "finding_count": 3,
        "error_count": 1,
        "warning_count": 2,
    }


def test_kicad_board_policy_accepts_clean_cardinal_and_45_degree_board() -> None:
    board_text = """
  (net 1 "GND")
  (segment
    (start 0 0)
    (end 10 0)
    (width 0.45)
    (layer "F.Cu")
    (net 1)
  )
  (segment
    (start 10 0)
    (end 15 5)
    (width 0.45)
    (layer "F.Cu")
    (net 1)
  )
  (segment
    (start 15 5)
    (end 15 15)
    (width 0.45)
    (layer "F.Cu")
    (net 1)
  )
"""

    report = inspect_kicad_board_policy(board_text)

    assert report.findings == ()
    assert report.exit_code == 0
