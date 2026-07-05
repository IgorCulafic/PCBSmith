"""Operating-point simulation for the MPU-6050 breakout's passive network.

The MEMS core and digital interface have no SPICE model, so this simulates
only what is honestly simulatable: the I2C bus conditioning. With the bus
idle the pullups must hold SDA/SCL at the supply and AD0 must sit at ground,
with no static current path.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.simulation.ngspice import find_ngspice, run_ngspice_batch

SUPPORTED_TOPOLOGY_ID = "mpu6050_imu"

IDLE_VOLTAGE_TOLERANCE_V = 0.01
IDLE_CURRENT_LIMIT_A = 1e-6

MODEL_NOTE = (
    "Idle-bus operating point only: the MPU-6050 MEMS core and digital "
    "interface have no SPICE model (datasheet current 3.6 mA is a review "
    "item, not a simulated result)."
)

_NODE_RE = re.compile(
    r"^\s*(?P<name>[a-z_][\w#]*)\s+(?P<value>[-+]?[0-9.]+(?:[eE][-+]?\d+)?)\s*$",
    re.MULTILINE,
)


def render_mpu6050_netlist(circuit: CircuitObject) -> str:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for MPU-6050 netlist rendering")
    calculations = circuit.math.calculations
    supply = calculations["supply_voltage_v"]
    pullup = calculations["i2c_pullup_selected_ohms"]
    return f"""* MPU-6050 breakout idle I2C bus operating point (sensor core NOT modelled)
V1 vdd 0 DC {supply:g}
RSDA vdd sda {pullup:g}
RSCL vdd scl {pullup:g}
RAD0 ad0 0 {pullup:g}
* Bus leakage stand-ins keep the idle nodes defined without loading them.
RLEAKSDA sda 0 100Meg
RLEAKSCL scl 0 100Meg
.op
.end
"""


def parse_operating_point(output: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for match in _NODE_RE.finditer(output):
        values[match.group("name").lower()] = float(match.group("value"))
    return values


def _evaluate(
    values: dict[str, float],
    supply: float,
) -> tuple[str, tuple[str, ...], dict[str, float]]:
    required = ("sda", "scl", "ad0")
    missing = tuple(key for key in required if key not in values)
    if missing:
        return (
            "failed",
            (
                "ngspice completed, but PCBSmith could not extract node "
                f"voltages: {', '.join(missing)}.",
            ),
            {},
        )
    measurements = {
        "i2c_sda_idle_v": values["sda"],
        "i2c_scl_idle_v": values["scl"],
        "ad0_idle_v": values["ad0"],
        "supply_current_a": abs(values.get("v1#branch", 0.0)),
    }
    findings: list[str] = []
    for name in ("i2c_sda_idle_v", "i2c_scl_idle_v"):
        if abs(measurements[name] - supply) > IDLE_VOLTAGE_TOLERANCE_V:
            findings.append(
                f"{name} is {measurements[name]:.3f} V; the idle bus must sit "
                f"at the {supply:g} V supply."
            )
    if abs(measurements["ad0_idle_v"]) > IDLE_VOLTAGE_TOLERANCE_V:
        findings.append(
            f"AD0 idles at {measurements['ad0_idle_v']:.3f} V; the address "
            "select must rest at ground (address 0x68)."
        )
    if measurements["supply_current_a"] > IDLE_CURRENT_LIMIT_A:
        findings.append(
            f"Idle supply current {measurements['supply_current_a']:.2e} A "
            "indicates an unintended static path in the passive network."
        )
    if findings:
        return ("failed", tuple(findings), measurements)
    return ("passed", (MODEL_NOTE,), measurements)


def run_mpu6050_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    result = run_ngspice_batch(
        render_mpu6050_netlist(circuit),
        output_dir,
        netlist_filename="mpu6050_idle_bus.cir",
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
    status, findings, measurements = _evaluate(
        parse_operating_point(result.raw_output),
        circuit.math.calculations["supply_voltage_v"],
    )
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=result.command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(result.raw_output_path),
    )
