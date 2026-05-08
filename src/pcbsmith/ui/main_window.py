from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDockWidget, QListWidget, QMainWindow, QMessageBox, QTextEdit

from pcbsmith.core.geom import Point
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.ui.schematic_scene import SchematicScene
from pcbsmith.ui.schematic_view import SchematicView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_dir: Path | None = None
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
        self._create_toolbar()

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

    def place_resistor_at_origin(self) -> None:
        self.scene.place_resistor(Point(x=0, y=0))
        self.console.append("Placed resistor")

    def show_error(self, message: str) -> None:
        self.console.append(message)
        QMessageBox.warning(self, "PCBSmith", message)
