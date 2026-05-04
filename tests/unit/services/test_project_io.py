from __future__ import annotations

from pathlib import Path

from pcbsmith.core.project import Project
from pcbsmith.services.project_io import create_project, load_project, save_project


def test_create_project_writes_expected_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    create_project(project_dir, "Demo")
    assert (project_dir / "project.pcbsmith.json").exists()
    assert (project_dir / "schematics" / "main.sch.json").exists()
    assert (project_dir / "boards" / "main.brd.json").exists()


def test_project_round_trip(tmp_path: Path) -> None:
    project_dir = tmp_path / "roundtrip"
    project = Project(name="Round Trip")
    save_project(project_dir, project)
    loaded = load_project(project_dir)
    assert loaded == project
