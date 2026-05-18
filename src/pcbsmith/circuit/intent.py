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
    return CircuitIntent(
        raw_request=raw_request,
        intent_id="unsupported",
        status="unsupported",
        unsupported_reasons=(
            "Only divider/high-pass/LED indicator is supported in this vertical slice.",
        ),
    )
