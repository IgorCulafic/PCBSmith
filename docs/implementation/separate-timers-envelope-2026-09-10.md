# Separate evaluation/execution clocks and conservative envelope — 2026-09-10

Status: shared implementation verified and independent fresh-board proof passed. Retained B4 routing is accepted, with a formal visual metadata follow-up still open. See [timing proof](fresh-board-timing-proof-2026-09-10.md). User authorization: the 2026-09-10 approval of the prospective execution/completion approach and separate evaluation timers. This supersedes a combined hard twenty/thirty-minute limit for new trials. Platform work is separate from the retained board and prospective fresh-board clocks.

## Scope and completion criteria

1. Implement independent evaluation and execution accounting, test expiry/reserve/restart behavior, and preserve all legacy windows and retry caps.
2. Implement an exact conservative projected-envelope screen and narrowly reviewed validation-policy revision. Preserve exact-simple legacy behavior, original limits, saved copper and failed checks. Run the affected unit/integration, typing, lint and caller gates.
3. Through the existing B4 owner, record the newly approved verification-only recovery with resolved-blocker hashes. Revalidate the retained complete copper without invoking the router. Complete current native visual/readiness publication if it passes.
4. Only then start a separate prospective four-corner, 32-component trial before project-specific preparation. Record separate clocks, editable vector inspection, actual route and final publication. Report every stopped attempt and honest timing; do not claim a pass without all gates.

## Timing semantics

New production CLI jobs default to 1,200 seconds evaluation and 1,800 seconds supervised execution, including a 360-second verification reserve. The outer deadline is their sum (50 minutes for this scoped simple-board policy), not twenty minutes. These allowances can be declared explicitly before preparation; execution remains bounded by declared complexity. Evaluation may be scoped up to 7,200 seconds. These are fallback caps, not target durations or guaranteed delivery times.

Time between workers includes investigation, input preparation, thinking, visual review and handover. It consumes evaluation only. A contained supported operation consumes execution only, including its subprocess setup/teardown. Worker operation classification is derived by the shared owner. There is no operator pause, arbitrary phase label or automatic renewal. End timestamps are retained, concurrent/overlapping attempts are rejected, and new instances derive the same cumulative clocks. An unsettled worker after an outage remains unsettled; it does not refund time. Total wall time includes all elapsed time and is always reported separately.

Old ledgers and continuation windows retain their original whole-wall limits. The Python API retains its legacy default when evaluation_seconds is omitted; the production CLI explicitly starts the new mode. Explicit authorized continuations can opt in without changing predecessor bytes, original deadlines or lifetime counters. All correction, identical-input, repeated-failure, diagnostic and lifetime operation checks remain in force.

## Envelope scope

The monotone-chain convex hull uses exact rational projected path-node coordinates, including straight endpoint closures. The result is a separate projected_envelope_area_mm2 bound, not a replacement fabricated simple-loop area. Crossed closures can have a finite conservative envelope. Collinear/degenerate input remains unverified. An envelope exceeding its limit is inconclusive, not proof of excessive physical area. Trace widths, package-internal current distribution, inductance and EMC are outside this geometric screen.

The reviewed replay revision binds the original engineering source, rejected transaction and exact candidate SHA-256. It permits only exact_simple to conservative_envelope plus explanatory rationale/revision metadata; it cannot change terminals, nets, loop coverage, thresholds or topology requirements. Original route inputs remain frozen. Fresh native and engineering checks still execute. No positive records are substituted and no board geometry is changed by the method revision.

## Verification and live results

Pending final scoped gate and actual supported replay. No new board acceptance or fresh timing pass is claimed by this implementation record alone.


## Retained-board phase completion

The same B4 job accepted a fifth explicit continuation window on 2026-09-10. Its empty build_operations scope prohibited rerouting or editing. The third lifetime routing-validation attempt passed in 38.516 seconds, reusing the exact saved candidate. Native enabled DRC/parity/opens and pin-net equivalence pass. The final engineering gate is ready: conservative envelope 100.118 mm² for U1 and 247.724 mm² for U2, within unchanged 200/400 mm² limits. U2's simple closure remains non-simple in the result; its alternative bound is explicitly recorded.

All 11 native 2D and 10 native 3D images plus 32 current component crops were inspected. The final package was published through pcbsmith.production_routing:route_saved_placement_candidate with a receipt derived from the accepted transaction. The platform registry previously omitted this ordinary router; it is now explicitly registered and rejects a foreign engine adapter under that identity. Current readiness uses exact native dependency hashes and freshly replayed proxy models. No new visual correction was needed.

Final generation: outputs/bounded-workflow-b4-2026-09-07/production-routed-final-2026-09-10/generations/final-routed-2026-09-10. Exact source/candidate checks, visual observations, current requests and handover: B4 envelope-recovery-2026-09-10/. The source placement and accepted CornerStep remain byte-identical; retained copper SHA-256 is f10eaefdc107ad72fba6f835f8647e656624c01173d036a98a5e8f6b8fbd181e.

This window completed in 562.472 seconds: 214.753 evaluation and 347.719 supervised execution (including setup/teardown). Worker-reported durations: validation 38.516 s, full native rendering 296.969 s, supported final publication 12.141 s. Completion timestamps freeze the report; later status calls cannot turn a completed job into an expired one or inflate its duration. Total historical wall time remains separately retained, including old windows/outage; the original thirty-minute trial remains a failure.

Verification: 212 affected tests, 27 publication/readiness tests, plus the targeted completion-timestamp regression suite in outputs/separate-timers-envelope-2026-09-10/. Strict typing and lint pass for the changed evaluator/timing owners; caller audit reports 196 classified and no changed/unclassified callers. The completion timestamp fix has its own retained follow-up test result. These are software gates, not physical qualification.

Remaining limitations: unbuilt prototype, established proxy-model scope, dense non-silkscreen fabrication value text near lower transistor/resistor groups, and required solder/wire joins for the unplated home process. No EMC, thermal, supply-integrity or exact purchased-package qualification is claimed. The independent prospective fresh-board proof remains outstanding until it runs.


## Completion update - 2026-09-10

The independent fresh-cornerstep trial completed supported final publication at outputs/fresh-cornerstep-timing-2026-09-10/production-final/generations/fresh-final-01. All 32 final visual artifacts have sealed accepted inspection decisions; enabled native DRC, opens, parity, pin-net equivalence and conservative bypass-loop screening pass. One initial placement and routing candidate, zero corrective cycles, no deadline extension. The frozen timing and exact identities are in outputs/fresh-cornerstep-timing-2026-09-10/handover.json and docs/implementation/fresh-board-timing-proof-2026-09-10.md. The 240 distinct focused tests pass; strict typing on six changed source modules and lint on ten changed source/test files pass; the workflow caller audit has 196 classified callers and no outstanding findings.

B4 distinction: its retained copper passed routing/native/engineering acceptance and its local prototype publication committed. Actual visual observations are retained separately, but its older committed visual manifest remains generated_pending_inspection with 32 uninspected artifacts. Therefore full formal B4 visual acceptance is still pending; publication alone does not establish it. Its finished ledger and immutable generation were preserved. The fresh trial has the complete formal inspection record. Original failed B4 timing remains failed. Physical qualification and DR7 remain open; later roadmap phases await review.
