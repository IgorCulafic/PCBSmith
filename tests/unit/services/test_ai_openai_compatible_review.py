from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from pcbsmith.services.ai_openai_compatible_review import run_openai_compatible_review
from pcbsmith.services.project_io import create_project, load_schematic


def _model_response() -> dict[str, object]:
    return {
        "version": 1,
        "description": "Pipeline resistor plan",
        "schematic": "schematics/main.sch.json",
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "1k",
                "position": {"x": 15_240_000, "y": 0},
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }


def test_openai_compatible_review_runs_full_dry_run_pipeline(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    request_path = tmp_path / "request.txt"
    output_dir = tmp_path / "ai-run"
    create_project(project_dir, "Pipeline Demo")
    request_path.write_text("Add a resistor to the circuit\n", encoding="utf-8")

    def runner(_request: urllib.request.Request, _timeout: float) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(_model_response())}}]}
        ).encode("utf-8")

    before = (project_dir / "schematics" / "main.sch.json").read_text(encoding="utf-8")
    result = run_openai_compatible_review(
        project_dir,
        request_path,
        output_dir,
        base_url="http://127.0.0.1:1234",
        model="local-test",
        runner=runner,
    )
    after = (project_dir / "schematics" / "main.sch.json").read_text(encoding="utf-8")

    assert result.exit_code == 0
    assert result.applied is False
    assert result.lines[:4] == (
        f"AI OpenAI-compatible review bundle: {output_dir}",
        f"Brief: {output_dir / 'ai-brief.json'}",
        f"Planner package: {output_dir / 'ai-planner-package.json'}",
        f"Candidate plan: {output_dir / 'candidate-plan.json'}",
    )
    assert "Dry run only; no files changed. Pass --apply to save changes." in result.lines
    assert before == after
    assert (output_dir / "ai-brief.json").exists()
    assert (output_dir / "ai-planner-package.json").exists()
    assert (output_dir / "candidate-plan.json").exists()


def test_openai_compatible_review_can_apply_after_validation(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    request_path = tmp_path / "request.txt"
    output_dir = tmp_path / "ai-run"
    create_project(project_dir, "Pipeline Demo")
    request_path.write_text("Add a resistor to the circuit\n", encoding="utf-8")

    def runner(_request: urllib.request.Request, _timeout: float) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(_model_response())}}]}
        ).encode("utf-8")

    result = run_openai_compatible_review(
        project_dir,
        request_path,
        output_dir,
        base_url="http://127.0.0.1:1234",
        model="local-test",
        apply=True,
        runner=runner,
    )
    schematic = load_schematic(project_dir, "schematics/main.sch.json")

    assert result.exit_code == 0
    assert result.applied is True
    assert result.lines[-1] == "Applied 1 commands and wrote .pcbsmith/action-log.jsonl"
    assert len(schematic.symbols) == 1
    assert schematic.symbols[0].reference == "R1"
