from __future__ import annotations

from pcbsmith.services.kicad_board_builder import (
    KiCadBoardBuilder,
    TwoPadSmdFootprintSpec,
)


def test_board_builder_assigns_stable_net_numbers_and_renders_outline() -> None:
    builder = KiCadBoardBuilder()
    vcc = builder.net("VCC")
    builder.net("GND")
    assert builder.net("VCC") == vcc

    builder.add_segment(1, 2, 3, 4, width_mm=0.45, net=vcc)
    text = builder.render(outline_end_mm=(50, 35))

    assert '(net 1 "VCC")' in text
    assert '(net 2 "GND")' in text
    assert "(start 1 2)" in text
    assert "(end 3 4)" in text
    assert "(width 0.45)" in text
    assert "(net 1)" in text
    assert "(end 50 35)" in text


def test_board_builder_renders_two_pad_smd_footprint_with_fab_body() -> None:
    builder = KiCadBoardBuilder()
    vcc = builder.net("VCC")
    led_a = builder.net("LED_A")

    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_R_0603_REAL",
            reference="R1",
            value="680",
            x_mm=10,
            y_mm=12,
            left_net=vcc,
            right_net=led_a,
            reference_layer="F.Fab",
            reference_offset_mm=(-2.4, -2),
        )
    )
    text = builder.render(outline_end_mm=(30, 20))

    assert '(footprint "PCBSmith_R_0603_REAL"' in text
    assert '(property "Reference" "R1"' in text
    assert '(layer "F.Fab")' in text
    assert "(fp_rect" in text
    assert '(net 1 "VCC")' in text
    assert '(net 2 "LED_A")' in text
    assert '(pad "1" smd roundrect' in text
    assert '(pad "2" smd roundrect' in text


def test_board_builder_can_add_toggleable_anode_plus_marker() -> None:
    builder = KiCadBoardBuilder()
    led_a = builder.net("LED_A")
    gnd = builder.net("GND")

    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_LED_0603_REAL",
            reference="LED1",
            value="Red LED",
            x_mm=10,
            y_mm=12,
            left_net=led_a,
            right_net=gnd,
            silk_marker="cathode",
            show_anode_plus=True,
        )
    )
    text = builder.render(outline_end_mm=(30, 20))

    assert '(fp_text user "+"' in text
    assert "(at -1.75 -1.25 0)" in text
    assert '(layer "F.SilkS")' in text


def test_board_builder_omits_anode_plus_marker_by_default() -> None:
    builder = KiCadBoardBuilder()
    led_a = builder.net("LED_A")
    gnd = builder.net("GND")

    builder.add_two_pad_smd_footprint(
        TwoPadSmdFootprintSpec(
            footprint="PCBSmith_LED_0603_REAL",
            reference="LED1",
            value="Red LED",
            x_mm=10,
            y_mm=12,
            left_net=led_a,
            right_net=gnd,
            silk_marker="cathode",
        )
    )
    text = builder.render(outline_end_mm=(30, 20))

    assert '(fp_text user "+"' not in text


def test_board_builder_quotes_user_text_for_kicad_strings() -> None:
    builder = KiCadBoardBuilder()
    builder.add_text('VIR "LAB"', 5, 6)

    text = builder.render(outline_end_mm=(10, 10))

    assert '(gr_text "VIR \\"LAB\\""' in text
