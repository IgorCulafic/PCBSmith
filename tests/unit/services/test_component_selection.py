from __future__ import annotations

from pcbsmith.services.component_knowledge_index import build_component_knowledge_index
from pcbsmith.services.component_selection import (
    COMPONENT_SELECTION_SCHEMA,
    format_component_selection_result,
    select_components_for_intent,
)


def _library_index() -> dict[str, object]:
    return {
        "schema": "pcbsmith-kicad-library-index-v1",
        "symbols": [
            {"id": "Device:R"},
            {"id": "Device:C"},
            {"id": "Device:LED"},
            {"id": "Device:D"},
            {"id": "Device:D_Zener"},
            {"id": "Device:Fuse"},
            {"id": "Device:L"},
            {"id": "power:VCC"},
            {"id": "power:GND"},
        ],
        "footprints": [
            {"id": "Resistor_SMD:R_0603_1608Metric"},
            {"id": "Capacitor_SMD:C_0603_1608Metric"},
            {"id": "LED_SMD:LED_0603_1608Metric"},
            {"id": "Diode_SMD:D_0603_1608Metric"},
            {"id": "Inductor_SMD:L_0603_1608Metric"},
            {"id": "Fuse:Fuse_0603_1608Metric"},
        ],
    }


def test_select_components_prefers_supported_smd_led_current_limit_part() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    result = select_components_for_intent(
        index,
        "led-current-limit",
        preferred_mounting="smd",
        limit=3,
    )

    assert result["schema"] == COMPONENT_SELECTION_SCHEMA
    assert result["intent"] == "led-current-limit"
    assert result["result_count"] == 1
    assert result["warnings"] == []
    assert result["candidates"][0] == {
        "rank": 1,
        "entry_id": "pcbs:resistor_0603",
        "family_id": "resistor",
        "family_name": "Resistor",
        "variant_name": "Resistor 0603",
        "package": "0603",
        "mounting_style": "smd",
        "preferred_mounting": True,
        "default_value": "10k",
        "tags": ["basic", "passive", "resistor", "smd", "0603"],
        "support_status": "well_supported",
        "kicad_symbol_id": "Device:R",
        "kicad_footprint_id": "Resistor_SMD:R_0603_1608Metric",
        "selection_status": "preferred",
        "reasons": [
            "Matches intent led-current-limit",
            "Matches required tags: resistor",
            "Uses preferred mounting: smd",
        ],
        "warnings": [],
    }


def test_select_components_flags_metadata_only_switching_parts_for_review() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    result = select_components_for_intent(index, "low-side-switch")

    assert [candidate["entry_id"] for candidate in result["candidates"]] == [
        "pcbs:nmos_sot23"
    ]
    candidate = result["candidates"][0]
    assert candidate["selection_status"] == "needs_review"
    assert candidate["warnings"] == [
        (
            "KiCad availability is not confirmed; resolve symbol and footprint "
            "before automated placement."
        ),
        "Verify Vgs(th), Rds(on), current rating, package heat, and gate drive before fabrication.",
    ]
    assert result["next_checks"] == [
        "Confirm load current and supply voltage.",
        "Confirm gate-drive voltage fully enhances the selected MOSFET.",
        "Add flyback protection for inductive loads.",
    ]


def test_select_components_falls_back_when_preferred_mounting_has_no_match() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    result = select_components_for_intent(index, "relay-switching")

    assert result["warnings"] == [
        "No smd candidates matched; returned other mounting styles instead."
    ]
    candidate = result["candidates"][0]
    assert candidate["entry_id"] == "pcbs:relay_spdt_th"
    assert candidate["selection_status"] == "needs_review"
    assert candidate["warnings"] == [
        (
            "KiCad availability is not confirmed; resolve symbol and footprint "
            "before automated placement."
        ),
        "Safety-sensitive component; require datasheet and human review before automated use.",
        "Verify coil voltage/current, contact ratings, isolation, and flyback protection.",
    ]


def test_format_component_selection_result_is_compact_for_ai_prompts() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())
    result = select_components_for_intent(index, "zener-protection")

    assert format_component_selection_result(result) == [
        "Component selection: zener-protection",
        "Preferred mounting: smd",
        "Matches: 1",
        "1. pcbs:zener_0603 | Zener Diode 0603 | smd | well_supported | preferred",
        (
            "   reasons: Matches intent zener-protection; Matches required tags: "
            "zener, protection; Uses preferred mounting: smd"
        ),
        (
            "Next checks: Choose breakdown voltage and power rating for the "
            "protected net.; Confirm clamp current path and series impedance."
        ),
    ]
