from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pcbsmith.services.kicad_backend import KICAD_CLI_ENV, KiCadInstall, find_kicad_cli


class KiCadDoctorReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cli_path: Path | None
    source: str | None
    version: str | None
    ready: bool
    problem: str | None
    exit_code: int


def run_kicad_doctor(
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    version_probe: Callable[[Path], str] | None = None,
    skip_version_check: bool = False,
) -> KiCadDoctorReport:
    version_probe = _probe_kicad_version if version_probe is None else version_probe
    install = finder()
    if install is None:
        return KiCadDoctorReport(
            cli_path=None,
            source=None,
            version=None,
            ready=False,
            problem=f"Install KiCad or set {KICAD_CLI_ENV}=<path-to-kicad-cli>.",
            exit_code=1,
        )

    if skip_version_check:
        return KiCadDoctorReport(
            cli_path=install.cli_path,
            source=install.source,
            version=None,
            ready=False,
            problem=None,
            exit_code=0,
        )

    try:
        version = version_probe(install.cli_path)
    except Exception as exc:
        return KiCadDoctorReport(
            cli_path=install.cli_path,
            source=install.source,
            version=None,
            ready=False,
            problem=f"KiCad CLI version check failed: {exc}",
            exit_code=2,
        )

    return KiCadDoctorReport(
        cli_path=install.cli_path,
        source=install.source,
        version=version,
        ready=True,
        problem=None,
        exit_code=0,
    )


def format_kicad_doctor_report(report: KiCadDoctorReport) -> list[str]:
    if report.cli_path is None:
        lines = ["KiCad CLI: missing"]
    else:
        lines = [f"KiCad CLI: {report.cli_path} ({report.source})"]

    if report.problem is not None:
        lines.append(f"Problem: {report.problem}")
    elif report.version is None:
        lines.extend(
            [
                "KiCad version: skipped",
                "KiCad backend configured but not version-checked",
            ]
        )
    else:
        lines.extend([f"KiCad version: {report.version}", "KiCad backend ready"])

    return lines


def _probe_kicad_version(cli_path: Path) -> str:
    completed = subprocess.run(
        [str(cli_path), "version"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"process exited with code {completed.returncode}")

    version = _first_nonempty_line(completed.stdout) or _first_nonempty_line(completed.stderr)
    if version is None:
        raise RuntimeError("version command returned no output")
    return version


def _first_nonempty_line(value: str) -> str | None:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


__all__ = [
    "KiCadDoctorReport",
    "format_kicad_doctor_report",
    "run_kicad_doctor",
]
