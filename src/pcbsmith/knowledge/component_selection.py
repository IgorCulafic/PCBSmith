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
            "KiCad binding is incomplete; resolve symbol and footprint before "
            "automated placement."
        )
    if "needs-safety-review" in entry["tags"]:
        warnings.append(
            "Safety-sensitive component; require datasheet and human review before "
            "automated use."
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
