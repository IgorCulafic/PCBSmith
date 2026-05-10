# PCBSmith

PCBSmith is an open-source AI companion for PCB design. The long-term goal is to let users describe circuits in natural language or code-like text, validate that intent as structured commands, and apply those commands through mature open-source EDA tooling.

PCBSmith is pivoting toward KiCad as the first real CAD backend/editor. The in-repo PySide6 schematic editor remains a prototype and command test harness, but the primary product direction is AI-assisted KiCad workflows rather than recreating a full PCB editor from scratch.

## Phase 0 CLI

The Phase 0 CLI is available through the installed `pcbsmith` script or as a Python module:

```powershell
python -m pcbsmith.cli new .\demo --name "Demo Board"
python -m pcbsmith.cli info .\demo
python -m pcbsmith.cli validate .\demo
python -m pcbsmith.cli netlist .\demo
python -m pcbsmith.cli erc .\demo
python -m pcbsmith.cli kicad-status
python -m pcbsmith.cli kicad-doctor
python -m pcbsmith.cli kicad-new .\kicad-demo --name "LED Blinker"
python -m pcbsmith.cli kicad-export .\demo .\kicad-demo --name "Demo Board"
python -m pcbsmith.cli kicad-validate .\kicad-demo
```

The CLI can create and inspect headless PCBSmith projects, load all referenced schematic and board files, derive the first schematic netlist from built-in symbols, and run the minimal Phase 0 ERC.

## KiCad Backend Direction

KiCad is the first target backend for serious CAD editing, routing, checking, and manufacturing export. PCBSmith should focus on AI planning, structured command generation, validation, user approval, and automation around KiCad rather than rebuilding KiCad's editor.

To check whether PCBSmith can find KiCad:

```powershell
python -m pcbsmith.cli kicad-status
```

PCBSmith looks for `kicad-cli` in this order:

1. `PCBSMITH_KICAD_CLI`
2. `PATH`
3. common Windows KiCad install paths

If KiCad is installed somewhere unusual, set:

```powershell
$env:PCBSMITH_KICAD_CLI = "C:\Path\To\KiCad\bin\kicad-cli.exe"
```

For a stronger readiness check that actually runs `kicad-cli version`:

```powershell
python -m pcbsmith.cli kicad-doctor
```

Use `--skip-version-check` only when you want to verify discovery/configuration without executing KiCad.

Future KiCad integration should prefer KiCad project files, `kicad-cli`, the KiCad IPC API, and official `kicad-python` bindings. PCBSmith should avoid modifying KiCad source unless the companion/plugin approach proves insufficient.

To create a first KiCad handoff skeleton:

```powershell
python -m pcbsmith.cli kicad-new .\kicad-demo --name "LED Blinker"
```

This writes the core KiCad project filenames: `.kicad_pro`, `.kicad_sch`, and `.kicad_pcb`. The generated board includes a starter 100 mm by 80 mm `Edge.Cuts` outline so KiCad DRC can validate the skeleton cleanly. The generated files are intentionally minimal and marked as PCBSmith-generated; once KiCad is installed, open/save or CLI validation can canonicalize them before deeper automation is built on top.

To export an existing PCBSmith project into a KiCad handoff folder:

```powershell
python -m pcbsmith.cli kicad-export .\demo .\kicad-demo --name "Demo Board"
```

This creates the KiCad skeleton plus `pcbsmith_handoff.json`, a structured manifest of the source schematic symbols, wires, labels, and no-connect markers. The export also writes safe KiCad-native schematic primitives for net labels and no-connect markers. Symbols and wires remain in the manifest until the KiCad library/component mapping is mature enough to generate them directly.

To run KiCad's own checks on a KiCad project folder:

```powershell
python -m pcbsmith.cli kicad-validate .\kicad-demo
```

This discovers one `.kicad_sch` and one `.kicad_pcb` file, runs `kicad-cli sch erc` and `kicad-cli pcb drc`, writes JSON reports under `.pcbsmith/kicad-reports`, and summarizes pass/fail status. Use `--skip-execution` to verify project discovery and KiCad configuration without launching KiCad.

## Phase 1A and 1B GUI

Phase 1A adds the first PySide6 schematic editor slice: launch the editor, open or
create a PCBSmith project, place resistor symbols, draw a basic wire, save/reopen
the schematic, navigate with zoom/pan/scroll, fit the view, and run ERC in the
console dock.

Phase 1B adds safer schematic editing: selecting items, moving/deleting/rotating
symbols, basic undo/redo, inspector edits for core symbol fields, and minimal net
label/no-connect marker editing.

Phase 3A began the editor usability pass: the GUI now uses a readable light
schematic canvas, CAD-style menus, a tool-oriented toolbar, keyboard shortcuts,
collapsible component families, and click-to-place component placement.
Component browser and menu actions arm placement; click the canvas to place the
previewed part. This GUI is now treated as a prototype, not the main CAD product.

## Component Catalog

PCBSmith includes a native component catalog for real CAD components. The first
catalog group, Basic Components, provides generic real variants such as 0603
resistors, 0603 capacitors, 0603 LEDs, diodes, switches, push buttons, headers,
and power symbols.

Catalog entries carry tags and aliases so users and future AI tools can search
by names, families, packages, and common terms. Simple starter parts use generic
real variants; chips and specialized components will use exact designations when
they are added.

External libraries such as LibrePCB and KiCad are future import sources. PCBSmith
keeps its own internal catalog schema so those sources can be adapted without
changing project files or the UI contract.

Run the GUI after installing the project:

```powershell
pcbsmith-gui
```

The GUI reuses the Phase 0 project JSON format. Text-to-schematic, real LLM
provider hooks, component family catalogs, circuit simulation, PCB layout, SVG,
laser-ready PCB outputs, and manufacturing exports should be pursued through
the KiCad-backed direction unless there is a strong reason to keep them native.

## Hard Rules

- Schematic and PCB are separate domains linked by a netlist.
- The data model is structured JSON/Pydantic. SVG, Gerber, PDF, and manufacturing files are export-only.
- Future LLM features must emit validated intermediate representation before project state changes.
- Core code has no UI or service imports.
- Coordinates are stored as signed integer nanometres.
- Unknown parts, pins, and values are surfaced as errors instead of fabricated.

## License

PCBSmith is licensed under AGPL-3.0-or-later.
