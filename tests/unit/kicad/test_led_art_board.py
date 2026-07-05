from __future__ import annotations

from pcbsmith.generation.led_art import LedArtPlan, LedString
from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist, placement_y
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.led_art_board import (
    ART_PITCH_MM,
    ART_X0_MM,
    ART_Y0_MM,
    BOTTOM_RAIL_Y_MM,
    TOP_RAIL_Y_MM,
    compute_led_art_board_layout,
)

LED_FOOTPRINT = "LED_SMD:LED_0603_1608Metric"
RESISTOR_FOOTPRINT = "Resistor_SMD:R_0603_1608Metric"
CONNECTOR_FOOTPRINT = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"


def _component(reference: str, footprint: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=reference,
        footprint=footprint,
        uuid_path=f"uuid-{reference}",
    )


def _fixture() -> tuple[BoardNetlist, LedArtPlan]:
    # One 2-LED string in column 0 with a gap row (rows 0 and 3).
    plan = LedArtPlan(
        text="TEST",
        strings=(
            LedString(
                resistor_ref="R1",
                led_refs=("D1", "D2"),
                column=0,
                rows=(0, 3),
                resistor_ohms=820.0,
            ),
        ),
        total_columns=1,
    )
    netlist = BoardNetlist(
        components=(
            _component("P1", CONNECTOR_FOOTPRINT),
            _component("R1", RESISTOR_FOOTPRINT),
            _component("D1", LED_FOOTPRINT),
            _component("D2", LED_FOOTPRINT),
        ),
        nets=(
            # KiCad pin convention (rule 8.4): LED pin 1 = cathode. Current
            # enters each LED at pin 2 (anode) and leaves at pin 1.
            BoardNet(name="/VIN", nodes=(("P1", "1"), ("R1", "1"))),
            BoardNet(name="/GND", nodes=(("P1", "2"), ("D2", "1"))),
            BoardNet(name="/S1_1", nodes=(("R1", "2"), ("D1", "2"))),
            BoardNet(name="/S1_2", nodes=(("D1", "1"), ("D2", "2"))),
        ),
    )
    return netlist, plan


def test_art_layout_places_leds_on_the_glyph_grid() -> None:
    netlist, plan = _fixture()

    layout = compute_led_art_board_layout(netlist, plan, frozenset({"VIN", "GND"}))

    assert placement_y(layout, "D1") == ART_Y0_MM
    assert placement_y(layout, "D2") == ART_Y0_MM + 3 * ART_PITCH_MM
    anchors = {component.reference: x for component, x in layout.placements}
    assert anchors["D1"] == ART_X0_MM
    assert anchors["R1"] == ART_X0_MM
    assert anchors["P1"] < ART_X0_MM  # connector hugs the left edge


def test_art_routing_keeps_series_links_in_column_and_rails_outside() -> None:
    netlist, plan = _fixture()

    layout = compute_led_art_board_layout(netlist, plan, frozenset({"VIN", "GND"}))

    for segment in layout.segments:
        assert segment.layer == "F.Cu"
        if segment.net_name.startswith("/S"):
            for x in (segment.x1, segment.x2):
                assert abs(x - ART_X0_MM) <= ART_PITCH_MM / 2
    rail_ys = {
        segment.y1
        for segment in layout.segments
        if segment.y1 == segment.y2 and segment.net_name in ("/VIN", "/GND")
    }
    assert rail_ys == {TOP_RAIL_Y_MM, BOTTOM_RAIL_Y_MM}
    assert not layout.vias


def test_series_polarity_check_passes_and_flags_reversal() -> None:
    netlist, plan = _fixture()
    layout = compute_led_art_board_layout(netlist, plan, frozenset({"VIN", "GND"}))
    spec = DesignChecksSpec(led_strings=(("R1", "D1", "D2"),))

    report = run_design_checks(layout, netlist, spec)
    assert "series_led_polarity" in report.checks_run
    assert not [f for f in report.findings if f.rule == "7.1"]

    reversed_netlist = BoardNetlist(
        components=netlist.components,
        nets=(
            netlist.nets[0],
            # Reversed: current would enter the LEDs at pin 1 (cathode).
            BoardNet(name="/GND", nodes=(("P1", "2"), ("D2", "2"))),
            BoardNet(name="/S1_1", nodes=(("R1", "2"), ("D1", "1"))),
            BoardNet(name="/S1_2", nodes=(("D1", "2"), ("D2", "1"))),
        ),
    )
    report = run_design_checks(layout, reversed_netlist, spec)
    assert [f for f in report.findings if f.rule == "7.1"]
    assert report.status == "failed"
