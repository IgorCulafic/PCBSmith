"""Open-loop averaged power-stage simulation for the LM2596 buck slice.

The LM2596 has no public SPICE model, so this deliberately does NOT claim to
simulate the regulator. It drives the real external power stage (catch diode,
inductor, output capacitor with ESR, load) from an ideal switch at the
datasheet switching frequency and the calculator's nominal duty cycle, then
checks that the averaged output lands on the design target with sane ripple
and inductor current. Closed-loop regulation remains unverified.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch

SUPPORTED_TOPOLOGY_ID = "lm2596_buck_regulator"

SWITCH_ON_RESISTANCE_OHMS = 0.15
DIODE_FORWARD_DROP_V = 0.45
OUTPUT_CAP_ESR_OHMS = 0.1
INDUCTOR_CURRENT_LIMIT_A = 3.0
OUTPUT_RIPPLE_LIMIT_V = 0.2
OUTPUT_AVG_TOLERANCE_RATIO = 0.12

_MEAS_RE = re.compile(
    r"^\s*(?P<name>[a-zA-Z_]\w*)\s*=\s*(?P<value>[-+]?[0-9.]+(?:[eE][-+]?\d+)?)"
)

OPEN_LOOP_NOTE = (
    "Open-loop averaged power-stage check at fixed duty cycle; LM2596 "
    "closed-loop regulation, transients, and thermals are NOT simulated "
    "(no public SPICE model)."
)


def render_lm2596_power_stage_netlist(circuit: CircuitObject) -> str:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for LM2596 power-stage rendering")
    calculations = circuit.math.calculations
    vin = calculations["input_voltage_nominal_v"]
    vout = calculations["regulated_output_v"]
    load_a = calculations["load_current_a"]
    inductance_uh = calculations["selected_inductance_uH"]
    frequency_hz = calculations["switching_frequency_hz"]

    period_s = 1.0 / frequency_hz
    switch_drop_v = load_a * SWITCH_ON_RESISTANCE_OHMS
    duty = (vout + DIODE_FORWARD_DROP_V) / (vin - switch_drop_v + DIODE_FORWARD_DROP_V)
    on_time_s = duty * period_s
    load_ohms = vout / load_a

    return f"""* LM2596 buck open-loop averaged power stage (control loop NOT modelled)
VIN vin 0 DC {vin:g}
VCTRL ctrl 0 PULSE(0 1 0 10n 10n {on_time_s:.9g} {period_s:.9g})
S1 vin sw ctrl 0 SWMOD
.model SWMOD SW(Ron={SWITCH_ON_RESISTANCE_OHMS:g} Roff=1Meg Vt=0.5)
D1 0 sw DSCHOTTKY
.model DSCHOTTKY D(Is=1e-6 Rs=0.02 N=1.2)
L1 sw out {inductance_uh:g}u
COUT out cesr 220u
RESR cesr 0 {OUTPUT_CAP_ESR_OHMS:g}
RLOAD out 0 {load_ohms:g}
.tran 0.2u 3m
.meas tran buck_vout_avg_v AVG V(out) from=2m to=3m
.meas tran buck_vout_ripple_pp_v PP V(out) from=2m to=3m
.meas tran buck_inductor_current_max_a MAX I(L1) from=2m to=3m
.end
"""


def parse_ngspice_meas_results(output: str) -> dict[str, float]:
    measurements: dict[str, float] = {}
    for line in output.splitlines():
        match = _MEAS_RE.match(line)
        if match:
            measurements[match.group("name").lower()] = float(match.group("value"))
    return measurements


def _evaluate_buck_measurements(
    measurements: dict[str, float],
    target_output_v: float,
) -> tuple[str, tuple[str, ...]]:
    required = (
        "buck_vout_avg_v",
        "buck_vout_ripple_pp_v",
        "buck_inductor_current_max_a",
    )
    missing = tuple(key for key in required if key not in measurements)
    if missing:
        return (
            "failed",
            (
                "ngspice completed, but PCBSmith could not extract required "
                f"measurements: {', '.join(missing)}.",
            ),
        )

    findings: list[str] = []
    avg = measurements["buck_vout_avg_v"]
    if abs(avg - target_output_v) > target_output_v * OUTPUT_AVG_TOLERANCE_RATIO:
        findings.append(
            f"Averaged output {avg:.3f} V is outside "
            f"{OUTPUT_AVG_TOLERANCE_RATIO:.0%} of the {target_output_v:.3f} V target."
        )
    ripple = measurements["buck_vout_ripple_pp_v"]
    if ripple > OUTPUT_RIPPLE_LIMIT_V:
        findings.append(
            f"Output ripple {ripple * 1000:.1f} mVpp exceeds the "
            f"{OUTPUT_RIPPLE_LIMIT_V * 1000:.0f} mVpp limit."
        )
    inductor_peak = measurements["buck_inductor_current_max_a"]
    if inductor_peak > INDUCTOR_CURRENT_LIMIT_A:
        findings.append(
            f"Peak inductor current {inductor_peak:.2f} A exceeds the "
            f"{INDUCTOR_CURRENT_LIMIT_A:g} A diode/inductor rating assumption."
        )
    if findings:
        return ("failed", tuple(findings))
    return ("passed", (OPEN_LOOP_NOTE,))


def run_lm2596_power_stage_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    result = run_ngspice_batch(
        render_lm2596_power_stage_netlist(circuit),
        output_dir,
        netlist_filename="lm2596_buck_power_stage.cir",
        finder=finder,
        runner=runner,
    )
    if result.status == "unavailable":
        return SimulationReport(
            backend="ngspice",
            status="unavailable",
            findings=result.findings,
            raw_output_path=str(result.raw_output_path),
        )
    if result.status == "failed":
        return SimulationReport(
            backend="ngspice",
            status="failed",
            command=result.command,
            findings=result.findings,
            raw_output_path=str(result.raw_output_path),
        )
    measurements = parse_ngspice_meas_results(result.raw_output)
    status, findings = _evaluate_buck_measurements(
        measurements,
        circuit.math.calculations["regulated_output_v"],
    )
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=result.command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(result.raw_output_path),
    )
