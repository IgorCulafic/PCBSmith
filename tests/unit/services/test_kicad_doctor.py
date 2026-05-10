from __future__ import annotations

from pathlib import Path

from pcbsmith.services.kicad_backend import KiCadInstall
from pcbsmith.services.kicad_doctor import format_kicad_doctor_report, run_kicad_doctor


def test_kicad_doctor_reports_missing_cli() -> None:
    report = run_kicad_doctor(finder=lambda: None)

    assert report.ready is False
    assert report.exit_code == 1
    assert report.cli_path is None
    assert report.problem == (
        "Install KiCad or set PCBSMITH_KICAD_CLI=<path-to-kicad-cli>."
    )
    assert format_kicad_doctor_report(report) == [
        "KiCad CLI: missing",
        "Problem: Install KiCad or set PCBSMITH_KICAD_CLI=<path-to-kicad-cli>.",
    ]


def test_kicad_doctor_reports_ready_backend_with_version() -> None:
    install = KiCadInstall(
        cli_path=Path("C:/Tools/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
    )

    report = run_kicad_doctor(
        finder=lambda: install,
        version_probe=lambda _path: "KiCad 9.0.2",
    )

    assert report.ready is True
    assert report.exit_code == 0
    assert report.version == "KiCad 9.0.2"
    assert format_kicad_doctor_report(report) == [
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "KiCad version: KiCad 9.0.2",
        "KiCad backend ready",
    ]


def test_kicad_doctor_can_skip_version_probe() -> None:
    install = KiCadInstall(
        cli_path=Path("C:/Tools/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
    )

    report = run_kicad_doctor(finder=lambda: install, skip_version_check=True)

    assert report.ready is False
    assert report.exit_code == 0
    assert report.version is None
    assert format_kicad_doctor_report(report) == [
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "KiCad version: skipped",
        "KiCad backend configured but not version-checked",
    ]


def test_kicad_doctor_reports_version_probe_failure() -> None:
    install = KiCadInstall(
        cli_path=Path("C:/Tools/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
    )

    def fail_version_probe(_path: Path) -> str:
        raise RuntimeError("process failed")

    report = run_kicad_doctor(finder=lambda: install, version_probe=fail_version_probe)

    assert report.ready is False
    assert report.exit_code == 2
    assert report.problem == "KiCad CLI version check failed: process failed"
    assert format_kicad_doctor_report(report) == [
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "Problem: KiCad CLI version check failed: process failed",
    ]
