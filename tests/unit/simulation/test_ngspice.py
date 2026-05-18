from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.simulation.ngspice import (
    extract_ngspice_measurements,
    find_ngspice,
    render_ngspice_netlist,
    run_ngspice_simulation,
)

NGSPICE_SAMPLE_OUTPUT = """
	Node                                  Voltage
	----                                  -------
	led_a                            2.295785e-24
	hp_out                           2.149611e-24
	div_out                          2.500000e+00
	vin                              5.000000e+00

Index   frequency       v(hp_out)
--------------------------------------------------------------------------------
0	1.000000e+01	2.934851e-03,	3.113932e-02
20	1.000000e+02	1.568052e-01,	1.663726e-01
40	1.000000e+03	3.296211e-01,	3.495961e-02
80	1.000000e+05	3.333244e-01,	-1.04254e-03
"""


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
        "ngspice executable was not found; set PCBSMITH_NGSPICE or install "
        "standalone ngspice before claiming simulation evidence.",
    )


def test_extracts_dc_and_ac_measurements_from_ngspice_output() -> None:
    measurements = extract_ngspice_measurements(NGSPICE_SAMPLE_OUTPUT)

    assert measurements["op_vin_v"] == 5.0
    assert measurements["op_div_out_v"] == 2.5
    assert measurements["op_hp_out_v"] == 2.149611e-24
    assert measurements["ac_hp_out_10_hz_mag_v"] == pytest.approx(0.03127731766719456)
    assert measurements["ac_hp_out_1khz_mag_v"] == pytest.approx(0.3314698235082073)
    assert measurements["ac_hp_out_100khz_mag_v"] == pytest.approx(0.3333260303899174)


def test_run_ngspice_captures_stdout_measurements_and_checks_them(tmp_path: Path) -> None:
    def fake_runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=NGSPICE_SAMPLE_OUTPUT, stderr="")

    report = run_ngspice_simulation(
        _circuit(),
        tmp_path,
        finder=lambda: Path("ngspice_con.exe"),
        runner=fake_runner,
    )

    output_path = tmp_path / ".pcbsmith" / "simulation" / "ngspice-output.txt"
    assert report.status == "passed"
    assert "-o" not in report.command
    assert report.measurements["op_div_out_v"] == 2.5
    assert report.measurements["ac_hp_out_100_hz_mag_v"] > report.measurements[
        "ac_hp_out_10_hz_mag_v"
    ]
    assert output_path.read_text(encoding="utf-8") == NGSPICE_SAMPLE_OUTPUT


def test_run_ngspice_fails_when_successful_process_has_no_measurements(tmp_path: Path) -> None:
    def fake_runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="ngspice banner only", stderr="")

    report = run_ngspice_simulation(
        _circuit(),
        tmp_path,
        finder=lambda: Path("ngspice_con.exe"),
        runner=fake_runner,
    )

    assert report.status == "failed"
    assert report.findings == (
        "ngspice completed, but PCBSmith could not extract required measurements: "
        "op_div_out_v, op_hp_out_v, op_vin_v, ac_hp_out_10_hz_mag_v, "
        "ac_hp_out_1khz_mag_v, ac_hp_out_100khz_mag_v.",
    )


def test_find_ngspice_uses_environment_override(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "ngspice_con.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("PCBSMITH_NGSPICE", str(executable))

    assert find_ngspice() == executable
