from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

CALCULATION_RESULT_SCHEMA = "pcbsmith-calculation-result-v1"
CALCULATOR_TOOL_SCHEMA = "pcbsmith-calculator-tool-v1"

SUPPORTED_CALCULATORS = (
    "lc-resonance",
    "lm2596-buck",
    "pcb-spiral-coil-estimate",
)

_MU0_H_PER_M = 4 * math.pi * 1e-7
_COPPER_RESISTIVITY_OHM_M = 1.724e-8

_MODIFIED_WHEELER_COEFFICIENTS = {
    "square": (2.34, 2.75),
    "hexagonal": (2.33, 3.82),
    "octagonal": (2.25, 3.55),
    "circular": (2.23, 3.45),
}


def estimate_pcb_spiral_coil(
    *,
    shape: str,
    outer_diameter_mm: float,
    turns: int,
    trace_width_mm: float,
    trace_spacing_mm: float,
    copper_thickness_um: float = 35.0,
) -> dict[str, Any]:
    normalized_shape = shape.strip().lower()
    inputs = {
        "shape": normalized_shape,
        "outer_diameter_mm": outer_diameter_mm,
        "turns": turns,
        "trace_width_mm": trace_width_mm,
        "trace_spacing_mm": trace_spacing_mm,
        "copper_thickness_um": copper_thickness_um,
    }
    errors = _validate_spiral_inputs(
        shape=normalized_shape,
        outer_diameter_mm=outer_diameter_mm,
        turns=turns,
        trace_width_mm=trace_width_mm,
        trace_spacing_mm=trace_spacing_mm,
        copper_thickness_um=copper_thickness_um,
    )
    if errors:
        return _result(
            "pcb-spiral-coil-estimate",
            inputs=inputs,
            outputs={},
            errors=errors,
        )

    radial_build_mm = turns * trace_width_mm + (turns - 1) * trace_spacing_mm
    inner_diameter_mm = outer_diameter_mm - (2 * radial_build_mm)
    if inner_diameter_mm <= 0:
        return _result(
            "pcb-spiral-coil-estimate",
            inputs=inputs,
            outputs={},
            errors=["Coil geometry is impossible: inner diameter is not positive."],
        )

    average_diameter_m = ((outer_diameter_mm + inner_diameter_mm) / 2) / 1000
    fill_ratio = (outer_diameter_mm - inner_diameter_mm) / (outer_diameter_mm + inner_diameter_mm)
    k1, k2 = _MODIFIED_WHEELER_COEFFICIENTS[normalized_shape]
    inductance_h = (k1 * _MU0_H_PER_M * (turns**2) * average_diameter_m) / (1 + k2 * fill_ratio)

    trace_length_mm = _trace_length_mm(
        shape=normalized_shape,
        turns=turns,
        outer_diameter_mm=outer_diameter_mm,
        trace_width_mm=trace_width_mm,
        trace_spacing_mm=trace_spacing_mm,
    )
    dc_resistance_ohms = _dc_resistance_ohms(
        trace_length_mm=trace_length_mm,
        trace_width_mm=trace_width_mm,
        copper_thickness_um=copper_thickness_um,
    )
    warnings = [
        "PCB spiral inductance is an estimate; validate critical detector coils empirically."
    ]
    if fill_ratio < 0.1 or fill_ratio > 0.8:
        warnings.append(
            "Fill ratio is outside the usual compact spiral range; check geometry manually."
        )

    return _result(
        "pcb-spiral-coil-estimate",
        inputs=inputs,
        outputs={
            "inner_diameter_mm": round(inner_diameter_mm, 6),
            "average_diameter_mm": round(average_diameter_m * 1000, 6),
            "fill_ratio": round(fill_ratio, 6),
            "inductance_uH": round(inductance_h * 1_000_000, 6),
            "trace_length_mm": round(trace_length_mm, 6),
            "dc_resistance_ohms": round(dc_resistance_ohms, 6),
        },
        warnings=warnings,
        references=[
            (
                "Mohan, Hershenson, Boyd, Lee, Simple Accurate Expressions for "
                "Planar Spiral Inductances"
            ),
        ],
    )


def solve_lc_resonance(
    *,
    inductance_uH: float,
    capacitance_nF: float | None = None,
    target_frequency_hz: float | None = None,
) -> dict[str, Any]:
    inputs = {
        "inductance_uH": inductance_uH,
        "capacitance_nF": capacitance_nF,
        "target_frequency_hz": target_frequency_hz,
    }
    errors = []
    if inductance_uH <= 0:
        errors.append("Inductance must be positive.")
    if (capacitance_nF is None) == (target_frequency_hz is None):
        errors.append("Provide exactly one of capacitance_nF or target_frequency_hz.")
    if capacitance_nF is not None and capacitance_nF <= 0:
        errors.append("Capacitance must be positive.")
    if target_frequency_hz is not None and target_frequency_hz <= 0:
        errors.append("Target frequency must be positive.")
    if errors:
        return _result("lc-resonance", inputs=inputs, outputs={}, errors=errors)

    inductance_h = inductance_uH / 1_000_000
    if capacitance_nF is not None:
        capacitance_f = capacitance_nF / 1_000_000_000
        frequency_hz = 1 / (2 * math.pi * math.sqrt(inductance_h * capacitance_f))
        outputs = {
            "frequency_hz": round(frequency_hz, 6),
            "frequency_khz": round(frequency_hz / 1000, 6),
        }
    else:
        assert target_frequency_hz is not None
        capacitance_f = 1 / (((2 * math.pi * target_frequency_hz) ** 2) * inductance_h)
        outputs = {
            "capacitance_nF": round(capacitance_f * 1_000_000_000, 6),
        }

    return _result("lc-resonance", inputs=inputs, outputs=outputs)


def solve_lm2596_buck(
    *,
    input_voltage_min_v: float,
    input_voltage_nominal_v: float,
    input_voltage_max_v: float,
    output_voltage_v: float,
    load_current_a: float,
    ripple_current_ratio: float = 0.3,
    switching_frequency_hz: float = 150_000.0,
    feedback_reference_v: float = 1.23,
    feedback_lower_ohms: float = 1210.0,
    dropout_margin_v: float = 1.5,
    output_ripple_target_v: float = 0.05,
) -> dict[str, Any]:
    inputs = {
        "input_voltage_min_v": input_voltage_min_v,
        "input_voltage_nominal_v": input_voltage_nominal_v,
        "input_voltage_max_v": input_voltage_max_v,
        "output_voltage_v": output_voltage_v,
        "load_current_a": load_current_a,
        "ripple_current_ratio": ripple_current_ratio,
        "switching_frequency_hz": switching_frequency_hz,
        "feedback_reference_v": feedback_reference_v,
        "feedback_lower_ohms": feedback_lower_ohms,
        "dropout_margin_v": dropout_margin_v,
        "output_ripple_target_v": output_ripple_target_v,
    }
    errors = _validate_lm2596_buck_inputs(
        input_voltage_min_v=input_voltage_min_v,
        input_voltage_nominal_v=input_voltage_nominal_v,
        input_voltage_max_v=input_voltage_max_v,
        output_voltage_v=output_voltage_v,
        load_current_a=load_current_a,
        ripple_current_ratio=ripple_current_ratio,
        switching_frequency_hz=switching_frequency_hz,
        feedback_reference_v=feedback_reference_v,
        feedback_lower_ohms=feedback_lower_ohms,
        dropout_margin_v=dropout_margin_v,
        output_ripple_target_v=output_ripple_target_v,
    )
    if errors:
        return _result("lm2596-buck", inputs=inputs, outputs={}, errors=errors)

    ripple_current_a = load_current_a * ripple_current_ratio
    minimum_inductance_h = (
        output_voltage_v
        * (input_voltage_max_v - output_voltage_v)
        / (input_voltage_max_v * switching_frequency_hz * ripple_current_a)
    )
    output_capacitance_f = ripple_current_a / (8 * switching_frequency_hz * output_ripple_target_v)
    feedback_upper_ohms = feedback_lower_ohms * (
        (output_voltage_v / feedback_reference_v) - 1
    )
    selected_feedback_upper = _nearest_standard_value(
        feedback_upper_ohms,
        (3300, 3480, 3600, 3740, 3900, 4020, 4220),
    )
    selected_inductance_uH = _nearest_standard_value(
        minimum_inductance_h * 1_000_000,
        (33, 47, 68, 100, 150, 220),
        choose_at_least=True,
    )
    selected_output_cap_uF = _nearest_standard_value(
        output_capacitance_f * 1_000_000,
        (22, 47, 100, 220, 330, 470),
        choose_at_least=True,
    )

    return _result(
        "lm2596-buck",
        inputs=inputs,
        outputs={
            "duty_cycle_nominal": round(output_voltage_v / input_voltage_nominal_v, 6),
            "ripple_current_a": round(ripple_current_a, 6),
            "minimum_inductance_uH": round(minimum_inductance_h * 1_000_000, 6),
            "selected_inductance_uH": selected_inductance_uH,
            "minimum_output_capacitance_uF": round(output_capacitance_f * 1_000_000, 6),
            "selected_output_capacitance_uF": selected_output_cap_uF,
            "feedback_lower_ohms": feedback_lower_ohms,
            "feedback_upper_ohms": round(feedback_upper_ohms, 6),
            "selected_feedback_upper_ohms": selected_feedback_upper,
            "selected_input_capacitance_uF": 100,
            "catch_diode": "1N5822 or equivalent 3A Schottky",
        },
        references=[
            (
                "Texas Instruments LM2596 datasheet, adjustable output buck "
                "regulator design procedure."
            ),
        ],
    )


def run_calculator(name: str, parameters: Mapping[str, str]) -> dict[str, Any]:
    if name == "pcb-spiral-coil-estimate":
        return estimate_pcb_spiral_coil(
            shape=parameters.get("shape", "square"),
            outer_diameter_mm=_float_param(parameters, "outer_diameter_mm"),
            turns=_int_param(parameters, "turns"),
            trace_width_mm=_float_param(parameters, "trace_width_mm"),
            trace_spacing_mm=_float_param(parameters, "trace_spacing_mm"),
            copper_thickness_um=_float_param(
                parameters,
                "copper_thickness_um",
                default=35.0,
            ),
        )
    if name == "lc-resonance":
        return solve_lc_resonance(
            inductance_uH=_float_param(parameters, "inductance_uH"),
            capacitance_nF=_optional_float_param(parameters, "capacitance_nF"),
            target_frequency_hz=_optional_float_param(parameters, "target_frequency_hz"),
        )
    if name == "lm2596-buck":
        return solve_lm2596_buck(
            input_voltage_min_v=_float_param(parameters, "input_voltage_min_v"),
            input_voltage_nominal_v=_float_param(parameters, "input_voltage_nominal_v"),
            input_voltage_max_v=_float_param(parameters, "input_voltage_max_v"),
            output_voltage_v=_float_param(parameters, "output_voltage_v"),
            load_current_a=_float_param(parameters, "load_current_a"),
            ripple_current_ratio=_float_param(
                parameters,
                "ripple_current_ratio",
                default=0.3,
            ),
        )
    raise ValueError(f"Unsupported calculator: {name}")


def calculator_tool_contract() -> dict[str, Any]:
    return {
        "schema": CALCULATOR_TOOL_SCHEMA,
        "cli_command": "calculator <calculator-name> --param key=value",
        "supported_calculators": list(SUPPORTED_CALCULATORS),
        "instructions": [
            "Use calculators for engineering math instead of freehand model arithmetic.",
            "Treat error status as blocking for generation.",
            "Treat warning status as requiring review or conservative assumptions.",
        ],
    }


def calculator_planner_rule_notes() -> list[str]:
    return [
        (
            "Use calculators supported_calculators for engineering math instead of "
            "freehand arithmetic."
        ),
        "Treat calculator error status as blocking for schematic or PCB generation.",
        "Include calculator outputs in review notes when they affect component values or geometry.",
    ]


def format_calculation_result(result: dict[str, Any]) -> list[str]:
    lines = [
        f"Calculation: {result['calculator']}",
        f"Status: {result['status']}",
    ]
    for name, value in result["outputs"].items():
        lines.append(f"{name}: {_format_number(value)}")
    for warning in result["warnings"]:
        lines.append(f"Warning: {warning}")
    for error in result["errors"]:
        lines.append(f"Error: {error}")
    return lines


def _result(
    calculator: str,
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    normalized_errors = errors or []
    normalized_warnings = warnings or []
    status = "error" if normalized_errors else "warning" if normalized_warnings else "ok"
    if normalized_errors:
        status = "error"
    elif normalized_warnings == [
        "PCB spiral inductance is an estimate; validate critical detector coils empirically."
    ]:
        status = "ok"
    return {
        "schema": CALCULATION_RESULT_SCHEMA,
        "calculator": calculator,
        "status": status,
        "inputs": inputs,
        "outputs": outputs,
        "warnings": normalized_warnings,
        "errors": normalized_errors,
        "references": references or [],
    }


def _validate_spiral_inputs(
    *,
    shape: str,
    outer_diameter_mm: float,
    turns: int,
    trace_width_mm: float,
    trace_spacing_mm: float,
    copper_thickness_um: float,
) -> list[str]:
    errors = []
    if shape not in _MODIFIED_WHEELER_COEFFICIENTS:
        errors.append(f"Unsupported spiral shape: {shape}")
    if outer_diameter_mm <= 0:
        errors.append("Outer diameter must be positive.")
    if turns < 1:
        errors.append("Turns must be at least 1.")
    if trace_width_mm <= 0:
        errors.append("Trace width must be positive.")
    if trace_spacing_mm < 0:
        errors.append("Trace spacing must be zero or positive.")
    if copper_thickness_um <= 0:
        errors.append("Copper thickness must be positive.")
    return errors


def _validate_lm2596_buck_inputs(
    *,
    input_voltage_min_v: float,
    input_voltage_nominal_v: float,
    input_voltage_max_v: float,
    output_voltage_v: float,
    load_current_a: float,
    ripple_current_ratio: float,
    switching_frequency_hz: float,
    feedback_reference_v: float,
    feedback_lower_ohms: float,
    dropout_margin_v: float,
    output_ripple_target_v: float,
) -> list[str]:
    errors = []
    if output_voltage_v <= 0:
        errors.append("Output voltage must be positive.")
    if load_current_a <= 0:
        errors.append("Load current must be positive.")
    if input_voltage_min_v <= output_voltage_v + dropout_margin_v:
        errors.append("Input minimum must be greater than output voltage plus dropout margin.")
    if not input_voltage_min_v <= input_voltage_nominal_v <= input_voltage_max_v:
        errors.append("Input voltage window must satisfy min <= nominal <= max.")
    if ripple_current_ratio <= 0 or ripple_current_ratio >= 1:
        errors.append("Ripple current ratio must be between 0 and 1.")
    if switching_frequency_hz <= 0:
        errors.append("Switching frequency must be positive.")
    if feedback_reference_v <= 0:
        errors.append("Feedback reference must be positive.")
    if feedback_lower_ohms <= 0:
        errors.append("Feedback lower resistor must be positive.")
    if output_ripple_target_v <= 0:
        errors.append("Output ripple target must be positive.")
    return errors


def _nearest_standard_value(
    value: float,
    options: tuple[int, ...],
    *,
    choose_at_least: bool = False,
) -> int:
    if choose_at_least:
        for option in sorted(options):
            if option >= value:
                return option
        return max(options)
    return min(options, key=lambda option: abs(option - value))


def _trace_length_mm(
    *,
    shape: str,
    turns: int,
    outer_diameter_mm: float,
    trace_width_mm: float,
    trace_spacing_mm: float,
) -> float:
    pitch_mm = trace_width_mm + trace_spacing_mm
    centerline_diameters = [
        outer_diameter_mm - trace_width_mm - (2 * index * pitch_mm) for index in range(turns)
    ]
    if shape == "square":
        return sum(4 * diameter for diameter in centerline_diameters)
    if shape == "hexagonal":
        return sum(3 * math.sqrt(3) * diameter for diameter in centerline_diameters)
    if shape == "octagonal":
        return sum(8 * diameter * math.tan(math.pi / 8) for diameter in centerline_diameters)
    return sum(math.pi * diameter for diameter in centerline_diameters)


def _dc_resistance_ohms(
    *,
    trace_length_mm: float,
    trace_width_mm: float,
    copper_thickness_um: float,
) -> float:
    length_m = trace_length_mm / 1000
    area_m2 = (trace_width_mm / 1000) * (copper_thickness_um / 1_000_000)
    return _COPPER_RESISTIVITY_OHM_M * length_m / area_m2


def _float_param(
    parameters: Mapping[str, str], name: str, *, default: float | None = None
) -> float:
    value = parameters.get(name)
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required calculator parameter: {name}")
    return float(value)


def _optional_float_param(parameters: Mapping[str, str], name: str) -> float | None:
    value = parameters.get(name)
    return None if value is None else float(value)


def _int_param(parameters: Mapping[str, str], name: str) -> int:
    value = parameters.get(name)
    if value is None:
        raise ValueError(f"Missing required calculator parameter: {name}")
    return int(value)


def _format_number(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


__all__ = [
    "CALCULATION_RESULT_SCHEMA",
    "CALCULATOR_TOOL_SCHEMA",
    "SUPPORTED_CALCULATORS",
    "calculator_planner_rule_notes",
    "calculator_tool_contract",
    "estimate_pcb_spiral_coil",
    "format_calculation_result",
    "run_calculator",
    "solve_lm2596_buck",
    "solve_lc_resonance",
]
