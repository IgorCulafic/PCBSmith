"""Operating-point simulation for the pear's LED rings.

Each ring net is modelled as an ideal supply (the drive contract: rings are
switched externally at the supply voltage); every branch is its series
resistor plus the fitted green-LED diode. The check: every branch carries
the design current within tolerance, and the per-ring totals match the
findings given to the user.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.kicad.pear_board import ring_unit_counts
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch
from pcbsmith.simulation.ngspice_clover import GREEN_LED_MODEL
from pcbsmith.simulation.ngspice_mpu6050 import parse_operating_point

SUPPORTED_TOPOLOGY_ID = "pear_led_rings"

LED_CURRENT_TOLERANCE_RATIO = 0.35

MODEL_NOTE = (
    "All ring branches biased at the supply voltage per the drive contract; "
    "the external ring driver is NOT simulated."
)


def render_pear_netlist(circuit: CircuitObject) -> str:
    calc = circuit.math.calculations
    supply = calc["supply_voltage_v"]
    led_r = calc["led_selected_resistor_ohms"]
    lines = [
        "* Pear LED rings: every branch biased at the drive voltage",
        GREEN_LED_MODEL,
    ]
    unit = 0
    for ring, count in enumerate(ring_unit_counts()):
        lines.append(f"VL{ring + 1} l{ring + 1} 0 DC {supply:g}")
        for _ in range(count):
            unit += 1
            lines.extend(
                (
                    f"R_{unit} l{ring + 1} a_{unit} {led_r:g}",
                    f"D_{unit} a_{unit} 0 DGREEN",
                )
            )
    lines.extend((".op", ".end", ""))
    return "\n".join(lines)


def _evaluate(
    values: dict[str, float],
    circuit: CircuitObject,
) -> tuple[str, tuple[str, ...], dict[str, float]]:
    calc = circuit.math.calculations
    supply = calc["supply_voltage_v"]
    led_r = calc["led_selected_resistor_ohms"]
    target = calc["led_current_a"]
    findings: list[str] = []
    measurements: dict[str, float] = {}
    unit = 0
    for ring, count in enumerate(ring_unit_counts()):
        ring_total = 0.0
        for _ in range(count):
            unit += 1
            anode = values.get(f"a_{unit}")
            if anode is None:
                return ("failed", (f"Branch node a_{unit} missing.",), measurements)
            current = (supply - anode) / led_r
            ring_total += current
            if abs(current - target) > target * LED_CURRENT_TOLERANCE_RATIO:
                findings.append(
                    f"Branch D{unit} current {current * 1000:.2f} mA is outside "
                    f"{LED_CURRENT_TOLERANCE_RATIO:.0%} of the "
                    f"{target * 1000:.1f} mA design point."
                )
        measurements[f"ring{ring + 1}_total_current_a"] = round(ring_total, 5)
        expected = calc[f"ring{ring + 1}_current_a"]
        if abs(ring_total - expected) > expected * 0.1:
            findings.append(
                f"Ring {ring + 1} total {ring_total * 1000:.1f} mA deviates "
                f"from the stated {expected * 1000:.1f} mA."
            )
    if findings:
        return ("failed", tuple(findings), measurements)
    return ("passed", (MODEL_NOTE,), measurements)


def run_pear_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    result = run_ngspice_batch(
        render_pear_netlist(circuit),
        output_dir,
        netlist_filename="pear_operating_point.cir",
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
