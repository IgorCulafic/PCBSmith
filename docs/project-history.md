# PCBSmith project history

A detailed narrative of what has been built, in order, with the
commits that carry each step. Written 2026-07-07 by Claude Fable 5 for
its successor models. The companion methodology document is
`/CLAUDE.md`; the enforced design knowledge is
`docs/pcb-design-rules.md`; the active plan is
`docs/hardening-and-generalization-plan.md`.

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

- **Clover** (commit `a817b5d`): shaped outline (four-leaf clover),
  silk art + motto, parts on the BACK (flip transforms — inverse
  rotation then x-mirror), zones as shaped-board power, bezier
  traces-as-art. Live DRC 0/0.
- **Pear** (commit `0e2978a`): two-circle convex-hull outline with
  exact parallel inward offsets, 49 tangent-following LED units on
  three rings (arbitrary-angle rotation support), worm silkscreen with
  occlusion-clipped circles.
- **Metal detector** (commit `21a5b35`): first FUNCTIONAL copper — a
  20-turn exposed spiral as the Colpitts tank inductor. Spiral
  inductance calculator (Mohan current-sheet, Wheeler cross-check),
  copper-only components via NetTie, soldermask-opening graphics,
  rule 9.1 (no pour under a sensing coil), and an ngspice TRANSIENT
  startup measuring 1.136 MHz vs 1.137 MHz calculated; a simulated
  metal-proximity inductance shift moved it +23.6 kHz.

## Hardening waves (2026-07-06, plan `docs/hardening-and-generalization-plan.md`)

Triggered by a post-challenge audit: "the project technically works,
but only because it's you doing it."

- **Waves 0-1** (commits `e49efdf`, `e17da2d`): repo hygiene;
  `kicad/virtual_drc.py` — stadium-model courtyard / copper-clearance /
  edge / (later) pour-connectivity pre-filter, wired before every
  KiCad run; rules→checks (`outline_is_simple`, `copper_keepout`);
  convention probe tests; the GOLDEN SUITE (`tests/golden`, gated by
  `PCBSMITH_GOLDEN=1`) regenerating every topology live and asserting
  terminal-clean.
- **Waves 2-3** (commits `8c99aa5`, `71984a4`): the shaped-board
  toolkit extracted (`kicad/shaped_board.py`: Router, Pieces,
  splice_rect_tab, silk primitives); assembly-view artifact;
  `fab-package` CLI (gerbers/drill/positions/notes/BOM zip); IPC-2221
  trace-current rule 5.3; frontend contract doc.
- **Rule 7.3** (commit `cca5fbd`): the "invisible forgotten IC pin"
  class (unwired pin = no ERC error, no DRC item) closed by the
  always-on `ic_pin_connectivity` check.
- **Track 6 — component onboarding** (commits `8820079`, `ae6291e`,
  `4e58ff8`, `c537b0a`): official SYMBOL import with
  extends-flattening (`kicad/symbols.py`); all IC exporters migrated to
  official symbols (PWR_FLAG semantics, native no-connects); component
  cards (`pcbsmith/components.py`, `ai_assets/components/*.json`) with
  pin requirement classes, must-tie enforcement (rule 7.4), required
  support parts (rule 7.5), card-driven NC whitelists; and the
  `onboard-component <mpn> --symbol --footprint` front door (live-tested
  on an NE555).
- **Final sweep** (commits `66db087`, `2c02d33`): `board-diff` — user
  KiCad edits become structured rule suggestions (live-tested on a
  hand-edited buck; every authority snapshots `layout.json`);
  pour-connectivity virtual check; green-LED datasheet fetched
  (assumption → datasheet_fact); DigiKey verdicts (old github lib =
  metadata seed only; reference site 403s curl).

## The flyback (2026-07-07, commit `7bf5029`) — first mains-isolated board

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

## Reference-driven hardening (2026-07-07, commit `864fd0b`)

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

## State at handoff (2026-07-07, HEAD `864fd0b`, branch codex/circuit-intelligence-slice)

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
