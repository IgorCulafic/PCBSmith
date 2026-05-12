from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcbsmith.services.ai_brief import AI_BRIEF_SCHEMA
from pcbsmith.services.board_intelligence import ai_planner_routing_rule_notes
from pcbsmith.services.component_selection import (
    component_selection_planner_rule_notes,
    component_selection_tool_contract,
)

AI_PLANNER_PACKAGE_SCHEMA = "pcbsmith-ai-planner-package-v1"


def build_ai_planner_package(brief: dict[str, Any]) -> dict[str, Any]:
    _require_supported_brief(brief)
    next_operation = _next_operation_type(brief)
    if next_operation == "review_only":
        return {
            "schema": AI_PLANNER_PACKAGE_SCHEMA,
            "planner_mode": "review_response",
            "brief": brief,
            "allowed_command_types": [],
            "target_plan_schema": None,
            "component_selection": component_selection_tool_contract(),
            "planner_rules": _planner_rules(review_only=True),
        }

    return {
        "schema": AI_PLANNER_PACKAGE_SCHEMA,
        "planner_mode": "structured_command_proposal",
        "brief": brief,
        "allowed_command_types": [
            "place_symbol",
            "add_wire",
            "add_label",
            "route_segment",
            "place_text",
        ],
        "target_plan_schema": _target_plan_schema(brief),
        "component_selection": component_selection_tool_contract(),
        "planner_rules": _planner_rules(review_only=False),
    }


def write_ai_planner_package(brief_path: Path, output_path: Path) -> None:
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    package = build_ai_planner_package(brief)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")


def _require_supported_brief(brief: dict[str, Any]) -> None:
    schema = brief.get("schema")
    if schema != AI_BRIEF_SCHEMA:
        raise ValueError(f"Unsupported AI brief schema: {schema}")


def _next_operation_type(brief: dict[str, Any]) -> str:
    intent = brief.get("intent", {})
    if not isinstance(intent, dict):
        return "brief_only"
    value = intent.get("next_operation_type", "brief_only")
    return value if isinstance(value, str) else "brief_only"


def _target_plan_schema(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "description": "<short human-readable summary>",
        "schematic": _first_schematic_path(brief),
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "330",
                "position": {"x": 0, "y": 0},
                "rotation_deg": 0,
                "footprint_id": "stdlib:R_0603",
            },
            {
                "type": "add_wire",
                "points": [
                    {"x": 0, "y": 0},
                    {"x": 5_080_000, "y": 0},
                ],
            },
            {
                "type": "add_label",
                "name": "NET",
                "position": {"x": 0, "y": 0},
            },
            {
                "type": "route_segment",
                "net_name": "NET",
                "layer": "F.Cu",
                "points": [
                    {"x": 4_000_000, "y": 31_000_000},
                    {"x": 46_000_000, "y": 31_000_000},
                ],
                "width": 250_000,
            },
            {
                "type": "place_text",
                "text": "AI note",
                "layer": "F.SilkS",
                "position": {"x": 25_000_000, "y": 31_000_000},
                "rotation_deg": 0,
                "size": 1_500_000,
                "thickness": 150_000,
            },
        ],
    }


def _first_schematic_path(brief: dict[str, Any]) -> str:
    context = brief.get("context", {})
    if isinstance(context, dict):
        project = context.get("project", {})
        if isinstance(project, dict):
            schematics = project.get("schematics", [])
            if isinstance(schematics, list) and schematics:
                first = schematics[0]
                if isinstance(first, str):
                    return first
    return "schematics/main.sch.json"


def _planner_rules(*, review_only: bool) -> list[str]:
    rules = [
        "Return only JSON matching target_plan_schema.",
        "Do not invent unknown symbols, footprints, pins, or KiCad capabilities.",
        "Do not mutate files directly; propose commands for the approval loop.",
        "Preserve the user's intent, assumptions, missing questions, and safety checks.",
        "Use integer nanometre coordinates for schematic command positions.",
        "Use board-local integer nanometre coordinates for route_segment and place_text commands.",
        "Only use F.Cu for route_segment until back-copper routing is enabled.",
        "Only use F.SilkS or B.SilkS for place_text.",
        *component_selection_planner_rule_notes(),
        *ai_planner_routing_rule_notes(),
    ]
    if review_only:
        return [
            "Do not propose project mutations for review_only briefs.",
            "Summarize findings, risks, and questions using the brief context.",
        ]
    return rules


__all__ = [
    "AI_PLANNER_PACKAGE_SCHEMA",
    "build_ai_planner_package",
    "write_ai_planner_package",
]
