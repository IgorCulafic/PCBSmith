from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QTextEdit,
)

from pcbsmith.core.geom import Point
from pcbsmith.core.project import Project
from pcbsmith.services import erc, project_io
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.services.project_io import ProjectIOError
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.inspector import InspectorWidget
from pcbsmith.ui.schematic_scene import SchematicScene
from pcbsmith.ui.schematic_view import SchematicView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_dir: Path | None = None
        self.project: Project | None = None
        self.scene = SchematicScene(self)
        self.view = SchematicView(self.scene, self)
        self.library_list = QListWidget()
        self.library_dock = QDockWidget("Library", self)
        self.console = QTextEdit()
        self.console_dock = QDockWidget("Console", self)
        self.inspector = InspectorWidget()
        self.inspector_dock = QDockWidget("Inspector", self)
        self.schematic_toolbar = None
        self.undo_action = QAction("Undo", self)
        self.redo_action = QAction("Redo", self)
        self.delete_action = QAction("Delete", self)
        self.rotate_action = QAction("Rotate", self)

        self.setWindowTitle("PCBSmith")
        self.setCentralWidget(self.view)
        self._create_library_dock()
        self._create_console_dock()
        self._create_inspector_dock()
        self._create_file_menu()
        self._create_toolbar()
        self.scene.selectionChanged.connect(self.refresh_inspector)

    def _create_file_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_project_action = QAction("New Project", self)
        new_project_action.triggered.connect(self.create_project_dialog)
        file_menu.addAction(new_project_action)

        open_project_action = QAction("Open Project", self)
        open_project_action.triggered.connect(self.open_project_dialog)
        file_menu.addAction(open_project_action)

        save_project_action = QAction("Save", self)
        save_project_action.triggered.connect(self.save_project)
        file_menu.addAction(save_project_action)

    def _create_library_dock(self) -> None:
        for symbol in SYMBOLS.values():
            self.library_list.addItem(symbol.name)

        self.library_dock.setWidget(self.library_list)
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

        select_action = QAction("Select", self)
        select_action.triggered.connect(lambda: self.scene.set_tool("select"))
        toolbar.addAction(select_action)

        place_resistor_action = QAction("Place R", self)
        place_resistor_action.triggered.connect(
            lambda: self.scene.set_tool("place_resistor")
        )
        toolbar.addAction(place_resistor_action)

        wire_action = QAction("Wire", self)
        wire_action.triggered.connect(lambda: self.scene.set_tool("wire"))
        toolbar.addAction(wire_action)

        label_action = QAction("Label", self)
        label_action.triggered.connect(lambda: self.scene.set_tool("label"))
        toolbar.addAction(label_action)

        no_connect_action = QAction("No Connect", self)
        no_connect_action.triggered.connect(lambda: self.scene.set_tool("no_connect"))
        toolbar.addAction(no_connect_action)

        toolbar.addSeparator()

        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.addAction(self.undo_action)
        toolbar.addAction(self.undo_action)

        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo)
        self.addAction(self.redo_action)
        toolbar.addAction(self.redo_action)

        self.delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_action.triggered.connect(self.delete_selected)
        self.addAction(self.delete_action)
        toolbar.addAction(self.delete_action)

        self.rotate_action.setShortcut(QKeySequence("Ctrl+R"))
        self.rotate_action.triggered.connect(self.rotate_selected)
        self.addAction(self.rotate_action)
        toolbar.addAction(self.rotate_action)

        toolbar.addSeparator()

        fit_action = QAction("Fit", self)
        fit_action.triggered.connect(self.view.fit_to_contents)
        toolbar.addAction(fit_action)

        run_erc = QAction("ERC", self)
        run_erc.triggered.connect(self.run_erc)
        toolbar.addAction(run_erc)

    def place_resistor_at_origin(self) -> None:
        self.scene.place_resistor(Point(x=0, y=0))
        self.console.append("Placed resistor")

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

    def refresh_inspector(self) -> None:
        self.inspector.show_selection(
            self.scene.editor_state,
            self.scene.selected_key(),
        )
