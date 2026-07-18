"""Operating-point simulation of the thermometer's LED branches.

What SPICE can honestly verify here is the analog part: one mercury-
column branch (74HC595 output -> 270R -> red LED -> GND) and the power
LED branch (VCC -> 1k -> LED), proving the branch currents land where
the calculator designed them and stay far below the register's per-pin
limit. The diode model is FIT to the datasheet forward-voltage point
(Kingbright red AlGaInP, Vf 1.85V typ at 20mA, N=2 ideality) - a
behavioural stand-in, declared as such.

NOT simulated (and stated in the reconciliation): the shift registers,
the ESP32-C3, I2C, the SHT31, USB and the AP2112 regulator - their
limits are enforced by the calculator against datasheet worst-case
tables, not by SPICE.
"""

from __future__ import annotations

import math
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch
from pcbsmith.simulation.ngspice_buck import parse_ngspice_meas_results

SUPPORTED_TOPOLOGY_ID = "thermometer_env_display"

MODEL_NOTE = (
    "LED branch .op only: diode fit to the datasheet Vf point; the "
    "registers, MCU, sensor and regulator are datasheet-limit verified "
    "by the calculator, NOT SPICE-simulated."
)

# Kingbright red AlGaInP: Vf typ at the datasheet test current.
LED_VF_TYP_V = 1.85
LED_IF_TEST_A = 0.02
LED_IDEALITY = 2.0
THERMAL_VOLTAGE_V = 0.02585


def _ohms(value: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmMrR]?)(?:R|)?", value)
    if match is None:
        raise ValueError(f"Unparseable resistance {value!r}")
    scale = {"": 1.0, "r": 1.0, "k": 1e3, "m": 1e6}[match.group(2).lower()]
    return float(match.group(1)) * scale


def _led_saturation_current() -> float:
    """IS for a diode that hits the datasheet (Vf, If) point at the
    chosen ideality: IS = If / exp(Vf / (N*VT))."""
    return LED_IF_TEST_A / math.exp(
        LED_VF_TYP_V / (LED_IDEALITY * THERMAL_VOLTAGE_V)
    )


def render_thermometer_netlist(circuit: CircuitObject) -> str:
    values = {c.reference: c.value for c in circuit.components}
    r_seg = _ohms(values["R1"])
    r_pwr = _ohms(values["R17"])
    vcc = float(circuit.intent.assumptions["vcc_v"])
    saturation = _led_saturation_current()
    return "\n".join(
        (
            "* thermometer LED branches: segment and power indicator",
            f"VCC vcc 0 DC {vcc:g}",
            # Segment branch: register output (rail, worst case) ->
            # series R -> LED. VSEG is a 0V ammeter.
            "VSEG vcc seg_in DC 0",
            f"R1 seg_in seg_a {r_seg:g}",
            "D1 seg_a 0 DLED",
            # Power LED branch off the rail.
            "VPWR vcc pwr_in DC 0",
            f"R17 pwr_in pwr_a {r_pwr:g}",
            "D17 pwr_a 0 DLED",
            f".model DLED D(IS={saturation:.3e} N={LED_IDEALITY:g} RS=1)",
            ".tran 10u 1m",
            ".meas tran i_seg FIND I(VSEG) AT=0.5m",
            ".meas tran v_f FIND V(seg_a) AT=0.5m",
            ".meas tran i_pwled FIND I(VPWR) AT=0.5m",
            ".end",
            "",
        )
    )


def _evaluate(
    measurements: dict[str, float], circuit: CircuitObject
) -> tuple[str, tuple[str, ...], dict[str, float]]:
    calc = circuit.math.calculations
    findings: list[str] = []
    i_seg = measurements.get("i_seg")
    v_f = measurements.get("v_f")
    i_pwled = measurements.get("i_pwled")
    if i_seg is None or v_f is None or i_pwled is None:
        return (
            "failed",
            ("ngspice did not produce the expected .meas results.",),
            measurements,
        )
    designed_ma = calc["led_current_typ_ma"]
    seg_ma = i_seg * 1e3
    if abs(seg_ma - designed_ma) > 0.2 * designed_ma:
        findings.append(
            f"Segment LED current {seg_ma:.2f}mA deviates more than 20% "
            f"from the designed {designed_ma:g}mA."
        )
    # 74HC595 continuous output current is +/-35mA absolute maximum;
    # the design must sit far below it.
    if seg_ma > 20.0:
        findings.append(
            f"Segment LED current {seg_ma:.2f}mA crowds the register's "
            "per-pin limit."
        )
    if not 1.5 <= v_f <= 2.2:
        findings.append(
            f"LED forward voltage {v_f:.2f}V is outside the red AlGaInP "
            "band (1.5-2.2V) - the branch model is off."
        )
    if not 0.5 <= i_pwled * 1e3 <= 3.0:
        findings.append(
            f"Power LED current {i_pwled * 1e3:.2f}mA is outside the "
            "0.5-3mA indicator band."
        )
    if findings:
        return ("failed", tuple(findings), measurements)
    return ("passed", (MODEL_NOTE,), measurements)


def run_thermometer_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    result = run_ngspice_batch(
        render_thermometer_netlist(circuit),
        output_dir,
        netlist_filename="thermometer_led_op.cir",
        finder=finder,
        runner=runner,
    )
    if result.status in ("unavailable", "failed"):
        return SimulationReport(
            backend="ngspice",
            status=result.status,
            command=result.command if result.status == "failed" else (),
            findings=result.findings,
            raw_output_path=str(result.raw_output_path),
        )
    status, findings, measurements = _evaluate(
        parse_ngspice_meas_results(result.raw_output), circuit
    )
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=result.command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(result.raw_output_path),
    )
