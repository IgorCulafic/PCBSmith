from __future__ import annotations

import math

from pcbsmith.calculators.electronics import solve_555_servo_tester
from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.servo555 import (
    CAPACITOR_DISCREPANCY_FINDING,
    compose_servo555,
    servo555_test_steps,
)
from pcbsmith.simulation.ngspice_servo555 import render_servo555_netlist

REQUEST = (
    "Design a compact PCB for a 555-timer-based RC servo driver tester "
    "with forward and reverse buttons"
)


def test_intent_and_composition_reproduce_the_reference_circuit() -> None:
    intent = classify_circuit_intent(REQUEST)
    assert intent.intent_id == "servo_555_tester"
    circuit = compose_servo555(intent, select_topology(intent))

    by_ref = {component.reference: component for component in circuit.components}
    assert len(by_ref) == 19
    # The reference schematic's values, exactly.
    assert by_ref["R1"].value == "33k"
    assert by_ref["R2"].value == "68k"
    assert by_ref["R3"].value == "10k"
    assert by_ref["R4"].value == "1k"
    assert by_ref["R5"].value == "4.7k"
    assert by_ref["C1"].value == "100n"
    assert by_ref["C2"].value == "10n"
    assert by_ref["U1"].footprint == "Package_DIP:DIP-8_W7.62mm_Socket"
    assert by_ref["Q1"].footprint == "Package_TO_SOT_THT:TO-92_Inline"

    # The requested uncertainty flag: schematic 10n vs instructable
    # text 100n on the CONT pin, surfaced before finalizing.
    assert CAPACITOR_DISCREPANCY_FINDING in circuit.math.findings

    calc = circuit.math.calculations
    assert math.isclose(calc["forward_servo_pulse_ms"], 4.712, abs_tol=5e-4)
    assert math.isclose(calc["reverse_servo_pulse_ms"], 0.693, abs_tol=5e-4)


def test_simulation_netlist_models_the_inverter_stage() -> None:
    intent = classify_circuit_intent(REQUEST)
    circuit = compose_servo555(intent, select_topology(intent))

    netlist = render_servo555_netlist(circuit)
    assert "Q1 sig base 0 QBC547" in netlist
    assert "R5 vcc sig 4.7k" in netlist
    assert ".meas tran pulse_width" in netlist


def test_bench_steps_carry_the_calculated_design_point() -> None:
    outputs = solve_555_servo_tester()["outputs"]
    steps = servo555_test_steps(outputs)
    assert len(steps) >= 5
    text = " ".join(f"{s.procedure} {s.expected}" for s in steps)
    assert "4.712" in text  # FORWARD pulse width on the bench plan
    assert "0.693" in text  # REVERSE pulse width
