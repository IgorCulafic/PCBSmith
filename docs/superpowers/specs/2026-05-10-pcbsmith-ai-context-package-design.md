# PCBSmith AI Context Package Design

## Purpose

Phase K4 adds a read-only context package for future AI review. The package gives an LLM or local model structured project facts instead of relying on chat memory or screenshots alone.

The first context package includes:

- project name, version, schematic paths, and board paths
- schematic summaries with symbol, wire, label, and no-connect counts
- component summaries with reference, symbol ID, value, footprint, rotation, and millimetre position
- optional KiCad ERC/DRC report summaries from `.pcbsmith/kicad-reports`
- optional rendered preview paths from `.pcbsmith/visual`

## CLI

```powershell
python -m pcbsmith.cli kicad-context .\demo .\ai-context.json
python -m pcbsmith.cli kicad-context .\demo .\ai-context.json --kicad-project .\kicad-demo
```

The command writes deterministic JSON and does not mutate the source project.

## Scope

This phase does not call an AI provider, compare images, or apply changes. It only builds the context object that later planner/reviewer flows will consume.
