# The mistake ledger — every failure class, where it was found, what to watch for

Written 2026-07-12 as institutional memory. Format: WHAT went wrong →
HOW it was discovered → THE FIX → WATCH OUT. The rulebook holds the
enforced form; this file holds the stories so successors understand
why the checks exist and where the next mistakes will come from.

## A. Geometry modeling mistakes (the biggest class)

1. **Custom pads modeled by their anchor size.** The SHT31 DFN's
   exposed pad is a KiCad "custom" pad: `(size 1 1)` anchor + a
   1.0x1.7 polygon in `(primitives ...)`. Every consumer modeled
   1.0x1.0; the router parked a /SCL1 via on the unmodeled lobe →
   live shorting_items. FOUND by kicad-cli DRC, decoded from
   drc.json positions. FIX: `library._custom_pad_extents` (primitive
   bbox + recentered anchor). WATCH: any NEW pad shape attribute
   (chamfered, trapezoid) will repeat this — grep the .kicad_mod for
   shape keywords when adding footprints.
2. **Unnamed drilled pads skipped as "paste helpers".** USB-C shell
   NPTH alignment holes have no name and no net; _collect_items
   skipped all unnamed pads → six tracks and a via routed THROUGH
   the holes. FOUND live (hole_clearance x12). FIX: unnamed pads with
   drill > 0 become net-less `~hole:` obstacles whose radius carries
   the 0.25 mm hole-to-copper excess; np_thru_hole keeps a distinct
   "npth" kind. WATCH: slots (oval drills) store only max drill dim;
   a slot wider than its copper is still under-modeled on one axis.
3. **Vias given the TRACK's edge margin.** Outline edge cells were
   computed at clearance + width/2; a 0.2 mm net could legally park a
   via 0.6 mm from the curved stem edge (needs 0.5 + via radius 0.3).
   FOUND live (edge_clearance x2). FIX: separate via edge mask.
   WATCH: any NEW mask (keepouts, moats) needs the same via-vs-track
   distinction.
4. **Redundancy pruning blind to its own new vias.** Junction slivers
   fully inside a fresh via barrel survived pruning → rule 11.2
   blockers. FIX: route's own vias join the prune covers.
5. **Bboxes where hulls belong** (historic, bit twice): courtyard and
   fab-body checks false-positived at round corners. FIX: convex
   hulls with sampled arcs. WATCH: law 3 — when the virtual DRC
   false-positives, the model OVERestimates somewhere; find the bbox.
6. **fp_rect parsed as two diagonal corners** → hull degenerated to a
   line and was discarded → courtyard checks blind for terminal
   blocks/discs. FOUND by flyback live DRC. FIX: 4-corner expansion +
   regression pinning real library extents.
7. **Pad/text angles are TOTAL angles in .kicad_pcb** (footprint +
   local) while positions stay footprint-local. Forgetting physically
   un-rotates pads — live DRC shorts every pin pair. Same family:
   back-side = INVERSE rotation then x-mirror; KiCad rot 90 maps
   (right,down)→(up,right) with y pointing DOWN.
8. **Duplicate pad numbers are separate physical pads** (SW_PUSH has
   two "1"s): connectivity keys by (label AND position). FOUND live:
   ratsnest demanded copper at the twin.

## B. Router lessons (beyond geometry)

1. **Sequential per-net A* has a hard ceiling.** The thermometer
   (53 nets, 24 mm stem) produced SEVEN successive single-net
   failures (VBUS→DM→CAS→SEG9→SEG6→SEG5→LK4→SER→SRCLK); each fix
   moved the failure. Rip-up-by-reordering (promote failed net) is an
   MVP, not a solution — congestion is global. CONSEQUENCE: bus-group
   routing + placement-driven corridors (the active plan). Do not
   hand-iterate placements against this router again.
2. **Order is leverage**: fine-pitch nets FIRST (0.5 mm-pitch pads are
   unreachable on the 0.2 grid — parities alternate by 0.1 mm; hence
   the 0.1 mm pre-route phase), long inflexible trunks before short
   local nets (probed: /SER routes in one try when first, dies after
   16 restarts when last), rails LAST (most pads = most freedom).
   Declaration order in FINE_PITCH_NETS is priority — a data lever.
3. **Grid parity math**: pad-center-on-grid decides feasibility.
   Anchor offsets like x=23.05, y=130.05 exist ON PURPOSE to land
   0.5 mm-pitch pads on the fine grid. Changing a placement by
   "just 0.1 mm" can wall a whole pad row.
4. **Fat nets wall skinny ones**: a 0.4 mm crossbar across a pad-row
   mouth seals every 0.2 mm escape. If a corridor is shared, the
   pad-pinned nets go first and the fat net dives layers.
5. **Grid routers emit staircases** unless: 8-connected moves with
   corner-cut guard, TURN_PENALTY in the search state, string-pull
   smoothing against the same blocked sets, collinear merge keeping
   ORIGINAL endpoints (reconstructing from line params drifts 1e-7),
   prune only by AREA containment. The user personally caught the
   0.2 mm stacked pieces in the KiCad editor — appearance is audited.
6. **The routing tree must absorb connected pads** (`tree |= targets`)
   or later legs lay parallel copper — 44% of the servo board's
   segments were redundant before this one line.

## C. Placement lessons

1. **Put drivers IN their load zones**: the inverted U2/U3 register
   arrangement made all 16 SEG nets cross the other register's zone.
   Check the net fan-out direction per IC before fixing coordinates.
2. **Columns follow SOURCE PIN SIDE, not aesthetic parity**: a TSSOP
   '595 exposes 7 outputs on one column — an odd/even resistor split
   forced 7 of 8 nets across the board center. Probe pin sides first.
3. **Respect pin bands**: a part whose connection lane crosses
   another IC's pin row at the same y is unroutable at that y; slide
   it out of the band (the LK4 lesson). Only user-visible parts
   (LEDs) must hold exact positions; back-side support parts slide.
4. **Courtyard pitch is probeable in seconds** — `FOOTPRINT_LIBRARY`
   hulls + arithmetic BEFORE burning a 40-minute route. Every
   hand-guessed clearance in project history was wrong at least once.
5. **Sensor thermal placement is a correctness issue**, not comfort:
   1 C parasitic heating = 5 %RH error at 90 %RH (Sensirion). The
   thermometer r001 draft still owes the moat + thin traces.
6. **Antenna zones**: thermometer r001 points the module antenna into the
   board interior over bulb copper. Pinned Espressif guidance prefers antenna
   overhang/feed at the edge or a module-specific cutout on both sides and
   below. Its 15 mm value is enclosure/object clearance, not blanket PCB
   copper clearance. No check exists yet (plan phase 3).
## D. KiCad interop traps (cost real hours each)

- kicad-cli silently DROPS unlabeled nets from ERC and netlist export
  — every stub needs a label (the founding label-net lesson).
- ERC JSON positions are sheet-mm x 1/100 (multiply by 100); lengths
  too. DRC JSON is mm but offset by BOARD_SHEET_ORIGIN (20,20).
- Board DRC constraints come from the SIBLING .kicad_pro — a board
  file alone is judged by defaults (min hole 0.3 broke the ESP32
  module's 0.2 thermal vias until `_render_project(min_through_hole_
  mm=)`).
- Re-saved boards store nets name-only; stroke blocks go multi-line —
  regexes over board text need two nesting levels.
- KiCad checks silk STROKES, not fills: own-label-over-own-body
  passes DRC if it misses the outline lines — dense silk still needs
  the live loop; the virtual model intentionally underestimates text.
- Wire-drawing rules in schematics: T-joints need shared endpoints +
  junction dots; a rail overhanging its last tap is an "unconnected
  wire endpoint" warning; label teleports (same label on disjoint
  islands) are how schematics lie — the reader validator forbids them.
- Symbol pin positions/text angles: PROBED conventions (angle =
  rotation for 90/270, 0 for 180; upright = rotation % 180 ? rotation
  : 0). Never derive from first principles — render and compare.
- Stacked pins (USB VBUS A4/A9/B4/B9) share one symbol point — one
  wire serves all four; the netlist still lists each.

## E. Process & environment mistakes (this machine)

- **Bash heredocs mangle**: f-strings, nested quotes, literal \n, AND
  regex character classes (three separate live failures). Any
  nontrivial script goes through the Write tool. Patch scripts that
  re-read the file between edits clobber their own earlier edits (the
  /CAS-never-actually-added incident — 40 min of routing wasted on a
  no-op config).
- Prefer direct Edit calls on live files; assert-count patch scripts
  go stale against the file while you iterate.
- Long jobs → run_in_background + notification; foreground sleep is
  blocked; polling loops must live inside one background command.
- Session rate limits kill agent fleets mid-flight (75 verifier
  agents died in the research workflow; one book agent died AFTER
  writing its file — check outputs before rerunning). Fan out in
  waves; make agents write results to files EARLY; salvage from
  workflow journal.jsonl.
- pytest: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, -p no:cacheprovider,
  ALWAYS ./.venv/Scripts/python.exe.
- Visual review paths that WORK: boards — kicad-cli pcb render
  --side top/bottom (also -review.png via preview.py); schematics —
  kicad-cli sch export svg → resvg_py (mm→px first) → Read the PNG.
  PDFs render only as text (pypdf); scanned PDFs → tools/book_ocr.py.
  Browser screenshots of SVG viewers are flaky — don't fight them.
- gitignore on Windows is case-insensitive: `Books/` swallowed
  `docs/reference/books/` until anchored as `/Books/`.

## F. Verification discipline (what kept this project honest)

- The golden suite catches what unit tests miss — run it for ANY
  kicad/ or calculators/ change; it has never false-alarmed.
- Every live-DRC failure class MUST become a virtual check or design
  check with a fixture test that PROVES it fires. This ratchet is the
  core mechanism — six silk round-trips became _check_silkscreen;
  the hole/custom-pad classes became permanent machinery the next day.
- LOOK at the renders. Text metrics, silk collisions, and "does it
  look like a thermometer" are not checkable yet; the -review.png and
  reader-SVG-to-PNG steps are mandatory, not optional.
- Report failures exactly (the user values honest status over green
  lights): unrouted is unrouted; assumption-level evidence is labeled
  assumption; NOT-simulated stages are listed in reconciliation.

## G. Research & knowledge process

- A freely available official source that closes an approved live gap must not
  stop at `online-verified` or `absent locally`. Attempt automatic retrieval,
  identity/cover verification, hashing, and manifest registration during the
  project; report `blocked` only with a concrete reason. Downloading still does
  not mean the guidance is production-integrated.
- Web research yields claims; BOOKS yield thresholds with mechanisms.
  The 9-source knowledge base (docs/reference/books/) is the durable
  extraction — never re-read the books wholesale; verify single
  locators against .book-cache when in doubt.
- Verify the user's beliefs too (their standing instruction): the
  45-degree "electrical" justification was folklore; their bus-routing
  instinct was exactly right.
- Vendor app notes vary in quality — encode a rule only with its
  mechanism + applicability range (Bogatin's discipline). One source
  claiming "app notes are usually bad" is itself just one source.
- When a fetched source contradicts a book, record BOTH with
  locators in the notes and pick explicitly (Ott same-value decap
  arrays vs decade-pair lore is the worked example).
