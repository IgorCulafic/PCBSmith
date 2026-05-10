from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.services.kicad_plan import (
    KiCadPlanError,
    load_kicad_plan_package,
    run_kicad_plan,
)
from pcbsmith.services.project_io import create_project, load_schematic


def _write_plan(path: Path, *, schematic: str = "schematics/main.sch.json") -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "description": "Add one resistor and one wire",
                "schematic": schematic,
                "commands": [
                    {
                        "type": "place_symbol",
                        "symbol_id": "stdlib:R",
                        "value": "330",
                        "position": {"x": 15_240_000, "y": 0},
                        "rotation_deg": 0,
                        "footprint_id": "stdlib:R_0603",
                    },
                    {
                        "type": "add_wire",
                        "points": [
                            {"x": 0, "y": 0},
                            {"x": 10_160_000, "y": 0},
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_load_kicad_plan_package_parses_structured_commands(tmp_path: Path) -> None:
    package_path = tmp_path / "plan.json"
    _write_plan(package_path)

    package = load_kicad_plan_package(package_path)

    assert package.version == 1
    assert package.description == "Add one resistor and one wire"
    assert package.schematic == "schematics/main.sch.json"
    assert [command.type for command in package.commands] == ["place_symbol", "add_wire"]


def test_run_kicad_plan_dry_run_leaves_project_unchanged(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    package_path = tmp_path / "plan.json"
    create_project(project_dir, "Plan Demo")
    _write_plan(package_path)

    before = (project_dir / "schematics" / "main.sch.json").read_text(encoding="utf-8")
    result = run_kicad_plan(project_dir, package_path, apply=False)
    after = (project_dir / "schematics" / "main.sch.json").read_text(encoding="utf-8")

    assert result.applied is False
    assert result.changed_symbol_count == 1
    assert result.changed_wire_count == 1
    assert result.lines == (
        "Plan: Add one resistor and one wire",
        "Target schematic: schematics/main.sch.json",
        "1. place_symbol stdlib:R value=330 at 15.24, 0 mm",
        "2. add_wire 0, 0 mm -> 10.16, 0 mm",
        "Dry run only; no files changed. Pass --apply to save changes.",
    )
    assert before == after
    assert not (project_dir / ".pcbsmith" / "action-log.jsonl").exists()


def test_run_kicad_plan_apply_saves_schematic_and_action_log(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    package_path = tmp_path / "plan.json"
    create_project(project_dir, "Plan Demo")
    _write_plan(package_path)

    result = run_kicad_plan(project_dir, package_path, apply=True)
    schematic = load_schematic(project_dir, "schematics/main.sch.json")
    log_lines = (project_dir / ".pcbsmith" / "action-log.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    log_entry = json.loads(log_lines[0])

    assert result.applied is True
    assert result.lines[-1] == "Applied 2 commands and wrote .pcbsmith/action-log.jsonl"
    assert len(schematic.symbols) == 1
    assert schematic.symbols[0].reference == "R1"
    assert len(schematic.wires) == 1
    assert log_entry["description"] == "Add one resistor and one wire"
    assert log_entry["target_schematic"] == "schematics/main.sch.json"
    assert log_entry["command_count"] == 2
    assert log_entry["summaries"] == [
        "place_symbol stdlib:R value=330 at 15.24, 0 mm",
        "add_wire 0, 0 mm -> 10.16, 0 mm",
    ]


def test_run_kicad_plan_rejects_schematic_not_in_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    package_path = tmp_path / "plan.json"
    create_project(project_dir, "Plan Demo")
    _write_plan(package_path, schematic="schematics/other.sch.json")

    with pytest.raises(KiCadPlanError, match="Target schematic is not in project"):
        run_kicad_plan(project_dir, package_path, apply=False)
