from __future__ import annotations

import json
import shutil
from pathlib import Path

from pcbsmith.services.ai_context import build_ai_context, write_ai_context

FIXTURE = Path("tests/fixtures/led_series_circuit")


def test_build_ai_context_summarizes_project_and_schematic(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    shutil.copytree(FIXTURE, project_dir)

    context = build_ai_context(project_dir)

    assert context["schema"] == "pcbsmith-ai-context-v1"
    assert context["project"] == {
        "name": "LED Series Circuit",
        "version": 1,
        "schematics": ["schematics/main.sch.json"],
        "boards": ["boards/main.brd.json"],
    }
    assert context["ai_tools"]["component_selection"] == {
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
    assert context["ai_tools"]["circuit_rules"] == {
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
    assert context["schematics"] == [
        {
            "path": "schematics/main.sch.json",
            "id": "main",
            "symbol_count": 4,
            "wire_count": 3,
            "label_count": 3,
            "no_connect_count": 0,
            "symbols": [
                {
                    "reference": "V1",
                    "symbol_id": "stdlib:VCC",
                    "value": "VCC",
                    "position_mm": {"x": 0.0, "y": 0.0},
                    "rotation_deg": 0,
                    "footprint_id": None,
                },
                {
                    "reference": "R1",
                    "symbol_id": "stdlib:R",
                    "value": "330",
                    "position_mm": {"x": 15.24, "y": 0.0},
                    "rotation_deg": 0,
                    "footprint_id": "stdlib:R_0603",
                },
                {
                    "reference": "LED1",
                    "symbol_id": "stdlib:LED",
                    "value": "Red LED",
                    "position_mm": {"x": 40.64, "y": 0.0},
                    "rotation_deg": 0,
                    "footprint_id": "stdlib:LED_0603",
                },
                {
                    "reference": "G1",
                    "symbol_id": "stdlib:GND",
                    "value": "GND",
                    "position_mm": {"x": 60.96, "y": 0.0},
                    "rotation_deg": 0,
                    "footprint_id": None,
                },
            ],
        }
    ]


def test_build_ai_context_includes_kicad_reports_and_visual_refs(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    kicad_dir = tmp_path / "kicad"
    shutil.copytree(FIXTURE, project_dir)
    report_dir = kicad_dir / ".pcbsmith" / "kicad-reports"
    board_report_dir = kicad_dir / ".pcbsmith" / "board-reports"
    visual_dir = kicad_dir / ".pcbsmith" / "visual"
    report_dir.mkdir(parents=True)
    board_report_dir.mkdir(parents=True)
    visual_dir.mkdir(parents=True)
    (report_dir / "erc.json").write_text(
        json.dumps({"sheets": [{"violations": [{"type": "pin_not_connected"}]}]}),
        encoding="utf-8",
    )
    (report_dir / "drc.json").write_text(
        json.dumps({"violations": [], "unconnected_items": [{"type": "ratsnest"}]}),
        encoding="utf-8",
    )
    (board_report_dir / "manufacturability.json").write_text(
        json.dumps(
            {
                "schema": "pcbsmith-board-manufacturability-v1",
                "summary": {"finding_count": 1, "error_count": 0, "warning_count": 1},
                "findings": [{"code": "non_preferred_trace_angle"}],
            }
        ),
        encoding="utf-8",
    )
    (visual_dir / "schematic.svg").write_text("<svg />", encoding="utf-8")
    (visual_dir / "schematic.png").write_text("png", encoding="utf-8")

    context = build_ai_context(project_dir, kicad_project_dir=kicad_dir)

    assert context["kicad"] == {
        "project_dir": str(kicad_dir),
        "board_rules": {
            "routing_style": "prefer_45_mitered",
            "preferred_segment_angles": [0, 45, 90, 135, 180],
            "routing_style_authority": "cad_polish_preference",
            "drc_authority": "hard_rule",
            "trace_width_strategy": "classify_net_role_then_apply_default_width",
            "notes": [
                "Prefer cardinal or 45-degree trace segments when practical.",
                "Avoid very sharp trace turns; DRC and manufacturability checks win over style.",
            ],
        },
        "board_layers": [
            {"id": "F.Cu", "role": "front_copper", "routing": True},
            {"id": "B.Cu", "role": "back_copper", "routing": False},
            {"id": "F.SilkS", "role": "front_silkscreen", "routing": False},
            {"id": "B.SilkS", "role": "back_silkscreen", "routing": False},
            {"id": "Edge.Cuts", "role": "board_outline", "routing": False},
        ],
        "reports": [
            {
                "name": "erc",
                "path": str(report_dir / "erc.json"),
                "violations": 1,
                "unconnected_items": 0,
            },
            {
                "name": "drc",
                "path": str(report_dir / "drc.json"),
                "violations": 0,
                "unconnected_items": 1,
            },
            {
                "name": "manufacturability",
                "path": str(board_report_dir / "manufacturability.json"),
                "violations": 0,
                "unconnected_items": 0,
                "findings": 1,
                "errors": 0,
                "warnings": 1,
            },
        ],
        "visuals": [
            str(visual_dir / "schematic.png"),
            str(visual_dir / "schematic.svg"),
        ],
    }


def test_write_ai_context_writes_pretty_json(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    output_path = tmp_path / "context.json"
    shutil.copytree(FIXTURE, project_dir)

    write_ai_context(project_dir, output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-ai-context-v1"
    assert output_path.read_text(encoding="utf-8").endswith("\n")
