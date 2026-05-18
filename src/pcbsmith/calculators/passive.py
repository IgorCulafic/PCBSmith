from __future__ import annotations

import math


def voltage_divider(
    *,
    input_voltage_v: float,
    r_top_ohms: float,
    r_bottom_ohms: float,
) -> dict[str, float]:
    _positive(input_voltage_v, "input_voltage_v")
    _positive(r_top_ohms, "r_top_ohms")
    _positive(r_bottom_ohms, "r_bottom_ohms")
    total = r_top_ohms + r_bottom_ohms
    return {
        "output_voltage_v": _round(input_voltage_v * (r_bottom_ohms / total)),
        "divider_current_ma": _round((input_voltage_v / total) * 1000.0),
    }


def rc_highpass_cutoff_hz(*, r_ohms: float, c_farads: float) -> float:
    _positive(r_ohms, "r_ohms")
    _positive(c_farads, "c_farads")
    return _round(1.0 / (2.0 * math.pi * r_ohms * c_farads))


def led_current_limit(
    *,
    supply_voltage_v: float,
    led_forward_voltage_v: float,
    resistor_ohms: float,
) -> dict[str, float]:
    _positive(supply_voltage_v, "supply_voltage_v")
    _positive(led_forward_voltage_v, "led_forward_voltage_v")
    _positive(resistor_ohms, "resistor_ohms")
    if led_forward_voltage_v >= supply_voltage_v:
        raise ValueError("LED forward voltage must be below supply voltage")
    current_a = (supply_voltage_v - led_forward_voltage_v) / resistor_ohms
    return {
        "led_current_ma": _round(current_a * 1000.0),
        "resistor_power_w": _round((current_a * current_a) * resistor_ohms),
    }


def _positive(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _round(value: float) -> float:
    return round(value, 3)
