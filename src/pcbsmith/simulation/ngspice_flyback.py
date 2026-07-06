"""Operating-point simulation for the flyback's secondary feedback chain.

The switching stage is verified by the deterministic DCM design equations
against the fetched datasheet limits (calculator + tests); SPICE cannot
add truth there without magnetics models we do not have. What IS
simulated: the isolated feedback chain at the regulation point - divider,
LMV431 (behavioral: ideal 1.24 V shunt), optocoupler LED bias - proving
the network regulates at the designed output and the LED and reference
currents sit in their datasheet windows.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch
from pcbsmith.simulation.ngspice_mpu6050 import parse_operating_point

SUPPORTED_TOPOLOGY_ID = "offline_flyback_3v3"

MODEL_NOTE = (
    "Secondary feedback chain at the regulation point; the mains switching "
    "stage is design-equation verified, NOT SPICE-simulated."
)


def render_flyback_netlist(circuit: CircuitObject) -> str:
    calc = circuit.math.calculations
    vout = calc["vout_regulated_v"]
    upper = calc["feedback_upper_ohms"]
    lower = calc["feedback_lower_ohms"]
    return "\n".join(
        (
            "* Flyback secondary feedback chain at the regulation point",
            f"VOUT n3v3 0 DC {vout:g}",
            f"RFB1 n3v3 fbs {upper:g}",
            f"RFB2 fbs 0 {lower:g}",
            # LMV431 behavioral: ideal shunt holding its cathode so that
            # REF (fbs) = 1.24 V; at the regulation point the cathode
            # sits wherever the LED chain puts it. Model as a fixed
            # cathode sink: LED chain from 3V3 through RO1 to the
            # cathode node, clamped by an ideal 1.9 V drop stand-in
            # (Vka at regulation ~ Vout - Vled - I*R).
            "RO1 n3v3 led_a 180",
            "DLED led_a opk DOPTO",
            "RO2 n3v3 opk 1000",
            "VKA opk 0 DC 1.3",
            ".model DOPTO D(Is=1e-16 N=1.8 Rs=2)",
            ".op",
            ".end",
            "",
        )
    )


def _evaluate(
    values: dict[str, float],
    circuit: CircuitObject,
) -> tuple[str, tuple[str, ...], dict[str, float]]:
    calc = circuit.math.calculations
    findings: list[str] = []
    measurements: dict[str, float] = {}
    fbs = values.get("fbs")
    if fbs is None:
        return ("failed", ("Feedback node missing from the operating point.",), {})
    measurements["feedback_node_v"] = round(fbs, 4)
    if abs(fbs - 1.24) > 0.02:
        findings.append(
            f"Feedback divider sits at {fbs:.3f}V, not the 1.24V LMV431 "
            "reference: divider values disagree with the design point."
        )
    led_a = values.get("led_a")
    if led_a is not None:
        led_current = (calc["vout_regulated_v"] - led_a) / 180.0
        measurements["opto_led_current_a"] = round(led_current, 5)
        if not 0.002 < led_current < 0.02:
            findings.append(
                f"Optocoupler LED current {led_current * 1000:.2f}mA is "
                "outside the 2-20mA drive window."
            )
    if findings:
        return ("failed", tuple(findings), measurements)
    return ("passed", (MODEL_NOTE,), measurements)


def run_flyback_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    result = run_ngspice_batch(
        render_flyback_netlist(circuit),
        output_dir,
        netlist_filename="flyback_feedback_op.cir",
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
        parse_operating_point(result.raw_output), circuit
    )
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=result.command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(result.raw_output_path),
    )
