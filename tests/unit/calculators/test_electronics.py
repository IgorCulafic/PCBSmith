from __future__ import annotations

import pytest

from pcbsmith.calculators.electronics import (
    calculator_planner_rule_notes,
    calculator_tool_contract,
    estimate_pcb_spiral_coil,
    format_calculation_result,
    solve_lc_resonance,
)


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
            "Use calculators supported_calculators for engineering math instead of "
            "freehand arithmetic."
        ),
        "Treat calculator error status as blocking for schematic or PCB generation.",
        "Include calculator outputs in review notes when they affect component values or geometry.",
    ]


def test_format_calculation_result_is_compact_for_cli() -> None:
    result = solve_lc_resonance(inductance_uH=66.5, capacitance_nF=10.0)

    assert format_calculation_result(result) == [
        "Calculation: lc-resonance",
        "Status: ok",
        "frequency_hz: 195168.313366",
        "frequency_khz: 195.168313",
    ]
