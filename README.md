# PCBSmith

> **Current project state (reconciled 2026-07-20):** PCBSmith has grown far
> beyond the original Phase 0 CLI below. The tenth thermometer project is
> complete as the accepted routed R005 proof-of-concept; R006 is a separate 3D
> proxy visualization pilot. Its slow legacy-path success does not establish
> generic negotiated-router scale or production/default adoption, but the board
> will not be rerun merely to prove newer machinery. Generic R2-R6 routing,
> corridor, bus, placement, and semantic authorities remain bounded tools to be
> exercised on the next genuinely unseen project. Start with
> [`docs/handoff-prompt.md`](docs/handoff-prompt.md),
> [`docs/current-state.md`](docs/current-state.md), [`CLAUDE.md`](CLAUDE.md),
> [`docs/reference/current-materials-knowledge-base-2026-07-14.md`](docs/reference/current-materials-knowledge-base-2026-07-14.md),
> [`docs/reference/standards-table-reverification-2026-07-14.md`](docs/reference/standards-table-reverification-2026-07-14.md),
> and [`docs/routing-placement-plan.md`](docs/routing-placement-plan.md).
> The July 14 synthesis covers 31 reconciled sources; the local extraction
> manifest now registers 41 documents. Registration is not the same as
> distillation or production use. Historical and archived documents never
> override the current-state record or active roadmap.
> Phase 11/12 now have a callable generic foundation for approved-source
> intake, private/redistributable KiCad assets, PNG outline and silkscreen
> tracing, model preflight, standardized 2D/3D review packages, and observable
> repository verification profiles. These are not yet automatically invoked by
> every board generator. See
> [`docs/evidence-assets-review-execution-guide.md`](docs/evidence-assets-review-execution-guide.md).
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

The maintained development and verification environment is Python 3.12. The
package metadata and Ruff syntax floor retain Python 3.11 compatibility, which
is checked separately; Python 3.14 is currently outside the supported range.

Run the deterministic offline gates from PowerShell:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict --python-version 3.12 src/pcbsmith
pcbsmith verify .pcbsmith/verification/quick --profile quick
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
