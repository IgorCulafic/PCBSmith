from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from pcbsmith.generators.led_art import (
    LedArtPlan,
    LedArtSpec,
    build_led_art_plan,
    build_led_art_plan_for_topology,
    compare_led_art_topologies,
    write_led_art_reports,
    write_led_art_topology_comparison_reports,
)
from pcbsmith.generators.led_art_board import (
    LedArtBoardSpec,
    LedArtControlMode,
    led_art_control_summary,
    led_art_physical_branch_summary,
    render_led_art_board,
)
from pcbsmith.kicad.kicad_backend import find_kicad_cli
from pcbsmith.kicad.kicad_preview import (
    format_kicad_preview_report,
    run_kicad_preview,
)
from pcbsmith.kicad.kicad_project import (
    render_kicad_project_file,
    render_kicad_schematic_file,
    sanitize_kicad_project_name,
)
from pcbsmith.kicad.kicad_validate import (
    format_kicad_validation_report,
    run_kicad_validation,
)

SOURCE_LOGO_SVG = Path("D:/VIR LAB/VEKTOR-04.svg")
SOURCE_LOGO_PNG = Path("D:/VIR LAB/1-04.png")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a KiCad VIR-LAB 0603 LED demo board."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/vir-lab-led-demo-20260511-01/kicad-review"),
        help="Output KiCad project directory.",
    )
    parser.add_argument("--name", default="VIR LAB 5V LED Demo")
    parser.add_argument(
        "--topology",
        choices=("5v_one_per_led", "5v_two_led_dense", "12v_dense"),
        default="5v_one_per_led",
        help="physical LED branch topology to route on the board",
    )
    parser.add_argument(
        "--no-polarity-marks",
        action="store_true",
        help="omit educational LED anode + marks from the board silkscreen",
    )
    parser.add_argument(
        "--control",
        choices=("none", "low_side_mosfet"),
        default="none",
        help="optional LED return control circuit to include on the board",
    )
    args = parser.parse_args()

    project_dir = args.output
    _reset_output_dir(project_dir)
    project_name = sanitize_kicad_project_name(args.name)
    project_dir.mkdir(parents=True)

    plan = build_led_art_plan_for_topology(LedArtSpec(text="VIR-LAB"), args.topology)
    control_mode: LedArtControlMode = args.control
    board_spec = LedArtBoardSpec(
        show_polarity_marks=not args.no_polarity_marks,
        control_mode=control_mode,
    )
    project_file = project_dir / f"{project_name}.kicad_pro"
    schematic_file = project_dir / f"{project_name}.kicad_sch"
    board_file = project_dir / f"{project_name}.kicad_pcb"

    project_file.write_text(render_kicad_project_file(project_name), encoding="utf-8")
    schematic_file.write_text(
        render_kicad_schematic_file(uuid4()),
        encoding="utf-8",
    )
    board_file.write_text(render_led_art_board(plan, board_spec), encoding="utf-8")
    _copy_logo_sources(project_dir)
    _write_layout_first_readme(project_dir, project_name, plan, control_mode=control_mode)
    reports_dir = project_dir / ".pcbsmith" / "reports"
    write_led_art_reports(plan, reports_dir)
    comparison = compare_led_art_topologies(build_led_art_plan(LedArtSpec(text="VIR-LAB")))
    write_led_art_topology_comparison_reports(comparison, reports_dir)

    validation = run_kicad_validation(project_dir)
    preview = run_kicad_preview(project_dir)
    schematic_note_paths = _replace_blank_schematic_svgs(project_dir, project_name, plan)
    assembly_preview = _export_assembly_preview(project_dir, project_name, board_file)
    print("\n".join(format_kicad_validation_report(validation)))
    print("\n".join(format_kicad_preview_report(preview)))
    for note_path in schematic_note_paths:
        print(f"Layout-first schematic note SVG: {note_path}")
    if assembly_preview is not None:
        print(f"Assembly preview SVG: {assembly_preview}")
    if validation.exit_code or preview.exit_code:
        raise SystemExit(1)


def _reset_output_dir(project_dir: Path) -> None:
    resolved = project_dir.resolve()
    workspace = Path.cwd().resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"Output must be inside the workspace: {project_dir}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _copy_logo_sources(project_dir: Path) -> None:
    assets_dir = project_dir / ".pcbsmith" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for source in (SOURCE_LOGO_SVG, SOURCE_LOGO_PNG):
        if source.exists():
            shutil.copyfile(source, assets_dir / source.name)


def _write_layout_first_readme(
    project_dir: Path,
    project_name: str,
    plan: LedArtPlan,
    *,
    control_mode: LedArtControlMode,
) -> None:
    readme = project_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                f"# {project_name}",
                "",
                "This is a PCB-layout-first KiCad demo generated by PCBSmith.",
                "",
                "- The board contains the routed VIR-LAB LED layout.",
                f"- Topology: {plan.electrical.grouping_strategy}.",
                f"- Supply: {plan.electrical.supply_voltage_v:g} V.",
                f"- Physical branch summary: {led_art_physical_branch_summary(plan)}.",
                f"- Control: {led_art_control_summary(control_mode)}.",
                "- The electrical report estimates current draw and flags "
                "input-power budget warnings.",
                "- The KiCad schematic is intentionally minimal in this demo.",
                "- Full schematic array and hierarchy generation is a later PCBSmith slice.",
                "- Use the board SVG, assembly preview SVG, Gerbers, and laser F.Cu SVG "
                "for review.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _replace_blank_schematic_svgs(
    project_dir: Path,
    project_name: str,
    plan: LedArtPlan,
) -> list[Path]:
    visual_dir = project_dir / ".pcbsmith" / "visual"
    note_svg = _layout_first_schematic_note_svg(project_name, plan)
    paths = [
        visual_dir / f"{project_name}-schematic.svg",
        visual_dir / f"{project_name}.svg",
        visual_dir / ".work" / "schematic" / f"{project_name}.svg",
    ]
    written_paths: list[Path] = []
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(note_svg, encoding="utf-8")
        written_paths.append(path)
    return written_paths


def _layout_first_schematic_note_svg(project_name: str, plan: LedArtPlan) -> str:
    supply_voltage = plan.electrical.supply_voltage_v
    circuit_intent = (
        f"{supply_voltage:g}V input, {led_art_physical_branch_summary(plan)}."
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" width="900" height="320" viewBox="0 0 900 320">
  <rect width="900" height="320" fill="#fffef8"/>
  <text x="40" y="70" font-family="Arial, sans-serif" font-size="28" fill="#006464">
    {project_name}
  </text>
  <text x="40" y="125" font-family="Arial, sans-serif" font-size="20" fill="#222">
    Layout-first PCB demo: schematic array generation is intentionally deferred.
  </text>
  <text x="40" y="170" font-family="Arial, sans-serif" font-size="18" fill="#222">
    Review the KiCad PCB, board SVG, assembly preview SVG, Gerbers, and laser F.Cu SVG.
  </text>
  <text x="40" y="215" font-family="Arial, sans-serif" font-size="18" fill="#222">
    Circuit intent: {circuit_intent}
  </text>
</svg>
"""


def _export_assembly_preview(
    project_dir: Path,
    project_name: str,
    board_file: Path,
) -> Path | None:
    install = find_kicad_cli()
    if install is None:
        return None

    output_file = project_dir / ".pcbsmith" / "visual" / f"{project_name}-assembly.svg"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            str(install.cli_path),
            "pcb",
            "export",
            "svg",
            "--output",
            str(output_file),
            "--layers",
            "F.Cu,F.Fab,F.SilkS,Edge.Cuts",
            "--page-size-mode",
            "2",
            "--fit-page-to-board",
            "--exclude-drawing-sheet",
            "--mode-single",
            str(board_file),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Assembly preview export failed: {message}")
    return output_file


if __name__ == "__main__":
    main()
