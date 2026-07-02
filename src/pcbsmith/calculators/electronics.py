from __future__ import annotations

from typing import Any

LM2596_FEEDBACK_REFERENCE_V = 1.23
LM2596_SWITCHING_FREQUENCY_HZ = 150_000.0

_STANDARD_FEEDBACK_UPPER_OHMS = (3300, 3480, 3600, 3740, 3900, 4020, 4220)
_STANDARD_INDUCTANCES_UH = (33, 47, 68, 100, 150, 220)
_STANDARD_OUTPUT_CAPS_UF = (22, 47, 100, 220, 330, 470)


def solve_lm2596_buck(
    *,
    input_voltage_min_v: float,
    input_voltage_nominal_v: float,
    input_voltage_max_v: float,
    output_voltage_v: float,
    load_current_a: float,
    ripple_current_ratio: float = 0.3,
    switching_frequency_hz: float = LM2596_SWITCHING_FREQUENCY_HZ,
    feedback_reference_v: float = LM2596_FEEDBACK_REFERENCE_V,
    feedback_lower_ohms: float = 1210.0,
    dropout_margin_v: float = 1.5,
    output_ripple_target_v: float = 0.05,
) -> dict[str, Any]:
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
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}

    ripple_current_a = load_current_a * ripple_current_ratio
    minimum_inductance_h = (
        output_voltage_v
        * (input_voltage_max_v - output_voltage_v)
        / (input_voltage_max_v * switching_frequency_hz * ripple_current_a)
    )
    minimum_output_capacitance_f = ripple_current_a / (
        8 * switching_frequency_hz * output_ripple_target_v
    )
    feedback_upper_ohms = feedback_lower_ohms * (
        (output_voltage_v / feedback_reference_v) - 1
    )
    selected_feedback_upper = _nearest_standard_value(
        feedback_upper_ohms,
        _STANDARD_FEEDBACK_UPPER_OHMS,
    )
    selected_inductance_uh = _nearest_standard_value(
        minimum_inductance_h * 1_000_000,
        _STANDARD_INDUCTANCES_UH,
        choose_at_least=True,
    )
    selected_output_cap_uf = _nearest_standard_value(
        minimum_output_capacitance_f * 1_000_000,
        _STANDARD_OUTPUT_CAPS_UF,
        choose_at_least=True,
    )
    regulated_output_v = feedback_reference_v * (
        1 + selected_feedback_upper / feedback_lower_ohms
    )

    warnings = [
        "Output capacitor sizing here covers capacitive ripple only; the LM2596 "
        "datasheet design procedure also bounds capacitor ESR for loop stability.",
    ]
    return {
        "status": "warning",
        "outputs": {
            "duty_cycle_nominal": round(output_voltage_v / input_voltage_nominal_v, 6),
            "ripple_current_a": round(ripple_current_a, 6),
            "minimum_inductance_uH": round(minimum_inductance_h * 1_000_000, 6),
            "selected_inductance_uH": float(selected_inductance_uh),
            "minimum_output_capacitance_uF": round(
                minimum_output_capacitance_f * 1_000_000, 6
            ),
            "selected_output_capacitance_uF": float(selected_output_cap_uf),
            "feedback_lower_ohms": feedback_lower_ohms,
            "feedback_upper_ohms": round(feedback_upper_ohms, 6),
            "selected_feedback_upper_ohms": float(selected_feedback_upper),
            "regulated_output_v": round(regulated_output_v, 6),
            "switching_frequency_hz": switching_frequency_hz,
        },
        "warnings": warnings,
        "errors": [],
        "references": [
            "Texas Instruments LM2596 datasheet, adjustable output buck regulator "
            "design procedure.",
        ],
    }


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
    errors: list[str] = []
    if output_voltage_v <= 0:
        errors.append("Output voltage must be positive.")
    if load_current_a <= 0:
        errors.append("Load current must be positive.")
    if input_voltage_min_v <= output_voltage_v + dropout_margin_v:
        errors.append(
            "Input minimum must be greater than output voltage plus dropout margin."
        )
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
