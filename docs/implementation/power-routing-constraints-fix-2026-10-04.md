# Power routing constraints and paste-pad fixes — October 4, 2026

The user's “just do the fixes” authorized this separate software scope. Both fixes are implemented and verified. No production board was routed, edited, approved or released during this scope. PowerSwitch's rejected candidate and two-attempt stopped job remain unchanged; PowerTrace's accepted delivery remains unchanged.

## Final behavior

`RouteNetLayerConstraint` carries exact net names, allowed copper layers and explicit via permission in the immutable `RouteRequest`. Net names/layers are canonical, duplicate or overlapping declarations fail, unknown nets and disallowed layers fail, and constraint IDs participate in the consumption ledger and fingerprint. Empty new fields are omitted so historical requests and fingerprints replay unchanged. The ordinary `production_routing` CLI accepts the typed list in its existing routing-options JSON; there is no separate board-specific route producer.

The pinned Freerouting 2.3.0 bridge splits a class when same-width nets need different restrictions. It exports `use_layer` and, for a net forbidden to use vias, the existing single-layer compatibility-padstack mechanism. The global physical through-via technology remains available to other nets. No-via nets must select exactly one layer; unsupported multilayer/no-via declarations, ambiguous classes, class-pair rules and conflicting layer-specific rules fail explicitly. Export preserves clearance and width requirements. A conflicting reserved compatibility padstack is rejected.

Imported native copper and the engine-neutral candidate validator independently reject a restricted net's forbidden segments, vias or zones. The native A* and other external adapters do not claim to consume unsupported new restrictions. A clean KiCad DRC result cannot override these constraints.

The pin-net reader now omits only pads satisfying all of: empty number, SMD kind, explicitly nonempty paste-only layers, and no drill declaration. Numbered pads, copper pads, drilled pads, missing-layer records, mask-only records and disagreeing stacked electrical pads remain checked. The actual retained PowerSwitch candidate now matches all 16 intended electrical pad bindings; its four unnumbered Q1 paste apertures are correctly excluded.

## Exact verification

Receipts and source hashes are retained under `outputs/platform-power-routing-fixes-2026-10-04/`.

- **201 regression tests pass** across routing IR, native/external adapters, transaction, policy, preparation/revision, package geometry and new restriction cases. Following the final reserved-padstack guard, **27 targeted tests pass**; these overlap the broader suite and are not added to it as distinct tests.
- **Two real pinned Freerouting probes pass**, each capped at five passes and 60 process seconds, using synthetic DSN fixtures only. In the feasible fixture, the restricted net uses F.Cu with zero vias while the separate cross-face signal uses a via. In the impossible fixture, moving one restricted terminal to the rear leaves exactly one open connection instead of using a forbidden transition; the unrestricted signal still routes. Neither probe is a production PCB or a claim of CAD handover/physical qualification. The final exporter reproduces both executed DSNs byte-for-byte.
- **Retained PowerSwitch read-only replay:** PCB `42fa069668abca429be029f2ef841a9b5a938d349f161a7240ac2f9150580a18` now passes pin-net equivalence. Adding the prospective P12/DRAIN front-only declaration to a diagnostic request causes native import to reject `/P12 on B.Cu`. This is a negative diagnostic, not a reissued production acceptance. The original request fingerprint remains `54fc2fddbbecf79adf9352a55e004d380e566d1761cbb4d11e137e3100b4f497`.
- Targeted **Ruff and mypy pass**. The workflow audit passes with **213 classified entries**, no unclassified/stale/changed-call findings. The changed production boundary remains the existing supervised `production_routing`/Freerouting bridge; the added integration test calls a bounded external process on synthetic interchange only and produces no native board. No new bypass or board-job allowance was added.

During development, the first synthetic fixture passed geometrically but logged that an empty named via rule was missing. Inspection of the pinned parser confirmed empty rules are ignored. That draft was replaced with the existing single-layer compatibility mechanism, and the feasible/impossible probes passed without that warning. Earlier logs remain in `.tmp/power-constraints-synthetic-smoke-01/`; they are not the final qualification. Two unit-fixture/idempotence failures and a final type-annotation error were corrected; their earlier logs remain retained. This report refers to the verified final implementation.

## Scope and remaining board work

These restrictions apply to an entire net. They do not express a selected high-current branch within a shared ground net while allowing different rules on its low-current branches. Actual source-to-terminal path review remains necessary in that case. The no-via translation is qualified for the pinned 2.3.0 bridge, not arbitrary router versions; the installed tool was not upgraded.

PowerSwitch still requires a separately scoped constrained board run and its complete final native, visual, CAM/pad/drill/iBOM and handover checks. Its original job has already used both allowed routes, so these software tests do not reset that history or manufacture another attempt. The old candidate is still unsuitable for the reviewed power requirement. No 3–5 A rating, plating ampacity, thermal behavior or physical switching qualification is inferred.

No commit/push, unrelated cleanup or modifications to accepted board packages were made. The shared delivery index and current-state/register now distinguish the completed software fixes from the unfinished PowerSwitch board.

## Upstream interpretation

The implementation was checked against the pinned source, not a current-version assumption: [Circuit parser, v2.3.0](https://github.com/freerouting/freerouting/blob/v2.3.0/src/main/java/app/freerouting/io/specctra/parser/Circuit.java) reads per-class layer/via selections, and [Network parser, v2.3.0](https://github.com/freerouting/freerouting/blob/v2.3.0/src/main/java/app/freerouting/io/specctra/parser/Network.java) applies active routing layers and skips empty named via rules. Retained source URLs and hashes are in the platform manifest. Actual installed-engine tests establish the behavior used here.
