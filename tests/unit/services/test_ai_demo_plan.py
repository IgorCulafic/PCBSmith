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
        "allowed_command_types": ["place_symbol", "add_wire", "add_label"],
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


def test_build_ai_demo_plan_can_create_visible_led_series_circuit() -> None:
    plan = build_ai_demo_plan(_planner_package(request="Create a complete LED circuit"))

    assert plan["description"] == "Demo plan: create a current-limited LED circuit"
    assert plan["schematic"] == "schematics/main.sch.json"
    assert plan["commands"] == [
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:VCC",
            "value": "VCC",
            "position": {"x": 0, "y": 0},
            "rotation_deg": 0,
            "footprint_id": None,
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:R",
            "value": "330",
            "position": {"x": 15_240_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": "stdlib:R_0603",
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:LED",
            "value": "Red LED",
            "position": {"x": 40_640_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": "stdlib:LED_0603",
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:GND",
            "value": "GND",
            "position": {"x": 60_960_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": None,
        },
        {
            "type": "add_wire",
            "points": [{"x": 0, "y": 0}, {"x": 10_160_000, "y": 0}],
        },
        {
            "type": "add_wire",
            "points": [{"x": 20_320_000, "y": 0}, {"x": 35_560_000, "y": 0}],
        },
        {
            "type": "add_wire",
            "points": [{"x": 45_720_000, "y": 0}, {"x": 60_960_000, "y": 0}],
        },
        {"type": "add_label", "name": "VCC", "position": {"x": 0, "y": 0}},
        {
            "type": "add_label",
            "name": "LED_A",
            "position": {"x": 27_940_000, "y": 0},
        },
        {"type": "add_label", "name": "GND", "position": {"x": 60_960_000, "y": 0}},
    ]


def test_build_ai_demo_plan_can_create_voltage_divider() -> None:
    plan = build_ai_demo_plan(_planner_package(request="Create a voltage divider"))

    assert plan["description"] == "Demo plan: create a voltage divider"
    assert plan["schematic"] == "schematics/main.sch.json"
    assert plan["commands"] == [
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:VCC",
            "value": "VCC",
            "position": {"x": 0, "y": 0},
            "rotation_deg": 0,
            "footprint_id": None,
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:R",
            "value": "10k",
            "position": {"x": 15_240_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": "stdlib:R_0603",
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:R",
            "value": "10k",
            "position": {"x": 30_480_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": "stdlib:R_0603",
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:GND",
            "value": "GND",
            "position": {"x": 45_720_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": None,
        },
        {
            "type": "add_wire",
            "points": [{"x": 0, "y": 0}, {"x": 10_160_000, "y": 0}],
        },
        {
            "type": "add_wire",
            "points": [{"x": 20_320_000, "y": 0}, {"x": 25_400_000, "y": 0}],
        },
        {
            "type": "add_wire",
            "points": [{"x": 35_560_000, "y": 0}, {"x": 45_720_000, "y": 0}],
        },
        {"type": "add_label", "name": "VCC", "position": {"x": 0, "y": 0}},
        {
            "type": "add_label",
            "name": "OUT",
            "position": {"x": 22_860_000, "y": 0},
        },
        {"type": "add_label", "name": "GND", "position": {"x": 45_720_000, "y": 0}},
    ]


def test_build_ai_demo_plan_can_create_rc_low_pass_filter() -> None:
    plan = build_ai_demo_plan(_planner_package(request="Create an RC low-pass filter"))

    assert plan["description"] == "Demo plan: create an RC low-pass filter"
    assert plan["schematic"] == "schematics/main.sch.json"
    assert plan["commands"] == [
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:VCC",
            "value": "VCC",
            "position": {"x": 0, "y": 0},
            "rotation_deg": 0,
            "footprint_id": None,
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:R",
            "value": "10k",
            "position": {"x": 15_240_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": "stdlib:R_0603",
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:C",
            "value": "100nF",
            "position": {"x": 40_640_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": "stdlib:C_0603",
        },
        {
            "type": "place_symbol",
            "symbol_id": "stdlib:GND",
            "value": "GND",
            "position": {"x": 60_960_000, "y": 0},
            "rotation_deg": 0,
            "footprint_id": None,
        },
        {
            "type": "add_wire",
            "points": [{"x": 0, "y": 0}, {"x": 10_160_000, "y": 0}],
        },
        {
            "type": "add_wire",
            "points": [{"x": 20_320_000, "y": 0}, {"x": 35_560_000, "y": 0}],
        },
        {
            "type": "add_wire",
            "points": [{"x": 45_720_000, "y": 0}, {"x": 60_960_000, "y": 0}],
        },
        {"type": "add_label", "name": "VCC", "position": {"x": 0, "y": 0}},
        {"type": "add_label", "name": "OUT", "position": {"x": 27_940_000, "y": 0}},
        {"type": "add_label", "name": "GND", "position": {"x": 60_960_000, "y": 0}},
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
