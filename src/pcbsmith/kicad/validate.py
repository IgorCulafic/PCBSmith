from __future__ import annotations

import json
from collections.abc import Callable, Sequence
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
    process = run_kicad_process(command) if runner is None else runner(command)

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
    data = json.loads(report_file.read_text(encoding="utf-8"))
    findings: list[str] = []
    for sheet in data.get("sheets", []):
        for violation in sheet.get("violations", []):
            description = str(violation.get("description") or "ERC violation")
            severity = str(
                violation.get("severity") or violation.get("type") or "unknown"
            )
            findings.append(f"{severity}: {description}")
    return tuple(findings)
