# PCBSmith — working handbook for the AI developer

Written 2026-07-07 by Claude Fable 5 as a handoff to its successors.
You are the DEVELOPER of this project; the pipeline itself is 100%
deterministic and must stay that way — no LLM in the design loop. Your
job is to grow the pipeline's intelligence so that, on its own, it
turns a plain-language request into a fabricable, evidence-backed,
machine-verified PCB. The user (Igor) sets challenges and supplies
reference material; you build, verify, and harden.

A detailed narrative of everything built so far is in
`docs/project-history.md`. Read it once before your first real task.

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

## How to build a new topology (the proven sequence)

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

## Environment pitfalls (Windows, this machine)

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
  prints datasheet text.
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

## Current frontier (where to push next)

- **Automation-first boards are proven**: the servo555 tester (9th
  golden topology) is the first board where `route_board` produced
  every trace from coarse placements — placement + probe + route +
  live DRC loop converged in 3 iterations and the fixes it forced
  (rect-pad cover, per-physical-pad connectivity, silk height/edge
  checks) are now permanent machinery.
- **flyback dual-side compaction DEMONSTRATED (2026-07-10)**:
  `tools/flyback_compaction.py` produced an 80×42 dual-side flyback
  (whole SMD control circuit on the back, FLBACK-001-style), 100%
  auto-routed, live kicad-cli DRC 0 violations / 0 unconnected.
  `placement_search` grew rotation/side-flip moves and
  `climb_placements`. NOT yet the golden flyback — silk production
  pass (barrier/value texts) and authority wiring remain; analysis in
  `docs/reference-comparisons/flyback-dual-side-compaction.md`. The
  42 mm height floor is the TEZ-22x24 transformer; matching the
  reference's 36.8 mm needs an EFD20-class part (component change).
- **Human-readable schematics (Track 9.1, user requirement)**: pilot
  LANDED on servo555 — `kicad/reader_schematic.py` (conventional
  drawing renderer + offline wire-connectivity validator that rejects
  label teleports and re-derives the machine pin->net table from the
  drawn wires), live ERC + netlist-export equality gate board
  generation, reader SVG is the schematic the bundle links. Next:
  backfill the other topologies; grow the spec into the role-driven
  column/rail placer.
- Polygon-exact pour analysis; pear/led-art/divider exporter
  migrations to official symbols; live forge-topology run (user must
  start KoboldCpp); more registry blocks (rcd-clamp and
  isolated-feedback landed 2026-07-10; next: blocks for the other
  topologies).
- Blocked on environment: live Nexar BOM (credentials), LLM datasheet
  extraction (API key / local server), DigiKey reference-design site
  (403s curl; local packs via ingest-reference sidestep it).
