from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QTextEdit,
)

from pcbsmith.core.geom import Point
from pcbsmith.core.project import Project
from pcbsmith.services import component_catalog, erc, project_io
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.services.project_io import ProjectIOError
from pcbsmith.ui.component_browser import ComponentBrowser
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.icons import tool_icon
from pcbsmith.ui.inspector import InspectorWidget
from pcbsmith.ui.schematic_scene import SchematicScene
from pcbsmith.ui.schematic_view import SchematicView
from pcbsmith.ui.selection import SelectionKey, parse_index_key
from pcbsmith.ui.theme import apply_window_theme


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_dir: Path | None = None
        self.project: Project | None = None
        self.scene = SchematicScene(self)
        self.view = SchematicView(self.scene, self)
        self.component_browser = ComponentBrowser()
        self.library_dock = QDockWidget("Library", self)
        self.console = QTextEdit()
        self.console_dock = QDockWidget("Console", self)
        self.inspector = InspectorWidget()
        self.inspector_dock = QDockWidget("Inspector", self)
        self.schematic_toolbar = None
        self.select_action = QAction("Select", self)
        self.pan_action = QAction("Pan", self)
        self.wire_action = QAction("Wire", self)
        self.label_action = QAction("Label", self)
        self.no_connect_action = QAction("No Connect", self)
        self.fit_action = QAction("Fit", self)
        self.run_erc_action = QAction("ERC", self)
        self.undo_action = QAction("Undo", self)
        self.redo_action = QAction("Redo", self)
        self.delete_action = QAction("Delete", self)
        self.rotate_action = QAction("Rotate", self)
        self.mirror_horizontal_action = QAction("Mirror H", self)
        self.light_theme_action = QAction("Light Theme", self)
        self.dark_theme_action = QAction("Dark Theme", self)
        self.wire_width_actions = [
            QAction("Wire Width 2", self),
            QAction("Wire Width 4", self),
            QAction("Wire Width 6", self),
        ]

        self.setWindowTitle("PCBSmith")
        self.setCentralWidget(self.view)
        self.view.installEventFilter(self)
        self.view.viewport().installEventFilter(self)
        self._create_library_dock()
        self._create_console_dock()
        self._create_inspector_dock()
        self.inspector.symbol_field_changed.connect(self.apply_symbol_field_change)
        self.inspector.label_text_changed.connect(self.apply_label_text_change)
        self._configure_actions()
        self._create_menus()
        self._create_toolbar()
        self.apply_theme("light")
        self.scene.selectionChanged.connect(self.refresh_inspector)

    def _configure_actions(self) -> None:
        self.select_action.setShortcut(QKeySequence("V"))
        self.select_action.setIcon(tool_icon("select"))
        self.select_action.triggered.connect(lambda: self.scene.set_tool("select"))
        self._register_action(self.select_action)

        self.pan_action.setShortcut(QKeySequence("P"))
        self.pan_action.setIcon(tool_icon("pan"))
        self.pan_action.triggered.connect(lambda: self.view.setFocus())
        self._register_action(self.pan_action)

        self.wire_action.setShortcut(QKeySequence("W"))
        self.wire_action.setIcon(tool_icon("wire"))
        self.wire_action.triggered.connect(lambda: self.scene.set_tool("wire"))
        self._register_action(self.wire_action)

        self.label_action.setShortcut(QKeySequence("T"))
        self.label_action.setIcon(tool_icon("label"))
        self.label_action.triggered.connect(lambda: self.scene.set_tool("label"))
        self._register_action(self.label_action)

        self.no_connect_action.setShortcut(QKeySequence("X"))
        self.no_connect_action.setIcon(tool_icon("no_connect"))
        self.no_connect_action.triggered.connect(lambda: self.scene.set_tool("no_connect"))
        self._register_action(self.no_connect_action)

        self.fit_action.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_action.setIcon(tool_icon("fit"))
        self.fit_action.triggered.connect(self.view.fit_to_contents)
        self._register_action(self.fit_action)

        self.run_erc_action.setShortcut(QKeySequence("F8"))
        self.run_erc_action.setIcon(tool_icon("erc"))
        self.run_erc_action.triggered.connect(self.run_erc)
        self._register_action(self.run_erc_action)

        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setIcon(tool_icon("undo"))
        self.undo_action.triggered.connect(self.undo)
        self._register_action(self.undo_action)

        self.redo_action.setShortcuts(
            [
                QKeySequence(QKeySequence.StandardKey.Redo),
                QKeySequence("Ctrl+Shift+Z"),
            ]
        )
        self.redo_action.setIcon(tool_icon("redo"))
        self.redo_action.triggered.connect(self.redo)
        self._register_action(self.redo_action)

        self.delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_action.setIcon(tool_icon("delete"))
        self.delete_action.triggered.connect(self.delete_selected)
        self._register_action(self.delete_action)

        self.rotate_action.setShortcut(QKeySequence("Ctrl+R"))
        self.rotate_action.setIcon(tool_icon("rotate"))
        self.rotate_action.triggered.connect(self.rotate_selected)
        self._register_action(self.rotate_action)

        self.mirror_horizontal_action.setShortcut(QKeySequence("H"))
        self.mirror_horizontal_action.setIcon(tool_icon("mirror"))
        self.mirror_horizontal_action.triggered.connect(self.mirror_horizontal_selected)
        self._register_action(self.mirror_horizontal_action)

        self.light_theme_action.triggered.connect(lambda: self.apply_theme("light"))
        self.dark_theme_action.triggered.connect(lambda: self.apply_theme("dark"))
        self._register_action(self.light_theme_action)
        self._register_action(self.dark_theme_action)

        for action, width in zip(self.wire_width_actions, (2, 4, 6), strict=True):
            action.triggered.connect(
                lambda _checked=False, width=width: self.scene.set_wire_stroke_width(width)
            )
            self._register_action(action)

    def _register_action(self, action: QAction) -> None:
        action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self._refresh_action_tooltip(action)
        self.addAction(action)

    def _refresh_action_tooltip(self, action: QAction) -> None:
        shortcuts = action.shortcuts()
        if shortcuts:
            action.setToolTip(f"{action.text()} ({shortcuts[0].toString()})")
        else:
            action.setToolTip(action.text())

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        edit_menu = self.menuBar().addMenu("&Edit")
        view_menu = self.menuBar().addMenu("&View")
        components_menu = self.menuBar().addMenu("&Components")
        tools_menu = self.menuBar().addMenu("&Tools")
        options_menu = self.menuBar().addMenu("&Options")
        project_menu = self.menuBar().addMenu("&Project")
        help_menu = self.menuBar().addMenu("&Help")

        new_project_action = QAction("New Project", self)
        new_project_action.triggered.connect(self.create_project_dialog)
        file_menu.addAction(new_project_action)

        open_project_action = QAction("Open Project", self)
        open_project_action.triggered.connect(self.open_project_dialog)
        file_menu.addAction(open_project_action)

        save_project_action = QAction("Save", self)
        save_project_action.setShortcut(QKeySequence.StandardKey.Save)
        save_project_action.triggered.connect(self.save_project)
        file_menu.addAction(save_project_action)

        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addAction(self.delete_action)
        edit_menu.addAction(self.rotate_action)
        edit_menu.addAction(self.mirror_horizontal_action)

        view_menu.addAction(self.fit_action)

        components_menu.addAction(self._component_action("Resistor", "pcbs:resistor_0603", "R"))
        components_menu.addAction(self._component_action("Capacitor", "pcbs:capacitor_0603", "C"))
        components_menu.addAction(self._component_action("Diode", "pcbs:diode_0603", "D"))
        components_menu.addAction(self._component_action("LED", "pcbs:led_0603", "L"))

        tools_menu.addAction(self.select_action)
        tools_menu.addAction(self.wire_action)
        tools_menu.addAction(self.label_action)
        tools_menu.addAction(self.no_connect_action)
        tools_menu.addAction(self.run_erc_action)

        options_menu.addAction(self.light_theme_action)
        options_menu.addAction(self.dark_theme_action)
        options_menu.addSeparator()
        for action in self.wire_width_actions:
            options_menu.addAction(action)
        options_menu.addSeparator()
        options_menu.addAction(QAction("Grid And Snap Settings", self))
        project_menu.addAction(QAction("Project Settings", self))
        help_menu.addAction(QAction("About PCBSmith", self))

    def _component_action(self, text: str, entry_id: str, shortcut: str) -> QAction:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        action.triggered.connect(lambda: self.arm_catalog_entry_by_id(entry_id))
        self._refresh_action_tooltip(action)
        self.addAction(action)
        return action

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched in (self.view, self.view.viewport())
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self._handle_bare_shortcut(event.key())
        ):
            event.accept()
            return True

        return super().eventFilter(watched, event)

    def _handle_bare_shortcut(self, key: int) -> bool:
        if key == Qt.Key.Key_V:
            self.select_action.trigger()
        elif key == Qt.Key.Key_W:
            self.wire_action.trigger()
        elif key == Qt.Key.Key_T:
            self.label_action.trigger()
        elif key == Qt.Key.Key_X:
            self.no_connect_action.trigger()
        elif key == Qt.Key.Key_R:
            self.arm_catalog_entry_by_id("pcbs:resistor_0603")
        elif key == Qt.Key.Key_C:
            self.arm_catalog_entry_by_id("pcbs:capacitor_0603")
        elif key == Qt.Key.Key_D:
            self.arm_catalog_entry_by_id("pcbs:diode_0603")
        elif key == Qt.Key.Key_L:
            self.arm_catalog_entry_by_id("pcbs:led_0603")
        elif key == Qt.Key.Key_H:
            self.mirror_horizontal_action.trigger()
        else:
            return False
        return True

    def _create_library_dock(self) -> None:
        self.component_browser.entry_activated.connect(self.place_catalog_entry_by_id)
        self.library_dock.setWidget(self.component_browser)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)

    def _create_console_dock(self) -> None:
        self.console.setReadOnly(True)
        self.console_dock.setWidget(self.console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)

    def _create_inspector_dock(self) -> None:
        self.inspector_dock.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)

    def _create_toolbar(self) -> None:
        self.schematic_toolbar = self.addToolBar("Schematic")
        toolbar = self.schematic_toolbar
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        toolbar.addAction(self.select_action)
        toolbar.addAction(self.pan_action)
        toolbar.addAction(self.wire_action)
        toolbar.addAction(self.label_action)
        toolbar.addAction(self.no_connect_action)

        toolbar.addSeparator()

        toolbar.addAction(self.undo_action)

        toolbar.addAction(self.redo_action)

        toolbar.addAction(self.delete_action)

        toolbar.addAction(self.rotate_action)
        toolbar.addAction(self.mirror_horizontal_action)

        toolbar.addSeparator()

        toolbar.addAction(self.fit_action)
        toolbar.addAction(self.run_erc_action)

    def place_resistor_at_origin(self) -> None:
        self.scene.place_resistor(Point(x=0, y=0))
        self.console.append("Placed resistor")

    def apply_theme(self, theme: str) -> None:
        apply_window_theme(self, theme)

    def arm_catalog_entry_by_id(self, entry_id: str) -> None:
        try:
            entry = component_catalog.entry_by_id(self.component_browser.catalog, entry_id)
        except KeyError as exc:
            self.show_error(str(exc))
            return
        self.scene.arm_catalog_entry(entry)
        self.console.append(f"Ready to place {entry.variant.name}")

    def place_catalog_entry_by_id(self, entry_id: str) -> None:
        self.arm_catalog_entry_by_id(entry_id)

    def place_selected_component_at_origin(self) -> None:
        entry = self.component_browser.selected_entry()
        if entry is None:
            self.show_error("No component is selected")
            return
        self.scene.arm_catalog_entry(entry)
        self.console.append(f"Ready to place {entry.variant.name}")

    def focus_component_browser_search(self) -> None:
        self.library_dock.show()
        self.library_dock.raise_()
        self.component_browser.search_box.setFocus()

    def run_erc(self) -> None:
        try:
            issues = erc.run_erc(self.scene.editor_state.to_schematic(), SYMBOLS)
        except KeyError as exc:
            symbol_id = exc.args[0] if exc.args else str(exc)
            self.show_error(f"ERC failed: Unknown symbol {symbol_id}")
            return
        except ValueError as exc:
            self.show_error(f"ERC failed: {exc}")
            return

        if not issues:
            self.console.append("ERC passed")
            return

        for issue in issues:
            self.console.append(f"{issue.code}: {issue.message} ({issue.where})")

    def create_project(self, project_dir: Path, name: str) -> None:
        try:
            project_io.create_project(project_dir, name)
        except ProjectIOError as exc:
            self.show_error(str(exc))
            return

        self.open_project(project_dir)

    def create_project_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "New Project Directory")
        if not directory:
            return

        name, accepted = QInputDialog.getText(self, "New Project", "Project name")
        if not accepted or not name.strip():
            return

        self.create_project(Path(directory), name.strip())

    def open_project_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open Project")
        if not directory:
            return

        self.open_project(Path(directory))

    def open_project(self, project_dir: Path) -> None:
        try:
            project = project_io.load_project(project_dir)
            if not project.schematics:
                self.show_error("Project has no schematics")
                return
            schematic = project_io.load_schematic(project_dir, project.schematics[0])
        except ProjectIOError as exc:
            self.show_error(str(exc))
            return

        self.project_dir = project_dir
        self.project = project
        self.component_browser.set_project_preferences(
            enabled_group_ids=project.catalog_preferences.enabled_group_ids,
            visible_entry_ids=project.catalog_preferences.visible_entry_ids,
            hidden_entry_ids=project.catalog_preferences.hidden_entry_ids,
        )
        self.scene.load_editor_state(EditorState.from_schematic(schematic))
        self.refresh_inspector()
        self.console.append(f"Opened {project.name}")

    def save_project(self) -> None:
        if self.project_dir is None or self.project is None:
            self.show_error("No project is open")
            return

        if not self.project.schematics:
            self.show_error("No schematic is open")
            return

        try:
            project_io.save_schematic(
                self.project_dir,
                self.project.schematics[0],
                self.scene.editor_state.to_schematic(),
            )
        except ProjectIOError as exc:
            self.show_error(str(exc))
            return

        self.console.append("Saved schematic")

    def show_error(self, message: str) -> None:
        self.console.append(message)
        QMessageBox.warning(self, "PCBSmith", message)

    def undo(self) -> None:
        try:
            self.scene.undo()
        except IndexError as exc:
            self.show_error(str(exc))
        self.refresh_inspector()

    def redo(self) -> None:
        try:
            self.scene.redo()
        except IndexError as exc:
            self.show_error(str(exc))
        self.refresh_inspector()

    def delete_selected(self) -> None:
        selection = self.scene.selected_key()
        if selection is None:
            return
        try:
            self.scene.delete_selection(selection)
        except ValueError as exc:
            self.show_error(str(exc))
        self.refresh_inspector()

    def rotate_selected(self) -> None:
        selection = self.scene.selected_key()
        if selection is None:
            return
        try:
            self.scene.rotate_selection(selection, 90)
        except ValueError as exc:
            self.show_error(str(exc))
        self.refresh_inspector()

    def mirror_horizontal_selected(self) -> None:
        selection = self.scene.selected_key()
        if selection is None:
            return
        try:
            self.scene.mirror_selection_horizontally(selection)
        except ValueError as exc:
            self.show_error(str(exc))
        self.refresh_inspector()

    def apply_symbol_field_change(self, change: tuple[SelectionKey, str, str]) -> None:
        selection, field, value = change
        if selection.kind != "symbol":
            return

        updates: dict[str, object] = {}
        restored_selection = selection
        if field == "reference":
            new_reference = value.strip()
            updates["new_reference"] = new_reference
            restored_selection = SelectionKey("symbol", new_reference)
        elif field == "value":
            updates["value"] = value.strip()
        elif field == "rotation":
            try:
                rotation_deg = int(value)
            except ValueError:
                self.show_error(f"Invalid rotation: {value}")
                return
            if rotation_deg not in {0, 90, 180, 270}:
                self.show_error(f"Invalid rotation: {value}")
                return
            updates["rotation_deg"] = rotation_deg
        elif field == "footprint":
            updates["footprint_id"] = value.strip()
        else:
            self.show_error(f"Unknown symbol field: {field}")
            return

        try:
            self.scene.update_symbol(selection.key, **updates)
        except ValueError as exc:
            self.show_error(str(exc))
            return

        self.scene.select_key(restored_selection)
        self.refresh_inspector()

    def apply_label_text_change(self, change: tuple[SelectionKey, str]) -> None:
        selection, value = change
        if selection.kind != "label":
            return

        try:
            self.scene.update_label(parse_index_key(selection), name=value)
        except ValueError as exc:
            self.show_error(str(exc))
            return

        self.scene.select_key(selection)
        self.refresh_inspector()

    def refresh_inspector(self) -> None:
        self.inspector.show_selection(
            self.scene.editor_state,
            self.scene.selected_key(),
        )
