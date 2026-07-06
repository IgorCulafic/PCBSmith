from __future__ import annotations

import re

from pcbsmith.circuit.models import CircuitIntent

# Forward voltage from the extracted Kingbright datasheet facts
# (ai_assets/evidence/divider-highpass-led.manifest.json: VF typ 1.85 V).
LED_ART_FORWARD_VOLTAGE_V = 1.85
LED_ART_TARGET_CURRENT_A = 0.010
_TEXT_PATTERN = re.compile(
    r"spell(?:ing|s)?(?:\s+out)?\s+(?P<text>[A-Za-z0-9 .\-]+?)(?:\s+with\b|\s+for\b|$)",
    re.IGNORECASE,
)
_SUPPLY_PATTERN = re.compile(r"(?P<volts>\d+(?:\.\d+)?)\s*v\b", re.IGNORECASE)


def _extract_led_art_text(raw_request: str) -> str | None:
    match = _TEXT_PATTERN.search(raw_request)
    if match is None:
        return None
    text = match.group("text").strip().upper()
    return text or None


def classify_circuit_intent(raw_request: str) -> CircuitIntent:
    normalized = raw_request.lower()
    has_led = "led" in normalized or "indicator" in normalized
    has_art = "matrix" in normalized or "spell" in normalized or "art" in normalized
    if has_led and has_art:
        text = _extract_led_art_text(raw_request)
        if text is None:
            return CircuitIntent(
                raw_request=raw_request,
                intent_id="unsupported",
                status="unsupported",
                unsupported_reasons=(
                    "LED matrix requests must state the text, for example "
                    "'spelling out IGOR C.'.",
                ),
            )
        supply_match = _SUPPLY_PATTERN.search(raw_request)
        supply_v = float(supply_match.group("volts")) if supply_match else 12.0
        return CircuitIntent(
            raw_request=raw_request,
            intent_id="led_text_matrix",
            status="supported",
            assumptions={
                "text": text,
                "supply_voltage_v": supply_v,
                "led_forward_voltage_v": LED_ART_FORWARD_VOLTAGE_V,
                "led_target_current_a": LED_ART_TARGET_CURRENT_A,
            },
        )
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
    if "pear" in normalized:
        supply_match = _SUPPLY_PATTERN.search(raw_request)
        supply_v = float(supply_match.group("volts")) if supply_match else 12.0
        return CircuitIntent(
            raw_request=raw_request,
            intent_id="pear_led_rings",
            status="supported",
            assumptions={
                "supply_voltage_v": supply_v,
                "led_forward_voltage_v": 2.2,
                "led_target_current_a": 0.005,
            },
        )
    if "clover" in normalized:
        return CircuitIntent(
            raw_request=raw_request,
            intent_id="clover_tilt_indicator",
            status="supported",
            assumptions={
                "supply_voltage_v": 3.3,
                "led_forward_voltage_v": 2.2,
                "led_target_current_a": 0.005,
                "i2c_bus_capacitance_pf": 50.0,
                "i2c_rise_time_ns": 300.0,
                "motto": "Luck be with 'ye",
            },
        )
    if "mpu6050" in normalized or "mpu-6050" in normalized:
        supply_match = _SUPPLY_PATTERN.search(raw_request)
        supply_v = float(supply_match.group("volts")) if supply_match else 3.3
        return CircuitIntent(
            raw_request=raw_request,
            intent_id="mpu6050_imu",
            status="supported",
            assumptions={
                "supply_voltage_v": supply_v,
                "i2c_bus_capacitance_pf": 50.0,
                "i2c_rise_time_ns": 300.0,
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
