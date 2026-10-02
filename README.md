# PCBSmith

> **Current scope, 2026-10-02:** See [current state](docs/current-state.md),
> [production usage](docs/production-usage.md) and
> [development and verification](docs/development.md).
> PCBSmith includes a schematic-editor prototype and native KiCad workflows with
> source-bound readiness, automatic Freerouting, visual review and handover checks.
> Single- and two-sided laser isolation artwork, interactive BOMs, editable vector
> plans and qualified same-footprint SMD substitution are supported within their
> documented limits. Physical process qualification remains separate.
> This public software snapshot excludes unpublished manuscripts, private experiment
> history, machine configuration, model weights and local board delivery archives.

PCBSmith is an open-source PCB design application foundation. The long-term goal is to let users describe circuits in natural language or code-like text, validate that intent as structured intermediate data, and turn it into schematic and PCB project data.

Phase 0 is deliberately headless. It builds the data model, project I/O, netlist derivation, minimal ERC, and CLI before any GUI or LLM workflow.

## Phase 0 CLI

The Phase 0 CLI is available through the installed `pcbsmith` script or as a Python module:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli new .\demo --name "Demo Board"
.\.venv\Scripts\python.exe -m pcbsmith.cli info .\demo
.\.venv\Scripts\python.exe -m pcbsmith.cli validate .\demo
.\.venv\Scripts\python.exe -m pcbsmith.cli netlist .\demo
.\.venv\Scripts\python.exe -m pcbsmith.cli erc .\demo
```

The CLI can create and inspect headless PCBSmith projects, load all referenced schematic and board files, derive the first schematic netlist from built-in symbols, and run the minimal Phase 0 ERC.

## Prototype GUI and component catalog

The consolidated repository retains the earlier PySide6 schematic-editor,
component-catalog, structured AI-command, and KiCad handoff prototypes. They are
useful test harnesses and research material, but they do not override the
current independent-generator architecture or its fail-closed production
workflow.

After installing project dependencies, launch the prototype with:

```powershell
pcbsmith-gui
```

The historical design and implementation records are retained under
[`docs/superpowers`](docs/superpowers). Current engineering status and execution
order remain authoritative in [`docs/current-state.md`](docs/current-state.md)
and [`docs/routing-placement-plan.md`](docs/routing-placement-plan.md).

## Setup and verification

Use Python **3.12.12** and uv **0.11.23**, the maintained verification versions.
The declared runtime range is 3.11–3.13; that range is not a claim that every
platform/version combination has passed the full suite. Install KiCad 10 with
its footprint and symbol libraries for native board workflows. Live golden
checks also require ngspice. See [development.md](docs/development.md) for
native paths, fonts, isolated environments and the separate CI lanes.

From the repository root in PowerShell:

```powershell
uv sync --frozen --all-extras --python 3.12.12
uv run --frozen --all-extras python -B tools/verify.py --output .pcbsmith/verification/first-run
uv run --frozen --all-extras pcbsmith-gui
```

Choose a new output directory for every verification run. The shared gate
checks the lockfile, Ruff, strict mypy, architecture imports and the full
ordinary pytest suite. It records logs, exit status, versions and heartbeats.
Qt runs offscreen with an explicitly registered font and explicit pytest-qt/Hypothesis plugins.
The `quick` profile is a subset; `deep` also enables live KiCad/ngspice golden
checks. A missing native tool fails the deep lane explicitly.

```powershell
uv run --frozen --all-extras python -B tools/verify.py --profile quick --output .pcbsmith/verification/quick-001
uv run --frozen --all-extras python -B tools/verify.py --profile deep --output .pcbsmith/verification/native-001
```

Existing `pcbsmith verify OUTPUT --profile PROFILE` uses the same gate factory
and execution orchestrator. Verification is developer functionality requiring
a source checkout. It is not a fabrication-release approval.

## Hard Rules

- Schematic and PCB are separate domains linked by a netlist.
- The data model is structured JSON/Pydantic. SVG, Gerber, PDF, and manufacturing files are export-only.
- Future LLM features must emit validated intermediate representation before project state changes.
- Core code has no UI or service imports.
- Coordinates are stored as signed integer nanometres.
- Unknown parts, pins, and values are surfaced as errors instead of fabricated.

## License

PCBSmith is licensed under AGPL-3.0-or-later.
