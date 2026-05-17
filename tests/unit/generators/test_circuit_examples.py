from __future__ import annotations

import re
from pathlib import Path

from pcbsmith.generators.circuit_examples import (
    CurrentLimitedLedCircuit,
    RcLowPassFilterCircuit,
    Timer555AstableCircuit,
    Timer555PwmDimmerCircuit,
    create_current_limited_led_project,
    create_rc_low_pass_filter_project,
    create_timer_555_astable_project,
    create_timer_555_pwm_dimmer_project,
    export_current_limited_led_kicad_project,
    export_rc_low_pass_filter_kicad_project,
    export_timer_555_astable_kicad_project,
    export_timer_555_pwm_dimmer_kicad_project,
)
from pcbsmith.kicad.kicad_export import export_pcbs_project_to_kicad
from pcbsmith.operations.project_io import load_board, load_project, load_schematic
from pcbsmith.rules.board_intelligence import segment_angle_degrees
from pcbsmith.rules.board_manufacturability import (
    ManufacturabilitySeverity,
    inspect_board_manufacturability,
)


def test_create_current_limited_led_project_writes_shared_schematic_and_board(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "source"

    result = create_current_limited_led_project(
        project_dir,
        CurrentLimitedLedCircuit(
            name="Schematic Backed LED",
            supply_voltage="5V",
            resistor_value="680",
            led_value="Red LED",
        ),
    )

    project = load_project(project_dir)
    schematic = load_schematic(project_dir, "schematics/main.sch.json")
    board = load_board(project_dir, "boards/main.brd.json")

    assert result.project_dir == project_dir
    assert result.schematic_path == "schematics/main.sch.json"
    assert result.board_path == "boards/main.brd.json"
    assert project.name == "Schematic Backed LED"
    assert [symbol.reference for symbol in schematic.symbols] == ["V1", "R1", "LED1", "G1"]
    assert [symbol.value for symbol in schematic.symbols] == ["5V", "680", "Red LED", "GND"]
    assert [label.name for label in schematic.labels] == ["VCC", "LED_A", "GND"]
    assert len(schematic.wires) == 3
    assert board.texts[0].text == "Schematic Backed LED"


def test_current_limited_led_project_exports_non_blank_kicad_schematic_and_board(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "kicad"
    create_current_limited_led_project(
        source_dir,
        CurrentLimitedLedCircuit(
            name="Schematic Backed LED",
            supply_voltage="5V",
            resistor_value="680",
            led_value="Red LED",
        ),
    )

    result = export_pcbs_project_to_kicad(source_dir, output_dir)

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")
    board_text = result.skeleton.board_file.read_text(encoding="utf-8")
    assert '(lib_id "PCBSmith:VCC")' in schematic_text
    assert '(lib_id "PCBSmith:R")' in schematic_text
    assert '(lib_id "PCBSmith:LED")' in schematic_text
    assert '(property "Value" "680"' in schematic_text
    assert '(footprint "PCBSmith_R_0603"' in board_text
    assert '(footprint "PCBSmith_LED_0603"' in board_text
    assert '(gr_text "Schematic Backed LED"' in board_text


def test_current_limited_led_direct_kicad_export_uses_clean_board_builder(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "kicad"

    result = export_current_limited_led_kicad_project(
        source_dir,
        output_dir,
        CurrentLimitedLedCircuit(
            name="Schematic Backed LED",
            supply_voltage="5V",
            resistor_value="680",
            led_value="Red LED",
        ),
    )

    schematic_text = result.schematic_file.read_text(encoding="utf-8")
    board_text = result.board_file.read_text(encoding="utf-8")
    assert result.source_project_dir == source_dir
    assert '(lib_id "PCBSmith:R")' in schematic_text
    assert '(lib_id "PCBSmith:LED")' in schematic_text
    assert '(footprint "PCBSmith_R_0603_REAL"' in board_text
    assert '(footprint "PCBSmith_LED_0603_REAL"' in board_text
    assert '(net 1 "VCC")' in board_text
    assert '(net 2 "LED_A")' in board_text
    assert '(net 3 "GND")' in board_text
    assert '(gr_text "Schematic Backed LED"' in board_text
    assert '(fp_text user "+"' in board_text


def test_current_limited_led_direct_kicad_export_can_disable_polarity_marks(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "kicad"

    result = export_current_limited_led_kicad_project(
        source_dir,
        output_dir,
        CurrentLimitedLedCircuit(
            name="Professional LED",
            show_polarity_marks=False,
        ),
    )

    board_text = result.board_file.read_text(encoding="utf-8")
    assert '(fp_text user "+"' not in board_text


def test_create_rc_low_pass_filter_project_writes_shared_schematic_and_board(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "source"

    result = create_rc_low_pass_filter_project(
        project_dir,
        RcLowPassFilterCircuit(
            name="RC Low Pass",
            resistor_value="10k",
            capacitor_value="100nF",
        ),
    )

    project = load_project(project_dir)
    schematic = load_schematic(project_dir, "schematics/main.sch.json")
    board = load_board(project_dir, "boards/main.brd.json")

    assert result.project_dir == project_dir
    assert result.schematic_path == "schematics/main.sch.json"
    assert result.board_path == "boards/main.brd.json"
    assert project.name == "RC Low Pass"
    assert [symbol.reference for symbol in schematic.symbols] == ["V1", "R1", "C1", "G1"]
    assert [symbol.value for symbol in schematic.symbols] == ["VCC", "10k", "100nF", "GND"]
    assert [label.name for label in schematic.labels] == ["VCC", "OUT", "GND"]
    assert len(schematic.wires) == 3
    assert board.texts[0].text == "RC Low Pass"


def test_rc_low_pass_filter_direct_kicad_export_uses_clean_board_builder(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "kicad"

    result = export_rc_low_pass_filter_kicad_project(
        source_dir,
        output_dir,
        RcLowPassFilterCircuit(
            name="RC Low Pass",
            resistor_value="10k",
            capacitor_value="100nF",
        ),
    )

    schematic_text = result.schematic_file.read_text(encoding="utf-8")
    board_text = result.board_file.read_text(encoding="utf-8")
    assert result.source_project_dir == source_dir
    assert '(lib_id "PCBSmith:R")' in schematic_text
    assert '(lib_id "PCBSmith:C")' in schematic_text
    assert '(footprint "PCBSmith_R_0603_REAL"' in board_text
    assert '(footprint "PCBSmith_C_0603_REAL"' in board_text
    assert '(net 1 "VCC")' in board_text
    assert '(net 2 "OUT")' in board_text
    assert '(net 3 "GND")' in board_text
    assert '(property "Reference" "R1"' in board_text
    assert '(property "Reference" "C1"' in board_text
    assert '(gr_text "RC Low Pass"' in board_text


def test_create_timer_555_astable_project_writes_shared_schematic_and_board(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "source"

    result = create_timer_555_astable_project(
        project_dir,
        Timer555AstableCircuit(name="555 Astable"),
    )

    project = load_project(project_dir)
    schematic = load_schematic(project_dir, "schematics/main.sch.json")
    board = load_board(project_dir, "boards/main.brd.json")

    assert result.project_dir == project_dir
    assert result.schematic_path == "schematics/main.sch.json"
    assert result.board_path == "boards/main.brd.json"
    assert project.name == "555 Astable"
    assert [symbol.reference for symbol in schematic.symbols] == [
        "V1",
        "U1",
        "R1",
        "R2",
        "C1",
        "C2",
        "C3",
        "R3",
        "LED1",
        "G1",
    ]
    assert list(dict.fromkeys(label.name for label in schematic.labels)) == [
        "VCC",
        "DISCH",
        "TIMING",
        "CTRL",
        "OUT",
        "LED_A",
        "GND",
    ]
    assert board.texts[0].text == "555 Astable"


def test_timer_555_astable_direct_kicad_export_uses_ic_and_support_parts(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "kicad"

    result = export_timer_555_astable_kicad_project(
        source_dir,
        output_dir,
        Timer555AstableCircuit(name="555 Astable"),
    )

    schematic_text = result.schematic_file.read_text(encoding="utf-8")
    board_text = result.board_file.read_text(encoding="utf-8")
    assert result.source_project_dir == source_dir
    assert '(lib_id "PCBSmith:NE555")' in schematic_text
    assert '(footprint "PCBSmith_SOIC8_NE555_REAL"' in board_text
    assert '(footprint "PCBSmith_R_0603_REAL"' in board_text
    assert '(footprint "PCBSmith_C_0603_REAL"' in board_text
    assert '(footprint "PCBSmith_LED_0603_REAL"' in board_text
    assert '(property "Reference" "U1"' in board_text
    assert '(property "Value" "NE555"' in board_text
    assert "(fp_circle" in board_text
    assert '(net 1 "VCC")' in board_text
    assert '(net 2 "GND")' in board_text
    assert '(net 3 "DISCH")' in board_text
    assert '(net 4 "TIMING")' in board_text
    assert '(net 5 "CTRL")' in board_text
    assert '(net 6 "OUT")' in board_text
    assert '(net 7 "LED_A")' in board_text
    assert "(via" in board_text
    assert '(layers "F.Cu" "B.Cu")' in board_text
    assert '(layer "B.Cu")' in board_text
    assert "(start 60 35)" in board_text
    assert "(end 154 96)" in board_text
    assert "(start 68 42.5)" in board_text
    assert "(end 69.5 41)" in board_text
    assert "(start 121.25 41)" in board_text
    assert "(end 119.75 42.5)" in board_text
    assert "(start 136.75 89)" in board_text
    assert "(end 138.25 87.5)" in board_text


def test_create_timer_555_pwm_dimmer_project_writes_shared_schematic_and_board(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "source"

    result = create_timer_555_pwm_dimmer_project(
        project_dir,
        Timer555PwmDimmerCircuit(name="555 PWM Dimmer"),
    )

    project = load_project(project_dir)
    schematic = load_schematic(project_dir, "schematics/main.sch.json")
    board = load_board(project_dir, "boards/main.brd.json")

    assert result.project_dir == project_dir
    assert project.name == "555 PWM Dimmer"
    assert {symbol.reference: symbol.symbol_id for symbol in schematic.symbols} == {
        "V1": "stdlib:VCC",
        "U1": "stdlib:NE555",
        "RV1": "stdlib:POT",
        "D1": "stdlib:D",
        "D2": "stdlib:D",
        "C1": "stdlib:C",
        "C2": "stdlib:C",
        "C3": "stdlib:C",
        "R1": "stdlib:R",
        "R2": "stdlib:R",
        "Q1": "stdlib:NMOS",
        "J1": "stdlib:CONN_01X02",
        "J2": "stdlib:CONN_01X02",
        "G1": "stdlib:GND",
    }
    assert [symbol.reference for symbol in schematic.symbols] == [
        "V1",
        "U1",
        "RV1",
        "D1",
        "D2",
        "C1",
        "C2",
        "C3",
        "R1",
        "R2",
        "Q1",
        "J1",
        "J2",
        "G1",
    ]
    assert list(dict.fromkeys(label.name for label in schematic.labels)) == [
        "VCC",
        "DISCH",
        "PWM_NODE",
        "CTRL",
        "OUT",
        "GATE",
        "LOAD_NEG",
        "GND",
    ]
    assert board.texts[0].text == "555 PWM Dimmer"


def test_timer_555_pwm_dimmer_direct_kicad_export_uses_power_and_load_parts(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "kicad"

    result = export_timer_555_pwm_dimmer_kicad_project(
        source_dir,
        output_dir,
        Timer555PwmDimmerCircuit(name="555 PWM Dimmer"),
    )

    schematic_text = result.schematic_file.read_text(encoding="utf-8")
    board_text = result.board_file.read_text(encoding="utf-8")
    assert result.source_project_dir == source_dir
    assert '(lib_id "PCBSmith:NE555")' in schematic_text
    assert '(lib_id "PCBSmith:POT")' in schematic_text
    assert '(lib_id "PCBSmith:NMOS")' in schematic_text
    assert '(lib_id "PCBSmith:CONN_01X02")' in schematic_text
    assert '(lib_id "PCBSmith:D")' in schematic_text
    assert '(footprint "PCBSmith_SOIC8_NE555_REAL"' in board_text
    assert '(footprint "PCBSmith_POT_3PIN_REAL"' in board_text
    assert '(footprint "PCBSmith_NMOS_POWER_REAL"' in board_text
    assert '(footprint "PCBSmith_POWER_INPUT_PAD"' in board_text
    assert '(net 1 "VCC")' in board_text
    assert '(net 2 "GND")' in board_text
    assert '(net 7 "GATE")' in board_text
    assert '(net 8 "LOAD_NEG")' in board_text
    assert '(gr_text "VIN 5-12V"' in board_text
    assert '(gr_text "LED OUT"' in board_text
    assert "(width 0.8)" in board_text
    assert "(start 60 35)" in board_text
    assert "(end 160 98)" in board_text


def test_timer_555_pwm_dimmer_board_uses_cardinal_or_45_degree_routing(
    tmp_path: Path,
) -> None:
    result = export_timer_555_pwm_dimmer_kicad_project(
        tmp_path / "source",
        tmp_path / "kicad",
        Timer555PwmDimmerCircuit(name="555 PWM Dimmer"),
    )

    off_style_segments = [
        (start, end, segment_angle_degrees(start, end))
        for start, end in _board_segments(result.board_file.read_text(encoding="utf-8"))
        if segment_angle_degrees(start, end) not in {0, 45, 90, 135, 180}
    ]

    assert off_style_segments == []


def test_timer_555_pwm_dimmer_board_has_no_manufacturability_errors(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "source"
    create_timer_555_pwm_dimmer_project(
        project_dir,
        Timer555PwmDimmerCircuit(name="555 PWM Dimmer"),
    )
    project = load_project(project_dir)
    board = load_board(project_dir, project.boards[0])

    report = inspect_board_manufacturability(board, design_rules=project.design_rules)

    assert [
        finding
        for finding in report.findings
        if finding.severity is ManufacturabilitySeverity.ERROR
    ] == []


def _board_segments(board_text: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segment_pattern = re.compile(
        r"\(segment\s+"
        r"\(start (?P<start_x>-?\d+(?:\.\d+)?) (?P<start_y>-?\d+(?:\.\d+)?)\)\s+"
        r"\(end (?P<end_x>-?\d+(?:\.\d+)?) (?P<end_y>-?\d+(?:\.\d+)?)\)",
        re.MULTILINE,
    )
    return [
        (
            (float(match.group("start_x")), float(match.group("start_y"))),
            (float(match.group("end_x")), float(match.group("end_y"))),
        )
        for match in segment_pattern.finditer(board_text)
    ]
