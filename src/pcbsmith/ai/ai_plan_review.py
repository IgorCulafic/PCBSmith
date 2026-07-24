from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pcbsmith.ai.ai_plan_check import check_ai_plan
from pcbsmith.kicad.kicad_plan import run_kicad_plan


class AIPlanReviewResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    applied: bool
    lines: tuple[str, ...]
    exit_code: int


def run_ai_plan_review(
    project_dir: Path,
    planner_package_path: Path,
    candidate_plan_path: Path,
    *,
    apply: bool,
) -> AIPlanReviewResult:
    check_result = check_ai_plan(planner_package_path, candidate_plan_path)
    if not check_result.valid:
        return AIPlanReviewResult(
            applied=False,
            lines=check_result.lines,
            exit_code=check_result.exit_code,
        )

    plan_result = run_kicad_plan(
        project_dir,
        candidate_plan_path,
        apply=apply,
    )
    return AIPlanReviewResult(
        applied=plan_result.applied,
        lines=(
            *check_result.lines,
            "Approval preview:",
            *plan_result.lines,
        ),
        exit_code=0,
    )


__all__ = [
    "AIPlanReviewResult",
    "run_ai_plan_review",
]
