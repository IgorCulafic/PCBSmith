from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.clover import compose_clover
from pcbsmith.kicad.export_clover import U1_PIN_NETS, U2_PIN_NETS
from pcbsmith.simulation.ngspice_clover import render_clover_netlist

REQUEST = "Make a board in the shape of a 4 leaf clover with tilt LEDs"


def test_intent_and_composition() -> None:
    intent = classify_circuit_intent(REQUEST)
    assert intent.intent_id == "clover_tilt_indicator"
    circuit = compose_clover(intent, select_topology(intent))

    by_ref = {component.reference: component for component in circuit.components}
    # Sensor support caps per the MPU-6000/6050 datasheet (p22, section 7.2).
    assert by_ref["C1"].value == "100nF"  # REGOUT
    assert by_ref["C3"].value == "2.2nF"  # CPOUT charge pump
    assert by_ref["U2"].footprint == "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
    # One resistor + LED per leaf.
    for index in range(3, 7):
        assert f"R{index}" in by_ref
    for index in range(1, 5):
        assert f"D{index}" in by_ref
    for leaf in ("NE", "NW", "SW", "SE"):
        assert f"LEAF_{leaf}" in circuit.nets
        assert f"LEAF_{leaf}_A" in circuit.nets


def test_pin_maps_are_consistent() -> None:
    # The AD0 strap makes the sensor answer at 0x68; its bus pins must meet
    # the MCU's USI pins on the same nets.
    assert U1_PIN_NETS[24] == "SDA" and U2_PIN_NETS[7] == "SDA"
    assert U1_PIN_NETS[23] == "SCL" and U2_PIN_NETS[9] == "SCL"
    assert U1_PIN_NETS[12] == "INT" and U2_PIN_NETS[6] == "INT"
    # The four leaves map to PA0..PA3 (pins 13..10).
    assert {U2_PIN_NETS[pin] for pin in (10, 11, 12, 13)} == {
        "LEAF_NE", "LEAF_SE", "LEAF_SW", "LEAF_NW"
    }
    # RESV pins 19/21/22 stay unconnected.
    for pin in (19, 21, 22):
        assert pin not in U1_PIN_NETS


def test_simulation_netlist_drives_each_leaf() -> None:
    intent = classify_circuit_intent(REQUEST)
    circuit = compose_clover(intent, select_topology(intent))

    netlist = render_clover_netlist(circuit)
    assert ".model DGREEN" in netlist
    for leaf in ("ne", "nw", "sw", "se"):
        assert f"VDRV_{leaf}" in netlist
        assert f"D_{leaf} a_{leaf} 0 DGREEN" in netlist
