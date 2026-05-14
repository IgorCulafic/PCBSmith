from __future__ import annotations

from pcbsmith.services.board_conventions import (
    BoardAnnotationPolicy,
    ReferenceDesignatorAllocator,
    ai_planner_annotation_rule_notes,
    board_annotation_rules_summary,
    silkscreen_value_enabled,
)


def test_reference_designator_allocator_uses_eda_prefix_conventions() -> None:
    allocator = ReferenceDesignatorAllocator()

    assert allocator.next("resistor") == "R1"
    assert allocator.next("resistor") == "R2"
    assert allocator.next("capacitor") == "C1"
    assert allocator.next("led") == "LED1"
    assert allocator.next("diode") == "D1"
    assert allocator.next("ic") == "U1"
    assert allocator.next("connector") == "J1"
    assert allocator.next("transistor") == "Q1"
    assert allocator.next("inductor") == "L1"
    assert allocator.next("switch") == "SW1"
    assert allocator.next("fuse") == "F1"
    assert allocator.next("relay") == "K1"
    assert allocator.next("transformer") == "T1"


def test_reference_designator_allocator_accepts_explicit_prefixes() -> None:
    allocator = ReferenceDesignatorAllocator()

    assert allocator.next_prefix("TP") == "TP1"
    assert allocator.next_prefix("TP") == "TP2"


def test_board_annotation_policy_keeps_values_off_silkscreen_by_default() -> None:
    assert not silkscreen_value_enabled(BoardAnnotationPolicy())
    assert silkscreen_value_enabled(
        BoardAnnotationPolicy(show_values_on_silkscreen=True)
    )


def test_board_annotation_rules_summary_is_ai_facing_best_practice_contract() -> None:
    assert board_annotation_rules_summary() == {
        "reference_designators": {
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
        },
        "silkscreen_defaults": {
            "show_references": True,
            "show_values": False,
            "value_default_destination": "fabrication_layers_and_bom",
        },
        "notes": [
            "Use conventional EDA reference prefixes globally, not demo-specific names.",
            "Keep component references on silkscreen by default.",
            "Keep values in KiCad properties, fabrication layers, and BOM by default; "
            "put values on silkscreen only for educational or showcase output.",
            "Place labels so they do not overlap pads, courtyard outlines, or polarity marks.",
        ],
    }


def test_ai_planner_annotation_rule_notes_share_the_same_contract() -> None:
    assert ai_planner_annotation_rule_notes() == [
        "Use conventional EDA reference designators: R, C, LED, D, U, J, Q, L, SW, F, K, T, TP.",
        "Keep references on silkscreen; keep values off silkscreen unless "
        "educational/showcase mode asks for them.",
        "Do not use semantic one-off references like RRESET or RLED1 when a normal "
        "sequential reference fits.",
        "Avoid silkscreen overlaps with pads, outlines, polarity marks, and readable "
        "component borders.",
    ]
