from __future__ import annotations

import math

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.metal_detector import compose_metal_detector
from pcbsmith.simulation.ngspice_metal_detector import render_detector_netlist

REQUEST = "Create a metal detector board that uses exposed traces as the coil"


def test_intent_and_composition_derive_from_the_geometry() -> None:
    intent = classify_circuit_intent(REQUEST)
    assert intent.intent_id == "metal_detector_coil"
    circuit = compose_metal_detector(intent, select_topology(intent))

    calc = circuit.math.calculations
    assert math.isclose(calc["coil_inductance_h"], 17.8e-6, rel_tol=0.02)
    assert math.isclose(calc["oscillation_frequency_hz"], 1.14e6, rel_tol=0.01)
    assert calc["coil_quality_factor"] > 30

    by_ref = {component.reference: component for component in circuit.components}
    # The coil is copper only: its "footprint" is the net tie.
    assert by_ref["L1"].footprint == "NetTie:NetTie-2_SMD_Pad2.0mm"
    assert "PCB spiral" in by_ref["L1"].value
    assert by_ref["Q1"].footprint == "Package_TO_SOT_SMD:SOT-23"
    # The detection mechanism is an explicit contract finding.
    assert any("Detection contract" in finding for finding in circuit.math.findings)


def test_simulation_netlist_carries_the_coil_and_the_detune() -> None:
    intent = classify_circuit_intent(REQUEST)
    circuit = compose_metal_detector(intent, select_topology(intent))

    nominal = render_detector_netlist(circuit)
    assert "Q1 col base em QNPN" in nominal
    assert "RDCR lx col" in nominal  # the coil's own resistance is modelled
    assert ".meas tran det_t1" in nominal

    detuned = render_detector_netlist(circuit, detune=0.96)
    inductance = circuit.math.calculations["coil_inductance_h"]
    assert f"L1 vcc lx {inductance * 0.96:g}" in detuned
