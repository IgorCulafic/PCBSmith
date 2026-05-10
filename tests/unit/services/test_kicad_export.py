from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import UUID

from pcbsmith.services.kicad_export import export_pcbs_project_to_kicad

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
