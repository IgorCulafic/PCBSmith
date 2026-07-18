# Johnson & Graham — High-Speed Digital Design (1993): distilled rules

Provenance:
- Book: Howard Johnson & Martin Graham, *High-Speed Digital Design: A
  Handbook of Black Magic*, Prentice Hall PTR, 1993 (1st ed.).
- Text cache: `.book-cache/johnson-hsdd/` (p0001–p0446), sha256
  `16d619e96d8c22f860e95c191e2553972e94b49abedadd1a010832472a481c50`
  (from `.book-cache/manifest.json`).
- **Cache is OCR** (RapidOCR over a scanned book), `ocr: true` in the
  manifest. Text prose is reliable; NUMBERS and EQUATIONS are the weak
  point — digit swaps (0/O, 1/l), lost decimals, and garbled formula
  symbols are common. Every numeric threshold below is sanity-checked
  against surrounding prose and physics; ones that could not be pinned
  are tagged **OCR-uncertain**.
- Extracted/distilled: 2026-07-12. Locators are "PDF p.N" into the
  cache; the book's printed page = PDF page − 9 (verified: printed
  p.2 = PDF p0011; printed section numbers quoted where visible).
- Board-class filter applied throughout: 2-layer 1.6 mm FR-4,
  3.3 V/5 V logic, edges ≥ 3 ns, clocks ≤ 50 MHz, I2C/SPI/USB-FS.

Chapter map (read deep / skimmed / skipped):
- READ: Ch 1 Fundamentals §1.1–1.3 (knee freq, propagation delay,
  lumped-vs-distributed; PDF p10–17); Ch 4 Transmission Lines §4.1
  (point-to-point shortcomings, ringing, EMI, crosstalk; PDF p142–148)
  and §4.4 (unterminated-line step response; PDF p176–177); Ch 5
  Ground Planes and Layer Stacking §5.2–5.8 in full (crosstalk numbers,
  slots, cross-hatch/grid, fingers, guard traces, near/far-end,
  stacking; PDF p198–223); Ch 7 Vias §7.3–7.4 (bypass effective radius,
  return-current jump; PDF p266–268); Ch 8 Power §8.4 (bypass cap
  selection, Table 8.1; PDF p289–293); Ch 9 Connectors §9.1–9.2, 9.5–9.7
  (crosstalk grounds rule, EMI loops, ground continuity; PDF p301–322).
- SKIMMED: Ch 2 (logic-family input/power table 2.1, PDF p53) for
  family edge/knee context; Ch 6 Terminations §6.1 (PDF p232–233) for
  the split-terminator drive-current facts.
- SKIPPED (out of class or measurement-lab material): Ch 3 Measurement
  Techniques, Ch 6.2–6.6 termination detail, Ch 10 Ribbon Cables,
  Ch 11 Clock Distribution (multi-drop/backplane clocking), Ch 12 Clock
  Oscillators, Appendices A–C (checklist/rise-time math/MathCad).

Foundation fact used throughout — the **knee frequency**, the book's
single screening tool: **Fknee = 0.5 / Tr** (Eq. 1.1, PDF p11, §1.1),
Tr = 10–90 % rise time. "Most energy in digital pulses concentrates
below the knee frequency" (PDF p14). Everything above Fknee "hardly
affects digital performance." Applicability of every rule below is
judged against Fknee, i.e. against the EDGE rate, never the clock.

---

## 0. Applicability screen for our class (Johnson's own formulas, arithmetic shown)

Inputs: Tr = 3 ns (slowest allowed edge); FR-4 delay D from Table 1.1
(PDF p15): outer/microstrip trace ≈ 140–180 ps/in (use 170), inner
180 ps/in. Dielectric height on 2-layer h ≈ 1.6 mm = 63 mil.

1. **Spectral reach.** Fknee = 0.5 / 3 ns = **167 MHz**. USB-FS (12 Mb/s,
   ~3–4 ns edges) lands at ~125–167 MHz. So the "high-speed" band that
   matters for us tops out near 167 MHz — LIVE up to there, nothing
   above.
2. **Termination / distributed behaviour — DORMANT on hand-sized boards.**
   Rising-edge length l = Tr/D = 3000 ps / 170 = **17.6 in ≈ 447 mm**
   (Eq. 1.3). Conservative lumped cutoff l/6 = **2.9 in ≈ 75 mm**
   (§1.3): any trace shorter than ~75 mm is purely lumped. Practical
   "reflections separate from the edge" boundary (round-trip delay
   2·Tp > Tr) → length > Tr/(2D) = **8.8 in ≈ 224 mm**. Johnson's own
   worked example (74HCT640 bus, 10 in, 1.6 ns one-way): "no terminators
   are required" (PDF p59). Conclusion: at 3 ns edges NO net on a
   sub-150 mm board needs termination. Ringing/reflection concerns are
   dormant; series damping stays craft-level, not mandatory.
3. **Bypass cooperation radius — LIVE but generous.** Effective radius
   l/12 = 17.6/12 = **1.5 in ≈ 37 mm**; caps within l/6 ≈ 75 mm diameter
   act as one lumped network (§7.3, PDF p266). On a small board every
   decap cooperates — but still mount each close to its IC (loop area).
4. **Crosstalk — THE live risk for our class.** Crosstalk ≤ 1/(1+(D/H)²)
   (Eq. 5.2). With a back-side ground pour at h = 1.6 mm, to hold
   crosstalk under 3 % you need (D/H)² > 32 → D > 5.7·h = **9.1 mm**
   centre-to-centre. On a 1.6 mm-thick 2-layer board you cannot get the
   plane close, so parallel runs couple strongly unless widely spaced —
   and with NO plane (both layers signal) inductive coupling is worse
   still. This is the dominant live concern (buses, ribbon-like runs).
5. **Return-path integrity — LIVE.** ns edges → return current takes the
   least-INDUCTANCE path directly under the trace (§5.1). Slots, connector
   pin-field cutouts, and via layer-jumps all divert it → LIVE.
6. **Via parasitics themselves — DORMANT.** A through-via is ~1 nH /
   ~0.3–0.5 pF; at 167 MHz its reactance is ~1 Ω, negligible against our
   trace impedances. Only the RETURN-current jump at a via matters (§7.4).

Net: for a 3 ns / ≤50 MHz / hand-sized 2-layer board the book collapses
to **crosstalk, return-path continuity, bypass loop area, and
connector/cable EMI**. Transmission-line termination and via parasitics
are dormant.

---

## 1. The knee-frequency screen (Ch 1 §1.1–1.3)

### HSDD-K1 — Knee frequency defines the design band
- THRESHOLD: Fknee = 0.5/Tr. A circuit with flat response to Fknee passes
  the edge undistorted; behaviour above Fknee "hardly affects" it.
- WHY: a random digital pulse train rolls off −20 dB/dec to Fknee, then
  much faster; at Fknee the amplitude is 6.8 dB below the straight slope.
- WHERE: PDF p11–14 §1.1, Eq. 1.1, Fig. 1.1.
- MACHINE FORM: calculator `knee_freq(tr_ns)=0.5/tr_ns` (GHz); the master
  screen every other high-speed check is gated on. Coexists with the
  existing Ott `bw=1/(π·tr)` knob — see cross-book note CB1.
- APPLICABILITY: all digital nets; it is a guidepost, not Fourier-exact.

### HSDD-K2 — Lumped vs distributed = length vs edge length / 6
- THRESHOLD: rising-edge length l = Tr/D (Eq. 1.3). A trace/bus is
  **lumped** (no transmission-line behaviour) if shorter than l/6;
  longer than that it is distributed and "always rings if unterminated."
- WHY: only structures small relative to the edge's physical length
  react with a uniform potential.
- WHERE: PDF p16–17 §1.3, Eqs. 1.3–1.4; "distributed circuits always
  ring if unterminated" PDF p146 §4.1.
- MACHINE FORM: check `trace_len_mm > (tr_ns·v_mm_per_ns)/6` → tag net
  `distributed` (candidate for termination); else `lumped`. FR-4 outer
  v ≈ 150 mm/ns → threshold ≈ 25·tr_ns mm (≈75 mm at 3 ns).
- APPLICABILITY: PCB traces, point-to-point, buses. Note the practical
  termination-NEED boundary is looser (~2× this, round-trip>Tr); the
  l/6 line is the conservative purely-lumped cutoff.

---

## 2. Point-to-point wiring, ringing, and EMI first principles (Ch 4 §4.1)

### HSDD-T1 — Ringing is a Q phenomenon; damp with rise time or R
- THRESHOLD: an RLC formed by driver Rs, wiring L, load C rings with
  Q = (1/Rs)·√(L/C) (Eq. 3.12/5.7). Q>1 rings; **worst-case ring is
  halved when Tr = ½ the ringing period** (Fring = 1/(2π√(LC))). Edges
  much shorter than ½ period excite full ringing.
- WHY: a fast edge carries energy above Fring to excite the resonance;
  a slow edge does not.
- WHERE: PDF p142–143 §4.1.1, Eqs. 4.5–4.7; PDF p146.
- MACHINE FORM: calculator `ring_Q(Rs,L,C)` and `f_ring(L,C)`; finding
  when Q>1 AND Fknee>Fring on a lumped net; suggested fix = source
  series R (raise Rs), NOT wider trace.
- APPLICABILITY: lumped nets with low-Rs drivers into heavy C; at 3 ns
  edges mostly minor, worst on SPI clock / USB.

### HSDD-T2 — EMI is proportional to loop area (height above return)
- THRESHOLD: radiated field ∝ total signal-current loop area. A trace
  0.005 in above a plane has ~1/40 the loop area of 0.2 in open wiring
  → **~32 dB less radiation per wire** for the same edge.
- WHY: outgoing and return currents cancel when their loop is small;
  loop area is the antenna.
- WHERE: PDF p144 §4.1.2, Fig. 4.2. (32 dB figure OCR-checked against
  the 40× area ratio: 20·log10(40) = 32 dB ✓.)
- MACHINE FORM: scoring — enclosed loop area (signal path vs actual
  return path) per critical net; "press traces close to the return
  copper" as a routing objective. Ties to Ott OTT-L1.
- APPLICABILITY: every net; the lever is proximity of signal to return.

### HSDD-T3 — Bundled/gathered parallel wiring is the crosstalk worst case
- THRESHOLD: worked example — 4 in of parallel wire 0.1 in apart at
  0.2 in height gave ~12 % crosstalk PER wire; 10 bundled wires → ~50 %.
- WHY: mutual inductance between tightly bundled loops approaches the
  self-inductance; contributions add linearly.
- WHERE: PDF p145–146 §4.1.3, Eqs. 4.8–4.10. (Absolute mV OCR-uncertain;
  the ratios and mechanism are sound.)
- MACHINE FORM: router/placement rule — never bundle a bus tightly away
  from its return; spread parallel bus members and keep each near
  ground copper. Reinforces HSDD-X1.
- APPLICABILITY: parallel buses/ribbon-like runs — LIVE for us.

---

## 3. Ground structures for boards WITHOUT solid planes (Ch 5) — our core chapter

### HSDD-G1 — Return current density falls as 1/(1+(D/H)²)
- THRESHOLD: under a microstrip at height H, return current density at
  lateral distance D ∝ 1/(1+(D/H)²) (Eq. 5.1) — falls with the SQUARE of
  distance. This same law governs crosstalk (Eq. 5.2) and bypass reach.
- WHY: the distribution minimises total loop inductance and stored field
  energy.
- WHERE: PDF p198 §5.2, Fig. 5.3, Eq. 5.1.
- MACHINE FORM: shared kernel `coupling_ratio(D,H)=1/(1+(D/H)²)` feeding
  both the crosstalk check (HSDD-X1) and the "keep return copper under
  the trace" corridor check.
- APPLICABILITY: any trace over a return plane/pour; H = dielectric
  thickness (2-layer: ~1.6 mm).

### HSDD-G2 — Two-layer ground topology hierarchy (grid > fingers)
- THRESHOLD: for a 2-layer board Johnson ranks the options: **solid
  plane ≫ power-and-ground grid (cross-hatch) > ground fingers ≫ none.**
  "If you must use a two layer board, this [power-and-ground grid] is a
  good way to do it" (PDF p205). Grid = ground horizontal on back, power
  vertical on top, bypass caps at intersections; signals may share those
  layers in the open channels. Explicitly "appropriate for small
  low-speed CMOS and ordinary TTL … provides inadequate grounding for
  high-speed logic" (PDF p204).
- WHY: a grid gives every trace a nearby return with far less mutual
  inductance than fingers (where return detours around the board edge);
  a plane is the limiting case.
- WHERE: PDF p204–208 §5.4–5.5.
- MACHINE FORM: composition/routing knob — default 2-layer ground
  strategy = gridded pour both layers stitched at crossings; flag
  "ground fingers"/edge-return topologies as a finding.
- APPLICABILITY: 2-layer boards. Our 3 ns / ≤50 MHz sits at the top of
  what a grid honestly covers — pair it with a solid back pour where the
  routing allows (standing advisory, matches Ott caution).

### HSDD-G3 — Cross-hatch/grid self-inductance ~ 5·Y·ln(X/W)
- THRESHOLD: a trace across a cross-hatched ground has L ≈ 5·Y·ln(X/W) nH
  (Eq. 5.11, X = hatch pitch, W = trace width, Y = length); mutual L to a
  neighbour between the same two hatch members is ~the same. Hatch pitch
  must be **much smaller than a rising-edge length** to behave as a plane.
- WHY: the hatch forces return current along grid members, raising both
  self- and mutual inductance vs a solid plane.
- WHERE: PDF p205–206 §5.4, Eqs. 5.11–5.12. **Constant "5" OCR-uncertain**
  (compare fingers Eq. 5.13 uses the same 5·Y·ln(X/W) form; treat as a
  first-order estimate, not a precision value).
- MACHINE FORM: calculator `hatch_trace_L(X,W,Y)`; a check that hatch
  pitch X < l/6 of the fastest edge before calling a grid a "return
  plane."
- APPLICABILITY: 2-layer gridded designs.

### HSDD-G4 — Slots in the return are forbidden (length, not width, hurts)
- THRESHOLD: a slot under a trace diverts return current around its
  ENDS, adding series L that depends on slot LENGTH (perpendicular
  diversion), not slot width — "any slot width, no matter how thin"
  behaves the same. Slots smaller than the trace width, or beside but
  not under the trace, have almost no effect.
- WHY: the diverted loop is large → high inductance, slowed edges, and
  strong mutual coupling to any second trace crossing the same slot.
- WHERE: PDF p201–204 §5.3, Eq. 5.3 (slot-inductance formula OCR-garbled;
  the length-not-width mechanism is stated plainly and repeatedly).
- MACHINE FORM: check — no routed net crosses a slot/gap in its return
  copper; generalises the existing hole-obstacle model to the return
  layer. Trace-crosses-slot = blocker. Same rule as Ott OTT-R1.
- APPLICABILITY: all boards with a pour/grid return.

### HSDD-G5 — Connector pin-field ground continuity (the slot most people miss)
- THRESHOLD: ground clear-out holes around connector pins must leave
  continuous ground copper BETWEEN all pins; over-large clear-outs merge
  into a slot exactly where all I/O return currents concentrate.
- WHY: it is HSDD-G4 in disguise at the one place returns pile up.
- WHERE: PDF p202 §5.3, Fig. 5.9; restated PDF p312 §9.5.
- MACHINE FORM: pour-web check between connector THT pins (ties to the
  existing hole-to-copper 0.25 mm constraint); flag merged annulars.
  Identical to Ott OTT-R4.
- APPLICABILITY: every connector over ground copper — LIVE (USB-C).

---

## 4. Crosstalk — magnitudes and remedies (Ch 5 §5.2–5.7)

### HSDD-X1 — Crosstalk ≤ 1/(1+(D/H)²); acceptable band 1–3 %
- THRESHOLD: crosstalk fraction ≤ 1/(1+(D/H)²) (Eq. 5.2). Worked case:
  D/H = 8 → 1.5 %. "For ordinary homogeneous digital systems, a crosstalk
  level of 1–3 % between adjacent wires is fine" — ASSUMING a solid
  ground plane so each wire only sees its nearest neighbour. On a
  hatch/fingers ground many pairs interact and you must SUM all
  contributions.
- WHY: mutual inductive (≥ capacitive) coupling drops with the square of
  the distance/height ratio.
- WHERE: PDF p209 §5.6, Eqs. 5.14–5.15; 1–3 % rule PDF p209.
- MACHINE FORM: check `crosstalk_est = 1/(1+(pitch/h)²)` per adjacent
  parallel pair; finding if > 3 % (homogeneous) or if summed neighbours
  > 3 % (no-plane). For our 1.6 mm h → need pitch ≥ ~9 mm for < 3 %.
- APPLICABILITY: LIVE and dominant for us. Note the mixed-family caveat:
  high-swing (TTL/5 V) next to low-swing (3.3 V/ECL) needs tighter limits.

### HSDD-X2 — Guard traces help only WITHOUT a solid plane
- THRESHOLD: a grounded trace between two microstrips halves their
  coupling; grounding it to the plane at frequent via intervals halves
  it again. BUT "a solid ground plane provides most of the benefit of
  grounded guard traces" — over a plane, "guard traces cause nothing but
  trouble." An OPEN/floating guard makes crosstalk worse. If two planes
  exist, ground the guard at the ENDS only, not the middle.
- WHY: on a plane the return is already directly under the trace; a guard
  adds little and forces spacing that itself lowered the coupling.
- WHERE: PDF p208–211 §5.6; "nothing but trouble" PDF p268 §7.4.
- MACHINE FORM: `guard` net role legal only on boards flagged
  no-solid-plane; must be grounded both ends (+ interval vias); reject a
  floating guard. On planed boards, prefer spacing (HSDD-X1) over guards.
- APPLICABILITY: 2-layer no-plane boards = the case guards are FOR.
  See cross-book CB3 (Montrose/Bogatin agree guards are a niche tool).

### HSDD-X3 — Forward vs reverse (near/far-end) crosstalk on long lines
- THRESHOLD: on distributed lines, reverse (near-end) coupling is a
  flat-topped pulse of duration 2·Tp whose HEIGHT is fixed once the line
  exceeds the saturation length; forward (far-end) coupling grows with
  coupled length. Over a solid plane, inductive and capacitive forward
  components nearly cancel (small negative FEXT); over a slotted/hatched
  ground the forward term is large and negative. "Forward crosstalk is
  never larger than the reverse."
- WHY: distributed mutual L/C act as a chain of small transformers with
  opposite-polarity forward/reverse blips.
- WHERE: PDF p211–214 §5.7, Figs. 5.15–5.18.
- MACHINE FORM: informational for our class — most nets are lumped
  (HSDD-K2), so use the lumped 1/(1+(D/H)²) estimate; the near/far split
  only fires on nets tagged `distributed`. Matches Bogatin R12–R14.
- APPLICABILITY: distributed lines only — largely DORMANT at 3 ns on
  hand-sized boards.

---

## 5. Bypass / power distribution (Ch 7 §7.3, Ch 8 §8.4)

### HSDD-P1 — SMT is the whole game; a bypass cap is L-ESR-C
- THRESHOLD: measured (Table 8.1): leaded "digital bypass" caps carry
  lead inductance 4–16 nH and ESR 0.1–1.1 Ω; an **SMT 1206 ≈ 1.1 nH,
  ESR ~0.1 Ω** — smaller packages (0805) less still. Below 1 MHz all look
  identical; ~10 MHz ESR shows; **above ~100 MHz only lead inductance
  matters.** Bonding a cap straight to power/ground copper beats a
  socketed/leaded part by ~8 dB above 10 MHz.
- WHY: series L-ESR-C; past self-resonance the mounting inductance sets
  the impedance regardless of capacitance value.
- WHERE: PDF p289–293 §8.4, Table 8.1, Fig. 8.14.
- MACHINE FORM: BOM/placement rule — decoupling caps ≤ 1206 (prefer
  0603/0805), short fat connections; calculator returns |Z|(f) from
  (C, ESR, L_mount). Consistent with Ott OTT-D1/D5.
- APPLICABILITY: all digital ICs; for our 3 ns edges (Fknee 167 MHz)
  mounting inductance dominates.

### HSDD-P2 — Bypass array effective radius = l/12
- THRESHOLD: caps within radius l/12 (diameter l/6) of a load act in
  concert as a lumped network; l = edge length. 1 ns edge → l ≈ 6 in →
  radius 0.5 in. **Halving the rise time makes a given bypass layout ~8×
  less effective** (cap count in the radius falls as Tr², via reactance
  rises as 1/Tr).
- WHY: only caps close enough to respond within the edge duration
  contribute; faster edges shrink the cooperating region and raise via Z.
- WHERE: PDF p266 §7.3.
- MACHINE FORM: placement check — decoupling for a fast IC within l/12
  (≈37 mm at our 3 ns) of its power pins; scale the budget by Tr² when
  edges tighten. On small boards this is easily met but still forces
  "cap near the pin."
- APPLICABILITY: all decoupling; generous at 3 ns, tight for future
  faster parts.

### HSDD-P3 — Via inductance degrades every bypass cap; fat, short, doubled
- THRESHOLD: the vias and traces between a bypass cap and the planes add
  the dominant inductance; "these traces should always be extra fat,"
  mount caps on the side nearest the planes, and an ARRAY beats a single
  larger cap.
- WHY: via/trace L is in series with the cap; it is the recharge-path
  bottleneck.
- WHERE: PDF p266 §7.3.
- MACHINE FORM: routing rule for decap fanout — widen cap-to-via traces,
  minimise via count, favour multiple small caps. Same direction as Ott
  OTT-D5 (via-at-pad-side mounting table).
- APPLICABILITY: all bypassing.

---

## 6. Vias and return-current jumps (Ch 7 §7.4)

### HSDD-V1 — A signal via with no nearby ground via is an EMI/crosstalk source
- THRESHOLD: where a signal changes layers, its return current cannot
  follow unless a ground path exists at that point. Remedies ranked:
  (1) keep each trace on the layer it starts; (2) restrict traces to the
  side of the plane they start nearest (natural H/V layer pairs);
  (3) put a **ground via next to every signal via**; (4) flood ground
  vias everywhere.
- WHY: the return detours to the nearest inter-plane connection → larger
  loop → more radiation AND more crosstalk.
- WHERE: PDF p267–268 §7.4.
- MACHINE FORM: router cost — layer-change penalty for critical nets;
  check — a critical-net via has a ground/stitch via within a set radius.
  Identical intent to Ott OTT-R3.
- APPLICABILITY: multi-plane boards; on 2-layer, a top↔bottom signal via
  needs a ground grid crossing/via nearby.

### HSDD-V2 — Do NOT use guard traces as a return path
- THRESHOLD: guard traces "don't do anything until they get very close"
  and to serve as a return they would have to be very wide; over a solid
  plane they cause "nothing but trouble."
- WHY: a guard is a poor, high-inductance stand-in for continuous return
  copper.
- WHERE: PDF p268 §7.4.
- MACHINE FORM: reject any composition that uses a guard net as the
  declared return for a signal; require real return copper. (Pairs with
  HSDD-X2 which allows guards purely for crosstalk on no-plane boards.)
- APPLICABILITY: all boards.

---

## 7. Connectors and cable EMI (Ch 9) — the "ground-pin" rules

### HSDD-C1 — Spread grounds THROUGH the connector; grounds at the ends do nothing
- THRESHOLD: connector crosstalk is mutual-inductance dominated and is
  "roughly proportional to the number of signal wires between grounds."
  One ground between two signals halves coupling; N grounds between them
  give coupling ∝ 1/(1+N²) (reduction ≈ 2N+1). **"Adding extra grounds
  at the end of a connector does almost nothing."** Practical placement
  guide from the worked example: no signal pin more than ~0.2 in from a
  ground pin (Fig. 9.8).
- WHY: a ground pin diverts return current away from adjacent signal
  loops only where it physically sits; end lugs are too far from the
  interior signals.
- WHERE: PDF p304–305 §9.1 (rules 4–5), Eq. 9.4; PDF p309 Fig. 9.8.
- MACHINE FORM: connector-footprint check — max signal-to-nearest-ground
  pin distance ≤ threshold; ground pins interspersed (not lumped at
  ends); "crosstalk ∝ signals-between-grounds" as the finding metric.
- APPLICABILITY: every multi-signal connector — LIVE (USB-C, headers).

### HSDD-C2 — Give every connector a low-inductance return; kill remote return loops
- THRESHOLD: return current diverted through a connector's ground pins
  forms a loop "bubble" that dominates the bus loop inductance; any
  return that finds a REMOTE path (second connector, chassis, I/O cable)
  radiates hugely. Fixes: more/interspersed ground pins (lower the local
  loop L and current), a continuous ground contact along the card edge,
  and **never attach I/O cables to the far edge** of a board.
- WHY: emissions ∝ loop_area · I_peak · Fclock / Tr (Eq. 9.6); moving a
  second connector farther apart makes it WORSE (area grows faster than
  inductance suppresses current).
- WHERE: PDF p305–310 §9.2, Eq. 9.6, Fig. 9.7. (Eq. 9.6 leading constant
  ~1.4e-18 is OCR-uncertain; the loop-area·I·f/Tr proportionality and
  "spread the grounds / don't create remote loops" conclusions are firm.)
- MACHINE FORM: placement check — cable-bearing connectors grouped in one
  I/O zone with continuous edge-ground; finding when a cable exits the
  edge opposite the ground bond. Aligns with Ott OTT-IO1/IO2.
- APPLICABILITY: boards with board-to-board or cable connectors.

### HSDD-C3 — Slow the driver / filter the cable; exposed high-speed wiring always fails FCC
- THRESHOLD: "Exposed wiring carrying high-speed digital signals between
  circuit boards always fails FCC and VDE radiated-emission tests."
  Emission ∝ 1/Tr, so use the SLOWEST practical driver on off-board
  lines; filter/slow every outgoing signal before it exits the chassis
  (series R/ferrite + a source-side cap — never a receiver-side cap,
  which just raises surge current); a common-mode choke on the cable
  suppresses remote-return current.
- WHY: off-board conductors are efficient antennas driven by ground-noise
  common-mode current; slowing edges and filtering starves them.
- WHERE: PDF p303 §9.1 (source-cap placement), PDF p310 §9.2 rule 6,
  PDF p321 §9.6.
- MACHINE FORM: composition rule — every off-board digital line gets a
  source-side slow/filter element; USB and similar get controlled-edge
  drivers. Matches Ott OTT-IO3.
- APPLICABILITY: any signal leaving the board on a cable — LIVE (USB-C).

---

## 8. Trace sizing and layer-stack strategy (Ch 5 §5.8)

### HSDD-D1 — Trace current capacity at a 10 °C rise
- THRESHOLD: keep trace heating inside a digital product ≤ ~10 °C. At
  that rise a **0.010 in-wide 1-oz trace (≈1.35e-5 in² area; exponent corrected 2026-07-12 per spot-check, width x thickness arithmetic) carries
  ~750 mA** (Fig. 5.23); capacity scales with cross-sectional area.
- WHY: temperature rise ∝ dissipated power for a given cross-section;
  hot traces are unreliable and heat neighbours.
- WHERE: PDF p221 §5.8.3, Fig. 5.23. (750 mA / 10 °C reads consistently;
  the log-log chart limits absolute OCR precision — treat as ±.)
- MACHINE FORM: cross-check against the existing IPC-2221/2152 trace-width
  calculator; Johnson's 10 °C interior limit is a conservative default
  for logic boards. See cross-book CB4.
- APPLICABILITY: signal and small-power traces; large power buses need the
  full IPC chart.

### HSDD-S1 — Design power/ground FIRST; plane pairs; symmetric stack
- THRESHOLD: plan power and ground layers before signals; use ground and
  power planes in PAIRS and keep the stack symmetric (a single offset
  plane warps the board). Transmission lines over a power plane work as
  well as over ground.
- WHY: the return system is nearly impossible to retrofit and sets the
  inductance floor; mechanical symmetry prevents warping.
- WHERE: PDF p219–222 §5.8.1–5.8.3.
- MACHINE FORM: pipeline ordering knob (ground/pour stitching before
  signal nets) + a mechanical-symmetry advisory. Matches Ott OTT-GR2.
- APPLICABILITY: all boards; on 2-layer this means "commit the gridded/
  solid return before routing signals."

### HSDD-S2 — Chassis/return strategy for controlled off-board drivers
- THRESHOLD: a controlled-rise-time off-board driver referenced to noisy
  digital ground "broadcasts ground noise outside." Bond digital ground
  to chassis over a WIDE parallel surface (plane-to-chassis along one
  axis near the driver) — not a wire (too much lead inductance); a
  separate chassis plane preserves low-frequency isolation if needed.
- WHY: only a large parallel-plate bond is low-inductance enough to short
  ground noise at RF.
- WHERE: PDF p219–220 §5.8.2, Fig. 5.22.
- MACHINE FORM: metadata + check — chassis-bond pads (≥2, wide, no
  thermal relief) near the I/O driver zone. Ties to Ott OTT-IO2.
- APPLICABILITY: products with a chassis and off-board drivers.

---

## Cross-book notes (recorded, not resolved)

- **CB1 — "highest significant frequency" definition differs three ways.**
  Johnson **Fknee = 0.5/Tr** (500 MHz @1 ns); Bogatin **BW = 0.35/Tr**
  (350 MHz @1 ns); Ott **BW = 1/(π·Tr) ≈ 0.318/Tr** (318 MHz @1 ns).
  Bogatin and Ott nearly agree; Johnson's is ~50 % HIGHER — deliberately
  conservative ("used as a guidepost … insignificant, worrisome, or
  devastating"). For PCBSmith: keep Ott's `bw=1/(π·tr)` as the default
  numeric knob (it is the median-to-conservative for emissions) but note
  that for "is this circuit flat enough" screening Johnson would push the
  test frequency higher. Do NOT silently unify — expose both.
- **CB2 — unterminated-length rule AGREES across books at ~1 in/ns FR-4.**
  Johnson's lumped cutoff l/6 → ≈0.93 in/ns; Bogatin's TD<20 %·RT →
  max length ≈ RT[ns] inches = 1 in/ns; both land together. Johnson's
  practical example is looser still (round-trip < rise time). Encode the
  Bogatin form (`len_mm > 25.4·rt_ns → distributed`) — it is the cleaner
  machine rule and Johnson corroborates it.
- **CB3 — guard traces: three books converge.** Johnson: over a solid
  plane guards are "nothing but trouble," useful only on no-plane
  boards, grounded both ends, floating guard is worse. Bogatin: fitting a
  guard (s=3w) already cuts noise ~4×; a both-ends-shorted guard halves
  again; floating guard worsens; ≥3 stitch vias per rise-time extent.
  Montrose: a guard "works only if closer to the signal than the plane
  spacing is" and in stripline is "a waste of time." All three agree
  guards are a niche 2-layer/no-plane tool, never a default over a plane.
  No conflict — combine into one `guard` role check.
- **CB4 — crosstalk spacing: Johnson (physics) vs Montrose (heuristic).**
  Johnson gives the continuous law 1/(1+(D/H)²) with 1–3 % acceptable;
  Montrose gives the fixed **3-W rule** (≈70 % flux boundary) and Bogatin
  the tabulated NEXT ≈ 5 %/2 %/1 % at s=w/2w/3w. These are compatible: 3-W
  and s=3w are the same geometry and both land near ~1 % — inside
  Johnson's "fine" band. Johnson's advantage is that it exposes H, so on
  a THICK 2-layer dielectric it correctly warns that 3-W is not enough
  (need D≈5.7·h ≈ 9 mm at h=1.6 mm). Record: use the D/H law for 2-layer
  (H-aware), fall back to 3-W as the floor when H is small/plane is close.
- **CB5 — trace current.** Johnson's 750 mA @0.010 in/1 oz/10 °C is a
  single conservative data point; IPC-2221/2152 (already encoded) is the
  authority. They are consistent in magnitude; keep IPC as the source of
  truth and treat Johnson's 10 °C interior limit as a default ΔT.
- **CB6 — 2-layer high-speed ceiling.** Johnson calls the power-and-ground
  grid adequate only for "small low-speed CMOS and ordinary TTL," not
  high-speed logic; Ott caps 2-layer at ~10 MHz clocks (20–25 MHz with
  expertise). Both agree our ≤50 MHz / 3 ns 2-layer class rides at the
  edge of honesty → standing advisory finding, with grid + close pour +
  crosstalk spacing + source damping all required, not optional.

---

## Top 10 most machine-encodable rules (ranked)

1. **HSDD-K2 / CB2 lumped-vs-distributed length** — `len_mm > 25.4·rt_ns`
   → tag distributed; cross-book-agreed ~1 in/ns; gates whether any
   termination/reflection logic even runs. Highest leverage (proves most
   nets on our boards are lumped).
2. **HSDD-X1 crosstalk = 1/(1+(pitch/h)²), 1–3 % band** — closed-form,
   H-aware, directly flags the dominant risk on thick 2-layer buses.
3. **HSDD-G4/G5 no-slot / connector-pin ground continuity** — pure
   geometry over the return copper; extends the hole-obstacle model;
   identical to Ott OTT-R1/R4 (shared check).
4. **HSDD-C1 connector ground-pin spread** — footprint check: max
   signal-to-ground-pin distance + "grounds not at ends"; crisp
   1/(1+N²) metric.
5. **HSDD-P1 SMT ≤1206 decoupling, L-ESR-C model** — BOM/placement rule
   plus `|Z|(f)` calculator; Table 8.1 numbers ready to encode.
6. **HSDD-K1 knee_freq(tr)=0.5/tr** — the master screen; trivial knob,
   feeds every other rule (coexists with Ott bw knob per CB1).
7. **HSDD-P2 bypass radius l/12 + Tr² scaling** — placement distance
   check with a clean derivation; explains WHY faster parts need closer
   caps.
8. **HSDD-V1 ground via beside every critical signal via** — countable at
   route time; same intent as Ott OTT-R3.
9. **HSDD-C2/C3 cable EMI: one I/O zone, edge ground, slow/filter
   off-board drivers** — placement + composition checks; "exposed
   high-speed wiring always fails FCC" is a hard rule for USB-C boards.
10. **HSDD-G2 two-layer ground hierarchy (grid default, fingers = finding)**
    — composition knob picking the return topology; carries the standing
    2-layer-ceiling advisory (CB6).

---

## Verification (2026-07-12, spot-check, sonnet)

| rule | verdict | note |
|------|---------|------|
| HSDD-K1 | VERIFIED | `Fknee = 0.5/Tr`, Eq 1.1, PDF p11 (`Fknee = 0.5 / Tr`). "6.8 dB below the natural 20-dB/decade rolloff" and "hardly affects digital performance" both read cleanly on PDF p11-12. Exact match. |
| HSDD-K2 | VERIFIED | `l = Tr/D` Eq 1.3 and "Circuits smaller than l/6 are lumped" Eq 1.4, PDF p16-17 — text reads verbatim, no OCR ambiguity. Derived `≈25·tr_ns mm` (v≈150 mm/ns outer trace) is consistent arithmetic, not itself a printed number. |
| HSDD-X1 | VERIFIED | `Crosstalk < 1/(1+(D/H)²)` Eq 5.14/5.15, PDF p209, worked example D/H=8 → "=0.015" (1.5%) printed explicitly, matching the note's "D/H = 8 → 1.5%" exactly. "a crosstalk level of 1-3% between adjacent wires is fine" (assumes solid plane, sum contributions on hatch/fingers) reads verbatim on the same page. |
| HSDD-G3 | VERIFIED | `L ~ 5Y·ln(X/W)` Eq 5.11 (grid, PDF p206) and the same `5Y ln(X/W)` form Eq 5.13 (fingers, PDF p208) — the constant "5" reads identically and unambiguously in TWO independently-OCR'd equations on different pages, which is strong corroboration despite the note's "OCR-uncertain" caution; no digit-swap candidate (0/O, 1/l, 3/5/8) fits both instances better. Downgrade the OCR-uncertain flag on the constant itself; the note's caveat that it's "a first-order estimate, not a precision value" is Johnson's own framing, still valid. |
| HSDD-P1 | VERIFIED | Table 8.1 (PDF p291), item 8 row reads "8 0.1 0.1 1.1 SMT 1206" = lead-spacing 0.1 in / **ESR 0.1 Ω** / **lead inductance 1.1 nH** — matches the note's "SMT 1206 ≈ 1.1 nH, ESR ~0.1 Ω" exactly (columns confirmed against the header row and items 1-7, whose ESR 0.1-1.1 Ω and inductance 4-16 nH ranges also match the note). The "~8 dB" bonded-vs-socketed claim (items 6 vs 7) is stated verbatim on PDF p293 ("makes an 8-dB difference in the impedance above 10MHz"). |
| HSDD-P2 | VERIFIED | PDF p266: "The effective radius within which this effect works is equal to l/12... All capacitors within the diameter of l/6 act in concert as a lumped circuit," worked to "l/12 = 0.5 in." for a 1 ns edge (l=6in). "a particular configuration of bypass capacitors that works at one frequency is eight times less effective when we halve the rise time" — exact match to the note's l/12 radius and "~8× less effective" claim. |
| HSDD-C1 | VERIFIED | Eq 9.4 (PDF p304) reads "Coupling is proportional to: 1/(1+N²)" with caption "coupling is reduced by a factor of 2N+1" — exact match. Rule 5 (PDF p305): "Adding extra grounds at the end of a connector does almost nothing to reduce crosstalk" — verbatim. Fig 9.8 caption (PDF p309): "No signal lies more than 0.2 in. away from a ground pin" — exact match to the note's "~0.2 in" placement guide. |
| HSDD-D1 | MISMATCH | The 750 mA / 10 °C / 0.010-in-wide-1-oz-trace claim itself is VERIFIED verbatim on PDF p221 ("a 0.010-in.-wide trace of 1-oz copper (0.00135 in. thick) can safely pass 750 mA of current at a temperature rise of 10° C"). But the note's parenthetical **"≈1.35e-3 in² area" is wrong by 100×**: 0.010 in × 0.00135 in = **1.35×10⁻⁵ in²**, not 1.35×10⁻³ in². This is not the cache's OCR garbling — the source page's own footnote gives the identical mantissa with only the exponent digit dropped ("cross-sectional area of 1.35×10- in.2" on PDF p221), and dimensional analysis (width × thickness) is unambiguous: the correct exponent is -5. This is an arithmetic slip introduced when the note was written, not a source disagreement or an OCR/glyph issue — flag for correction (1.35e-3 → 1.35e-5 in²). |

7/8 verified; 1 mismatch (HSDD-D1's cross-sectional-area parenthetical is off by 100× — 1.35e-5 in² per width×thickness, not 1.35e-3 in² as written; the 750 mA/10 °C headline number itself is correct and verbatim-sourced). No UNFINDABLE rules; no case where the cache's OCR itself was shown to disagree with the physics once cross-checked against neighbouring pages/equations.
