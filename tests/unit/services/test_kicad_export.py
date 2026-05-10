from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import UUID

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import NetLabel, NoConnect, Schematic, SymbolInstance
from pcbsmith.services.kicad_export import export_pcbs_project_to_kicad
from pcbsmith.services.project_io import create_project, save_schematic

FIXTURE = Path("tests/fixtures/voltage_divider")


def _fixed_uuid() -> UUID:
    return UUID("11111111-2222-3333-4444-555555555555")


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
    manifest = json.loads(result.handoff_file.read_text(encoding="utf-8"))

    assert '(lib_id "PCBSmith:VCC")' in schematic_text
    assert '(lib_id "PCBSmith:R")' in schematic_text
    assert '(lib_id "PCBSmith:GND")' in schematic_text
    assert '(property "Reference" "R1"' in schematic_text
    assert '(property "Value" "10k"' in schematic_text
    assert "(wire" in schematic_text
    assert "(xy 10.16 0) (xy 15.24 0)" in schematic_text
    assert "(xy 25.4 0) (xy 30.48 0)" in schematic_text
    assert '(label "VCC"' in schematic_text
    assert '(label "OUT"' in schematic_text
    assert '(label "GND"' in schematic_text
    assert "(at 25.4 0 0)" in schematic_text
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
    assert schematic_text.count("(no_connect") == 6


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
    assert "(at 7.62 10.16)" in schematic_text
