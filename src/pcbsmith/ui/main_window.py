from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
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

        self.setWindowTitle("PCBSmith")
        self.setCentralWidget(self.view)
        self._create_library_dock()
        self._create_console_dock()
        self._create_file_menu()
        self._create_toolbar()

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

    def _create_toolbar(self) -> None:
        toolbar = self.addToolBar("Schematic")

        place_resistor_action = QAction("Place R", self)
        place_resistor_action.triggered.connect(self.place_resistor_at_origin)
        toolbar.addAction(place_resistor_action)

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
