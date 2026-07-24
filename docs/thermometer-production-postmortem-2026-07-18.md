# Thermometer production-board postmortem (R002-R006)

Date: 2026-07-18

Scope: the complete thermometer PCB effort culminating in the accepted R005
electrical board and the R006 3D-model visualization pilot.

> **Project closure (2026-07-20):** The user confirmed that the thermometer is
> accomplished and must not be rerun merely to retrofit newer generic routing or
> placement authorities. The `P0`/`P1` headings below are postmortem priority
> classes, not roadmap phase identifiers. Their reusable workflow requirements
> are scheduled under new Phases 10-12 in the active roadmap. The historical P1
> proposal to migrate this specific thermometer is superseded; generality will
> be tested on the next unseen project.

## Outcome

The effort eventually produced a complete 66 x 178 mm KiCad project with a
60 mm bulb, 24 mm stem, 63 netlisted components, 64 board placements, 53 routed
nets, 567 segments, 99 vias, zero unconnected items, clean machine and reader
ERC, clean KiCad DRC, deterministic copper replay, byte-identical repeated
KiCad saves, inspected front/back/perspective/routing/assembly images, and a
separate R006 3D-model pilot. The user accepts this as a proof-of-concept
success.

The process was not acceptable as a mature production workflow. The user
reports approximately one hour for the first failed session and two hours for
the second failed session before the result was accepted. Much of that time was
spent discovering deficiencies that should have been automatic preflight
findings, waiting on opaque full-board routing attempts, creating missing
inspection artifacts after the fact, and repairing stale board-specific test
assumptions.

## Assessment of the user's critique

The following criticisms are correct:

- Visual inspection happened too late. The original handoff explicitly required
  rendered front and back inspection, so this was an execution failure, not an
  ambiguous requirement.
- The first failed state did not provide an inspectable `.kicad_pcb` or the
  expected review images. The pipeline withheld the board because routing had
  not completed, which made useful review unnecessarily dependent on routing.
- Several verification steps were implemented or orchestrated as one-off tools
  and manual probes even though the mature form belongs in generic rules,
  authority reports, and one standard verification command.
- Absolute production coordinates and golden fingerprints in the historical
  `/PWLED` pilot were not updated when the bulb and D17/R17 placement changed.
  The dependency was discovered only during the late full regression run.
- Missing and incomplete 3D assets were not detected automatically. KiCad
  silently omitted the unresolved SHT31 model, while the OLED footprints showed
  headers rather than complete modules.
- Runtime and operator feedback were poor. Full routing attempts took tens of
  minutes with almost no progress telemetry, and multiple attempts were needed.

One nuance is important: writing tests was not inherently wasteful. Tests were
appropriate for the new ordered-bus terminal declarations, geometry contracts,
and the changed historical pilot. The pilot tests correctly refused a crop that
no longer contained the production D17/R17 positions. The problem was the
architecture and timing: duplicated absolute facts made the break predictable,
the invalidation was not surfaced during placement preflight, and the full
suite was first run only after the expensive board work. New tests should prove
generic capability and stable contracts; ordinary board instances should be
verified mainly by data-driven rules and automatically generated evidence.

Visual inspection also cannot be replaced entirely by rules. DRC and semantic
checks cannot judge whether the board reads as a thermometer, whether labels
are visually balanced, or whether a 3D module looks obviously mirrored. The
correct workflow is automatic rendering plus mandatory recorded visual review,
not visual review instead of deterministic checks.

## Detailed issue register

### A. Missing early artifacts and delayed visual review

#### A1. No inspectable PCB after the first failed route

- Symptom: the user received neither a `.kicad_pcb` nor the expected review
  images when routing failed.
- Root cause: `generate_thermometer_board` serialized only after
  `compute_thermometer_board_layout` returned a complete route. Routing failure
  therefore prevented persistence of the otherwise useful placement and board
  geometry.
- Impact: the user could not inspect proportions, component placement, antenna
  orientation, OLED envelopes, sensor isolation, or silkscreen while routing
  work continued.
- Workaround used: `tools/export_thermometer_review_candidate.py` was added to
  write an explicitly unrouted R002 candidate and render top, bottom,
  perspective, routing-review, and assembly-review artifacts.
- Permanent correction: every board authority run must persist a status-labelled
  placement PCB and review renders before routing begins. The output must say
  `unrouted_review_only` and must never be confused with a fabrication-ready
  board.

#### A2. Visual inspection was performed only after the user asked for it

- Symptom: visual deficiencies and missing artifacts were not discovered in the
  first delivery.
- Root cause: the work followed parser, routing, and DRC feedback before
  enforcing the handoff's mandatory image-generation-and-inspection gate.
- Impact: obvious presentation and mechanical issues were found later than they
  should have been.
- Permanent correction: render placement review immediately; render the exact
  routed saved board after KiCad read-back; record a structured visual-review
  attestation with image hashes and findings before a board can be called ready.

#### A3. Review artifacts were incomplete or inconsistently named

- Symptom: the normal authority path emitted top/bottom/perspective and one
  general review plot, but not the explicit assembly/routing filenames expected
  from the bunny-board precedent.
- Workaround used: the final routing review was copied to an explicit
  `routing-review` name, and an assembly review from the identical placement
  authority was copied into R005.
- Permanent correction: the board authority must always emit a standard set:
  placement, assembly, routing, front, back, perspective, sensor close-up,
  antenna close-up, connector close-up, and a manifest tying each image to the
  saved board/layout fingerprint.

#### A4. Small critical parts were hard to see in whole-board renders

- Symptom: even after U4 had a model, a physically correct 2.5 mm SHT31 is tiny
  in a full 178 mm board render.
- Permanent correction: automatic detail renders should be driven by component
  roles and review rules. Sensors, fine-pitch connectors, antennas, isolation
  barriers, and externally mating modules need close-up images in addition to
  whole-board views.

### B. Routing architecture and performance

#### B1. The production thermometer still used the legacy hard-blocking router

- Symptom: `compute_thermometer_board_layout` called legacy `route_board` rather
  than the accepted R2-R6 negotiated/corridor/exact-commit chain requested by
  the original mission.
- Partial improvement: executable ordered groups were added for 16 SEG nets,
  16 LK nets, and four shift-control nets, with live terminal-drift validation.
- Remaining gap: those declarations did not make the full production caller use
  negotiated congestion, ordered transition authority, exact checked commit,
  and persisted R2-R6 telemetry.
- Impact: completion depended on placement and board enlargement giving the
  legacy router enough space, rather than on the intended generic capacity and
  exchange machinery.
- Permanent correction: migrate the production thermometer caller only after a
  bounded full-board R2-R6 acceptance fixture passes and persists its run
  result, exact commit, replay evidence, and zero-overuse ledger.

#### B2. Full route attempts were slow and opaque

- Evidence: successful full-board runs took about 23 minutes (R004) and
  30 minutes (R005). Earlier failed permutations also consumed substantial
  time. The CLI buffered almost all output until completion.
- Impact: there was no useful per-net progress, remaining-work estimate,
  congestion hotspot report, or early reason to abort an unproductive attempt.
- Permanent correction:
  - emit per-pass/per-net telemetry and a heartbeat;
  - persist checkpoints after fine-pitch and control/bus phases;
  - enforce elapsed-time, expansion, and memory budgets;
  - expose the current failed net and blocking resources;
  - reuse accepted unaffected routes after artwork or local geometry changes;
  - stop before a full solve when capacity/preflight proves the corridor
    impossible.

#### B3. A negotiated diagnostic probe consumed excessive memory without acceptance

- Symptom: one control-group negotiated probe grew to multi-gigabyte state
  (approximately 7 GB observed during the attempt) without producing an
  accepted result.
- Root cause: the diagnostic search space and evidence retention were too large
  for a bounded full-stem probe, and resource ceilings did not terminate it
  early enough.
- Permanent correction: hard resident-memory limits, compact telemetry,
  checkpoint pruning, bounded corridor subsets, and explicit
  `memory_budget_exceeded` failure evidence.

#### B4. Fine-grid scope was initially too broad

- Symptom: VCC and other global trees were promoted to the expensive 0.1 mm
  graph because they touched fine-pitch parts.
- Evidence-based correction: live probes showed only USB `/DP`, `/DM`, `/CC1`,
  and `/CC2` lacked legal 0.2 mm pad-entry cells. SHT31, TSSOP, rail, and cascade
  pads had legal main-grid entries.
- Impact: routing time and congestion grew without necessity.
- Permanent correction: derive fine-grid promotion per terminal escape, not per
  entire net; return to the coarse/main grid immediately after a proven escape.

#### B5. Control-net order created antagonistic failures

- Symptom: routing `/SER` first caused `/OE` to fail; routing `/OE` first could
  cause `/SER` to fail on the original narrow placement.
- Root cause: the long narrow stem was a single shared corridor, while the
  legacy router committed nets greedily and did not negotiate capacity.
- Resolution used: enlarge the bulb, move module support circuitry out of the
  lower stem, and give the control trunks more room.
- Permanent correction: capacity planning and whole-net negotiated rip-up must
  decide corridor ownership before detailed traces are committed.

#### B6. The original proportions created avoidable congestion

- Symptom: the earlier 46 x 158 mm board with a 42 mm bulb left limited space
  for the controller support field, displays, sensor, USB, and route escapes.
- User correction: a much larger round bulb would look more realistic and offer
  more working area.
- Resolution: 66 x 178 mm board, 60 mm bulb, 24 mm stem, 2.5:1 bulb-to-stem
  ratio. This was both aesthetically and electrically better.
- Permanent correction: aesthetic/mechanical proportion candidates must be
  scored for routable capacity before detailed routing. A user-visible shape
  choice should not be treated as decoration separate from placement capacity.

### C. Geometry and DRC gaps

#### C1. Internal Edge.Cuts were not treated as routing obstacles

- Symptom: the router completed all electrical connections but routed SCL1,
  SDA1, and GND too close to or across the SHT31 isolation slot.
- Evidence: R003/R004 had zero unconnected items but KiCad reported multiple
  `copper_edge_clearance` errors at the slot.
- Root cause: the static layout and corridor authorities understood cutouts,
  but the production legacy A* routing legality did not fully enforce internal
  Edge.Cuts clearance.
- Workaround used: extract exact saved sensor-route coordinates, reshape the
  three-sided moat around the accepted top-right four-net bridge, prove the
  result on a routed-board copy, then rerun the canonical board.
- Permanent correction: one canonical board-region mask must feed placement,
  legacy routing, negotiated routing, virtual DRC, design checks, and KiCad
  serialization. Add a firing fixture for tracks/vias near every side and
  concave corner of an internal cutout.

#### C2. Artwork and intentional edge overhang produced late warnings

- Findings included OLED outlines/polarity text near the circular edge, the
  intentional ESP32 antenna overhang's library silkscreen, and an R10 reference
  over copper.
- Workarounds used: move the OLED headers/envelopes inward, leave a deliberate
  gap around the `+` marks, hide dense resistor references, and move U1's
  overhanging library artwork from B.SilkS to B.Fab.
- Remaining design smell: the U1 treatment is a thermometer-specific
  postprocessor rather than a generic per-footprint artwork policy.
- Permanent correction: typed per-footprint layer suppression/translation and
  explicit intentional-overhang policy, checked before serialization.

#### C3. Post-route manufacturing corrections required expensive full replay

- Symptom: cutout and silk corrections were known not to change accepted
  copper, but exact-authority requirements forced another 30-minute route run.
- Positive evidence: R004 and R005 normalized copper hashes were identical.
- Permanent correction: separate route-affecting geometry from review-only
  artwork/3D metadata; permit a checked no-copper-change commit when the new
  board-region mask is proven clear of the existing route; reroute only nets
  whose legality dependencies changed.

### D. Stale scale, coordinate, and golden coupling

#### D1. Historical `/PWLED` crop retained obsolete absolute coordinates

- Symptom: after D17/R17 moved from `(31,147)/(35,147)` to
  `(50,160)/(54,160)`, the historical pilot still used crop origin `(28,144)`.
  The components no longer fit its 10 x 6 mm crop, and legalization failed.
- Impact: the first full regression run reached 100% only to report three
  failures and nineteen dependent errors. The full run took about 14 minutes.
- Resolution: move the crop origin to `(47,157)`, preserving the pilot's exact
  local `(3,3)/(7,3)` geometry, and renew the outline/input fingerprints.
- Analysis: the tests were right to fail. The defect was duplicated absolute
  production truth and lack of early dependency invalidation.
- Permanent correction:
  - derive crop origins from selected production poses plus declared local
    anchors instead of repeating absolute numbers;
  - give semantic fingerprints explicit version/migration metadata;
  - record which fixtures depend on each placement/outline authority;
  - run affected focused tests immediately after changing board dimensions or
    canonical placements.

#### D2. Board shape and placement truth were spread across constants, comments,
silk coordinates, historical fixtures, and expected hashes

- Symptom: enlarging the bulb required coordinated edits to outline constants,
  placements, silkscreen positions, module envelopes, sensor cutout, pilot crop,
  and golden fingerprints.
- Permanent correction: introduce a `ThermometerMechanicalAuthority` containing
  shape, display envelopes, sensor island, USB opening, antenna edge, scale
  geometry, and named placement regions. Derived artifacts consume this one
  authority and declare fingerprint dependencies.

### E. Verification was too manual and too late

#### E1. Verification evidence was assembled with ad hoc probes

- Manual work included parsing DRC JSON, extracting routed sensor coordinates,
  counting segments/vias/routed nets, comparing normalized copper, copying
  review images, running repeated-save experiments, and hand-writing the final
  verification manifest.
- Impact: more opportunity for omission, stale evidence, and inconsistent
  wording.
- Permanent correction: one `pcbsmith verify-board-authority` command must
  perform and persist netlist retention, route counts, overuse, exact replay,
  virtual DRC, semantic checks, KiCad DRC/parity, repeated save, ERC/reader
  equality, simulation, render inventory, model existence, and visual-review
  status.

#### E2. Routing telemetry and exact-commit evidence were not persisted by the
production path

- Symptom: the final segment/via/routed-net counts and zero-overuse statement
  had to be recovered from the saved board and legacy router invariants.
- Gap: the requested R2-R6 run result, checked commit, and exact replay bundle
  were not the production authority.
- Workaround: independent R004/R005 full runs produced identical normalized
  copper; repeated KiCad saves were byte-identical.
- Permanent correction: persist canonical `RoutingRunResult`, resource ledger,
  accepted-layout fingerprint, checked-commit result, saved-board read-back
  fingerprint, and exact per-net copper graph in every production bundle.

#### E3. The review-bundle status model could not record completed visual review

- Symptom: `_finish_board_authority` changed a clean board to
  `needs_human_review` unconditionally, and there was no standard mechanism for
  this session's completed visual inspection to promote or attest the result.
- Permanent correction: keep machine board status and review status separate.
  A signed/hashed review attestation may close the visual gate without erasing
  procurement or firmware warnings.

#### E4. Full regression was run twice

- Evidence: the first full run took about 851 seconds and exposed the stale
  pilot; the corrected rerun took about 674 seconds and passed 2546 tests with
  16 intentional skips.
- Avoidable portion: focused dependency tests should have run immediately after
  placement changes, allowing only one final full run.
- Permanent correction: maintain a change-to-test dependency map and use
  targeted gates during iteration, followed by one full suite at final
  acceptance.

#### E5. Toolchain commands were not fully pinned

- Symptom: the first strict mypy command targeted Python 3.11 semantics while
  installed NumPy stubs used Python 3.12 type syntax. The corrected
  `--python-version 3.12` run passed 233 source files.
- Symptom: repository-wide Ruff first stopped on one extra blank line in
  `lint_imports.py`, unrelated to the PCB logic.
- Permanent correction: one checked-in verification command must use the
  project's pinned interpreter and tool configuration; fast hygiene should run
  before expensive routing.

### F. 3D asset failures and component onboarding

#### F1. SHT31 referenced a nonexistent installed model

- Symptom: U4 contained a syntactically valid
  `${KICAD10_3DMODEL_DIR}/Sensor_Humidity...step` reference, but the installed
  KiCad 10.0.3 directory contained the footprint and no matching STEP file.
  KiCad silently omitted the package from the 3D view.
- Important limitation: ERC and DRC do not validate 3D model file existence.
- Workaround: R006 used a bundled 3 x 3 mm DFN-8 model scaled to approximately
  2.5 x 2.5 mm and labelled it a visualization proxy.
- Permanent correction: resolve path variables and verify every model exists
  before rendering; missing required models must appear in the review bundle.

#### F2. OLED footprints modeled only the headers

- Symptom: J2/J3 showed accurate 1x04 header models but no OLED carrier boards
  or screens.
- Root cause: a connector footprint is not a complete module footprint, and no
  exact 0.49-inch OLED module MPN/model had been selected.
- Workaround: R006 added KiCad's bundled larger Adafruit SSD1306 model, scaled
  and lifted above each header. It looks useful but is explicitly not exact
  mechanical evidence.
- Permanent correction: component onboarding must distinguish package,
  connector, carrier, and complete module assets and bind the model for the
  selected purchasable module.

#### F3. There was no 3D acquisition/cache/provenance pipeline

- Resolution started: Track 6.5 and the active roadmap now specify exact KiCad
  or manufacturer model preference, selected on-demand downloads, local
  checksum/licensing cache, deterministic transforms, bounding-box/orientation
  validation, proxy status, and rendered inspection.
- Remaining work: implement the resolver, component-card schema, downloader,
  offline replay, and model-preflight report. R006 directly edits a derivative
  board and is a pilot, not the implementation of that pipeline.

### G. Official-document retrieval failed to run during the project

- Symptom: the research audit identified the official Sensirion SHT/STS design
  guide and USB 2.0 signalling specification as freely available but reported
  them as absent locally. It did not attempt the official downloads while those
  sources were already relevant to the thermometer and USB interface work.
- Root cause: source discovery, acquisition, identity verification, extraction,
  and utilization were treated as separate manual activities with no fail-closed
  handoff. “Found online” could therefore stop at a wishlist entry.
- Correction performed 2026-07-18: both official sources were downloaded,
  hashed, visually verified, inventoried, and registered for extraction. The
  USB archive and its base specification remain separately identified.
- Permanent correction: an approved free primary source must trigger automatic
  official-URL retrieval and identity/hash verification. The system may report
  `blocked` only with a concrete paywall, authentication, license, robots,
  network, or identity reason. Acquisition still does not equal rule promotion;
  scoped distillation and production exercise remain separate gates.

### H. Residual design and evidence reviews

#### H1. Exact OLED procurement identity remains unspecified

- The PCB assumes 0.49-inch SSD1306 modules with GND/VCC/SCL/SDA pin order.
  Exact module dimensions, connector origin, mounting retention, and STEP model
  must be verified against the purchased part.

#### H2. AP2112 thermal usage remains an operational constraint

- The design review warns that continuous worst-case ESP32 radio transmit is
  outside the intended display-load thermal budget. Firmware must keep Wi-Fi off
  or duty-cycled unless the power/thermal design is revised.

#### H3. R005 is the electrical production authority; R006 is not

- R006 changed only 3D metadata and proved identical copper plus clean DRC, but
  its OLED and SHT31 assets are proxies. It must not replace R005 as exact
  mechanical/fabrication authority.

## What worked and should be retained

- The user's larger-bulb suggestion improved both realism and routability.
- Independent KiCad DRC caught the internal-cutout defect that the router missed.
- Reader schematic equality and ngspice gates remained stable throughout.
- Stable UUIDs, normalized copper hashing, and repeated-save checks allowed
  strong proof that R004/R005 routing was deterministic and R005/R006 copper was
  unchanged.
- The stale historical pilot tests correctly prevented silent divergence.
- Keeping failed probes and R002-R004 outputs separate protected the accepted
  R005 artifact.
- Explicit proxy labelling in R006 prevented a useful visual experiment from
  becoming a false mechanical-fit claim.

## Required workflow before the next production-sized board

### P0 - must land first

1. **Always-persist inspectable pre-route artifacts.** Within the first minute,
   emit a labelled placement `.kicad_pcb`, front/back/perspective/assembly
   renders, and the retention manifest even if routing later fails.
2. **One automatic verification command.** Eliminate manual counting, image
   copying, hash comparison, repeated-save scripting, and hand-authored final
   manifests.
3. **Canonical board-region legality.** Internal cutouts and edge clearance must
   be shared by every router and checker, with firing integration fixtures.
4. **Progressive bounded routing.** Preflight capacity, per-net progress,
   checkpoints, time/memory budgets, and typed failure evidence are mandatory.
5. **Single mechanical/placement authority with dependency invalidation.** No
   fixed historical crop or golden may silently retain obsolete production
   coordinates.
6. **3D asset preflight and resolver.** Missing files, proxy status, transform,
   model envelope, and exact module identity must be automatic review evidence.
7. **Automatic official-source intake.** For an approved free primary source,
   retrieve from the official URL, verify identity, hash/inventory it, and emit
   an explicit blocked reason if retrieval cannot proceed.
8. **Pin the verification environment.** Ruff and focused dependency tests run
   before routing; strict mypy uses the project interpreter/target; one full
   regression runs only at final acceptance.

### P1 - next architecture work

1. Migrate the complete thermometer from legacy `route_board` to the accepted
   R2-R6 production path with persisted zero-overuse and exact checked commit.
2. Add affected-net incremental rerouting and checked no-copper-change commits
   for artwork/3D/manufacturing metadata revisions.
3. Replace project-specific silk/model postprocessors with typed generic
   footprint artwork and 3D-model policies.
4. Add role-driven close-up renders and a machine-readable visual-review
   attestation.
5. Implement exact module selection so OLED pinout, retention, envelope, and 3D
   model come from one reviewed component card.

### Performance targets for the next proof

These are engineering targets, not current guarantees:

- placement PCB and review images: <= 60 seconds;
- capacity/routability preflight: <= 2 minutes;
- complete route on a thermometer-sized two-layer board: <= 15 minutes or a
  typed bounded failure with useful hotspot evidence;
- KiCad save/read-back/DRC and all renders: <= 2 minutes;
- focused iteration gates: <= 2 minutes;
- one final full regression only.

## Definition of a smoother success

The next comparable task should not require the user to ask for the PCB or
images. A single run should always leave an inspectable project, clearly mark
whether copper is routed, expose progress and blockers while routing, prevent
cutout/model omissions before KiCad review, update dependent fixtures when the
mechanical authority changes, and produce one complete evidence bundle without
manual reconstruction. Visual review remains mandatory, but it becomes a
recorded final gate rather than a late recovery step.
