# PCBSmith Hardening & Generalization Plan

Date: 2026-07-06

Status: Action plan following the challenge-board audit (clover `a817b5d`,
pear `0e2978a`, metal detector `21a5b35`). Companion to
`circuit-intelligence-roadmap.md`; does not replace it.

## The Problem This Plan Solves

The audit finding, in one sentence: **the pipeline works, but a large share
of the working knowledge lives in the AI operator's session craft rather
than in code, checks, or reusable tooling.** Three symptoms:

1. Rules discovered on the challenge boards (no pour under coils, outline
   simplicity, pour-cell sealing, courtyard spacing on curves) are written
   in `pcb-design-rules.md` but almost none are machine-enforced. The
   ratchet — every live-DRC failure becomes a deterministic check — was
   only partially applied.
2. Each shaped board is a bespoke module. Clover, pear, and detector share
   obvious DNA (outline splicing, offset paths, units-along-paths, stitch
   bridges, clipped silk) that exists three times with variations.
3. DRC iteration is human-in-the-loop geometric reasoning with a full
   KiCad regeneration per round (~15 rounds on the clover). The failure
   classes repeat; the fixes repeat; neither is automated.

Plus three debts: formulas encoded from the operator's memory without
independent verification, generic parts without datasheets, and outputs
that stop one step short of fabrication.

## Non-Negotiable Principles (inherited, plus two new)

All principles from the circuit-intelligence roadmap hold. Two additions:

- **A rule that is not a check is a wish.** Every entry in
  `pcb-design-rules.md` carries an enforcement status; new rules land with
  their check in the same commit, or with an explicit `unenforced` marker
  and a tracking entry in this plan.
- **No assumed geometry.** Board code never hardcodes a pad position,
  rotation convention, or footprint dimension that the library can
  provide. Convention facts (rotation direction, mirror behavior) are
  pinned by probe tests, not comments.
- **Every AI-facing capability is a narrow, schema-validated tool.** New
  capabilities (checks, fix proposals, extraction) are exposed through
  small function interfaces with strict JSON-serializable inputs and
  outputs — never "run arbitrary shell / edit arbitrary files". This is
  what makes the pipeline drivable by a local model later (Track 5)
  without retrofitting.

---

## Track 1 — Make the knowledge machine-enforced

### 1.1 Promote §7–§9 rules into design checks

Motivation: rules 7.2, 9.1–9.4 and the outline lessons are prose.

Deliverables in `kicad/design_checks.py` (each parametrized via
`DesignChecksSpec`, findings with the rule id):

- `outline_is_simple` — the segment-intersection probe (already written
  three times as per-board tests) runs on every `BoardLayout.outline`,
  always. Blocker.
- `pour_keepout_regions` — spec lists keepout circles/polys (e.g. the
  coil disc); check asserts no zone rect and no non-whitelisted copper
  intersects them. Enforces 9.1. Blocker.
- `mask_opening_hygiene` — silkscreen graphics and reference texts must
  not intersect declared mask-opening regions (9.3). Warning.
- `net_tie_bom_parity` — components on net-tie footprints must be BOM
  excluded in the schematic export (9.2; the detector hit this live).
- `every_net_labelled` — walk the schematic exporter's output for nets
  without labels (rule 7.2, currently enforced only by convention).

Acceptance: regenerate all 8 topologies; all checks run; zero new
findings on the committed-clean boards; a deliberately broken fixture
(pour under coil, self-intersecting outline) fails each check in unit
tests.

Effort: 2–3 sessions. No dependencies.

### 1.2 Convention probe tests

One test module, `tests/unit/kicad/test_conventions.py`, that pins the
facts we paid DRC iterations to learn:

- front rotation 90/180/270 pad positions for a two-pin part (rot-90 puts
  pad 1 at the bottom);
- back-side placement uses the inverse angle before the x-mirror;
- pad and text angles in `.kicad_pcb` are total angles;
- net-tie pad groups survive embedding verbatim.

Acceptance: each probe reads the real library footprint and asserts the
transformed coordinates numerically. Effort: 1 session.

### 1.3 Formula verification (the "sim-agrees-with-itself" gap)

Motivation: the Mohan coefficients and Colpitts math were written from
the operator's memory. The 0.1% sim/calc frequency match validates the
netlist wiring, not the inductance — the sim consumes the calculated L.

Deliverables:

- Cross-check `solve_pcb_spiral_inductor` against a second independent
  estimator (modified Wheeler) inside the calculator; disagreement > 10%
  becomes a warning on the output.
- A `references/` evidence note per calculator: fetch the actual source
  (Mohan 1999 abstract/tables, or a vendor app note with a worked
  example) with the existing datasheet-fetch + sha-manifest machinery,
  and add a test that reproduces the published worked example.
- Apply the same pattern to `solve_lm2596_buck` (already has the TI
  datasheet) and `solve_i2c_pullup` (NXP UM10204 worked example).

Acceptance: every calculator's test file contains at least one assertion
traceable to a fetched, sha-pinned document. Effort: 1–2 sessions,
network required for fetches.

---

## Track 2 — Generalize the craft

### 2.1 Virtual DRC (fast pre-checks)

Motivation: ~90% of all live-DRC iterations across the three boards were
four failure classes. A Python implementation gives instant feedback and
enables machine-proposed fixes later.

Deliverables, new module `kicad/virtual_drc.py` operating on
`BoardLayout` + `FOOTPRINT_LIBRARY` before any KiCad invocation:

- courtyard–courtyard overlap (arbitrary rotations, exact polygons);
- track/via vs pad clearance across nets (segment-to-rect distance);
- copper vs outline edge clearance (distance to the outline polygon);
- pour-cell connectivity: build the planar subdivision of a zone rect cut
  by traces/pads with clearance halos, flood-fill, and report cells that
  contain same-net items but no connection to the main region — the
  sealed-cell class that cost the most iterations;
- track–track crossing on the same layer across nets.

Wire into `_board_authority`: run virtual DRC first; on findings, skip
kicad-cli and report (fast fail). kicad-cli DRC remains the authority —
virtual DRC is a pre-filter, never a replacement.

Acceptance: replay test — feed the archived failing intermediate layouts
from the challenge-board iterations (reconstructible from git history of
the board modules) and assert virtual DRC flags what live DRC flagged.
Regeneration of the 8 clean boards yields zero virtual-DRC findings.

Effort: 3–4 sessions. The pour-cell analysis is the hard part; ship the
first four checks before it. Unlocks 2.3.

### 2.2 Art-board toolkit

Motivation: three bespoke modules; the fourth shaped board should be
composition, not authorship.

Deliverables, new module `kicad/shaped_board.py`, extracted from the
existing three (which become thin consumers — behavior-preserving
refactor verified by regenerating byte-comparable boards):

- `OutlineSpec`: closed base shape (circle, two-circle hull, arc-union)
  plus tab splices (the clover stem / pear stem / detector handle are one
  parametrized operation);
- `OffsetPath`: the piece-based path model from the pear (arcs + lines
  with exact tangent/normal/curvature), generalized to any outline built
  from the primitives above;
- `place_along_path`: pitch-based unit placement with curvature-aware
  skipping and tangent rotations;
- silk primitives: filled poly, clipped-circle outlines (occlusion
  chains), text, mask-opening region;
- routing primitives: `stitch_bridge` (via–trace–via over a free layer),
  `radial_stub`, `bus_loop`, and the computed-pad helpers (`pad`,
  `pad_for`) as the only sanctioned way to reference pads;
- `pour_spec`: zone regions with declared keepouts (feeds 1.1's check).

Acceptance: clover, pear, and detector regenerate DRC-clean from the
toolkit with their modules reduced to data + topology-specific routing;
line count of the three modules drops by roughly half.

Effort: 3–4 sessions. Do after 2.1 so refactor mistakes are caught fast.

### 2.3 Assisted routing for small nets

Motivation: hand waypoints are the remaining fragility; the handle
clusters are small enough for search.

Deliverable: a grid A* router (0.1 mm grid, clearance-inflated
obstacles from virtual DRC's geometry, two layers + via cost) used for
short point-to-point nets inside a declared region. Hand waypoints stay
available; the router is opt-in per net.

Acceptance: the metal detector's handle routes fully by router with zero
virtual-DRC findings; diff review confirms sane paths.

Effort: 3 sessions. Depends on 2.1's geometry layer. This is the last
step of the track, not the first — the primitives already remove most of
the pain.

---

## Track 3 — Make outputs real

### 3.1 Fabrication package export

Motivation: a DRC-clean `.kicad_pcb` is one `kicad-cli` step away from
an orderable zip.

Deliverables: `pcbsmith fab-package <rev-dir>` producing
`fab/<name>-fab.zip`: gerbers + drill (`kicad-cli pcb export gerbers`,
`drill`), pick-and-place positions (`pos`), and a generated
`fab-notes.md` (layer count, finish recommendation pulled from findings
— e.g. the detector's ENIG note — board size, exposed-copper regions).
Board authority gains a `fabrication` artifact section; bundle status
unchanged (packaging adds no new truth).

Acceptance: package generated for all 8 topologies; gerbers reimport
cleanly in KiCad's gerber viewer (spot-check); zip contents listed in
the bundle. Effort: 1–2 sessions.

### 3.2 BOM with real parts (Nexar into selection)

Motivation: `evidence/nexar.py` exists but part selection still emits
"R 2k 0603" instead of an orderable MPN.

Deliverables: `pcbsmith bom <rev-dir> [--nexar]` producing `bom.csv`
(reference, value, footprint, MPN, manufacturer, datasheet URL, stock,
price) — offline mode fills what the composition knows, `--nexar` mode
queries live and caches into the evidence manifest. Selected MPNs feed
back into `ComponentRole` as evidence refs, moving parts from
`demo_only` toward `supported`.

Acceptance: detector BOM lists a real MMBT3904 MPN with its datasheet
registered in a manifest. Effort: 2 sessions, needs Nexar credentials.

### 3.3 Assembly artifact (undo the hidden-references trade)

Motivation: silk warnings were resolved by hiding references, trading
away hand-assembly usability.

Deliverable: extend `kicad/preview.py` with an assembly view — top-side
plot with courtyards, reference callouts with leader lines (placed by a
simple label-scatter that avoids overlaps), and value table. Emitted as
`board_assembly_plot` artifact by every board authority.

Acceptance: assembly PNGs for the three challenge boards show every
hidden reference legibly. Effort: 1–2 sessions.

### 3.4 Evidence debt for recurring generics

Fetch + extract (existing in-session extraction pattern) datasheets for:
MMBT3904 (onsemi), a concrete green 0603 LED (e.g. Kingbright
APT1608SGC), and the already-evidenced parts stay as-is. Add
`select_metal_detector_components` mirroring the mpu6050 validator so
`--evidence-manifest` works for the detector.

Acceptance: detector rerun with manifest reports Q1 `supported`.
Effort: 1 session, network required.

---

## Track 4 — Learning, regression, and process

### 4.1 Golden-board regression suite

Motivation: a router or library change can silently break seven other
topologies; today only unit tests would notice.

Deliverable: `tests/golden/test_regenerate_all.py` (opt-in marker, needs
kicad-cli + ngspice): regenerates every topology into a temp dir,
asserts ERC pass, sim pass, DRC zero violations/zero unconnected, and
revision-plan clean. A `make golden` / documented command runs it before
any commit touching `kicad/` or `calculators/`.

Acceptance: suite green on current HEAD; deliberately breaking a router
constant fails it. Effort: 1 session (runtime ~10 min is acceptable).

### 4.2 Board-diff learning from user edits

Motivation: the user's hand edits are the highest-quality training
signal (P1's rotation became rule 8.3). Today they are noticed manually.

Deliverables: `pcbsmith board-diff <rev-dir>` — parse the (possibly
user-edited) `.kicad_pcb` with the existing s-expr layer, diff placements
/rotations/track routes against the stored `BoardLayout`, and emit a
structured `human-edits.json` plus draft entries in
`docs/ai-rule-suggestions.md` ("P1 moved from X to Y — candidate rule?").
The revision planner treats an un-reviewed edits file as
`needs_human_review`.

Acceptance: hand-move a component in KiCad, run board-diff, get a
correct, human-readable delta and a suggestion stub. Effort: 2 sessions.

### 4.3 Reference-design ingestion (DigiKey library)

Motivation: user-supplied source; topology library should grow from
grounded designs, not only from operator knowledge.

Approach (start narrow): pick 2–3 reference designs (power + sensor),
cache their PDFs into evidence manifests, extract the parts/topology
facts in-session (the proven extraction pattern), and encode each as a
topology template with `reference_design` evidence refs — the same
lineage the BC-LM2596 board already has. Defer any automated scraping;
this is curation, not crawling.

Acceptance: one new topology whose every component carries a
reference-design locator. Effort: 2 sessions per design, network.

### 4.4 Repo hygiene

- `.gitignore`: `outputs/`, `Spice64/`, `.pytest_cache/`,
  `.cleanup-archive/`, `*.lck`; document that ngspice should eventually
  live outside the repo (path already configurable).
- Kill the stale-`__pycache__` and permission-locked directories noted in
  the roadmap.
- Line-ending policy (`.gitattributes` with `* text=auto eol=lf` for
  source) to end the CRLF warning noise.

Acceptance: `git add -A` is safe; `git status` is quiet after a full
pipeline run. Effort: half a session. **Do this first — it is the only
item that prevents accidents rather than adding capability.**

### 4.5 Trace-current and thermal checks (circuit depth)

- IPC-2221 external-layer current capacity calculator; check net-role
  trace widths against computed load currents (buck power path, LED ring
  totals). Rule 3.x addition with enforcement in the same commit (per the
  new principle).
- Finish rule 3.5 (thermal pour area vs datasheet R-theta) for the buck.

Effort: 1–2 sessions.

### 4.6 Intent layer upgrade (deferred, gated)

Keyword matching stays until the user-facing layer starts. When it does:
LLM classification as a *proposal* mapped onto the existing intent ids
with the keyword matcher as validator (both must agree or the request is
`needs_human_review`) — consistent with the "AI output is a proposal
only" principle. No work now; recorded so it is not reinvented.

### 4.7 Local-model runway (Track 5, design constraint now, code later)

Motivation: today the pipeline works because the operating AI brings a
full agent harness — tool loop, file editing, shell, vision. A local
model behind llama-server has none of that, and the 2026-05 KoboldCPP
experiment showed mid-size models emit malformed tool calls when the
output is unconstrained.

What changes NOW (costs nothing, shapes Waves 1-3):

- every capability lands as a narrow function with schema-typed I/O (see
  the new principle above): `run_virtual_drc(layout) -> findings[]`,
  `propose_patch(rule_id, parameter, value)`, `classify_intent(text)`,
  `extract_facts(pdf, roles)` — the AI chooses among machine-verified
  options; it never computes geometry or arithmetic (calculators and the
  virtual DRC own all numbers);
- findings/fix objects stay JSON-serializable so they can round-trip
  through any model.

What comes LATER (after Waves 1-2 shrink the reasoning burden):

- a thin local harness: llama-server (already being stood up for the
  Exam Generator) with **grammar-constrained decoding** (GBNF /
  JSON-schema at the sampler) so malformed tool calls become impossible,
  not merely repaired; Phase G's repair layer demotes to a fallback;
- the tool registry: a dozen PCBSmith functions exposed OpenAI-tools
  style, with the existing `evidence/llm.py` client as the base;
- vision is a nice-to-have, not a correctness dependency: local mmproj
  models can be tried for render review, but anything the model "must
  notice by looking" is by definition a missing deterministic check.

Realistic capability ladder for a ~30B local model once Waves 1-2 land:
intent classification, datasheet fact extraction, review-finding triage,
parameter-level patch proposals. Out of scope: authoring new board
topologies from scratch (templates and the toolkit carry that).

### 4.8 Front-end readiness contract (no code yet)

The backend already emits everything a UI needs. Freeze the contract in
one doc page: revision directory layout, bundle schema id, artifact keys,
the `review-comment` CLI as the comment API, and the px↔mm mapping the
review plot must expose. Acceptance: a UI could be built against the doc
without reading source. Effort: half a session.

---

## Track 6 - Component onboarding (new part -> trusted building block)

Motivation (user, 2026-07-06, after reviewing the buck in KiCad): today a
new IC requires the operating AI to hand-draw a schematic symbol, hand-
build a pin-net table, and hand-read the datasheet. The knowledge of HOW
to use the part (which pins are mandatory, which are reviewed
no-connects, what support parts the maker requires) lives nowhere the
machine can check. Rule 7.3 (`ic_pin_connectivity`) now guards the
worst symptom - a silently forgotten pin - but the onboarding itself
must become a pipeline.

### 6.1 Official KiCad SYMBOL import

We already embed official footprints verbatim; symbols are still
hand-drawn boxes. The installed share ships the full symbol library
(`share/kicad/symbols/*.kicad_sym`, e.g. `Regulator_Switching` contains
LM2596S-ADJ with real pin names/numbers). Deliverable: `kicad/symbols.py`
mirroring `library.py` - parse the .kicad_sym s-expr, vendor the used
symbols under `ai_assets/kicad_symbols/`, embed verbatim into generated
schematics with injected reference/value/footprint properties. Pin
positions come from the symbol, killing the label-placement guesswork.
Effort: 2-3 sessions.

### 6.2 The component card

One JSON per part under `ai_assets/components/<mpn>.json`, produced by
the extraction pipeline from a sha-pinned datasheet, holding the machine-
checkable contract:

- pin table: number, name, function class (power_in, gnd, output,
  feedback, enable, nc_reserved, ...), connection requirement
  (required / optional / must_tie_to with target), with page locators;
- absolute limits and operating windows used by the evidence validators;
- mandatory support parts from the typical-application section (the
  LM2596 card would demand the catch diode, the output LC, and ON/OFF
  disposition) - compositions get validated against the card;
- symbol id + footprint id + verified pin-number mapping between them.

The card REPLACES per-topology hand knowledge: `allowed_unconnected_pins`
derives from `nc_reserved` pins, `must_tie_to` feeds a new check (e.g.
ON/OFF must reach GND), and the evidence selector reads limits from it.
Effort: 2 sessions for the schema + generator, then one card per part.

### 6.3 Acquisition front door

`pcbsmith onboard-component <mpn>`: resolve datasheet URL (Nexar when
credentialed, else --datasheet PATH/URL), cache + sha-manifest, run
extraction (in-session AI or the llm.py clients) into a DRAFT card,
verify symbol/footprint availability in the official libraries (vendor
them), and emit a review summary. Cards start
`support_status=needs_datasheet_review`; a human (or later a validated
extraction) promotes them. New parts never silently enter compositions -
the card is the gate. Effort: 2 sessions after 6.1/6.2.

### 6.4 Checks that consume the cards

- `must_tie_to` connectivity (ON/OFF-class pins) - schematic-level;
- mandatory-support-part presence (catch diode class) - composition
  level;
- card-vs-footprint pad census (every card pin exists on the footprint
  and vice versa) - onboarding level.

Sequencing: 6.1 alone already upgrades every existing board's schematic
quality; 6.2+6.4 retire the hand-maintained pin tables; 6.3 makes new
parts a command instead of a session. Slot after Wave 4's evidence
fetches (the card generator IS the extraction pipeline pointed at pin
tables).

## Progress (2026-07-06)

- DONE: 4.4 hygiene; 2.1 virtual DRC (first four checks; pour-cell
  analysis pending); 1.1 (outline_is_simple, copper_keepout; net-tie BOM
  parity resolved as kicad-parity-enforced; net labelling as
  by-construction+ERC); 1.2 convention probes; 4.1 golden suite; 1.3
  Wheeler cross-check (evidence fetches pending); 2.2 art-board toolkit
  (geometry-hash-verified); 3.3 assembly artifact; 3.1 fab package; 3.2
  offline BOM half; 4.5 IPC-2221 current check (thermal 3.5 still
  pending); 4.8 front-end contract.
- DONE (later same day): 7.3 ic_pin_connectivity check (buck review
  scare: a forgotten IC pin is invisible to ERC and DRC alike); clover
  and MPU authorities carry reviewed NC whitelists derived from their
  pin-net tables.
- DONE (2026-07-06 final sweep): 4.2 board-diff (live-tested on the
  user's hand-edited buck r010: D1 moved -6.5mm, recorded as a rule
  candidate; layout.json snapshots now emitted by every authority); 2.1
  pour-cell connectivity check (grid flood-fill, lenient-by-design so a
  clean board never flags; sealed-cell fixture proves it fires); 7.5
  required-support check (cards' mandatory parts vs composition roles,
  explicit aliases; missing catch diode = blocker); green LED evidence
  upgraded to the fetched Kingbright APT1608SGC datasheet (VF 2.2V typ
  confirmed) in clover+pear compositions.
- ASSESSED: digikey-kicad-library (github) - officially unmaintained,
  pre-v6 format; NOT a symbol source (ours is better) but its per-part
  metadata (MPN + DK datasheet link + 1:1 footprint mapping) is a good
  seed table for onboard-component later. digikey.com/reference-designs
  is bot-walled to curl (403) - ingestion (4.3) needs a browser-assisted
  session or manually downloaded design PDFs.
- BLOCKED (environment): MMBT3904 datasheet (onsemi/diodes/smc/archive
  all bot-walled - card annotated with attempts); live Nexar (no
  credentials in env); LLM extraction + local-model spike (no API key,
  no llama-server yet).
- NOTED: tests/unit/core/test_geom.py::test_point_add_sub_inverse is a
  latent hypothesis flake (float-precision example found once, passes on
  rerun; .hypothesis cache unwritable since the reinstall).
- REMAINING: 2.1 tightening (polygon-exact pour analysis); 1.3/3.4 evidence fetches
  (network session); 3.2 live Nexar; 4.2 board-diff learning; 4.3
  reference-design ingestion; 2.3 assisted routing; 4.7 local-model
  harness spike; 3.5 thermal check; Track 6 component onboarding
  (6.1 symbol import first).

## Execution Order

Wave 0 (immediately, half a session):
- 4.4 repo hygiene.

Wave 1 (highest compounding value):
- 2.1 virtual DRC (first four checks, then pour-cell analysis)
- 1.1 rules-to-checks + 1.2 convention probes
- 4.1 golden-board regression (protects everything that follows)

Wave 2 (generalization):
- 2.2 art-board toolkit (refactor under golden-suite protection)
- 3.3 assembly artifact
- 1.3 formula verification

Wave 3 (outputs become real):
- 3.1 fab package
- 3.2 BOM/Nexar + 3.4 evidence debt
- 4.5 current/thermal checks

Wave 4 (learning loops):
- 4.2 board-diff learning
- 4.3 reference-design ingestion
- 2.3 assisted routing
- 4.7 local-model harness spike; 4.8 front-end contract; 4.6 stays gated

Rough total: 20–25 working sessions. Each wave leaves the repo green
(golden suite from Wave 1 onward) and each item lands with its tests and
rulebook updates in the same commit.

## Done Means

- A shaped board never written before can be produced by composing
  toolkit primitives, passes virtual DRC before KiCad ever runs, and
  ships as a fab zip with a real-part BOM and an assembly diagram.
- Every rule in `pcb-design-rules.md` either has a running check or an
  explicit `unenforced` marker pointing at this plan.
- Every calculator traces to a fetched document, not operator memory.
- A user edit in KiCad becomes a structured suggestion without anyone
  reading coordinates by hand.
