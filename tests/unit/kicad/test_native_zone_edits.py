from __future__ import annotations

import pytest
from tests.unit.kicad.test_final_fill_adapter import BOARD

from pcbsmith.kicad.native_zone_edits import merge_verified_fill

ZONE = "00000000-0000-0000-0000-000000000001"
FILL = '(filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 4 0) (xy 4 4) (xy 0 4)))'


def test_fill_preserves_non_fill_and_requires_declared_zone():
    source = BOARD.format(filled="").encode()
    filled = BOARD.format(filled=FILL).encode()
    merged, evidence = merge_verified_fill(source, filled, (ZONE,))
    assert evidence["changed_zone_ids"] == [ZONE]
    assert evidence["dependency_closure"][ZONE]["whole_zone_dependency"]
    assert merge_verified_fill(merged, filled, (ZONE,))[0] == merged
    with pytest.raises(ValueError, match="undeclared"):
        merge_verified_fill(source, filled, ())
    with pytest.raises(ValueError, match="zone intent"):
        merge_verified_fill(source, filled.replace(b"(priority 2)", b"(priority 3)"), (ZONE,))
    with pytest.raises(ValueError, match="inventory"):
        merge_verified_fill(source, filled.replace(ZONE.encode(), b"different"), (ZONE,))


def test_fill_state_is_derived_but_thermal_parameters_remain_protected():
    source = BOARD.format(filled="").replace("(fill yes", "(fill").encode()
    filled = BOARD.format(filled=FILL).encode()
    merged, evidence = merge_verified_fill(source, filled, (ZONE,))
    assert b"fill yes" in merged
    assert evidence["changed_zone_ids"] == [ZONE]
    with pytest.raises(ValueError, match="zone intent"):
        merge_verified_fill(source, filled.replace(b"thermal_gap 0.4", b"thermal_gap 0.2"), (ZONE,))


def test_inspection_exposes_native_zone_identity_and_vertices():
    from pcbsmith.kicad.native_edits import inspect_edit_objects

    zone = inspect_edit_objects(BOARD.format(filled=FILL).encode())[0]
    assert zone["id"] == ZONE
    assert zone["zone"]["net_fields"] == ["GND"]
    assert zone["zone"]["layer"] == "B.Cu"
    assert zone["zone"]["outline_points_mm"][0] == [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert zone["zone"]["filled_region_count"] == 1
