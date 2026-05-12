from __future__ import annotations

import pytest

from pcbsmith.core.catalog import (
    CatalogEntry,
    CatalogGroup,
    CatalogPreferences,
    CatalogSearchQuery,
    ComponentFamily,
    ComponentVariant,
)
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
        "pcbs:fuse_0603",
        "pcbs:inductor_0603",
        "pcbs:zener_0603",
        "pcbs:photoresistor_th",
        "pcbs:potentiometer_3pin_smd",
        "pcbs:potentiometer_3pin_th",
        "pcbs:nmos_sot23",
        "pcbs:ne555_soic8",
        "pcbs:relay_spdt_th",
        "pcbs:transformer_th",
    } <= {entry.id for entry in catalog.entries}


def test_builtin_catalog_marks_smd_and_through_hole_variants_explicitly() -> None:
    catalog = builtin_catalog()

    assert entry_by_id(catalog, "pcbs:potentiometer_3pin_smd").variant.mounting == "smd"
    assert (
        entry_by_id(catalog, "pcbs:potentiometer_3pin_th").variant.mounting
        == "through-hole"
    )
    assert "smd" in entry_by_id(catalog, "pcbs:nmos_sot23").tags
    assert "through-hole" in entry_by_id(catalog, "pcbs:relay_spdt_th").tags


def test_builtin_catalog_entries_include_kicad_bindings() -> None:
    catalog = builtin_catalog()
    resistor = entry_by_id(catalog, "pcbs:resistor_0603")
    led = entry_by_id(catalog, "pcbs:led_0603")
    vcc = entry_by_id(catalog, "pcbs:vcc_power")

    assert resistor.kicad is not None
    assert resistor.kicad.symbol_id == "Device:R"
    assert resistor.kicad.footprint_id == "Resistor_SMD:R_0603_1608Metric"
    assert led.kicad is not None
    assert led.kicad.symbol_id == "Device:LED"
    assert vcc.kicad is not None
    assert vcc.kicad.symbol_id == "power:VCC"
    assert vcc.kicad.footprint_id is None


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
    assert _entry_ids(search_catalog(catalog, CatalogSearchQuery(text="zener"))) == [
        "pcbs:zener_0603"
    ]
    assert {
        "pcbs:potentiometer_3pin_smd",
        "pcbs:potentiometer_3pin_th",
    } <= set(_entry_ids(search_catalog(catalog, CatalogSearchQuery(text="pot"))))


def test_search_catalog_matches_short_aliases_exactly() -> None:
    catalog = builtin_catalog()

    assert _entry_ids(search_catalog(catalog, CatalogSearchQuery(text="r"))) == [
        "pcbs:resistor_0603"
    ]
    assert _entry_ids(search_catalog(catalog, CatalogSearchQuery(text="c"))) == [
        "pcbs:capacitor_0603"
    ]


def test_search_catalog_excludes_non_user_visible_entries() -> None:
    hidden_entry = CatalogEntry(
        id="pcbs:hidden_dev_part",
        family=ComponentFamily(id="developer", name="Developer"),
        variant=ComponentVariant(name="Hidden Developer Part"),
        symbol_id="stdlib:R",
        tags=("hidden",),
        group_ids=("basic-components",),
        normal_user_visible=False,
    )
    catalog = ComponentCatalog(
        groups=builtin_catalog().groups,
        entries=(*builtin_catalog().entries, hidden_entry),
    )

    assert _entry_ids(search_catalog(catalog, CatalogSearchQuery(text="hidden"))) == []


def test_preferred_search_cannot_force_non_user_visible_entries_visible() -> None:
    hidden_entry = CatalogEntry(
        id="pcbs:hidden_dev_part",
        family=ComponentFamily(id="developer", name="Developer"),
        variant=ComponentVariant(name="Hidden Developer Part"),
        symbol_id="stdlib:R",
        tags=("hidden",),
        group_ids=("basic-components",),
        normal_user_visible=False,
    )
    catalog = ComponentCatalog(
        groups=builtin_catalog().groups,
        entries=(*builtin_catalog().entries, hidden_entry),
    )

    results = search_catalog(
        catalog,
        CatalogSearchQuery(preferred_only=True),
        project_preferences=CatalogPreferences(
            visible_entry_ids=("pcbs:hidden_dev_part",)
        ),
    )

    assert "pcbs:hidden_dev_part" not in _entry_ids(results)


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
