from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport


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


def run_ngspice_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
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
    command = (str(executable), "-b", "-o", str(output_path), str(netlist_path))
    completed = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout or completed.stderr:
        output_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return SimulationReport(
            backend="ngspice",
            status="failed",
            command=command,
            findings=(f"ngspice exited with code {completed.returncode}.",),
            raw_output_path=str(output_path),
        )
    return SimulationReport(
        backend="ngspice",
        status="warning",
        command=command,
        findings=(
            "ngspice ran, but this slice only records execution status; measured "
            "pass/fail thresholds are not yet implemented.",
        ),
        raw_output_path=str(output_path),
    )
