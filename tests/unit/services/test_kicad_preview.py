from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pcbsmith.services.kicad_backend import KiCadInstall
from pcbsmith.services.kicad_preview import (
    KiCadPreviewProcessResult,
    format_kicad_preview_report,
    run_kicad_preview,
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


def test_kicad_preview_reports_missing_cli(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)

    report = run_kicad_preview(tmp_path, finder=lambda: None)

    assert report.exit_code == 1
    assert report.ready is False
    assert format_kicad_preview_report(report) == [
        f"KiCad project: {tmp_path}",
        "KiCad CLI: missing",
        "Problem: Install KiCad or set PCBSMITH_KICAD_CLI=<path-to-kicad-cli>.",
    ]


def test_kicad_preview_can_skip_execution(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)

    report = run_kicad_preview(tmp_path, finder=_install, execute=False)

    assert report.exit_code == 0
    assert report.ready is False
    assert [artifact.status for artifact in report.artifacts] == [
        "skipped",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
    ]
    laser_preview = tmp_path / ".pcbsmith" / "fabrication" / "Demo-fcu-laser.svg"
    gerber_dir = tmp_path / ".pcbsmith" / "fabrication" / "gerbers"
    drill_dir = tmp_path / ".pcbsmith" / "fabrication" / "drill"
    assert format_kicad_preview_report(report) == [
        f"KiCad project: {tmp_path}",
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        f"Schematic SVG: skipped ({tmp_path / '.pcbsmith' / 'visual' / 'Demo-schematic.svg'})",
        f"Board SVG: skipped ({tmp_path / '.pcbsmith' / 'visual' / 'Demo-board.svg'})",
        f"Laser F.Cu SVG: skipped ({laser_preview})",
        f"Gerber package: skipped ({gerber_dir})",
        f"Drill package: skipped ({drill_dir})",
    ]


def test_kicad_preview_exports_normalized_svg_outputs(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> KiCadPreviewProcessResult:
        commands.append(tuple(command))
        if command[1:4] == ["sch", "export", "svg"]:
            output_dir = Path(command[command.index("--output") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "Demo.svg").write_text("<svg>schematic</svg>", encoding="utf-8")
        elif command[1:4] == ["pcb", "export", "svg"]:
            output_file = Path(command[command.index("--output") + 1])
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text("<svg>board</svg>", encoding="utf-8")
        elif command[1:4] == ["pcb", "export", "gerbers"]:
            output_dir = Path(command[command.index("--output") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "Demo-F_Cu.gtl").write_text("gerber", encoding="utf-8")
        elif command[1:4] == ["pcb", "export", "drill"]:
            output_dir = Path(command[command.index("--output") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "Demo.drl").write_text("drill", encoding="utf-8")
        return KiCadPreviewProcessResult(returncode=0, stdout="ok", stderr="")

    report = run_kicad_preview(tmp_path, finder=_install, runner=runner)

    visual_dir = tmp_path / ".pcbsmith" / "visual"
    fabrication_dir = tmp_path / ".pcbsmith" / "fabrication"
    laser_file = fabrication_dir / "Demo-fcu-laser.svg"
    gerber_dir = fabrication_dir / "gerbers"
    drill_dir = fabrication_dir / "drill"
    assert report.exit_code == 0
    assert report.ready is True
    assert [artifact.output_file for artifact in report.artifacts] == [
        visual_dir / "Demo-schematic.svg",
        visual_dir / "Demo-board.svg",
        laser_file,
        gerber_dir,
        drill_dir,
    ]
    assert (visual_dir / "Demo-schematic.svg").read_text(encoding="utf-8") == (
        "<svg>schematic</svg>"
    )
    assert (visual_dir / "Demo-board.svg").read_text(encoding="utf-8") == "<svg>board</svg>"
    assert laser_file.read_text(encoding="utf-8") == "<svg>board</svg>"
    assert (gerber_dir / "Demo-F_Cu.gtl").read_text(encoding="utf-8") == "gerber"
    assert (drill_dir / "Demo.drl").read_text(encoding="utf-8") == "drill"
    assert commands == [
        (
            "C:\\Tools\\KiCad\\bin\\kicad-cli.exe",
            "sch",
            "export",
            "svg",
            "--output",
            str(visual_dir / ".work" / "schematic"),
            "--exclude-drawing-sheet",
            "--no-background-color",
            str(tmp_path / "Demo.kicad_sch"),
        ),
        (
            "C:\\Tools\\KiCad\\bin\\kicad-cli.exe",
            "pcb",
            "export",
            "svg",
            "--output",
            str(visual_dir / "Demo-board.svg"),
            "--layers",
            "F.Cu,F.SilkS,Edge.Cuts",
            "--page-size-mode",
            "2",
            "--fit-page-to-board",
            "--exclude-drawing-sheet",
            "--mode-single",
            str(tmp_path / "Demo.kicad_pcb"),
        ),
        (
            "C:\\Tools\\KiCad\\bin\\kicad-cli.exe",
            "pcb",
            "export",
            "svg",
            "--output",
            str(tmp_path / ".pcbsmith" / "fabrication" / "Demo-fcu-laser.svg"),
            "--layers",
            "F.Cu",
            "--page-size-mode",
            "2",
            "--fit-page-to-board",
            "--exclude-drawing-sheet",
            "--black-and-white",
            "--drill-shape-opt",
            "0",
            "--mode-single",
            str(tmp_path / "Demo.kicad_pcb"),
        ),
        (
            "C:\\Tools\\KiCad\\bin\\kicad-cli.exe",
            "pcb",
            "export",
            "gerbers",
            "--output",
            str(gerber_dir),
            "--layers",
            "F.Cu,F.Mask,F.SilkS,Edge.Cuts",
            "--subtract-soldermask",
            "--precision",
            "6",
            str(tmp_path / "Demo.kicad_pcb"),
        ),
        (
            "C:\\Tools\\KiCad\\bin\\kicad-cli.exe",
            "pcb",
            "export",
            "drill",
            "--output",
            str(drill_dir),
            "--format",
            "excellon",
            "--excellon-units",
            "mm",
            "--generate-map",
            "--map-format",
            "svg",
            "--generate-report",
            "--report-path",
            str(drill_dir / "drill-report.txt"),
            str(tmp_path / "Demo.kicad_pcb"),
        ),
    ]
    assert format_kicad_preview_report(report)[2:] == [
        f"Schematic SVG: exported ({visual_dir / 'Demo-schematic.svg'})",
        f"Board SVG: exported ({visual_dir / 'Demo-board.svg'})",
        f"Laser F.Cu SVG: exported ({laser_file})",
        f"Gerber package: exported ({gerber_dir})",
        f"Drill package: exported ({drill_dir})",
    ]


def test_kicad_preview_reports_export_failure(tmp_path: Path) -> None:
    _write_kicad_project(tmp_path)

    def runner(_command: Sequence[str]) -> KiCadPreviewProcessResult:
        return KiCadPreviewProcessResult(returncode=2, stdout="", stderr="bad export")

    report = run_kicad_preview(tmp_path, finder=_install, runner=runner)

    assert report.exit_code == 2
    assert report.ready is False
    assert format_kicad_preview_report(report)[2:] == [
        "Schematic SVG: error (bad export)",
        "Board SVG: error (bad export)",
        "Laser F.Cu SVG: error (bad export)",
        "Gerber package: error (bad export)",
        "Drill package: error (bad export)",
    ]
