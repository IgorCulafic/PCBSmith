from __future__ import annotations

import pytest

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.led_art import (
    GLYPHS_5ROW,
    compose_led_art,
    plan_led_text,
)

REQUEST = "Create a LED matrix spelling out IGOR C. with input pins for a 12V system"


def _circuit_and_plan():
    intent = classify_circuit_intent(REQUEST)
    topology = select_topology(intent)
    return compose_led_art(intent, topology)


def test_intent_extracts_text_and_supply() -> None:
    intent = classify_circuit_intent(REQUEST)

    assert intent.status == "supported"
    assert intent.intent_id == "led_text_matrix"
    assert intent.assumptions["text"] == "IGOR C."
    assert intent.assumptions["supply_voltage_v"] == 12.0


def test_plan_strings_are_one_per_lit_column() -> None:
    circuit, plan = _circuit_and_plan()

    lit_columns = sum(
        sum(1 for rows in GLYPHS_5ROW[char] if rows) for char in "IGOR C."
    )
    assert len(plan.strings) == lit_columns
    # Columns are unique: one string per glyph column, gaps between glyphs.
    columns = [string.column for string in plan.strings]
    assert len(set(columns)) == len(columns)
    assert columns == sorted(columns)


def test_string_resistors_scale_with_led_count() -> None:
    circuit, plan = _circuit_and_plan()

    by_count = {len(string.rows): string.resistor_ohms for string in plan.strings}
    # More LEDs leave less headroom, so the resistor shrinks monotonically.
    counts = sorted(by_count)
    assert all(
        by_count[a] > by_count[b] for a, b in zip(counts, counts[1:], strict=False)
    )
    # 5-LED string: (12 - 5*1.85) / 10mA = 275 -> E24 270.
    assert by_count[5] == 270


def test_compose_builds_components_for_every_string() -> None:
    circuit, plan = _circuit_and_plan()

    references = {component.reference for component in circuit.components}
    assert "P1" in references
    for string in plan.strings:
        assert string.resistor_ref in references
        assert set(string.led_refs) <= references
    assert circuit.math.calculations["led_count"] == sum(
        len(string.led_refs) for string in plan.strings
    )


def test_unknown_glyph_is_rejected() -> None:
    with pytest.raises(ValueError, match="No 5-row glyph"):
        plan_led_text("IGOR@", string_solutions={1: 1000.0})
