# PCB Design Rules Knowledge Base

Date: 2026-07-02

Governance: this file is the authoritative rulebook. AI reviewers currently
edit it directly with user permission; once rule confinement is enabled they
must instead propose changes in `docs/ai-rule-suggestions.md` for human
promotion. Rules with machine checks are enforced by
`src/pcbsmith/kicad/design_checks.py`; every promoted rule should gain one.

Status: v1 — general rules PCBSmith encodes as circuit composition, placement,
routing, and review predicates. Every rule cites its source. Rules marked
`pending` gate features (notably: switching-converter board generation stays
`not_run` until every rule in section 3 has a machine check).

Sources:

- `TI-DS`: Texas Instruments LM2596 datasheet, SNVS124G (Nov 1999, rev Mar
  2023), cached at `ai_assets/datasheets/ti-lm2596.pdf`.
- `REF-BC2596`: PCBWay community reference design `BC-LM2596-ADJ.kicad_sch`
  (Ampnics, KiCad 9.0.1) — the ubiquitous LM2596 module.
- `SESSION`: review findings from generated boards in this repo (see
  `outputs/` revisions and git history).

These rules are deliberately general: they came from one regulator's
documentation, but each is stated as the transferable principle so it applies
to future, more complex designs.

## 1. Connectors and off-board interfaces

- **1.1 Connectors belong at board edges or corners.** Off-board wiring must
  not reach into the interior of the board. (`SESSION` — human review caught
  interior placement; `REF-BC2596` uses four single-pin pads at the corners.)
  - Machine check: connector footprints are classified (`is_connector`); the
    first leads the row at the left edge and any further connectors close the
    row at the right edge, so power enters one side and exits the other.
    Status: **implemented** (`kicad/board.py`); edge-parallel orientation
    **pending** (needs escape routing).
- **1.2 Single-pin solder pads at corners are a valid connector style for
  modules.** (`REF-BC2596` J1–J4.) Status: **pending** (footprint library has
  no 1-pin pad entry yet).
- **1.3 Indicator LEDs sit near the board edge where they are visible.**
  (`REF-BC2596`; general product convention.) Status: circuit-level
  **implemented** for the buck (power LED branch); placement rule **pending**.

## 2. Capacitors and decoupling

- **2.1 Every bulk electrolytic gets a small parallel ceramic (typ. 100 nF)
  for high-frequency decoupling, placed closest to the IC pin it serves.**
  (`REF-BC2596` C2/C4 beside C1/C3.) Status: circuit-level **implemented**
  (buck compose adds `CIN2`/`COUT2`); proximity placement rule **pending**.
- **2.2 Input capacitors are selected by RMS ripple-current rating, not just
  capacitance** — for a buck, roughly half the DC load current. Tantalums
  additionally need surge-current-tested series. (`TI-DS` §9.2.2.2.)
  Status: **pending** (evidence fact `ripple_current_a_rms` + selection check).
- **2.3 Output capacitor ESR, not capacitance alone, governs output ripple
  and loop stability.** Capacitance formulas give a floor; the datasheet ESR
  window is binding. (`TI-DS` design procedure; calculator emits this
  warning.) Status: warning **implemented** (`calculators/electronics.py`);
  ESR evidence check **pending**.

## 3. Switching-converter layout (safety-relevant — gates board generation)

Quoting `TI-DS` §9.4.1: "layout is very important … wires indicated by heavy
lines must be wide printed-circuit traces and must be kept as short as
possible. For best results, external components must be placed as close to
the switcher IC as possible using ground plane construction or single point
grounding."

- **3.1 Minimise the high di/dt loop area.** For a buck this loop is
  input cap → VIN pin → switch → catch diode → ground → input cap. Traces in
  it are wide and short. Status: **partially implemented** — power nets carry
  a 3x weight in the row-ordering cost, which pulls the power path into
  adjacent placement (a 1-D loop-length minimisation); true 2-D loop-area
  minimisation and a ground plane remain **pending** and are flagged in every
  buck board report.
- **3.2 All power externals (diode, inductor, in/out capacitors) cluster
  tightly around the IC; ground via a plane or a single point.** (`TI-DS`
  §9.4.1.) Status: **partially implemented** (adjacency via weighted
  ordering); ground plane **pending**.
- **3.3 Feedback components sit next to the IC, and the feedback trace routes
  away from the inductor.** The FB node is high impedance; coupling from the
  switch node or inductor flux corrupts regulation. (`TI-DS` §9.4.1, §9.1.7.)
  Status: **pending**.
- **3.4 Open-core inductors need a flux keepout** over feedback, IC ground
  path, and output-capacitor wiring; prefer shielded inductors. (`TI-DS`
  §9.4.1.) Status: **pending** (evidence fact: inductor core type).
- **3.5 Thermal copper for power tabs.** A TO-263 tab wants its dissipation
  pour: ~2.5 in² of 1 oz copper single-sided (or 3 in² + 16 in² double-sided)
  per `TI-DS` thermal notes. Status: **pending**.
- **3.6 Net roles drive trace width.** Switching/power nets get wide traces;
  width follows current, not aesthetics. (`TI-DS` §9.4.1; archived board
  builder.) Status: **implemented** — topology names its power nets and the
  router uses 0.8 mm tracks / 0.8-0.4 vias for them, 0.3 mm for signals.

## 4. Placement logic

- **4.1 Physical order follows the signal chain**, minimising total copper
  span — not reference-designator order. (`SESSION` — visual review caught
  alphabetical placement.) Status: **implemented** (exact net-span
  minimisation for ≤8 parts in `kicad/board.py`).
- **4.2 Feedback/adjustment parts group with their IC** (special case of 3.3
  that applies to any regulator, ADC reference, or bias network). Status:
  **pending**.

## 5. Mechanical

- **5.1 Mounting holes at board corners** for enclosure or standoff mounting.
  (`SESSION` — user reference photos; ubiquitous on real modules.) Status:
  **pending** (needs parity-exempt `board_only` footprints).
- **5.2 The board outline sits inside the drawing-sheet frame** and wraps the
  design with a small uniform margin. (`SESSION`.) Status: **implemented**.

## 6. Verification ritual (applies to every design)

1. Deterministic calculators run before any file is generated; calculator
   errors block generation. (Roadmap non-negotiable.)
2. KiCad ERC on the schematic; KiCad DRC **with schematic parity** on any
   board.
3. Simulate what can honestly be simulated; name what cannot. A switching
   regulator without a vendor model gets an open-loop averaged power-stage
   check and an explicit "closed loop NOT simulated" finding — never silence.
4. Render previews (3D + 2D review plot + schematic SVG) so both human and
   model eyes review every revision. Some defects only appear visually.
   (`SESSION` — alphabetical ordering, interior connectors.)
5. Each design revision goes to a fresh `outputs/<name>-rNNN` directory;
   failed revisions are kept for comparison.
6. A DRC/ERC pass is EDA validation, not proof of electrical correctness.
   Boards ship from this tool marked `needs_human_review` until a human
   signs off. (Project reset lesson, 2026-05-18.)
