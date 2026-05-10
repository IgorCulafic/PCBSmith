from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pcbsmith.services.ai_brief import write_ai_brief
from pcbsmith.services.ai_openai_compatible_plan import (
    OpenAICompatibleRunner,
    write_openai_compatible_plan,
)
from pcbsmith.services.ai_plan_review import run_ai_plan_review
from pcbsmith.services.ai_planner_package import write_ai_planner_package


class OpenAICompatibleReviewResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    applied: bool
    exit_code: int
    brief_path: str
    planner_package_path: str
    candidate_plan_path: str
    lines: tuple[str, ...]


def run_openai_compatible_review(
    project_dir: Path,
    request_path: Path,
    output_dir: Path,
    *,
    base_url: str,
    model: str,
    api_key: str | None = None,
    timeout_seconds: float = 60,
    use_json_mode: bool = True,
    kicad_project_dir: Path | None = None,
    apply: bool = False,
    runner: OpenAICompatibleRunner | None = None,
) -> OpenAICompatibleReviewResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    brief_path = output_dir / "ai-brief.json"
    planner_package_path = output_dir / "ai-planner-package.json"
    candidate_plan_path = output_dir / "candidate-plan.json"

    request_text = request_path.read_text(encoding="utf-8")
    write_ai_brief(
        project_dir,
        request_text,
        brief_path,
        kicad_project_dir=kicad_project_dir,
    )
    write_ai_planner_package(brief_path, planner_package_path)
    write_openai_compatible_plan(
        planner_package_path,
        candidate_plan_path,
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        use_json_mode=use_json_mode,
        runner=runner,
    )
    review = run_ai_plan_review(
        project_dir,
        planner_package_path,
        candidate_plan_path,
        apply=apply,
    )
    return OpenAICompatibleReviewResult(
        applied=review.applied,
        exit_code=review.exit_code,
        brief_path=str(brief_path),
        planner_package_path=str(planner_package_path),
        candidate_plan_path=str(candidate_plan_path),
        lines=(
            f"AI OpenAI-compatible review bundle: {output_dir}",
            f"Brief: {brief_path}",
            f"Planner package: {planner_package_path}",
            f"Candidate plan: {candidate_plan_path}",
            *review.lines,
        ),
    )


__all__ = [
    "OpenAICompatibleReviewResult",
    "run_openai_compatible_review",
]
