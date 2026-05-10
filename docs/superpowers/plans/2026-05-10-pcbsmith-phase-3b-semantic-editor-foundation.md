# PCBSmith Phase 3B Semantic Editor Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move PCBSmith toward a command-driven editor where the GUI and future AI tools edit the same validated schematic/board model through explicit operations.

**Architecture:** Keep the current PySide6 GUI, but stop making the canvas the source of truth. Add UI-independent command services under `pcbsmith.services`, have `EditorState` delegate basic edits through those services, then build selection, snapping, pins, and wire editing on top of semantic commands.

**Tech Stack:** Python 3.12, PySide6, Pydantic models, pytest, pytest-qt, ruff.

---

## File Structure

- `src/pcbsmith/services/schematic_commands.py`: UI-independent command models and command application for schematic edits.
- `tests/unit/services/test_schematic_commands.py`: command behavior tests.
- `src/pcbsmith/ui/editor_state.py`: temporary bridge from GUI editor state to service commands.
- Future: `src/pcbsmith/services/schematic_anchors.py` for pin/endpoint anchor resolution.
- Future: `src/pcbsmith/ui/selection_tools.py` for rubber-band and handle rendering.
- Future: `src/pcbsmith/ui/wire_tools.py` for preview, vertex handles, and snap-driven wire editing.

## Task 1: Add Command Service Spine

**Files:**
- Create: `src/pcbsmith/services/schematic_commands.py`
- Create: `tests/unit/services/test_schematic_commands.py`
- Modify: `src/pcbsmith/ui/editor_state.py`

- [x] **Step 1: Write failing command tests**

Cover `PlaceSymbolCommand` reference generation, existing-reference continuation, and `AddWireCommand` append behavior.

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_schematic_commands.py -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3b-commands-red"
```

Expected: FAIL because `pcbsmith.services.schematic_commands` does not exist.

- [x] **Step 3: Implement command models and application**

Add immutable Pydantic command models:

- `PlaceSymbolCommand`
- `AddWireCommand`
- `SchematicCommandResult`
- `apply_schematic_command`

- [x] **Step 4: Route existing editor state through commands**

Update `EditorState.place_symbol()` and `EditorState.add_wire()` to call `apply_schematic_command()` and rebuild editor state from the returned schematic.

- [x] **Step 5: Verify focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_schematic_commands.py tests/unit/ui/test_editor_state.py -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3b-commands-focused"
```

Expected: PASS.

## Task 2: Real Pin And Endpoint Anchors

**Files:**
- Create: `src/pcbsmith/services/schematic_anchors.py`
- Create: `tests/unit/services/test_schematic_anchors.py`
- Modify: `src/pcbsmith/ui/items.py`
- Modify: `src/pcbsmith/ui/schematic_scene.py`

- [ ] **Step 1: Write anchor tests**

Test that symbol library pins become absolute schematic anchor positions and that nearest-anchor lookup prefers pins/endpoints over grid points within a configured tolerance.

- [ ] **Step 2: Implement anchor extraction**

Create service functions that accept `Schematic` plus library symbols and return semantic anchors with IDs like `R1.1`, `R1.2`, and `wire:0:end`.

- [ ] **Step 3: Render anchors through UI items**

Keep pin dots as visual handles, but drive them from the same anchor positions used by snapping.

## Task 3: Drag Select And Selection Handles

**Files:**
- Create: `src/pcbsmith/ui/selection_tools.py`
- Create: `tests/unit/ui/test_selection_tools.py`
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Modify: `tests/integration/test_gui_phase3a.py`

- [ ] **Step 1: Write drag-select tests**

Test that a scene rectangle selects symbols and wires whose item bounds intersect it.

- [ ] **Step 2: Add rubber-band selection state**

Use Qt scene events for press/move/release in select mode and select intersecting items on release.

- [ ] **Step 3: Add visible hover and selected affordances**

Show selection outlines, wire hover color, and endpoint/vertex handles without changing the schematic model.

## Task 4: Wire Editing And Snap Resolver

**Files:**
- Create: `src/pcbsmith/services/snap_resolver.py`
- Create: `tests/unit/services/test_snap_resolver.py`
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Modify: `src/pcbsmith/ui/items.py`

- [ ] **Step 1: Write snap priority tests**

Verify priority order: pin anchor, wire endpoint, wire segment, then grid.

- [ ] **Step 2: Implement snap resolver**

Return both the snapped point and the snap reason so the UI can highlight valid connection targets.

- [ ] **Step 3: Use snap resolver in wire placement**

Wire clicks should commit to real anchor points, not arbitrary component body points.

## Task 5: AI Tool Readiness

**Files:**
- Modify: `src/pcbsmith/services/schematic_commands.py`
- Create: `tests/unit/services/test_schematic_command_serialization.py`

- [ ] **Step 1: Add command serialization tests**

Ensure commands validate from JSON-like dictionaries and reject extra fields.

- [ ] **Step 2: Add dry-run command result metadata**

Return messages and warnings without applying when future callers request dry-run behavior.

- [ ] **Step 3: Document AI command contract**

Add a short command contract section to the project docs before exposing any LLM hooks.

## Verification

Every task should finish with:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=".tmp/pytest-phase3b-full"
```

## Self-Review

- Spec coverage: the plan covers command-driven editing, anchors, drag selection, selection affordances, snap priority, wire correctness, and AI-readiness.
- Placeholder scan: no `TBD` or open-ended implementation placeholders remain.
- Type consistency: command model names match the implemented first slice.
