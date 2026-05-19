from __future__ import annotations

from pathlib import Path

from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.kicad.spice import export_kicad_spice_netlist


def test_spice_export_reports_unavailable_without_kicad(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    report = export_kicad_spice_netlist(schematic, finder=lambda: None)

    assert report.status == "unavailable"
    assert report.schematic_file == str(schematic)
    assert report.findings == (
        "KiCad CLI was not found; SPICE netlist export was not run.",
    )


def test_spice_export_writes_netlist_with_fake_runner(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command):
        output_file = Path(command[7])
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("* exported by KiCad\n.op\n.end\n", encoding="utf-8")
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = export_kicad_spice_netlist(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "passed"
    assert report.spice_netlist is not None
    assert report.command == (
        "kicad-cli.exe",
        "sch",
        "export",
        "netlist",
        "--format",
        "spice",
        "--output",
        str(Path(report.spice_netlist)),
        str(schematic),
    )
    assert Path(report.spice_netlist).read_text(encoding="utf-8").startswith(
        "* exported by KiCad"
    )


def test_spice_export_reports_process_failure(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command):
        return KiCadProcessResult(
            command=tuple(command),
            returncode=1,
            stdout="stdout detail",
            stderr="stderr detail",
        )

    report = export_kicad_spice_netlist(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == ("stderr detail",)


def test_spice_export_reports_process_launch_error(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(_command):
        raise OSError("permission denied")

    report = export_kicad_spice_netlist(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == (
        "KiCad SPICE netlist export could not run: permission denied",
    )


def test_spice_export_reports_missing_or_empty_output_file(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command):
        output_file = Path(command[7])
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("   \n", encoding="utf-8")
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = export_kicad_spice_netlist(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == (
        "KiCad SPICE netlist export did not produce a non-empty file.",
    )
