from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pcbsmith.services.board_manufacturability import BoardManufacturabilityReport
from pcbsmith.services.kicad_preview import KiCadPreviewReport
from pcbsmith.services.kicad_project import KiCadProjectSkeleton
from pcbsmith.services.kicad_review_bundle import (
    format_kicad_review_bundle_result,
    run_kicad_review_bundle,
)
from pcbsmith.services.kicad_validate import KiCadValidationReport


class FakeExportResult:
    def __init__(self, project_dir: Path) -> None:
        self.skeleton = KiCadProjectSkeleton(
            project_name="Review_Demo",
            project_dir=project_dir,
            project_file=project_dir / "Review_Demo.kicad_pro",
            schematic_file=project_dir / "Review_Demo.kicad_sch",
            board_file=project_dir / "Review_Demo.kicad_pcb",
        )
        self.handoff_file = project_dir / "pcbsmith_handoff.json"


def _validation_report(project_dir: Path, exit_code: int = 0) -> KiCadValidationReport:
    return KiCadValidationReport(
        project_dir=project_dir,
        cli_path=Path("C:/Tools/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
        ready=exit_code == 0,
        problem=None,
        checks=(),
        exit_code=exit_code,
    )


def _preview_report(project_dir: Path, exit_code: int = 0) -> KiCadPreviewReport:
    return KiCadPreviewReport(
        project_dir=project_dir,
        cli_path=Path("C:/Tools/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
        ready=exit_code == 0,
        problem=None,
        artifacts=(),
        exit_code=exit_code,
    )


def _board_report(_project_dir: Path, output_path: Path) -> BoardManufacturabilityReport:
    output_path.write_text(
        '{"schema": "pcbsmith-board-manufacturability-v1"}\n',
        encoding="utf-8",
    )
    return BoardManufacturabilityReport(findings=())


def test_review_bundle_runs_export_validation_preview_and_context(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "review"
    calls: list[tuple[str, tuple[object, ...]]] = []

    def exporter(
        source: Path, output: Path, *, project_name: str | None = None
    ) -> FakeExportResult:
        calls.append(("export", (source, output, project_name)))
        output.mkdir()
        return FakeExportResult(output)

    def validator(project_dir: Path, *, execute: bool = True) -> KiCadValidationReport:
        calls.append(("validate", (project_dir, execute)))
        return _validation_report(project_dir)

    def previewer(project_dir: Path, *, execute: bool = True) -> KiCadPreviewReport:
        calls.append(("preview", (project_dir, execute)))
        return _preview_report(project_dir)

    def context_writer(
        project_dir: Path, output_path: Path, *, kicad_project_dir: Path | None = None
    ) -> None:
        calls.append(("context", (project_dir, output_path, kicad_project_dir)))
        output_path.write_text("{}\n", encoding="utf-8")

    def board_reporter(project_dir: Path, output_path: Path) -> BoardManufacturabilityReport:
        calls.append(("board_report", (project_dir, output_path)))
        output_path.write_text(
            '{"schema": "pcbsmith-board-manufacturability-v1"}\n',
            encoding="utf-8",
        )
        return BoardManufacturabilityReport(findings=())

    result = run_kicad_review_bundle(
        source_project,
        output_project,
        project_name="Review Demo",
        exporter=exporter,
        validator=validator,
        previewer=previewer,
        context_writer=context_writer,
        board_reporter=board_reporter,
    )

    assert result.exit_code == 0
    assert result.context_file == output_project / "ai-context.json"
    assert result.manufacturability_report_file == (
        output_project / ".pcbsmith" / "board-reports" / "manufacturability.json"
    )
    assert calls == [
        ("export", (source_project, output_project, "Review Demo")),
        ("validate", (output_project, True)),
        ("preview", (output_project, True)),
        (
            "board_report",
            (
                source_project,
                output_project / ".pcbsmith" / "board-reports" / "manufacturability.json",
            ),
        ),
        ("context", (source_project, output_project / "ai-context.json", output_project)),
    ]
    assert format_kicad_review_bundle_result(result) == [
        f"Review bundle: {output_project}",
        f"Exported KiCad handoff: {output_project}",
        "Validation: passed",
        "Preview: exported",
        "Board manufacturability: passed",
        f"AI context: {output_project / 'ai-context.json'}",
    ]


def test_review_bundle_can_skip_kicad_execution(tmp_path: Path) -> None:
    output_project = tmp_path / "review"

    def exporter(
        _source: Path, output: Path, *, project_name: str | None = None
    ) -> FakeExportResult:
        output.mkdir()
        return FakeExportResult(output)

    def capture_execute(
        report_factory: Callable[[Path], object],
        seen: list[bool],
    ) -> Callable[[Path], object]:
        def runner(project_dir: Path, *, execute: bool = True) -> object:
            seen.append(execute)
            return report_factory(project_dir)

        return runner

    validation_execute: list[bool] = []
    preview_execute: list[bool] = []

    result = run_kicad_review_bundle(
        tmp_path / "source",
        output_project,
        exporter=exporter,
        validator=capture_execute(_validation_report, validation_execute),
        previewer=capture_execute(_preview_report, preview_execute),
        context_writer=lambda _project, output, *, kicad_project_dir=None: output.write_text(
            "{}\n", encoding="utf-8"
        ),
        board_reporter=_board_report,
        execute_kicad=False,
    )

    assert result.exit_code == 0
    assert validation_execute == [False]
    assert preview_execute == [False]


def test_review_bundle_returns_nonzero_when_validation_or_preview_fails(
    tmp_path: Path,
) -> None:
    output_project = tmp_path / "review"

    def exporter(
        _source: Path, output: Path, *, project_name: str | None = None
    ) -> FakeExportResult:
        output.mkdir()
        return FakeExportResult(output)

    result = run_kicad_review_bundle(
        tmp_path / "source",
        output_project,
        exporter=exporter,
        validator=lambda project_dir, *, execute=True: _validation_report(project_dir, 1),
        previewer=lambda project_dir, *, execute=True: _preview_report(project_dir, 2),
        context_writer=lambda _project, output, *, kicad_project_dir=None: output.write_text(
            "{}\n", encoding="utf-8"
        ),
        board_reporter=_board_report,
    )

    assert result.exit_code == 2
    assert format_kicad_review_bundle_result(result)[2:4] == [
        "Validation: issues found",
        "Preview: failed",
    ]
