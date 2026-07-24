from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pcbsmith.core.catalog import CatalogEntry
from pcbsmith.kicad.kicad_library_index import KICAD_LIBRARY_INDEX_SCHEMA
from pcbsmith.knowledge.component_catalog import ComponentCatalog, builtin_catalog

COMPONENT_KNOWLEDGE_INDEX_SCHEMA = "pcbsmith-component-knowledge-index-v1"
COMPONENT_KNOWLEDGE_SEARCH_SCHEMA = "pcbsmith-component-knowledge-search-v1"

SupportStatus = Literal["well_supported", "metadata_only", "needs_datasheet_review"]
_SUPPORT_STATUSES: tuple[SupportStatus, ...] = (
    "well_supported",
    "metadata_only",
    "needs_datasheet_review",
)


def build_component_knowledge_index(
    *,
    catalog: ComponentCatalog | None = None,
    kicad_library_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kicad_library_index is not None:
        _validate_kicad_library_index(kicad_library_index)

    component_catalog = catalog or builtin_catalog()
    entries = [
        _knowledge_entry(entry, kicad_library_index)
        for entry in component_catalog.entries
        if entry.normal_user_visible
    ]
    families = _family_summaries(entries)
    coverage = _support_status_counts(entries)
    mounting = _mounting_counts(entries)
    return {
        "schema": COMPONENT_KNOWLEDGE_INDEX_SCHEMA,
        "source_catalog": "builtin",
        "source_kicad_index_schema": (
            kicad_library_index.get("schema") if kicad_library_index is not None else None
        ),
        "tier1_core": entries,
        "families": families,
        "coverage_summary": coverage,
        "mounting_summary": mounting,
    }


def write_component_knowledge_index(
    output_path: Path,
    *,
    kicad_library_index_path: Path | None = None,
) -> dict[str, Any]:
    kicad_library_index = None
    if kicad_library_index_path is not None:
        loaded = json.loads(kicad_library_index_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(
                f"Expected KiCad library index JSON object: {kicad_library_index_path}"
            )
        kicad_library_index = loaded

    index = build_component_knowledge_index(kicad_library_index=kicad_library_index)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index


def format_component_knowledge_index_summary(
    index: dict[str, Any],
    *,
    output_path: Path,
) -> list[str]:
    coverage = index["coverage_summary"]
    return [
        f"Wrote component knowledge index to {output_path}",
        f"Tier 1 entries: {len(index['tier1_core'])}",
        f"Families: {len(index['families'])}",
        "Coverage: "
        f"well_supported={coverage['well_supported']}, "
        f"metadata_only={coverage['metadata_only']}, "
        f"needs_datasheet_review={coverage['needs_datasheet_review']}",
        "Mounting: "
        f"smd={index['mounting_summary']['smd']}, "
        f"through-hole={index['mounting_summary']['through-hole']}, "
        f"virtual={index['mounting_summary']['virtual']}, "
        f"unspecified={index['mounting_summary']['unspecified']}",
    ]


def search_component_knowledge_index(
    index: dict[str, Any],
    *,
    query: str = "",
    mounting: str | None = None,
    support_status: SupportStatus | None = None,
    tags: tuple[str, ...] = (),
    limit: int = 10,
) -> dict[str, Any]:
    _validate_component_knowledge_index(index)
    if limit < 1:
        raise ValueError("Search limit must be at least 1")

    query_terms = _search_terms(query)
    tag_terms = tuple(_normalize_search_value(tag) for tag in tags)
    results = []
    for entry in index["tier1_core"]:
        if mounting is not None and entry["mounting_style"] != mounting:
            continue
        if support_status is not None and entry["support_status"] != support_status:
            continue
        if tag_terms and not set(tag_terms).issubset(entry["tags"]):
            continue
        tokens = _entry_search_tokens(entry)
        if query_terms and not all(term in tokens for term in query_terms):
            continue
        results.append(_compact_search_entry(entry))
        if len(results) >= limit:
            break

    return {
        "schema": COMPONENT_KNOWLEDGE_SEARCH_SCHEMA,
        "query": query,
        "filters": {
            "mounting": mounting,
            "support_status": support_status,
            "tags": list(tag_terms),
            "limit": limit,
        },
        "result_count": len(results),
        "results": results,
    }


def search_component_knowledge_index_file(
    index_path: Path,
    *,
    query: str = "",
    mounting: str | None = None,
    support_status: SupportStatus | None = None,
    tags: tuple[str, ...] = (),
    limit: int = 10,
) -> dict[str, Any]:
    loaded = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected component knowledge index JSON object: {index_path}")
    return search_component_knowledge_index(
        loaded,
        query=query,
        mounting=mounting,
        support_status=support_status,
        tags=tags,
        limit=limit,
    )


def format_component_knowledge_search_result(result: dict[str, Any]) -> list[str]:
    lines = [
        f"Component knowledge search: {result['query'] or '(all)'}",
        f"Matches: {result['result_count']}",
    ]
    for entry in result["results"]:
        lines.append(
            f"{entry['entry_id']} | {entry['variant_name']} | "
            f"{entry['mounting_style']} | {entry['support_status']} | "
            f"tags: {', '.join(entry['tags'])}"
        )
    if not result["results"]:
        lines.append("No component knowledge matches.")
    return lines


def _knowledge_entry(
    entry: CatalogEntry,
    kicad_library_index: dict[str, Any] | None,
) -> dict[str, Any]:
    status, notes = _support_status(entry, kicad_library_index)
    return {
        "entry_id": entry.id,
        "family_id": entry.family.id,
        "family_name": entry.family.name,
        "variant_name": entry.variant.name,
        "package": entry.variant.package,
        "mounting": entry.variant.mounting,
        "mounting_style": entry.variant.mounting or "unspecified",
        "preferred_mounting": entry.variant.mounting == "smd",
        "default_value": entry.variant.default_value,
        "tags": list(entry.tags),
        "aliases": list(entry.aliases),
        "local_symbol_id": entry.symbol_id,
        "local_footprint_id": entry.footprint_id,
        "kicad_symbol_id": entry.kicad.symbol_id if entry.kicad is not None else None,
        "kicad_footprint_id": entry.kicad.footprint_id if entry.kicad is not None else None,
        "support_status": status,
        "support_notes": notes,
    }


def _support_status(
    entry: CatalogEntry,
    kicad_library_index: dict[str, Any] | None,
) -> tuple[SupportStatus, list[str]]:
    if entry.kicad is None:
        return "metadata_only", ["No KiCad binding yet"]
    if kicad_library_index is None:
        return "metadata_only", ["KiCad availability not checked"]

    symbol_ids = _ids(kicad_library_index.get("symbols", []))
    footprint_ids = _ids(kicad_library_index.get("footprints", []))
    symbol_available = entry.kicad.symbol_id in symbol_ids
    footprint_available = (
        True if entry.kicad.footprint_id is None else entry.kicad.footprint_id in footprint_ids
    )

    if symbol_available and footprint_available:
        notes = (
            ["KiCad symbol found"]
            if entry.kicad.footprint_id is None
            else ["KiCad symbol and footprint found"]
        )
        return "well_supported", notes

    notes = [f"KiCad symbol {'found' if symbol_available else 'missing'}"]
    if entry.kicad.footprint_id is not None:
        notes.append(f"KiCad footprint {'found' if footprint_available else 'missing'}")
    return "needs_datasheet_review", notes


def _family_summaries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        family_entries[entry["family_id"]].append(entry)

    summaries = []
    for family_id, grouped_entries in sorted(family_entries.items()):
        support_counts = _support_status_counts(grouped_entries)
        summaries.append(
            {
                "family_id": family_id,
                "family_name": grouped_entries[0]["family_name"],
                "entry_count": len(grouped_entries),
                "entry_ids": sorted(entry["entry_id"] for entry in grouped_entries),
                "tags": _sorted_non_null_values(
                    tag for entry in grouped_entries for tag in entry["tags"]
                ),
                "packages": _sorted_non_null_values(
                    entry["package"] for entry in grouped_entries
                ),
                "mountings": _sorted_non_null_values(
                    entry["mounting"] for entry in grouped_entries
                ),
                "support_status_counts": support_counts,
            }
        )
    return summaries


def _support_status_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(entry["support_status"] for entry in entries)
    return {status: counter[status] for status in _SUPPORT_STATUSES}


def _mounting_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(entry["mounting_style"] for entry in entries)
    return {
        "smd": counter["smd"],
        "through-hole": counter["through-hole"],
        "virtual": counter["virtual"],
        "unspecified": counter["unspecified"],
    }


def _sorted_non_null_values(values: Iterable[object]) -> list[str]:
    return sorted({value for value in values if isinstance(value, str) and value})


def _ids(entries: object) -> set[str]:
    if not isinstance(entries, list):
        return set()
    return {
        entry["id"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }


def _validate_kicad_library_index(index: dict[str, Any]) -> None:
    if index.get("schema") != KICAD_LIBRARY_INDEX_SCHEMA:
        raise ValueError(f"Unsupported KiCad library index schema: {index.get('schema')}")


def _validate_component_knowledge_index(index: dict[str, Any]) -> None:
    if index.get("schema") != COMPONENT_KNOWLEDGE_INDEX_SCHEMA:
        raise ValueError(
            f"Unsupported component knowledge index schema: {index.get('schema')}"
        )
    if not isinstance(index.get("tier1_core"), list):
        raise ValueError("Component knowledge index is missing tier1_core entries")


def _compact_search_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": entry["entry_id"],
        "family_id": entry["family_id"],
        "family_name": entry["family_name"],
        "variant_name": entry["variant_name"],
        "package": entry["package"],
        "mounting_style": entry["mounting_style"],
        "preferred_mounting": entry["preferred_mounting"],
        "default_value": entry["default_value"],
        "tags": entry["tags"],
        "support_status": entry["support_status"],
        "kicad_symbol_id": entry["kicad_symbol_id"],
        "kicad_footprint_id": entry["kicad_footprint_id"],
    }


def _entry_search_tokens(entry: dict[str, Any]) -> set[str]:
    values = (
        entry["entry_id"],
        entry["family_id"],
        entry["family_name"],
        entry["variant_name"],
        entry["package"] or "",
        entry["mounting_style"],
        entry["default_value"] or "",
        *(entry["tags"] or []),
        *(entry["aliases"] or []),
    )
    tokens: set[str] = set()
    for value in values:
        tokens.update(_search_terms(str(value)))
    return tokens


def _search_terms(value: str) -> tuple[str, ...]:
    normalized = _normalize_search_value(value)
    if not normalized:
        return ()
    return tuple(term for term in re.split(r"[-\s]+", normalized) if term)


def _normalize_search_value(value: str) -> str:
    return re.sub(r"[\s_]+", "-", value.strip().lower())


__all__ = [
    "COMPONENT_KNOWLEDGE_INDEX_SCHEMA",
    "COMPONENT_KNOWLEDGE_SEARCH_SCHEMA",
    "build_component_knowledge_index",
    "format_component_knowledge_index_summary",
    "format_component_knowledge_search_result",
    "search_component_knowledge_index",
    "search_component_knowledge_index_file",
    "write_component_knowledge_index",
]
