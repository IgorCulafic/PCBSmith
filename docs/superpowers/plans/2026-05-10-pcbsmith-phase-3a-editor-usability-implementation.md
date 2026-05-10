# PCBSmith Phase 3A Editor Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the PCBSmith GUI readable and CAD-like by adding a light editor theme, real menus/tool actions, collapsible component families, armed placement with preview, keyboard shortcuts, and basic mirror controls.

**Architecture:** Keep the existing PySide6 app structure. Add focused UI helpers for editor theme constants, component family browsing, and placement preview behavior while preserving the current `ui -> services -> core` boundary.

**Tech Stack:** Python 3.12, PySide6, pytest-qt, ruff, existing PCBSmith catalog/editor services.

---

## File Structure

- Modify `src/pcbsmith/ui/items.py`: readable pens/colors, symbol pin handle rendering, optional preview rendering.
- Modify `src/pcbsmith/ui/schematic_scene.py`: armed catalog placement, placement preview, Escape cancel, click-to-place behavior, mirror methods.
- Modify `src/pcbsmith/ui/component_browser.py`: collapsible family sections and activation-as-arm behavior.
- Modify `src/pcbsmith/ui/main_window.py`: menu bar, icon-oriented toolbar text, shortcuts, arm placement actions, mirror actions.
- Modify `src/pcbsmith/ui/editor_state.py`: add symbol mirror/flip state updates if existing model supports it through transform fields; otherwise represent mirror visually in UI only for this phase.
- Modify `src/pcbsmith/ui/inspector.py`: expose mirror/flip controls only if the model can persist them cleanly in this phase.
- Modify `tests/integration/test_gui_phase2.py`: update old add-at-origin behavior expectations.
- Create `tests/integration/test_gui_phase3a.py`: GUI usability reset tests.
- Create `tests/unit/ui/test_component_browser_phase3a.py`: component family/browser tests if browser-only checks become too crowded in integration tests.
- Modify `README.md`: update GUI notes after behavior changes.

## Commands

Use the repaired project environment:

```powershell
cd "D:\AI\PCB designer"
.\.venv\Scripts\python.exe -m ruff check src tests
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=".tmp/pytest-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

Launch the GUI after implementation:

```powershell
cd "D:\AI\PCB designer"
.\.venv\Scripts\pcbsmith-gui.exe
```

## Task 1: Readable Editor Theme

**Files:**
- Modify: `src/pcbsmith/ui/items.py`
- Test: `tests/integration/test_gui_phase3a.py`

- [ ] **Step 1: Write failing rendering constants test**

Add this test:

```python
from PySide6.QtGui import QColor

from pcbsmith.ui import items


def test_phase3a_item_theme_is_readable_on_light_canvas() -> None:
    assert items.CANVAS_BACKGROUND == QColor(248, 250, 252)
    assert items.GRID_COLOR == QColor(221, 226, 232)
    assert items.SYMBOL_PEN.color() == QColor(24, 32, 42)
    assert items.SYMBOL_TEXT_COLOR == QColor(17, 24, 39)
    assert items.CONNECTION_HANDLE_COLOR == QColor(27, 115, 209)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_gui_phase3a.py::test_phase3a_item_theme_is_readable_on_light_canvas -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3a-theme-red"
```

Expected: FAIL because the constants do not exist.

- [ ] **Step 3: Add theme constants and use them**

In `src/pcbsmith/ui/items.py`, add constants near the existing drawing constants:

```python
CANVAS_BACKGROUND = QColor(248, 250, 252)
GRID_COLOR = QColor(221, 226, 232)
SYMBOL_TEXT_COLOR = QColor(17, 24, 39)
SYMBOL_PEN = QPen(QColor(24, 32, 42), 0)
WIRE_PEN = QPen(QColor(25, 96, 179), 0)
CONNECTION_HANDLE_COLOR = QColor(27, 115, 209)
CONNECTION_HANDLE_FILL = QColor(255, 255, 255)
```

Update `SymbolItem.__init__`:

```python
label.setDefaultTextColor(SYMBOL_TEXT_COLOR)
```

Update `SymbolItem.paint`:

```python
painter.setPen(SYMBOL_PEN)
```

Add pin handles at the lead ends in `SymbolItem.paint`:

```python
handle_radius = 220_000
painter.setPen(QPen(CONNECTION_HANDLE_COLOR, 0))
painter.setBrush(CONNECTION_HANDLE_FILL)
painter.drawEllipse(
    int(-SYMBOL_WIDTH / 2 - handle_radius / 2),
    int(-handle_radius / 2),
    handle_radius,
    handle_radius,
)
painter.drawEllipse(
    int(SYMBOL_WIDTH / 2 - handle_radius / 2),
    int(-handle_radius / 2),
    handle_radius,
    handle_radius,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/items.py tests/integration/test_gui_phase3a.py
git commit -m "feat: improve editor item contrast"
```

## Task 2: Apply Light Canvas Theme In The View

**Files:**
- Modify: `src/pcbsmith/ui/schematic_view.py`
- Test: `tests/integration/test_gui_phase3a.py`

- [ ] **Step 1: Write failing canvas theme test**

Add:

```python
from PySide6.QtGui import QBrush

from pcbsmith.ui.items import CANVAS_BACKGROUND
from pcbsmith.ui.main_window import MainWindow


def test_phase3a_canvas_uses_light_background(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.scene.backgroundBrush() == QBrush(CANVAS_BACKGROUND)
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_gui_phase3a.py::test_phase3a_canvas_uses_light_background -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3a-canvas-red"
```

Expected: FAIL because the scene background does not use the theme constant.

- [ ] **Step 3: Set scene background and grid color**

In `src/pcbsmith/ui/schematic_view.py`, import:

```python
from pcbsmith.ui.items import CANVAS_BACKGROUND, GRID_COLOR
```

In `SchematicView.__init__`, after `super().__init__`, set:

```python
self.scene().setBackgroundBrush(CANVAS_BACKGROUND)
```

In the grid drawing method, replace hardcoded grid pen color with:

```python
painter.setPen(QPen(GRID_COLOR, 0))
```

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/schematic_view.py tests/integration/test_gui_phase3a.py
git commit -m "feat: apply readable canvas theme"
```

## Task 3: Menu Bar And Tool-Oriented Toolbar

**Files:**
- Modify: `src/pcbsmith/ui/main_window.py`
- Test: `tests/integration/test_gui_phase3a.py`

- [ ] **Step 1: Write failing menu and toolbar tests**

Add:

```python
from pcbsmith.ui.main_window import MainWindow


def _menu_titles(window: MainWindow) -> set[str]:
    return {action.text().replace("&", "") for action in window.menuBar().actions()}


def _toolbar_texts(window: MainWindow) -> set[str]:
    return {
        action.text()
        for action in window.schematic_toolbar.actions()
        if action.text()
    }


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


def test_phase3a_toolbar_is_tool_oriented(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    texts = _toolbar_texts(window)
    assert {"Select", "Pan", "Wire", "Label", "No Connect", "Rotate", "Mirror H", "Fit", "ERC"}.issubset(texts)
    assert "Add R" not in texts
    assert "Add C" not in texts
    assert "Add LED" not in texts
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_gui_phase3a.py::test_phase3a_main_window_has_cad_menus tests/integration/test_gui_phase3a.py::test_phase3a_toolbar_is_tool_oriented -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3a-menu-red"
```

Expected: FAIL because only File exists and toolbar still has component add buttons.

- [ ] **Step 3: Replace menu setup**

In `MainWindow.__init__`, replace `_create_file_menu()` with:

```python
self._create_menus()
```

Add `self.mirror_horizontal_action = QAction("Mirror H", self)` next to existing action fields.

Replace `_create_file_menu` with `_create_menus` that creates:

```python
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

    fit_action = QAction("Fit", self)
    fit_action.triggered.connect(self.view.fit_to_contents)
    view_menu.addAction(fit_action)

    components_menu.addAction(self._component_action("Resistor", "pcbs:resistor_0603", "R"))
    components_menu.addAction(self._component_action("Capacitor", "pcbs:capacitor_0603", "C"))
    components_menu.addAction(self._component_action("Diode", "pcbs:diode_0603", "D"))
    components_menu.addAction(self._component_action("LED", "pcbs:led_0603", "L"))

    select_action = QAction("Select", self)
    select_action.setShortcut(QKeySequence("V"))
    select_action.triggered.connect(lambda: self.scene.set_tool("select"))
    tools_menu.addAction(select_action)

    wire_action = QAction("Wire", self)
    wire_action.setShortcut(QKeySequence("W"))
    wire_action.triggered.connect(lambda: self.scene.set_tool("wire"))
    tools_menu.addAction(wire_action)

    label_action = QAction("Label", self)
    label_action.setShortcut(QKeySequence("T"))
    label_action.triggered.connect(lambda: self.scene.set_tool("label"))
    tools_menu.addAction(label_action)

    no_connect_action = QAction("No Connect", self)
    no_connect_action.triggered.connect(lambda: self.scene.set_tool("no_connect"))
    tools_menu.addAction(no_connect_action)

    options_menu.addAction(QAction("Grid And Snap Settings", self))
    project_menu.addAction(QAction("Project Settings", self))
    help_menu.addAction(QAction("About PCBSmith", self))
```

Add helper:

```python
def _component_action(self, text: str, entry_id: str, shortcut: str) -> QAction:
    action = QAction(text, self)
    action.setShortcut(QKeySequence(shortcut))
    action.triggered.connect(lambda: self.arm_catalog_entry_by_id(entry_id))
    self.addAction(action)
    return action
```

Keep local variables for select/wire/label/no-connect actions if needed by toolbar, or store them as `self.select_action`, `self.wire_action`, `self.label_action`, and `self.no_connect_action`.

- [ ] **Step 4: Replace toolbar component buttons**

Update `_create_toolbar` so it adds tool/action controls, not `Add R`, `Add C`, `Add LED`:

```python
toolbar.addAction(self.select_action)
toolbar.addAction(QAction("Pan", self))
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
toolbar.addAction(fit_action)
toolbar.addAction(run_erc)
```

- [ ] **Step 5: Run tests to verify they pass**

Run the same pytest command from Step 2.

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase3a.py
git commit -m "feat: add cad menus and tool toolbar"
```

## Task 4: Collapsible Component Families

**Files:**
- Modify: `src/pcbsmith/ui/component_browser.py`
- Test: `tests/unit/ui/test_component_browser_phase3a.py`

- [ ] **Step 1: Write failing browser tests**

Create `tests/unit/ui/test_component_browser_phase3a.py`:

```python
from PySide6.QtWidgets import QToolBox

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
    assert "pcbs:spst_switch_th" in visible
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/ui/test_component_browser_phase3a.py -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3a-browser-red"
```

Expected: FAIL because `family_box` does not exist.

- [ ] **Step 3: Replace flat list with family toolbox**

In `src/pcbsmith/ui/component_browser.py`, add imports:

```python
from PySide6.QtWidgets import QGridLayout, QPushButton, QToolBox
```

Add role:

```python
BUTTON_ENTRY_ID_PROPERTY = "catalogEntryId"
```

In `__init__`, replace `self.component_list = QListWidget()` as the only visual list with:

```python
self.family_box = QToolBox()
self.component_list = QListWidget()
```

Build layout:

```python
layout.addWidget(self.search_box)
layout.addWidget(self.preferred_only)
layout.addWidget(self.family_box)
layout.addWidget(self.component_list)
```

In `refresh`, when search text is empty, hide `component_list`, show `family_box`, and populate family pages. When search text is non-empty, show `component_list`, hide `family_box`, and use the existing search list behavior.

Create a basic family page:

```python
def _build_basic_family_page(self, entries: list[CatalogEntry]) -> QWidget:
    page = QWidget()
    grid = QGridLayout()
    for index, entry in enumerate(entries):
        button = QPushButton(entry.family.name)
        button.setProperty(BUTTON_ENTRY_ID_PROPERTY, entry.id)
        button.clicked.connect(lambda _checked=False, entry_id=entry.id: self.entry_activated.emit(entry_id))
        grid.addWidget(button, index // 3, index % 3)
    page.setLayout(grid)
    return page
```

Use catalog group names to add pages, with `Basic Components` first.

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/component_browser.py tests/unit/ui/test_component_browser_phase3a.py
git commit -m "feat: group component browser families"
```

## Task 5: Armed Placement And Preview

**Files:**
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Modify: `src/pcbsmith/ui/main_window.py`
- Test: `tests/integration/test_gui_phase3a.py`

- [ ] **Step 1: Write failing armed placement tests**

Add:

```python
from pcbsmith.core.geom import Point
from pcbsmith.ui.main_window import MainWindow


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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_gui_phase3a.py::test_component_action_arms_placement_without_adding_symbol tests/integration/test_gui_phase3a.py::test_canvas_click_places_armed_component tests/integration/test_gui_phase3a.py::test_escape_cancels_armed_placement -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3a-placement-red"
```

Expected: FAIL because `arm_catalog_entry_by_id`, `armed_catalog_entry_id`, and `cancel_active_tool` do not exist.

- [ ] **Step 3: Add armed placement state to scene**

In `SchematicScene.__init__`, add:

```python
self._armed_catalog_entry: CatalogEntry | None = None
self._placement_preview: SymbolItem | None = None
```

Add methods:

```python
def arm_catalog_entry(self, entry: CatalogEntry) -> None:
    self._tool = "place_catalog"
    self._armed_catalog_entry = entry
    self._pending_wire_start = None

def armed_catalog_entry_id(self) -> str | None:
    if self._armed_catalog_entry is None:
        return None
    return self._armed_catalog_entry.id

def cancel_active_tool(self) -> None:
    self._tool = "select"
    self._armed_catalog_entry = None
    self._pending_wire_start = None
    if self._placement_preview is not None:
        self.removeItem(self._placement_preview)
        self._placement_preview = None
```

Update `_tools` to include `"place_catalog"`.

Update `handle_canvas_click` before wire handling:

```python
if self._tool == "place_catalog" and self._armed_catalog_entry is not None:
    self.place_catalog_entry(self._armed_catalog_entry, position)
    self.cancel_active_tool()
    return
```

Update `keyPressEvent` Escape branch:

```python
self.cancel_active_tool()
```

- [ ] **Step 4: Add main-window arming method**

In `MainWindow`, replace `place_catalog_entry_by_id` placement behavior with:

```python
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
```

Update `place_selected_component_at_origin` to arm the selected entry instead of placing:

```python
self.scene.arm_catalog_entry(entry)
self.console.append(f"Ready to place {entry.variant.name}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run the same pytest command from Step 2.

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/ui/schematic_scene.py src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase3a.py
git commit -m "feat: arm catalog placement from ui"
```

## Task 6: Mirror Action And Shortcuts

**Files:**
- Modify: `src/pcbsmith/ui/editor_state.py`
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Modify: `src/pcbsmith/ui/main_window.py`
- Test: `tests/integration/test_gui_phase3a.py`

- [ ] **Step 1: Write failing mirror and shortcut tests**

Add:

```python
from PySide6.QtGui import QKeySequence

from pcbsmith.core.geom import Point
from pcbsmith.ui.main_window import MainWindow


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

    mirrored = window.scene.symbol_items()[0]
    assert mirrored.transform().m11() == -1
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_gui_phase3a.py::test_phase3a_shortcuts_are_registered tests/integration/test_gui_phase3a.py::test_mirror_horizontal_updates_selected_symbol_transform -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3a-shortcuts-red"
```

Expected: FAIL because mirror action and shortcut registrations are incomplete.

- [ ] **Step 3: Add visual mirror support**

If `SymbolInstance` has no persistent mirror fields, keep Phase 3A mirror visual-only and document persistence for Phase 3C. In `SymbolItem`, add:

```python
self._mirrored_horizontally = False

def set_mirrored_horizontally(self, mirrored: bool) -> None:
    self._mirrored_horizontally = mirrored
    self.setScale(-1 if mirrored else 1)
```

In `SchematicScene`, add:

```python
def mirror_selection_horizontally(self, selection: SelectionKey) -> None:
    if selection.kind != "symbol":
        raise ValueError(f"Cannot mirror {selection.kind}")
    for item in self._symbol_items:
        if item.selection_key() == selection:
            item.set_mirrored_horizontally(item.transform().m11() >= 0)
            return
    raise ValueError(f"Unknown selected symbol: {selection.key}")
```

- [ ] **Step 4: Wire action and shortcuts**

In `MainWindow.__init__`, configure:

```python
self.mirror_horizontal_action.setShortcut(QKeySequence("H"))
self.mirror_horizontal_action.triggered.connect(self.mirror_horizontal_selected)
self.addAction(self.mirror_horizontal_action)
```

Add method:

```python
def mirror_horizontal_selected(self) -> None:
    selection = self.scene.selected_key()
    if selection is None:
        return
    try:
        self.scene.mirror_selection_horizontally(selection)
    except ValueError as exc:
        self.show_error(str(exc))
    self.refresh_inspector()
```

- [ ] **Step 5: Run tests to verify they pass**

Run the same pytest command from Step 2.

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/ui/items.py src/pcbsmith/ui/schematic_scene.py src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase3a.py
git commit -m "feat: add editor shortcuts and mirror action"
```

## Task 7: Update Existing Phase 2 GUI Tests

**Files:**
- Modify: `tests/integration/test_gui_phase2.py`
- Modify: `tests/integration/test_gui_phase1a.py`

- [ ] **Step 1: Run impacted tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_gui_phase1a.py tests/integration/test_gui_phase2.py -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3a-compat-red"
```

Expected: Some tests that expected toolbar component actions to place at origin now fail.

- [ ] **Step 2: Update behavior expectations**

Change toolbar/catalog tests from "places immediately" to "arms placement":

```python
_toolbar_action(window, "Resistor").trigger()
assert window.scene.armed_catalog_entry_id() == "pcbs:resistor_0603"
assert len(window.scene.editor_state.symbols) == 0
```

For compatibility tests that need immediate placement, use scene helpers directly:

```python
entry = component_catalog.entry_by_id(window.component_browser.catalog, "pcbs:resistor_0603")
window.scene.place_catalog_entry(entry, Point(x=0, y=0))
```

- [ ] **Step 3: Run impacted tests again**

Run the same pytest command from Step 1.

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/integration/test_gui_phase1a.py tests/integration/test_gui_phase2.py
git commit -m "test: update gui placement expectations"
```

## Task 8: README And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README GUI behavior**

Add a short GUI note:

```markdown
The GUI includes a schematic canvas, component browser, project/console/inspector docks, CAD-style menus, keyboard shortcuts, and click-to-place component placement. Component browser actions arm placement; click the canvas to place the previewed part.
```

- [ ] **Step 2: Run ruff**

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
```

Expected: `All checks passed!`

- [ ] **Step 3: Run full tests**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=".tmp/pytest-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

Expected: all tests pass.

- [ ] **Step 4: Launch GUI**

```powershell
.\.venv\Scripts\pcbsmith-gui.exe
```

Expected: the app opens with a light readable canvas, menu bar, tool-oriented toolbar, collapsible Basic Components family, and armed placement behavior.

- [ ] **Step 5: Commit README and verification notes**

```powershell
git add README.md
git commit -m "docs: document phase 3a gui behavior"
```

## Self-Review

- Spec coverage: Phase 3A contrast, menus, toolbar, component families, armed placement, shortcuts, transform controls, and GUI launch are covered.
- Phase 3B routing and Phase 3C polish are intentionally not included in this implementation plan; they have separate scope in the design spec.
- Placeholder scan: no placeholder tasks or open-ended instructions remain.
- Type consistency: planned methods are `arm_catalog_entry`, `armed_catalog_entry_id`, `cancel_active_tool`, `arm_catalog_entry_by_id`, and `mirror_horizontal_selected`; tests use the same names.
