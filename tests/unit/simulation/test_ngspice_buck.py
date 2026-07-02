from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.lm2596_buck import compose_lm2596_buck
from pcbsmith.simulation.ngspice_buck import (
    _evaluate_buck_measurements,
    parse_ngspice_meas_results,
    render_lm2596_power_stage_netlist,
)


def _buck_circuit():
    intent = classify_circuit_intent("LM2596 buck step-down module")
    return compose_lm2596_buck(intent, select_topology(intent))


def test_power_stage_netlist_uses_calculator_values() -> None:
    netlist = render_lm2596_power_stage_netlist(_buck_circuit())

    assert "VIN vin 0 DC 12" in netlist
    assert "L1 sw out 100u" in netlist
    assert "PULSE(0 1 0 10n 10n" in netlist
    assert ".meas tran buck_vout_avg_v AVG V(out)" in netlist
    assert "control loop NOT modelled" in netlist


def test_parse_ngspice_meas_results_extracts_named_values() -> None:
    output = """
No. of Data Rows : 15001
buck_vout_avg_v     =  5.012345e+00 from=  2.000000e-03 to=  3.000000e-03
buck_vout_ripple_pp_v =  3.412000e-02 from=  2.000000e-03 to=  3.000000e-03
buck_inductor_current_max_a =  1.152000e+00 from=  2.000000e-03 to=  3.000000e-03
"""

    measurements = parse_ngspice_meas_results(output)

    assert measurements["buck_vout_avg_v"] == 5.012345
    assert measurements["buck_vout_ripple_pp_v"] == 0.03412
    assert measurements["buck_inductor_current_max_a"] == 1.152


def test_evaluate_buck_measurements_passes_with_open_loop_note() -> None:
    status, findings = _evaluate_buck_measurements(
        {
            "buck_vout_avg_v": 5.0,
            "buck_vout_ripple_pp_v": 0.04,
            "buck_inductor_current_max_a": 1.2,
        },
        5.031149,
    )

    assert status == "passed"
    assert any("NOT simulated" in finding for finding in findings)


def test_evaluate_buck_measurements_fails_out_of_band_output() -> None:
    status, findings = _evaluate_buck_measurements(
        {
            "buck_vout_avg_v": 3.9,
            "buck_vout_ripple_pp_v": 0.04,
            "buck_inductor_current_max_a": 1.2,
        },
        5.031149,
    )

    assert status == "failed"
    assert any("outside" in finding for finding in findings)


def test_evaluate_buck_measurements_fails_excess_inductor_current() -> None:
    status, findings = _evaluate_buck_measurements(
        {
            "buck_vout_avg_v": 5.0,
            "buck_vout_ripple_pp_v": 0.04,
            "buck_inductor_current_max_a": 3.4,
        },
        5.031149,
    )

    assert status == "failed"
    assert any("inductor current" in finding for finding in findings)
