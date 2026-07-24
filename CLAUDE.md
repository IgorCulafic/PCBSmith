# PCBSmith — working handbook for the AI developer

Written 2026-07-07 by Claude Fable 5 as a handoff to its successors.

> **Current-state amendment (2026-07-20):** This is the stable working handbook,
> not the volatile status authority. Read `docs/handoff-prompt.md`, then
> `docs/current-state.md`, before using dated frontier text below. The archived
> long handoff is historical only. The thermometer project completed as the
> accepted routed R005 proof-of-concept; R006 is its 3D proxy pilot. Do not rerun
> the thermometer to prove generic machinery—use the next unseen user project.
> Phase 11/12 source, asset, artwork, visual-review, and bounded-execution
> operations are documented in `docs/evidence-assets-review-execution-guide.md`.

You are the DEVELOPER of this project; the pipeline itself is 100%
deterministic and must stay that way — no LLM in the design loop. Your
job is to grow the pipeline's intelligence so that, on its own, it
turns a plain-language request into a fabricable, evidence-backed,
machine-verified PCB. The user (Igor) sets challenges and supplies
reference material; you build, verify, and harden.

A detailed narrative of everything built so far is in
`docs/project-history.md`. Read it once before your first real task.
Then: `docs/architecture.md` (what every module does and how the
pipeline flows), `docs/lessons-and-pitfalls.md` (the complete mistake
ledger — read BEFORE touching the router or placements), and
`docs/routing-placement-plan.md` (the active roadmap).

## The five laws (learned the hard way, in force everywhere)

1. **A rule that is not a check is a wish.** Every lesson — yours, the
   user's, or a reference design's — becomes a machine check
   (`design_checks.py`, `virtual_drc.py`) or it will be violated again.
   The rulebook `docs/pcb-design-rules.md` records each rule with its
   source and its enforcement status; a rule may be "documented" only
   temporarily.
2. **No assumed geometry.** Never guess a footprint dimension, pad
   position, pin convention, or symbol pin. Probe the real `.kicad_mod`
   / `.kicad_sym` files (`kicad/library.py`, `kicad/symbols.py`).
   Every geometry bug in this project's history came from an
   assumption; every fix came from measuring.
3. **Pre-filters underestimate; kicad-cli is the authority.** The
   virtual DRC exists to turn 30-second KiCad round trips into
   millisecond feedback. It must NEVER block a board KiCad would pass:
   pads are stadiums with radius min(w,h)/2, text extents are shrunk
   estimates, round shapes are convex hulls (bboxes false-positive at
   corners — this bit twice: courtyards, then fab bodies). When you add
   a virtual check, run the full board test suite AND the golden suite
   to prove no false positives.
4. **The pipeline never self-approves.** Terminal-clean output is
   capped at `needs_human_review`. Mains/safety-relevant designs carry
   standing SAFETY findings (certified parts, qualified review). Do not
   weaken this, ever, even when everything passes.
5. **Every component fact carries evidence.** Datasheets are fetched
   (TI pattern: `https://www.ti.com/lit/gpn/<part>`), sha256-pinned in
   `ai_assets/datasheets/` + manifests, and facts carry page-level
   locators. `assumption` is an honest status — mark it, don't hide it.
   Component cards (`ai_assets/components/*.json`) are the durable form.

## How to build a new topology (the sequence - proven through
## schematics on 10/10 topologies, through boards on 10/10 with scope limits)

1. **Datasheets first.** Fetch, pin, read; extract the WORST-CASE
   limits table into the calculator's defaults.
2. **Calculator** (`calculators/electronics.py`): closed-form design
   chain, every number derived, references listed in the output dict.
   Write the hand-check test immediately (assert the energy balance /
   design equations hold on the outputs, not just golden numbers).
3. **Intent → topology → composition** (`circuit/intent.py`,
   `circuit/topologies.py`, `generation/<name>.py`): keyword intent,
   assumptions dict, ComponentRole per part with evidence refs.
   `support_status` values: draft / needs_datasheet_review / reviewed /
   supported — "reviewed" is NOT valid for ComponentRole (use
   "supported").
4. **Schematic exporter** (`kicad/export_<name>.py`): label-net style —
   instances table `(ref, lib_id, x, {pin: net})`, a stub wire + label
   per pin. Official symbols always; custom symbols only when none
   exists (UCC28881, LMV431), drawn from datasheet pin tables, with the
   sidecar `PCBSmith.kicad_sym` + `sym-lib-table` written next to the
   schematic. EVERY net needs a label — kicad-cli silently drops
   unlabelled nets from ERC and netlist export. Stub pitch 17.78 mm on
   A2 avoids label collisions.
5. **Simulation**: ngspice behavioral check of what can honestly be
   simulated (`.op` for feedback chains, transient with `.meas` for
   oscillators). State plainly what is NOT simulated (reconciliation
   section) — e.g. the flyback's switching stage is verified by design
   equations, not SPICE.
6. **Board** (`kicad/<name>_board.py`): PLACEMENTS dict + hand routing
   through `shaped_board.Router` with `pad_for(ref, net)` — never
   hardcode a pad position you can query. Iterate against virtual DRC
   until zero findings, THEN run the authority (kicad-cli DRC +
   parity), then LOOK at the renders (`-review.png`, `-top.png` are
   readable images; schematic via PDF export).
7. **Tests**: calculator hand-check; offline board test building the
   netlist from the exporter's pin tables (no kicad-cli needed);
   fixture tests that PROVE each new check fires (a deliberate
   violation must produce the finding); golden-suite entry.
8. **Gates before commit**: ruff, strict mypy, full pytest, and — if
   `kicad/` or `calculators/` changed — `PCBSMITH_GOLDEN=1 pytest
   tests/golden` (regenerates all topologies live, ~10-15 min, run it
   in the background). All four green or no commit.
9. **Commit** with a message that records the WHY and the lessons, then
   update the auto-memory.

## Placement and routing craft

- Before placing anything dense, COMPUTE the placed courtyard hulls
  and pairwise gaps with a probe script (load_footprint + rotate_offset
  over the PLACEMENTS dict). Hand-guessing clearances burned an entire
  session on the flyback (v4→v9).
- Clearance arithmetic: centers ≥ r1 + r2 + 0.2 mm clearance
  (+0.05 tolerance). Pad radius = min(w,h)/2 (stadium). Via radius 0.3.
- `rotate_offset` convention: KiCad CCW with y pointing DOWN, so
  rot 90 maps (right,down)→(up,right); front rot-90 puts pad1 at the
  BOTTOM. Back side = INVERSE rotation `(360-rot)%360`, then x-mirror.
- Pad and text angles in `.kicad_pcb` are TOTAL angles
  (footprint + local); positions stay footprint-local. Forgetting this
  physically un-rotates pads (live DRC shorts every pin pair).
- KiCad pin conventions: diode/LED pad 1 = CATHODE; CP pad 1 =
  POSITIVE. `pad_for(ref, net)` makes this a non-issue — use it.
- B.Cu runs must dodge ALL THT annulars (they exist on both layers)
  and via annuli. Two same-layer nets that must cross: one dives to
  the back through a via pair. Same-net T-joints are free.
- Don't route through unused THT pads (the transformer's unused pins
  are still copper).
- 45° parallel diagonals at 0.5 mm pitch are only 0.354 mm apart —
  rejected for QFN fanout; use the nested-elbow escape planner.
- Dense layouts: reposition silk reference labels via
  `BoardLayout.part_reference_at` (footprint-local x, y, total angle;
  0 = upright). ALL KiCad DRC violations fail the board stage,
  warnings included — silk is not optional cosmetics.
- Mains isolation (rulebook §10): declare barrier_x, gap, primary and
  secondary net sets, straddle refs (transformer/opto/Y-cap). No
  copper pours on isolated boards — creepage analysis must stay exact.
- RECT pads (square pin-1 markers on TO-92, pin headers) stick out past
  the stadium model at the corners: the router covers them via
  `_collect_items(..., cover_rect_pads=True)` for FOREIGN obstacles
  only (own-net pads stay exact or stubs would miss the copper). The
  DRC-checking model stays underestimating. Learned live: the servo
  board's first route cut Q1/J2 pad corners and shorted /SIG to /GND.
- Duplicate pad numbers are separate PHYSICAL pads to KiCad's ratsnest
  (SW_PUSH_6mm has two "1" and two "2" pads): the router terminals and
  the virtual `pad_connectivity` check key by (label AND position),
  never label alone.
- KiCad real silk text is ~1.9x the font size tall (ascender/descender
  + thickness) and ~0.85mm/char wide at size 0.8 — the virtual text box
  (0.4/char, 0.55 half-height) underestimates by design. Board minimum
  silk height is 0.8mm (`silk_text_height` virtual check). Plan value
  labels with REAL metrics: a corridor between two part outlines must
  be >= ~2.0mm for a 0.8mm text row. The 52x38 servo cut failed live
  silk DRC three times before growing to 56x40.
- KiCad checks silk STROKES, not filled interiors: a ref label centered
  over its own body clears DRC if it misses the outline lines. The
  virtual model skips own-footprint label overlaps entirely (fab-hull
  proxy would false-positive) — own-label collisions surface only in
  live DRC, so keep the probe → kicad-cli loop for dense silk.
- Grid routers emit STAIRCASE micro-segments unless you make them
  KiCad-like on purpose (user caught 0.2mm stacked pieces at every
  corner in the editor). Three parts, all required: 8-connected moves
  (diagonals at grid·√2, corner-cut guard = both orthogonal cells
  free), a TURN_PENALTY_MM in the search state (direction rides along;
  among equal-length paths the straightest wins — without it A*
  interleaves diagonal/straight into sawtooth), and
  `merge_collinear_segments` on the emitted copper (keep ORIGINAL
  endpoint coords when merging — reconstructing from line parameters
  drifts ~1e-7). Judge output by segment stats: sub-0.3mm count should
  be ≈ pad-entry stubs only.
- Rule 11 trace craft (user directive 2026-07-10): the emit pipeline
  is route → string-pull smooth (H/V/45 connectors, cells checked
  against the SAME blocked sets) → merge collinear → prune covered
  copper → checks. TWO root causes of the servo board's spaghetti:
  the routing tree never absorbed a connected pad's own copper (later
  legs laid parallel copper instead of branching — `tree |= targets`
  after every leg), and grid wander that only post-smoothing removes.
  `trace_corner_angle` (no acute joints outside pad copper) and
  `redundant_copper` (no fully-contained track) are always-on blocker
  checks; pruning is provably safe ONLY for area containment
  (centerline coverage changes the copper point-set).

## The reference knowledge base (reconciled 2026-07-14; read before layout work)

- Thirty-one exact sources live in `Books/` (gitignored), with text
  caches in `.book-cache/` and hashes in its manifest. The collection
  comprises the original nine, a historical sixteen-source second wave,
  and six later standards/status sources.
  `tools/book_extract.py` (pypdf/EPUB) extracted seven;
  `tools/book_ocr.py` (pypdfium2+RapidOCR, ~7 s/page, resumable)
  OCR'd the two scanned ones (johnson-hsdd, ipc-7351). All nine are now
  distilled.
- The durable form is `docs/reference/books/*.md` - every rule carries
  THRESHOLD/WHY/WHERE(page)/MACHINE FORM/APPLICABILITY. All NINE sources
  are distilled and
  spot-verified (72 rules checked 2026-07-12; corrections and two
  honest ambiguities recorded in each file's Verification section).
  `docs/reference/current-materials-knowledge-base-2026-07-14.md` plus
  `docs/reference/standards-table-reverification-2026-07-14.md` are the
  current entry point: they preserve source authority, applicability,
  edition status, policy holds, and visual table verification.
  `docs/reference/books/CONSOLIDATED.md` remains historical first-wave
  candidate data; do not promote from it without reconciling the July 14
  do-not-encode docket.
  Text-cache hazard: pypdf/OCR drop the Greek mu glyph; close any
  unit-sensitive verification by dimensional analysis, never string
  match. NEVER re-read the books wholesale.
- `docs/routing-placement-plan.md` is THE roadmap. Completed phase scopes are
  frozen; new capabilities use the next sequential phase, and dated errata
  correct invalidated claims. The thermometer is complete. Phases 10-12 govern
  continuity/environment, evidence/assets/review, and execution health before
  the next unseen project.
- Headline audit results already known: our trace-current formula is
  IPC-2221A's and must be labeled as such; IPC-2152 is useful historical
  measured data but is no longer maintained. Flat `CLEARANCE_MM = 0.2`
  is inadequate, but a bare voltage-to-distance lookup is also unsafe:
  ordinary PCB/fab spacing and IEC/product insulation coordination need
  separate profiles. The flyback rulebook now correctly labels 6.4 mm as
  a conservative project minimum rather than a universal IPC mandate.
  Corners at 90 degrees are NOT an SI issue
  below multi-GHz (2 fF/mil — keep 45-degree as craft, honestly
  labeled); decap PROXIMITY is weak, routed loop area is first-order;
  Ott caps 2-layer boards at ~10 MHz clocks (standing advisory vs our
  50 MHz class); thermometer r001 violates the Espressif antenna rule
  (U1 antenna over bulb copper). Sensirion's current guide is now locally
  pinned and supports thermal isolation, but still does not specify a universal
  moat width or bridge geometry.

## Environment pitfalls (Windows, this machine)

- Canonical development and verification use `.venv` Python 3.12. Package
  metadata and Ruff retain a Python 3.11 compatibility floor; do not run project
  commands with the system-default Python 3.14, which is outside the declared
  range. Mypy targets 3.12 because the maintained environment includes
  3.12-syntax third-party stubs.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` always; add `-p no:cacheprovider`
  (the `.pytest_cache` ACL is broken from a PC reinstall and spams
  warnings; occasionally pytest's summary line is eaten — pipe to a
  file in the scratchpad if you need it).
- Bash heredocs that contain f-strings, nested quotes, or literal
  `\n` sequences GET MANGLED. For multi-edit patches use the Write
  tool to create a `.py` patch script in the scratchpad — but prefer
  direct Edit calls on the live file; big atomic patch scripts go
  stale against their own asserts while you iterate.
- Read tool mangles `\u...` in backslashed paths — use forward slashes.
- kicad-cli: `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe` (10.0.3).
  ngspice: `D:\AI\PCB designer\Spice64\bin\ngspice_con.exe`.
- KiCad 10 file quirks: re-saved boards store nets NAME-ONLY
  `(net "/FB")`; stroke blocks are multi-line (regexes over board text
  need two levels of paren nesting); DRC report positions are offset
  by `BOARD_SHEET_ORIGIN_MM` (20, 20) from board-local coordinates.
- No poppler/pdftoppm: PDFs are read via pypdf TEXT extraction (works
  well on vector PDFs — Altium/TI). `python -X utf8` for anything that
  prints datasheet text. Scanned PDFs: `tools/book_ocr.py` pattern
  (pypdfium2 render + RapidOCR). SVG schematics: rasterize with
  resvg_py (installed; convert the mm width/height attrs to px first)
  and Read the PNG. Board images: `kicad-cli pcb render --side
  top|bottom`. kicad-cli ERC JSON positions decode at x100 to sheet mm
  (lengths /100); DRC JSON stays mm with the (20,20) origin. Heredocs
  also mangle regex character classes — use the Write tool for any
  nontrivial patch/probe script.
- Session rate limits KILL mid-flight agent fleets (the deep-research
  verify phase lost 75 agents; one book agent died after writing its
  file). Fan out in waves, make outputs land in files early, and
  salvage from `subagents/workflows/*/journal.jsonl` before rerunning.
- No Nexar credentials, no ANTHROPIC_API_KEY, no local llama-server in
  this environment — the evidence-extraction LLM path and live BOM
  pricing stay dormant until the user provides them.
- Long jobs (golden suite, authorities) → background with
  run_in_background; you'll be notified.

## Debugging discipline

- Live DRC failed? Parse `.pcbsmith/kicad/drc.json` for item
  descriptions AND positions (subtract the 20 mm origin), don't guess
  from the summary strings.
- Every live-DRC failure class you hit must end as a virtual-DRC check
  or a design check. That ratchet is the project's core mechanism —
  the flyback's six silk round-trips became `_check_silkscreen` the
  next day.
- When a check false-positives, the model is overestimating somewhere;
  find the geometric overreach (it has always been a bbox where a hull
  belongs, or a forgotten shrink) rather than loosening thresholds.
- Trust the golden suite. It has caught every subtle regression
  (rollout false positives, courtyard-hull overreach on TO-92).

## Working with the user

- Challenges arrive as plain-language briefs, sometimes with reference
  images/files. Standing instruction on long tasks: work autonomously
  in commit-sized chunks, report when finished or blocked.
- Reference packs (Altium/KiCad output folders) are gold:
  `pcbsmith ingest-reference <dir>` stores BOM/drill/placements/PDF
  text under `ai_assets/references/`. Compare against our output, write
  `docs/reference-comparisons/<slug>.md`, and file rule candidates in
  `docs/ai-rule-suggestions.md` — the user promotes them; don't
  silently rewrite the rulebook for judgment calls (direct edits are
  allowed for factual/enforcement updates).
- Hand edits to generated boards are learning input:
  `pcbsmith board-diff` records them; confirm INTENT with the user
  before promoting a placement rule.
- The user values honest status over green lights: report failed
  steps, unsimulated stages, and assumption-level evidence exactly as
  they are.
- Project context beyond the code: PCBSmith is the RESTART of an
  earlier attempt (archived in `old_files/r8-pre-restructure-snapshot-
  2026-05*` - browsable for history, never imported). The user has a
  FUNDING angle: a separate session built a mockup chat GUI over old
  board visuals for a funding-run presentation video; expect demo/
  presentation asks, and keep renders/review packs presentation-
  quality. Only one prior session transcript survives on this machine;
  everything else from earlier chats lives ONLY in CLAUDE.md, the
  rulebook, docs/project-history.md, the commit messages, and now
  docs/architecture.md + docs/lessons-and-pitfalls.md - treat those as
  the canonical memory and keep updating them.

## Current frontier (where to push next)

- **Legacy automation is proven but does not establish generic scale**: the servo555
  tester (9th
  golden topology) is the first board where `route_board` produced
  every trace from coarse placements — placement + probe + route +
  live DRC loop converged in 3 iterations and the fixes it forced
  (rect-pad cover, per-physical-pad connectivity, silk height/edge
  checks) are now permanent machinery. SCOPE LIMIT, learned the
  hard way: that was 9 parts on an open rectangle. The 63-part thermometer
  initially failed repeatedly in its narrow corridor, then eventually completed
  as R005 after a slow legacy route and extensive correction. That proves the
  accepted board, not a mature or generally scalable routing workflow.
- **flyback dual-side compaction (2026-07-10, one data point)**:
  `tools/flyback_compaction.py` produced an 80×42 dual-side flyback
  (whole SMD control circuit on the back, FLBACK-001-style), 100%
  auto-routed, live kicad-cli DRC 0 violations / 0 unconnected.
  `placement_search` grew rotation/side-flip moves and
  `climb_placements`. NOT yet the golden flyback — silk production
  pass (barrier/value texts) and authority wiring remain; analysis in
  `docs/reference-comparisons/flyback-dual-side-compaction.md`. The
  42 mm height floor is the TEZ-22x24 transformer; matching the
  reference's 36.8 mm needs an EFD20-class part (component change).
- **Human-readable schematics (Track 9.1, user requirement)**:
  working with live gates on 3 of 10 topologies (servo555,
  flyback, thermometer) — the other SEVEN still lack reader
  schematics. LANDED
  on servo555 AND the flyback (31 parts, custom symbols via
  ReaderSpec.customs) — `kicad/reader_schematic.py` (conventional
  drawing renderer + offline wire-connectivity validator that rejects
  label teleports and re-derives the machine pin->net table from the
  drawn wires), live ERC + netlist-export equality gate board
  generation via the shared `_reader_schematic_checks` authority
  helper, reader SVG is the schematic the bundle links. Property text
  angles are PROBED convention (angle=rotation for 90/270, 0 for
  180). Next: buck/detector backfill (INSTANCES tables exist); the
  role-driven column/rail placer.
- **R2-R6 GENERIC MACHINERY EXISTS; THE NEXT UNSEEN PROJECT IS THE FUTURE
  GENERALITY TEST (2026-07-20)**: the research-first rebuild now includes
  negotiated congestion and shaped capacity, fine/ordinary exchange, generated
  bus escapes and transition vias, physical-swap and cost-aware LCS authority,
  atomic exact checked commit, placement probes/candidates/detail/exact
  envelopes, live reduced-stem KiCad and reader/ERC producers, and generic R6
  semantic/process authorities. The accepted R4 consumer exposes only an
  in-memory exact-accepted `BoardLayout`; it does not save or render a board.
  Do not retrofit this chain into the completed thermometer. Apply it through
  an explicitly persisted/read-back artifact on the next user-selected design,
  whose shape and circuit are not already encoded in the repository.
  `docs/circuit-intelligence-review-supplement-5-2026-07-17.md` records the
  accepted bounds; `docs/r5-thermometer-pilot-prerequisite-audit-2026-07-17.md`
  records the remaining prerequisites.
- **Thermometer challenge (2026-07-10 through 2026-07-18, 10th topology,
  COMPLETE PROOF-OF-CONCEPT)**:
  63 parts (ESP32-C3, SHT31 DFN, 2x74HC595, USB-C 16P, 16-LED mercury
  column) on a thermometer-shaped outline. It forced five GENERIC
  machinery upgrades, each regression-tested and rulebook'd (5.3-5.5):
  custom-pad primitive extents (SHT31 EP anchors 1.0x1.0, copper
  1.0x1.7 - a via parked on the unmodelled lobe), NPTH/unnamed drilled
  pads as net-less `~hole:` obstacles (hole-to-copper 0.25), via edge
  margin on shaped outlines, `min_through_hole` project constraint
  (module thermal vias drill 0.2), and `route_board(fine_pitch_nets=)`
  - 0.1mm-grid pre-routing WITH rip-up-by-reordering (0.5mm-pitch pads
  cannot center tracks on the 0.2 grid; corridor priority decides
  feasibility). Reader schematic (63 parts) validates clean + live ERC
  + netlist equality; no-connect crosses are now first-class in the
  reader machinery. Placement lesson: put each register IN its load
  zone - the inverted U2/U3 arrangement made all 16 SEG nets cross the
  other register's zone and /SEG9 unroutable. BOARD STATUS: unrouted —
  seven successive single-net failures (VBUS/DM/CAS/SEG9/SEG6/SEG5/
  LK4/SER/SRCLK) proved per-net A* + rip-up cannot shepherd 20+ nets
  through the 24 mm stem; every failure became a committed placement/
  machinery fix. A later corrected legacy-path run completed as R005: all 53
  nets routed, clean machine/reader ERC, netlist equality, ngspice checks,
  virtual/design checks, clean KiCad DRC, deterministic copper replay,
  byte-identical repeated save, and inspected review images. R006 added proxy
  SHT31/OLED 3D metadata without changing copper. The isolated
  production-derived R17/D17 `/PWLED` offline micro-pilot now proves exact
  vendored R0603/LED0805 body/courtyard input, one reviewed R17 -0.5 mm
  `LEGAL_EXACT` move, a 56-cell/82-portal zero-overuse R3 plan in 202 expansions,
  and an explicitly authorized ordinary-R2 fallback in 271 expansions. The
  exact guide is truthfully `INCOMPATIBLE` because of conservative bounded
  roundrect issues; the fallback emits five F.Cu segments and zero vias.
  Serialization proves only the R17 pose and `/PWLED` segments changed, and the
  offline virtual-DRC/design-check aggregate plus replay/tamper gates pass.
  Boundary tests pin graph 120/82 success against 119/81 failure, R3 49 against
  48 expansions, and R2 271 against 270. A separate opt-in live KiCad 10 gate
  passes exact read-back, byte-identical repeated save, and clean DRC with zero
  findings; the offline wrapper remains truthfully `kicad_live_checked=False`.
  These isolated generic results do not establish broad routing superiority or
  default adoption, but that does not reopen the completed project. R005 is the
  accepted electrical proof; R006 is visualization-only. The user explicitly
  retired the planned thermometer rerun on 2026-07-20.
- Polygon-exact pour analysis; pear/led-art/divider exporter
  migrations to official symbols; live forge-topology run (user must
  start KoboldCpp); more registry blocks (rcd-clamp,
  isolated-feedback, ne555-button-astable, and bjt-signal-inverter
  landed 2026-07-10; next: buck/detector blocks).
- Blocked on environment: live Nexar BOM (credentials), LLM datasheet
  extraction (API key / local server), DigiKey reference-design site
  (403s curl; local packs via ingest-reference sidestep it).
