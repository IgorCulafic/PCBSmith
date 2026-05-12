from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pcbsmith.services.ai_context import write_ai_context
from pcbsmith.services.board_manufacturability import (
    BoardManufacturabilityReport,
    inspect_board_manufacturability,
    write_board_manufacturability_report,
)
from pcbsmith.services.kicad_export import KiCadExportResult, export_pcbs_project_to_kicad
from pcbsmith.services.kicad_preview import KiCadPreviewReport, run_kicad_preview
from pcbsmith.services.kicad_validate import KiCadValidationReport, run_kicad_validation
from pcbsmith.services.project_io import load_board, load_project


class KiCadReviewBundleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    source_project_dir: Path
    output_project_dir: Path
    context_file: Path
    manufacturability_report_file: Path
    export_result: object
    validation_report: KiCadValidationReport
    preview_report: KiCadPreviewReport
    manufacturability_report: BoardManufacturabilityReport
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
    board_reporter: Callable[[Path, Path], BoardManufacturabilityReport] | None = None,
) -> KiCadReviewBundleResult:
    board_reporter = board_reporter or _write_project_board_manufacturability_report
    export_result = exporter(
        source_project_dir,
        output_project_dir,
        project_name=project_name,
    )
    validation_report = validator(output_project_dir, execute=execute_kicad)
    preview_report = previewer(output_project_dir, execute=execute_kicad)
    manufacturability_report_file = (
        output_project_dir / ".pcbsmith" / "board-reports" / "manufacturability.json"
    )
    manufacturability_report_file.parent.mkdir(parents=True, exist_ok=True)
    manufacturability_report = board_reporter(
        source_project_dir,
        manufacturability_report_file,
    )
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
        manufacturability_report_file=manufacturability_report_file,
        export_result=export_result,
        validation_report=validation_report,
        preview_report=preview_report,
        manufacturability_report=manufacturability_report,
        exit_code=max(
            validation_report.exit_code,
            preview_report.exit_code,
            manufacturability_report.exit_code,
        ),
    )


def format_kicad_review_bundle_result(result: KiCadReviewBundleResult) -> list[str]:
    return [
        f"Review bundle: {result.output_project_dir}",
        f"Exported KiCad handoff: {result.output_project_dir}",
        f"Validation: {_validation_status(result.validation_report)}",
        f"Preview: {_preview_status(result.preview_report)}",
        f"Board manufacturability: {_manufacturability_status(result.manufacturability_report)}",
        f"AI context: {result.context_file}",
    ]


def _write_project_board_manufacturability_report(
    source_project_dir: Path,
    output_path: Path,
) -> BoardManufacturabilityReport:
    project = load_project(source_project_dir)
    if not project.boards:
        raise ValueError("Project has no boards")
    board = load_board(source_project_dir, project.boards[0])
    report = inspect_board_manufacturability(board, design_rules=project.design_rules)
    write_board_manufacturability_report(report, output_path)
    return report


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


def _manufacturability_status(report: BoardManufacturabilityReport) -> str:
    if report.exit_code == 0:
        if report.findings:
            return "warnings found"
        return "passed"
    return "issues found"


__all__ = [
    "KiCadReviewBundleResult",
    "format_kicad_review_bundle_result",
    "run_kicad_review_bundle",
]
