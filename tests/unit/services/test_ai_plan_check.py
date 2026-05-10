from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.services.ai_plan_check import check_ai_plan


def _planner_package(*, review_only: bool = False) -> dict[str, object]:
    if review_only:
        return {
            "schema": "pcbsmith-ai-planner-package-v1",
            "planner_mode": "review_response",
            "allowed_command_types": [],
            "target_plan_schema": None,
        }
    return {
        "schema": "pcbsmith-ai-planner-package-v1",
        "planner_mode": "structured_command_proposal",
        "allowed_command_types": ["place_symbol", "add_wire"],
        "target_plan_schema": {
            "version": 1,
            "schematic": "schematics/main.sch.json",
            "commands": [],
        },
    }


def _candidate_plan(*, schematic: str = "schematics/main.sch.json") -> dict[str, object]:
    return {
        "version": 1,
        "description": "Add one resistor",
        "schematic": schematic,
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "330",
                "position": {"x": 0, "y": 0},
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_check_ai_plan_accepts_matching_structured_plan(tmp_path: Path) -> None:
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    _write_json(planner_path, _planner_package())
    _write_json(candidate_path, _candidate_plan())

    result = check_ai_plan(planner_path, candidate_path)

    assert result.valid is True
    assert result.exit_code == 0
    assert result.lines == (
        "AI plan: valid",
        "Target schematic: schematics/main.sch.json",
        "Commands: 1",
    )


def test_check_ai_plan_rejects_wrong_target_schematic(tmp_path: Path) -> None:
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    _write_json(planner_path, _planner_package())
    _write_json(candidate_path, _candidate_plan(schematic="schematics/other.sch.json"))

    result = check_ai_plan(planner_path, candidate_path)

    assert result.valid is False
    assert result.exit_code == 1
    assert result.lines == (
        "AI plan: invalid",
        "Problem: target schematic does not match planner package: schematics/other.sch.json",
    )


def test_check_ai_plan_rejects_structured_plan_for_review_only_package(
    tmp_path: Path,
) -> None:
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    _write_json(planner_path, _planner_package(review_only=True))
    _write_json(candidate_path, _candidate_plan())

    result = check_ai_plan(planner_path, candidate_path)

    assert result.valid is False
    assert result.lines == (
        "AI plan: invalid",
        "Problem: planner package is review-only and does not allow command plans",
    )


def test_check_ai_plan_rejects_invalid_candidate_schema(tmp_path: Path) -> None:
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    _write_json(planner_path, _planner_package())
    _write_json(candidate_path, {"version": 1, "commands": []})

    result = check_ai_plan(planner_path, candidate_path)

    assert result.valid is False
    assert result.lines[0] == "AI plan: invalid"
    assert result.lines[1].startswith("Problem: candidate plan schema is invalid")
