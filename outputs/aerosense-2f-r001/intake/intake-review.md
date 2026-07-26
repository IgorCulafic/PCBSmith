# AeroSense-2F R001 concept approval gate

This package stops before schematic and PCB generation, as required by the
reviewed prompt. Approval authorizes the proposed physical architecture;
it does not approve electrical correctness, routing or manufacturing release.

## Automated result

- Prompt examination: ready for concept.
- Exact-part selection: frozen for concept.
- Component/courtyard overlap check: clean.
- Pre-route feasibility: ready.
- Estimated two-side envelope utilization: 53.0%.
- Routing-corridor capacity: all declared demands assigned; no failing nets.

## Proposed architecture

- 70 × 50 mm rectangular two-layer board with four 3.2 mm NPTH holes.
- Front: OLED upper centre; USB-C at the left edge; two fan headers at
  upper-right; microSD at the bottom edge; three buttons lower-right;
  SHT45 isolated at the lower-left ambient corner.
- Back: TC2030 no-legs SWD probe interface only.
- USB-C shell intentionally overhangs the left edge by 0.575 mm, while its pads remain 1.125 mm inside.
- OLED edge clearance: 0.500 mm.
- microSD courtyard edge clearance: 0.520 mm.
- The 5 mm SHT45 isolation region is free of unrelated component envelopes.

## Approval decision

Approve or revise these five points before schematic generation:

1. 70 × 50 mm outline and four-hole pattern.
2. OLED-dominant front layout and lower-right button row.
3. Left-edge USB-C overhang and bottom-edge microSD access.
4. Lower-left SHT45 ambient isolation zone.
5. Bottom-side SWD probe location.

The selected exact parts and unresolved evidence actions are recorded in
`exact-part-selection.md`; the authoritative geometry is in `concept/`.
