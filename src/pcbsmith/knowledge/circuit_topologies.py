from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CIRCUIT_TOPOLOGY_SELECTION_SCHEMA = "pcbsmith-circuit-topology-selection-v1"
CIRCUIT_TOPOLOGY_TOOL_SCHEMA = "pcbsmith-circuit-topology-tool-v1"


@dataclass(frozen=True)
class CircuitTopology:
    id: str
    label: str
    intent: str
    description: str
    component_intents: tuple[str, ...]
    required_math_tools: tuple[str, ...]
    required_inputs: tuple[str, ...]
    do_not_use_rules: tuple[str, ...]
    validation_gates: tuple[str, ...]
    confidence: str = "prototype"

    def to_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "intent": self.intent,
            "description": self.description,
            "component_intents": list(self.component_intents),
            "required_math_tools": list(self.required_math_tools),
            "required_inputs": list(self.required_inputs),
            "do_not_use_rules": list(self.do_not_use_rules),
            "validation_gates": list(self.validation_gates),
            "confidence": self.confidence,
        }


SUPPORTED_TOPOLOGY_INTENTS = (
    "buck-converter",
    "led-indicator",
    "metal-detector",
    "oscillator",
    "power-switching",
)

_TOPOLOGIES = (
    CircuitTopology(
        id="lc-oscillator-metal-detector",
        label="LC oscillator metal detector",
        intent="metal-detector",
        description=(
            "A PCB spiral coil participates in an LC oscillator or sensing stage, "
            "then a gain/threshold stage drives a visible or audible output."
        ),
        component_intents=(
            "lc-sense-coil",
            "bjt-npn-amplifier",
            "trim-adjustment",
            "comparator-threshold",
            "buzzer-output",
            "led-current-limit",
            "terminal-power-input",
        ),
        required_math_tools=(
            "pcb-spiral-coil-estimate",
            "lc-resonance",
            "bjt-bias",
            "comparator-threshold",
            "buzzer-output",
        ),
        required_inputs=(
            "supply_voltage_v",
            "coil_outer_diameter_mm",
            "coil_turns",
            "trace_width_mm",
            "trace_spacing_mm",
            "target_detection_output",
        ),
        do_not_use_rules=(
            "Do not choose NE555 just because it is familiar; only use it when "
            "LC sensing math and topology justify it.",
        ),
        validation_gates=(
            "topology-rationale",
            "component-selection",
            "deterministic-math",
            "schematic-connectivity",
            "KiCad ERC/DRC",
        ),
    ),
)


def select_topologies_for_intent(intent: str) -> dict[str, Any]:
    topologies = [topology.to_data() for topology in _TOPOLOGIES if topology.intent == intent]
    return {
        "schema": CIRCUIT_TOPOLOGY_SELECTION_SCHEMA,
        "intent": intent,
        "supported_intents": list(SUPPORTED_TOPOLOGY_INTENTS),
        "topologies": topologies,
    }


def circuit_topology_tool_contract() -> dict[str, Any]:
    return {
        "schema": CIRCUIT_TOPOLOGY_TOOL_SCHEMA,
        "cli_command": "circuit-topologies <intent>",
        "supported_intents": list(SUPPORTED_TOPOLOGY_INTENTS),
        "instructions": [
            "Select a circuit topology before choosing parts or laying out a board.",
            "Treat topology required_math_tools as hard prerequisites for generation.",
            "Honor do_not_use_rules when a familiar part is not justified by the topology.",
        ],
    }


def circuit_topology_planner_rule_notes() -> list[str]:
    return [
        "Choose a supported circuit topology before selecting parts for a new circuit family.",
        (
            "Do not choose familiar components when a topology do_not_use_rule says "
            "they are unjustified."
        ),
        "Run required math tools before generating schematics or PCB layout for that topology.",
    ]


def format_circuit_topology_selection(result: dict[str, Any]) -> list[str]:
    lines = [
        f"Circuit topologies: {result['intent']}",
        f"Matches: {len(result['topologies'])}",
    ]
    for index, topology in enumerate(result["topologies"], start=1):
        lines.append(f"{index}. {topology['id']} | {topology['label']} | {topology['confidence']}")
        lines.append(f"   required math: {'; '.join(topology['required_math_tools'])}")
        lines.append(f"   component intents: {'; '.join(topology['component_intents'])}")
        if topology["do_not_use_rules"]:
            lines.append(f"   do not use: {'; '.join(topology['do_not_use_rules'])}")
    if not result["topologies"]:
        lines.append("No supported circuit topology matches this intent.")
    return lines


__all__ = [
    "CIRCUIT_TOPOLOGY_SELECTION_SCHEMA",
    "CIRCUIT_TOPOLOGY_TOOL_SCHEMA",
    "SUPPORTED_TOPOLOGY_INTENTS",
    "circuit_topology_planner_rule_notes",
    "circuit_topology_tool_contract",
    "format_circuit_topology_selection",
    "select_topologies_for_intent",
]
