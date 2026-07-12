# Montrose — PCB Design Techniques for EMC Compliance, 2nd ed. (distilled rules)

Provenance: Mark I. Montrose, *Printed Circuit Board Design Techniques
for EMC Compliance: A Handbook for Designers*, Second Edition, IEEE
Press, 2000. Text cache `.book-cache/montrose-emc/` (340 pages, one
Books24x7 web-rip page per file), sha256
`4bc2b3b3b5c4e8d806e615c35553d741e954dcfed42e2db7fc73b9e4fbfc35ea`
per `.book-cache/manifest.json`. Distilled 2026-07-11. Locators are
"PDF p.N" into the cache plus the book's section number; the rip does
not carry printed page numbers, so section numbers are the stable
reference.

Chapter map (TOC, PDF p.11): 1 Introduction (p.12-30); 2 PCB Basics —
stackups, grounding, image planes, partitioning, critical frequencies
(p.31-76); 3 Bypassing and Decoupling (p.77-109); 4 Clock Circuits,
Trace Routing, and Terminations (p.110-164); 5 Interconnects and I/O
(p.165-185); 6 ESD Protection (p.186-203); 7 Backplanes, Ribbon
Cables, Daughter Cards (p.204-223); 8 Additional Design Techniques —
localized planes, 20-H, corners, ferrites, heatsinks, creepage,
trace current (p.224-254); Appendix A Summary of Design Techniques
(p.255-281). Ch.1 (regulatory overview) and Ch.8 §8.4/8.5/8.7/8.10
(ferrite selection, heatsinks, BNC, film/QA) were read but yield no
machine-encodable PCB-geometry rules; they are summarized only where
a threshold exists.

The book's own hedge, repeated throughout: every technique is
"application dependent" — the preface states techniques must be
justified for when they are and are not appropriate. Rules below
record the applicability limits the book itself attaches.

---

## 1. Trace separation and crosstalk

### 1.1 The 3-W rule (primary spacing rule)

- THRESHOLD: separation between traces >= 3x the width of a single
  trace, **centerline to centerline** (equivalently edge-to-edge
  > 2x trace width). Example given: 6-mil clock trace -> nothing
  within 12 mils edge-to-edge. 3-W represents the "approximate 70%
  flux boundary at logic current levels"; for ~98% boundary use
  **10-W**.
- WHY: the magnetic-flux/current-density distribution around a trace
  falls off with distance; the local field extends ~1 trace width
  each side (see 1.4), and 3-W keeps an adjacent victim outside the
  bulk of the flux so inductive/capacitive coupling is minimized.
- WHERE: PDF p.150-151, sect. 4.11; flux-boundary percentages
  PDF p.150; also PDF p.229 (sect. 8.2) restates "signal currents
  between 3-W and about 10-W" channel width.
- MACHINE FORM: router net-class spacing constraint
  `spacing >= 2*W_edge` (3W centerline) for nets tagged critical;
  virtual check `three_w_spacing` over critical-net copper vs all
  other copper on the same layer.
- APPLICABILITY: **mandatory only for "high-threat" nets** — clock,
  periodic signals, differential pairs, video, audio, reset, and
  other system-critical nets (PDF p.150-151). Not all traces need
  it. Book's own let-out: if the reference plane is physically
  closer to the trace than the trace-to-trace spacing, the plane
  captures the flux and "enhances performance over that of the 3-W
  rule" (PDF p.150) — i.e. thin dielectrics relax the rule.

### 1.2 3-W applies to vias and breakout pins too

- THRESHOLD: distance from a critical trace to a **via barrel**
  (including its anti-pad/clearance) and to a component **breakout
  (pin-escape) trace** must also satisfy 3-W.
- WHY: "flux loss into the annular keep-out region of vias" couples
  RF energy into whatever net the via carries (a static net like
  reset can then re-propagate RF board-wide).
- WHERE: PDF p.142, sect. 4.9 item 3; PDF p.151, sect. 4.11.
- MACHINE FORM: extend the 3-W spacing check's obstacle set to via
  pads/annuli and foreign pin-escape stubs, not just parallel traces.
- APPLICABILITY: same critical-net scope as 1.1.

### 1.3 Differential-pair spacing: 1-W inside, 3-W outside

- THRESHOLD: distance between the two traces of a differential pair
  = **1-W** (as close as manufacturable, held constant); distance
  from either member of the pair to any unrelated trace = **3-W**.
  Do not place vias or connector pins *between* the pair members.
- WHY: pair members are complementary so mutual coupling is benign
  (and sets Zdiff); foreign single-ended signals or power noise
  coupling into one member unbalances the pair and converts to
  common mode.
- WHERE: PDF p.151, sect. 4.11 (Fig. 4.22); no-vias-between-pairs
  PDF p.263 (App. A ch.4 item 7); constant gap D "minimal spacing
  possible during manufacturing" PDF p.118, sect. 4.2.5.
- MACHINE FORM: pair-aware net class: `intra_pair_gap == const`,
  `extern_clearance >= 2*W` edge-to-edge; obstacle check that no via
  or pad sits inside the pair corridor.
- APPLICABILITY: book states no frequency limit for the spacing
  rule itself; length-match tolerance is frequency-limited (see 1.5).

### 1.4 Field-distribution constants behind the rules

- THRESHOLD: RF current spreading in a reference plane extends about
  **one trace width** to each side of the trace ("if a trace is
  0.008 in wide, flux coupling to an adjacent trace will occur if
  the adjacent trace is <= 0.008 in away"); the RF field around a
  trace is "approximately 1-W" distant. Crosstalk ratio (Eq. 4.24)
  scales as ~K/(1+(D/H)^2): minimize height H above the return
  plane, maximize centerline distance D. For embedded microstrip
  traces at different heights the H^2 term becomes the product of
  the two heights (Eq. 4.25); for stripline H is the parallel
  combination of distances to the two planes (Eq. 4.26). Crosstalk
  falls off "as the square of distance"; doubling distance cuts
  crosstalk to one-fourth.
- WHY: current-density distribution under a trace peaks directly
  beneath it and falls off sharply (Eq. 2.4).
- WHERE: PDF p.55-56, sect. 2.8; PDF p.149, sect. 4.10.2 (Eqs.
  4.24-4.26); square-law falloff PDF p.119, sect. 4.2.5 item 4.
- MACHINE FORM: quantitative crosstalk estimator
  `xtalk = 1/(1+(D/H)^2)` per parallel-run segment pair, thresholded
  per net-class mix (book: 5% coupling OK TTL->TTL, not TTL->
  LVDS/ECL/PCI — PDF p.148); usable as a smarter alternative to
  blanket 3-W on non-critical nets.
- APPLICABILITY: parallel-routed segments; K depends on rise time
  and parallel length (K <= 1, "value of one generally used" for
  approximation, PDF p.149).

### 1.5 Differential pair length matching

- THRESHOLD: length match need not be better than **0.500 in
  (1.27 cm)** for signals below 1 GHz (velocity 140 ps/in microstrip,
  176 ps/in stripline). For LVDS at 250 ps edges, match to within
  **1.5 in (3.8 cm) "or less"** [sic — book's own number; note it is
  *looser* than the general rule, flagged in section 10]. Pair
  members must be routed on the same layer type (both microstrip or
  both stripline), never mixed.
- WHY: skew budget is set by propagation velocity; microstrip and
  stripline propagate at different speeds so mixing layers skews
  the pair even at matched length.
- WHERE: PDF p.139-140, sect. 4.8.2; same-topology requirement
  PDF p.162, sect. 4.13.7.
- MACHINE FORM: `diff_pair_skew <= 12.7 mm` routed-length check;
  layer-type-consistency check per pair.
- APPLICABILITY: below 1 GHz; faster protocols need tighter analysis.

### 1.6 Parallelism / overlap discipline

- THRESHOLD: no quantitative limit; qualitative — minimize parallel
  routed lengths, avoid trace-over-trace overlap on adjacent layers
  ("overlapping parallelism should be avoided at all times"), route
  adjacent routing layers orthogonally (one layer x-axis, other
  y-axis), and isolate same-axis routing layers with a plane.
- WHY: broadside (over/under) capacitive coupling is stronger per
  unit length than edge coupling; orthogonal crossings minimize
  the overlap area.
- WHERE: PDF p.146-148, sect. 4.10.1-4.10.2 (12-item prevention
  list); dual-stripline orthogonality note PDF p.118, sect. 4.2.5;
  backplane "never route two signal planes adjacent to each other"
  PDF p.209, sect. 7.4.
- MACHINE FORM: `parallel_run_length` accumulator per net pair
  (same layer and adjacent-layer overlap), thresholded by the 1.4
  estimator; stackup lint: no two adjacent routing layers with the
  same preferred axis unless separated by a plane.
- APPLICABILITY: book states no limit; emphasis on clock/periodic
  aggressors and reset/analog/video/audio victims.

### 1.7 Guard and shunt traces

- THRESHOLD: a guard trace works only if it is **closer to the
  signal trace than the reference plane is** (worked example: with
  H = 8 mil plane spacing and 10 mil trace gap the guard is useless;
  with H = 20 mil it works). Guard-to-signal gap: smallest
  manufacturable, held for the whole route, nothing ever routed
  between signal and guard. Ground the guard at both ends at the
  source/destination components plus vias along the route (App. A:
  at **irregular** intervals, to avoid building a tuned resonator).
  A shunt trace (over/under the signal on an adjacent layer) must be
  **>= 3x the signal trace width** and via-stitched; no voids from
  vias. Two different signals must not share one guard channel
  (differential pairs excepted).
- WHY: the guard/shunt is an alternate RF return path; flux couples
  to whichever conductor is closest. On multilayer boards the plane
  is closer, so "for many applications, implementing guard traces in
  a stripline topology is a waste of time" — the 3-W rule gives the
  same benefit with less real estate.
- WHERE: PDF p.152-155, sect. 4.12; irregular-interval grounding
  PDF p.267 (App. A ch.4 item 37); guard around every clock on
  boards without planes PDF p.267.
- MACHINE FORM: for 1-2 layer boards: router directive
  `guard_trace(net, gap=min_mfg)` with end + interval via stitching;
  design check that guard is closer than any return plane before
  emitting one (else warn "use 3-W instead").
- APPLICABILITY: guard traces primarily for single/double-sided
  boards (no planes); shunt traces only in 6+ layer boards; on
  multilayer stripline prefer 3-W.

### 1.8 Trace corners (90 degrees vs 45 degrees) — myth measured

- THRESHOLD: a 90-degree corner adds ~**0.014 pF** parasitic
  capacitance (65-ohm, 7-mil trace, er 4.3), drops local impedance
  **15-20% for ~15 ps per corner** (App. A restates as ~10% for
  17 ps); measured radiated-emissions difference of corner shapes
  is **+2 to 5 dB** max, within +/-4% instrument uncertainty, and
  only appears >= ~700 MHz. Signal-integrity effect only matters for
  edge rates faster than **~50 ps** (Eq. 8.3 formal limit 100 ps;
  App. A: "signals that exceed 33 GHz"). A 45-degree chamfer removes
  up to **57%** of the corner capacitance. Conclusion: right-angle
  corners are NOT an EMI or SI problem for sub-GHz digital.
- WHY (for still avoiding 90 deg): **manufacturing** — etchant
  attacks corners first; a 5-mil trace can finish at 3 mils at the
  corner (current fusing risk under load, delamination risk). Keep
  the CAD 90-degree prevention on; convert any 90s to 45s at
  cleanup.
- WHERE: PDF p.232-235, sect. 8.3 (8.3.1 time domain, 8.3.2
  frequency domain, 8.3.3 summary + manufacturing rationale);
  App. A restatement PDF p.278-279.
- MACHINE FORM: PCBSmith already emits 45-degree routing (rule 11
  craft pipeline); keep it, but justified as manufacturing/etch
  craft — do NOT cite EMI as the reason. A `no_90deg_corner` check
  is cosmetic below GHz; the existing `trace_corner_angle` check
  (no acute joints) is stricter than the book requires.
- APPLICABILITY: EMI/SI indifference holds below ~1 GHz / edges
  slower than ~50 ps; microwave designs use rounded corners anyway.
  Numbers between ch.8 body and App. A disagree slightly (recorded
  in section 10).

### 1.9 Backplane / parallel-bus specifics

- THRESHOLD: ideal pinout 1 ground pin per signal pin; acceptable
  fallback 1 ground per 2 signals; if only ONE return is possible,
  put it in the **middle** of the connector with the most aggressive
  signals adjacent. A clock pin must have an adjacent RF return
  **on all sides** in the connector. Max separation of any signal
  pin from its power/ground pin in a connector: **0.5 in (1.27 cm)**.
  Crosstalk/radiating-loop behavior persists down to assemblies as
  small as 1 in end-to-end. Connector clearance holes must not
  overlap into a continuous "ground slot"; added inductance depends
  only on slot length perpendicular to the trace, not slot width
  (Eq. 7.1); traces must not route across overlapping through-hole
  slots.
- WHY: a lone end-of-connector return creates a large inductive
  loop for far-side signals (efficient radiator + crosstalk);
  slots force return currents around the connector, adding
  inductance and common-impedance coupling.
- WHERE: PDF p.206, sect. 7.2 (Fig. 7.1); PDF p.214, sect. 7.6
  (0.5 in); PDF p.217-218, sect. 7.9 (Fig. 7.4, 1-in floor);
  PDF p.221-222, sect. 7.11 (ground slots, Eq. 7.1).
- MACHINE FORM: connector pin-assignment check: every net tagged
  clock/high-threat has a ground pin adjacent on all sides; ratio
  check grounds:signals >= 1:2; `ground_slot` check — no two
  clearance holes of a connector row overlapping in any plane layer,
  and no trace routed through the slot region (PCBSmith's hole-true
  obstacle model already half-covers this).
- APPLICABILITY: interconnects (connectors, ribbon, backplane);
  the 1:1 ideal is acknowledged as often infeasible ("tradeoff").

### 1.10 T-stubs / bifurcated traces

- THRESHOLD: not permitted at all on clock/periodic/high-threat
  nets. On other nets, max stub length **1 in** (ch.7) or, formally,
  stub cannot exceed the tr-derived length limit (sect. 4.8.1),
  and both legs of a T must be **exactly** identical in length and
  loading (serpentine the shorter leg to match). Each leg of a
  bifurcation has characteristic impedance 2*Zo.
- WHY: two reflected waves return to the T junction with amplitude/
  phase difference and corrupt the signal back to the source; also
  a maintainability trap (future editors don't know the legs are
  matched).
- WHERE: PDF p.138-139, sect. 4.8.1; PDF p.215, sect. 7.7 (1-in
  limit, "stub no longer than the physical size of the device").
- MACHINE FORM: netlist topology check `no_tstub(critical_nets)`;
  for permitted stubs, `stub_length <= 25.4 mm` and leg-length
  equality check.
- APPLICABILITY: all speeds for clocks; 1-in relaxation only for
  non-periodic signals, scaled by edge rate.

---

## 2. Electrically long traces, termination

### 2.1 When a trace is "electrically long" (termination trigger)

- THRESHOLD: terminate when the round-trip propagation delay
  exceeds the signal edge rate: condition `2 * t'pd * length > tr`
  (use the FASTER of rise/fall; t'pd = loaded propagation delay).
  Closed form for er = 4.6: `lmax_roundtrip = 9 * tr` cm microstrip,
  `7 * tr` cm stripline (tr in ns; one-way length = half that;
  inch constants 3.49 and 2.75). Frequency-domain equivalent: a
  trace is electrically long beyond **lambda/10** of the highest
  frequency in the trace (PDF p.35). Sect. 4.13 restates the
  trigger as length exceeding **1/6 the electrical length of the
  edge** — i.e. the book itself uses both /2-liberal and stricter
  variants; it recommends replacing the 2 in the denominator with
  4-8 for conservatism. Safety-margin practice: use
  `3 * t'pd * length` vs tr. Termination may be needed even on
  short traces if the load is strongly capacitive or inductive.
- WHY: a second edge launched before the first round trip returns
  produces reflections/ringing (SI) which are re-radiated (EMI).
- WHY (numbers): FR-4 velocity ~60% of c; unloaded tpd 1.68 ns/ft
  microstrip, 2.11 ns/ft stripline/embedded (Table 4.1, er 4.3).
- WHERE: PDF p.132-134, sect. 4.7 (Eqs. 4.20-4.23, worked
  examples PDF p.134-137); lambda/10 PDF p.35, sect. 2.2; 1/6-edge
  PDF p.156, sect. 4.13; capacitive-load caveat PDF p.156.
- MACHINE FORM: calculator + design check: per net,
  `needs_termination = routed_len > k * tr_min / 2` with k from
  topology; require a termination component in the net when true.
  Loaded delay via Eq. 4.16: `t'pd = tpd * sqrt(1 + Cd/Co)`
  (Cd = sum of input capacitances per unit length; Co = intrinsic
  trace capacitance/length).
- APPLICABILITY: any periodic or edge-sensitive net; use minimum
  (not typical) edge rate — estimate `tr_min = 0.6 * tr_typ`,
  `tr_max = 1.2 * tr_typ` when unspecified (PDF p.75, sect. 2.16.1).

### 2.2 Loading constants for the calculator

- THRESHOLD: input capacitance ~5 pF ECL, ~10 pF CMOS, 10-15 pF
  TTL; trace intrinsic capacitance 2-2.5 pF/in; sockets ~2 pF each;
  vias **0.3-0.8 pF and 1-3 nH each** (ch.7 App. A: "1-3 nH and
  2 pF"); PCB trace inductance 12-20 nH/in; loaded impedance
  `Z'o = Zo / sqrt(1 + Cd/Co)` (50-ohm line with 50 pF load drops
  to 32 ohms).
- WHY: capacitive loading lowers Zo and raises delay; the driver
  must source more current at lower Z (V=IZ), raising RF energy.
- WHERE: PDF p.125-127, sect. 4.4 (Eqs. 4.16-4.19); via/socket
  values PDF p.126 and p.128, p.215; 12-20 nH/in PDF p.58,
  sect. 2.9.2.
- MACHINE FORM: constants table in `calculators/electronics.py`
  for a transmission-line/termination calculator.
- APPLICABILITY: below ~1 GHz rules-of-thumb; consult board vendor
  for controlled-impedance accuracy (tolerances +/-5-10%).

### 2.3 Termination methods (Table 4.2 condensed)

- THRESHOLD / forms:
  - **Series**: Rs = Zo - Ro (driver output R); typical 15-75 ohm,
    33 common. Resistor DIRECTLY at driver pin, **no via between
    driver and resistor** (via goes after the resistor). Best for
    lumped single load at end of route.
  - **Parallel**: R = Zo at the far end to ground; high DC power
    (5V/55ohm = 91 mA logic-HI); "rarely used in TTL/CMOS".
  - **Thevenin**: R1 (to V) and R2 (to gnd), parallel combination
    = Zo; common 220/330 (132 ohm eff.); pick ratio to bias toward
    the logic family's drive asymmetry; never exceed IOLmax/IOHmax.
  - **AC/RC**: R = Zo plus C = 20-600 pF in series at the far end;
    time constant RC > 2x round-trip delay (commonly 3x); use for
    **clocks only, never data/address** (adds delay per pattern).
  - **Diode (Schottky)**: clamps overshoot, does not absorb
    reflections; diode switching >= 4x faster than signal rise;
    good when line Z is undefined (backplanes); clamp currents can
    inject into planes.
  - **Differential**: line-to-line R (LVDS: 100 ohm single
    resistor); resistor-array (3R) when common-mode termination is
    also required.
  - End termination must be at the **very end** of the route; the
    terminator is the LAST item on the bus, driver the first.
- WHY: absorb reflections at source (series, early) or load (end,
  late); wrong placement leaves an unterminated stub.
- WHERE: PDF p.156-163, sect. 4.13.1-4.13.7 (Table 4.2, Table 4.3);
  series-at-driver-no-via PDF p.141, sect. 4.9.1; last-on-bus
  PDF p.216, sect. 7.8.
- MACHINE FORM: composition-level check: nets flagged
  `needs_termination` must contain a termination block of an
  allowed type; placement check `series_R_adjacent_to_driver`
  (distance driver-pad -> resistor-pad below a few mm, no via on
  that segment); `terminator_is_last_load` order check along the
  routed tree.
- APPLICABILITY: logic-family-dependent resistor values; AC type
  restricted to clocks.

### 2.4 Routing topology for multi-load clocks

- THRESHOLD: radial point-to-point routing (one driver leg per
  load, each leg terminated) instead of daisy-chains, unless loads
  are clustered at the end of the line. Clock traces must be
  terminated even when short enough to be tempting to leave open.
- WHY: daisy-chain intermediate loads see reflections from every
  downstream discontinuity; an unterminated line "energizes a
  dipole antenna" (trace = driven element, plane = ground element).
- WHERE: PDF p.138, sect. 4.8.1 (Fig. 4.10); dipole framing
  PDF p.128, sect. 4.5; daisy-chain exception PDF p.215, sect. 7.7.
- MACHINE FORM: topology check on clock nets: tree must be a star
  from driver (or chain with all loads within the lmax cluster
  window); each leg carries its own termination.
- APPLICABILITY: fast-edge nets with a single driver and multiple
  loads.

---

## 3. Routing layers, layer jumps, return paths

### 3.1 Layer discipline for clocks / high-threat nets

- THRESHOLD: route clocks on ONE routing layer (x and y in the same
  plane) as the initial approach; if that fails, keep every segment
  adjacent to the same reference plane. Do not route clocks
  microstrip (outer layers) on a multilayer board — route them
  stripline. Prefer routing against a **ground (0V) plane** rather
  than a power plane. Manual-route clocks FIRST, before autoroute.
- WHY: outer layers radiate; power planes carry switching noise and
  cancel flux less well than 0V planes (asymmetric pull-up/down
  currents); the first-routed traces get the freedom to jump layers
  at component ground pins.
- WHERE: PDF p.141-143, sect. 4.9.1; ground-plane preference
  PDF p.42 sect. 2.5 and PDF p.64-65 sect. 2.12; manual-route-first
  PDF p.144, sect. 4.9.2; stripline for high-threat in backplanes
  PDF p.210, sect. 7.4.
- MACHINE FORM: net-class router constraint `layers=[stripline]`
  and `single_layer_preferred` for clock class; design check that
  clock-class copper is adjacent to a 0V plane everywhere.
- APPLICABILITY: multilayer boards; on 2-layer boards see section 5.

### 3.2 Ground vias at every layer jump

- THRESHOLD: if a high-threat trace must jump between routing
  layers, place a **ground via at each and every jump location**
  (two per signal-via transition gives a continuous return); a
  component's ground pin via can serve as the ground via (jump the
  trace at a pin escape, sharing the pin's ground via). Where the
  jump moves the trace from a ground reference to a POWER
  reference (4-layer boards), run a parallel **ground trace** on
  the power-adjacent layer, via'd to the ground plane at both ends,
  as close to the signal as manufacturable. Signal layer changes
  should happen at a component lead (pin escape), not mid-route.
- WHY: return current cannot follow the signal through the board
  unless a same-potential path exists at the jump; between
  different-potential planes it can only cross where decoupling
  capacitors sit; the interrupted return becomes a loop antenna
  (this is EMI phenomenon #1 of 3 listed).
- WHERE: PDF p.143-144, sect. 4.9.2 (ground-via technique credited
  to W. Michael King; Figs. 4.15, 4.16); jump-at-pin-escape
  PDF p.128 sect. 4.5 and p.134 sect. 4.7; three-phenomena list
  PDF p.142, sect. 4.9.1.
- MACHINE FORM: post-route check: for every via on a critical net,
  a same-net-side ground via (or component ground pad via) within
  a small radius; router hook to co-place a stitching via when a
  critical net changes layers.
- APPLICABILITY: boards with >= 2 ground planes for the pure
  ground-via form; the ground-trace fallback for 4-layer
  power+ground stackups.

### 3.3 Image plane integrity

- THRESHOLD: reference planes must be SOLID under routed signals:
  no traces routed inside a plane layer (a +12V trace inside a +5V
  plane fragments it); no three adjacent routing layers (middle one
  has no image); every routing layer adjacent to a plane. Vias in a
  plane are harmless unless clearance holes overlap into
  **continuous slots** (Swiss-cheese / oversized through-holes).
  Traces routed between through-hole pin fields need **>= 3x trace
  width** spacing from the hole edge. A trace forced across a slot
  or moat gets a bypass capacitor across the discontinuity
  immediately adjacent (up to 20 dB improvement observed) — but the
  book's stance is that needing one means the return path should
  have been continuous in the first place.
- WHY: RF return mirrors the trace in the plane; any break makes
  return current detour = loop area = differential->common-mode
  conversion.
- WHERE: PDF p.64-66, sect. 2.12 (traces-in-plane violation,
  3-routing-layer ban); PDF p.68-69, sect. 2.13 (slots, 3x width,
  moat-crossing capacitor); backplane restatement PDF p.221,
  sect. 7.11.
- MACHINE FORM: plane-layer lint (no signal copper in plane
  layers); stackup lint (routing layer adjacency); hole-overlap /
  slot detector on plane layers (PCBSmith's hole-true obstacle
  model extended to plane connectivity); `trace_across_split`
  check (already standard practice in virtual DRC when pours land).
- APPLICABILITY: all multilayer boards; slot concern strongest for
  connectors/through-hole rows.

---

## 4. Component placement

### 4.1 Clock / oscillator placement

- THRESHOLD: clock circuits near the board CENTER and/or adjacent
  to a chassis ground stitch, NOT along the perimeter or near I/O.
  Oscillators/crystals soldered directly — **never socketed**.
  Oscillator + all clock support circuitry (buffers, drivers, load
  Rs) grouped over a single **localized plane** on the outer layer,
  tied to the main plane by the component ground pins PLUS at
  least 2 extra vias, 360-degree connection to a ground stitch (no
  thermal-relief wagon wheels), no soldermask over the stitch.
  **No foreign traces under the oscillator or through the clock
  zone** — the localized plane area is a route keep-out; on the
  embedded-microstrip layer under it, likewise; on 2- or 4-layer
  boards a trace that must cross the zone goes on the far (solder)
  side only. Never near the oscillator's output pin. Provision for
  a Faraday shield / ground-via ring around the zone.
- WHY: oscillator packages (especially plastic SMT) radiate
  common-mode RF the single ground pin cannot sink; the localized
  plane images the flux; traces through the zone pick up the clock
  by crosstalk ("route a reset line under an oscillator and the
  product keeps resetting").
- WHERE: PDF p.128, sect. 4.5; PDF p.224-226, sect. 8.1 (localized
  plane, keep-outs, via counts, soldermask note); App. A
  PDF p.264 and p.278.
- MACHINE FORM: placement rule: `clock_zone` region derived from
  oscillator + buffer placements; checks: zone contains only
  clock-class parts, no foreign traces intersect zone (per layer
  class), oscillator not within X of board edge or I/O zone,
  localized pour present with >= 2 stitching vias, no soldermask
  over stitch pad.
- APPLICABILITY: any board with periodic generators; localized
  plane technique is for outer-layer (microstrip) mounting.

### 4.2 Clock proximity to I/O

- THRESHOLD: periodic circuitry within **2 in (5 cm)** of I/O
  components/connectors only if its edges are slower than **10 ns**;
  within **3 in (7.6 cm)** use 5-10 ns edges. Waived when the I/O
  area is properly partitioned (moat/bridge, sect. 5.x of book).
- WHY: RF from clocks couples onto I/O cables which radiate as
  antennas; slow-edge logic near I/O bounds the spectral content.
- WHERE: PDF p.129, sect. 4.5; App. A PDF p.264 item 18.
- MACHINE FORM: placement check: distance(clock-class part, io-zone)
  >= 50 mm unless part's tr >= 10 ns, >= 76 mm unless tr >= 5 ns,
  suppressed when the board declares an I/O partition.
- APPLICABILITY: explicitly waived under functional partitioning.

### 4.3 Functional partitioning / zones

- THRESHOLD: group by bandwidth: high (CPU/clock), medium, low
  (I/O), analog, each a contiguous zone; I/O drivers/logic as close
  to their connector as possible; every I/O port isolated from
  digital planes; slow I/O ports bypassed with **470-1000 pF** caps
  at the connector. Products with clocks above **50 MHz** generally
  require frequent chassis ground stitches; "at least four ground
  points surround each section". Radial migration: bandwidth
  decreases stage-by-stage from CPU zone out to I/O.
- WHY: keeps each zone's spectral energy inside the zone; the I/O
  cable is the final antenna and must see only low-bandwidth
  signals.
- WHERE: PDF p.70-71, sect. 2.14 (Fig. 2.35-2.36); PDF p.51,
  sect. 2.6 (radial migration); PDF p.165-166, sect. 5.0-5.1;
  bypass values PDF p.166, sect. 5.1.2.
- MACHINE FORM: PCBSmith intent-level `zones` dict (already the
  thermometer lesson: register in its load zone); checks:
  component-zone membership, I/O logic-to-connector distance,
  inter-zone net crossings only via declared interfaces.
- APPLICABILITY: all boards; scale of enforcement grows with clock
  frequency.

### 4.4 Analog/digital moat and bridge

- THRESHOLD: moat = absence of copper on ALL layers, **>= 0.010 in
  (0.25 mm)** wide; analog and digital grounds tied at ONE point
  only (the bridge); the analog-interface component (ADC/DAC/codec)
  sits **exactly in the middle of the bridge**; NO signal crosses
  the moat anywhere except through the bridge, routed on a layer
  adjacent to the bridge copper; analog power crosses via a ferrite
  bead (+ regulator if needed); power+ground crossing traces routed
  adjacent to each other; ground both ends of the bridge to chassis
  when multipoint-grounded. AGND/DGND moating only when the device
  itself isolates them internally (RAMDAC rule: internally-tied
  parts get a solid common plane and NO ground bead). Unused power
  plane in an isolated area may be redefined as a second ground
  plane, via-stitched. Between a data-line filter and its I/O
  connector: REMOVE all copper (no plane), so filtered lines cannot
  re-couple to unfiltered energy.
- WHY: a second ground connection anywhere else circulates digital
  return current through the analog zone; component-internal
  AGND/DGND ties short the moat invisibly.
- WHERE: PDF p.168-171, sect. 5.2 (moating steps 1-8, Methods 1
  and 2); RAMDAC note PDF p.181, sect. 5.5; copper removal after
  DLF PDF p.170, sect. 5.2.1; audio 3-zone variant PDF p.183-184,
  sect. 5.6; App. A PDF p.269-271.
- MACHINE FORM: PCBSmith mains-isolation machinery (rulebook sect.
  10 barrier declaration) generalizes: declare moat polygon,
  bridge segment, allowed-crossing nets; checks: copper absence in
  moat >= 0.25 mm on all layers, single bridge, no non-listed net
  crossing, bridging part centered on bridge.
- APPLICABILITY: mixed-signal (book's example threshold: A/D
  converters faster than 20 MHz / more than 8 bits); NOT for parts
  with internally common grounds.

### 4.5 I/O filters and connector treatment

- THRESHOLD: filter components located **exactly at the connector
  entry point — "one inch (2.54 cm) may be too far away"**; order
  from controller: transformer/wave-shaper -> data-line filter ->
  connector. Bypass-capacitor placement has two techniques:
  (1) 100 pF at the connector pins (emissions + immunity; bigger
  values round data edges too much); (2) capacitor on the
  controller side of the data-line filter (protects 25V SMT caps
  from ESD). Metal connector shells bonded 360 degrees to chassis,
  never by pigtail (pigtail vs 360 = **40-50 dB** worse,
  15-200 MHz). Inductors alone are NOT filters (ferrite absorbers
  are); ferrites effective only above ~10 MHz.
- WHY: any trace length after the filter re-couples noise onto the
  filtered line; the cable is the antenna.
- WHERE: PDF p.173-175, sect. 5.3.1 (Fig. 5.6 techniques 1/2);
  pigtail numbers PDF p.245, sect. 8.7; ferrite band PDF p.173.
- MACHINE FORM: placement check `filter_adjacent_to_connector`
  (distance filter-pad -> connector-pad below ~5 mm, no other
  component between); netlist order check controller->filter->
  connector.
- APPLICABILITY: every I/O trace "with exceptions permitted" (fiber
  optic, some LAN/telecom protocols that forbid filtering).

---

## 5. Grounding topologies and 1-2 layer boards

### 5.1 Single-point vs multipoint

- THRESHOLD: single-point grounding for low frequency — sect. 2.9.1
  says best "1 MHz or less"; Appendix A tightens to "clocks
  **100 kHz and slower**", multipoint above 100 kHz (both recorded;
  see section 10). Multipoint ground stitch spacing: straight-line
  distance between chassis ground connections must not exceed
  **lambda/20 of the highest frequency OR HARMONIC of concern**
  (not the fundamental). Worked example: 64 MHz -> lambda/20 =
  9.2 in (23.4 cm) max spacing. At every chassis stitch, bypass
  pairs 0.1 uF || 0.001 uF remove plane eddy currents.
- WHY: an efficient dipole exists down to lambda/20 of the highest
  harmonic; ground conductors longer than that between stitches
  radiate; below ~1 MHz the loop-current cost of multipoint
  outweighs its impedance benefit.
- WHERE: PDF p.57-59, sect. 2.9.1-2.9.2; lambda/20 aspect-ratio
  rule PDF p.61-62, sect. 2.11; App. A PDF p.258 items 17-22;
  stitch bypass pair PDF p.59.
- MACHINE FORM: design check `ground_stitch_aspect_ratio`: max
  pairwise gap between declared chassis-stitch points (x and y)
  <= lambda/20 of declared highest harmonic (default = 10th
  harmonic of fastest clock, or 1/(pi*tr_min)).
- APPLICABILITY: products with chassis metal; plastic-enclosure
  single-point designs exempt (and then ESD guard band must NOT
  tie to ground — see 5.5).

### 5.2 Critical-frequency table (lambda/20 quick values)

- THRESHOLD (Table 2.3): 10 MHz -> 1.5 m; 27 MHz -> 0.56 m;
  35 MHz -> 0.43 m; 50 MHz -> 0.3 m; 80 MHz -> 0.19 m; 100 MHz ->
  0.15 m; 160 MHz -> 9.4 cm; 200 MHz -> 7.5 cm; 400 MHz ->
  3.75 cm; 600 MHz -> 2.5 cm; 1000 MHz -> 1.5 cm. lambda = 300/f
  (m, MHz).
- WHY: dimensions >= lambda/20 of any present harmonic act as
  efficient antennas ("critical frequency" definition used
  throughout the book).
- WHERE: PDF p.72, sect. 2.15 (Table 2.3, Eq. 2.5).
- MACHINE FORM: shared helper `critical_length(f) = 15/f_MHz` m,
  used by stitch spacing, fence spacing, 20-H applicability,
  guard-band via pitch.
- APPLICABILITY: universal geometry/frequency relation.

### 5.3 Spectral content of logic (what "highest frequency" means)

- THRESHOLD: principal harmonic content f = 1/(pi * tr); EMI
  observed out to the ~10th harmonic (Table 2.4: e.g. 74HC 13-15 ns
  -> 24 MHz -> 240 MHz; 74F 1.5 ns -> 212 MHz -> 2.1 GHz; LVDS
  0.3 ns -> 1.1 GHz -> 11 GHz). Edge rate, not clock frequency, is
  the driver: a 5-MHz oscillator into a 74F04 (1 ns) makes more RF
  than 50 MHz into a 74ALS04 (4 ns). Min/max edge estimate when
  unpublished: 0.6x / 1.2x typical. Use the slowest logic family
  that meets timing; devices with tr > 5 ns rarely need these
  techniques at all.
- WHY: Fourier content of the edge sets the radiated spectrum;
  datasheets publish max (slow) edges, not the min (fast) edges
  that cause EMI.
- WHERE: PDF p.73-75, sect. 2.16 (Table 2.4, rule-of-thumb);
  slowest-family directive PDF p.74, sect. 2.16.1.
- MACHINE FORM: component-card field `tr_min_ns` (evidence-backed
  or `assumption`); pipeline derives f_highest = 10/(pi*tr_min)
  for all frequency-scaled checks.
- APPLICABILITY: digital logic generally.

### 5.4 Single- and double-sided board rules

- THRESHOLD / directives:
  - Single-sided: reserve for circuits below "a few hundred kHz";
    build power/ground trace structure FIRST, then clocks adjacent
    to ground traces, then everything else; radial power routing
    from the supply, never tie separate radial branches together
    (loop); power and ground traces parallel/adjacent, separated
    more than one trace width only at decoupling-cap connections.
  - Double-sided (grid style): power and ground gridded, total
    loop area of each grid square **<= 1.5 sq in** (book prints
    "3.8 sq cm" — unit error, 1.5 in^2 = 9.7 cm^2; see section 10);
    power traces on one layer at 90 degrees to ground traces on the
    other; decoupling caps between power and ground **at all
    connectors and at each and every IC**; grid ties in as many
    places as possible; ground fill as alternate return, stitched
    to 0V at many points.
  - Double-sided (modern style): treat as TWO single-sided boards;
    the opposite-side plane is NOT a usable RF return — at 1.6 mm
    thickness the plane is many trace-widths away, so "any RF
    return path greater than one trace width away is too far";
    return/guard trace routed parallel and immediately adjacent to
    every high-threat signal; signal routed as close to a ground
    trace as possible (ESD chapter repeats: signals close to
    ground, never near board edge).
  - Four-layer: both configurations (S-G-P-S or planes outside)
    still have trace-to-plane spacing "excessively large" for
    optimal cancellation — better than 2-layer, worse than 6+.
- WHY: without planes, loop area control is everything: flux
  cancellation only happens if the return conductor is within
  ~1 trace width.
- WHERE: PDF p.42-44, sect. 2.5.1-2.5.3 (Figs. 2.6-2.10); ESD
  restatement PDF p.195, sect. 6.4.1 (Fig. 6.4) and p.199 (Fig.
  6.6); "no such thing as a double-sided PCB" PDF p.44.
- MACHINE FORM: for PCBSmith 2-layer boards: `ground_grid` check
  (max enclosed cell area of the power/ground mesh <= 1.5 in^2 =
  967 mm^2); `return_adjacent` check for clock-class nets: parallel
  same-layer ground copper (trace or fill) within 1 trace width
  for >= X% of the route; decoupling-presence per IC (see 6.1).
- APPLICABILITY: 1-2 layer boards; the grid style is called
  "rarely used, memory arrays" — the return-trace style is the
  current-practice form.

### 5.5 ESD guard band (board-edge ring)

- THRESHOLD: **1/8 in (3.2 mm)** wide copper band around all board
  edges on BOTH outer layers; **>= 0.020 in (0.5 mm)** clearance
  from all components/traces; top and bottom bands stitched by vias
  every **1/2 in (1.3 cm)**; NO soldermask/conformal coating over
  the band; band must NOT form a closed loop — break it into
  segments with **0.020 in (0.5 mm)** air gaps (a closed ring is a
  loop antenna; gaps smaller than 0.020 in couple capacitively and
  re-close the loop); break the band where a moat reaches the board
  edge. Connect band to ground planes ONLY if the board is
  multipoint-grounded into a metal chassis with third-wire earth;
  in plastic enclosures / single-point designs, leave it
  unconnected (else all ESD current funnels through the one ground
  point, "destroying almost everything in its path").
- WHY: handling discharges hit the board edge first; the band
  intercepts and (when chassis-grounded) drains the pulse.
- WHERE: PDF p.201-202, sect. 6.5 (Fig. 6.7); App. A PDF p.274
  (which misprints the via pitch as "1/2 in (0.5 mm)" — the ch.6
  value 1.3 cm is correct).
- MACHINE FORM: board-outline generator option
  `esd_guard_band(width=3.2, clearance=0.5, via_pitch=12.7,
  segmented=True, tie_to_ground=chassis_grounded)`; checks: band
  clearance, soldermask opening, segmentation gaps >= 0.5 mm.
- APPLICABILITY: boards handled by edge / in plastic enclosures;
  connection policy depends on grounding architecture.

### 5.6 Other ESD layout constants

- THRESHOLD: ESD is "approximately a 300-MHz event" (~1 ns edge;
  measured rise times to 500 ps) — bypass caps for ESD chosen
  self-resonant near 300 MHz (mid-pF range), though lead L limits
  them; high-voltage shunt caps at I/O rated **>= 1.5 kV** (25V SMT
  caps die); transient devices returned to CHASSIS ground, never
  circuit ground; chassis ground strap geometry width:length
  **5:1 max ratio (3:1 suffices)**; multilayer is 10-100x better
  than 2-layer against indirect ESD; spark gaps: 0.006-0.010 in
  point gap, outer layer, no mask — but "totally impractical",
  historical only; series R protection for CMOS inputs ~1 kohm;
  digital edges faster than 3 ns are the vulnerable class.
- WHY: divert the pulse to chassis before it reaches logic; the
  spectral peak sets the filter design point.
- WHERE: PDF p.192-199, sect. 6.3-6.4 (components list, circuit
  layout list, system list); 5:1 strap PDF p.199; 300 MHz
  PDF p.195 and p.200.
- MACHINE FORM: mostly composition-level (protection parts present
  on I/O nets, returned to chassis net); strap-geometry check where
  a chassis strap is drawn as copper.
- APPLICABILITY: I/O-facing circuits and human-touchable boards.

---

## 6. Bypassing and decoupling (Ch. 3)

### 6.1 When decoupling is required, and how much

- THRESHOLD: discrete decoupling capacitors **must** be provided
  for devices with edge rates faster than **2 ns**, and SHOULD be
  provisioned (pads placed) for every component. Power+ground plane
  pairs alone suffice only for logic slower than ~10 ns edges
  (standard TTL) — bulk caps still needed. One bulk capacitor per
  **two LSI/VLSI devices**, plus bulk at: power entry connector,
  power terminals of daughter-card/peripheral interconnects, near
  power-hungry digital parts, the point FARTHEST from the input
  power connector, high-density areas remote from power entry, and
  adjacent to clock generation circuits. Bulk range 4.7-100 uF;
  voltage rating >= 2x nominal rail. Memory arrays and high pin
  count parts get extra bulk.
- WHY: point-source charge for simultaneous-switching loads; bulk
  prevents dI/dt droop, decoupling shunts the RF component.
- WHERE: PDF p.96, sect. 3.5.3 (2 ns rule); PDF p.90, sect. 3.4
  (10 ns planes-only); PDF p.106-107, sect. 3.6.3 (bulk list, 50%
  derating); App. A PDF p.261-262.
- MACHINE FORM: composition check: every IC whose card lists
  tr_min < 2 ns has >= 1 dedicated decoupling cap; bulk-cap
  presence at power connector + far corner; cap voltage >= 2x rail.
- APPLICABILITY: universal; the 2 ns line is the book's hard
  trigger, slower logic "usually not required".

### 6.2 Capacitor value selection (calculate, don't copy 0.1 uF)

- THRESHOLD: C = dI * dt / dV (example: 74HC, 20 mA surge, 10 ns,
  100 mV allowed -> 2000 pF); max tolerable loop inductance
  L = V * dt / dI (same example at 2 ns edge -> **10 nH total**,
  including via + trace + bond wires). Select the self-resonant
  frequency to sit at the harmonic needing suppression — generally
  the **3rd to 5th harmonic** of the clock; "typically one selects
  srf 10-30 MHz for edges >= 2 ns". 0.1 uF is "too inductive and
  too slow above 50 MHz"; 0.001 uF (or similar high-srf value)
  suits ACT/F-class edges. SRF reference points (Table 3.2):
  0.1 uF: 8.2 MHz THT / 16 MHz 0805; 0.01 uF: 26/50 MHz; 1000 pF:
  82/159 MHz; 100 pF: 260/503 MHz. Lead inductance: THT ~2.5 nH
  per 0.1 in lead (15 nH/in); SMT ~1 nH total. Dielectrics: Z5U
  good below ~50 MHz; NPO above 10 MHz and temperature-stable.
- WHY: above self-resonance a capacitor is an inductor; decoupling
  effectiveness dies exactly where fast logic needs it.
- WHERE: PDF p.102-104, sect. 3.6.1 (Eqs. 3.7-3.9, worked example);
  Table 3.2 PDF p.85; dielectric notes PDF p.85; 0.1 uF folklore
  history PDF p.102.
- MACHINE FORM: decoupling calculator: given rail dV budget, part
  dI/dt (or estimated from tr and loads), emit C_min, L_max, and a
  target srf window; check chosen part against its card.
- APPLICABILITY: per-component; requires dI which vendors rarely
  publish (book flags this — mark `assumption` when estimated).

### 6.3 Parallel (two-value) decoupling — use with eyes open

- THRESHOLD: if paralleling, values must differ by **two orders of
  magnitude (100x)** (0.1 uF || 0.001 uF for 50 MHz systems;
  0.01 uF || 100 pF for higher clocks); benefit is only ~**6 dB**
  over one larger cap, valid over a narrow band; between the two
  srfs the pair forms an ANTIRESONANT peak (worked example: 0.01 uF
  + 100 pF peak at ~110 MHz — right on a 36 MHz clock's 3rd
  harmonic) where impedance exceeds either cap alone.
- WHY: 6 dB comes from halved lead inductance; the L||C between
  srfs is a parallel-resonant tank.
- WHERE: PDF p.88-89, sect. 3.3 (Fig. 3.8, Paul citation);
  values-by-clock PDF p.97, sect. 3.5.3.
- MACHINE FORM: lint: paralleled decoupling values on one power pin
  must be ~100x apart; calculator flags antiresonance frequency and
  compares against clock harmonic list.
- APPLICABILITY: optional technique; single well-chosen cap
  often preferable ("for EMI below 50 MHz better to use only a
  good low-inductance Z5U").

### 6.4 Decoupling placement geometry

- THRESHOLD: capacitor via'd DIRECTLY to the planes — do NOT run
  a trace from cap to component and then one shared via pair
  (largest loop); component power pins also route directly to
  planes. Best: via inside/adjacent the mounting pad, multiple vias
  per pad, short fat traces. Inductance ladder: pair of surface
  traces 10-15 nH/in; via pair 0.4-1 nH (200-500 pH each); plane
  path 0.1 nH. On multilayer, exact cap XY placement is secondary
  ("lumped model... capacitors still function regardless of where
  placed") BUT loop inductance rules; on 1-2 layer boards the cap
  must sit right at the IC power/ground pins (Vgnd noise in the
  ground trace drives the whole board). Optionally 1000 pF caps on
  a **1-in grid** across high-density boards (values down to
  30-40 pF depending on board resonance).
- WHY: EMI is loop geometry x frequency; the decoupling loop must
  be lower impedance than the power-distribution loop or energy
  transfers to the bigger loop.
- WHERE: PDF p.97-99, sect. 3.5.3-3.5.5 (Figs. 3.14, 3.16-3.18,
  inductance numbers); 1-in grid PDF p.97; placement-insensitivity
  research note PDF p.97.
- MACHINE FORM: geometry check per decoupling cap: each pad has
  its own via(s) to the correct plane within X mm, no shared
  cap->component trace before the via; on planeless boards,
  distance(cap, IC power pin) below threshold.
- APPLICABILITY: multilayer for the via rules; 2-layer for the
  adjacency rule.

### 6.5 Plane-pair capacitance

- THRESHOLD: power-ground plane pair effective as a capacitor when
  spaced **< 0.010 in (0.25 mm), 0.005 in (0.13 mm) preferred**;
  Cpp = k * er * A / d with k = 0.2249 (inch units) / 0.884 (cm);
  buried capacitance (0.001 in dielectric) effective to
  **200-300 MHz**, ~506 pF/in^2; multilayer PCBs self-resonate
  **200-400 MHz** — if the lumped discrete-cap srf lands on the
  plane srf, a sharp board resonance appears (change plane spacing/
  area or add different-srf caps). Skin depth: RF cannot penetrate
  1-oz copper above ~30 MHz (6.6e-6 in at 100 MHz) — doubling
  ground planes adjacent to each other adds nothing; capacitor
  usage bands (Table 3.4): electrolytic/tantalum DC-2 kHz-1 MHz;
  ceramic 1-50 MHz; planes 50 MHz+; on-package >100 MHz; on-die
  >500 MHz.
- WHY: parallel-plate capacitance with near-zero ESL is the only
  effective decoupling in the hundreds-of-MHz range.
- WHERE: PDF p.90-93, sect. 3.4.1-3.4.3 (Eqs. 3.5-3.6); skin
  effect PDF p.69, sect. 2.13; Table 3.4 PDF p.90.
- MACHINE FORM: stackup calculator reports plane-pair capacitance
  and srf; warn when plane spacing > 0.25 mm on boards with
  tr_min < 2 ns.
- APPLICABILITY: multilayer with plane pairs; high-frequency
  designs.

---

## 7. Stackups (Ch. 2.5 — reference data)

- THRESHOLD / directives: every routing layer adjacent to a
  reference plane (only outer microstrip and 1-2 layer boards
  excepted); outer microstrip carries only slow, non-periodic
  traces; prefer ground over power as the adjacent plane; ground as
  layer 2 (instead of power) reduces capacitive coupling to
  enclosure; three routing layers adjacent = banned. Recommended
  assignments (Table 2.1): 4-layer S-G-P-S; 6-layer S-G-S-S-P-S
  (config 2) or S-P-G-S-G-S (config 3, clock layer coaxial between
  grounds); 8-layer best = S-G-S-G-P-S-G-S (config 2, "best
  possible configuration"); 10-layer S-G-S-S-G-P-S-S-G-S.
  Impedance reference tables for 62-mil boards, er 4.3, 1-oz:
  e.g. 8-mil trace: outer microstrip 97 ohm / embedded 66 ohm
  (6-layer cfg 1); 71/57 (cfg 2); 5-mil trace 8-layer cfg 2:
  S1/S4 72, S2 50, S3 54 ohm. Trace impedance tolerance target
  +/-10% (accept 20-30% only after SI review). Impedance formula
  validity: microstrip Eq. 4.1 +/-5% for W/H <= 0.6; sidewall
  ~2 ohm/mil thickness sensitivity; soldermask drops microstrip Z
  0.5-1 ohm per mil of coating (sensitivity ~3 ohm/mil).
- WHY: adjacency = flux cancellation; ground preferred because
  power planes modulate with switching current.
- WHERE: PDF p.41-50, sect. 2.5 (Table 2.1, Figs. 2.11-2.15,
  impedance lists); +/-10% PDF p.134, sect. 4.7; formula-accuracy
  notes PDF p.111-114, sect. 4.1-4.2.
- MACHINE FORM: stackup validator: each routing layer has an
  adjacent plane; clock-class layer adjacency to 0V plane;
  impedance calculator cross-check against these table anchors as
  golden values.
- APPLICABILITY: 62-mil FR-4 er 4.3-4.6 for the numeric tables;
  concepts general.

---

## 8. The 20-H rule (Ch. 8.2) — with the book's own limits

- THRESHOLD: make every power plane physically SMALLER than its
  nearest ground plane by **20x the interplane dielectric spacing
  (20-H)** on each edge. Example: 0.006 in spacing -> inset
  0.120 in (3.0 mm). Effect first noticeable at 10-H; 20-H is the
  ~70% flux boundary; **100-H** for 98%; beyond 20-H no significant
  further benefit and routing gets harder. Traces on the routing
  layer adjacent to the inset region must be pulled inward so they
  stay over solid power plane copper — "no exceptions" (routing
  over the setback = routing over a moat). Power pins landing in
  the setback may be fed by reshaping the plane or a trace.
- WHY: the plane pair is an unterminated z-axis transmission line;
  its edges are "flying stubs" that reflect and resonate; fringing
  flux at the board edge radiates. Undercutting the power plane
  "removes the stub" — a z-axis version of the 3-W rule. Also
  raises the board's intrinsic self-resonant frequency (less
  interplane capacitance).
- WHERE: PDF p.227-231, sect. 8.2 (implementation, Fig. 8.4;
  technical transmission-line explanation p.229-231); App. A
  PDF p.278.
- MACHINE FORM: plane-generator option `power_plane_inset =
  20 * interplane_gap` per edge; companion check that no trace on
  adjacent layers lies over the setback strip; applicability gate
  (below).
- APPLICABILITY (book's own gating — important):
  - only "very high-speed" boards; the fringing effect is
    "generally observed on ONLY very high-speed PCBs";
  - useless when board dimensions are small vs wavelength: apply
    per-edge only when the edge's straight-line dimension matches
    some lambda permutation (lambda/4, lambda/8...) of a clock
    harmonic present (worked example: a 5-in board with 100 MHz
    clock -> lambda/4 = 2.46 in, lambda/8 = 1.23 in... book
    concludes 20-H "not appropriate" there — note the example's
    logic is loose, recorded in section 10);
  - App. A softens "must" to "should... not required for every
    PCB";
  - required use case: on the ANALOG power plane at moat
    boundaries in video/audio partitions (PDF p.181, 183).

---

## 9. Trace current capacity, creepage (Ch. 8.8-8.9, safety anchors)

- THRESHOLD: conservative design limit **10 degC rise above
  ambient** for any trace; example anchor: 0.010-in trace, 1-oz
  copper carries **1.2 A at 20 degC rise**. Published curves
  already include 10% current derating; derate a FURTHER 15% when
  board thickness <= 0.031 in (0.8 mm) OR copper >= 3 oz. Fusing
  (wire) per Eq. 8.7 with K = 10,244 for copper; copper melts at
  1083 degC. Creepage/clearance: reproduces the IEC/UL 60950 ITE
  tables (Tables 8.3-8.6) — anchors, pollution degree 2, working
  voltage: clearance (basic) 150 Vrms -> 1.0 mm (reinforced
  2.0 mm); 300 Vrms -> 2.0 mm (R 4.0 mm); creepage PD2 material
  group I/II/IIIa+b: 50 V -> 0.6/0.9/1.2 mm; 150 V ->
  0.8/1.1/1.6 mm; 250 V -> 1.3/1.8/2.5 mm; 300 V -> 1.6/2.2/3.2 mm.
  Lithium battery circuits require REDUNDANT reverse-current
  protection (two series elements: diode+diode or diode+resistor).
  Flammability V-1 or V-0 minimum. All unconnected vias removed
  from artwork (intentional stitching/ground vias exempt). No
  soldermask on ground stitches, guard bands, ESD bands, chassis
  screw pads.
- WHY: trace heating degrades reliability and dielectric; safety
  tables are shock/fire law, not EMC.
- WHERE: PDF p.249, sect. 8.9 (Fig. 8.15, deratings); PDF
  p.247-248, sect. 8.8 (Tables 8.3-8.6, from UL1950/IEC950);
  battery PDF p.244, sect. 8.6; via/soldermask/flammability
  PDF p.253, sect. 8.10.
- MACHINE FORM: PCBSmith already has IPC-2221-based width/current
  and clearance machinery — cross-check only; add
  `unconnected_via` artwork check and `soldermask_over_stitch`
  check; battery-redundancy is a composition check for any Li cell.
- APPLICABILITY: creepage tables are the 1999-era ITE standard —
  IPC-2221B and current IEC 62368-1 take precedence in PCBSmith
  (rulebook sect. 10); keep these as historical corroboration only.

---

## 10. Contradictions, hedges, and suspected errata

1. **90-degree corner myth**: the book's central myth-bust —
   right-angle corners have no measurable EMI/SI effect below GHz;
   45-degree routing is justified by ETCH MANUFACTURING only. This
   contradicts decades of "no 90s for EMI" folklore. Internal
   inconsistency: ch.8 body says 15-20% Z dip for ~15 ps and edges
   < 50 ps affected; App. A says ~10% for 17 ps and "signals that
   exceed 33 GHz". Keep the qualitative conclusion, not the digits.
2. **Single-point ground threshold**: sect. 2.9.1 says single-point
   is best "1 MHz or less"; App. A says single-point for clocks
   <= 100 kHz and multipoint above 100 kHz. A 10x disagreement in
   the same book. PCBSmith should treat 100 kHz-1 MHz as a
   judgment band.
3. **Grid loop-area unit error**: "1.5 square in. (3.8 square cm)"
   (PDF p.43) — 1.5 in^2 = 9.68 cm^2; 3.8 cm is the LINEAR
   conversion of 1.5 in. Use 1.5 in^2.
4. **App. A guard-band via pitch misprint**: "every 1/2 in
   (0.5 mm)" (PDF p.274); ch.6 body says 1/2 in (1.3 cm) — body is
   correct.
5. **Parallel-trace separation "0.002 in (0.05 mm)"** as a
   crosstalk-control technique (PDF p.220, sect. 7.10) — almost
   certainly a misprint (0.002 in is *tighter* than any normal
   spacing); likely intended 0.020 in. Do not encode.
6. **LVDS length-match number**: "matching would need to be within
   an accuracy of 1.5 in (3.8 cm) or less" for 250 ps parts
   (PDF p.140) — looser than the generic 0.5 in figure for slower
   signals, which is backwards vs physics as literally printed.
   Interpret as: 0.5 in is a general safe bound; compute skew
   budget from tr for fast parts.
7. **Tight differential coupling**: the book argues close pair
   spacing does NOT reduce localized crosstalk (separation from the
   aggressor wins, square-law) and 0.1 in pair spacing is
   "adequate" for EMI — contradicts modern tightly-coupled-pair
   practice, which is driven by impedance control and density, a
   motivation the book does list (routability). For PCBSmith: keep
   1-W tight pairs (impedance + density), don't expect crosstalk
   magic from it.
8. **Parallel decoupling is oversold in industry**: only ~6 dB,
   narrowband, with an antiresonance hazard; the book both
   recommends the 0.1||0.001 pairing at every VLSI power pin
   (sect. 3.5.3) and warns against it (sect. 3.3). Encode the 100x
   spacing + antiresonance-vs-harmonic check rather than a blanket
   "two caps per pin" rule.
9. **20-H rule hedges**: mandatory in high-bandwidth zones and
   analog-partition power planes, but "not required for every PCB",
   pointless on boards small vs wavelength, and its applicability
   example (5-in board, 100 MHz) is internally shaky — the stated
   lambda/4 (2.46 in) DOES fit inside a 5-in board, yet the book
   concludes it doesn't apply. Treat 20-H as opt-in, gated on
   declared clock harmonics vs board dimensions. (Montrose is the
   20-H rule's chief proponent; later literature — e.g. IEEE EMC
   papers 2000s — found negligible or even negative benefit in some
   configurations. Keep it a knob, never a blocker.)
10. **Guard traces on multilayer**: "a waste of time" in stripline
    (the plane is closer) — contradicts the widespread habit of
    guard-ringing clocks on multilayer boards. Encode guard traces
    only for planeless boards.
11. **Buried-capacitance srf claim** (Table 3.2 header) — SMT srf
    "higher by approximately two orders of magnitude (100x)"
    (PDF p.102) vs its own Table 3.2 showing ~2x. Table is right.
12. **Book scope**: nothing on double-sided COMPONENT MOUNTING
    (parts on both sides) — its "double-sided" always means
    2-layer copper. The nearest content is interboard coupling
    (sect. 7.4: solid bottom ground plane on adapter cards) and
    localized-plane keep-outs. No rule extracted for PCBSmith's
    dual-side placement work beyond: keep the far side of a
    frequency generator free of foreign traces (sect. 8.1) and
    prefer a solid outer plane facing an adjacent noisy board.

---

## Top 10 most machine-encodable rules (ranked)

1. **3-W spacing for critical nets** (sect. 1.1-1.3): pure geometry
   — centerline >= 3W between critical-net copper and any other
   copper, including vias and breakout stubs; 1-W intra-pair.
   Direct router constraint + virtual check.
2. **Electrically-long-trace termination trigger** (sect. 2.1):
   `routed_length > k * tr_min` per topology (k = 3.49/2.75 in/ns
   round-trip at er 4.6) -> net must contain a termination block.
   Closed-form, evidence-backed by component tr.
3. **Series-terminator adjacency** (sect. 2.3): termination R
   within a few mm of the driver pad with no via between; end
   terminator is the last element on the routed tree. Pure netlist
   + geometry order check.
4. **Ground via at every critical-net layer jump** (sect. 3.2):
   for each via on a clock-class net, require a ground stitching
   via (or component ground pad) within radius r. Geometry check;
   router co-placement hook.
5. **Decoupling presence + loop geometry** (sect. 6.1, 6.4): every
   IC with tr_min < 2 ns has a dedicated cap; cap pads have own
   vias to planes (no shared trace-then-via); bulk caps at power
   entry and far corner; values 100x apart when paralleled.
6. **Clock-zone keep-out** (sect. 4.1): no foreign trace under or
   through the oscillator/clock-buffer zone on any layer class
   where it applies; oscillator not socketed; localized plane with
   >= 2 stitching vias; zone away from board edge and I/O.
7. **Ground-stitch aspect ratio lambda/20** (sect. 5.1-5.2): max
   spacing between declared chassis stitches <= 15/f_MHz meters
   with f = highest harmonic (10/(pi*tr_min)). One-line formula
   over placement data.
8. **Moat/bridge partition validator** (sect. 4.4): moat >= 0.25 mm
   copper-free on all layers, exactly one bridge, no undeclared net
   crossing, bridging component centered on the bridge, crossing
   traces adjacent to bridge copper. Extends PCBSmith's existing
   isolation machinery.
9. **Two-layer ground-grid / return-adjacency** (sect. 5.4): grid
   cell loop area <= 1.5 in^2 (967 mm^2); clock-class routes have
   parallel ground copper within one trace width for the route
   length; per-IC decoupling on planeless boards.
10. **ESD guard band generator + checks** (sect. 5.5): 3.2 mm band,
    0.5 mm clearance, 12.7 mm via stitching, segmented with
    >= 0.5 mm gaps, no soldermask, grounding policy switched on
    enclosure/grounding declaration. Fully parametric geometry.

Runners-up: connector ground-pin adjacency for clock pins
(sect. 1.9), T-stub ban/length check (sect. 1.10), stackup
adjacency lint (sect. 7), unconnected-via and
soldermask-over-stitch artwork checks (sect. 9), 20-H plane inset
as an opt-in generator knob (sect. 8).
