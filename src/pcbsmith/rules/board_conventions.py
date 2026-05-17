from __future__ import annotations

from dataclasses import dataclass, field

REFERENCE_PREFIXES: dict[str, str] = {
    "resistor": "R",
    "capacitor": "C",
    "led": "LED",
    "diode": "D",
    "ic": "U",
    "connector": "J",
    "transistor": "Q",
    "mosfet": "Q",
    "inductor": "L",
    "switch": "SW",
    "fuse": "F",
    "relay": "K",
    "transformer": "T",
    "test_point": "TP",
}


@dataclass
class ReferenceDesignatorAllocator:
    _counts_by_prefix: dict[str, int] = field(default_factory=dict)

    def next(self, component_kind: str) -> str:
        try:
            prefix = REFERENCE_PREFIXES[component_kind]
        except KeyError as exc:
            raise ValueError(f"Unknown component kind: {component_kind}") from exc
        return self.next_prefix(prefix)

    def next_prefix(self, prefix: str) -> str:
        normalized_prefix = prefix.strip().upper()
        if not normalized_prefix:
            raise ValueError("Reference prefix cannot be blank")
        next_index = self._counts_by_prefix.get(normalized_prefix, 0) + 1
        self._counts_by_prefix[normalized_prefix] = next_index
        return f"{normalized_prefix}{next_index}"


@dataclass(frozen=True)
class BoardAnnotationPolicy:
    show_references_on_silkscreen: bool = True
    show_values_on_silkscreen: bool = False
    value_default_destination: str = "fabrication_layers_and_bom"


DEFAULT_BOARD_ANNOTATION_POLICY = BoardAnnotationPolicy()


def silkscreen_value_enabled(
    policy: BoardAnnotationPolicy = DEFAULT_BOARD_ANNOTATION_POLICY,
) -> bool:
    return policy.show_values_on_silkscreen


def board_annotation_rules_summary(
    policy: BoardAnnotationPolicy = DEFAULT_BOARD_ANNOTATION_POLICY,
) -> dict[str, object]:
    return {
        "reference_designators": dict(REFERENCE_PREFIXES),
        "silkscreen_defaults": {
            "show_references": policy.show_references_on_silkscreen,
            "show_values": policy.show_values_on_silkscreen,
            "value_default_destination": policy.value_default_destination,
        },
        "notes": [
            "Use conventional EDA reference prefixes globally, not demo-specific names.",
            "Keep component references on silkscreen by default.",
            "Keep values in KiCad properties, fabrication layers, and BOM by default; "
            "put values on silkscreen only for educational or showcase output.",
            "Place labels so they do not overlap pads, courtyard outlines, or polarity marks.",
        ],
    }


def ai_planner_annotation_rule_notes() -> list[str]:
    return [
        "Use conventional EDA reference designators: R, C, LED, D, U, J, Q, L, SW, F, K, T, TP.",
        "Keep references on silkscreen; keep values off silkscreen unless "
        "educational/showcase mode asks for them.",
        "Do not use semantic one-off references like RRESET or RLED1 when a normal "
        "sequential reference fits.",
        "Avoid silkscreen overlaps with pads, outlines, polarity marks, and readable "
        "component borders.",
    ]


__all__ = [
    "BoardAnnotationPolicy",
    "DEFAULT_BOARD_ANNOTATION_POLICY",
    "REFERENCE_PREFIXES",
    "ReferenceDesignatorAllocator",
    "ai_planner_annotation_rule_notes",
    "board_annotation_rules_summary",
    "silkscreen_value_enabled",
]
