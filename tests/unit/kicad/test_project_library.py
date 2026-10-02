from pathlib import Path

import pytest

from pcbsmith.kicad.project_library import (
    PCBSMITH_FOOTPRINT_LIBRARY_DIR_NAME,
    project_local_footprint_id,
    write_project_local_footprint_library,
)

BOARD = """(kicad_pcb
  (version 20241229)
  (generator "PCBSmith")
  (footprint "PCBSmith:Fixture_2P"
    (layer "F.Cu")
    (uuid 00000000-0000-0000-0000-000000000001)
    (at 10 20)
    (property "Reference" "J1" (at 0 -2 0) (layer "F.SilkS")
      (uuid 00000000-0000-0000-0000-000000000002))
    (property "Value" "Input" (at 0 2 0) (layer "F.Fab")
      (uuid 00000000-0000-0000-0000-000000000003))
    (pad "1" thru_hole circle (at 0 -1) (size 2 2) (drill 1)
      (layers "*.Cu" "*.Mask") (net 1 "VIN")
      (uuid 00000000-0000-0000-0000-000000000004))
    (pad "2" thru_hole circle (at 0 1) (size 2 2) (drill 1)
      (layers "*.Cu" "*.Mask") (net 2 "GND")
      (uuid 00000000-0000-0000-0000-000000000005))
  )
)
"""


def test_project_local_footprint_id_is_stable() -> None:
    assert project_local_footprint_id("Fixture") == "PCBSmith:Fixture"
    assert project_local_footprint_id("Vendor:Fixture") == "Vendor:Fixture"


def test_write_project_local_footprint_library_strips_instance_authority(
    tmp_path: Path,
) -> None:
    board_file = tmp_path / "fixture.kicad_pcb"
    board_file.write_text(BOARD, encoding="utf-8")

    written = write_project_local_footprint_library(tmp_path, board_file)

    assert len(written) == 1
    module = (tmp_path / PCBSMITH_FOOTPRINT_LIBRARY_DIR_NAME / "Fixture_2P.kicad_mod").read_text(
        encoding="utf-8"
    )
    assert '(footprint "Fixture_2P"' in module
    assert '(property "Reference" "REF**"' in module
    assert '(property "Value" "Fixture_2P"' in module
    assert "(net " not in module
    assert "(uuid " not in module
    assert "(at 10 20)" not in module
    assert "${KIPRJMOD}/PCBSmith.pretty" in (tmp_path / "fp-lib-table").read_text(encoding="utf-8")


def test_inconsistent_duplicate_geometry_fails_closed(tmp_path: Path) -> None:
    second = BOARD.split('  (footprint "PCBSmith:Fixture_2P"', maxsplit=1)[1]
    second = '  (footprint "PCBSmith:Fixture_2P"' + second.rsplit("\n)", maxsplit=1)[0]
    second = second.replace("(at 10 20)", "(at 30 20)").replace("(size 2 2)", "(size 3 2)", 1)
    duplicate = BOARD.rsplit("\n)", maxsplit=1)[0] + "\n" + second + "\n)\n"
    board_file = tmp_path / "fixture.kicad_pcb"
    board_file.write_text(duplicate, encoding="utf-8")

    with pytest.raises(ValueError, match="inconsistent embedded geometry"):
        write_project_local_footprint_library(tmp_path, board_file)
