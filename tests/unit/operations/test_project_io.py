from __future__ import annotations

from pathlib import Path

import pytest

from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic
from pcbsmith.operations.project_io import (
    ProjectIOError,
    create_project,
    load_board,
    load_project,
    load_schematic,
    save_board,
    save_project,
    save_schematic,
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


@pytest.mark.parametrize("path", ["../outside.sch.json", None])
def test_load_schematic_rejects_paths_outside_project(
    tmp_path: Path, path: str | None
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside.sch.json"
    outside.write_text(Schematic(id="outside").model_dump_json(), encoding="utf-8")

    unsafe_path = str(outside) if path is None else path

    with pytest.raises(ProjectIOError):
        load_schematic(project_dir, unsafe_path)


@pytest.mark.parametrize("path", ["../outside.brd.json", None])
def test_load_board_rejects_paths_outside_project(tmp_path: Path, path: str | None) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside.brd.json"
    outside.write_text(Board(id="outside").model_dump_json(), encoding="utf-8")

    unsafe_path = str(outside) if path is None else path

    with pytest.raises(ProjectIOError):
        load_board(project_dir, unsafe_path)


@pytest.mark.parametrize("path", ["../escaped.sch.json", None])
def test_save_schematic_rejects_paths_outside_project(
    tmp_path: Path, path: str | None
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    escaped = tmp_path / "escaped.sch.json"
    unsafe_path = str(escaped) if path is None else path

    with pytest.raises(ProjectIOError):
        save_schematic(project_dir, unsafe_path, Schematic(id="escaped"))

    assert not escaped.exists()


@pytest.mark.parametrize("path", ["../escaped.brd.json", None])
def test_save_board_rejects_paths_outside_project(tmp_path: Path, path: str | None) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    escaped = tmp_path / "escaped.brd.json"
    unsafe_path = str(escaped) if path is None else path

    with pytest.raises(ProjectIOError):
        save_board(project_dir, unsafe_path, Board(id="escaped"))

    assert not escaped.exists()
