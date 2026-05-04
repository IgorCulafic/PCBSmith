from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic

PROJECT_FILE = "project.pcbsmith.json"


class ProjectIOError(RuntimeError):
    pass


def _write_json(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data + "\n", encoding="utf-8")


def _resolve_project_relative_path(project_dir: Path, relative_path: str) -> Path:
    requested_path = Path(relative_path)
    if requested_path.is_absolute():
        raise ProjectIOError(f"Project path must be relative: {relative_path}")

    project_root = project_dir.resolve()
    path = (project_root / requested_path).resolve(strict=False)
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise ProjectIOError(f"Project path escapes project directory: {relative_path}") from exc
    return path


def save_project(project_dir: Path, project: Project) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    _write_json(project_dir / PROJECT_FILE, project.model_dump_json(indent=2))


def load_project(project_dir: Path) -> Project:
    path = project_dir / PROJECT_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Project.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Project file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid project file: {path}") from exc


def save_schematic(project_dir: Path, relative_path: str, schematic: Schematic) -> None:
    path = _resolve_project_relative_path(project_dir, relative_path)
    _write_json(path, schematic.model_dump_json(indent=2))


def load_schematic(project_dir: Path, relative_path: str) -> Schematic:
    path = _resolve_project_relative_path(project_dir, relative_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Schematic.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Schematic file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid schematic file: {path}") from exc


def save_board(project_dir: Path, relative_path: str, board: Board) -> None:
    path = _resolve_project_relative_path(project_dir, relative_path)
    _write_json(path, board.model_dump_json(indent=2))


def load_board(project_dir: Path, relative_path: str) -> Board:
    path = _resolve_project_relative_path(project_dir, relative_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Board.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Board file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid board file: {path}") from exc


def create_project(project_dir: Path, name: str) -> Project:
    project = Project(name=name)
    save_project(project_dir, project)
    save_schematic(project_dir, project.schematics[0], Schematic(id="main"))
    save_board(project_dir, project.boards[0], Board(id="main"))
    return project
