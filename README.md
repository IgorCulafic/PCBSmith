# PCBSmith

> **Current project state (implementation reconciled 2026-07-18):** PCBSmith has grown far beyond
> the original Phase 0 CLI below. Nine topology authorities regenerate
> through the live golden suite; the tenth thermometer challenge failed
> at board routing and now drives the active authority application. Generic
> R2-R6 negotiated-routing, corridor, ordered-bus, placement, live reduced-stem,
> and semantic/process machinery is accepted within documented bounds. There is
> still no persisted exact-accepted thermometer board, production/default caller
> migration, complete thermometer declaration set, or routed full-board golden.
> One isolated production-derived R17/D17 `/PWLED` crop now completes an offline
> placement-and-routing micro-pilot, including an authorized ordinary-R2 fallback,
> exact budget-cliff tests, and a separate opt-in live KiCad 10 save/read-back/
> clean-DRC gate. The offline wrapper deliberately retains `kicad_live_checked=False`;
> neither result is full-board routing, production persistence, or R7 completion. Start
> with [`CLAUDE.md`](CLAUDE.md),
> [`docs/project-catchup-2026-07-12.md`](docs/project-catchup-2026-07-12.md),
> [`docs/reference/current-materials-knowledge-base-2026-07-14.md`](docs/reference/current-materials-knowledge-base-2026-07-14.md),
> [`docs/reference/standards-table-reverification-2026-07-14.md`](docs/reference/standards-table-reverification-2026-07-14.md),
> [`docs/routing-placement-plan.md`](docs/routing-placement-plan.md), and
> [`docs/circuit-intelligence-review-supplement-5-2026-07-17.md`](docs/circuit-intelligence-review-supplement-5-2026-07-17.md).
> The July 14 reference synthesis is the current 31-source knowledge entry
> point; `docs/reference/books/CONSOLIDATED.md` is historical first-wave
> candidate data, not direct authorization to encode a threshold.
> The remainder of this README documents the still-supported original
> headless foundation.

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

## Verification

Run the deterministic offline gates from PowerShell:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict --python-version 3.12 src/pcbsmith
```

The independent live KiCad/ngspice gate commands and their environment-variable
cleanup are recorded in [`docs/handoff-prompt.md`](docs/handoff-prompt.md).

## Hard Rules

- Schematic and PCB are separate domains linked by a netlist.
- The data model is structured JSON/Pydantic. SVG, Gerber, PDF, and manufacturing files are export-only.
- Future LLM features must emit validated intermediate representation before project state changes.
- Core code has no UI or service imports.
- Coordinates are stored as signed integer nanometres.
- Unknown parts, pins, and values are surfaced as errors instead of fabricated.

## License

PCBSmith is licensed under AGPL-3.0-or-later.
