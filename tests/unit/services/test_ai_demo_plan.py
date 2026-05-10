from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.services.ai_demo_plan import build_ai_demo_plan, write_ai_demo_plan


def _planner_package(*, request: str = "Add a resistor to the LED circuit") -> dict[str, object]:
    return {
        "schema": "pcbsmith-ai-planner-package-v1",
        "planner_mode": "structured_command_proposal",
        "brief": {
            "request": {
                "text": request,
            },
        },
        "allowed_command_types": ["place_symbol", "add_wire"],
        "target_plan_schema": {
            "version": 1,
            "schematic": "schematics/main.sch.json",
            "commands": [],
        },
    }


def test_build_ai_demo_plan_creates_resistor_candidate_from_edit_package() -> None:
    plan = build_ai_demo_plan(_planner_package())

    assert plan == {
        "version": 1,
        "description": "Demo plan: add a resistor",
        "schematic": "schematics/main.sch.json",
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "330",
                "position": {"x": 0, "y": 0},
                "rotation_deg": 0,
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }


def test_build_ai_demo_plan_can_place_capacitor_from_request() -> None:
    plan = build_ai_demo_plan(_planner_package(request="Place a 100nF capacitor"))

    assert plan["description"] == "Demo plan: add a capacitor"
    assert plan["commands"] == [
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:C",
            "value": "100nF",
            "position": {"x": 0, "y": 0},
            "rotation_deg": 0,
            "footprint_id": "stdlib:C_0603",
        }
    ]


def test_build_ai_demo_plan_rejects_review_only_package() -> None:
    package = _planner_package()
    package["planner_mode"] = "review_response"
    package["target_plan_schema"] = None

    with pytest.raises(ValueError, match="review-only"):
        build_ai_demo_plan(package)


def test_write_ai_demo_plan_writes_pretty_candidate_json(tmp_path: Path) -> None:
    planner_path = tmp_path / "planner-package.json"
    output_path = tmp_path / "candidate-plan.json"
    planner_path.write_text(json.dumps(_planner_package()), encoding="utf-8")

    write_ai_demo_plan(planner_path, output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["description"] == "Demo plan: add a resistor"
    assert output_path.read_text(encoding="utf-8").endswith("\n")
