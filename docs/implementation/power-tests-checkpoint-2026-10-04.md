# PowerTrace and PowerSwitch 12V: retained build checkpoint

The user requested two 70 × 100 mm, two-face power test boards with unknown copper thickness, a 3–5 A test target, and 12 V power / 5 V control for the switched-load example. Public names are **PowerTrace** and **PowerSwitch 12V**. Do not use “coupon” in their new delivery names. PowerTrace's existing internal job directory is retained to preserve its ledger; it is not a public delivery name.

Neither board has an accepted fabrication handover. No new laser/drill package has been published. The earlier accepted two-sided LED/timer delivery is unchanged.

## PowerTrace

Stable root: `outputs/power-laser-tests-2026-10-04/01-current-coupon`.

The native schematic and 26-reference placement are prepared. The dimensioned vector and both planning overlays were inspected before placement. Current source/engineering and 37 placement artifacts were reviewed; eleven SVGs independently replayed pixel-identical to their inspected PNGs, and five diagnostic copies matched their source images. Three resistor detail crops were inspected. Nine reference-field overlaps were corrected through the supported local-edit owner, with unchanged pads and component poses. Native placement ERC/DRC/parity passed; placement opens were expected.

The routing entry gate initially found a review classification mismatch. General signal-return review remains applicable, while controlled return-path adjacency is outside the DC / ≤1 kHz, ≥10 µs-edge test scope. An immutable metadata successor corrected this distinction; the routing entry gate then passed. Both correction cycles are recorded, not reset.

The first pinned Freerouting run completed in 6.391 seconds. It routed the power and signal paths but retained one open: J23 registration GND to the lower ground row. KiCad reported zero geometric violations and one unconnected item. The result was rejected and was not published as a routed board. Current candidate/source identity is retained in `routing/result.json` and `acceptance/route-diagnostic.json`.

Bounded recommendation: move J23 from (35,97) to (35,93) mm, inspect the revised vector, perform a source-preserving native move, then make the one meaningful-change automatic retry. Edge-constrained access is a hypothesis, not a proven cause. No manual copper edit or increased search budget is authorized by this recommendation. The shared recovery owner must accommodate the existing annotation edit and metadata history; do not bypass it, reset the root or silently regenerate.

At the stopped checkpoint: 56m28.393s wall, 46m50.397s evaluation, 9m37.995s supervised execution. The stop was the correction/diagnostic boundary, not timer expiry.

## PowerSwitch 12V

Stable root: `outputs/power-laser-tests-2026-10-04/02-powerswitch-12v`.

One native schematic/project preparation passed for twelve references, including three purchased SMD parts: IPB80N04S4L04ATMA1, CRCW1206330RFKEA and CRCW251247K0FKEG. This is a draft; complete source/package/model qualification remains outstanding. No vector approval or PCB placement has occurred.

The proposed circuit is a low-side resistive-load switch with a 330 Ω gate resistor and 47 kΩ pull-down. It requires an external current-limited source/load and a continuously connected 5 V push-pull driver. Initial testing is DC on/off at ≤1 Hz. Unknown copper, switching behavior and heating remain physical holds; it is not a qualified 5 A product.

Actual source review found that the installed generic TO-263 footprint uses smaller lands than Infineon's PG-TO263-3-2 recommendation. The proposed pinned local footprint uses 4.6 × 1.35 mm gate/source lands and a 9.5 × 10.9 mm drain land, retaining the 5.08 mm gate/source pitch and 9.15 mm lead-to-drain center separation. The package and footprint drawings were viewed. Datasheet page 1 confirms 1=gate, 2=drain/tab, 3=source. Proposed asset, source hashes and observations are in `sources/footprint-review.json`; this is not native acceptance.

Three native preparation invocations are retained:

1. Failed before output because `Device:Q_NMOS_GDS` is not in the installed KiCad 10 library.
2. Passed after resolving the installed `Transistor_FET:Q_NMOS_GDS` and the other symbols.
3. Failed before output because my input-preparation snippet supplied float atoms to a string-based S-expression serializer, then the shell continued with a missing specification file. This was an orchestration error, not a KiCad or router defect.

The proposed asset and specification now parse correctly, but native preparation was not rerun. The lifetime operation allowance and completed diagnostic are preserved. Further work needs a supported finite recovery for this exact pre-output failure; it does not need another routine user approval. Never launch a dependent producer after failed input preparation.

At the stopped checkpoint: 51m43.744s wall, 51m39.799s evaluation, 3.945s supervised execution. This overlaps PowerTrace work and must not be added as separate end-to-end elapsed time. The stop was the operation/diagnostic boundary, not timer expiry.

## Remaining delivery work

Finish the supported recoveries, current engineering/native/visual review, automatic routing and release. Then generate both-face 0.5/0.8 mm isolation SVG/PNG, **both contact-only coating-removal SVG/PNG**, drill files/map, portable KiCad dependencies, editable reviewed vector and interactive BOM. Run exact handover and archive verification before claiming readiness. Copper thickness, temperature rise/drop, plated-hole quality, component fit and powered behavior require actual measurements on the exact as-built revision.

No platform framework change, commit, push or new fabrication-ready delivery was made in this attempt.
