from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_NODE_VOLTAGE_RE = re.compile(
    rf"^\s*(?P<node>vin|div_out|hp_out|led_a)\s+(?P<value>{_NUMBER})\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_AC_HP_OUT_RE = re.compile(
    rf"^\s*\d+\s+(?P<frequency>{_NUMBER})\s+"
    rf"(?P<real>{_NUMBER}),\s*(?P<imag>{_NUMBER})\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_REQUIRED_MEASUREMENTS = (
    "op_div_out_v",
    "op_hp_out_v",
    "op_vin_v",
    "ac_hp_out_10_hz_mag_v",
    "ac_hp_out_1khz_mag_v",
    "ac_hp_out_100khz_mag_v",
)


def find_ngspice() -> Path | None:
    env_path = os.environ.get("PCBSMITH_NGSPICE")
    if env_path:
        configured_env_path = Path(env_path)
        if configured_env_path.exists():
            return configured_env_path
    configured = Path("D:/AI/PCB designer/Spice64/bin/ngspice_con.exe")
    if configured.exists():
        return configured
    path = shutil.which("ngspice_con") or shutil.which("ngspice")
    return Path(path) if path else None


def render_ngspice_netlist(circuit: CircuitObject) -> str:
    if circuit.topology.topology_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported circuit for ngspice rendering")
    return """* PCBSmith divider + high-pass + LED indicator vertical slice
V1 VIN 0 DC 5 AC 1
R1 VIN DIV_OUT 10000
R2 DIV_OUT 0 10000
C1 DIV_OUT HP_OUT 100n
RLOAD HP_OUT 0 10000
R3 HP_OUT LED_A 680
D1 LED_A 0 DRED
.model DRED D(IS=1e-14 N=2 RS=10 CJO=2p)
.op
.ac dec 20 10 100k
.print ac v(HP_OUT)
.end
"""


def extract_ngspice_measurements(output: str) -> dict[str, float]:
    measurements: dict[str, float] = {}
    for match in _NODE_VOLTAGE_RE.finditer(output):
        node = match.group("node").lower()
        measurements[f"op_{node}_v"] = float(match.group("value"))

    rows = [
        (
            float(match.group("frequency")),
            float(match.group("real")),
            float(match.group("imag")),
        )
        for match in _AC_HP_OUT_RE.finditer(output)
    ]
    for label, target_frequency in (
        ("10_hz", 10.0),
        ("100_hz", 100.0),
        ("1khz", 1_000.0),
        ("100khz", 100_000.0),
    ):
        selected = _closest_ac_row(rows, target_frequency)
        if selected is None:
            continue
        _frequency, real, imag = selected
        measurements[f"ac_hp_out_{label}_real_v"] = real
        measurements[f"ac_hp_out_{label}_imag_v"] = imag
        measurements[f"ac_hp_out_{label}_mag_v"] = math.hypot(real, imag)
    return measurements


def _closest_ac_row(
    rows: Sequence[tuple[float, float, float]],
    target_frequency: float,
) -> tuple[float, float, float] | None:
    if not rows:
        return None
    selected = min(rows, key=lambda row: abs(row[0] - target_frequency) / target_frequency)
    if abs(selected[0] - target_frequency) / target_frequency > 0.01:
        return None
    return selected


def _evaluate_measurements(measurements: dict[str, float]) -> tuple[str, tuple[str, ...]]:
    missing = tuple(key for key in _REQUIRED_MEASUREMENTS if key not in measurements)
    if missing:
        return (
            "failed",
            (
                "ngspice completed, but PCBSmith could not extract required "
                f"measurements: {', '.join(missing)}.",
            ),
        )

    findings: list[str] = []
    if not math.isclose(measurements["op_vin_v"], 5.0, rel_tol=0.0, abs_tol=0.01):
        findings.append("ngspice DC operating point did not preserve the expected 5 V input.")
    if not math.isclose(measurements["op_div_out_v"], 2.5, rel_tol=0.0, abs_tol=0.05):
        findings.append(
            "ngspice DC operating point did not show the expected 2.5 V divider output."
        )
    if abs(measurements["op_hp_out_v"]) > 0.001:
        findings.append(
            "ngspice DC operating point did not block DC through the high-pass capacitor."
        )
    if measurements["ac_hp_out_1khz_mag_v"] <= measurements["ac_hp_out_10_hz_mag_v"]:
        findings.append(
            "ngspice AC response did not rise from 10 Hz to 1 kHz as a high-pass should."
        )
    if not (0.30 <= measurements["ac_hp_out_100khz_mag_v"] <= 0.36):
        findings.append(
            "ngspice AC high-frequency gain was outside the expected divider/load range."
        )
    return ("failed", tuple(findings)) if findings else ("passed", ())


def run_ngspice_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    executable = finder()
    netlist_path = output_dir / ".pcbsmith" / "simulation" / "divider_highpass_led.cir"
    output_path = output_dir / ".pcbsmith" / "simulation" / "ngspice-output.txt"
    netlist_path.parent.mkdir(parents=True, exist_ok=True)
    netlist_path.write_text(render_ngspice_netlist(circuit), encoding="utf-8")
    if executable is None:
        return SimulationReport(
            backend="ngspice",
            status="unavailable",
            findings=(
                "ngspice executable was not found; set PCBSMITH_NGSPICE or install "
                "standalone ngspice before claiming simulation evidence.",
            ),
            raw_output_path=str(output_path),
        )
    command = (str(executable), "-b", str(netlist_path))
    completed = runner(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    output_path.write_text(output, encoding="utf-8")
    if completed.returncode != 0:
        return SimulationReport(
            backend="ngspice",
            status="failed",
            command=command,
            findings=(f"ngspice exited with code {completed.returncode}.",),
            raw_output_path=str(output_path),
        )
    measurements = extract_ngspice_measurements(output)
    status, findings = _evaluate_measurements(measurements)
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(output_path),
    )
