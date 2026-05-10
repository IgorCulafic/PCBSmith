from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pcbsmith.services.ai_context import write_ai_context
from pcbsmith.services.kicad_export import KiCadExportResult, export_pcbs_project_to_kicad
from pcbsmith.services.kicad_preview import KiCadPreviewReport, run_kicad_preview
from pcbsmith.services.kicad_validate import KiCadValidationReport, run_kicad_validation


class KiCadReviewBundleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    source_project_dir: Path
    output_project_dir: Path
    context_file: Path
    export_result: object
    validation_report: KiCadValidationReport
    preview_report: KiCadPreviewReport
    exit_code: int


def run_kicad_review_bundle(
    source_project_dir: Path,
    output_project_dir: Path,
    *,
    project_name: str | None = None,
    execute_kicad: bool = True,
    exporter: Callable[..., KiCadExportResult | object] = export_pcbs_project_to_kicad,
    validator: Callable[..., KiCadValidationReport] = run_kicad_validation,
    previewer: Callable[..., KiCadPreviewReport] = run_kicad_preview,
    context_writer: Callable[..., None] = write_ai_context,
) -> KiCadReviewBundleResult:
    export_result = exporter(
        source_project_dir,
        output_project_dir,
        project_name=project_name,
    )
    validation_report = validator(output_project_dir, execute=execute_kicad)
    preview_report = previewer(output_project_dir, execute=execute_kicad)
    context_file = output_project_dir / "ai-context.json"
    context_writer(
        source_project_dir,
        context_file,
        kicad_project_dir=output_project_dir,
    )

    return KiCadReviewBundleResult(
        source_project_dir=source_project_dir,
        output_project_dir=output_project_dir,
        context_file=context_file,
        export_result=export_result,
        validation_report=validation_report,
        preview_report=preview_report,
        exit_code=max(validation_report.exit_code, preview_report.exit_code),
    )


def format_kicad_review_bundle_result(result: KiCadReviewBundleResult) -> list[str]:
    return [
        f"Review bundle: {result.output_project_dir}",
        f"Exported KiCad handoff: {result.output_project_dir}",
        f"Validation: {_validation_status(result.validation_report)}",
        f"Preview: {_preview_status(result.preview_report)}",
        f"AI context: {result.context_file}",
    ]


def _validation_status(report: KiCadValidationReport) -> str:
    if report.checks and all(check.status == "skipped" for check in report.checks):
        return "skipped"
    if report.exit_code == 0:
        return "passed"
    if report.exit_code == 1:
        return "issues found"
    return "failed"


def _preview_status(report: KiCadPreviewReport) -> str:
    if report.artifacts and all(artifact.status == "skipped" for artifact in report.artifacts):
        return "skipped"
    if report.exit_code == 0:
        return "exported"
    return "failed"


__all__ = [
    "KiCadReviewBundleResult",
    "format_kicad_review_bundle_result",
    "run_kicad_review_bundle",
]
