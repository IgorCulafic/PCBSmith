from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.board import Board, BoardText, Layer
from pcbsmith.core.geom import Point, Vec, mm_to_nm
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire
from pcbsmith.services.board_intelligence import (
    BoardPlacementFrame,
    RouteStylePolicy,
    classify_net_role,
    recommended_trace_width_mm,
    route_segments,
    styled_route_points,
    tap_route_points,
)
from pcbsmith.services.kicad_board_builder import (
    KiCadBoardBuilder,
    NetRef,
    TwoPadSmdFootprintSpec,
)
from pcbsmith.services.kicad_export import (
    PCBSMITH_SYMBOL_LIBRARY_FILE_NAME,
    PCBSMITH_SYMBOL_TABLE_FILE_NAME,
    render_kicad_schematic_items,
    render_pcbs_kicad_embedded_symbols,
    render_pcbs_kicad_symbol_library,
    render_pcbs_kicad_symbol_table,
)
from pcbsmith.services.kicad_project import (
    create_kicad_project_skeleton,
    render_kicad_schematic_file,
)
from pcbsmith.services.project_io import save_board, save_project, save_schematic

SCHEMATIC_PATH = "schematics/main.sch.json"
BOARD_PATH = "boards/main.brd.json"


class CurrentLimitedLedCircuit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    supply_voltage: str = "5V"
    resistor_value: str = "680"
    led_value: str = "Red LED"
    show_polarity_marks: bool = True


class RcLowPassFilterCircuit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    input_label: str = "VCC"
    output_label: str = "OUT"
    resistor_value: str = "10k"
    capacitor_value: str = "100nF"


class Timer555AstableCircuit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    supply_voltage: str = "5V"
    timing_resistor_a: str = "10k"
    timing_resistor_b: str = "100k"
    timing_capacitor: str = "10uF"
    decoupling_capacitor: str = "100nF"
    control_capacitor: str = "10nF"
    led_resistor: str = "680"
    led_value: str = "Red LED"
    show_polarity_marks: bool = True


class CircuitExampleProjectResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_dir: Path
    schematic_path: str
    board_path: str


class CircuitExampleKiCadResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_project_dir: Path
    project_dir: Path
    project_file: Path
    schematic_file: Path
    board_file: Path


def create_current_limited_led_project(
    project_dir: Path,
    circuit: CurrentLimitedLedCircuit,
) -> CircuitExampleProjectResult:
    project = Project(
        name=circuit.name,
        schematics=(SCHEMATIC_PATH,),
        boards=(BOARD_PATH,),
    )
    save_project(project_dir, project)
    save_schematic(project_dir, SCHEMATIC_PATH, _current_limited_led_schematic(circuit))
    save_board(project_dir, BOARD_PATH, _current_limited_led_board(circuit))
    return CircuitExampleProjectResult(
        project_dir=project_dir,
        schematic_path=SCHEMATIC_PATH,
        board_path=BOARD_PATH,
    )


def export_current_limited_led_kicad_project(
    source_project_dir: Path,
    output_project_dir: Path,
    circuit: CurrentLimitedLedCircuit,
) -> CircuitExampleKiCadResult:
    create_current_limited_led_project(source_project_dir, circuit)
    schematic = _current_limited_led_schematic(circuit)
    skeleton = create_kicad_project_skeleton(output_project_dir, circuit.name)
    (skeleton.project_dir / PCBSMITH_SYMBOL_LIBRARY_FILE_NAME).write_text(
        render_pcbs_kicad_symbol_library(),
        encoding="utf-8",
    )
    (skeleton.project_dir / PCBSMITH_SYMBOL_TABLE_FILE_NAME).write_text(
        render_pcbs_kicad_symbol_table(),
        encoding="utf-8",
    )
    skeleton.schematic_file.write_text(
        render_kicad_schematic_file(
            uuid4(),
            render_kicad_schematic_items(
                schematic,
                project_name=skeleton.project_name,
            ),
            lib_symbol_items=render_pcbs_kicad_embedded_symbols(),
        ),
        encoding="utf-8",
    )
    skeleton.board_file.write_text(
        _render_current_limited_led_board(circuit),
        encoding="utf-8",
    )
    return CircuitExampleKiCadResult(
        source_project_dir=source_project_dir,
        project_dir=skeleton.project_dir,
        project_file=skeleton.project_file,
        schematic_file=skeleton.schematic_file,
        board_file=skeleton.board_file,
    )


def create_rc_low_pass_filter_project(
    project_dir: Path,
    circuit: RcLowPassFilterCircuit,
) -> CircuitExampleProjectResult:
    project = Project(
        name=circuit.name,
        schematics=(SCHEMATIC_PATH,),
        boards=(BOARD_PATH,),
    )
    save_project(project_dir, project)
    save_schematic(project_dir, SCHEMATIC_PATH, _rc_low_pass_filter_schematic(circuit))
    save_board(project_dir, BOARD_PATH, _rc_low_pass_filter_board(circuit))
    return CircuitExampleProjectResult(
        project_dir=project_dir,
        schematic_path=SCHEMATIC_PATH,
        board_path=BOARD_PATH,
    )


def export_rc_low_pass_filter_kicad_project(
    source_project_dir: Path,
    output_project_dir: Path,
    circuit: RcLowPassFilterCircuit,
) -> CircuitExampleKiCadResult:
    create_rc_low_pass_filter_project(source_project_dir, circuit)
    schematic = _rc_low_pass_filter_schematic(circuit)
    skeleton = create_kicad_project_skeleton(output_project_dir, circuit.name)
    (skeleton.project_dir / PCBSMITH_SYMBOL_LIBRARY_FILE_NAME).write_text(
        render_pcbs_kicad_symbol_library(),
        encoding="utf-8",
    )
    (skeleton.project_dir / PCBSMITH_SYMBOL_TABLE_FILE_NAME).write_text(
        render_pcbs_kicad_symbol_table(),
        encoding="utf-8",
    )
    skeleton.schematic_file.write_text(
        render_kicad_schematic_file(
            uuid4(),
            render_kicad_schematic_items(
                schematic,
                project_name=skeleton.project_name,
            ),
            lib_symbol_items=render_pcbs_kicad_embedded_symbols(),
        ),
        encoding="utf-8",
    )
    skeleton.board_file.write_text(
        _render_rc_low_pass_filter_board(circuit),
        encoding="utf-8",
    )
    return CircuitExampleKiCadResult(
        source_project_dir=source_project_dir,
        project_dir=skeleton.project_dir,
        project_file=skeleton.project_file,
        schematic_file=skeleton.schematic_file,
        board_file=skeleton.board_file,
    )


def create_timer_555_astable_project(
    project_dir: Path,
    circuit: Timer555AstableCircuit,
) -> CircuitExampleProjectResult:
    project = Project(
        name=circuit.name,
        schematics=(SCHEMATIC_PATH,),
        boards=(BOARD_PATH,),
    )
    save_project(project_dir, project)
    save_schematic(project_dir, SCHEMATIC_PATH, _timer_555_astable_schematic(circuit))
    save_board(project_dir, BOARD_PATH, _timer_555_astable_board(circuit))
    return CircuitExampleProjectResult(
        project_dir=project_dir,
        schematic_path=SCHEMATIC_PATH,
        board_path=BOARD_PATH,
    )


def export_timer_555_astable_kicad_project(
    source_project_dir: Path,
    output_project_dir: Path,
    circuit: Timer555AstableCircuit,
) -> CircuitExampleKiCadResult:
    create_timer_555_astable_project(source_project_dir, circuit)
    schematic = _timer_555_astable_schematic(circuit)
    skeleton = create_kicad_project_skeleton(output_project_dir, circuit.name)
    (skeleton.project_dir / PCBSMITH_SYMBOL_LIBRARY_FILE_NAME).write_text(
        render_pcbs_kicad_symbol_library(),
        encoding="utf-8",
    )
    (skeleton.project_dir / PCBSMITH_SYMBOL_TABLE_FILE_NAME).write_text(
        render_pcbs_kicad_symbol_table(),
        encoding="utf-8",
    )
    skeleton.schematic_file.write_text(
        render_kicad_schematic_file(
            uuid4(),
            render_kicad_schematic_items(
                schematic,
                project_name=skeleton.project_name,
            ),
            lib_symbol_items=render_pcbs_kicad_embedded_symbols(),
        ),
        encoding="utf-8",
    )
    skeleton.board_file.write_text(
        _render_timer_555_astable_board(circuit),
        encoding="utf-8",
    )
    return CircuitExampleKiCadResult(
        source_project_dir=source_project_dir,
        project_dir=skeleton.project_dir,
        project_file=skeleton.project_file,
        schematic_file=skeleton.schematic_file,
        board_file=skeleton.board_file,
    )


def _current_limited_led_schematic(circuit: CurrentLimitedLedCircuit) -> Schematic:
    return Schematic(
        id="main",
        symbols=(
            SymbolInstance(
                reference="V1",
                symbol_id="stdlib:VCC",
                value=circuit.supply_voltage,
                position=Point.from_mm(0, 0),
            ),
            SymbolInstance(
                reference="R1",
                symbol_id="stdlib:R",
                value=circuit.resistor_value,
                position=Point.from_mm(15.24, 0),
                footprint_id="stdlib:R_0603",
            ),
            SymbolInstance(
                reference="LED1",
                symbol_id="stdlib:LED",
                value=circuit.led_value,
                position=Point.from_mm(40.64, 0),
                footprint_id="stdlib:LED_0603",
            ),
            SymbolInstance(
                reference="G1",
                symbol_id="stdlib:GND",
                value="GND",
                position=Point.from_mm(60.96, 0),
            ),
        ),
        wires=(
            Wire(points=(Point.from_mm(0, 0), Point.from_mm(10.16, 0))),
            Wire(points=(Point.from_mm(20.32, 0), Point.from_mm(35.56, 0))),
            Wire(points=(Point.from_mm(45.72, 0), Point.from_mm(60.96, 0))),
        ),
        labels=(
            NetLabel(name="VCC", position=Point.from_mm(0, 0)),
            NetLabel(name="LED_A", position=Point.from_mm(27.94, 0)),
            NetLabel(name="GND", position=Point.from_mm(60.96, 0)),
        ),
    )


def _rc_low_pass_filter_schematic(circuit: RcLowPassFilterCircuit) -> Schematic:
    return Schematic(
        id="main",
        symbols=(
            SymbolInstance(
                reference="V1",
                symbol_id="stdlib:VCC",
                value=circuit.input_label,
                position=Point.from_mm(0, 0),
            ),
            SymbolInstance(
                reference="R1",
                symbol_id="stdlib:R",
                value=circuit.resistor_value,
                position=Point.from_mm(15.24, 0),
                footprint_id="stdlib:R_0603",
            ),
            SymbolInstance(
                reference="C1",
                symbol_id="stdlib:C",
                value=circuit.capacitor_value,
                position=Point.from_mm(40.64, 0),
                footprint_id="stdlib:C_0603",
            ),
            SymbolInstance(
                reference="G1",
                symbol_id="stdlib:GND",
                value="GND",
                position=Point.from_mm(60.96, 0),
            ),
        ),
        wires=(
            Wire(points=(Point.from_mm(0, 0), Point.from_mm(10.16, 0))),
            Wire(points=(Point.from_mm(20.32, 0), Point.from_mm(35.56, 0))),
            Wire(points=(Point.from_mm(45.72, 0), Point.from_mm(60.96, 0))),
        ),
        labels=(
            NetLabel(name=circuit.input_label, position=Point.from_mm(0, 0)),
            NetLabel(name=circuit.output_label, position=Point.from_mm(27.94, 0)),
            NetLabel(name="GND", position=Point.from_mm(60.96, 0)),
        ),
    )


def _timer_555_astable_schematic(circuit: Timer555AstableCircuit) -> Schematic:
    u1 = Point.from_mm(35.56, 25.4)
    r1 = Point.from_mm(60.96, 12.7)
    r2 = Point.from_mm(60.96, 20.32)
    c1 = Point.from_mm(60.96, 30.48)
    c2 = Point.from_mm(15.24, 12.7)
    c3 = Point.from_mm(15.24, 30.48)
    r3 = Point.from_mm(60.96, 40.64)
    led1 = Point.from_mm(76.2, 40.64)
    vcc = Point.from_mm(10.16, 5.08)
    gnd = Point.from_mm(10.16, 48.26)
    wires: list[Wire] = []
    labels: list[NetLabel] = []
    _add_label_stub(wires, labels, "VCC", vcc, Point.from_mm(12.7, 5.08))
    _add_label_stub(wires, labels, "DISCH", _ne555_pin_point(u1, "7"), Point.from_mm(45.72, 22.86))
    _add_label_stub(wires, labels, "TIMING", _ne555_pin_point(u1, "2"), Point.from_mm(25.4, 22.86))
    _add_label_stub(wires, labels, "CTRL", _ne555_pin_point(u1, "5"), Point.from_mm(25.4, 27.94))
    _add_label_stub(wires, labels, "OUT", _ne555_pin_point(u1, "3"), Point.from_mm(45.72, 30.48))
    _add_label_stub(
        wires, labels, "LED_A", r3 + Vec(mm_to_nm(5.08), 0), Point.from_mm(68.58, 40.64)
    )
    _add_label_stub(wires, labels, "GND", gnd, Point.from_mm(12.7, 48.26))
    _add_label_stub(wires, labels, "GND", _ne555_pin_point(u1, "1"), Point.from_mm(25.4, 20.32))
    _add_label_stub(wires, labels, "TIMING", _ne555_pin_point(u1, "6"), Point.from_mm(45.72, 25.4))
    _add_label_stub(wires, labels, "VCC", _ne555_pin_point(u1, "4"), Point.from_mm(25.4, 25.4))
    _add_label_stub(wires, labels, "VCC", _ne555_pin_point(u1, "8"), Point.from_mm(45.72, 20.32))
    _add_label_stub(wires, labels, "VCC", r1 + Vec(mm_to_nm(-5.08), 0), Point.from_mm(53.34, 12.7))
    _add_label_stub(wires, labels, "DISCH", r1 + Vec(mm_to_nm(5.08), 0), Point.from_mm(68.58, 12.7))
    _add_label_stub(
        wires, labels, "DISCH", r2 + Vec(mm_to_nm(-5.08), 0), Point.from_mm(53.34, 20.32)
    )
    _add_label_stub(
        wires, labels, "TIMING", r2 + Vec(mm_to_nm(5.08), 0), Point.from_mm(68.58, 20.32)
    )
    _add_label_stub(
        wires, labels, "TIMING", c1 + Vec(mm_to_nm(-5.08), 0), Point.from_mm(53.34, 30.48)
    )
    _add_label_stub(wires, labels, "GND", c1 + Vec(mm_to_nm(5.08), 0), Point.from_mm(68.58, 30.48))
    _add_label_stub(wires, labels, "VCC", c2 + Vec(mm_to_nm(-5.08), 0), Point.from_mm(7.62, 12.7))
    _add_label_stub(wires, labels, "GND", c2 + Vec(mm_to_nm(5.08), 0), Point.from_mm(22.86, 12.7))
    _add_label_stub(wires, labels, "CTRL", c3 + Vec(mm_to_nm(-5.08), 0), Point.from_mm(7.62, 30.48))
    _add_label_stub(wires, labels, "GND", c3 + Vec(mm_to_nm(5.08), 0), Point.from_mm(22.86, 30.48))
    _add_label_stub(wires, labels, "OUT", r3 + Vec(mm_to_nm(-5.08), 0), Point.from_mm(53.34, 40.64))
    _add_label_stub(
        wires, labels, "LED_A", led1 + Vec(mm_to_nm(-5.08), 0), Point.from_mm(68.58, 40.64)
    )
    _add_label_stub(
        wires, labels, "GND", led1 + Vec(mm_to_nm(5.08), 0), Point.from_mm(83.82, 40.64)
    )
    return Schematic(
        id="main",
        symbols=(
            SymbolInstance(
                reference="V1",
                symbol_id="stdlib:VCC",
                value="VCC",
                position=vcc,
            ),
            SymbolInstance(
                reference="U1",
                symbol_id="stdlib:NE555",
                value="NE555",
                position=u1,
                footprint_id="stdlib:SOIC8",
            ),
            SymbolInstance(
                reference="R1",
                symbol_id="stdlib:R",
                value=circuit.timing_resistor_a,
                position=r1,
                footprint_id="stdlib:R_0603",
            ),
            SymbolInstance(
                reference="R2",
                symbol_id="stdlib:R",
                value=circuit.timing_resistor_b,
                position=r2,
                footprint_id="stdlib:R_0603",
            ),
            SymbolInstance(
                reference="C1",
                symbol_id="stdlib:C",
                value=circuit.timing_capacitor,
                position=c1,
                footprint_id="stdlib:C_0603",
            ),
            SymbolInstance(
                reference="C2",
                symbol_id="stdlib:C",
                value=circuit.decoupling_capacitor,
                position=c2,
                footprint_id="stdlib:C_0603",
            ),
            SymbolInstance(
                reference="C3",
                symbol_id="stdlib:C",
                value=circuit.control_capacitor,
                position=c3,
                footprint_id="stdlib:C_0603",
            ),
            SymbolInstance(
                reference="R3",
                symbol_id="stdlib:R",
                value=circuit.led_resistor,
                position=r3,
                footprint_id="stdlib:R_0603",
            ),
            SymbolInstance(
                reference="LED1",
                symbol_id="stdlib:LED",
                value=circuit.led_value,
                position=led1,
                footprint_id="stdlib:LED_0603",
            ),
            SymbolInstance(
                reference="G1",
                symbol_id="stdlib:GND",
                value="GND",
                position=gnd,
            ),
        ),
        wires=tuple(wires),
        labels=tuple(labels),
    )


def _add_label_stub(
    wires: list[Wire],
    labels: list[NetLabel],
    name: str,
    start: Point,
    end: Point,
) -> None:
    wires.append(Wire(points=(start, end)))
    labels.append(NetLabel(name=name, position=end))


def _ne555_pin_point(center: Point, pin_number: str) -> Point:
    offsets = {
        "1": Vec(mm_to_nm(-7.62), mm_to_nm(-5.08)),
        "2": Vec(mm_to_nm(-7.62), mm_to_nm(-2.54)),
        "3": Vec(mm_to_nm(7.62), mm_to_nm(5.08)),
        "4": Vec(mm_to_nm(-7.62), 0),
        "5": Vec(mm_to_nm(-7.62), mm_to_nm(2.54)),
        "6": Vec(mm_to_nm(7.62), 0),
        "7": Vec(mm_to_nm(7.62), mm_to_nm(-2.54)),
        "8": Vec(mm_to_nm(7.62), mm_to_nm(-5.08)),
    }
    return center + offsets[pin_number]


def _current_limited_led_board(circuit: CurrentLimitedLedCircuit) -> Board:
    return Board(
        id="main",
        texts=(
            BoardText(
                text=circuit.name,
                layer=Layer.F_SILK,
                position=Point.from_mm(25, 31),
                size=1_500_000,
                thickness=150_000,
            ),
        ),
    )


def _rc_low_pass_filter_board(circuit: RcLowPassFilterCircuit) -> Board:
    return Board(
        id="main",
        texts=(
            BoardText(
                text=circuit.name,
                layer=Layer.F_SILK,
                position=Point.from_mm(25, 31),
                size=1_500_000,
                thickness=150_000,
            ),
        ),
    )


def _timer_555_astable_board(circuit: Timer555AstableCircuit) -> Board:
    return Board(
        id="main",
        texts=(
            BoardText(
                text=circuit.name,
                layer=Layer.F_SILK,
                position=Point.from_mm(40, 51),
                size=1_500_000,
                thickness=150_000,
            ),
        ),
    )


def _render_current_limited_led_board(circuit: CurrentLimitedLedCircuit) -> str:
    builder = KiCadBoardBuilder()
    vcc = builder.net("VCC")
    led_a = builder.net("LED_A")
    gnd = builder.net("GND")
    builder.add_power_pad(
        "VCC",
        9.0,
        10.0,
        net=vcc,
        value=f"{circuit.supply_voltage} Input",
        reference_offset_mm=(-4.0, 0.0),
    )
    builder.add_power_pad(
        "GND",
        9.0,
        15.0,
        net=gnd,
        value="Return",
        reference_offset_mm=(-4.0, 0.0),
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="R1",
            value=circuit.resistor_value,
            x_mm=18.0,
            y_mm=10.0,
            left_net=vcc,
            right_net=led_a,
            reference_offset_mm=(0.0, -2.0),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_LED_0603_REAL",
            reference="LED1",
            value=circuit.led_value,
            x_mm=30.0,
            y_mm=10.0,
            left_net=led_a,
            right_net=gnd,
            reference_offset_mm=(0.0, -2.0),
            silk_marker="cathode",
            show_anode_plus=circuit.show_polarity_marks,
        )
    )
    builder.add_segment(9.0, 10.0, 17.25, 10.0, width_mm=0.45, net=vcc)
    builder.add_segment(18.75, 10.0, 29.25, 10.0, width_mm=0.45, net=led_a)
    builder.add_segment(30.75, 10.0, 35.0, 10.0, width_mm=0.45, net=gnd)
    builder.add_segment(35.0, 10.0, 35.0, 22.0, width_mm=0.45, net=gnd)
    builder.add_segment(35.0, 22.0, 9.0, 22.0, width_mm=0.45, net=gnd)
    builder.add_segment(9.0, 22.0, 9.0, 15.0, width_mm=0.45, net=gnd)
    builder.add_text(circuit.name, 25.0, 26.0, size_mm=1.5)
    builder.add_rect(0.0, 0.0, 50.0, 30.0, layer="F.Fab", width_mm=0.1)
    return builder.render(outline_end_mm=(50.0, 30.0))


def _render_rc_low_pass_filter_board(circuit: RcLowPassFilterCircuit) -> str:
    builder = KiCadBoardBuilder()
    vcc = builder.net(circuit.input_label)
    out = builder.net(circuit.output_label)
    gnd = builder.net("GND")
    builder.add_power_pad(
        circuit.input_label,
        8.0,
        10.0,
        net=vcc,
        value="Filter Input",
        reference_offset_mm=(-4.0, 0.0),
    )
    builder.add_power_pad(
        "GND",
        8.0,
        15.0,
        net=gnd,
        value="Return",
        reference_offset_mm=(-4.0, 0.0),
    )
    builder.add_power_pad(
        circuit.output_label,
        42.0,
        10.0,
        net=out,
        value="Filter Output",
        reference_offset_mm=(0.0, -2.2),
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="R1",
            value=circuit.resistor_value,
            x_mm=20.0,
            y_mm=10.0,
            left_net=vcc,
            right_net=out,
            reference_offset_mm=(0.0, -2.0),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_C_0603_REAL",
            reference="C1",
            value=circuit.capacitor_value,
            x_mm=32.0,
            y_mm=16.0,
            left_net=out,
            right_net=gnd,
            reference_offset_mm=(0.0, 2.2),
        )
    )
    builder.add_segment(8.0, 10.0, 19.25, 10.0, width_mm=0.45, net=vcc)
    builder.add_segment(20.75, 10.0, 42.0, 10.0, width_mm=0.45, net=out)
    builder.add_segment(28.0, 10.0, 31.25, 13.25, width_mm=0.45, net=out)
    builder.add_segment(31.25, 13.25, 31.25, 16.0, width_mm=0.45, net=out)
    builder.add_segment(32.75, 16.0, 38.0, 16.0, width_mm=0.45, net=gnd)
    builder.add_segment(38.0, 16.0, 38.0, 22.0, width_mm=0.45, net=gnd)
    builder.add_segment(38.0, 22.0, 8.0, 22.0, width_mm=0.45, net=gnd)
    builder.add_segment(8.0, 22.0, 8.0, 15.0, width_mm=0.45, net=gnd)
    builder.add_text(circuit.name, 25.0, 26.0, size_mm=1.5)
    builder.add_text(
        f"{circuit.resistor_value} / {circuit.capacitor_value}",
        25.0,
        28.5,
        size_mm=0.9,
    )
    builder.add_rect(0.0, 0.0, 50.0, 30.0, layer="F.Fab", width_mm=0.1)
    return builder.render(outline_end_mm=(50.0, 30.0))


def _render_timer_555_astable_board(circuit: Timer555AstableCircuit) -> str:
    frame = BoardPlacementFrame(origin_mm=(60.0, 35.0), size_mm=(94.0, 61.0))
    route_policy = RouteStylePolicy(chamfer_mm=1.5)

    def point(local_x_mm: float, local_y_mm: float) -> tuple[float, float]:
        return frame.point(local_x_mm, local_y_mm)

    def route(
        points: tuple[tuple[float, float], ...],
        *,
        net: NetRef,
        layer: str = "F.Cu",
        preserved_points: tuple[tuple[float, float], ...] = (),
    ) -> None:
        page_points = tuple(point(x_mm, y_mm) for x_mm, y_mm in points)
        page_preserved_points = tuple(
            point(x_mm, y_mm) for x_mm, y_mm in preserved_points
        )
        width_mm = recommended_trace_width_mm(classify_net_role(net.name))
        for start, end in route_segments(
            styled_route_points(
                page_points,
                policy=route_policy,
                preserved_points=page_preserved_points,
            )
        ):
            builder.add_segment(
                start[0],
                start[1],
                end[0],
                end[1],
                layer=layer,
                width_mm=width_mm,
                net=net,
            )

    def tap(
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        net: NetRef,
        side: int = 1,
        layer: str = "F.Cu",
    ) -> None:
        route(
            tap_route_points(start, end, side=side, policy=route_policy),
            net=net,
            layer=layer,
        )

    def via(via_x_mm: float, via_y_mm: float, *, net: NetRef) -> None:
        x_mm, y_mm = point(via_x_mm, via_y_mm)
        builder.add_via(x_mm, y_mm, net=net)

    builder = KiCadBoardBuilder()
    vcc = builder.net("VCC")
    gnd = builder.net("GND")
    disch = builder.net("DISCH")
    timing = builder.net("TIMING")
    ctrl = builder.net("CTRL")
    out = builder.net("OUT")
    led_a = builder.net("LED_A")

    builder.add_power_pad(
        "VCC",
        *point(8.0, 10.0),
        net=vcc,
        value=f"{circuit.supply_voltage} Input",
        reference_offset_mm=(-4.0, 0.0),
    )
    builder.add_power_pad(
        "GND",
        *point(8.0, 15.0),
        net=gnd,
        value="Return",
        reference_offset_mm=(-4.0, 0.0),
    )
    builder.add_rectangular_ic_footprint(
        footprint="PCBSmith_SOIC8_NE555_REAL",
        reference="U1",
        value="NE555",
        x_mm=point(35.0, 25.0)[0],
        y_mm=point(35.0, 25.0)[1],
        left_pads=(
            ("1", gnd),
            ("2", timing),
            ("4", vcc),
            ("5", ctrl),
        ),
        right_pads=(
            ("8", vcc),
            ("7", disch),
            ("6", timing),
            ("3", out),
        ),
        body_width_mm=12.0,
        body_height_mm=18.0,
        pad_width_mm=1.0,
        pad_height_mm=1.6,
        pad_x_offset_mm=8.0,
        pin_pitch_mm=4.0,
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="R1",
            value=circuit.timing_resistor_a,
            x_mm=point(62.0, 14.0)[0],
            y_mm=point(62.0, 14.0)[1],
            left_net=vcc,
            right_net=disch,
            reference_offset_mm=(0.0, -2.0),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="R2",
            value=circuit.timing_resistor_b,
            x_mm=point(62.0, 24.0)[0],
            y_mm=point(62.0, 24.0)[1],
            left_net=disch,
            right_net=timing,
            reference_offset_mm=(0.0, -2.0),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_C_0603_REAL",
            reference="C1",
            value=circuit.timing_capacitor,
            x_mm=point(76.0, 34.0)[0],
            y_mm=point(76.0, 34.0)[1],
            left_net=timing,
            right_net=gnd,
            reference_offset_mm=(0.0, 2.2),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_C_0603_REAL",
            reference="C2",
            value=circuit.decoupling_capacitor,
            x_mm=point(16.0, 14.0)[0],
            y_mm=point(16.0, 14.0)[1],
            left_net=vcc,
            right_net=gnd,
            reference_offset_mm=(0.0, -2.0),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_C_0603_REAL",
            reference="C3",
            value=circuit.control_capacitor,
            x_mm=point(24.0, 38.0)[0],
            y_mm=point(24.0, 38.0)[1],
            left_net=ctrl,
            right_net=gnd,
            reference_offset_mm=(0.0, 2.2),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="R3",
            value=circuit.led_resistor,
            x_mm=point(62.0, 44.0)[0],
            y_mm=point(62.0, 44.0)[1],
            left_net=out,
            right_net=led_a,
            reference_offset_mm=(0.0, 2.2),
        )
    )
    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_LED_0603_REAL",
            reference="LED1",
            value=circuit.led_value,
            x_mm=point(76.0, 44.0)[0],
            y_mm=point(76.0, 44.0)[1],
            left_net=led_a,
            right_net=gnd,
            reference_offset_mm=(0.0, 2.2),
            silk_marker="cathode",
            show_anode_plus=circuit.show_polarity_marks,
        )
    )

    route(((8.0, 10.0), (8.0, 6.0), (61.25, 6.0)), net=vcc)
    route(((8.0, 15.0), (8.0, 54.0), (76.75, 54.0)), net=gnd)
    for x_mm, y_mm in (
        (15.25, 14.0),
        (23.0, 27.0),
        (43.0, 19.0),
        (61.25, 14.0),
    ):
        tap((x_mm, 6.0), (x_mm, y_mm), net=vcc, side=-1)
    route(((23.0, 27.0), (27.0, 27.0)), net=vcc)
    for x_mm, y_mm in (
        (16.75, 14.0),
        (24.75, 38.0),
        (20.0, 19.0),
        (76.75, 34.0),
        (76.75, 44.0),
    ):
        side = 1 if x_mm > 70.0 else -1
        tap((x_mm, 54.0), (x_mm, y_mm), net=gnd, side=side)

    for x_mm, y_mm, net in (
        (27.0, 19.0, gnd),
        (20.0, 19.0, gnd),
        (43.0, 23.0, disch),
        (62.75, 14.0, disch),
        (61.25, 24.0, disch),
        (27.0, 23.0, timing),
        (43.0, 27.0, timing),
        (62.75, 24.0, timing),
        (75.25, 34.0, timing),
    ):
        via(x_mm, y_mm, net=net)

    route(((27.0, 19.0), (20.0, 19.0)), layer="B.Cu", net=gnd)
    route(
        ((43.0, 23.0), (52.0, 23.0), (52.0, 14.0), (62.75, 14.0)),
        layer="B.Cu",
        net=disch,
        preserved_points=((52.0, 23.0),),
    )
    route(((52.0, 23.0), (52.0, 24.0), (61.25, 24.0)), layer="B.Cu", net=disch)

    route(
        ((27.0, 23.0), (27.0, 35.0), (52.0, 35.0), (52.0, 27.0), (43.0, 27.0)),
        layer="B.Cu",
        net=timing,
    )
    route(
        ((43.0, 27.0), (66.0, 27.0), (66.0, 24.0), (62.75, 24.0)),
        layer="B.Cu",
        net=timing,
        preserved_points=((66.0, 24.0),),
    )
    route(
        ((66.0, 24.0), (70.0, 24.0), (70.0, 34.0), (75.25, 34.0)),
        layer="B.Cu",
        net=timing,
    )

    route(((27.0, 31.0), (23.25, 31.0), (23.25, 38.0)), net=ctrl)

    route(((43.0, 31.0), (58.0, 31.0), (58.0, 44.0), (61.25, 44.0)), net=out)
    route(((62.75, 44.0), (75.25, 44.0)), net=led_a)

    builder.add_text(circuit.name, *point(47.0, 56.0), size_mm=1.5)
    builder.add_text("NE555 astable LED blinker", *point(47.0, 58.5), size_mm=0.9)
    start_x_mm, start_y_mm = frame.outline_start_mm
    end_x_mm, end_y_mm = frame.outline_end_mm
    builder.add_rect(start_x_mm, start_y_mm, end_x_mm, end_y_mm, layer="F.Fab", width_mm=0.1)
    return builder.render(
        outline_start_mm=frame.outline_start_mm,
        outline_end_mm=frame.outline_end_mm,
    )


__all__ = [
    "CircuitExampleKiCadResult",
    "CircuitExampleProjectResult",
    "CurrentLimitedLedCircuit",
    "RcLowPassFilterCircuit",
    "Timer555AstableCircuit",
    "create_current_limited_led_project",
    "create_rc_low_pass_filter_project",
    "create_timer_555_astable_project",
    "export_current_limited_led_kicad_project",
    "export_rc_low_pass_filter_kicad_project",
    "export_timer_555_astable_kicad_project",
]
