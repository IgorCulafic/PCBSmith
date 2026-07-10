"""Proven-module registry (Track 8.4 MVP)."""

from __future__ import annotations


def test_flyback_front_end_block_is_registered_and_composes() -> None:
    import pcbsmith.generation.flyback  # noqa: F401 - registers blocks
    from pcbsmith.generation.blocks import MODULE_REGISTRY, list_modules

    entry = MODULE_REGISTRY["mains-input-front-end"]
    parts = entry.builder()
    assert [c.reference for c in parts] == [
        "J1", "RF1", "RV1", "CX1", "CY2", "CY3", "E1",
    ]
    assert "earth_terminal" in entry.provides_roles
    assert entry.proven_by == "design-flyback-authority"
    assert [m.name for m in list_modules()] == sorted(
        m.name for m in list_modules()
    )


def test_block_parts_match_the_composition() -> None:
    from pcbsmith.circuit.intent import classify_circuit_intent
    from pcbsmith.circuit.topologies import select_topology
    from pcbsmith.generation.blocks import MODULE_REGISTRY
    from pcbsmith.generation.flyback import compose_flyback

    intent = classify_circuit_intent("120 VAC to 3.3 V flyback converter")
    circuit = compose_flyback(intent, select_topology(intent))
    block_parts = MODULE_REGISTRY["mains-input-front-end"].builder()
    composed = {c.reference: c for c in circuit.components}
    for part in block_parts:
        assert composed[part.reference] == part


def test_rcd_clamp_block_is_registered_and_matches_composition() -> None:
    from pcbsmith.circuit.intent import classify_circuit_intent
    from pcbsmith.circuit.topologies import select_topology
    from pcbsmith.generation.blocks import MODULE_REGISTRY
    from pcbsmith.generation.flyback import compose_flyback

    entry = MODULE_REGISTRY["rcd-clamp"]
    parts = entry.builder()
    assert [c.reference for c in parts] == ["RC1", "CC1", "D6"]
    assert entry.provides_roles == (
        "clamp_resistor", "clamp_capacitor", "clamp_diode",
    )
    assert entry.proven_by == "design-flyback-authority"

    intent = classify_circuit_intent("120 VAC to 3.3 V flyback converter")
    circuit = compose_flyback(intent, select_topology(intent))
    composed = {c.reference: c for c in circuit.components}
    for part in parts:
        assert composed[part.reference] == part


def test_clamp_resistor_value_tracks_the_calculator_input() -> None:
    # The block's RC1 value string and the dissipation the calculator
    # checks must come from the same constant.
    from pcbsmith.generation.blocks import MODULE_REGISTRY
    from pcbsmith.generation.flyback import CLAMP_RESISTANCE_OHMS

    (rc1, _cc1, _d6) = MODULE_REGISTRY["rcd-clamp"].builder()
    assert rc1.value.startswith(f"{CLAMP_RESISTANCE_OHMS / 1000:g}k")


def test_isolated_feedback_block_is_registered_and_matches_composition() -> None:
    from pcbsmith.circuit.intent import classify_circuit_intent
    from pcbsmith.circuit.topologies import select_topology
    from pcbsmith.generation.blocks import MODULE_REGISTRY
    from pcbsmith.generation.flyback import compose_flyback

    intent = classify_circuit_intent("120 VAC to 3.3 V flyback converter")
    circuit = compose_flyback(intent, select_topology(intent))
    entry = MODULE_REGISTRY["isolated-feedback"]
    # Divider values are the CALCULATOR's output, passed into the block;
    # the identity check must therefore build with the composed values.
    parts = entry.builder(
        feedback_upper_ohms=circuit.math.calculations["feedback_upper_ohms"],
        feedback_lower_ohms=circuit.math.calculations["feedback_lower_ohms"],
    )
    assert [c.reference for c in parts] == [
        "U2", "U3", "RFB1", "RFB2", "RO1", "RO2", "RP1",
    ]
    assert entry.proven_by == "design-flyback-authority"
    composed = {c.reference: c for c in circuit.components}
    for part in parts:
        assert composed[part.reference] == part


def test_servo555_blocks_are_registered_and_match_the_composition() -> None:
    from pcbsmith.circuit.intent import classify_circuit_intent
    from pcbsmith.circuit.topologies import select_topology
    from pcbsmith.generation.blocks import MODULE_REGISTRY
    from pcbsmith.generation.servo555 import compose_servo555

    intent = classify_circuit_intent(
        "555 timer servo tester with forward and reverse buttons"
    )
    circuit = compose_servo555(intent, select_topology(intent))
    composed = {c.reference: c for c in circuit.components}

    astable = MODULE_REGISTRY["ne555-button-astable"]
    parts = astable.builder()
    assert [c.reference for c in parts] == [
        "R1", "R2", "R3", "C1", "C2", "SW1", "SW2",
    ]
    assert astable.proven_by == "design-servo555-authority"
    for part in parts:
        assert composed[part.reference] == part

    inverter = MODULE_REGISTRY["bjt-signal-inverter"]
    parts = inverter.builder()
    assert [c.reference for c in parts] == ["R4", "Q1", "R5"]
    for part in parts:
        assert composed[part.reference] == part
