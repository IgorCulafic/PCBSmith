# AeroSense-2F R001 routing progress — 2026-07-26

## Status

The refined 70 mm × 50 mm, two-layer prompt remains feasible. Routing is not
complete and no fabrication-readiness claim is authorized.

The latest deterministic run passes:

- retained VBUS and 3V3 distribution;
- RP2040 local power, QSPI and 12 MHz oscillator stages;
- Type-C current-state outputs;
- OLED reset and the branched OLED/SHT45 I2C bus;
- reversible USB-C D+/D- pad merging;
- connector → ESD → 27 ohm resistor → RP2040 USB topology;
- CC1/CC2 through local ESD into the Type-C controller; and
- the full microSD SPI/card-detect routing stage.

The current terminal failure is the first fan-stage net, `/FAN1_EN`. Fan,
button/LED/debug, remainder routing, exact DRC cleanup, visual review and
production outputs remain open.

## Root causes found

1. The board prompt is dense but is not the primary failure.
2. The router is sequential single-net A*. It does not yet implement general
   negotiated congestion, coupled-bus routing or automatic rip-up across a
   group. The first member of a dense pair can consume the only useful
   corridor for the second.
3. A retained fanout was previously treated as non-blocking own copper, but
   not as an existing routing tree. A legal QFN escape therefore did not
   guide the subsequent search.
4. Failed runs previously discarded the useful intermediate board, forcing
   expensive replay and encouraging retry loops.
5. Connector/module courtyards and dense reversible/multi-endpoint nets need
   explicit topology: USB-C duplicate pads, OLED header entry, shared I2C,
   and protected microSD buses are not ordinary point-to-point nets.
6. Several initial placements increased routing difficulty. The USB-C
   receptacle orientation was corrected so electrical pads remain on
   supported PCB material, the OLED reset escape was opened, and the SD
   series resistors were moved under the socket nearer the MCU/card boundary.

## System changes retained

- Functional route stages now isolate core, Type-C, oscillator, display,
  USB, storage, fan and UI failures.
- Every successful or failed stage writes a persistent KiCad PCB checkpoint
  under `.pcbsmith/routing-checkpoints`.
- `GridRouter` can now continue from the connected component of retained
  same-net copper that touches a physical pad. Disconnected same-net islands
  are not treated as joined.
- A unit regression proves that a retained fanout becomes the A* seed and is
  not redundantly rerouted.
- Exact local bundle topology is retained for the constrained USB-C, I2C and
  microSD interfaces. These are candidate-specific topology decisions, not
  evidence that general negotiated routing is complete.

## Prompt and intake issues kept explicit

- Passive UFP `Rd` wording and the added TUSB320 current-advertisement
  detector must remain reconciled against the exact reference circuit.
- The selected 0.10 A fans satisfy the present selected-part evidence but do
  not prove the prompt's generic 0.50 A connector/interface envelope.
- KiCad/ERC/DRC and manufacturing gates must not be interpreted as thermal,
  USB compliance, firmware, fan-startup or source-current proof.

## Next work

1. Complete the paired fan-control/power groups from the latest checkpoint.
2. Complete UI/debug and remainder routing.
3. Run virtual DRC and KiCad DRC; repair any collisions introduced by
   retained topology.
4. Inspect front/back copper and standardized 2D/3D review images.
5. Generate the Phase 18 neutral manufacturing package while keeping
   `package_generated`, `fabrication_ready` and `assembly_ready` separate.
6. Generalize the successful local bundle patterns into negotiated
   congestion and coupled-bus candidate search rather than accumulating
   board-specific manual routes.
