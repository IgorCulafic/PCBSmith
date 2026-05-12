from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.services.led_art import (
    LedArtSpec,
    build_led_art_plan,
    select_led_resistor_ohms,
    write_led_art_reports,
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
    assert plan.electrical.grouping_strategy == "one_led_per_resistor"
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
    assert report["grouping_strategy"] == "one_led_per_resistor"
    assert "VIR-LAB" in markdown
    assert "680 ohm" in markdown
    assert "one_led_per_resistor" in markdown
