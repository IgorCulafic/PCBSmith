"""Compatibility imports for project persistence operations."""

from __future__ import annotations

from pcbsmith.operations.project_io import (
    PROJECT_FILE,
    ProjectIOError,
    create_project,
    load_board,
    load_project,
    load_schematic,
    save_board,
    save_project,
    save_schematic,
)

__all__ = [
    "PROJECT_FILE",
    "ProjectIOError",
    "create_project",
    "load_board",
    "load_project",
    "load_schematic",
    "save_board",
    "save_project",
    "save_schematic",
]
