# Layout-craft rebuild plan (2026-07-11)

The user's directive after the thermometer board stalled: rebuild trace
and placement craft from researched rules — bus routing, component
compatibility, dual-side placement — "properly, not haphazardly."
Every phase below cites the book notes in `docs/reference/books/`
(rules carry THRESHOLD/WHY/WHERE/MACHINE FORM/APPLICABILITY there);
nothing gets encoded without its applicability range. Execute phases
in order; each ends with the standard gates (ruff, mypy, pytest,
golden) and a commit.

> **Research reconciliation (2026-07-14):**
> `docs/routing-placement-research-update-2026-07-12.md` is the evidence memo;
> the canonical implementation order is folded directly into this plan as
> R1-R7. There is no competing order. Negotiated congestion precedes shaped-
> corridor capacity, and both precede bus/lane semantics. Leader-plus-offset is
> only a local realization technique after capacity and lane allocation succeed.
> **Tooling backlog amendment (2026-07-14):**
> The open-source KiCad/ngspice integrations identified in the July tooling
> review are recorded after R7. They do not displace the active R1-R7
> routing and placement work unless a phase explicitly calls for an evaluation.

## Phase 0 — finish the knowledge base — **COMPLETE 2026-07-12**

Done: all nine sources distilled; 72-rule spot-verification campaign
(5 corrections applied, 1 false mismatch overturned by dimensional
analysis); CONSOLIDATED.md written with the six-docket resolutions;
source-wishlist.md ranks the next acquisitions. Honest residuals:
IPC-7351 is the 2005 original (three OCR-ambiguous exception cells
deferred to a 7351B copy); the sensitive-victim spacing number
assumes a back-side pour - the no-pour penalty needs a field-solver
or measurement; johnson has 5 remaining OCR-uncertain thresholds
outside the verified sample.

- Distill `johnson-hsdd` (446 OCR'd pages) and `ipc-7351` (85 pages)
  from `.book-cache/` with the same agent brief as the other seven
  (see `docs/reference/books/README.md` protocol). Johnson: crosstalk,
  terminations, layer strategy; IPC-7351: courtyard classes — audit
  our courtyard margins against the standard's density levels.
- Write `docs/reference/books/CONSOLIDATED.md`: one table of every
  machine-encodable rule across all nine sources, deduplicated, with
  contradictions resolved EXPLICITLY (e.g. Ott same-value decap arrays
  vs decade-pair lore; Ott 10 MHz 2-layer cap vs our 50 MHz class;
  Bogatin "proximity is weak, loop area is first-order" vs app-note
  "as close as possible"). This table feeds ai-rule-suggestions.md
  entries for user promotion.

### Phase 0 addendum — sources still to obtain (ask the user)

Confirmed gaps the current nine sources cannot close, in priority
order (the user can obtain books/documents given author + title):
1. **IPC-2152** (Standard for Determining Current Carrying Capacity
   in Printed Board Design) — 2221B explicitly defers current sizing
   to it; our formula is the older 2221A fit. Highest-value single
   document.
2. **IPC-2222A** (Sectional Design Standard for Rigid Organic Printed
   Boards) — PTH aspect-ratio limits and rigid-board specifics that
   2221B defers.
3. **Bruce Archambeault — "PCB Design for Real-World EMI Control"** —
   measurement-driven EMC rules; closes gaps where Ott/Montrose give
   mechanisms without board-level numbers.
4. **Lee Ritchey — "Right the First Time" (vols 1-2)** — stackup and
   routing strategy from a working designer; strong on WHERE rules
   stop applying.
5. **Howard Johnson — "High-Speed Signal Propagation: Advanced Black
   Magic"** — only if we ever pass ~100 MHz; low priority.
6. **USB 2.0 specification** (usb.org, free) — normative eye/skew
   numbers instead of app-note relays.
7. **JLCPCB / PCBWay capability pages** (free, web) — the ACTUAL fab
   limits our boards face (min drill/annular/slot/silk); turn into a
   machine-readable fab profile the checks read instead of constants.
8. **Sensirion SHT3x "Design-In Guide" PDF** (free) — we cite it via
   web extraction; pin the original next to the datasheets.
9. **IEC 62368-1 creepage/clearance tables** (or a summary source) —
   the flyback's mains rules currently lean on IPC Table 6-1 plus
   folklore wording; the real safety standard is this one.

## Canonical active implementation order

Phase 0 and the R1 solder-mask exposure/selector/report-gate slice are complete.
The broader R1 authority items below remain individually tracked. R2.1, R2.2a,
R2.2b, R2.3a, and the R2.3b in-memory board-maze proof are complete. R2.4 is
partially complete through the separate compact serialized/read-back/live-KiCad
gate; the adversarial serialized board, corpus measurements, and caller/default
migration remain pending. R3.1's engine-neutral IR/quantity ledger, R3.2's
exact/simple KiCad corridor graph adapter, R3.3's exact typed board-cutout path,
R3.4's negotiated coarse allocator, R3.5's conservative pairwise-demand
derivation, R3.6's opt-in soft detailed-router guidance, R3.7's negotiated
fine/ordinary exchange seam, and R3.8's read-only placement summary are
implemented. The generic R4 path now extends through generated pigtails and
transition vias, physical-swap and cost-aware LCS planning, physical
realization, replay-bound routing, atomic exact checked commit, and a neutral
accepted-layout handoff. R5's generic chain and reduced capacity-two live
fixture are accepted; generic R6 authorities and the replay-bound R5/R6
integration envelope are also accepted. The current ordered work is the bounded
real-thermometer declaration/application path followed by R7 regression. The
persisted accepted artifact, default caller migration, complete thermometer
declarations, and routed full-board golden remain open. See
`circuit-intelligence-review-supplement-5-2026-07-17.md`. Each slice ends with
firing fixtures, deterministic-repeat tests, the standard gates, and a commit.

> **R1 solder-mask/exposure checkpoint (2026-07-15; this slice is complete):**
> The engine now has an exact, engine-neutral mask kernel for discs, capsules,
> oriented rectangles, rounded rectangles, convex polygons, and compound unions;
> concave polygons are rejected unless supplied as an explicit convex compound.
> Pad parsing losslessly retains mask layers, source anchors, local margins,
> round-rect/chamfer data, ratio clauses, and canonical custom-pad clauses. A
> typed front-side board-disc bridge preserves the existing 96-point KiCad bytes
> and stable UUID. `ViaSpec` carries per-side `inherit|tented|open` intent and
> serializes it as KiCad `none|yes|no` tenting.
>
> KiCad 10.0.3 behavior is pinned by the durable 88-file corpus (87 artifacts
> covered by the manifest, plus the manifest itself) under
> `docs/reference/fixtures/kicad-mask-parity-10.0.3/`; `hashes.sha256` covers
> every retained artifact except itself (manifest SHA-256
> `22B8B15D93D1E3472B7222E9A8FB55D7908D73DC5ABAB1BA69084C62A96BDF14`).
> Verified semantics are: board `pad_to_mask_clearance` supplies global expansion;
> a non-zero pad-local margin replaces it; pad-local zero inherits it; mask-layer
> membership is side-specific; and KiCad 10.0.3 rejects
> `solder_mask_margin_ratio`.
>
> The exact aperture collector drives profile-scoped
> `fab.solder_mask_web`, `fab.mask_aperture_merge`, and
> `fab.solder_mask_web_unverified` checks. Raw board/footprint mask graphics,
> custom/chamfered pad apertures, ratio clauses, missing effective expansion, and
> inherited via policy produce unsupported/unverified results rather than numeric
> passes. Stable outer-copper identities, source-derived roles, and per-side
> exposure from final apertures now drive ordinary pairwise role/mask-state
> selectors. Unknown selector scope emits
> `ordinary_pairwise_clearance_scope_unverified`; design reports record
> `outer_copper_exposure` and emit `fab.copper_exposure_unverified`.
> Unsupported apertures without a quantitative error contract poison the whole
> same side unless a copper item is already proven fully exposed; bounded
> approximations use their `maximum_error_mm` envelope. Exact
> custom/footprint-mask graphics remain open, and this does not change the
> separate safety/creepage gate.
>
> Focused R1 validation was 106 passed for the exposure/selector set and 26
> passed for the report/design-check set. The historical full authority run
> after R3.5 completed with all collected tests green in 195.4 seconds, ten intentional
> live/golden skips, and only the known pytest-cache permission warning; strict
> mypy is clean over 122 source files and focused Ruff is clean. Detailed design
> records are
> `docs/mask-exposure-integration-design-2026-07-15.md` and
> `docs/r2-negotiated-congestion-design-2026-07-15.md`. Exposure is implemented,
> and R2 is complete through the R2.3b in-memory maze proof; R2.4 is partially
> complete as described below.

### R1 - ordinary fabrication/electrical authority and geometry prerequisites

1. Add an ordinary `FabElectricalSpacingProfile` for non-safety PCB construction
   and manufacturability: fab minima, copper/mask exposure, stackup facts,
   trace-current assumptions, ordinary pairwise spacing, hole/drill capability,
   annular-ring producibility, residual laminate, and body/copper edge rules.
   Router legality, virtual DRC, design checks, calculators, fabrication notes,
   and KiCad project constraints consume it instead of copying constants.
2. Keep safety insulation separate in a full-context `InsulationProfile`:
   applicable standard/edition, working RMS and peak voltage, transient/impulse,
   insulation type, pollution degree, CTI/material group, altitude, coating,
   overvoltage category where applicable, creepage/clearance paths, and qualified
   review. **Never derive or approve safety spacing from a bare voltage lookup.**
   IPC-2221B Table 6-1 may inform ordinary conductor spacing; it does not replace
   IEC 62368-1 or applicable product-safety analysis.
3. Correct trace-current provenance: the present equation is the legacy
   IPC-2221A Figure 6-4 external fit; IPC-2221B defers to IPC-2152. Keep it only
   as a labeled interim. Do **not** add the old `k=0.024` internal branch; replace
   it only when pinned IPC-2152/profile data supports the replacement.
4. Rulebook section 10's wording correction is **COMPLETE 2026-07-14**: 6.4 mm
   is a conservative project minimum, not a universal IPC reinforced-insulation
   or pollution-degree mandate. Preserve `needs_human_review` until a complete
   `InsulationProfile` and qualified safety review exist.
5. Add ordinary-profile checks with deliberate violations: voltage/exposure-
   aware pairwise spacing; Table 9-1/9-2 land sizing and annular ring; body-to-
   edge 1.5 mm with declared connector/breakaway exceptions; residual laminate
   between adjacent hole edges >= 0.5 mm.
6. Preserve lossless geometry first: typed copper-item kind/exposure; drill
   width, height, and rotation for round/slotted PTH/NPTH; via drill geometry;
   exact front/back body/courtyard transforms; shaped-outline distance and
   containment. Never infer item type from labels or collapse slots to one
   scalar diameter.
7. Replace uncontrolled generated `uuid4()` values with stable IDs derived from
   canonical object identity and a versioned namespace. Add byte/hash-repeat
   fixtures for fixed topology, rules, toolchain, and seed.

### R2 - negotiated congestion core

**Status (2026-07-15):** R2.1 resource accounting, including arbitrary emitted-
segment raster claims, is complete. R2.2a synthetic graph negotiation and R2.2b
real-grid complete-net search are complete. R2.3a board orchestration, truthful
telemetry, transactional restoration, and exact-check callback separation are
complete. R2.3b proves the real in-memory board maze: both legacy permutations
fail, while negotiated routing reaches zero overuse in three passes (`4 -> 5 ->
0`) with 16,427 expansions and pinned pass fingerprints. The negotiated cluster
was 66 passed before the maze addition; the maze is 3 passed. Legacy `route_board` remains unchanged/default. R2.4a adds a separate compact
real two-resistor board whose deterministic serialized KiCad bytes have SHA-256
`e91a7464d702c821f6ac0bb659a30bd39ccecdbe52e79167164650ce907dc628`;
repository read-back and all non-route-field preservation are tested, and its
version-aware opt-in exact KiCad 10.0.3 DRC passed locally. This is not the
adversarial maze. A legal-geometry serialized adversarial board, measured
performance/quality corpus, and deliberate caller/default migration remain
pending; no superiority claim is justified.

Add layer-specific cell/edge occupancy, width-and-clearance resource halos,
present/history costs, complete-net rip-up, stable tie-breaking, fixed expansion
and pass budgets, stagnation detection, typed failure reasons, and telemetry.
Temporary sharing exists only in the search model: accepted copper has zero
overuse and passes exact checks. Do not add bus semantics until first- and
second-order congestion fixtures pass.

### R3 - shaped-corridor capacity planning

**Status:** R3.1 is implemented with 21 focused tests after the terminal-owner
extension: engine-neutral corridor IR, canonical identities/validation, and the
heterogeneous quantity ledger. R3.2 is also implemented with 14 focused tests:
the exact/simple KiCad adapter handles rectangular and concave outer outlines,
conservative full cells, terminal/layer ownership, orthogonal portals, center
via sites, fixed copper/holes/zones, profile-sensitive capacity, and explicit
unsupported raw graphics or target-net zones. The pre-R3.3 R3.1/R3.2
checkpoint was 35 passed. The empty-board graph/result fingerprints are respectively
`18792a2bded9dd69bc83f2bf7f270762696216904542c1e82d5be107e418f79a` and
`6b0b5bab0591a2bb76b07ae99e8c6db0965c4eb4ddd99f1e0dbb60b5a5bff392`.
R3.3 is now complete: `BoardLayout` has strictly validated canonical exact
cutout polygons; legal closed Edge.Cuts `gr_poly` serialization uses semantic
UUIDs; and cutouts exclude corridor cells on both copper layers and center-via
sites exactly. Empty-default board bytes remain unchanged. The exact segment-to-
cell predicate's asymmetric distance defect was corrected. Bounded approximation
remains deferred because no real two-sided uncertainty carrier exists. Validation
is 38 focused and 62 broader tests.

R3.4 is complete. The engine-neutral allocator builds complete deterministic
multi-terminal coarse trees, charges heterogeneous integer quantities against
portal and via-site capacity, and negotiates whole-demand transactional
replacements with present/history costs. It enforces forbidden/allowed/required
via policy and zero-work semantics, and reports typed geometry, unsupported,
terminal, capacity, expansion, pass, and stagnation failures. Per-demand attempt
telemetry, pass run-context fingerprints, expansion budgets, and canonical
allocation/pass/result fingerprints make the outcome reproducible. Literal
first-order and second-order capacity fixtures prove deterministic convergence,
including exact overuse sequences, expansion counts, rollback, and one-less-
budget failures. The historical R3.4 focused R3 authority set was 85 passed.

R3.5 is complete. R2 and R3 now share one canonical executable air-clearance-
domain builder. Corridor demand derivation applies a pairwise domain only when
both endpoints produce actual multi-terminal demands, takes the maximum of the
ordinary and every applicable clearance, and retains every applicable domain ID.
Absent, single-terminal, and same-side counterparts therefore do not inflate a
net. Mask/role selectors and component exemptions cannot narrow coarse un-emitted
copper; qualified air-clearance enters once, while creepage never enters this
Euclidean model. Exact `Decimal` ceiling replaces epsilon-biased float rounding,
preventing under-reservation at quantum boundaries.

The combined R2/R3.5 authority set is 104 passed, including 26/26 corridor-
planner tests. That historical full suite was green in 195.4 seconds with ten intentional
skips and only the known pytest-cache warning; strict mypy is clean over 122
source files and focused Ruff was clean.

R3.6 is complete. Versioned engine-neutral coarse guide/report artifacts and a
versioned KiCad grid projection map allocated cells plus selected portals and
via sites to transition-precise preferences. A separate non-negative guidance
cost steers R2 without changing its hard legality, heuristic, physical claims,
or pad-stub exemption. `RoutingRunResult` remains schema v2 and retains its
algorithmic zero-overuse meaning. The opt-in board wrapper reports `ABSENT`,
`PLAN_NOT_READY`, `INCOMPLETE_INPUT`, `INCOMPATIBLE`, or `APPLIED`; every
non-applied state falls back to ordinary unguided R2. It rebuilds the current
layout's corridor graph before applying a supplied plan, so stale guidance also
falls back as `INCOMPATIBLE`. Exact-check acceptance remains separate from R2
success.

The broader R2/R3 cluster was 122 passed before final strengthening. The focused
post-golden R3.6 set is 60 passed. The definitive post-R3.6 full suite is green
in 229 seconds with ten intentional skips and only the known pytest-cache
warning; strict mypy is clean over 124 source files. The real shaped U-board
integration golden pins 29 coarse and 4,876 detailed
expansions, five `F.Cu` segments, no vias, zero virtual-DRC/connectivity
findings, lower-bottleneck use, and stable graph/plan/guide/run fingerprints.
R3.7 is complete. Separate versioned exchange records preserve all earlier R3
fingerprints; synthetic fine-prefix alternatives are negotiated with ordinary
area demands, selected prefix claims are replaced transactionally in detailed
R2, and the final exchange wrapper applies compatible prefix plus soft-guide
inputs once or falls back fail-honestly as `PLAN_NOT_READY`/`INCOMPATIBLE`.
Algorithmic R2 success and exact-check acceptance remain separate. The pinned
two-pass exchange result fingerprint is
`fc6162c17f5ed9be569e2e36f4d642e62c41f6a12dc7c3e32fbf1eedc1cba499`.
A failed or pessimistic corridor exchange remains no proof of physical
unroutability.

R3.8 is complete as a read-only seam, not placement integration.
`CorridorPlanSummary` validates exact graph/demand/plan fingerprints and reports
geometry completeness/issues, readiness/failure, unresolved demands, work, and
guaranteed/committed/overflow channel and via quantities. It does not rewrite,
rank, or mutate the R5 placement search.

Add a shaped-outline-aware coarse capacity/portal graph. Compute per-layer lane
capacity for the active `FabElectricalSpacingProfile`, route net/bus demand over
it with negotiated costs, and guide exact routing through selected corridors.
Fine-pitch escape and area routing exchange capacity/order information instead
of freezing locally legal but globally harmful routes.

### R4 - ordered bus/lane routing

**Status (reconciled 2026-07-18):** the generic ordered-bus authority is
accepted through replay-bound physical realization, routing, exact checked
commit, and a read-only neutral `BoardLayout` handoff. The detailed historical
design remains in `r4-ordered-bus-design-2026-07-15.md`; later accepted slices
and their limitations are recorded in
`circuit-intelligence-review-supplement-5-2026-07-17.md`.

1. `BusGroup` declares boundary order, allowed reversal/swaps, layers, via
   policy, widths, and a **per-bus coupling/timing budget** derived from
   interface timing, driver edge rate, stackup/reference return, parallel-run
   length, and acceptable noise/skew. A shared bus or nominally same-cycle
   switching does not permit manufacturing-minimum spacing by itself.
2. Allocate a capacity-proven corridor and lanes, then realize followers and
   pigtails with the exact obstacle kernel. Leader-plus-offset is optional local
   geometry, not the global planner. Re-plan after collision; report individual
   fallback as degraded, never silent success.
3. Keep coherence, timing/length matching, and crosstalk separate. The current
   3W foreign-net floor, 9.1 mm sensitive-victim estimate, and any coherence
   percentage are **advisory calibration hypotheses**, not universal blockers.
   Promote a number only after declared applicability and field-solver,
   simulation, measurement, or interface-specific validation.
4. Pilot thermometer SEG groups and the SER/SRCLK/RCLK/OE trunk only after
   R2-R3 pass. If capacity is insufficient, couple placement to its routability
   certificate or change the outline; do not resume manual placement iteration.

Implemented boundaries: R4.0 provides versioned bus declarations, evidence-
aware hard/advisory budgets, capacity certificates, and a fail-closed freshness/
ownership/reference handshake. R4.1 schema v2 allocates deterministic semantic
lanes with exact declared permutations, whole reversals, bounded certified
adjacent swaps, source/tap/sink activation intervals, and certified semantic
layer transitions with fixed state budgets. Its straight fixture pins result
fingerprint `3417223856291e6ce0ff43939468d84d18f222070bc94ff5383b57a261c359e1`
and allocation fingerprint
`34190f2212eedabeae24186cd6a855e55e20585712e7c8a04c3f0c5f27eb4366`.
R4.2a realizes only exact certified trunk centerlines and reconstructs R2
ordinary/pairwise claims; it emits no pigtails, transition vias, search, board
mutation, or acceptance verdict. R4.2b atomically replaces a complete bus route
bundle in the occupancy ledger/route map and restores the exact prior state on
late failure or exception; visible overuse is telemetry, not acceptance.

Implemented later slices include generated pigtail search, transition-via
geometry, connected trunk/pigtail/via composition, group/ordinary negotiated
orchestration, physical-swap candidates and transaction bridges, bounded
cost-aware LCS planning, exact physical realization, and exact checked board
commit. Still open are a production/default migration, thermometer-specific
BusGroup/boundary/order application, and persisted saved/read-back consumption
of the accepted neutral layout. The generic handoff itself claims no saved or
rendered KiCad artifact.

### R5 - placement API fidelity and routability surrogates

**Status (reconciled 2026-07-18):** generic probe, legalization, candidate,
surrogate, Pareto/detail, exact, compatibility, shaped serialization, measured
corpus, manifest, and acceptance authorities are accepted. The reduced
capacity-two stem passes condition-matched live KiCad save/read-back/DRC and
live dual-drawing reader/ERC; its routing-only v2 policy truthfully marks
simulation not applicable. Separately, an isolated production-derived R17/D17
`/PWLED` crop now accepts exact vendored R0603/LED0805 geometry, one reviewed
R17 -0.5 mm `LEGAL_EXACT` move, and an offline route. Its zero-overuse R3 plan
uses 56 cells, 82 portals, and 202 expansions. Conservative bounded roundrect
issues make exact guidance `INCOMPATIBLE`; the explicitly authorized ordinary-
R2 fallback succeeds in 271 expansions with five F.Cu segments and no vias.
Offline virtual DRC/design checks, serialization isolation, deterministic replay,
and tamper rejection pass. Exact boundaries are graph 120 cells/82 portals
versus one-less 119/81, R3 planning 49 versus 48 expansions, and R2 271 versus
270. A separate opt-in KiCad 10 gate passes exact read-back, byte-identical
repeated save, and clean DRC with zero findings; the offline wrapper remains
`kicad_live_checked=False`. This remains an isolated micro-pilot, not full-
template/fixed-neighbor preservation, equivalence, a persisted production
artifact, or a superiority claim.

Preserve shaped outlines, zones, graphics, front/back transforms, fine-pitch
and net-order declarations, bus groups, profiles, and every router budget through
placement probes. Add exact body/courtyard legalization, then screen with net-
separation margin, crossing/order conflicts, HPWL as a weak secondary term,
portal overflow, and pin escape alignment. Route a deterministic Pareto subset.
Each candidate records scores, capacity, conflicts, overuse, unresolved nets,
route metrics, and exact rejection reason.

### R6 - semantic compatibility and process-scoped dual-side guidance

**Status (reconciled 2026-07-18):** the generic source-bound sensor, antenna,
routed-copper, decoupling/hot-loop, switch-node, oscillator, connector,
return-adjacency, assembly-retention, neighbor-overhang, and R5/R6 integration
authorities are accepted within the limitations in supplement 5. No real
thermometer candidate has supplied the complete declaration/evidence set or
entered every applicable evaluator. Source-approved antenna exceptions,
condition-matched RF campaigns, and real thermometer semantic evidence remain
open.

1. Add declared thermal/sensor zones, antenna/feed geometry, routed decoupling-
   loop quality, oscillator keepouts, switching hot-loop area, connector zoning,
   and return-adjacency metrics to the R5 candidate model.
2. Sensor moats remain candidacy, not universal geometry. Slot width, web
   thickness, tabs, copper removal, and thin-trace entry come from the selected
   fab/assembly profile plus pinned sensor guidance, then require thermal and
   humidity validation in the built enclosure. A convenient 1.0 mm router
   diameter is not a Sensirion requirement.
3. Dual-side retention is process scoped. Record mass and wetted perimeter, but
   treat the SAC305/QFN surface-tension estimate as an advisory for a declared
   inverted second-reflow process, including paste, finish, package, oven
   profile, orientation, handling, and assembler capability. It is not a
   universal hard gate. Heavy parts become hard constraints only when the
   selected process and qualified assembler require them; otherwise emit review
   findings. Neighbor-overhang budgets remain package/class specific.

### R7 - thermometer r002 and authority regression

**Status (2026-07-18): IN PROGRESS, isolated offline execution only.** The
production-derived R17/D17 `/PWLED` micro-pilot completes its reviewed
placement, R3 planning, explicitly authorized unguided R2 fallback, offline
aggregate, serialization, replay, tamper, exact boundary, and separate opt-in
live KiCad save/read-back/clean-DRC gates. The live result remains external to
the offline wrapper. It does not preserve the full 64-placement template or
fixed neighbors, establish circuit equivalence, run reader/simulation gates,
prove readiness or superiority, persist a production board, migrate defaults,
or complete R7.

The final combined-tree gate is green: 2,560 tests were collected across 198
files, the default offline suite exited successfully in 843.6 seconds with its
intentional opt-in skips, whole-tree Ruff passed, strict mypy passed all 232
production files, and the independent `/PWLED` live KiCad 10 gate passed again.
Repository regression and handoff reconciliation are therefore complete; the
four full-board R7 tasks below remain open.

1. Rotate/replace U1 so its antenna faces the bulb edge and apply exact module-
   specific overhang/copper-cutout geometry; keep enclosure clearance and final
   throughput/range validation separate.
2. Select moat/thin-trace/copper-removal geometry through R6's chosen fab and
   sensor-validation profile. If inputs are not pinned, emit an advisory and do
   not claim validated thermal isolation.
3. Route SEG/control groups through R2-R4 and choose placement through R5-R6,
   never hand iteration.
4. Add the thermometer to the live golden suite only after ERC, reader equality,
   simulation, zero-overuse routing, virtual/semantic checks, KiCad DRC,
   deterministic-repeat checks, and visual review complete. The command and fast
   tests exist; a routed golden case does not.

## Post-R7 open-source tooling backlog (2026-07-14)
Keep KiCad files, `kicad-cli` DRC, and PCBSmith's deterministic checks as the
authorities. Plugins and external tools may produce or transform artifacts,
but their output must be revalidated before PCBSmith presents it as complete.

**Repository status (checked 2026-07-18):** KiKit, InteractiveHtmlBom,
`kicad-python`, KiCad StepUp/FreeCAD, Qucs-S, and OpenVAF are not installed,
version-pinned, or evaluated by this repository. The structured ngspice batch
adapters exist, but the proposed sweep/Monte-Carlo harness does not. No ngspice
shared-library runtime is present in the bundled `Spice64` tree. Freerouting has
one bunny DSN/SES experiment and a KiCad prepare/import helper, but no pinned
jar, production runner, or measured golden-board corpus.

### Priority A - adopt or evaluate first

1. **KiCad 10 native Multi-Channel / Repeat Layout** - evaluate during the
   Phase 2 repeated-bus pilot. Determine whether equivalent LED/channel blocks
   can reuse a proven placement and route without weakening net identity,
   provenance, or post-copy DRC. This is built into KiCad 10, not a plugin.
2. **KiKit CLI** - add reproducible, version-pinned panelization and
   manufacturing-package generation after single-board fabrication outputs are
   stable. Cover odd outlines, mouse bites, V-cuts, fiducials, Gerbers, drill
   files, BOM, and position files with regression fixtures. Prefer the CLI over
   GUI automation.
3. **InteractiveHtmlBom** - generate a self-contained assembly/review artifact
   in the standard output bundle. Verify front/back placement, DNP handling,
   BOM grouping, custom fields, and optional track/net rendering against the
   canonical KiCad board.
4. **Structured ngspice verification harness** - extend the existing batch
   runner with `.measure` assertions, parameter/corner sweeps, Monte Carlo runs,
   machine-readable vector/result capture, deterministic seeds where supported,
   and explicit threshold failures. Preserve the exact netlist, models,
   ngspice version, command, and result hashes.
5. **Official `kicad-python` IPC API prototype** - build a small interactive
   PCBSmith companion for inspection, selection/highlighting, and guided repair.
   KiCad 10 requires a running GUI, so this must not replace direct file
   generation or `kicad-cli`; reassess headless API use when KiCad 11 is adopted.

### Priority B - integrate when the corresponding capability is needed

6. **ngspice shared-library API (`ngspice.dll` / libngspice)** - prototype a
   process-isolated worker that receives callbacks and vectors without parsing
   console text. Adopt only if it is more reliable than the batch runner on
   Windows; retain batch mode as a fallback and regression oracle.
7. **KiCad StepUp / FreeCAD** - test the current release against KiCad 10 for
   enclosure fit, component/board collision checks, connector accessibility,
   board-edge exchange, and STEP output. Do not make it a dependency until
   KiCad 10 compatibility and deterministic exports are proven.
8. **Manufacturer-specific fabrication adapters** - evaluate
   `kicad-jlcpcb-tools` first for JLCPCB BOM/CPL generation and part mapping.
   Keep it optional: canonical Gerber, drill, BOM, and position outputs remain
   manufacturer-neutral, and every adapter gets golden rotation/side fixtures.
9. **Qucs-S** - keep as an optional developer frontend for manually debugging
   difficult ngspice/Xyce models, plots, RF networks, and sweeps. Do not place it
   in the production authority path.

### Priority C - advanced simulation, later

10. **XSPICE** - evaluate its behavioral and event-driven mixed-signal code
    models when PCBSmith supports switch-mode controls or mixed analog/digital
    systems that ordinary SPICE primitives cannot model cleanly.
11. **OpenVAF-Reloaded + ngspice OSDI** - add only when modern Verilog-A
    compact device models are required. Pin the model-source hash, model license,
    compiler version, OSDI ABI, operating system/architecture, and ngspice
    version in every cache/provenance key. Treat VA-Models entries as
    individually licensed rather than assuming a repository-wide license.

### Autorouter position

12. **Keep Freerouting as the preferred external candidate/oracle, not a
    production default or authority.** First add a version-pinned runner,
    deterministic DSN/SES exchange, post-import cleanup, and `kicad-cli` DRC,
    then measure it on the golden-board corpus. Any alternative must be compared
    using completion rate, DRC violations, via count, routed length, runtime,
    reproducibility, and manual repair burden before adoption.

## Standing constraints for whoever executes this

- The pipeline stays 100% deterministic — no LLM in the loop.
- Every rule encoded must carry its applicability range in the
  rulebook; judgment-call rules go through ai-rule-suggestions.md.
- Run the golden suite before any commit touching kicad/ or
  calculators/ — it has caught every regression.
- The books are NOT to be re-read wholesale: the notes in
  docs/reference/books/ are the durable extraction; consult the
  .book-cache text (sha-pinned) only to verify a specific locator.
