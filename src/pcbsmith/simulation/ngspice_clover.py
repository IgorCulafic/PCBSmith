"""Operating-point simulation for the clover's passive network.

Simulates what is honest: the I2C bus conditioning and the four LED branches
driven high (each MCU pin modelled as an ideal 3.3 V source, the datasheet
condition for the 5 mA IOL characterization). The MCU program and the MEMS
sensor are not simulatable and are flagged as findings elsewhere.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch
from pcbsmith.simulation.ngspice_mpu6050 import parse_operating_point

SUPPORTED_TOPOLOGY_ID = "clover_tilt_indicator"

# Diode fit for a green LED: 2.2 V at 5 mA.
GREEN_LED_MODEL = ".model DGREEN D(Is=2e-18 N=2.4 Rs=1)"
LED_CURRENT_TOLERANCE_RATIO = 0.35

MODEL_NOTE = (
    "Idle I2C bus plus per-leaf LED bias at the characterized 5 mA drive; "
    "the MCU program and MEMS sensor are NOT simulated."
)


def render_clover_netlist(circuit: CircuitObject) -> str:
    calc = circuit.math.calculations
    supply = calc["supply_voltage_v"]
    pullup = calc["i2c_pullup_selected_ohms"]
    led_r = calc["led_selected_resistor_ohms"]
    lines = [
        "* Clover tilt indicator: idle bus + leaf LED branches",
        f"V1 vdd 0 DC {supply:g}",
        f"RSDA vdd sda {pullup:g}",
        f"RSCL vdd scl {pullup:g}",
        "RLEAKSDA sda 0 100Meg",
        "RLEAKSCL scl 0 100Meg",
        GREEN_LED_MODEL,
    ]
    for leaf in ("ne", "nw", "sw", "se"):
        lines.extend(
            (
                f"VDRV_{leaf} drv_{leaf} 0 DC {supply:g}",
                f"R_{leaf} drv_{leaf} a_{leaf} {led_r:g}",
                f"D_{leaf} a_{leaf} 0 DGREEN",
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
    for name in ("sda", "scl"):
        if name not in values:
            return ("failed", (f"Node {name} missing from the operating point.",), {})
        measurements[f"i2c_{name}_idle_v"] = values[name]
        if abs(values[name] - supply) > 0.01:
            findings.append(f"{name.upper()} idles at {values[name]:.3f} V, not {supply:g} V.")
    for leaf in ("ne", "nw", "sw", "se"):
        anode = values.get(f"a_{leaf}")
        if anode is None:
            return ("failed", (f"Leaf node a_{leaf} missing.",), measurements)
        current = (supply - anode) / led_r
        measurements[f"leaf_{leaf}_led_current_a"] = round(current, 6)
        if abs(current - target) > target * LED_CURRENT_TOLERANCE_RATIO:
            findings.append(
                f"Leaf {leaf.upper()} LED current {current * 1000:.2f} mA is "
                f"outside {LED_CURRENT_TOLERANCE_RATIO:.0%} of the "
                f"{target * 1000:.1f} mA design point."
            )
    if findings:
        return ("failed", tuple(findings), measurements)
    return ("passed", (MODEL_NOTE,), measurements)


def run_clover_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    result = run_ngspice_batch(
        render_clover_netlist(circuit),
        output_dir,
        netlist_filename="clover_operating_point.cir",
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
