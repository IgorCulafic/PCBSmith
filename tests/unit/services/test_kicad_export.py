from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from uuid import UUID

from pcbsmith.core.board import (
    Board,
    BoardEdgeLoop,
    BoardEdgeLoopRole,
    BoardGraphic,
    BoardGraphicKind,
    BoardText,
    Layer,
    Trace,
)
from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import NetLabel, NoConnect, Schematic, SymbolInstance, Wire
from pcbsmith.services.kicad_export import export_pcbs_project_to_kicad
from pcbsmith.services.project_io import create_project, save_board, save_schematic

FIXTURE = Path("tests/fixtures/voltage_divider")
LED_SERIES_FIXTURE = Path("tests/fixtures/led_series_circuit")


def _fixed_uuid() -> UUID:
    return UUID("11111111-2222-3333-4444-555555555555")


def _assert_hidden_label(schematic_text: str, name: str, x_mm: str, y_mm: str) -> None:
    assert re.search(
        rf'\(label "{re.escape(name)}"\s+'
        rf"\(at {re.escape(x_mm)} {re.escape(y_mm)} 0\)"
        r"\s+\(effects\s+"
        r"\(font\s+"
        r"\(size 0\.01 0\.01\)"
        r"\s+\)\s+"
        r"\(hide yes\)"
        r"\s+\)\s+"
        r'\(uuid "[^"]+"\)'
        r"\s+\)",
        schematic_text,
        re.DOTALL,
    )


def test_export_pcbs_project_to_kicad_creates_skeleton_and_handoff_manifest(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    shutil.copytree(FIXTURE, source_project)

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        project_name="Voltage Divider",
        uuid_factory=_fixed_uuid,
    )

    assert result.skeleton.project_file == output_project / "Voltage_Divider.kicad_pro"
    assert result.handoff_file == output_project / "pcbsmith_handoff.json"
    assert result.handoff_file.exists()
    assert (output_project / "PCBSmith.kicad_sym").exists()
    assert (output_project / "sym-lib-table").exists()


def test_export_native_multiterminal_symbols_invert_vertical_pin_y(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Native Parts")
    save_schematic(
        source_project,
        Path("schematics/main.sch.json"),
        Schematic(
            id="main",
            symbols=(
                SymbolInstance(
                    reference="RV1",
                    symbol_id="stdlib:POT",
                    value="100k",
                    position=Point.from_mm(0, 0),
                ),
                SymbolInstance(
                    reference="Q1",
                    symbol_id="stdlib:NMOS",
                    value="NMOS",
                    position=Point.from_mm(20, 0),
                ),
                SymbolInstance(
                    reference="J1",
                    symbol_id="stdlib:CONN_01X02",
                    value="Conn_01x02",
                    position=Point.from_mm(40, 0),
                ),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    symbol_library = (result.skeleton.project_dir / "PCBSmith.kicad_sym").read_text(
        encoding="utf-8"
    )
    assert re.search(
        r'\(symbol "POT_1_1".*?\(pin passive line\s+\(at 0\.00 5\.08 90\)',
        symbol_library,
        re.DOTALL,
    )
    assert re.search(
        r'\(symbol "NMOS_1_1".*?\(pin passive line\s+\(at 0\.00 -5\.08 270\)',
        symbol_library,
        re.DOTALL,
    )
    assert re.search(
        r'\(symbol "CONN_01X02_1_1".*?\(pin passive line\s+\(at 0\.00 -2\.54 0\)',
        symbol_library,
        re.DOTALL,
    )


def test_export_handoff_manifest_preserves_source_project_identity(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    shutil.copytree(FIXTURE, source_project)

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    manifest = json.loads(result.handoff_file.read_text(encoding="utf-8"))

    assert manifest["schema"] == "pcbsmith-kicad-handoff-v1"
    assert manifest["source_project"]["name"] == "Voltage Divider"
    assert manifest["source_project"]["schematic"] == "schematics/main.sch.json"
    assert manifest["kicad_project"]["name"] == "Voltage_Divider"


def test_export_handoff_manifest_emits_ordered_schematic_commands(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    shutil.copytree(FIXTURE, source_project)

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    manifest = json.loads(result.handoff_file.read_text(encoding="utf-8"))

    command_types = [command["type"] for command in manifest["commands"]]
    assert command_types == [
        "place_symbol",
        "place_symbol",
        "place_symbol",
        "place_symbol",
        "add_wire",
        "add_wire",
        "add_wire",
        "add_label",
        "add_label",
        "add_label",
    ]
    assert manifest["commands"][0] == {
        "type": "place_symbol",
        "reference": "V1",
        "symbol_id": "stdlib:VCC",
        "value": "VCC",
        "position_nm": {"x": 0, "y": 0},
        "rotation_deg": 0,
        "footprint_id": None,
        "mirrored_x": False,
    }
    assert manifest["commands"][4] == {
        "type": "add_wire",
        "points_nm": [{"x": 0, "y": 0}, {"x": 0, "y": 0}],
    }
    assert manifest["commands"][-1] == {
        "type": "add_label",
        "name": "GND",
        "position_nm": {"x": 30480000, "y": 0},
    }


def test_export_writes_native_symbols_wires_and_connected_net_labels(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    shutil.copytree(FIXTURE, source_project)

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")
    board_text = result.skeleton.board_file.read_text(encoding="utf-8")
    manifest = json.loads(result.handoff_file.read_text(encoding="utf-8"))

    assert '(lib_id "PCBSmith:VCC")' in schematic_text
    assert '(lib_id "PCBSmith:R")' in schematic_text
    assert '(lib_id "PCBSmith:GND")' in schematic_text
    assert '(property "Reference" "R1"' in schematic_text
    assert '(property "Value" "10k"' in schematic_text
    assert "(wire" in schematic_text
    assert "(xy 142.24 104.14) (xy 147.32 104.14)" in schematic_text
    assert "(xy 157.48 104.14) (xy 162.56 104.14)" in schematic_text
    assert '(label "VCC"' not in schematic_text
    assert '(label "OUT"' in schematic_text
    _assert_hidden_label(schematic_text, "GND", "157.48", "104.14")
    assert "(at 152.4 104.14 0)" in schematic_text
    assert '(net 1 "OUT")' in board_text
    assert '(net 2 "GND")' in board_text
    assert '(footprint "PCBSmith_R_0603"' in board_text
    assert (
        '(segment (start 137.5 107.5) (end 140.5 107.5) (width 0.25) '
        '(layer "F.Cu") (net 1)'
    ) in board_text
    assert (
        '(segment (start 143.5 107.5) (end 146.5 107.5) (width 0.25) '
        '(layer "F.Cu") (net 1)'
    ) in board_text
    assert "(at 127.5 111.5)" in board_text
    assert (
        '(segment (start 130.5 111.5) (end 127.5 111.5) (width 0.25) '
        '(layer "F.Cu") (net 2)'
    ) in board_text
    assert {
        "type": "add_wire",
        "points_nm": [{"x": 10160000, "y": 0}, {"x": 15240000, "y": 0}],
    } in manifest["commands"]
    assert {
        "type": "add_label",
        "name": "OUT",
        "position_nm": {"x": 15240000, "y": 0},
    } in manifest["commands"]


def test_export_writes_project_local_pcbs_library(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    shutil.copytree(FIXTURE, source_project)

    export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    library_text = (output_project / "PCBSmith.kicad_sym").read_text(encoding="utf-8")
    symbol_table_text = (output_project / "sym-lib-table").read_text(encoding="utf-8")

    assert '(symbol "R"' in library_text
    assert '(symbol "VCC"' in library_text
    assert '(symbol "GND"' in library_text
    assert '(name "PCBSmith")' in symbol_table_text
    assert '${KIPRJMOD}/PCBSmith.kicad_sym' in symbol_table_text


def test_export_translates_source_origin_into_visible_sheet_area(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Visible Origin Demo")
    save_schematic(
        source_project,
        "schematics/main.sch.json",
        Schematic(
            id="main",
            symbols=(
                SymbolInstance(
                    reference="R1",
                    symbol_id="stdlib:R",
                    value="10k",
                    position=Point.from_mm(0, 0),
                    footprint_id="stdlib:R_0603",
                ),
            ),
            no_connects=(
                NoConnect(position=Point.from_mm(-5.08, 0)),
                NoConnect(position=Point.from_mm(5.08, 0)),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")
    board_text = result.skeleton.board_file.read_text(encoding="utf-8")

    assert "(at 147.32 104.14 0)" in schematic_text
    assert "(at 142.24 104.14)" in schematic_text
    assert "(at 152.4 104.14)" in schematic_text
    assert "(at 133.5 107.5)" in board_text
    assert "(start 123.5 87.5)" in board_text
    assert "(end 183.5 127.5)" in board_text


def test_export_writes_common_passive_and_diode_family_symbols(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Common Parts Demo")
    save_schematic(
        source_project,
        "schematics/main.sch.json",
        Schematic(
            id="main",
            symbols=(
                SymbolInstance(
                    reference="C1",
                    symbol_id="stdlib:C",
                    value="100nF",
                    position=Point.from_mm(10.16, 0),
                    footprint_id="stdlib:C_0603",
                ),
                SymbolInstance(
                    reference="D1",
                    symbol_id="stdlib:D",
                    value="D",
                    position=Point.from_mm(30.48, 0),
                    footprint_id="stdlib:D_0603",
                ),
                SymbolInstance(
                    reference="LED1",
                    symbol_id="stdlib:LED",
                    value="LED",
                    position=Point.from_mm(50.8, 0),
                    footprint_id="stdlib:LED_0603",
                ),
            ),
            no_connects=(
                NoConnect(position=Point.from_mm(5.08, 0)),
                NoConnect(position=Point.from_mm(15.24, 0)),
                NoConnect(position=Point.from_mm(25.4, 0)),
                NoConnect(position=Point.from_mm(35.56, 0)),
                NoConnect(position=Point.from_mm(45.72, 0)),
                NoConnect(position=Point.from_mm(55.88, 0)),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")
    library_text = (output_project / "PCBSmith.kicad_sym").read_text(encoding="utf-8")

    assert '(lib_id "PCBSmith:C")' in schematic_text
    assert '(lib_id "PCBSmith:D")' in schematic_text
    assert '(lib_id "PCBSmith:LED")' in schematic_text
    assert '(symbol "C"' in library_text
    assert '(symbol "D"' in library_text
    assert '(symbol "LED"' in library_text
    assert "(length 2.54)" in library_text
    assert "(length 3.81)" in library_text
    assert "(length 4.318)" in library_text
    assert schematic_text.count("(no_connect") == 6


def test_export_writes_visible_led_series_circuit_fixture(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    shutil.copytree(LED_SERIES_FIXTURE, source_project)

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")
    board_text = result.skeleton.board_file.read_text(encoding="utf-8")
    manifest = json.loads(result.handoff_file.read_text(encoding="utf-8"))

    assert '(lib_id "PCBSmith:VCC")' in schematic_text
    assert '(lib_id "PCBSmith:R")' in schematic_text
    assert '(lib_id "PCBSmith:LED")' in schematic_text
    assert '(lib_id "PCBSmith:GND")' in schematic_text
    assert '(property "Reference" "R1"' in schematic_text
    assert '(property "Reference" "LED1"' in schematic_text
    assert '(property "Value" "330"' in schematic_text
    assert '(property "Value" "Red LED"' in schematic_text
    assert "(at 157.48 104.14 0)" in schematic_text
    assert "(xy 116.84 104.14) (xy 127 104.14)" in schematic_text
    assert "(xy 137.16 104.14) (xy 152.4 104.14)" in schematic_text
    assert "(xy 162.56 104.14) (xy 177.8 104.14)" in schematic_text
    _assert_hidden_label(schematic_text, "VCC", "127", "104.14")
    _assert_hidden_label(schematic_text, "LED_A", "144.78", "104.14")
    _assert_hidden_label(schematic_text, "GND", "162.56", "104.14")
    assert '(net 1 "VCC")' in board_text
    assert '(net 2 "LED_A")' in board_text
    assert '(net 3 "GND")' in board_text
    assert '(footprint "PCBSmith_R_0603"' in board_text
    assert '(footprint "PCBSmith_LED_0603"' in board_text
    assert '(footprint "PCBSmith_POWER_PAD"' in board_text
    assert '(property "Reference" "R1"' in board_text
    assert '(property "Reference" "LED1"' in board_text
    assert '(pad "1" smd roundrect' in board_text
    assert "(at 127.5 107.5)" in board_text
    assert "(at 127.5 111.5)" in board_text
    assert (
        '(segment (start 137.5 107.5) (end 140.5 107.5) (width 0.25) '
        '(layer "F.Cu") (net 2)'
    ) in board_text
    assert (
        '(segment (start 143.5 107.5) (end 146.5 107.5) (width 0.25) '
        '(layer "F.Cu") (net 2)'
    ) in board_text
    assert "(gr_rect" in board_text
    assert "(start 123.5 87.5)" in board_text
    assert "(end 183.5 127.5)" in board_text
    assert '(gr_text "PCBSmith Demo"' in board_text
    assert '(layer "F.SilkS")' in board_text
    assert '(layer "B.Cu") (net' not in board_text
    assert {
        "type": "place_symbol",
        "reference": "LED1",
        "symbol_id": "stdlib:LED",
        "value": "Red LED",
        "position_nm": {"x": 40640000, "y": 0},
        "rotation_deg": 0,
        "footprint_id": "stdlib:LED_0603",
        "mirrored_x": False,
    } in manifest["commands"]


def test_export_hides_signal_net_labels_on_wire_interiors(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "RC Filter Demo")
    save_schematic(
        source_project,
        "schematics/main.sch.json",
        Schematic(
            id="main",
            symbols=(
                SymbolInstance(
                    reference="V1",
                    symbol_id="stdlib:VCC",
                    value="VCC",
                    position=Point.from_mm(0, 0),
                ),
                SymbolInstance(
                    reference="R1",
                    symbol_id="stdlib:R",
                    value="10k",
                    position=Point.from_mm(15.24, 0),
                    footprint_id="stdlib:R_0603",
                ),
                SymbolInstance(
                    reference="C1",
                    symbol_id="stdlib:C",
                    value="100nF",
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
                NetLabel(name="VCC", position=Point.from_mm(0, 0)),
                NetLabel(name="OUT", position=Point.from_mm(27.94, 0)),
                NetLabel(name="GND", position=Point.from_mm(60.96, 0)),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")
    board_text = result.skeleton.board_file.read_text(encoding="utf-8")

    _assert_hidden_label(schematic_text, "OUT", "144.78", "104.14")
    assert '(footprint "PCBSmith_C_0603"' in board_text
    assert '(net 2 "OUT")' in board_text


def test_export_routes_non_aligned_board_nets_with_bent_tracks(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Bent Route Demo")
    save_schematic(
        source_project,
        "schematics/main.sch.json",
        Schematic(
            id="main",
            symbols=(
                SymbolInstance(
                    reference="R1",
                    symbol_id="stdlib:R",
                    value="330",
                    position=Point.from_mm(15.24, 0),
                    footprint_id="stdlib:R_0603",
                ),
                SymbolInstance(
                    reference="LED1",
                    symbol_id="stdlib:LED",
                    value="Red LED",
                    position=Point.from_mm(40.64, -10.16),
                    footprint_id="stdlib:LED_0603",
                ),
            ),
            wires=(
                Wire(points=(Point.from_mm(20.32, 0), Point.from_mm(25.4, 0))),
                Wire(points=(Point.from_mm(25.4, 0), Point.from_mm(25.4, -10.16))),
                Wire(points=(Point.from_mm(25.4, -10.16), Point.from_mm(35.56, -10.16))),
            ),
            labels=(NetLabel(name="DRIVE", position=Point.from_mm(22.86, 0)),),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    board_text = result.skeleton.board_file.read_text(encoding="utf-8")

    assert (
        '(segment (start 137.5 107.5) (end 146.5 97.34) (width 0.25) '
        '(layer "F.Cu") (net 1)'
    ) not in board_text
    assert (
        '(segment (start 146.5 97.34) (end 143.5 97.34) (width 0.25) '
        '(layer "F.Cu") (net 1)'
    ) in board_text
    assert (
        '(segment (start 142.75 97.34) (end 142 98.09) (width 0.25) '
        '(layer "F.Cu") (net 1)'
    ) in board_text
    assert (
        '(segment (start 140.5 107.5) (end 137.5 107.5) (width 0.25) '
        '(layer "F.Cu") (net 1)'
    ) in board_text


def test_export_keeps_floating_labels_in_handoff_only(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Floating Label Demo")
    save_schematic(
        source_project,
        "schematics/main.sch.json",
        Schematic(
            id="main",
            labels=(NetLabel(name="FLOAT", position=Point.from_mm(2.54, 5.08)),),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")
    manifest = json.loads(result.handoff_file.read_text(encoding="utf-8"))

    assert '(label "FLOAT"' not in schematic_text
    assert {
        "type": "add_label",
        "name": "FLOAT",
        "position_nm": {"x": 2540000, "y": 5080000},
    } in manifest["commands"]


def test_export_writes_no_connect_markers_to_kicad_schematic(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "No Connect Demo")
    save_schematic(
        source_project,
        "schematics/main.sch.json",
        Schematic(
            id="main",
            no_connects=(NoConnect(position=Point.from_mm(7.62, 10.16)),),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")

    assert "(no_connect" in schematic_text
    assert "(at 147.32 104.14)" in schematic_text


def test_export_renders_command_authored_board_text_and_route(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Board Command Demo")
    save_board(
        source_project,
        "boards/main.brd.json",
        Board(
            id="main",
            traces=(
                Trace(
                    net_name="LED_A",
                    layer=Layer.F_CU,
                    points=(Point.from_mm(4, 31), Point.from_mm(46, 31)),
                    width=250_000,
                ),
            ),
            texts=(
                BoardText(
                    text="AI LED Demo",
                    layer=Layer.F_SILK,
                    position=Point.from_mm(25, 31),
                    size=1_500_000,
                    thickness=150_000,
                ),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    board_text = result.skeleton.board_file.read_text(encoding="utf-8")

    assert '(net 1 "LED_A")' in board_text
    assert (
        '(segment (start 127.5 118.5) (end 169.5 118.5) (width 0.25) '
        '(layer "F.Cu") (net 1)'
    ) in board_text
    assert '(gr_text "AI LED Demo"' in board_text
    assert "(at 148.5 118.5 0)" in board_text


def test_export_renders_command_authored_silkscreen_graphics(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Silkscreen Graphic Demo")
    save_board(
        source_project,
        "boards/main.brd.json",
        Board(
            id="main",
            graphics=(
                BoardGraphic(
                    kind=BoardGraphicKind.LINE,
                    layer=Layer.F_SILK,
                    start=Point.from_mm(10, 10),
                    end=Point.from_mm(20, 10),
                    stroke_width=150_000,
                ),
                BoardGraphic(
                    kind=BoardGraphicKind.RECT,
                    layer=Layer.B_SILK,
                    start=Point.from_mm(30, 10),
                    end=Point.from_mm(38, 16),
                    stroke_width=200_000,
                ),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    board_text = result.skeleton.board_file.read_text(encoding="utf-8")

    assert "(gr_line" in board_text
    assert "(start 133.5 97.5)" in board_text
    assert "(end 143.5 97.5)" in board_text
    assert '(layer "F.SilkS")' in board_text
    assert "(gr_rect" in board_text
    assert "(start 153.5 97.5)" in board_text
    assert "(end 161.5 103.5)" in board_text
    assert "(width 0.2)" in board_text
    assert '(layer "B.SilkS")' in board_text


def test_export_renders_custom_edge_cuts_without_default_outline(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Custom Outline Demo")
    save_board(
        source_project,
        "boards/main.brd.json",
        Board(
            id="main",
            edge_cuts=(
                BoardEdgeLoop(
                    role=BoardEdgeLoopRole.OUTLINE,
                    points=(
                        Point.from_mm(0, 0),
                        Point.from_mm(40, 0),
                        Point.from_mm(40, 20),
                        Point.from_mm(0, 20),
                    ),
                ),
                BoardEdgeLoop(
                    role=BoardEdgeLoopRole.CUTOUT,
                    points=(
                        Point.from_mm(10, 5),
                        Point.from_mm(15, 5),
                        Point.from_mm(15, 10),
                        Point.from_mm(10, 10),
                    ),
                ),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    board_text = result.skeleton.board_file.read_text(encoding="utf-8")

    assert '(layer "Edge.Cuts")' in board_text
    assert board_text.count("(gr_line") == 8
    assert "(start 123.5 87.5)" in board_text
    assert "(end 163.5 87.5)" in board_text
    assert "(start 133.5 92.5)" in board_text
    assert "(end 138.5 92.5)" in board_text
    assert "(gr_rect" not in board_text
    assert "(end 183.5 127.5)" not in board_text


def test_export_skips_default_silkscreen_when_board_text_exists(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    shutil.copytree(LED_SERIES_FIXTURE, source_project)
    save_board(
        source_project,
        "boards/main.brd.json",
        Board(
            id="main",
            texts=(
                BoardText(
                    text="AI LED Demo",
                    layer=Layer.F_SILK,
                    position=Point.from_mm(25, 31),
                ),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    board_text = result.skeleton.board_file.read_text(encoding="utf-8")

    assert '(gr_text "AI LED Demo"' in board_text
    assert '(gr_text "PCBSmith Demo"' not in board_text


def test_export_writes_branched_schematic_and_board_nets(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad"
    create_project(source_project, "Branched Demo")
    save_schematic(
        source_project,
        "schematics/main.sch.json",
        Schematic(
            id="main",
            symbols=(
                SymbolInstance(
                    reference="V1",
                    symbol_id="stdlib:VCC",
                    value="VCC",
                    position=Point.from_mm(0, 0),
                ),
                SymbolInstance(
                    reference="R1",
                    symbol_id="stdlib:R",
                    value="330",
                    position=Point.from_mm(15.24, 0),
                    footprint_id="stdlib:R_0603",
                ),
                SymbolInstance(
                    reference="LED1",
                    symbol_id="stdlib:LED",
                    value="Red LED",
                    position=Point.from_mm(40.64, -10.16),
                    footprint_id="stdlib:LED_0603",
                ),
                SymbolInstance(
                    reference="C1",
                    symbol_id="stdlib:C",
                    value="100nF",
                    position=Point.from_mm(40.64, 10.16),
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
                Wire(points=(Point.from_mm(20.32, 0), Point.from_mm(25.4, 0))),
                Wire(points=(Point.from_mm(25.4, 0), Point.from_mm(25.4, -10.16))),
                Wire(points=(Point.from_mm(25.4, -10.16), Point.from_mm(35.56, -10.16))),
                Wire(points=(Point.from_mm(25.4, 0), Point.from_mm(25.4, 10.16))),
                Wire(points=(Point.from_mm(25.4, 10.16), Point.from_mm(35.56, 10.16))),
                Wire(points=(Point.from_mm(45.72, -10.16), Point.from_mm(50.8, -10.16))),
                Wire(points=(Point.from_mm(50.8, -10.16), Point.from_mm(50.8, 0))),
                Wire(points=(Point.from_mm(45.72, 10.16), Point.from_mm(50.8, 10.16))),
                Wire(points=(Point.from_mm(50.8, 10.16), Point.from_mm(50.8, 0))),
                Wire(points=(Point.from_mm(50.8, 0), Point.from_mm(60.96, 0))),
            ),
            labels=(
                NetLabel(name="VCC", position=Point.from_mm(0, 0)),
                NetLabel(name="DRIVE", position=Point.from_mm(22.86, 0)),
                NetLabel(name="GND", position=Point.from_mm(60.96, 0)),
            ),
        ),
    )

    result = export_pcbs_project_to_kicad(
        source_project,
        output_project,
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.skeleton.schematic_file.read_text(encoding="utf-8")
    board_text = result.skeleton.board_file.read_text(encoding="utf-8")

    assert "(xy 142.24 104.14) (xy 142.24 93.98)" in schematic_text
    assert "(xy 142.24 104.14) (xy 142.24 114.3)" in schematic_text
    _assert_hidden_label(schematic_text, "DRIVE", "139.7", "104.14")
    assert '(net 2 "DRIVE")' in board_text
    assert '(net 3 "GND")' in board_text
    assert "(at 150.5 97.34)" in board_text
    assert "(at 167.5 117.66)" in board_text
    assert '(gr_text "PCBSmith Demo"' in board_text
    assert "(at 148.5 92.5 0)" in board_text
    assert '(pad "1" smd roundrect' in board_text
    assert '(net 0 "")' not in board_text
    assert board_text.count('(footprint "PCBSmith_POWER_PAD"') == 2
