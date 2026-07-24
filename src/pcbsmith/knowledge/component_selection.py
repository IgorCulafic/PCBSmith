from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pcbsmith.knowledge.component_knowledge_index import search_component_knowledge_index

COMPONENT_SELECTION_SCHEMA = "pcbsmith-component-selection-v1"
COMPONENT_SELECTION_TOOL_SCHEMA = "pcbsmith-component-selection-tool-v1"

MountingStyle = Literal["smd", "through-hole", "virtual", "unspecified"]
SelectionStatus = Literal["preferred", "candidate", "needs_review"]


@dataclass(frozen=True)
class ComponentSelectionRule:
    label: str
    query: str
    tags: tuple[str, ...]
    family_ids: tuple[str, ...]
    preferred_mounting: MountingStyle
    candidate_warning: str | None
    next_checks: tuple[str, ...]


_RULES: dict[str, ComponentSelectionRule] = {
    "led-current-limit": ComponentSelectionRule(
        label="LED current-limit resistor",
        query="resistor",
        tags=("resistor",),
        family_ids=("resistor",),
        preferred_mounting="smd",
        candidate_warning=None,
        next_checks=(
            "Calculate resistor value from supply voltage, LED forward voltage, "
            "and target current.",
            "Check resistor power dissipation.",
        ),
    ),
    "low-side-switch": ComponentSelectionRule(
        label="Low-side MOSFET switch",
        query="mosfet nmos switching",
        tags=("mosfet", "nmos", "switching"),
        family_ids=("mosfet",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify Vgs(th), Rds(on), current rating, package heat, and gate drive "
            "before fabrication."
        ),
        next_checks=(
            "Confirm load current and supply voltage.",
            "Confirm gate-drive voltage fully enhances the selected MOSFET.",
            "Add flyback protection for inductive loads.",
        ),
    ),
    "bjt-npn-amplifier": ComponentSelectionRule(
        label="NPN BJT gain or switching stage",
        query="npn bjt amplifier",
        tags=("transistor", "bjt", "npn"),
        family_ids=("bjt",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify gain, bias point, collector current, package power, and exact pinout."
        ),
        next_checks=(
            "Calculate base resistor and collector/emitter operating point.",
            "Confirm signal swing and saturation or linear-region intent.",
            "Check selected package pin mapping against the footprint.",
        ),
    ),
    "bjt-pnp-switch": ComponentSelectionRule(
        label="PNP BJT high-side or signal switch",
        query="pnp bjt switching",
        tags=("transistor", "bjt", "pnp"),
        family_ids=("bjt",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify high-side topology, base drive limits, package power, and exact pinout."
        ),
        next_checks=(
            "Confirm load current and supply voltage.",
            "Calculate base drive and pull resistor values.",
            "Check selected package pin mapping against the footprint.",
        ),
    ),
    "comparator-threshold": ComponentSelectionRule(
        label="Comparator threshold stage",
        query="comparator threshold",
        tags=("comparator", "threshold"),
        family_ids=("comparator",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify input common-mode range, output type, supply range, and hysteresis needs."
        ),
        next_checks=(
            "Calculate threshold divider and optional hysteresis.",
            "Confirm output pull-up and logic/input compatibility.",
            "Add local decoupling near VCC/GND.",
        ),
    ),
    "op-amp-buffer": ComponentSelectionRule(
        label="Op amp buffer or gain stage",
        query="op amp buffer amplifier",
        tags=("op-amp", "amplifier"),
        family_ids=("op-amp",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify input/output range, supply voltage, bandwidth, stability, and package pinout."
        ),
        next_checks=(
            "Calculate gain and bias network.",
            "Confirm input/output swing at the requested supply voltage.",
            "Add local decoupling near VCC/GND.",
        ),
    ),
    "buzzer-output": ComponentSelectionRule(
        label="Audible buzzer output",
        query="buzzer audio indicator",
        tags=("buzzer",),
        family_ids=("buzzer",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify active/passive buzzer type, voltage, current, polarity, and driver needs."
        ),
        next_checks=(
            "Confirm output current budget and whether a transistor driver is needed.",
            "Confirm active versus passive buzzer behavior.",
            "Mark polarity on silkscreen when useful.",
        ),
    ),
    "terminal-power-input": ComponentSelectionRule(
        label="Solderable power input connector",
        query="terminal block power entry",
        tags=("connector", "power-entry"),
        family_ids=("terminal-block", "pin-header"),
        preferred_mounting="through-hole",
        candidate_warning=(
            "Verify pitch, wire gauge, current rating, polarity marking, and mechanical clearance."
        ),
        next_checks=(
            "Place VCC and GND next to each other when practical.",
            "Add clear polarity silkscreen.",
            "Check current rating and edge clearance.",
        ),
    ),
    "battery-power": ComponentSelectionRule(
        label="Battery power source",
        query="battery coin cell cr2032",
        tags=("battery", "power"),
        family_ids=("battery-holder",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify cell chemistry, holder polarity, load current, and whether the "
            "requested circuit can run from the battery voltage."
        ),
        next_checks=(
            "Confirm supply voltage and expected current draw.",
            "Add clear polarity silkscreen and reverse-polarity protection when useful.",
            "Check holder mechanical clearance and battery access.",
        ),
    ),
    "regulated-power": ComponentSelectionRule(
        label="Linear regulated power rail",
        query="regulator ldo power",
        tags=("regulator", "power"),
        family_ids=("linear-regulator",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify input voltage, dropout, current, heat dissipation, stability, "
            "and required input/output capacitors."
        ),
        next_checks=(
            "Calculate regulator power dissipation from voltage drop and load current.",
            "Add required input and output capacitors close to the regulator pins.",
            "Check package thermal limits against the fabrication/use case.",
        ),
    ),
    "user-input-button": ComponentSelectionRule(
        label="User input push button",
        query="button switch tactile",
        tags=("button", "switch"),
        family_ids=("push-button",),
        preferred_mounting="smd",
        candidate_warning=None,
        next_checks=(
            "Choose pull-up or pull-down behavior.",
            "Decide whether hardware debounce or firmware debounce is expected.",
            "Keep switch placement accessible at the board edge when practical.",
        ),
    ),
    "programming-header": ComponentSelectionRule(
        label="Programming/debug header",
        query="programming header connector",
        tags=("programming", "connector"),
        family_ids=("pin-header",),
        preferred_mounting="through-hole",
        candidate_warning=(
            "Verify pin order against the programmer and add unambiguous silkscreen labels."
        ),
        next_checks=(
            "Confirm header pinout and orientation.",
            "Place related pins together and label them on silkscreen.",
            "Keep enough clearance for the programmer cable or pogo adapter.",
        ),
    ),
    "clock-source": ComponentSelectionRule(
        label="Crystal or resonator clock source",
        query="crystal clock oscillator",
        tags=("crystal", "clock"),
        family_ids=("crystal",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify frequency, load capacitance, drive level, ESR, and MCU oscillator requirements."
        ),
        next_checks=(
            "Calculate load capacitors from crystal CL and stray capacitance.",
            "Place the crystal and capacitors close to the IC clock pins.",
            "Keep high-current or fast-switching traces away from the oscillator loop.",
        ),
    ),
    "microcontroller-8bit": ComponentSelectionRule(
        label="Small 8-bit microcontroller",
        query="attiny85 microcontroller avr",
        tags=("microcontroller",),
        family_ids=("microcontroller",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify supply voltage, clock source, programming method, pin mapping, "
            "firmware availability, and decoupling."
        ),
        next_checks=(
            "Reserve VCC/GND decoupling close to the IC.",
            "Confirm reset, programming, and IO pin assignments.",
            "Check that requested behavior is possible with the selected pin count "
            "and firmware path.",
        ),
    ),
    "reverse-polarity-protection": ComponentSelectionRule(
        label="Reverse-polarity protection diode",
        query="schottky protection reverse polarity",
        tags=("schottky", "protection"),
        family_ids=("schottky-diode",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify forward voltage drop, current rating, reverse voltage, and power dissipation."
        ),
        next_checks=(
            "Choose series or shunt protection topology.",
            "Calculate voltage drop and diode heating at expected load current.",
            "Confirm downstream circuit still receives enough voltage.",
        ),
    ),
    "trim-adjustment": ComponentSelectionRule(
        label="User trim adjustment",
        query="potentiometer trimmer",
        tags=("potentiometer",),
        family_ids=("potentiometer",),
        preferred_mounting="smd",
        candidate_warning=None,
        next_checks=(
            "Choose adjustment range and taper.",
            "Confirm the wiper is never left floating in the intended circuit.",
        ),
    ),
    "lc-sense-coil": ComponentSelectionRule(
        label="PCB spiral sensing coil",
        query="inductor coil magnetic",
        tags=("inductor", "magnetic"),
        family_ids=("inductor",),
        preferred_mounting="smd",
        candidate_warning=(
            "For a PCB spiral coil, use the deterministic coil geometry tool instead "
            "of treating a discrete inductor as equivalent."
        ),
        next_checks=(
            "Calculate PCB spiral inductance from geometry.",
            "Check trace width, spacing, resistance, and board outline constraints.",
            "Route the inner coil terminal on another layer or with a via strategy.",
        ),
    ),
    "555-timer": ComponentSelectionRule(
        label="555 timer IC",
        query="ne555 timer",
        tags=("timer",),
        family_ids=("timer",),
        preferred_mounting="smd",
        candidate_warning=(
            "Confirm exact 555 variant, supply range, output current, and package pinout."
        ),
        next_checks=(
            "Choose timing resistor and capacitor values.",
            "Add local decoupling near VCC/GND.",
            "Confirm RESET and CTRL pins are intentionally handled.",
        ),
    ),
    "power-entry": ComponentSelectionRule(
        label="Protected power entry",
        query="fuse protection",
        tags=("fuse",),
        family_ids=("fuse",),
        preferred_mounting="smd",
        candidate_warning=(
            "Choose fuse current, voltage rating, trip behavior, and downstream protection."
        ),
        next_checks=(
            "Add input connector or pads with clear polarity labels.",
            "Choose fuse rating for expected load and startup current.",
            "Consider reverse-polarity and transient protection.",
        ),
    ),
    "zener-protection": ComponentSelectionRule(
        label="Zener clamp protection",
        query="zener protection",
        tags=("zener", "protection"),
        family_ids=("zener-diode",),
        preferred_mounting="smd",
        candidate_warning=None,
        next_checks=(
            "Choose breakdown voltage and power rating for the protected net.",
            "Confirm clamp current path and series impedance.",
        ),
    ),
    "relay-switching": ComponentSelectionRule(
        label="Relay switching",
        query="relay switching",
        tags=("relay", "switching"),
        family_ids=("relay",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify coil voltage/current, contact ratings, isolation, and flyback protection."
        ),
        next_checks=(
            "Confirm coil drive circuit and current budget.",
            "Check contact voltage/current and clearance requirements.",
            "Add flyback protection across the relay coil.",
        ),
    ),
    "isolated-power": ComponentSelectionRule(
        label="Transformer or magnetic isolation",
        query="transformer magnetic",
        tags=("transformer",),
        family_ids=("transformer",),
        preferred_mounting="smd",
        candidate_warning=(
            "Verify insulation rating, creepage/clearance, saturation, frequency, and power."
        ),
        next_checks=(
            "Confirm isolation voltage and safety standard requirements.",
            "Check frequency, core saturation, and temperature rise.",
            "Keep high-voltage and low-voltage copper separated by rule.",
        ),
    ),
}

SUPPORTED_COMPONENT_INTENTS = tuple(sorted(_RULES))
_MOUNTING_STYLES: tuple[MountingStyle, ...] = (
    "smd",
    "through-hole",
    "virtual",
    "unspecified",
)


def select_components_for_intent(
    index: dict[str, Any],
    intent: str,
    *,
    preferred_mounting: MountingStyle = "smd",
    limit: int = 5,
) -> dict[str, Any]:
    if intent not in _RULES:
        raise ValueError(f"Unsupported component selection intent: {intent}")
    if preferred_mounting not in _MOUNTING_STYLES:
        raise ValueError(f"Unsupported preferred mounting style: {preferred_mounting}")

    rule = _RULES[intent]
    mounting = preferred_mounting or rule.preferred_mounting
    search_result = search_component_knowledge_index(
        index,
        query=rule.query,
        mounting=mounting,
        tags=rule.tags,
        limit=limit,
    )
    search_result["results"] = _filter_rule_families(search_result["results"], rule)
    warnings: list[str] = []
    if not search_result["results"]:
        search_result = search_component_knowledge_index(
            index,
            query=rule.query,
            tags=rule.tags,
            limit=limit,
        )
        search_result["results"] = _filter_rule_families(search_result["results"], rule)
        if search_result["results"]:
            warnings.append(
                f"No {mounting} candidates matched; returned other mounting styles instead."
            )

    candidates = [
        _selection_candidate(entry, rank=rank + 1, intent=intent, rule=rule, mounting=mounting)
        for rank, entry in enumerate(search_result["results"])
    ]
    return {
        "schema": COMPONENT_SELECTION_SCHEMA,
        "intent": intent,
        "intent_label": rule.label,
        "preferred_mounting": mounting,
        "result_count": len(candidates),
        "candidates": candidates,
        "warnings": warnings,
        "next_checks": list(rule.next_checks),
    }


def select_components_for_intent_file(
    index_path: Path,
    intent: str,
    *,
    preferred_mounting: MountingStyle = "smd",
    limit: int = 5,
) -> dict[str, Any]:
    loaded = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected component knowledge index JSON object: {index_path}")
    return select_components_for_intent(
        loaded,
        intent,
        preferred_mounting=preferred_mounting,
        limit=limit,
    )


def component_selection_tool_contract() -> dict[str, Any]:
    return {
        "schema": COMPONENT_SELECTION_TOOL_SCHEMA,
        "cli_command": "component-selection <component-knowledge-index> <intent>",
        "preferred_mounting_default": "smd",
        "supported_intents": list(SUPPORTED_COMPONENT_INTENTS),
        "selection_statuses": ["preferred", "candidate", "needs_review"],
        "instructions": [
            "Use an intent when choosing a part role instead of inventing symbols or footprints.",
            "Treat needs_review candidates as requiring user approval or deeper datasheet review.",
        ],
    }


def component_selection_planner_rule_notes() -> list[str]:
    return [
        "Use component_selection supported_intents before choosing catalog parts.",
        "Do not invent component roles outside supported_intents without saying what is missing.",
        "Treat component_selection needs_review candidates as blocked until the user "
        "or a deeper review approves them.",
    ]


def format_component_selection_result(result: dict[str, Any]) -> list[str]:
    lines = [
        f"Component selection: {result['intent']}",
        f"Preferred mounting: {result['preferred_mounting']}",
        f"Matches: {result['result_count']}",
    ]
    for warning in result["warnings"]:
        lines.append(f"Warning: {warning}")
    for candidate in result["candidates"]:
        lines.append(
            f"{candidate['rank']}. {candidate['entry_id']} | "
            f"{candidate['variant_name']} | {candidate['mounting_style']} | "
            f"{candidate['support_status']} | {candidate['selection_status']}"
        )
        lines.append(f"   reasons: {'; '.join(candidate['reasons'])}")
        if candidate["warnings"]:
            lines.append(f"   warnings: {'; '.join(candidate['warnings'])}")
    if result["next_checks"]:
        lines.append(f"Next checks: {'; '.join(result['next_checks'])}")
    if not result["candidates"]:
        lines.append("No component selection candidates.")
    return lines


def _selection_candidate(
    entry: dict[str, Any],
    *,
    rank: int,
    intent: str,
    rule: ComponentSelectionRule,
    mounting: str,
) -> dict[str, Any]:
    warnings = _candidate_warnings(entry, rule)
    return {
        "rank": rank,
        **entry,
        "selection_status": _selection_status(entry, rank=rank, warnings=warnings),
        "reasons": _candidate_reasons(entry, intent=intent, rule=rule, mounting=mounting),
        "warnings": warnings,
    }


def _filter_rule_families(
    entries: list[dict[str, Any]],
    rule: ComponentSelectionRule,
) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry["family_id"] in rule.family_ids]


def _selection_status(
    entry: dict[str, Any],
    *,
    rank: int,
    warnings: list[str],
) -> SelectionStatus:
    if warnings or entry["support_status"] != "well_supported":
        return "needs_review"
    if rank == 1:
        return "preferred"
    return "candidate"


def _candidate_reasons(
    entry: dict[str, Any],
    *,
    intent: str,
    rule: ComponentSelectionRule,
    mounting: str,
) -> list[str]:
    reasons = [
        f"Matches intent {intent}",
        f"Matches required tags: {', '.join(rule.tags)}",
    ]
    if entry["mounting_style"] == mounting:
        reasons.append(f"Uses preferred mounting: {mounting}")
    else:
        reasons.append(f"Fallback mounting: {entry['mounting_style']}")
    return reasons


def _candidate_warnings(
    entry: dict[str, Any],
    rule: ComponentSelectionRule,
) -> list[str]:
    warnings = []
    if entry["support_status"] == "metadata_only":
        warnings.append(
            "KiCad availability is not confirmed; resolve symbol and footprint before "
            "automated placement."
        )
    elif entry["support_status"] == "needs_datasheet_review":
        warnings.append(
            "KiCad binding is incomplete; resolve symbol and footprint before automated placement."
        )
    if "needs-safety-review" in entry["tags"]:
        warnings.append(
            "Safety-sensitive component; require datasheet and human review before automated use."
        )
    if rule.candidate_warning is not None:
        warnings.append(rule.candidate_warning)
    return warnings


__all__ = [
    "COMPONENT_SELECTION_SCHEMA",
    "COMPONENT_SELECTION_TOOL_SCHEMA",
    "SUPPORTED_COMPONENT_INTENTS",
    "component_selection_planner_rule_notes",
    "component_selection_tool_contract",
    "format_component_selection_result",
    "select_components_for_intent",
    "select_components_for_intent_file",
]
