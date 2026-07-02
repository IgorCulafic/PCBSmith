from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent


def test_classifies_supported_divider_highpass_led_request() -> None:
    intent = classify_circuit_intent(
        "Generate a voltage divider connected to a high-pass filter and LED indicator"
    )

    assert intent.status == "supported"
    assert intent.intent_id == "divider_highpass_led_indicator"
    assert intent.assumptions["supply_voltage_v"] == 5.0


def test_rejects_generic_buck_converter_request() -> None:
    intent = classify_circuit_intent("Generate a 12V to 5V buck converter")

    assert intent.status == "unsupported"
    assert intent.intent_id == "unsupported"
    assert "name a specific regulator" in intent.unsupported_reasons[0]


def test_classifies_lm2596_buck_module_request() -> None:
    intent = classify_circuit_intent(
        "Make the LM2596 DC-DC Buck Converter Step-Down Power Module"
    )

    assert intent.status == "supported"
    assert intent.intent_id == "lm2596_buck_regulator"
    assert intent.assumptions["output_voltage_v"] == 5.0
    assert intent.assumptions["load_current_a"] == 1.0
