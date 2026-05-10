# PCBSmith Editor Usability And Routing Design

Date: 2026-05-10

## Goal

Make the current Phase 2 GUI feel like the beginning of a real electronics CAD tool instead of a raw test harness. The next work is split into two implementation phases:

- **Phase 3A: Editor Usability Reset** fixes readability, menus, component browsing, placement, selection, keyboard shortcuts, and basic transform controls.
- **Phase 3B: Routing Interaction Pass** improves connection-point snapping, wire/trace previews, free positioning, and 45-degree routing behavior.
- **Phase 3C: CAD Polish And Annotation** adds silkscreen text, richer style/property controls, deeper transform tools, and board-layer UI hooks after the core editor interactions are usable.

This design keeps the current PySide6 desktop app and the existing model/service/UI boundaries. It does not add LLM hooks, external library imports, simulation, PCB board layout, or first-run tutorials yet.

## Important CAD Distinction

PCBSmith should separate schematic wiring from PCB copper routing:

- **Schematic wires** describe electrical connectivity. They do not carry current physically, so 90-degree schematic lines are acceptable and often useful for readability.
- **PCB traces** are physical copper. They need stronger routing constraints, design-rule checks, and preferably 45-degree routing options for manufacturability and signal/current quality.

Phase 3B should improve the interaction model in a way that can serve both, but the first implementation remains in the schematic editor. Future board-routing work can reuse the same snap/preview/tool-mode concepts with stricter PCB rules.

## Phase 3A Scope: Editor Usability Reset

### Visual Contrast

The canvas must use a readable default theme. Components, labels, pins, wire previews, and selected items must remain visible against the canvas grid.

Default direction:

- Light canvas background with pale grid.
- Dark component strokes and readable reference/value text.
- Blue selection and connection affordances.
- Avoid black-on-black component rendering.

This is the default for now. A dark theme can come later through an Options/Preferences surface once theme choices are deliberate.

### Menu And Toolbar Shape

Replace the current row of text shortcut buttons with a draw.io-like application shell:

- Menu bar: `File`, `Edit`, `View`, `Components`, `Tools`, `Options`, `Project`, `Help`.
- Icon-oriented toolbar for tool modes and common actions.
- Text labels are acceptable where icons are unclear, but the toolbar should stop looking like a row of component buttons.

Expected menu ownership:

- `File`: new/open/save project, export placeholders.
- `Edit`: undo, redo, delete, rotate, mirror/flip.
- `View`: zoom in/out, fit, grid visibility, snap toggles.
- `Components`: focus/search component browser, basic component entries.
- `Tools`: select, pan, wire, label, no-connect, future silkscreen.
- `Options`: grid size, snap behavior, visual theme later.
- `Project`: project metadata and preferred parts later.
- `Help`: about and future tutorial/onboarding.

### Component Browser

The left component dock should feel closer to draw.io, but focused on electronics:

- Search bar stays at the top.
- Component families are collapsible sections.
- `Basic Components` is its own expanded starter family.
- Basic family shows quick tiles for resistor, capacitor, diode, LED, button, switch, power, ground, and connector/header.
- Other families can remain collapsed until the catalog grows.
- Search should still work across tags, aliases, family, package, and description.

The browser should select/arm a component for placement instead of immediately adding it to the schematic.

### Placement Model

Clicking a component should arm placement mode:

1. User chooses a component from the browser, menu, toolbar, or keyboard shortcut.
2. The canvas shows a placement preview following the cursor.
3. Click places the component at the cursor location.
4. Drag placement can determine initial orientation where practical.
5. Escape cancels placement.

This replaces the current behavior where toolbar/component actions add a part at the origin.

### Selection And Transform Controls

Clicking an existing component should select it and show transform affordances through the inspector, toolbar, context menu, and keyboard shortcuts.

Minimum Phase 3A transforms:

- Rotate clockwise.
- Mirror/flip horizontally.
- Mirror/flip vertically if the model can represent it cleanly.

This matters for polarized parts such as diodes, LEDs, electrolytic capacitors later, and connector orientation.

### Keyboard Shortcuts

Add real keyboard shortcuts for common tools and parts. Initial defaults:

- `V`: select tool.
- `W`: wire tool.
- `R`: arm resistor placement.
- `C`: arm capacitor placement.
- `D`: arm diode placement.
- `L`: arm LED placement or label only if `D` covers diode clearly. If this conflicts in practice, prefer component placement and expose labels through toolbar/menu.
- `T`: text/label tool.
- `Delete`: delete selection.
- `Ctrl+Z`: undo.
- `Ctrl+Y` and `Ctrl+Shift+Z`: redo.
- `Ctrl+R`: rotate selection.
- `H`: mirror horizontally.
- `Shift+H` or `V` alternative must not conflict with select; choose final binding during implementation tests.

Shortcuts should be discoverable through menu labels/tooltips.

## Phase 3B Scope: Routing Interaction Pass

### Connection Points

Components should expose visible connection targets when relevant:

- Pin/end indicators appear on hover, while placing wires, or when a component is selected.
- Connection targets use small circles or handles.
- Wire placement should prefer snapping to component pins and existing wire endpoints over grid snapping.
- The visual state should make it obvious when the cursor is over a valid connection.

### Snap Modes

Snapping should be configurable enough for real editing:

- Endpoint/pin snap: always available in wire mode.
- Grid snap: toggleable.
- Free placement: available for non-grid layouts and asymmetric circuits.
- Future: finer grid sizes and unit controls through Options.

Grid snap remains useful, but it should not be the only way to draw or place.

### Wire Preview And Angles

Wire drawing should preview the segment before committing it.

Initial modes:

- Free segment: direct point-to-point.
- 45-degree constrained segment: locks to horizontal, vertical, and diagonal increments.
- Orthogonal segment: useful for schematic readability.

Phase 3B should store the resulting wire points in the existing schematic model unless model changes become unavoidable. Future PCB trace routing can add board-specific trace models and design rules.

## Phase 3C Scope: CAD Polish And Annotation

Phase 3C should happen after 3A and 3B, because annotation and polish are much easier to build once placement, selection, snapping, and routing previews are reliable.

Expected Phase 3C work:

- Silkscreen text and markings with position, rotation, layer, and size controls.
- More complete mirror/flip behavior for polarized and asymmetric symbols.
- Richer inspector/style controls for references, values, text, labels, and future board annotations.
- Options and Project dialogs that expose settings without crowding the canvas.
- Toolbar polish and icon refinement once the stable tool set is known.
- Early board-layer UI hooks for future copper, silkscreen, solder mask, and mechanical layers.

Phase 3C is not required before the app can be useful for schematic editing. It is the next polish layer after the core editor and routing interactions feel solid.

## Testing Strategy

Phase 3A tests:

- Component/browser action arms placement instead of placing immediately.
- Canvas click places the armed component at the clicked location.
- Escape cancels armed placement.
- Component browser exposes collapsible family sections with Basic Components visible.
- Main window exposes the expected menus and non-component toolbar actions.
- Shortcuts trigger placement/tool actions.
- Components render with readable pens/text on the default canvas theme.
- Selection supports rotate and mirror actions.

Phase 3B tests:

- Wire tool highlights/snaps to symbol pins.
- Endpoint snap wins over grid snap when near a valid pin.
- Grid snap can be toggled off for free placement.
- Wire preview updates before commit.
- 45-degree mode constrains segment endpoints.
- Existing save/load and ERC behavior still work.

Phase 3C tests:

- Silkscreen text can be placed, selected, edited, moved, rotated, saved, and reopened.
- Inspector/style controls update the selected annotation without affecting unrelated objects.
- Mirror/flip behavior is preserved through save/load for supported symbol types.
- Options and Project dialogs open from their menus and persist only explicitly supported settings.
- Toolbar/menu actions remain discoverable through labels, shortcuts, and tooltips.

## Out Of Scope

- Full PCB board editor.
- Copper trace width/current calculations.
- Simulation.
- KiCad/LibrePCB import.
- LLM tool execution.
- First-run tutorial.
- Advanced component metadata for exact chips and manufacturer part numbers.

## Implementation Order

1. Phase 3A visual contrast and menu/toolbar shell.
2. Phase 3A collapsible component browser.
3. Phase 3A armed placement and placement preview.
4. Phase 3A selection transform controls and shortcuts.
5. Phase 3A verification, GUI launch, and commit.
6. Phase 3B endpoint/pin indicators.
7. Phase 3B snap modes and wire preview.
8. Phase 3B 45-degree/orthogonal routing modes.
9. Phase 3B verification, GUI launch, and commit.
10. Phase 3C silkscreen text and annotation model.
11. Phase 3C richer inspector/options/project surfaces.
12. Phase 3C toolbar polish, GUI launch, and commit.

Each chunk should keep the app runnable and testable before moving on.
