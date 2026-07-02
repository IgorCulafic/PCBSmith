from __future__ import annotations

import pytest
from tests.unit.kicad.test_led_art_board import _fixture

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardGenerationError,
    SilkLine,
    SilkText,
    render_board_from_layout,
    rotate_offset,
)
from pcbsmith.kicad.led_art_board import compute_led_art_board_layout


def test_rotate_offset_right_angles() -> None:
    # KiCad rotations are CCW on screen with y pointing down.
    assert rotate_offset(2.54, 0.0, 0) == (2.54, 0.0)
    assert rotate_offset(2.54, 0.0, 90) == (0.0, -2.54)
    assert rotate_offset(2.54, 0.0, 180) == (-2.54, 0.0)
    assert rotate_offset(2.54, 0.0, 270) == (0.0, 2.54)
    with pytest.raises(BoardGenerationError):
        rotate_offset(1.0, 0.0, 45)


def test_polarized_footprints_carry_standard_marks() -> None:
    led = FOOTPRINT_LIBRARY["LED_SMD:LED_0603_1608Metric"]
    assert any(isinstance(mark, SilkLine) for mark in led.silk_marks)
    diode = FOOTPRINT_LIBRARY["Diode_SMD:D_SMA"]
    assert any(isinstance(mark, SilkLine) for mark in diode.silk_marks)
    cap = FOOTPRINT_LIBRARY["Capacitor_SMD:CP_Elec_8x10"]
    assert len([m for m in cap.silk_marks if isinstance(m, SilkLine)]) == 2
    header = FOOTPRINT_LIBRARY[
        "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    ]
    texts = {mark.text for mark in header.silk_marks if isinstance(mark, SilkText)}
    assert texts == {"+", "-"}
    # Plain resistors are non-polar: no marks.
    assert not FOOTPRINT_LIBRARY["Resistor_SMD:R_0603_1608Metric"].silk_marks


def test_art_connector_is_vertical_with_rotated_pads() -> None:
    netlist, plan = _fixture()

    layout = compute_led_art_board_layout(netlist, plan, frozenset({"VIN", "GND"}))

    rotations = dict(layout.part_rotation)
    assert rotations["P1"] == 270.0
    # Rotation 270 stacks pin 2 directly below pin 1 along the left edge, so
    # both VIN and GND rail drops run at the same x.
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
    assert "(at 22 40 270)" in board_text
    assert '(fp_text user "+"' in board_text
    assert '(fp_text user "-"' in board_text
    # LED cathode bars are rendered on silk.
    assert board_text.count("(fp_line") >= len(
        [c for c, _ in layout.placements if c.footprint.startswith("LED_SMD")]
    )
