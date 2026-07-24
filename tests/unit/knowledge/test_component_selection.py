from __future__ import annotations

from pcbsmith.knowledge.component_knowledge_index import build_component_knowledge_index
from pcbsmith.knowledge.component_selection import (
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
            {"id": "Device:D_Schottky"},
            {"id": "Device:D_Zener"},
            {"id": "Device:Fuse"},
            {"id": "Device:L"},
            {"id": "Device:Buzzer"},
            {"id": "Regulator_Linear:AMS1117-3.3"},
            {"id": "Device:Battery_Cell"},
            {"id": "Switch:SW_Push"},
            {"id": "Device:Crystal"},
            {"id": "MCU_Microchip_ATtiny:ATtiny85-20S"},
            {"id": "Connector:Conn_01x06_Pin"},
            {"id": "Transistor_BJT:Q_NPN_BEC"},
            {"id": "Transistor_BJT:Q_PNP_BEC"},
            {"id": "Comparator:LM393"},
            {"id": "Amplifier_Operational:LM358"},
            {"id": "Connector:Conn_01x02_Pin"},
            {"id": "power:VCC"},
            {"id": "power:GND"},
        ],
        "footprints": [
            {"id": "Resistor_SMD:R_0603_1608Metric"},
            {"id": "Resistor_SMD:R_0805_2012Metric"},
            {"id": "Capacitor_SMD:C_0603_1608Metric"},
            {"id": "Capacitor_SMD:C_0805_2012Metric"},
            {"id": "LED_SMD:LED_0603_1608Metric"},
            {"id": "LED_SMD:LED_0805_2012Metric"},
            {"id": "Diode_SMD:D_0603_1608Metric"},
            {"id": "Diode_SMD:D_SOD-323"},
            {"id": "Inductor_SMD:L_0603_1608Metric"},
            {"id": "Fuse:Fuse_0603_1608Metric"},
            {"id": "Package_TO_SOT_SMD:SOT-223-3_TabPin2"},
            {"id": "Battery:BatteryHolder_LINX_BAT-HLD-012-SMT"},
            {"id": "Button_Switch_SMD:SW_SPST_TL3305A"},
            {"id": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm"},
            {"id": "Package_TO_SOT_SMD:SOT-23"},
            {"id": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"},
            {"id": "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical"},
            {"id": "Buzzer_Beeper:Buzzer_12x9.5RM7.6"},
            {"id": "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"},
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
    assert result["result_count"] == 2
    assert result["warnings"] == []
    assert [candidate["entry_id"] for candidate in result["candidates"]] == [
        "pcbs:resistor_0603",
        "pcbs:resistor_0805",
    ]
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

    assert [candidate["entry_id"] for candidate in result["candidates"]] == ["pcbs:nmos_sot23"]
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


def test_select_components_supports_metal_detector_building_blocks() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    transistor = select_components_for_intent(index, "bjt-npn-amplifier")
    comparator = select_components_for_intent(index, "comparator-threshold")
    buzzer = select_components_for_intent(index, "buzzer-output")
    power = select_components_for_intent(index, "terminal-power-input")

    assert transistor["candidates"][0]["entry_id"] == "pcbs:npn_bjt_sot23"
    assert transistor["candidates"][0]["selection_status"] == "needs_review"
    assert comparator["candidates"][0]["entry_id"] == "pcbs:lm393_soic8"
    assert comparator["candidates"][0]["selection_status"] == "needs_review"
    assert buzzer["candidates"][0]["entry_id"] == "pcbs:active_buzzer_th"
    assert buzzer["warnings"] == [
        "No smd candidates matched; returned other mounting styles instead."
    ]
    assert power["candidates"][0]["entry_id"] == "pcbs:terminal_block_1x02_p5mm"


def test_select_components_supports_controller_and_power_building_blocks() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    regulator = select_components_for_intent(index, "regulated-power")
    battery = select_components_for_intent(index, "battery-power")
    switch = select_components_for_intent(index, "user-input-button")
    controller = select_components_for_intent(index, "microcontroller-8bit")
    header = select_components_for_intent(index, "programming-header")
    crystal = select_components_for_intent(index, "clock-source")
    protection = select_components_for_intent(index, "reverse-polarity-protection")

    assert regulator["candidates"][0]["entry_id"] == "pcbs:ams1117_3v3_sot223"
    assert battery["candidates"][0]["entry_id"] == "pcbs:cr2032_battery_holder_smd"
    assert switch["candidates"][0]["entry_id"] == "pcbs:tactile_switch_smd"
    assert controller["candidates"][0]["entry_id"] == "pcbs:attiny85_soic8"
    assert header["candidates"][0]["entry_id"] == "pcbs:pin_header_1x06_p2.54mm"
    assert crystal["candidates"][0]["entry_id"] == "pcbs:crystal_3225"
    assert protection["candidates"][0]["entry_id"] == "pcbs:schottky_diode_sod323"

    assert header["warnings"] == [
        "No smd candidates matched; returned other mounting styles instead."
    ]
    assert regulator["candidates"][0]["selection_status"] == "needs_review"


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
