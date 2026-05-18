from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.core.netops import derive_netlist
from pcbsmith.generation.divider_highpass_led import (
    compose_divider_highpass_led,
    write_divider_highpass_led_project,
)
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.services.erc import run_erc
from pcbsmith.services.project_io import load_project, load_schematic


def test_composes_circuit_object_with_explicit_roles_and_math() -> None:
    intent = classify_circuit_intent(
        "Generate a voltage divider connected to a high-pass filter and LED indicator"
    )
    topology = select_topology(intent)

    circuit = compose_divider_highpass_led(intent, topology)

    assert circuit.math.status == "warning"
    assert circuit.math.calculations["divider_output_voltage_v"] == 2.5
    assert circuit.math.calculations["highpass_cutoff_hz"] == 159.155
    assert [component.reference for component in circuit.components] == [
        "R1",
        "R2",
        "C1",
        "R3",
        "D1",
    ]
    assert "LED after AC coupling is signal-dependent" in circuit.math.findings[0]


def test_writes_schematic_first_project_that_passes_pcbs_erc(tmp_path: Path) -> None:
    intent = classify_circuit_intent(
        "Generate a voltage divider connected to a high-pass filter and LED indicator"
    )
    circuit = compose_divider_highpass_led(intent, select_topology(intent))

    write_divider_highpass_led_project(circuit, tmp_path, project_name="Slice")

    project = load_project(tmp_path)
    schematic = load_schematic(tmp_path, project.schematics[0])
    issues = run_erc(schematic, SYMBOLS)
    netlist = derive_netlist(schematic, SYMBOLS)

    assert project.name == "Slice"
    assert [symbol.reference for symbol in schematic.symbols] == [
        "P1",
        "R1",
        "R2",
        "C1",
        "RLOAD",
        "R3",
        "D1",
        "GND1",
    ]
    assert {net.name for net in netlist.nets} >= {"VIN", "DIV_OUT", "HP_OUT", "GND"}
    assert issues == []
