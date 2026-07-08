"""Transient simulation of the 555 servo tester's output stage.

The 555 astable itself is verified by the deterministic datasheet
equations (SLFS022 6.3.2, calculator + tests); a behavioural 555 macro
would add no truth. What IS simulated: the BC547 inverter driven by a
pin-3-shaped pulse train (REVERSE branch timing from the calculator),
proving the servo signal inverts cleanly - saturated low while the 555
output is high, pulled to the rail through the 4k7 against a
servo-input-class load - and that the positive pulse width equals the
astable's LOW time as designed.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch
from pcbsmith.simulation.ngspice_buck import parse_ngspice_meas_results

SUPPORTED_TOPOLOGY_ID = "servo_555_tester"

MODEL_NOTE = (
    "BC547 inverter stage under a pin-3-shaped pulse train (REVERSE "
    "branch); the astable timing itself is design-equation verified, "
    "NOT SPICE-simulated."
)

SERVO_INPUT_LOAD_OHMS = 30e3  # hobby-servo signal input, order of magnitude


def render_servo555_netlist(circuit: CircuitObject) -> str:
    calc = circuit.math.calculations
    vcc = float(circuit.intent.assumptions["supply_voltage_v"])
    v_high = calc["output_high_v"]
    pulse_ms = calc["reverse_servo_pulse_ms"]
    period_ms = calc["reverse_servo_pulse_ms"] + (
        1e3 / calc["reverse_frame_rate_hz"] - calc["reverse_servo_pulse_ms"]
    )
    t_high_ms = period_ms - pulse_ms  # 555 OUT high while the cap charges
    stop_ms = period_ms * 3
    return "\n".join(
        (
            "* 555 servo tester: BC547 inverter under pin-3 drive",
            f"VCC vcc 0 DC {vcc:g}",
            # Pin 3 emulation: high for tH, low for tL, repeating.
            f"VOUT out 0 PULSE(0 {v_high:g} 0 1u 1u "
            f"{t_high_ms:g}m {period_ms:g}m)",
            "R4 out base 1k",
            "Q1 sig base 0 QBC547",
            "R5 vcc sig 4.7k",
            f"RL sig 0 {SERVO_INPUT_LOAD_OHMS:g}",
            ".model QBC547 NPN(IS=1.8e-14 BF=200 VAF=80 RB=10)",
            f".tran 2u {stop_ms:g}m",
            # While the 555 output is high the transistor saturates.
            f".meas tran sig_low MIN V(sig) from=0.2m to={t_high_ms * 0.9:g}m",
            ".meas tran sig_high MAX V(sig)",
            # The positive servo pulse: crossing width at half swing.
            f".meas tran pulse_width TRIG V(sig) VAL={vcc / 2:g} RISE=1 "
            f"TARG V(sig) VAL={vcc / 2:g} FALL=2",
            ".end",
            "",
        )
    )


def _evaluate(
    measurements: dict[str, float], circuit: CircuitObject
) -> tuple[str, tuple[str, ...], dict[str, float]]:
    calc = circuit.math.calculations
    vcc = float(circuit.intent.assumptions["supply_voltage_v"])
    findings: list[str] = []
    sig_low = measurements.get("sig_low")
    sig_high = measurements.get("sig_high")
    pulse_width = measurements.get("pulse_width")
    if sig_low is None or sig_high is None or pulse_width is None:
        return (
            "failed",
            ("ngspice did not produce the expected .meas results.",),
            measurements,
        )
    if sig_low > 0.3:
        findings.append(
            f"BC547 does not saturate: signal low {sig_low:.2f}V > 0.3V."
        )
    if sig_high < vcc * 0.8:
        findings.append(
            f"Servo signal high {sig_high:.2f}V is below 80% of VCC "
            f"({vcc:g}V) into a {SERVO_INPUT_LOAD_OHMS:g} ohm load."
        )
    expected_ms = calc["reverse_servo_pulse_ms"]
    if abs(pulse_width * 1e3 - expected_ms) > 0.15 * expected_ms:
        findings.append(
            f"Servo pulse width {pulse_width * 1e3:.3f}ms deviates more "
            f"than 15% from the designed {expected_ms:g}ms."
        )
    if findings:
        return ("failed", tuple(findings), measurements)
    return ("passed", (MODEL_NOTE,), measurements)


def run_servo555_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    result = run_ngspice_batch(
        render_servo555_netlist(circuit),
        output_dir,
        netlist_filename="servo555_inverter_tran.cir",
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
