from __future__ import annotations

import math

from pcbsmith.calculators.electronics import solve_lm2596_buck


def _solve_12v_to_5v_1a() -> dict:
    return solve_lm2596_buck(
        input_voltage_min_v=7.0,
        input_voltage_nominal_v=12.0,
        input_voltage_max_v=24.0,
        output_voltage_v=5.0,
        load_current_a=1.0,
    )


def test_lm2596_buck_12v_to_5v_reference_design_values() -> None:
    result = _solve_12v_to_5v_1a()

    assert result["status"] == "warning"
    outputs = result["outputs"]
    assert math.isclose(outputs["duty_cycle_nominal"], 5.0 / 12.0, rel_tol=1e-4)
    assert math.isclose(outputs["ripple_current_a"], 0.3, rel_tol=1e-9)
    assert math.isclose(outputs["minimum_inductance_uH"], 87.962963, rel_tol=1e-4)
    assert outputs["selected_inductance_uH"] == 100.0
    assert math.isclose(outputs["minimum_output_capacitance_uF"], 5.0, rel_tol=1e-6)
    assert outputs["selected_output_capacitance_uF"] == 22.0
    assert math.isclose(outputs["feedback_upper_ohms"], 3708.699187, rel_tol=1e-6)
    assert outputs["selected_feedback_upper_ohms"] == 3740.0
    assert math.isclose(outputs["regulated_output_v"], 5.031818, rel_tol=1e-5)


def test_lm2596_buck_rejects_insufficient_input_headroom() -> None:
    result = solve_lm2596_buck(
        input_voltage_min_v=6.0,
        input_voltage_nominal_v=6.2,
        input_voltage_max_v=6.5,
        output_voltage_v=5.0,
        load_current_a=1.0,
    )

    assert result["status"] == "error"
    assert any("dropout margin" in error for error in result["errors"])


def test_lm2596_buck_rejects_invalid_ripple_ratio() -> None:
    result = solve_lm2596_buck(
        input_voltage_min_v=7.0,
        input_voltage_nominal_v=12.0,
        input_voltage_max_v=24.0,
        output_voltage_v=5.0,
        load_current_a=1.0,
        ripple_current_ratio=1.5,
    )

    assert result["status"] == "error"


def test_led_series_string_selects_e24_resistor() -> None:
    from pcbsmith.calculators.electronics import solve_led_series_string

    result = solve_led_series_string(
        supply_voltage_v=12.0,
        led_forward_voltage_v=1.85,
        target_current_a=0.010,
        led_count=4,
    )

    assert result["status"] == "ok"
    assert result["outputs"]["resistor_ohms"] == 460.0
    assert result["outputs"]["selected_resistor_ohms"] == 470.0


def test_led_series_string_rejects_overlong_string() -> None:
    from pcbsmith.calculators.electronics import solve_led_series_string

    result = solve_led_series_string(
        supply_voltage_v=12.0,
        led_forward_voltage_v=1.85,
        target_current_a=0.010,
        led_count=7,
    )

    assert result["status"] == "error"
    assert any("shorten the string" in error for error in result["errors"])


def test_led_series_string_warns_on_resistor_power() -> None:
    from pcbsmith.calculators.electronics import solve_led_series_string

    result = solve_led_series_string(
        supply_voltage_v=12.0,
        led_forward_voltage_v=1.85,
        target_current_a=0.010,
        led_count=1,
    )

    assert result["status"] == "warning"
    assert any("0603 rating" in warning for warning in result["warnings"])
