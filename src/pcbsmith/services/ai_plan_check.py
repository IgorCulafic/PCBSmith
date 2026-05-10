from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from pcbsmith.services.ai_planner_package import AI_PLANNER_PACKAGE_SCHEMA
from pcbsmith.services.kicad_plan import KiCadPlanPackage


class AIPlanCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    lines: tuple[str, ...]
    exit_code: int


_PLAN_ADAPTER = TypeAdapter(KiCadPlanPackage)


def check_ai_plan(planner_package_path: Path, candidate_plan_path: Path) -> AIPlanCheckResult:
    try:
        planner_package = _read_json(planner_package_path)
        candidate_raw = _read_json(candidate_plan_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(f"could not read plan inputs: {exc}")

    if planner_package.get("schema") != AI_PLANNER_PACKAGE_SCHEMA:
        return _invalid(f"unsupported planner package schema: {planner_package.get('schema')}")

    if planner_package.get("planner_mode") == "review_response":
        return _invalid("planner package is review-only and does not allow command plans")

    try:
        candidate = _PLAN_ADAPTER.validate_python(candidate_raw)
    except ValidationError as exc:
        return _invalid(f"candidate plan schema is invalid: {exc.errors()[0]['msg']}")

    expected_schematic = _expected_schematic(planner_package)
    if expected_schematic is not None and candidate.schematic != expected_schematic:
        return _invalid(
            f"target schematic does not match planner package: {candidate.schematic}"
        )

    allowed_types = set(_allowed_command_types(planner_package))
    for command in candidate.commands:
        if command.type not in allowed_types:
            return _invalid(f"command type is not allowed: {command.type}")

    return AIPlanCheckResult(
        valid=True,
        lines=(
            "AI plan: valid",
            f"Target schematic: {candidate.schematic}",
            f"Commands: {len(candidate.commands)}",
        ),
        exit_code=0,
    )


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _expected_schematic(planner_package: dict[str, Any]) -> str | None:
    target_plan_schema = planner_package.get("target_plan_schema")
    if not isinstance(target_plan_schema, dict):
        return None
    schematic = target_plan_schema.get("schematic")
    return schematic if isinstance(schematic, str) else None


def _allowed_command_types(planner_package: dict[str, Any]) -> list[str]:
    raw = planner_package.get("allowed_command_types", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


def _invalid(problem: str) -> AIPlanCheckResult:
    return AIPlanCheckResult(
        valid=False,
        lines=(
            "AI plan: invalid",
            f"Problem: {problem}",
        ),
        exit_code=1,
    )


__all__ = [
    "AIPlanCheckResult",
    "check_ai_plan",
]
