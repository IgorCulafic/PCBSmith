# PCBSmith Phase 1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a narrow PySide6 schematic-editor vertical slice: launch the GUI, place two resistors, draw a wire, save, reopen, navigate the canvas, and run ERC.

**Architecture:** Add a new `pcbsmith.ui` layer above existing `services` and `core`. Keep Qt code in UI files, keep non-Qt edit conversion in `ui/editor_state.py`, and reuse existing `project_io`, `builtin_library`, and `erc` services for durable behavior.

**Tech Stack:** Python 3.11-3.14, PySide6, Pydantic, pytest, pytest-qt, existing import-linter boundaries.

---

## File Structure

Create these files:

- `src/pcbsmith/ui/__init__.py`: UI package marker.
- `src/pcbsmith/ui/app.py`: QApplication startup and `pcbsmith-gui` console script entry point.
- `src/pcbsmith/ui/editor_state.py`: non-Qt schematic edit state and conversion to/from `core.schematic.Schematic`.
- `src/pcbsmith/ui/items.py`: `QGraphicsItem` subclasses for symbols and wires.
- `src/pcbsmith/ui/schematic_view.py`: `QGraphicsView` subclass for grid, zoom, pan, scroll, and fit-to-view.
- `src/pcbsmith/ui/schematic_scene.py`: `QGraphicsScene` subclass for tools, placement, wire drawing, and scene/model sync.
- `src/pcbsmith/ui/main_window.py`: main window, menus, docks, project lifecycle, save/open, and ERC action.
- `tests/unit/ui/test_editor_state.py`: fast non-Qt tests for editor state.
- `tests/unit/ui/test_schematic_view.py`: pytest-qt tests for view navigation behavior.
- `tests/integration/test_gui_phase1a.py`: pytest-qt tests for the main acceptance path.

Modify these files:

- `pyproject.toml`: add PySide6 dependency, pytest-qt dev dependency, GUI script, pytest Qt configuration, and import-linter UI boundary.
- `README.md`: document Phase 1A GUI launch and status after implementation.

## Task 1: Packaging And UI Boundary

**Files:**
- Modify: `pyproject.toml`
- Create: `src/pcbsmith/ui/__init__.py`
- Create: `src/pcbsmith/ui/app.py`
- Test: `tests/integration/test_gui_phase1a.py`

- [ ] **Step 1: Add a failing GUI import and entry-point test**

Create `tests/integration/test_gui_phase1a.py` with this content:

```python
from __future__ import annotations


def test_gui_entrypoint_imports() -> None:
    from pcbsmith.ui.app import main

    assert callable(main)
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_gui_entrypoint_imports -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task1
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pcbsmith.ui'`.

- [ ] **Step 3: Add PySide6, pytest-qt, the GUI script, and Qt test config**

Modify `pyproject.toml` so the relevant sections contain these entries:

```toml
[project]
dependencies = [
  "pydantic>=2.7,<3",
  "PySide6>=6.10,<7",
]

[project.optional-dependencies]
dev = [
  "hypothesis>=6.100",
  "import-linter>=2.0",
  "mypy>=1.10",
  "pytest>=8.0",
  "pytest-qt>=4.4",
  "ruff>=0.5",
]

[project.scripts]
pcbsmith = "pcbsmith.cli:main"
pcbsmith-gui = "pcbsmith.ui.app:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
qt_api = "pyside6"

[[tool.importlinter.contracts]]
name = "UI is the only layer that may import Qt"
type = "forbidden"
source_modules = ["pcbsmith.core", "pcbsmith.services", "pcbsmith.cli"]
forbidden_modules = ["PySide6", "pcbsmith.ui"]
```

- [ ] **Step 4: Create the UI package and minimal application entry point**

Create `src/pcbsmith/ui/__init__.py`:

```python
"""PySide6 user interface for PCBSmith."""
```

Create `src/pcbsmith/ui/app.py`:

```python
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv if argv is None else argv)

    from pcbsmith.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    if owns_app:
        return app.exec()
    return 0
```

- [ ] **Step 5: Add a temporary main window shell to satisfy imports**

Create `src/pcbsmith/ui/main_window.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PCBSmith")
```

- [ ] **Step 6: Run the entry-point test**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_gui_entrypoint_imports -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task1
```

Expected: PASS.

- [ ] **Step 7: Run existing Phase 0 tests**

Run:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task1-full
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add pyproject.toml src/pcbsmith/ui/__init__.py src/pcbsmith/ui/app.py src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase1a.py
git commit -m "feat: add gui package entry point"
```

## Task 2: Non-Qt Editor State

**Files:**
- Create: `src/pcbsmith/ui/editor_state.py`
- Test: `tests/unit/ui/test_editor_state.py`

- [ ] **Step 1: Write failing editor-state tests**

Create `tests/unit/ui/test_editor_state.py`:

```python
from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import Schematic
from pcbsmith.ui.editor_state import EditorState


def test_place_resistors_generates_references_and_schematic() -> None:
    state = EditorState.blank("main")

    state = state.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    state = state.place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))

    schematic = state.to_schematic()

    assert [symbol.reference for symbol in schematic.symbols] == ["R1", "R2"]
    assert [symbol.symbol_id for symbol in schematic.symbols] == ["stdlib:R", "stdlib:R"]
    assert [symbol.value for symbol in schematic.symbols] == ["10k", "1k"]


def test_add_wire_round_trips_through_schematic() -> None:
    schematic = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))
        .add_wire((Point(x=5_080_000, y=0), Point(x=15_240_000, y=0)))
        .to_schematic()
    )

    restored = EditorState.from_schematic(schematic).to_schematic()

    assert restored == schematic


def test_load_existing_references_continues_counter() -> None:
    state = EditorState.from_schematic(
        Schematic(
            id="main",
            symbols=(
                EditorState.blank("main")
                .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
                .to_schematic()
                .symbols[0],
            ),
        )
    )

    updated = state.place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))

    assert [symbol.reference for symbol in updated.to_schematic().symbols] == ["R1", "R2"]
```

- [ ] **Step 2: Run the editor-state tests to verify they fail**

Run:

```powershell
python -m pytest tests/unit/ui/test_editor_state.py -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task2
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pcbsmith.ui.editor_state'`.

- [ ] **Step 3: Implement immutable editor state**

Create `src/pcbsmith/ui/editor_state.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import Schematic, SymbolInstance, Wire


_REFERENCE_PATTERN = re.compile(r"^([A-Z]+)([0-9]+)$")
_PREFIX_BY_SYMBOL = {
    "stdlib:R": "R",
    "stdlib:C": "C",
    "stdlib:LED": "LED",
    "stdlib:VCC": "PWR",
    "stdlib:GND": "PWR",
    "stdlib:CONN_01X02": "J",
}


@dataclass(frozen=True)
class EditorState:
    schematic_id: str
    symbols: tuple[SymbolInstance, ...] = ()
    wires: tuple[Wire, ...] = ()

    @classmethod
    def blank(cls, schematic_id: str) -> EditorState:
        return cls(schematic_id=schematic_id)

    @classmethod
    def from_schematic(cls, schematic: Schematic) -> EditorState:
        return cls(
            schematic_id=schematic.id,
            symbols=tuple(schematic.symbols),
            wires=tuple(schematic.wires),
        )

    def place_symbol(
        self,
        symbol_id: str,
        value: str,
        position: Point,
        rotation_deg: int = 0,
        footprint_id: str | None = None,
    ) -> EditorState:
        symbol = SymbolInstance(
            reference=self._next_reference(symbol_id),
            symbol_id=symbol_id,
            value=value,
            position=position,
            rotation_deg=rotation_deg,
            footprint_id=footprint_id,
        )
        return replace(self, symbols=(*self.symbols, symbol))

    def add_wire(self, points: tuple[Point, ...]) -> EditorState:
        return replace(self, wires=(*self.wires, Wire(points=points)))

    def to_schematic(self) -> Schematic:
        return Schematic(id=self.schematic_id, symbols=self.symbols, wires=self.wires)

    def _next_reference(self, symbol_id: str) -> str:
        prefix = _PREFIX_BY_SYMBOL.get(symbol_id, "U")
        used = [
            int(match.group(2))
            for symbol in self.symbols
            if (match := _REFERENCE_PATTERN.match(symbol.reference)) and match.group(1) == prefix
        ]
        return f"{prefix}{max(used, default=0) + 1}"
```

- [ ] **Step 4: Run the editor-state tests**

Run:

```powershell
python -m pytest tests/unit/ui/test_editor_state.py -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task2
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/editor_state.py tests/unit/ui/test_editor_state.py
git commit -m "feat: add schematic editor state"
```

## Task 3: Schematic View Navigation

**Files:**
- Create: `src/pcbsmith/ui/schematic_view.py`
- Test: `tests/unit/ui/test_schematic_view.py`

- [ ] **Step 1: Write failing view tests**

Create `tests/unit/ui/test_schematic_view.py`:

```python
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene

from pcbsmith.ui.schematic_view import SchematicView


def test_view_has_expected_navigation_defaults(qtbot) -> None:  # type: ignore[no-untyped-def]
    scene = QGraphicsScene()
    view = SchematicView(scene)
    qtbot.addWidget(view)

    assert view.dragMode() == SchematicView.DragMode.NoDrag
    assert view.transformationAnchor() == SchematicView.ViewportAnchor.AnchorUnderMouse
    assert view.renderHints() & QPainter.RenderHint.Antialiasing


def test_fit_to_contents_changes_transform(qtbot) -> None:  # type: ignore[no-untyped-def]
    scene = QGraphicsScene()
    scene.addItem(QGraphicsRectItem(QRectF(-1_000_000, -1_000_000, 2_000_000, 2_000_000)))
    view = SchematicView(scene)
    view.resize(400, 300)
    qtbot.addWidget(view)

    before = view.transform()
    view.fit_to_contents()

    assert view.transform() != before
```

- [ ] **Step 2: Run the view tests to verify they fail**

Run:

```powershell
python -m pytest tests/unit/ui/test_schematic_view.py -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task3
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pcbsmith.ui.schematic_view'`.

- [ ] **Step 3: Implement the schematic view**

Create `src/pcbsmith/ui/schematic_view.py`:

```python
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from pcbsmith.core.geom import mm_to_nm


GRID_NM = 2_540_000
ZOOM_IN_FACTOR = 1.15
ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR


class SchematicView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self._panning = False
        self._last_pan_pos = QPoint()
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setSceneRect(QRectF(-mm_to_nm(500), -mm_to_nm(500), mm_to_nm(1000), mm_to_nm(1000)))

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        left = int(rect.left()) - (int(rect.left()) % GRID_NM)
        top = int(rect.top()) - (int(rect.top()) % GRID_NM)
        lines = []
        x = left
        while x < rect.right():
            lines.append((x, rect.top(), x, rect.bottom()))
            x += GRID_NM
        y = top
        while y < rect.bottom():
            lines.append((rect.left(), y, rect.right(), y))
            y += GRID_NM
        painter.setPen(QPen(Qt.GlobalColor.lightGray, 0))
        for x1, y1, x2, y2 in lines:
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = ZOOM_IN_FACTOR if event.angleDelta().y() > 0 else ZOOM_OUT_FACTOR
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._last_pan_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position().toPoint() - self._last_pan_pos
            self._last_pan_pos = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def fit_to_contents(self) -> None:
        items_rect = self.scene().itemsBoundingRect()
        if items_rect.isNull():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            return
        self.fitInView(items_rect.adjusted(-GRID_NM, -GRID_NM, GRID_NM, GRID_NM), Qt.AspectRatioMode.KeepAspectRatio)
```

- [ ] **Step 4: Run the view tests**

Run:

```powershell
python -m pytest tests/unit/ui/test_schematic_view.py -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task3
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/schematic_view.py tests/unit/ui/test_schematic_view.py
git commit -m "feat: add schematic view navigation"
```

## Task 4: Graphics Items And Scene Rendering

**Files:**
- Create: `src/pcbsmith/ui/items.py`
- Create: `src/pcbsmith/ui/schematic_scene.py`
- Test: `tests/integration/test_gui_phase1a.py`

- [ ] **Step 1: Extend GUI tests for scene rendering**

Append these tests to `tests/integration/test_gui_phase1a.py`:

```python
from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.schematic_scene import SchematicScene


def test_scene_renders_symbols_and_wires() -> None:
    state = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))
        .add_wire((Point(x=5_080_000, y=0), Point(x=15_240_000, y=0)))
    )
    scene = SchematicScene()

    scene.load_editor_state(state)

    assert len(scene.symbol_items()) == 2
    assert len(scene.wire_items()) == 1
```

- [ ] **Step 2: Run the rendering test to verify it fails**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_scene_renders_symbols_and_wires -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task4
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pcbsmith.ui.schematic_scene'`.

- [ ] **Step 3: Implement symbol and wire graphics items**

Create `src/pcbsmith/ui/items.py`:

```python
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsLineItem, QGraphicsSimpleTextItem

from pcbsmith.core.schematic import SymbolInstance, Wire


SYMBOL_WIDTH = 6_000_000
SYMBOL_HEIGHT = 2_200_000


class SymbolItem(QGraphicsItem):
    def __init__(self, symbol: SymbolInstance) -> None:
        super().__init__()
        self.symbol = symbol
        self.setPos(symbol.position.x, symbol.position.y)
        self.setRotation(symbol.rotation_deg)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.reference_text = QGraphicsSimpleTextItem(symbol.reference, self)
        self.reference_text.setPos(-SYMBOL_WIDTH / 2, -SYMBOL_HEIGHT * 1.6)

    def boundingRect(self) -> QRectF:
        return QRectF(-SYMBOL_WIDTH / 2, -SYMBOL_HEIGHT / 2, SYMBOL_WIDTH, SYMBOL_HEIGHT)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[no-untyped-def]
        pen = QPen(Qt.GlobalColor.black, 0)
        if self.isSelected():
            pen = QPen(Qt.GlobalColor.blue, 0)
        painter.setPen(pen)
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        painter.drawRect(self.boundingRect())
        painter.drawLine(int(-SYMBOL_WIDTH / 2 - 1_540_000), 0, int(-SYMBOL_WIDTH / 2), 0)
        painter.drawLine(int(SYMBOL_WIDTH / 2), 0, int(SYMBOL_WIDTH / 2 + 1_540_000), 0)


class WireItem(QGraphicsLineItem):
    def __init__(self, wire: Wire) -> None:
        start = wire.points[0]
        end = wire.points[-1]
        super().__init__(start.x, start.y, end.x, end.y)
        self.wire = wire
        self.setPen(QPen(Qt.GlobalColor.darkBlue, 0))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
```

- [ ] **Step 4: Implement scene rendering**

Create `src/pcbsmith/ui/schematic_scene.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QGraphicsScene

from pcbsmith.core.geom import Point, snap
from pcbsmith.core.schematic import Wire
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.items import SymbolItem, WireItem
from pcbsmith.ui.schematic_view import GRID_NM


class SchematicScene(QGraphicsScene):
    def __init__(self) -> None:
        super().__init__()
        self._state = EditorState.blank("main")
        self._symbol_items: list[SymbolItem] = []
        self._wire_items: list[WireItem] = []

    @property
    def editor_state(self) -> EditorState:
        return self._state

    def load_editor_state(self, state: EditorState) -> None:
        self.clear()
        self._state = state
        self._symbol_items = []
        self._wire_items = []
        for symbol in state.symbols:
            item = SymbolItem(symbol)
            self.addItem(item)
            self._symbol_items.append(item)
        for wire in state.wires:
            item = WireItem(wire)
            self.addItem(item)
            self._wire_items.append(item)

    def symbol_items(self) -> tuple[SymbolItem, ...]:
        return tuple(self._symbol_items)

    def wire_items(self) -> tuple[WireItem, ...]:
        return tuple(self._wire_items)

    def place_resistor(self, position: Point, value: str = "10k") -> None:
        snapped = snap(position, GRID_NM)
        self.load_editor_state(self._state.place_symbol("stdlib:R", value, snapped))

    def add_wire(self, start: Point, end: Point) -> None:
        self.load_editor_state(self._state.add_wire((snap(start, GRID_NM), snap(end, GRID_NM))))
```

- [ ] **Step 5: Run the rendering test**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_scene_renders_symbols_and_wires -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task4
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/ui/items.py src/pcbsmith/ui/schematic_scene.py tests/integration/test_gui_phase1a.py
git commit -m "feat: render schematic scene items"
```

## Task 5: Main Window Shell, Palette, And Console

**Files:**
- Modify: `src/pcbsmith/ui/main_window.py`
- Test: `tests/integration/test_gui_phase1a.py`

- [ ] **Step 1: Add failing main-window tests**

Append these tests to `tests/integration/test_gui_phase1a.py`:

```python
from pcbsmith.ui.main_window import MainWindow


def test_main_window_has_phase1a_docks(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.library_dock.windowTitle() == "Library"
    assert window.console_dock.windowTitle() == "Console"
    assert window.scene is not None
    assert window.view is not None


def test_library_can_place_resistor(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    window.place_resistor_at_origin()

    assert [item.symbol.reference for item in window.scene.symbol_items()] == ["R1"]
```

- [ ] **Step 2: Run the main-window tests to verify they fail**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_main_window_has_phase1a_docks tests/integration/test_gui_phase1a.py::test_library_can_place_resistor -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task5
```

Expected: FAIL because `MainWindow` does not expose the docks and scene.

- [ ] **Step 3: Implement the main-window shell**

Replace `src/pcbsmith/ui/main_window.py` with:

```python
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QTextEdit,
    QToolBar,
)

from pcbsmith.core.geom import Point
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.ui.schematic_scene import SchematicScene
from pcbsmith.ui.schematic_view import SchematicView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_dir: Path | None = None
        self.setWindowTitle("PCBSmith")

        self.scene = SchematicScene()
        self.view = SchematicView(self.scene)
        self.setCentralWidget(self.view)

        self.library_list = QListWidget()
        for symbol in SYMBOLS.values():
            self.library_list.addItem(f"{symbol.id} - {symbol.name}")
        self.library_list.itemDoubleClicked.connect(lambda _item: self.place_resistor_at_origin())
        self.library_dock = QDockWidget("Library", self)
        self.library_dock.setWidget(self.library_list)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console_dock = QDockWidget("Console", self)
        self.console_dock.setWidget(self.console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)

        self._build_actions()

    def _build_actions(self) -> None:
        toolbar = QToolBar("Main", self)
        self.addToolBar(toolbar)

        place_resistor = QAction("Place R", self)
        place_resistor.triggered.connect(self.place_resistor_at_origin)
        toolbar.addAction(place_resistor)

        fit_view = QAction("Fit", self)
        fit_view.triggered.connect(self.view.fit_to_contents)
        toolbar.addAction(fit_view)

    def place_resistor_at_origin(self) -> None:
        self.scene.place_resistor(Point(x=0, y=0))
        self.console.append("Placed resistor")

    def show_error(self, message: str) -> None:
        self.console.append(message)
        QMessageBox.warning(self, "PCBSmith", message)
```

- [ ] **Step 4: Run the main-window tests**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_main_window_has_phase1a_docks tests/integration/test_gui_phase1a.py::test_library_can_place_resistor -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task5
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase1a.py
git commit -m "feat: add schematic editor shell"
```

## Task 6: Project Open, Save, And Reopen

**Files:**
- Modify: `src/pcbsmith/ui/main_window.py`
- Test: `tests/integration/test_gui_phase1a.py`

- [ ] **Step 1: Add failing project persistence test**

Append this test to `tests/integration/test_gui_phase1a.py`:

```python
from pcbsmith.services import project_io


def test_gui_saves_and_reopens_schematic(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    project_dir = tmp_path / "demo"
    project_io.create_project(project_dir, "Demo")

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_dir)
    window.scene.place_resistor(Point(x=0, y=0), value="10k")
    window.scene.place_resistor(Point(x=20_320_000, y=0), value="1k")
    window.scene.add_wire(Point(x=5_080_000, y=0), Point(x=15_240_000, y=0))
    window.save_project()

    reopened = MainWindow()
    qtbot.addWidget(reopened)
    reopened.open_project(project_dir)

    schematic = reopened.scene.editor_state.to_schematic()
    assert [symbol.reference for symbol in schematic.symbols] == ["R1", "R2"]
    assert len(schematic.wires) == 1
```

- [ ] **Step 2: Run the persistence test to verify it fails**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_gui_saves_and_reopens_schematic -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task6
```

Expected: FAIL because `MainWindow.open_project` and `save_project` do not exist.

- [ ] **Step 3: Add project persistence methods**

Modify `src/pcbsmith/ui/main_window.py`:

```python
from PySide6.QtWidgets import QFileDialog, QInputDialog
from pcbsmith.services import project_io
from pcbsmith.ui.editor_state import EditorState
```

Add file actions inside `_build_actions`:

```python
        file_menu = self.menuBar().addMenu("&File")

        new_project = QAction("New Project", self)
        new_project.triggered.connect(self.create_project_dialog)
        file_menu.addAction(new_project)

        open_project = QAction("Open Project", self)
        open_project.triggered.connect(self.open_project_dialog)
        file_menu.addAction(open_project)

        save_project = QAction("Save", self)
        save_project.triggered.connect(self.save_project)
        file_menu.addAction(save_project)
        toolbar.addAction(save_project)
```

Add these methods to `MainWindow`:

```python
    def create_project(self, project_dir: Path, name: str) -> None:
        project_io.create_project(project_dir, name)
        self.open_project(project_dir)

    def create_project_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Create PCBSmith Project")
        if not directory:
            return
        name, accepted = QInputDialog.getText(self, "Project Name", "Name:")
        if not accepted or not name:
            return
        self.create_project(Path(directory), name)

    def open_project_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open PCBSmith Project")
        if not directory:
            return
        self.open_project(Path(directory))

    def open_project(self, project_dir: Path) -> None:
        project = project_io.load_project(project_dir)
        schematic = project_io.load_schematic(project_dir, project.schematics[0])
        self.project_dir = project_dir
        self.project = project
        self.scene.load_editor_state(EditorState.from_schematic(schematic))
        self.console.append(f"Opened {project.name}")

    def save_project(self) -> None:
        if self.project_dir is None:
            self.show_error("No project is open")
            return
        project = project_io.load_project(self.project_dir)
        project_io.save_schematic(
            self.project_dir,
            project.schematics[0],
            self.scene.editor_state.to_schematic(),
        )
        self.console.append("Saved schematic")
```

Also initialize `self.project = None` in `__init__`.

- [ ] **Step 4: Run the persistence test**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_gui_saves_and_reopens_schematic -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task6
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase1a.py
git commit -m "feat: save and reopen gui schematics"
```

## Task 7: ERC In The Console Dock

**Files:**
- Modify: `src/pcbsmith/ui/main_window.py`
- Test: `tests/integration/test_gui_phase1a.py`

- [ ] **Step 1: Add failing ERC test**

Append this test to `tests/integration/test_gui_phase1a.py`:

```python
def test_gui_runs_erc_to_console(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0), value="10k")

    window.run_erc()

    assert "ERC001" in window.console.toPlainText()
```

- [ ] **Step 2: Run the ERC test to verify it fails**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_gui_runs_erc_to_console -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task7
```

Expected: FAIL because `MainWindow.run_erc` does not exist.

- [ ] **Step 3: Implement ERC action and console output**

Modify imports in `src/pcbsmith/ui/main_window.py`:

```python
from pcbsmith.services import erc, project_io
from pcbsmith.services.builtin_library import SYMBOLS
```

Add a toolbar action in `_build_actions`:

```python
        run_erc = QAction("ERC", self)
        run_erc.triggered.connect(self.run_erc)
        toolbar.addAction(run_erc)
```

Add this method to `MainWindow`:

```python
    def run_erc(self) -> None:
        issues = erc.run_erc(self.scene.editor_state.to_schematic(), SYMBOLS)
        if not issues:
            self.console.append("ERC passed")
            return
        for issue in issues:
            self.console.append(f"{issue.code}: {issue.message} ({issue.where})")
```

- [ ] **Step 4: Run the ERC test**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_gui_runs_erc_to_console -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task7
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase1a.py
git commit -m "feat: show erc results in gui"
```

## Task 8: Mouse Placement And Wire Interaction

**Files:**
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Modify: `src/pcbsmith/ui/main_window.py`
- Test: `tests/integration/test_gui_phase1a.py`

- [ ] **Step 1: Add failing tool-mode test**

Append this test to `tests/integration/test_gui_phase1a.py`:

```python
def test_scene_tools_place_resistor_and_wire() -> None:
    scene = SchematicScene()

    scene.set_tool("place_resistor")
    scene.handle_canvas_click(Point(x=0, y=0))
    scene.handle_canvas_click(Point(x=20_320_000, y=0))
    scene.set_tool("wire")
    scene.handle_canvas_click(Point(x=5_080_000, y=0))
    scene.handle_canvas_click(Point(x=15_240_000, y=0))

    schematic = scene.editor_state.to_schematic()
    assert [symbol.reference for symbol in schematic.symbols] == ["R1", "R2"]
    assert len(schematic.wires) == 1
```

- [ ] **Step 2: Run the tool-mode test to verify it fails**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_scene_tools_place_resistor_and_wire -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task8
```

Expected: FAIL because `set_tool` and `handle_canvas_click` do not exist.

- [ ] **Step 3: Implement basic tool state**

Modify `src/pcbsmith/ui/schematic_scene.py`:

```python
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

ToolName = Literal["select", "place_resistor", "wire"]
```

Initialize in `__init__`:

```python
        self._tool: ToolName = "select"
        self._pending_wire_start: Point | None = None
```

Add methods:

```python
    def set_tool(self, tool: ToolName) -> None:
        self._tool = tool
        self._pending_wire_start = None

    def handle_canvas_click(self, position: Point) -> None:
        if self._tool == "place_resistor":
            self.place_resistor(position)
            return
        if self._tool == "wire":
            snapped = snap(position, GRID_NM)
            if self._pending_wire_start is None:
                self._pending_wire_start = snapped
                return
            self.add_wire(self._pending_wire_start, snapped)
            self._pending_wire_start = None

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._tool != "select":
            position = event.scenePos()
            self.handle_canvas_click(Point(x=int(position.x()), y=int(position.y())))
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.set_tool("select")
            event.accept()
            return
        super().keyPressEvent(event)
```

- [ ] **Step 4: Wire toolbar actions to tools**

Modify `_build_actions` in `src/pcbsmith/ui/main_window.py`:

```python
        wire = QAction("Wire", self)
        wire.triggered.connect(lambda: self.scene.set_tool("wire"))
        toolbar.addAction(wire)
```

Change the `place_resistor` action:

```python
        place_resistor = QAction("Place R", self)
        place_resistor.triggered.connect(lambda: self.scene.set_tool("place_resistor"))
        toolbar.addAction(place_resistor)
```

Keep `place_resistor_at_origin` for tests.

- [ ] **Step 5: Run the tool-mode test**

Run:

```powershell
python -m pytest tests/integration/test_gui_phase1a.py::test_scene_tools_place_resistor_and_wire -q -p no:cacheprovider --basetemp .tmp/pytest-phase1a-task8
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/ui/schematic_scene.py src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase1a.py
git commit -m "feat: add basic schematic edit tools"
```

## Task 9: Full Verification And README

**Files:**
- Modify: `README.md`
- Test: all tests

- [ ] **Step 1: Update README with GUI usage**

Append this section to `README.md`:

````markdown
## Phase 1A GUI

Phase 1A adds the first PySide6 schematic editor slice. It is intentionally narrow:
launch the editor, open or create a PCBSmith project, place resistor symbols, draw a
basic wire, save/reopen the schematic, navigate with zoom/pan/scroll, and run ERC in
the console dock.

Run the GUI after installing the project:

```powershell
pcbsmith-gui
```

The GUI reuses the Phase 0 project JSON format. LLM-assisted editing, first-run
tutorials, component family filters, labels, junction automation, and PCB layout are
future phases.
````

- [ ] **Step 2: Run style checks**

Run:

```powershell
python -m ruff check src tests
```

Expected: PASS.

- [ ] **Step 3: Run all tests with a project-local temp directory**

Run:

```powershell
$env:TMP='D:\AI\PCB designer\.tmp'; $env:TEMP='D:\AI\PCB designer\.tmp'; New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null; python -m pytest -q -p no:cacheprovider --basetemp 'D:\AI\PCB designer\.tmp\pytest-phase1a-full'
```

Expected: PASS.

- [ ] **Step 4: Manually launch the GUI**

Run:

```powershell
pcbsmith-gui
```

Expected: the PCBSmith window opens with the grid canvas, library dock, console dock,
toolbar actions, zoom/pan/scroll behavior, and fit action.

- [ ] **Step 5: Commit**

```powershell
git add README.md
git commit -m "docs: document phase 1a gui"
```

- [ ] **Step 6: Push the branch**

```powershell
git push
```

Expected: `origin/codex/phase-1a-schematic-editor` is updated.

## Self-Review

- Spec coverage: the plan covers PySide6 UI layer, GUI script, main window, central canvas, library dock, console dock, 100 mil grid, zoom, pan, scroll, fit-to-view, resistor placement, wire drawing, save/open, ERC console output, focused tests, README update, and preservation of the existing `ui -> services -> core` boundary.
- Deferred scope: LLM panels, first-run tutorials, component family filters, labels, junction automation, inspector, full undo/redo, PCB layout, exports, and multi-sheet support stay outside Phase 1A.
- Type consistency: `EditorState`, `SchematicScene`, `SchematicView`, and `MainWindow` names are introduced before later tasks reference them. Test snippets use the same method names as implementation snippets.
- Verification: task-level tests run after each feature, then `ruff` and the full pytest suite run before final push.
