from __future__ import annotations

import re

from pcbsmith.services.board_intelligence import segment_angle_degrees
from pcbsmith.services.controller_boards import (
    AttinyLedControllerSpec,
    render_attiny_led_controller_board,
)


def test_attiny_led_controller_board_contains_controller_support_and_io() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())

    assert '(footprint "PCBSmith_SOIC14_ATTINY_REAL"' in board_text
    assert '(property "Reference" "U1"' in board_text
    assert '(property "Value" "ATtiny84"' in board_text
    assert '(property "Reference" "C1"' in board_text
    assert '(property "Value" "100nF"' in board_text
    assert '(property "Reference" "RRESET"' in board_text
    assert '(property "Reference" "RLED1"' in board_text
    assert '(property "Reference" "LED1"' in board_text
    assert '(property "Reference" "LED2"' in board_text
    assert '(gr_text "ISP"' in board_text
    assert '(gr_text "LED OUT"' in board_text
    assert '(net 1 "VCC")' in board_text
    assert '(net 2 "GND")' in board_text
    assert '(net ' in board_text
    assert '"MISO"' in board_text
    assert '"MOSI"' in board_text
    assert '"SCK"' in board_text
    assert '"RESET"' in board_text


def test_attiny_led_controller_board_honors_led_output_count() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec(led_outputs=1))

    assert '(property "Reference" "RLED1"' in board_text
    assert '(property "Reference" "LED1"' in board_text
    assert '(property "Reference" "RLED2"' not in board_text
    assert '(property "Reference" "LED2"' not in board_text


def test_attiny_led_controller_board_prefers_cardinal_or_45_degree_routing() -> None:
    board_text = render_attiny_led_controller_board(AttinyLedControllerSpec())

    off_style_segments = [
        (start, end, segment_angle_degrees(start, end))
        for start, end in _board_segments(board_text)
        if segment_angle_degrees(start, end) not in {0, 45, 90, 135, 180}
    ]

    assert off_style_segments == []


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
