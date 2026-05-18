from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology


def test_selects_topology_with_formula_evidence() -> None:
    intent = classify_circuit_intent(
        "voltage divider connected to a high-pass filter and led indicator"
    )

    topology = select_topology(intent)

    assert topology.topology_id == "divider_highpass_led_indicator"
    assert topology.status == "selected"
    assert [item.kind for item in topology.evidence] == [
        "textbook_formula",
        "textbook_formula",
        "engineering_assumption",
    ]
    assert topology.warnings == (
        "LED brightness and conduction after AC coupling require simulation and human review.",
    )
