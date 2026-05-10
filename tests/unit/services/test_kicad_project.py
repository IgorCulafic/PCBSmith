from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from pcbsmith.services.kicad_project import create_kicad_project_skeleton


def _fixed_uuid() -> UUID:
    return UUID("11111111-2222-3333-4444-555555555555")


def test_create_kicad_project_skeleton_writes_core_project_files(tmp_path: Path) -> None:
    result = create_kicad_project_skeleton(
        tmp_path / "demo",
        "LED Blinker",
        uuid_factory=_fixed_uuid,
    )

    assert result.project_name == "LED_Blinker"
    assert result.project_file == tmp_path / "demo" / "LED_Blinker.kicad_pro"
    assert result.schematic_file == tmp_path / "demo" / "LED_Blinker.kicad_sch"
    assert result.board_file == tmp_path / "demo" / "LED_Blinker.kicad_pcb"

    assert result.project_file.exists()
    assert result.schematic_file.exists()
    assert result.board_file.exists()


def test_kicad_project_file_records_generated_metadata(tmp_path: Path) -> None:
    result = create_kicad_project_skeleton(
        tmp_path / "demo",
        "Demo Board",
        uuid_factory=_fixed_uuid,
    )

    project_data = json.loads(result.project_file.read_text(encoding="utf-8"))

    assert project_data["meta"]["filename"] == "Demo_Board.kicad_pro"
    assert project_data["pcbsmith"]["generated_by"] == "PCBSmith"
    assert project_data["pcbsmith"]["schema"] == "kicad-skeleton-v1"


def test_kicad_schematic_uses_pcbsmith_generator_and_root_uuid(tmp_path: Path) -> None:
    result = create_kicad_project_skeleton(
        tmp_path / "demo",
        "Demo Board",
        uuid_factory=_fixed_uuid,
    )

    schematic_text = result.schematic_file.read_text(encoding="utf-8")

    assert '(generator "PCBSmith")' in schematic_text
    assert "(uuid 11111111-2222-3333-4444-555555555555)" in schematic_text
    assert '(path "/" (page "1"))' in schematic_text


def test_kicad_board_uses_required_header_general_page_and_layers(tmp_path: Path) -> None:
    result = create_kicad_project_skeleton(
        tmp_path / "demo",
        "Demo Board",
        uuid_factory=_fixed_uuid,
    )

    board_text = result.board_file.read_text(encoding="utf-8")

    assert board_text.startswith("(kicad_pcb")
    assert '(generator "PCBSmith")' in board_text
    assert "(general" in board_text
    assert '(paper "A4")' in board_text
    assert '(0 "F.Cu" signal)' in board_text
    assert '(31 "B.Cu" signal)' in board_text
    assert '(44 "Edge.Cuts" user)' in board_text


def test_kicad_board_includes_default_edge_cuts_outline(tmp_path: Path) -> None:
    result = create_kicad_project_skeleton(
        tmp_path / "demo",
        "Demo Board",
        uuid_factory=_fixed_uuid,
    )

    board_text = result.board_file.read_text(encoding="utf-8")

    assert "(gr_rect" in board_text
    assert "(start 0 0)" in board_text
    assert "(end 100 80)" in board_text
    assert '(layer "Edge.Cuts")' in board_text


def test_create_kicad_project_skeleton_refuses_existing_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "existing.txt").write_text("do not overwrite\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Project target already exists"):
        create_kicad_project_skeleton(project_dir, "Demo Board")


def test_create_kicad_project_skeleton_rejects_blank_project_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Project name cannot be blank"):
        create_kicad_project_skeleton(tmp_path / "demo", "   ")
