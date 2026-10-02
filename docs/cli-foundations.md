# Project history and foundations

PCBSmith began with a deliberately headless Phase 0: structured project data,
project I/O, netlist derivation, basic electrical-rule checks and a CLI. That is
historical context, not the current feature ceiling. The project now includes
a schematic editor prototype and native KiCad preparation, routing, review and
delivery workflows. See the [README](../README.md) and [current scope](current-state.md).

## Original project CLI

These commands remain useful for creating and inspecting a headless PCBSmith
project. They do not by themselves run the complete native board workflow.

```powershell
uv run --frozen --all-extras pcbsmith new ./demo --name "Demo Board"
uv run --frozen --all-extras pcbsmith info ./demo
uv run --frozen --all-extras pcbsmith validate ./demo
uv run --frozen --all-extras pcbsmith netlist ./demo
uv run --frozen --all-extras pcbsmith erc ./demo
```

## Architectural foundations

- Schematics and boards are separate domains linked by a netlist.
- Project data uses structured JSON/Pydantic models.
- Proposed AI changes must pass structured validation before application.
- Core code has no UI or service imports.
- Coordinates are stored as signed integer nanometres.
- Unknown parts, pins and values must be resolved explicitly.

Historical design notes remain in [the design archive](superpowers). Use
[production usage](production-usage.md) for current supported entry points and
[development](development.md) for current verification commands.
