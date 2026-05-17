from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.operations.design_operations import (
    AttinyLedControllerDesignRequest,
    LedArtDesignRequest,
    SilkscreenArtworkDesignRequest,
    generate_attiny_led_controller_design,
    generate_led_art_design,
    generate_silkscreen_artwork_design,
)
from pcbsmith.rules.board_conventions import board_annotation_rules_summary
from pcbsmith.rules.board_intelligence import board_routing_rules_summary


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
    assert (output_dir / "PCBSmith.kicad_sym").exists()
    assert (output_dir / "sym-lib-table").exists()
    schematic_text = (output_dir / "AI_VIR_LAB.kicad_sch").read_text(encoding="utf-8")
    assert "Board-first LED art design" not in schematic_text
    assert '(symbol "PCBSmith:R"' in schematic_text
    assert '(symbol "PCBSmith:LED"' in schematic_text
    assert '(property "Reference" "J1"' in schematic_text
    assert '(property "Reference" "R1"' in schematic_text
    assert '(property "Reference" "LED1"' in schematic_text
    assert (output_dir / "README.md").exists()
    assert (output_dir / ".pcbsmith" / "reports" / "led-art-electrical.json").exists()

    summary = json.loads(result.operation_summary_file.read_text(encoding="utf-8"))
    assert summary["schema"] == "pcbsmith-design-operation-v1"
    assert summary["operation"] == "led_art"
    assert summary["request"]["text"] == "VIR-LAB"
    assert summary["request"]["control_mode"] == "low_side_mosfet"
    assert summary["outputs"]["board_file"] == "AI_VIR_LAB.kicad_pcb"
    assert summary["routing_rules"] == board_routing_rules_summary()
    assert summary["annotation_rules"] == board_annotation_rules_summary()
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
    assert summary["request"]["connector_style"] == "through_hole"
    assert summary["outputs"]["revision_brief_file"] == "revision-brief.json"
    assert summary["routing_rules"] == board_routing_rules_summary()
    assert summary["annotation_rules"] == board_annotation_rules_summary()
    assert summary["checks"]["revision_brief"] == "passed"


def test_generate_silkscreen_artwork_design_writes_review_bundle(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "silkscreen-review"
    request = SilkscreenArtworkDesignRequest(
        name="R7A Logo Placement",
        text="VIR LAB",
        x_mm=18,
        y_mm=16,
    )

    result = generate_silkscreen_artwork_design(
        request,
        output_dir,
        execute_kicad=False,
    )

    assert result.operation == "silkscreen_artwork"
    assert result.exit_code == 0
    assert result.project_dir == output_dir
    assert result.board_file == output_dir / "R7A_Logo_Placement.kicad_pcb"
    assert result.revision_brief_file == output_dir / "revision-brief.json"
    assert result.operation_summary_file == output_dir / ".pcbsmith" / "operation.json"
    assert result.board_file.exists()
    assert result.revision_brief_file.exists()
    board_text = result.board_file.read_text(encoding="utf-8")
    assert '(gr_text "VIR LAB"' in board_text

    summary = json.loads(result.operation_summary_file.read_text(encoding="utf-8"))
    assert summary["schema"] == "pcbsmith-design-operation-v1"
    assert summary["operation"] == "silkscreen_artwork"
    assert summary["request"]["text"] == "VIR LAB"
    assert summary["request"]["layer"] == "F.SilkS"
    assert (
        summary["outputs"]["preflight_report_file"]
        == ".pcbsmith/reports/silkscreen-preflight.json"
    )
    assert summary["checks"]["silkscreen_preflight"] == "passed"
    assert summary["checks"]["revision_brief"] == "passed"
    report = json.loads(
        (output_dir / ".pcbsmith" / "reports" / "silkscreen-preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["summary"] == {"finding_count": 0, "status": "passed"}


def test_generate_silkscreen_artwork_design_blocks_failed_preflight(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "bad-review"

    with pytest.raises(ValueError, match="silkscreen preflight failed"):
        generate_silkscreen_artwork_design(
            SilkscreenArtworkDesignRequest(
                name="Bad Silk",
                text="too small",
                x_mm=18,
                y_mm=16,
                size_mm=0.5,
            ),
            output_dir,
            execute_kicad=False,
        )

    assert not output_dir.exists()
