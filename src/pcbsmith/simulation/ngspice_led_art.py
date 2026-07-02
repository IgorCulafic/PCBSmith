"""Operating-point simulation for the LED text-matrix topology.

Every string is netlisted against a diode model fitted to the datasheet
forward voltage (1.85 V at 10 mA), and the supply operating point is checked:
the total supply current must land near the sum of the per-string design
currents. Brightness matching and forward-voltage spread are not simulated.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.generation.led_art import LedArtPlan
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch

SUPPORTED_TOPOLOGY_ID = "led_text_matrix"

# Diode-equation fit to the extracted Kingbright VF fact: 1.85 V at 10 mA.
LED_MODEL = ".model DLED D(Is=4.3e-19 N=1.9 Rs=0.5)"
TOTAL_CURRENT_TOLERANCE_RATIO = 0.3

_BRANCH_RE = re.compile(
    r"^\s*v1#branch\s+(?P<value>[-+]?[0-9.]+(?:[eE][-+]?\d+)?)\s*$",
    re.MULTILINE,
)

MODEL_NOTE = (
    "Operating-point check with a diode model fitted to the datasheet VF; "
    "forward-voltage spread and brightness matching are NOT simulated."
)


def render_led_art_netlist(circuit: CircuitObject, plan: LedArtPlan) -> str:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for LED art netlist rendering")
    supply_v = circuit.math.calculations["supply_voltage_v"]
    lines = [
        "* LED text matrix operating point (one series string per glyph column)",
        f"V1 vin 0 DC {supply_v:g}",
        LED_MODEL,
    ]
    for index, string in enumerate(plan.strings, start=1):
        node = f"s{index}_0"
        lines.append(f"R{index} vin {node} {string.resistor_ohms:g}")
        for position, led_ref in enumerate(string.led_refs, start=1):
            next_node = (
                "0" if position == len(string.led_refs) else f"s{index}_{position}"
            )
            lines.append(f"D{led_ref} {node} {next_node} DLED")
            node = next_node
    lines.extend((".op", ".end", ""))
    return "\n".join(lines)


def parse_supply_current_a(output: str) -> float | None:
    match = _BRANCH_RE.search(output)
    if match is None:
        return None
    # The source branch current is negative for current flowing out of V1.
    return abs(float(match.group("value")))


def _evaluate_operating_point(
    supply_current_a: float | None,
    expected_current_a: float,
) -> tuple[str, tuple[str, ...], dict[str, float]]:
    if supply_current_a is None:
        return (
            "failed",
            (
                "ngspice completed, but PCBSmith could not extract the supply "
                "branch current (v1#branch) from the operating point.",
            ),
            {},
        )
    measurements = {
        "led_art_supply_current_a": supply_current_a,
        "led_art_expected_current_a": expected_current_a,
    }
    deviation = abs(supply_current_a - expected_current_a)
    if deviation > expected_current_a * TOTAL_CURRENT_TOLERANCE_RATIO:
        return (
            "failed",
            (
                f"Simulated supply current {supply_current_a * 1000:.1f} mA is "
                f"outside {TOTAL_CURRENT_TOLERANCE_RATIO:.0%} of the "
                f"{expected_current_a * 1000:.1f} mA design total.",
            ),
            measurements,
        )
    return ("passed", (MODEL_NOTE,), measurements)


def run_led_art_simulation(
    circuit: CircuitObject,
    plan: LedArtPlan,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    result = run_ngspice_batch(
        render_led_art_netlist(circuit, plan),
        output_dir,
        netlist_filename="led_art_operating_point.cir",
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
    status, findings, measurements = _evaluate_operating_point(
        parse_supply_current_a(result.raw_output),
        circuit.math.calculations["total_supply_current_a"],
    )
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=result.command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(result.raw_output_path),
    )
