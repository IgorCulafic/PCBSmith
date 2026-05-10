from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.services.ai_plan_review import run_ai_plan_review
from pcbsmith.services.project_io import create_project, load_schematic


def _write_planner_package(path: Path, *, review_only: bool = False) -> None:
    if review_only:
        data: dict[str, object] = {
            "schema": "pcbsmith-ai-planner-package-v1",
            "planner_mode": "review_response",
            "allowed_command_types": [],
            "target_plan_schema": None,
        }
    else:
        data = {
            "schema": "pcbsmith-ai-planner-package-v1",
            "planner_mode": "structured_command_proposal",
            "allowed_command_types": ["place_symbol", "add_wire"],
            "target_plan_schema": {
                "version": 1,
                "schematic": "schematics/main.sch.json",
                "commands": [],
            },
        }
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_candidate_plan(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "description": "AI proposed resistor",
                "schematic": "schematics/main.sch.json",
                "commands": [
                    {
                        "type": "place_symbol",
                        "symbol_id": "stdlib:R",
                        "value": "330",
                        "position": {"x": 15_240_000, "y": 0},
                        "footprint_id": "stdlib:R_0603",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_run_ai_plan_review_validates_then_dry_runs_without_mutating(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    create_project(project_dir, "AI Review Demo")
    _write_planner_package(planner_path)
    _write_candidate_plan(candidate_path)

    before = (project_dir / "schematics" / "main.sch.json").read_text(encoding="utf-8")
    result = run_ai_plan_review(
        project_dir,
        planner_path,
        candidate_path,
        apply=False,
    )
    after = (project_dir / "schematics" / "main.sch.json").read_text(encoding="utf-8")

    assert result.exit_code == 0
    assert result.applied is False
    assert result.lines == (
        "AI plan: valid",
        "Target schematic: schematics/main.sch.json",
        "Commands: 1",
        "Approval preview:",
        "Plan: AI proposed resistor",
        "Target schematic: schematics/main.sch.json",
        "1. place_symbol stdlib:R value=330 at 15.24, 0 mm",
        "Dry run only; no files changed. Pass --apply to save changes.",
    )
    assert before == after
    assert not (project_dir / ".pcbsmith" / "action-log.jsonl").exists()


def test_run_ai_plan_review_apply_mutates_after_validation(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    create_project(project_dir, "AI Review Demo")
    _write_planner_package(planner_path)
    _write_candidate_plan(candidate_path)

    result = run_ai_plan_review(
        project_dir,
        planner_path,
        candidate_path,
        apply=True,
    )
    schematic = load_schematic(project_dir, "schematics/main.sch.json")

    assert result.exit_code == 0
    assert result.applied is True
    assert result.lines[-1] == "Applied 1 commands and wrote .pcbsmith/action-log.jsonl"
    assert len(schematic.symbols) == 1
    assert schematic.symbols[0].reference == "R1"
    assert (project_dir / ".pcbsmith" / "action-log.jsonl").exists()


def test_run_ai_plan_review_stops_invalid_ai_plan_before_project_mutation(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    create_project(project_dir, "AI Review Demo")
    _write_planner_package(planner_path, review_only=True)
    _write_candidate_plan(candidate_path)

    result = run_ai_plan_review(
        project_dir,
        planner_path,
        candidate_path,
        apply=True,
    )

    assert result.exit_code == 1
    assert result.applied is False
    assert result.lines == (
        "AI plan: invalid",
        "Problem: planner package is review-only and does not allow command plans",
    )
    assert not (project_dir / ".pcbsmith" / "action-log.jsonl").exists()
