# Routing & placement craft — research digest (2026-07-11)

> **Pinned-source correction (2026-07-12):** use this digest for discovery,
> not final thresholds. The later source audit found that Espressif's 15 mm
> value is housing/object clearance, not blanket PCB copper keepout; module
> edge/overhang/cutout geometry comes from the pinned module guide/drawing.
> The SHT3x numeric humidity-error claim is still unpinned. See
> `books/SECOND-WAVE-2026-07.md` for current confidence and applicability.
Provenance: deep-research harness over ~15 technical sources (5 search
angles, 29 extraction agents, 114 claims). The adversarial verification
phase was cut short by session rate limits, so each claim below was
instead checked against model knowledge of the primary literature and
labeled: **[HIGH]** = matches the primary source and standard practice,
**[MED]** = plausible, source known, exact number should be confirmed
against the cited document before hard-coding, **[LOW]** = single
source / contested.

Key sources: Bogatin (Signal Integrity Journal, EDN rule-of-thumb #24),
Howard Johnson (sigcon.com "Who's Afraid of the Big Bad Bend"), TI
SPRAAR7 (high-speed interface layout guidelines), Espressif ESP32
Hardware Design Guidelines, Sensirion SHT3x Design-In Guide, ST AN2867
(oscillator design), ADI/LTC AN-139 (hot loops), NXP/Freescale AN2536,
ADI MT-101 (decoupling), SMTA/Zarrow double-sided reflow literature,
Croes et al. IRPS 2013 (electromigration at corners).

## 1. Corner angles — the verdict

The user's supplied source (bestpcbs.com) repeats the folk claim that
90-degree corners are an electrical hazard. The primary literature
CONTRADICTS the electrical framing at our speeds:

- **[HIGH]** A 90-degree bend is electrically a tiny lumped excess
  capacitance — Bogatin's number: ~2 fF per mil of trace width (his TDR
  measurement: 96 fF measured vs 120 fF estimated on a 60-mil trace);
  Johnson's worked example: 0.012 pF for an 8-mil 50-ohm microstrip,
  reflecting 0.3% of a 100 ps edge. Corners are electrically negligible
  below multi-Gbps signaling; they start to matter around 10 Gbps
  serial links or when trace width (mils) > 5x rise time (ps).
- **[HIGH]** The acid-trap argument for avoiding 90-degree inside
  corners is a 1980s etch-chemistry problem that modern fabs have
  eliminated; electromigration at right angles measures no worse than
  at 45 degrees (IRPS 2013).
- **[HIGH]** The one legitimate electrical objection is HIGH-VOLTAGE
  design: field concentration at sharp corners degrades
  creepage/breakdown margin (relevant to our flyback primary, not to
  3.3V logic).
- **CONCLUSION for PCBSmith**: 45-degree discipline (rule 11) is
  justified as CRAFT — professional appearance, shorter paths, uniform
  bundles — not as signal integrity. Keep rule 11's H/V/45 emission;
  do NOT invent electrical justifications for it. TI's actual
  high-speed corner rule is geometric and encodable: interior angle
  >= 135 degrees, segment >= 1.5x width around a bend, >= 5x width
  between bends **[MED — SPRAAR7]**.

## 2. Bus routing and crosstalk spacing

- **[HIGH]** Professional bus routing = related nets in a shared
  corridor at constant pitch with matched bends. It is a layout
  discipline (readability, area, systematic escape), and the crosstalk
  rules bound how TIGHT the bundle may pack:
- **[MED]** Single-ended crosstalk spacing: the common "3W" rule
  (center-to-center >= 3x width) for <= ~10% coupling; NXP AN2536
  specifies 4W center-to-center plus edge spacing >= 3x dielectric
  height; TI SPRAAR7: 5W pair-to-pair for diff pairs, 30 mil keepout
  to other signals, 50 mil to clocks/periodic signals.
- Inside one bundle of same-bus signals (our SEG nets), mutual
  crosstalk is functionally harmless (same-cycle register outputs
  driving LEDs) — bundle pitch can be tight (manufacturing clearance),
  while the BUNDLE keeps 3W-class distance from foreign nets. This is
  the machine-encodable form.
- **[MED]** Serpentine/meander self-coupling: spacing between parallel
  sections of the same trace >= 3x dielectric height.
- **[HIGH]** Length matching at our speeds: only USB HS pairs would
  need intra-pair matching (~100 ps / 50 mil class); Full-Speed USB
  (12 Mbps, 4-20 ns edges) tolerates inches of mismatch — our boards
  need pair COHERENCE (route DP/DM together, same via count), not
  serpentine tuning.

## 3. Component placement compatibility

- Decoupling: **[HIGH]** smallest-value cap closest to the pin, wide
  short entry or via-in-pad-adjacent; on 2-layer boards (ours) distance
  DOES matter (no closely-spaced plane pair to flatten the loop
  inductance). Machine form: per-IC decoupling cap within N mm of its
  supply pin (N ~ 2-3 mm for 0402/0603 class), own via/trace, not
  daisy-chained. **[MED]** the Hubing plane-pair insensitivity result
  applies only to <10 mil plane pairs — irrelevant to 2-layer.
- Crystals: **[HIGH]** crystal adjacent to MCU, short symmetric load
  paths, keepout for foreign traces under/near the oscillator, local
  ground; **[MED]** quantified keepouts: >= 2 mm from clock traces
  (Espressif), one source claims 25.4 mm from unrelated components
  (that is a conservative EMC-lab rule, too strong to hard-code).
  (No discrete crystal on current boards — ESP32 module contains its
  own — but the rule belongs in the library for MCU topologies.)
- Switching regulators: **[HIGH]** the HOT LOOP (input cap + switches)
  is the dominant radiator; its enclosed area is a directly computable,
  minimizable metric; ceramic input cap closest to VIN; feedback nets
  routed away from the switch node/inductor; unbroken plane under the
  loop. Machine form: hot-loop area check for buck/flyback topologies +
  FB-to-SW clearance class.
- Temperature/humidity sensors (SHT3x): **[UNPINNED]** the digest reported
  `1 degree C ~= 5 %RH at 90 %RH` and recommended distance from heat sources,
  minimal copper/thin traces, and slot/moat isolation. Treat these as design
  hypotheses until the current Sensirion guide is pinned. A sensor card may
  declare heat isolation and low-copper entry now; numeric thresholds wait.
- Antennas: **[PINNED CORRECTION]** Espressif prefers the module antenna
  beyond the baseboard edge with feed near the edge, or a module-specific
  cutout on both sides and below. The 15 mm value is final housing/object
  clearance, not blanket PCB copper clearance. Thermometer r001 still points
  U1 into the interior over bulb copper and violates the placement intent.- **[LOW]** One source claims vendor app notes are usually poor layout
  guidance. Rejected as a blanket rule — but it supports the project's
  law: never encode a rule without its WHY and applicability range.

## 4. Double-sided SMD assembly

- **[HIGH]** Passives and small parts on the secondary side are normal
  practice (our flyback r003 already does it). The physics for what
  survives hanging upside-down through second reflow: surface tension
  x wetted PERIMETER (not area). Classic Zarrow tin-lead rule: 30 g
  per square inch of pad area; SAC305 measured: ~0.0269 g per mm of
  wetted perimeter (use with a 20% engineering margin). Chip passives,
  SOT, SOIC, TSSOP, QFN, small DFN: all safe. Heavy parts
  (transformers, big connectors, electrolytics) stay on the last-
  soldered side or get hand/selective soldering.
- **[MED]** Espressif recommends NO components on the bottom of ESP32
  boards (their reference designs) — a conservative vendor preference,
  not a physical constraint; our USB-C + module on the back is
  legitimate but worth a documented deviation note.
- Machine form: a per-footprint mass/perimeter table gate for
  FLIPPED_REFS (blocker only for parts beyond the SAC305 ratio), plus
  the existing courtyard/DRC machinery which is already side-aware.

## 5. What the user's supplied source gets right/wrong

bestpcbs.com (the supplied link): right that 45-degree routing is
standard practice and looks/manufactures well; wrong (or at least
outdated) wherever it implies 90-degree corners are an electrical or
acid-trap hazard on modern low-speed boards. Trust its craft
prescription, not its physics.

## 6. Books worth obtaining (canonical, repeatedly cited)

1. Eric Bogatin — *Signal and Power Integrity — Simplified* (3rd ed.):
   THE first book; corners, crosstalk, decoupling, planes, with
   rules-of-thumb quantified.
2. Howard Johnson & Martin Graham — *High-Speed Digital Design: A
   Handbook of Black Magic*: edge-rate-driven layout physics;
   crosstalk, terminations, vias, corners.
3. Henry W. Ott — *Electromagnetic Compatibility Engineering*: the EMC
   bible; grounding, partitioning, cable/connector strategy.
4. Mark I. Montrose — *EMC and the Printed Circuit Board* and *Printed
   Circuit Board Design Techniques for EMC Compliance*: board-level EMC
   rules in checkable form.
5. Tim Williams — *The Circuit Designer's Companion*: practical
   analog/power/grounding craft at exactly our board class.
6. Clyde F. Coombs — *Printed Circuits Handbook*: fabrication/assembly
   ground truth (etching, reflow, double-sided processes).
7. (Free) IPC-2221B (generic design), IPC-7351 (land patterns),
   IPC-A-610 (assembly acceptability) — the standards our checks
   already lean on; worth having the real texts.
