from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led


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
