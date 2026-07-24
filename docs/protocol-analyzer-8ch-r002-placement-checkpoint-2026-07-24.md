# Protocol Analyzer R002 Placement Checkpoint — 2026-07-24

## Outcome — Rejected

User review rejected R002 on 2026-07-24. It must not be used as routing or
release authority.

The rejection reasons are:

1. The USB-C receptacle was positioned on the requested edge but not rotated
   into the correct outward-facing mating orientation.
2. The 70 mm width still retained unnecessary open area.
3. The work stopped at an unrouted placement even though the user had
   confirmed proceeding with the PCB build.
4. The visual review therefore showed ratsnest connectivity only, not real
   copper routing.

The original checkpoint text below is retained as failure evidence.

## Superseded checkpoint outcome

R002 replaces the rejected 88 mm × 50 mm R001 placement with a compact
70 mm × 42 mm placement. The board area is 2,940 mm², a 33.2% reduction from
R001's 4,400 mm².

The corrected physical anchors are:

- USB-C centered on the top edge;
- 2×10 target header on the left edge;
- BOOT and RESET side-actuated controls on the right edge;
- four M2.5 NPTH mounting holes at 4 mm edge offsets.

This is a placement checkpoint, not a routed-board release. Routing remains
blocked until the R002 visual placement is accepted.

## Corrections from R001

1. Removed the stale “USB on left edge” instruction and made the approved
   top-edge USB position authoritative.
2. Reflowed the schematic into separated USB/power, MCU/debug, target-input,
   and trigger/monitor sections.
3. Added connectivity-preserving, on-grid label extensions for dense symbols.
   A broad label-spreading experiment was rejected because ERC detected a net
   merge; only selected collinear extensions remain.
4. Replaced the large inherited concept canvas with an envelope derived from
   actual footprint courtyards, mounting holes, connector access, and control
   access.
5. Moved BOOT and RESET to right-edge horizontal switch footprints.
6. Added a project-local, dimensioned 3D switch proxy so actuator projection
   is visible during review. It is not supplier CAD and is not authoritative
   for enclosure sign-off.
7. Declared the project-local footprint library in `fp-lib-table`, avoiding
   hidden dependence on a global KiCad installation.

## Verification

- Unit tests: 6 passed.
- Import architecture: 2 contracts kept, 0 broken.
- KiCad ERC: 0 errors, 0 warnings.
- KiCad placement DRC: 0 geometric violations.
- Unconnected pads: 137, expected because the checkpoint is intentionally
  unrouted.
- Exact courtyard analysis: no component-to-component overlaps.
- Visual inspection: USB is on the approved top edge, the target header is on
  the left edge, and both right-edge switch actuators project beyond the board
  edge.

## Review evidence

The output directory contains:

- the KiCad project, schematic, and placement PCB;
- ERC, placement-DRC, and 3D-model preflight evidence;
- 1080p quick top, perspective, and right-side renders;
- a high-resolution standardized visual-review package with front/back,
  copper, mask, silkscreen, drill, 3D, and four zoomed detail regions;
- the schematic PDF and raster review image.

## Remaining gate

The visual placement must be accepted before deterministic escape generation
or routing begins. A routed candidate is not promotable unless KiCad later
reports both zero DRC violations and zero unconnected items.
