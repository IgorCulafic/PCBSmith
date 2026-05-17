from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcbsmith.ai.ai_context import build_ai_context

AI_BRIEF_SCHEMA = "pcbsmith-ai-brief-v1"


def build_ai_brief(
    project_dir: Path,
    request_text: str,
    *,
    kicad_project_dir: Path | None = None,
) -> dict[str, Any]:
    normalized_request = request_text.strip()
    if not normalized_request:
        raise ValueError("AI brief request cannot be blank")

    intent = _classify_intent(normalized_request)
    return {
        "schema": AI_BRIEF_SCHEMA,
        "request": {
            "text": normalized_request,
        },
        "intent": intent,
        "assumptions": _assumptions(intent["category"]),
        "missing_questions": _missing_questions(intent["category"]),
        "safety_checks": _safety_checks(intent["category"]),
        "required_capabilities": _required_capabilities(intent["category"]),
        "context": build_ai_context(project_dir, kicad_project_dir=kicad_project_dir),
    }


def write_ai_brief(
    project_dir: Path,
    request_text: str,
    output_path: Path,
    *,
    kicad_project_dir: Path | None = None,
) -> None:
    brief = build_ai_brief(
        project_dir,
        request_text,
        kicad_project_dir=kicad_project_dir,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(brief, indent=2) + "\n", encoding="utf-8")


def _classify_intent(request_text: str) -> dict[str, str]:
    lowered = request_text.lower()
    if _mentions_any(lowered, ("image", "logo", "shape", "picture", "photo")) and (
        "led" in lowered
    ):
        return {
            "category": "image_to_led",
            "next_operation_type": "layout_task",
            "confidence": "medium",
        }
    if _mentions_any(lowered, ("check", "review", "safe", "inspect", "validate")):
        return {
            "category": "review",
            "next_operation_type": "review_only",
            "confidence": "medium",
        }
    if _mentions_any(lowered, ("add", "place", "connect", "wire", "resistor", "capacitor", "led")):
        return {
            "category": "schematic_edit",
            "next_operation_type": "schematic_edit",
            "confidence": "medium",
        }
    return {
        "category": "general_design",
        "next_operation_type": "brief_only",
        "confidence": "low",
    }


def _assumptions(category: str) -> list[str]:
    assumptions = [
        "Assume KiCad is the authoritative CAD editor/backend.",
        "Assume PCBSmith commands must be validated before changing project files.",
    ]
    if category == "image_to_led":
        assumptions.extend(
            [
                "Assume LED placement should become structured KiCad operations, not pixels.",
                "Assume current limiting is required for every LED string.",
            ]
        )
    if category == "schematic_edit":
        assumptions.append("Assume edits should start in the schematic before PCB layout.")
    return assumptions


def _missing_questions(category: str) -> list[str]:
    if category == "image_to_led":
        return [
            "Ask for the reference image before placing LEDs along image paths.",
            "Ask for supply voltage, LED color/type, target board size, and manufacturing limits.",
        ]
    if category == "schematic_edit":
        return [
            "Ask for missing component values or part numbers before applying edits.",
        ]
    if category == "review":
        return [
            "Ask what risk level to prioritize if the user wants more than ERC/DRC review.",
        ]
    return [
        "Ask the user to clarify whether they want review, schematic edits, layout, or export.",
    ]


def _safety_checks(category: str) -> list[str]:
    checks = [
        "Run ERC/DRC and summarize blocking issues before edits.",
        "Require user approval before applying generated commands.",
    ]
    if category == "image_to_led":
        checks.extend(
            [
                "Check LED current limiting and polarity before approval.",
                "Check board edge clearance and silkscreen overlap before manufacturing export.",
            ]
        )
    if category == "schematic_edit":
        checks.append("Check nets, polarity, and unconnected pins after schematic edits.")
    return checks


def _required_capabilities(category: str) -> list[str]:
    capabilities = ["project_context", "kicad_validation", "command_approval"]
    if category == "image_to_led":
        capabilities.extend(
            ["vision_reference_processing", "placement_planning", "power_budgeting"]
        )
    elif category == "schematic_edit":
        capabilities.append("schematic_command_generation")
    elif category == "review":
        capabilities.append("issue_summarization")
    else:
        capabilities.append("intent_clarification")
    return capabilities


def _mentions_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


__all__ = [
    "AI_BRIEF_SCHEMA",
    "build_ai_brief",
    "write_ai_brief",
]
