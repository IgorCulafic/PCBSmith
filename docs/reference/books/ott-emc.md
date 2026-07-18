# Ott — Electromagnetic Compatibility Engineering (2009): distilled rules

Provenance:
- Book: Henry W. Ott, *Electromagnetic Compatibility Engineering*, Wiley 2009.
- Text cache: `.book-cache/ott-emc/` (p0001–p0862), sha256
  `5d1ca4d84fc6a67953846d480ce8752921d0ad7d610ab01c065024b7b92f748e`
  (from `.book-cache/manifest.json`).
- Extracted: 2026-07-11. Locators are "PDF p.N" into the cache; printed
  page = PDF page − 25 (offset verified on chapter title pages).
- Board class filter applied: 2-layer, 3.3 V/5 V logic, clocks ≤ 50 MHz,
  I2C/SPI, small switching converters, one WiFi module (supply/ground
  only).

Chapter map (read deep / skimmed / skipped):
- READ: Ch 3 Grounding §3.2 (signal grounds, PDF p.145–156); Ch 4 §4.3
  (analog decoupling, p.203–211); Ch 10 Digital Circuit Grounding
  (p.404–447); Ch 11 Digital Circuit Power Distribution (p.450–488);
  Ch 12 Digital Circuit Radiation (p.489–516); Ch 13 §13.2 (SMPS
  emissions, p.520–535); Ch 16 PCB Layout and Stackup (p.645–683);
  Ch 17 Mixed-Signal PCB Layout (p.685–712).
- SKIMMED: Ch 15 §15.5.2 (I/O cable ESD treatment, p.624–629) — only
  the grounding-of-protection-parts rule extracted.
- SKIPPED (per brief): Ch 1–2 (intro, cabling), 5 (passives, except
  facts quoted inside Ch 10/11), 6 (shielding enclosures), 7 (contact
  protection), 8–9 (device noise), 13 mains-filter details, 14
  (immunity test), 15 bulk (ESD guns), 18 (precompliance measurement).

Foundation fact used throughout: the bandwidth of a digital edge is
BW = 1/(π·tr) (Eq. 10-2, PDF p.404, §10.1). A 1 ns edge ≡ 318 MHz.
Applicability of every "high frequency" rule below is judged against
the edge rate, not the clock fundamental.

---

## 1. Grounding topology vs frequency (Ch 3 §3.2, Ch 10 §10.5)

### OTT-G1 — Single-point grounds are a low-frequency technique
- THRESHOLD: single-point (star) grounding effective DC–20 kHz; "should
  usually not be used above 100 kHz" (sometimes pushed to 1 MHz).
  Multipoint (grid/plane) grounding is for >100 kHz and all digital.
- WHY: above ~100 kHz conductor inductance dominates resistance (a
  24 AWG wire 1 in over a plane crosses over at 13 kHz, PDF p.145);
  stray capacitance turns any attempted star into an uncontrolled
  multipoint anyway (Fig. 3-18, PDF p.151).
- WHERE: PDF p.149 §3.2.1, p.150–152 §3.2.2, p.146 Fig. 3-10.
- MACHINE FORM: design check — any net classified digital or
  >100 kHz must be grounded to the grid/plane (multipoint); star-only
  ground topologies allowed only for audio/DC analog subcircuits.
- APPLICABILITY: the 20 kHz / 100 kHz / 1 MHz limits are Ott's exact
  numbers. All our digital boards are multipoint by default.

### OTT-G2 — Ground lead length limit
- THRESHOLD: any ground lead/stub < λ/20 at the highest frequency of
  concern (λ/20 at 318 MHz ≈ 47 mm; at 50 MHz ≈ 300 mm).
- WHY: longer leads have high impedance and act as antennas; odd
  quarter-wave multiples are resonant.
- WHERE: PDF p.151 §3.2.1.
- MACHINE FORM: check — ground stub trace length from any pad to the
  grid/plane < λ/20 at BW = 1/(π·tr) of the attached IC's logic family.
- APPLICABILITY: all frequencies; binding for fast logic ground pins.

### OTT-G3 — Return current path changes with frequency
- THRESHOLD: below "a few hundred kilohertz" return current takes the
  least-RESISTANCE (direct/diagonal) path; above it, the
  least-INDUCTANCE path directly under the signal trace.
- WHY: loop inductance minimization; the plane current distribution
  formula (Eq. 10-13) is valid only above a few hundred kHz where
  inductive reactance dominates plane resistance.
- WHERE: PDF p.147 Fig. 3-12; PDF p.418 (validity note under Eq. 10-13).
- MACHINE FORM: router knob — for nets tagged low-frequency/high-current
  (motor, relay, LED column drive at kHz PWM), the return conductor
  must be an explicit paired trace, not "the plane will handle it"
  (see OTT-MX6). For fast nets, obstruct nothing directly under them.
- APPLICABILITY: crossover a few hundred kHz — I2C at 100–400 kHz sits
  ON the boundary; treat SCL as high-frequency (its edges are ns-scale).

---

## 2. Ground structure for 2-layer boards (Ch 10 §10.5, Ch 16 §16.4.1)

### OTT-GR1 — Grid is the required topology; plane is its limit
- THRESHOLD: every digital board gets a ground GRID or plane. Grid
  spacing ≤ 0.5 in (12.7 mm) — Smith & Paul study cited as "0.5 in or
  less ... most significant reduction of ground noise".
- WHY: N parallel paths divide inductance by ~N once mutual inductance
  is decoupled; a plane is the limiting case of a grid. Measured
  (German 1985, Table 10-2): grid vs single-point ground dropped worst
  IC-to-IC ground noise 1000 mV → 100 mV and radiated emissions 7.1 dB.
- WHERE: PDF p.413–414 §10.5.3, Table 10-2 p.414.
- MACHINE FORM: post-route check — build the ground copper graph on
  both layers; verify a connected mesh whose maximum cell dimension
  ≤ 12.7 mm over the digital zone; report the largest cell.
- APPLICABILITY: grids proven "up to a few tens of MHz"; above
  5–10 MHz Ott says seriously consider a plane. For our ≤50 MHz class:
  grid is the floor, a gridded pour on both layers is the target.

### OTT-GR2 — Lay the grid first; narrow closing traces count
- THRESHOLD: grid before signal routing; primary distribution wide
  (DC drop), closing traces may be narrow ("narrow trace better than
  no trace"). Horizontal runs on one side, vertical on the other,
  vias at crossings.
- WHY: width is a DC/resistance parameter; gridding is the inductance
  parameter — the two are independent. Grid is nearly impossible to
  retrofit after signal routing.
- WHERE: PDF p.413 §10.5.3, Fig. 10-5.
- MACHINE FORM: pipeline ordering knob — route_board phase order:
  ground grid/pour stitching before signal nets; permit min-width grid
  closers.
- APPLICABILITY: 1- and 2-layer boards (multilayer gets planes).

### OTT-GR3 — Widening a trace barely reduces inductance
- THRESHOLD: doubling width → only ~20% inductance drop; 12× width for
  50%. Loop inductance of a PCB trace: L = 0.005·ln(2πh/w) µH/in
  (Eq. 10-5, valid h ≥ w). Reference values: 0.006 in trace 0.02 in
  from return = 15 nH/in and 82 mΩ/in; ≈30 Ω/in reactance for 1 ns
  edges (Table 10-1).
- WHY: logarithmic dependence; parallel paths (grid) or reduced spacing
  (loop area) are the effective levers.
- WHERE: PDF p.409–411 §10.5.1, Table 10-1 p.410.
- MACHINE FORM: calculator — expose trace_loop_inductance(h, w, len)
  in `calculators/electronics.py`; refuse "wider ground trace" as a
  fix suggestion when inductance is the failing quantity.
- APPLICABILITY: any 2-conductor trace pair; equations for long narrow
  traces, h ≥ w.

### OTT-GR4 — Parallel same-direction conductors: separate them
- THRESHOLD: two paralleled ground conductors reach most of their
  inductance benefit within the FIRST 0.5 in of separation; closer than
  that, mutual inductance cancels the benefit.
- WHY: Lt = (L+M)/2; tightly coupled parallel conductors behave as one.
- WHERE: PDF p.411–412 §10.5.2, Fig. 10-4.
- MACHINE FORM: knob — when adding redundant ground stitching traces or
  via pairs for inductance (not thermal), space them ≥ 12.7 mm apart;
  conversely signal+return pairs as CLOSE as possible (OTT-L1).
- APPLICABILITY: conductors carrying current in the SAME direction.

### OTT-GR5 — Via constriction dominates plane/grid inductance
- THRESHOLD: measured: plane inductance rises within ~1 in of a single
  feeding via, approaching trace-like 15 nH/in at the via; 3 vias
  (0.1 in apart, perpendicular to trace) halve the constriction
  inductance. A through-via on a 62-mil board ≈ 0.8 nH.
- WHY: the plane's low inductance comes from current spreading; forcing
  current through one via un-spreads it.
- WHERE: PDF p.434–435 §10.6.4, Figs. 10-27/28/29; via value PDF p.469.
- MACHINE FORM: knob — ground return transitions for critical nets get
  ≥2 stitching vias; decoupling-cap ground connections prefer 2 vias.
- APPLICABILITY: any plane/pour fed through vias; matters most for
  nets with ns edges.

---

## 3. Loop area and trace-return proximity (Ch 10 §10.5.4/10.6, Ch 12 §12.1–12.2)

### OTT-L1 — Signal and return as close as possible
- THRESHOLD: no number — a direction rule with a formula behind it:
  differential-mode radiated E = 263e-16·f²·A·I/r (Eq. 12-2, free
  space +ground reflection); at 3 m E = 87.6e-16·f²·A·I. Radiation
  grows with frequency SQUARED and linearly with loop area A.
- WHY: opposite-direction currents: Lt = 2(L−M); maximizing mutual
  inductance (proximity) cancels loop inductance and shrinks the
  radiating loop.
- WHERE: PDF p.415–416 §10.5.4; PDF p.489–490 §12.1.
- MACHINE FORM: scoring — compute enclosed loop area for each
  critical net (signal path vs actual return path through the grid);
  emissions estimate via Eq. 12-3 against FCC B as a design check
  (needs I and tr from the component card).
- APPLICABILITY: loops with circumference < λ/4 (small-loop model);
  above that the formula overestimates.

### OTT-L2 — Return current spread under a microstrip
- THRESHOLD: return current in a plane/grid under a trace at height h:
  50% within ±1h, 80% within ±3h, 97% within ±20h, 99% within ±50h of
  the trace centerline (Table 17-1 / Fig. 10-10). Crosstalk between
  adjacent traces ∝ h²/x² (Eq. 10-15).
- WHY: Holloway/Kuester current density J(x) ∝ arctan terms in x/h; the
  spread is what makes the plane low-inductance.
- WHERE: PDF p.417–419 §10.6.1.1; Table 17-1 PDF p.688; Eq. 10-15
  p.419.
- MACHINE FORM: two checks — (a) keep a corridor of intact ground
  copper ±20h around critical traces; (b) crosstalk screen: victim
  spacing x such that h²/x² below threshold instead of blanket
  spacing rules.
- APPLICABILITY: frequencies above a few hundred kHz; h = dielectric
  thickness (2-layer: ~1.5 mm — so ±20h = ±30 mm, rarely satisfiable:
  prefer paired return traces on 2-layer, OTT-C2).

### OTT-L3 — Board-edge keep-out for critical signals
- THRESHOLD: keep critical traces ≥ 20× (trace-height-above-plane) from
  the board edge.
- WHY: return current needs room to spread symmetrically (OTT-L2); at
  the edge the distribution is truncated, raising inductance and
  emissions.
- WHERE: PDF p.646 §16.1.2, Fig. 16-2.
- MACHINE FORM: DRC-style check — clock/critical nets ≥ 20h from
  outline (2-layer h=1.5 mm → 30 mm is impractical; encode as "route
  critical nets through board interior, never along the rim" with a
  relaxed floor, e.g. ≥5 mm, and record the deviation).
- APPLICABILITY: boards with a reference plane/grid under the trace.

### OTT-L4 — One ground return trace per 8 bus bits
- THRESHOLD: on double-sided boards, ≥1 ground return trace adjacent to
  each group of 8 data/address lines, placed next to the LSB (highest
  toggle rate).
- WHY: bounds every bus bit's return loop without a full plane.
- WHERE: PDF p.496 §12.2.1.
- MACHINE FORM: composition rule — parallel buses (our 74HC595 SEG
  lines qualify) get an accompanying GND trace in the routing corridor
  per 8 members.
- APPLICABILITY: 2-layer boards; multilayer with plane exempt.

---

## 4. Return path continuity (Ch 16 §16.3)

### OTT-R1 — No slots in the ground structure; holes must not overlap
- THRESHOLD: a 1.5 in slot under a trace raised local ground voltage
  5× (15→75 mV, 14 dB, Table 16-1); a 1-in line of NON-overlapping
  0.052 in holes raised it 0%. Slots/splits can add >20 dB radiation.
- WHY: return current detours around the slot → large loop, higher
  inductance, more emission and crosstalk.
- WHERE: PDF p.650–651 §16.3.1, Table 16-1 p.651.
- MACHINE FORM: check — in the ground pour/grid, detect overlapping
  clearance holes forming an effective slot under any routed net;
  flag trace-crosses-slot as a blocker. (Generalizes our existing
  hole-true obstacle model to the RETURN layer.)
- APPLICABILITY: all boards with pours/grids; the measured numbers are
  10 MHz / 3 ns edges — representative of our class.

### OTT-R2 — Traces must not cross plane splits; stitching caps are last resort
- THRESHOLD: stitching capacitor within 0.1 in (2.54 mm) of the
  crossing trace, 1–10 nF; adds ~5 nH (3 Ω @100 MHz). Measured: solid
  plane −37 dB, 1 stitching cap −28 dB, 2 caps −32 dB vs split at
  300 MHz (Archambeault).
- WHY: return current must cross the gap somewhere; a cap is a poor
  substitute for continuous copper.
- WHERE: PDF p.651–653 §16.3.2, Fig. 16-6.
- MACHINE FORM: check — no signal trace crosses a gap between distinct
  ground/power pour regions on its return layer; if declared exception,
  require a stitch cap within 2.54 mm.
- APPLICABILITY: any split reference (e.g. separate analog pour,
  isolated converter output region).

### OTT-R3 — Layer changes: keep the same reference
- THRESHOLD: preference order for critical signals: (1) one layer only;
  (2) two layers referencing the SAME plane (return passes through the
  via antipad barrel — no discontinuity); (3) two planes same type +
  plane-to-plane via at the signal via; (4) different-type planes +
  cap at the via; (5) never more layers. Measured: a single top→bottom
  transition on a 30 cm trace raised emissions ~30 dB at 247 MHz.
- WHY: return current cannot penetrate a plane above skin-effect
  opacity (1 oz: 30 MHz; 0.5 oz: 120 MHz; 2 oz: 8 MHz) — it must find
  a physical path between reference surfaces.
- WHERE: PDF p.653–656 §16.3.3/16.3.4; skin thresholds PDF p.417 fn,
  p.649.
- MACHINE FORM: router cost knob — layer-change penalty for nets
  tagged critical; check — every critical-net via has a ground
  stitching via within a set radius (2-layer: ground grid crossing via
  nearby).
- APPLICABILITY: on our 2-layer boards top and bottom ground pours ARE
  "two planes of the same type": the stitching-via-near-signal-via
  check is the applicable form.

### OTT-R4 — Connector pin fields: per-pin clearance, not a cutout
- THRESHOLD: remove copper only around individual pins; never a single
  cutout under the whole connector.
- WHY: a cutout is a slot (OTT-R1) exactly where all I/O return
  currents concentrate.
- WHERE: PDF p.657 §16.3.5, Fig. 16-11.
- MACHINE FORM: pour-generation rule + check: ground pour must flow
  between connector THT pins (ties into our hole-to-copper 0.25 mm
  constraint — verify pour webs exist between pins, flag if annulars
  merge into a slot).
- APPLICABILITY: all connectors over ground copper.

### OTT-R5 — Ground fill must be stitched, never floating
- THRESHOLD: fill connected to the ground structure at MULTIPLE points;
  no floating islands ever; avoid small or long-skinny fill areas.
- WHERE: PDF p.657–658 §16.3.6.
- WHY: floating copper couples noise capacitively into neighbors,
  worsens crosstalk and ESD.
- MACHINE FORM: check — every ground-fill polygon: ≥2 connections
  (via/trace) to the grid; delete islands below a minimum area
  automatically.
- APPLICABILITY: all boards. (Ott cautions fill on high-speed
  controlled-impedance digital; fine for our class.)

---

## 5. Decoupling — digital (Ch 11)

### OTT-D1 — It's an L-C network, not a capacitor
- THRESHOLD: budget the loop: SMT cap internal 1–2 nH (0603 ≈ 0.6 nH,
  1206 ≈ 1.2 nH), PCB traces+vias 5–20 nH, IC lead frame 3–15 nH;
  typical total 15–30 nH. 0.1 µF+30 nH resonates at 3 MHz; 0.01 µF at
  9 MHz; above ~50 MHz the inductance alone sets the impedance
  regardless of capacitor value.
- WHY: series L-C; above resonance only L matters.
- WHERE: PDF p.456–457 §11.3, Fig. 11-8.
- MACHINE FORM: calculator — decoupling_network(C, L_mount) returning
  f_res and |Z|(f); design check that the network impedance at the
  logic BW=1/(π·tr) is below target (OTT-D3).
- APPLICABILITY: all digital ICs. For 3.3 V logic with 2–5 ns edges
  (BW 64–160 MHz) mounting inductance is the whole game.

### OTT-D2 — Same-value capacitors; avoid decade-spread arrays
- THRESHOLD: multiple capacitors ALL the same value, physically spread
  out (mutual-L decoupling); values within 2:1 are fine; decade-apart
  values create antiresonance spikes measured up to +25 dB noise in
  50–200 MHz (Archambeault).
- WHY: n same-value networks: C×n, L/n, no parallel-resonant peak;
  large/small pairs form an L‖C tank between their resonances.
- WHERE: PDF p.460–467 §11.4.2–11.4.4.
- MACHINE FORM: BOM/composition rule — one decoupling value per rail
  per board (plus bulk); check flags mixed decade values on the same
  rail without a declared reason.
- APPLICABILITY: high-frequency digital decoupling; the bulk cap is the
  sanctioned exception (spike lands low and damped, OTT-D6).

### OTT-D3 — Target impedance sizing
- THRESHOLD: Zt = k·dV/dI with k = 2 (only ~half the transient spectrum
  is below 1/(π·tr)); Zt may rise 20 dB/decade above f = 1/(π·tr).
  Minimum capacitor count n = 2L/(Zt·tr) (Eq. 11-7). Worked example:
  2 ns, 2.5 A, 5% of 5 V → Zt = 200 mΩ, 50 caps @10 nH each.
- WHY: treat the IC as a noise current source; keep the shunt below Zt
  across the band instead of chasing resonant frequencies.
- WHERE: PDF p.468–470 §11.4.5, Eqs. 11-7/11-8, Fig. 11-17.
- MACHINE FORM: calculator — decoupling_plan(dI, dV, tr, L_mount) →
  (Zt, n, C_min); evidence: dI and tr from datasheet card, assumption
  status if absent.
- APPLICABILITY: any rail; for our small MCUs n usually lands at 1–4 —
  the formula still documents WHY.

### OTT-D4 — Minimum capacitance for the charge transient
- THRESHOLD: C ≥ dI·dt/dV (Eq. 11-12); e.g. 500 mA for 2 ns with 0.1 V
  droop → ≥ 0.01 µF. Then pick the LARGEST value available in the
  SMALLEST package (value doesn't hurt HF; package L does).
- WHERE: PDF p.480 §11.6.
- MACHINE FORM: calculator input to component selection: package ≤0603
  preferred for decoupling; value = max readily available in package.
- APPLICABILITY: per-IC decoupling, all speeds.

### OTT-D5 — Placement/mounting geometry
- THRESHOLD: measured mounting inductance for an 0805 (pads→plane):
  long thin traces 2.8 nH; wide short traces 2.1 nH; via at pad end
  1.1 nH; vias at pad SIDES 0.7 nH; doubled side vias 0.4–0.5 nH.
  Minimum TWO capacitors per IC (opposite ends); four on a quad
  package — the doubled, mirrored loops CANCEL (first doubling is
  worth ~18 dB total; diminishing after).
- WHY: loop area between cap, IC, and reference sets L; mirrored
  transient loops radiate anti-phase.
- WHERE: PDF p.481–482 §11.7 Fig. 11-25; two-cap analysis p.478–479
  §11.5.
- MACHINE FORM: placement check — decap-to-IC-power-pin loop
  (trace length + via count) budgeted in nH via the Fig. 11-25 table;
  ≥2 decaps per digital IC on opposite sides where package allows.
- APPLICABILITY: all SMT decoupling. On 2-layer boards "connect cap
  straight to the IC pins with short traces" is explicitly acceptable
  (fewer vias) — either topology passes if the loop is small.

### OTT-D6 — Bulk decoupling
- THRESHOLD: bulk C > Σ(IC decoupling caps served); 5–100 µF (typ.
  10 µF); one at the power entry point, others spread; multilayer
  ceramic or tantalum — NOT aluminum electrolytic (10× the ESL). A
  little ESR is beneficial (damps antiresonance).
- WHERE: PDF p.482–483 §11.8.
- MACHINE FORM: BOM check — per rail: bulk cap present at power entry,
  value > sum of that rail's decaps, dielectric/technology whitelist.
- APPLICABILITY: every board; recharge path operates at ≤2× clock.

### OTT-D7 — Power entry filter on the DC input
- THRESHOLD: π filter: 0.01–0.1 µF caps + series ferrite 50–100 Ω over
  the band of interest (or 0.5–5 µH inductor); plus a common-mode
  element (CM choke on board or ferrite on the cable). Ferrite must
  not saturate at the DC current.
- WHY: confine the board's transient currents to the board; keep
  external noise out.
- WHERE: PDF p.483–484 §11.9, Fig. 11-26.
- MACHINE FORM: topology block — `power-entry-filter` inserted between
  input connector and rails; check its presence when a cable leaves
  the board.
- APPLICABILITY: boards with external DC supply cables (ours: USB-C).

### OTT-D8 — Analog decoupling: dissipative beats reactive
- THRESHOLD: prefer R-C over L-C stage decoupling; if L-C, damping
  ζ = (R/2)·√(C/L) > 0.5 to hold resonant gain < 2 dB. Amplifier decap
  must be a short across the amplifier's FULL gain bandwidth, not just
  the signal band.
- WHY: L-C filters relocate noise (across the inductor) and can ring;
  R-C converts it to heat. Undecoupled supply lead gain → oscillation
  via bias feedback.
- WHERE: PDF p.208–210 §4.3.1/4.3.2, Fig. 4-18/4-19.
- MACHINE FORM: calculator — lc_filter_damping(R, L, C) with ζ > 0.5
  check whenever a ferrite/inductor + cap feeds an analog rail (our
  SHT31 / sensor rails).
- APPLICABILITY: low-frequency analog stages sharing a supply.

---

## 6. Clocks and critical signals (Ch 12 §12.2, Ch 16 §16.1)

### OTT-C1 — Identify and prioritize critical signals
- THRESHOLD: 10% of circuitry causes 90% of problems. Critical =
  periodic + fast: clocks first, then buses, then repetitive strobes
  (ALE/RAS/CAS class). Speed metric: F0·I0/tr (Eq. 16-1).
- WHY: periodic signals concentrate energy in few harmonics — high
  amplitude per line; random data spreads it.
- WHERE: PDF p.646–647 §16.1.3; clock spectrum evidence PDF p.495
  Fig. 12-7.
- MACHINE FORM: net classifier — score nets by F0·I0/tr from intent +
  component cards; the top class drives routing order, loop budgets,
  keep-outs.
- APPLICABILITY: all boards. Our class: SPI SCK, 74HC595 SRCLK/RCLK,
  crystal/oscillator nets, converter switch node.

### OTT-C2 — Clock routing on 2-layer boards
- THRESHOLD: route clocks FIRST, absolute minimum loop area and length,
  minimum vias; adjacent ground return trace; best: ground return
  traces BOTH sides (symmetric) → return splits, mirrored half-loops
  cancel, 20+ dB reduction vs single return (Fig. 12-8).
- WHY: canceling loops beat unachievably small single loops.
- WHERE: PDF p.495–497 §12.2.1–12.2.2; 2-layer restatement PDF p.659
  §16.4.1.
- MACHINE FORM: router feature — `guard_return_nets=` for tagged
  clocks: auto-lay GND trace(s) parallel at min spacing, stitched to
  grid at both ends; route phase order: clock class first.
- APPLICABILITY: 2-layer, clock ≥ a few MHz or edges ≤ 10 ns.

### OTT-C3 — Series damping on clock outputs
- THRESHOLD: series R (≈33 Ω) or ferrite in EVERY clock output with
  f ≥ 20 MHz, placed at the driver, even for short traces. If trace
  length (in) ≥ 3 × tr (ns): treat as transmission line, R = Z0 −
  R_driver.
- WHY: damps the high-Q series-resonant ring of stray C with ground L
  (Q = (1/R)·√(L/C), Eq. 10-3) and controls reflections.
- WHERE: PDF p.648 §16.1.4 incl. footnote; ring mechanism PDF p.406–407
  §10.4.
- MACHINE FORM: composition check — clock-class net without a series
  R/ferrite at source = finding; calculator computes the long-trace
  criterion from tr and routed length.
- APPLICABILITY: ≥20 MHz clocks always; lower if ringing observed.

### OTT-C4 — Crystal/oscillator zone
- THRESHOLD: crystal/osc adjacent to the IC using it; local ground
  plane on the COMPONENT layer under crystal + driver, stitched to
  main ground with multiple vias; metal can grounded to that plane; no
  other signals routed under the crystal; provision for a board-level
  shield. Keep ≥ 0.5 in (13 mm) from the I/O area (keep-out). Ferrite
  bead in the oscillator/driver Vcc feed. On 1–2 layer boards prefer a
  crystal over a packaged oscillator (less harmonic energy).
- WHY: the highest-dV/dt periodic node; its stray fields must
  terminate locally, not on I/O cables.
- WHERE: PDF p.646 §16.1.2 (13 mm); PDF p.647–648 §16.1.4; PDF p.659
  §16.4.1 (crystal-vs-osc).
- MACHINE FORM: placement checks — distance(crystal zone, I/O zone)
  ≥ 13 mm; ground pour patch under crystal footprint with ≥2 stitch
  vias; routing keep-out over the patch.
- APPLICABILITY: all boards with crystals/oscillators (ESP32-C3 module
  has its own; our external clock sources on future boards).

---

## 7. Placement zoning / partitioning (Ch 16 §16.1.1, Ch 12 §12.2.1)

### OTT-P1 — Functional block zoning by speed
- THRESHOLD: zone the board: (1) high-speed logic+clocks farthest from
  I/O; (2) memory; (3) medium/low-speed logic; (4) analog/audio with
  I/O access that does NOT pass through digital zones; (5) I/O drivers
  next to connectors; (6) connectors + CM filters in ONE I/O area.
  Off-board line drivers sit at the connector and must not also drive
  on-board loads.
- WHY: minimizes trace lengths and parasitic coupling of the noisiest
  circuits into the unintentional antennas (cables).
- WHERE: PDF p.645–646 §16.1.1, Fig. 16-1; drivers PDF p.496 §12.2.1.
- MACHINE FORM: placement objective — zone assignment from
  ComponentRole speed class; check pairwise: high-speed zone∩I/O zone
  buffer ≥ 13 mm; analog corridor to I/O avoids digital zone hulls.
  (Directly generalizes the thermometer lesson: register IN its load
  zone.)
- APPLICABILITY: every board; the win grows with cable count.

### OTT-P2 — Critical-trace keep-out ring
- THRESHOLD: critical signals only inside the interior region; keep-out
  ring around board periphery and the whole I/O area (Fig. 16-2).
- WHERE: PDF p.646 §16.1.2.
- MACHINE FORM: router region constraint — forbid clock-class nets in
  the I/O zone polygon and the edge ring (see OTT-L3 for width).
- APPLICABILITY: all boards.

---

## 8. Mixed-signal partitioning (Ch 17)

### OTT-MX1 — ONE ground plane, partitioned; do not split
- THRESHOLD: single ground structure, board partitioned into analog and
  digital REGIONS; analog signals routed only over the analog region
  (all layers), digital only over digital. Return current follows the
  trace (OTT-L2), so digital returns never enter the analog region
  UNLESS a trace is misrouted. 100% routing discipline required —
  one misrouted trace defeats the layout; autorouting "more often than
  not results in a layout disaster".
- WHY: splitting fixes nothing a correct routing doesn't, and adds
  loop/dipole antennas; a trace crossing a split can add 20 dB
  emissions and crosstalk.
- WHERE: PDF p.688–689 §17.2, Figs. 17-3/4/5; p.693–694 §17.4.
- MACHINE FORM: check — with declared analog/digital region polygons,
  every net classified analog must have all copper inside the analog
  region (and vice versa); converters/straddle refs exempted by role.
  This is the mixed-signal sibling of our mains-isolation §10 checks.
- APPLICABILITY: all mixed-signal boards up to ~16-bit resolution;
  ≥18-bit needs more (stripline or the 0.25 in margin below).

### OTT-MX2 — Digital trace to analog-region margin
- THRESHOLD: keep digital traces ≥ 0.25 in (6.35 mm) from the analog
  partition boundary when h = 0.005 in (i.e., x/h ≥ 50 → 99% of return
  current stays digital-side). Scale as x ≥ 50h. Beyond x/h = 50 there
  is little further reduction.
- WHERE: PDF p.697–698 §17.6, Fig. 17-12, Table 17-3 context.
- MACHINE FORM: clearance check between digital-class copper and the
  analog region polygon: ≥ 50 × (layer-to-return spacing), capped
  pragmatically on 2-layer (h = 1.5 mm → advisory).
- APPLICABILITY: moderate/high-resolution analog (our SHT31 I2C side is
  digital; applies when we do ADC front-ends).

### OTT-MX3 — Mixed-signal ICs are ANALOG components
- THRESHOLD: AGND and DGND pins BOTH tied to the analog ground region,
  minimum length (converter noise couples through internal stray C
  otherwise). Exception: big DSP/codec parts — follow datasheet. In
  multi-board systems the converter goes on the ANALOG board.
- WHERE: PDF p.690–692 §17.3/17.5, Fig. 17-6; p.696 §17.5.1.
- MACHINE FORM: netlist check — converter AGND/DGND pins connect to
  the same ground region (analog) with stub length budget; finding if
  DGND is routed to the digital region.
- APPLICABILITY: ADC/DAC/mixed ICs; low-to-moderate resolution.

### OTT-MX4 — Mixed-signal decoupling and supply isolation
- THRESHOLD: digital supply pin of the mixed-signal IC decoupled TO
  ANALOG ground with the cap tied DIRECTLY to the DGND pin (via to
  analog plane at the pin); a ferrite bead or R in the VD feed
  (from either supply). Analog power: linear regulator or R-C/L-C
  filter off digital power; power connector in the DIGITAL partition;
  regulator/filter STRADDLES the partition line.
- WHERE: PDF p.707–708 §17.9, Figs. 17-20/21/22.
- MACHINE FORM: composition template for adc-frontend blocks; placement
  check that analog power filter/regulator centroid sits on the
  declared partition line (same machinery as isolation straddle refs).
- APPLICABILITY: mixed-signal boards fed from one supply (our class).

### OTT-MX5 — Converter digital-side hygiene
- THRESHOLD: each converter digital output feeds ONE load; buffer
  register adjacent to converter isolates the noisy bus; series
  100–500 Ω output resistors reduce transient currents. Sampling clock
  and voltage reference grounded/decoupled to ANALOG ground; if clock
  comes from the digital side, carry it differentially or via
  transformer. Clock jitter, not ground noise, often limits ENOB
  (5 ps rms jitter caps a 1 MHz signal at ~14 bits).
- WHERE: PDF p.702–703 §17.7, Figs. 17-17/18.
- MACHINE FORM: topology block rule for future ADC designs; fanout
  check on converter digital pins (=1).
- APPLICABILITY: sampled systems; informational until we build one.

### OTT-MX6 — The "IPC problem": low-frequency high-current returns
- THRESHOLD: motor/relay/solenoid class currents return by least
  RESISTANCE (not under the trace); give them an explicit return
  TRACE, not the plane, or route so the direct path misses sensitive
  regions; if a split is forced, isolate crossings (opto/transformer)
  and pass everything else over ONE bridge ("chain saw test": a cut
  along the split should sever nothing).
- WHERE: PDF p.709 §17.10, Fig. 17-23; split-plane rules p.693–694.
- MACHINE FORM: net class `hi_current_lo_freq` → router pairs it with a
  dedicated return trace to the supply entry; check that its
  least-resistance path (straight line proxy) avoids analog regions.
- APPLICABILITY: relay/motor/LED-bar drivers at kHz rates — our
  thermometer LED column current is this class.

---

## 9. Connectors, cables, chassis (Ch 12 §12.3–12.4, Ch 16 §16.2, Ch 15 §15.5)

### OTT-IO1 — All connectors in ONE I/O area (why one edge)
- THRESHOLD: all I/O connectors grouped in one board area; a "clean"
  I/O ground region under them carrying ONLY connector backshells and
  cable filter capacitors, tied to chassis at multiple points, joined
  to logic ground at ONE bridge.
- WHY: cables radiate as monopoles driven by the ground-voltage
  difference between their entry points; only a few µA of common-mode
  current on 1 m of cable violates FCC B (Table 12-1: 5 µA @50 MHz,
  3 m) and a few mV of ground noise supplies it. Grouping means all
  cable references sit at the SAME potential, and gives the chassis
  bond and filters one place to live. It takes ~1000× more DM than CM
  current to radiate equally (Eq. 12-9b) — cables, not loops, fail
  first.
- WHERE: PDF p.502–503 §12.3 Table 12-1; p.509–511 §12.4.3 Fig. 12-15;
  p.646 §16.1.1.
- MACHINE FORM: placement check — all off-board connectors within one
  declared I/O zone polygon (single board edge for our class); finding
  when cables exit opposite edges.
- APPLICABILITY: every board with ≥1 external cable. On unshielded
  plastic products the I/O ground region still works (ESD ch.: it
  bypasses cable transients through its capacitance, PDF p.626–627).

### OTT-IO2 — Circuit-ground-to-chassis bond at the cable entry
- THRESHOLD: connect PCB ground to chassis AT the I/O area, as close to
  cable termination as possible, SHORT and MULTIPLE connections
  (parallel standoffs/screws) for low RF impedance. Metal backshells:
  360° bond to chassis (gasket/fingers), never a pigtail — any pigtail
  radiates.
- WHY: the chassis is the return reference for cable common-mode
  current; impedance in this bond becomes the antenna drive voltage.
- WHERE: PDF p.648–649 §16.2, Fig. 16-3; pigtail analysis PDF
  p.506–507 §12.4.2.
- MACHINE FORM: design check — mounting-hole/chassis-tie pads present
  inside the I/O zone, ≥2, with direct pour connection (no thermal
  relief on the chassis ties); metadata field on the board intent for
  chassis vs floating product.
- APPLICABILITY: metal or partially metal enclosures; for fully plastic
  products substitute the I/O ground region (OTT-IO1).

### OTT-IO3 — Filter/protect every cable line at the I/O ground
- THRESHOLD: I/O filter caps (100–1000 pF for ESD band) and/or series
  ferrite/R 50–100 Ω per line; ≥40 dB attenuation in 100–500 MHz for
  ESD. Protection parts' ground currents must flow to I/O/chassis
  ground, NOT through logic ground. Low-frequency I/O (<5–10 MHz):
  signal + companion return trace pair to the connector (return joins
  only at connector). High-frequency I/O (>5–10 MHz, e.g. USB): route
  over the bridge; bridge width = traces + 20h each side (≈0.1 in per
  side at h = 5 mil).
- WHERE: PDF p.510–511 §12.4.3; ESD values PDF p.625–626 §15.5.2.
- MACHINE FORM: composition rule — every net leaving the board passes a
  filter/protection element placed inside the I/O zone; router
  constraint pairing LF I/O with companion returns.
- APPLICABILITY: unshielded cables; shielded cables instead need 360°
  shield-to-chassis termination (never to logic ground — shield tied
  to PCB ground radiates like a plain wire, PDF p.507–508 Fig 12-13E).

---

## 10. Switching converters (Ch 13 §13.2)

### OTT-SW1 — Input filter capacitor ESL sets differential-mode emissions
- THRESHOLD: V_DM = 2·F0·L_F·I_P at the fundamental, flat to 1/(π·tr),
  −20 dB/dec beyond (Eq. 13-6). L_F = ESL + MOUNTING inductance of the
  input ripple capacitor — the ONLY designer-controlled parameter once
  F0 and power are fixed. Example: 4 A, 30 nH, 50 kHz → 12 mV ≈ 26 dB
  over Class B.
- WHY: at emission frequencies the capacitor is "through"; its
  inductance is the source impedance seen by the switching current.
- WHERE: PDF p.528–530 §13.2.2, Eq. 13-6.
- MACHINE FORM: placement/routing check — input cap of a converter:
  minimum-loop mounting (OTT-D5 geometry table); calculator estimates
  V_DM from I_P, F0, ESL for the finding text.
- APPLICABILITY: all switchers; our small buck/boost modules included.

### OTT-SW2 — Switch-node parasitic capacitance sets common-mode
- THRESHOLD: V_CM = 50·π·f·C_P·V(f); C_P (switch node / heatsink /
  chassis parasitic) typically 50–500 pF. High-V/low-I supplies: CM
  dominates; low-V/high-I (ours): DM dominates (criterion
  V_P > L_F·I_P/(50·C_P), Eq. 13-7).
- WHY: dV/dt of the switch node drives displacement current through
  parasitic C to the reference.
- WHERE: PDF p.523–525 §13.2.1, Eq. 13-1; p.530 Eq. 13-7.
- MACHINE FORM: check — minimize switch-node copper area (net-area
  metric on the SW net); keep SW copper away from chassis ties and
  I/O zone.
- APPLICABILITY: switching converters; the SW-node-area rule is the
  encodable part for board layout.

---

## Contradictions / boundary notes for our board class

- Ott caps 2-layer boards at ~10 MHz clocks (exception: 20–25 MHz with
  strong EMC expertise, PDF p.660). Our class allows ≤50 MHz on
  2-layer: encode as a standing advisory finding (not a blocker) when
  clock class > 10 MHz on a 2-layer board — mitigations that must then
  ALL be present: grid per OTT-GR1, guard returns per OTT-C2, series
  damping per OTT-C3, decoupling per OTT-D2/D5.
- The ±20h corridor and 50h analog margin assume plane spacing of
  5–10 mil; on 1.5 mm 2-layer dielectric they become geometrically
  impossible — the book's own alternative for that regime is paired
  return traces (OTT-C2, OTT-L4, OTT-IO3), which is what we encode.
- Ott prefers same-value decap arrays; much app-note lore says
  100 nF + 1 nF pairs. Record: Ott's measured basis (Archambeault
  +25 dB antiresonance) wins for PCBSmith defaults; two-value designs
  need a declared justification.

---

## Top 10 most machine-encodable rules (ranked)

1. **OTT-GR1 ground grid ≤ 12.7 mm cell** — pure geometry over the
   ground copper graph; the single highest-leverage 2-layer check.
2. **OTT-R1 no slots / no trace over slot** — extends the existing
   hole-true obstacle model to return-layer continuity; exact numbers
   (14 dB @1.5 in) for finding text.
3. **OTT-D5 decap loop budget + ≥2 caps/IC** — nH lookup table by
   mounting pattern (2.8→0.4 nH) is directly computable from placement.
4. **OTT-IO1 single I/O zone** — polygon containment test on connector
   placements; encodes the whole cable-radiation mechanism.
5. **OTT-C3 series damping on ≥20 MHz clocks** — netlist pattern check
   with a crisp threshold (33 Ω; R = Z0 − Rdrv when len_in ≥ 3·tr_ns).
6. **OTT-C2 guard return traces for clock class** — router feature +
   post-route check (parallel GND trace both sides, stitched ends).
7. **OTT-D3/D4 decoupling calculator** — Zt = 2·dV/dI, n = 2L/(Zt·tr),
   C ≥ dI·dt/dV; closed-form, evidence-linked to datasheet dI/tr.
8. **OTT-MX1 region routing discipline** — copper-inside-region check
   per net class; reuses the mains-isolation region machinery.
9. **OTT-P1/OTT-C4 zoning distances** — crystal/high-speed ≥13 mm from
   I/O zone; placement-stage pairwise distance checks.
10. **OTT-GR5/OTT-R3 stitching-via rules** — ≥2 vias per critical
    ground transition, ground via adjacent to critical signal vias;
    countable at route time.

---

## Verification (2026-07-12, spot-check, sonnet)

| rule | verdict | note |
|------|---------|------|
| OTT-GR1 (grid ≤12.7mm/0.5in cell) | VERIFIED | PDF p.413–414: Smith & Paul (1991) "grid spacing of 0.5 in. or less"; Table 10-2 German (1985) worst pair IC15-IC16 1000→100 mV; radiated emission 42.9→35.8 dB mV/m = 7.1 dB. All numbers match exactly. |
| OTT-R1 (slot/hole slotting, 14 dB @1.5in) | VERIFIED | PDF p.650–651, Table 16-1: baseline (0 in) 15 mV → 1.5 in slot 75 mV (5×, 14 dB per note text); 1-in array of 15 non-overlapping 0.052-in holes = 15 mV (0% increase). Matches notes exactly, incl. ">20 dB" for slots/splits in general. |
| OTT-D5 (decap mounting-inductance table + ≥2/≥4 caps) | VERIFIED | PDF p.481–482 Fig. 11-25: thin trace 2.8 nH, wide trace 2.1 nH, end via 1.1 nH, side via 0.7 nH, multiple vias 0.5/0.4 nH — matches. PDF p.478–479: two caps → 6 dB (current split) + ~12 dB (loop cancellation) = 18 dB total; book recommends min. 2 caps on a DIP (opposite ends), min. 4 on a quad flat pack (one per side) — matches notes. |
| OTT-IO1 (Table 12-1 common-mode current limit) | VERIFIED (verifier's MISMATCH overturned on adjudication) | The spot-checker read the cache text literally: p0502 prints "100 mV/m" and "5 mA". That is a TEXT-EXTRACTION GLYPH LOSS: pypdf renders the µ glyph as "m" on this page. Proof from the SAME page's Eq. 12-8 (Icm = 0.8·E·r/(f·l), stated to yield MICROamps): FCC B 100 µV/m at 3 m, 50 MHz, 1 m cable → 0.8·100·3/50 = 4.8 ≈ 5 µA; FCC A → 14.4 ≈ 15; MIL-STD-461 16 µV/m at 1 m → 0.256 ≈ 0.25. All three table rows close EXACTLY in µA/µV; in mA the table would put FCC-B failure ~62 dB above the limit, contradicting the book's own µA-vs-mA CM/DM contrast (p.480). Original note value 5 µA stands. |
| OTT-C3 (33 Ω series damping, ≥20 MHz) | VERIFIED | PDF p.648: "series damping resistors... to all clock output traces with a frequency of 20 MHz or more... A typical value resistor would be 33 Ω"; footnote: if trace length (in) ≥ 3× rise time (ns), use R = Z0 − driver output resistance. Matches exactly. |
| OTT-C2 (guard return traces, 20+ dB) | VERIFIED | PDF p.496–497 §12.2.2, Fig. 12-8: single return loop vs. symmetric two-sided return traces — current splits (6 dB), loops cancel (additional, not perfect) → "will therefore radiate 20 + dB less." Matches exactly; also confirms OTT-L4 (one ground return trace per 8 bus bits, adjacent to LSB) on the same p.496. |
| OTT-D3 (Zt = k·dV/dI, k=2, worked example) | VERIFIED | PDF p.468–470 Eq. 11-7/11-8: n = 2L/(Zt·tr); k=2 because "no more than about 50% of the current is contained in the frequencies below the 1/(π·tr) frequency." Worked example: 2 ns rise, 2.5 A, 5% of 5 V → Zt = 200 mΩ; 50 caps @ 10 nH each needed at 159 MHz. All values match exactly. |
| OTT-C4 (13 mm / 0.5in crystal-to-I/O keepout) | VERIFIED | PDF p.646: "keeping these circuits at least 0.5 in. (13 mm) from the I/O area will minimize the parasitic coupling"; same page also gives the 20× layer-to-plane-spacing edge keep-out (OTT-L3) and the Fig. 16-1 zoning diagram (OTT-P1). Matches. |

8/8 verified after adjudication (2026-07-12, fable): the one flagged
mismatch (OTT-IO1) was a false positive caused by µ-glyph loss in the
text cache — dimensional analysis against the page's own equation
confirms the notes' 5 µA. Standing caveat for ALL verifications
against this cache: pypdf drops the µ glyph as "m" on at least some
pages; any µ/m-sensitive threshold must be closed by dimensional
analysis, not by string comparison.
