from __future__ import annotations

import pytest

from pcbsmith.calculators.passive import (
    led_current_limit,
    rc_highpass_cutoff_hz,
    voltage_divider,
)


def test_voltage_divider_calculates_output_and_current() -> None:
    result = voltage_divider(input_voltage_v=5.0, r_top_ohms=10_000.0, r_bottom_ohms=10_000.0)

    assert result == {
        "output_voltage_v": 2.5,
        "divider_current_ma": 0.25,
    }


def test_rc_highpass_cutoff_uses_standard_formula() -> None:
    assert rc_highpass_cutoff_hz(r_ohms=10_000.0, c_farads=100e-9) == 159.155


def test_led_current_limit_calculates_current_and_power() -> None:
    result = led_current_limit(
        supply_voltage_v=5.0,
        led_forward_voltage_v=2.0,
        resistor_ohms=680.0,
    )

    assert result == {
        "led_current_ma": 4.412,
        "resistor_power_w": 0.013,
    }


def test_led_current_limit_rejects_forward_voltage_above_supply() -> None:
    with pytest.raises(ValueError, match="LED forward voltage must be below supply voltage"):
        led_current_limit(
            supply_voltage_v=2.0,
            led_forward_voltage_v=2.1,
            resistor_ohms=680.0,
        )
