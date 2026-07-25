# PCBSmith current state

Status date: 2026-07-24

This is the volatile status authority. Stable engineering method belongs in
`CLAUDE.md`; detailed history belongs in dated or archived documents; execution
order belongs in `docs/routing-placement-plan.md`.

## Roadmap numbering

- The active roadmap now has exactly 22 formal phases numbered 0 through 21.
- Historical technical aliases `R1`-`R7` are formal Phases 1-7 while retaining
  their aliases in code, tests, and dated evidence.
- Phase 8 is the accepted R006 3D asset-onboarding pilot.
- Phase 9 is the thermometer postmortem and workflow-requirements closure.
- Phase 16 completed workflow-authority consolidation and froze the migration
  contracts. Phase 17 is now the active production-workflow closure and
  default-path proof. Manufacturing/
  assembly, MCAD/FreeCAD, advanced simulation, and correlated validation/
  release work are Phases 18-21 respectively.
- The item-by-item scheduling authority is
  `docs/roadmap-open-item-migration-2026-07-23.md`.

## Accepted project outcome

- The thermometer project is complete and accepted as a proof-of-concept.
- R005 is the routed electrical board: 63 netlisted components, 53 routed nets,
  zero unrouted connections, passing machine and reader ERC, reader-netlist
  equality, ngspice checks, virtual/design checks, KiCad DRC, repeated-save,
  deterministic-copper, and recorded visual-review evidence.
- R005 used the legacy router. Its success is not R2/R3 negotiated-capacity
  evidence and does not prove generic production/default adoption.
- R006 changes only 3D metadata and retains identical copper. Its SHT31 and OLED
  assets are visualization proxies, not exact procurement or enclosure-fit
  evidence.
- The bounded `outputs/thermometer-production-r005/` and
  `outputs/thermometer-3d-model-test-r006/` directories are explicit exceptions
  to the generated-output ignore rule so the accepted project-generated PCB,
  manifests, reports, and review images can survive a fresh checkout. They
  contain no book/standard PDFs or third-party 3D model files.
- The user explicitly retired the planned thermometer rerun on 2026-07-20.
  Generality will be evaluated on a future unseen project.

## Routing-omission correction

- The system now records objective saved-board routing state and refuses to
  treat placement copper views or ratsnest lines as a routed result.
- Retro-Pad 3x3 R001 is an exact-DRC-clean routed candidate with 643 segments,
  112 vias, and 48/48 copper-carrier nets.
- Retro-Pad R003 is an exact-DRC-clean routed candidate with 496 segments,
  93 vias, and 36/36 copper-carrier nets.
- R003 routing required deterministic Type-C and ISP fanout, exact completed-net
  checkpoints, selective rip-up, cutout-aware obstacles, stable domain ordering,
  and relocating the back-side ISP header beside the MCU.
- Their exact-hash final review packages exist. This is not yet release
  qualification: complete artifact inspection, typed read-back/netlist
  evidence, and repository-wide generator migration remain open. R003's top 3D
  image is retained as attention-required because KiCad misframed the camera.

## Review, simulation, and check-closure housekeeping

- The 2026-07-24 external-review and local audit is recorded in
  `docs/housekeeping-schematic-review-simulation-check-closure-2026-07-24.md`.
- Pinscope was audited at commit
  `b26ad3509f4a19878fb7050aad3da9eacba8d914`. PCBSmith and Pinscope are
  AGPL-compatible. The user selected independent PCBSmith-native
  implementation of the useful methods rather than direct source copying.
- Exact-package pin evidence, deterministic per-IC neighborhoods, derived
  review obligations, evidence-query budgets, exact coverage closure, and
  replay-bound component-review manifests are implemented. Ten focused tests
  and Ruff pass. These are internal generator-validation components, not a
  separate assistant workflow. Automatic transactional invocation, retained
  traces, bounded neighbor evidence retrieval, and repair-loop integration
  remain open.
- The detailed comparison and the classified user-supplied schematic/PCB
  conventions are in
  `docs/pinscope-method-audit-and-review-convention-integration-2026-07-24.md`.
- A green repository test suite does not prove that one project's applicable
  checks ran. Phase 17 now explicitly requires a project-wide
  applicability-to-execution manifest with exact input binding and evaluated-
  object coverage.
- The audit found and corrected one silent coverage case: a declared
  trace-current check with no routed segments now reports that capacity was not
  evaluated instead of listing the check with no finding.
- ngspice remains the canonical automated simulation backend. LTspice is
  scheduled only as an optional, process-isolated ADI-focused cross-check after
  model provenance and compatibility records exist.
- Functional multi-sheet schematic review output is scheduled from the same
  canonical connectivity authority; a manually maintained duplicate schematic
  is prohibited.
- Four-layer implementation remains deferred. The immediate sequence is Phase
  17 execution closure, two-layer current/return authority, then structured
  simulation.

## Generic capability boundary

- R2-R3 provide accepted bounded negotiated-routing, shaped-capacity, guidance,
  exchange, and summary authorities.
- R4 provides accepted bounded bus declaration through exact checked neutral
  layout handoff.
- R5 provides accepted bounded placement authority, live reduced-stem evidence,
  and an isolated production-derived `/PWLED` micro-pilot.
- R6 provides accepted bounded semantic/process evaluators.
- These authorities are not yet a universal or default end-to-end board path.
  Their next integration proof must use a new user-selected project rather than
  thermometer-specific hard-coding.

## Evidence and source status

- Copyrighted books, paid standards, and non-redistributable source files remain
  local and gitignored.
- The original July synthesis reconciles 31 sources.
- The local extraction manifest registers 41 documents after the July 18 intake.
- The additional registration includes official Sensirion and USB 2.0 sources
  plus newly supplied IPC/IEC documents. Pinned/extracted is not equivalent to
  distilled, reconciled, implemented, or production-exercised.
- Commit only permitted bibliographic metadata, hashes, short locators,
  paraphrased derived facts, applicability, and implementation status.

## Repository and verification checkpoint

- Active branch: `codex/circuit-intelligence-slice`.
- A daily user-owned task is intended to preserve work during the week. Its
  commits must be treated as snapshots unless their recorded verification gates
  pass; snapshot preservation is not acceptance.
- Collection audit on 2026-07-20 after the first Phase 13 slice: 2,597 tests
  across 207 test files, generated from 1,885 authored test functions.
- Production source inventory on 2026-07-20 after the Phase 13 slice: 246 Python files under
  `src/pcbsmith`.
- Canonical development and verification use the project Python 3.12 venv.
  Python 3.11 remains within package metadata and Ruff's syntax floor; the
  earlier 233-file/2,562-test baseline compiled and collected in an isolated
  Python 3.11
  environment. That is compatibility evidence, not a completed second full
  regression. Python 3.14 remains outside the declared supported range.
- The last retained complete R005 report records 2,546 passed and 16 optional
  skips, Ruff passing, and strict mypy passing across 233 source files.
- The fresh Phase 10 full regression ran under Python 3.12 on 2026-07-20 with
  warnings treated as errors. It reached 100% in 471 seconds with one
  non-functional failure: Hypothesis reported slow input generation for
  `test_point_add_sub_inverse` after producing only two valid integer examples
  in 1.27 seconds. The test then passed in isolation and passed again with the
  exact reported seed. This checkpoint is therefore **attention required**, not
  green; the timing health check remains enabled and the incident is Phase 12
  test-health evidence.
- The later Phase 11/12 standard verification checkpoint is green: lock, Ruff,
  strict mypy over all 239 source files, and all 2,590 collected tests passed
  with warnings treated as errors. Pytest completed in 512 seconds with a
  2,381,729,792-byte peak job-memory reading under the enforced 4 GiB ceiling.
  The Hypothesis incident did not recur, but one clean run does not establish
  its root cause or close the later test-health audit.
- The final Phase 13 standard verification checkpoint is green: lock and Ruff
  passed, strict mypy passed across all 246 production source files, and pytest
  completed all 2,597 collected cases (2,580 passed, 17 intentional skips) with
  warnings treated as errors. Pytest took 746.375 seconds and reached a
  2,391,515,136-byte peak job-memory reading under the enforced 4 GiB ceiling.
  The retained run is `.pcbsmith/verification/phase13-final-2026-07-20/`.
- The generic Phase 11 foundation now provides controlled HTTPS/cache source
  intake, rights-aware KiCad asset installation, 3D-model preflight,
  deterministic PNG outline/silkscreen tracing, and a standardized hashed
  2D/3D review package whose generation cannot self-approve inspection.
- Phase 14 has hardened the source-intake boundary without widening electrical
  rule scope: bounded retry/backoff, final-attempt browser-compatible headers,
  final-redirect host revalidation, retrieval telemetry, distinct
  authentication failures, and entry-by-entry resumable catalog intake are
  implemented. The 18-entry advanced-research catalog parses through the live
  CLI; payload licensing and exact content identity remain fail-closed.
- Phase 14's first electrical promotion is now implemented in the existing R6
  decoupling-loop authority. Advisory thresholds cannot emit acceptance;
  sourced-hard PASS/FAIL requires complete applicability review plus
  revision-identified, hash-pinned, locator-verified evidence bound to the exact
  retained graph, paths, terminals, thresholds, and intended consumer. Missing,
  invalid, or stale authority returns UNVERIFIED. This is evaluator-level proof,
  not yet a production-board or cross-board validation claim.
- Phase 14 connector-to-ESD ordering is also implemented as a composition of
  the existing connector-zone and routed-copper authorities. It derives order
  from exact copper legs and physical-pad transitions rather than trusting a
  caller-supplied component tuple, requires each involved net's graph anchors
  to cover its complete netlist terminal inventory, and rejects undeclared
  parallel/bypass nodes. Hard results use the same revision, pinning, locator,
  applicability, reviewer, and exact-context gate as the decoupling slice. Its
  scope deliberately excludes ESD rating, clamp performance, EMC, and system
  immunity claims.
- Phase 14 oscillator evidence zones are promoted with exact source-context
  binding. Hard zone intrusion, forbidden-net-class, ground, stitch, separation,
  and capacitance rules now require matching policy claims, source revision,
  pinned/verified/applicable evidence, reviewer state, and a fingerprint over
  every retained declaration input. Explicit advisory intrusion zones report
  without blocking. The result continues to state that its object inventory is
  supplied-only, so whole-board extraction/completeness remains open rather
  than being hidden behind a PASS.
- Phase 14 switcher hot-loop membership is promoted inside the existing exact
  projected-area evaluator. Transitions now prove same-component ingress and
  egress physical pads and typed switching roles; every routed leg net must
  have complete graph-anchor coverage of its retained netlist terminals.
  Undeclared parallel/bypass nodes fail membership, while missing terminal
  inventory is UNVERIFIED. Hard membership and area share one revisioned,
  applicable, exact-context evidence binding.
- Phase 14 stack-up/reference continuity is promoted inside the existing
  return-adjacency authority. Every declaration now carries either a verified,
  evidence-bound two-layer context or an explicit unknown context. Verified
  order, adjacent signal/reference layer pairs, and permitted reference nets
  gate exact containment, hard thresholds, and transition-stitch acceptance;
  unknown stack-up can produce advisory guidance only. Dielectric/material
  properties, controlled impedance, multilayer behavior, and SI signoff remain
  outside this evaluator.
- Phase 14 now has an operational project-engineering gate. A reviewed,
  snapshot-bound component and feature inventory determines applicability for
  all five promoted rule families. The gate consumes their real replay-valid
  result objects, requires the exact declaration set, rejects foreign-board or
  undeclared results, and leaves all axes unresolved when inventory is
  incomplete. Its CLI writes one replay-bound completion artifact.
- Exact-MPN discovery now covers datasheet, errata, hardware guide, package
  drawing, reference design, simulation model, symbol, footprint, and 3D-model
  roles. It supports deterministic API/export catalogs, an adapter for the
  existing Nexar-compatible datasheet provider, safe source-intake retrieval,
  and exact installed-asset binding. Required documents must be validated in
  cache; required CAD must be installed. Live multi-role provider breadth and
  credentials/terms remain open.
- The generic Phase 12 repository-verification core now provides
  quick/standard/deep profiles, OS-enforced memory ceilings, wall-time limits,
  heartbeats, typed termination, complete-gate checkpoints, and one
  orchestrator reusing the existing lock/Ruff/mypy/pytest/golden gates. A
  generic algorithm-budget ledger exists but is not yet bound to board engines.
- The roadmap audit found that board workflow integration did not match those
  library-level claims: Retro-Pad bypassed the execution runner, did not create
  post-placement review evidence, and left mixed-generation artifacts. The
  generic work-budget ledger is not consumed by routing algorithms, although
  routing engines retain their own typed budgets.
- Phase 13's first pre-design slice now provides a provenance-carrying brief,
  exact outline/footprint feasibility overlays, and hash-bound user approval.
  The literal Retro-Pad corner-hole conflict was resolved by an explicit,
  approved 120 x 48 mm amendment with inward symmetric mounting holes.
- Retro-Pad R002 now proves the first complete staged path: approved concept,
  separately rendered and visually accepted placement, routed KiCad schematic
  and PCB, clean ERC/DRC/design review, passing model preflight, 35 required
  final review artifacts, and an accepted final visual inspection. The routed
  result contains 457 segments and 78 vias. R001 remains failure evidence.
- The pilot also exposed one remaining reproducibility/performance issue: the
  router may reverse equivalent segment endpoint order across processes and is
  expensive enough that failed post-route assertions cost several minutes.
  Retro-Pad's aperture repair is now orientation-independent and the accepted
  verification run pinned `PYTHONHASHSEED=0`; repository-wide deterministic
  router ordering and resumable stage checkpoints remain open.

## Active numbered work

1. Phase 10 repository work is complete. The unidentified user-owned daily
   snapshot automation is an external, non-blocking follow-up.
2. Phase 11's foundation is complete; production-default review/evidence use is
   scheduled in Phase 17. Optional server storage remains a triggered product
   decision, not an implementation blocker.
3. Phase 12's execution core is complete; board-algorithm telemetry and default
   caller integration are scheduled in Phase 17.
   The initial 2,597-case stewardship audit is complete; timed runtime
   attribution, rule-to-caller mapping, and the non-repeating Hypothesis
   incident remain open.
4. Phase 13's first Retro-Pad intake-to-final proof is accepted in
   `outputs/retro-pad-r002/`. Generalize pre-route capacity evidence, make
   routing determinism/checkpointing repository-wide, add transactional output
   commits, and prove the format on a later materially different board.
   Its remaining generalization work is scheduled in Phase 17.
5. Phase 14's source-retrieval hardening, five-item narrow promotion slice,
   the first reviewed project context, automatic applicability gate, and exact-
   MPN discovery foundation are complete within their stated scopes. Next
   exercise the gate on a materially different production candidate and add
   only the context/provider gaps that board exposes; do not expand all 23
   families at once. BLDC ESC R002 is now the current candidate: it preserves
   R001's source-bound schematic and exact-footprint four-layer placement, and
   adds a common isolated heatsink/TIM/support envelope, paired installed/hidden
   4K review views, and exported-GLB alignment readback. It remains unrouted,
   uses non-selected mechanical envelopes, and is pending user mechanical
   placement approval. It does not yet count as a routed five-family gate
   exercise, thermal proof, or current-rating proof.
   Phase 16 owns the remaining shared context and promotion contracts; Phase 17
   owns default-path population and cross-board proof; advanced analysis is
   Phase 20.
6. Phase 15's workflow-deviation policy, multi-physics system decomposition,
   14-source official intake, shared profile/manifest conformance authority,
   canonical R002 review repair, typed operating-scenario matrix, exact-source
   fact register, first loss/stress-ledger slice, deterministic point-input
   steady, transient, and coupled point thermal solvers, Phase-U thermal
   topology, typed cooling-assembly gate, sourced cooling-candidate register,
   minimum-bus gate-drive applicability gate, gate-charge capacity screen, and
   dead-time authority are complete. A five-option gate-supply decision now
   prefers a native-bus DRV8334 redesign while retaining `not_selected`; the
   exact screened candidate is now `DRV8334RGZR`. A complete proposed 49-pad
   migration map and nine functional migration groups are retained, together
   with hash-pinned compatible KiCad footprint and STEP geometry candidates.
   This closes exact-orderable and initial pin-accounting uncertainty, but not
   land/paste, placement/routing, firmware, quantitative protection,
   sensing, timing, transient, or validation obligations. The migration remains
   `conditional_candidate` and `not_selected`; the 12 V and 15 V separate-VM
   options remain conditional alternatives. DRV8334 bootstrap sizing now has a
   394.69 nF per-phase effective minimum, but remains `indeterminate` until a
   selected capacitor's bias/tolerance/temperature/aging lower bound is retained.
   All ten mandatory DRV8334 support capacitors are now explicit, but their
   exact MPNs/footprints are unselected and three applied-voltage bounds remain
   unresolved, so candidate placement is blocked rather than guessed. A typed
   protection foundation now evaluates nine event requirements against eight
   declared paths. None is released: detector settings, tolerance, response
   latency, safe-state action, independence, and residual energy remain open;
   no battery fault interrupter or reverse-polarity path is declared. The exact
   7KPD26A TVS source is automatically cached and hash-pinned. Its 26 V
   standoff provides only 0.8 V physical headroom above 25.2 V, and the 42.1 V
   clamp point is conditional on 166 A and a non-repetitive 10/1000 us pulse,
   so surge coordination remains `indeterminate`.
   R002 retains ten startup/normal/peak/
   fault/shutdown/cooling scenarios and eighteen loss entries. Phase-shunt
   I-squared-R is computed as 0.4455-0.4545 W at the 30 A prototype assumption,
   1.782-1.818 W at 60 A, and 4.95-5.05 W at 100 A. Phase-U MOSFET-pair
   conduction also retains a `validation_required` typical-curve/duty screening
   interval of 1.254-1.320 W, 5.016-5.280 W, and 13.933-14.667 W respectively;
   it cannot satisfy release coverage and is conditional on its 10 V VGS test
   condition. At the requested 9 V minimum bus, the retained DRV8353 topology
   guarantees only 5.5 V high-side VGS, below the MOSFET's lowest 6 V RDS(on)
   condition; gate-drive status is `inadequate`. Current semantics, environment,
   retained simultaneous-switch PWM membership, IDRIVE/dead-time configuration,
   transition timing,
   switching/dead-time losses, routed-path parasitics, faults, and thermal
   boundaries fail closed as unresolved. The exact board hash is bound to the
   cooling profile. Henkel A2000, Boyd 78045, and Delta AUB0405VD-00 are
   retained as candidates only; clamp hardware remains uncovered and no
   candidate satisfies exact selection. The TIM, sink, clamp, isolation, and
   air mover remain geometry proxies or unselected. The canonical
   visual package is conformant but `attention_required` for six crowded
   back-side text artifacts. The current Phase-U solve is correctly
   `indeterminate`; the 100 A/10 s Foster model is also `indeterminate` without
   ambient, total loss, and a reviewed/correlated Zth fit. Phase 20 owns the
   bounded electrical losses, physical TIM/contact/heatsink/board/ambient
   inputs, and determinate coupled solve; Phase 21 owns correlation. The present
   R002 model is `indeterminate` rather than substituting missing values. No
   current model establishes heatsink adequacy, clamp pressure, airflow
   performance, isolation, lifetime, or 30/60/100 A capability.
7. Phase 16 contract/consolidation scope is complete. It reconciled duplicate
   authorities, froze the workflow state machine and shared project context,
   normalized stable identities and applicability contracts, assigned
   test/check ownership, closed the Hypothesis incident, and published the
   compatibility contract consumed by Phase 17. Its canonical registry has 26
   active owners and three deprecated one-off authorities; the 15-record
   capability map covers every
   Phase 1-15. The full warnings-as-errors checkpoint passed all 2,763 cases
   (2,746 passed, 17 intentional skips) in 788.832 seconds. Phase 16 does not
   establish normal production caller adoption.
8. Phase 17 is now the highest-priority active phase. Its core contracts are
   implemented: exact-span/no-invention prompt examination; all ten project
   contexts; typed spatial anchors and conflict consequences; bounded
   usable-region/neck feasibility; saved-design concept-drift comparison;
   immutable generation transactions and rollback; automatic placement review;
   transactional inspection; exact reviewed-board routing entry; repository-
   deterministic route-domain order and resumable exact-accepted prefixes;
   execution-profile bindings, native ledgers, heartbeats, and telemetry; and
   typed triggered diagnostic views. Registered 3D-model transforms can now
   fail preflight when shifted from their expected alignment. The routing gate
   also requires a complete, ready, same-layout engineering-applicability
   result, and the native A* production adapter consumes operative profile
   limits with pass telemetry and checkpoint heartbeats. Retained,
   independently reconstructible R2/R4/R5 artifacts and the six-category
   failure corpus now exist under `.pcbsmith/verification/phase17/`; live
   KiCad 10.0.3 R2/R4/R5 gates pass. The focused checkpoint is 84 tests green;
   repository-wide Ruff and strict mypy over 284 source files pass. The frozen
   full suite collected 2,799 tests: 2,781 passed, 18 intentional skips, zero
   failures/errors in 647.047 seconds. Its stewardship audit counts 2,069
   authored functions and 93 name-matched production checks, preventing the
   collected-case count from being misread as 2,799 independent rules.
   The 2026-07-25 closure slice replaced final-release booleans with exact
   producer/version/input-bound verification records, made the
   applicability-to-execution manifest mandatory at routed release, and made
   production placement plus every emitted review render consume operative
   native budgets. Typed user review conventions now distinguish release,
   conditional electrical/layout, and presentation obligations; dormant or
   presentation advice cannot become a universal blocker. Remaining Phase 17
   work is automatic per-component review invocation/recovery, legacy generator migration,
   board-triggered R6/default-caller execution, Protocol Analyzer correction,
   and two materially different prompt-to-final boards including one unseen
   after implementation freezes and human review of both packages.
   Connected schematic review is now implemented and production-callable: one
   atomic manifest binds explicit root/per-sheet SVG/PDF exports, a complete
   project PDF, raw and canonical whole-project ERC/netlist hashes, the exact
   root schematic, and KiCad version. A three-page fixture and live KiCad
   10.0.3 Retro-Pad export pass.
   A controlled edge-interface slice is also implemented for components that
   must be clicked, plugged, or accessed at an edge. New containment waivers
   require replay-bound geometry that separately proves retained support and
   pad containment, exact selected-edge contact, and bounded useful overhang.
   The authority is tied to the exact layout/component/source geometry and is
   rejected after layout movement. Automatic extraction from supplier CAD,
   3D enclosure/mating-path proof, and production placement-candidate use
   remain open.
9. Phase 18 is active manufacturing and assembly output authority. Typed
   fabrication/stack-up/IPC-2152 profiles, full current-path coverage,
   saved-board manufacturing identities, ten-category DFM/DFT evidence,
   content-recognized atomic neutral packages, and human/fabricator/assembler
   release-language gates are implemented. KiCad 10.0.3 neutral exports and
   pinned InteractiveHtmlBom 2.11.2 ran successfully on the regular Retro-Pad
   3x3 and irregular Retro-Pad R003 candidates. KiKit 1.8.0 generated both
   first panels, but KiCad panel DRC rejected them with 19 and 231 findings;
   panelization and cross-board package proof remain open rather than being
   promoted through exclusions. Optional manufacturer adapters remain dormant
   until a manufacturer is selected.
10. Phase 19 is MCAD/mechanical authority: native STEP baselines, KiCad
    StepUp/FreeCAD, exact mechanical envelopes, collision/accessibility checks,
    deterministic round trips, and optional `kicad-python` inspection. KiCad
    11's developing FreeCAD `planegcs`-based geometric solver is now a
    version-gated Phase 19 evaluation target for outlines, hole patterns, and
    mechanical datums; it will not replace PCBSmith's typed constraints or
    electrical and release authorities.
11. Phase 20 is context-triggered advanced analysis: complete loss/thermal/
    protection authority, PDN/SI/power transients, EMC/reliability adapters, and
    structured ngspice with optional advanced model frontends.
12. Phase 21 is correlated validation and release qualification: measurement
    plans, uncertainty, raw-data/model identity, calibration-versus-validation,
    cross-board failure corpus, claim vocabulary, and named human approval.

KiCad 11's native PCB diff/merge support is also recorded as a non-blocking
Phase 17 watchpoint. After a stable, pinned command-line interface exists, it
may become an independent CAD-aware change-review and Git merge adapter. It
must remain subordinate to exact hashes, semantic identities, transactions,
read-back, netlist equivalence, DRC, routing coverage, and review gates.

Before paper drafting, the publication plan now requires a repository-wide
milestone review and evidence freeze. That review will separate implementation
from production invocation, cross-board proof, human inspection, and release
qualification; index claim evidence and failures; audit check-count semantics;
and freeze paper-specific experiment protocols. Papers 1 and 2 do not need to
wait for Phases 19-21 once their own evidence is frozen.

## Authority order

When claims disagree, use this order:

1. current code plus retained condition-matched verification evidence;
2. this dated current-state record;
3. the active completion ledger and roadmap;
4. current rule/source authority documents for their scoped questions;
5. stable methodology in `CLAUDE.md` and `docs/lessons-and-pitfalls.md`;
6. dated audits and postmortems for historical evidence;
7. archived or explicitly historical handoffs/plans for context only.

A checked phase does not override contradictory evidence. New capabilities use
new sequential phases; a later factual defect receives a dated erratum and
reopens only the invalidated scope.
