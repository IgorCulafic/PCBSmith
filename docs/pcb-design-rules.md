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

- **1.1 Connectors belong at board edges or corners — ANY edge.** Off-board
  wiring must not reach into the interior of the board; which edge is a
  layout choice, what matters is solder and wiring access. (`SESSION` — human
  review caught interior placement and later clarified that all four edges
  qualify; `REF-BC2596` uses four single-pin pads at the corners.)
  - Machine check: connector footprints are classified (`is_connector`); the
    first leads the row at the left edge and any further connectors close the
    row at the right edge, so power enters one side and exits the other.
    Status: **implemented** (`kicad/board.py`); edge-parallel orientation
    **implemented** in both layouts — the official 1x02 vertical header
    stacks its pins along the edge, and the row channel gives each stacked
    pad its own escape column (`_connector_escapes`) so drops never pass
    through a neighbouring pad.
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
  §9.4.1.) Status: **implemented** — adjacency via weighted ordering plus a
  full-board B.Cu ground plane (`ground_pour`), zone-filled and DRC-checked
  by KiCad (`--refill-zones`).
- **3.3 Feedback components sit next to the IC, and the feedback trace routes
  away from the inductor.** The FB node is high impedance; coupling from the
  switch node or inductor flux corrupts regulation. (`TI-DS` §9.4.1, §9.1.7.)
  Status: **partially implemented** — topologies name their sensitive nets;
  the router assigns them the deepest lanes and the geometric check enforces
  >= 8 mm clearance from inductor bodies. Component proximity to the IC and
  full keepout routing remain **pending**.
- **3.4 Open-core inductors need a flux keepout** over feedback, IC ground
  path, and output-capacitor wiring; prefer shielded inductors. (`TI-DS`
  §9.4.1.) Status: **pending** (evidence fact: inductor core type).
- **3.5 Thermal copper for power tabs.** A TO-263 tab wants its dissipation
  pour: ~2.5 in² of 1 oz copper single-sided (or 3 in² + 16 in² double-sided)
  per `TI-DS` thermal notes. Status: **partially implemented** — a GND F.Cu
  pour surrounds the tab (`thermal_pour_references`); the pour AREA is not
  yet checked against the datasheet figure.
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
- **4.3 Multi-side packages (QFN and friends) fan out per side.** South pins
  spread through nested elbows onto a wider via grid (outermost pin jogs
  shallowest); north pins rise into a mirrored top routing channel; east and
  west pins escape outward into per-pad drop columns; nets spanning both
  channels join through a row-level pad column. Vias never sit closer to a
  neighbouring drop than the clearance rule allows. (`SESSION` — MPU-6050
  slice, five live-DRC iterations.) Status: **implemented**
  (`_side_escapes`/`_route_channel` in `kicad/board.py`).

## 5. Mechanical

- **5.1 Mounting holes at board corners** for enclosure or standoff mounting.
  (`SESSION` — user reference photos; ubiquitous on real modules.) Status:
  **implemented** — four official `MountingHole_3.2mm_M3` footprints at the
  corners of both layouts, embedded with a `board_only` attr so schematic
  parity ignores them; the parts row and board bands reserve hole clearance.
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

## 7. Electrical composition rules

- **7.1 Series LED strings chain anode-to-cathode from supply to ground.**
  A reversed LED blocks the whole string while ERC, DRC, and parity all pass;
  only the pin-level netlist reveals it. (`SESSION` — LED text-matrix slice;
  symbol rotation determines which pin faces the supply.) Status:
  **implemented** (`series_led_polarity` check in `design_checks.py`, keyed on
  the topology's declared strings).
- **7.2 Every schematic net carries an explicit label.** `kicad-cli` (10.0.3)
  silently drops UNLABELLED nets from both ERC connectivity and the exported
  netlist — wires between rotated symbol pins reported "dangling" and their
  nets vanished until a label was attached. Named nets also make board review
  plots readable. (`SESSION` — discovered by probe bisection on the LED
  text-matrix schematic.) Status: **implemented** in both generators (all
  divider/buck nets were already labelled; LED-art series nets are labelled
  `S<string>_<link>`).

## 8. Silkscreen and assembly marks

Source `KICAD-LIB`: the official KiCad footprint library installed at
`C:\Program Files\KiCad\10.0\share\kicad\footprints` — the reference
implementation of polarity silkscreen (KiCad Library Conventions, klc
rules F4/F5: polarized parts must show polarity; pin 1 must be identifiable).

- **8.1 Polarized two-terminal parts mark polarity on silkscreen.** Diodes
  and LEDs get a CATHODE BAR (a silk line beside the cathode terminal —
  `KICAD-LIB` `LED_0603_1608Metric` closes its silk outline with a bar at the
  cathode pad); polarized capacitors get a "+" cross beside the positive pad
  (`KICAD-LIB` `CP_Elec_8x10` draws a 1 mm cross plus a chamfered body
  corner). Status: **implemented** — `FootprintSpec.silk_marks` renders the
  bar/cross into both the board file and the review plot.
- **8.2 Off-board power connectors are labelled "+" and "-" on silkscreen**
  so the user knows the wiring polarity without the schematic. (`SESSION` —
  user request on the LED matrix; `REF-BC2596` labels its corner pads.)
  PCBSmith topologies always put the positive rail on connector pin 1.
  Status: **implemented** (pin-header spec carries the marks; text
  counter-rotates so it stays upright on rotated connectors).
- **8.3 Power connectors sit edge-parallel: pins stack along the board
  edge.** (`SESSION` — user's hand edit of the LED matrix moved P1 to
  vertical on the left edge, `(at 22 40 -90)`.) Status: **implemented** in
  the art-grid layout (rotation 270, "+" pin up); the row-channel layout
  still places headers edge-perpendicular pending escape routing.
- **8.4 Pin-numbering conventions (deviation, documented hazard).** Official
  KiCad libraries put the diode/LED CATHODE on pad 1 (the bar marks it) and
  the polarized-capacitor POSITIVE on pad 1. **PCBSmith's generated
  symbol/footprint pairs currently deviate: LED/diode pad 1 = anode, CP
  pad 1 = negative.** The pairs are internally consistent and the silk marks
  are placed by electrical truth, so fabrication is correct — but swapping a
  PCBSmith footprint for the same-named KiCad library footprint would flip
  polarity. This is also why `lib_footprint_mismatch` stays suppressed in
  generated projects. Status: deviation **documented**; queued fix is to
  adopt the KiCad conventions or import official `.kicad_mod` geometry
  outright (which would bring the real silk art with it).
