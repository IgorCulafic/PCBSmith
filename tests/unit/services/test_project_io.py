from __future__ import annotations

from pathlib import Path

from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic
from pcbsmith.services.project_io import (
    create_project,
    load_board,
    load_project,
    load_schematic,
    save_project,
)


def test_create_project_writes_expected_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    create_project(project_dir, "Demo")
    assert (project_dir / "project.pcbsmith.json").exists()
    assert (project_dir / "schematics" / "main.sch.json").exists()
    assert (project_dir / "boards" / "main.brd.json").exists()
    assert load_schematic(project_dir, "schematics/main.sch.json") == Schematic(id="main")
    assert load_board(project_dir, "boards/main.brd.json") == Board(id="main")


def test_project_round_trip(tmp_path: Path) -> None:
    project_dir = tmp_path / "roundtrip"
    project = Project(name="Round Trip")
    save_project(project_dir, project)
    loaded = load_project(project_dir)
    assert loaded == project


def test_voltage_divider_fixture_loads_referenced_design_files() -> None:
    fixture_dir = Path("tests/fixtures/voltage_divider")
    project = load_project(fixture_dir)
    schematics = [load_schematic(fixture_dir, path) for path in project.schematics]
    boards = [load_board(fixture_dir, path) for path in project.boards]

    assert project.name == "Voltage Divider"
    assert {schematic.id for schematic in schematics} >= {"main"}
    assert {board.id for board in boards} >= {"main"}
