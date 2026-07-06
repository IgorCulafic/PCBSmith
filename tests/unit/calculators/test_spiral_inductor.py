from __future__ import annotations

import math

from pcbsmith.calculators.electronics import (
    solve_colpitts_oscillator,
    solve_pcb_spiral_inductor,
    solve_trace_current_capacity,
)


def test_spiral_inductor_matches_the_current_sheet_formula() -> None:
    result = solve_pcb_spiral_inductor(
        outer_diameter_m=0.062,
        trace_width_m=0.0005,
        trace_gap_m=0.0005,
        turns=20,
        frequency_hz=1.14e6,
    )

    assert result["status"] == "ok"
    outputs = result["outputs"]
    # Hand check: d_avg 42 mm, fill 0.476 ->
    # L = mu0 * 400 * 0.021 * (ln(2.46/0.476) + 0.2*0.476^2) ~ 17.8 uH.
    assert math.isclose(outputs["inductance_h"], 17.8e-6, rel_tol=0.02)
    # Two independent estimators from separate derivations must agree;
    # this is what actually validates the recalled coefficients (the
    # oscillator sim consumes the value, so it cannot).
    assert math.isclose(
        outputs["wheeler_inductance_h"], outputs["inductance_h"], rel_tol=0.05
    )
    assert outputs["inner_diameter_m"] == 0.022
    # 2.6 m of 0.5 mm / 1 oz trace is a couple of ohms.
    assert 2.0 < outputs["dc_resistance_ohm"] < 3.5
    assert outputs["quality_factor"] > 30


def test_spiral_inductor_rejects_overrun_turns() -> None:
    result = solve_pcb_spiral_inductor(
        outer_diameter_m=0.02,
        trace_width_m=0.0005,
        trace_gap_m=0.0005,
        turns=20,
    )
    assert result["status"] == "error"


def test_colpitts_frequency_and_bias() -> None:
    result = solve_colpitts_oscillator(
        supply_voltage_v=5.0,
        inductance_h=17.8e-6,
        tank_c1_f=2.2e-9,
        tank_c2_f=2.2e-9,
        emitter_resistor_ohms=1000.0,
        base_upper_ohms=47000.0,
        base_lower_ohms=47000.0,
    )

    assert result["status"] == "ok"
    outputs = result["outputs"]
    assert math.isclose(outputs["series_tank_c_f"], 1.1e-9, rel_tol=1e-6)
    assert math.isclose(outputs["frequency_hz"], 1.137e6, rel_tol=0.01)
    assert math.isclose(outputs["collector_current_a"], 1.8e-3, rel_tol=0.01)


def test_colpitts_rejects_a_dead_bias_point() -> None:
    result = solve_colpitts_oscillator(
        supply_voltage_v=5.0,
        inductance_h=17.8e-6,
        tank_c1_f=2.2e-9,
        tank_c2_f=2.2e-9,
        emitter_resistor_ohms=1000.0,
        base_upper_ohms=100000.0,
        base_lower_ohms=10000.0,
    )
    assert result["status"] == "error"


def test_trace_current_capacity_matches_the_published_tables() -> None:
    # 0.8 mm / 1 oz at 10 C rise ~ 2 A; 0.3 mm ~ 1 A.
    wide = solve_trace_current_capacity(trace_width_m=0.0008)
    assert math.isclose(wide["outputs"]["capacity_a"], 2.03, rel_tol=0.02)
    narrow = solve_trace_current_capacity(trace_width_m=0.0003)
    assert math.isclose(narrow["outputs"]["capacity_a"], 1.0, rel_tol=0.02)
