from __future__ import annotations

from pcbsmith.calculators.electronics import solve_lm2596_buck


def test_lm2596_buck_calculator_sizes_feedback_and_inductor() -> None:
    result = solve_lm2596_buck(
        input_voltage_min_v=7.0,
        input_voltage_nominal_v=12.0,
        input_voltage_max_v=24.0,
        output_voltage_v=5.0,
        load_current_a=1.0,
        ripple_current_ratio=0.3,
        switching_frequency_hz=150_000,
        feedback_lower_ohms=1210.0,
    )

    assert result["schema"] == "pcbsmith-calculation-result-v1"
    assert result["calculator"] == "lm2596-buck"
    assert result["status"] == "warning"
    assert result["warnings"]
    assert result["outputs"]["duty_cycle_nominal"] == 0.416667
    assert result["outputs"]["minimum_inductance_uH"] > 80
    assert result["outputs"]["selected_inductance_uH"] == 100
    assert result["outputs"]["feedback_upper_ohms"] == 3708.699187
    assert result["outputs"]["selected_feedback_upper_ohms"] == 3740


def test_lm2596_buck_calculator_rejects_invalid_voltage_window() -> None:
    result = solve_lm2596_buck(
        input_voltage_min_v=4.0,
        input_voltage_nominal_v=12.0,
        input_voltage_max_v=24.0,
        output_voltage_v=5.0,
        load_current_a=1.0,
    )

    assert result["status"] == "error"
    assert "Input minimum must be greater than output voltage plus dropout margin." in result[
        "errors"
    ]
