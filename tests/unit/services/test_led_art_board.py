from __future__ import annotations

import re

from pcbsmith.services.board_intelligence import segment_angle_degrees
from pcbsmith.services.led_art import LedArtSpec, build_led_art_plan_for_topology
from pcbsmith.services.led_art_board import LedArtBoardSpec, render_led_art_board


def test_dense_led_board_labels_mixed_resistor_values_on_silkscreen() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="VIR-LAB"), "12v_dense")

    board_text = render_led_art_board(plan, LedArtBoardSpec(show_polarity_marks=True))

    assert '(gr_text "470R"' in board_text
    assert '(gr_text "2K2"' in board_text


def test_led_board_can_add_low_side_mosfet_control_stage() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="VIR-LAB"), "12v_dense")

    board_text = render_led_art_board(
        plan,
        LedArtBoardSpec(show_polarity_marks=True, control_mode="low_side_mosfet"),
    )

    assert '(net 3 "LOAD_NEG")' in board_text
    assert '(net 4 "CTRL")' in board_text
    assert '(net 5 "GATE")' in board_text
    assert '(property "Reference" "Q1"' in board_text
    assert '(property "Reference" "RCTRL"' in board_text
    assert '(property "Reference" "RPD"' in board_text
    assert '(gr_text "CTRL/PWM"' in board_text


def test_led_art_board_routes_with_central_cardinal_or_45_degree_preference() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="VIR-LAB"), "12v_dense")

    board_text = render_led_art_board(plan, LedArtBoardSpec(control_mode="low_side_mosfet"))

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
