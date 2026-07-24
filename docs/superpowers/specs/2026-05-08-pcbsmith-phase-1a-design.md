# PCBSmith Phase 1A Design

Date: 2026-05-08
Status: Draft for user review
Source reference: `docs/reference/PCB_Application_Specification.pdf`

## Decision

Phase 1A is a small vertical slice of the PDF's Phase 1 schematic editor milestone.
The product direction is a professional schematic editor first, with data and event
boundaries that leave room for later LLM-assisted editing. Beginner tutorial flows
and richer component-family browsing are important, but they are deferred until the
basic editor surface is trustworthy.

The goal is not to complete the whole Phase 1 chapter at once. The goal is to prove
the central workflow: create or open a project, edit a schematic on a grid, save it,
reopen it, and run ERC.

## Phase 1A Scope

Phase 1A includes:

- A new PySide6 UI layer under `src/pcbsmith/ui`.
- A desktop application entry point, exposed through a console script such as
  `pcbsmith-gui`.
- A `QMainWindow` shell with a central schematic canvas, a left library palette,
  and a bottom console/ERC dock.
- A `QGraphicsView`/`QGraphicsScene` schematic canvas with a stable 100 mil grid.
- Cursor-centered zoom, workspace panning, scroll bars for large schematics, and a
  fit-to-view action.
- Resistor placement from the built-in library.
- Orthogonal wire drawing sufficient to connect two placed resistors.
- Save and open for the first schematic in a PCBSmith project using existing
  `project_io`.
- Basic ERC execution using the existing `services.erc` behavior, with issues shown
  in the console dock.
- Focused GUI tests for the acceptance workflow, plus unit tests for any non-Qt
  editor-state adapter.

Phase 1A excludes:

- LLM prompt panels, automatic schematic generation, or AI edit previews.
- First-run tutorials or onboarding screens.
- Component family/category dropdowns beyond the current small searchable palette.
- Full 25-part library expansion from the PDF.
- Labels, no-connect markers, auto-junction insertion, and manual junction editing.
- A rich inspector dock.
- Deep undo/redo behavior.
- PCB layout editing and manufacturing exports.
- Multi-sheet schematics.

## Architecture

The existing architecture remains `ui -> services -> core`.

`core/` stays pure. It must not import Qt, filesystem services, CLI code, or UI
helpers. The existing Pydantic schematic, geometry, library, and netlist models
remain the durable source of truth.

`services/` remains responsible for project I/O, built-in library access, and ERC.
Phase 1A should reuse those services instead of duplicating JSON parsing or
validation inside UI widgets.

`ui/` is the new top layer. It may import PySide6, services, and core models. UI
classes should stay thin where possible. Schematic editing behavior that can be
tested without Qt should live in a small editor-state module rather than being
buried inside mouse event handlers.

The likely package shape is:

- `src/pcbsmith/ui/app.py` for application startup.
- `src/pcbsmith/ui/main_window.py` for menus, docks, actions, and project lifecycle.
- `src/pcbsmith/ui/schematic_view.py` for zoom, pan, scroll, grid drawing, and view
  configuration.
- `src/pcbsmith/ui/schematic_scene.py` for scene-level editing state and item
  orchestration.
- `src/pcbsmith/ui/items.py` for symbol and wire graphics items.
- `src/pcbsmith/ui/editor_state.py` for conversion between user edits and
  immutable `Schematic` models.

Names can change during implementation if the codebase points to a clearer split,
but the boundaries should stay intact.

## User Workflow

The acceptance workflow is:

1. Launch the GUI from a fresh clone after installing dependencies.
2. Create a new project or open an existing PCBSmith project.
3. See a professional editor shell with a central schematic grid.
4. Use the library palette to place two resistor symbols.
5. Pan and zoom around the canvas without losing grid alignment.
6. Draw an orthogonal wire between the resistor pins.
7. Save the project.
8. Quit and relaunch the application.
9. Reopen the project and see the schematic restored.
10. Run ERC and see issues or success messages in the console dock.

## Canvas Behavior

The scene uses schematic coordinates. The view handles presentation concerns such
as zoom, panning, scroll bars, antialiasing, and fit-to-view.

Grid spacing is 100 mil, represented in integer nanometres through the existing
geometry model. Placement and wire points snap to the grid. The grid should remain
visually stable while zooming and panning.

Basic navigation is part of Phase 1A:

- Mouse wheel or trackpad scroll zooms in and out centered on the cursor when the
  user performs the platform-standard zoom gesture.
- Scroll bars and wheel scrolling allow movement across larger schematics.
- Middle-mouse drag, or an equivalent non-conflicting gesture, pans the workspace.
- A menu or toolbar action fits the current schematic contents in view.

The default interaction should not trap the user. `Esc` cancels active place or wire
tools. Selection remains simple in Phase 1A and does not need full inspector support.

## Editing Behavior

The first placement target is the built-in resistor symbol, `stdlib:R`. The palette
can show the small existing built-in library, but resistor placement is the required
acceptance behavior.

Symbol items display a compact professional schematic representation with visible
reference text. The saved model must include reference, symbol id, value, position,
rotation, and footprint id where applicable.

Wire drawing supports the narrow acceptance flow: create connected orthogonal wire
segments between resistor pins or snapped grid points. Advanced corner editing,
auto-junction insertion, labels, and bus behavior are deferred.

References should be generated predictably enough for tests, for example `R1`,
`R2`, and so on for resistor placement.

## Data Flow

Project files continue to use the Phase 0 JSON model:

1. UI opens or creates a project through `services.project_io`.
2. UI loads the first schematic model.
3. The scene renders symbols and wires from the model.
4. User edits update an editor-state representation.
5. Save converts editor state back to a `core.schematic.Schematic`.
6. `project_io.save_schematic` writes the schematic JSON.
7. ERC calls `services.erc.run_erc` with the saved or current schematic and the
   built-in symbols.

This flow is intentionally deterministic. Later LLM features should produce the
same validated schematic edits that the UI produces, not a separate side channel.

## LLM Hooks For Later

Phase 1A will not call an LLM. It should still avoid choices that make LLM editing
awkward later.

Future LLM hooks need:

- Stable object identities or predictable references for schematic items.
- Explicit editor actions such as place symbol, move symbol, add wire, delete item,
  and run ERC.
- Structured ERC results that can be shown to users and passed back into a future
  assistant loop.
- A clean conversion path from proposed structured edits into the same model updates
  used by direct UI editing.

Phase 1A only needs to preserve these boundaries. The AI panel, action preview, and
approval workflow belong to a later phase.

## Deferred UX

First-run tutorial behavior is deferred but should be planned as a future layer over
the editor, not a replacement for editor basics. A later tutorial can guide users
through placing a resistor, wiring pins, saving, and reading ERC messages.

Component family browsing is also deferred. The eventual library UX should support
component types and families, likely through category dropdowns, search, and filters.
Phase 1A can keep the palette simple while avoiding hard-coded UI assumptions that
only one flat list will ever exist.

## Error Handling

The GUI should show recoverable user-facing errors in dialogs or the console dock.
Examples include invalid project files, failed loads, failed saves, unknown symbol
ids, and ERC derivation errors.

The UI must not silently repair corrupt data or fabricate missing parts. Service
errors should stay visible and specific. The app should prefer leaving the current
in-memory schematic unchanged when an open/save operation fails.

## Testing

Tests should scale with the risk of introducing the first GUI layer.

Phase 1A testing includes:

- Existing Phase 0 tests still passing.
- Unit tests for editor-state conversion where behavior can be tested without Qt.
- GUI tests, likely with `pytest-qt`, that cover launching the main window and the
  save/reopen acceptance path.
- Tests or direct verification for zoom, pan, scroll, and fit-to-view behavior at
  the view/controller level where practical.

Manual verification remains useful because graphics interactions can be brittle in
headless environments. Manual checks should confirm that the grid renders, panning
and zooming feel usable, resistor placement is visible, wire drawing is visible,
save/reopen restores the schematic, and ERC output appears.

## Acceptance Criteria

Phase 1A is accepted when:

- A developer can install dependencies and launch the GUI.
- The main window shows a central grid canvas, a library palette, and a console/ERC
  dock.
- The user can zoom, pan, scroll, and fit the schematic view.
- The user can place two resistor symbols.
- The user can draw a wire connecting the resistors.
- Saving and reopening restores the placed resistors and wire.
- ERC can be run from the GUI and displays results.
- Existing Phase 0 CLI/core/service tests still pass.
- New GUI/editor tests cover the main acceptance path.

## Risks

The main risk is letting the GUI grow too broad before one vertical slice works.
The response is to keep Phase 1A deliberately narrow and defer tutorial, advanced
library browsing, labels, junctions, inspector, and full undo/redo.

Another risk is mixing Qt state with domain state until save/load becomes fragile.
The response is to keep the Pydantic `Schematic` model as the source of truth and
use explicit conversion between graphics items and core models.

PySide6 and pytest-qt introduce heavier dependencies than Phase 0. The response is
to keep them out of `core` and `services`, and to make GUI dependencies explicit in
project packaging.
