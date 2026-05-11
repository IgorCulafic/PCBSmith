from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.board import Board, BoardText, Layer
from pcbsmith.core.geom import Point
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire
from pcbsmith.services.kicad_board_builder import (
    KiCadBoardBuilder,
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


__all__ = [
    "CircuitExampleKiCadResult",
    "CircuitExampleProjectResult",
    "CurrentLimitedLedCircuit",
    "RcLowPassFilterCircuit",
    "create_current_limited_led_project",
    "create_rc_low_pass_filter_project",
    "export_current_limited_led_kicad_project",
    "export_rc_low_pass_filter_kicad_project",
]
