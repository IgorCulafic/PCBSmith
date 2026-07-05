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
