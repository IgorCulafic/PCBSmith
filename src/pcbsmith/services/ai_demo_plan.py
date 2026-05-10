from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcbsmith.services.ai_planner_package import AI_PLANNER_PACKAGE_SCHEMA


def build_ai_demo_plan(planner_package: dict[str, Any]) -> dict[str, Any]:
    _require_editable_package(planner_package)
    request_text = _request_text(planner_package).lower()
    schematic = _target_schematic(planner_package)

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
            {
                "type": "place_symbol",
                "symbol_id": symbol_id,
                "value": value,
                "position": {"x": 0, "y": 0},
                "rotation_deg": 0,
                "footprint_id": footprint_id,
            }
        ],
    }


__all__ = [
    "build_ai_demo_plan",
    "write_ai_demo_plan",
]
