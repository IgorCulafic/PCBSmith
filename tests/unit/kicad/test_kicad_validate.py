from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from pcbsmith.kicad.kicad_backend import KiCadInstall
from pcbsmith.kicad.kicad_validate import (
    KiCadProcessResult,
    format_kicad_validation_report,
    run_kicad_validation,
)


def _install() -> KiCadInstall:
    return KiCadInstall(
        cli_path=Path("C:/Tools/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
    )


def _write_kicad_project(project_dir: Path) -> None:
    project_dir.mkdir(exist_ok=True)
    (project_dir / "Demo.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")
    (project_dir / "Demo.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")


def test_kicad_validate_reports_missing_cli(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)

    report = run_kicad_validation(tmp_path, finder=lambda: None)

    assert report.exit_code == 1
    assert report.ready is False
    assert format_kicad_validation_report(report) == [
        f"KiCad project: {tmp_path}",
        "KiCad CLI: missing",
        "Problem: Install KiCad or set PCBSMITH_KICAD_CLI=<path-to-kicad-cli>.",
    ]


def test_kicad_validate_can_skip_execution(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)

    report = run_kicad_validation(
        tmp_path,
        finder=_install,
        execute=False,
    )

    assert report.exit_code == 0
    assert report.ready is False
    assert [check.status for check in report.checks] == ["skipped", "skipped"]
    assert format_kicad_validation_report(report) == [
        f"KiCad project: {tmp_path}",
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "ERC: skipped (Demo.kicad_sch)",
        "DRC: skipped (Demo.kicad_pcb)",
    ]


def test_kicad_validate_runs_erc_and_drc_with_json_reports(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> KiCadProcessResult:
        commands.append(tuple(command))
        report_file = Path(command[command.index("--output") + 1])
        if command[1:3] == ["sch", "erc"]:
            report_file.write_text(
                json.dumps({"sheets": [{"violations": []}]}),
                encoding="utf-8",
            )
        elif command[1:3] == ["pcb", "drc"]:
            report_file.write_text(
                json.dumps({"violations": [], "unconnected_items": []}),
                encoding="utf-8",
            )
        return KiCadProcessResult(returncode=0, stdout="ok", stderr="")

    report = run_kicad_validation(tmp_path, finder=_install, runner=runner)

    assert report.exit_code == 0
    assert report.ready is True
    assert commands == [
        (
            "C:\\Tools\\KiCad\\bin\\kicad-cli.exe",
            "sch",
            "erc",
            "--format",
            "json",
            "--output",
            str(tmp_path / ".pcbsmith" / "kicad-reports" / "erc.json"),
            str(tmp_path / "Demo.kicad_sch"),
        ),
        (
            "C:\\Tools\\KiCad\\bin\\kicad-cli.exe",
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(tmp_path / ".pcbsmith" / "kicad-reports" / "drc.json"),
            str(tmp_path / "Demo.kicad_pcb"),
        ),
    ]
    assert format_kicad_validation_report(report) == [
        f"KiCad project: {tmp_path}",
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "ERC: passed (0 violations)",
        "DRC: passed (0 violations, 0 unconnected)",
    ]


def test_kicad_validate_reports_rule_violations(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)

    def runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = Path(command[command.index("--output") + 1])
        if command[1:3] == ["sch", "erc"]:
            report_file.write_text(
                json.dumps({"sheets": [{"violations": [{"type": "erc_error"}]}]}),
                encoding="utf-8",
            )
        elif command[1:3] == ["pcb", "drc"]:
            report_file.write_text(
                json.dumps(
                    {
                        "violations": [{"type": "invalid_outline"}],
                        "unconnected_items": [{"type": "ratsnest"}],
                    }
                ),
                encoding="utf-8",
            )
        return KiCadProcessResult(returncode=0, stdout="", stderr="")

    report = run_kicad_validation(tmp_path, finder=_install, runner=runner)

    assert report.exit_code == 1
    assert report.ready is False
    assert format_kicad_validation_report(report) == [
        f"KiCad project: {tmp_path}",
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "ERC: failed (1 violations)",
        "DRC: failed (1 violations, 1 unconnected)",
    ]


def test_kicad_validate_ignores_generated_pcbs_library_mismatch(
    tmp_path: Path,
) -> None:
    _write_kicad_project(tmp_path)

    def runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = Path(command[command.index("--output") + 1])
        if command[1:3] == ["sch", "erc"]:
            report_file.write_text(
                json.dumps(
                    {
                        "sheets": [
                            {
                                "violations": [
                                    {
                                        "type": "lib_symbol_mismatch",
                                        "description": (
                                            "Symbol 'R' doesn't match copy in "
                                            "library 'PCBSmith'"
                                        ),
                                    }
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        elif command[1:3] == ["pcb", "drc"]:
            report_file.write_text(
                json.dumps({"violations": [], "unconnected_items": []}),
                encoding="utf-8",
            )
        return KiCadProcessResult(returncode=0, stdout="", stderr="")

    report = run_kicad_validation(tmp_path, finder=_install, runner=runner)
    sanitized_erc = json.loads(
        (tmp_path / ".pcbsmith" / "kicad-reports" / "erc.json").read_text(
            encoding="utf-8"
        )
    )

    assert report.exit_code == 0
    assert report.ready is True
    assert format_kicad_validation_report(report)[2] == "ERC: passed (0 violations)"
    assert sanitized_erc["sheets"][0]["violations"] == []


def test_kicad_validate_reports_cli_failure(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)

    def runner(_command: Sequence[str]) -> KiCadProcessResult:
        return KiCadProcessResult(returncode=2, stdout="", stderr="bad input")

    report = run_kicad_validation(tmp_path, finder=_install, runner=runner)

    assert report.exit_code == 2
    assert report.ready is False
    assert format_kicad_validation_report(report) == [
        f"KiCad project: {tmp_path}",
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "ERC: error (bad input)",
        "DRC: error (bad input)",
    ]
