from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from json import JSONDecodeError
from pathlib import Path

from pcbsmith.circuit.models import KiCadReport
from pcbsmith.kicad.cli import (
    KiCadInstall,
    KiCadProcessResult,
    find_kicad_cli,
    run_kicad_process,
)


def run_kicad_erc(
    schematic_file: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> KiCadReport:
    report_file = schematic_file.parent / ".pcbsmith" / "kicad" / "erc.json"
    install = finder()
    if install is None:
        return KiCadReport(
            status="unavailable",
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
            findings=("KiCad CLI was not found; ERC was not run.",),
        )

    command = (
        str(install.path),
        "sch",
        "erc",
        "--format",
        "json",
        "--output",
        str(report_file),
        str(schematic_file),
    )
    report_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        process = run_kicad_process(command) if runner is None else runner(command)
    except OSError as exc:
        return KiCadReport(
            status="failed",
            command=command,
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
            findings=(f"KiCad ERC could not run: {exc}",),
        )

    if process.returncode != 0:
        return KiCadReport(
            status="failed",
            command=process.command,
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
            findings=(_process_failure_finding(process),),
        )

    findings = _erc_findings(report_file)
    return KiCadReport(
        status="failed" if findings else "passed",
        command=process.command,
        schematic_file=str(schematic_file),
        erc_report=str(report_file),
        findings=findings,
    )


def _process_failure_finding(process: KiCadProcessResult) -> str:
    return process.stderr.strip() or process.stdout.strip() or "KiCad ERC failed."


def _erc_findings(report_file: Path) -> tuple[str, ...]:
    if not report_file.exists():
        return ("KiCad ERC report was not written.",)
    try:
        data = json.loads(report_file.read_text(encoding="utf-8"))
    except JSONDecodeError:
        return ("KiCad ERC report was not valid JSON.",)
    if not isinstance(data, dict):
        return ("KiCad ERC report root was not a JSON object.",)
    sheets = data.get("sheets")
    if not isinstance(sheets, list):
        return ("KiCad ERC report did not contain a sheets list.",)

    findings: list[str] = []
    for sheet in sheets:
        if not isinstance(sheet, dict):
            return ("KiCad ERC report contained a malformed sheet entry.",)
        violations = sheet.get("violations")
        if not isinstance(violations, list):
            return ("KiCad ERC report sheet did not contain a violations list.",)
        for violation in violations:
            if not isinstance(violation, dict):
                return ("KiCad ERC report contained a malformed violation entry.",)
            description = str(violation.get("description") or "ERC violation")
            severity = str(
                violation.get("severity") or violation.get("type") or "unknown"
            )
            findings.append(f"{severity}: {description}")
    return tuple(findings)
