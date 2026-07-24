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

LM2596_FEEDBACK_REFERENCE_V = 1.23
LM2596_SWITCHING_FREQUENCY_HZ = 150_000.0

_STANDARD_FEEDBACK_UPPER_OHMS = (3300, 3480, 3600, 3740, 3900, 4020, 4220)
_STANDARD_INDUCTANCES_UH = (33, 47, 68, 100, 150, 220)
_STANDARD_OUTPUT_CAPS_UF = (22, 47, 100, 220, 330, 470)


COPPER_RESISTIVITY_OHM_M = 1.72e-8
_MU0_H_PER_M = 4 * math.pi * 1e-7
_MODIFIED_WHEELER_COEFFICIENTS = {
    "square": (2.34, 2.75),
    "hexagonal": (2.33, 3.82),
    "octagonal": (2.25, 3.55),
    "circular": (2.23, 3.45),
}


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
        return _calculation_result(
            "lm2596-buck",
            inputs=inputs,
            outputs={},
            errors=errors,
        )

    ripple_current_a = load_current_a * ripple_current_ratio
    minimum_inductance_h = (
        output_voltage_v
        * (input_voltage_max_v - output_voltage_v)
        / (input_voltage_max_v * switching_frequency_hz * ripple_current_a)
    )
    minimum_output_capacitance_f = ripple_current_a / (
        8 * switching_frequency_hz * output_ripple_target_v
    )
    feedback_upper_ohms = feedback_lower_ohms * ((output_voltage_v / feedback_reference_v) - 1)
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
    regulated_output_v = feedback_reference_v * (1 + selected_feedback_upper / feedback_lower_ohms)

    warnings = [
        "Output capacitor sizing here covers capacitive ripple only; the LM2596 "
        "datasheet design procedure also bounds capacitor ESR for loop stability.",
    ]
    return _calculation_result(
        "lm2596-buck",
        inputs=inputs,
        status="warning",
        outputs={
            "duty_cycle_nominal": round(output_voltage_v / input_voltage_nominal_v, 6),
            "ripple_current_a": round(ripple_current_a, 6),
            "minimum_inductance_uH": round(minimum_inductance_h * 1_000_000, 6),
            "selected_inductance_uH": float(selected_inductance_uh),
            "minimum_output_capacitance_uF": round(minimum_output_capacitance_f * 1_000_000, 6),
            "selected_output_capacitance_uF": float(selected_output_cap_uf),
            "feedback_lower_ohms": feedback_lower_ohms,
            "feedback_upper_ohms": round(feedback_upper_ohms, 6),
            "selected_feedback_upper_ohms": float(selected_feedback_upper),
            "regulated_output_v": round(regulated_output_v, 6),
            "switching_frequency_hz": switching_frequency_hz,
            "selected_input_capacitance_uF": 100.0,
            "catch_diode": "1N5822 or equivalent 3A Schottky",
        },
        warnings=warnings,
        references=[
            "Texas Instruments LM2596 datasheet, adjustable output buck regulator "
            "design procedure.",
        ],
    )


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


_E24_MANTISSAS = (
    1.0,
    1.1,
    1.2,
    1.3,
    1.5,
    1.6,
    1.8,
    2.0,
    2.2,
    2.4,
    2.7,
    3.0,
    3.3,
    3.6,
    3.9,
    4.3,
    4.7,
    5.1,
    5.6,
    6.2,
    6.8,
    7.5,
    8.2,
    9.1,
)
RESISTOR_0603_POWER_RATING_W = 0.1
LED_STRING_HEADROOM_WARNING_RATIO = 0.15


def nearest_e24_ohms(value_ohms: float) -> float:
    if value_ohms <= 0:
        raise ValueError("E24 lookup requires a positive resistance.")
    candidates: list[float] = []
    for decade in (1, 10, 100, 1_000, 10_000, 100_000):
        candidates.extend(mantissa * decade for mantissa in _E24_MANTISSAS)
    return min(candidates, key=lambda candidate: abs(candidate - value_ohms))


def solve_led_series_string(
    *,
    supply_voltage_v: float,
    led_forward_voltage_v: float,
    target_current_a: float,
    led_count: int,
) -> dict[str, Any]:
    errors: list[str] = []
    if supply_voltage_v <= 0:
        errors.append("Supply voltage must be positive.")
    if led_forward_voltage_v <= 0:
        errors.append("LED forward voltage must be positive.")
    if target_current_a <= 0:
        errors.append("Target current must be positive.")
    if led_count < 1:
        errors.append("A string needs at least one LED.")
    string_drop_v = led_forward_voltage_v * led_count
    if not errors and string_drop_v >= supply_voltage_v:
        errors.append(
            f"{led_count} LEDs drop {string_drop_v:g} V, which the "
            f"{supply_voltage_v:g} V supply cannot drive; shorten the string."
        )
    if errors:
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}

    headroom_v = supply_voltage_v - string_drop_v
    resistor_ohms = headroom_v / target_current_a
    selected_ohms = nearest_e24_ohms(resistor_ohms)
    current_with_selected_a = headroom_v / selected_ohms
    resistor_power_w = headroom_v * current_with_selected_a

    warnings: list[str] = []
    if headroom_v < supply_voltage_v * LED_STRING_HEADROOM_WARNING_RATIO:
        warnings.append(
            f"A {led_count}-LED string leaves only {headroom_v:g} V across the "
            "resistor; forward-voltage tolerance will swing the current widely."
        )
    if resistor_power_w > RESISTOR_0603_POWER_RATING_W:
        warnings.append(
            f"The string resistor dissipates {resistor_power_w * 1000:.0f} mW, above "
            f"the {RESISTOR_0603_POWER_RATING_W * 1000:.0f} mW 0603 rating; use a "
            "larger footprint or reduce the current."
        )
    return {
        "status": "warning" if warnings else "ok",
        "outputs": {
            "string_drop_v": round(string_drop_v, 6),
            "resistor_ohms": round(resistor_ohms, 6),
            "selected_resistor_ohms": selected_ohms,
            "current_with_selected_a": round(current_with_selected_a, 6),
            "resistor_power_w": round(resistor_power_w, 6),
        },
        "warnings": warnings,
        "errors": [],
        "references": [
            "Series LED string: R = (Vsupply - n*Vf) / I_target; Vf from the component datasheet.",
        ],
    }


I2C_FAST_MODE_RISE_TIME_NS = 300.0
I2C_LOW_LEVEL_SINK_MA = 3.0
I2C_LOW_LEVEL_VOLTAGE_V = 0.4
I2C_RC_RISE_FACTOR = 0.8473  # ln(0.7/0.3): 30%->70% rise on an RC bus


def solve_offline_flyback(
    *,
    vac_min_v: float,
    vac_max_v: float,
    vout_v: float,
    iout_a: float,
    reflected_voltage_v: float = 100.0,
    efficiency: float = 0.75,
    diode_drop_v: float = 0.5,
    fsw_min_hz: float = 52e3,
    fsw_max_hz: float = 75e3,
    ilimit_min_a: float = 0.33,
    ton_max_s: float = 6.5e-6,
    bulk_capacitance_f: float = 9.4e-6,
    line_frequency_hz: float = 60.0,
    ref_voltage_v: float = 1.24,
    clamp_resistance_ohms: float | None = None,
    clamp_voltage_v: float | None = None,
) -> dict[str, Any]:
    """Offline DCM flyback design point (UCC28881-class hysteretic
    switcher). Every device parameter defaults to the WORST-CASE limit
    from the UCC28881 datasheet table 6.5 (fsw 52-75 kHz, ILIMIT >= 330
    mA, tON <= 6.5 us); pass measured values to tighten.

    Design chain: bulk ripple from the capacitor energy balance ->
    maximum duty from the reflected voltage -> primary inductance sized
    so the peak current stays under the device limit at the SLOWEST
    switching frequency -> turns ratio from the reflected voltage ->
    stress checks (drain, secondary PIV, DCM margin) -> feedback divider
    on the shunt reference, nearest E24.
    """
    errors: list[str] = []
    if vac_min_v <= 0 or vac_max_v < vac_min_v:
        errors.append("AC input range is invalid.")
    if vout_v <= ref_voltage_v:
        errors.append("Output voltage must exceed the reference voltage.")
    if iout_a <= 0:
        errors.append("Output current must be positive.")
    if errors:
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}

    warnings: list[str] = []
    pout_w = vout_v * iout_a
    pin_w = pout_w / efficiency

    vdc_peak_min = vac_min_v * math.sqrt(2.0)
    vdc_peak_max = vac_max_v * math.sqrt(2.0)
    # Bulk hold-up: the capacitor carries the load for ~0.35 of a line
    # half-cycle between recharge peaks.
    discharge_s = 0.35 / line_frequency_hz
    vdc_min_sq = vdc_peak_min**2 - 2.0 * pin_w * discharge_s / bulk_capacitance_f
    if vdc_min_sq <= 0:
        return {
            "status": "error",
            "outputs": {},
            "warnings": [],
            "errors": ["Bulk capacitance is too small for the load."],
        }
    vdc_min = math.sqrt(vdc_min_sq)

    duty_max = reflected_voltage_v / (reflected_voltage_v + vdc_min)
    # Peak current at 90% of the device's minimum guaranteed limit; the
    # inductance follows from the energy balance at the SLOWEST fsw.
    ipk_budget_a = 0.9 * ilimit_min_a
    inductance_h = 2.0 * pin_w / (ipk_budget_a**2 * fsw_min_hz)
    ipk_a = math.sqrt(2.0 * pin_w / (inductance_h * fsw_min_hz))
    ton_s = inductance_h * ipk_a / vdc_min
    if ton_s > ton_max_s:
        warnings.append(
            f"Required on-time {ton_s * 1e6:.2f}us exceeds the device "
            f"maximum {ton_max_s * 1e6:.1f}us; reduce power or raise VOR."
        )
    demag_s = inductance_h * ipk_a / reflected_voltage_v
    period_min_s = 1.0 / fsw_min_hz
    dcm_margin = (ton_s + demag_s) / period_min_s
    if dcm_margin > 0.9:
        warnings.append(
            f"DCM margin is thin ({dcm_margin:.0%} of the period); the "
            "converter may enter CCM at low line."
        )

    turns_ratio = reflected_voltage_v / (vout_v + diode_drop_v)
    turns_ratio_selected = round(turns_ratio)

    drain_peak_v = vdc_peak_max + 2.5 * reflected_voltage_v
    secondary_piv_v = vout_v + vdc_peak_max / turns_ratio_selected

    # RCD clamp bleed: the clamp resistor holds Vclamp between switching
    # events, dissipating ~ Vclamp * (Vclamp - VOR) / R continuously. The
    # FLBACK-001 reference uses a 2 W axial here; small-body resistors
    # cook (rule of thumb: warn past 0.4 W).
    clamp_dissipation_w = None
    if clamp_resistance_ohms is not None:
        vclamp = clamp_voltage_v if clamp_voltage_v is not None else 2.5 * reflected_voltage_v
        clamp_dissipation_w = (
            vclamp * max(vclamp - reflected_voltage_v, 0.0) / clamp_resistance_ohms
        )
        if clamp_dissipation_w > 0.4:
            warnings.append(
                f"Clamp resistor dissipates ~{clamp_dissipation_w:.2f}W "
                "continuously; specify a >= 2W axial part "
                "(reference-design practice)."
            )

    lower_ohms = 12000.0
    upper_exact = lower_ohms * (vout_v - ref_voltage_v) / ref_voltage_v
    upper_ohms = nearest_e24_ohms(upper_exact)
    vout_regulated = ref_voltage_v * (1.0 + upper_ohms / lower_ohms)
    if abs(vout_regulated - vout_v) > 0.03 * vout_v:
        warnings.append(
            f"E24 divider regulates to {vout_regulated:.3f}V "
            f"({(vout_regulated / vout_v - 1):+.1%} from target)."
        )

    return {
        "status": "warning" if warnings else "ok",
        "outputs": {
            "pin_w": round(pin_w, 3),
            "vdc_min_v": round(vdc_min, 1),
            "vdc_peak_max_v": round(vdc_peak_max, 1),
            "duty_max": round(duty_max, 4),
            "primary_inductance_h": round(inductance_h, 6),
            "peak_primary_current_a": round(ipk_a, 4),
            "on_time_s": round(ton_s, 9),
            "dcm_period_fraction": round(dcm_margin, 3),
            "turns_ratio": round(turns_ratio, 2),
            "turns_ratio_selected": float(turns_ratio_selected),
            "clamp_dissipation_w": (
                round(clamp_dissipation_w, 3) if clamp_dissipation_w is not None else None
            ),
            "drain_peak_v": round(drain_peak_v, 1),
            "secondary_piv_v": round(secondary_piv_v, 2),
            "feedback_upper_ohms": upper_ohms,
            "feedback_lower_ohms": lower_ohms,
            "vout_regulated_v": round(vout_regulated, 4),
        },
        "warnings": warnings,
        "errors": [],
        "references": [
            "UCC28881 datasheet (ai_assets/datasheets/ucc28881.pdf) p6: "
            "fSW 52-75 kHz, ILIMIT 330-570 mA, tON_MAX >= 6.5 us; p3 pin "
            "table; 700 V drain p4.",
            "LMV431 datasheet (ai_assets/datasheets/lmv431.pdf) p5: VREF 1.24 V, IZ(MIN) <= 80 uA.",
            "DCM flyback energy balance: Pin = 0.5*Lp*Ipk^2*fsw; "
            "Dmax = VOR/(VOR+Vdc_min); Np/Ns = VOR/(Vout+Vf).",
        ],
    }


def solve_trace_current_capacity(
    *,
    trace_width_m: float,
    copper_thickness_m: float = 35e-6,
    temperature_rise_c: float = 10.0,
) -> dict[str, Any]:
    """Legacy IPC-2221A Figure 6-4 external fit: I = k*dT^0.44*A^0.725.

    k = 0.048 for external layers, A in square mils. At 10 C rise a 0.8 mm
    1 oz trace carries ~2 A, matching the published nomograph tables.
    """
    errors: list[str] = []
    if trace_width_m <= 0 or copper_thickness_m <= 0:
        errors.append("Trace width and copper thickness must be positive.")
    if temperature_rise_c <= 0:
        errors.append("Temperature rise must be positive.")
    if errors:
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}
    mil = 25.4e-6
    area_sq_mil = (trace_width_m / mil) * (copper_thickness_m / mil)
    capacity_a = 0.048 * temperature_rise_c**0.44 * area_sq_mil**0.725
    return {
        "status": "ok",
        "outputs": {
            "cross_section_sq_mil": round(area_sq_mil, 3),
            "capacity_a": round(capacity_a, 4),
        },
        "warnings": [],
        "errors": [],
        "references": [
            "Legacy IPC-2221A Figure 6-4 external fit: I = 0.048 * dT^0.44 * "
            "A^0.725 (A in sq mil).",
        ],
    }


def solve_pcb_spiral_inductor(
    *,
    outer_diameter_m: float,
    trace_width_m: float,
    trace_gap_m: float,
    turns: int,
    copper_thickness_m: float = 35e-6,
    frequency_hz: float | None = None,
) -> dict[str, Any]:
    """Circular planar spiral inductance via the current-sheet approximation.

    Mohan, del Mar Hershenson, Boyd, Lee, "Simple Accurate Expressions for
    Planar Spiral Inductances", IEEE JSSC 34(10), 1999. Circle coefficients
    c1=1.00, c2=2.46, c3=0.00, c4=0.20; stated accuracy ~2-3% for
    0.2 <= fill ratio.
    """
    errors: list[str] = []
    if outer_diameter_m <= 0:
        errors.append("Outer diameter must be positive.")
    if trace_width_m <= 0 or trace_gap_m <= 0:
        errors.append("Trace width and gap must be positive.")
    if turns < 2:
        errors.append("A spiral needs at least two turns.")
    pitch_m = trace_width_m + trace_gap_m
    inner_diameter_m = outer_diameter_m - 2 * turns * pitch_m
    if not errors and inner_diameter_m <= trace_width_m:
        errors.append(
            f"{turns} turns at {pitch_m * 1000:g} mm pitch overrun the "
            f"{outer_diameter_m * 1000:g} mm outer diameter."
        )
    if errors:
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}

    mu0 = 4e-7 * math.pi
    average_diameter_m = (outer_diameter_m + inner_diameter_m) / 2
    fill_ratio = (outer_diameter_m - inner_diameter_m) / (outer_diameter_m + inner_diameter_m)
    inductance_h = (
        mu0
        * turns**2
        * average_diameter_m
        * 1.00
        / 2
        * (math.log(2.46 / fill_ratio) + 0.20 * fill_ratio**2)
    )
    # Independent cross-check: the modified-Wheeler expression from the
    # same paper (octagonal coefficients K1=2.25, K2=3.55; an octagon
    # tracks a circle within a few percent). Two estimators from separate
    # derivations agreeing is the guard against a mis-remembered formula -
    # the simulation cannot provide it because it consumes this value.
    wheeler_h = 2.25 * mu0 * turns**2 * average_diameter_m / (1 + 3.55 * fill_ratio)
    trace_length_m = math.pi * average_diameter_m * turns
    resistance_ohm = (
        COPPER_RESISTIVITY_OHM_M * trace_length_m / (trace_width_m * copper_thickness_m)
    )

    warnings: list[str] = []
    outputs = {
        "inductance_h": round(inductance_h, 12),
        "wheeler_inductance_h": round(wheeler_h, 12),
        "inner_diameter_m": round(inner_diameter_m, 6),
        "average_diameter_m": round(average_diameter_m, 6),
        "fill_ratio": round(fill_ratio, 6),
        "trace_length_m": round(trace_length_m, 4),
        "dc_resistance_ohm": round(resistance_ohm, 4),
    }
    disagreement = abs(inductance_h - wheeler_h) / inductance_h
    if disagreement > 0.10:
        warnings.append(
            f"The current-sheet and modified-Wheeler estimates disagree by "
            f"{disagreement:.0%}; do not trust either without measurement."
        )
    if fill_ratio < 0.2:
        warnings.append(
            "Fill ratio below 0.2 is outside the current-sheet formula's stated accuracy band."
        )
    if frequency_hz is not None:
        quality = 2 * math.pi * frequency_hz * inductance_h / resistance_ohm
        outputs["quality_factor"] = round(quality, 2)
        if quality < 10:
            warnings.append(
                f"Coil Q of {quality:.1f} at {frequency_hz / 1e6:g} MHz is low; "
                "oscillation amplitude and detection sensitivity suffer."
            )
    return {
        "status": "warning" if warnings else "ok",
        "outputs": outputs,
        "warnings": warnings,
        "errors": [],
        "references": [
            "Mohan et al. 1999 current-sheet approximation, circle "
            "coefficients c1=1.00 c2=2.46 c3=0 c4=0.20.",
            "Cross-check: Mohan et al. modified Wheeler, octagonal coefficients K1=2.25 K2=3.55.",
            "DC resistance: rho * length / (width * copper thickness).",
        ],
    }


def solve_colpitts_oscillator(
    *,
    supply_voltage_v: float,
    inductance_h: float,
    tank_c1_f: float,
    tank_c2_f: float,
    emitter_resistor_ohms: float,
    base_upper_ohms: float,
    base_lower_ohms: float,
) -> dict[str, Any]:
    """Common-base Colpitts oscillator: frequency and DC bias point."""
    errors: list[str] = []
    for label, value in (
        ("Supply voltage", supply_voltage_v),
        ("Inductance", inductance_h),
        ("Tank C1", tank_c1_f),
        ("Tank C2", tank_c2_f),
        ("Emitter resistor", emitter_resistor_ohms),
        ("Upper bias resistor", base_upper_ohms),
        ("Lower bias resistor", base_lower_ohms),
    ):
        if value <= 0:
            errors.append(f"{label} must be positive.")
    if errors:
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}

    series_c_f = tank_c1_f * tank_c2_f / (tank_c1_f + tank_c2_f)
    frequency_hz = 1 / (2 * math.pi * math.sqrt(inductance_h * series_c_f))
    base_v = supply_voltage_v * base_lower_ohms / (base_upper_ohms + base_lower_ohms)
    emitter_v = base_v - 0.7
    collector_current_a = emitter_v / emitter_resistor_ohms

    warnings: list[str] = []
    if emitter_v <= 0.3:
        errors.append(f"Base divider gives {base_v:.2f} V; the transistor cannot bias on.")
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}
    if collector_current_a < 0.5e-3 or collector_current_a > 10e-3:
        warnings.append(
            f"Collector current {collector_current_a * 1000:.2f} mA is outside "
            "the comfortable 0.5-10 mA small-signal window."
        )
    return {
        "status": "warning" if warnings else "ok",
        "outputs": {
            "series_tank_c_f": round(series_c_f, 15),
            "frequency_hz": round(frequency_hz, 1),
            "base_v": round(base_v, 4),
            "collector_current_a": round(collector_current_a, 6),
        },
        "warnings": warnings,
        "errors": [],
        "references": [
            "Colpitts: f = 1 / (2*pi*sqrt(L * C1*C2/(C1+C2))).",
            "Bias: Vb = Vcc*R2/(R1+R2); Ic ~= (Vb - 0.7) / RE.",
        ],
    }


def solve_i2c_pullup(
    *,
    supply_voltage_v: float,
    bus_capacitance_pf: float,
    rise_time_ns: float = I2C_FAST_MODE_RISE_TIME_NS,
) -> dict[str, Any]:
    errors: list[str] = []
    if supply_voltage_v <= I2C_LOW_LEVEL_VOLTAGE_V:
        errors.append("Supply voltage must exceed the I2C low-level voltage.")
    if bus_capacitance_pf <= 0:
        errors.append("Bus capacitance must be positive.")
    if rise_time_ns <= 0:
        errors.append("Rise time must be positive.")
    if errors:
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}

    maximum_ohms = (rise_time_ns * 1e-9) / (I2C_RC_RISE_FACTOR * bus_capacitance_pf * 1e-12)
    minimum_ohms = (supply_voltage_v - I2C_LOW_LEVEL_VOLTAGE_V) / (I2C_LOW_LEVEL_SINK_MA / 1000.0)
    if minimum_ohms >= maximum_ohms:
        return {
            "status": "error",
            "outputs": {},
            "warnings": [],
            "errors": [
                f"No pullup satisfies both limits: minimum {minimum_ohms:.0f} ohm "
                f"exceeds maximum {maximum_ohms:.0f} ohm at "
                f"{bus_capacitance_pf:g} pF."
            ],
        }
    target = (minimum_ohms * maximum_ohms) ** 0.5
    selected = nearest_e24_ohms(target)
    if selected < minimum_ohms or selected > maximum_ohms:
        selected = nearest_e24_ohms((minimum_ohms + maximum_ohms) / 2)
    warnings = [
        f"Bus capacitance {bus_capacitance_pf:g} pF is an assumption; measure "
        "the real bus before finalizing the pullup value.",
    ]
    return {
        "status": "warning",
        "outputs": {
            "minimum_ohms": round(minimum_ohms, 3),
            "maximum_ohms": round(maximum_ohms, 3),
            "selected_ohms": selected,
        },
        "warnings": warnings,
        "errors": [],
        "references": [
            "I2C-bus specification: Rmax = tr / (0.8473*Cb); "
            "Rmin = (VDD - VOL) / IOL with IOL = 3 mA, VOL = 0.4 V.",
        ],
    }


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


def solve_555_servo_tester(
    *,
    vcc_v: float = 6.0,
    r_charge_ohms: float = 33e3,
    r_forward_ohms: float = 68e3,
    r_reverse_ohms: float = 10e3,
    c_timing_f: float = 100e-9,
    base_resistor_ohms: float = 1e3,
    collector_pullup_ohms: float = 4.7e3,
    vbe_v: float = 0.7,
    output_drop_v: float = 1.7,
    servo_pulse_min_s: float = 0.9e-3,
    servo_pulse_max_s: float = 2.1e-3,
) -> dict[str, Any]:
    """The 555-timer-circuits.com SERVO TESTER design point (the circuit
    the instructables 'Drive Servos With a 555 Timer IC' builds).

    Astable per the NE555 datasheet (SLFS022, section 6.3.2 p12):
    tH = 0.693*(RA+RB)*C, tL = 0.693*RB*C, where RA is the 33k charge
    resistor and RB is whichever button branch (68k FORWARD / 10k
    REVERSE) is held. The BC547 stage INVERTS pin 3, so the servo pulse
    width equals tL. Both branches land OUTSIDE the standard 0.9-2.1ms
    proportional window - by design this is an END-STOP driver/tester,
    not a proportional controller, and the outputs say so honestly.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not 4.5 <= vcc_v <= 16.0:
        errors.append(f"VCC {vcc_v:g}V outside the NE555 supply range 4.5-16V (SLFS022 p3).")
    if errors:
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}

    def branch(rb_ohms: float) -> dict[str, float]:
        t_high = 0.693 * (r_charge_ohms + rb_ohms) * c_timing_f
        t_low = 0.693 * rb_ohms * c_timing_f
        period = t_high + t_low
        return {
            "servo_pulse_ms": round(t_low * 1e3, 3),
            "frame_period_ms": round(period * 1e3, 3),
            "frame_rate_hz": round(1.0 / period, 1),
        }

    forward = branch(r_forward_ohms)
    reverse = branch(r_reverse_ohms)
    for name, data in (("FORWARD", forward), ("REVERSE", reverse)):
        pulse_s = data["servo_pulse_ms"] / 1e3
        if not servo_pulse_min_s <= pulse_s <= servo_pulse_max_s:
            warnings.append(
                f"{name} pulse {data['servo_pulse_ms']:g}ms is outside "
                f"the {servo_pulse_min_s * 1e3:g}-"
                f"{servo_pulse_max_s * 1e3:g}ms proportional window: the "
                "servo drives to an end stop (the source circuit's "
                "intended behaviour for a tester)."
            )

    v_out_high = vcc_v - output_drop_v
    base_current_a = (v_out_high - vbe_v) / base_resistor_ohms
    collector_current_a = vcc_v / collector_pullup_ohms
    forced_beta = collector_current_a / base_current_a
    if forced_beta > 10.0:
        warnings.append(
            f"Forced beta {forced_beta:.1f} is high; the BC547 may not saturate cleanly."
        )

    return {
        "status": "warning" if warnings else "ok",
        "outputs": {
            "forward": forward,
            "reverse": reverse,
            "base_current_ma": round(base_current_a * 1e3, 2),
            "collector_current_ma": round(collector_current_a * 1e3, 2),
            "forced_beta": round(forced_beta, 2),
            "output_high_v": round(v_out_high, 2),
        },
        "warnings": warnings,
        "errors": [],
        "references": [
            "NE555 datasheet SLFS022 (ai_assets/datasheets/ne555.pdf) "
            "p12 eq 1-3 (astable tH/tL), p3 (VCC 4.5-16V), p18 (bypass "
            "capacitor recommendation), p17 (output level).",
            "555-timer-circuits.com SERVO TESTER (the schematic the "
            "instructable reproduces): 33k charge, 68k/10k button "
            "branches, 100n timing, 10n control bypass, BC547 inverter "
            "with 1k base and 4k7 collector.",
            "Proportional window 0.9-2.1ms per the same site's pot "
            "variant (SERVO CONTROLLER page).",
        ],
    }


def thermometer_scale_fraction(
    temperature_c: float,
    *,
    scale_min_c: float = 0.0,
    scale_max_c: float = 50.0,
) -> float:
    """Where a temperature sits on the thermometer scale, 0.0 at the
    bottom of the scale to 1.0 at the top. ONE function feeds the
    firmware thresholds, the LED column placement, and the silkscreen
    tick marks, so the mercury column and the printed graduations can
    never drift apart."""
    span = scale_max_c - scale_min_c
    if span <= 0:
        raise ValueError("scale_max_c must exceed scale_min_c")
    return (temperature_c - scale_min_c) / span


def solve_thermometer_display(
    *,
    vbus_v: float = 5.0,
    vcc_v: float = 3.3,
    led_count: int = 16,
    led_vf_typ_v: float = 1.85,
    led_vf_dim_v: float = 2.2,
    led_series_ohms: float = 270.0,
    scale_min_c: float = 0.0,
    scale_max_c: float = 50.0,
    module_current_a: float = 0.30,
    display_current_a: float = 0.04,
    i2c_bus_capacitance_f: float = 50e-12,
    i2c_rise_time_max_s: float = 1000e-9,
    i2c_pullup_ohms: float = 4.7e3,
    i2c_sink_current_a: float = 3e-3,
    i2c_vol_v: float = 0.4,
    hc595_supply_abs_max_a: float = 0.070,
    ldo_current_min_a: float = 0.6,
    ldo_theta_ja_c_per_w: float = 250.0,
) -> dict[str, Any]:
    """Design chain for the thermometer-shaped SHT31 + ESP32-C3 display.

    LED chain per the Kingbright APT2012SRCPRV datasheet (Vf 1.85V typ /
    2.5V max at 20mA, p2; the p3 V-I curve puts the dim-corner Vf near
    2.2V at the low currents used here). Per-device current against the
    SN74HC595 absolute continuous VCC/GND limit (70mA). I2C pull-up
    window per the standard-mode rise-time budget (t_r <= 0.8473*R*Cb).
    AP2112K-3.3 dissipation from the worst-case rail current (module
    WiFi TX burst + both OLEDs + full LED column).
    """
    errors: list[str] = []
    warnings: list[str] = []
    if led_count < 2 or led_count % 8:
        errors.append(
            f"led_count {led_count} must be a positive multiple of 8 (whole 74HC595 stages)."
        )
    if not 3.0 <= vcc_v <= 3.6:
        errors.append(
            f"VCC {vcc_v:g}V outside the ESP32-C3-WROOM-02 supply range 3.0-3.6V (datasheet p3)."
        )
    if errors:
        return {"status": "error", "outputs": {}, "warnings": [], "errors": errors}

    led_current_typ_a = (vcc_v - led_vf_typ_v) / led_series_ohms
    led_current_dim_a = max(0.0, (vcc_v - led_vf_dim_v) / led_series_ohms)
    per_register_a = 8 * led_current_typ_a
    if per_register_a > hc595_supply_abs_max_a:
        errors.append(
            f"Per-74HC595 supply current {per_register_a * 1e3:.1f}mA "
            f"exceeds the {hc595_supply_abs_max_a * 1e3:.0f}mA absolute "
            "continuous VCC/GND limit (SN74HC595 abs max table)."
        )
    if led_current_dim_a < 1.5e-3:
        warnings.append(
            f"Dim-corner LED current {led_current_dim_a * 1e3:.1f}mA may "
            "be hard to see through a diffuser; consider a smaller "
            "series resistor."
        )

    degrees_per_led = (scale_max_c - scale_min_c) / led_count
    # 4 decimals keeps the default 3.125C steps EXACT: these numbers
    # are the shared truth for firmware, LED placement, and silk ticks.
    led_on_thresholds_c = [
        round(scale_min_c + step * degrees_per_led, 4) for step in range(1, led_count + 1)
    ]

    pullup_max_ohms = i2c_rise_time_max_s / (0.8473 * i2c_bus_capacitance_f)
    pullup_min_ohms = (vcc_v - i2c_vol_v) / i2c_sink_current_a
    if not pullup_min_ohms <= i2c_pullup_ohms <= pullup_max_ohms:
        errors.append(
            f"I2C pull-up {i2c_pullup_ohms:g} ohm outside the "
            f"{pullup_min_ohms:.0f}-{pullup_max_ohms:.0f} ohm window."
        )

    total_led_a = led_count * led_current_typ_a
    rail_current_a = module_current_a + display_current_a + total_led_a
    if rail_current_a > ldo_current_min_a:
        errors.append(
            f"Worst-case rail current {rail_current_a * 1e3:.0f}mA "
            f"exceeds the AP2112 guaranteed {ldo_current_min_a * 1e3:.0f}mA."
        )
    ldo_dissipation_w = (vbus_v - vcc_v) * rail_current_a
    ldo_rise_c = ldo_dissipation_w * ldo_theta_ja_c_per_w
    if ldo_rise_c > 80.0:
        warnings.append(
            f"LDO temperature rise {ldo_rise_c:.0f}C at the worst-case "
            f"{rail_current_a * 1e3:.0f}mA rail (module WiFi TX burst): "
            "keep the radio off or duty-cycled in firmware - the display "
            "workload itself draws a small fraction of this."
        )

    if errors:
        return {"status": "error", "outputs": {}, "warnings": warnings, "errors": errors}
    return {
        "status": "warning" if warnings else "ok",
        "outputs": {
            "led_current_typ_ma": round(led_current_typ_a * 1e3, 2),
            "led_current_dim_ma": round(led_current_dim_a * 1e3, 2),
            "per_register_supply_ma": round(per_register_a * 1e3, 1),
            "total_led_current_ma": round(total_led_a * 1e3, 1),
            "degrees_per_led_c": round(degrees_per_led, 3),
            "led_on_thresholds_c": led_on_thresholds_c,
            "i2c_pullup_min_ohms": round(pullup_min_ohms, 0),
            "i2c_pullup_max_ohms": round(pullup_max_ohms, 0),
            "i2c_pullup_ohms": i2c_pullup_ohms,
            "rail_current_worst_ma": round(rail_current_a * 1e3, 1),
            "ldo_dissipation_w": round(ldo_dissipation_w, 3),
            "ldo_temperature_rise_c": round(ldo_rise_c, 1),
        },
        "warnings": warnings,
        "errors": [],
        "references": [
            "Kingbright APT2012SRCPRV (ai_assets/datasheets/"
            "kingbright-apt2012srcprv.pdf) p2 (Vf 1.85 typ / 2.5 max at "
            "20mA), p3 (V-I curve for the dim corner).",
            "TI SN74HC595 (ai_assets/datasheets/sn74hc595.pdf) p1 "
            "(2-6V), p4 (absolute maximum continuous VCC/GND current).",
            "Espressif ESP32-C3-WROOM-02 (ai_assets/datasheets/"
            "esp32-c3-wroom-02.pdf) p3 (3.0-3.6V supply).",
            "Diodes AP2112 (ai_assets/datasheets/ap2112.pdf) p1 (600mA min), p2 (1uF X7R in/out).",
            "Sensirion SHT3x-DIS (ai_assets/datasheets/sht3x-dis.pdf) "
            "p6 (supply), p8 (pinout), p9 (I2C addresses).",
            "I2C rise-time budget t_r = 0.8473*Rp*Cb (NXP UM10204).",
        ],
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
    """Estimate a planar spiral while retaining explicit approximation evidence."""
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
        return _calculation_result(
            "pcb-spiral-coil-estimate",
            inputs=inputs,
            outputs={},
            errors=errors,
        )

    radial_build_mm = turns * trace_width_mm + (turns - 1) * trace_spacing_mm
    inner_diameter_mm = outer_diameter_mm - 2 * radial_build_mm
    if inner_diameter_mm <= 0:
        return _calculation_result(
            "pcb-spiral-coil-estimate",
            inputs=inputs,
            outputs={},
            errors=["Coil geometry is impossible: inner diameter is not positive."],
        )

    average_diameter_m = (outer_diameter_mm + inner_diameter_mm) / 2 / 1000
    fill_ratio = (outer_diameter_mm - inner_diameter_mm) / (outer_diameter_mm + inner_diameter_mm)
    k1, k2 = _MODIFIED_WHEELER_COEFFICIENTS[normalized_shape]
    inductance_h = k1 * _MU0_H_PER_M * turns**2 * average_diameter_m / (1 + k2 * fill_ratio)
    trace_length_mm = _spiral_trace_length_mm(
        shape=normalized_shape,
        turns=turns,
        outer_diameter_mm=outer_diameter_mm,
        trace_width_mm=trace_width_mm,
        trace_spacing_mm=trace_spacing_mm,
    )
    dc_resistance_ohms = _spiral_dc_resistance_ohms(
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
    return _calculation_result(
        "pcb-spiral-coil-estimate",
        inputs=inputs,
        status="ok",
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
            "Mohan, Hershenson, Boyd, Lee, Simple Accurate Expressions for "
            "Planar Spiral Inductances",
        ],
    )


def solve_lc_resonance(
    *,
    inductance_uH: float,
    capacitance_nF: float | None = None,
    target_frequency_hz: float | None = None,
) -> dict[str, Any]:
    """Solve one missing LC resonance variable with structured evidence."""
    inputs = {
        "inductance_uH": inductance_uH,
        "capacitance_nF": capacitance_nF,
        "target_frequency_hz": target_frequency_hz,
    }
    errors: list[str] = []
    if inductance_uH <= 0:
        errors.append("Inductance must be positive.")
    if (capacitance_nF is None) == (target_frequency_hz is None):
        errors.append("Provide exactly one of capacitance_nF or target_frequency_hz.")
    if capacitance_nF is not None and capacitance_nF <= 0:
        errors.append("Capacitance must be positive.")
    if target_frequency_hz is not None and target_frequency_hz <= 0:
        errors.append("Target frequency must be positive.")
    if errors:
        return _calculation_result(
            "lc-resonance",
            inputs=inputs,
            outputs={},
            errors=errors,
        )

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
        capacitance_f = 1 / ((2 * math.pi * target_frequency_hz) ** 2 * inductance_h)
        outputs = {
            "capacitance_nF": round(capacitance_f * 1_000_000_000, 6),
        }
    return _calculation_result(
        "lc-resonance",
        inputs=inputs,
        outputs=outputs,
    )


def run_calculator(
    name: str,
    parameters: Mapping[str, str],
) -> dict[str, Any]:
    """Dispatch the bounded calculator surface used by AI and CLI callers."""
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
            target_frequency_hz=_optional_float_param(
                parameters,
                "target_frequency_hz",
            ),
        )
    if name == "lm2596-buck":
        return solve_lm2596_buck(
            input_voltage_min_v=_float_param(
                parameters,
                "input_voltage_min_v",
            ),
            input_voltage_nominal_v=_float_param(
                parameters,
                "input_voltage_nominal_v",
            ),
            input_voltage_max_v=_float_param(
                parameters,
                "input_voltage_max_v",
            ),
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
            "Use calculators supported_calculators for engineering math instead "
            "of freehand arithmetic."
        ),
        "Treat calculator error status as blocking for schematic or PCB generation.",
        (
            "Include calculator outputs in review notes when they affect "
            "component values or geometry."
        ),
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


def _calculation_result(
    calculator: str,
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    status: str | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    normalized_errors = errors or []
    normalized_warnings = warnings or []
    if status is None:
        status = "error" if normalized_errors else "warning" if normalized_warnings else "ok"
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
    errors: list[str] = []
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


def _spiral_trace_length_mm(
    *,
    shape: str,
    turns: int,
    outer_diameter_mm: float,
    trace_width_mm: float,
    trace_spacing_mm: float,
) -> float:
    pitch_mm = trace_width_mm + trace_spacing_mm
    centerline_diameters = [
        outer_diameter_mm - trace_width_mm - 2 * index * pitch_mm for index in range(turns)
    ]
    if shape == "square":
        return sum(4 * diameter for diameter in centerline_diameters)
    if shape == "hexagonal":
        return sum(3 * math.sqrt(3) * diameter for diameter in centerline_diameters)
    if shape == "octagonal":
        return sum(8 * diameter * math.tan(math.pi / 8) for diameter in centerline_diameters)
    return sum(math.pi * diameter for diameter in centerline_diameters)


def _spiral_dc_resistance_ohms(
    *,
    trace_length_mm: float,
    trace_width_mm: float,
    copper_thickness_um: float,
) -> float:
    length_m = trace_length_mm / 1000
    area_m2 = trace_width_mm / 1000 * copper_thickness_um / 1_000_000
    return COPPER_RESISTIVITY_OHM_M * length_m / area_m2


def _float_param(
    parameters: Mapping[str, str],
    name: str,
    *,
    default: float | None = None,
) -> float:
    value = parameters.get(name)
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required calculator parameter: {name}")
    return float(value)


def _optional_float_param(
    parameters: Mapping[str, str],
    name: str,
) -> float | None:
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
