"""Transient simulation of the metal detector's Colpitts oscillator.

Two runs: the nominal coil, and the coil with its inductance reduced 4%
(the eddy-current effect of nearby metal). Checks: the oscillator actually
starts and sustains, the frequency matches the calculator within
tolerance, and the detuned run shifts the frequency UP - the detection
mechanism itself.
"""

from __future__ import annotations

import math
import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch
from pcbsmith.simulation.ngspice_buck import parse_ngspice_meas_results

SUPPORTED_TOPOLOGY_ID = "metal_detector_coil"

# Generic 2N3904-class small-signal NPN.
NPN_MODEL = (
    ".model QNPN NPN(IS=6.7e-15 BF=200 VAF=74 IKF=0.3 ISE=6.7e-15 NE=1.26 "
    "RB=10 RC=1 RE=0.2 CJE=4.5p CJC=3.6p TF=0.4n TR=21n)"
)
METAL_DETUNE_RATIO = 0.96  # metal proximity: eddy currents reduce L ~4%
FREQUENCY_TOLERANCE_RATIO = 0.10
MIN_SWING_VPP = 0.5

MODEL_NOTE = (
    "Colpitts startup transient with the nominal coil and with L reduced "
    f"to {METAL_DETUNE_RATIO:.0%} (metal proximity); the external frequency "
    "counter is NOT simulated."
)


def render_detector_netlist(circuit: CircuitObject, *, detune: float = 1.0) -> str:
    calc = circuit.math.calculations
    supply = calc["supply_voltage_v"]
    inductance = calc["coil_inductance_h"] * detune
    dcr = calc["coil_dc_resistance_ohm"]
    tank_c = calc["tank_c1_f"]
    return "\n".join(
        (
            "* Metal detector: common-base Colpitts with the PCB spiral coil",
            NPN_MODEL,
            f"VCC vcc 0 DC {supply:g}",
            f"R1 vcc base {calc['base_bias_ohms']:g}",
            f"R2 base 0 {calc['base_bias_ohms']:g}",
            "C5 base 0 100n",
            "Q1 col base em QNPN",
            f"R3 em 0 {calc['emitter_resistor_ohms']:g}",
            f"L1 vcc lx {inductance:g}",
            f"RDCR lx col {dcr:g}",
            f"C1 col em {tank_c:g}",
            f"C2 em 0 {calc['tank_c2_f']:g}",
            "C4 vcc 0 100n",
            "C3 col foa 10n",
            f"R4 foa fout {calc['output_series_ohms']:g}",
            "RLOAD fout 0 1Meg",
            f".ic v(col)={supply + 1:g}",
            ".tran 5n 100u",
            f".meas tran det_t1 when v(col)={supply:g} rise=40",
            f".meas tran det_t2 when v(col)={supply:g} rise=90",
            ".meas tran det_swing_pp PP v(col) from=60u to=100u",
            ".op",
            ".end",
            "",
        )
    )


def _measured_frequency(measures: dict[str, float]) -> float | None:
    t1, t2 = measures.get("det_t1"), measures.get("det_t2")
    if t1 is None or t2 is None or t2 <= t1:
        return None
    return 50.0 / (t2 - t1)


def run_detector_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    calc = circuit.math.calculations
    expected_hz = float(calc["oscillation_frequency_hz"])
    findings: list[str] = []
    measurements: dict[str, float] = {}
    frequencies: dict[str, float] = {}

    for label, detune in (("nominal", 1.0), ("metal", METAL_DETUNE_RATIO)):
        result = run_ngspice_batch(
            render_detector_netlist(circuit, detune=detune),
            output_dir,
            netlist_filename=f"detector_{label}.cir",
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
        measures = parse_ngspice_meas_results(result.raw_output)
        frequency = _measured_frequency(measures)
        swing = measures.get("det_swing_pp")
        if frequency is None or swing is None:
            return SimulationReport(
                backend="ngspice",
                status="failed",
                command=result.command,
                findings=(
                    f"The {label} run did not oscillate: frequency "
                    "measurement points were never reached.",
                ),
                raw_output_path=str(result.raw_output_path),
            )
        frequencies[label] = frequency
        measurements[f"{label}_frequency_hz"] = round(frequency, 1)
        measurements[f"{label}_collector_swing_vpp"] = round(swing, 4)
        if swing < MIN_SWING_VPP:
            findings.append(
                f"The {label} oscillation decays: {swing:.2f} Vpp at the "
                f"collector after 60 us (need >= {MIN_SWING_VPP:g})."
            )

    if abs(frequencies["nominal"] - expected_hz) > expected_hz * FREQUENCY_TOLERANCE_RATIO:
        findings.append(
            f"Simulated {frequencies['nominal'] / 1e6:.3f} MHz deviates from "
            f"the calculated {expected_hz / 1e6:.3f} MHz by more than "
            f"{FREQUENCY_TOLERANCE_RATIO:.0%}."
        )
    expected_shift = frequencies["nominal"] * (1 / math.sqrt(METAL_DETUNE_RATIO) - 1)
    actual_shift = frequencies["metal"] - frequencies["nominal"]
    measurements["metal_shift_hz"] = round(actual_shift, 1)
    if actual_shift <= 0:
        findings.append(
            "Metal proximity must RAISE the frequency; the detuned run "
            f"shifted it by {actual_shift:.0f} Hz."
        )
    elif abs(actual_shift - expected_shift) > expected_shift * 0.5:
        findings.append(
            f"Frequency shift {actual_shift / 1e3:.1f} kHz is far from the "
            f"expected {expected_shift / 1e3:.1f} kHz for a "
            f"{METAL_DETUNE_RATIO:.0%} inductance change."
        )

    if findings:
        return SimulationReport(
            backend="ngspice",
            status="failed",
            command=(),
            measurements=measurements,
            findings=tuple(findings),
            raw_output_path=str(output_dir / "detector_nominal.raw.log"),
        )
    return SimulationReport(
        backend="ngspice",
        status="passed",
        command=(),
        measurements=measurements,
        findings=(MODEL_NOTE,),
        raw_output_path=str(output_dir / "detector_nominal.raw.log"),
    )
