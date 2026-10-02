# Routing acceptance implementation and interrupted recovery — 2026-09-09

Status: shared implementation verified; native routing complete; final engineering/publication acceptance BLOCKED. Fresh-board timing proof is not claimed.

## Authorized scope and preservation

The user authorized routing acceptance and a fresh-board timing proof, then explicitly asked to resume after a power outage. All B4 work stays under `outputs/bounded-workflow-b4-2026-09-07`. No original deadline, correction count, failed result or accepted predecessor was reset. The original two corrective cycles remain consumed. Four explicitly recorded continuation windows now remain in the ledger, including the latest verification-only outage recovery. Its `build_operations` is empty.

The accepted CornerStep board remains SHA-256 `54652c98f30a697520b8b0c5a0a797264088bf2a1e81e3bfac53bf0764962786`. B4 placement remains `ead13c54e839ee446e569af2133694da78a3133b1d2ef285be3568e6065841d4`. No component move, silk adjustment or regeneration occurred in this phase.

## Implemented changes

- `src/pcbsmith/board_job.py`: a newly authorized resolved-blocker recovery may bind the exact latest failed routing token with `retry_failed_operations`. It retains lifetime operation limits, predecessor windows and correction counters; identical effective inputs remain rejected. Verification-only recovery grants no build operation. `production_routing --revalidate-result` is classified as verification, with the same supervisor and finite operation limits.
- `src/pcbsmith/kicad/routing_candidate_adapter.py`: the production initial-route path normalizes copper coordinates to the native writer's precision before sealing the deltas. Existing-copper conversion is rejected before search. Default historical adapter behavior remains unchanged.
- `src/pcbsmith/routed_copper_graph_ir.py` and `src/pcbsmith/kicad/routed_copper_graph.py`: explicit native through-pad transitions, opt-in exact point/T-junction contacts and conservative native pad-region contacts. Collinear overlap remains unverified. Pad-contact edges have no invented trace width or via size and are excluded from trace-length totals. The radial witness is a projected topology convention, not a physical current distribution. Optional fields are omitted at defaults to preserve old serialized identities.
- `src/pcbsmith/decoupling_loop_ir.py`, `src/pcbsmith/kicad/decoupling_loop.py`, and new `src/pcbsmith/production_decoupling.py`: retain distinct physical switch pads with the same electrical pin number; reject conflicting nets, stacked aliases, unsupported pad shapes and ambiguous multi-pad loop endpoints. Native pin inventories include every physical instance. No internal switch copper is fabricated. Supported pad contact uses strictly interior points in a disk inscribed in the saved circle/oval/rectangle/rounded-rectangle dimensions, so tangencies and outside/foreign-net points are not joined.
- `src/pcbsmith/production_routing.py`: require pinned project loop requirements before search; execute real native copper-loop evaluation after native checks; bind final engineering evidence to the actual routed layout. Failed or unverified results cannot be promoted.
- `src/pcbsmith/kicad/routing_candidate_transaction.py`: validation-only replay binds a rejected result hash, exact request, snapshot, source files, original route result and engine logs. It invokes no router and requires byte-identical candidate serialization. Fresh native/electrical/engineering validation still runs. Changed or partial candidates are rejected.

## Actual board results

The explicitly authorized deep-profile search completed all 27 nets in **35.844 seconds**, using 1,057,367 of the finite 5,000,000 expansion allowance. It produced 220 segments and 6 vias. The full supervised routing/validation operation took 57.329 seconds and was rejected by the then-incomplete switch-pad validator.

Two later validation-only operations took 30.843 and 29.844 seconds. Both retained exactly the same candidate board bytes, SHA-256 `f10eaefdc107ad72fba6f835f8647e656624c01173d036a98a5e8f6b8fbd181e`. Neither rerouted it. All failed results remain retained.

Final native checks report zero DRC violations, zero unconnected items, zero schematic-parity findings and matching pin/net assignments. These statements apply to the enabled checks; five ignored check categories remain declared in the native report. No production generation pointer was promoted by the rejected transactions.

Evidence:

- `outputs/bounded-workflow-b4-2026-09-07/routing-acceptance-2026-09-09/result.json`
- `outputs/bounded-workflow-b4-2026-09-07/routing-validation-2026-09-09/result.json`
- `outputs/bounded-workflow-b4-2026-09-07/routing-validation-pad-contact-2026-09-09/result.json`
- Final `routing-candidates/candidate-01/verification/{drc.json,pin-net-equivalence.json,native-fill.json,candidate-validation.json,engineering-gate.json}` under the last directory.

## Remaining engineering gate: confirmed limitation, not a confirmed electrical fault

Criteria were pinned before routing in B4 `acceptance-2026-09-09/routed-engineering-source.json`: 0.8 mm minimum trace width; at most six vertical transitions including native pad transitions; projected envelope/area limits of 200 mm² for U1 and 400 mm² for U2. Shared branching is explicitly permitted for this prototype. These are project screening criteria, not manufacturer or measured EMC limits.

U1 passes: exact simple projected area **75.366 mm²**, minimum trace width 0.8 mm and four vertical transitions.

U2 has exact connected supply and return paths, minimum trace width 0.8 mm and four vertical transitions. Its ground path is classified as a daisy chain through U2 pin 13 and R3 pin 2. That classification is disclosed and permitted by the pinned prototype policy. Its projected area remains **unverified_non_simple**. The mathematical straight closure from VDD `(54.62, 24)` to VSS `(47, 41.78)` crosses the return-path projection twice. The closure is not a PCB trace or a measured internal IC current path. No supply-to-return short is inferred from those crossings.

See `outputs/routing-acceptance-2026-09-09/loop-projection-diagnosis.json` and the inspected editable projection diagram (local reference `../../outputs/routing-acceptance-2026-09-09/u2-loop-projection.svg`, not included in this public snapshot). Diagnostic convex envelopes are 100.118 mm² (U1) and 247.724 mm² (U2). These numbers are retained as diagnostic calculations only; they do not replace the currently required exact-simple-area result or grant acceptance.

Recommended next change: add an explicitly named conservative projected-envelope screen to the shared evaluator, with exact rational hull geometry, replay validation and a separate bound/result field. Keep the existing 200/400 mm² limits. Preserve exact-simple-area behavior and mark its applicability honestly. Test self-crossing closures, degenerate/collinear inputs, foreign geometry and limit exceedance before using this method. A bound exceeding its limit must not be converted into a physical failure claim or a smaller area estimate. This changes the documented method, not the board or the threshold, and needs a reviewed scope before another B4 validation allowance. No board rebuild is justified by this finding.

## Power-loss recovery

Three test files had zero-filled prior contents after the outage: `test_board_job.py`, `test_production_decoupling.py`, and `kicad/test_routing_candidate_transaction.py`. The damaged copies are retained in `outputs/routing-acceptance-2026-09-09/power-loss-recovery/`. Original literal writes/substitutions were recovered from read-only local task history; the tracked transaction-test baseline was also used. No historical command was executed wholesale. Two command-display quoting artifacts were corrected, the runtime-isolation test fixture was restored, and all pre-outage test names were checked against the last passing XML inventory. New tests were retained. Source modules and recorded candidate/evidence hashes survived intact.

The outage did not pause or rewrite a board clock. The old allowance expired. The user's resume message authorized a new, separately recorded verification-only window. Consequently neither this recovery nor its elapsed wall time can be represented as the original thirty-minute timing proof.

## Verification and remaining limits

Final evidence root: `outputs/routing-acceptance-2026-09-09/`.

- `final-tests.xml` / `final-tests.log`: 202 affected integration tests.
- `final-types.log`: strict mypy across nine affected source modules.
- `final-lint.log`: Ruff over fifteen affected source/test files.
- `final-caller-audit.json`: 196 classified callers; no unknown, changed or stale classifications.

The scoped test suite covers deadline/continuation preservation, explicit failed-token retries, no-build recovery, no-engine revalidation, stale retained artifacts, actual native precision, graph contacts and failing engineering criteria. It is not a full-repository CI run or hardware qualification.

B4 is stopped by the repeated-failure fallback. No further automatic revalidation, new-root restart or correction is authorized by the diagnostic. Final routed visual/publication readiness is still pending. Through-hole CAD transitions require actual solder/wire continuity under the selected unplated home process; the graph is not proof of plated barrels, assembly accessibility or measured supply integrity. The board remains unbuilt.

Next-phase status and prospective timing criteria are in fresh-board timing readiness (local reference `fresh-board-timing-readiness-2026-09-09.md`, not included in this public snapshot).
