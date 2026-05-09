# PCBSmith

PCBSmith is an open-source PCB design application foundation. The long-term goal is to let users describe circuits in natural language or code-like text, validate that intent as structured intermediate data, and turn it into schematic and PCB project data.

Phase 0 is deliberately headless. It builds the data model, project I/O, netlist derivation, minimal ERC, and CLI before any GUI or LLM workflow.

## Phase 0 CLI

The Phase 0 CLI is available through the installed `pcbsmith` script or as a Python module:

```powershell
python -m pcbsmith.cli new .\demo --name "Demo Board"
python -m pcbsmith.cli info .\demo
python -m pcbsmith.cli validate .\demo
python -m pcbsmith.cli netlist .\demo
python -m pcbsmith.cli erc .\demo
```

The CLI can create and inspect headless PCBSmith projects, load all referenced schematic and board files, derive the first schematic netlist from built-in symbols, and run the minimal Phase 0 ERC.

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
provider hooks, component family catalogs, circuit simulation, PCB layout, SVG,
laser-ready PCB outputs, and manufacturing exports are future phases.

## Hard Rules

- Schematic and PCB are separate domains linked by a netlist.
- The data model is structured JSON/Pydantic. SVG, Gerber, PDF, and manufacturing files are export-only.
- Future LLM features must emit validated intermediate representation before project state changes.
- Core code has no UI or service imports.
- Coordinates are stored as signed integer nanometres.
- Unknown parts, pins, and values are surfaced as errors instead of fabricated.

## License

PCBSmith is licensed under AGPL-3.0-or-later.
