"""Thermometer display design chain: hand checks on the outputs."""

from __future__ import annotations

import math

from pcbsmith.calculators.electronics import (
    solve_thermometer_display,
    thermometer_scale_fraction,
)


def test_design_point_holds_by_hand() -> None:
    result = solve_thermometer_display()
    assert result["status"] in ("ok", "warning")
    out = result["outputs"]
    # Ohm's law on the LED chain, recomputed from first principles.
    assert math.isclose(
        out["led_current_typ_ma"], (3.3 - 1.85) / 270.0 * 1e3, abs_tol=0.01
    )
    assert math.isclose(
        out["per_register_supply_ma"], 8 * out["led_current_typ_ma"],
        rel_tol=1e-3,
    )
    assert out["per_register_supply_ma"] < 70.0  # HC595 abs max
    # Threshold ladder: monotone, endpoints at the scale limits.
    thresholds = out["led_on_thresholds_c"]
    assert len(thresholds) == 16
    assert thresholds == sorted(thresholds)
    assert math.isclose(thresholds[-1], 50.0, abs_tol=1e-9)
    assert math.isclose(out["degrees_per_led_c"], 50.0 / 16, abs_tol=1e-9)
    # I2C pull-up inside the computed window.
    assert (
        out["i2c_pullup_min_ohms"]
        <= out["i2c_pullup_ohms"]
        <= out["i2c_pullup_max_ohms"]
    )
    # LDO energy balance: P = (Vbus - Vcc) * I.
    assert math.isclose(
        out["ldo_dissipation_w"],
        (5.0 - 3.3) * out["rail_current_worst_ma"] / 1e3,
        rel_tol=1e-2,
    )
    # The WiFi-burst thermal warning must ride the result honestly.
    assert any("WiFi" in warning for warning in result["warnings"])


def test_scale_fraction_is_shared_geometry_truth() -> None:
    assert thermometer_scale_fraction(0.0) == 0.0
    assert thermometer_scale_fraction(50.0) == 1.0
    assert math.isclose(thermometer_scale_fraction(20.0), 0.4)
    # LED k's threshold lands exactly at its fraction of the scale.
    out = solve_thermometer_display()["outputs"]
    for index, threshold in enumerate(out["led_on_thresholds_c"], start=1):
        assert math.isclose(
            thermometer_scale_fraction(threshold), index / 16, abs_tol=1e-6
        )


def test_guards_fire() -> None:
    assert solve_thermometer_display(led_count=15)["status"] == "error"
    assert solve_thermometer_display(vcc_v=5.0)["status"] == "error"
    # A tiny series resistor overdrives the register's supply pins.
    hot = solve_thermometer_display(led_series_ohms=100.0)
    assert hot["status"] == "error"
    assert any("VCC/GND" in e for e in hot["errors"])
    # Pull-up outside the window is an error.
    assert solve_thermometer_display(i2c_pullup_ohms=100.0)["status"] == "error"
