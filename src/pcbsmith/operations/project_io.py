from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic
from pcbsmith.operations.file_transaction import (
    FileTransactionError,
    commit_project_files,
    project_path,
    recover_project_files,
    require_complete_project,
)

PROJECT_FILE = "project.pcbsmith.json"


class ProjectIOError(RuntimeError):
    pass


def _require_complete(project_dir: Path) -> None:
    try:
        require_complete_project(project_dir)
    except (OSError, FileTransactionError) as exc:
        raise ProjectIOError(str(exc)) from exc


def save_project_files(
    project_dir: Path,
    payloads: dict[str, bytes],
    *,
    append_payloads: dict[str, bytes] | None = None,
    create_only: bool = False,
    expected_sha256s: dict[str, str] | None = None,
) -> str:
    try:
        return commit_project_files(
            project_dir,
            payloads,
            append_payloads=append_payloads,
            create_only=create_only,
            expected_sha256s=expected_sha256s,
        )
    except (OSError, FileTransactionError) as exc:
        raise ProjectIOError(str(exc)) from exc


def recover_project(project_dir: Path) -> bool:
    try:
        return recover_project_files(project_dir)
    except (OSError, ValueError, KeyError, TypeError, FileTransactionError) as exc:
        raise ProjectIOError(f"Cannot recover project: {exc}") from exc


def _resolve_project_relative_path(project_dir: Path, relative_path: str | Path) -> Path:
    try:
        return project_path(project_dir, str(relative_path))
    except FileTransactionError as exc:
        raise ProjectIOError(str(exc)) from exc


def save_project(project_dir: Path, project: Project) -> None:
    save_project_files(
        project_dir, {PROJECT_FILE: (project.model_dump_json(indent=2) + "\n").encode()}
    )


def load_project(project_dir: Path) -> Project:
    _require_complete(project_dir)
    path = project_dir / PROJECT_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Project.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Project file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid project file: {path}") from exc
    except (OSError, UnicodeError) as exc:
        raise ProjectIOError(f"Cannot read project file {path}: {exc}") from exc


def save_schematic(
    project_dir: Path,
    relative_path: str | Path,
    schematic: Schematic,
    *,
    expected_sha256s: dict[str, str] | None = None,
) -> None:
    _resolve_project_relative_path(project_dir, relative_path)
    save_project_files(
        project_dir,
        {str(relative_path): (schematic.model_dump_json(indent=2) + "\n").encode()},
        expected_sha256s=expected_sha256s,
    )


def load_schematic(project_dir: Path, relative_path: str | Path) -> Schematic:
    _require_complete(project_dir)
    path = _resolve_project_relative_path(project_dir, relative_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Schematic.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Schematic file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid schematic file: {path}") from exc
    except (OSError, UnicodeError) as exc:
        raise ProjectIOError(f"Cannot read schematic file {path}: {exc}") from exc


def save_board(project_dir: Path, relative_path: str | Path, board: Board) -> None:
    _resolve_project_relative_path(project_dir, relative_path)
    save_project_files(
        project_dir, {str(relative_path): (board.model_dump_json(indent=2) + "\n").encode()}
    )


def load_board(project_dir: Path, relative_path: str | Path) -> Board:
    _require_complete(project_dir)
    path = _resolve_project_relative_path(project_dir, relative_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Board.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Board file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid board file: {path}") from exc
    except (OSError, UnicodeError) as exc:
        raise ProjectIOError(f"Cannot read board file {path}: {exc}") from exc


def create_project(project_dir: Path, name: str) -> Project:
    project = Project(name=name)
    payloads = {
        PROJECT_FILE: (project.model_dump_json(indent=2) + "\n").encode(),
        project.schematics[0]: (Schematic(id="main").model_dump_json(indent=2) + "\n").encode(),
        project.boards[0]: (Board(id="main").model_dump_json(indent=2) + "\n").encode(),
    }
    for relative_path in payloads:
        target = _resolve_project_relative_path(project_dir, relative_path)
        if target.exists():
            raise ProjectIOError(f"Project artifact already exists: {target}")
    save_project_files(project_dir, payloads, create_only=True)
    return project
