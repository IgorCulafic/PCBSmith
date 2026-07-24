# PCBSmith Board AI Commands Design

## Goal

Add the first board-level AI commands so a candidate plan can intentionally add simple copper route segments and silkscreen text through the same approval loop used for schematic edits.

## Scope

This step adds a narrow command surface:

- `route_segment` writes a board trace on `F.Cu`.
- `place_text` writes board text on `F.SilkS` or `B.SilkS`.
- Plan dry-runs summarize board commands without mutating files.
- Plan apply saves the selected schematic and the project board file.
- KiCad export renders command-authored board traces and text into the review `.kicad_pcb`.
- Planner packages advertise the new command types and include examples in the target schema.

This step does not add vias, back-copper routing, autorouting, net validation against pad connectivity, text collision checks, or final manufacturing export.

## Architecture

`schematic_commands` becomes the shared command module for both schematic and starter board commands. The existing `SchematicCommand` union expands to a broader plan command union while keeping the existing schematic command behavior unchanged.

The core board model gains a `BoardText` item. `RouteSegmentCommand` appends a `Trace`; `PlaceTextCommand` appends a `BoardText`. `kicad_plan` loads the first project board by default, applies schematic commands to the schematic and board commands to the board, then saves both files only when `--apply` is used.

`kicad_export` continues generating deterministic schematic-derived board previews, then overlays command-authored board traces and text from the project board file. Board command coordinates are board-local nanometres and are rendered inside the centered board outline using the existing board display offset.

## Command Shape

`route_segment`:

```json
{
  "type": "route_segment",
  "net_name": "LED_A",
  "layer": "F.Cu",
  "points": [{"x": 4000000, "y": 31000000}, {"x": 46000000, "y": 31000000}],
  "width": 250000
}
```

`place_text`:

```json
{
  "type": "place_text",
  "text": "AI LED Demo",
  "layer": "F.SilkS",
  "position": {"x": 25000000, "y": 31000000},
  "rotation_deg": 0,
  "size": 1500000,
  "thickness": 150000
}
```

## Testing

Tests cover:

- plan package parsing for `route_segment` and `place_text`;
- dry-run summaries without file mutation;
- apply saving traces and board text to `boards/main.brd.json`;
- planner packages advertising the new commands;
- KiCad export rendering command-authored board text and traces;
- `B.Cu` route commands rejected until the later double-sided routing phase.
