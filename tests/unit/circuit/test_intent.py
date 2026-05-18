from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent


def test_classifies_supported_divider_highpass_led_request() -> None:
    intent = classify_circuit_intent(
        "Generate a voltage divider connected to a high-pass filter and LED indicator"
    )

    assert intent.status == "supported"
    assert intent.intent_id == "divider_highpass_led_indicator"
    assert intent.assumptions["supply_voltage_v"] == 5.0


def test_rejects_buck_converter_request_for_this_slice() -> None:
    intent = classify_circuit_intent("Generate a 12V to 5V buck converter")

    assert intent.status == "unsupported"
    assert intent.intent_id == "unsupported"
    assert "Only divider/high-pass/LED indicator is supported" in intent.unsupported_reasons[0]
