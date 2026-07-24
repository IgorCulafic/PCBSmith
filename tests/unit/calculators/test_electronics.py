from __future__ import annotations

import math

import pytest

from pcbsmith.calculators.electronics import (
    calculator_planner_rule_notes,
    calculator_tool_contract,
    estimate_pcb_spiral_coil,
    format_calculation_result,
    solve_lc_resonance,
    solve_lm2596_buck,
)


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


def test_offline_flyback_design_point_matches_hand_calculation() -> None:
    from pcbsmith.calculators.electronics import solve_offline_flyback

    result = solve_offline_flyback(
        vac_min_v=108.0,
        vac_max_v=132.0,
        vout_v=3.3,
        iout_a=0.5,
    )

    outputs = result["outputs"]
    # Hand chain: Pout = 1.65 W, Pin = 1.65 / 0.75 = 2.2 W.
    assert outputs["pin_w"] == 2.2
    # Dmax = VOR / (VOR + Vdc_min) with VOR = 100.
    assert abs(outputs["duty_max"] - 100.0 / (100.0 + outputs["vdc_min_v"])) < 1e-3
    # Energy balance at the slowest datasheet frequency:
    # Pin = 0.5 * Lp * Ipk^2 * 52 kHz.
    lp = outputs["primary_inductance_h"]
    ipk = outputs["peak_primary_current_a"]
    assert abs(0.5 * lp * ipk**2 * 52e3 - 2.2) < 0.02
    # The peak current must respect the weakest-device current limit.
    assert ipk <= 0.33
    # Np/Ns = VOR / (Vout + Vf) = 100 / 3.8 -> 26.
    assert outputs["turns_ratio_selected"] == 26.0
    # Drain stress stays under the 700 V rating with margin.
    assert outputs["drain_peak_v"] < 500.0
    # E24 divider around the 1.24 V LMV431 reference: 20k / 12k.
    assert outputs["feedback_upper_ohms"] == 20000.0
    assert outputs["feedback_lower_ohms"] == 12000.0
    assert abs(outputs["vout_regulated_v"] - 3.3) < 0.05
    # Discontinuous conduction with a wide margin.
    assert outputs["dcm_period_fraction"] < 0.5


def test_offline_flyback_warns_on_hot_clamp_resistor() -> None:
    from pcbsmith.calculators.electronics import solve_offline_flyback

    cool = solve_offline_flyback(
        vac_min_v=108.0,
        vac_max_v=132.0,
        vout_v=3.3,
        iout_a=0.5,
        clamp_resistance_ohms=680e3,
    )
    assert cool["outputs"]["clamp_dissipation_w"] < 0.1
    assert not any("Clamp resistor" in w for w in cool["warnings"])

    hot = solve_offline_flyback(
        vac_min_v=108.0,
        vac_max_v=132.0,
        vout_v=3.3,
        iout_a=0.5,
        clamp_resistance_ohms=56e3,  # the reference's 2W-axial value
    )
    assert hot["outputs"]["clamp_dissipation_w"] > 0.4
    assert any("2W axial" in w for w in hot["warnings"])


def test_555_servo_tester_matches_datasheet_hand_calculation() -> None:
    from pcbsmith.calculators.electronics import solve_555_servo_tester

    result = solve_555_servo_tester()

    # END-STOP behaviour is a warning state by design.
    assert result["status"] == "warning"
    outputs = result["outputs"]
    # tL = 0.693 * RB * C (SLFS022 6.3.2): 0.693*68k*100n = 4.7124 ms.
    assert math.isclose(outputs["forward"]["servo_pulse_ms"], 4.712, abs_tol=5e-4)
    # Period tH+tL = 0.693*(RA+RB)*C + 0.693*RB*C:
    # 0.693*(33k+68k)*100n + 4.7124 ms = 11.712 ms -> 85.4 Hz.
    assert math.isclose(outputs["forward"]["frame_rate_hz"], 85.4, abs_tol=0.05)
    # REVERSE: 0.693*10k*100n = 0.693 ms at 0.693*(43k)*100n + 0.693ms.
    assert math.isclose(outputs["reverse"]["servo_pulse_ms"], 0.693, abs_tol=5e-4)
    assert math.isclose(outputs["reverse"]["frame_rate_hz"], 272.3, abs_tol=0.05)
    # BC547 drive: Ib=(4.3-0.7)/1k=3.6mA, Ic=6/4.7k=1.28mA, beta 0.35.
    assert math.isclose(outputs["base_current_ma"], 3.6, abs_tol=0.01)
    assert math.isclose(outputs["collector_current_ma"], 1.28, abs_tol=0.01)
    assert math.isclose(outputs["forced_beta"], 0.35, abs_tol=0.01)
    # Both branches sit outside the 0.9-2.1 ms proportional window.
    assert sum("end stop" in w for w in result["warnings"]) == 2


def test_555_servo_tester_rejects_out_of_range_supply() -> None:
    from pcbsmith.calculators.electronics import solve_555_servo_tester

    result = solve_555_servo_tester(vcc_v=3.0)
    assert result["status"] == "error"
    assert any("4.5-16V" in e for e in result["errors"])


def test_estimate_square_pcb_spiral_coil_returns_structured_result() -> None:
    result = estimate_pcb_spiral_coil(
        shape="square",
        outer_diameter_mm=55.0,
        turns=24,
        trace_width_mm=0.3,
        trace_spacing_mm=0.3,
        copper_thickness_um=35.0,
    )

    assert result["schema"] == "pcbsmith-calculation-result-v1"
    assert result["calculator"] == "pcb-spiral-coil-estimate"
    assert result["status"] == "ok"
    assert result["inputs"]["shape"] == "square"
    assert result["outputs"]["inner_diameter_mm"] == pytest.approx(26.8)
    assert result["outputs"]["fill_ratio"] == pytest.approx(0.345, abs=0.001)
    assert result["outputs"]["inductance_uH"] == pytest.approx(35.6, abs=1.0)
    assert result["outputs"]["trace_length_mm"] == pytest.approx(3926.4, abs=2.0)
    assert result["outputs"]["dc_resistance_ohms"] == pytest.approx(6.45, abs=0.2)
    assert result["warnings"] == [
        "PCB spiral inductance is an estimate; validate critical detector coils empirically.",
    ]


def test_estimate_spiral_coil_rejects_impossible_geometry() -> None:
    result = estimate_pcb_spiral_coil(
        shape="square",
        outer_diameter_mm=20.0,
        turns=50,
        trace_width_mm=0.4,
        trace_spacing_mm=0.4,
    )

    assert result["status"] == "error"
    assert result["outputs"] == {}
    assert result["errors"] == [
        "Coil geometry is impossible: inner diameter is not positive.",
    ]


def test_solve_lc_resonance_from_inductance_and_capacitance() -> None:
    result = solve_lc_resonance(
        inductance_uH=66.5,
        capacitance_nF=10.0,
    )

    assert result["schema"] == "pcbsmith-calculation-result-v1"
    assert result["calculator"] == "lc-resonance"
    assert result["status"] == "ok"
    assert result["outputs"]["frequency_hz"] == pytest.approx(195_200, rel=0.01)
    assert result["outputs"]["frequency_khz"] == pytest.approx(195.2, rel=0.01)


def test_solve_lc_resonance_from_target_frequency() -> None:
    result = solve_lc_resonance(
        inductance_uH=66.5,
        target_frequency_hz=100_000.0,
    )

    assert result["status"] == "ok"
    assert result["outputs"]["capacitance_nF"] == pytest.approx(38.1, rel=0.02)


def test_calculator_tool_contract_is_ai_facing() -> None:
    assert calculator_tool_contract() == {
        "schema": "pcbsmith-calculator-tool-v1",
        "cli_command": "calculator <calculator-name> --param key=value",
        "supported_calculators": [
            "lc-resonance",
            "lm2596-buck",
            "pcb-spiral-coil-estimate",
        ],
        "instructions": [
            "Use calculators for engineering math instead of freehand model arithmetic.",
            "Treat error status as blocking for generation.",
            "Treat warning status as requiring review or conservative assumptions.",
        ],
    }


def test_calculator_planner_notes_block_freehand_math() -> None:
    assert calculator_planner_rule_notes() == [
        (
            "Use calculators supported_calculators for engineering math instead "
            "of freehand arithmetic."
        ),
        "Treat calculator error status as blocking for schematic or PCB generation.",
        (
            "Include calculator outputs in review notes when they affect "
            "component values or geometry."
        ),
    ]


def test_format_calculation_result_is_compact_for_cli() -> None:
    result = solve_lc_resonance(inductance_uH=66.5, capacitance_nF=10.0)

    assert format_calculation_result(result) == [
        "Calculation: lc-resonance",
        "Status: ok",
        "frequency_hz: 195168.313366",
        "frequency_khz: 195.168313",
    ]
