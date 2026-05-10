# PCBSmith KiCad Approval Loop Design

## Purpose

Phase K3 adds the first safe approval loop for future AI-generated edits. The AI is not wired in yet. Instead, PCBSmith accepts a structured command package that a human, script, or later LLM planner can produce.

The loop must make every proposed change reviewable before mutation:

1. Load a PCBSmith project and command package.
2. Validate and summarize the proposed schematic commands.
3. Dry-run by default without changing project files.
4. Apply only when `--apply` is passed.
5. Save an action log when commands are applied.
6. Export the result to KiCad and run KiCad validation when requested by the CLI flow.

## Command Package

The first package format is intentionally small and compatible with the existing `schematic_commands` service:

```json
{
  "version": 1,
  "description": "Add a current-limited LED branch",
  "schematic": "schematics/main.sch.json",
  "commands": [
    {
      "type": "place_symbol",
      "symbol_id": "stdlib:R",
      "value": "330",
      "position": {"x": 15240000, "y": 0},
      "rotation_deg": 0,
      "footprint_id": "stdlib:R_0603"
    },
    {
      "type": "add_wire",
      "points": [
        {"x": 0, "y": 0},
        {"x": 10160000, "y": 0}
      ]
    }
  ]
}
```

Later command types can add labels, no-connects, board placement, footprints, routing, or KiCad IPC edits. This phase only needs the existing schematic placement and wire commands.

## CLI

Add:

```powershell
python -m pcbsmith.cli kicad-plan <project> <command-package.json>
python -m pcbsmith.cli kicad-plan <project> <command-package.json> --apply
```

Dry-run output lists the package description, target schematic, each command summary, and states that no files were changed.

Apply output lists the same command summaries, saves the modified schematic, and writes an action log at:

```text
<project>/.pcbsmith/action-log.jsonl
```

Each action log line is JSON containing timestamp, package path, description, target schematic, command count, and command summaries. JSONL keeps the log append-only and simple for future AI audit/replay tooling.

## Validation

The K3 service validates:

- command package version is `1`
- target schematic exists in the project
- command types are supported
- command models parse through Pydantic with `extra="forbid"`
- dry-run does not write project files
- apply writes only the target schematic and action log

KiCad export/validation remains a separate CLI step for now. We already have `kicad-export` and `kicad-validate`, so this phase should not merge too many responsibilities into one command.

## Testing

Tests should cover:

- parsing a command package
- formatting command summaries
- dry-run leaves the schematic unchanged
- apply mutates the target schematic and writes action log JSONL
- CLI dry-run and apply behavior
- invalid target schematic returns a CLI error

## Non-Goals

- Calling an LLM.
- Multi-agent orchestration.
- Live KiCad IPC editing.
- Board routing commands.
- A custom GUI approval panel.
