from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.services.kicad_board_builder import (
    KiCadBoardBuilder,
    NetRef,
    ThreePadSmdFootprintSpec,
    TwoPadSmdFootprintSpec,
)
from pcbsmith.services.led_art import LedArtPixel, LedArtPlan, LedArtString

BOARD_WIDTH_MM = 420.0
BOARD_HEIGHT_MM = 120.0
VCC_RAIL_Y_MM = 8.0
TRACE_WIDTH_MM = 0.45
ROW_POWER_OFFSET_MM = 3.0

LedArtControlMode = Literal["none", "low_side_mosfet"]


class LedArtBoardSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    show_polarity_marks: bool = True
    control_mode: LedArtControlMode = "none"
    title: str = "VIR-LAB"
    logo_text_lines: tuple[str, ...] = Field(default=("VIR", "LAB"), min_length=1)


def render_led_art_board(plan: LedArtPlan, spec: LedArtBoardSpec | None = None) -> str:
    board_spec = spec or LedArtBoardSpec()
    builder = KiCadBoardBuilder()
    pixels = plan.pixels
    net_refs = {name: builder.net(name) for name in ["VCC", "GND"]}
    if board_spec.control_mode == "low_side_mosfet":
        for name in ("LOAD_NEG", "CTRL", "GATE"):
            net_refs[name] = builder.net(name)
    pixel_by_index = {pixel.index: pixel for pixel in pixels}
    for string in plan.strings:
        for net_name in _branch_net_names(string):
            net_refs[net_name] = builder.net(net_name)

    _add_silkscreen(builder, plan, board_spec)
    _add_power_pads(builder, net_refs, plan, control_mode=board_spec.control_mode)
    _add_power_rails(
        builder,
        net_refs,
        plan.strings,
        pixel_by_index,
        control_mode=board_spec.control_mode,
    )
    if board_spec.control_mode == "low_side_mosfet":
        _add_low_side_mosfet_control(builder, net_refs)
    for string in plan.strings:
        string_pixels = tuple(pixel_by_index[index] for index in string.pixel_indices)
        _add_led_string(
            builder,
            string,
            string_pixels,
            net_refs,
            show_polarity_marks=board_spec.show_polarity_marks,
            return_net_name=_return_net_name(board_spec.control_mode),
        )
    return builder.render(outline_end_mm=(BOARD_WIDTH_MM, BOARD_HEIGHT_MM))


def led_art_physical_branch_summary(plan: LedArtPlan) -> str:
    string_lengths = sorted({len(string.led_refs) for string in plan.strings})
    resistor_values = sorted({string.resistor_value_ohms for string in plan.strings})
    length_summary = _range_summary(string_lengths)
    resistor_summary = _range_summary(resistor_values, suffix="R")
    return f"{length_summary} LED/string, {resistor_summary}"


def led_art_control_summary(control_mode: LedArtControlMode) -> str:
    if control_mode == "low_side_mosfet":
        return "low-side MOSFET return switching with a CTRL/PWM input pad"
    return "always-on LED strings"


def _add_power_pads(
    builder: KiCadBoardBuilder,
    net_refs: dict[str, NetRef],
    plan: LedArtPlan,
    *,
    control_mode: LedArtControlMode,
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
    control_mode: LedArtControlMode,
) -> None:
    first_bus_x = 18.0 if control_mode == "low_side_mosfet" else 11.0
    return_rail_x = 15.0 if control_mode == "low_side_mosfet" else 7.0
    return_net = net_refs[_return_net_name(control_mode)]
    vcc_taps_by_row: dict[float, set[float]] = {}
    return_taps_by_row: dict[float, set[float]] = {}
    for string in strings:
        first_pixel = pixel_by_index[string.pixel_indices[0]]
        last_pixel = pixel_by_index[string.pixel_indices[-1]]
        vcc_taps_by_row.setdefault(first_pixel.y, set()).add(first_pixel.vcc_tap_x)
        return_taps_by_row.setdefault(last_pixel.y, set()).add(last_pixel.gnd_tap_x)
    row_ys = sorted(set(vcc_taps_by_row) | set(return_taps_by_row))
    vcc_row_ys = sorted(vcc_taps_by_row)
    return_row_ys = sorted(return_taps_by_row)
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
    return_trunk_points = [row_y + ROW_POWER_OFFSET_MM for row_y in return_row_ys]
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
            x_points=(return_rail_x, *sorted(return_taps_by_row.get(row_y, ()))),
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


def _return_net_name(control_mode: LedArtControlMode) -> str:
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


def _add_silkscreen(
    builder: KiCadBoardBuilder,
    plan: LedArtPlan,
    spec: LedArtBoardSpec,
) -> None:
    builder.add_text(
        f"{spec.title} {plan.electrical.supply_voltage_v:g}V LED TEST",
        180,
        5,
        size_mm=2.0,
    )
    builder.add_text(
        (
            f"{plan.electrical.grouping_strategy}, "
            f"{led_art_physical_branch_summary(plan)}"
        ),
        180,
        114,
        size_mm=1.2,
    )
    for index, line in enumerate(spec.logo_text_lines):
        builder.add_text(line, 382, 88 + (index * 9), size_mm=4.0)
    builder.add_rect(366, 78, 412, 108)


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


__all__ = [
    "LedArtBoardSpec",
    "LedArtControlMode",
    "led_art_control_summary",
    "led_art_physical_branch_summary",
    "render_led_art_board",
]
