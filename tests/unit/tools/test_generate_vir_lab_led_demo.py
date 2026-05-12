from __future__ import annotations

from tools.generate_vir_lab_led_demo import _render_board

from pcbsmith.services.led_art import LedArtSpec, build_led_art_plan_for_topology


def test_dense_led_board_labels_mixed_resistor_values_on_silkscreen() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="VIR-LAB"), "12v_dense")

    board_text = _render_board(plan, show_polarity_marks=True)

    assert '(gr_text "470R"' in board_text
    assert '(gr_text "2K2"' in board_text
