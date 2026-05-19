from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pcbsmith.circuit.models import CircuitObject, SimulationReport

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_NODE_ROW_RE = re.compile(rf"^\s*(?P<node>\S+)\s+(?P<value>{_NUMBER})\s*$")
_AC_HEADER_RE = re.compile(r"^\s*Index\s+frequency\s+(?P<columns>.+?)\s*$", re.IGNORECASE)
_AC_ROW_START_RE = re.compile(r"^\s*\d+\s+")
_REQUIRED_MEASUREMENTS = (
    "op_div_out_v",
    "op_hp_out_v",
    "op_vin_v",
    "ac_hp_out_10_hz_mag_v",
    "ac_hp_out_1khz_mag_v",
    "ac_hp_out_100khz_mag_v",
)


@dataclass(frozen=True)
class NgspiceAcPoint:
    frequency_hz: float
    values: dict[str, float | complex]


@dataclass(frozen=True)
class NgspiceOutput:
    operating_point_voltages: dict[str, float]
    ac_points: tuple[NgspiceAcPoint, ...]


@dataclass(frozen=True)
class NgspiceBatchResult:
    status: Literal["completed", "failed", "unavailable"]
    command: tuple[str, ...]
    netlist_path: Path
    raw_output_path: Path
    raw_output: str
    parsed_output: NgspiceOutput
    findings: tuple[str, ...] = ()


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


def run_ngspice_batch(
    netlist_text: str,
    output_dir: Path,
    *,
    netlist_filename: str,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> NgspiceBatchResult:
    executable = finder()
    simulation_dir = output_dir / ".pcbsmith" / "simulation"
    netlist_path = simulation_dir / netlist_filename
    output_path = simulation_dir / f"{Path(netlist_filename).stem}-ngspice-output.txt"
    simulation_dir.mkdir(parents=True, exist_ok=True)
    netlist_path.write_text(netlist_text, encoding="utf-8")
    if executable is None:
        return NgspiceBatchResult(
            status="unavailable",
            command=(),
            netlist_path=netlist_path,
            raw_output_path=output_path,
            raw_output="",
            parsed_output=NgspiceOutput(operating_point_voltages={}, ac_points=()),
            findings=(
                "ngspice executable was not found; set PCBSMITH_NGSPICE or install "
                "standalone ngspice before claiming simulation evidence.",
            ),
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
        return NgspiceBatchResult(
            status="failed",
            command=command,
            netlist_path=netlist_path,
            raw_output_path=output_path,
            raw_output=output,
            parsed_output=parse_ngspice_output(output),
            findings=(f"ngspice exited with code {completed.returncode}.",),
        )
    return NgspiceBatchResult(
        status="completed",
        command=command,
        netlist_path=netlist_path,
        raw_output_path=output_path,
        raw_output=output,
        parsed_output=parse_ngspice_output(output),
    )


def parse_ngspice_output(output: str) -> NgspiceOutput:
    return NgspiceOutput(
        operating_point_voltages=_parse_operating_point_voltages(output),
        ac_points=_parse_ac_points(output),
    )


def ac_value_at(
    parsed_output: NgspiceOutput,
    expression: str,
    target_frequency_hz: float,
    *,
    tolerance: float = 0.01,
) -> float | complex | None:
    expression_key = expression.lower()
    candidates = [
        point
        for point in parsed_output.ac_points
        if expression_key in point.values
        and abs(point.frequency_hz - target_frequency_hz) / target_frequency_hz <= tolerance
    ]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda point: abs(point.frequency_hz - target_frequency_hz) / target_frequency_hz,
    )
    return selected.values[expression_key]


def extract_ngspice_measurements(output: str) -> dict[str, float]:
    measurements: dict[str, float] = {}
    parsed_output = parse_ngspice_output(output)
    for node, voltage in parsed_output.operating_point_voltages.items():
        measurements[f"op_{_measurement_key(node)}_v"] = voltage

    for label, target_frequency in (
        ("10_hz", 10.0),
        ("100_hz", 100.0),
        ("1khz", 1_000.0),
        ("100khz", 100_000.0),
    ):
        value = ac_value_at(parsed_output, "v(hp_out)", target_frequency)
        if value is None:
            value = ac_value_at(parsed_output, "vm(hp_out)", target_frequency)
        if value is None:
            continue
        if isinstance(value, complex):
            measurements[f"ac_hp_out_{label}_real_v"] = value.real
            measurements[f"ac_hp_out_{label}_imag_v"] = value.imag
            measurements[f"ac_hp_out_{label}_mag_v"] = abs(value)
        else:
            measurements[f"ac_hp_out_{label}_mag_v"] = value
    return measurements


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
    result = run_ngspice_batch(
        render_ngspice_netlist(circuit),
        output_dir,
        netlist_filename="divider_highpass_led.cir",
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
    measurements = extract_ngspice_measurements(result.raw_output)
    status, findings = _evaluate_measurements(measurements)
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=result.command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(result.raw_output_path),
    )


def run_ngspice_netlist_file(
    netlist_path: Path,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    try:
        netlist_text = netlist_path.read_text(encoding="utf-8")
    except OSError as exc:
        reason = exc.strerror or str(exc)
        return SimulationReport(
            backend="ngspice",
            status="failed",
            findings=(
                f"ngspice netlist file could not be read: {netlist_path} ({reason})",
            ),
        )
    if not netlist_text.strip():
        return SimulationReport(
            backend="ngspice",
            status="failed",
            findings=(f"ngspice netlist file is empty: {netlist_path}",),
        )

    result = run_ngspice_batch(
        netlist_text,
        output_dir,
        netlist_filename=netlist_path.name,
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
    measurements = extract_ngspice_measurements(result.raw_output)
    status, findings = _evaluate_measurements(measurements)
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=result.command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(result.raw_output_path),
    )


def _parse_operating_point_voltages(output: str) -> dict[str, float]:
    voltages: dict[str, float] = {}
    in_node_table = False
    for line in output.splitlines():
        if re.search(r"\bNode\b", line, re.IGNORECASE) and re.search(
            r"\bVoltage\b",
            line,
            re.IGNORECASE,
        ):
            in_node_table = True
            continue
        if not in_node_table:
            continue
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("source"):
            break
        if set(stripped) <= {"-", "\t"}:
            continue
        match = _NODE_ROW_RE.match(line)
        if match:
            voltages[match.group("node").lower()] = float(match.group("value"))
    return voltages


def _parse_ac_points(output: str) -> tuple[NgspiceAcPoint, ...]:
    points: list[NgspiceAcPoint] = []
    active_columns: tuple[str, ...] = ()
    for line in output.splitlines():
        header = _AC_HEADER_RE.match(line.lstrip("\f"))
        if header:
            active_columns = tuple(column.lower() for column in header.group("columns").split())
            continue
        if not active_columns or not _AC_ROW_START_RE.match(line):
            continue
        point = _parse_ac_row(line, active_columns)
        if point is not None:
            points.append(point)
    return tuple(points)


def _parse_ac_row(line: str, columns: Sequence[str]) -> NgspiceAcPoint | None:
    tokens = line.strip().split()
    if len(tokens) < 3:
        return None
    try:
        frequency = float(tokens[1])
    except ValueError:
        return None

    values: dict[str, float | complex] = {}
    index = 2
    for column in columns:
        if index >= len(tokens):
            return None
        token = tokens[index]
        if token.endswith(","):
            if index + 1 >= len(tokens):
                return None
            values[column] = complex(float(token.rstrip(",")), float(tokens[index + 1]))
            index += 2
        else:
            values[column] = float(token)
            index += 1
    return NgspiceAcPoint(frequency_hz=frequency, values=values)


def _measurement_key(name: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return key or "unnamed"
