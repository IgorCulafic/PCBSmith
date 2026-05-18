from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.calculators.electronics import solve_lm2596_buck
from pcbsmith.core.circuit import CircuitComponent, CircuitDesign, CircuitNet, CircuitPin
from pcbsmith.kicad.kicad_board_builder import (
    KiCadBoardBuilder,
    MultiPadSmdFootprintSpec,
    NetRef,
    TwoPadSmdFootprintSpec,
)

BOARD_WIDTH_MM = 100.0
BOARD_HEIGHT_MM = 55.0
POWER_TRACE_WIDTH_MM = 1.0
SIGNAL_TRACE_WIDTH_MM = 0.3


class BuckConverterSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(default="LM2596 Buck Demo", min_length=1)
    input_voltage_min_v: float = Field(default=7.0, gt=0)
    input_voltage_nominal_v: float = Field(default=12.0, gt=0)
    input_voltage_max_v: float = Field(default=24.0, gt=0)
    output_voltage_v: float = Field(default=5.0, gt=0)
    load_current_a: float = Field(default=1.0, gt=0)


def buck_converter_calculation(spec: BuckConverterSpec) -> dict[str, object]:
    return solve_lm2596_buck(
        input_voltage_min_v=spec.input_voltage_min_v,
        input_voltage_nominal_v=spec.input_voltage_nominal_v,
        input_voltage_max_v=spec.input_voltage_max_v,
        output_voltage_v=spec.output_voltage_v,
        load_current_a=spec.load_current_a,
    )


def buck_converter_to_circuit_design(
    spec: BuckConverterSpec,
    calculation: dict[str, object],
) -> CircuitDesign:
    outputs = calculation["outputs"]
    assert isinstance(outputs, dict)
    upper = outputs["selected_feedback_upper_ohms"]
    lower = outputs["feedback_lower_ohms"]
    inductor = outputs["selected_inductance_uH"]
    input_cap = outputs["selected_input_capacitance_uF"]
    output_cap = outputs["selected_output_capacitance_uF"]
    return CircuitDesign(
        name=spec.name,
        nets=(
            CircuitNet(name="VIN", role="power_input"),
            CircuitNet(name="GND", role="ground"),
            CircuitNet(name="SW", role="switching_node"),
            CircuitNet(name="VOUT", role="power_output"),
            CircuitNet(name="FB", role="feedback"),
        ),
        components=(
            CircuitComponent(
                reference="J1",
                symbol_id="stdlib:CONN_01X02",
                value=f"VIN {spec.input_voltage_min_v:g}-{spec.input_voltage_max_v:g}V",
                pins=(CircuitPin(number="1", net="VIN"), CircuitPin(number="2", net="GND")),
            ),
            CircuitComponent(
                reference="U1",
                symbol_id="stdlib:LM2596_ADJ",
                value="LM2596-ADJ",
                pins=(
                    CircuitPin(number="1", net="VIN"),
                    CircuitPin(number="2", net="SW"),
                    CircuitPin(number="3", net="GND"),
                    CircuitPin(number="4", net="FB"),
                    CircuitPin(number="5", net="GND"),
                ),
            ),
            CircuitComponent(
                reference="L1",
                symbol_id="stdlib:L",
                value=f"{inductor:g}uH",
                pins=(CircuitPin(number="1", net="SW"), CircuitPin(number="2", net="VOUT")),
            ),
            CircuitComponent(
                reference="D1",
                symbol_id="stdlib:D",
                value="1N5822",
                pins=(CircuitPin(number="1", net="GND"), CircuitPin(number="2", net="SW")),
            ),
            CircuitComponent(
                reference="CIN",
                symbol_id="stdlib:C",
                value=f"{input_cap:g}uF",
                pins=(CircuitPin(number="1", net="VIN"), CircuitPin(number="2", net="GND")),
            ),
            CircuitComponent(
                reference="COUT",
                symbol_id="stdlib:C",
                value=f"{output_cap:g}uF",
                pins=(CircuitPin(number="1", net="VOUT"), CircuitPin(number="2", net="GND")),
            ),
            CircuitComponent(
                reference="RFB1",
                symbol_id="stdlib:R",
                value=f"{lower:g}R",
                pins=(CircuitPin(number="1", net="FB"), CircuitPin(number="2", net="GND")),
            ),
            CircuitComponent(
                reference="RFB2",
                symbol_id="stdlib:R",
                value=f"{upper:g}R",
                pins=(CircuitPin(number="1", net="VOUT"), CircuitPin(number="2", net="FB")),
            ),
            CircuitComponent(
                reference="J2",
                symbol_id="stdlib:CONN_01X02",
                value=f"VOUT {spec.output_voltage_v:g}V {spec.load_current_a:g}A",
                pins=(CircuitPin(number="1", net="VOUT"), CircuitPin(number="2", net="GND")),
            ),
        ),
        notes=(
            "LM2596 adjustable asynchronous buck converter.",
            "Keep SW loop short: U1 SW, D1, L1, and input/output return paths are layout-critical.",
        ),
    )


def render_buck_converter_board(
    spec: BuckConverterSpec,
    calculation: dict[str, object],
) -> str:
    outputs = calculation["outputs"]
    assert isinstance(outputs, dict)
    builder = KiCadBoardBuilder()
    vin = builder.net("VIN")
    gnd = builder.net("GND")
    sw = builder.net("SW")
    vout = builder.net("VOUT")
    fb = builder.net("FB")

    _add_connectors(builder, spec, vin=vin, gnd=gnd, vout=vout)
    _add_power_stage(builder, outputs, vin=vin, gnd=gnd, sw=sw, vout=vout, fb=fb)
    _add_routes(builder, vin=vin, gnd=gnd, sw=sw, vout=vout, fb=fb)
    _add_silkscreen(builder, spec, outputs)
    return builder.render(outline_end_mm=(BOARD_WIDTH_MM, BOARD_HEIGHT_MM))


def _add_connectors(
    builder: KiCadBoardBuilder,
    spec: BuckConverterSpec,
    *,
    vin: NetRef,
    gnd: NetRef,
    vout: NetRef,
) -> None:
    builder.add_power_pad(
        "VIN",
        8.0,
        14.0,
        net=vin,
        value=f"VIN {spec.input_voltage_min_v:g}-{spec.input_voltage_max_v:g}V",
        reference_offset_mm=(-5.0, 0.0),
    )
    builder.add_power_pad(
        "GND_IN",
        8.0,
        36.0,
        net=gnd,
        value="Input ground",
        reference_offset_mm=(5.0, 0.0),
    )
    builder.add_power_pad(
        "VOUT",
        92.0,
        14.0,
        net=vout,
        value=f"VOUT {spec.output_voltage_v:g}V",
        reference_offset_mm=(5.0, 0.0),
    )
    builder.add_power_pad(
        "GND_OUT",
        92.0,
        36.0,
        net=gnd,
        value="Output ground",
        reference_offset_mm=(-5.0, 0.0),
    )


def _add_power_stage(
    builder: KiCadBoardBuilder,
    outputs: dict[object, object],
    *,
    vin: NetRef,
    gnd: NetRef,
    sw: NetRef,
    vout: NetRef,
    fb: NetRef,
) -> None:
    builder.add_multi_pad_smd_footprint(
        MultiPadSmdFootprintSpec(
            footprint="PCBSmith_LM2596_TO263_REAL",
            reference="U1",
            value="LM2596-ADJ",
            x_mm=36.0,
            y_mm=24.0,
            body_width_mm=9.0,
            body_height_mm=10.0,
            show_silkscreen_outline=False,
            pads=(
                ("1", -5.2, -4.0, 1.5, 1.7, vin),
                ("2", 5.2, -4.0, 1.5, 1.7, sw),
                ("3", -5.2, 0.0, 1.5, 1.7, gnd),
                ("4", 5.2, 0.0, 1.5, 1.7, fb),
                ("5", -5.2, 4.0, 1.5, 1.7, gnd),
            ),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_L_POWER_REAL",
            reference="L1",
            value=f"{outputs['selected_inductance_uH']:g}uH",
            x_mm=57.0,
            y_mm=18.0,
            left_net=sw,
            right_net=vout,
            body_width_mm=8.0,
            body_height_mm=5.0,
            pad_offset_mm=4.2,
            pad_width_mm=1.8,
            pad_height_mm=2.4,
            reference_offset_mm=(0.0, -4.0),
            show_silkscreen_outline=False,
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_D_SCHOTTKY_REAL",
            reference="D1",
            value="1N5822",
            x_mm=49.0,
            y_mm=30.0,
            left_net=gnd,
            right_net=sw,
            body_width_mm=4.0,
            body_height_mm=2.0,
            pad_offset_mm=2.4,
            pad_width_mm=1.4,
            pad_height_mm=1.8,
            reference_offset_mm=(0.0, 3.0),
            silk_marker="cathode",
            show_anode_plus=True,
            anode_pad="1",
            show_silkscreen_outline=False,
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_C_ELEC_REAL",
            reference="CIN",
            value=f"{outputs['selected_input_capacitance_uF']:g}uF",
            x_mm=17.0,
            y_mm=22.0,
            left_net=vin,
            right_net=gnd,
            body_width_mm=5.5,
            body_height_mm=4.0,
            pad_offset_mm=2.8,
            reference_offset_mm=(0.0, -3.5),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_C_ELEC_REAL",
            reference="COUT",
            value=f"{outputs['selected_output_capacitance_uF']:g}uF",
            x_mm=78.0,
            y_mm=24.0,
            left_net=gnd,
            right_net=vout,
            body_width_mm=5.5,
            body_height_mm=4.0,
            pad_offset_mm=2.8,
            reference_offset_mm=(0.0, -3.5),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="RFB1",
            value=f"{outputs['feedback_lower_ohms']:g}R",
            x_mm=65.0,
            y_mm=30.0,
            left_net=fb,
            right_net=gnd,
            reference_offset_mm=(0.0, 2.0),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="RFB2",
            value=f"{outputs['selected_feedback_upper_ohms']:g}R",
            x_mm=65.0,
            y_mm=25.0,
            left_net=fb,
            right_net=vout,
            reference_offset_mm=(0.0, 2.0),
        )
    )


def _add_routes(
    builder: KiCadBoardBuilder,
    *,
    vin: NetRef,
    gnd: NetRef,
    sw: NetRef,
    vout: NetRef,
    fb: NetRef,
) -> None:
    _route(builder, ((8.0, 14.0), (14.2, 14.0), (14.2, 22.0)), vin)
    _route(builder, ((14.2, 22.0), (14.2, 18.0), (28.8, 18.0), (30.8, 20.0)), vin)
    _route(builder, ((8.0, 36.0), (92.0, 36.0)), gnd)
    _route(builder, ((19.8, 22.0), (21.8, 24.0), (21.8, 36.0)), gnd)
    _route(builder, ((30.8, 24.0), (30.8, 36.0)), gnd)
    _route(builder, ((30.8, 28.0), (30.8, 36.0)), gnd)
    _route(builder, ((46.6, 30.0), (46.6, 36.0)), gnd)
    _route(builder, ((75.2, 24.0), (75.2, 36.0)), gnd)
    _route(builder, ((65.75, 30.0), (65.75, 36.0)), gnd)
    _route(builder, ((41.2, 20.0), (50.8, 20.0), (52.8, 18.0)), sw)
    _route(builder, ((41.2, 20.0), (43.0, 20.0), (51.4, 28.4), (51.4, 30.0)), sw)
    _route(builder, ((61.2, 18.0), (74.8, 18.0), (80.8, 24.0)), vout)
    _route(builder, ((80.8, 24.0), (86.0, 24.0), (92.0, 18.0), (92.0, 14.0)), vout)
    _route(builder, ((65.75, 25.0), (65.75, 18.0)), vout)
    builder.add_via(43.0, 24.0, net=fb, size_mm=0.6, drill_mm=0.3)
    builder.add_via(62.0, 28.0, net=fb, size_mm=0.6, drill_mm=0.3)
    _route(builder, ((41.2, 24.0), (43.0, 24.0)), fb, width=SIGNAL_TRACE_WIDTH_MM)
    _route(
        builder,
        ((43.0, 24.0), (62.0, 24.0), (62.0, 28.0)),
        fb,
        layer="B.Cu",
        width=SIGNAL_TRACE_WIDTH_MM,
    )
    _route(
        builder,
        ((62.0, 28.0), (64.25, 28.0), (64.25, 25.0), (64.25, 30.0)),
        fb,
        width=SIGNAL_TRACE_WIDTH_MM,
    )


def _route(
    builder: KiCadBoardBuilder,
    points: tuple[tuple[float, float], ...],
    net: NetRef,
    *,
    layer: str = "F.Cu",
    width: float = POWER_TRACE_WIDTH_MM,
) -> None:
    for start, end in zip(points, points[1:], strict=False):
        if start == end:
            continue
        builder.add_segment(
            start[0],
            start[1],
            end[0],
            end[1],
            layer=layer,
            width_mm=width,
            net=net,
        )


def _add_silkscreen(
    builder: KiCadBoardBuilder,
    spec: BuckConverterSpec,
    outputs: dict[object, object],
) -> None:
    builder.add_text("VIN 7-24V", 9.0, 7.0, size_mm=1.2)
    builder.add_text("VOUT 5V 1A", 84.0, 7.0, size_mm=1.2)
    builder.add_text(spec.name, 50.0, 48.0, size_mm=1.6)
    builder.add_text(
        f"LM2596 ADJ | L={outputs['selected_inductance_uH']:g}uH | D=1N5822",
        50.0,
        51.0,
        size_mm=0.9,
    )


__all__ = [
    "BuckConverterSpec",
    "buck_converter_calculation",
    "buck_converter_to_circuit_design",
    "render_buck_converter_board",
]
