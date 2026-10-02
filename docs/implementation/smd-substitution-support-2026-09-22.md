# Source-qualified SMD substitution support — 2026-09-22

The shared same-footprint substitution workflow now accepts explicit SMD package evidence as well as historical through-hole evidence. This is separately authorized platform implementation. No accepted example PCB, package, production generation or stopped board-job ledger was changed.

## Supported scope

Front-side SMD parts with uniquely numbered, undrilled rectangular or rounded-rectangle F.Cu pads can use the existing inspect/edit/replay/apply transaction. Footprint identity, pin numbering/functions, nets, placement, pads, copper, models and object identities remain preserved; only reviewed MPN/value and associated source records change. Back-side components, custom/chamfered/oval pads, repeated or unnamed pads, package remapping and footprint changes remain unsupported. Unsupported geometry fails before a candidate is accepted.

The existing `PackageGeometryEvidence` schema and THT checks retain their meaning. `AnyPackageGeometryEvidence` also accepts the new `SmdPackageGeometryEvidence`; SMD records require `mounting: "smd"`. The same parser is consumed by preparation/readiness, source-context collection and both predecessor/replacement substitution checks. Historical untagged THT records remain readable without migration.

SMD validation checks complete terminal coverage, maximum body-envelope containment in the footprint courtyard, actual copper containment of each required land rectangle and a positive minimum terminal-contact overlap in both local axes. Rectangle corner containment accounts for rounded corners and local pad rotation, rather than treating rounded pads as solid bounding boxes. Saved board pad angles are normalized by the parent footprint rotation before comparing local source geometry. The 1e-9 mm numerical epsilon is for floating-point arithmetic only; it does not waive fabrication clearance or source tolerances.

## Supplying genuine evidence

Use the same `geometry_evidence` field of `PartSubstitution` and the same per-reference `component-package-geometry.json` map. The generated combined schema is retained at `outputs/smd-substitution-support-2026-09-22/part-substitution.schema.json`.

Required SMD fields:

| Field | Meaning |
| --- | --- |
| `mounting` | Exactly `smd`; a THT evidence object cannot qualify SMD pads. |
| `part_number`, `source_local_path`, `source_sha256`, `source_page` | Exact MPN and retained, source-bound geometry evidence. The transaction requires a confined project-local source path. |
| `coordinate_basis` | Explain top view, local origin, axes and numbered terminal positions. |
| `land_pattern_basis` | Explain the source and review behind required lands, tolerances and minimum contact dimensions. |
| `body_bounds_mm` | `[xmin, ymin, xmax, ymax]` for the maximum source-qualified package body envelope. |
| `pins[].number` | Exact pin number, covering every pad once. |
| `pins[].terminal_contact_bounds_mm` | Guaranteed contact rectangle across the reviewed terminal/placement tolerance envelope. A maximum terminal outer envelope is not guaranteed contact. |
| `pins[].required_land_bounds_mm` | Source-reviewed minimum required copper rectangle in footprint-local axes. Do not infer it from the existing pad merely to get a pass. |
| `pins[].minimum_contact_size_mm` | Required positive overlap width and height with the guaranteed terminal contact rectangle. |

All bounds and dimensions must be finite; rectangles must have positive area. Both old and replacement parts require their own exact MPN-bound evidence. Existing pin-function matching, hashed electrical suitability review, exact source closure and model-policy checks still apply. Manufacturer recommendations and engineering derivations must be genuinely reviewed; the geometry screen cannot establish the truth of supplied source interpretation or solderability.

Usage remains `production-inspect-board --substitutions`, then the existing `production-edit-board` and `production-apply-board-edit` under a live, properly authorized board-job worker. The planner is read-only and returns a deterministic delta; no new producer, router, board-specific script or bypass was added. The existing producer classification remains appropriate. Material changes still require current native checks and refreshed engineering/readiness/release evidence.

## Verification

The final focused regression run passed **114 tests**, zero failures/errors/skips, in 19.719 seconds. An earlier run passed 117 cases before three no-op THT variants of an SMD-only rotation test were removed. The final rotation test uses an elongated pad/land to expose incorrect parent-angle normalization. All six standard gates passed: lock, repository lint, caller audit, strict types, architecture and full tests. The full suite passed 4522 tests, with 18 standard-profile skips and zero failures/errors. Standard verification took 13m07s, including 12m34s for the full suite. The final focused run independently verified the strengthened elongated-pad rotation case (114 passes). Coverage includes source/readiness freshness; wrong MPN/pin coverage and order; body/land/contact rejection; rounded-corner and rotation handling; unsupported pad/layer/hole types; finite dimensions; backward-compatible THT validation; and full transaction replay, unchanged copper, atomic apply, rollback, interruption/resume, stale candidate rejection, missing worker and failed-native-check rejection for both THT and SMD.

The transaction tests use explicitly synthetic XML/native-check fixtures, so they establish software control behavior, not live KiCad SMD qualification. No new real-part SMD replacement or hardware measurement is claimed. The separately retained BeaconLeaf R2 revision remains to be executed using genuine resistor source evidence and the original stopped-root recovery rules.

Initial checks caught a missing pytest basetemp parent (setup errors before assertions), a fixture-import lint error and an explicit TypeAdapter annotation requirement. These were corrected without relaxing validation; diagnostic details remain under the platform evidence root.

## Remaining work

The previous THT-only platform limitation is removed within this documented SMD scope. BeaconLeaf's actual 2.2k to 3.3k revision and live SMD native checks remain a board follow-up, with source-qualified body/contact/land evidence required. Its accepted CAD, corrected CAM delivery and stopped revision history are preserved. Desktop/iBOM interaction runtime failures and physical qualification are unchanged independent holds.

Exact source/test hashes, preserved accepted artifact checks, focused JUnit results and final standard gate results are retained in `outputs/smd-substitution-support-2026-09-22/implementation-evidence.json`. The full standard run used the unchanged final production code; the elongated-pad test was strengthened during that run and independently rerun afterward as part of the final focused suite. No further production code changes followed verification.
