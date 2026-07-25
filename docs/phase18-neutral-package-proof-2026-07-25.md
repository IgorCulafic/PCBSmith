# Phase 18 neutral-package proof — 2026-07-25

## Scope and disposition

PCBSmith generated, independently unpacked, hash-checked, model-reloaded, and
visually inspected one manufacturer-neutral package for each of these exact
routed boards:

- regular rectangular Retro-Pad 3x3 R001; and
- irregular/cutout Retro-Pad R003.

This closes the Phase 18 cross-board package-structure proof. It does **not**
make either package fabrication-ready or assembly-ready. Both manifests remain
`blocked` because the board-specific current paths are deliberately
`unverified` and the ten-category DFM/DFT reports are not ready.

Canonical retained evidence is under the ignored path
`.pcbsmith/verification/phase18/neutral-package-proofs-2026-07-25-r6/`.
Earlier `r3` through `r5` roots retain the corrective failure progression.

## Corrections found by inspecting the outputs

The first exporter/package pass was not accepted merely because commands
returned success:

1. InteractiveHtmlBom with optional track/zone rendering became idle and did
   not complete. The process was stopped, the failure root was retained, and
   the optional copper view remains disabled until it has a bounded,
   deterministic proof.
2. KiCad's `.gbrjob` metadata file was initially classified as a Gerber image.
   It is now retained as `other`; only recognizable layer Gerbers use the
   `gerber` role.
3. The first so-called fabrication PDF was a cluttered `F.Fab`, `B.Fab`, and
   `Edge.Cuts` overlay, while the assembly PDFs were tiny at fixed scale.
   Assembly plots now use automatic page scale and omit value text. The
   prototype fabrication sheet is now explicitly the KiCad PDF drill map with
   outline, drill symbols, counts, plating status, and a separate drill report.
4. The first ZIP manifest recorded fingerprints for the fabrication profile,
   manufacturing identities, current paths, and DFM/DFT report without
   including those records. Schema version 2 now includes all four exact JSON
   evidence artifacts and forbids callers from replacing the generated
   records.
5. The package README now states that the present fabrication PDF is a drill
   map, not a complete dimensioned fabrication drawing. Required dimensions,
   tolerances, fabrication notes, process confirmation, and approvals remain
   blockers.

## Accepted structural proof

| Evidence | Regular R001 | Irregular R003 |
| --- | --- | --- |
| Board SHA-256 | `176403c5e3663d11b1ff1a2a81489bb2277db35628e3f0d1d898b999a6e48f08` | `f9c3fadede4fb976dc0bb10d0aa90d1d4a346b12365cf581a963b8ff49ae6b81` |
| Package fingerprint | `f5187a2c79c968b78b69232b0a32580d475613ea944499bb1f6bdcf4c227a024` | `066a93602ece37d08af3cda655bd5b6a14e00266ce84452830a0135be46ff37d` |
| ZIP size | 498,444 bytes | 393,253 bytes |
| Manifest artifacts | 26 | 26 |
| BOM rows | 70 | 50 |
| Placement rows | 66 | 46 |
| Release status | `blocked` | `blocked` |

For each ZIP, independent extraction established:

- the archived manifest is byte-identical to the retained package manifest;
- the archive contains exactly the 26 manifest artifacts plus
  `manifest.json` and `SHA256SUMS`;
- every artifact digest matches both the manifest and `SHA256SUMS`;
- every artifact is bound to the exact board SHA-256;
- the embedded fabrication profile, identity registry, current-path record,
  and DFM/DFT report reload through their typed models and their fingerprints
  exactly match the manifest;
- `.gbrjob` is `other`, while the `gerber` role contains only layer Gerbers;
- the assembly, drill-map, and fabrication PDFs are single-page documents;
- the InteractiveHtmlBom files are self-contained; their only HTTP links are
  informational links to the upstream project and usage guide; and
- CSV headers and rows are parseable for BOM and placement consumers.

## Visual inspection

The six final PDFs were rendered at 150 dpi and inspected:

- regular front assembly: legible outline, switches, encoder, connector, and
  reference labels;
- regular back assembly: legible MCU, passives, diodes, LEDs, and references;
- regular drill map: complete rectangular outline, distinguishable symbols,
  and readable drill legend;
- irregular front assembly: complete dog-bone outline and coherent front-side
  placement;
- irregular back assembly: complete outline and readable bottom-side
  placement; and
- irregular drill map: complete irregular outline, distinguishable symbols,
  and readable drill legend.

These views prove inspectability of the generated documents. They do not prove
component sourcing, assembly sequence, rework clearance, drill/process
capability, impedance, current capacity, or fabrication acceptance.

## Remaining release work

- Build verified per-path conductor/current/voltage-drop evidence from actual
  operating requirements and exact copper geometry.
- Resolve every unsupported DFM/DFT category with selected process and
  assembly authority.
- Replace or augment the prototype drill-map sheet with the selected
  fabricator's required dimensioned drawing and notes.
- Generate a physical impedance coupon only when a selected stack-up requires
  one.
- Collect human engineering, fabricator, and assembler approvals only after
  the exact package satisfies their gates.

