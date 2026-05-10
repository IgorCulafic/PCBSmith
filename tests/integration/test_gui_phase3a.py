from __future__ import annotations

from PySide6.QtGui import QBrush, QColor, QKeySequence

from pcbsmith.core.geom import Point
from pcbsmith.ui import items
from pcbsmith.ui.main_window import MainWindow


def _menu_titles(window: MainWindow) -> set[str]:
    return {action.text().replace("&", "") for action in window.menuBar().actions()}


def _toolbar_texts(window: MainWindow) -> set[str]:
    return {
        action.text()
        for action in window.schematic_toolbar.actions()
        if action.text()
    }


def test_phase3a_item_theme_is_readable_on_light_canvas() -> None:
    assert items.CANVAS_BACKGROUND == QColor(248, 250, 252)
    assert items.GRID_COLOR == QColor(221, 226, 232)
    assert items.SYMBOL_PEN.color() == QColor(24, 32, 42)
    assert items.SYMBOL_TEXT_COLOR == QColor(17, 24, 39)
    assert items.CONNECTION_HANDLE_COLOR == QColor(27, 115, 209)


def test_phase3a_canvas_uses_light_background(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.scene.backgroundBrush() == QBrush(items.CANVAS_BACKGROUND)


def test_phase3a_main_window_has_cad_menus(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert {
        "File",
        "Edit",
        "View",
        "Components",
        "Tools",
        "Options",
        "Project",
        "Help",
    }.issubset(_menu_titles(window))


def test_phase3a_main_window_uses_light_chrome_by_default(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.property("pcbsTheme") == "light"
    assert "#f3f5f7" in window.styleSheet()
    assert "#17202a" in window.styleSheet()


def test_phase3a_options_menu_can_switch_themes(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    actions = {action.text(): action for action in window.actions()}

    actions["Dark Theme"].trigger()
    assert window.property("pcbsTheme") == "dark"

    actions["Light Theme"].trigger()
    assert window.property("pcbsTheme") == "light"


def test_phase3a_toolbar_is_tool_oriented(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    texts = _toolbar_texts(window)
    assert {
        "Select",
        "Pan",
        "Wire",
        "Label",
        "No Connect",
        "Rotate",
        "Mirror H",
        "Fit",
        "ERC",
    }.issubset(texts)
    assert "Add R" not in texts
    assert "Add C" not in texts
    assert "Add LED" not in texts


def test_component_action_arms_placement_without_adding_symbol(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    window.arm_catalog_entry_by_id("pcbs:resistor_0603")

    assert len(window.scene.editor_state.symbols) == 0
    assert window.scene.armed_catalog_entry_id() == "pcbs:resistor_0603"


def test_canvas_click_places_armed_component(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    window.arm_catalog_entry_by_id("pcbs:resistor_0603")
    window.scene.handle_canvas_click(Point(x=2_540_000, y=0))

    assert len(window.scene.editor_state.symbols) == 1
    assert window.scene.editor_state.symbols[0].reference == "R1"
    assert window.scene.armed_catalog_entry_id() is None


def test_escape_cancels_armed_placement(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    window.arm_catalog_entry_by_id("pcbs:resistor_0603")
    window.scene.cancel_active_tool()

    assert window.scene.armed_catalog_entry_id() is None


def test_phase3a_shortcuts_are_registered(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    actions = {action.text(): action for action in window.actions()}
    assert actions["Resistor"].shortcut() == QKeySequence("R")
    assert actions["Capacitor"].shortcut() == QKeySequence("C")
    assert actions["Diode"].shortcut() == QKeySequence("D")
    assert actions["LED"].shortcut() == QKeySequence("L")
    assert actions["Mirror H"].shortcut() == QKeySequence("H")


def test_mirror_horizontal_updates_selected_symbol_transform(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    item = window.scene.place_resistor(Point(x=0, y=0))
    item.setSelected(True)
    window.mirror_horizontal_selected()

    assert window.scene.editor_state.symbols[0].mirrored_x is True
    mirrored = window.scene.symbol_items()[0]
    assert mirrored.transform().m11() == -1


def test_mirror_horizontal_survives_scene_rerender(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    item = window.scene.place_resistor(Point(x=0, y=0))
    item.setSelected(True)
    window.mirror_horizontal_selected()
    window.scene.load_editor_state(window.scene.editor_state)

    assert window.scene.editor_state.symbols[0].mirrored_x is True
    assert window.scene.symbol_items()[0].transform().m11() == -1
