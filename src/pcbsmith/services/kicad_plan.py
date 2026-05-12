from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeGuard

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from pcbsmith.core.geom import Point
from pcbsmith.services.project_io import (
    load_board,
    load_project,
    load_schematic,
    save_board,
    save_schematic,
)
from pcbsmith.services.schematic_commands import (
    AddLabelCommand,
    AddWireCommand,
    BoardCommand,
    PlaceSymbolCommand,
    PlaceTextCommand,
    PlanCommand,
    RouteSegmentCommand,
    SchematicCommand,
    apply_board_command,
    apply_schematic_command,
)


class KiCadPlanError(RuntimeError):
    pass


class KiCadPlanPackage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    description: str = ""
    schematic: str
    commands: tuple[PlanCommand, ...] = Field(min_length=1)


class KiCadPlanResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    applied: bool
    changed_symbol_count: int
    changed_wire_count: int
    lines: tuple[str, ...]


_PACKAGE_ADAPTER = TypeAdapter(KiCadPlanPackage)


def load_kicad_plan_package(path: Path) -> KiCadPlanPackage:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _PACKAGE_ADAPTER.validate_python(raw)
    except FileNotFoundError as exc:
        raise KiCadPlanError(f"Plan package not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise KiCadPlanError(f"Invalid plan package: {path}") from exc
    except ValidationError as exc:
        messages = [str(error["msg"]) for error in exc.errors()]
        first_error = next(
            (
                message
                for message in messages
                if "routing is not enabled" in message
                or "text is not enabled" in message
            ),
            messages[0],
        )
        raise KiCadPlanError(f"Invalid plan package: {path}: {first_error}") from exc


def run_kicad_plan(
    project_dir: Path,
    package_path: Path,
    *,
    apply: bool,
) -> KiCadPlanResult:
    package = load_kicad_plan_package(package_path)
    project = load_project(project_dir)
    if package.schematic not in project.schematics:
        raise KiCadPlanError(f"Target schematic is not in project: {package.schematic}")

    board_path = project.boards[0] if project.boards else None
    if board_path is None and any(_is_board_command(command) for command in package.commands):
        raise KiCadPlanError("Project has no board file for board commands")

    schematic = load_schematic(project_dir, package.schematic)
    board = load_board(project_dir, board_path) if board_path is not None else None
    summaries = tuple(_summarize_command(command) for command in package.commands)
    updated = schematic
    updated_board = board
    messages: list[str] = []
    for command in package.commands:
        if _is_schematic_command(command):
            command_result = apply_schematic_command(updated, command)
            updated = command_result.schematic
            messages.extend(command_result.messages)
        elif _is_board_command(command):
            if updated_board is None:
                raise KiCadPlanError("Project has no board file for board commands")
            updated_board = apply_board_command(updated_board, command)

    lines = [
        f"Plan: {package.description or '(no description)'}",
        f"Target schematic: {package.schematic}",
    ]
    if any(_is_board_command(command) for command in package.commands):
        lines.append(f"Target board: {board_path}")
    lines.extend(f"{index}. {summary}" for index, summary in enumerate(summaries, start=1))
    if not apply:
        lines.append("Dry run only; no files changed. Pass --apply to save changes.")
        return KiCadPlanResult(
            applied=False,
            changed_symbol_count=len(updated.symbols) - len(schematic.symbols),
            changed_wire_count=len(updated.wires) - len(schematic.wires),
            lines=tuple(lines),
        )

    save_schematic(project_dir, package.schematic, updated)
    if updated_board is not None:
        if board_path is None:
            raise KiCadPlanError("Project has no board file for board commands")
        save_board(project_dir, board_path, updated_board)
    _append_action_log(
        project_dir,
        package_path=package_path,
        package=package,
        summaries=summaries,
        messages=tuple(messages),
    )
    lines.append(f"Applied {len(package.commands)} commands and wrote .pcbsmith/action-log.jsonl")
    return KiCadPlanResult(
        applied=True,
        changed_symbol_count=len(updated.symbols) - len(schematic.symbols),
        changed_wire_count=len(updated.wires) - len(schematic.wires),
        lines=tuple(lines),
    )


def _is_schematic_command(command: PlanCommand) -> TypeGuard[SchematicCommand]:
    return isinstance(command, PlaceSymbolCommand | AddWireCommand | AddLabelCommand)


def _is_board_command(command: PlanCommand) -> TypeGuard[BoardCommand]:
    return isinstance(command, RouteSegmentCommand | PlaceTextCommand)


def _summarize_command(command: PlanCommand) -> str:
    if isinstance(command, PlaceSymbolCommand):
        return (
            f"place_symbol {command.symbol_id} value={command.value} "
            f"at {_format_point(command.position)}"
        )
    if isinstance(command, AddWireCommand):
        first = command.points[0]
        last = command.points[-1]
        return f"add_wire {_format_point(first)} -> {_format_point(last)}"
    if isinstance(command, AddLabelCommand):
        return f"add_label {command.name} at {_format_point(command.position)}"
    if isinstance(command, RouteSegmentCommand):
        first = command.points[0]
        last = command.points[-1]
        return (
            f"route_segment {command.net_name} on {command.layer} "
            f"{_format_point(first)} -> {_format_point(last)} width={_format_mm(command.width)} mm"
        )
    if isinstance(command, PlaceTextCommand):
        return f"place_text {command.text} on {command.layer} at {_format_point(command.position)}"


def _format_point(point: Point) -> str:
    return f"{_format_mm(point.x)}, {_format_mm(point.y)} mm"


def _format_mm(nm: int) -> str:
    return f"{nm / 1_000_000:g}"


def _append_action_log(
    project_dir: Path,
    *,
    package_path: Path,
    package: KiCadPlanPackage,
    summaries: tuple[str, ...],
    messages: tuple[str, ...],
) -> None:
    log_dir = project_dir / ".pcbsmith"
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "package_path": str(package_path),
        "description": package.description,
        "target_schematic": package.schematic,
        "command_count": len(package.commands),
        "summaries": list(summaries),
        "messages": list(messages),
    }
    with (log_dir / "action-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


__all__ = [
    "KiCadPlanError",
    "KiCadPlanPackage",
    "KiCadPlanResult",
    "load_kicad_plan_package",
    "run_kicad_plan",
]
