from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.knowledge.component_knowledge_index import (
    COMPONENT_KNOWLEDGE_INDEX_SCHEMA,
    build_component_knowledge_index,
    format_component_knowledge_index_summary,
    format_component_knowledge_search_result,
    search_component_knowledge_index,
    write_component_knowledge_index,
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


def test_build_component_knowledge_index_summarizes_core_supported_parts() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    assert index["schema"] == COMPONENT_KNOWLEDGE_INDEX_SCHEMA
    assert index["source_catalog"] == "builtin"
    assert index["coverage_summary"] == {
        "well_supported": 9,
        "metadata_only": 10,
        "needs_datasheet_review": 6,
    }
    assert index["mounting_summary"] == {
        "smd": 14,
        "through-hole": 9,
        "virtual": 2,
        "unspecified": 0,
    }

    entries = {entry["entry_id"]: entry for entry in index["tier1_core"]}
    assert entries["pcbs:resistor_0603"] == {
        "entry_id": "pcbs:resistor_0603",
        "family_id": "resistor",
        "family_name": "Resistor",
        "variant_name": "Resistor 0603",
        "package": "0603",
        "mounting": "smd",
        "mounting_style": "smd",
        "preferred_mounting": True,
        "default_value": "10k",
        "tags": ["basic", "passive", "resistor", "smd", "0603"],
        "aliases": ["r", "chip-resistor", "res-0603"],
        "local_symbol_id": "stdlib:R",
        "local_footprint_id": "stdlib:R_0603",
        "kicad_symbol_id": "Device:R",
        "kicad_footprint_id": "Resistor_SMD:R_0603_1608Metric",
        "support_status": "well_supported",
        "support_notes": ["KiCad symbol and footprint found"],
    }
    assert entries["pcbs:push_button_th"]["support_status"] == "metadata_only"
    assert entries["pcbs:vcc_power"]["support_notes"] == ["KiCad symbol found"]
    assert entries["pcbs:potentiometer_3pin_smd"]["mounting_style"] == "smd"
    assert entries["pcbs:potentiometer_3pin_th"]["mounting_style"] == "through-hole"
    assert entries["pcbs:relay_spdt_th"]["support_status"] == "metadata_only"
    assert entries["pcbs:lm393_soic8"]["support_status"] == "needs_datasheet_review"
    assert entries["pcbs:npn_bjt_sot23"]["support_notes"] == [
        "KiCad symbol missing",
        "KiCad footprint missing",
    ]


def test_build_component_knowledge_index_groups_entries_by_family() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    families = {family["family_id"]: family for family in index["families"]}
    assert families["power"] == {
        "family_id": "power",
        "family_name": "Power",
        "entry_count": 2,
        "entry_ids": ["pcbs:gnd_power", "pcbs:vcc_power"],
        "tags": ["basic", "ground", "power", "vcc", "virtual"],
        "packages": [],
        "mountings": ["virtual"],
        "support_status_counts": {
            "well_supported": 2,
            "metadata_only": 0,
            "needs_datasheet_review": 0,
        },
    }


def test_build_component_knowledge_index_marks_missing_bound_parts_for_review() -> None:
    index = build_component_knowledge_index(
        kicad_library_index={
            "schema": "pcbsmith-kicad-library-index-v1",
            "symbols": [{"id": "Device:R"}],
            "footprints": [],
        }
    )

    entries = {entry["entry_id"]: entry for entry in index["tier1_core"]}
    assert entries["pcbs:resistor_0603"]["support_status"] == "needs_datasheet_review"
    assert entries["pcbs:resistor_0603"]["support_notes"] == [
        "KiCad symbol found",
        "KiCad footprint missing",
    ]


def test_write_component_knowledge_index_and_format_summary(tmp_path: Path) -> None:
    index_path = tmp_path / "kicad-index.json"
    output_path = tmp_path / "component-knowledge.json"
    index_path.write_text(json.dumps(_library_index()), encoding="utf-8")

    index = write_component_knowledge_index(
        output_path,
        kicad_library_index_path=index_path,
    )

    assert json.loads(output_path.read_text(encoding="utf-8")) == index
    assert format_component_knowledge_index_summary(index, output_path=output_path) == [
        f"Wrote component knowledge index to {output_path}",
        "Tier 1 entries: 25",
        "Families: 22",
        "Coverage: well_supported=9, metadata_only=10, needs_datasheet_review=6",
        "Mounting: smd=14, through-hole=9, virtual=2, unspecified=0",
    ]


def test_search_component_knowledge_index_returns_compact_ai_results() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    result = search_component_knowledge_index(
        index,
        query="zener protection",
        mounting="smd",
        limit=3,
    )

    assert result == {
        "schema": "pcbsmith-component-knowledge-search-v1",
        "query": "zener protection",
        "filters": {
            "mounting": "smd",
            "support_status": None,
            "tags": [],
            "limit": 3,
        },
        "result_count": 1,
        "results": [
            {
                "entry_id": "pcbs:zener_0603",
                "family_id": "zener-diode",
                "family_name": "Zener Diode",
                "variant_name": "Zener Diode 0603",
                "package": "0603",
                "mounting_style": "smd",
                "preferred_mounting": True,
                "default_value": "3.3V",
                "tags": ["basic", "diode", "zener", "protection", "smd", "0603"],
                "support_status": "well_supported",
                "kicad_symbol_id": "Device:D_Zener",
                "kicad_footprint_id": "Diode_SMD:D_0603_1608Metric",
            }
        ],
    }
    assert format_component_knowledge_search_result(result) == [
        "Component knowledge search: zener protection",
        "Matches: 1",
        (
            "pcbs:zener_0603 | Zener Diode 0603 | smd | "
            "well_supported | tags: basic, diode, zener, protection, smd, 0603"
        ),
    ]


def test_search_component_knowledge_index_filters_support_status_and_tags() -> None:
    index = build_component_knowledge_index(kicad_library_index=_library_index())

    result = search_component_knowledge_index(
        index,
        query="relay",
        support_status="metadata_only",
        tags=("needs-safety-review",),
    )

    assert [entry["entry_id"] for entry in result["results"]] == ["pcbs:relay_spdt_th"]
