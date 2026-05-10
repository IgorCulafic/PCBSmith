from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QToolBox

from pcbsmith.ui.component_browser import ComponentBrowser


def test_component_browser_has_basic_components_family(qtbot) -> None:  # type: ignore[no-untyped-def]
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    assert isinstance(browser.family_box, QToolBox)
    family_titles = {
        browser.family_box.itemText(index)
        for index in range(browser.family_box.count())
    }
    assert "Basic Components" in family_titles


def test_component_browser_basic_family_contains_quick_parts(qtbot) -> None:  # type: ignore[no-untyped-def]
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    visible = browser.visible_entry_ids()
    assert "pcbs:resistor_0603" in visible
    assert "pcbs:capacitor_0603" in visible
    assert "pcbs:diode_0603" in visible
    assert "pcbs:led_0603" in visible
    assert "pcbs:push_button_th" in visible
    assert "pcbs:switch_spst_th" in visible


def test_component_browser_family_tiles_are_compact(qtbot) -> None:  # type: ignore[no-untyped-def]
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    page = browser.family_box.widget(0)
    buttons = page.findChildren(QPushButton)

    assert buttons
    assert all(button.maximumHeight() <= 44 for button in buttons)
    assert page.layout().alignment() & Qt.AlignmentFlag.AlignTop
