from __future__ import annotations

import re

from pcbsmith.generators.controller_boards import (
    AttinyLedControllerSpec,
    render_attiny_led_controller_board,
)
from pcbsmith.rules.board_intelligence import segment_angle_degrees


def test_attiny_led_controller_board_contains_controller_support_and_io() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())

    assert '(footprint "PCBSmith_SOIC14_ATTINY_REAL"' in board_text
    assert '(property "Reference" "U1"' in board_text
    assert '(property "Value" "ATtiny84"' in board_text
    assert '(property "Reference" "C1"' in board_text
    assert '(property "Value" "100nF"' in board_text
    assert '(property "Reference" "R1"' in board_text
    assert '(property "Reference" "R2"' in board_text
    assert '(property "Reference" "R3"' in board_text
    assert '(property "Reference" "RRESET"' not in board_text
    assert '(property "Reference" "RLED1"' not in board_text
    assert '(property "Reference" "LED1"' in board_text
    assert '(property "Reference" "LED2"' in board_text
    assert '(gr_text "ISP"' not in board_text
    assert '(gr_text "LED OUT"' not in board_text
    assert '(net 1 "VCC")' in board_text
    assert '(net 2 "GND")' in board_text
    assert '(net ' in board_text
    assert '"MISO"' in board_text
    assert '"MOSI"' in board_text
    assert '"SCK"' in board_text
    assert '"RESET"' in board_text


def test_attiny_led_controller_board_hides_helper_pad_references() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())

    for reference in (
        "J1_VCC",
        "J1_RST",
        "J1_MOSI",
        "J1_SCK",
        "J1_MISO",
        "J1_GND",
    ):
        assert "(hide yes)" in _property_block(board_text, "Reference", reference)


def test_attiny_led_controller_board_uses_labeled_through_hole_isp_by_default() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())

    assert '(footprint "PCBSmith_THROUGH_HOLE_PAD"' in board_text
    assert '(pad "1" thru_hole circle' in board_text
    assert '(footprint "PCBSmith_POWER_INPUT_PAD"' in board_text
    for label in ("MISO", "VCC", "SCK", "MOSI", "RESET", "GND"):
        assert f'(gr_text "{label}"' in board_text


def test_attiny_led_controller_board_can_use_compact_smd_isp_pads() -> None:
    board_text = render_attiny_led_controller_board(
        AttinyLedControllerSpec(connector_style="smd_pads")
    )

    assert '(footprint "PCBSmith_THROUGH_HOLE_PAD"' not in board_text
    assert '(footprint "PCBSmith_POWER_INPUT_PAD"' in board_text
    assert '(property "Reference" "J1_MISO"' in board_text
    assert "(hide yes)" in _property_block(board_text, "Reference", "J1_MISO")


def test_attiny_led_controller_board_omits_gpio_silk_labels_by_default() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())

    for label in ("PA0", "PA1", "PA2", "PA3", "PA7"):
        assert f'(gr_text "{label}"' not in board_text


def test_attiny_led_controller_board_can_show_gpio_and_section_labels() -> None:
    board_text = render_attiny_led_controller_board(
        AttinyLedControllerSpec(show_gpio_labels=True, show_section_labels=True)
    )

    assert '(gr_text "ISP"' in board_text
    assert '(gr_text "LED OUT"' in board_text
    assert '(gr_text "PA0"' in board_text


def test_attiny_led_controller_board_honors_led_output_count() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec(led_outputs=1))

    assert '(property "Reference" "R2"' in board_text
    assert '(property "Reference" "LED1"' in board_text
    assert '(property "Reference" "R3"' not in board_text
    assert '(property "Reference" "LED2"' not in board_text


def test_attiny_led_controller_board_can_show_values_on_silkscreen() -> None:
    board_text = render_attiny_led_controller_board(
        AttinyLedControllerSpec(show_values_on_silkscreen=True)
    )

    assert '(gr_text "10K"' in board_text
    assert '(gr_text "330R"' in board_text


def test_attiny_led_controller_board_prefers_cardinal_or_45_degree_routing() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())

    off_style_segments = [
        (start, end, segment_angle_degrees(start, end))
        for start, end in _board_segments(board_text)
        if segment_angle_degrees(start, end) not in {0, 45, 90, 135, 180}
    ]

    assert off_style_segments == []


def test_attiny_led_controller_board_fans_vias_outside_smd_pads() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())
    via_positions = set(_board_vias(board_text))
    solder_pad_centers = {
        (22.0, 24.0),
        (30.75, 23.0),
        (31.0, 33.0),
        (39.0, 27.0),
        (39.0, 30.81),
        (47.0, 29.54),
        (47.0, 30.81),
        (56.0, 14.0),
        (56.0, 33.0),
    }

    assert via_positions.isdisjoint(solder_pad_centers)


def test_attiny_led_controller_board_merges_c1_and_u1_ground_on_shared_trunk() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())
    segments = _board_segments(board_text)

    assert ((35.75, 16.0), (35.75, 44.0)) in segments
    assert ((39.0, 29.54), (35.75, 29.54)) in segments
    assert ((36.0, 29.54), (36.0, 44.0)) not in segments
    assert (35.75, 17.5) not in set(_board_vias(board_text))
    assert (48.5, 21.69) not in set(_board_vias(board_text))


def _board_segments(board_text: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segment_pattern = re.compile(
        r"\(segment\s+"
        r"\(start (?P<start_x>-?\d+(?:\.\d+)?) (?P<start_y>-?\d+(?:\.\d+)?)\)\s+"
        r"\(end (?P<end_x>-?\d+(?:\.\d+)?) (?P<end_y>-?\d+(?:\.\d+)?)\)",
        re.MULTILINE,
    )
    return [
        (
            (float(match.group("start_x")), float(match.group("start_y"))),
            (float(match.group("end_x")), float(match.group("end_y"))),
        )
        for match in segment_pattern.finditer(board_text)
    ]


def _board_vias(board_text: str) -> list[tuple[float, float]]:
    via_pattern = re.compile(
        r"\(via\s+"
        r"\(at (?P<x>-?\d+(?:\.\d+)?) (?P<y>-?\d+(?:\.\d+)?)\)",
        re.MULTILINE,
    )
    return [
        (float(match.group("x")), float(match.group("y")))
        for match in via_pattern.finditer(board_text)
    ]


def _property_block(board_text: str, name: str, value: str) -> str:
    pattern = re.compile(
        rf'\(property "{re.escape(name)}" "{re.escape(value)}".*?'
        r"(?=\n    \(property|\n    \(attr)",
        re.DOTALL,
    )
    match = pattern.search(board_text)
    if match is None:
        raise AssertionError(f"Property not found: {name}={value}")
    return match.group(0)
