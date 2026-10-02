# Roadmap Phase 1 — completion and verification

Date: 2026-09-06. Authority: the user requested completion of the approved Phase 1 before a separate appropriate board test. This continues [the foundation record](roadmap-phase-1-iterative-edits.md); it does not renumber the historical implementation phases.

**Status: Phase 1 complete for the approved supported edit matrix, with the limitations below.** The later user board-design test has not been started. This is the supported working-CAD edit matrix, not universal KiCad editing, a production release, or completion of the full roadmap.

## What changed and why

| Confirmed issue / severity | Implemented response and evidence |
| --- | --- |
| P1: the public revision command had not adopted the existing IF owners. | [board_revision](../../src/pcbsmith/board_revision.py) now runs actual IF1–IF5 callbacks through the existing [checkpoint workflow](../../src/pcbsmith/iterative_fixing_workflow.py). The thin [workflow adapter](../../src/pcbsmith/board_revision_workflow.py) calls existing diagnosis/impact, placement, regional and semantic owners. Each retained candidate has `workflow/IF1.json` through `IF5.json`, a checkpoint, manifest and explicit working-CAD scope. |
| P1: there was no bounded expansion at the public edit boundary. | Requested geometry first tries its declared region; the [local-region owner](../../src/pcbsmith/local_routing_repair.py) expands only after a retained out-of-region failure and within the budget. Native segment and zone-outline examples each reject the initial region and succeed after one expansion. Exhaustion and protected-region intersection are tested. This scopes an explicit edit; it does not run a route-search algorithm. |
| P0: the final-fill helper retained only the PCB, so native fill could use a different project rule context. | [Final fill](../../src/pcbsmith/kicad/final_fill_adapter.py) now retains PCB/project/rules, recursive local sheets, table-declared libraries and local models, checks the exact context before/after the native tool, and retains its command/report. A fault-injection test proves a changed custom rule file blocks the result. |
| P1: the first real zone run exposed a false intent-change rejection. | KiCad inserts the derived `yes` fill-state flag when copper is filled. The shared intent reader excludes that state and computed polygons while retaining thermal, clearance, island, outline and other parameters. The first blocked attempt (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/native-zone-refill/fill/failure-snapshot.json`, not included in this public snapshot) and successful fresh retry (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/native-zone-refill-2/revision.json`, not included in this public snapshot) are both retained. Tests still reject changed thermal settings or undeclared zones. |
| P0: a whole-board native resave must not broaden a local edit. | [Native zone integration](../../src/pcbsmith/kicad/native_zone_edits.py) transplants only declared computed fill and its state into the declared native delta. All other object semantics/IDs stay protected. Full affected zone extents participate in region checks. Application refills again and rejects stale saved fill. |
| P0: interrupted work and stale stage evidence needed a public continuation path. | `production-edit-board --resume` validates the same request, predecessor, checkpoint, completed stage evidence, candidate and dependency closure. Completed stages are reused; partial native/fill attempts are retained before retry. A changed stage or candidate blocks continuation. Candidate save failure, interrupted application and recovery are covered by injected faults. |
| P0: rebuild decisions needed the expanded dependency closure too. | [Rebuild authority](../../src/pcbsmith/board_rebuild.py) now binds recursive local dependencies and the accepted-edit journal. [Shared generation](../../src/pcbsmith/production_generators.py) retains that exact predecessor context and rejects changes during retention. Changes to child sheets, model files or local libraries invalidate old decisions. Rebuild reconciliation still reports changed/removed objects and never silently overwrites the source. |
| P0: new revision/fill callers should not evade the writer inventory through neutral names or import aliases. | [Caller audit](../../src/pcbsmith/workflow_entrypoint_audit.py) now includes the revision, refill and context-retention owners explicitly. All 194 discovered callers have reviewed [classifications](../board-workflow-entrypoints.json). Unknown/changed callers fail shared verification. This is workflow enforcement, not a sandbox for arbitrary local Python. |

## Completion criteria and evidence

| Phase 1 requirement | Result |
| --- | --- |
| Supported public saved-board entry over existing owners | CLI matrix below; actual shared IF stage artifacts accompany every candidate. |
| Explicit requested move versus optimization | Requested rotation passes with unchanged topology score; the optimization control rejects a non-improving request. Exact placement, native ERC/DRC and schematic parity remain separate gates. |
| Text, reference, model, component/rotation, trace and via edits | All exercised on retained native copies through `production-edit-board`; generators and autorouters were not invoked. |
| Zone/fill effects and regional expansion | Native refill, bounded outline repair and a component move with attached traces plus zone refill pass. Undeclared zone authority is rejected. |
| Preserve source/context and unrelated objects | Independent KiCad load/save/reopen checks on 12 positive cases find zero undeclared changes. Pure native object inventories cover other saved fields and identities. |
| No-op and undo | No-op is byte-identical and makes no new check claim. Public apply, inverse edit and inverse apply restore original object semantics with two journal entries; restore record (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/restore-summary.json`, not included in this public snapshot). |
| Conflicts, save failure and interrupted promotion | Regression tests reject stale inputs/evidence and injected save failures. An interrupted board/journal application makes the project unreadable until recovery; recovery refuses to overwrite subsequent manual work. |
| Resume | Public CLI continuation skips completed IF stages, retains partial native output and rejects altered completed evidence/candidate bytes. This is injected process interruption, not a physical power-loss experiment. |
| Rebuild controls | Existing predecessor without an explicit decision is rejected; changed dependencies/journal and unsubstantiated exhausted-repair claims fail. Shared builder tests retain predecessor/reconciliation and failures. Test authorizations are synthetic, not fabricated real engineering approvals. |
| Existing repair fixture adoption | W10A v14 title move passes through the public CLI on a fresh complete project copy. Its existing visual/package hold remains. The previously retained synthetic via fixture is also replayed. |
| Timings and saved visuals | Per-command, per-stage and native-check durations retained; native SVG render and independent readback below. |

## Live native matrix

Evidence root (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion`, not included in this public snapshot), summary (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/native-matrix-summary.json`, not included in this public snapshot). Each `process-*.json` contains the actual command, return code, stdout/stderr and timing. Candidate directories retain exact requests, predecessor/candidate inputs, deltas, shared workflow records and native reports.

| Case | Changed objects | Protected objects | Result | Seconds |
| --- | ---: | ---: | --- | ---: |
| blocked | 3 | 63 | blocked_candidate | 6.48 |
| component | 3 | 63 | digitally_checked_candidate | 5.48 |
| model | 1 | 65 | digitally_checked_candidate | 5.33 |
| noop | 0 | 66 | no_change | 1.86 |
| reference | 1 | 65 | digitally_checked_candidate | 6.64 |
| regional | 3 | 65 | digitally_checked_candidate | 6.42 |
| restore | 3 | 63 | digitally_checked_candidate | 4.86 |
| rotation | 2 | 64 | digitally_checked_candidate | 6.08 |
| segment | 3 | 65 | digitally_checked_candidate | 6.12 |
| silk | 1 | 65 | digitally_checked_candidate | 19.19 |
| via | 4 | 64 | digitally_checked_candidate | 6.61 |
| w10a | 1 | 96 | digitally_checked_candidate | 8.38 |
| zone-component | 4 | 66 | digitally_checked_candidate | 7.08 |
| zone-outline | 1 | 69 | digitally_checked_candidate | 7.42 |
| zone-refill-2 | 1 | 69 | digitally_checked_candidate | 7.78 |

All changed positive candidates have zero enabled ERC findings, DRC violations, unconnected items and schematic-parity findings. The deliberately bad D1 move retains six DRC violations and is blocked. BenchLeaf retains its four existing ignored ERC categories; these are recorded in the summaries, not silently treated as executed checks. Model resolution passes, while package/mechanical/visual qualification remains unaccepted.

The zone fixture is explicitly synthetic: native KiCad adds a ground zone to an isolated BenchLeaf copy with unchanged rules. It is not a proposed capacitor/return-plane redesign or fabrication recommendation. The two fixture-setup API/name errors occurred before any board save and are retained in `zone-fixture-*-failure.json`. The first real refill failure led to the adapter correction above; no failed attempt was deleted or relabeled.

Independent native readback (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/native-readback.json`, not included in this public snapshot) uses KiCad 10.0.3 to load every positive edit class, inspect footprint/pad/net geometry, reference positions, model transforms, copper and zone fill state, save separately, and reopen. All 12 cases have zero undeclared changes. The previously observed 1 nm native roundtrip rounding on the intentionally rotated pad is explicitly bounded; it is not a tolerance for changing protected objects. Zone cases retain their filled state and polygon inventory after reopening.

Saved copper/silkscreen SVG (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/zone-component-preview.svg`, not included in this public snapshot) and render log (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/render-process.json`, not included in this public snapshot) were produced in 0.328 seconds from the exact zone/component candidate and visually inspected as a diagnostic overlay. The filled region, clearance voids, thermal connections and retained labels are visible. This does not certify thermal spoke performance, home etching, all visual crops or assembly access.

Observed normal edit-command times are generally 5–8 seconds here, with a 19.19-second first silk run; the no-op took 1.86 seconds. Concurrent verification and startup affect these measurements. They are not a controlled comparison with the user's 70-minute complete board-design session. Phase 3 still needs end-to-end engineering/orchestration timing.

## Software verification

- Complete standard verification (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/verification-standard-1/verification-run.json`, not included in this public snapshot): all six gates passed; 3,840 tests passed, 18 skipped (3,858 collected), approximately 767 seconds for the test gate. This is the standard profile; opt-in deep/native golden campaigns and remote CI were not run.
- Final complete quick verification (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/verification-final/verification-run.json`, not included in this public snapshot): all six gates passed on final source, including repository lint, lock consistency, full-source typing, architecture contracts, the 194-caller audit and 184 focused tests. This follows the final dependency/inspection changes made while the broader suite was running.
- Final affected regressions (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/affected-tests-final.xml`, not included in this public snapshot): 121 passed, including public CLI resume and candidate-save failure. Rebuild/readiness tests (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/rebuild-final.xml`, not included in this public snapshot): 22 passed after complete-context rebuild hardening. Counts overlap; do not add them.
- Final preservation/replay check (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/final-preservation-replay.json`, not included in this public snapshot): all 13 successful retained revisions, including the inverse edit, replay with final source. Original BenchLeaf and W10A project closures match their untouched starting copies. BenchLeaf PCB SHA-256 remains `35d15caf403f15e8826e301fc9fca56364f507aa4f3985f6d1f8e06f77cbdace`.


Relevant regressions include [revision completion](../../tests/unit/test_board_revision_completion.py), [native fill](../../tests/unit/kicad/test_native_zone_edits.py), [exact final-fill context](../../tests/unit/kicad/test_final_fill_adapter.py), [regional qualification separation](../../tests/unit/test_local_routing_repair.py), [rebuild inputs](../../tests/unit/test_board_rebuild.py) and [caller/alias controls](../../tests/unit/test_workflow_entrypoint_audit.py). Historical qualified-routing receipts remain readable; geometry-only results cannot masquerade as qualified-routing metrics in the shared domain.

## Supported boundary and remaining work

- Supported: board/reference text positions and angles, front-side component poses, selected straight-track replacement and via movement, existing model xyz offsets, explicit native zone refill and single-outline same-vertex-count zone edits. Recursive project-local schematic and model dependencies are retained.
- Unsupported object classes stop explicitly: back-side component transforms, attached arcs/locked copper, footprint/package substitutions, arbitrary outline/layer/architecture changes, and unresolved/outside-project hierarchical dependencies. The approved roadmap permits these explicit stops; this completion does not claim arbitrary KiCad support. Phase 2 owns qualified substitutions and broader package authority.
- A regional result is a geometric scope check. Unmeasured DRC/open/width/return metrics remain null at that stage, followed by actual native checks. It does not prove a new routing engine succeeded. Whole-zone connectivity/thermal/return-path and mating/visual obligations remain unverified where measurements/review are absent. Declared protected regions are conservative geometry constraints, not automatic physical qualification.
- Working CAD candidates and applications remain `production_accepted: false`. Existing visual/component/engineering, routing publication, manufacturing and physical evidence must be refreshed for stronger acceptance. No dummy positive records fill these gaps.
- Cross-phase bypass work remains: ordinary generation orchestration and full stage provenance in Phase 3, broader consuming-boundary and two real DR7 proofs in Phase 4, justified script retirement in Phase 6. Static inventory cannot prevent arbitrary filesystem writes or authenticate approval-reference strings.
- Original BenchLeaf R001, accepted R005/R006 scopes, W10, Montenegro and AeroSense holds are preserved. No commits, publishing, destructive cleanup or physical operations were performed. No original board was applied or rebuilt.

## Next user test

Use a disposable but representative complete native project through the public commands. Include a component move with attached copper and declared zone effects, one bounded expansion, a deliberately blocked request, apply, undo and interrupted-run continuation. Check exact preserved objects and native readback, then inspect affected visuals/engineering constraints. Choose any new-board design separately; do not count these synthetic fixtures as a new DR7 board. The user asked to do that separate test after Phase 1, so it has not been started here.

Implemented file changes are recorded against the start-of-turn source hashes in changed-files.json (local reference `../../outputs/roadmap-implementation-2026-09-06/phase-1-completion/changed-files.json`, not included in this public snapshot): 15 source modules, 7 test files and 7 documentation/policy files; no files were removed. Pre-existing unrelated working-tree changes were retained.
