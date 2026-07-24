"""Convention probes: geometry facts we paid live-DRC iterations to learn.

Each test pins a KiCad file-format or transform convention numerically
against the real library footprints, so a regression is caught by pytest
instead of by a wall of DRC violations (hardening plan 1.2).
"""

from __future__ import annotations

import math
from pathlib import Path

from pcbsmith.kicad.board import FOOTPRINT_LIBRARY, rotate_offset
from pcbsmith.kicad.clover_board import _back_pad
from pcbsmith.kicad.library import (
    ImportedFootprint,
    _measure,
    load_footprint,
    parse_sexpr,
    render_embedded_footprint,
)

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
    assert rotate_offset(dx, dy, 90.0) == (0.0, -dx)  # bottom (y down)
    assert rotate_offset(dx, dy, 270.0) == (0.0, dx)  # top
    assert rotate_offset(dx, dy, 180.0) == (-dx, 0.0)  # east


def test_back_side_placement_uses_inverse_rotation_then_mirror() -> None:
    # Clover lesson: a rot-90 BACK part has its pads swapped versus the
    # front convention - the physical position uses the INVERSE angle
    # before the x-mirror. For pad 1 at local (-0.7875, 0), anchor (0,0):
    dx, _dy = _pad_local(RESISTOR, "1")
    x, y = _back_pad((0.0, 0.0), 90.0, (dx, 0.0))
    assert (round(x, 4), round(y, 4)) == (0.0, dx)  # TOP on the back
    x, y = _back_pad((0.0, 0.0), 270.0, (dx, 0.0))
    assert (round(x, 4), round(y, 4)) == (0.0, -dx)  # bottom on the back
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


def test_netlist_standard_fields_merge_without_kicad_save_rewrites() -> None:
    rendered = render_embedded_footprint(
        load_footprint(RESISTOR),
        reference="R1",
        value="R",
        x_mm=40.0,
        y_mm=40.0,
        rotation=0.0,
        uuid_path="probe-r1-fields",
        pad_nets={"1": (1, "/A"), "2": (2, "/B")},
        extra_fields=(
            ("Footprint", RESISTOR),
            ("Datasheet", "datasheet.pdf"),
            ("Description", "fixture resistor"),
            ("Source", "fixture"),
        ),
    )

    assert rendered.count('(property "Datasheet"') == 1
    assert rendered.count('(property "Description"') == 1
    assert '(property "Datasheet" "datasheet.pdf"' in rendered
    assert '(property "Description" "fixture resistor"' in rendered
    assert '(property "Footprint"' not in rendered
    assert '(property "Source" "fixture"' in rendered


def test_legacy_fp_text_reference_is_bound_to_real_board_reference() -> None:
    tree = parse_sexpr(
        """(footprint "Legacy_Terminal"
  (version 20221018)
  (generator pcbnew)
  (layer "F.Cu")
  (fp_text reference "REF**" (at 0 -2) (layer "F.SilkS"))
  (fp_text value "OLD" (at 0 2) (layer "F.Fab") hide)
  (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu" "*.Mask"))
)
"""
    )
    imported = ImportedFootprint(
        library_id="Fixture:Legacy_Terminal",
        spec=_measure(tree, "Fixture:Legacy_Terminal"),
        source_file=Path("legacy-terminal.kicad_mod"),
        tree=tree,
    )

    rendered = render_embedded_footprint(
        imported,
        reference="J1",
        value="7461057",
        x_mm=20.0,
        y_mm=20.0,
        rotation=0.0,
        uuid_path="probe-legacy-j1",
        pad_nets={"1": (1, "/BAT_P")},
    )

    assert '(fp_text reference "J1"' in rendered
    assert '(fp_text value "7461057"' in rendered
    assert "REF**" not in rendered


def test_arbitrary_rotation_matches_the_right_angle_fast_paths() -> None:
    # The trig branch and the exact branch must agree at the boundaries.
    for angle in (90.0, 180.0, 270.0):
        exact = rotate_offset(1.2, -0.7, angle)
        # Nudge into the trig branch and compare.
        trig = rotate_offset(1.2, -0.7, angle + 1e-9)
        assert math.isclose(exact[0], trig[0], abs_tol=1e-6)
        assert math.isclose(exact[1], trig[1], abs_tol=1e-6)


def test_fp_rect_courtyards_produce_full_hulls() -> None:
    # fp_rect parses as two DIAGONAL corners; the hull of those is a
    # line and was silently discarded, blinding the virtual courtyard
    # check for every footprint that draws its F.CrtYd as one rect
    # (terminal blocks, D9 discs, solder-wire pads - caught live by
    # kicad-cli on the compacted flyback). The parsed hull must now
    # span the real library rect.
    from pcbsmith.kicad.board import FOOTPRINT_LIBRARY

    expected = {
        "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-2-5.08_1x02_P5.08mm_Horizontal": (
            -3.04,
            -6.4,
            8.13,
            5.8,
        ),
        "Capacitor_THT:C_Disc_D9.0mm_W5.0mm_P10.00mm": (-1.25, -2.75, 11.25, 2.75),
        "Connector_Wire:SolderWire-2.5sqmm_1x01_D2.4mm_OD3.6mm": (-2.55, -2.5, 2.55, 2.5),
    }
    for library_id, (x1, y1, x2, y2) in expected.items():
        hull = FOOTPRINT_LIBRARY[library_id].courtyard_hull
        assert hull is not None, f"{library_id} lost its courtyard hull"
        xs = [x for x, _ in hull]
        ys = [y for _, y in hull]
        assert (min(xs), min(ys), max(xs), max(ys)) == (x1, y1, x2, y2)


def test_padless_board_only_footprint_uses_fab_geometry() -> None:
    tree = parse_sexpr(
        """(footprint "Mechanical_Envelope"
  (version 20241229)
  (generator "PCBSmith")
  (layer "F.Cu")
  (attr board_only exclude_from_pos_files exclude_from_bom)
  (fp_rect (start -21 -41) (end 21 41)
    (stroke (width 0.25) (type default)) (fill none) (layer "F.Fab"))
)
"""
    )

    spec = _measure(tree, "Fixture:Mechanical_Envelope")

    assert spec.pads == ()
    assert spec.board_only
    assert spec.fab_rect == (-21.0, -41.0, 21.0, 41.0)
    assert (spec.x_min, spec.y_min, spec.x_max, spec.y_max) == (
        -21.0,
        -41.0,
        21.0,
        41.0,
    )
    assert spec.fab_hull is not None


def test_custom_pads_and_npth_holes_parse_their_real_geometry() -> None:
    # A custom pad's (size w h) is only its anchor; the copper is the
    # primitives (the SHT31 EP anchors at 1.0x1.0 but spans 1.0x1.7 -
    # kicad-cli caught a via parked on the unmodelled lobe). NPTH shell
    # holes must stay distinct from copper-carrying THT pads (routed
    # tracks crossed the USB-C alignment holes while they were
    # collapsed into "tht").
    from pcbsmith.kicad.board import FOOTPRINT_LIBRARY

    sensor = FOOTPRINT_LIBRARY["Sensor_Humidity:Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm"]
    ep = next(pad for pad in sensor.pads if pad.name == "9")
    assert (ep.width_mm, ep.height_mm) == (1.0, 1.7)

    usb = FOOTPRINT_LIBRARY["Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"]
    npth = [pad for pad in usb.pads if pad.kind == "npth"]
    assert [(pad.x_mm, pad.y_mm, pad.drill_mm) for pad in npth] == [
        (-2.89, -2.605, 0.65),
        (2.89, -2.605, 0.65),
    ]
