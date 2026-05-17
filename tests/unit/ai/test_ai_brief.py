from __future__ import annotations

import json
import shutil
from pathlib import Path

from pcbsmith.ai.ai_brief import (
    AI_BRIEF_SCHEMA,
    build_ai_brief,
    write_ai_brief,
)

FIXTURE = Path("tests/fixtures/led_series_circuit")


def test_build_ai_brief_expands_led_image_request_with_context(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    kicad_dir = tmp_path / "review-bundle"
    shutil.copytree(FIXTURE, project_dir)
    visual_dir = kicad_dir / ".pcbsmith" / "visual"
    visual_dir.mkdir(parents=True)
    (visual_dir / "preview.svg").write_text("<svg />", encoding="utf-8")

    brief = build_ai_brief(
        project_dir,
        "Make an LED board in the shape of this logo",
        kicad_project_dir=kicad_dir,
    )

    assert brief["schema"] == AI_BRIEF_SCHEMA
    assert brief["request"]["text"] == "Make an LED board in the shape of this logo"
    assert brief["intent"] == {
        "category": "image_to_led",
        "next_operation_type": "layout_task",
        "confidence": "medium",
    }
    assert "Assume KiCad is the authoritative CAD editor/backend." in brief["assumptions"]
    assert "Ask for the reference image before placing LEDs along image paths." in (
        brief["missing_questions"]
    )
    assert "Check LED current limiting and polarity before approval." in (
        brief["safety_checks"]
    )
    assert "vision_reference_processing" in brief["required_capabilities"]
    assert brief["context"]["project"]["name"] == "LED Series Circuit"
    assert brief["context"]["kicad"]["visuals"] == [str(visual_dir / "preview.svg")]


def test_build_ai_brief_classifies_review_request(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    shutil.copytree(FIXTURE, project_dir)

    brief = build_ai_brief(project_dir, "Check if this LED circuit is safe")

    assert brief["intent"] == {
        "category": "review",
        "next_operation_type": "review_only",
        "confidence": "medium",
    }
    assert "Run ERC/DRC and summarize blocking issues before edits." in (
        brief["safety_checks"]
    )
    assert "kicad_validation" in brief["required_capabilities"]


def test_build_ai_brief_rejects_blank_request(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    shutil.copytree(FIXTURE, project_dir)

    try:
        build_ai_brief(project_dir, "   ")
    except ValueError as exc:
        assert str(exc) == "AI brief request cannot be blank"
    else:
        raise AssertionError("Expected ValueError")


def test_write_ai_brief_writes_pretty_json(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    output_path = tmp_path / "brief.json"
    shutil.copytree(FIXTURE, project_dir)

    write_ai_brief(project_dir, "Add a resistor to the LED circuit", output_path)

    text = output_path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["schema"] == AI_BRIEF_SCHEMA
    assert data["intent"]["category"] == "schematic_edit"
    assert text.endswith("\n")
