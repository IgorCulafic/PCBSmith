from __future__ import annotations

from tests.unit.kicad.test_led_art_board import _fixture

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    render_board_from_layout,
    rotate_offset,
)
from pcbsmith.kicad.led_art_board import compute_led_art_board_layout
from pcbsmith.kicad.library import (
    SilkLine,
    SilkText,
    load_footprint,
)


def test_rotate_offset_right_angles() -> None:
    # KiCad rotations are CCW on screen with y pointing down. Right angles
    # stay exact; arbitrary angles (tangent-following art placements) use
    # the same convention.
    assert rotate_offset(2.54, 0.0, 0) == (2.54, 0.0)
    assert rotate_offset(2.54, 0.0, 90) == (0.0, -2.54)
    assert rotate_offset(2.54, 0.0, 180) == (-2.54, 0.0)
    assert rotate_offset(2.54, 0.0, 270) == (0.0, 2.54)
    x, y = rotate_offset(1.0, 0.0, 45)
    assert (round(x, 6), round(y, 6)) == (0.707107, -0.707107)


def test_library_specs_come_from_official_footprints() -> None:
    led = FOOTPRINT_LIBRARY["LED_SMD:LED_0603_1608Metric"]
    # Real KiCad pad positions, not the old hand-drawn approximation.
    assert {pad.x_mm for pad in led.pads} == {-0.7875, 0.7875}
    # The official silkscreen closes with a cathode bar: a vertical line at
    # the pad-1 end.
    assert any(
        isinstance(mark, SilkLine) and mark.x1 == mark.x2 and mark.x1 < -1.0
        for mark in led.silk_marks
    )

    header = FOOTPRINT_LIBRARY[
        "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    ]
    assert header.is_connector
    # The official 1x02 vertical header stacks its pads in y.
    assert [(pad.x_mm, pad.y_mm) for pad in header.pads] == [(0.0, 0.0), (0.0, 2.54)]
    texts = {mark.text for mark in header.silk_marks if isinstance(mark, SilkText)}
    assert texts == {"+", "-"}

    hole = FOOTPRINT_LIBRARY["MountingHole:MountingHole_3.2mm_M3"]
    assert hole.board_only

    to263 = FOOTPRINT_LIBRARY["Package_TO_SOT_SMD:TO-263-5_TabPin3"]
    assert len(to263.pads_named("3")) == 2  # pin 3 and the tab


def test_embedded_footprint_carries_nets_and_parity_path() -> None:
    from pcbsmith.kicad.library import render_embedded_footprint

    text = render_embedded_footprint(
        load_footprint("LED_SMD:LED_0603_1608Metric"),
        reference="D7",
        value="LED",
        x_mm=30.0,
        y_mm=40.0,
        rotation=0.0,
        uuid_path="abcd-1234",
        pad_nets={"1": (3, "/S1_1"), "2": (4, "/S1_2")},
        extra_fields=(("Sim.Device", "D"),),
    )

    assert text.lstrip().startswith('(footprint "LED_SMD:LED_0603_1608Metric"')
    assert '(net 3 "/S1_1")' in text
    assert '(net 4 "/S1_2")' in text
    assert '(path "/abcd-1234")' in text
    assert '"Sim.Device"' in text
    assert "(version" not in text
    assert "(generator" not in text
    # The official silk and 3D model come along verbatim.
    assert '(layer "F.SilkS")' in text
    assert "LED_SMD.3dshapes" in text


def test_art_connector_is_vertical_with_polarity_marks() -> None:
    netlist, plan = _fixture()

    layout = compute_led_art_board_layout(netlist, plan, frozenset({"VIN", "GND"}))

    # The official header is already edge-parallel: both rail drops run at
    # the connector column x.
    vin_drops = [
        segment for segment in layout.segments
        if segment.net_name == "/VIN" and segment.x1 == segment.x2 == 2.0
    ]
    gnd_drops = [
        segment for segment in layout.segments
        if segment.net_name == "/GND" and segment.x1 == segment.x2 == 2.0
    ]
    assert vin_drops and gnd_drops

    board_text = render_board_from_layout(netlist, layout)
    assert '(fp_text user "+"' in board_text
    assert '(fp_text user "-"' in board_text
