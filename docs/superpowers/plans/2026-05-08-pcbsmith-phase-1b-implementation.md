# PCBSmith Phase 1B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1B schematic editing core: selectable/editable schematic objects, undo/redo, inspector editing, net labels, and no-connect markers.

**Architecture:** Keep the existing `ui -> services -> core` boundary. Add non-Qt editing commands and undo history below the Qt scene so direct GUI edits and future structured LLM edits can share the same state transitions. Keep project I/O and ERC in services.

**Tech Stack:** Python 3.11-3.13, PySide6, Pydantic, pytest, pytest-qt, ruff.

---

## Current Baseline

Phase 1A is complete on branch `codex/phase-1b-schematic-editing-core` at or after commit `a6b49c5`.

Important existing files:

- `src/pcbsmith/ui/editor_state.py`: immutable `EditorState` with symbols, wires, junctions, labels, and no-connects.
- `src/pcbsmith/ui/items.py`: `SymbolItem` and `WireItem`.
- `src/pcbsmith/ui/schematic_scene.py`: tool modes, resistor placement, wire placement, rendering.
- `src/pcbsmith/ui/main_window.py`: main window, file actions, library dock, console dock, toolbar, ERC.
- `tests/unit/ui/test_editor_state.py`: non-Qt editor-state tests.
- `tests/integration/test_gui_phase1a.py`: GUI integration tests.

Known local test environment:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest ...
```

Use a `.tmp` basetemp for pytest commands to avoid Windows temp-directory permission issues.

## File Structure

Create:

- `src/pcbsmith/ui/history.py`: state-snapshot undo/redo history.
- `src/pcbsmith/ui/selection.py`: typed selection keys for symbols, wires, labels, and no-connects.
- `src/pcbsmith/ui/inspector.py`: right-side inspector widget for selected item details and editable symbol/label fields.
- `tests/unit/ui/test_history.py`: undo/redo unit tests.
- `tests/unit/ui/test_selection.py`: selection helper tests if needed.
- `tests/unit/ui/test_inspector.py`: inspector widget tests.
- `tests/integration/test_gui_phase1b.py`: Phase 1B GUI workflow tests.

Modify:

- `src/pcbsmith/ui/editor_state.py`: add editing commands.
- `src/pcbsmith/ui/items.py`: add label/no-connect graphics items and stable item selection keys.
- `src/pcbsmith/ui/schematic_scene.py`: render all supported items, selection, move/delete/rotate command routing, label/no-connect tools.
- `src/pcbsmith/ui/main_window.py`: add inspector dock, undo/redo/delete/rotate/select/label/no-connect actions, project-open history reset.
- `README.md`: update Phase 1B status after implementation.

## Shared Types For Phase 1B

Workers should converge on these names unless a reviewer finds a better local fit:

```python
from dataclasses import dataclass
from typing import Literal

SelectionKind = Literal["symbol", "wire", "label", "no_connect"]


@dataclass(frozen=True)
class SelectionKey:
    kind: SelectionKind
    key: str
```

Use symbol references as symbol keys. Use stable string indexes for wires, labels, and no-connects in the current `EditorState`, for example `"0"`, `"1"`. Phase 1B does not need durable UUIDs, but all index-based editing must validate that the index still exists before changing state.

## Task 1: Selection Keys And Editor-State Commands

**Files:**
- Create: `src/pcbsmith/ui/selection.py`
- Modify: `src/pcbsmith/ui/editor_state.py`
- Test: `tests/unit/ui/test_editor_state.py`
- Test: `tests/unit/ui/test_selection.py`

- [ ] **Step 1: Add failing editor-state command tests**

Append these tests to `tests/unit/ui/test_editor_state.py`:

```python
import pytest

from pcbsmith.core.schematic import NetLabel, NoConnect
from pcbsmith.ui.selection import SelectionKey


def test_move_symbol_updates_position_without_dropping_other_fields() -> None:
    state = EditorState.blank("main").place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    moved = state.move_item(SelectionKey("symbol", "R1"), Point(x=2_540_000, y=0))

    schematic = moved.to_schematic()

    assert schematic.symbols[0].position == Point(x=2_540_000, y=0)
    assert schematic.symbols[0].reference == "R1"


def test_delete_symbol_removes_selected_symbol() -> None:
    state = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=2_540_000, y=0))
    )

    updated = state.delete_item(SelectionKey("symbol", "R1"))

    assert [symbol.reference for symbol in updated.to_schematic().symbols] == ["R2"]


def test_rotate_symbol_uses_right_angle_steps() -> None:
    state = EditorState.blank("main").place_symbol("stdlib:R", "10k", Point(x=0, y=0))

    updated = state.rotate_symbol("R1", 90)

    assert updated.to_schematic().symbols[0].rotation_deg == 90


def test_edit_symbol_rejects_duplicate_reference() -> None:
    state = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=2_540_000, y=0))
    )

    with pytest.raises(ValueError, match="Duplicate reference"):
        state.update_symbol("R2", new_reference="R1")


def test_add_rename_and_delete_net_label() -> None:
    state = EditorState.blank("main").add_label("VIN", Point(x=0, y=0))

    renamed = state.update_label(0, name="VOUT")
    deleted = renamed.delete_item(SelectionKey("label", "0"))

    assert renamed.to_schematic().labels == (NetLabel(name="VOUT", position=Point(x=0, y=0)),)
    assert deleted.to_schematic().labels == ()


def test_add_and_delete_no_connect() -> None:
    state = EditorState.blank("main").add_no_connect(Point(x=0, y=0))

    deleted = state.delete_item(SelectionKey("no_connect", "0"))

    assert state.to_schematic().no_connects == (NoConnect(position=Point(x=0, y=0)),)
    assert deleted.to_schematic().no_connects == ()
```

- [ ] **Step 2: Add failing selection helper tests**

Create `tests/unit/ui/test_selection.py`:

```python
from __future__ import annotations

import pytest

from pcbsmith.ui.selection import SelectionKey, parse_index_key


def test_parse_index_key_accepts_non_negative_integer_strings() -> None:
    assert parse_index_key(SelectionKey("wire", "0")) == 0


def test_parse_index_key_rejects_non_integer_keys() -> None:
    with pytest.raises(ValueError, match="Invalid wire key"):
        parse_index_key(SelectionKey("wire", "abc"))
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run:

```powershell
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/ui/test_editor_state.py tests/unit/ui/test_selection.py -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task1-red'
```

Expected: FAIL because `pcbsmith.ui.selection` and the new `EditorState` command methods do not exist.

- [ ] **Step 4: Implement `selection.py`**

Create `src/pcbsmith/ui/selection.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SelectionKind = Literal["symbol", "wire", "label", "no_connect"]


@dataclass(frozen=True)
class SelectionKey:
    kind: SelectionKind
    key: str


def parse_index_key(selection: SelectionKey) -> int:
    try:
        index = int(selection.key)
    except ValueError as exc:
        raise ValueError(f"Invalid {selection.kind} key: {selection.key}") from exc
    if index < 0:
        raise ValueError(f"Invalid {selection.kind} key: {selection.key}")
    return index
```

- [ ] **Step 5: Implement editor-state commands**

Modify `src/pcbsmith/ui/editor_state.py`:

```python
from pcbsmith.ui.selection import SelectionKey, parse_index_key
```

Add these methods to `EditorState`:

```python
    def move_item(self, selection: SelectionKey, position: Point) -> EditorState:
        if selection.kind == "symbol":
            return replace(
                self,
                symbols=tuple(
                    symbol.model_copy(update={"position": position})
                    if symbol.reference == selection.key
                    else symbol
                    for symbol in self.symbols
                ),
            )
        if selection.kind == "label":
            index = self._validated_index(selection, len(self.labels))
            labels = list(self.labels)
            labels[index] = labels[index].model_copy(update={"position": position})
            return replace(self, labels=tuple(labels))
        if selection.kind == "no_connect":
            index = self._validated_index(selection, len(self.no_connects))
            no_connects = list(self.no_connects)
            no_connects[index] = no_connects[index].model_copy(update={"position": position})
            return replace(self, no_connects=tuple(no_connects))
        raise ValueError(f"Cannot move {selection.kind}")

    def delete_item(self, selection: SelectionKey) -> EditorState:
        if selection.kind == "symbol":
            return replace(
                self,
                symbols=tuple(symbol for symbol in self.symbols if symbol.reference != selection.key),
            )
        if selection.kind == "wire":
            index = self._validated_index(selection, len(self.wires))
            return replace(self, wires=tuple(wire for i, wire in enumerate(self.wires) if i != index))
        if selection.kind == "label":
            index = self._validated_index(selection, len(self.labels))
            return replace(self, labels=tuple(label for i, label in enumerate(self.labels) if i != index))
        if selection.kind == "no_connect":
            index = self._validated_index(selection, len(self.no_connects))
            return replace(
                self,
                no_connects=tuple(marker for i, marker in enumerate(self.no_connects) if i != index),
            )
        raise ValueError(f"Unknown selection kind: {selection.kind}")

    def rotate_symbol(self, reference: str, delta_deg: int) -> EditorState:
        symbols = []
        found = False
        for symbol in self.symbols:
            if symbol.reference == reference:
                found = True
                symbols.append(symbol.model_copy(update={"rotation_deg": (symbol.rotation_deg + delta_deg) % 360}))
            else:
                symbols.append(symbol)
        if not found:
            raise ValueError(f"Unknown symbol reference: {reference}")
        return replace(self, symbols=tuple(symbols))

    def update_symbol(
        self,
        reference: str,
        *,
        new_reference: str | None = None,
        value: str | None = None,
        rotation_deg: int | None = None,
        footprint_id: str | None = None,
    ) -> EditorState:
        replacement_reference = new_reference or reference
        if replacement_reference != reference and any(
            symbol.reference == replacement_reference for symbol in self.symbols
        ):
            raise ValueError(f"Duplicate reference designator: {replacement_reference}")

        symbols = []
        found = False
        for symbol in self.symbols:
            if symbol.reference == reference:
                found = True
                updates: dict[str, object] = {"reference": replacement_reference}
                if value is not None:
                    updates["value"] = value
                if rotation_deg is not None:
                    updates["rotation_deg"] = rotation_deg
                if footprint_id is not None:
                    updates["footprint_id"] = footprint_id or None
                symbols.append(symbol.model_copy(update=updates))
            else:
                symbols.append(symbol)
        if not found:
            raise ValueError(f"Unknown symbol reference: {reference}")
        return replace(self, symbols=tuple(symbols))

    def add_label(self, name: str, position: Point) -> EditorState:
        if not name.strip():
            raise ValueError("Net label cannot be empty")
        return replace(self, labels=(*self.labels, NetLabel(name=name.strip(), position=position)))

    def update_label(
        self,
        index: int,
        *,
        name: str | None = None,
        position: Point | None = None,
    ) -> EditorState:
        if index < 0 or index >= len(self.labels):
            raise ValueError(f"Unknown label index: {index}")
        label = self.labels[index]
        updates: dict[str, object] = {}
        if name is not None:
            if not name.strip():
                raise ValueError("Net label cannot be empty")
            updates["name"] = name.strip()
        if position is not None:
            updates["position"] = position
        labels = list(self.labels)
        labels[index] = label.model_copy(update=updates)
        return replace(self, labels=tuple(labels))

    def add_no_connect(self, position: Point) -> EditorState:
        return replace(self, no_connects=(*self.no_connects, NoConnect(position=position)))

    def _validated_index(self, selection: SelectionKey, length: int) -> int:
        index = parse_index_key(selection)
        if index >= length:
            raise ValueError(f"Unknown {selection.kind} key: {selection.key}")
        return index
```

If mypy complains about long lines or dict object types, split lines without changing behavior.

- [ ] **Step 6: Run Task 1 tests**

Run:

```powershell
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/ui/test_editor_state.py tests/unit/ui/test_selection.py -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task1-green'
```

Expected: PASS.

- [ ] **Step 7: Run Ruff on touched files**

Run:

```powershell
& '.tmp\phase1a-venv2\Scripts\python.exe' -m ruff check src/pcbsmith/ui/editor_state.py src/pcbsmith/ui/selection.py tests/unit/ui/test_editor_state.py tests/unit/ui/test_selection.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add src/pcbsmith/ui/editor_state.py src/pcbsmith/ui/selection.py tests/unit/ui/test_editor_state.py tests/unit/ui/test_selection.py
git commit -m "feat: add schematic editor commands"
```

## Task 2: Undo And Redo History

**Files:**
- Create: `src/pcbsmith/ui/history.py`
- Test: `tests/unit/ui/test_history.py`

- [ ] **Step 1: Write failing history tests**

Create `tests/unit/ui/test_history.py`:

```python
from __future__ import annotations

import pytest

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.history import EditHistory


def test_commit_then_undo_and_redo_restores_states() -> None:
    initial = EditorState.blank("main")
    changed = initial.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    history = EditHistory(initial)

    history.commit(changed)

    assert history.current == changed
    assert history.undo() == initial
    assert history.redo() == changed


def test_new_commit_clears_redo_stack() -> None:
    initial = EditorState.blank("main")
    first = initial.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    second = initial.place_symbol("stdlib:R", "1k", Point(x=2_540_000, y=0))
    history = EditHistory(initial)
    history.commit(first)
    history.undo()

    history.commit(second)

    assert history.current == second
    assert not history.can_redo


def test_reset_clears_undo_and_redo() -> None:
    initial = EditorState.blank("main")
    changed = initial.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    replacement = EditorState.blank("replacement")
    history = EditHistory(initial)
    history.commit(changed)

    history.reset(replacement)

    assert history.current == replacement
    assert not history.can_undo
    assert not history.can_redo


def test_undo_without_history_raises() -> None:
    history = EditHistory(EditorState.blank("main"))

    with pytest.raises(IndexError, match="No undo state"):
        history.undo()
```

- [ ] **Step 2: Run history tests to verify they fail**

Run:

```powershell
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/ui/test_history.py -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task2-red'
```

Expected: FAIL because `pcbsmith.ui.history` does not exist.

- [ ] **Step 3: Implement snapshot history**

Create `src/pcbsmith/ui/history.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from pcbsmith.ui.editor_state import EditorState


@dataclass
class EditHistory:
    current: EditorState
    _undo_stack: list[EditorState] = field(default_factory=list)
    _redo_stack: list[EditorState] = field(default_factory=list)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def commit(self, state: EditorState) -> EditorState:
        if state == self.current:
            return self.current
        self._undo_stack.append(self.current)
        self.current = state
        self._redo_stack.clear()
        return self.current

    def reset(self, state: EditorState) -> None:
        self.current = state
        self._undo_stack.clear()
        self._redo_stack.clear()

    def undo(self) -> EditorState:
        if not self._undo_stack:
            raise IndexError("No undo state")
        self._redo_stack.append(self.current)
        self.current = self._undo_stack.pop()
        return self.current

    def redo(self) -> EditorState:
        if not self._redo_stack:
            raise IndexError("No redo state")
        self._undo_stack.append(self.current)
        self.current = self._redo_stack.pop()
        return self.current
```

- [ ] **Step 4: Run history tests**

Run:

```powershell
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/ui/test_history.py -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task2-green'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/history.py tests/unit/ui/test_history.py
git commit -m "feat: add schematic edit history"
```

## Task 3: Render Labels And No-Connect Markers

**Files:**
- Modify: `src/pcbsmith/ui/items.py`
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Test: `tests/integration/test_gui_phase1b.py`

- [ ] **Step 1: Add failing rendering tests**

Create `tests/integration/test_gui_phase1b.py` with:

```python
from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.schematic_scene import SchematicScene


def test_scene_renders_labels_and_no_connects() -> None:
    state = (
        EditorState.blank("main")
        .add_label("VIN", Point(x=0, y=0))
        .add_no_connect(Point(x=2_540_000, y=0))
    )
    scene = SchematicScene()

    scene.load_editor_state(state)

    assert [item.label.name for item in scene.label_items()] == ["VIN"]
    assert [item.no_connect.position for item in scene.no_connect_items()] == [
        Point(x=2_540_000, y=0)
    ]
```

- [ ] **Step 2: Run rendering test to verify it fails**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_scene_renders_labels_and_no_connects -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task3-red'
```

Expected: FAIL because `label_items()` and `no_connect_items()` do not exist.

- [ ] **Step 3: Add graphics item classes**

Modify `src/pcbsmith/ui/items.py`:

```python
from pcbsmith.core.schematic import NetLabel, NoConnect, SymbolInstance, Wire

LABEL_TEXT_SCALE = 120_000
NO_CONNECT_SIZE = 1_200_000
```

Add:

```python
class NetLabelItem(QGraphicsTextItem):
    def __init__(self, label: NetLabel, index: int, parent: QGraphicsItem | None = None) -> None:
        super().__init__(label.name, parent)
        self.label = label
        self.index = index
        self.setDefaultTextColor(QColor(181, 71, 8))
        self.setScale(LABEL_TEXT_SCALE)
        self.setPos(label.position.x, label.position.y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )


class NoConnectItem(QGraphicsItem):
    def __init__(self, no_connect: NoConnect, index: int, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.no_connect = no_connect
        self.index = index
        self.setPos(no_connect.position.x, no_connect.position.y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )

    def boundingRect(self) -> QRectF:
        half = NO_CONNECT_SIZE / 2
        return QRectF(-half, -half, NO_CONNECT_SIZE, NO_CONNECT_SIZE)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        half = int(NO_CONNECT_SIZE / 2)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(181, 71, 8), 0))
        painter.drawLine(-half, -half, half, half)
        painter.drawLine(-half, half, half, -half)
        painter.restore()
```

Update `__all__` to include `NetLabelItem`, `NoConnectItem`, `LABEL_TEXT_SCALE`, and `NO_CONNECT_SIZE`.

- [ ] **Step 4: Render new item types from the scene**

Modify `src/pcbsmith/ui/schematic_scene.py` imports:

```python
from pcbsmith.ui.items import NetLabelItem, NoConnectItem, SymbolItem, WireItem
```

Add fields in `__init__`:

```python
self._label_items: list[NetLabelItem] = []
self._no_connect_items: list[NoConnectItem] = []
```

Update `load_editor_state`:

```python
self._label_items = [
    NetLabelItem(label, index)
    for index, label in enumerate(state.labels)
]
self._no_connect_items = [
    NoConnectItem(no_connect, index)
    for index, no_connect in enumerate(state.no_connects)
]
for item in (*self._wire_items, *self._symbol_items, *self._label_items, *self._no_connect_items):
    self.addItem(item)
```

Add accessors:

```python
def label_items(self) -> tuple[NetLabelItem, ...]:
    return tuple(self._label_items)

def no_connect_items(self) -> tuple[NoConnectItem, ...]:
    return tuple(self._no_connect_items)
```

- [ ] **Step 5: Run rendering tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_scene_renders_labels_and_no_connects tests/integration/test_gui_phase1a.py::test_scene_renders_symbols_and_wires -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task3-green'
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/ui/items.py src/pcbsmith/ui/schematic_scene.py tests/integration/test_gui_phase1b.py
git commit -m "feat: render schematic annotations"
```

## Task 4: Scene Selection And Command Application

**Files:**
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Modify: `src/pcbsmith/ui/items.py`
- Test: `tests/integration/test_gui_phase1b.py`

- [ ] **Step 1: Add failing scene command tests**

Append to `tests/integration/test_gui_phase1b.py`:

```python
from pcbsmith.ui.selection import SelectionKey


def test_scene_applies_move_delete_and_rotate_commands() -> None:
    scene = SchematicScene()
    scene.place_resistor(Point(x=0, y=0))

    scene.move_selection(SelectionKey("symbol", "R1"), Point(x=2_540_000, y=0))
    scene.rotate_selection(SelectionKey("symbol", "R1"), 90)
    schematic = scene.editor_state.to_schematic()
    assert schematic.symbols[0].position == Point(x=2_540_000, y=0)
    assert schematic.symbols[0].rotation_deg == 90

    scene.delete_selection(SelectionKey("symbol", "R1"))

    assert scene.editor_state.to_schematic().symbols == ()


def test_scene_tools_place_label_and_no_connect() -> None:
    scene = SchematicScene()

    scene.set_tool("label")
    scene.handle_canvas_click(Point(x=0, y=0))
    scene.set_tool("no_connect")
    scene.handle_canvas_click(Point(x=2_540_000, y=0))

    schematic = scene.editor_state.to_schematic()
    assert [label.name for label in schematic.labels] == ["NET"]
    assert [marker.position for marker in schematic.no_connects] == [Point(x=2_540_000, y=0)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_scene_applies_move_delete_and_rotate_commands tests/integration/test_gui_phase1b.py::test_scene_tools_place_label_and_no_connect -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task4-red'
```

Expected: FAIL because scene command methods and tools do not exist.

- [ ] **Step 3: Add item selection-key helpers**

In `src/pcbsmith/ui/items.py`, import `SelectionKey` and add methods:

```python
from pcbsmith.ui.selection import SelectionKey


class SymbolItem(QGraphicsItem):
    ...
    def selection_key(self) -> SelectionKey:
        return SelectionKey("symbol", self.symbol.reference)


class WireItem(QGraphicsItem):
    def __init__(self, wire: Wire, index: int, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.wire = wire
        self.index = index
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def selection_key(self) -> SelectionKey:
        return SelectionKey("wire", str(self.index))


class NetLabelItem(QGraphicsTextItem):
    ...
    def selection_key(self) -> SelectionKey:
        return SelectionKey("label", str(self.index))


class NoConnectItem(QGraphicsItem):
    ...
    def selection_key(self) -> SelectionKey:
        return SelectionKey("no_connect", str(self.index))
```

Update `SchematicScene.load_editor_state` so wires are constructed with indexes:

```python
self._wire_items = [
    WireItem(wire, index)
    for index, wire in enumerate(state.wires)
]
```

- [ ] **Step 4: Add scene command methods and tools**

Modify `_tools` in `src/pcbsmith/ui/schematic_scene.py`:

```python
_tools = frozenset(("select", "place_resistor", "wire", "label", "no_connect"))
```

Add scene methods:

```python
def apply_editor_state(self, state: EditorState) -> None:
    self.load_editor_state(state)

def move_selection(self, selection: SelectionKey, position: Point) -> None:
    self.apply_editor_state(self._editor_state.move_item(selection, snap(position, GRID_NM)))

def delete_selection(self, selection: SelectionKey) -> None:
    self.apply_editor_state(self._editor_state.delete_item(selection))

def rotate_selection(self, selection: SelectionKey, delta_deg: int = 90) -> None:
    if selection.kind != "symbol":
        raise ValueError(f"Cannot rotate {selection.kind}")
    self.apply_editor_state(self._editor_state.rotate_symbol(selection.key, delta_deg))

def selected_key(self) -> SelectionKey | None:
    selected = self.selectedItems()
    if len(selected) != 1:
        return None
    item = selected[0]
    if hasattr(item, "selection_key"):
        return item.selection_key()
    return None
```

Update `handle_canvas_click`:

```python
if self._tool == "label":
    self.apply_editor_state(self._editor_state.add_label("NET", snap(position, GRID_NM)))
    return
if self._tool == "no_connect":
    self.apply_editor_state(self._editor_state.add_no_connect(snap(position, GRID_NM)))
    return
```

- [ ] **Step 5: Run scene command tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_scene_applies_move_delete_and_rotate_commands tests/integration/test_gui_phase1b.py::test_scene_tools_place_label_and_no_connect tests/integration/test_gui_phase1a.py::test_scene_tools_place_resistor_and_wire -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task4-green'
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/ui/items.py src/pcbsmith/ui/schematic_scene.py tests/integration/test_gui_phase1b.py
git commit -m "feat: add scene edit commands"
```

## Task 5: Scene History Integration

**Files:**
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Test: `tests/integration/test_gui_phase1b.py`

- [ ] **Step 1: Add failing undo/redo integration tests**

Append:

```python
def test_scene_undo_redo_tracks_edit_commands() -> None:
    scene = SchematicScene()
    scene.place_resistor(Point(x=0, y=0))
    scene.move_selection(SelectionKey("symbol", "R1"), Point(x=2_540_000, y=0))

    scene.undo()
    assert scene.editor_state.to_schematic().symbols[0].position == Point(x=0, y=0)

    scene.redo()
    assert scene.editor_state.to_schematic().symbols[0].position == Point(x=2_540_000, y=0)


def test_load_editor_state_resets_history() -> None:
    scene = SchematicScene()
    scene.place_resistor(Point(x=0, y=0))

    scene.load_editor_state(EditorState.blank("replacement"))

    assert not scene.can_undo
    assert not scene.can_redo
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_scene_undo_redo_tracks_edit_commands tests/integration/test_gui_phase1b.py::test_load_editor_state_resets_history -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task5-red'
```

Expected: FAIL because history is not integrated into the scene.

- [ ] **Step 3: Integrate `EditHistory` into `SchematicScene`**

Modify `src/pcbsmith/ui/schematic_scene.py`:

```python
from pcbsmith.ui.history import EditHistory
```

In `__init__`:

```python
self._history = EditHistory(self._editor_state)
```

Split current load behavior:

```python
def _render_editor_state(self, state: EditorState) -> None:
    self.clear()
    self._editor_state = state
    self._pending_wire_start = None
    ...

def load_editor_state(self, state: EditorState) -> None:
    self._history.reset(state)
    self._render_editor_state(state)

def apply_editor_state(self, state: EditorState) -> None:
    committed = self._history.commit(state)
    self._render_editor_state(committed)
```

Add properties and methods:

```python
@property
def can_undo(self) -> bool:
    return self._history.can_undo

@property
def can_redo(self) -> bool:
    return self._history.can_redo

def undo(self) -> None:
    self._render_editor_state(self._history.undo())

def redo(self) -> None:
    self._render_editor_state(self._history.redo())
```

Ensure `place_resistor`, `add_wire`, `move_selection`, `delete_selection`, `rotate_selection`, label placement, and no-connect placement call `apply_editor_state`, not `load_editor_state`.

- [ ] **Step 4: Run undo/redo scene tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_scene_undo_redo_tracks_edit_commands tests/integration/test_gui_phase1b.py::test_load_editor_state_resets_history tests/integration/test_gui_phase1a.py::test_gui_saves_and_reopens_schematic -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task5-green'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/schematic_scene.py tests/integration/test_gui_phase1b.py
git commit -m "feat: add scene undo redo"
```

## Task 6: Inspector Widget

**Files:**
- Create: `src/pcbsmith/ui/inspector.py`
- Test: `tests/unit/ui/test_inspector.py`

- [ ] **Step 1: Write failing inspector tests**

Create `tests/unit/ui/test_inspector.py`:

```python
from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.inspector import InspectorWidget
from pcbsmith.ui.selection import SelectionKey


def test_inspector_shows_symbol_fields(qtbot) -> None:  # type: ignore[no-untyped-def]
    state = EditorState.blank("main").place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    inspector = InspectorWidget()
    qtbot.addWidget(inspector)

    inspector.show_selection(state, SelectionKey("symbol", "R1"))

    assert inspector.reference_edit.text() == "R1"
    assert inspector.value_edit.text() == "10k"
    assert inspector.item_type_label.text() == "Symbol"


def test_inspector_emits_symbol_update(qtbot) -> None:  # type: ignore[no-untyped-def]
    state = EditorState.blank("main").place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    inspector = InspectorWidget()
    qtbot.addWidget(inspector)
    updates: list[tuple[SelectionKey, str, str]] = []
    inspector.symbol_field_changed.connect(updates.append)
    inspector.show_selection(state, SelectionKey("symbol", "R1"))

    inspector.value_edit.setText("4.7k")
    inspector.commit_value_edit()

    assert updates == [(SelectionKey("symbol", "R1"), "value", "4.7k")]


def test_inspector_shows_empty_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    inspector = InspectorWidget()
    qtbot.addWidget(inspector)

    inspector.show_selection(EditorState.blank("main"), None)

    assert inspector.item_type_label.text() == "No selection"
```

- [ ] **Step 2: Run inspector tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/ui/test_inspector.py -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task6-red'
```

Expected: FAIL because `pcbsmith.ui.inspector` does not exist.

- [ ] **Step 3: Implement `InspectorWidget`**

Create `src/pcbsmith/ui/inspector.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.selection import SelectionKey, parse_index_key


class InspectorWidget(QWidget):
    symbol_field_changed = Signal(tuple)
    label_text_changed = Signal(tuple)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selection: SelectionKey | None = None
        self.item_type_label = QLabel("No selection")
        self.reference_edit = QLineEdit()
        self.value_edit = QLineEdit()
        self.rotation_edit = QLineEdit()
        self.footprint_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.position_label = QLabel("")
        self.diagnostic_label = QLabel("")

        layout = QFormLayout(self)
        layout.addRow("Type", self.item_type_label)
        layout.addRow("Reference", self.reference_edit)
        layout.addRow("Value", self.value_edit)
        layout.addRow("Rotation", self.rotation_edit)
        layout.addRow("Footprint", self.footprint_edit)
        layout.addRow("Label", self.label_edit)
        layout.addRow("Position", self.position_label)
        layout.addRow("Diagnostics", self.diagnostic_label)

        self.reference_edit.editingFinished.connect(self.commit_reference_edit)
        self.value_edit.editingFinished.connect(self.commit_value_edit)
        self.rotation_edit.editingFinished.connect(self.commit_rotation_edit)
        self.footprint_edit.editingFinished.connect(self.commit_footprint_edit)
        self.label_edit.editingFinished.connect(self.commit_label_edit)

    def show_selection(self, state: EditorState, selection: SelectionKey | None) -> None:
        self._selection = selection
        self._set_all_enabled(False)
        self._clear_fields()
        if selection is None:
            self.item_type_label.setText("No selection")
            return
        if selection.kind == "symbol":
            symbol = next((item for item in state.symbols if item.reference == selection.key), None)
            if symbol is None:
                self.item_type_label.setText("No selection")
                return
            self.item_type_label.setText("Symbol")
            self.reference_edit.setText(symbol.reference)
            self.value_edit.setText(symbol.value)
            self.rotation_edit.setText(str(symbol.rotation_deg))
            self.footprint_edit.setText(symbol.footprint_id or "")
            self.position_label.setText(f"{symbol.position.x}, {symbol.position.y}")
            for widget in (self.reference_edit, self.value_edit, self.rotation_edit, self.footprint_edit):
                widget.setEnabled(True)
            return
        if selection.kind == "label":
            index = parse_index_key(selection)
            if index >= len(state.labels):
                self.item_type_label.setText("No selection")
                return
            label = state.labels[index]
            self.item_type_label.setText("Net label")
            self.label_edit.setText(label.name)
            self.position_label.setText(f"{label.position.x}, {label.position.y}")
            self.label_edit.setEnabled(True)
            return
        if selection.kind == "wire":
            self.item_type_label.setText("Wire")
            self.diagnostic_label.setText("Derived net diagnostics pending")
            return
        if selection.kind == "no_connect":
            self.item_type_label.setText("No connect")
            return

    def commit_reference_edit(self) -> None:
        self._emit_symbol_field("reference", self.reference_edit.text())

    def commit_value_edit(self) -> None:
        self._emit_symbol_field("value", self.value_edit.text())

    def commit_rotation_edit(self) -> None:
        self._emit_symbol_field("rotation", self.rotation_edit.text())

    def commit_footprint_edit(self) -> None:
        self._emit_symbol_field("footprint", self.footprint_edit.text())

    def commit_label_edit(self) -> None:
        if self._selection is not None and self._selection.kind == "label":
            self.label_text_changed.emit((self._selection, self.label_edit.text()))

    def _emit_symbol_field(self, field: str, value: str) -> None:
        if self._selection is not None and self._selection.kind == "symbol":
            self.symbol_field_changed.emit((self._selection, field, value))

    def _set_all_enabled(self, enabled: bool) -> None:
        for widget in (
            self.reference_edit,
            self.value_edit,
            self.rotation_edit,
            self.footprint_edit,
            self.label_edit,
        ):
            widget.setEnabled(enabled)

    def _clear_fields(self) -> None:
        for widget in (
            self.reference_edit,
            self.value_edit,
            self.rotation_edit,
            self.footprint_edit,
            self.label_edit,
        ):
            widget.clear()
        self.position_label.clear()
        self.diagnostic_label.clear()
```

- [ ] **Step 4: Run inspector tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/ui/test_inspector.py -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task6-green'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/ui/inspector.py tests/unit/ui/test_inspector.py
git commit -m "feat: add schematic inspector widget"
```

## Task 7: Main Window Inspector, Actions, And Shortcuts

**Files:**
- Modify: `src/pcbsmith/ui/main_window.py`
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Test: `tests/integration/test_gui_phase1b.py`

- [ ] **Step 1: Add failing main-window tests**

Append:

```python
from pcbsmith.ui.main_window import MainWindow


def test_main_window_has_inspector_and_edit_actions(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.inspector_dock.windowTitle() == "Inspector"
    action_texts = {action.text() for action in window.schematic_toolbar.actions()}
    assert {"Select", "Label", "No Connect", "Undo", "Redo", "Delete", "Rotate"}.issubset(action_texts)


def test_main_window_undo_redo_actions_update_scene(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))

    window.undo()
    assert window.scene.editor_state.to_schematic().symbols == ()

    window.redo()
    assert [symbol.reference for symbol in window.scene.editor_state.to_schematic().symbols] == ["R1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_main_window_has_inspector_and_edit_actions tests/integration/test_gui_phase1b.py::test_main_window_undo_redo_actions_update_scene -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task7-red'
```

Expected: FAIL because inspector/action methods do not exist.

- [ ] **Step 3: Add inspector dock and toolbar attributes**

Modify `src/pcbsmith/ui/main_window.py` imports:

```python
from PySide6.QtGui import QAction, QKeySequence
from pcbsmith.ui.inspector import InspectorWidget
```

In `__init__`:

```python
self.inspector = InspectorWidget()
self.inspector_dock = QDockWidget("Inspector", self)
self.schematic_toolbar = None
```

Add `_create_inspector_dock`:

```python
def _create_inspector_dock(self) -> None:
    self.inspector_dock.setWidget(self.inspector)
    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)
```

Call it after `_create_console_dock()`.

- [ ] **Step 4: Add edit actions**

In `_create_toolbar`, store toolbar:

```python
self.schematic_toolbar = self.addToolBar("Schematic")
toolbar = self.schematic_toolbar
```

Add actions:

```python
select_action = QAction("Select", self)
select_action.triggered.connect(lambda: self.scene.set_tool("select"))
toolbar.addAction(select_action)

label_action = QAction("Label", self)
label_action.triggered.connect(lambda: self.scene.set_tool("label"))
toolbar.addAction(label_action)

no_connect_action = QAction("No Connect", self)
no_connect_action.triggered.connect(lambda: self.scene.set_tool("no_connect"))
toolbar.addAction(no_connect_action)

delete_action = QAction("Delete", self)
delete_action.setShortcut(QKeySequence.StandardKey.Delete)
delete_action.triggered.connect(self.delete_selected)
toolbar.addAction(delete_action)

rotate_action = QAction("Rotate", self)
rotate_action.triggered.connect(self.rotate_selected)
toolbar.addAction(rotate_action)

undo_action = QAction("Undo", self)
undo_action.setShortcut(QKeySequence.StandardKey.Undo)
undo_action.triggered.connect(self.undo)
toolbar.addAction(undo_action)
self.undo_action = undo_action

redo_action = QAction("Redo", self)
redo_action.setShortcut(QKeySequence.StandardKey.Redo)
redo_action.triggered.connect(self.redo)
toolbar.addAction(redo_action)
self.redo_action = redo_action
```

- [ ] **Step 5: Add main-window methods**

Add:

```python
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
    self.inspector.show_selection(self.scene.editor_state, self.scene.selected_key())
```

Connect scene selection changes in `__init__` after scene creation:

```python
self.scene.selectionChanged.connect(self.refresh_inspector)
```

When opening a project, call `self.refresh_inspector()` after `load_editor_state`.

- [ ] **Step 6: Run main-window action tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_main_window_has_inspector_and_edit_actions tests/integration/test_gui_phase1b.py::test_main_window_undo_redo_actions_update_scene -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task7-green'
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/pcbsmith/ui/main_window.py src/pcbsmith/ui/schematic_scene.py tests/integration/test_gui_phase1b.py
git commit -m "feat: wire schematic edit actions"
```

## Task 8: Inspector Edits Apply To Scene

**Files:**
- Modify: `src/pcbsmith/ui/main_window.py`
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Test: `tests/integration/test_gui_phase1b.py`

- [ ] **Step 1: Add failing inspector integration tests**

Append:

```python
def test_main_window_applies_symbol_inspector_edits(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))

    window.apply_symbol_field_change((SelectionKey("symbol", "R1"), "value", "4.7k"))
    window.apply_symbol_field_change((SelectionKey("symbol", "R1"), "footprint", "R_0603"))

    symbol = window.scene.editor_state.to_schematic().symbols[0]
    assert symbol.value == "4.7k"
    assert symbol.footprint_id == "R_0603"


def test_main_window_rejects_duplicate_reference_from_inspector(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))
    window.scene.place_resistor(Point(x=2_540_000, y=0))
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]

    window.apply_symbol_field_change((SelectionKey("symbol", "R2"), "reference", "R1"))

    assert errors == ["Duplicate reference designator: R1"]
    assert [symbol.reference for symbol in window.scene.editor_state.to_schematic().symbols] == ["R1", "R2"]


def test_main_window_applies_label_text_edits(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.set_tool("label")
    window.scene.handle_canvas_click(Point(x=0, y=0))

    window.apply_label_text_change((SelectionKey("label", "0"), "VIN"))

    assert [label.name for label in window.scene.editor_state.to_schematic().labels] == ["VIN"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_main_window_applies_symbol_inspector_edits tests/integration/test_gui_phase1b.py::test_main_window_rejects_duplicate_reference_from_inspector tests/integration/test_gui_phase1b.py::test_main_window_applies_label_text_edits -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task8-red'
```

Expected: FAIL because apply methods do not exist.

- [ ] **Step 3: Add scene update methods**

In `src/pcbsmith/ui/schematic_scene.py`:

```python
def update_symbol(self, reference: str, **updates: object) -> None:
    self.apply_editor_state(self._editor_state.update_symbol(reference, **updates))

def update_label(self, index: int, *, name: str | None = None, position: Point | None = None) -> None:
    self.apply_editor_state(self._editor_state.update_label(index, name=name, position=position))
```

- [ ] **Step 4: Connect inspector signals and apply edits**

In `MainWindow.__init__` after inspector creation:

```python
self.inspector.symbol_field_changed.connect(self.apply_symbol_field_change)
self.inspector.label_text_changed.connect(self.apply_label_text_change)
```

Add:

```python
def apply_symbol_field_change(self, change: tuple[SelectionKey, str, str]) -> None:
    selection, field, value = change
    if selection.kind != "symbol":
        return
    updates: dict[str, object] = {}
    if field == "reference":
        updates["new_reference"] = value.strip()
    elif field == "value":
        updates["value"] = value.strip()
    elif field == "rotation":
        try:
            updates["rotation_deg"] = int(value)
        except ValueError:
            self.show_error(f"Invalid rotation: {value}")
            return
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
    self.refresh_inspector()

def apply_label_text_change(self, change: tuple[SelectionKey, str]) -> None:
    selection, value = change
    if selection.kind != "label":
        return
    try:
        self.scene.update_label(int(selection.key), name=value)
    except ValueError as exc:
        self.show_error(str(exc))
        return
    self.refresh_inspector()
```

- [ ] **Step 5: Run inspector integration tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_main_window_applies_symbol_inspector_edits tests/integration/test_gui_phase1b.py::test_main_window_rejects_duplicate_reference_from_inspector tests/integration/test_gui_phase1b.py::test_main_window_applies_label_text_edits -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task8-green'
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/ui/main_window.py src/pcbsmith/ui/schematic_scene.py tests/integration/test_gui_phase1b.py
git commit -m "feat: apply inspector schematic edits"
```

## Task 9: Save/Reopen Labels And No-Connect Workflow

**Files:**
- Modify: `tests/integration/test_gui_phase1b.py`
- Modify only if required by failures: `src/pcbsmith/ui/*`

- [ ] **Step 1: Add failing save/reopen workflow test**

Append:

```python
from pcbsmith.services import project_io


def test_gui_saves_and_reopens_labels_and_no_connects(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    project_dir = tmp_path / "demo"
    project_io.create_project(project_dir, "Demo")

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_dir)
    window.scene.set_tool("label")
    window.scene.handle_canvas_click(Point(x=0, y=0))
    window.apply_label_text_change((SelectionKey("label", "0"), "VIN"))
    window.scene.set_tool("no_connect")
    window.scene.handle_canvas_click(Point(x=2_540_000, y=0))
    window.save_project()

    reopened = MainWindow()
    qtbot.addWidget(reopened)
    reopened.open_project(project_dir)

    schematic = reopened.scene.editor_state.to_schematic()
    assert [(label.name, label.position) for label in schematic.labels] == [
        ("VIN", Point(x=0, y=0))
    ]
    assert [marker.position for marker in schematic.no_connects] == [
        Point(x=2_540_000, y=0)
    ]
```

- [ ] **Step 2: Run the workflow test**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1b.py::test_gui_saves_and_reopens_labels_and_no_connects -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task9'
```

Expected: PASS if previous tasks correctly connected state to project I/O. If it fails, fix only the broken save/open/render path and re-run this test.

- [ ] **Step 3: Run Phase 1A regression workflow tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase1a.py tests/integration/test_gui_phase1b.py -q -p no:cacheprovider --basetemp '.tmp\pytest-phase1b-task9-regression'
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/integration/test_gui_phase1b.py src/pcbsmith/ui
git commit -m "test: cover phase 1b persistence workflow"
```

If no source files changed, the commit still contains the new integration test.

## Task 10: README And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README Phase 1A GUI section**

Modify `README.md` so the GUI section contains this text or equivalent:

````markdown
## Phase 1A and 1B GUI

Phase 1A adds the first PySide6 schematic editor slice: launch the editor, open or
create a PCBSmith project, place resistor symbols, draw a basic wire, save/reopen
the schematic, navigate with zoom/pan/scroll, fit the view, and run ERC in the
console dock.

Phase 1B adds safer schematic editing: selecting items, moving/deleting/rotating
symbols, basic undo/redo, inspector edits for core symbol fields, and minimal net
label/no-connect marker editing.

Run the GUI after installing the project:

```powershell
pcbsmith-gui
```

The GUI reuses the Phase 0 project JSON format. Text-to-schematic, real LLM
provider hooks, component family catalogs, circuit simulation, PCB layout, and
manufacturing exports are future phases.
````

- [ ] **Step 2: Run Ruff**

Run:

```powershell
& '.tmp\phase1a-venv2\Scripts\python.exe' -m ruff check src tests
```

Expected: PASS.

- [ ] **Step 3: Run all tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:TMP='D:\AI\PCB designer\.tmp'
$env:TEMP='D:\AI\PCB designer\.tmp'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp 'D:\AI\PCB designer\.tmp\pytest-phase1b-full'
```

Expected: PASS.

- [ ] **Step 4: Smoke-test GUI startup**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -c "from PySide6.QtWidgets import QApplication; app = QApplication([]); from pcbsmith.ui.app import main; raise SystemExit(main(['pcbsmith-gui']))"
```

Expected: exit code 0.

- [ ] **Step 5: Commit README**

```powershell
git add README.md
git commit -m "docs: document phase 1b gui"
```

- [ ] **Step 6: Push branch**

```powershell
git push
```

Expected: `origin/codex/phase-1b-schematic-editing-core` is updated.

## Self-Review

- Spec coverage: The plan covers selection, move, delete, rotate, undo/redo, inspector, labels, no-connect markers, save/reopen, tests, and README. Text-to-schematic, component-family catalogs, simulation, PCB layout, and tutorials stay deferred.
- Boundaries: Durable editing behavior is planned in non-Qt `EditorState` and `EditHistory`; Qt classes route events and render state.
- Type consistency: The plan consistently uses `SelectionKey`, `EditHistory`, `InspectorWidget`, `SchematicScene.apply_editor_state`, and `SchematicScene.selected_key`.
- Risk controls: Every behavior gets focused tests before implementation; full regression and GUI smoke checks happen before final push.
