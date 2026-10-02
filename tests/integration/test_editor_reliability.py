from dataclasses import replace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import SymbolInstance, Wire
from pcbsmith.ui.items import WireItem
from pcbsmith.ui.main_window import MainWindow
from pcbsmith.ui.schematic_view import MAX_VIEW_SCALE, MIN_VIEW_SCALE
from pcbsmith.ui.selection import SelectionKey


def shown_window(qtbot, size=(1000, 700)):
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.view.setFocus()
    return window


def test_pan_consumes_drag_without_placing_and_escape_restores_select(qtbot):
    window = shown_window(qtbot)
    window.arm_catalog_entry_by_id("pcbs:resistor_0603")
    window.pan_action.trigger()
    before = window.scene.editor_state
    center = window.view.viewport().rect().center()
    old = window.view.mapToScene(center)
    QTest.mousePress(window.view.viewport(), Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseMove(window.view.viewport(), center + QPoint(40, 25))
    QTest.mouseRelease(
        window.view.viewport(), Qt.MouseButton.LeftButton, pos=center + QPoint(40, 25)
    )
    assert window.scene.editor_state == before
    assert window.view.mapToScene(center) != old
    assert window.pan_action.isChecked() and not window.select_action.isChecked()
    QTest.keyClick(window.view, Qt.Key.Key_Escape)
    assert window.scene.current_tool() == "select" and window.select_action.isChecked()


def test_keyboard_search_place_cancel_and_text_shortcuts(qtbot):
    window = shown_window(qtbot)
    window.focus_component_browser_search()
    search = window.component_browser.search_box
    QTest.keyClicks(search, "resistor")
    assert search.text() == "resistor"
    assert window.scene.current_tool() == "select"
    QTest.keyClick(search, Qt.Key.Key_Return)
    assert window.scene.current_tool() == "place_catalog"
    assert window.view.hasFocus(), (
        QApplication.focusWidget(),
        window.focusWidget(),
        window.isActiveWindow(),
    )
    QTest.keyClick(window.view, Qt.Key.Key_Return)
    assert len(window.scene.symbol_items()) == 1
    assert window.scene.current_tool() == "select"
    window.arm_catalog_entry_by_id("pcbs:led_0603")
    QTest.keyClick(window.view, Qt.Key.Key_Escape)
    assert len(window.scene.symbol_items()) == 1
    window.scene.select_key(SelectionKey("symbol", "R1"))
    edit = window.inspector.value_edit
    edit.setFocus()
    edit.selectAll()
    QTest.keyClicks(edit, "RCDLWPTH")
    QTest.keyClick(edit, Qt.Key.Key_Backspace)
    assert edit.text() == "RCDLWPT"
    assert len(window.scene.symbol_items()) == 1
    assert window.scene.current_tool() == "select"


def test_rotation_preserves_selection_and_unrelated_graphics(qtbot):
    window = shown_window(qtbot)
    window.scene.place_resistor(Point(x=0, y=0))
    window.scene.place_resistor(Point(x=20_000_000, y=0))
    unrelated = window.scene.symbol_items()[1]
    window.scene.select_key(SelectionKey("symbol", "R1"))
    window.rotate_action.trigger()
    window.rotate_action.trigger()
    assert window.scene.editor_state.symbols[0].rotation_deg == 180
    assert window.scene.selected_key() == SelectionKey("symbol", "R1")
    assert window.scene.symbol_items()[0].isSelected()
    assert window.scene.symbol_items()[1] is unrelated
    window.undo_action.trigger()
    assert window.scene.editor_state.symbols[0].rotation_deg == 90
    window.redo_action.trigger()
    assert window.scene.editor_state.symbols[0].rotation_deg == 180


@pytest.mark.parametrize("scale", [MIN_VIEW_SCALE, 4e-6, MAX_VIEW_SCALE])
def test_wire_hit_area_is_segment_shaped_at_each_zoom(scale):
    item = WireItem(Wire(points=(Point(x=0, y=0), Point(x=200_000_000, y=200_000_000))), 0)
    item.set_pick_scale(scale)
    assert item.contains(QPointF(100_000_000, 100_000_000 + 2 / scale))
    assert not item.contains(QPointF(100_000_000, 100_000_000 + 12 / scale))
    assert not item.contains(QPointF(200_000_000, 0))
    assert item.boundingRect().contains(item.shape().boundingRect())


def test_noop_does_not_render_and_single_edit_reuses_items(qtbot):
    window = shown_window(qtbot)
    symbols = tuple(
        SymbolInstance(
            reference=f"R{i}",
            symbol_id="stdlib:R",
            value="10k",
            position=Point(x=i * 15_000_000, y=0),
        )
        for i in range(100)
    )
    state = replace(window.scene.editor_state, symbols=symbols)
    window.scene.load_editor_state(state)
    old = window.scene.symbol_items()
    signals = []
    window.scene.editor_state_changed.connect(lambda: signals.append(1))
    window.scene.apply_editor_state(state)
    assert signals == []
    window.scene.update_symbol("R50", value="1k")
    assert window.scene.symbol_items()[49] is old[49]
    assert window.scene.symbol_items()[51] is old[51]
    assert window.scene.symbol_items()[50] is not old[50]
    assert len(signals) == 1


def test_catalog_cycles_release_widgets_and_keep_expansion(qtbot):
    window = shown_window(qtbot)
    browser = window.component_browser
    browser.family_header("Basic Components").click()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    baseline = len(QApplication.allWidgets())
    for _ in range(150):
        browser.search_box.setText("resistor")
        browser.search_box.clear()
        browser.set_project_preferences(hidden_entry_ids=("pcbs:led_0603",))
        browser.set_project_preferences()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(QApplication.allWidgets()) <= baseline + 3
    assert browser.family_page("Basic Components").isHidden()
    assert browser.search_box.hasFocus() is False  # refresh never steals focus
    buttons = browser.family_page("Basic Components").findChildren(QPushButton)
    assert all(button.accessibleName() == button.text() for button in buttons)


@pytest.mark.parametrize("size", [(800, 600), (1366, 768)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_small_layout_and_label_separation(qtbot, size, theme):
    window = shown_window(qtbot, size)
    window.apply_theme(theme)
    QApplication.processEvents()
    assert window.width() == size[0] and window.height() == size[1]
    assert window.view.viewport().width() >= 250
    assert window.view.viewport().height() >= 200
    assert window.component_browser.family_scroll.verticalScrollBar().maximum() > 0
    item = window.scene.place_resistor(Point(x=0, y=0))
    assert not item.boundingRect().intersects(
        item._label.mapRectToParent(item._label.boundingRect())
    )
    window.scene.select_key(SelectionKey("symbol", "R1"))
    assert window.inspector.position_label.text() == "0, 0 mm"
    placeholders = {a.text(): a for a in window.findChildren(QAction)}
    assert not placeholders["Project Settings"].isEnabled()
    assert not placeholders["Grid And Snap Settings"].isEnabled()


def test_extreme_zoom_and_grid_work_remain_bounded(qtbot):
    window = shown_window(qtbot)
    view = window.view
    for factor in [0.1] * 80 + [10] * 80 + [0.1] * 80:
        view.zoom_by(factor)
        assert MIN_VIEW_SCALE * 0.999 <= view.transform().m11() <= MAX_VIEW_SCALE * 1.001
        rect = view.mapToScene(view.viewport().rect()).boundingRect()
        step = view.display_grid_spacing(rect)
        assert (rect.width() + rect.height()) / step <= 400
    assert view.display_grid_spacing(QRectF(-1e15, -1e15, 2e15, 2e15)) > 0
    # Actual render at minimum scale exercises floating-point grid coordinates.
    assert not window.grab().isNull()
