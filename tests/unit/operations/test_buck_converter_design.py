from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.operations.design_operations import (
    BuckConverterDesignRequest,
    generate_buck_converter_design,
)


def test_generate_buck_converter_design_writes_real_lm2596_bundle(tmp_path: Path) -> None:
    output_dir = tmp_path / "buck-review"
    request = BuckConverterDesignRequest(name="LM2596 Buck Demo")

    result = generate_buck_converter_design(
        request,
        output_dir,
        execute_kicad=False,
    )

    assert result.exit_code == 0
    assert result.operation == "buck_converter"
    assert result.board_file == output_dir / "LM2596_Buck_Demo.kicad_pcb"
    assert result.board_file.exists()
    assert result.schematic_file.exists()
    assert result.kicad_board_policy_report_file.exists()

    schematic_text = result.schematic_file.read_text(encoding="utf-8")
    assert "LM2596-ADJ" in schematic_text
    assert "L1" in schematic_text
    assert "D1" in schematic_text
    assert "RFB1" in schematic_text
    assert "RFB2" in schematic_text

    board_text = result.board_file.read_text(encoding="utf-8")
    assert "PCBSmith_LM2596_TO263_REAL" in board_text
    assert "VIN 7-24V" in board_text
    assert "VOUT 5V 1A" in board_text
    assert "LM2596 Buck Demo" in board_text

    policy = json.loads(result.kicad_board_policy_report_file.read_text(encoding="utf-8"))
    assert policy["summary"] == {
        "finding_count": 0,
        "error_count": 0,
        "warning_count": 0,
    }

    summary = json.loads(result.operation_summary_file.read_text(encoding="utf-8"))
    assert summary["operation"] == "buck_converter"
    assert summary["topology"]["id"] == "lm2596-adjustable-buck"
    assert summary["calculator"]["calculator"] == "lm2596-buck"
    assert summary["calculator"]["status"] == "warning"
    assert summary["calculator"]["warnings"]
