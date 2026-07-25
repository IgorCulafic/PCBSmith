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
> **3D asset onboarding amendment (2026-07-18):**
> Missing or unresolved KiCad 3D models are now a first-class review-output
> concern. After R7, add the Track 6.5 acquisition/validation pipeline from
> `docs/hardening-and-generalization-plan.md`: resolve exact package and module
> models, fetch only selected assets, retain provenance/license/checksum data,
> bind deterministic transforms, and verify rendered scale/orientation. A
> missing required model must produce an explicit review finding instead of
> being silently omitted. Design-specific pilots may proceed earlier when a
> missing model prevents useful mechanical review; the thermometer R006
> SHT31/OLED experiment is the first such pilot.
> **Thermometer production postmortem amendment (2026-07-18):**
> Before another production-sized shaped board, complete the P0 workflow items
> in `docs/thermometer-production-postmortem-2026-07-18.md`: always-persisted
> pre-route PCB/renders, one automatic verification command, cutout-aware shared
> legality, bounded progressive routing telemetry, single-source mechanical
> authority with dependency invalidation, 3D asset preflight/resolution, and a
> pinned fast-before-expensive verification sequence. These are execution
> prerequisites, not a replacement for the accepted R1-R7 technical order.
> **Evidence-utilization amendment (2026-07-18):**
> Broad source acquisition is no longer a proxy for progress. Until the
> existing R2-R7 authorities run through the production/default path, prefer
> short source-to-production vertical slices and exact part/module/fab/assembler
> evidence. Apply the decision gate, revision policy, status ladder, and session
> checklist in `docs/evidence-acquisition-and-utilization-guide.md`. The dated
> local audit is `docs/reference/books/LOCAL-SOURCE-INVENTORY-2026-07-18.md`.
> **Roadmap-governance correction (2026-07-20):** Completed phase scopes are
> frozen. New capabilities are appended under the next sequential phase rather
> than inserted into Phase 0 or another completed phase. A later factual error
> receives a dated erratum and may reopen only the invalidated scope; preserving
> a checkbox never outranks contradictory evidence. The earlier `P0-V` and
> `P0-E` labels were planning mistakes. Their useful requirements are retained
> as design records and scheduled under Phases 11 and 12 below. The postmortem's
> `P0`/`P1` headings are priority classes, not roadmap phase identifiers.

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

- [x] Distill `johnson-hsdd` (446 OCR'd pages) and `ipc-7351` (85 pages)
  from `.book-cache/` with the same agent brief as the other seven
  (see `docs/reference/books/README.md` protocol). Johnson: crosstalk,
  terminations, layer strategy; IPC-7351: courtyard classes — audit
  our courtyard margins against the standard's density levels.
- [x] Write `docs/reference/books/CONSOLIDATED.md`: one table of every
  machine-encodable rule across all nine sources, deduplicated, with
  contradictions resolved EXPLICITLY (e.g. Ott same-value decap arrays
  vs decade-pair lore; Ott 10 MHz 2-layer cap vs our 50 MHz class;
  Bogatin "proximity is weak, loop area is first-order" vs app-note
  "as close as possible"). This table feeds ai-rule-suggestions.md
  entries for user promotion.

### Historical post-Phase-0 source audit - not additional Phase 0 work

The 2026-07-18 filesystem/hash/title-page audit supersedes the old assumption
that IPC-7352 was missing. The full May 2023 document was already pinned and
synthesized; the second copy is byte-identical. Full IEC 60664-1:2020 is also
present twice. Newly verified full additions are IPC-2222 original (1998) and
IEC 62368-1 Edition 2.0 (2014). They are usable for proof-of-concept mechanisms
and historical comparison, but their revision must remain visible and they do
not establish current contractual or safety compliance.

The following list records the 2026-07-18 intake decisions. New acquisition and
utilization work is scheduled under Phase 11 rather than added to completed
Phase 0:

1. **Sensirion SHT/STS design-in guide (acquired 2026-07-18):** the official
   Version 2 (March 2024) is pinned and extracted. Distill it into thermometer
   sensor evidence while keeping moat/isolation geometry board-, housing-, fab-,
   and validation-specific.
2. **Selected fabricator and assembler evidence:** capture versioned
   trace/space, drill, annular-ring, mask, milling, stackup, assembly, stencil,
   and package limits in machine-readable profiles.
3. **Exact selected-part/module packages and CAD:** current datasheets,
   mechanical drawings, recommended land patterns, errata, reference designs,
   and STEP/WRL assets before generic substitution.
4. **IPC-7093A (full revision acquired 2026-07-18):** the October 2020 revision
   is pinned and extracted. Distill the directly assembled SHT31/MPU6050
   DFN/QFN/BTC paste, voiding, exposed-pad, inspection, and thermal-via sections
   only when their production consumers are scheduled.
5. **Current IPC-2221/2222 and IPC-7525 material:** acquire when completing
   general fabrication or stencil authority. The full local IPC-2222 is the
   1998 original, IPC-2221C is preview-only, and the file labelled IPC-7525C TOC
   is mismatched content rather than a valid preview.
6. **Current applicable IEC/product standards:** acquire only when a board makes
   a corresponding safety/compliance claim. IEC 60664-1:2020 lacks AMD1:2025;
   local IEC 62368-1:2014 is an older product-standard edition.
7. **USB 2.0 signalling:** the official June 2025 USB-IF bundle is now pinned
   separately from USB Type-C 2.5. Extract only the base/ECN material required
   by a declared USB 2.0 profile. Archambeault, Ritchey, and Johnson HSSP remain
   conditional gaps and are not the current integration bottleneck.
8. **IPC-2152:** the full August 2009 historical standard is now pinned. Use it
   for defined validation/model-comparison work with Brooks/Adam; do not promote
   it as a maintained current standard or universal single-equation authority.

Do not begin another broad source wave while high-priority material remains
stalled at `distilled` rather than `production_exercised`. Every new acquisition
must name its rule/profile/card/artifact consumer and acceptance fixture first.

## Canonical active implementation order

**Numbering normalization (2026-07-23):** The historical `R1`-`R7` labels are
retained as technical aliases because they appear in schemas, tests, and dated
reports. For roadmap sequencing they are now formal Phases 1-7. The accepted
R006 3D asset pilot is Phase 8, and the thermometer postmortem/workflow-
requirements closure is Phase 9. The roadmap therefore has exactly 22 formal
phases numbered 0 through 21.

Phase 0 and the Phase 1/R1 solder-mask exposure/selector/report-gate slice are
complete. Broader Phase 1 work is migrated to Phases 16/17. R2.1, R2.2a,
R2.2b, R2.3a, and the R2.3b in-memory board-maze proof are complete. R2.4 is
partially complete through the separate compact serialized/read-back/live-KiCad
gate; the adversarial serialized board, corpus measurements, and caller/default
migration are Phase 17. R3.1's engine-neutral IR/quantity ledger, R3.2's
exact/simple KiCad corridor graph adapter, R3.3's exact typed board-cutout path,
R3.4's negotiated coarse allocator, R3.5's conservative pairwise-demand
derivation, R3.6's opt-in soft detailed-router guidance, R3.7's negotiated
fine/ordinary exchange seam, and R3.8's read-only placement summary are
implemented. The generic R4 path now extends through generated pigtails and
transition vias, physical-swap and cost-aware LCS planning, physical
realization, replay-bound routing, atomic exact checked commit, and a neutral
accepted-layout handoff. R5's generic chain and reduced capacity-two live
fixture are accepted; generic R6 authorities and the replay-bound R5/R6
integration envelope are also accepted. The thermometer project then completed
through the routed R005 proof-of-concept and R006 3D visualization pilot. The
user accepted that project on 2026-07-18 and explicitly retired the planned
thermometer rerun on 2026-07-20. Generic production/default adoption remains a
project capability gap, but it must be tested on the next genuinely unseen
design rather than hard-coded back into the known thermometer. See
`circuit-intelligence-review-supplement-5-2026-07-17.md` for bounded generic
authority evidence and the thermometer postmortem for lessons.

## Audited completion ledger (2026-07-18)

This ledger is the quick status authority. A checked item means the stated,
bounded slice has repository evidence and passed its stated gates; it does not
promote a broader phase by implication. Dated historical checkpoints retain
their scope. Historical aliases are normalized as Phases 1-7; unfinished
default-path work is scheduled only once under Phase 17 or its later owner.

- [x] Phase 0: nine-source knowledge-base distillation, reconciliation, and
  spot-verification campaign.
- [x] Phase 1 (`R1`) bounded slice: solder-mask geometry, parsing, exposure classification,
  selector integration, report gates, and pinned KiCad 10.0.3 parity corpus.
- **Migrated (Phase 16/18):** Phase 1/R1's remaining stable-identity work is
  scheduled in Phase 16; fabrication/electrical profiles, insulation, IPC-2152
  replacement data, and remaining manufacturing geometry are Phase 18.
- [x] Phase 2 (`R2.1-R2.3b`): resource accounting, negotiated search/orchestration, and the
  in-memory adversarial board-maze proof.
- [x] Phase 2 (`R2.4a`): compact serialized/read-back/live-KiCad gate.
- **Migrated (Phase 17, P0):** Phase 2/R2.4 serialized adversarial fixture, measured
  corpus, and deliberate production/default caller migration.
- [x] Phase 3 (`R3.1-R3.8`): corridor IR and adapter, exact cutouts, coarse negotiation,
  clearance demand, detailed guidance, fine/ordinary exchange, and the
  read-only placement summary seam.
- [x] Phase 4 (`R4`) generic authority: declarations through physical realization,
  replay-bound routing, exact checked commit, and neutral layout handoff.
- **Migrated (Phase 17, P0):** Phase 4/R4 persisted saved/read-back consumption and
  deliberate caller/default migration on a future unseen design.
- [x] Phase 5 (`R5`) generic authority and reduced capacity-two live fixture, including the
  isolated R17/D17 `/PWLED` micro-pilot.
- **Migrated (Phase 17, P0):** Phase 5/R5 full-template/fixed-neighbor preservation,
  artifact persistence, equivalence, and comparative proof.
- [x] Phase 6 (`R6`) generic semantic authorities and the replay-bound R5/R6 integration
  envelope within their documented limitations.
- **Migrated (Phase 17, P0):** Phase 6/R6 complete design-specific evidence,
  declarations, and every applicable evaluator on a future unseen design.
- [x] Phase 7 (`R7`) thermometer electrical project: R005 is routed, persisted
  locally, deterministic, clean in KiCad DRC/ERC/parity, and visually reviewed.
- [x] Phase 8: R006 proves proxy SHT31/OLED 3D attachment and model-resolution
  evidence without copper change.
- [x] Phase 9: the production postmortem, standard review requirements, failure
  record, and no-rerun/governance decision are retained. Reusable review APIs
  were implemented later in Phase 11.
- [x] Phase 10 repository scope: continuity records and Python/environment
  normalization. The unidentified user-owned daily automation remains open.
- [x] Phase 11 foundation: evidence intake, asset/model handling, raster
  adapters, and standardized review-package APIs. Automatic use by every board
  workflow remains open.
- [x] Phase 12 repository execution core and initial test/check audit. Binding
  board algorithms and every project caller to it remains open.
- [x] Phase 13 first slice: structured normalization, feasibility overlays, and
  hash-bound concept approval gate. Capacity and transactional generation
  remain open.

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

## Phase 1 - ordinary fabrication/electrical authority and geometry prerequisites

Historical technical alias: `R1`.

**Status (normalized 2026-07-23): BOUNDED MASK/EXPOSURE SLICE COMPLETE.**
Stable-identity consolidation is Phase 16; remaining manufacturing, insulation,
and current/geometry authority is Phase 18.

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

## Phase 2 - negotiated congestion core

Historical technical alias: `R2`.

**Status (normalized 2026-07-23): BOUNDED GENERIC CORE COMPLETE.** R2.1 resource accounting, including arbitrary emitted-
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
adversarial maze. The legal-geometry serialized adversarial board, measured
performance/quality corpus, and deliberate caller/default migration are
scheduled in Phase 17; no superiority claim is justified.

Add layer-specific cell/edge occupancy, width-and-clearance resource halos,
present/history costs, complete-net rip-up, stable tie-breaking, fixed expansion
and pass budgets, stagnation detection, typed failure reasons, and telemetry.
Temporary sharing exists only in the search model: accepted copper has zero
overuse and passes exact checks. Do not add bus semantics until first- and
second-order congestion fixtures pass.

## Phase 3 - shaped-corridor capacity planning

Historical technical alias: `R3`.

**Status (normalized 2026-07-23): BOUNDED GENERIC AUTHORITY COMPLETE;
PRODUCTION-DEFAULT PROOF IS PHASE 16.** R3.1 is implemented with 21 focused tests after the terminal-owner
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

## Phase 4 - ordered bus/lane routing

Historical technical alias: `R4`.

**Status (normalized 2026-07-23): BOUNDED GENERIC AUTHORITY COMPLETE;
PRODUCTION ADOPTION IS PHASE 16.** The generic ordered-bus authority is accepted
through replay-bound physical realization, routing, exact checked commit, and a
read-only neutral `BoardLayout` handoff. The detailed historical
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
commit. Production/default migration and persisted saved/read-back consumption
of the accepted neutral layout are scheduled in Phase 17. The generic handoff
itself claims no saved or rendered KiCad artifact.

## Phase 5 - placement API fidelity and routability surrogates

Historical technical alias: `R5`.

**Status (normalized 2026-07-23): BOUNDED GENERIC AUTHORITY COMPLETE;
PRODUCTION ADOPTION IS PHASE 16.** Generic probe, legalization, candidate,
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

## Phase 6 - semantic compatibility and process-scoped dual-side guidance

Historical technical alias: `R6`.

**Status (normalized 2026-07-23): BOUNDED GENERIC AUTHORITY COMPLETE;
DESIGN-SPECIFIC DEFAULT ADOPTION IS PHASE 16.** The generic source-bound sensor, antenna,
routed-copper, decoupling/hot-loop, switch-node, oscillator, connector,
return-adjacency, assembly-retention, neighbor-overhang, and R5/R6 integration
authorities are accepted within the limitations in supplement 5. Complete
design-specific declarations/evaluators and the materially different proof
board are scheduled in Phase 17. Source-approved antenna exceptions and
condition-matched RF campaigns remain board-triggered rather than universal.

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

### Cross-reference: Phase 11 standardized visual-review design record

**Status (2026-07-20): FOUNDATION IMPLEMENTED; DEFAULT WORKFLOW INTEGRATION OPEN.** Rendering is
an automatic evidence-production stage; visual acceptance remains a separate,
recorded human or vision-assisted gate. A clean DRC cannot substitute for this
gate, because composition, legibility, model visibility, realistic placement,
and mechanically suspicious relationships are not completely reducible to DRC.

Generate the package immediately after placement and again after final routing.
Every board authority writes it beneath a dedicated `review/` directory:

```text
review/
  manifest.json
  overview/
  fabrication/
  assembly/
  routing/
  electrical/
  details/
  3d/
  comparisons/
  diagnostics/
  review-report.md
```

Resolution is physical-scale-aware, not merely labelled 1080p or 4K. Full-board
raster views use at least a 3,840-pixel long edge and target 20-40 px/mm,
whichever requirement is stronger. Dense-region crops target 80-120 px/mm.
Retain SVG or PDF for zoomable 2D views where KiCad export supports it; PNG is
still required for convenient viewing and automated vision inspection. Large
boards are divided into deterministically labelled, slightly overlapping tiles
(`A1`, `A2`, `B1`, ...) at a constant physical scale.

The minimum image/profile set is:

1. front and back design overviews: copper, mask, silkscreen, and `Edge.Cuts`;
2. front and back fabrication views, plus front and back assembly views;
3. front-only, back-only, and combined copper routing views with obscuring mask
   and nonessential graphics disabled;
4. zones, keepouts, courtyards, cutouts, holes, vias, and layer-transition views;
5. power/ground, high-current, sensitive analog/sensor, fast-bus, matched-pair,
   and RF-filtered views when those declared classes exist;
6. deterministic detail crops for dense placement, connectors/edges, power
   entry and regulation, sensors, fine-pitch devices, cutouts, mounting points,
   and enclosure-critical regions;
7. populated and bare-board 3D top, bottom, perspective, front-low, and rear-low
   views, plus close-ups of mechanically important modules;
8. previous/current placement and copper comparisons when a predecessor exists;
9. diagnostic renders containing DRC or semantic markers whenever findings exist.

`manifest.json` records the board/copper hashes, source revision when available,
KiCad and renderer versions, render-profile version, enabled layers, side and
mirror convention, camera/orientation, pixel density, tile bounds/overlap, 3D
model resolution and proxy status, generation result, and image hashes.
`review-report.md` marks each required artifact `generated`, `inspected`,
`accepted`, or `attention_required`, names the reviewer/inspection mechanism,
and retains findings with image/tile coordinates. Missing required images,
unresolved required 3D models, ambiguous mirroring, or an incomplete inspection
record fail the review-output gate instead of disappearing silently.

Implementation order:

- [x] define a versioned render-profile schema and board-size/feature-triggered
  image matrix;
- [x] implement deterministic 2D/vector/raster layer profiles and tiled crops;
- [x] implement deterministic 3D camera profiles and model/proxy preflight;
- [x] generate the manifest and review report from the same board authority;
- [x] add callable early post-placement and final post-routing commands and
  fail-closed missing-artifact checks;
- **Migrated (Phase 17, P0):** invoke the post-placement command automatically
  from the shared board workflow before any route attempt;
- **Migrated (Phase 17, P0):** add golden coverage for layer membership,
  physical scale, tile coverage, repeat hashes, missing models, and
  intentionally firing diagnostic overlays;
- [x] run a non-acceptance infrastructure smoke on the existing bunny board:
  36 required/conditional artifacts were produced in 231.6 seconds with no
  missing required files, and the result correctly remained
  `generated_pending_inspection`. This did not certify the bunny board and did
  not reuse the completed thermometer as the generality proof.
- **Migrated (Phase 17, P0):** pilot the full package and inspection gate on a
  materially different board, then promote it to every production board. The
  older R005/R006 pilot proposal remains retired.

## Phase 7 - thermometer electrical project - **COMPLETE 2026-07-18**

Historical technical alias: `R7`.

R005 is the accepted routed electrical proof-of-concept: 63 netlisted
components, 53 routed nets, zero unrouted connections, passing machine and
reader ERC, reader-netlist equality, ngspice checks, virtual/design checks,
KiCad DRC, deterministic copper replay, repeated save, and recorded visual
inspection. It used the legacy router; its completion must not be relabelled as
R2/R3 negotiated-capacity proof or generic production/default adoption.

The separate R006 3D visualization pilot is formal Phase 8 below.

The earlier proposal to rerun the known thermometer through R2-R6 is retired.
The user explicitly confirmed on 2026-07-20 that the thermometer is accomplished
and should not be redone. Keep the isolated `/PWLED` and reduced-stem fixtures as
generic regression evidence; validate broader generality on the next unseen
project rather than tailoring the pipeline to this completed design.

The historical combined-tree checkpoint before the last two test additions was
2,560 tests and 232 production files. The first 2026-07-20 collection audit was
2,562 tests across 198 test files and 233 production Python files. After the
Phase 11/12 core implementation, the collection is 2,590 tests across 204 test
files and 239 production Python files; the current-state record carries the
latest fully executed gate rather than silently rewriting older checkpoints.

## Phase 8 - 3D asset onboarding pilot - **COMPLETE 2026-07-18**

R006 adds proxy SHT31 and OLED model metadata without changing the accepted
R005 copper. It proves deterministic model-path resolution, attachment,
transform recording, and useful mechanical-review visibility for components
missing from the default KiCad 3D libraries. Its proxies are visual evidence,
not exact procurement, collision, tolerance, or enclosure-fit authority. Those
stronger capabilities are Phase 19.

## Phase 9 - production postmortem and workflow requirements - **COMPLETE 2026-07-20**

The thermometer failure/success record was converted into durable workflow
requirements: always-persisted pre-route PCB and renders, one automatic
verification entrypoint, cutout-aware shared legality, bounded progressive
routing telemetry, single-source mechanical authority with dependency
invalidation, 3D asset preflight, fast-before-expensive verification, and a
standardized visual-review methodology. The user accepted the thermometer and
retired a hard-coded rerun.

Phase 9 completed the postmortem, requirements, and roadmap-governance decision;
it did not claim the reusable APIs were already implemented. Their foundation
was implemented in Phase 11 and their production-default integration is now
scheduled in Phase 17.

## Phase 10 - continuity and environment normalization

**Status (2026-07-23): REPOSITORY SCOPE COMPLETE; EXTERNAL AUTOMATION IDENTITY
FOLLOW-UP NON-BLOCKING.** This phase was appended after the user accepted R7.
It does not modify the scope of any completed phase.

- [x] Archive the stale long handoff verbatim and remove it from the mandatory
  reading path.
- [x] Replace it with a concise live bootstrap that separates stable operating
  rules from volatile status.
- [x] Establish one dated current-state authority and reconcile README/handbook
  claims, source/test counts, R005/R006 scope, and the active reading order.
- [x] Correct R005 verification language so the legacy router does not
  masquerade as negotiated resource-overuse authority.
- [x] Audit actual Python 3.11/3.12 compatibility, dependencies, Ruff, mypy,
  documentation, and `uv.lock`; normalize versions only from that evidence.
- **External follow-up:** review the daily commit automation as snapshot
  preservation once its exact identity/location is available. The repository
  and local Codex automation directory exposed no matching configuration on
  2026-07-20 or 2026-07-23. Do not recreate or alter the user-owned task from
  an assumption; this does not block repository work.
- [x] Run focused/static gates during the correction and one full regression at
  the Phase 10 checkpoint. The 2026-07-20 static gates passed. The 2,562-test
  run reached 100% in 471 seconds with one Hypothesis slow-input-generation
  health-check failure; that test passed both isolated and with the reported
  seed. The checkpoint is recorded as attention-required, not green.
  A later Phase 11/12 standard checkpoint passed all 2,590 tests with warnings
  treated as errors; it is the current repository verification authority but
  does not retrospectively erase the earlier health-check evidence.

## Phase 11 - evidence, assets, and review automation

**Status (2026-07-23): FOUNDATION COMPLETE; DEFAULT-PATH ADOPTION MIGRATED TO
PHASE 16.** Keep copyrighted books, paid standards, and non-redistributable CAD
local. Commit only permitted metadata, hashes, short locators, paraphrased
derived facts, applicability, transforms, proxy/license status, and
implementation state.

- [x] Build local-first source intake with cache lookup, approved official-source
  retrieval, content/archive identity checks, SHA-256, explicit blocked reasons,
  and separate local-private versus committed metadata records.
- **Standing governance rule:** distill only claims with named consumers and
  acceptance evidence. Downloading or summarizing does not make a rule
  production-exercised.
- [x] Resolve every KiCad 3D path before rendering; distinguish exact package,
  complete module, connector-only, and proxy assets. Never upload an external
  model unless its license permits redistribution.
- [x] Implement validated symbol/footprint/model installation into either
  redistributable repository assets or an ignored private asset root; never
  mutate the global KiCad installation.
- [x] Implement deterministic PNG-to-outline and PNG-to-silkscreen adapters
  with source hashes and explicit physical transforms.
- [x] Implement the standardized visual-review design record above: early placement
  PCB/renders, high-resolution overview and tiled detail, layer-isolated views,
  fixed 3D cameras, diagnostic images, hashes, and recorded inspection state.
- **Triggered product option:** server-side evidence storage remains
  unscheduled until a server/service architecture is selected. A server may
  store only material whose rights and access policy permit it.

## Phase 12 - execution health and test stewardship

**Status (2026-07-23): REPOSITORY EXECUTION CORE COMPLETE; BOARD-ALGORITHM
INTEGRATION MIGRATED TO PHASE 16.** There is no universal timeout. Separate
reproducible algorithmic work limits from machine-safety and operator
observability.

- [x] Design and implement `quick`, `standard`, and `deep` subprocess profiles
  with heartbeats, progress evidence, hard memory ceilings, configurable
  wall-time escalation, typed termination, and a generic work-budget ledger.
- **Migrated (Phase 17, P0):** bind the selected profile to each board
  algorithm's native expansion/pass budgets and aggregate stage telemetry.
- [x] Checkpoint only at deterministic semantic boundaries. Claim resume support
  only after replay from a checkpoint is proven equivalent.
- [x] Build one verification orchestrator that reuses existing gates; do not create
  a parallel family of one-off inspection tests.
- [x] Complete the initial static and semantic test/check audit by current
  contract, historical regression value,
  duplication, runtime, and accidental implementation coupling. Age alone is
  not a removal reason. Replace obsolete coordinate/scale pins with current
  semantic invariants before deleting them. The 2026-07-20 review found 2,597
  collected cases from 1,885 authored functions and corrected the globally
  applied rule-11.1 blocker. Runtime attribution and full rule-to-caller mapping
  remain open; see `test-check-stewardship-review-2026-07-20.md`.
  The post-review standard gate completed all 2,597 cases (2,580 passed, 17
  intentional skips) with warnings treated as errors; lock, Ruff, and strict
  mypy over 246 source files also passed.
- **Migrated (Phase 16, P0 reliability):** investigate the 2026-07-20
  Hypothesis slow-input-generation incident under full-suite load. Later green
  runs do not establish its cause.
- **Migrated (Phase 17, P0 acceptance):** apply the generic R2-R6 authorities
  and Phase 11/12 workflow to a materially different user-selected project.

## Phase 13 - project-brief normalization and expansion

**Status (2026-07-23): FIRST PILOT COMPLETE; GENERALIZATION MIGRATED TO PHASE
16.** This is a new sequential phase, not work retroactively added to a
completed phase. The failed Retro-Pad R001 attempt proved that brief
normalization cannot wait until after a pilot. The approved R002 amendment
resolves its dogbone/corner-hole conflict and proves the first staged intake,
placement-review, routing, validation, model, and final-visual-review path.

- [x] Define a versioned core project-brief schema for provenance-carrying
  requirements, mechanics, components, placements, artwork, assets, spirit
  anchors, engineering freedoms, findings, and outcomes.
- **Migrated (Phase 17, P0):** add first-class interface, firmware-limit,
  assembly-process, and acceptance-gate records.
- [x] Build a deterministic structured normalizer that preserves the user's
  original text, rejects duplicate/missing identities, keeps resolution state,
  and separates user requirements from engineering selections.
- **Migrated (Phase 17, P0):** add the prompt-to-structured-draft
  examiner/refiner with retained source spans and no invented requirements.
- [x] Add a pre-design geometry examiner for traced-outline containment of real
  footprint bodies, courtyards, pads/holes, component/keycap rectangles,
  mounting holes, and apertures; return fail-closed concept outcomes.
- **Migrated (Phase 17, P0):** derive usable-region/neck-width capacity,
  connector mating access, keepouts, and routing-region envelopes.
- [x] Add a concept-layout review before detailed placement. Produce
  both (a) a spirit-preserving front/back visual proposal and (b) a
  dimensionally accurate engineering overlay generated from the traced outline
  and real footprint, body, keycap, courtyard, hole, artwork, and aperture
  envelopes. Connector-access, keepout, and routing-region overlays remain in
  the examiner item above.
- [x] Use consistent concept-review status colors: green for comfortable,
  yellow for tight/assumption-dependent, red for conflicting or outside the
  usable substrate, and blue for an engineering selection not explicitly
  required by the user. Save the image set, scale, transforms, and legend in the
  project evidence package.
- [x] Record `spirit anchors`, `engineering freedoms`, and `hard conflicts`
  separately, and illustrate the Retro-Pad hole conflict plus an inward
  alternative without silently accepting it.
- **Migrated (Phase 17, P0):** generalize typed deviation/consequence records
  and multiple spirit-preserving alternatives for hard conflicts.
- [x] Require hash-bound user approval of the normalized brief and concept
  review before the existing Retro-Pad PCB generator can run.
- **Migrated (Phase 17, P0):** check later schematic/board output for geometric
  and semantic drift from the approved concept.
- [x] Record explicit Retro-Pad power/current resolution, anchor semantics,
  artwork transform, 3D-model fidelity, and proxy policy.
- **Migrated (Phase 17, P0):** replace free-text anchor semantics with
  measurable typed edge, center, spacing, tolerance, mating-access, and
  aperture constraints.
- [x] Require an auditable resolution for every ambiguity: accepted assumption,
  derived value, explicit user decision, or blocking conflict. The reformater
  must never silently invent requirements.
- **Migrated (Phase 17, P0):** add a generic pre-route placement/capacity gate,
  compact failing-net diagnostics, and execution heartbeat/checkpoints.
- **Migrated (Phase 17, P0):** make generation transactional so failed stages
  cannot leave mixed schematic/PCB/review revisions.
- **Migrated (Phase 17, P0 acceptance):** prove the format on a second,
  materially different prompt-to-final board before default promotion.
- [x] Prove the first half of that requirement on Retro-Pad R002: approved
  120 x 48 mm concept amendment, hash-bound placement inspection, routed KiCad
  schematic/PCB, clean ERC/DRC/design/model gates, and accepted 35-artifact
  final visual package.
- [x] Add a real pre-route placement artifact and require its retained,
  hash-bound visual inspection before Retro-Pad final routing can start.
- [x] Generate standardized 4K front/back, isolated copper, fabrication,
  assembly, holes/vias, focused subsystem, and populated/bare 3D evidence for
  the accepted Retro-Pad board.
- **Migrated (Phase 17, P0):** make router ordering repository-deterministic
  without invocation-level `PYTHONHASHSEED`, and checkpoint completed route
  domains.

The intake slice is implemented in `project_brief.py`, `concept_review.py`, and
`predesign_gate.py`. `tools/generate_retro_pad_predesign.py` produced the
revised brief and 4K front/back engineering overlays; the R002 generator then
enforced approval and placement inspection before routing. The accepted board
and evidence are in `outputs/retro-pad-r002/`. This completes the first-board
proof, but not generic capacity derivation, transactional generation,
repository-wide deterministic/checkpointed routing, or the second-board proof.
The implementation/state audit is `roadmap-implementation-audit-2026-07-20.md`.

Retro-Pad failure evidence is preserved at
`outputs/retro-pad-r001/evidence/failure-review-2026-07-20.md`. Do not treat its
older PCB or review renders as an accepted deliverable.

## Phase 14 - context-gated advanced-board intelligence

**Status (2026-07-23): FOUNDATION AND FIRST PROMOTION SLICE COMPLETE; WORKFLOW
CLOSURE MIGRATED TO PHASE 16 AND ADVANCED ANALYSIS TO PHASE 19.** This is a new
sequential phase. It does not add unimplemented work to Phases 0-13 or weaken
their completion records. Its evidence and implementation guide is
`reference/advanced-pcb-design-research-and-source-guide-2026-07-22.md`.

- [x] Audit the local collection by document content and reconcile the known
  source wishlist against current holdings. The collection already covers much
  of the foundational IPC, USB, sensor, ESD, thermal, EMC, and SI material; the
  dominant gap is utilization rather than bulk acquisition.
- [x] Define a 23-family research taxonomy spanning exact-part identity, power
  entry and sequencing, PDN, stack-up, return paths, clocks, SerDes, DDR,
  Ethernet, RF, switching power, motor/high-current, precision analog, sensors,
  thermal, EMC/ESD, isolation/safety, BGA/HDI, DFM, test/bring-up, reliability,
  and CAD assets.
- [x] Run the approved official-source intake. Thirteen new PDFs are validated,
  SHA-256 pinned, and retained only in the private cache; five Analog Devices
  endpoints are explicit network-blocked records rather than silently replaced
  by unofficial mirrors. TI SLVA680A was already local and was not duplicated.
- [x] Intake the 2026-07-22 user-supplied standards wave with normalized names,
  visual identity review, and SHA-256 verification. The original IPC-2226,
  IPC-6012C, IPC-6013D, IPC-7251 first working draft, IPC-2221B second working
  draft, and 2016 IPC Standards Tree are local historical/draft evidence; none
  silently closes a newer-revision gap or outranks the existing final IPC-2221B.
- [x] Publish commit-safe source-request, public-intake, source-matrix, and
  machine-readable rule-catalog records. Keep payloads, paid standards, and
  non-redistributable assets out of Git.
- [x] Evaluate component/document discovery and CAD providers. DigiKey, Mouser,
  element14, and Nexar can locate part metadata and datasheet URLs after
  credential setup; they are not layout-rule authorities. KiCad is the preferred
  generic CAD source. SnapMagic and Ultra Librarian remain conditional on terms,
  credentials, cache rights, and asset-level verification.
- [x] Define L0-L3 complexity escalation so controlled impedance, DDR, BGA/HDI,
  multi-gigabit, FPGA/SoC, isolation, safety, and certification work cannot pass
  on ordinary ERC/DRC alone.
- [x] Harden source retrieval with bounded retry/backoff, resumable queues,
  redirect/content-disposition handling, rate-limit telemetry, and a
  browser-capable fallback restricted to the approved official host. Preserve
  typed cache-hit, authentication, licensing, identity, and network outcomes.
  The CLI now accepts the 18-entry research request catalog directly, persists
  every entry before advancing, reuses hash-validated cache entries on restart,
  records per-attempt/final-response telemetry in manifest v2, and still reads
  v1 manifests. Redirect escape, rate-limit retry, retry exhaustion,
  authentication classification, cache resume, catalog validation, and CLI
  defaults have focused regression coverage.
- **Partially complete; remainder migrated/triggered:** revision-aware
  document-role discovery by exact MPN has a deterministic foundation.
  Phase 17 may qualify one live provider only when an approved board need,
  credentials, terms, and cache rights exist.
  - [x] Implement the exact-identity resolver, nine typed resource roles,
    deterministic candidate-catalog provider, existing Nexar-compatible
    datasheet-provider adapter, safe source-intake retrieval, installed-asset
    binding, replay-bound report, CLI, and project-gate consumption. Fuzzy or
    different MPNs are rejected; downloaded CAD is not called installed.
  - **Triggered provider breadth:** additional symbol/footprint/3D services
    require terms, credentials, stable API mapping, cache rights, and
    exact-asset validation before becoming default.
- **Migrated (Phase 16, P0):** add remaining typed project contexts for
  stack-up/fabricator, assembly, power/sequencing, interface/timing,
  environment, protection, isolation/safety, and validation.
  - [x] Implement the first Phase 14 project-engineering context: exact
    BoardNetlist and layout identities, exhaustive component profiles,
    reviewed feature declarations, source-context/reviewer identity, exact-MPN
    resource requirements, and L0-L3 complexity label.
  - **Migrated (Phase 16, P0):** complete the remaining project subcontexts.
- **Standing promotion gate; Phase 16 exercise:** reconcile proposed rules
  against exact device guides and applicable standards. Every promoted rule
  carries applicability, revision, authority, consumer, class, and evidence.
- [x] Complete the narrow first slice through existing semantic authorities
  rather than creating one-off checks:
  - [x] Evidence-gate decoupling-loop topology and numeric limits. A hard
    PASS/FAIL now requires a revision-identified, hash-pinned, locator-verified,
    applicability-confirmed source binding tied to the exact graph, paths,
    terminals, thresholds, and intended consumer. Unsupported limits remain
    advisory, while missing, stale, or incomplete authority is UNVERIFIED.
    Focused and shared-semantic regression coverage is green; production-board
    exercise remains part of the later cross-board proof item.
  - [x] Promote connector-to-ESD ordering. The evaluator composes the existing
    connector-zone result with replay-derived routed-copper paths and explicit
    physical-pad transitions. It derives the actual connector/protection/load
    order, requires complete per-net terminal inventories, detects undeclared
    parallel or bypass components, separates advisory from sourced-hard policy,
    and rejects missing or stale applicability evidence. This proves declared
    signal-chain ordering only, not protection-device rating or EMC immunity.
  - [x] Promote oscillator evidence zones. Hard intrusion, forbidden-net-class,
    reference-ground, stitch-via, separation, and capacitance requirements now
    require revision-identified, pinned, verified, applicable evidence whose
    claim and full declaration-context fingerprints match. Exact context covers
    board snapshots, zone geometry, oscillator/support references, exemptions,
    net-class membership, thresholds, policy authority, and intended consumer.
    Intrusion zones may instead be explicitly advisory. The current evaluator
    still declares supplied-object-only inventory and therefore does not claim
    automatic whole-board completeness.
  - [x] Promote switcher hot-loop membership. Each transition now proves exact
    ingress/egress pad identities on one component and carries a typed switching
    role. Every leg net requires complete graph-anchor coverage of retained
    netlist terminals; undeclared parallel or bypass components fail membership.
    Expected roles, declared parallel nodes, source revision/applicability, area
    threshold, topology kind, graph, paths, policy claim, and intended consumer
    are one replay-bound authority. Advisory results retain candidate violations
    without claiming acceptance.
  - [x] Promote stack-up/reference continuity. Return-path declarations now
    carry a typed, board-snapshot-bound stack-up context. Exact containment,
    sourced hard thresholds, and transition-stitch acceptance require verified
    two-layer order, declared adjacent signal/reference pairs, named reference
    nets, and revisioned pinned applicable evidence bound to the full stack-up
    context. Unknown stack-up is explicit and permits advisory guidance only.
    This does not infer dielectric properties, controlled impedance, material
    construction, plane quality, or multilayer SI performance.
- [x] Add the Phase 14 automatic applicability/completion gate. It derives the
  required declaration set for all five promoted families from the reviewed,
  snapshot-bound feature inventory; consumes the actual replay-valid evaluator
  result types; rejects missing, extra, foreign-board, or not-applicable results
  in applicable scope; and emits one replay-bound CLI artifact. Incomplete
  inventory leaves every family unresolved rather than silently skipped.
  Required exact-part documents must be validated in cache and required KiCad
  CAD assets must be installed. Production-board pipeline exercise remains in
  the cross-board proof item below.
- **Migrated (Phase 20, P1/triggered):** impedance/field solving, IBIS or
  S-parameter channel analysis, PDN impedance, power transients, and
  thermal/airflow analysis with typed inputs and acceptance metrics.
- **Migrated (Phase 17 framework; Phase 18/20 consumers):** extend the standard
  visual package with stack-up/reference, return-current, power-domain,
  thermal/current-density, high-speed, BGA, and DFM diagnostic views.
- **Migrated (Phase 17 acceptance and Phase 21 release corpus):** prove promoted
  rules on materially different boards with retained failure evidence and
  formal unresolved-risk records.

## Phase 15 - workflow conformance and multi-physics authority

**Status (2026-07-23): FOUNDATION SLICES COMPLETE; QUANTITATIVE ENGINEERING
MIGRATED TO PHASE 19 AND CORRELATION/RELEASE TO PHASE 20.**

Phase 15 is a new sequential phase. It does not add work retroactively to the
completed Phase 0-9 scopes. Its research authority is
`docs/reference/multiphysics-and-engineering-gap-research-2026-07-22.md`; its
normative deviation policy is `docs/workflow-deviation-governance.md`; and its
machine-readable capability decomposition is
`docs/reference/data/multiphysics-capability-gap-catalog-2026-07-22.json`.

- [x] Define workflow deviation classes. D0 additive evidence and D1 bounded
  refinements are allowed; D2 equivalent substitutions require coverage proof;
  D3 omissions fail closed without an approved waiver; D4 authority/safety
  changes require a new workflow version and human decision.
- [x] Research the missing engineering systems beyond component calculators and
  geometry semantics: scenario/mission profile, loss ledger, electrothermal
  network, cooling assembly/TIM/clamp, airflow/enclosure, interconnect,
  protection/fault energy, PDN/control, EMC/common mode, mechanical/
  thermomechanical, reliability/life, manufacturing variation, and correlated
  validation.
- [x] Acquire and SHA-256 pin 14 selected free official PDF sources through the
  allowlisted source-intake service. Payloads remain private; the public
  projection is
  `docs/reference/data/multiphysics-source-intake-2026-07-22.json`.
- [x] Enforce profile-to-manifest completeness in every authoritative generator.
  Shared workflow APIs own mandatory artifacts; board-specific generators may
  only append supplemental evidence or declare a governed substitution/waiver.
- [x] Repair BLDC ESC R002 by generating and inspecting the canonical structured
  `review/` package while retaining its existing `review-images/` folder as D0
  supplemental thermal-mechanical evidence. Preserve the omission as a failure
  corpus item and add a caller-integration regression. The package is conformant
  but remains `attention_required` because six back-side design/assembly/tile
  artifacts expose crowded overlapping control-cluster text.
- [x] Add a typed operating-scenario/mission-profile matrix and coverage gate.
  Pilot it on bounded BLDC startup, normal, peak, stall, regenerative, hot-plug,
  short, shutdown, and cooling-failure cases. Electrical target coverage is
  separated from thermal/environment/fault completeness; unresolved values do
  not satisfy coverage.
- [x] Add the source-bound loss/stress-ledger foundation and exercise it on R002.
  It calculates the selected phase-shunt I-squared-R interval at 30 A, 60 A,
  and 100 A under a named conservative current-semantics assumption, prevents
  physical-loss double counting, and emits non-numeric unresolved entries for
  missing mechanisms. Exact Infineon/Vishay facts retain PDF hash, page, test
  conditions, and applicability limits.
- [x] Add a validation-required MOSFET conduction screening path without
  promoting it to release authority. R002 now combines the guaranteed 25 C
  RDS(on) maximum with a manually bounded typical-only 175 C multiplier and an
  explicit six-step aggregate conduction-duty assumption. The 60 A Phase-U
  switch-pair screen is approximately 5.016-5.280 W, but it does not satisfy
  loss coverage and is not a hot guaranteed bound.
- **Migrated (Phase 20, P1):** complete the BLDC loss/stress ledger for
  conduction, switching, dead-time, recovery, avalanche, shunts, copper/vias,
  driver, DC-link capacitors, connectors, and cables with exact-part evidence,
  temperature, tolerance, and uncertainty.
- [x] Add the deterministic point-input electrothermal-network authority and
  instantiate the Phase-U topology. The solver handles a fully specified
  passive DC nodal network, fingerprints the mission profile and loss ledger,
  and returns `indeterminate` for interval or unresolved inputs instead of
  substituting nominal values. R002's junction-equivalent, package top, TIM,
  spreader, heatsink, PCB territory, and local-ambient nodes are retained.
- [x] Add a typed cooling-assembly authority and exercise it on the exact R002
  board hash. It distinguishes the selected Infineon package from geometry-only
  TIM, heatsink, clamp-hole, isolation, and air-mover records; evaluates six
  package interfaces; and fails closed on missing conductivity, contact Rth,
  clamp force/torque, isolation withstand, sink-to-ambient performance, and
  airflow. Visual solids and mounting holes cannot count as selected parts.
- [x] Add a deterministic point-input Foster step-response foundation. It
  supports reviewed resistance/time-constant branches but refuses interval or
  unresolved values and never digitizes a datasheet Zth curve implicitly. The
  R002 100 A/10 s model is retained as `indeterminate` because ambient, total
  switch-pair loss, and a reviewed/correlated Zth fit are missing.
- [x] Add sourced cooling-candidate authority without allowing candidates to
  satisfy exact-selection gates. R002 retains the Henkel A2000 TIM, Boyd 78045
  extrusion, and Delta AUB0405VD-00 fan as vendor/system-validation candidates.
  Clamp hardware is uncovered, and catalog endpoints are not assembly ratings.
- [x] Add a minimum-bus gate-drive applicability gate. At 9 V VM, guaranteed
  high-side VGS is 5.5 V, below the MOSFET's lowest 6 V RDS(on) condition; the
  earlier 10 V conduction interval is conditional arithmetic only.
- [x] Add separate gate-charge capacity and dead-time screening authorities.
  Qg-times-frequency demand is aggregated by simultaneously switching high and
  low-side device counts; R002 fails closed because its retained firmware does
  not define that PWM strategy. IDRIVE remains a separate edge-rate input.
  Dead-time screening requires programmed timing,
  turn-off completion, propagation mismatch, and a reviewed policy margin; it
  remains `indeterminate` rather than assuming the driver default is adequate.
- [x] Add a non-selecting gate-supply architecture decision. The retained 9 V
  and amended 10 V DRV8353 bus-coupled options fail a one-volt characterization
  margin. Separate 12 V/15 V VM rails pass voltage screening but add converter
  obligations. A sourced DRV8334 replacement is preferred because its native
  9 V operation guarantees at least 11.3 V gate high level under the inspected
  conditions, but exact variant, pinout, protection, sensing, firmware,
  transient derating, layout, sourcing, and validation remain unresolved.
- [x] Add an exact-candidate gate-driver migration screen without changing the
  retained board. `DRV8334RGZR` is active production; its full 48-pin plus
  exposed-pad map is accounted for, nine functional migration groups are
  classified, and compatible hash-pinned KiCad footprint/STEP candidates are
  present locally. The result remains `conditional_candidate` and
  `not_selected` because the package is non-drop-in and support-network,
  land/paste, placement/routing, firmware, protection, sensing, timing,
  transient, and validation work remains.
- [x] Add a source-formula bootstrap-capacitance screen. For the retained
  223 nC upper Qg and the DRV8334 candidate's 11.3 V lower gate amplitude, the
  minimum is 394.69 nF effective on each phase. A nominal 1 uF value remains
  `indeterminate` until MPN-specific DC-bias, tolerance, temperature, and aging
  derating establish its effective lower bound.
- [x] Inventory every mandatory DRV8334 support capacitor as a typed physical
  obligation. The candidate requires ten capacitors: PVDD, GVDD, flying and
  trickle-pump, VCP, VDRAIN, three phase bootstrap, and VREF. Exact capacitor
  MPNs/footprints are unselected; PVDD, VCP, and VDRAIN applied-voltage bounds
  remain unresolved. Placement implementation is therefore correctly blocked
  rather than packed around assumed 0603/0805 bodies.
- [x] Add a deterministic coupled electrothermal point solver with explicit
  R(T), I-squared-R, fixed-loss, and Rth feedback, convergence tolerance, and
  unstable-loop detection. Its R002 instance remains `indeterminate` because
  applicable RDS(on), ambient, fixed loss, and assembly Rth are unresolved.
- **Migrated and corrected (Phase 20, P1):** the one-phase network and coupled
  solver already exist. Supply bounded package/TIM/PCB/sink/ambient inputs and
  obtain a determinate, condition-matched electrothermal result.
- **Migrated (Phase 20, P1):** extend the solved slice to the shared three-phase
  sink and exact cooling assembly, including clamp, isolation, common-mode
  capacitance, and convection.
- [x] Add the typed protection-path and first surge-clamp foundations. Nine
  event requirements now cover stall, shoot-through, phase short, battery/bus
  short, reverse polarity, regeneration, hot plug, gate-drive fault, and
  cooling/overtemperature. Eight declared hardware, firmware, passive-clamp,
  and sensor paths fail closed until thresholds, tolerance, latency, action,
  domain independence, and residual energy are bounded. The exact 7KPD26A
  source is automatically cached and hash-pinned; its 26 V standoff leaves
  only 0.8 V above 25.2 V normal maximum, while its 42.1 V clamp point is tied
  to 166 A and a non-repetitive 10/1000 us waveform. Peak power is not treated
  as a universal energy rating.
- **Migrated (Phase 20, P1):** complete quantitative protection/fault-energy
  coordination, add fault interruption and reverse-polarity architecture, and
  prove downstream derated survival, repetition, SOA, and shutdown latency.
- **Migrated (Phase 21, P1 release prerequisite):** generate the measurement
  and correlation plan before thermal or current-capability claims.
- **Migrated (Phase 20 analysis; Phase 21 correlation):** add PDN/control,
  EMC/common-mode, structural/thermomechanical, reliability/life, and
  manufacturing-corner adapters only for triggering boards with complete
  context.

## Phase 16 - workflow authority consolidation and migration contracts

**Status (2026-07-23): COMPLETE.** Contract/consolidation scope only; Phase 17
production-path implementation remains open.

Phase 16 reconciles the important unfinished foundations from Phases 1-15 into
one non-duplicated architecture before production callers are migrated. It
defines the contracts, ownership, applicability, and evidence topology that
Phase 17 must consume. It does not claim production closure merely because the
contracts exist. The detailed migration authority is
`docs/roadmap-open-item-migration-2026-07-23.md`.

### Consolidated workflow and authority map

- [x] Publish one phase/capability map from every retained Phase 1-15 authority
  to its canonical owner, schema, caller, test, artifact, source/evidence
  requirements, and known limitation.
- [x] Identify and remove or formally deprecate duplicate one-off inspectors,
  parallel workflow gates, copied constants, and board-specific authority that
  conflicts with a shared semantic owner.
- [x] Define one versioned workflow state machine from raw prompt through
  normalized brief, concept approval, schematic, placement, routing, review,
  verification, manufacturing handoff, and explicit incomplete/failure states.
- [x] Define the shared project-context composition for interfaces, firmware
  limits, assembly, environment, safety/protection, power/sequencing,
  timing/signals, validation, fabricator, and exact-part evidence.
- [x] Define the authority/applicability protocol for promoted rules, optional
  board-triggered analyzers, external credentials, human decisions, and
  unresolved evidence. An unavailable provider must not block unrelated work
  or authorize a substitute.
- [x] Reconcile stable object, generation, board, route, evidence, and review
  identities so Phase 17 can detect stale or mixed artifacts across every
  stage.
- [x] Complete the test/check ownership map and runtime attribution; identify
  obsolete coordinate/scale pins, accidental implementation coupling, and
  missing caller coverage before deleting or adding checks.
- [x] Investigate and close the 2026-07-20 Hypothesis slow-input-generation
  incident by cause; later green suites do not establish the cause.
- [x] Freeze the Phase 17 migration contract and publish deliberate compatibility
  adapters for retained generators rather than rewriting their historical
  evidence.

### Phase 16 completion gate

- [x] Every migrated item has exactly one destination and no active duplicate
  checkbox in a historical phase.
- [x] Every shared authority has one owner, one version/fingerprint boundary,
  named consumers, and an explicit unsupported/unresolved outcome.
- [x] The frozen Phase 17 contract has architecture tests for state
  transitions, identity invalidation, applicability, and duplicate-authority
  rejection.
- [x] Publish a Phase 16 completion audit and update the current-state authority
  before production-path implementation begins.

## Phase 17 - production workflow closure and default-path proof

**Status (2026-07-24): ACTIVE; ROUTING-OMISSION GATE AND TWO RETRO-PAD
RECOVERY ROUTES ARE PROVEN, DEFAULT-PATH CROSS-BOARD PROOF REMAINS.**

Phase 17 finishes the Phase 11-13 integration gaps and consumes the consolidated
Phase 16 contracts. It is complete only when a materially different board
cannot bypass prompt examination, feasibility, automatic review, bounded
execution, transactional output, deterministic routing, and retained
verification.

### Brief, concept, and feasibility implementation

- [x] Add the prompt-to-structured-draft examiner/refiner with exact source
  spans, explicit unknowns, ambiguity findings, and a no-invention gate.
- [x] Implement the consolidated project contexts and typed edge, center,
  spacing, tolerance, mating-access, aperture, orientation, and side anchors.
- [x] Derive usable-region and neck-width capacity, component/courtyard/pad
  containment, connector mating access, keepouts, and routing envelopes before
  detailed placement.
- [x] Produce typed conflict consequences and at least two spirit-preserving
  alternatives when a hard requirement is infeasible.
- [x] Compare generated schematic/PCB geometry and semantics against the
  approved concept, not merely input-file hashes.

### Automatic review, execution, and transaction implementation

- [x] Make post-placement PCB persistence and the canonical review package an
  automatic shared gate before routing.
- [x] Add golden tests for layers, physical scale, tiling, mirroring, hashes,
  missing models, camera alignment, and diagnostic overlays.
- [x] Extend triggered diagnostic views for stack-up/reference, return current,
  power domains, thermal/current density, high-speed, BGA, and DFM.
- [x] Bind execution profiles to the native A* router and verification runner;
  retain actual pass/expansion telemetry, checkpoints, heartbeats, and a
  separate mandatory exact-check verdict before completion.
- [x] Complete the same operative budget binding for production placement and
  per-artifact rendering callers; contract-only bindings do not close this item.
- [x] Make generation transactional with one generation identity, explicit
  incomplete states, rollback, and no mixed artifact revisions.
- [x] Make router ordering repository-deterministic and checkpoint only
  replay-equivalent completed route domains.
- [x] Add compact pre-route failing-net and capacity diagnostics.
- [x] Add one project-wide applicability-to-execution manifest that binds
  every applicable rule/check to the exact saved inputs, producer/tool
  version, evaluated-object count, result, limitations, and final authority.
  Missing, stale, conflicting, or unjustified zero-object executions must fail
  closed; a green repository test suite is not project execution evidence.
- [x] Generate connected functional-sheet schematic review views from the same
  canonical semantic/netlist authority. Bind root and per-sheet SVG/PDF
  exports to the whole-project ERC/netlist hashes so a presentation-only copy
  cannot drift from the electrical design. The 2026-07-25 implementation
  exports every retained page explicitly, retains the complete-project PDF,
  and binds exact plus canonical ERC/netlist identities in one atomic manifest.
  A three-page fixture and live KiCad 10.0.3 Retro-Pad export pass.
- [x] Add exact-package pin evidence, deterministic per-IC neighborhoods,
  applicability-aware review obligations, bounded evidence-query accounting,
  and an exact-coverage manifest that cannot silently omit a review area.
- [x] Invoke component-review obligations automatically inside transactional
  generation and repair. Add retained per-IC traces, no-submission recovery,
  bounded neighbor-evidence retrieval, conservative normalization/
  deduplication, and production invocation of the new manifest. Do not create
  a separate assistant-style or routine human-operated review workflow. The
  2026-07-25 runner covers every `U*` component from the exact BoardNetlist,
  shares evidence-query budgets across retries, retains exceptions/invalid or
  absent submissions, and recovers unresolved work as unverified. Placement
  and repair transactions retain the execution, per-IC manifests, and traces;
  routing requires the same-netlist retained execution to be complete.
- [x] Turn the user-supplied schematic/PCB review conventions into typed
  release, conditional electrical/layout, and presentation obligations.
  Universal blocker promotion is forbidden without applicable authority.

### Generic-authority migration and Phase 17 completion

- [x] Complete the R2.4 serialized adversarial fixture and measured corpus.
- [x] Exercise persisted R4 handoff consumption through repeat KiCad
  save/read-back and mandatory clean DRC.
- [x] Retain R5 fixed-neighbor/full-template preservation tests and a
  two-case shaped-placement corpus through live KiCad save/read-back and DRC.
- [ ] Exercise complete R6 declarations/evaluators on the saved/read-back
  identity of the post-freeze unseen board. The routing gate now requires and
  binds this engineering-applicability result.
- [ ] Evaluate KiCad Multi-Channel / Repeat Layout when a repeated-channel proof
  board triggers it.
- [ ] Keep Freerouting an external candidate/oracle until it is pinned,
  deterministic, benchmarked, cleaned up, and revalidated by KiCad.
- [x] Exercise exact-MPN document/CAD discovery; a retained external blocked
  result is acceptable when credentials or terms are unavailable.
- [ ] Prove the complete prompt-to-final default path on at least two materially
  different boards, including one unseen after implementation freezes.
- [x] Retain deliberate failure cases for ambiguity, capacity, missing assets,
  routing, review omission, and transaction rollback.
- [x] Pass repository-wide Ruff, strict mypy, the warnings-as-errors full test
  suite, and live KiCad 10.0.3 R2/R4/R5 read-back/deterministic gates.
- [ ] Inspect the canonical review packages for both complete cross-board
  default-path proofs; internal fixtures do not satisfy human visual review.
- [ ] Publish a Phase 17 completion audit mapping every migrated implementation
  item to code, caller, test, artifact, and limitation.

### KiCad 11 PCB diff/merge watchpoint - not a Phase 17 completion blocker

KiCad's post-v10 development branch now contains native PCB diff and merge
support with GUI and command-line entry points, including `git mergetool`
integration. This is potentially valuable as an independent CAD-aware review
and conflict-resolution tool, but it is not required to close Phase 17 and a
nightly build must not become the production file authority.

- [ ] After a pinned KiCad 11 release candidate or stable release is available,
  evaluate the PCB diff/merge CLI in an isolated copy of the cross-board corpus.
  Record tool version, invocation, base/ours/theirs/output hashes, exit state,
  and retained diff/merge artifacts.
- [ ] Compare its detected changes with PCBSmith's semantic board identities,
  generation transactions, concept-drift checks, and routed-board evidence.
  Determine whether it adds useful change classes rather than duplicating a
  textual or object-hash comparison.
- [ ] Exercise clean, conflicting, and deliberately unsafe merges. A
  syntactically valid merged board must still pass read-back, netlist
  equivalence, routing coverage, DRC, applicability-to-execution, and review
  gates before it can replace a canonical artifact.
- [ ] If stable and headless, add it as an optional independent change-review
  oracle and Git merge adapter. Do not make a nightly file format, GUI-only
  interaction, or the merge tool's own success message a release authority.

### 2026-07-24 routing-omission corrective gate

- [x] Add saved-board routing evidence that records segment/via/zone counts,
  multi-pad-net copper-carrier coverage, uncovered nets, board hash, and an
  explicit `placement_only|partially_routed|routed_candidate` state.
- [x] Make final visual-package generation and later inspection fail closed
  when the exact saved board is not a routed candidate. Placement-stage copper
  views now retain an explicit unrouted warning instead of implying completion.
- [x] Add a routed-board release gate requiring exact-route acceptance,
  read-back, netlist equivalence, zero KiCad DRC/unconnected/parity findings,
  accepted conformant final review, and one committed board/review transaction.
- [x] Audit all canonical retained output boards with isolated KiCad 10 DRC and
  publish `docs/project-routing-revalidation-2026-07-24.md`.
- [x] Replace caller-supplied release booleans with retained typed exact-route,
  read-back, and netlist-equivalence evidence objects.
- [x] Implement one operative routed-board persistence/final-review transaction
  that rejects placement-only boards, dirty DRC, stale hashes, and mixed
  board/review generations before atomic persistence.
- [ ] Migrate every board generator to the routed-board transaction; the shared
  implementation does not by itself stop a legacy one-off script from
  bypassing it.
- [x] Repair routability-informed placement/escape generation for Retro-Pad
  R003 and 3x3. Both exact saved candidates now have full carrier coverage and
  clean KiCad DRC. R003 required deterministic Type-C and ISP local fanout,
  clock/ground/matrix/power/control ordering, exact completed-net checkpoints,
  selective rip-up, and moving the ISP header beside the MCU.
- [ ] Correct and route Protocol Analyzer R002 only after its rejected USB
  orientation, compaction, and placement issues are resolved.
- [ ] Keep the BLDC ESC placement-only until exact power-stage, gate-driver,
  protection, thermal, heatsink/clamp, and current-path decisions are complete.

### 2026-07-24 controlled edge-interface placement

- [x] Replace new whole-body edge waivers with replay-bound per-reference
  authority for connectors, jacks, sockets, actuated switches, and user
  controls. The declaration splits pinned local geometry into retained support,
  pads, and the user-facing overhang.
- [x] Require retained support and pads to remain in board material with
  independent edge-clearance thresholds. Require the overhang to touch exactly
  one selected real outline segment, occupy no board material, and remain
  between a minimum useful projection and maximum allowed projection.
- [x] Bind the authority to the canonical saved `BoardLayout`, installed
  footprint, component UUID path, source-file hash, geometry fingerprint, exact
  orthogonal transform, rule IDs, and replay-derived result fingerprint.
- [x] Make R5 legalization consume only an approved same-layout authority
  before waiving body or courtyard containment. A moved layout, failed
  geometry, bounded transform, wrong edge, pad intrusion, excessive overhang,
  or detached component fails closed.
- [ ] Derive the local responsibility regions automatically from pinned
  supplier mechanical drawings/CAD and footprint primitives. The first slice
  requires explicit source-bound polygons and does not infer a connector shell,
  button actuator, panel opening, keepout, insertion path, cable bend radius,
  finger/tool envelope, enclosure wall, strain load, or retention adequacy.
- [ ] Connect the same authority to the concept/feasibility anchor system,
  automatic placement candidate generator, MCAD enclosure-access gate, and
  standard connector/edge visual-review crop. Phase 19 owns full 3D mating and
  enclosure proof.

Recovery evidence:

- `retro-pad-3x3-r001-routing-candidate.kicad_pcb`: 643 segments, 112 vias,
  48/48 carrier nets, zero KiCad violations and unconnected items.
- `retro-pad-r003-routing-candidate.kicad_pcb`: 496 segments, 93 vias, 36/36
  carrier nets, zero KiCad violations and unconnected items.
- Both canonical review packages were generated from the exact routed hashes.
  Their inspected 2D copper/design views are accepted. Review packages remain
  non-release evidence because not every required artifact is inspected and
  the KiCad top 3D render has a known camera/framing defect.

## Phase 18 - manufacturing and assembly outputs

**Status (2026-07-25): ACTIVE; NEUTRAL PACKAGE, PANEL, AND CROSS-BOARD
STRUCTURAL PROOFS COMPLETE; BOARD ENGINEERING/PROCESS CLOSURE REMAINS.**

Phase 18 turns an authoritative single-board design into reproducible,
manufacturer-neutral fabrication and assembly deliverables. It does not claim
that generated files are production-ready without selected fabricator,
assembler, stack-up, process, and human release review.

- [x] Complete typed fabrication/electrical profiles for trace/space, drill,
  annular ring, mask, paste, milling, copper weight, stack-up, impedance,
  material, finish, insulation, and applicable IPC-2152 current/thermal context.
- [x] Replace trace-only current estimates with complete current-path records
  covering tracks, zones/planes, vias, pads, neck-downs, parallel sharing,
  connectors, voltage drop, current waveform/duty, and declared thermal
  context. Unknown conductor geometry must remain unverified.
- [x] Complete stable manufacturing identities for footprints, pads, holes,
  apertures, components, BOM rows, and placement rows across saved/read-back
  KiCad artifacts.
- [x] Generate one canonical manufacturer-neutral package: Gerber, drill/map,
  netlist, stack-up notes, fabrication drawing, assembly drawings, BOM, pick-
  and-place, paste, readme, hashes, tool versions, and release status.
- [x] Evaluate and version-pin KiKit for panelization and manufacturing-package
  generation. Cover regular/irregular outlines, rails, exact tabs, mouse
  bites, V-cuts, fiducials, tooling holes, matching KiCad project-rule
  authority, and panel-level DRC.
- [ ] Generate and validate actual impedance coupon geometry when required by
  the selected stack-up/process. Coupon identity declarations alone are not a
  physical coupon.
- [x] Add InteractiveHtmlBom as a self-contained assembly/review artifact with
  correct side, rotation, DNP, variant, BOM grouping, and optional net/copper
  rendering.
- [x] Add DFM/DFT checks for courtyard/process clearance, paste strategy,
  exposed pads/thermal vias, fiducials, tooling, test points, probe access,
  polarity/orientation, assembly sequence, and rework access.
- [ ] Evaluate optional manufacturer adapters, beginning with JLCPCB only when
  needed. Preserve canonical neutral outputs and require golden part mapping,
  side, rotation, origin, and units fixtures.
- [x] Prove packages on at least one regular and one irregular/cutout board,
  reimport or independently inspect the outputs, and retain intentional failure
  fixtures. Schema-v2 ZIPs now include their exact profile, identity,
  current-path, and DFM/DFT evidence; all files and hashes were independently
  checked and the six assembly/drill-map PDFs were visually inspected.
- [x] Require explicit human/fabricator/assembler approval before using
  `fabrication_ready`, `assembly_ready`, or equivalent release language.

## Phase 19 - MCAD, enclosure, and mechanical authority

**Status (2026-07-23): PLANNED; FREECAD/STEPUP WORK FORMALLY SCHEDULED HERE.**

Phase 19 validates mechanical exchange and enclosure-relevant geometry. Visual
3D renders remain review evidence; they do not become tolerance, collision, or
fit authority merely because they look plausible.

- [ ] Pin the KiCad, FreeCAD, KiCad StepUp, OCCT, and exporter versions and
  define accepted STEP/VRML/GLB coordinate, origin, side, rotation, scale, and
  unit conventions.
- [ ] Establish native KiCad STEP export/import as the baseline and characterize
  its behavior for exact models, proxies, omitted models, board cutouts,
  plated/non-plated holes, and component transforms.
- [ ] Test current KiCad StepUp / FreeCAD compatibility with KiCad 10 for board
  exchange, component placement, enclosure fit, connector accessibility,
  keepouts, mounting alignment, and collision/interference checks.
- [ ] Define typed mechanical envelopes and tolerances for components,
  heatsinks, fasteners, cables, mating connectors, buttons/knobs, airflow
  volumes, enclosure walls, assembly tools, and service/rework access.
- [ ] Add deterministic collision, clearance, insertion/mating direction, and
  board-edge accessibility reports tied to the exact board and model hashes.
- [ ] Round-trip representative assemblies and compare board outline, holes,
  cutouts, component poses, and critical dimensions within explicit tolerances;
  retain deviations rather than visually aligning them by hand.
- [ ] Prototype the official `kicad-python` IPC API as an optional interactive
  inspection/highlight/guided-repair companion. It must not replace direct file
  generation, headless `kicad-cli`, or retained deterministic evidence.
- [ ] Evaluate KiCad 11's FreeCAD `planegcs`-based geometric constraint solver
  in an isolated, version-pinned corpus. Target board outlines, radii,
  tangency, symmetry, mounting-hole patterns, connector datums, panel openings,
  and other mechanical relations; do not misapply it to electrical,
  current-path, routing, thermal, or enclosure-fit authority.
- [ ] Build any adopted solver integration as an adapter from PCBSmith's typed
  spatial and mechanical constraints. Retain constraint identities, units,
  tolerances, degrees of freedom, solver version, solve result, and the exact
  before/after board hashes.
- [ ] Characterize deterministic replay, serialization, under-constrained and
  over-constrained states, conflicting constraints, tolerance behavior, and
  failure recovery before solver output can update a canonical board. The
  typed PCBSmith requirement remains authoritative even if KiCad performs the
  geometric solve.
- [ ] Prove the MCAD gate on a connector/enclosure-critical board and a
  heatsink/mechanical-assembly board with exact and proxy-model failure cases.

## Phase 20 - advanced electrical, thermal, protection, and simulation authority

**Status (2026-07-23): PLANNED; CONTEXT-TRIGGERED AFTER PHASE 17.**

Phase 20 consumes complete board contexts and exact selected parts. It adds
analysis adapters only where a triggering board supplies the required inputs.
Simulation remains unverified until Phase 21 correlation.

- [ ] Complete condition-matched loss/stress ledgers for conduction, switching,
  dead-time, recovery, avalanche, gate drive, shunts, copper/vias, capacitors,
  connectors, cables, magnetics, contacts, and applicable fault energy.
- [ ] Obtain determinate one-phase and shared multi-phase electrothermal
  solutions using exact package, PCB, TIM/contact, clamp, sink, airflow,
  enclosure, ambient, tolerance, and mission-profile inputs.
- [ ] Complete quantitative protection coordination for stall, shoot-through,
  phase/bus/battery shorts, regeneration, hot plug, reverse polarity, cooling
  loss, TVS/fuse/SOA, downstream voltage survival, repetition, and shutdown
  latency.
- [ ] Add typed PDN impedance and power-transient analysis with selected
  stack-up, decoupling, source/load models, target impedance, frequency range,
  and acceptance metrics.
- [ ] Add impedance/field, return-path, IBIS, and S-parameter channel analysis
  only for declared high-speed/RF interfaces with exact models, fixtures,
  de-embedding assumptions, and pass/fail metrics.
- [ ] Broaden to EMC/common-mode, control-loop, structural/thermomechanical,
  reliability/life, and manufacturing-corner adapters only when a board and
  source context require them.
- [ ] Extend the structured ngspice batch harness with `.measure`, corners,
  parameter sweeps, Monte Carlo, deterministic seeds where supported, vector
  capture, exact netlist/model/tool hashes, and threshold failures.
- [ ] Add a revisioned simulation-model registry with manufacturer/source URL,
  checksum, license/cache rights, exact part/package and pin mapping, model
  scope, compatibility mode, validation fixture, and supported analyses.
- [ ] Keep ngspice as the canonical automated backend. Evaluate LTspice as an
  optional process-isolated ADI-focused model/demo-circuit cross-check; require
  equivalent stimuli/measurements and report solver disagreements rather than
  selecting whichever result passes.
- [ ] Evaluate the process-isolated ngspice shared-library API only if it
  outperforms batch mode without weakening reliability; retain batch as the
  fallback and regression oracle.
- [ ] Keep Qucs-S a developer frontend. Add XSPICE only for a mixed-signal
  trigger and OpenVAF/OSDI only for required, individually licensed Verilog-A
  models with compiler/ABI/platform provenance.
- [ ] Produce board-triggered diagnostic visualizations for current density,
  thermal distribution, PDN, return current, high-speed transitions, protection
  paths, and uncertainty; never present an illustrative heat map as solver
  evidence.

## Phase 21 - correlated validation and release qualification

**Status (2026-07-23): PLANNED; FINAL AUTHORITY LAYER, NOT AUTONOMOUS SIGNOFF.**

Phase 21 closes the loop between prediction and physical evidence. PCBSmith may
organize evidence and enforce claim prerequisites; it may not autonomously
certify safety, compliance, lifetime, SI/PI, thermal performance, or current
rating.

- [ ] Define a typed validation-plan schema covering scenario, load, duty,
  environment, samples, instruments, calibration, bandwidth, probing,
  junction/case/board/sink/air measurements, emissivity/contact errors,
  uncertainty, acceptance limits, and responsible reviewer.
- [ ] Generate measurement and correlation plans before permitting thermal,
  protection, current-capability, SI/PI, EMC, mechanical-fit, reliability, or
  manufacturing-yield claims.
- [ ] Retain prediction-versus-measurement records with raw-data identity,
  processing scripts, model revision, uncertainty, residuals, pass/fail, and
  the exact parameter changes made during calibration.
- [ ] Separate calibration data from validation data and require new validation
  after any material component, layout, stack-up, cooling, firmware, enclosure,
  or model change.
- [ ] Build a cross-board success/failure corpus covering ordinary, shaped,
  high-current, thermally constrained, high-speed, and mechanically constrained
  designs; record applicability rather than averaging unlike boards together.
- [ ] Add claim-specific release gates and vocabulary so `calculated`,
  `simulated`, `correlated`, `bench-validated`, `qualified`, and
  `production-released` cannot be used interchangeably.
- [ ] Require named human engineering, fabrication, assembly, safety/compliance,
  and product approval roles wherever applicable, with explicit unresolved-risk
  acceptance.
- [ ] Publish a final capability matrix showing what PCBSmith can generate,
  inspect, calculate, simulate, correlate, and release—and what remains outside
  its authority.

## Historical post-R7 open-source tooling backlog (2026-07-14)

**Scheduling note (2026-07-23):** This list is retained for historical rationale.
Its active work has been migrated to Phases 16-19 and the migration audit. The
numbered priorities below are not additional parallel roadmap tasks.

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

BLDC ESC R002 adds a native KiCad GLB readback gate as a narrower prerequisite:
it verifies component centers and thermal-interface height continuity in the
actual exported visual assembly. Native STEP export remains incomplete while
the project uses VRML envelope models, so it is labeled partial rather than
treated as MCAD authority. This does not close the StepUp/FreeCAD evaluation.

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
