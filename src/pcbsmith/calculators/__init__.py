"""Deterministic engineering calculators used by circuit-intelligence tools."""

from __future__ import annotations

from pcbsmith.calculators.electronics import (
    CALCULATION_RESULT_SCHEMA,
    CALCULATOR_TOOL_SCHEMA,
    SUPPORTED_CALCULATORS,
    calculator_planner_rule_notes,
    calculator_tool_contract,
    estimate_pcb_spiral_coil,
    format_calculation_result,
    run_calculator,
    solve_lc_resonance,
)

__all__ = [
    "CALCULATION_RESULT_SCHEMA",
    "CALCULATOR_TOOL_SCHEMA",
    "SUPPORTED_CALCULATORS",
    "calculator_planner_rule_notes",
    "calculator_tool_contract",
    "estimate_pcb_spiral_coil",
    "format_calculation_result",
    "run_calculator",
    "solve_lc_resonance",
]
