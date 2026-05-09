from __future__ import annotations

from pcbsmith.core.catalog import (
    CatalogEntry,
    CatalogPreferences,
    ComponentFamily,
    ComponentVariant,
)
from pcbsmith.core.geom import Point
from pcbsmith.services import component_catalog, project_io
from pcbsmith.services.component_catalog import ComponentCatalog
from pcbsmith.ui.component_browser import ComponentBrowser
from pcbsmith.ui.main_window import MainWindow
from pcbsmith.ui.schematic_scene import SchematicScene


def _toolbar_action(window: MainWindow, text: str):
    for action in window.schematic_toolbar.actions():
        if action.text() == text:
            return action
    raise AssertionError(f"Toolbar action not found: {text}")


def test_scene_places_catalog_component(qtbot) -> None:
    scene = SchematicScene()
    catalog = component_catalog.builtin_catalog()
    entry = component_catalog.entry_by_id(catalog, "pcbs:capacitor_0603")

    item = scene.place_catalog_entry(entry, Point(x=0, y=0))

    symbol = scene.editor_state.symbols[0]
    assert item.symbol.reference == "C1"
    assert symbol.symbol_id == "stdlib:C"
    assert symbol.value == "100nF"
    assert symbol.footprint_id == "stdlib:C_0603"


def test_component_browser_filters_by_search_text(qtbot) -> None:
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    browser.search_box.setText("led")

    assert browser.visible_entry_ids() == ("pcbs:led_0603",)


def test_component_browser_preferred_only_can_hide_entries(qtbot) -> None:
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    browser.set_project_preferences(hidden_entry_ids=("pcbs:led_0603",))
    browser.preferred_only.setChecked(True)
    browser.search_box.setText("led")

    assert browser.visible_entry_ids() == ()


def test_component_browser_cannot_select_non_visible_entry(qtbot) -> None:
    browser = ComponentBrowser()
    qtbot.addWidget(browser)
    hidden_entry = CatalogEntry(
        id="pcbs:hidden_dev_part",
        family=ComponentFamily(id="developer", name="Developer"),
        variant=ComponentVariant(name="Hidden Developer Part"),
        symbol_id="stdlib:R",
        tags=("hidden",),
        group_ids=("basic-components",),
        normal_user_visible=False,
    )
    browser.catalog = ComponentCatalog(
        groups=browser.catalog.groups,
        entries=(*browser.catalog.entries, hidden_entry),
    )

    browser.set_project_preferences(visible_entry_ids=("pcbs:hidden_dev_part",))
    browser.search_box.setText("hidden")

    assert browser.visible_entry_ids() == ()
    try:
        browser.select_entry("pcbs:hidden_dev_part")
    except ValueError as exc:
        assert "Catalog entry is not visible" in str(exc)
    else:
        raise AssertionError("Expected hidden catalog entry to stay unavailable")


def test_main_window_places_selected_browser_component(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.component_browser.search_box.setText("capacitor")
    window.component_browser.select_entry("pcbs:capacitor_0603")
    window.place_selected_component_at_origin()

    symbol = window.scene.editor_state.symbols[0]
    assert symbol.symbol_id == "stdlib:C"
    assert symbol.value == "100nF"


def test_main_window_add_r_toolbar_action_places_catalog_resistor(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    _toolbar_action(window, "Add R").trigger()

    symbol = window.scene.editor_state.symbols[0]
    assert symbol.symbol_id == "stdlib:R"
    assert symbol.value == "10k"
    assert symbol.footprint_id == "stdlib:R_0603"
    assert symbol.position == Point(x=0, y=0)


def test_main_window_add_c_toolbar_action_places_capacitor_at_origin(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    _toolbar_action(window, "Add C").trigger()

    symbol = window.scene.editor_state.symbols[0]
    assert symbol.symbol_id == "stdlib:C"
    assert symbol.value == "100nF"
    assert symbol.position == Point(x=0, y=0)


def test_main_window_add_led_toolbar_action_places_led_at_origin(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    _toolbar_action(window, "Add LED").trigger()

    symbol = window.scene.editor_state.symbols[0]
    assert symbol.symbol_id == "stdlib:LED"
    assert symbol.value == "LED"
    assert symbol.position == Point(x=0, y=0)


def test_open_project_applies_project_catalog_preferences(qtbot, tmp_path) -> None:
    project_dir = tmp_path / "preferred-project"
    project = project_io.create_project(project_dir, "Preferred")
    project_io.save_project(
        project_dir,
        project.model_copy(
            update={
                "catalog_preferences": CatalogPreferences(
                    enabled_group_ids=("basic-components",),
                    hidden_entry_ids=("pcbs:led_0603",),
                )
            }
        ),
    )

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_dir)
    window.component_browser.preferred_only.setChecked(True)
    window.component_browser.search_box.setText("led")

    assert window.component_browser.visible_entry_ids() == ()
