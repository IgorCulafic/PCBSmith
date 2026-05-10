from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from pcbsmith.core.geom import Point
from pcbsmith.services.project_io import (
    load_project,
    load_schematic,
    save_schematic,
)
from pcbsmith.services.schematic_commands import (
    AddLabelCommand,
    AddWireCommand,
    PlaceSymbolCommand,
    SchematicCommand,
    apply_schematic_command,
)


class KiCadPlanError(RuntimeError):
    pass


class KiCadPlanPackage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    description: str = ""
    schematic: str
    commands: tuple[SchematicCommand, ...] = Field(min_length=1)


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
    except (json.JSONDecodeError, ValidationError) as exc:
        raise KiCadPlanError(f"Invalid plan package: {path}") from exc


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

    schematic = load_schematic(project_dir, package.schematic)
    summaries = tuple(_summarize_command(command) for command in package.commands)
    updated = schematic
    messages: list[str] = []
    for command in package.commands:
        command_result = apply_schematic_command(updated, command)
        updated = command_result.schematic
        messages.extend(command_result.messages)

    lines = [
        f"Plan: {package.description or '(no description)'}",
        f"Target schematic: {package.schematic}",
        *(f"{index}. {summary}" for index, summary in enumerate(summaries, start=1)),
    ]
    if not apply:
        lines.append("Dry run only; no files changed. Pass --apply to save changes.")
        return KiCadPlanResult(
            applied=False,
            changed_symbol_count=len(updated.symbols) - len(schematic.symbols),
            changed_wire_count=len(updated.wires) - len(schematic.wires),
            lines=tuple(lines),
        )

    save_schematic(project_dir, package.schematic, updated)
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


def _summarize_command(command: SchematicCommand) -> str:
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
