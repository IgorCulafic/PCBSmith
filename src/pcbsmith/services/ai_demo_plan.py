from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcbsmith.services.ai_planner_package import AI_PLANNER_PACKAGE_SCHEMA


def build_ai_demo_plan(planner_package: dict[str, Any]) -> dict[str, Any]:
    _require_editable_package(planner_package)
    request_text = _request_text(planner_package).lower()
    schematic = _target_schematic(planner_package)

    if _requests_led_circuit(request_text):
        return _led_series_circuit_plan(schematic)

    if "capacitor" in request_text or "100nf" in request_text:
        return _single_symbol_plan(
            description="Demo plan: add a capacitor",
            schematic=schematic,
            symbol_id="stdlib:C",
            value="100nF",
            footprint_id="stdlib:C_0603",
        )

    return _single_symbol_plan(
        description="Demo plan: add a resistor",
        schematic=schematic,
        symbol_id="stdlib:R",
        value="330",
        footprint_id="stdlib:R_0603",
    )


def _requests_led_circuit(request_text: str) -> bool:
    return "led" in request_text and (
        "complete" in request_text
        or "series circuit" in request_text
        or "create" in request_text
        or "make" in request_text
        or "build" in request_text
    )


def _led_series_circuit_plan(schematic: str) -> dict[str, Any]:
    return {
        "version": 1,
        "description": "Demo plan: create a current-limited LED circuit",
        "schematic": schematic,
        "commands": [
            _place_symbol_command(
                symbol_id="stdlib:VCC",
                value="VCC",
                x=0,
                y=0,
                footprint_id=None,
            ),
            _place_symbol_command(
                symbol_id="stdlib:R",
                value="330",
                x=15_240_000,
                y=0,
                footprint_id="stdlib:R_0603",
            ),
            _place_symbol_command(
                symbol_id="stdlib:LED",
                value="Red LED",
                x=40_640_000,
                y=0,
                footprint_id="stdlib:LED_0603",
            ),
            _place_symbol_command(
                symbol_id="stdlib:GND",
                value="GND",
                x=60_960_000,
                y=0,
                footprint_id=None,
            ),
            _wire_command((0, 0), (10_160_000, 0)),
            _wire_command((20_320_000, 0), (35_560_000, 0)),
            _wire_command((45_720_000, 0), (60_960_000, 0)),
            _label_command("VCC", 0, 0),
            _label_command("LED_A", 27_940_000, 0),
            _label_command("GND", 60_960_000, 0),
        ],
    }


def _place_symbol_command(
    *,
    symbol_id: str,
    value: str,
    x: int,
    y: int,
    footprint_id: str | None,
) -> dict[str, Any]:
    return {
        "type": "place_symbol",
        "symbol_id": symbol_id,
        "value": value,
        "position": {"x": x, "y": y},
        "rotation_deg": 0,
        "footprint_id": footprint_id,
    }


def _wire_command(start: tuple[int, int], end: tuple[int, int]) -> dict[str, Any]:
    return {
        "type": "add_wire",
        "points": [
            {"x": start[0], "y": start[1]},
            {"x": end[0], "y": end[1]},
        ],
    }


def _label_command(name: str, x: int, y: int) -> dict[str, Any]:
    return {
        "type": "add_label",
        "name": name,
        "position": {"x": x, "y": y},
    }


def write_ai_demo_plan(planner_package_path: Path, output_path: Path) -> None:
    planner_package = json.loads(planner_package_path.read_text(encoding="utf-8"))
    if not isinstance(planner_package, dict):
        raise ValueError("Planner package must be a JSON object")
    plan = build_ai_demo_plan(planner_package)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


def _require_editable_package(planner_package: dict[str, Any]) -> None:
    schema = planner_package.get("schema")
    if schema != AI_PLANNER_PACKAGE_SCHEMA:
        raise ValueError(f"Unsupported planner package schema: {schema}")
    if planner_package.get("planner_mode") == "review_response":
        raise ValueError("Cannot create a demo plan from a review-only planner package")

    allowed_types = planner_package.get("allowed_command_types", [])
    if not isinstance(allowed_types, list) or "place_symbol" not in allowed_types:
        raise ValueError("Planner package does not allow place_symbol commands")


def _request_text(planner_package: dict[str, Any]) -> str:
    brief = planner_package.get("brief", {})
    if not isinstance(brief, dict):
        return ""
    request = brief.get("request", {})
    if not isinstance(request, dict):
        return ""
    text = request.get("text", "")
    return text if isinstance(text, str) else ""


def _target_schematic(planner_package: dict[str, Any]) -> str:
    target_schema = planner_package.get("target_plan_schema")
    if isinstance(target_schema, dict):
        schematic = target_schema.get("schematic")
        if isinstance(schematic, str) and schematic:
            return schematic
    return "schematics/main.sch.json"


def _single_symbol_plan(
    *,
    description: str,
    schematic: str,
    symbol_id: str,
    value: str,
    footprint_id: str,
) -> dict[str, Any]:
    return {
        "version": 1,
        "description": description,
        "schematic": schematic,
        "commands": [
            _place_symbol_command(
                symbol_id=symbol_id,
                value=value,
                x=0,
                y=0,
                footprint_id=footprint_id,
            )
        ],
    }


__all__ = [
    "build_ai_demo_plan",
    "write_ai_demo_plan",
]
