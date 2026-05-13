from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.services.board_intelligence import board_routing_rules_summary
from pcbsmith.services.design_operations import (
    AttinyLedControllerDesignRequest,
    LedArtDesignRequest,
    generate_attiny_led_controller_design,
    generate_led_art_design,
)


def test_generate_led_art_design_writes_review_bundle_without_kicad_execution(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "review"
    request = LedArtDesignRequest(
        name="AI VIR LAB",
        text="VIR-LAB",
        topology="12v_dense",
        control_mode="low_side_mosfet",
    )

    result = generate_led_art_design(
        request,
        output_dir,
        execute_kicad=False,
    )

    assert result.exit_code == 0
    assert result.validation_status == "skipped"
    assert result.preview_status == "skipped"
    assert result.project_dir == output_dir
    assert result.board_file == output_dir / "AI_VIR_LAB.kicad_pcb"
    assert result.operation_summary_file == output_dir / ".pcbsmith" / "operation.json"
    assert result.revision_brief_file == output_dir / "revision-brief.json"
    assert result.board_file.exists()
    assert result.revision_brief_file.exists()
    assert (output_dir / "AI_VIR_LAB.kicad_pro").exists()
    assert (output_dir / "AI_VIR_LAB.kicad_sch").exists()
    assert (output_dir / "README.md").exists()
    assert (output_dir / ".pcbsmith" / "reports" / "led-art-electrical.json").exists()

    summary = json.loads(result.operation_summary_file.read_text(encoding="utf-8"))
    assert summary["schema"] == "pcbsmith-design-operation-v1"
    assert summary["operation"] == "led_art"
    assert summary["request"]["text"] == "VIR-LAB"
    assert summary["request"]["control_mode"] == "low_side_mosfet"
    assert summary["outputs"]["board_file"] == "AI_VIR_LAB.kicad_pcb"
    assert summary["routing_rules"] == board_routing_rules_summary()
    assert summary["checks"]["validation"] == "skipped"
    assert summary["checks"]["preview"] == "skipped"
    assert summary["checks"]["revision_brief"] == "passed"
    assert summary["outputs"]["revision_brief_file"] == "revision-brief.json"


def test_generate_led_art_design_refuses_existing_output_without_overwrite(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "review"
    output_dir.mkdir()

    with pytest.raises(FileExistsError, match="Output already exists"):
        generate_led_art_design(
            LedArtDesignRequest(name="AI VIR LAB"),
            output_dir,
            execute_kicad=False,
        )


def test_generate_attiny_led_controller_design_writes_review_bundle(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "attiny-review"
    request = AttinyLedControllerDesignRequest(name="R6 ATtiny Controller")

    result = generate_attiny_led_controller_design(
        request,
        output_dir,
        execute_kicad=False,
    )

    assert result.operation == "attiny_led_controller"
    assert result.exit_code == 0
    assert result.project_dir == output_dir
    assert result.board_file == output_dir / "R6_ATtiny_Controller.kicad_pcb"
    assert result.revision_brief_file == output_dir / "revision-brief.json"
    assert result.operation_summary_file == output_dir / ".pcbsmith" / "operation.json"
    assert result.board_file.exists()
    assert result.revision_brief_file.exists()

    summary = json.loads(result.operation_summary_file.read_text(encoding="utf-8"))
    assert summary["schema"] == "pcbsmith-design-operation-v1"
    assert summary["operation"] == "attiny_led_controller"
    assert summary["request"]["controller"] == "ATtiny84"
    assert summary["request"]["led_outputs"] == 2
    assert summary["outputs"]["revision_brief_file"] == "revision-brief.json"
    assert summary["checks"]["revision_brief"] == "passed"
