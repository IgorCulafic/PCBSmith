from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.ai.ai_proposal_bundle import run_ai_proposal_bundle
from pcbsmith.operations.project_io import create_project, load_schematic


def _write_planner_package(path: Path, *, review_only: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-ai-planner-package-v1",
                "planner_mode": "review_response"
                if review_only
                else "structured_command_proposal",
                "allowed_command_types": [] if review_only else ["place_symbol"],
                "target_plan_schema": None
                if review_only
                else {
                    "version": 1,
                    "schematic": "schematics/main.sch.json",
                    "commands": [],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_candidate_plan(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "description": "Proposal resistor",
                "schematic": "schematics/main.sch.json",
                "commands": [
                    {
                        "type": "place_symbol",
                        "symbol_id": "stdlib:R",
                        "value": "1k",
                        "position": {"x": 0, "y": 0},
                        "footprint_id": "stdlib:R_0603",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_ai_proposal_bundle_applies_plan_to_staged_copy_only(tmp_path: Path) -> None:
    project_dir = tmp_path / "source"
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    output_dir = tmp_path / "proposal"
    create_project(project_dir, "Proposal Demo")
    _write_planner_package(planner_path)
    _write_candidate_plan(candidate_path)

    result = run_ai_proposal_bundle(
        project_dir,
        planner_path,
        candidate_path,
        output_dir,
        execute_kicad=False,
    )

    original = load_schematic(project_dir, "schematics/main.sch.json")
    staged = load_schematic(output_dir / "pcbs-project", "schematics/main.sch.json")

    assert result.exit_code == 0
    assert result.staged_project_dir == output_dir / "pcbs-project"
    assert result.kicad_review_dir == output_dir / "kicad-review"
    assert result.revision_brief_file == output_dir / "revision-brief.json"
    assert result.revision_brief.status == "passed"
    assert len(original.symbols) == 0
    assert len(staged.symbols) == 1
    assert staged.symbols[0].reference == "R1"
    assert (output_dir / "kicad-review" / "Proposal_Demo.kicad_pro").exists()
    assert (output_dir / "revision-brief.json").exists()
    assert result.lines[:5] == (
        f"AI proposal bundle: {output_dir}",
        f"Staged PCBSmith project: {output_dir / 'pcbs-project'}",
        "AI plan: valid",
        "Target schematic: schematics/main.sch.json",
        "Commands: 1",
    )


def test_ai_proposal_bundle_rejects_invalid_plan_before_copy(tmp_path: Path) -> None:
    project_dir = tmp_path / "source"
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    output_dir = tmp_path / "proposal"
    create_project(project_dir, "Proposal Demo")
    _write_planner_package(planner_path, review_only=True)
    _write_candidate_plan(candidate_path)

    with pytest.raises(ValueError, match="planner package is review-only"):
        run_ai_proposal_bundle(
            project_dir,
            planner_path,
            candidate_path,
            output_dir,
            execute_kicad=False,
        )

    assert not output_dir.exists()


def test_ai_proposal_bundle_refuses_existing_output_dir(tmp_path: Path) -> None:
    project_dir = tmp_path / "source"
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    output_dir = tmp_path / "proposal"
    create_project(project_dir, "Proposal Demo")
    output_dir.mkdir()
    _write_planner_package(planner_path)
    _write_candidate_plan(candidate_path)

    with pytest.raises(FileExistsError):
        run_ai_proposal_bundle(
            project_dir,
            planner_path,
            candidate_path,
            output_dir,
            execute_kicad=False,
        )
