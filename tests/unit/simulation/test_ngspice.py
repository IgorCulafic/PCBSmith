from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.simulation.ngspice import find_ngspice, render_ngspice_netlist, run_ngspice_simulation


def _circuit():
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    return compose_divider_highpass_led(intent, select_topology(intent))


def test_renders_netlist_with_ac_analysis_and_measurements() -> None:
    netlist = render_ngspice_netlist(_circuit())

    assert "V1 VIN 0 DC 5 AC 1" in netlist
    assert "R1 VIN DIV_OUT 10000" in netlist
    assert "C1 DIV_OUT HP_OUT 100n" in netlist
    assert ".ac dec 20 10 100k" in netlist
    assert ".print ac v(HP_OUT)" in netlist


def test_reports_unavailable_when_ngspice_missing(tmp_path: Path) -> None:
    report = run_ngspice_simulation(
        _circuit(),
        tmp_path,
        finder=lambda: None,
    )

    assert report.status == "unavailable"
    assert report.findings == (
        "ngspice executable was not found; set PCBSMITH_NGSPICE or install standalone ngspice before claiming simulation evidence.",
    )


def test_find_ngspice_uses_environment_override(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "ngspice_con.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("PCBSMITH_NGSPICE", str(executable))

    assert find_ngspice() == executable
