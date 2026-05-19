from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.circuit.models import KiCadReport
from pcbsmith.kicad.cli import (
    KiCadInstall,
    KiCadProcessResult,
    find_kicad_cli,
    run_kicad_process,
)


def export_kicad_spice_netlist(
    schematic_file: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> KiCadReport:
    netlist_file = (
        schematic_file.parent / ".pcbsmith" / "kicad" / f"{schematic_file.stem}.cir"
    )
    install = finder()
    if install is None:
        return KiCadReport(
            status="unavailable",
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
            findings=("KiCad CLI was not found; SPICE netlist export was not run.",),
        )

    command = (
        str(install.path),
        "sch",
        "export",
        "netlist",
        "--format",
        "spice",
        "--output",
        str(netlist_file),
        str(schematic_file),
    )
    netlist_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        process = run_kicad_process(command) if runner is None else runner(command)
    except OSError as exc:
        return KiCadReport(
            status="failed",
            command=command,
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
            findings=(f"KiCad SPICE netlist export could not run: {exc}",),
        )

    if process.returncode != 0:
        return KiCadReport(
            status="failed",
            command=process.command,
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
            findings=(_process_failure_finding(process),),
        )

    if not netlist_file.exists() or not netlist_file.read_text(encoding="utf-8").strip():
        return KiCadReport(
            status="failed",
            command=process.command,
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
            findings=(
                "KiCad SPICE netlist export did not produce a non-empty file.",
            ),
        )

    return KiCadReport(
        status="passed",
        command=process.command,
        schematic_file=str(schematic_file),
        spice_netlist=str(netlist_file),
    )


def _process_failure_finding(process: KiCadProcessResult) -> str:
    return (
        process.stderr.strip()
        or process.stdout.strip()
        or "KiCad SPICE netlist export failed."
    )
