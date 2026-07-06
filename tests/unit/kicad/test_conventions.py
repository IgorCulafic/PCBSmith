"""Convention probes: geometry facts we paid live-DRC iterations to learn.

Each test pins a KiCad file-format or transform convention numerically
against the real library footprints, so a regression is caught by pytest
instead of by a wall of DRC violations (hardening plan 1.2).
"""

from __future__ import annotations

import math

from pcbsmith.kicad.board import FOOTPRINT_LIBRARY, rotate_offset
from pcbsmith.kicad.clover_board import _back_pad
from pcbsmith.kicad.library import load_footprint, render_embedded_footprint

RESISTOR = "Resistor_SMD:R_0603_1608Metric"
NET_TIE = "NetTie:NetTie-2_SMD_Pad2.0mm"


def _pad_local(footprint: str, pin: str) -> tuple[float, float]:
    pad = FOOTPRINT_LIBRARY[footprint].pads_named(pin)[0]
    return (pad.x_mm, pad.y_mm)


def test_front_rotation_pad_positions() -> None:
    # Pad 1 of a two-pin part sits at local (-x, 0). On the FRONT:
    # rotation 90 puts it at the BOTTOM, 270 on top, 180 to the east.
    # (Metal-detector lesson: assuming 90 = top produced 14 shorts.)
    dx, dy = _pad_local(RESISTOR, "1")
    assert dx < 0 and dy == 0
    assert rotate_offset(dx, dy, 90.0) == (0.0, -dx)   # bottom (y down)
    assert rotate_offset(dx, dy, 270.0) == (0.0, dx)   # top
    assert rotate_offset(dx, dy, 180.0) == (-dx, 0.0)  # east


def test_back_side_placement_uses_inverse_rotation_then_mirror() -> None:
    # Clover lesson: a rot-90 BACK part has its pads swapped versus the
    # front convention - the physical position uses the INVERSE angle
    # before the x-mirror. For pad 1 at local (-0.7875, 0), anchor (0,0):
    dx, _dy = _pad_local(RESISTOR, "1")
    x, y = _back_pad((0.0, 0.0), 90.0, (dx, 0.0))
    assert (round(x, 4), round(y, 4)) == (0.0, dx)     # TOP on the back
    x, y = _back_pad((0.0, 0.0), 270.0, (dx, 0.0))
    assert (round(x, 4), round(y, 4)) == (0.0, -dx)    # bottom on the back
    # Rotation 0 on the back simply mirrors x.
    x, y = _back_pad((0.0, 0.0), 0.0, (dx, 0.0))
    assert (round(x, 4), round(y, 4)) == (-dx, 0.0)


def test_embedded_pad_angles_are_total_angles() -> None:
    # KiCad file quirk: pad angles in .kicad_pcb are TOTAL angles
    # (footprint + local); positions stay local. A rotated TO-263 shorted
    # every pin pair before this was learned.
    rendered = render_embedded_footprint(
        load_footprint(RESISTOR),
        reference="R1",
        value="R",
        x_mm=50.0,
        y_mm=50.0,
        rotation=45.0,
        uuid_path="probe-r1",
        pad_nets={"1": (1, "/A"), "2": (2, "/B")},
    )
    dx, _dy = _pad_local(RESISTOR, "1")
    # Pad POSITION stays local, pad ANGLE is footprint+local = 45.
    assert f"(at {dx:g} 0 45)" in rendered
    # The footprint anchor carries the placement rotation too.
    assert "(at 50 50 45)" in rendered


def test_net_tie_pad_groups_survive_embedding() -> None:
    # Rule 9.2: the net-tie's legal-short declaration must reach the
    # board file verbatim, or DRC flags the coil junction as a short.
    rendered = render_embedded_footprint(
        load_footprint(NET_TIE),
        reference="L1",
        value="coil tie",
        x_mm=40.0,
        y_mm=40.0,
        rotation=0.0,
        uuid_path="probe-l1",
        pad_nets={"1": (1, "/A"), "2": (2, "/B")},
    )
    assert "net_tie_pad_groups" in rendered


def test_arbitrary_rotation_matches_the_right_angle_fast_paths() -> None:
    # The trig branch and the exact branch must agree at the boundaries.
    for angle in (90.0, 180.0, 270.0):
        exact = rotate_offset(1.2, -0.7, angle)
        # Nudge into the trig branch and compare.
        trig = rotate_offset(1.2, -0.7, angle + 1e-9)
        assert math.isclose(exact[0], trig[0], abs_tol=1e-6)
        assert math.isclose(exact[1], trig[1], abs_tol=1e-6)
