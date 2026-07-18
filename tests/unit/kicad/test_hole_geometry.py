from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.hole_geometry import HoleGeometry, HolePlating, HoleShape
from pcbsmith.kicad.library import PadSpec, _measure, parse_sexpr


def test_hole_geometry_preserves_axes_rotation_plating_and_offset() -> None:
    hole = HoleGeometry(
        shape=HoleShape.OVAL,
        width_mm=0.5,
        height_mm=1.3,
        rotation_deg=-90.0,
        plating=HolePlating.PLATED,
        offset_x_mm=0.1,
        offset_y_mm=-0.2,
    )

    assert hole.minor_mm == 0.5
    assert hole.major_mm == 1.3
    assert hole.is_slot
    assert hole.rotation_deg == -90.0
    assert (hole.offset_x_mm, hole.offset_y_mm) == (0.1, -0.2)


def test_round_hole_rejects_unequal_axes() -> None:
    with pytest.raises(ValidationError, match="equal width and height"):
        HoleGeometry(
            shape=HoleShape.ROUND,
            width_mm=0.8,
            height_mm=0.9,
            plating=HolePlating.NON_PLATED,
        )


def test_pad_spec_keeps_legacy_scalar_drill_path() -> None:
    pad = PadSpec(
        name="1",
        x_mm=0.0,
        y_mm=0.0,
        kind="tht",
        width_mm=1.4,
        height_mm=1.4,
        drill_mm=0.8,
        angle_deg=90.0,
    )

    assert pad.drill_mm == 0.8
    assert pad.hole == HoleGeometry(
        shape=HoleShape.ROUND,
        width_mm=0.8,
        height_mm=0.8,
        rotation_deg=90.0,
        plating=HolePlating.PLATED,
    )


def test_kicad_parser_preserves_round_and_oval_drill_geometry() -> None:
    tree = parse_sexpr(
        """
        (footprint "GeometryProbe"
          (pad "1" thru_hole oval
            (at 1 2 90)
            (size 1.9 1.4)
            (drill oval 1.3 0.5 (offset 0.1 -0.2))
            (layers "*.Cu" "*.Mask"))
          (pad "" np_thru_hole circle
            (at -1 -2 30)
            (size 0.8 0.8)
            (drill 0.8)
            (layers "*.Cu" "*.Mask"))
          (pad "2" smd rect
            (at 0 0)
            (size 1 1)
            (layers "F.Cu" "F.Paste" "F.Mask")))
        """
    )

    spec = _measure(tree, "Test:GeometryProbe")
    oval, round_hole, smd = spec.pads

    assert oval.kind == "tht"
    assert oval.drill_mm == 1.3
    assert oval.hole == HoleGeometry(
        shape=HoleShape.OVAL,
        width_mm=1.3,
        height_mm=0.5,
        rotation_deg=90.0,
        plating=HolePlating.PLATED,
        offset_x_mm=0.1,
        offset_y_mm=-0.2,
    )
    assert round_hole.kind == "npth"
    assert round_hole.drill_mm == 0.8
    assert round_hole.hole == HoleGeometry(
        shape=HoleShape.ROUND,
        width_mm=0.8,
        height_mm=0.8,
        rotation_deg=30.0,
        plating=HolePlating.NON_PLATED,
    )
    assert smd.drill_mm == 0.0
    assert smd.hole is None
