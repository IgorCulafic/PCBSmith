from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.led_art import compose_led_art
from pcbsmith.simulation.ngspice_led_art import (
    parse_supply_current_a,
    render_led_art_netlist,
)

REQUEST = "Create a LED matrix spelling out IGOR C. with input pins for a 12V system"


def test_netlist_contains_every_string() -> None:
    intent = classify_circuit_intent(REQUEST)
    circuit, plan = compose_led_art(intent, select_topology(intent))

    netlist = render_led_art_netlist(circuit, plan)

    assert "V1 vin 0 DC 12" in netlist
    assert ".op" in netlist
    for index, string in enumerate(plan.strings, start=1):
        assert f"R{index} vin " in netlist
        for led_ref in string.led_refs:
            assert f"D{led_ref} " in netlist
    # Every string ends at ground.
    assert netlist.count(" 0 DLED") == len(plan.strings)


def test_parse_supply_current_reads_branch_row() -> None:
    output = """
	Node                                   Voltage
	----                                   -------
	vin                                    12.000000e+00
	v1#branch                             -2.043210e-01
"""

    assert parse_supply_current_a(output) == 0.204321
    assert parse_supply_current_a("no branch here") is None
