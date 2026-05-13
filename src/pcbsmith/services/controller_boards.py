from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.services.board_intelligence import routed_trace_segments
from pcbsmith.services.kicad_board_builder import (
    KiCadBoardBuilder,
    NetRef,
    TwoPadSmdFootprintSpec,
)


class AttinyLedControllerSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(default="ATtiny LED Controller", min_length=1)
    controller: str = Field(default="ATtiny84", min_length=1)
    led_outputs: int = Field(default=2, ge=1, le=2)
    led_resistor_value: str = Field(default="330R", min_length=1)
    show_polarity_marks: bool = True


def render_attiny_led_controller_board(
    spec: AttinyLedControllerSpec | None = None,
) -> str:
    board_spec = spec or AttinyLedControllerSpec()
    builder = KiCadBoardBuilder()
    nets = {
        name: builder.net(name)
        for name in (
            "VCC",
            "GND",
            "MISO",
            "MOSI",
            "SCK",
            "RESET",
            "LED1_IO",
            "LED1_A",
            "LED2_IO",
            "LED2_A",
            "PA0",
            "PA1",
            "PA2",
            "PA3",
            "PA7",
        )
    }

    _add_silkscreen(builder, board_spec)
    _add_power_input(builder, nets)
    _add_isp_header(builder, nets)
    _add_controller(builder, nets, board_spec)
    _add_support_passives(builder, nets)
    _add_led_outputs(builder, nets, board_spec)
    _add_gpio_labels(builder)
    _add_routes(builder, nets, board_spec)
    return builder.render(outline_end_mm=(95.0, 55.0))


def _add_silkscreen(
    builder: KiCadBoardBuilder,
    spec: AttinyLedControllerSpec,
) -> None:
    builder.add_text(spec.title, 47.5, 49.0, size_mm=1.5)
    builder.add_text("ISP", 14.0, 12.5, size_mm=1.0)
    builder.add_text("LED OUT", 72.0, 12.5, size_mm=1.0)
    builder.add_text("+", 4.2, 9.8, size_mm=1.0)
    builder.add_text("-", 4.2, 14.8, size_mm=1.0)
    builder.add_rect(3.0, 4.0, 92.0, 51.5, width_mm=0.15)


def _add_power_input(
    builder: KiCadBoardBuilder,
    nets: dict[str, NetRef],
) -> None:
    builder.add_power_pad(
        "VIN",
        8.0,
        10.0,
        net=nets["VCC"],
        value="5V Input",
        size_mm=2.2,
        reference_offset_mm=(-3.2, -1.8),
    )
    builder.add_power_pad(
        "GND",
        8.0,
        15.0,
        net=nets["GND"],
        value="Input Return",
        size_mm=2.2,
        reference_offset_mm=(-3.5, 1.8),
    )


def _add_isp_header(
    builder: KiCadBoardBuilder,
    nets: dict[str, NetRef],
) -> None:
    header_pads = (
        ("J1_VCC", "VCC", 24.0, 10.0),
        ("J1_RST", "RESET", 22.0, 24.0),
        ("J1_MOSI", "MOSI", 31.0, 33.0),
        ("J1_SCK", "SCK", 56.0, 14.0),
        ("J1_MISO", "MISO", 56.0, 33.0),
        ("J1_GND", "GND", 24.0, 42.0),
    )
    for reference, net_name, x_mm, y_mm in header_pads:
        builder.add_power_pad(
            reference,
            x_mm,
            y_mm,
            net=nets[net_name],
            value=net_name,
            size_mm=1.75,
            reference_offset_mm=(0.0, -1.7),
        )


def _add_controller(
    builder: KiCadBoardBuilder,
    nets: dict[str, NetRef],
    spec: AttinyLedControllerSpec,
) -> None:
    builder.add_rectangular_ic_footprint(
        footprint="PCBSmith_SOIC14_ATTINY_REAL",
        reference="U1",
        value=spec.controller,
        x_mm=43.0,
        y_mm=27.0,
        left_pads=(
            ("1", nets["VCC"]),
            ("2", nets["PA0"]),
            ("3", nets["PA1"]),
            ("4", nets["RESET"]),
            ("5", nets["PA7"]),
            ("6", nets["GND"]),
            ("7", nets["MOSI"]),
        ),
        right_pads=(
            ("14", nets["GND"]),
            ("13", nets["LED1_IO"]),
            ("12", nets["LED2_IO"]),
            ("11", nets["PA2"]),
            ("10", nets["PA3"]),
            ("9", nets["SCK"]),
            ("8", nets["MISO"]),
        ),
        body_width_mm=6.0,
        body_height_mm=5.0,
        pad_height_mm=0.75,
        pad_x_offset_mm=4.0,
        pin_pitch_mm=1.27,
    )


def _add_support_passives(
    builder: KiCadBoardBuilder,
    nets: dict[str, NetRef],
) -> None:
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_C_0603_REAL",
            reference="C1",
            value="100nF",
            x_mm=35.0,
            y_mm=16.0,
            left_net=nets["VCC"],
            right_net=nets["GND"],
            reference_offset_mm=(0.0, -2.0),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="RRESET",
            value="10K",
            x_mm=30.0,
            y_mm=23.0,
            left_net=nets["VCC"],
            right_net=nets["RESET"],
            reference_offset_mm=(0.0, -1.4),
        )
    )


def _add_led_outputs(
    builder: KiCadBoardBuilder,
    nets: dict[str, NetRef],
    spec: AttinyLedControllerSpec,
) -> None:
    for index, y_mm in enumerate((22.0, 34.0)[: spec.led_outputs], start=1):
        io_net = nets[f"LED{index}_IO"]
        anode_net = nets[f"LED{index}_A"]
        builder.add_two_pad_smd_footprint(
            TwoPadSmdFootprintSpec(
                footprint="PCBSmith_R_0603_REAL",
                reference=f"RLED{index}",
                value=spec.led_resistor_value,
                x_mm=63.0,
                y_mm=y_mm,
                left_net=io_net,
                right_net=anode_net,
                reference_offset_mm=(0.0, -1.4),
            )
        )
        builder.add_two_pad_smd_footprint(
            TwoPadSmdFootprintSpec(
                footprint="PCBSmith_LED_0603_REAL",
                reference=f"LED{index}",
                value="Status LED",
                x_mm=74.0,
                y_mm=y_mm,
                left_net=anode_net,
                right_net=nets["GND"],
                reference_offset_mm=(0.0, -2.0),
                silk_marker="cathode",
                show_anode_plus=spec.show_polarity_marks,
            )
        )


def _add_gpio_labels(builder: KiCadBoardBuilder) -> None:
    for label, x_mm, y_mm in (
        ("PA0", 51.5, 24.46),
        ("PA1", 51.5, 25.73),
        ("PA2", 51.5, 27.0),
        ("PA3", 51.5, 28.27),
        ("PA7", 34.5, 28.27),
    ):
        builder.add_text(label, x_mm, y_mm, size_mm=0.8)


def _add_routes(
    builder: KiCadBoardBuilder,
    nets: dict[str, NetRef],
    spec: AttinyLedControllerSpec,
) -> None:
    _route(builder, nets["VCC"], ((8.0, 10.0), (24.0, 10.0)))
    _route(builder, nets["VCC"], ((24.0, 10.0), (34.25, 10.0), (34.25, 16.0)))
    _route(builder, nets["VCC"], ((24.0, 10.0), (29.25, 10.0), (29.25, 23.0)))
    _route(builder, nets["VCC"], ((24.0, 10.0), (39.0, 10.0), (39.0, 23.19)))
    _route(builder, nets["GND"], ((8.0, 15.0), (8.0, 44.0), (80.0, 44.0)))
    _route(builder, nets["GND"], ((24.0, 42.0), (24.0, 44.0)))
    _route(builder, nets["GND"], ((35.75, 16.0), (35.75, 44.0)))
    _route(builder, nets["GND"], ((39.0, 29.54), (36.0, 29.54), (36.0, 44.0)))
    _route(builder, nets["GND"], ((47.0, 23.19), (47.0, 18.0), (80.0, 18.0), (80.0, 44.0)))
    _route(
        builder,
        nets["RESET"],
        ((30.75, 23.0), (22.0, 24.0), (22.0, 27.0), (39.0, 27.0)),
        layer="B.Cu",
        via_points=((30.75, 23.0), (22.0, 24.0), (39.0, 27.0)),
    )
    _route(
        builder,
        nets["MOSI"],
        ((31.0, 33.0), (36.81, 33.0), (39.0, 30.81)),
        layer="B.Cu",
        add_endpoint_vias=True,
    )
    _route(
        builder,
        nets["SCK"],
        ((47.0, 29.54), (47.0, 20.0), (53.0, 20.0), (56.0, 17.0), (56.0, 14.0)),
        layer="B.Cu",
        add_endpoint_vias=True,
    )
    _route(
        builder,
        nets["MISO"],
        ((47.0, 30.81), (47.0, 37.0), (56.0, 37.0), (56.0, 33.0)),
        layer="B.Cu",
        add_endpoint_vias=True,
    )
    _route(
        builder,
        nets["LED1_IO"],
        ((47.0, 24.46), (55.0, 24.46), (57.46, 22.0), (62.25, 22.0)),
    )
    _route(builder, nets["LED1_A"], ((63.75, 22.0), (73.25, 22.0)))
    _route(builder, nets["GND"], ((74.75, 22.0), (80.0, 27.25), (80.0, 44.0)))
    if spec.led_outputs >= 2:
        _route(
            builder,
            nets["LED2_IO"],
            ((47.0, 25.73), (54.0, 25.73), (62.25, 34.0)),
        )
        _route(builder, nets["LED2_A"], ((63.75, 34.0), (73.25, 34.0)))
        _route(builder, nets["GND"], ((74.75, 34.0), (80.0, 39.25), (80.0, 44.0)))


def _route(
    builder: KiCadBoardBuilder,
    net: NetRef,
    points: tuple[tuple[float, float], ...],
    *,
    layer: str = "F.Cu",
    width_mm: float = 0.35,
    add_endpoint_vias: bool = False,
    via_points: tuple[tuple[float, float], ...] = (),
) -> None:
    route_vias = set(via_points)
    if add_endpoint_vias:
        route_vias.update((points[0], points[-1]))
    for point in sorted(route_vias):
        builder.add_via(*point, net=net)
    for segment in routed_trace_segments(
        points,
        net_name=net.name,
        width_mm=width_mm,
    ):
        builder.add_segment(
            *segment.start,
            *segment.end,
            layer=layer,
            width_mm=segment.width_mm,
            net=net,
        )


__all__ = [
    "AttinyLedControllerSpec",
    "render_attiny_led_controller_board",
]
