from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.services.ai_planner_package import (
    AI_PLANNER_PACKAGE_SCHEMA,
    build_ai_planner_package,
    write_ai_planner_package,
)


def _brief() -> dict[str, object]:
    return {
        "schema": "pcbsmith-ai-brief-v1",
        "request": {"text": "Add a resistor to the LED"},
        "intent": {
            "category": "schematic_edit",
            "next_operation_type": "schematic_edit",
            "confidence": "medium",
        },
        "assumptions": ["Assume KiCad is the authoritative CAD editor/backend."],
        "missing_questions": ["Ask for missing component values."],
        "safety_checks": ["Require user approval before applying generated commands."],
        "required_capabilities": ["schematic_command_generation"],
        "context": {
            "project": {
                "name": "LED Series Circuit",
                "schematics": ["schematics/main.sch.json"],
            }
        },
    }


def test_build_ai_planner_package_wraps_brief_with_output_contract() -> None:
    package = build_ai_planner_package(_brief())

    assert package["schema"] == AI_PLANNER_PACKAGE_SCHEMA
    assert package["planner_mode"] == "structured_command_proposal"
    assert package["brief"]["request"]["text"] == "Add a resistor to the LED"
    assert package["allowed_command_types"] == [
        "place_symbol",
        "add_wire",
        "add_label",
        "route_segment",
        "place_text",
    ]
    assert package["target_plan_schema"]["version"] == 1
    assert package["target_plan_schema"]["schematic"] == "schematics/main.sch.json"
    assert package["target_plan_schema"]["commands"][0]["type"] == "place_symbol"
    assert package["target_plan_schema"]["commands"][1]["type"] == "add_wire"
    assert package["target_plan_schema"]["commands"][2]["type"] == "add_label"
    assert package["target_plan_schema"]["commands"][3]["type"] == "route_segment"
    assert package["target_plan_schema"]["commands"][4]["type"] == "place_text"
    assert "Return only JSON matching target_plan_schema." in package["planner_rules"]
    assert "Do not invent unknown symbols, footprints, pins, or KiCad capabilities." in (
        package["planner_rules"]
    )
    assert "Prefer 45-degree/mitered PCB routing for CAD polish when practical." in (
        package["planner_rules"]
    )
    assert "Do not treat 45-degree routing as an electrical hard rule; DRC wins." in (
        package["planner_rules"]
    )
    assert package["component_selection"] == {
        "schema": "pcbsmith-component-selection-tool-v1",
        "cli_command": "component-selection <component-knowledge-index> <intent>",
        "preferred_mounting_default": "smd",
        "supported_intents": [
            "555-timer",
            "isolated-power",
            "led-current-limit",
            "low-side-switch",
            "power-entry",
            "relay-switching",
            "zener-protection",
        ],
        "selection_statuses": ["preferred", "candidate", "needs_review"],
        "instructions": [
            "Use an intent when choosing a part role instead of inventing symbols or footprints.",
            "Treat needs_review candidates as requiring user approval or deeper datasheet review.",
        ],
    }
    assert "Use component_selection supported_intents before choosing catalog parts." in (
        package["planner_rules"]
    )
    assert package["circuit_rules"] == {
        "schema": "pcbsmith-circuit-rules-tool-v1",
        "cli_command": "circuit-rules <intent> --param key=value",
        "supported_intents": [
            "555-astable",
            "555-pwm",
            "led-current-limit",
            "low-side-switch",
            "power-entry",
            "rc-filter",
            "voltage-divider",
        ],
        "instructions": [
            "Use circuit rules to check electrical assumptions before proposing board edits.",
            "Treat warning and error findings as revision inputs, not as fabrication approval.",
        ],
    }
    assert (
        "Use circuit_rules supported_intents to check electrical assumptions before board edits."
        in package["planner_rules"]
    )


def test_build_ai_planner_package_marks_review_only_brief_as_no_edit() -> None:
    brief = _brief()
    brief["intent"] = {
        "category": "review",
        "next_operation_type": "review_only",
        "confidence": "medium",
    }

    package = build_ai_planner_package(brief)

    assert package["planner_mode"] == "review_response"
    assert package["allowed_command_types"] == []
    assert package["target_plan_schema"] is None
    assert "component_selection" in package
    assert "circuit_rules" in package
    assert "Do not propose project mutations for review_only briefs." in (
        package["planner_rules"]
    )


def test_build_ai_planner_package_rejects_wrong_brief_schema() -> None:
    try:
        build_ai_planner_package({"schema": "wrong"})
    except ValueError as exc:
        assert str(exc) == "Unsupported AI brief schema: wrong"
    else:
        raise AssertionError("Expected ValueError")


def test_write_ai_planner_package_reads_brief_and_writes_pretty_json(tmp_path: Path) -> None:
    brief_path = tmp_path / "brief.json"
    output_path = tmp_path / "planner-package.json"
    brief_path.write_text(json.dumps(_brief()), encoding="utf-8")

    write_ai_planner_package(brief_path, output_path)

    text = output_path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["schema"] == AI_PLANNER_PACKAGE_SCHEMA
    assert text.endswith("\n")
