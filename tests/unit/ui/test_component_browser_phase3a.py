from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from pcbsmith.ui.component_browser import ComponentBrowser


def test_component_browser_has_basic_components_family(qtbot) -> None:  # type: ignore[no-untyped-def]
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    assert "Basic Components" in browser.family_titles()
    assert browser.family_header("Basic Components").isCheckable()


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

    page = browser.family_page("Basic Components")
    buttons = page.findChildren(QPushButton)

    assert buttons
    assert all(button.maximumHeight() <= 44 for button in buttons)
    assert page.layout().alignment() & Qt.AlignmentFlag.AlignTop


def test_component_browser_family_can_be_collapsed(qtbot) -> None:  # type: ignore[no-untyped-def]
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    header = browser.family_header("Basic Components")
    page = browser.family_page("Basic Components")

    assert not page.isHidden()
    header.click()

    assert page.isHidden()
    assert header.arrowType() == Qt.ArrowType.RightArrow


def test_component_browser_tiles_have_previews_and_tooltips(qtbot) -> None:  # type: ignore[no-untyped-def]
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    buttons = browser.family_page("Basic Components").findChildren(QPushButton)

    assert buttons
    assert all(not button.icon().isNull() for button in buttons)
    assert any("R" in button.toolTip() for button in buttons)
