# Fabrication Workflow

PCBSmith treats KiCad as the authoritative CAD and fabrication backend. The
AI path should create or edit KiCad-readable project data, then let KiCad
validate and export the board.

Current flow:

1. Generate or stage a PCBSmith project change.
2. Export a KiCad project with native schematic, footprints, nets, board outline,
   silkscreen, and front-copper tracks.
3. Run KiCad ERC and DRC.
4. Export review SVGs, laser-ready front copper SVG, Gerbers, and drill files.

Routing status:

- Simple generated boards now use bent KiCad track segments instead of direct
  ratsnest-style pad-to-pad lines.
- The generated tracks are real KiCad `segment` copper objects and are included
  in DRC, Gerber, drill, and SVG export.
- This is still a small deterministic router for simple demos. It is not a
  general autorouter with obstacle avoidance, differential pairs, vias, or
  multi-layer optimization.

Near-term routing direction:

- Keep KiCad as the source of truth for fabrication files.
- Use KiCad DRC as the approval gate before treating a board as manufacturable.
- Add a real autorouter integration point, likely through a DSN/SES-capable
  router such as Freerouting, once the project can reliably export/import that
  handoff.
- Keep laser outputs derived from KiCad copper layers, not schematic wires.

Manufacturing outputs:

- `.pcbsmith/visual/*-schematic.svg`
- `.pcbsmith/visual/*-board.svg`
- `.pcbsmith/fabrication/*-fcu-laser.svg`
- `.pcbsmith/fabrication/gerbers/`
- `.pcbsmith/fabrication/drill/`
