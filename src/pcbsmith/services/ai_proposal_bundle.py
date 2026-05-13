from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pcbsmith.services.ai_plan_check import check_ai_plan
from pcbsmith.services.kicad_plan import run_kicad_plan
from pcbsmith.services.kicad_review_bundle import (
    KiCadReviewBundleResult,
    format_kicad_review_bundle_result,
    run_kicad_review_bundle,
)
from pcbsmith.services.revision_brief import (
    RevisionBrief,
    build_revision_brief,
    format_revision_brief,
    write_revision_brief,
)


class AIProposalBundleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    output_dir: Path
    staged_project_dir: Path
    kicad_review_dir: Path
    revision_brief_file: Path
    revision_brief: RevisionBrief
    review_bundle: KiCadReviewBundleResult
    lines: tuple[str, ...]
    exit_code: int


def run_ai_proposal_bundle(
    project_dir: Path,
    planner_package_path: Path,
    candidate_plan_path: Path,
    output_dir: Path,
    *,
    execute_kicad: bool = True,
) -> AIProposalBundleResult:
    check_result = check_ai_plan(planner_package_path, candidate_plan_path)
    if not check_result.valid:
        raise ValueError("\n".join(check_result.lines))

    _require_new_output_dir(project_dir, output_dir)
    staged_project_dir = output_dir / "pcbs-project"
    kicad_review_dir = output_dir / "kicad-review"
    output_dir.mkdir(parents=True)
    shutil.copytree(
        project_dir,
        staged_project_dir,
        ignore=shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
        ),
    )
    run_kicad_plan(staged_project_dir, candidate_plan_path, apply=True)
    review_bundle = run_kicad_review_bundle(
        staged_project_dir,
        kicad_review_dir,
        execute_kicad=execute_kicad,
    )
    revision_brief = build_revision_brief(
        plan_check=check_result,
        validation_report=review_bundle.validation_report,
        preview_report=review_bundle.preview_report,
        manufacturability_report=review_bundle.manufacturability_report,
    )
    revision_brief_file = output_dir / "revision-brief.json"
    write_revision_brief(revision_brief, revision_brief_file)

    lines = (
        f"AI proposal bundle: {output_dir}",
        f"Staged PCBSmith project: {staged_project_dir}",
        *check_result.lines,
        "Applied candidate plan to staged copy only.",
        *format_kicad_review_bundle_result(review_bundle),
        f"Revision brief: {revision_brief_file}",
        *format_revision_brief(revision_brief),
    )
    return AIProposalBundleResult(
        output_dir=output_dir,
        staged_project_dir=staged_project_dir,
        kicad_review_dir=kicad_review_dir,
        revision_brief_file=revision_brief_file,
        revision_brief=revision_brief,
        review_bundle=review_bundle,
        lines=lines,
        exit_code=review_bundle.exit_code,
    )


def _require_new_output_dir(project_dir: Path, output_dir: Path) -> None:
    if output_dir.exists():
        raise FileExistsError(f"AI proposal bundle target already exists: {output_dir}")
    project_root = project_dir.resolve()
    output_root = output_dir.resolve()
    if output_root == project_root or output_root.is_relative_to(project_root):
        raise ValueError("AI proposal bundle output cannot be inside the source project")


__all__ = [
    "AIProposalBundleResult",
    "run_ai_proposal_bundle",
]
