# Bogatin — Signal and Power Integrity, Simplified (distilled rules)

**Provenance**
- Book: Eric Bogatin, *Signal and Power Integrity — Simplified*, 3rd edition, 2018, Prentice Hall / Pearson.
- Source: EPUB text cache `.book-cache/bogatin-spi/` (33 chapter files).
- sha256 (EPUB, from `.book-cache/manifest.json`): `e7b48edc58e8dec4914063bb3ab88e83b4534082291922b5630badd5359c6f1a`
- Distilled: 2026-07-11 by Claude (PCBSmith developer agent).
- Locators are chapter.section numbers as printed (EPUB has no fixed pages). "App A/B" = the
  book's Appendix A (100+ design guidelines) and Appendix B (100 collected rules of thumb).
- Bogatin's own caveat (App B): rules of thumb are for estimates, not sign-off; a rule of
  thumb "is quick; it is not meant to be accurate."

**PCBSmith applicability screen (do this once per board).** Our current boards: 2-layer
1.6 mm FR4, 3.3 V logic, edges no faster than ~3 ns, I2C/SPI-class buses, USB Full Speed
(12 Mbit/s, ~4-8 ns edges). In FR4 the signal speed is ~6 in/ns = ~150 mm/ns (B.7 #31:
delay ~170 ps/inch = ~6.7 ps/mm). For RT = 3 ns:

| Derived quantity | Formula | Value at RT = 3 ns |
|---|---|---|
| Signal bandwidth | BW = 0.35/RT (2.10) | ~117 MHz |
| Spatial extent of edge | Δx = RT × v (7.6) | ~18 in / ~457 mm |
| Max unterminated line | Len ≤ RT[ns] inches (8.9) | ~3 in / ~76 mm |
| Max discontinuity length | Len ≤ RT[ns] inches (8.11) | ~76 mm |
| Max lumped C discontinuity | C ≤ 4 pF × RT[ns] (B.7 #51) | ~12 pF |
| Max lumped L discontinuity | L ≤ 10 nH × RT[ns] (B.7 #54) | ~30 nH |
| NEXT saturation length | Lsat = ½ RT × v (10.8) | ~9 in / ~229 mm |

Conclusion the numbers force: at 3-ns edges on boards ≤ 100 mm across, reflections,
corners, and vias are non-issues; the live risks are **crosstalk on long parallel runs**,
**return-path discontinuities**, and **PDN loop inductance**. Every rule below still
carries its threshold so the checks stay valid when a faster part (edge < 1 ns) lands.

---

## 1. Rise time, bandwidth, and when any of this matters (Ch. 2)

**R1. Bandwidth from rise time.**
- THRESHOLD: BW = 0.35 / RT (10-90 rise time). RT in ns → BW in GHz.
- WHY: empirical fit of highest significant sine component needed to rebuild the edge.
- WHERE: 2.10 (Fig 2-11); App B #3.
- MACHINE FORM: `signal_bandwidth(rt_ns) = 0.35/rt_ns` — the master knob every other
  check keys off; store per-net `rise_time_ns` in the design intent.
- APPLICABILITY: general; book states no limit.

**R2. Rise time from clock frequency (when RT unknown).**
- THRESHOLD: assume RT ≈ 7% of clock period (aggressive; 10% typical), giving
  BW ≈ 5 × Fclock. App B #1 uses RT ≈ 10% × period.
- WHY: overestimating bandwidth is safer than underestimating (2.13, explicitly argued).
- WHERE: 2.13; App B #1, #4.
- MACHINE FORM: default `rise_time_ns = 0.07 / f_clock_GHz` when a component card gives
  no edge-rate fact; mark as `assumption`.
- APPLICABILITY: clock-like repetitive signals only.

**R3. Spatial extent of the edge.**
- THRESHOLD: Len = RT × v ≈ RT[ns] × 6 inches (FR4). 1 ns → 6 in (152 mm).
- WHY: SI problems scale with discontinuity size *relative to* the edge length in copper.
- WHERE: 7.6; App B #32.
- MACHINE FORM: `edge_extent_mm(rt_ns) = rt_ns * 152` — comparator used by R6, R13.
- APPLICABILITY: general.

## 2. Transmission-line criticality — when a trace is "long" (Ch. 7, 8)

**R4. When to terminate (the central criticality rule).**
- THRESHOLD: line needs no termination if TD < 20% of RT. Equivalent easy form:
  **max unterminated length in inches ≈ rise time in ns** (FR4). 1 ns → 1 in; 3 ns → 3 in.
- WHY: reflections still occur but smear into the rising edge when round-trip flight
  time << RT; ringing becomes discernible past the 20% boundary (Fig 8-16).
- WHERE: 8.9 (TIP); App B #47. Quote: "the maximum length of an unterminated line
  (in inches) is the rise time (in nsec)" (8.9).
- MACHINE FORM: check `trace_length_mm > 25.4 * rt_ns` → finding `unterminated_long_line`
  unless net has a series/parallel termination role in the composition.
- APPLICABILITY: point-to-point CMOS-style drivers; book states no other limit.

**R5. Impedance control tolerance.**
- THRESHOLD: keep characteristic-impedance changes < 10% to hold reflection noise < 5%
  of swing (ΔZ of 5 Ω in 50 Ω ↔ 5% reflection).
- WHY: reflection coefficient = ΔZ/(Z1+Z2); 10% Z change ≈ 5% reflected voltage.
- WHERE: 8.11; App B #48. "the typical spec for the control of the impedance in a
  board is ±10%" (8.11).
- MACHINE FORM: when we ever do controlled impedance: width/stack calculator with ±10%
  acceptance band.
- APPLICABILITY: matters only when the line is long per R4.

**R6. Short discontinuities are transparent.**
- THRESHOLD: any neck-down/width-change region shorter (in inches) than RT (in ns) —
  same 20%-of-RT criterion — may be ignored.
- WHY: reflections from the discontinuity's two ends are equal, opposite, and cancel
  when it is electrically short.
- WHERE: 8.11; App B #49.
- MACHINE FORM: allow router width-necking segments if `segment_len_mm < 25.4 * rt_ns`.
- APPLICABILITY: uniform-impedance discontinuities (neck-downs, via fields).

**R7. Lumped capacitive load limit.**
- THRESHOLD: C ≤ 0.004 nF × RT[ns] (= 4 pF per ns of rise time) "may not cause a
  problem". Delay adder of any shunt C ≈ 0.5 × Z0 × C (1 pF on 50 Ω → 25 ps).
- WHY: shunt C forms an RC filter with Z0/2; reflected dip scales with C/RT.
- WHERE: 8.13-8.15; App B #50, #51, #53.
- MACHINE FORM: sum per-net stub/test-pad/via capacitance; flag if `> 4 * rt_ns` pF.
- APPLICABILITY: mid-trace loads; at the receiver the C instead sets RT ≈ 100 ps × C[pF]
  (B.7 #50).

**R8. Lumped inductive discontinuity limit.**
- THRESHOLD: L ≤ 10 nH × RT[ns] may be acceptable. Compensation: 10 nH wants ~4 pF in
  50-Ω systems. Axial resistors (~10 nH ESL) banned below 1-ns rise times; SMT ~2 nH.
- WHY: series L inserts Z = L/RT impedance spike into the line.
- WHERE: 8.18, 8.19; App B #54-56, #7; App A #14, #15.
- MACHINE FORM: connector/jumper/0-Ω-link inductance budget per net: flag
  `total_series_L_nH > 10 * rt_ns`.
- APPLICABILITY: book states no other limit.

## 3. Corners and vias (Ch. 8.16)

**R9. Corner excess capacitance — the number.**
- THRESHOLD: **C_corner[fF] ≈ 2 × w[mils]** for a 50-Ω line (a 90° bend adds roughly half
  a square of extra metal). 0.2 mm trace (7.9 mil) → ~16 fF; 0.4 mm (15.7 mil) → ~31 fF.
  Two 45° bends or a constant-width arc reduce it further; measured example: two 90°
  bends on a 65-mil line = 200 fF total (100 fF each), matching the rule.
- WHY: the *only* SI effect of a corner is the extra trace width at the bend acting as a
  capacitive discontinuity — not electron acceleration, not radiation (explicitly
  debunked in 8.16).
- WHERE: 8.16 (TIP); App B #52; App A #9: "Don't worry about corners unless 10 fF of
  capacitance is important."
- WHEN CORNERS MATTER: a 10-fF corner (5-mil line) matters only for rise times of order
  **3 ps**; a 20-fF corner ~5 ps (B #52). Delay adder of 10 fF ≈ 0.25 ps. Against R7's
  budget (4 pF/ns), one corner of our 0.3-mm trace (24 fF) is 0.6% of the 3-ns budget.
- MACHINE FORM: no check needed — document as a non-rule. If we ever add a corner check,
  it is `n_corners * 2 * w_mil * 1e-3 pF` counted into R7's per-net C budget, active only
  when `rt_ns < 0.1`. Right-angle-corner avoidance in PCBSmith remains justified by acid
  traps/fab and aesthetics (rulebook §11), NOT by signal integrity.
- APPLICABILITY: 50-Ω-ish lines; scales with C_len via Z0 (formula in 8.16).

**R10. Via parasitics — the numbers.**
- THRESHOLD: via stub capacitance ≈ **5 fF per mil of stub length** (via acts like a
  ~35-Ω line, ~5 pF/inch); typical through-via C = 0.1-1 pF; measured 10-layer example
  0.4 pF → 9-10 ps delay adder. Via partial self-inductance ≈ **1 nH/mm**
  (25 nH/inch rod formula): a 1.6-mm through-via ≈ 1.6 nH.
- WHY: barrel + pads have excess C to planes; narrow barrel has rod-like L.
- WHERE: 8.16 (C, ~35 Ω, 5 fF/mil); App B #19 (1 nH/mm rod); App A #16.
- MACHINE FORM: per-via constants for R7/R8 budgets: `via_c_pf = 0.005 * stub_len_mil`
  (2-layer full-barrel: use ~0.3 pF), `via_l_nh = 1.0 * board_thick_mm`.
- APPLICABILITY: our 1.6-mm 2-layer vias: ~0.3 pF / ~1.6 nH each — negligible against
  the 12 pF / 30 nH budgets at 3 ns; ~10 vias in one net still fine.

## 4. Crosstalk (Ch. 10)

**Noise budget premise (10.0/10.11):** noise margin ~15% of swing; crosstalk allocation
~5%; with aggressors on both sides of a victim, design each pair for < 2%.

**R11. The spacing rule.**
- THRESHOLD: **edge-to-edge spacing ≥ 2 × line width** keeps worst-case NEXT below ~5%
  (each neighbor < 2%, both sides + rest of bus < 5%).
- WHY: fringe-field extent is set by dielectric height h; for 50-Ω lines w ≈ 2h
  (microstrip), so spacing in w-units is a proxy for spacing in h-units. Coupling falls
  off roughly with (s/h)².
- WHERE: 10.11 (TIP), Fig 10-26/27; App B #84; App A #34.
- MACHINE FORM: virtual check `crosstalk_spacing`: parallel same-layer runs with
  `gap < 2*w` for longer than `min(coupled_len_threshold, saturation length)` → finding.
  Exempt nets flagged static (LED drive, resets).
- APPLICABILITY: 50-Ω-geometry lines. CAUTION for PCBSmith: our 2-layer stack has
  h ≈ 1.5 mm >> w, so fringe fields extend much farther than "2 × w" — the w-based
  shortcut *understates* coupling without a plane close by; treat 2×w as the floor,
  not proof of safety, for parallel runs longer than ~50 mm (see R18).

**R12. NEXT magnitude table (50-Ω lines, FR4).**
- THRESHOLD: microstrip NEXT ≈ 5% at s=w, 2% at s=2w, 1% at s=3w. Stripline: 6%, 2%,
  0.5%. In a bus at s=w, ~75% of victim noise comes from the two nearest neighbors,
  95% from the nearest two on each side; at s=2w, 100% from nearest neighbors.
- WHY: NEXT = ¼(Cm/C + Lm/L); both ratios drop steeply with spacing.
- WHERE: 10.11 (Fig 10-27); App B #70-71, #74-79, #85-87.
- MACHINE FORM: `next_estimate(s_over_w)` lookup {1:0.05, 2:0.02, 3:0.01} interpolated;
  multiply by coupled-length fraction (R13) and signal swing to report mV.
- APPLICABILITY: 50-Ω geometry; only nearest neighbors need checking at s ≥ 2w.

**R13. Saturation length — crosstalk stops growing.**
- THRESHOLD: **Lensat = ½ × RT × v** (= RT[ns] × 3 inches in FR4). 1 ns → 3 in (76 mm);
  3 ns → 9 in (229 mm). Below saturation, NEXT scales linearly:
  `NEXT_actual = NEXT_table × coupled_len / Lensat`. Beyond it, extra coupled length
  adds nothing (and shortening below it is the only way length helps).
- WHY: near-end noise builds while new rising edge keeps entering the coupled region —
  for a duration RT — but starts decaying after 2×TD; the two balance when TD = RT/2.
- WHERE: 10.8 (definition + TIP), 10.11 item 2; App B #72; App A #40.
- MACHINE FORM: in the `crosstalk_spacing` check, compute
  `severity = min(1, coupled_len_mm / (rt_ns*76.2)) * next_estimate(s/w) * v_swing`;
  threshold at 2% of swing per aggressor.
- APPLICABILITY: general; independent of RT once saturated.

**R14. Far-end crosstalk (FEXT) — microstrip only.**
- THRESHOLD: microstrip at s=w: FEXT ≈ 4% × TD/RT; s=2w: 2% × TD/RT; s=3w: 1.5% × TD/RT
  (grows with coupled length without saturating). **Zero FEXT in stripline / fully
  embedded microstrip** (homogeneous dielectric). Going s=w → s=3w cuts FEXT 65%.
  Keeping tightly coupled regions under TD ≈ 0.1 ns (~15 mm) keeps FEXT < 1% even at 0.5-ns RT.
- WHY: FEXT exists because capacitive and inductive coupling don't cancel when the
  fields see mixed air/dielectric; it rides the wavefront and integrates over length.
  Solder mask / top dielectric reduces it (an optimal coat thickness nulls it).
- WHERE: 10.12, 10.13; App B #80-83; App A #37-39.
- MACHINE FORM: `fext_estimate = k(s/w) * (coupled_len_mm*0.0067) / rt_ns` with
  k = {1:0.04, 2:0.02, 3:0.015}; flag > 2% of swing. All PCBSmith traces are surface
  microstrip → FEXT check is always relevant for long buses.
- APPLICABILITY: surface (microstrip) traces; scales 1/RT so 3-ns edges need ~450 mm
  coupled at s=w to hit 4% — only matters for us on very long parallel buses.

**R15. Guard traces — when and how.**
- THRESHOLD: separating traces enough to *fit* a guard (s = 3w) already cuts noise ~4×
  (4% → 1.2% in the worked 5-mil example) — usually sufficient alone. A guard shorted
  at both ends halves it again (~50% reduction; 1.2% → 0.66%). An **open/floating guard
  makes crosstalk worse**. Shorting vias along the guard: at least **3 vias per spatial
  extent of RT** (spacing ≤ RT×v/3; 1 ns → ~50 mm pitch). Stripline + guard reaches
  −160 dB; microstrip guards "do not help much" beyond the spacing effect.
- WHY: guard reduces Cm/Lm geometrically, but noise induced *on* the guard re-couples to
  the victim unless the ends (and mid-points, for FEXT) are shorted to return.
- WHERE: 10.15 (three TIPs); App B #88, #89; App A #43-45.
- MACHINE FORM: design check on any `guard` net role: must connect to GND at both ends,
  via pitch ≤ `rt_ns*152/3` mm, width as wide as fits; reject floating guards.
- APPLICABILITY: only for isolation needs beyond the s ≥ 2w rule (mixed-signal, RF).

**R16. Shared-return switching noise (connectors, headers, packages).**
- THRESHOLD: keep mutual inductance between signal/return pairs Lm < 2.5 nH × RT[ns].
  Max usable clock for a shared-return connector ≈ 250 MHz / (n × Lm[nH]) for n
  simultaneously switching lines.
- WHY: ground bounce V = Lm × dI/dt across the shared return.
- WHERE: 10.18; App B #90, #91; App A #50-52 (assign no-connects as returns, etc.).
- MACHINE FORM: connector pinout check: count signal pins per return pin; with
  Lm ≈ 1 nH per adjacent 100-mil header pin pair, flag `n_sig/`return > 250/(f_clk_MHz)`.
- APPLICABILITY: the check that actually bites on hobby-class 0.1-inch headers.

## 5. Return path and 2-layer-board reality (Ch. 7.13-7.14, App A)

**R17. Return current is directly under the trace; width matters.**
- THRESHOLD: return conductor under the signal should be ≥ 3 × signal width — Z0 then
  within 1% of the infinite-plane value; equal-width return raises Z0 by 20%. Above
  about 100 kHz return current localizes in the plane surface directly beneath the
  trace (spot-check corrected 2026-07-12: the note originally said ~10 MHz; §7.13
  states ~100 kHz as the onset, 10 MHz was only an example point).
- WHY: minimum-loop-inductance path; the current distribution self-selects it.
- WHERE: localization onset 7.13; the 3×w / +20% figures are App B #41, #42 and
  Fig 7-34 in 7.17 (locator corrected 2026-07-12); App A #10, #11 (route around,
  not across, plane gaps).
- MACHINE FORM: virtual check `return_path_continuity`: for each fast net, verify a
  same-direction GND copper corridor ≥ 3×w exists beneath/alongside within one
  dielectric height; flag crossings of GND pour gaps.
- APPLICABILITY: any net whose length exceeds R4's unterminated limit.

**R18. When is a 2-layer board without planes acceptable? (synthesis — the book gives
no single rule; state per-criterion.)**
- THE BOOK'S CLOSEST STATEMENT: in the 10-MHz era (RT ≈ 10 ns) the max unterminated
  line was 10 inches, longer than virtually all traces, so "the interconnects were
  'transparent to the signals'" (Ch. 1; 8.9 retells it quantitatively).
- DERIVED CRITERIA, all must hold: (a) every trace shorter than RT[ns] inches (R4);
  (b) crosstalk budget met per R12/R13 with the caveat in R11 about large h;
  (c) PDN target impedance ≥ ~1 Ω, which on-die + bulk capacitance satisfies without
  board finesse (R20); (d) each signal has an intentional, continuous return conductor
  (R17) — on 2-layer, a solid GND pour/grid on the bottom under signal runs.
- FOR OUR BOARDS: 3-ns edges → traces < 76 mm are transparent; 3.3 V/5% ripple with
  < 150 mA transients → Ztarget ≈ 1.1 Ω → criterion (c) holds. 2-layer is defensible
  by the book's own numbers, PROVIDED the GND-side copper under fast nets is continuous.
- WHERE: Ch. 1; 8.9; 13.11; App A #10.
- MACHINE FORM: board-level advisory check `two_layer_si_screen` evaluating (a)-(d)
  from per-net rise-time facts; emits `needs_review` finding listing which criterion
  fails, never auto-passes (law 4).
- APPLICABILITY: book states no explicit limit; this is our synthesis — mark findings
  as derived, cite this file.

## 6. Decoupling and the PDN (Ch. 13, 5, 6)

**R19. Target impedance is the master spec.**
- THRESHOLD: Ztarget = (Vdd × ripple%) / Itransient; ripple typically ±5%. Example:
  3.3 V × 5% / 0.15 A ≈ 1.1 Ω. Keep PDN impedance below Ztarget from DC to where the
  package takes over (~100 MHz assumption for board-level work).
- WHY: worst-case transient current through PDN impedance is the rail noise.
- WHERE: 13.2 (definition), 13.4; 13.10 (100-MHz package-barrier assumption).
- MACHINE FORM: calculator `pdn_target_impedance(vdd, ripple_pct, i_transient)` in
  `calculators/electronics.py`; every topology's composition records its Ztarget.
- APPLICABILITY: per rail, per chip; peak transient current, not average.

**R20. When decoupling details don't matter.**
- THRESHOLD: **Ztarget ≥ ~1 Ω → board decoupling "may not play a very important
  role"** (on-die C + VRM bulk caps cover it); below 1 Ω careful board design starts;
  mΩ-class needs engineered plane cavities. Even 0.2 Ω can work if the current spectrum
  avoids the 5-20 MHz dip region.
- WHY: on-die capacitance handles high frequency, VRM handles low; the board only owns
  the middle decades.
- WHERE: 13.11 (both TIPs).
- MACHINE FORM: gate the strictness of decoupling checks on computed Ztarget: ≥ 1 Ω →
  advisory only; < 1 Ω → placement/loop-inductance checks become blockers.
- APPLICABILITY: assumes chips with normal on-die capacitance; unknown die C stays an
  `assumption`-status fact.

**R21. Capacitor mounting loop inductance — what actually matters (priority order).**
- THRESHOLD: typical mounted MLCC loop ≈ 2 nH; good design 0.5-2 nH; < 0.5 nH is heroic.
  First-order (linear) knobs: shallow cavity depth, thin plane-pair dielectric, SHORT
  and WIDE surface traces from pads to vias. Second/third-order (logarithmic) knobs:
  via diameter, via pitch, **capacitor-to-chip distance** ("only a weak dependence").
  Worked example: long thin traces 6.1 nH → short wide traces 3.7 nH → closer + thin
  cavity 1.8 nH.
- WHY: inductance is linear in dielectric/trace geometry but log in radial spreading
  distance — proximity buys little once the connection itself is clean.
- WHERE: 13.14, 13.15 (TIPs + Fig 13-36); App B #24; App A #72, #75.
- MACHINE FORM: two checks: (1) `decap_connection`: pad-to-via trace length ≤ ~1-2 mm
  and width ≥ pad width, own vias (no long shared necks); (2) `decap_proximity` stays
  advisory (severity below connection quality) — placement matters less than trace
  craft. On our 2-layer boards (no plane cavity) the surface loop IS the whole
  inductance: route cap directly in the chip's power path, minimize enclosed loop area.
- APPLICABILITY: quantitatively derived for plane-pair boards; direction of the
  priority order carries over to 2-layer.

**R22. Decoupling quantity numbers.**
- THRESHOLD: charge-supply time of a cap for a 1-W chip at 5% droop: t[s] ≈ C[F]/2
  (10 nF → 5 ns; 20 µF → 10 µs). Plane-pair capacitance ≈ 1 nF/in² at 1-mil spacing,
  scaling 1/thickness. Plane-pair loop inductance ≈ 33 pH/square per mil of spacing;
  a field of clearance holes at 50% open area adds ~50%. Package leads ~20 nH/inch
  of loop per power/ground pair.
- WHY: caps hold the rail only until recharge paths respond; planes are the lowest-L
  structure available.
- WHERE: App B #16, #17, #25, #26; 13.10 (20 nH/inch), 6.10-6.12.
- MACHINE FORM: calculator terms for the PDN chain: `bulk_c_for_droop(power_w,
  droop_pct, hold_time_s)`; not a layout check.
- APPLICABILITY: order-of-magnitude estimates only (Bogatin's own framing).

## 7. Impedance quick numbers for our stackup (Ch. 7, 9)

Handy constants, all App B unless noted:
- 50-Ω FR4 line: 3.3 pF/inch (0.13 pF/mm), 8.3 nH/inch (0.33 nH/mm) (#34, #35).
- Z0 ≈ 160 / C_len[pF/inch] (#33). 50-Ω microstrip: w ≈ 2 × h (#36); stripline b ≈ 2w (#37).
- Trace thickness: −2 Ω per mil; solder mask on microstrip: −2 Ω per mil (#43, #44).
- Sheet resistance 1-oz copper: 0.5 mΩ/square (#10); skin effect starts ~10 MHz (#11);
  skin depth 2 µm at 1 GHz (#27).
- Our geometry reality check: 0.2-0.4 mm traces over 1.5 mm of FR4 to a bottom pour are
  ~110-135 Ω lines, not 50 Ω. Nothing in our signal class needs 50 Ω (USB-FS spec
  tolerates it at 12 Mbit/s with 4-8 ns edges per R4: max unterminated ≈ 100-200 mm).
  Record `assumption: no controlled impedance required while rt_ns >= 3`.
- Loss: irrelevant for us — rise-time degradation matters only when length[in] > 50 × RT[ns]
  (#69: at 3 ns → 3.8 m of trace).

## 8. EMI adjacencies worth encoding (App A)

- Keep all traces ≥ 5 line widths from the board edge (App A #81) — MACHINE FORM:
  extend the existing edge-clearance virtual check with a per-net `5*w` rule for
  routed signal layers. Book states no rise-time limit.
- Use the longest rise time the timing budget tolerates (App A #0, #95) — intent-level
  knob: prefer slow/series-damped drivers in compositions.
- Place high-speed components far from I/O connectors (App A #83).

---

## Top 10 most machine-encodable rules (ranked by check-worthiness for PCBSmith)

1. **Unterminated-line length gate** — `len_mm ≤ 25.4 × rt_ns` (R4, 8.9). One number,
   per-net, decides whether ANY SI machinery engages. The keystone check.
2. **Crosstalk spacing floor** — parallel-run gap ≥ 2×w for coupled runs (R11, 10.11);
   direct geometric router/DRC rule.
3. **Saturation-length severity scaling** — `min(1, len/(76.2×rt_ns))` × NEXT table
   (R13+R12, 10.8/10.11); turns rule 2 from binary into a quantitative finding.
4. **Return-path continuity under fast nets** — GND corridor ≥ 3×w, no gap crossings
   (R17, 7.13); pure geometry against the bottom pour.
5. **Decap connection quality** — pad-to-via ≤ ~2 mm, width ≥ pad, own via, loop area
   minimized; proximity advisory only (R21, 13.15). Directly expressible on placements.
6. **PDN target impedance calculator + ≥1 Ω strictness gate** — Ztarget =
   Vdd×ripple/Itransient; ≥1 Ω relaxes board decoupling checks (R19+R20, 13.2/13.11).
7. **Lumped C/L discontinuity budgets** — ΣC ≤ 4 pF×rt_ns, ΣL ≤ 10 nH×rt_ns per net,
   with via constants 0.3 pF / 1.6 nH (R7, R8, R10; 8.13-8.18).
8. **Shared-return pin ratio** — f_max ≈ 250 MHz/(n×Lm) for connectors/headers
   (R16, 10.18); catches real hobby-board failures (one GND pin on a 10-pin header).
9. **Guard-trace validity** — guard nets must be end-shorted with via pitch ≤
   rt_ns×152/3 mm; floating guard = blocker finding (R15, 10.15).
10. **FEXT budget for surface buses** — k(s/w)×TD/RT ≤ 2% of swing (R14, 10.12);
    matters because every PCBSmith trace is microstrip.

Explicit non-rule worth recording: **corner capacitance (2 fF/mil, R9)** ranks below
all of these — at ≥3-ns edges a corner is ~0.5% of the C budget; right-angle avoidance
stays a fab/aesthetics rule, not an SI rule.

## Verification (2026-07-12, spot-check, sonnet)

| rule | verdict | note |
|------|---------|------|
| R4 (unterminated line, `Lenmax[in] = RT[ns]`) | VERIFIED | c0015-ch08 §8.9 line ~509-531: "the maximum length of an unterminated line (in inches) is the rise time (in nsec)"; 20%-of-RT criterion matches exactly. |
| R11 (crosstalk spacing floor, s ≥ 2w) | VERIFIED | c0017-ch10 §10.11 line ~856-859: "the edge-to-edge spacing of signal traces should be at least two times the line width" → NEXT < 2% per neighbor, < 5% worst-case bus, matches note verbatim. |
| R13 (saturation length, Lensat = ½ RT × v) | VERIFIED | c0017-ch10 §10.8 line ~608-629: "Lensat = ... ½ nsec × 6 inches/nsec = 3 inches" for RT=1ns; linear scaling below saturation confirmed at line 794 ("NEXT × 4 inches/6 inches"). |
| R17 (return path ≥ 3×w for Z0 within 1%; "above ~10 MHz" localization) | MISMATCH | Numeric core (equal-width → +20% Z0; ≥3×w → within 1%) is correct but is App B #41/#42 (c0003-app02 lines 125,127) and Fig 7-34, which lives in §7.17, not §7.13 as cited. Separately, the "above ~10 MHz" localization claim does not match the source: c0014-ch07 §7.13 line 854 states the current localizes "for frequencies above about 100 kHz" (100x lower than the note's figure); line 852 only uses 10 MHz as an example point, not the onset threshold. |
| R19 (Ztarget = Vdd×ripple/Itransient; 100-MHz package barrier) | VERIFIED | c0020-ch13 §13.2/§13.4 (line ~93-298) gives the target-impedance formula and worked 3.3V/5%/example; §13.10 "The Package Barrier" (line 634-780) confirms the ~100-MHz board-effective-frequency assumption. |
| R7 (lumped C budget, C ≤ 4 pF × RT[ns]; delay adder 0.5×Z0×C) | VERIFIED | c0015-ch08 §8.13 line 848: "keep the capacitance, in pF, less than four times the rise time"; §8.15 line 895: "1-pF pad will add about 0.5 × 50 × 1 pF = 25 psec" matches note's "1 pF on 50 Ω → 25 ps" exactly. |
| R16 (shared-return: Lm < 2.5 nH×RT; fmax ≈ 250 MHz/(n×Lm)) | VERIFIED | c0017-ch10 §10.18 line 1506 ("Lm < 2.5 nH × RT") and line 1525-1528 ("highest usable clock frequency ... 250 MHz/Lm" and worked 5-aggressor example "250 MHz/5 = 50 MHz"), matching App B #90/#91 (c0003-app02 lines 238,240). |
| R9 (corner capacitance, C_corner[fF] ≈ 2×w[mils]) | VERIFIED | c0015-ch08 §8.16 line 979: "the capacitance associated with a corner, in fF, is equal to 2 times the line width in mils"; worked 65-mil/200-fF-total example (line 966) and 5-mil/10-fF/~3-ps and 0.25-ps delay-adder figures (line 982) all match the note precisely. |

7/8 verified; mismatches: R17 — the "above ~10 MHz" return-current-localization threshold should be "above about 100 kHz" per §7.13, and the 3×w/1% figure is sourced from §7.17 (Fig 7-34)/App B #41-42, not §7.13 as cited (the quantitative claim itself is otherwise numerically correct).
