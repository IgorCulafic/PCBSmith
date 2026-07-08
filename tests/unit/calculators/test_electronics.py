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
    assert abs(
        outputs["duty_max"]
        - 100.0 / (100.0 + outputs["vdc_min_v"])
    ) < 1e-3
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
        vac_min_v=108.0, vac_max_v=132.0, vout_v=3.3, iout_a=0.5,
        clamp_resistance_ohms=680e3,
    )
    assert cool["outputs"]["clamp_dissipation_w"] < 0.1
    assert not any("Clamp resistor" in w for w in cool["warnings"])

    hot = solve_offline_flyback(
        vac_min_v=108.0, vac_max_v=132.0, vout_v=3.3, iout_a=0.5,
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
    assert math.isclose(
        outputs["forward"]["servo_pulse_ms"], 4.712, abs_tol=5e-4
    )
    # Period tH+tL = 0.693*(RA+RB)*C + 0.693*RB*C:
    # 0.693*(33k+68k)*100n + 4.7124 ms = 11.712 ms -> 85.4 Hz.
    assert math.isclose(
        outputs["forward"]["frame_rate_hz"], 85.4, abs_tol=0.05
    )
    # REVERSE: 0.693*10k*100n = 0.693 ms at 0.693*(43k)*100n + 0.693ms.
    assert math.isclose(
        outputs["reverse"]["servo_pulse_ms"], 0.693, abs_tol=5e-4
    )
    assert math.isclose(
        outputs["reverse"]["frame_rate_hz"], 272.3, abs_tol=0.05
    )
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
