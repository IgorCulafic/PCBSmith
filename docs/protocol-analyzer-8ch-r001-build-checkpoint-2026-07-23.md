# Reduced 8-channel protocol analyzer R001 build checkpoint

Date: 2026-07-23

## Outcome

This attempt produced a complete KiCad schematic and a two-layer placement
candidate. The schematic passes KiCad ERC with zero errors and zero warnings.
The routed candidate does **not** pass KiCad DRC and was transactionally
rejected rather than promoted as the current PCB.

On 2026-07-24, user inspection also rejected the placement candidate. R001 is
therefore a failed build checkpoint, not a reviewable board awaiting only
cosmetic cleanup.

The current authority is therefore:

- accepted for continued engineering: circuit architecture, part identities,
  and pin-population accounting;
- conditionally retained: schematic connectivity, pending a new uncrowded
  functional-section layout;
- rejected: board dimensions, connector/button placement, component placement,
  copper routing, manufacturing output, performance claims, and release
  qualification.

## Architecture exercised

- RP2040 with 2 MiB external QSPI flash;
- USB-C USB 2.0 device connection with CC pull-downs, flow-through USB ESD,
  and 27 ohm series resistors;
- eight input-only channels through two four-channel ESD arrays, 33 ohm
  series resistors, and a 5.5 V-tolerant SN74LVC244A buffer;
- separate protected Schmitt-trigger input;
- protected VTARGET monitor, not a target-power output;
- 2x10 target header with each capture channel adjacent to a ground pin;
- SWD, BOOTSEL, RESET, power indication, and capture status;
- 88 mm x 50 mm, two copper layers, four M2.5 mounting holes.

The required acquisition target is triggered SRAM capture at 10 MS/s followed
by USB upload. Twenty MS/s is retained only as a stretch target pending
firmware and measurement. Continuous streaming is not claimed.

## Evidence and checks

Automatic source retrieval obtained and pinned the official RP2040 hardware
design material and the relevant TI buffer, ESD, and trigger-buffer data
sheets. The source manifests and cache are under
`outputs/protocol-analyzer-8ch-r001/intake/`.

The following evidence was produced:

- KiCad ERC: 0 errors, 0 warnings;
- deterministic component, schematic-instance, and placement identities;
- explicit connected-or-no-connect accounting for every schematic pin;
- a geometric placement gate was run, but subsequent user inspection proved its
  no-overlap verdict was a false pass;
- standard front/back, copper, assembly, fabrication, detail, holes/vias, and
  populated/bare 3D review images.

The standard review workflow correctly remains nonconformant at this stage:
the placement-only board has no final routed fast-bus, matched-pair, or
power/ground electrical views to inspect.

## Visual findings

Manual inspection of the generated front overview and populated 3D views found
that the broad zoning is plausible: USB and power enter from the left, the MCU
and memory occupy the center, protected inputs flow from the right-side
header, and mounting holes remain clear.

The initial internal inspection identified only two presentation defects:

1. reference designators and functional labels are crowded or overlap in
   several areas;
2. the populated top-camera render is framed too tightly and clips the board
   vertically.

That inspection was incomplete. User inspection on 2026-07-24 found the
following additional, decisive failures:

1. the USB connector is on the wrong edge for the intended product;
2. schematic components overlap or are too crowded for reliable review;
3. physical PCB component/courtyard overlaps remain;
4. the 88 mm x 50 mm board wastes substantial area and is not compact;
5. the user-accessible buttons do not project through an edge access region and
   are difficult to actuate.

The first finding exposes a requirements-governance failure. The written prompt
and both concept images explicitly locked USB-C to the left edge, so the CAD
followed the recorded constraint. The concept gate nevertheless failed to
confirm that this recorded anchor still matched the user's actual intent. The
replacement edge must be explicitly selected before R002 placement.

The remaining findings expose inadequate review gates. Ratnest readability,
successful rendering, and the previous virtual placement result were incorrectly
treated as sufficient evidence of collision-free and usable placement.

## Rejected routing candidate

The routing experiment produced 216 track segments and 36 vias. KiCad DRC
reported 297 violations and 96 unconnected pads. The main reported categories
were:

| Category | Count |
| --- | ---: |
| unconnected items | 96 |
| shorting items | 71 |
| hole clearance | 55 |
| solder-mask bridge | 50 |
| clearance | 37 |
| tracks crossing | 31 |
| copper-to-edge clearance | 18 |
| silkscreen overlap | 17 |
| silkscreen over copper | 7 |
| text height | 6 |
| hole-to-hole | 3 |
| copper sliver | 2 |

The counts overlap because a single geometric defect can trigger more than one
DRC category.

Root cause: manually seeded/frozen fanout copper was accepted by the general
router without first passing the same exact aggregate clearance checks applied
to generated routes. The A* stage then treated invalid seed geometry as
authority. Final KiCad DRC correctly exposed crossings, pad shorts, via/hole
clearance failures, and unfinished connectivity.

The failed board is retained only as negative evidence in
`outputs/protocol-analyzer-8ch-r001/rejected-routing/`.

## Required next slice

1. Confirm the intended USB edge and update the structured brief, vector
   anchors, and acceptance record before regenerating CAD.
2. Reflow the schematic into separated USB/power, MCU/clock/flash/debug, input
   front-end, and target-connector sections with explicit symbol/body and label
   spacing checks.
3. Compute a compact board envelope from actual courtyard, mating, mounting,
   routing-corridor, and edge-control access geometry instead of inheriting the
   preferred 88 mm x 50 mm concept canvas.
4. Place BOOT and RESET as edge-accessible controls. Verify their actuator
   envelopes, finger/tool approach, enclosure implications, and intentional
   board-edge projection.
5. Run exact footprint, courtyard, hole, mating-envelope, and actuator-envelope
   collision checks on the saved/read-back placement. Any overlap is a hard
   rejection.
6. Clean and re-place silkscreen/reference text, then regenerate correctly
   framed review cameras.
7. Replace the present seed fanout with deterministic USB, QFN, header-bus,
   and local-power escape primitives.
8. Exact-check every seed segment and via before it can become frozen routing
   authority.
9. Route transactionally from the clean placement board; reject any candidate
   with unresolved connectivity or DRC violations.
10. Generate the final semantic electrical views and inspect the complete
   standard review package.
11. Promote a routed PCB only after KiCad reports zero DRC violations and zero
   unconnected items.

## Paper linkage

The associated image-generation study is recorded separately in
`docs/paper1-vector-conditioned-image-study-2026-07-23.md`. It defines the
four-condition comparison requested for the paper:

1. no image;
2. pure generated image;
3. pure vector image;
4. combined vector and generated image.

The examples from this project are useful formative cases. They are not yet a
controlled experiment; publication-grade comparison requires identical
prompts, fresh contexts, fixed budgets, retained provenance, and blinded
scoring.
