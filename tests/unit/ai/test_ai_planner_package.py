from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.ai.ai_planner_package import (
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
    assert (
        "Do not invent unknown symbols, footprints, pins, or KiCad capabilities."
        in (package["planner_rules"])
    )
    assert (
        "Prefer 45-degree/mitered PCB routing for CAD polish when practical."
        in (package["planner_rules"])
    )
    assert (
        "Do not treat 45-degree routing as an electrical hard rule; DRC wins."
        in (package["planner_rules"])
    )
    assert (
        "Use conventional EDA reference designators: R, C, LED, D, U, J, Q, L, SW, F, K, T, TP."
        in package["planner_rules"]
    )
    assert (
        "Keep references on silkscreen; keep values off silkscreen unless "
        "educational/showcase mode asks for them." in package["planner_rules"]
    )
    assert package["calculators"] == {
        "schema": "pcbsmith-calculator-tool-v1",
        "cli_command": "calculator <calculator-name> --param key=value",
        "supported_calculators": [
            "lc-resonance",
            "pcb-spiral-coil-estimate",
        ],
        "instructions": [
            "Use calculators for engineering math instead of freehand model arithmetic.",
            "Treat error status as blocking for generation.",
            "Treat warning status as requiring review or conservative assumptions.",
        ],
    }
    assert (
        "Use calculators supported_calculators for engineering math instead of "
        "freehand arithmetic." in package["planner_rules"]
    )
    assert package["circuit_topologies"] == {
        "schema": "pcbsmith-circuit-topology-tool-v1",
        "cli_command": "circuit-topologies <intent>",
        "supported_intents": [
            "led-indicator",
            "metal-detector",
            "oscillator",
            "power-switching",
        ],
        "instructions": [
            "Select a circuit topology before choosing parts or laying out a board.",
            "Treat topology required_math_tools as hard prerequisites for generation.",
            "Honor do_not_use_rules when a familiar part is not justified by the topology.",
        ],
    }
    assert (
        "Choose a supported circuit topology before selecting parts for a new circuit family."
        in package["planner_rules"]
    )
    assert (
        "Run required math tools before generating schematics or PCB layout for that topology."
        in package["planner_rules"]
    )
    assert package["component_selection"] == {
        "schema": "pcbsmith-component-selection-tool-v1",
        "cli_command": "component-selection <component-knowledge-index> <intent>",
        "preferred_mounting_default": "smd",
        "supported_intents": [
            "555-timer",
            "bjt-npn-amplifier",
            "bjt-pnp-switch",
            "buzzer-output",
            "comparator-threshold",
            "isolated-power",
            "lc-sense-coil",
            "led-current-limit",
            "low-side-switch",
            "op-amp-buffer",
            "power-entry",
            "relay-switching",
            "terminal-power-input",
            "trim-adjustment",
            "zener-protection",
        ],
        "selection_statuses": ["preferred", "candidate", "needs_review"],
        "instructions": [
            "Use an intent when choosing a part role instead of inventing symbols or footprints.",
            "Treat needs_review candidates as requiring user approval or deeper datasheet review.",
        ],
    }
    assert (
        "Use component_selection supported_intents before choosing catalog parts."
        in (package["planner_rules"])
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
    assert package["board_feature_intent"] == {
        "schema": "pcbsmith-board-feature-intent-v1",
        "feature_kinds": [
            "silkscreen_artwork",
            "board_outline_geometry",
            "needs_clarification",
        ],
        "layer_rules": {
            "silkscreen_artwork": ["F.SilkS", "B.SilkS"],
            "board_outline_geometry": ["Edge.Cuts"],
        },
        "instructions": [
            "Treat logos, text, QR codes, labels, and printed artwork as silkscreen by default.",
            "Treat shaped boards, cutouts, notches, USB edges, and card-edge "
            "geometry as Edge.Cuts.",
            "When a request asks for both artwork and physical shape, split it "
            "into separate operations.",
            "Do not use silkscreen commands to change the physical board outline.",
        ],
    }
    assert (
        "Classify board artwork requests before planning: silkscreen artwork "
        "targets F.SilkS/B.SilkS." in package["planner_rules"]
    )
    assert (
        "Classify physical shape requests separately: board outlines and cutouts target Edge.Cuts."
        in package["planner_rules"]
    )
    assert package["silkscreen_artwork"] == {
        "schema": "pcbsmith-silkscreen-artwork-tool-v1",
        "allowed_layers": ["F.SilkS", "B.SilkS"],
        "allowed_graphics": ["line", "rect"],
        "modes": ["professional", "showcase"],
        "preflight_checks": [
            "inside_board_outline",
            "edge_margin",
            "minimum_text_size_mm",
            "minimum_stroke_width_mm",
            "copper_keepout",
        ],
        "instructions": [
            "Use silkscreen artwork for printed labels, logos, notes, and decorative text.",
            "Use native line and rectangle primitives for simple logo geometry when possible.",
            "Do not use this operation for physical board outlines or cutouts.",
            "Run preflight before applying artwork to a board.",
        ],
    }
    assert (
        "Run silkscreen artwork preflight before applying printed text or logos."
        in (package["planner_rules"])
    )
    assert package["board_outline_geometry"] == {
        "schema": "pcbsmith-board-outline-geometry-tool-v1",
        "allowed_layer": "Edge.Cuts",
        "loop_roles": ["outline", "cutout"],
        "preflight_checks": [
            "closed_edge_loop",
            "minimum_outline_size_mm",
            "minimum_stroke_width_mm",
            "cutout_inside_outline",
            "copper_edge_clearance",
        ],
        "instructions": [
            "Use board outline geometry for physical board shape, slots, and cutouts.",
            "Do not use this operation for silkscreen artwork.",
            "Keep Edge.Cuts geometry separate from copper, mask, and silkscreen layers.",
            "Run preflight before applying board outline geometry.",
        ],
    }
    assert (
        "Use Edge.Cuts only for physical board outlines and cutouts." in (package["planner_rules"])
    )
    assert (
        "Keep silkscreen logos/text in the silkscreen_artwork tool." in (package["planner_rules"])
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
    assert "calculators" in package
    assert "circuit_topologies" in package
    assert "component_selection" in package
    assert "circuit_rules" in package
    assert "board_feature_intent" in package
    assert "silkscreen_artwork" in package
    assert "board_outline_geometry" in package
    assert "Do not propose project mutations for review_only briefs." in (package["planner_rules"])


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
