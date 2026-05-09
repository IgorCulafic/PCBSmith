from __future__ import annotations

import pytest

from pcbsmith.core.catalog import CatalogGroup, CatalogPreferences, CatalogSearchQuery
from pcbsmith.services.component_catalog import (
    ComponentCatalog,
    builtin_catalog,
    create_developer_proposal,
    create_missing_part_request,
    entry_by_id,
    search_catalog,
    validate_catalog,
)


def _entry_ids(entries: object) -> list[str]:
    return [entry.id for entry in entries]


def test_builtin_catalog_contains_basic_component_entries() -> None:
    catalog = builtin_catalog()

    assert {
        "pcbs:resistor_0603",
        "pcbs:capacitor_0603",
        "pcbs:led_0603",
        "pcbs:diode_0603",
        "pcbs:push_button_th",
        "pcbs:switch_spst_th",
        "pcbs:pin_header_1x02_p2.54mm",
    } <= {entry.id for entry in catalog.entries}


def test_builtin_catalog_validates() -> None:
    validate_catalog(builtin_catalog())


def test_validate_catalog_rejects_duplicate_group_ids() -> None:
    catalog = ComponentCatalog(
        groups=(
            CatalogGroup(id="basic-components", name="Basic Components"),
            CatalogGroup(id="basic-components", name="Duplicate Basic Components"),
        ),
        entries=(),
    )

    with pytest.raises(ValueError, match="Duplicate catalog group"):
        validate_catalog(catalog)


def test_search_catalog_matches_text_package_tags_and_aliases() -> None:
    catalog = builtin_catalog()

    assert search_catalog(catalog, CatalogSearchQuery(text="0603"))
    assert _entry_ids(search_catalog(catalog, CatalogSearchQuery(text="led"))) == [
        "pcbs:led_0603"
    ]
    assert _entry_ids(search_catalog(catalog, CatalogSearchQuery(text="button"))) == [
        "pcbs:push_button_th"
    ]
    assert search_catalog(catalog, CatalogSearchQuery(tags=("smd",)))
    assert search_catalog(catalog, CatalogSearchQuery(text="through hole"))


def test_search_catalog_group_filter_matches_any_requested_group() -> None:
    results = search_catalog(
        builtin_catalog(),
        CatalogSearchQuery(group_ids=("basic-components", "other-group")),
    )

    assert "pcbs:resistor_0603" in _entry_ids(results)


def test_search_catalog_preferred_only_uses_default_and_project_preferences() -> None:
    catalog = builtin_catalog()
    project_preferences = CatalogPreferences(
        enabled_group_ids=("basic-components",),
        hidden_entry_ids=("pcbs:led_0603",),
    )

    results = search_catalog(
        catalog,
        CatalogSearchQuery(preferred_only=True),
        project_preferences=project_preferences,
    )

    ids = _entry_ids(results)
    assert "pcbs:resistor_0603" in ids
    assert "pcbs:led_0603" not in ids


def test_search_catalog_project_visible_overrides_global_hidden() -> None:
    results = search_catalog(
        builtin_catalog(),
        CatalogSearchQuery(preferred_only=True),
        global_preferences=CatalogPreferences(hidden_entry_ids=("pcbs:led_0603",)),
        project_preferences=CatalogPreferences(visible_entry_ids=("pcbs:led_0603",)),
    )

    assert "pcbs:led_0603" in _entry_ids(results)


def test_search_catalog_project_hidden_overrides_global_visible() -> None:
    results = search_catalog(
        builtin_catalog(),
        CatalogSearchQuery(preferred_only=True),
        global_preferences=CatalogPreferences(visible_entry_ids=("pcbs:led_0603",)),
        project_preferences=CatalogPreferences(hidden_entry_ids=("pcbs:led_0603",)),
    )

    assert "pcbs:led_0603" not in _entry_ids(results)


def test_entry_by_id_raises_for_unknown_entry() -> None:
    with pytest.raises(KeyError, match="Unknown catalog entry"):
        entry_by_id(builtin_catalog(), "pcbs:missing")


def test_create_missing_part_request_returns_requested_fields() -> None:
    request = create_missing_part_request(
        "NE555 DIP-8",
        reason="Timer IC is not in the catalog",
        tags=("ic", "dip-8"),
    )

    assert request.requested_name == "NE555 DIP-8"
    assert request.requested_tags == ("ic", "dip-8")


def test_create_developer_proposal() -> None:
    proposal = create_developer_proposal(
        requested_name="NE555 DIP-8",
        proposed_entry_id="pcbs:ne555_dip8",
        notes="Needs exact pin map before normal-user placement.",
    )

    assert proposal.requested_name == "NE555 DIP-8"
    assert proposal.proposed_entry_id == "pcbs:ne555_dip8"
    assert proposal.notes == "Needs exact pin map before normal-user placement."
    assert proposal.status == "draft"


def test_developer_proposal_rejects_non_namespaced_id() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        create_developer_proposal(
            requested_name="Bad",
            proposed_entry_id="bad",
            notes="Invalid id",
        )
