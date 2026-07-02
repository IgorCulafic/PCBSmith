from __future__ import annotations

from pcbsmith.circuit.models import CircuitIntent


def classify_circuit_intent(raw_request: str) -> CircuitIntent:
    normalized = raw_request.lower()
    has_divider = "divider" in normalized
    has_highpass = (
        "high-pass" in normalized or "high pass" in normalized or "highpass" in normalized
    )
    has_led = "led" in normalized or "indicator" in normalized
    if has_divider and has_highpass and has_led:
        return CircuitIntent(
            raw_request=raw_request,
            intent_id="divider_highpass_led_indicator",
            status="supported",
            assumptions={
                "supply_voltage_v": 5.0,
                "divider_target_v": 2.5,
                "led_forward_voltage_v": 2.0,
                "led_target_current_ma": 5.0,
            },
        )
    has_buck = (
        "buck" in normalized or "step-down" in normalized or "step down" in normalized
    )
    if "lm2596" in normalized and has_buck:
        return CircuitIntent(
            raw_request=raw_request,
            intent_id="lm2596_buck_regulator",
            status="supported",
            assumptions={
                "input_voltage_min_v": 7.0,
                "input_voltage_nominal_v": 12.0,
                "input_voltage_max_v": 24.0,
                "output_voltage_v": 5.0,
                "load_current_a": 1.0,
            },
        )
    if has_buck:
        return CircuitIntent(
            raw_request=raw_request,
            intent_id="unsupported",
            status="unsupported",
            unsupported_reasons=(
                "Generic buck converter requests are unsupported: name a specific "
                "regulator with an evidence pack. LM2596 is currently supported.",
            ),
        )
    return CircuitIntent(
        raw_request=raw_request,
        intent_id="unsupported",
        status="unsupported",
        unsupported_reasons=(
            "Supported intents are divider/high-pass/LED indicator and the "
            "LM2596 buck regulator module.",
        ),
    )
