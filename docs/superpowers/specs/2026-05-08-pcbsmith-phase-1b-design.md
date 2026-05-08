# PCBSmith Phase 1B Design

Date: 2026-05-08
Status: Draft for user review
Previous milestone: `docs/superpowers/specs/2026-05-08-pcbsmith-phase-1a-design.md`

## Decision

Phase 1B extends the Phase 1A GUI into a safer schematic editing core. The app
should remain a human-usable schematic editor first, with editing commands shaped
so future LLM-assisted actions can reuse the same pathways.

Text-to-schematic and real LLM provider hooks are intentionally deferred. They are
important to the product direction, but they should sit on top of reliable editing
commands, undo/redo, selection, inspection, and data-preserving schematic state.

The next milestone is therefore:

- Select, move, delete, and rotate schematic items.
- Add basic undo/redo for editing actions.
- Add an inspector panel for selected items.
- Add minimal editable net labels and no-connect markers.
- Preserve the existing architecture boundary: `ui -> services -> core`.

## Phase 1B Scope

Phase 1B includes:

- Selection behavior for symbols, wires, net labels, and no-connect markers.
- Move behavior for selected items, snapped to the schematic grid.
- Delete behavior for selected items.
- Rotate behavior for selected symbols.
- Basic undo and redo for place, move, delete, rotate, wire, label, and no-connect
  edits.
- A right-side inspector dock for the current selection.
- Inspector editing for selected symbol reference, value, rotation, and footprint
  id.
- Inspector diagnostics for selected item type, position, and connected net when
  that can be derived from the current schematic.
- Minimal net-label placement, selection, movement, deletion, and text editing.
- Minimal no-connect marker placement, selection, movement, and deletion.
- Existing labels, no-connect markers, and junctions remain preserved on save even
  when not all of them have rich editing behavior.
- Focused tests for editor-state mutations, undo/redo behavior, selection-driven
  inspector updates, save/reopen preservation, and GUI tool wiring.

Phase 1B excludes:

- Text-to-schematic, prompt panels, LLM provider calls, or LLM edit previews.
- Full component-family library expansion.
- Detailed component subtype catalogs for resistor, capacitor, diode, IC, connector,
  package, SMD, through-hole, value, tolerance, voltage, and power metadata.
- Circuit simulation, SPICE export, DC operating point checks, transient analysis,
  or "will this LED turn on" style electrical behavior prediction.
- Auto-junction insertion or advanced junction editing.
- Rich wire rerouting, drag handles, bend editing, or bus behavior.
- Full ERC workflow improvements beyond showing diagnostics where useful.
- PCB layout editing, footprint placement, routing, and manufacturing exports.
- First-run tutorial polish.

## Future Component Library Direction

The component library should eventually become a structured catalog rather than a
flat symbol list. Later phases should support component families and subtypes such
as resistors, capacitors, diodes, LEDs, ICs, connectors, power symbols, and modules.

Parts should also carry metadata users and LLMs can trust, including package type,
SMD versus through-hole, footprint options, electrical values, tolerance, voltage
rating, current rating, power rating, and any part-family-specific fields. That work
is deferred because Phase 1B is about making placed schematic items editable and
safe first. The Phase 1B inspector and edit-command design should avoid assumptions
that would block richer component metadata later.

## Future Simulation Direction

PCBSmith should eventually support circuit simulation or simulation-assisted checks.
That includes practical beginner-facing questions such as whether an LED is likely
to turn on, whether a divider produces the expected voltage, or whether a component
is operating outside a rough rating.

Simulation is deferred until the schematic editor and component library carry enough
electrical meaning. A useful simulation phase will likely need:

- Component values, tolerances, and ratings.
- Diode and LED forward-voltage/current assumptions or models.
- Power source models.
- Simulation-ready netlist export, likely SPICE-compatible.
- A backend such as ngspice or a compatible local simulation engine.
- A user-facing result layer that explains DC operating point findings in plain
  language without pretending rough models are exact.

Phase 1B should not implement simulation, but its edit-command and data-preservation
work should keep this later path open.

## Architecture

The architecture remains `ui -> services -> core`.

`core/` remains pure and UI-free. Any durable schematic behavior belongs in core
models or non-Qt helpers only when it is independent of desktop presentation.

`services/` remains responsible for project I/O, built-in library access, netlist
derivation, and ERC. Phase 1B should reuse these services instead of parsing JSON
or deriving nets inside widgets.

`ui/` owns PySide6 widgets, graphics items, docks, and user interaction. Direct
editing behavior should be expressed through clear editor-state commands so that
buttons, mouse events, tests, and later structured LLM edits can call the same
small operations.

Likely module responsibilities:

- `ui/editor_state.py`: immutable schematic edit state and non-Qt command helpers.
- `ui/schematic_scene.py`: tool modes, selection orchestration, mouse/key routing,
  and rendering from editor state.
- `ui/items.py`: graphics items for symbols, wires, net labels, and no-connect
  markers.
- `ui/main_window.py`: actions, docks, project lifecycle, inspector wiring, and
  undo/redo action state.
- New focused UI helper modules may be added if `main_window.py` or
  `schematic_scene.py` grows too broad. Good candidates are an inspector widget
  module and an undo history module.

## Editing Commands

Phase 1B should introduce explicit editing operations instead of burying all
behavior inside Qt event handlers. Commands should be small, deterministic, and
testable without launching a full window where practical.

Required command behavior:

- Place symbol.
- Move selected symbol, label, or no-connect marker.
- Delete selected symbols, wires, labels, and no-connect markers.
- Rotate selected symbol in 90-degree increments.
- Add wire between snapped points.
- Add or update net label text and position.
- Add no-connect marker at a snapped position.
- Edit selected symbol metadata: reference, value, rotation, and footprint id.

Reference edits must keep schematic references unique. If a user tries to change
`R1` to an existing reference, the UI should reject the change with a visible error
and leave the previous schematic unchanged.

Unknown symbol ids, invalid rotations, duplicate references, invalid wire geometry,
or model validation failures must stay visible. The GUI should not silently repair
or fabricate data.

## Undo And Redo

Undo/redo is part of Phase 1B because move and delete make accidental edits easy.
The first implementation can be simple and reliable rather than sophisticated.

The recommended model is state snapshots:

- Each committed editing command pushes the previous `EditorState` onto an undo
  stack.
- Undo restores the most recent previous state and pushes the current state onto a
  redo stack.
- Redo restores the most recent redo state and pushes the current state onto the
  undo stack.
- New edits clear the redo stack.
- Opening or creating a project resets both stacks.
- Failed edits must not modify either stack.

The history can be capped later if memory becomes a concern. Phase 1B can keep the
implementation straightforward and testable.

## Inspector

The inspector is a right-side dock that reflects the current selection.

For selected symbols, the inspector should show editable fields:

- Reference.
- Value.
- Rotation.
- Footprint id.

It should also show read-only diagnostics:

- Item type.
- Position.
- Symbol id.
- Connected net when the existing netlist derivation can determine it.
- Relevant ERC hints when available without creating a broad ERC workflow.

For net labels, the inspector should allow editing the label text and show position.
For no-connect markers, it should show item type and position. For wires, it should
show item type, point count, and any derived net name if available.

If there is no selection or there are multiple selected items, the inspector should
show a simple neutral state rather than exposing misleading fields. Multi-selection
bulk editing is deferred.

## Labels And No-Connect Markers

Phase 1B adds minimal editable support for net labels and no-connect markers because
they are basic schematic safety tools and make ERC results more meaningful.

Net labels:

- Can be placed on the grid.
- Render as text near the chosen point.
- Can be selected, moved, deleted, and renamed.
- Save and reopen through the existing `Schematic.labels` field.

No-connect markers:

- Can be placed on the grid.
- Render as a compact visible marker.
- Can be selected, moved, and deleted.
- Save and reopen through the existing `Schematic.no_connects` field.

Junctions remain preserved on save but auto-junction insertion and manual junction
editing are deferred.

## Selection And Interaction

The default tool should be select. Users should be able to click an item to select
it and press `Esc` to cancel active tools or clear the current interaction.

Expected interactions:

- Select tool chooses existing items.
- Place tools create a new item on a snapped grid point.
- Move can be implemented either by direct dragging or by command-level movement
  through a tested helper; if direct dragging is implemented, persisted state must
  update after the drag completes.
- Delete removes selected items.
- Rotate changes selected symbol rotation in 90-degree increments.
- Undo and redo are available from toolbar/menu actions and common shortcuts where
  practical.

Phase 1B does not need advanced selection rectangles, grouping, bulk edits, or item
alignment tools.

## Data Flow

Project files continue to use the Phase 0 JSON model.

1. UI opens or creates a project through `services.project_io`.
2. UI loads the first schematic into `EditorState`.
3. The scene renders all Phase 1B-supported items from `EditorState`.
4. User commands create new `EditorState` instances.
5. The scene re-renders from the new state.
6. Undo/redo restores previous `EditorState` snapshots.
7. Save converts the current `EditorState` back to `core.schematic.Schematic`.
8. `project_io.save_schematic` writes the schematic JSON.
9. ERC and inspector diagnostics use existing service behavior where possible.

This is intentionally close to the future LLM flow: a later assistant should emit
validated edit commands that go through the same state transition and undo/redo
machinery.

## Error Handling

Recoverable user-facing errors should appear in the console dock or a dialog and
should leave the current schematic unchanged.

Examples:

- Duplicate reference edits.
- Invalid rotation values.
- Empty net-label text.
- Invalid project load/save errors.
- ERC or netlist derivation failures.

The GUI must not silently drop schematic fields that it does not yet render richly.
The Phase 1A preservation fix for labels, junctions, and no-connects remains a hard
constraint.

## Testing

Phase 1B testing should be heavier than Phase 1A because editing state is now richer.

Required automated coverage:

- Editor-state tests for every command: move, delete, rotate, metadata edit, add
  label, rename label, add no-connect, delete item, and validation failures.
- Undo/redo unit tests for stack behavior, redo clearing, open/reset behavior, and
  failed edits not entering history.
- GUI integration tests for selection, inspector field updates, toolbar/menu
  actions, and save/reopen with labels and no-connect markers.
- Regression tests that existing Phase 0 and Phase 1A behavior still passes.
- Import boundary checks remain valid: core/services/cli do not import Qt or UI.

Manual verification should confirm that users can select items, move them, edit
symbol fields, place labels and no-connects, undo/redo changes, save, reopen, and
see the same schematic state restored.

## Acceptance Criteria

Phase 1B is accepted when:

- The GUI still launches and the Phase 1A workflow still works.
- The user can select schematic items.
- The user can move, delete, and rotate symbols.
- The user can edit selected symbol reference, value, rotation, and footprint id
  through the inspector.
- Duplicate reference edits are rejected without changing schematic state.
- The user can place, select, move, delete, and rename net labels.
- The user can place, select, move, and delete no-connect markers.
- Undo and redo work for Phase 1B editing commands.
- Opening or creating a project resets undo/redo history.
- Saving and reopening restores symbols, wires, labels, and no-connect markers.
- Existing unrendered schematic fields are preserved unless explicitly edited.
- Existing tests plus new Phase 1B tests pass.

## Risks

The main risk is letting the editor become a pile of widget-specific side effects.
The response is to push durable behavior into non-Qt editor-state commands and keep
Qt classes responsible for presentation and event routing.

Another risk is overbuilding the component library before editing is trustworthy.
The response is to document the future catalog direction while keeping Phase 1B
focused on editing placed schematic objects.

Undo/redo can become complicated if implemented as many bespoke inverse commands.
The response for Phase 1B is to use simple state snapshots first and only optimize
later when needed.

Net labels and no-connect markers introduce new schematic concepts. The response is
to support minimal visible editing while deferring auto-junctions and richer ERC
workflows.
