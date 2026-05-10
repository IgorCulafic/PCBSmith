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
python -m pcbsmith.cli kicad-preview .\kicad-demo
python -m pcbsmith.cli kicad-library-index .\kicad-library-index.json
python -m pcbsmith.cli kicad-review-bundle .\demo .\review-bundle
python -m pcbsmith.cli ai-brief .\demo .\request.txt .\brief.json --kicad-project .\review-bundle
python -m pcbsmith.cli ai-planner-package .\brief.json .\planner-package.json
python -m pcbsmith.cli ai-demo-plan .\planner-package.json .\candidate-plan.json
python -m pcbsmith.cli ai-plan-check .\planner-package.json .\candidate-plan.json
python -m pcbsmith.cli ai-plan-review .\demo .\planner-package.json .\candidate-plan.json
python -m pcbsmith.cli kicad-plan .\demo .\plan.json
python -m pcbsmith.cli kicad-context .\demo .\ai-context.json
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

This creates the KiCad skeleton plus `pcbsmith_handoff.json`, a structured manifest of the source schematic symbols, wires, labels, and no-connect markers. For supported built-in symbols, the export also writes a project-local `PCBSmith.kicad_sym` library, a `sym-lib-table`, and KiCad-native schematic symbols, connected wires, labels, and no-connect markers. The first native symbol set includes resistor, capacitor, diode, LED, VCC, and GND. Unsupported symbols remain in the handoff manifest until their KiCad mapping exists.

The fixture `tests/fixtures/led_series_circuit` is a small visual smoke test for this path: VCC, a current-limiting resistor, an LED, and GND exported as a KiCad schematic that passes KiCad ERC/DRC.

To run KiCad's own checks on a KiCad project folder:

```powershell
python -m pcbsmith.cli kicad-validate .\kicad-demo
```

This discovers one `.kicad_sch` and one `.kicad_pcb` file, runs `kicad-cli sch erc` and `kicad-cli pcb drc`, writes JSON reports under `.pcbsmith/kicad-reports`, and summarizes pass/fail status. Use `--skip-execution` to verify project discovery and KiCad configuration without launching KiCad.

To export schematic and board SVG previews for user or AI review:

```powershell
python -m pcbsmith.cli kicad-preview .\kicad-demo
```

This discovers one `.kicad_sch` and one `.kicad_pcb` file and writes stable preview paths under `.pcbsmith/visual`, such as `Demo-schematic.svg` and `Demo-board.svg`. The schematic preview is normalized from KiCad's generated SVG output; the board preview uses KiCad's single-file SVG export for front copper, front silkscreen, and edge cuts. Use `--skip-execution` to verify project discovery and KiCad configuration without launching KiCad.

To inspect KiCad's installed symbol and footprint libraries for AI context:

```powershell
python -m pcbsmith.cli kicad-library-index .\kicad-library-index.json
```

By default this reads a small starter subset from the KiCad install discovered through `kicad-cli`: `Device`, `power`, `Resistor_SMD`, `Capacitor_SMD`, and `LED_SMD`. You can pass repeatable `--symbol-library` and `--footprint-library` options to choose other KiCad libraries. This command is read-only; it exposes real KiCad IDs for planning/context and does not make those IDs automatically applyable until the command layer supports writing them safely.

To create a complete review bundle for user or AI inspection:

```powershell
python -m pcbsmith.cli kicad-review-bundle .\demo .\review-bundle
```

This exports the PCBSmith project into a KiCad handoff folder, runs KiCad validation, exports SVG previews, and writes `ai-context.json` in the same output folder. Use `--skip-execution` to create the KiCad files and context package without launching KiCad checks or preview exports.

To turn a user request into a structured engineering brief for future AI planning:

```powershell
python -m pcbsmith.cli ai-brief .\demo .\request.txt .\brief.json --kicad-project .\review-bundle
```

The brief is provider-neutral JSON. It records the user goal, classified intent, explicit assumptions, missing questions, safety checks, required capabilities, and the current project context. It does not call an LLM or mutate design files; it prepares the next AI/planner step.

To wrap that brief with the allowed planner output contract:

```powershell
python -m pcbsmith.cli ai-planner-package .\brief.json .\planner-package.json
```

The planner package tells a future LLM or local model whether it should produce a review response or a structured command proposal. For editable briefs, the current allowed command contract is the same approval-loop package consumed by `kicad-plan`: `place_symbol`, `add_wire`, and `add_label` commands targeting a project schematic.

To generate a deterministic demo candidate plan without calling a model:

```powershell
python -m pcbsmith.cli ai-demo-plan .\planner-package.json .\candidate-plan.json
```

This is a local smoke-test planner. It only supports tiny known examples, but it exercises the same candidate-plan file that future OpenAI, Ollama, LM Studio, or other local model providers should produce.

The current demo examples include single resistor/capacitor placement and a complete current-limited LED series circuit with VCC, resistor, LED, GND, wires, and net labels. The LED example can be applied through `ai-plan-review --apply`, then exported with `kicad-review-bundle` to produce a KiCad-rendered SVG preview.

To validate a future model's candidate command plan before it reaches the approval loop:

```powershell
python -m pcbsmith.cli ai-plan-check .\planner-package.json .\candidate-plan.json
```

This checks that the candidate plan is valid JSON for the current approval-loop schema, targets the expected schematic, and only uses command types allowed by the planner package. It does not apply changes.

To validate that same candidate and pass it through the project approval preview:

```powershell
python -m pcbsmith.cli ai-plan-review .\demo .\planner-package.json .\candidate-plan.json
```

The review command runs `ai-plan-check` first, then runs the normal `kicad-plan` dry-run preview only if the AI plan is valid. Add `--apply` to save the validated commands through the same approval loop and action log used by `kicad-plan`.

To review a structured command package before changing a PCBSmith project:

```powershell
python -m pcbsmith.cli kicad-plan .\demo .\plan.json
```

Apply only after review:

```powershell
python -m pcbsmith.cli kicad-plan .\demo .\plan.json --apply
```

The first approval-loop package format targets a project schematic and reuses PCBSmith's structured schematic command models:

```json
{
  "version": 1,
  "description": "Add one resistor",
  "schematic": "schematics/main.sch.json",
  "commands": [
    {
      "type": "place_symbol",
      "symbol_id": "stdlib:R",
      "value": "330",
      "position": {"x": 15240000, "y": 0},
      "footprint_id": "stdlib:R_0603"
    }
  ]
}
```

Dry-run is the default and prints the proposed operations without writing files. `--apply` saves the schematic and appends an audit entry to `.pcbsmith/action-log.jsonl`. This is the first command-approval path that future AI planners will use before real KiCad edits.

To generate a structured package for future AI review:

```powershell
python -m pcbsmith.cli kicad-context .\demo .\ai-context.json
```

If you also have a KiCad handoff project with `.pcbsmith/kicad-reports` or `.pcbsmith/visual` outputs, include those references:

```powershell
python -m pcbsmith.cli kicad-context .\demo .\ai-context.json --kicad-project .\kicad-demo
```

The context package includes project metadata, schematic symbol/wire/label counts, component summaries with millimetre positions, optional KiCad ERC/DRC report summaries, and optional rendered preview paths. This is the first read-only context path for future LLM and vision-model review.

## Developer Maintenance

Run the standard local check before committing:

```powershell
python tools/dev_check.py
```

The dev check runs linting, the test suite with a repository-local pytest temp directory, fixture validation, KiCad library indexing, KiCad preview/review-bundle discovery, AI context, AI brief, planner package, demo plan, AI plan-check, and AI plan-review smoke tests.

Generated cache folders and old one-off pytest workspaces can be reviewed with:

```powershell
python tools/clean_workspace.py
```

The cleanup tool is dry-run by default. Delete generated targets with `--apply`, or move them aside first:

```powershell
python tools/clean_workspace.py --archive .cleanup-archive
```

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
