# PCBSmith Layer-Aware Board Groundwork Design

## Goal

Add the first explicit layer-aware board groundwork so PCBSmith can generate KiCad boards with clear copper-layer intent and simple top silkscreen text while keeping routing deliberately basic.

## Scope

This step adds foundation, not a full PCB router:

- Keep generated copper routing on `F.Cu` for now.
- Make board output explicitly aware of front copper, back copper, front silkscreen, back silkscreen, and edge cuts.
- Add a small silkscreen text primitive to the generated KiCad board.
- Include layer information in the AI-facing KiCad context so future AI plans can reason about board-side and silkscreen capabilities.
- Preserve the current centered board outline, footprints, traces, ERC/DRC checks, and SVG preview flow.

This step does not add automatic double-sided routing, vias, trace-width optimization, stackup management, impedance rules, Gerber export orchestration, or silkscreen collision checking.

## Architecture

`kicad_export` remains the owner of deterministic KiCad board generation. The board renderer will get small named constants for the layers PCBSmith currently supports and will use those constants when emitting tracks, footprints, text, and edge cuts. `kicad_project` already emits KiCad board layers; this phase keeps that as the physical layer declaration and uses `kicad_export` for generated board content.

The new silkscreen primitive is generated as native KiCad `gr_text`, not as a custom drawing format. This keeps KiCad as the renderer and validator and avoids duplicating text layout.

AI context reports board layer capabilities in plain structured data. The context is descriptive, not a permission bypass: plans still go through validation and approval before writing files.

## Behavior

The generated review board includes:

- a centered `Edge.Cuts` outline;
- existing footprints and `F.Cu` segments;
- a readable `PCBSmith Demo` text item on `F.SilkS`;
- layer metadata that identifies `F.Cu`, `B.Cu`, `F.SilkS`, `B.SilkS`, and `Edge.Cuts`;
- no generated `B.Cu` routing yet.

The generated schematic remains unchanged.

## Testing

Tests assert:

- exported board text contains `gr_text "PCBSmith Demo"` on `F.SilkS`;
- front-copper segments still use `F.Cu`;
- no back-copper segment is generated in this groundwork step;
- AI context includes the supported board layer list;
- `tools/dev_check.py` still passes with KiCad available.

## Future Work

Future phases can build on this by adding `route_segment` commands with selectable layer, `add_via`, bottom-side footprints, board-side constraints, silkscreen/logo import, and Gerber/SVG manufacturing exports.
