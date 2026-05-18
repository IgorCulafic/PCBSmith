from __future__ import annotations

from pcbsmith.knowledge.circuit_topologies import (
    circuit_topology_planner_rule_notes,
    circuit_topology_tool_contract,
    select_topologies_for_intent,
)


def test_metal_detector_intent_prefers_lc_sensing_before_familiar_555_shortcuts() -> None:
    result = select_topologies_for_intent("metal-detector")

    assert result["schema"] == "pcbsmith-circuit-topology-selection-v1"
    assert result["intent"] == "metal-detector"
    assert result["topologies"][0]["id"] == "lc-oscillator-metal-detector"
    assert "pcb-spiral-coil-estimate" in result["topologies"][0]["required_math_tools"]
    assert "lc-resonance" in result["topologies"][0]["required_math_tools"]
    assert "bjt-npn-amplifier" in result["topologies"][0]["component_intents"]
    assert "buzzer-output" in result["topologies"][0]["component_intents"]
    assert any(
        "Do not choose NE555 just because it is familiar" in rule
        for rule in result["topologies"][0]["do_not_use_rules"]
    )


def test_unknown_intent_returns_empty_selection_with_supported_intents() -> None:
    result = select_topologies_for_intent("calculator")

    assert result["topologies"] == []
    assert "metal-detector" in result["supported_intents"]


def test_buck_converter_selects_lm2596_topology_with_math_gate() -> None:
    result = select_topologies_for_intent("buck-converter")

    assert result["intent"] == "buck-converter"
    assert result["topologies"][0]["id"] == "lm2596-adjustable-buck"
    assert "lm2596-buck" in result["topologies"][0]["required_math_tools"]
    assert "buck-converter" in result["supported_intents"]


def test_topology_tool_contract_is_ai_facing() -> None:
    contract = circuit_topology_tool_contract()

    assert contract == {
        "schema": "pcbsmith-circuit-topology-tool-v1",
        "cli_command": "circuit-topologies <intent>",
        "supported_intents": [
            "buck-converter",
            "led-indicator",
            "metal-detector",
            "oscillator",
            "power-switching",
        ],
        "instructions": [
            "Select a circuit topology before choosing parts or laying out a board.",
            "Treat topology required_math_tools as hard prerequisites for generation.",
            "Honor do_not_use_rules when a familiar part is not justified by the topology.",
        ],
    }


def test_topology_planner_notes_block_freehand_part_choice() -> None:
    assert circuit_topology_planner_rule_notes() == [
        "Choose a supported circuit topology before selecting parts for a new circuit family.",
        (
            "Do not choose familiar components when a topology do_not_use_rule says "
            "they are unjustified."
        ),
        "Run required math tools before generating schematics or PCB layout for that topology.",
    ]
