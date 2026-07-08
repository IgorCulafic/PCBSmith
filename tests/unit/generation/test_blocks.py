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
