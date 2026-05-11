from __future__ import annotations

from pathlib import Path

from pcbsmith.services.circuit_examples import (
    CurrentLimitedLedCircuit,
    RcLowPassFilterCircuit,
    Timer555AstableCircuit,
    create_current_limited_led_project,
    create_rc_low_pass_filter_project,
    create_timer_555_astable_project,
    export_current_limited_led_kicad_project,
    export_rc_low_pass_filter_kicad_project,
    export_timer_555_astable_kicad_project,
)
from pcbsmith.services.kicad_export import export_pcbs_project_to_kicad
from pcbsmith.services.project_io import load_board, load_project, load_schematic


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
