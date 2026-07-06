from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.pear import compose_pear
from pcbsmith.kicad.pear_board import ring_unit_counts
from pcbsmith.simulation.ngspice_pear import render_pear_netlist

REQUEST = "A pear shaped board with LEDs around the edges in 3 layers, 12V drive"


def test_intent_and_composition_match_the_geometry() -> None:
    intent = classify_circuit_intent(REQUEST)
    assert intent.intent_id == "pear_led_rings"
    assert intent.assumptions["supply_voltage_v"] == 12.0
    circuit = compose_pear(intent, select_topology(intent))

    counts = ring_unit_counts()
    total = sum(counts)
    by_ref = {component.reference: component for component in circuit.components}
    assert len(by_ref) == 1 + 2 * total  # connector plus R/D per unit
    # (12 - 2.2) / 5 mA = 1960 ohms -> E24 2.0k.
    assert by_ref["R1"].value == "2k"
    assert circuit.math.calculations["ring1_led_count"] == counts[0]
    for ring in range(1, 4):
        assert f"L{ring}" in circuit.nets
    assert f"D{total}_A" in circuit.nets


def test_simulation_netlist_covers_every_branch() -> None:
    intent = classify_circuit_intent(REQUEST)
    circuit = compose_pear(intent, select_topology(intent))

    netlist = render_pear_netlist(circuit)
    total = sum(ring_unit_counts())
    for ring in range(1, 4):
        assert f"VL{ring} l{ring} 0 DC 12" in netlist
    assert f"D_{total} a_{total} 0 DGREEN" in netlist
    assert netlist.count("DGREEN") == total + 1  # model line plus every diode
