from __future__ import annotations

import math
from typing import Any

LM2596_FEEDBACK_REFERENCE_V = 1.23
LM2596_SWITCHING_FREQUENCY_HZ = 150_000.0

_STANDARD_FEEDBACK_UPPER_OHMS = (3300, 3480, 3600, 3740, 3900, 4020, 4220)
_STANDARD_INDUCTANCES_UH = (33, 47, 68, 100, 150, 220)
_STANDARD_OUTPUT_CAPS_UF = (22, 47, 100, 220, 330, 470)


COPPER_RESISTIVITY_OHM_M = 1.72e-8


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


_E24_MANTISSAS = (
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
    3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1,
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
            "Series LED string: R = (Vsupply - n*Vf) / I_target; Vf from the "
            "component datasheet.",
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
            "status": "error", "outputs": {}, "warnings": [],
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
        vclamp = (
            clamp_voltage_v
            if clamp_voltage_v is not None
            else 2.5 * reflected_voltage_v
        )
        clamp_dissipation_w = (
            vclamp * max(vclamp - reflected_voltage_v, 0.0)
            / clamp_resistance_ohms
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
                round(clamp_dissipation_w, 3)
                if clamp_dissipation_w is not None
                else None
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
            "LMV431 datasheet (ai_assets/datasheets/lmv431.pdf) p5: "
            "VREF 1.24 V, IZ(MIN) <= 80 uA.",
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
    """IPC-2221 external-layer current capacity: I = k * dT^0.44 * A^0.725.

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
            "IPC-2221 external-layer chart fit: I = 0.048 * dT^0.44 * "
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
    fill_ratio = (outer_diameter_m - inner_diameter_m) / (
        outer_diameter_m + inner_diameter_m
    )
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
    wheeler_h = (
        2.25 * mu0 * turns**2 * average_diameter_m / (1 + 3.55 * fill_ratio)
    )
    trace_length_m = math.pi * average_diameter_m * turns
    resistance_ohm = (
        COPPER_RESISTIVITY_OHM_M * trace_length_m
        / (trace_width_m * copper_thickness_m)
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
            "Fill ratio below 0.2 is outside the current-sheet formula's "
            "stated accuracy band."
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
            "Cross-check: Mohan et al. modified Wheeler, octagonal "
            "coefficients K1=2.25 K2=3.55.",
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
        errors.append(
            f"Base divider gives {base_v:.2f} V; the transistor cannot bias on."
        )
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

    maximum_ohms = (rise_time_ns * 1e-9) / (
        I2C_RC_RISE_FACTOR * bus_capacitance_pf * 1e-12
    )
    minimum_ohms = (supply_voltage_v - I2C_LOW_LEVEL_VOLTAGE_V) / (
        I2C_LOW_LEVEL_SINK_MA / 1000.0
    )
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
