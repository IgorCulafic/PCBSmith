# PCBSmith project history

A detailed narrative of what has been built, in order, with the
commits that carry each step. Written 2026-07-07 by Claude Fable 5 for
its successor models. The companion methodology document is
`/CLAUDE.md`; the enforced design knowledge is
`docs/pcb-design-rules.md`; the active plan is
`docs/routing-placement-plan.md`. The July 12 state reconciliation is
`docs/project-catchup-2026-07-12.md`.

## What PCBSmith is

A fully deterministic prompt→PCB pipeline. One CLI command per
topology (`design-<name>-authority <output-dir> --request "..."`)
runs: intent classification → topology selection → closed-form design
calculators → evidence-backed circuit composition → KiCad schematic
generation (official symbols, label-net style) → kicad-cli ERC →
ngspice behavioral simulation → deterministic placement + hand-crafted
routing → virtual DRC (millisecond pre-filter) → kicad-cli DRC with
schematic parity → geometric design checks (the rulebook as code) →
review bundle with authority statuses, renders, and a revision plan.
Terminal-clean output is deliberately capped at `needs_human_review`.

There is NO LLM inside the pipeline. The AI (you) develops the
pipeline; the pipeline does the designing.

## Prehistory and the reset (2026-05)

The project was originally built with Codex (conversations lost in a
PC crash). A 2026-05-18 LM2596 buck attempt passed ERC/DRC but was
rejected by the user as "not a credible buck converter" — it was
geometrically legal and electrically meaningless. That failure defined
the project's philosophy: passing checks is not the same as being
right, so every claim needs either math, a datasheet locator, a
simulation, or an explicit "assumption" tag. The old generator was
archived (`old_files/r8-pre-restructure-snapshot-*`) and the project
restarted "circuit-first" with `docs/circuit-intelligence-roadmap.md`.

## The validation chain (2026-07-02)

- Divider+highpass+LED slice: first full authority chain with
  calculators, KiCad schematic, ERC, ngspice, review bundle.
- Evidence subsystem: sha-pinned datasheet cache + manifests; all five
  divider parts backed by real datasheets with page locators (commit
  `1c7e076` fixed extraction-job dedup found doing this). CLI:
  `evidence-add-local`, `evidence-acquire` (Nexar, needs creds),
  `evidence-extract`. LLM extraction clients exist (`evidence/llm.py`,
  Anthropic + OpenAI-compatible) but are dormant without keys.

## Board generation era (2026-07-02 .. 07-04)

- `kicad/board.py` (commit `aa75333`): netlist from kicad-cli kicadxml,
  embedded footprint geometry, row placement, two-layer Manhattan
  channel router, `run_kicad_drc` with schematic parity. First
  DRC+parity-clean board.
- Row intelligence (commits `b2bb025`, `f60f506`, `05f55a4`):
  net-span-minimizing part order, connectors pinned to edges, review
  PNG renders readable by the AI, versioned `outputs/<name>-rNNN`
  revision dirs. The LM2596 buck (13 parts incl. reference-design
  upgrades from a PCBWay community schematic) got a real PCB.
- Revision loop (commits `098053b`, `3ca0fa4`): structured
  ReviewFindings with rule ids, `design_checks.py` (connector edge,
  switching cluster, sensitive-net-under-inductor), `revision-plan`
  (patch/redo/escalate), human review comments via CLI, and the
  governance file `docs/ai-rule-suggestions.md`. The ratchet was proven
  live: a check written from one revision's flaw auto-caught it in the
  next.
- LED text-matrix board (commit `94b5eec`): first 2-D art layout; the
  "every net needs a label" kicad-cli discovery; series-LED polarity
  rule 7.1.
- Overnight batch (commits `2fcc2d3`..`762e93b`): official KiCad
  footprint import with verbatim embedding (the TOTAL-angle discovery),
  KiCad pin-convention alignment (pad1=cathode), escape routing for
  stacked connector pads, buck GND plane + thermal pour, corner
  mounting holes, buck evidence validation, schematic ladder builder.
  Renders gained real 3D models.
- MPU-6050 breakout (commit `700645b`): first multi-side IC; QFN
  nested-elbow escape planner, mirrored top routing channel, I2C
  pullup calculator; five live-DRC iterations each converted into a
  structural routing rule.

## Challenge-board era (2026-07-05 .. 07-06)

Each board was a user challenge chosen to break the tool somewhere new.

- **Clover** (commit `2d79a4a`): shaped outline (four-leaf clover),
  silk art + motto, parts on the BACK (flip transforms — inverse
  rotation then x-mirror), zones as shaped-board power, bezier
  traces-as-art. Live DRC 0/0.
- **Pear** (commit `5456fe4`): two-circle convex-hull outline with
  exact parallel inward offsets, 49 tangent-following LED units on
  three rings (arbitrary-angle rotation support), worm silkscreen with
  occlusion-clipped circles.
- **Metal detector** (commit `6e4483a`): first FUNCTIONAL copper — a
  20-turn exposed spiral as the Colpitts tank inductor. Spiral
  inductance calculator (Mohan current-sheet, Wheeler cross-check),
  copper-only components via NetTie, soldermask-opening graphics,
  rule 9.1 (no pour under a sensing coil), and an ngspice TRANSIENT
  startup measuring 1.136 MHz vs 1.137 MHz calculated; a simulated
  metal-proximity inductance shift moved it +23.6 kHz.

## Hardening waves (2026-07-06, plan `docs/hardening-and-generalization-plan.md`)

Triggered by a post-challenge audit: "the project technically works,
but only because it's you doing it."

- **Waves 0-1** (commits `c6c5f4d`, `ea2e0bd`): repo hygiene;
  `kicad/virtual_drc.py` — stadium-model courtyard / copper-clearance /
  edge / (later) pour-connectivity pre-filter, wired before every
  KiCad run; rules→checks (`outline_is_simple`, `copper_keepout`);
  convention probe tests; the GOLDEN SUITE (`tests/golden`, gated by
  `PCBSMITH_GOLDEN=1`) regenerating every topology live and asserting
  terminal-clean.
- **Waves 2-3** (commits `2753e82`, `47d5ef6`): the shaped-board
  toolkit extracted (`kicad/shaped_board.py`: Router, Pieces,
  splice_rect_tab, silk primitives); assembly-view artifact;
  `fab-package` CLI (gerbers/drill/positions/notes/BOM zip); IPC-2221
  trace-current rule 5.3; frontend contract doc.
- **Rule 7.3** (commit `a326ad4`): the "invisible forgotten IC pin"
  class (unwired pin = no ERC error, no DRC item) closed by the
  always-on `ic_pin_connectivity` check.
- **Track 6 — component onboarding** (commits `8e80713`, `e790ff2`,
  `5d55cf8`, `6c83b0e`): official SYMBOL import with
  extends-flattening (`kicad/symbols.py`); all IC exporters migrated to
  official symbols (PWR_FLAG semantics, native no-connects); component
  cards (`pcbsmith/components.py`, `ai_assets/components/*.json`) with
  pin requirement classes, must-tie enforcement (rule 7.4), required
  support parts (rule 7.5), card-driven NC whitelists; and the
  `onboard-component <mpn> --symbol --footprint` front door (live-tested
  on an NE555).
- **Final sweep** (commits `fc7ccf4`, `5f32b09`): `board-diff` — user
  KiCad edits become structured rule suggestions (live-tested on a
  hand-edited buck; every authority snapshots `layout.json`);
  pour-connectivity virtual check; green-LED datasheet fetched
  (assumption → datasheet_fact); DigiKey verdicts (old github lib =
  metadata seed only; reference site 403s curl).

## The flyback (2026-07-07, commit `179c775`) — first mains-isolated board

The user's "really difficult test": 120 VAC → 3.3 V / 0.5 A isolated
flyback. UCC28881 (SOIC-7, leads 6/7 absent for drain creepage),
custom TEZ-22x24 transformer, LMV431 + PC817 isolated feedback,
fusible resistor + MOV + discrete bridge + TVS input, RCD clamp,
Y-capacitor across the barrier. 92 x 50 mm two-layer: THT primary,
SMD secondary.

What it produced beyond the board itself:

- `solve_offline_flyback`: full DCM design chain from datasheet
  worst-case limits (bulk ripple → Dmax → Lp → turns ratio → stress
  checks → E24 divider), later extended with clamp dissipation.
- Rulebook **section 10 (galvanic isolation)**: 10.1 machine-checked
  pairwise creepage ≥ 6.4 mm + side discipline with straddle-part
  exemptions (`isolation_barrier` design check, blocker); 10.2 the
  barrier drawn on silk; 10.3 barrier-crossing parts chosen for the
  barrier. No pours on isolated boards.
- Custom evidence-backed symbols + sidecar library; component cards
  for UCC28881 and LMV431; card validation extended to custom symbols.
- **Tool defects the challenge exposed and fixed**: `fp_circle`
  parsed as two points degenerated radial-can courtyards to a LINE
  (virtual DRC blind to the exact conflicts KiCad found) → exact
  F.CrtYd CONVEX HULLS (circles sampled as 24-gons); bboxes
  false-positive on rounded courtyards (TO-92, caught by golden) →
  hulls, not bboxes; dense-layout silk labels → `part_reference_at`
  label repositioning; ALL DRC warnings fail the board stage.
- The layout cost six KiCad round trips on silkscreen alone and a
  courtyard crisis that physically forced the board from 86 to 92 mm
  (two radial bulk cans between the bridge pads and the transformer
  body). Both pains drove the next day's work.

## Reference-driven hardening (2026-07-07, commit `bc074d2`)

The user supplied NWES's FLBACK-001 Rev B — a professional Altium
build of the SAME circuit (also copied to `outputs/FLBACK-001-RevB`).
Analysis: `docs/reference-comparisons/flback-001-vs-flyback-r001.md`.

- It VALIDATES our architecture: identical UCC28881 pin map, same
  feedback chain, same fusible-resistor input strategy, same barrier
  Y-cap. Our divider and theirs solve the same equation.
- It exposes the r002 backlog: ONE 450 V bulk cap (kills the 92 mm
  growth), integrated MiniDIP bridge, X2 + line-to-earth Y-caps +
  earth pad front end, rated clamp parts (56K 2 W / 250 V / MURS160),
  test points, DNP as a BOM state, dual-side assembly (their entire
  SMD control circuit is on the bottom; 80.4 x 36.8 mm vs our
  92 x 50), transformer spec in the BOM row (EFD20/10/7, N49, 69:4 —
  a lower-VOR design point than ours).
- Built from it: **`pcbsmith ingest-reference`** (`pcbsmith/
  references.py`) — Altium output packs become stored records
  (BOM xlsx parsed as zip+XML, .DRR drill tables, **ODB++ component
  placements** in mm per side, PDF text) under `ai_assets/references/`;
  FLBACK-001 is ingested (28 BOM rows, 48 holes, 36 placements).
  **Virtual silkscreen checks** (labels/texts/lines vs pads, fab
  hulls, and each other) — the six flyback round trips now cost
  milliseconds. **Professional fab notes** (numbered spec, drill table
  with PTH/NPTH counts, assembly block, dual-unit extents). DNP BOM
  annotation. Clamp-dissipation warning.

## State at handoff (2026-07-07, HEAD `bc074d2`, branch codex/circuit-intelligence-slice)

- 9 topologies regenerate terminal-clean in the golden suite: divider,
  buck, led-art, mpu6050, clover, pear, detector, flyback (+ the suite
  itself asserts DRC 0/0 and bundle status for each).
- 335 collected tests (327 run by default, golden gated), ruff and
  strict mypy clean.
- Virtual DRC checks: copper_clearance, courtyard_overlap (exact
  hulls), edge_clearance, pour_connectivity, silk_overlap,
  silk_over_pad.
- Design checks (rulebook as code): connector_edge, switching_cluster,
  sensitive_net_under_inductor, series_led_polarity,
  outline_is_simple, copper_keepout, trace_current,
  ic_pin_connectivity, component_card_contract, required_support,
  isolation_barrier.
- CLI surface: 8 design authorities + evidence-*, onboard-component,
  board-diff, fab-package, revision-plan, review-comment,
  ingest-reference, datasheet-facts.
- Open, needs environment: live Nexar BOM (credentials), LLM datasheet
  extraction (API key or local server), DigiKey reference site
  (browser).
- Open, next code work: flyback r002 (reference-driven redesign),
  A* assisted routing (plan 2.3 — the biggest lever), polygon-exact
  pour analysis, remaining passive-exporter migrations, local-model
  harness spike (plan 4.7).
- Open question for the user: the intent behind their hand-moved buck
  D1 (+0.47, −6.50 mm) before promoting a placement rule.

## Track 8 + the automation-routed servo tester (2026-07-07 .. 07-08)

Track 8 landed in full: the deterministic review pack (block diagram,
test plan, FMEA, pin tables, BOM lint), the layout scorecard
(`layout_score.py`, hard gates + track/via/bbox cost), the A* router
(`astar_router.py`: `route_net`/`route_board` with shortest-first
ordering and rip-up-by-reorder), placement search
(`placement_search.py`: courtyard+silk pre-gate, 1-2-part local moves),
the topology forge (`ai/topology_forge.py`, propose-verify-refine
against a local LLM), and the proven-module registry
(`generation/blocks.py`). Landmarks: `route_board` routed the whole
flyback from bare placements in 14 s beating the hand layout
(731 mm/8 vias vs 754 mm/10 vias) and the scorer caught the router's
first creepage violation, which became `clearance_groups_from_spec`.

The 555 servo tester (`design-servo555-authority`, golden topology #9)
was the first board designed automation-first: composition placed the
parts coarsely, `route_board` produced every trace. The live loop
(probe pre-gate -> route -> kicad-cli DRC) converged in three
iterations and each failure became machinery:

- kicad-cli caught routes cutting the corners of RECT pads (square
  pin-1 markers) that the stadium model underestimates -> the router
  now inflates rect/roundrect FOREIGN obstacles to min_dim/sqrt(2)
  (`cover_rect_pads`), own-net pads stay exact.
- SW_PUSH's duplicate pad numbers (two physical "1" pads) were left
  half-unrouted by label-keyed dedupe -> router terminals key by
  (label, position); new `pad_connectivity` virtual check asserts
  every physical pad of a multi-pad net touches same-net copper.
- Silk failures (0.7 mm text under the 0.8 mm board minimum, a rotated
  connector ref walking off the board edge, KiCad's real ~1.9x-size
  text boxes overlapping part outlines) -> new `silk_text_height` and
  `silk_edge_clearance` virtual checks, and the board grew 52x38 ->
  56x40 so every component value fits on silk in measured corridors.

Circuit side: NE555 card from the sha-pinned TI datasheet (SLFS022),
`solve_555_servo_tester` (astable per 6.3.2: FORWARD 4.712 ms at
85.4 Hz, REVERSE 0.693 ms at 272.3 Hz — an END-STOP tester by design,
flagged), the schematic's 10n-vs-100n CONT-pin discrepancy surfaced as
a composition finding per the user's request, BC547 inverter stage
simulated (saturation 22 mV, rail pull-up 5.19 V, pulse width within
0.3% of design). Final state: ERC passed, sim passed, kicad-cli DRC
0 violations / 0 unconnected, design review passed, fab package
exported, bundle at needs_human_review.

## Trace craft, flyback compaction, and reader schematics (2026-07-10)

The user rejected the servo555 trace appearance and required reusable trace
craft. The old dimmer was only a 45-degree bend example; the real target is
ordered river routing: local pin escapes gather into uniform-pitch shared
corridors, bend together, and fan out near destinations. The routing tree had
failed to absorb connected pad copper, making 44% of servo segments redundant.
Rule 11 now enforces route -> smooth -> merge -> prune, no acute joints outside
pad copper, and no fully covered copper. Reader schematics with live ERC and
netlist equality exist for servo555, flyback, and thermometer. The 80 x 42 mm
dual-side flyback result remains an experimental compaction path, not a separate
promoted authority.

## Thermometer challenge - board failed (2026-07-10)

The 63-part thermometer topology landed evidence, calculators, composition,
machine and reader schematics, simulation, authority CLI, and fast tests. It did
not land a routed board. Seven long attempts failed on different nets in the
24 mm stem; after more than two hours the user stopped the run and correctly
called the main test a failure. A superseded routed preview is not authority.
The sequence established the ceiling of per-net sequential A* and produced
reusable fixes for custom-pad extents, NPTH holes, via-edge masks, project
minimum holes, and fine-pitch routing. Thermometer r002 remains gated on global
congestion/capacity routing and placement compatibility.

## Research-first layout rebuild and book knowledge base (2026-07-11 .. 07-12)

The user redirected the project to reputable-source research before more board
iteration. The original nine sources were extracted or OCR'd, distilled, and
spot-verified across 72 rules; five corrections, one dimensional-analysis
adjudication, and remaining ambiguities were recorded. `CONSOLIDATED.md`
resolves cross-book dockets. Phase 0 is complete. A second wave of 16 acquired
sources is distilled in `docs/reference/books/SECOND-WAVE-2026-07.md`. The next
engineering phase is the shared rules/current-capacity cleanup, followed by the
revised routing order in `docs/routing-placement-research-update-2026-07-12.md`.

## R1 solder-mask fabrication slice (2026-07-15)

The repository gained an engine-neutral exact solder-mask geometry kernel for
discs, capsules, oriented/rounded rectangles, convex polygons, and compound
unions. Concave polygons are rejected unless the caller supplies an explicit
convex compound. Footprint parsing now losslessly retains pad mask layers, the
original source anchor, round-rect/chamfer data, local margin and ratio clauses,
and canonical custom-pad source clauses. A typed front-side board-disc bridge
keeps the detector opening's historical 96-point KiCad rendering and stable UUID.

A local KiCad 10.0.3 probe retained 87 hash-covered fixtures, Gerbers, reports,
measurements, commands, and patches plus their manifest. The complete 88-file
bundle is durable at `docs/reference/fixtures/kicad-mask-parity-10.0.3/`;
`hashes.sha256` covers every retained artifact except itself, and the manifest's
SHA-256 is
`22B8B15D93D1E3472B7222E9A8FB55D7908D73DC5ABAB1BA69084C62A96BDF14`.
The corpus proves that board `pad_to_mask_clearance` supplies global expansion,
a non-zero local margin replaces it, local zero inherits it, mask membership is
side-specific, and KiCad 10.0.3 rejects `solder_mask_margin_ratio`. It also pins
per-side via `inherit|tented|open` serialization to `none|yes|no` and Gerber
behavior.

The exact collector now feeds profile-scoped `fab.solder_mask_web`,
`fab.mask_aperture_merge`, and `fab.solder_mask_web_unverified` findings. Raw
board/footprint mask strings, exact custom/chamfered aperture geometry, ratio
clauses, missing expansion, and inherited via policy cannot silently pass; they
remain unsupported or require human review. At that mask-kernel checkpoint, the
KiCad and full suites were green with nine gated golden skips, and Ruff plus
strict mypy were clean.

The subsequent R1 exposure slice added stable outer-copper identities,
source-derived roles, per-side final-aperture exposure classification, active
ordinary pairwise role/mask-state selectors, the deterministic
`ordinary_pairwise_clearance_scope_unverified` finding, and the design-report
`outer_copper_exposure` / `fab.copper_exposure_unverified` gate. Unsupported
apertures without a quantitative error contract conservatively poison the whole
same side for any result not already proven fully exposed; bounded
approximations use their `maximum_error_mm` envelope. Focused validation was 106
passed for the R1 exposure/selector set and 26 passed for the report/design-check
set. The later full authority run completed with all collected tests green in
226.4 seconds, nine intentional live/golden skips, and only the known
pytest-cache permission warning. Strict mypy was clean over 117 source files.
Exact custom/footprint mask graphics and electrical-insulation,
safety-clearance, and creepage authority remain open.

R2 then completed through the R2.3b in-memory board proof. R2.1 added canonical
capacity-one resources, whole-net occupancy, pair-specific clearance domains,
deterministic overuse/fingerprints, and exact arbitrary-segment raster claims.
R2.2a added the deterministic synthetic candidate-graph negotiation kernel;
R2.2b adapted the real grid search without changing legacy routing. R2.3a added
board orchestration, complete-net transactional rip-up/restore, history and
stagnation, fixed budgets, truthful schema-v2 telemetry, zero-overuse success,
and a separate exact-check callback.

R2.3b added `tests/unit/kicad/test_negotiated_board_maze.py`, a real one-layer
in-memory geometry maze in which both legacy net-order permutations fail. The
negotiated route repeats exactly, converges in three passes with total overuse
`4 -> 5 -> 0`, consumes 16,427 expansions, and pins these pass fingerprints:
`6bf59d7fec8031f984f13102bc4a5dd112b53b4dc81c4f212bf13c5fba733a71`,
`1884e9fd36b5af6a57709cf1311e8a7b31d4ec6c4328618bd2c620a1fa67234b`, and
`0734b8883000f8c4460be48bdb3e387afd10022bee24a8af28c8bc26fd394161`.
The deterministic in-memory exact checker accepts connected, clear, front-layer,
via-free copper. This is not a serialized KiCad fixture or exact KiCad DRC. The
negotiated cluster was 66 passed before the maze addition; the maze is 3 passed.

Legacy `route_board` remains unchanged and default. R2.4a added a separate
compact real two-resistor negotiated board whose deterministic serialized KiCad
bytes have SHA-256
`e91a7464d702c821f6ac0bb659a30bd39ccecdbe52e79167164650ce907dc628`.
Repository S-expression and placement read-back plus preservation of every
non-route `BoardLayout` field are pinned. Its version-aware opt-in exact KiCad
10.0.3 DRC passed locally. This is a serialization/tool-authority gate, not the
adversarial maze proof. R2.4 therefore remains partially complete: a
legal-geometry serialized adversarial board, measured performance/quality
corpus, and deliberate caller/default migration are still open. No superiority
claim is supported.

R3.1 then implemented the engine-neutral corridor IR, canonical identities and
validation, and the heterogeneous quantity/capacity ledger. Its terminal-owner
extension brought that slice to 21 focused tests. R3.2 added the exact/simple
KiCad corridor graph adapter with 14 focused tests, for a pre-R3.3 combined
R3.1/R3.2 checkpoint of 35 passed. It handles rectangular and concave outer outlines, conservative
full-cell classification, terminal/layer ownership, orthogonal portals, center
via sites, fixed copper/holes/zones, and profile-sensitive capacity. Opaque raw
graphics and target-net zones are explicit unsupported geometry rather than
numeric success. The empty-board graph and build-result fingerprints are pinned
as `18792a2bded9dd69bc83f2bf7f270762696216904542c1e82d5be107e418f79a`
and `6b0b5bab0591a2bb76b07ae99e8c6db0965c4eb4ddd99f1e0dbb60b5a5bff392`.

R3.3 then added exact typed `BoardLayout` cutout polygons with strict canonical,
containment, boundary, and mutual-intersection validation. Legal closed Edge.Cuts
`gr_poly` serialization uses semantic UUIDs, and the corridor adapter excludes
every cutout exactly from both copper-layer cells and center-via sites. The
empty-default board serialization remains byte-identical. This slice also fixed
the exact segment-to-cell test's asymmetric endpoint-distance defect by using a
symmetric segment-distance predicate. Bounded approximation is deliberately
deferred because the current model has no real two-sided uncertainty input
carrier. Validation completed with 38 focused and 62 broader tests.

R3.4 then implemented the engine-neutral deterministic negotiated allocator for
complete multi-terminal coarse trees. It charges heterogeneous integer demand
against portal/via-site quantities, uses whole-demand transactional replacement
with present/history costs, and honors forbidden, allowed, and required via
policies including zero-work demands. Typed geometry/unsupported/terminal/
capacity/budget/stagnation failures, per-demand attempt telemetry, run-context
fingerprints, and canonical pass/result identities preserve exact accounting and
reproducibility. Literal first-order and cascading second-order fixtures pin the
overuse sequence, expansion counts, convergence, rollback, and one-less-budget
failure state; the dedicated allocator matrix is 19 focused tests.

R3.5 then introduced one shared canonical executable air-clearance-domain builder
for R2 and R3. Conservative corridor demand considers only pairwise endpoints
that both became actual multi-terminal demands, takes the maximum ordinary and
applicable clearance, and retains all applicable domain IDs. Same-side nets and
absent or single-terminal counterparts remain unaffected. Because the copper is
not yet emitted, role/mask selectors and component exemptions cannot narrow the
coarse demand. Qualified air-clearance is added once; creepage is excluded from
the Euclidean routing model. Exact `Decimal` ceiling replaced epsilon-biased
float rounding so quantum-boundary demand cannot be under-reserved.

The historical R3.4 focused checkpoint was 85 passed. The completed R3.5 combined
R2/R3 authority is 104 passed, including corridor-planner 26/26. The full suite
at that pre-R3.6 checkpoint was green in 195.4 seconds with ten intentional
live/golden skips and only the known pytest-cache warning; strict mypy was clean
over 122 source files and focused Ruff was clean. This is the historical
pre-R3.6 full-suite checkpoint.

R3.6 then implemented opt-in soft realization of coarse corridor allocations.
Versioned coarse guide and guidance-report artifacts are projected into a
versioned KiCad-grid guide with transition-precise selected-portal and selected-
via preferences. A separately accounted non-negative guidance cost steers
detailed R2 search without changing hard geometry legality, the admissible
heuristic, physical resource claims, or the existing pad-stub exemption.
`RoutingRunResult` remains schema v2: detailed algorithmic success still means
no unresolved nets and zero detailed overuse, while exact-check acceptance is a
separate authority.

The opt-in board wrapper records `ABSENT`, `PLAN_NOT_READY`, `INCOMPLETE_INPUT`,
`INCOMPATIBLE`, or `APPLIED`. Missing, failed, incomplete, mismatched, unsupported,
and stale guidance all fall back to ordinary unguided R2. Before applying a
ready plan, the wrapper rebuilds the current layout's corridor graph and requires
an exact fingerprint match. The broader R2/R3 cluster was 122 passed before
final strengthening, and the focused post-golden R3.6 set is 60 passed. The
definitive post-R3.6 full suite is green in 229 seconds with ten intentional
skips and only the known pytest-cache warning; strict mypy is clean over 124
source files. The real shaped U-board golden pins 29 coarse and 4,876
detailed expansions, five front-copper segments, no vias, clean virtual DRC and
connectivity, use of the lower bottleneck, and stable graph, plan, guide, and
routing-run fingerprints. At this R3.6 checkpoint, R3.7 routability integration
still remained next and corridor-guidance failure was not proof of physical
unroutability. The later 2026-07-16 checkpoint below supersedes that historical
status for R3.7, R3.8, and the bounded R4 slices.


## Fine/ordinary exchange, placement summary, and ordered-bus foundation (2026-07-16)

R3.7 closed the fine/ordinary exchange seam without mutating earlier corridor
records or fingerprints. Versioned exchange demands describe deterministic
fine-prefix alternatives, exit layer/via and prefix-owned resource claims. The
negotiated exchange allocator can replace a locally shortest blocking escape
with a longer alternative while ordinary demands remain in the same capacity
ledger. Canonical `GridRoutePrefix` records validate exact connected prefix
copper, anchors, exit, grid, width, vias, and fingerprints; detailed R2 seeds
the selected prefix as part of the same complete-net transaction. The final
board wrapper binds compatible exchange selection, prefix, and soft guidance
once; non-ready or incompatible input falls back fail-honestly to ordinary R2,
and exact-check acceptance remains separate. The convergence fixture pins pass
fingerprints `438d2942596392c63ee5c025c61fb2ac0303e2e40dbe0b8f328eef974d5b6049`
and `2a8f56304e54908f36c78b642fe21a52d78a6678e3fb17df981c49944b77d474`,
plus result fingerprint
`fc6162c17f5ed9be569e2e36f4d642e62c41f6a12dc7c3e32fbf1eedc1cba499`.

R3.8 added the read-only `CorridorPlanSummary` placement-surrogate seam. It
validates exact graph, demand, and plan identities and reports geometry issues,
readiness/failure, unresolved demands, work, guaranteed capacity, committed
demand, and overflow separately for channels and via sites. It does not rank,
rewrite, or mutate placement candidates; full R5 integration remains future
work.

R4.0 added engine-neutral bus declarations and the R3 capacity-certificate
handshake. It validates unique bus/member/terminal/boundary identities, connected
activity intervals, exact permutation/swap/layer/via/fallback declarations,
evidence authority for timing/coupling/coherence budgets, terminal ownership,
minimum width, freshness, grid, portal, and window references. It performs no
routing.

R4.1a/b then added deterministic semantic lane allocation. Schema-v2 results
support same/reversed order, exact declared boundary permutations, bounded
adjacent swaps only in certificate-listed windows, source/tap/sink activation
and deactivation, and certified semantic layer transitions respecting
synchronous, declared-window, independent-bounded, forbidden, per-member via,
and spread policy. No physical transition via is emitted. Fixed state budgets
are checked before every swap or lane-state expansion. The straight fixture pins
result fingerprint `3417223856291e6ce0ff43939468d84d18f222070bc94ff5383b57a261c359e1`
and allocation-decision fingerprint
`34190f2212eedabeae24186cd6a855e55e20585712e7c8a04c3f0c5f27eb4366`;
the combined bus-IR/allocator matrix was 61 passed. Exact declared permutation
and one-member outlier-transition fixtures are separate: a genuine combined
LCS/disordered-pin-row optimizer is not implemented. Hard pairwise pitch
enforcement is also open.

R4.2a now realizes exact caller-certified trunk centerlines only. It validates
keep-ins and exact bus/allocation/certificate/profile/geometry-registry bindings,
emits straight/one-bend/multi-bend trunk segments, tracks active section subsets,
and reconstructs ordinary and pairwise R2 claims. It performs no search, emits
no pigtails or transition vias, mutates no board, and gives no acceptance
verdict. The straight fixture pins geometry
`3667a89d37849bc4b17166bca1f5fbf769e983ca053da489fcc5e601f0b9a852`,
claims `003bcd7fb5e0b117913e407a2aaa4b19152726981cb4dd59f40a8abf88ab3195`,
and realization `7f50715d306290fc8906027bffc0cf5929d7f5e652491cd158c3b22f5a644bc1`.
R4.2b adds an atomic whole-bus ledger/route-map replacement coordinator. It
commits every member together or restores exact old routes, claims, and
fingerprints after late failure or exception. Its commit telemetry exposes
overuse but is not exact-check acceptance; the fixture bundle pins
`8e137ab2503406ca2983a7f0bc17b43fefa0ce003951e55f88ae14ec3eac121e`.

R4.2c integration is in progress. Generated pigtail search, physical transition-
via geometry, complete trunk/pigtail/via claim reconstruction, board
materialization, negotiated retry, exact-checked atomic commit, R4.3
group/ordinary negotiation, thermometer pilots, and production/default caller
migration are not complete. Do not infer them from the R4.2a/b primitives.


## Complete thermometer proof and process postmortem (2026-07-18)

The production thermometer proof ultimately completed as R005: 63 netlisted
components, 64 placements, 53 routed nets, 567 segments, 99 vias, zero
unconnected items, clean machine/reader ERC, clean KiCad DRC/parity, identical
R004/R005 normalized copper, byte-identical repeated KiCad saves, and inspected
front/back/perspective/routing/assembly images. The user's larger-bulb correction
produced a 66 x 178 mm board with a 60 mm bulb and 24 mm stem and materially
improved both realism and routability.

R006 then proved 3D metadata can be added without changing copper. It exposed a
silent missing SHT31 STEP reference and the difference between header-only and
complete OLED module models; its scaled SHT31/Adafruit assets remain explicitly
labelled visualization proxies. The active roadmap and Track 6.5 now require a
source/checksum/license-bound 3D asset resolver and model preflight.

The result was accepted as a proof of concept, not as an ideal workflow. The
complete issue register, root-cause analysis, qualified agreement/disagreement
with the user's critique, and P0/P1 remediation order are retained in
`docs/thermometer-production-postmortem-2026-07-18.md`. Its P0 items are now
prerequisites in `docs/routing-placement-plan.md` before another production-sized
shaped-board exercise.

## Standardized visual-review roadmap (2026-07-18)

The active routing roadmap now treats visual evidence as a versioned production
artifact rather than an informal screenshot step. P0-V specifies a dedicated
`review/` tree, physical-scale-aware 4K-or-greater overviews, constant-scale
zoomed tiles, layer-isolated KiCad views, fixed-camera 3D views, comparisons,
diagnostics, a render manifest, and a recorded inspection verdict. The same
roadmap now has an audited checkbox ledger: completed generic slices are marked
without conflating them with still-open production/default adoption work.

## Evidence-utilization policy and Books reconciliation (2026-07-18)

The roadmap now prioritizes short source-to-production vertical slices over
another broad reading wave while R2-R7 production integration remains open. A
durable guide defines source precedence, acquisition gates, revision handling,
the status ladder from discovery to production exercise, and session reminders.

The local Books audit confirmed that IPC-7352 May 2023 and IEC 60664-1:2020 were
already present, pinned, and duplicated byte-identically. It newly verified full
older IPC-2222 original (1998) and IEC 62368-1 Edition 2.0 (2014) copies.
The later 2026-07-18 intake added full IPC-2152, IPC-7093/7093A, IPC-TM-650,
IPC-2221A, and IPC-7525 original sources. The official Sensirion Version 2
design guide and USB-IF USB 2.0 June 2025 bundle were then downloaded
automatically, hashed, and visually verified. The guide and USB base
specification were registered, and the complete archive was inventoried. The
file initially presented as IPC-2231A was verified as IPC-2221A and is now
correctly named.
The older purported IPC-2231A and IPC-7525C preview files contain mismatched
IPC-1401 material and are not counted.

## Thermometer closure and Phase 10 continuity reset (2026-07-20)

The user confirmed that the thermometer is accomplished. R005 remains the
accepted routed electrical proof-of-concept and R006 the separate proxy-3D
pilot; the project will not be rerun merely to retrofit newer generic R2-R6
machinery. That machinery will instead face a genuinely unseen future project,
which is stronger evidence against project-specific hard-coding.

The prior long handoff was archived verbatim and removed from the mandatory
reading path after its volatile claims became stale. A short live bootstrap now
points to `docs/current-state.md`, the active roadmap, stable handbook, and
current source authorities. Completed roadmap scopes are frozen; new work begins
at Phase 10, while factual defects receive dated errata rather than being hidden
to preserve a checkbox.

Phase 10 covers continuity, truthful R005 authority labelling, Python/tooling
normalization, and one verification checkpoint. Phase 11 covers local-first
source metadata/derived facts, rights-aware 3D assets, and standardized visual
review. Phase 12 covers long-job observability and budgets, one verification
orchestrator, and a later contract-based test-suite audit.

## Phase 11/12 generic pre-project foundation (2026-07-20)

> **2026-07-20 integration correction:** “foundation” below means callable
> libraries and CLI entrypoints, not automatic use by production board scripts.
> The failed Retro-Pad pilot bypassed post-placement review and the execution
> orchestrator. Its audit and Phase 13 corrective work are recorded in
> `roadmap-implementation-audit-2026-07-20.md`; this historical section must not
> be read as unseen-board proof.

Before requesting the next unseen board, PCBSmith gained a controlled source
intake boundary with private and commit-safe manifests, validated local KiCad
symbol/footprint/model installation, model-path and classification preflight,
and deterministic PNG adapters for physical board outlines and explicitly
transformed silkscreen artwork. The visual-review package now emits hashed 4K
overviews, layer-isolated views, tiles/details, declared overlays and
diagnostics, fixed populated/bare 3D cameras, and predecessor comparisons. Its
initial state is always pending inspection and a named reviewer must record the
artifact decisions.

The execution core now exposes quick, standard, and deep profiles with separate
algorithmic work budgets and machine-safety limits, heartbeat evidence, typed
termination, and complete-gate checkpoints. A single verification orchestrator
reuses the existing lock, Ruff, mypy, pytest, and golden gates. Its final
standard checkpoint passed all 2,590 collected tests with warnings treated as
errors in 512 seconds, strict mypy over 239 source files, Ruff, and the lock
check. The pytest job peaked at 2,381,729,792 bytes under an enforced 4 GiB
ceiling. The earlier Hypothesis timing incident did not recur, but remains an
input to the later test-health audit rather than being silently dismissed.

An existing bunny board served only as an infrastructure smoke test: its review
generator produced 36 required artifacts and stayed pending inspection, while
model preflight correctly reported 70 unresolved LED model references. This is
not evidence of generic board-design acceptance. The next proof is the user's
new two-layer IC/sensor board with its supplied outline and silkscreen artwork.
