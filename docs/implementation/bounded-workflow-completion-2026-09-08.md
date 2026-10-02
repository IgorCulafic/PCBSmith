# Bounded workflow recovery and stagnation control — 2026-09-08

## Outcome

The current recovery-control and native-stagnation fixes, current B4 component review and placement/readiness publication are complete. The live routing trial stopped and retained a partial result. **B4 routed acceptance and the original fresh-board timing proof remain open.** This does not close the entire bounded-delivery roadmap or later phases.

The user's clarification is recorded in AGENTS.md and maintained policy: prevent wasted revision loops without rushing useful engineering or cutting authorized platform work into arbitrary twenty-minute slices. Board operations still have finite declared allowances; stopping never means engineering acceptance.

## Changes

- `src/pcbsmith/board_job.py`: resolved-blocker recovery requires a completed previous continuation diagnostic, new explicit user authorization reference, exact predecessor hash, substantive resolution and unchanged retained evidence. Prior windows are archived and retained in continuation_history. Original deadline, job ID, attempts, correction count and lifetime operation restrictions remain. No automatic renewal, additional correction cycles or regeneration.
- `src/pcbsmith/kicad/routing_candidate_adapter.py`: forwards the requested stagnant-pass limit and reports stagnation as budget exhaustion.
- `src/pcbsmith/kicad/astar_router.py`: stops consecutive passes without increased completed-net count within each fine/coarse target set. Reordering alone is not progress; improvement resets the counter. Zero allows no failed-pass retry. Omitted limits retain the legacy pass-budget ceiling. Existing expansion/source/acceptance checks remain enabled.
- Updated authoritative status, working instructions and production usage. Historical failures remain unchanged. No commits or external publication.

## Current evidence

All paths in this section are under `outputs/bounded-workflow-completion-2026-09-08/`.

| Evidence | Result and scope |
| --- | --- |
| current-engineering-review.md, current-circuit-facts.json, component-review-execution.json | Fourteen newly reviewed IC obligations complete. Current netlist and pinned TI diagrams/tables inspected. Nominal interval 0.4644 seconds; physical/PVT behavior remains unmeasured. |
| placement-visual/review/manifest.json, visual-decisions.json, model-crops.json | 32 generated artifacts, including 21 native PNGs. Contact sheets, enlarged top and all 32 body crops inspected. Placement accepted; models remain proxies. F.Fab text crowding is a nonblocking drawing limitation. |
| readiness-replay.json | Current native inputs, source evidence, model hashes/transforms and actual pixel crops pass the shared saved-readiness evaluator. |
| concept-anchor-observations.json, concept-drift.json | All 96 explicit approved amended-brief coordinates/orientations match current native footprints. The prompt's empty anchor list was not used as proof. |
| layout.json, netlist.json, profile.json | Detached routing inputs match saved native geometry/electrical semantics, including the four corrected labels. |
| placement-publication-result.json | Supported placement transaction committed at B4/production-placement-recovery/generations/placement-recovery-2026-09-08. Exact existing native images retained without rerendering. |
| route-entry.json | Current entry gate passes with two actual post-route bypass-loop obligations, C3/U1 and C4/U2, deferred rather than waived. Prior exact ERC/parity remains applicable because checked native inputs did not change. |

## Live trial and diagnosis

Original root: `outputs/bounded-workflow-b4-2026-09-07`; job ID `efc4ac78633f47849c11e1dbbcb65665`.

A user-authorized 30-minute recovery window reserved six minutes for verification and permitted routing once. The exact predecessor ledger is retained as `.pcbsmith/continuation-predecessor-2.json`. Recovery took **720.115 seconds** through cancellation, including publication, gate preparation, routing and diagnosis. This excludes separately recorded engineering/render preparation and subsequent shared-code repair; it is not total board creation time. `scope.json` records the engineering session start. Original timing failures remain failures.

The production route used retained counter-first order and the standard **500,000 expansion** budget. It stopped in **19.579 seconds**, with zero restarts, retaining **109 segment and one via deltas**. Seven nets remain unresolved: +5V, GND, LED3_A/K, LED4_A/K and RESET. No final native validation or canonical board promotion occurred. These are partial route deltas, not a digitally checked routed PCB.

Evidence: `B4/routing-recovery-2026-09-08/result.json`, candidate request and telemetry; `B4/recovery-2026-09-08/routing-diagnosis.json` and `final-diagnostic.json`. The broader diagnostic completed in **75.943 seconds**. The original job was then cancelled through the supported control, without a retry or rebuild.

Confirmed findings:

1. **Selected search budget insufficient.** COUNT4 consumed 284,847 expansions; total reached 500,000. Selecting standard despite retained deeper prior experimentation was a preparation decision error. This does not prove an impossible placement or guarantee that a larger budget succeeds.
2. **Dropped stagnation control.** Request limit was two; actual backend telemetry reported 100 and the backend marked every pass non-stagnant. The shared fix addresses this independent loop risk. It did not cause or repair the observed first-pass expansion stop; historical evidence remains unchanged.
3. **Post-route engineering integration incomplete.** The deferred-feature loop in production_routing.py retains bypass requirements without executing them. Even a connected route needs actual copper-loop evaluation and retained execution evidence before stronger acceptance.
4. **Evidence preparation is still laborious.** Wrong import/path assumptions, canonical JSON newline rejection and decimal-string comparison errors were corrected before routing without board changes. A shared typed preparation adapter would reduce this overhead; new board-specific orchestration or copied approval results would not solve it.

## Verification and preservation

- Recovery/execution/preflight tests: **103 passed**, zero failures/skips (`recovery-tests.xml`).
- Router, native adapter and candidate transaction suites: **45 passed**, zero failures/skips (`router-tests-complete.xml`).
- Focused stagnation tests: **5 passed**, including the subsequently added progress-reset case (`stagnation-tests.xml`). Most overlap the broader run.
- Additional adapter stagnation-stop test: **1 passed**, proving typed failure and no retry (`adapter-stagnation-test.xml`).
- Scoped Ruff and mypy on the three changed source owners passed. Caller audit: **196 classified callers**, no unknown/stale/changed-call entries. This was not a complete repository/native-golden rerun.
- An initial test command named a nonexistent file and collected no tests; its failed log remains. Corrected suites passed.
- `final-state.json` confirms unchanged B4 placement SHA `ead13c54e839ee446e569af2133694da78a3133b1d2ef285be3568e6065841d4`, unchanged accepted CornerStep SHA `54652c98f30a697520b8b0c5a0a797264088bf2a1e81e3bfac53bf0764962786`, original job/correction history and stopped state.

Runtime assertions and file hashes are not an OS sandbox or authentication of a reviewer. Proxy bodies do not qualify purchased-part fit. Physical timing, startup/reset, rail extremes, brightness, transistor behavior and home-fabrication quality remain unmeasured. No fabrication release is granted.

## Next phase discussion

Before another board trial, choose an evidence-informed effective routing budget, integrate actual post-route bypass checks and simplify typed evidence preparation. A fresh end-to-end trial is still needed to demonstrate practical turnaround. Review these findings with the user before revising later phases; do not automatically reopen or reroute the stopped B4 job.
