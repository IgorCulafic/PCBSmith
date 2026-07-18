from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.kicad.validate import run_kicad_erc


def test_kicad_erc_reports_unavailable_without_cli(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    report = run_kicad_erc(schematic, finder=lambda: None)

    assert report.status == "unavailable"
    assert report.schematic_file == str(schematic)
    assert report.erc_report == str(tmp_path / ".pcbsmith" / "kicad" / "erc.json")
    assert report.findings == ("KiCad CLI was not found; ERC was not run.",)


def test_kicad_erc_runs_json_report_with_fake_runner(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = _report_file_from_command(command)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps({"sheets": [{"violations": []}]}),
            encoding="utf-8",
        )
        return KiCadProcessResult(
            command=tuple(command),
            returncode=0,
            stdout="",
            stderr="",
        )

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "passed"
    assert report.erc_report == str(tmp_path / ".pcbsmith" / "kicad" / "erc.json")
    assert report.command == (
        "kicad-cli.exe",
        "sch",
        "erc",
        "--format",
        "json",
        "--output",
        str(tmp_path / ".pcbsmith" / "kicad" / "erc.json"),
        str(schematic),
    )
    assert report.findings == ()


def test_kicad_erc_reports_json_violations(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = _report_file_from_command(command)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(
                {
                    "sheets": [
                        {
                            "path": "/",
                            "violations": [
                                {
                                    "severity": "error",
                                    "description": "Pin not connected",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return KiCadProcessResult(
            command=tuple(command),
            returncode=0,
            stdout="",
            stderr="",
        )

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == ("error: Pin not connected",)


def test_kicad_erc_reports_nonzero_process_output(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        return KiCadProcessResult(
            command=tuple(command),
            returncode=1,
            stdout="",
            stderr="Failed to load schematic",
        )

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == ("Failed to load schematic",)


def test_kicad_erc_reports_runner_exception_as_failed(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(_command: Sequence[str]) -> KiCadProcessResult:
        raise OSError("permission denied")

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == ("KiCad ERC could not run: permission denied",)


def test_kicad_erc_reports_missing_json_report_as_failed(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    stale_report = tmp_path / ".pcbsmith" / "kicad" / "erc.json"
    stale_report.parent.mkdir(parents=True)
    stale_report.write_text(
        json.dumps({"sheets": [{"violations": []}]}), encoding="utf-8"
    )

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == ("KiCad ERC report was not written.",)
    assert not stale_report.exists()


def test_kicad_erc_reports_invalid_json_as_failed(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = _report_file_from_command(command)
        report_file.write_text("{not-json", encoding="utf-8")
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == ("KiCad ERC report was not valid JSON.",)


def test_kicad_erc_reports_malformed_json_shape_as_failed(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = _report_file_from_command(command)
        report_file.write_text(json.dumps({}), encoding="utf-8")
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == ("KiCad ERC report did not contain a sheets list.",)


def test_kicad_erc_reports_malformed_sheet_entries_as_failed(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = _report_file_from_command(command)
        report_file.write_text(json.dumps({"sheets": ["bad-sheet"]}), encoding="utf-8")
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == ("KiCad ERC report contained a malformed sheet entry.",)


def test_kicad_erc_reports_malformed_violation_entries_as_failed(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command: Sequence[str]) -> KiCadProcessResult:
        report_file = _report_file_from_command(command)
        report_file.write_text(
            json.dumps({"sheets": [{"violations": ["bad-violation"]}]}),
            encoding="utf-8",
        )
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == (
        "KiCad ERC report contained a malformed violation entry.",
    )


def _report_file_from_command(command: Sequence[str]) -> Path:
    return Path(command[command.index("--output") + 1])
