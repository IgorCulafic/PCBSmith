from __future__ import annotations

import re
from dataclasses import dataclass

from pcbsmith.core.catalog import (
    CatalogEntry,
    CatalogGroup,
    CatalogPreferences,
    CatalogSearchQuery,
    ComponentFamily,
    ComponentVariant,
    DeveloperLibraryProposal,
    MissingPartRequest,
)
from pcbsmith.services.builtin_library import FOOTPRINTS, SYMBOLS

_SEARCH_SPLIT_PATTERN = re.compile(r"[\s-]+")


@dataclass(frozen=True)
class ComponentCatalog:
    groups: tuple[CatalogGroup, ...]
    entries: tuple[CatalogEntry, ...]


def _family(id: str, name: str) -> ComponentFamily:
    return ComponentFamily(id=id, name=name)


def builtin_catalog() -> ComponentCatalog:
    basic_group = CatalogGroup(
        id="basic-components",
        name="Basic Components",
        description="Common passive, power, connector, diode, and switch parts.",
        default_enabled=True,
    )
    entries = (
        CatalogEntry(
            id="pcbs:resistor_0603",
            family=_family("resistor", "Resistor"),
            variant=ComponentVariant(
                name="Resistor 0603",
                package="0603",
                mounting="smd",
                default_value="10k",
            ),
            symbol_id="stdlib:R",
            footprint_id="stdlib:R_0603",
            tags=("basic", "passive", "resistor", "smd", "0603"),
            aliases=("r", "chip resistor", "res 0603"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:capacitor_0603",
            family=_family("capacitor", "Capacitor"),
            variant=ComponentVariant(
                name="Capacitor 0603",
                package="0603",
                mounting="smd",
                default_value="100nF",
            ),
            symbol_id="stdlib:C",
            footprint_id="stdlib:C_0603",
            tags=("basic", "passive", "capacitor", "smd", "0603"),
            aliases=("c", "cap", "chip capacitor"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:led_0603",
            family=_family("led", "LED"),
            variant=ComponentVariant(name="LED 0603", package="0603", mounting="smd"),
            symbol_id="stdlib:LED",
            footprint_id="stdlib:LED_0603",
            tags=("basic", "diode", "indicator", "smd", "0603"),
            aliases=("light emitting diode",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:diode_0603",
            family=_family("diode", "Diode"),
            variant=ComponentVariant(name="Diode 0603", package="0603", mounting="smd"),
            symbol_id="stdlib:D",
            footprint_id="stdlib:D_0603",
            tags=("basic", "diode", "smd", "0603"),
            aliases=("signal diode",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:push_button_th",
            family=_family("push-button", "Push Button"),
            variant=ComponentVariant(
                name="Push Button Through Hole",
                package="TH",
                mounting="through-hole",
            ),
            symbol_id="stdlib:SW_PUSH",
            footprint_id="stdlib:SW_PUSH_TH",
            tags=("basic", "switch", "button", "through-hole"),
            aliases=("momentary switch", "pushbutton"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:switch_spst_th",
            family=_family("switch", "Switch"),
            variant=ComponentVariant(
                name="Switch SPST Through Hole",
                package="TH",
                mounting="through-hole",
            ),
            symbol_id="stdlib:SW_SPST",
            footprint_id="stdlib:SW_SPST_TH",
            tags=("basic", "switch", "spst", "through-hole"),
            aliases=("toggle switch", "single pole single throw"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:pin_header_1x02_p2.54mm",
            family=_family("pin-header", "Pin Header"),
            variant=ComponentVariant(
                name="Pin Header 1x02 P2.54mm",
                package="1x02 P2.54mm",
                mounting="through-hole",
            ),
            symbol_id="stdlib:CONN_01X02",
            footprint_id="stdlib:PinHeader_1x02_P2.54mm",
            tags=("basic", "connector", "pin-header", "through-hole", "p2.54mm"),
            aliases=("header 2 pin", "connector 1x02"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:vcc_power",
            family=_family("power", "Power"),
            variant=ComponentVariant(
                name="VCC Power Flag",
                mounting="virtual",
                default_value="VCC",
            ),
            symbol_id="stdlib:VCC",
            tags=("basic", "power", "vcc", "virtual"),
            aliases=("positive supply",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:gnd_power",
            family=_family("power", "Power"),
            variant=ComponentVariant(
                name="GND Power Flag",
                mounting="virtual",
                default_value="GND",
            ),
            symbol_id="stdlib:GND",
            tags=("basic", "power", "ground", "virtual"),
            aliases=("gnd", "0v"),
            group_ids=("basic-components",),
        ),
    )
    catalog = ComponentCatalog(groups=(basic_group,), entries=entries)
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: ComponentCatalog) -> None:
    group_ids: set[str] = set()
    for group in catalog.groups:
        if group.id in group_ids:
            raise ValueError(f"Duplicate catalog group id: {group.id}")
        group_ids.add(group.id)

    entry_ids: set[str] = set()
    for entry in catalog.entries:
        if entry.id in entry_ids:
            raise ValueError(f"Duplicate catalog entry id: {entry.id}")
        entry_ids.add(entry.id)

        if entry.symbol_id not in SYMBOLS:
            raise ValueError(f"Unknown symbol id for catalog entry {entry.id}: {entry.symbol_id}")
        if entry.footprint_id is not None and entry.footprint_id not in FOOTPRINTS:
            raise ValueError(
                f"Unknown footprint id for catalog entry {entry.id}: {entry.footprint_id}"
            )
        for group_id in entry.group_ids:
            if group_id not in group_ids:
                raise ValueError(f"Unknown group id for catalog entry {entry.id}: {group_id}")


def entry_by_id(catalog: ComponentCatalog, entry_id: str) -> CatalogEntry:
    for entry in catalog.entries:
        if entry.id == entry_id:
            return entry
    raise KeyError(f"Unknown catalog entry: {entry_id}")


def search_catalog(
    catalog: ComponentCatalog,
    query: CatalogSearchQuery,
    *,
    global_preferences: CatalogPreferences | None = None,
    project_preferences: CatalogPreferences | None = None,
) -> tuple[CatalogEntry, ...]:
    preferred_ids = _preferred_entry_ids(catalog, global_preferences, project_preferences)
    text_terms = tuple(term for term in query.text.split("-") if term)

    results: list[CatalogEntry] = []
    for entry in catalog.entries:
        if not entry.normal_user_visible:
            continue
        if query.preferred_only and entry.id not in preferred_ids:
            continue
        if query.group_ids and not (set(entry.group_ids) & set(query.group_ids)):
            continue
        if query.tags and not set(query.tags).issubset(entry.tags):
            continue

        search_tokens = _search_tokens(entry)
        if text_terms and not all(term in search_tokens for term in text_terms):
            continue
        results.append(entry)
    return tuple(results)


def _search_tokens(entry: CatalogEntry) -> set[str]:
    tokens: set[str] = set()
    values = (
        entry.family.name,
        entry.variant.name,
        entry.variant.package or "",
        *entry.tags,
        *entry.aliases,
    )
    for value in values:
        normalized = value.strip().lower().replace("_", "-")
        if not normalized:
            continue
        tokens.add(normalized)
        tokens.update(term for term in _SEARCH_SPLIT_PATTERN.split(normalized) if term)
    return tokens


def _preferred_entry_ids(
    catalog: ComponentCatalog,
    global_preferences: CatalogPreferences | None,
    project_preferences: CatalogPreferences | None,
) -> set[str]:
    enabled_group_ids = {group.id for group in catalog.groups if group.default_enabled}
    visible_entry_ids: set[str] = set()
    hidden_entry_ids: set[str] = set()

    for preferences in (global_preferences, project_preferences):
        if preferences is None:
            continue
        enabled_group_ids.update(preferences.enabled_group_ids)

        hidden_entry_ids.difference_update(preferences.visible_entry_ids)
        visible_entry_ids.update(preferences.visible_entry_ids)

        visible_entry_ids.difference_update(preferences.hidden_entry_ids)
        hidden_entry_ids.update(preferences.hidden_entry_ids)

    preferred_ids = {
        entry.id
        for entry in catalog.entries
        if entry.normal_user_visible and set(entry.group_ids).intersection(enabled_group_ids)
    }
    user_visible_ids = {entry.id for entry in catalog.entries if entry.normal_user_visible}
    preferred_ids.update(visible_entry_ids & user_visible_ids)
    preferred_ids.difference_update(hidden_entry_ids)
    return preferred_ids


def create_missing_part_request(
    requested_name: str, *, reason: str, tags: tuple[str, ...] = ()
) -> MissingPartRequest:
    return MissingPartRequest(
        requested_name=requested_name,
        reason=reason,
        requested_tags=tags,
    )


def create_developer_proposal(
    *,
    requested_name: str,
    proposed_entry_id: str,
    notes: str,
) -> DeveloperLibraryProposal:
    return DeveloperLibraryProposal(
        requested_name=requested_name,
        proposed_entry_id=proposed_entry_id,
        notes=notes,
    )
