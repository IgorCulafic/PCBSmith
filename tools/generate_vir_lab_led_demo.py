from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pcbsmith.services.kicad_backend import find_kicad_cli
from pcbsmith.services.kicad_board_builder import (
    KiCadBoardBuilder,
    NetRef,
    ThreePadSmdFootprintSpec,
    TwoPadSmdFootprintSpec,
)
from pcbsmith.services.kicad_preview import (
    format_kicad_preview_report,
    run_kicad_preview,
)
from pcbsmith.services.kicad_project import (
    render_kicad_project_file,
    render_kicad_schematic_file,
    sanitize_kicad_project_name,
)
from pcbsmith.services.kicad_validate import (
    format_kicad_validation_report,
    run_kicad_validation,
)
from pcbsmith.services.led_art import (
    LedArtPixel,
    LedArtPlan,
    LedArtSpec,
    LedArtString,
    build_led_art_plan,
    build_led_art_plan_for_topology,
    compare_led_art_topologies,
    write_led_art_reports,
    write_led_art_topology_comparison_reports,
)

BOARD_WIDTH_MM = 420.0
BOARD_HEIGHT_MM = 120.0
VCC_RAIL_Y_MM = 8.0
GND_RAIL_Y_MM = 108.0
TRACE_WIDTH_MM = 0.45
ROW_POWER_OFFSET_MM = 3.0
SOURCE_LOGO_SVG = Path("D:/VIR LAB/VEKTOR-04.svg")
SOURCE_LOGO_PNG = Path("D:/VIR LAB/1-04.png")
ControlMode = Literal["none", "low_side_mosfet"]


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
    project_file = project_dir / f"{project_name}.kicad_pro"
    schematic_file = project_dir / f"{project_name}.kicad_sch"
    board_file = project_dir / f"{project_name}.kicad_pcb"

    project_file.write_text(render_kicad_project_file(project_name), encoding="utf-8")
    schematic_file.write_text(
        render_kicad_schematic_file(uuid4()),
        encoding="utf-8",
    )
    board_file.write_text(
        _render_board(
            plan,
            show_polarity_marks=not args.no_polarity_marks,
            control_mode=args.control,
        ),
        encoding="utf-8",
    )
    _copy_logo_sources(project_dir)
    _write_layout_first_readme(project_dir, project_name, plan, control_mode=args.control)
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
    control_mode: ControlMode,
) -> None:
    control_summary = (
        "low-side MOSFET return switching with a CTRL/PWM input pad"
        if control_mode == "low_side_mosfet"
        else "always-on LED strings"
    )
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
                f"- Physical branch summary: {_physical_branch_summary(plan)}.",
                f"- Control: {control_summary}.",
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
        f"{supply_voltage:g}V input, {_physical_branch_summary(plan)}."
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


def _render_board(
    plan: LedArtPlan,
    *,
    show_polarity_marks: bool,
    control_mode: ControlMode = "none",
) -> str:
    builder = KiCadBoardBuilder()
    pixels = plan.pixels
    net_refs = {name: builder.net(name) for name in ["VCC", "GND"]}
    if control_mode == "low_side_mosfet":
        for name in ("LOAD_NEG", "CTRL", "GATE"):
            net_refs[name] = builder.net(name)
    pixel_by_index = {pixel.index: pixel for pixel in pixels}
    for string in plan.strings:
        for net_name in _branch_net_names(string):
            net_refs[net_name] = builder.net(net_name)

    _add_silkscreen(builder, plan)
    _add_power_pads(builder, net_refs, plan, control_mode=control_mode)
    _add_power_rails(
        builder,
        net_refs,
        plan.strings,
        pixel_by_index,
        control_mode=control_mode,
    )
    if control_mode == "low_side_mosfet":
        _add_low_side_mosfet_control(builder, net_refs)
    for string in plan.strings:
        string_pixels = tuple(pixel_by_index[index] for index in string.pixel_indices)
        _add_led_string(
            builder,
            string,
            string_pixels,
            net_refs,
            show_polarity_marks=show_polarity_marks,
            return_net_name=_return_net_name(control_mode),
        )
    return builder.render(outline_end_mm=(BOARD_WIDTH_MM, BOARD_HEIGHT_MM))


def _add_power_pads(
    builder: KiCadBoardBuilder,
    net_refs: dict[str, NetRef],
    plan: LedArtPlan,
    *,
    control_mode: ControlMode,
) -> None:
    builder.add_power_pad(
        "VCC",
        7.0,
        VCC_RAIL_Y_MM,
        net=net_refs["VCC"],
        value=f"{plan.electrical.supply_voltage_v:g}V Input",
        reference_offset_mm=(-4.0, 0.0),
    )
    builder.add_power_pad(
        "GND",
        7.0,
        12.0,
        net=net_refs["GND"],
        value="Input Return",
        reference_offset_mm=(-4.0, 0.0),
    )
    if control_mode == "low_side_mosfet":
        builder.add_power_pad(
            "CTRL",
            16.0,
            107.3,
            net=net_refs["CTRL"],
            value="PWM / Switch Input",
            reference_offset_mm=(-5.0, 0.0),
        )


def _add_power_rails(
    builder: KiCadBoardBuilder,
    net_refs: dict[str, NetRef],
    strings: tuple[LedArtString, ...],
    pixel_by_index: dict[int, LedArtPixel],
    *,
    control_mode: ControlMode,
) -> None:
    first_bus_x = 18.0 if control_mode == "low_side_mosfet" else 11.0
    return_rail_x = 15.0 if control_mode == "low_side_mosfet" else 7.0
    return_net = net_refs[_return_net_name(control_mode)]
    vcc_taps_by_row: dict[float, set[float]] = {}
    gnd_taps_by_row: dict[float, set[float]] = {}
    for string in strings:
        first_pixel = pixel_by_index[string.pixel_indices[0]]
        last_pixel = pixel_by_index[string.pixel_indices[-1]]
        vcc_taps_by_row.setdefault(first_pixel.y, set()).add(first_pixel.vcc_tap_x)
        gnd_taps_by_row.setdefault(last_pixel.y, set()).add(last_pixel.gnd_tap_x)
    row_ys = sorted(set(vcc_taps_by_row) | set(gnd_taps_by_row))
    vcc_row_ys = sorted(vcc_taps_by_row)
    gnd_row_ys = sorted(gnd_taps_by_row)
    builder.add_segment(
        7.0,
        VCC_RAIL_Y_MM,
        first_bus_x,
        VCC_RAIL_Y_MM,
        width_mm=TRACE_WIDTH_MM,
        net=net_refs["VCC"],
    )
    builder.add_via(first_bus_x, VCC_RAIL_Y_MM, net=net_refs["VCC"])
    vcc_trunk_points = [
        VCC_RAIL_Y_MM,
        *(row_y - ROW_POWER_OFFSET_MM for row_y in vcc_row_ys),
    ]
    for start_y, end_y in zip(vcc_trunk_points, vcc_trunk_points[1:], strict=False):
        builder.add_via(first_bus_x, end_y, net=net_refs["VCC"])
        builder.add_segment(
            first_bus_x,
            start_y,
            first_bus_x,
            end_y,
            layer="B.Cu",
            width_mm=TRACE_WIDTH_MM,
            net=net_refs["VCC"],
        )
    return_trunk_points = [row_y + ROW_POWER_OFFSET_MM for row_y in gnd_row_ys]
    if control_mode == "none":
        return_trunk_points.insert(0, 12.0)
    else:
        return_trunk_points.append(104.5)
    for start_y, end_y in zip(return_trunk_points, return_trunk_points[1:], strict=False):
        builder.add_segment(
            return_rail_x,
            start_y,
            return_rail_x,
            end_y,
            width_mm=TRACE_WIDTH_MM,
            net=return_net,
        )
    if control_mode == "low_side_mosfet":
        builder.add_segment(
            return_rail_x,
            104.5,
            30.0,
            104.5,
            width_mm=0.65,
            net=return_net,
        )
    for row_y in row_ys:
        _add_bus_segments(
            builder,
            y_mm=row_y - ROW_POWER_OFFSET_MM,
            x_points=(first_bus_x, *sorted(vcc_taps_by_row.get(row_y, ()))),
            net=net_refs["VCC"],
        )
        _add_bus_segments(
            builder,
            y_mm=row_y + ROW_POWER_OFFSET_MM,
            x_points=(return_rail_x, *sorted(gnd_taps_by_row.get(row_y, ()))),
            net=return_net,
        )


def _add_bus_segments(
    builder: KiCadBoardBuilder,
    *,
    y_mm: float,
    x_points: tuple[float, ...],
    net: NetRef,
    layer: str = "F.Cu",
) -> None:
    points = tuple(dict.fromkeys(x_points))
    for start_x, end_x in zip(points, points[1:], strict=False):
        builder.add_segment(
            start_x,
            y_mm,
            end_x,
            y_mm,
            layer=layer,
            width_mm=TRACE_WIDTH_MM,
            net=net,
        )


def _add_pixel_tracks(
    builder: KiCadBoardBuilder,
    pixel: LedArtPixel,
    net_refs: dict[str, NetRef],
) -> None:
    builder.add_segment(
        pixel.vcc_tap_x,
        VCC_RAIL_Y_MM,
        pixel.vcc_tap_x,
        pixel.y,
        width_mm=TRACE_WIDTH_MM,
        net=net_refs["VCC"],
    )
    builder.add_segment(
        pixel.x - 1.05,
        pixel.y,
        pixel.x + 1.05,
        pixel.y,
        width_mm=TRACE_WIDTH_MM,
        net=net_refs[pixel.drive_net],
    )
    builder.add_segment(
        pixel.gnd_tap_x,
        pixel.y,
        pixel.gnd_tap_x,
        GND_RAIL_Y_MM,
        width_mm=TRACE_WIDTH_MM,
        net=net_refs["GND"],
    )


def _add_led_string(
    builder: KiCadBoardBuilder,
    string: LedArtString,
    pixels: tuple[LedArtPixel, ...],
    net_refs: dict[str, NetRef],
    *,
    show_polarity_marks: bool,
    return_net_name: str,
) -> None:
    first_pixel = pixels[0]
    builder.add_segment(
        first_pixel.vcc_tap_x,
        first_pixel.y - ROW_POWER_OFFSET_MM,
        first_pixel.vcc_tap_x,
        first_pixel.y,
        width_mm=TRACE_WIDTH_MM,
        net=net_refs["VCC"],
    )
    _add_resistor(
        builder,
        first_pixel,
        net_refs["VCC"],
        net_refs[_branch_net_name(string.index, 0)],
        string.resistor_ref,
        string.resistor_value_ohms,
    )
    for index, pixel in enumerate(pixels):
        left_net = net_refs[_branch_net_name(string.index, index)]
        right_net = (
            net_refs[_branch_net_name(string.index, index + 1)]
            if index < len(pixels) - 1
            else net_refs[return_net_name]
        )
        _add_led(
            builder,
            pixel,
            left_net,
            right_net,
            show_polarity_marks=show_polarity_marks,
        )
        if index == 0:
            _route_between_pads(
                builder,
                (pixel.x - 1.05, pixel.y),
                (pixel.x + 1.05, pixel.y),
                net_refs[_branch_net_name(string.index, 0)],
            )
        if index < len(pixels) - 1:
            next_pixel = pixels[index + 1]
            _route_between_pads(
                builder,
                (pixel.gnd_tap_x, pixel.y),
                (next_pixel.x + 1.05, next_pixel.y),
                net_refs[_branch_net_name(string.index, index + 1)],
                layer="B.Cu",
                use_vias=True,
            )
        else:
            builder.add_segment(
                pixel.gnd_tap_x,
                pixel.y,
                pixel.gnd_tap_x,
                pixel.y + ROW_POWER_OFFSET_MM,
                width_mm=TRACE_WIDTH_MM,
                net=net_refs[return_net_name],
            )


def _add_low_side_mosfet_control(
    builder: KiCadBoardBuilder,
    net_refs: dict[str, NetRef],
) -> None:
    gate = net_refs["GATE"]
    ctrl = net_refs["CTRL"]
    gnd = net_refs["GND"]
    load_neg = net_refs["LOAD_NEG"]

    builder.add_three_pad_smd_footprint(
        ThreePadSmdFootprintSpec(
            footprint="PCBSmith_NMOS_POWER_REAL",
            reference="Q1",
            value="Logic N-MOSFET",
            x_mm=30.0,
            y_mm=106.0,
            reference_offset_mm=(0.0, -4.0),
            body_width_mm=5.0,
            body_height_mm=4.0,
            pads=(
                ("G", -2.0, 1.3, 1.2, 1.4, gate),
                ("S", 2.0, 1.3, 1.4, 1.4, gnd),
                ("D", 0.0, -1.5, 3.0, 1.7, load_neg),
            ),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="RCTRL",
            value="100R",
            x_mm=23.0,
            y_mm=107.3,
            left_net=ctrl,
            right_net=gate,
            reference_offset_mm=(0.0, -2.0),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="RPD",
            value="100K",
            x_mm=30.0,
            y_mm=113.0,
            left_net=gate,
            right_net=gnd,
            reference_offset_mm=(0.0, 2.2),
        )
    )

    builder.add_segment(28.0, 107.3, 23.75, 107.3, width_mm=0.3, net=gate)
    builder.add_segment(28.0, 107.3, 28.0, 113.0, width_mm=0.3, net=gate)
    builder.add_segment(28.0, 113.0, 29.25, 113.0, width_mm=0.3, net=gate)
    builder.add_segment(16.0, 107.3, 22.25, 107.3, width_mm=0.3, net=ctrl)
    builder.add_segment(7.0, 12.0, 7.0, 116.0, width_mm=0.65, net=gnd)
    builder.add_segment(7.0, 116.0, 32.0, 116.0, width_mm=0.65, net=gnd)
    builder.add_segment(30.75, 113.0, 30.75, 116.0, width_mm=0.65, net=gnd)
    builder.add_segment(32.0, 107.3, 32.0, 116.0, width_mm=0.65, net=gnd)
    builder.add_text("CTRL/PWM", 15.0, 103.0, size_mm=1.0)
    builder.add_text("LOW-SIDE SWITCH", 32.0, 100.0, size_mm=0.9)


def _add_resistor(
    builder: KiCadBoardBuilder,
    pixel: LedArtPixel,
    left_net: NetRef,
    right_net: NetRef,
    reference: str,
    resistor_value_ohms: int,
) -> None:
    value_label = _format_resistor_value(resistor_value_ohms)
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference=reference,
            value=value_label,
            x_mm=pixel.resistor_x,
            y_mm=pixel.y,
            left_net=left_net,
            right_net=right_net,
            reference_offset_mm=(0.0, -2.0),
        )
    )
    builder.add_text(
        value_label,
        pixel.resistor_x,
        pixel.y + 2.1,
        size_mm=0.8,
    )


def _add_led(
    builder: KiCadBoardBuilder,
    pixel: LedArtPixel,
    left_net: NetRef,
    right_net: NetRef,
    *,
    show_polarity_marks: bool,
) -> None:
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_LED_0603_REAL",
            reference=pixel.led_ref,
            value="Red 0603",
            x_mm=pixel.led_x,
            y_mm=pixel.y,
            left_net=left_net,
            right_net=right_net,
            reference_offset_mm=(0.0, -2.0),
            silk_marker="cathode",
            show_anode_plus=show_polarity_marks,
        )
    )


def _branch_net_names(string: LedArtString) -> tuple[str, ...]:
    return tuple(_branch_net_name(string.index, index) for index in range(len(string.led_refs)))


def _branch_net_name(string_index: int, node_index: int) -> str:
    return f"STR{string_index}_{node_index}"


def _return_net_name(control_mode: ControlMode) -> str:
    if control_mode == "low_side_mosfet":
        return "LOAD_NEG"
    return "GND"


def _route_between_pads(
    builder: KiCadBoardBuilder,
    start: tuple[float, float],
    end: tuple[float, float],
    net: NetRef,
    *,
    layer: str = "F.Cu",
    use_vias: bool = False,
) -> None:
    if use_vias:
        builder.add_via(start[0], start[1], net=net)
        builder.add_via(end[0], end[1], net=net)
    builder.add_segment(
        start[0],
        start[1],
        end[0],
        end[1],
        layer=layer,
        width_mm=TRACE_WIDTH_MM,
        net=net,
    )


def _add_silkscreen(builder: KiCadBoardBuilder, plan: LedArtPlan) -> None:
    builder.add_text(
        f"VIR-LAB {plan.electrical.supply_voltage_v:g}V LED TEST",
        180,
        5,
        size_mm=2.0,
    )
    builder.add_text(
        (
            f"{plan.electrical.grouping_strategy}, "
            f"{_physical_branch_summary(plan)}"
        ),
        180,
        114,
        size_mm=1.2,
    )
    builder.add_text("VIR", 382, 88, size_mm=4.0)
    builder.add_text("LAB", 382, 97, size_mm=4.0)
    builder.add_rect(366, 78, 412, 108)


def _physical_branch_summary(plan: LedArtPlan) -> str:
    string_lengths = sorted({len(string.led_refs) for string in plan.strings})
    resistor_values = sorted({string.resistor_value_ohms for string in plan.strings})
    length_summary = _range_summary(string_lengths)
    resistor_summary = _range_summary(resistor_values, suffix="R")
    return f"{length_summary} LED/string, {resistor_summary}"


def _format_resistor_value(resistor_value_ohms: int) -> str:
    if resistor_value_ohms < 1000:
        return f"{resistor_value_ohms}R"
    if resistor_value_ohms % 1000 == 0:
        return f"{resistor_value_ohms // 1000}K"
    return f"{resistor_value_ohms // 1000}K{resistor_value_ohms % 1000 // 100}"


def _range_summary(values: list[int], *, suffix: str = "") -> str:
    if len(values) == 1:
        return f"{values[0]}{suffix}"
    return f"{values[0]}-{values[-1]}{suffix}"

if __name__ == "__main__":
    main()
