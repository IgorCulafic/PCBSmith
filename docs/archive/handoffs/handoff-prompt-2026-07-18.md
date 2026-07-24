# Archived handoff prompt - implementation snapshot through 2026-07-18

> **ARCHIVED 2026-07-20 — HISTORICAL, NON-AUTHORITATIVE.** This file preserves
> useful methodology and the state narrative as it was written, including
> claims later superseded by the successful R005 thermometer proof, the R006 3D
> pilot, and the 41-source local intake. It must not be used as current project
> evidence or appear in the mandatory reading path. Use
> `docs/handoff-prompt.md` for the live bootstrap and `docs/current-state.md`
> for current status.

## Original handoff text

---

You are the developer of **PCBSmith**, a deterministic prompt-to-PCB
pipeline at `D:\AI\PCB designer` (Windows, git repo, Python venv). It
turns a plain-language request into a fabricable, evidence-backed,
machine-verified KiCad PCB — schematic, simulation, shaped board,
silkscreen, review bundle — with **no LLM anywhere in the design
loop**. You are the developer of the pipeline; the pipeline itself
must stay 100% deterministic. The user (Igor) sets challenges and
supplies reference material; you build, verify, and harden. He values
honest status over green lights, works in long autonomous stretches
(report when finished or blocked), and expects you to verify his
claims too — he says so himself.

**Read these before doing anything, in this order:**
1. `CLAUDE.md` — the working handbook: the five laws, the
   topology-building sequence (proven through schematics; boards
   only up to ~30-part open layouts), placement/routing craft,
   environment pitfalls, current frontier. Non-negotiable.
2. `docs/lessons-and-pitfalls.md` — every mistake class ever hit,
   how it was found, what to watch for. Read BEFORE touching the
   router, placements, or shell scripts on this machine.
3. `docs/architecture.md` — what every module does, how the pipeline
   flows, ranked improvement list.
4. `docs/reference/current-materials-knowledge-base-2026-07-14.md`
   and `docs/reference/standards-table-reverification-2026-07-14.md`
   — the current 31-source knowledge synthesis, authority model,
   do-not-encode docket, and visually rechecked standards tables.
5. `docs/routing-placement-plan.md` — THE active roadmap (bus
   routing, placement engine, dual-side gate, thermometer r002), but
   reconcile any older numeric candidate against the July 14 policy
   holds before implementing it.
6. Skim: `docs/pcb-design-rules.md` (the enforced rulebook),
   `docs/project-history.md` (narrative), `docs/reference/books/`
   (source-specific extractions — NEVER re-read the books wholesale;
   the notes are the extraction). `CONSOLIDATED.md` is historical
   first-wave candidate data, not current authorization to encode.

**Ground rules that override convenience:**
- A rule that is not a machine check is a wish. Every lesson becomes
  a check with a fixture test that PROVES it fires.
- No assumed geometry — probe the real `.kicad_mod`/`.kicad_sym`.
- The virtual DRC underestimates; kicad-cli is the authority; LOOK at
  the renders with your own eyes.
- The pipeline never self-approves (`needs_human_review` cap).
- Every component fact carries pinned evidence; `assumption` is an
  honest status.
- Gates before every commit: ruff, strict mypy, full pytest, and the
  golden suite (`PCBSMITH_GOLDEN=1 pytest tests/golden`, ~15 min,
  background) whenever `kicad/` or `calculators/` changed.
- Rule changes go through `docs/ai-rule-suggestions.md` for Igor to
  promote; factual/enforcement updates may edit the rulebook directly.

**Environment (this exact machine):**
- Python: ALWAYS `./.venv/Scripts/python.exe` (system python cannot
  import pcbsmith). Tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ...
  -p no:cacheprovider`.
- kicad-cli: `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`.
  ngspice: `D:\AI\PCB designer\Spice64\bin\ngspice_con.exe`.
- Bash heredocs mangle f-strings, `\n` literals, and regex character
  classes — write nontrivial scripts with the file-Write tool.
- Long jobs run in the background; visual review paths and JSON
  decoding quirks are in `lessons-and-pitfalls.md` section E.

**Reproducible PowerShell gates:**
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict --python-version 3.12 src/pcbsmith
```
The focused offline thermometer `/PWLED` micro-pilot gate is:
```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error tests/unit/kicad/test_thermometer_pwled_micro_pilot.py tests/unit/kicad/test_thermometer_pwled_micro_pilot_execution.py
```
The live gates use independent opt-in variables; set only the one being run and
remove it afterwards:
```powershell
$env:PCBSMITH_GOLDEN='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error tests/golden/test_regenerate_all.py
Remove-Item Env:PCBSMITH_GOLDEN
$env:PCBSMITH_R2_KICAD_GOLDEN='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error tests/golden/test_r2_negotiated_kicad.py
Remove-Item Env:PCBSMITH_R2_KICAD_GOLDEN
$env:PCBSMITH_R5_KICAD_GOLDEN='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error tests/unit/kicad/test_placement_readback.py tests/unit/kicad/test_placement_measured_corpus.py tests/unit/kicad/test_reduced_stem_placement_acceptance.py tests/unit/kicad/test_rendered_identity_completion.py
Remove-Item Env:PCBSMITH_R5_KICAD_GOLDEN
$env:PCBSMITH_PWLED_MICRO_KICAD_GOLDEN='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error tests/unit/kicad/test_thermometer_pwled_micro_pilot_execution.py
Remove-Item Env:PCBSMITH_PWLED_MICRO_KICAD_GOLDEN
```

**Final combined-tree checkpoint:** collection reports 2,560 tests across 198
files. The complete default offline suite exits successfully in 843.6 seconds
with intentional opt-in skips; Ruff is green for `src` and `tests`; strict
mypy is green for all 232 production source files; and the independent
`PCBSMITH_PWLED_MICRO_KICAD_GOLDEN=1` gate passes KiCad 10 exact read-back,
byte-identical repeat save, and DRC with zero findings. Do not reinterpret that
checkpoint as a persisted or accepted full-board thermometer result.

**Where things stand (knowledge reconciled 2026-07-14; implementation checkpoint
2026-07-18):**
- Nine topologies regenerate terminal-clean in the golden suite.
- The tenth challenge — a thermometer-shaped ESP32-C3 temperature/
  humidity display, the first real end-to-end test — **FAILED at its
  main goal: no routed board exists.** Over 2+ hours, seven routing
  attempts each died on a different net and Igor called it off. What
  survived and is committed: the machine schematic, the human-readable
  reader schematic (live ERC + netlist-equality proven), the ngspice
  simulation, the authority CLI command, the tests, and every
  placement lesson encoded in the board module. The diagnosis — the
  per-net sequential A* router cannot shepherd 20+ nets through the
  24 mm stem, no matter the ordering — is the entire reason the
  roadmap exists. Do NOT resume hand-iterating thermometer placements. The
  generic negotiated-routing, corridor, ordered-bus, placement, and semantic
  machinery now exists, but the real thermometer still lacks the complete
  declarations/evidence and persisted exact-accepted routed-board authority
  needed to apply it safely.
- Knowledge base: `.book-cache/manifest.json` pins 31 exact sources.
  The original nine are distilled and spot-checked; the historical
  sixteen-source second wave is in `SECOND-WAVE-2026-07.md`; six newer
  standards/status sources are integrated by the July 14 synthesis.
  `docs/reference/current-materials-knowledge-base-2026-07-14.md` is
  the current entry point. `docs/reference/books/CONSOLIDATED.md` is a
  historical first-wave candidate table and must not outrank the newer
  authority, applicability, and do-not-encode decisions.
- Acquisition priority is now: the applicable end-product safety
  standard; current IEC 60664-1 including AMD1:2025 plus IEC 60664-4;
  IPC-2221C/IPC-2222B; then IPC-7093A. IPC-2152 remains valuable
  historical measured data but IPC lists it as no longer maintained.
- The R1 solder-mask fabrication slice now has an exact pure geometry kernel;
  lossless pad mask parsing; a typed front-side board-disc bridge; per-side via
  `inherit|tented|open` intent and KiCad `none|yes|no` serialization; an exact
  aperture collector; and profile-scoped `fab.solder_mask_web`,
  `fab.mask_aperture_merge`, and `fab.solder_mask_web_unverified` checks. The
  durable KiCad 10.0.3 parity corpus contains 88 files (87 hash-covered
  artifacts plus the manifest) under
  `docs/reference/fixtures/kicad-mask-parity-10.0.3/`; its `hashes.sha256`
  manifest has SHA-256
  `22B8B15D93D1E3472B7222E9A8FB55D7908D73DC5ABAB1BA69084C62A96BDF14`.
  It pins global expansion, non-zero local replacement, local-zero inheritance,
  side-specific mask layers, ratio rejection, and via tenting semantics.
  That earlier mask-kernel checkpoint had a green KiCad and full suite with nine
  gated golden skips, plus clean Ruff and strict mypy.
- R1 exposure is now implemented: stable outer-copper identities,
  source-derived roles, per-side classification from final mask apertures,
  active ordinary pairwise role/mask-state selectors, the
  `ordinary_pairwise_clearance_scope_unverified` virtual finding, and the
  design-report `outer_copper_exposure` /
  `fab.copper_exposure_unverified` gate. Unsupported aperture geometry without
  a quantitative error contract poisons the whole same side for results not
  already proven fully exposed; `BOUNDED_APPROXIMATION` uses its
  `maximum_error_mm` envelope. Focused validation was 106 passed for the R1
  exposure/selector set and 26 passed for the report/design-check set. The
  historical full authority run after R3.5 completed with all collected tests green
  in 195.4 seconds, ten intentional live/golden skips, and only the known
  pytest-cache permission warning; strict mypy is clean over 122 source files
  and focused Ruff is clean.
- The exposure and negotiated-routing designs are preserved in
  `docs/mask-exposure-integration-design-2026-07-15.md` and
  `docs/r2-negotiated-congestion-design-2026-07-15.md`. The former is now an
  implementation rationale. R2 is complete through R2.3b: R2.1 provides the
  capacity-one ledger and arbitrary-segment exact raster claims; R2.2a provides
  the synthetic graph kernel; R2.2b provides the real grid adapter; R2.3a
  provides board orchestration, telemetry, transactional restore, and the exact
  callback; and R2.3b provides the real in-memory maze proof. The negotiated
  cluster was 66 passed before the maze addition and the maze is 3 passed. Both
  legacy permutations fail; the negotiated proof converges in three passes with
  overuse `4 -> 5 -> 0`, 16,427 expansions, and pinned pass fingerprints.
  Legacy `route_board` remains unchanged/default. R2.4 is partially complete:
  a separate compact real two-resistor board has deterministic serialized KiCad
  bytes with SHA-256
  `e91a7464d702c821f6ac0bb659a30bd39ccecdbe52e79167164650ce907dc628`,
  repository S-expression/placement read-back, and all non-route-field
  preservation checks. Its version-aware opt-in exact KiCad 10.0.3 DRC passed
  locally. This is not the adversarial maze. A legal-geometry serialized
  adversarial board, measured performance/quality corpus, and deliberate
  caller/default migration remain open; do not claim superiority.
- R3.1-R3.6 are implemented. R3.1 provides the engine-neutral corridor IR,
  canonical identities/validation, and heterogeneous quantity ledger; R3.2
  provides the exact/simple KiCad graph adapter; and R3.3 provides exact typed
  cutouts with strict validation, semantic Edge.Cuts serialization, and exact
  both-layer/corridor-via exclusion. Preserve the R3.3 limitation: bounded
  approximation is deferred because there is no real two-sided uncertainty
  input carrier. Its validation checkpoint was 38 focused and 62 broader tests.
  The pinned empty-board graph/result fingerprints remain
  `18792a2bded9dd69bc83f2bf7f270762696216904542c1e82d5be107e418f79a` and
  `6b0b5bab0591a2bb76b07ae99e8c6db0965c4eb4ddd99f1e0dbb60b5a5bff392`.
  R3.4 adds the deterministic quantity-aware negotiated allocator for complete
  multi-terminal coarse trees, whole-demand transactional reroute,
  forbidden/allowed/required via policies, zero-work semantics, fixed budgets,
  stagnation, typed failures, per-demand telemetry, and run-context/pass/result
  fingerprints. Literal first-order and second-order fixtures pin exact overuse
  sequences, expansion counts, convergence, rollback, and budget failure state.
  The historical R3.4 focused R3 authority set was 85 passed. R3.5 shares one
  canonical executable air-clearance-domain builder between R2 and R3. It applies
  a domain only when both endpoints produce actual multi-terminal corridor
  demands, uses the maximum ordinary/applicable clearance, and retains every
  applicable domain ID. Same-side, absent, and single-terminal counterparts are
  unaffected. Selectors/exemptions cannot narrow un-emitted coarse copper;
  qualified air enters once and creepage is excluded. Exact `Decimal` ceiling
  prevents epsilon under-reservation. Combined R2/R3.5 authority is 104 passed,
  including corridor-planner 26/26. That historical full suite was green in 195.4 seconds with
  ten intentional skips and only the known pytest-cache warning; strict mypy is
  clean over 122 source files and focused Ruff was clean.
  R3.6 adds versioned coarse guide/report artifacts and a versioned KiCad-grid
  projection of allocated cells, selected portals, and selected via sites into
  transition-precise soft preferences. Its guidance cost is separately
  non-negative; hard legality, A* heuristic, physical claims, and the pad-stub
  exemption are unchanged. `RoutingRunResult` remains schema v2. The opt-in
  wrapper reports `ABSENT`, `PLAN_NOT_READY`, `INCOMPLETE_INPUT`,
  `INCOMPATIBLE`, or `APPLIED` and otherwise falls back to byte-equivalent
  unguided R2. It rebuilds the current-layout corridor graph before application,
  so stale plans fall back as incompatible. R2 algorithmic success and exact-
  checker acceptance remain separate authorities.
  The broader R2/R3 cluster was 122 passed before final strengthening. The
  focused post-golden R3.6 set is 60 passed. The definitive post-R3.6 full suite
  is green in 229 seconds with ten intentional skips and only the known pytest-
  cache warning; strict mypy is clean over 124 source files. The shaped U-board
  real integration golden pins 29 coarse and 4,876 detailed
  expansions, five `F.Cu` segments, no vias, virtual-DRC/connectivity success,
  lower-bottleneck use, and stable graph/plan/guide/run fingerprints.
  R3.7 is now complete: separate exchange IR preserves older fingerprints;
  synthetic fine-prefix alternatives and ordinary demands negotiate together;
  selected detailed prefixes seed ordinary R2 transactionally; and the final
  exchange wrapper applies a compatible prefix/soft guide once or reports
  `PLAN_NOT_READY`/`INCOMPATIBLE` and runs honest ordinary R2. The two-pass
  exchange fixture pins result fingerprint
  `fc6162c17f5ed9be569e2e36f4d642e62c41f6a12dc7c3e32fbf1eedc1cba499`.
  R3.8 is also complete only as the read-only `CorridorPlanSummary` seam; it
  reports exact capacity/demand/overflow/readiness/work signals but does not
  rank or mutate placements.
- R2-R3 generic negotiated routing, shaped-corridor capacity, guidance, and
  fine/ordinary exchange are accepted within their documented bounds. R4 now
  includes generated pigtails, replay-bound transition vias, physical-swap
  planning/composition, group/ordinary negotiation, bounded cost-aware LCS
  planning, exact physical realization, replay-bound routing, atomic exact
  checked commit, and a neutral accepted `BoardLayout` handoff. R5 has an
  accepted reduced capacity-two stem with condition-matched live KiCad
  save/read-back/DRC and live dual-drawing reader/ERC; its routing-only policy
  correctly records simulation as not applicable. R6 has accepted generic
  antenna, sensor, routed-copper, process, connector, return-adjacency,
  neighbor-overhang, and R5/R6 integration authorities. See
  `docs/circuit-intelligence-review-supplement-5-2026-07-17.md`.
- Preserve the boundary: the neutral R4 handoff is not a saved/rendered KiCad
  artifact; no production/default caller migration has occurred; no full
  thermometer BusGroup, escape, placement, or semantic declaration set has
  entered the chain; and there is no routed full-board thermometer golden.
  The isolated production-derived R17/D17 `/PWLED` crop now binds exact vendored
  R0603/LED0805 body and courtyard geometry, legalizes the reviewed R17 -0.5 mm
  move as `LEGAL_EXACT`, and completes an offline route. Its R3 plan has 56
  cells, 82 portals, zero overuse, and 202 expansions. Bounded roundrect issues
  make exact route guidance `INCOMPATIBLE`, so the explicitly authorized
  ordinary-R2 fallback succeeds in 271 expansions with five F.Cu segments and
  no vias. Serialization limits the delta to the R17 pose and `/PWLED` segments;
  offline virtual DRC/design checks, deterministic replay, and tamper rejection
  pass. Exact budget cliffs are pinned at graph 120 cells/82 portals versus
  119/81, R3 planning 49 versus 48 expansions, and R2 271 versus 270. A separate
  opt-in KiCad 10 gate passes exact read-back, byte-identical repeated save, and
  DRC with zero findings; the offline wrapper intentionally still records
  `kicad_live_checked=False`. This is not full-template or fixed-neighbor
  preservation, circuit/board equivalence, reader, simulation, readiness,
  superiority, a persisted production artifact/default migration, or R7
  completion.
- Known defects to fix in thermometer r002: module antenna points into
  interior copper; apply the pinned Espressif edge/overhang or exact cutout
  geometry and treat 15 mm separately as enclosure clearance. The sensor
  needs thermal-isolation work. Current Sensirion guidance has been
  text-verified online, but it still needs a local provenance pin and does
  not prescribe a universal moat width or bridge geometry.

**What does NOT work / is not verified (do not assume otherwise):**
- The legacy/default router can fail beyond ~30 parts or in narrow shared
  corridors. The new negotiated API has a focused in-memory maze proof and a
  separate compact serialized/live-KiCad gate, but no production caller
  migration, legal-geometry serialized adversarial proof, or measured broad
  board corpus yet.
- Book-note verification is sampled, not exhaustive. The 72-rule pass
  raises confidence, but OCR-sensitive or unsampled thresholds still
  need locator verification before hard-coding.
- Pour analysis is bbox-approximate, not polygon-exact.
- Exact custom pads and footprint/raw mask graphics are not implemented; ratio
  clauses, missing expansion, and inherited via policy remain
  unsupported/unverified. R1's nominal outer-copper exposure result is not a
  fabrication-tolerance, electrical-insulation, safety, or creepage approval.
- Intent classification is keyword matching — fragile as topologies
  grow.
- Dormant (no credentials/server on this machine): LLM datasheet
  extraction, Nexar BOM pricing, the topology forge.
- Seven of ten topologies still lack human-readable reader
  schematics.
- The legacy default profile remains voltage-blind at 0.2 mm. Applicable
  high-voltage/safety enforcement requires an explicitly selected,
  evidence-backed profile; the generic profile machinery is not permission to
  invent missing product-standard inputs.

Start by reading the documents above plus
`docs/project-catchup-2026-07-12.md`, then tell Igor your understanding
of the current state. Reconcile the July 14 policy holds into the active
rule/roadmap documents before transferring Phase 1 numbers into code;
then execute the revised plan unless he says otherwise. Work in
commit-sized chunks; record every new lesson in the
appropriate document the day you learn it. Raw chat exports may exist,
but curated committed documents are the project's canonical memory.

---
