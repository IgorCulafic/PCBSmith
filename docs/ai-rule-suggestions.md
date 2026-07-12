# AI Rule-Change Suggestion Log

Governance: `docs/pcb-design-rules.md` is the authoritative rulebook. Once
rule confinement is enabled, AI reviewers and revision loops must NOT edit
the rulebook or the check implementations directly. Instead, a proposed rule
change, new rule, or relaxation is appended here as a dated entry; a human
reviews and either promotes it into the rulebook (with a machine check) or
rejects it with a note. Until then, entries below also serve as a changelog
of AI-originated rules that were applied directly with user permission.

Entry format:

```
## YYYY-MM-DD <short title>
- status: proposed | promoted | rejected
- proposed_by: <model / check / session>
- rule: <existing rule id, or "new">
- suggestion: <what should change and the exact proposed wording>
- evidence: <the design/revision and observation that motivated it>
- decision_note: <filled by the human>
```

---

## 2026-07-05 QFN fanout rules (MPU-6050 slice)
- status: promoted (user-requested topology)
- proposed_by: claude-fable-5, MPU-6050 slice live-DRC iteration
- rule: new 4.3
- suggestion: route multi-side packages with per-side fanout (nested-elbow
  south spread, mirrored top channel for north pins, lateral escapes east
  and west, row-pad cross-channel joins); clamp fanout track width to the
  pad's short dimension so power nets never bridge fine-pitch pins.
- evidence: five DRC iterations on outputs/mpu6050-r001 — 0.8 mm power
  stubs shorting 0.5 mm pitch pins, 45-degree diagonals clipping neighbour
  pads, joins slicing through stacked connector pads, and a dangling via on
  a single-pad bottom lane; each failure is now a structural rule.
- decision_note: r001 passes DRC+parity clean; the idle-I2C-bus op check
  measures SDA/SCL at 3.2999 V and 66 nA static draw.

## 2026-07-05 Official KiCad footprints imported; overnight batch
- status: promoted (user-directed: "do all 6 tonight")
- proposed_by: claude-fable-5 overnight backend session
- rule: 8.4 resolution + 3.2/3.5/5.1/1.1 statuses
- suggestion: replace hand-drawn footprint geometry with the official KiCad
  `.kicad_mod` files (vendored under ai_assets/kicad_footprints), embedded
  verbatim into boards with injected nets/position/parity clauses; flip our
  polarized symbols to the KiCad pin convention (diode/LED pin1=cathode,
  CP pin1=positive); pour a B.Cu ground plane and a TO-263 thermal zone on
  the buck; add corner mounting holes (board_only); validate the buck
  regulator against the extracted datasheet facts.
- evidence: live DRC caught that pad angles in board files are TOTAL angles
  (rotated TO-263 shorted every pin until the embed added the footprint
  rotation to each pad); r010/r011 buck, r005 LED art, and r003 divider all
  pass DRC+parity with real silk, courtyards, 3D models, pours, and holes.
- decision_note: lib_footprint_mismatch stays suppressed because PCBSmith
  decorates footprints (+/- marks, parity fields); geometry itself is now
  the library's.

## 2026-07-02 Polarity silkscreen, +/- connector labels, edge-parallel connectors
- status: promoted (user-requested)
- proposed_by: user review of outputs/led-art-igorc-r002 (hand edit rotated P1
  vertical at the left edge and asked for +/- marks and standard polarity
  silkscreen)
- rule: new 8.1-8.4
- suggestion: polarized parts mark polarity on silk with the standard glyphs
  (cathode bar for diodes/LEDs, "+" cross for polarized caps, per the official
  KiCad footprint library); power connectors get "+"/"-" text; connectors sit
  edge-parallel (pins stacked along the edge).
- evidence: KiCad's LED_0603_1608Metric closes its silk outline with a bar at
  the cathode pad; CP_Elec_8x10 draws a 1 mm "+" cross and chamfered corner;
  the user's hand edit placed P1 at (at 22 40 -90). Reading the library also
  exposed that our pad-numbering deviates from the KiCad convention
  (diode pad1=cathode, CP pad1=positive) — documented as rule 8.4 hazard with
  a queued alignment fix.
- decision_note: implemented via FootprintSpec.silk_marks + right-angle
  rotation support (rotate_offset), verified by DRC parity on r003.

## 2026-07-02 Series LED polarity check and mandatory net labels
- status: promoted (applied directly with user permission)
- proposed_by: claude-fable-5, LED text-matrix slice (outputs/led-art-igorc-r001
  failure diagnosis)
- rule: new 7.1 and 7.2
- suggestion: (7.1) series LED strings must chain anode-to-cathode from supply
  to ground, enforced by a netlist-level check keyed on the topology's string
  declarations; (7.2) every schematic net gets an explicit label because
  kicad-cli 10.0.3 silently drops unlabelled nets from ERC connectivity and
  netlist export.
- evidence: r001 failed ERC with 52 "dangling" wires that were geometrically
  exact; probe bisection (wire variants, grounded sweeps, transplant into the
  known-good buck schematic) isolated the missing-label cause — adding a label
  made the identical wire netlist correctly. Rotation probing also showed
  rotation 90 puts the LED anode at the bottom (reversed); rotation 270 fixed
  it and the 7.1 check guards it.
- decision_note: r002 passed end-to-end; the toolchain quirk is recorded as a
  generation rule so future topologies never hit it.

## 2026-07-02 Trailing connectors close the row at the right edge
- status: promoted (applied directly with user permission, commit `05f55a4`)
- proposed_by: claude-fable-5 visual review of outputs/lm2596-buck-r004
- rule: 1.1
- suggestion: Multi-connector boards place the first connector at the left
  edge and all further connectors at the right edge so power enters one side
  and exits the other.
- evidence: r004 placed P2 adjacent to P1, forcing VOUT to traverse the full
  board and return.
- decision_note: user-approved direct edit; promoted into rule 1.1 and the
  placer.

## 2026-07-02 Sensitive nets take the deepest lanes; rule 3.3 measures clearance
- status: promoted (applied directly with user permission)
- proposed_by: revision loop — outputs/lm2596-buck-r006 revision-plan (patch,
  rule 3.3) originating from the rule-3.3 geometric check
- rule: 3.3
- suggestion: Route sensitive (high-impedance) nets on the deepest channel
  lanes, and evaluate rule 3.3 as a 2-D clearance measurement (>= 8 mm from
  the inductor body) instead of a binary x-overlap test.
- evidence: r006's FB lane sat on the shallowest lane, 3.1 mm from the L1
  body; deepest-lane assignment yields 11+ mm and resolves the finding
  (r007 revision-plan: clean).
- decision_note: first patch plan executed end-to-end by the revision loop.

## 2026-07-02 Power nets weight the placement ordering cost
- status: promoted (applied directly with user permission, commit `05f55a4`)
- proposed_by: claude-fable-5 visual review of outputs/lm2596-buck-r004
- rule: 3.1 / 3.2
- suggestion: Weight power-net span 3x in the row-ordering cost so the
  switching path places contiguously (1-D loop minimisation).
- evidence: r004 interleaved CIN/COUT far from U1/D1/L1, producing a long
  switching loop despite a DRC pass.
- decision_note: user-approved direct edit; promoted with the
  switching-cluster geometric check as the enforcement ratchet.

## Human board edit (2026-07-06, `outputs\lm2596-buck-r010`)

Source: `pcbsmith board-diff` (plan 4.2). The user moved parts by
hand; each delta below is a candidate placement rule. Review and
promote or discard.

- D1: moved (62.03, 30) -> (62.5, 23.5) [d=(+0.47, -6.50)mm]

Analysis (AI): D1 is the buck's catch diode; the generated row placed it
at the row centerline (y 10). The edit lifts it 6.5 mm toward the top
edge at the same x. If the intent was tightening the SW/GND loop or
clearing the lane channel, the candidate rule is 2-D placement for
switching-cluster parts (extend rule 3.1 beyond row adjacency). Needs
the user's confirmation of intent before promotion.

## 2026-07-07: FLBACK-001 Rev B reference comparison (plan 4.3)

Source: `pcbsmith ingest-reference` on the NWES FLBACK-001 pack
(ai_assets/references/flback-001), same UCC28881 architecture as our
flyback-r001. Full analysis in
docs/reference-comparisons/flback-001-vs-flyback-r001.md. Rule
candidates for review:

- **Clamp-part ratings are calculated, not assumed.** The reference
  uses a 2 W axial clamp resistor and a 250 V clamp cap; the calculator
  now emits `clamp_dissipation_w` and warns past 0.4 W. Candidate rule:
  composition must derive the clamp R power class and the clamp C
  voltage class from the design point (partially implemented -
  calculator warning only).
- **Mains designs need a complete EMI/safety front end.** Fusible
  resistor + MOV alone is not the professional baseline: X2 cap across
  the line, line-to-earth Y-caps, an earth connection, and (optionally)
  a GDT position. Candidate: extend rule 7.5 required-support for the
  offline-converter topology class.
- **Prefer integrated packages when they exist.** Four DO-41 diodes vs
  one MiniDIP bridge cost ~16x24 mm and caused the courtyard crisis.
  Candidate: component selection should surface integrated equivalents
  (bridge, dual diodes) when the BOM has 2+ identical discretes in a
  rectifier role.
- **Every power design carries test points** (reference: rectified bus
  + secondary ground). Candidate placement rule.
- **DNP is a BOM state, not an absence** (reference keeps
  frequency-compensation options on the board as DNP). Implemented:
  value "DNP" now annotates the grouped BOM; composition support
  pending.

## 2026-07-11 Bus routing, placement compatibility, dual-side assembly (research wave)
- status: proposed
- proposed_by: claude-fable-5, deep-research harness + user directive (bus-routing example image)
- rule: new 11.6-11.8, new section 12, amendment to 4.x
- suggestion:
  - **11.6 Bus routing**: nets declared as a BUS GROUP (e.g. SEG1-16,
    address/data lines, I2C pairs) route as a bundle: one leader path,
    followers offset at constant pitch with matched bends; pigtails
    only at the pad ends. Check: >= X% of each member's length runs
    within one pitch of a neighbouring member; bends occur at shared
    stations. Rationale: craft/area (research digest section 2) - NOT
    signal integrity at our speeds.
  - **11.7 Corner physics honesty**: rule 11 keeps H/V/45 as CRAFT;
    the rulebook must not claim electrical harm from 90-degree corners
    below multi-Gbps (Bogatin ~2 fF/mil; Johnson 0.3% reflection at
    100 ps edges). High-voltage sections keep sharp-corner avoidance
    (field concentration) - already implicit in section 10.
  - **11.8 Crosstalk spacing classes**: foreign-net-to-bundle spacing
    >= 3x width (3W) as the default class; clock/periodic nets get a
    wider class (50 mil per TI SPRAAR7). Intra-bundle pitch may be
    manufacturing-minimum for same-bus members.
  - **12.x Placement compatibility engine**: component cards gain
    optional declarations the placer/checks enforce: heat-source
    keepout (SHT3x-class sensors: distance from LDO/module, thin-trace
    entry, slot/moat candidate), antenna keepout (ESP32: antenna zone
    over board edge, >= 15 mm clearance, no copper under), decoupling
    proximity (cap within N mm of its pin, own connection), crystal
    keepout (foreign traces out of oscillator zone), hot-loop area
    metric for switching topologies.
  - **4.x Dual-side placement as strategy**: FLIPPED_REFS is gated by
    a mass-per-wetted-perimeter table (SAC305 ~0.0269 g/mm with 20%
    margin; chip passives/SOT/TSSOP/QFN safe, heavy parts excluded)
    instead of ad-hoc judgment.
- evidence: thermometer stem congestion (7 failed route attempts from
  independent per-net A*); user-supplied bus-routing example image;
  research digest docs/reference/routing-placement-research-2026-07.md
  (sources: TI SPRAAR7, Espressif HW design guidelines, Sensirion SHT3x
  design-in, ADI AN-139, ST AN2867, SMTA dual-side reflow, Bogatin,
  Johnson). Antenna finding applies to the CURRENT thermometer r001
  draft: U1's antenna points into the bulb over copper.
- decision_note:


## 2026-07-12 Consolidated book-rule candidates (phase 0 complete)
- status: proposed
- proposed_by: claude-fable-5 + opus consolidation agent, nine-source book KB
- rule: candidates spanning 11.6-11.8, 12.x, 4.x, and phase-1 audit fixes
- suggestion: docs/reference/books/CONSOLIDATED.md is the canonical
  candidate list - ~48 consolidated rules organized by plan phase, each
  with every supporting source, verification status, thresholds
  EVALUATED for our board class, and machine form; the final section
  lists the 12 highest-value promotion-ready entries. Headline
  decision: three crosstalk spacing classes (same-bus at mfg minimum /
  foreign 3W craft floor - explicitly NOT a coupling guarantee on our
  1.6 mm 2-layer stack / sensitive victims 5.7h = 9.1 mm with pour, or
  opposite-layer/guard without).
- evidence: 72-rule spot-verification campaign (5 corrections, 1 false
  mismatch overturned by dimensional analysis, 2 honest ambiguities);
  six-item contradiction docket resolved explicitly in the file.
- decision_note:
