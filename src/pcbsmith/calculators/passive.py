from __future__ import annotations

import math
import re


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


def led_current_limit_bounds(
    *,
    supply_min_v: float,
    supply_max_v: float,
    forward_min_v: float,
    forward_max_v: float,
    resistance_ohms: float,
    resistance_tolerance: float,
) -> dict[str, float]:
    """Unrounded DC bounds for one resistor/LED series branch (no reverse drive).

    Forward-drop limits and resistor tolerance must cover the operating conditions.
    A zero lower forward drop supplies a conservative shorted-LED current bound.
    """
    values = (
        supply_min_v,
        supply_max_v,
        forward_min_v,
        forward_max_v,
        resistance_ohms,
        resistance_tolerance,
    )
    if any(isinstance(v, bool) or not math.isfinite(v) for v in values):
        raise ValueError("LED envelope requires finite numbers")
    if not (
        0 < supply_min_v <= supply_max_v
        and 0 <= forward_min_v <= forward_max_v
        and resistance_ohms > 0
        and 0 <= resistance_tolerance < 1
    ):
        raise ValueError("LED envelope has invalid bounds")
    low_drop = max(0.0, supply_min_v - forward_max_v)
    high_drop = max(0.0, supply_max_v - forward_min_v)
    rmin = resistance_ohms * (1 - resistance_tolerance)
    rmax = resistance_ohms * (1 + resistance_tolerance)
    return {
        "current_min_a": low_drop / rmax,
        "current_max_a": high_drop / rmin,
        "power_min_w": low_drop**2 / rmax,
        "power_max_w": high_drop**2 / rmin,
    }


def parse_resistance_value(value: str) -> tuple[float, float | None]:
    """Simple schematic resistance, optionally followed by an explicit tolerance."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmMrR]?)(?:R|)?(?:\s+(\d+(?:\.\d+)?)%)?", value)
    if match is None:
        raise ValueError(f"Unparseable resistance {value!r}")
    scale = {"": 1.0, "r": 1.0, "k": 1e3, "m": 1e6}[match.group(2).lower()]
    tolerance = float(match.group(3)) / 100 if match.group(3) is not None else None
    if tolerance is not None and not 0 <= tolerance < 1:
        raise ValueError("Invalid schematic resistance tolerance")
    return float(match.group(1)) * scale, tolerance


def parse_resistance_ohms(value: str) -> float:
    """Preserve the established simulation API, sharing the schematic parser."""
    return parse_resistance_value(value)[0]


def parse_capacitance_farads(value: str) -> float:
    """Parse explicit plain/F, pF, nF, uF/µF or mF schematic values."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([pnuµm]?)[Ff]?", value)
    if match is None:
        raise ValueError(f"Unparseable capacitance {value!r}")
    return (
        float(match.group(1))
        * {"": 1.0, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3}[match.group(2)]
    )
