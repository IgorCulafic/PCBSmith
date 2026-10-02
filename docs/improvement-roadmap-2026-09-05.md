# PCBSmith fixes and improvements roadmap — 2026-09-05

**Cross-reference update — 2026-09-22:** Preserve this document's requirements and phase numbering; use [current-state](current-state.md) as the single live queue. The review matrix (local reference `implementation/roadmap-cross-reference-2026-09-22.md`, not included in this public snapshot) credits completed work, identifies remaining enforcement/live-proof gaps and recommends practical deferrals. B4 exact inspection and live revised publication have since completed in their recorded scopes; SMD software support now exists, with its real-part trial pending. DR7, native UI and physical qualification are not declared complete. Historical “next” statements below do not override current status.

**Status revised 2026-09-10:** Phase 1 remains complete within its supported edit matrix. The bounded-workflow interruption has been addressed sufficiently to resume Phases 2-3: the independent familiar trial passed with separate clocks, vector planning, exact asset reuse and complete final visual inspection. Original B4 timing remains failed; its inspection metadata and physical qualification are separate explicit holds. Phases 2-7 and DR7 are not declared complete.

**Current execution detail:** [Revised Phases 2-3](phase-2-3-revision-2026-09-10.md) credits completed overlap and defines slices 2A-2C and 3A-3C. Start with current native input closure before layout. The historical September 6 timing priority is superseded by this revision; preserve its evidence.

The immediate objective is reliable, direct and reasonably fast ordinary two-layer board design. A local revision should modify the existing saved design through a bounded transaction. Initial generation and justified architectural changes may require a rebuild. The workflow must distinguish these cases before expensive work.

This roadmap reconciles the user's BenchLeaf feedback, retained failures, approved A01–A22 implementation, IF0–IF6 repair work, DR7 and unfinished formal Phases 17–21. The execution phases below order remaining work; they do not renumber the historical roadmap or erase completed implementation. Implementation is approved; use this order for the next fixes. Historical technical requirements remain at the linked sources.

## 1. Baseline and evidence

The user accepted BenchLeaf's appearance, spacing, clean layout and improved silkscreen, reported approximately 70 minutes of turnaround, and made direct iterative editing a priority while retaining rebuilding where appropriate. That feedback concerns the shown design; it does not claim inspection of every artifact or measurement of a manufactured board.

| Finding | Classification and evidence | Roadmap consequence |
| --- | --- | --- |
| BenchLeaf regenerated from its script for each routed revision. | **Confirmed.** [routed()](../tools/boards/benchleaf_r001.py) calls placement() and renders an explicit copper plan; routing receipt (local reference `../outputs/benchleaf-3v3-r001/attempts/manual-route-03/manual-routing.json`, not included in this public snapshot) records automatic_router_used=false. | Default to saved-board edits for revisions. This is not a DR7 automatic-routing proof. |
| Local-repair foundations already exist. | **Confirmed in source and scoped proofs.** IF plan (local reference `iterative-board-fixing-implementation-plan-2026-08-20.md`, not included in this public snapshot), IF4 (local reference `phase17-if4-local-routing-transaction-2026-08-20.md`, not included in this public snapshot), IF6 (local reference `phase17-if6-orchestration-and-evaluation-2026-08-20.md`, not included in this public snapshot). | Integrate existing mechanisms rather than create a competing framework. Scoped completion did not ensure BenchLeaf used them. |
| Placement repair is not a general user-edit operation. | **Confirmed in source.** [run_placement_repair_transaction](../src/pcbsmith/placement_repair_transaction.py) rejects topology_cost_not_improved. | Separate optimization repair from an explicit valid move request; preserve hard constraints in both cases. |
| Footprint recognition, silkscreen and model failures occurred. | **Confirmed and corrected for R001.** Builder failure (local reference `../outputs/benchleaf-3v3-r001/attempts/placement-01/builder-failure.json`, not included in this public snapshot), initial DRC (local reference `../outputs/benchleaf-3v3-r001/attempts/manual-route-01/drc.json`, not included in this public snapshot), failed visual manifest (local reference `../outputs/benchleaf-3v3-r001/attempts/visual-before-capacitor-model-fix/review/manifest.json`, not included in this public snapshot). | Resolve dependencies early and repair locally. These are not remaining findings on the final board. |
| Custom scripting and workflow repairs were mixed into board construction. | **Confirmed.** Build record (local reference `board-builds/benchleaf-3v3-r001.md`, not included in this public snapshot); about 1,750 lines across the three helpers, including declarations/checks. | Extract proven reusable operations and measure complete workflow cost. Line count alone is not a removal criterion. |
| The 70-minute total lacks a complete performance breakdown. | **Unverified attribution.** User-reported total; file times show chronology, not exclusive computation. Static gates (local reference `../outputs/benchleaf-3v3-r001/checks/static-gates/verification-run.json`, not included in this public snapshot) took about 24 seconds. | Measure engineering/setup, tool, iteration and reporting work separately before promising speedups. |
| PET capacitors add a stability question. | **Documented risk, not observed oscillation.** Engineering review (local reference `../outputs/benchleaf-3v3-r001/engineering/engineering-review.md`, not included in this public snapshot) explains the substitution and the limits of a 1 kHz ESR estimate. | Prefer supported component combinations for simple circuits; retain explicit verification obligations. |
| Final digital checks and fresh reproduction pass. | **Retained observed results.** Handover summary (local reference `../outputs/benchleaf-3v3-r001/checks/handover-summary.json`, not included in this public snapshot), DRC (local reference `../outputs/benchleaf-3v3-r001/checks/drc-final.json`, not included in this public snapshot), reproduction (local reference `../outputs/benchleaf-3v3-r001/checks/full-reproduction.json`, not included in this public snapshot). | Preserve R001 as a regression input. These results do not establish physical stability, temperature or fabrication yield. |

This planning pass inspected current source, retained task history and reports. It did not rerun the full software suite, route a board, operate a native GUI, collect model responses or make measurements. Previous test counts remain results tied to their recorded revisions.

## 2. Reconcile completed and unfinished work

| Earlier work | Current disposition | New destination |
| --- | --- | --- |
| A01–A06: persistence, coordinates, evidence, cleanup protection, confidentiality | Implemented; phase 0 record (local reference `implementation/phase-0-integrity.md`, not included in this public snapshot). | Preserve protections and regressions throughout; no blanket reimplementation. |
| A07–A09: frozen gates, regression triage, AI failure evidence | Implemented; phase 1 record (local reference `implementation/phase-1-verification.md`, not included in this public snapshot). | Phase 3 extends design-workflow timing/diagnostics. |
| A10–A12: supported path, export lineage, shared decisions | Implemented within recorded scope (local reference `implementation/phase-2-supported-path.md`, not included in this public snapshot); DR7 remains open. | Phases 1–4 complete ordinary usage and real proofs. |
| A13–A17: editor behavior/visuals/lifetime/redraw/lazy assets | Implemented locally; native accessibility/DPI and broader workload checks remain open. Broad CLI extraction was deferred after timing. | Phase 5 native qualification; Phase 3 measurement before optimization. |
| A18–A19: docs and repository ownership | Indexing/disposition implemented; no major migration justified. | Phase 6 maintains ownership and evaluates only specific removals. |
| A20–A22: held boards, hardware/firmware, research | Contracts/private replay prepared; measurements, board resumption and stronger research claims remain open. | Phases 4–7 with target-specific conditions. |
| IF0–IF6 | Scoped transaction mechanisms/proofs implemented; W10 qualification blocked. | Phase 1 normal-path adoption and general edit intent; Phase 4 craft/proofs. |
| W0–W9 | Major geometry/topology/fill/placement/escape/backend/repair foundations exist; historical hard-set/RT40 acceptance unresolved. | Phase 4 re-evaluates and fixes reproducible remaining classes. Do not assume every old defect persists. |
| W10 / DR7 / formal Phase 17 | Two-board attempts exist, accepted supported-path closure does not. DR0–DR6 and A10 enforcement are foundations. | Phase 4: two genuinely new, materially different supported-path proofs. |
| Formal Phase 18 | Neutral output implementation exists; per-board process, independent CAM and release obligations remain. | Phase 5 handover qualification; optional adapters/coupons in Phase 7. |
| Formal Phases 19–21 | Mechanical exchange, advanced analysis and correlation remain planned or target-dependent. | Phase 7; basic prototype measurement is earlier in Phase 5. |
| Formal Phases 0–16 / legacy product tracks | Preserve completed scopes and [migration mapping](roadmap-open-item-migration-2026-07-23.md). Broader circuit blocks/evidence/AI are not automatically complete or reopened. | Reuse necessary consumers in Phases 2–3; broader features require Phase 7 triggers. |
| User-owned snapshot automation | Earlier identity/access question remains unresolved and non-blocking. | External follow-up when identified; no automation created by this plan. |

R005 remains the accepted legacy proof, not a new-router test; R006 remains a separate visual/proxy pilot. W10 v14 remains package/visual rejected. Montenegro stays paused pending two-pin LED/process decisions, with its timer/watchdog redesign deferred. AeroSense remains unresolved. BenchLeaf R001 remains a manually routed, unbuilt prototype. See [current state](current-state.md) and qualification obligations (local reference `qualification-obligations.md`, not included in this public snapshot).

## 3. Execution order and completion gates

P0 protects design/evidence integrity. P1 delivers the ordinary two-layer workflow. P2 improves maintainability or closes conditional product/research gaps. These priorities do not imply a newly observed data-loss incident.

| Execution phase | Priority | Deliverable | Completion gate |
| --- | --- | --- | --- |
| 1. Direct iterative editing and controlled rebuilding | P0/P1, first | Supported saved-board edit path over existing transactions | Public-boundary edit matrix passes; unaffected objects survive; rebuild decisions are explicit. |
| 2. Early component and circuit checks | P1 | Exact package dependency closure and conservative reusable circuit choices | Incorrect/missing parts, pin maps, models and support conditions are identified before routing. |
| 3. Repeatable workflow and measured efficiency | P1 | Shared create/edit/check/export orchestration, resume and timing | New generation, local revision and resume need no custom orchestration code; unchanged work is not needlessly repeated. |
| 4. Routing craft and unfinished real proofs | P1 | Current failure register plus two new supported-path proofs | DR7 conditions pass with actual routing provenance, bounded edits and exact evidence. |
| 5. Native usability, handover and prototype qualification | P1, target-dependent | Native UI results, independent output checks and measured target record | Claims close only for exercised UI/export/unit configurations. |
| 6. Maintenance and research follow-through | P2 | Consolidated ownership, retention decisions and prospective research | Migrations replay; stronger claims have appropriate new evidence. |
| 7. Triggered advanced capabilities | P2/later | Board-driven MCAD, simulation, manufacturing and AI integrations | Pinned inputs/fixtures and required correlation precede stronger claims. |

Current software order: completed scoped Phase 1 and the scoped bounded-delivery proof → remaining Phase 2 slices → Phase 3 slices → Phase 4. Credit overlapping Phase 2/3 work only after its relevant checks pass, without repeating completed implementation. Native UI checks and documentation maintenance can proceed independently. Physical availability must not block unrelated software work or be fabricated to close a phase. Advanced work does not displace this sequence.

### Cross-phase priority B0 — prevent workflow bypasses

The user explicitly added bypass prevention when approving this roadmap. It applies to every phase, beginning with direct-edit adoption. The bypass in scope is skipping shared engineering, review, routing or release boundaries by calling a raw builder, regenerating through a project script, or supplying asserted success evidence. This is separate from electrical bypass/decoupling capacitors, which remain part of Phase 2 circuit checks.

**Confirmed evidence:** the earlier generator registry covered 23 public generator functions in `src/pcbsmith/kicad`; BenchLeaf's manual `tools/boards/benchleaf_r001.py:routed` path was outside that discovery pattern. Legacy `design-*` handlers also called operations directly. Existing downstream gates did not ensure those callers entered the ordinary workflow. See the [Phase 1 implementation record](implementation/roadmap-phase-1-iterative-edits.md).

| Item | Required change and verification | State / dependency |
| --- | --- | --- |
| B01 — ordinary entry points | Existing boards default to edits; generation requires an explicit source-bound rebuild decision. Legacy CLI design commands require explicit research opt-in. Negative tests must prove rejection before output creation. | Implemented for the shared generator, 15 legacy handlers and the frozen BenchLeaf recipe; broader direct-script migration remains open. |
| B02 — producer inventory | Inventory potential writers across source and tools, including aliases and direct native writes. New callers or changed recorded calls fail shared local/CI checks until explicitly classified and reviewed. | Implemented static inventory; its classifications are not acceptance evidence or a dynamic sandbox. |
| B03 — truthful transitions | Generate, edit, route, check, review, export and release must retain distinct statuses. Recompute the declared edit; check exact current inputs and live native results before working application. Preserve existing stronger publication/release checks. | Edit/rebuild boundaries implemented; Phase 3 must expose end-to-end stage events, skipped stages and intervention provenance. |
| B04 — bypass regression matrix | Test direct-builder calls, omitted stage inputs, stale/copy-edited receipts, weakened rules, out-of-envelope edits, hand-authored routing and misleading completion labels at each consuming boundary. Do not count a research result as a supported-path proof. | Initial edit/rebuild/CLI controls exercised. Carry existing release controls forward; complete cross-boundary matrix in Phases 3–4 and require it on both new DR7 proofs. |
| B05 — retire redundant escape routes | Replace per-board orchestration only after the shared path reproduces its needed capabilities. Freeze needed research recipes; archive/delete only with an evidenced replacement and preserved history. | Phase 3 orchestration, Phase 6 disposition. No bulk deletion is justified now. |

**Completion rule:** a new ordinary board and its revision must traverse the declared shared stages with preserved failures and independently checked outputs. Passing an inventory or adding `--research` does not satisfy this rule. Local Python can still write arbitrary files; preventing that absolutely would require execution/permission isolation beyond these workflow controls. Approval-reference strings document intent but do not authenticate a human identity. No agent should use a research exception to fulfill an ordinary production request.

## 4. Phase 1 — make local editing the normal revision path

### 1.1 Adopt existing transactions through a supported entry point

**Issue/evidence:** BenchLeaf rebuilt through its script. The CLI exposes iterative-fix-dry-run and component-review repair; [IF workflow](../src/pcbsmith/iterative_fixing_workflow.py) already supplies checkpoints, evidence closure and promotion.

**Change:** Provide one discoverable public edit operation using the existing diagnosis, envelope, placement, routing and semantic transaction owners. Accept an identified finding or an explicit requested edit. Start with text/reference moves and model-only corrections, then component moves/rotations and selected trace/via changes. Use retained native files; a live KiCad IPC connection is not a prerequisite.

Explicit user edits must satisfy the requested result and all hard engineering constraints. Optimization repairs retain their appropriate improvement objective. A valid requested move must not fail only because the helper's generic topology score stays equal; changing this policy must not permit clearance, pin-map or functional-topology regressions.

**Affected components:** [iterative_fixing_ir](../src/pcbsmith/iterative_fixing_ir.py), [iterative_fixing_workflow](../src/pcbsmith/iterative_fixing_workflow.py), [placement transaction](../src/pcbsmith/placement_repair_transaction.py), [local routing](../src/pcbsmith/local_routing_repair.py), [semantic transaction](../src/pcbsmith/semantic_repair_transaction.py), [production workflow](../src/pcbsmith/production_workflow.py), [CLI](../src/pcbsmith/cli.py), existing tests. Add a thin adapter, not a second state machine.

**Dependencies/risks:** Reuse existing exact part/rule bindings. Unsupported edits stop with a reason. Some helpers check a limited property such as pose; the integrated acceptance boundary must protect all relevant object classes.

**Verify:** Real saved candidates accept silk, model, component and copper edits through the public API/CLI without editing a generator. Include a valid explicit move that does not improve the old optimization score, plus hard-constraint failure controls.

### 1.2 Preserve identity, source authority and recovery

An iterative edit is a delta to the existing native object model. KiCad may serialize the whole file when saving; that is not whole-board design regeneration. Compare source-file integrity and meaningful object changes separately from formatting.

The transaction must:

1. Bind project, schematic, PCB, libraries, rules and request hashes; retain an immutable predecessor.
2. Declare mutable stable IDs, attached endpoints, affected nets/regions, fixed objects and an expansion budget.
3. Patch an isolated candidate. Preserve unrelated IDs, poses, pad/net bindings, copper, mechanical features, markings and models.
4. Reconnect affected endpoints after movement; check neighboring clearances, return paths, zones, mating access and topology. Moving a part must not silently leave detached traces.
5. Compare actual changes with the envelope. Zone refill can affect a broad area; compute the real dependency closure and reject undeclared protected changes.
6. Run cheap affected checks during iteration and complete applicable exact checks before promotion.
7. Promote atomically against the expected source revision. Concurrent/manual source changes produce a conflict; rejected/interrupted attempts remain recoverable without a mixed project.
8. Record accepted edits as revisioned deltas/constraint updates linked to design intent. Later generator replay must preserve them or report a reconciliation conflict. An old script must not silently erase native edits.

**Reuse:** [routing_candidate_transaction](../src/pcbsmith/kicad/routing_candidate_transaction.py), [file transactions](../src/pcbsmith/operations/file_transaction.py), [local repair execution](../src/pcbsmith/local_repair_execution.py) and library-retention helpers. Add a minimal edit journal only where existing records cannot express intent synchronization; avoid an unrelated event-store architecture.

**Verify:** No-op, undo/restore, source conflict, save failure, interrupted promotion, stale evidence, undeclared mutation, unsupported native objects and generator-replay conflicts. Compare geometry/electrical meaning, not only names/counts. The predecessor stays byte-identical; unchanged candidate objects retain identity and semantics. Do not claim every native construct is supported without fixtures covering it.

### 1.3 Choose local edit, regional repair or rebuild explicitly

| Change / finding | Default action | Justified escalation |
| --- | --- | --- |
| Text position or model transform | Object edit; refresh affected visuals/assembly dependencies | Unresolved source/package identity returns upstream; it does not itself require rerouting. |
| Small component move/rotation | Neighborhood plus attached copper | Expand to selected nets/functional cluster after retained bounded failure. |
| Trace detour, open or clearance | Selected objects and region | Protect unrelated nets and same-net copper outside the envelope; expand only after a typed failure. |
| Part/footprint substitution | Verify pin/pad/MPN authority, then local geometry/net repair | Broad incompatible mapping or function may require partial circuit regeneration or rebuild; package changes are not automatically global. |
| Zone/fill/return repair | Responsible zone/region and actual connectivity closure | Plane-wide effects can require broader checks/repair without replacing placement. |
| Outline change | Recheck boundary/capacity; preserve compatible objects | Changed fixed interfaces or demonstrated global capacity failure may invalidate the layout. |
| Rules/profile/layer strategy/architecture change | Revalidate the affected design | Rebuild when the approved change invalidates local preservation or bounded attempts demonstrate global scope. |
| New board / no usable predecessor | Initial generation | Generation is not a failed local edit. |

A rebuild record must identify the requested/approved change, invalidated requirements, smallest feasible scope, attempts considered/exhausted, work that cannot survive and before/after comparison. Do not silently weaken rules, enlarge the board, change layers or substitute components to obtain a pass. Seek a user decision only for a genuine scope change or missing engineering choice. Exhausted compute time alone is not proof of physical infeasibility.

**Phase 1 exit — completed within the [documented supported scope](implementation/roadmap-phase-1-completion.md):** Exercise the edit matrix on fresh copies of BenchLeaf and existing repair fixtures, with zero unintended protected-object changes. Include bounded regional expansion and justified rebuild controls. Preserve R001 and do not rerun accepted R005 for this purpose. Retain operation/check/render timings. Unit tests alone do not close adoption.

## 5. Phase 2 — identify component and circuit problems before layout

### 2.1 Resolve the complete component package early

**Issue:** R001 encountered late footprint recognition and model failures. A symbol, footprint and attractive render do not alone establish purchased-part compatibility.

**Change:** Reuse selection/readiness/library/model owners for one pre-placement input-closure report: exact MPN or procurement envelope; symbol-pin to physical-pad mapping; body/lead/pitch/drill dimensions; footprint identity; local/external library dependencies; model availability/transform and exact/proxy classification; and support parts. Freeze versions/hashes and resolve selected assets only.

Replace board-script edits to a process-local footprint whitelist with the shared exact KiCad footprint resolver where supported. Detect missing models early and give an explicit blocked/proxy disposition. Test nested project-local paths and reopened retained projects; copying only top-level .pretty folders is not a general dependency-closure strategy.

**Affected components:** [design_readiness](../src/pcbsmith/design_readiness.py), [production_generators](../src/pcbsmith/production_generators.py), [library](../src/pcbsmith/kicad/library.py), [project_dependencies](../src/pcbsmith/kicad/project_dependencies.py), [model_preflight](../src/pcbsmith/kicad/model_preflight.py), component-selection callers and tests.

**Dependencies/risks:** Phase 1 uses already-qualified bindings; substitutions with missing authority remain blocked until this work supplies it. Model availability must not be confused with exact mechanical qualification or license permission.

**Verify:** A correct package succeeds; missing footprint/model, wrong pin order, changed library bytes, missing nested dependency and inconsistent procurement dimensions fail early. A qualified substitution uses Phase 1 and preserves unrelated copper. Use real libraries/fresh copies, not only mock dictionaries.

### 2.2 Prefer simple, supported circuit choices

**Issue:** PET capacitors increased area and added a stability question to the simple LDO supply. This is an engineering tradeoff, not a measured failure.

**Change:** Reuse circuit-intelligence/readiness authorities to define a small set of source-bound patterns for functions actually used: initially supply, connector and indicator circuits. Declare operating ranges, support parts, tolerances, placement relationships, protection assumptions and outstanding measurements. Prefer regulator/capacitor combinations directly supported by manufacturer guidance when compatible with assembly needs. Novel substitutions require a reason and verification obligation.

Review a prospective BenchLeaf capacitor revision before fabrication; preserve R001 and its evidence. Do not treat one-frequency ESR estimates or DRC as a stability proof. Keep header procurement envelopes explicit until ordered variants are selected.

**Dependencies/risks:** A small reusable pattern is justified; a new general synthesis engine is not. A capacitor change can affect geometry and copper, so apply the local/region decision. Reuse existing deterministic engineering calculations rather than duplicate them in templates.

**Verify/exit:** A source-backed supply pattern produces complete support/power/package obligations; missing bypass, wrong pin mapping/polarity and unsupported ratings are rejected. Every selected part in the next proof boards has reviewed input closure before routing. Unknown behavior remains an explicit test obligation.

## 6. Phase 3 — simplify execution and measure improvement

### 3.1 One create/edit/check/export workflow

**Issue:** R001 needed three custom scripts and manual coordination of checks, renders and reports. Workflow repair was mixed into board construction, obscuring routine turnaround.

**Change:** Put a shared runner over production/IF owners, with initial-generation, local-edit and rebuild modes, exact checkpoint resume, and standard manifests/BOM/POS/drawings/notes generated from canonical data. Separate circuit declarations from reusable operations. Wrap historical scripts for compatibility; do not rewrite all of them or erase their proof provenance.

Treat file/image tool failures as environment diagnostics with bounded fallback; record them separately from electrical/routing failures. Reuse ordinary work budgets and cancellation handling. This does not resume the deferred Montenegro timer/watchdog redesign.

**Affected components:** production_workflow, production_generators, iterative_fixing_workflow, execution/verification, review/visual_package, manufacturing_lineage/release, CLI and BenchLeaf helpers. Extract demonstrated repeated operations into existing owners with thin adapters.

**Dependencies/risks:** Phases 1–2 supply edit semantics and input closure. Preserve compatibility and source identities; a shared runner must not become a new way to bypass required review or release checks.

**Verify:** A documented command/API sequence creates a board, applies a local revision, resumes after interruption and exports a correctly classified package without modifying orchestration Python. Faults at every stage leave coherent retained evidence and no misleading completed package.

### 3.2 Reuse valid work and measure the full process

**Change:** Record end-to-end and stage times; attempts, changed/protected objects, route expansions, resource use where available, reused work and invalidation reasons. Separate first setup/development from routine warm revisions. Record assistant/user interaction time separately where observable; unknown time stays unknown.

Reuse iteration evidence only when its declared dependency hashes, tool versions, rules, native configuration and render profile are unchanged. A text edit can avoid route search but still affects markings/views. A model change affects mechanical/visual evidence. Pin/part/power changes invalidate dependent electrical and physical assumptions. Never relabel cached output as a fresh check against different board bytes.

Before promotion, execute complete applicable native ERC/DRC/parity/connectivity and other required final checks against the exact saved candidate. Material changes invalidate relevant prior measurements. Selective quick checks improve iteration speed; they do not weaken final acceptance.

**Benchmark/exit:** Freeze a compact same-hardware/tool edit set: no-op, silk, model, component, local route and rebuild. Use at least five warm repetitions per supported case and report a cold run separately. Compare median, slowest observed run, correctness, changed-object counts and full-check cost against the regeneration method. Count generator/router invocations to prove eligible edits avoid rebuilding. Demonstrate stale-cache rejection and interruption recovery. Use these observations to refine measured completion targets. The newer bounded-delivery policy already sets provisional complexity-based stop limits; a stop limit is not a completion guarantee.

## 7. Phase 4 — close routing and supported-path proof gaps

### 4.1 Reconcile and repair real failure classes

**Issue/evidence:** W0–W10 (local reference `phase17-two-layer-routing-remediation-plan-2026-08-19.md`, not included in this public snapshot) retains incomplete hard-set/RT40 acceptance. W10 transactions worked while package/layout craft was rejected. Passing unit tests did not close board-level findings.

**Change:** Build a current failure register, keeping historical and newly evaluated revisions distinct. Classify each issue as reproduced, already corrected with evidence, unresolved authority or out-of-scope. Repair reproduced escape/capacity/power-return/fill/thermal/detour/access/marking problems through the smallest appropriate transaction. Protect geometry across repository and external routing backends. Internal router success cannot replace independent native readback and final checks.

**Affected components:** Placement/capacity/escape owners, backend adapters, local_routing_repair, routing_candidate_transaction, saved_board_routing_evidence, whole_board_qualification_adapter and review. Reuse W/IF mechanisms. The old 99 findings and 0/8 hard-set result are historical until re-evaluated, not asserted current results.

**Dependencies/risks:** Phases 1–3 must provide a usable edit workflow and trustworthy timing/evidence. Resolve package/semantic authority before repairing copper. Never count an unexamined or waived issue as fixed.

**Verify:** Representative failure-class controls with unchanged rules and retained rejected attempts, followed by affected regressions. Run the full frozen corpus when shared routing/geometry changes justify it, not for every text edit. Report layout craft, preservation and connection completion separately.

### 4.2 Finish DR7 with two materially different new boards

Current evidence update: September 26 adjudication (local reference `implementation/ui-dr7-qualification-2026-09-26.md`, not included in this public snapshot) accepts QuadLeaf as the first prospective CAD workflow proof after recorded recovery and preserves its failed original timing target. TriggerLeaf (local reference `briefs/triggerleaf-dr7-2026-09-26.md`, not included in this public snapshot) is the frozen second functional brief; preparation and execution remain pending. The requirements below are unchanged.

Freeze two unseen briefs before using them as acceptance cases. After the ordinary workflow works, candidate categories are a modest controller/sensor interface and a materially different multi-channel or shaped/interface-constrained board. Final circuits require exact parts/process/evidence. Switching-power complexity is unnecessary merely to make a demonstration look difficult.

Each proof must traverse intake/requirements → part/support checks → approved predesign → saved schematic/placement → required review → supported actual routing → bounded correction where needed → exact final checks → standard handover and release evaluation. Retain all interventions. Manually authored/replaced routing cannot count as autonomous/backend-generated success. Engineering decisions remain allowed; the declared workflow and gates must not be bypassed.

Require:

- Complete circuit/pin/package/power/support and source-to-board identity, not matching filenames alone.
- Actual backend receipts, frozen configuration, bounded failures and native saved/readback verification.
- At least one demonstrated local revision per proof, preserving unrelated objects and running meaningful affected checks.
- Required subject/final-package review against current artifacts; missing or failed obligations block.
- Reproducible source plus accepted deltas, no hidden board-script replacement, and measured workflow cost.
- Correct release evaluation: genuine unresolved physical/manufacturing conditions remain explicitly blocked without fabricated signoff.

BenchLeaf is useful for edit/visual regression but its manually authored routing is not one of these new proofs. W10 attempts are not retrospectively counted as accepted. DR7 default-path closure needs both successful workflow proofs; physical fabrication approval is separate. If an applicable engineering gate is unresolved, the proof is incomplete rather than a reason to weaken the gate.

**Phase 4 exit:** Both new proofs pass their software/design-workflow gates and the failure register accounts for every migrated outstanding class. External/physical holds remain explicit. This is the principal unfinished formal Phase 17 acceptance milestone.

## 8. Phase 5 — qualify usability, handover and real prototypes

### 5.1 Native UI and export acceptance

Current evidence update: the September 26 qualification (local reference `implementation/ui-dr7-qualification-2026-09-26.md`, not included in this public snapshot) passes ten actual headless browser interaction checks on each exact BeaconLeaf/DuoFilter iBOM. Intentional DNP-part semantics and native desktop/mixed-DPI/accessibility remain open; headless browser checks do not close those scopes.

**Issue:** Earlier editor/offscreen behavior improved, but native Windows focus, mixed-monitor DPI and screen-reader behavior remain unverified. BenchLeaf iBOM interactions and independent CAM were not exercised. Editor record (local reference `implementation/phase-3-editor.md`, not included in this public snapshot), BenchLeaf handover (local reference `../outputs/benchleaf-3v3-r001/README.md`, not included in this public snapshot).

**Change:** Exercise real keyboard/mouse/focus, Save/Discard/Cancel, small windows, mixed DPI, themes and screen-reader labels. Provide minimal edit-impact/before-after/result presentation in the existing workflow; a full new PCB editor or multi-model application is not required. Fix observed failures only.

Independently compare Gerber/drill sides, origins, units, outlines and hole treatment against the board. Exercise iBOM selection, sides, pin-1 and populated/DNP behavior against actual BOM/POS data. Define process-specific 1:1/mirroring instructions once the process is known. Distinguish illustrative 3D finish from actual mask/legend exports. Reuse Phase 18 exporters/receipts.

**Affected components/dependencies:** Existing Qt UI, production/edit presentation, manufacturing exporters and integration tests; native interactive environment and an independent CAM reader. The software path should not wait for a fabrication order.

**Verify:** Retained native task results/captures and independent CAM dimensions with input/output identities. HTML generation alone cannot close interaction tests. A documented GUI/CAM tool is not assumed available until exercised.

### 5.2 Close physical questions on a selected unit

Choose exact revision, ordered/as-built parts, process, operating contract and tester before measurement. BenchLeaf can be the first modest target after component review. Use the worksheet (local reference `../outputs/benchleaf-3v3-r001/assembly/bring-up.md`, not included in this public snapshot): assembly/polarity/short checks, current-limited startup, load sweep, startup/load-step scope captures, warm-run temperatures and etch/drill coupon. Final limits must match actual parts and intended load; a worksheet is not a test result.

An MCU board also needs a bound firmware/toolchain/binary, pin-interface contract, boot/reset states, bus/error handling, flashing/recovery and HIL where applicable. BenchLeaf itself has no firmware. Measurements require an assembled unit and instruments; unrelated software work proceeds while they are unavailable.

W10 needs exact package/pin authority and local craft fixes before resumption. AeroSense needs current geometry/model/review binding. Protocol Analyzer R002 remains conditional on USB orientation, compaction and placement correction. Montenegro stays paused until its brief/process is deliberately resumed. Preserve R005/R006 history; do not introduce high-energy ESC/mains work through an ordinary prototype task.

**Phase 5 exit:** Native UX and manufacturing checks close for their tested scopes. Each measured unit has raw data, conditions, instrument identity and disposition. Unavailable units/tests remain specifically open; no blanket hardware-qualified claim.

## 9. Phase 6 — keep the repository and research maintainable

### 6.1 Consolidate usage and retire only proven duplication

**Issue/change:** Roadmap layers and board-specific helpers can create competing entry points. Keep this document as the approved execution order, current-state as live status and implementation records as historical results. Link completed work rather than repeat conflicting completion claims. Put create/edit/check/export instructions at maintained entry points. Distinguish generated, routed, digitally checked, reviewed, simulated, bench-tested and released capabilities.

Extract reusable BenchLeaf operations only after the shared path passes; preserve a thin compatibility wrapper or frozen source sufficient to reproduce R001. Part/coordinate declarations can remain board data. Broad CLI splitting, directory renaming and repository-wide cleanup are not justified by appearance.

**Dependencies/risks:** Follow [retention policy](repository-retention.md). Every actual migration/removal needs consumers/citations, an exact old/new hash map, compatibility/relocation handling, cold setup/import/native/research replay checks and a reviewable disposition list. Protect .venv and its .tmp/uv-python base. Keep unpublished papers, failed attempts, logs and local-only designs private. Backups do not replace dependency analysis.

**Affected components/verify:** Maintained docs, shared owners extracted in Phase 3, packaging/retention tools and appropriate compatibility tests. Each operation has one documented owner; historical reproduction still works; each removal has evidence of dispensability. No migration is a valid outcome. Remote CI counts as verified only if actually run with authorized access; local green checks are not remote CI evidence.

### 6.2 Preserve evidence and plan stronger research prospectively

**Issue:** The claim matrix (local reference `research-claim-matrix.md`, not included in this public snapshot) identifies empirical gaps that software fixes do not close. Private hash/policy/session replay is complete within scope; it is not fresh model collection, feedback-efficacy evidence or measured PCB function.

**Change:** Preserve Paper 3's 44 complete first-candidate acceptances, four exclusions and zero feedback exposure. Stronger repair/feedback claims need harder pilot tasks, appropriate independent baselines, a frozen edit allowance and new collection with actual feedback opportunity. Paper 4 needs authored/adjudicated, frozen tasks, numeric conventions and exclusions before primary collection. Papers 5/6 remain prospective. Keep regression/prototype cases separate from held-out research tasks.

Future collection records exposed model/provider identity, actual usage/latency/cost, context isolation, retries and failures; unknown identities stay unknown. Compare initial generation and iterative repair separately. Paid collection, external uploads and publication require their own explicit scope and are not started by this roadmap.

**Affected components/dependencies:** Evaluation/collection and paper tooling, prospective protocols and claim matrix; settled study design, independent review and any required authorized service access. Frozen raw results remain unchanged.

**Exit:** Every stronger claim has the prospective data it requires. Additional unit tests or deterministic replay cannot substitute for empirical evidence. Report research collection as an independent track rather than block ordinary board-engineering improvements on it.

## 10. Phase 7 — later, triggered capabilities

| Retained capability | Trigger and bounded next work | Acceptance requirement |
| --- | --- | --- |
| MCAD / FreeCAD / StepUp / formal Phase 19 | Selected enclosure/assembly; pin versions and characterize native KiCad exchange first. Carry connector access and source-bound mechanical envelopes into placement/review. | Verified units/transforms, holes/cutouts, tolerances, collisions and repeat exchange; renders are not metrology. |
| Optional KiCad IPC / future constraint solvers | Demonstrated interaction need after file-based edits work. Check current API/version support at implementation time. | Isolated deterministic/unsupported/conflict/recovery fixtures; no unverified upgrade dependency for Phases 1–4. |
| Simulation / formal Phase 20 | Exact models and a board-specific question. Extend existing batch ngspice; add loss/thermal/protection/PDN/high-speed adapters only when triggered. | Source/license/pin-map/tool hashes, known fixtures, corners, limits and retained failures; solver disagreements visible. |
| Correlation / formal Phase 21 | Prediction tied to a selected unit and operating envelope. | Raw measurement/uncertainty/residuals; separate calibration and validation; material changes invalidate prior qualification. |
| Optional manufacturer/panel/impedance features | Actual selected process requiring the feature; reuse Phase 18. | Real geometry and independent output checks; a coupon declaration is not a physical coupon. |
| Broader evidence and circuit-block coverage | Repeated unmet needs from real boards; provider terms/access/provenance where applicable. | Exact selected-part coverage and working consumers, rather than catalog-size targets. |
| Multi-model application, broader autonomy and product tracks | Separately chosen product/study scope after ordinary-board closure. | Defined roles, isolation, costs, evaluations, recovery and useful end-to-end tests. |
| Four or more copper layers | Deferred to 2027 under current scope; deliberately resume before implementation. | New stack-up/return/fabrication/routing evidence; two-layer success is insufficient. |

These are retained requirements with explicit triggers, not permission to start every integration. External inputs are settled when their work is selected. The corresponding older Phase 19–21 technical detail remains in [routing-placement-plan](routing-placement-plan.md).

## 11. Reporting and overall completion

At each implemented phase boundary, write one concise report: actual files changed, evidence/commands, targeted and native checks, measured timing, failures, remaining uncertainty and proposed migrations/removals. Update this roadmap and current-state without rewriting earlier evidence. Test changed behavior; do not create tests for documentation-only edits or run the full suite after every cosmetic board adjustment.

Near-term success means a new ordinary two-layer board and its local revision use the supported workflow without bespoke orchestration; unaffected accepted work survives; component problems surface early; real routing proofs pass; and runtime/release status are measured and truthful. Physical, UI, research and advanced-feature completion applies only to scopes actually exercised.

No calendar or speedup promise precedes the Phase 3 baseline. This planning update changes documentation only; it does not implement source/board fixes, alter research results, install dependencies, create automations, order fabrication or publish material.
