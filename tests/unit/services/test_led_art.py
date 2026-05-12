from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.services.led_art import (
    LedArtSpec,
    build_led_art_plan,
    build_led_art_plan_for_topology,
    compare_led_art_topologies,
    select_led_resistor_ohms,
    write_led_art_reports,
    write_led_art_topology_comparison_reports,
)


def test_select_led_resistor_chooses_next_standard_value() -> None:
    assert select_led_resistor_ohms(
        supply_voltage_v=5.0,
        led_forward_voltage_v=2.0,
        target_current_ma=5.0,
    ) == 680


def test_build_led_art_plan_generates_stable_pixel_references() -> None:
    plan = build_led_art_plan(LedArtSpec(text="V"))

    assert len(plan.pixels) == 13
    assert plan.pixels[0].resistor_ref == "R1"
    assert plan.pixels[0].led_ref == "LED1"
    assert plan.pixels[0].drive_net == "LED_1"
    assert plan.pixels[-1].resistor_ref == "R13"
    assert plan.electrical.resistor_value_ohms == 680
    assert plan.electrical.grouping_strategy == "5v_one_per_led"
    assert plan.electrical.total_led_count == 13


def test_vir_lab_plan_reports_total_current_warning() -> None:
    plan = build_led_art_plan(
        LedArtSpec(
            text="VIR-LAB",
            supply_voltage_v=5.0,
            led_forward_voltage_v=2.0,
            target_current_ma=5.0,
            usb_warning_current_ma=250.0,
        )
    )

    assert plan.electrical.total_led_count == len(plan.pixels)
    assert plan.electrical.string_count == len(plan.pixels)
    assert plan.electrical.string_current_ma == pytest.approx(4.4118, abs=0.001)
    assert plan.electrical.total_current_ma > 250.0
    assert plan.electrical.warnings == (
        "Estimated LED current exceeds 250.0 mA; review USB/input power budget.",
    )


def test_write_led_art_reports_writes_json_and_markdown(tmp_path: Path) -> None:
    plan = build_led_art_plan(LedArtSpec(text="VIR-LAB"))

    report_paths = write_led_art_reports(plan, tmp_path)

    report = json.loads(report_paths.json_path.read_text(encoding="utf-8"))
    markdown = report_paths.markdown_path.read_text(encoding="utf-8")
    assert report["schema"] == "pcbsmith-led-art-electrical-v1"
    assert report["text"] == "VIR-LAB"
    assert report["resistor_value_ohms"] == 680
    assert report["total_led_count"] == len(plan.pixels)
    assert report["grouping_strategy"] == "5v_one_per_led"
    assert "VIR-LAB" in markdown
    assert "680 ohm" in markdown
    assert "5v_one_per_led" in markdown


def test_compare_led_art_topologies_includes_5v_and_12v_dense_options() -> None:
    plan = build_led_art_plan(LedArtSpec(text="VIR-LAB"))

    comparison = compare_led_art_topologies(plan, priority="density")

    by_id = {option.id: option for option in comparison.options}
    assert by_id["5v_one_per_led"].series_leds_per_string == 1
    assert by_id["5v_one_per_led"].resistor_value_ohms == 680
    assert by_id["5v_two_led_dense"].series_leds_per_string == 2
    assert by_id["5v_two_led_dense"].resistor_value_ohms == 220
    assert by_id["12v_dense"].series_leds_per_string == 5
    assert by_id["12v_dense"].resistor_value_ohms == 470
    assert by_id["12v_dense"].string_count == 20
    assert by_id["12v_dense"].total_current_ma == pytest.approx(85.106, abs=0.001)
    assert comparison.recommended_option_id == "12v_dense"


def test_write_led_art_topology_comparison_reports(tmp_path: Path) -> None:
    plan = build_led_art_plan(LedArtSpec(text="VIR-LAB"))
    comparison = compare_led_art_topologies(plan, priority="density")

    report_paths = write_led_art_topology_comparison_reports(comparison, tmp_path)

    report = json.loads(report_paths.json_path.read_text(encoding="utf-8"))
    markdown = report_paths.markdown_path.read_text(encoding="utf-8")
    assert report["schema"] == "pcbsmith-led-art-topology-comparison-v1"
    assert report["recommended_option_id"] == "12v_dense"
    assert "5v_two_led_dense" in markdown
    assert "12v_dense" in markdown
    assert "20" in markdown
    assert "470 ohm" in markdown
    assert "planning alternatives" in markdown


def test_build_led_art_plan_for_5v_dense_groups_two_led_strings() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="VIR-LAB"), "5v_two_led_dense")

    assert plan.electrical.supply_voltage_v == 5.0
    assert plan.electrical.grouping_strategy == "5v_two_led_dense"
    assert plan.electrical.resistor_value_ohms == 220
    assert plan.electrical.string_count == 57
    assert plan.electrical.total_current_ma == pytest.approx(257.219, abs=0.001)
    assert plan.strings[0].resistor_ref == "R1"
    assert len(plan.strings[0].led_refs) == 2
    assert plan.strings[0].pixel_indices == (1, 3)
    assert plan.strings[0].resistor_value_ohms == 220
    assert max(len(string.led_refs) for string in plan.strings) == 2


def test_build_led_art_plan_for_12v_dense_groups_five_led_strings() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="VIR-LAB"), "12v_dense")

    assert plan.electrical.supply_voltage_v == 12.0
    assert plan.electrical.grouping_strategy == "12v_dense"
    assert plan.electrical.resistor_value_ohms == 470
    assert plan.electrical.string_count == 35
    assert plan.electrical.total_current_ma == pytest.approx(159.397, abs=0.001)
    assert len(plan.strings[0].led_refs) == 5
    assert plan.strings[0].pixel_indices == (16, 19, 20, 21, 22)
    assert plan.strings[0].resistor_value_ohms == 470
    assert len(plan.strings[-1].led_refs) == 1
    assert plan.strings[-1].resistor_value_ohms == 2200


def test_12v_dense_uses_vertical_adjacency_to_reduce_resistor_count() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="VIR-LAB"), "12v_dense")
    pixel_by_index = {pixel.index: pixel for pixel in plan.pixels}

    vertical_strings = [
        string
        for string in plan.strings
        if any(
            pixel_by_index[left].x == pixel_by_index[right].x
            and abs(pixel_by_index[left].y - pixel_by_index[right].y)
            == plan.spec.y_step_mm
            for left, right in zip(
                string.pixel_indices,
                string.pixel_indices[1:],
                strict=False,
            )
        )
    ]

    assert plan.electrical.string_count <= 40
    assert vertical_strings
