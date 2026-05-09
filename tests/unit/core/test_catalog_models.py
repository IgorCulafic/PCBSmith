from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.core.catalog import (
    CatalogEntry,
    CatalogSearchQuery,
    ComponentFamily,
    ComponentVariant,
    DeveloperLibraryProposal,
    MissingPartRequest,
    PreferredPartsProfile,
    normalize_tag,
)


def test_normalize_tag_lowercases_trims_and_hyphenates() -> None:
    assert normalize_tag("Through Hole") == "through-hole"
    assert normalize_tag("  P2.54MM  ") == "p2.54mm"
    assert normalize_tag("SMD") == "smd"


def test_catalog_entry_normalizes_tags_aliases_and_search_text() -> None:
    entry = CatalogEntry(
        id=" PCBS:R_0603 ",
        family=ComponentFamily(id="resistor", name="Resistor"),
        variant=ComponentVariant(name="Resistor 0603", package="0603"),
        symbol_id="stdlib:R",
        tags=("Passive", "SMD", "0603", "Passive"),
        aliases=("Basic", "Chip Resistor", "R 0603", "Basic"),
        group_ids=("Basic",),
    )

    assert entry.id == "pcbs:r_0603"
    assert entry.tags == ("passive", "smd", "0603")
    assert entry.aliases == ("basic", "chip-resistor", "r-0603")
    assert (
        entry.search_text
        == "Resistor Resistor 0603 0603 passive smd 0603 basic chip-resistor r-0603"
    )


def test_catalog_entry_rejects_non_namespaced_id() -> None:
    with pytest.raises(ValidationError, match="Catalog ids must be namespaced"):
        CatalogEntry(
            id="resistor_0603",
            family=ComponentFamily(id="resistor", name="Resistor"),
            variant=ComponentVariant(name="Resistor 0603"),
            symbol_id="pcbs:resistor",
        )


def test_preferred_parts_profile_dedupes_group_and_entry_ids() -> None:
    profile = PreferredPartsProfile(
        enabled_group_ids=("Basic Components", "basic_components"),
        visible_entry_ids=(" PCBS:R_0603 ",),
        hidden_entry_ids=(" PCBS:LED_0603 ", "pcbs:led_0603"),
    )

    assert profile.enabled_group_ids == ("basic-components",)
    assert profile.visible_entry_ids == ("pcbs:r_0603",)
    assert profile.hidden_entry_ids == ("pcbs:led_0603",)


def test_catalog_search_query_normalizes_text_and_tags() -> None:
    query = CatalogSearchQuery(text=" Through Hole LED ", tags=("Basic", "P2.54MM"))

    assert query.text == "through-hole-led"
    assert query.tags == ("basic", "p2.54mm")


def test_missing_part_request_normalizes_requested_tags() -> None:
    request = MissingPartRequest(
        requested_name="NE555",
        reason="Needed for a timer circuit",
        requested_tags=("IC", "DIP-8"),
    )

    assert request.requested_tags == ("ic", "dip-8")


def test_missing_part_request_requires_reason() -> None:
    with pytest.raises(ValidationError):
        MissingPartRequest(requested_name="NE555")


def test_developer_library_proposal_defaults_to_draft() -> None:
    proposal = DeveloperLibraryProposal(
        requested_name="NE555",
        proposed_entry_id=" PCBS:NE555_DIP8 ",
    )

    assert proposal.proposed_entry_id == "pcbs:ne555_dip8"
    assert proposal.status == "draft"
