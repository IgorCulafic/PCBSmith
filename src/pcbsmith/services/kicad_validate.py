from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pcbsmith.services.kicad_backend import KICAD_CLI_ENV, KiCadInstall, find_kicad_cli


class KiCadProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    stdout: str
    stderr: str


class KiCadValidationCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    input_file: Path
    report_file: Path
    status: str
    violations: int
    unconnected_items: int
    message: str | None


class KiCadValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_dir: Path
    cli_path: Path | None
    source: str | None
    ready: bool
    problem: str | None
    checks: tuple[KiCadValidationCheck, ...]
    exit_code: int


def run_kicad_validation(
    project_dir: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
    report_dir: Path | None = None,
    execute: bool = True,
) -> KiCadValidationReport:
    install = finder()
    schematic_file = _single_project_file(project_dir, "*.kicad_sch", "schematic")
    board_file = _single_project_file(project_dir, "*.kicad_pcb", "board")
    report_dir = project_dir / ".pcbsmith" / "kicad-reports" if report_dir is None else report_dir
    checks = _planned_checks(schematic_file, board_file, report_dir)

    if install is None:
        return KiCadValidationReport(
            project_dir=project_dir,
            cli_path=None,
            source=None,
            ready=False,
            problem=f"Install KiCad or set {KICAD_CLI_ENV}=<path-to-kicad-cli>.",
            checks=(),
            exit_code=1,
        )

    if not execute:
        skipped_checks = tuple(
            check.model_copy(update={"status": "skipped"}) for check in checks
        )
        return KiCadValidationReport(
            project_dir=project_dir,
            cli_path=install.cli_path,
            source=install.source,
            ready=False,
            problem=None,
            checks=skipped_checks,
            exit_code=0,
        )

    runner = _run_kicad_process if runner is None else runner
    report_dir.mkdir(parents=True, exist_ok=True)
    completed_checks = tuple(
        _run_check(install.cli_path, check, runner) for check in checks
    )
    has_error = any(check.status == "error" for check in completed_checks)
    has_violations = any(check.status == "failed" for check in completed_checks)

    return KiCadValidationReport(
        project_dir=project_dir,
        cli_path=install.cli_path,
        source=install.source,
        ready=not has_error and not has_violations,
        problem=None,
        checks=completed_checks,
        exit_code=2 if has_error else 1 if has_violations else 0,
    )


def format_kicad_validation_report(report: KiCadValidationReport) -> list[str]:
    lines = [f"KiCad project: {report.project_dir}"]
    if report.cli_path is None:
        lines.append("KiCad CLI: missing")
    else:
        lines.append(f"KiCad CLI: {report.cli_path} ({report.source})")

    if report.problem is not None:
        lines.append(f"Problem: {report.problem}")
        return lines

    for check in report.checks:
        if check.name == "ERC":
            lines.append(_format_erc_check(check))
        elif check.name == "DRC":
            lines.append(_format_drc_check(check))
        else:
            lines.append(f"{check.name}: {check.status}")
    return lines


def _planned_checks(
    schematic_file: Path,
    board_file: Path,
    report_dir: Path,
) -> tuple[KiCadValidationCheck, KiCadValidationCheck]:
    return (
        KiCadValidationCheck(
            name="ERC",
            input_file=schematic_file,
            report_file=report_dir / "erc.json",
            status="pending",
            violations=0,
            unconnected_items=0,
            message=None,
        ),
        KiCadValidationCheck(
            name="DRC",
            input_file=board_file,
            report_file=report_dir / "drc.json",
            status="pending",
            violations=0,
            unconnected_items=0,
            message=None,
        ),
    )


def _run_check(
    cli_path: Path,
    check: KiCadValidationCheck,
    runner: Callable[[Sequence[str]], KiCadProcessResult],
) -> KiCadValidationCheck:
    command = _check_command(cli_path, check)
    process_result = runner(command)
    if process_result.returncode != 0:
        return check.model_copy(
            update={"status": "error", "message": _process_message(process_result)}
        )

    try:
        result = _read_check_report(check)
    except Exception as exc:
        return check.model_copy(
            update={"status": "error", "message": f"report parse failed: {exc}"}
        )

    status = "failed" if result["violations"] or result["unconnected_items"] else "passed"
    return check.model_copy(update={"status": status, **result})


def _check_command(cli_path: Path, check: KiCadValidationCheck) -> list[str]:
    if check.name == "ERC":
        return [
            str(cli_path),
            "sch",
            "erc",
            "--format",
            "json",
            "--output",
            str(check.report_file),
            str(check.input_file),
        ]
    if check.name == "DRC":
        return [
            str(cli_path),
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(check.report_file),
            str(check.input_file),
        ]
    raise ValueError(f"Unsupported KiCad check: {check.name}")


def _read_check_report(check: KiCadValidationCheck) -> dict[str, int]:
    data = json.loads(check.report_file.read_text(encoding="utf-8"))
    if check.name == "ERC":
        return {
            "violations": sum(
                1
                for sheet in data.get("sheets", [])
                for violation in sheet.get("violations", [])
                if not _is_ignored_erc_violation(violation)
            ),
            "unconnected_items": 0,
        }
    if check.name == "DRC":
        return {
            "violations": len(data.get("violations", [])),
            "unconnected_items": len(data.get("unconnected_items", [])),
        }
    raise ValueError(f"Unsupported KiCad check: {check.name}")


def _is_ignored_erc_violation(violation: object) -> bool:
    if not isinstance(violation, dict):
        return False
    return (
        violation.get("type") == "lib_symbol_mismatch"
        and "library 'PCBSmith'" in str(violation.get("description", ""))
    )


def _format_erc_check(check: KiCadValidationCheck) -> str:
    if check.status == "skipped":
        return f"ERC: skipped ({check.input_file.name})"
    if check.status == "error":
        return f"ERC: error ({check.message})"
    return f"ERC: {check.status} ({check.violations} violations)"


def _format_drc_check(check: KiCadValidationCheck) -> str:
    if check.status == "skipped":
        return f"DRC: skipped ({check.input_file.name})"
    if check.status == "error":
        return f"DRC: error ({check.message})"
    return (
        f"DRC: {check.status} "
        f"({check.violations} violations, {check.unconnected_items} unconnected)"
    )


def _run_kicad_process(command: Sequence[str]) -> KiCadProcessResult:
    completed = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )
    return KiCadProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _process_message(result: KiCadProcessResult) -> str:
    return result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"


def _single_project_file(project_dir: Path, pattern: str, label: str) -> Path:
    matches = sorted(project_dir.glob(pattern))
    if not matches:
        raise ValueError(f"KiCad {label} file not found in {project_dir}")
    if len(matches) > 1:
        raise ValueError(f"Multiple KiCad {label} files found in {project_dir}")
    return matches[0]


__all__ = [
    "KiCadProcessResult",
    "KiCadValidationCheck",
    "KiCadValidationReport",
    "format_kicad_validation_report",
    "run_kicad_validation",
]
