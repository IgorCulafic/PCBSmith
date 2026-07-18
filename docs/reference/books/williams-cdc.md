# The Circuit Designer's Companion — distilled rules for PCBSmith

```
book:        The Circuit Designer's Companion, 4th edition
authors:     Tim Williams (1st/2nd ed.), Peter Wilson (3rd/4th ed. revisions)
publisher:   Newnes/Elsevier, 2017, ISBN 978-0-08-101764-7
source pdf:  "The Circuit Designer's Companio - Unknown.pdf"
sha256:      67fa153def7543673490c560d5db3320fc219cc380c789dcf92a4327c262e137
text cache:  .book-cache/williams-cdc/p0001.txt .. p0480.txt (480 pages, 0 empty)
extracted:   2026-07-11 by Claude (PCBSmith reference distillation)
locators:    "PDF p.N" = cache page index; printed section numbers given
             alongside (printed page ~= PDF page - 5).
```

Chapter map (PDF pages): Ch1 Grounding and Wiring 7–53 · Ch2 Printed
Circuits 54–96 · Ch3 Passive Components 97–161 · Ch4 Active Components
162–211 · Ch5 Analog ICs 212–260 · Ch6 Digital Circuits 261–322 ·
Ch7 Power Supplies 323–366 · Ch8 EMC 367–402 · Ch9 General Product
Design 403–480.

Deep-read: Ch1 (grounding/return paths), Ch2 (layout craft, thermal
behavior, SMT rules), Ch3 (electrolytics, ceramics, inductors, crystals),
Ch5 (op-amp/comparator layout), Ch6 (switching noise, decoupling,
mixed-signal), Ch7 (regulator dissipation, reservoir layout), Ch8 (EMC at
board level), Ch9 (thermal management, reliability derating). Skimmed
only: Ch4 (device physics), transmission-line math, batteries, safety
law, software sections.

Rule format: **THRESHOLD** (number as stated) · **WHY** · **WHERE**
(PDF p.N + printed section) · **MACHINE FORM** (one-line PCBSmith
check/knob) · **APPLICABILITY**.

---

## 1. Grounding and return-path discipline (Ch1)

### G1 — There is only one true 0 V point
- THRESHOLD: example arithmetic: 10 mΩ/inch of 0-V conductor at 40 mA
  cumulative → 400–900 µV offsets along the rail.
- WHY: every conductor has finite R and L; current through it makes
  "0 V" different at every point. Trouble starts when currents are amps
  not milliamps, conductor impedance is ohms not milliohms, or the drop
  lands in a sensitive configuration.
- WHERE: PDF p.8–9, §1.1.
- MACHINE FORM: net-current annotation on GND segments; flag GND
  segments shared by a high-current load loop and a low-level signal
  return (common-impedance detector over the routed tree).
- APPLICABILITY: every board; critical for mixed power/signal boards.

### G2 — Separate supply returns per load; join only at the source
- THRESHOLD: worked example: 0.2 Ω shared return, 1.2 A + 50 mA loads →
  0.25 V drop = brownout of a 3.3 V rail. Rule as stated: "always
  separate power supply returns" so each load's current flows in its own
  conductor; same for the feed side.
- WHY: shared return impedance subtracts load-modulated voltage from
  every supply that shares it; varying loads turn it into injected noise
  (chattering relays, motor-boating).
- WHERE: PDF p.15–17, §1.1.5.
- MACHINE FORM: design check: high-current return path (>threshold, e.g.
  >250 mA) must reach the supply/reservoir node without sharing tracked
  copper with a logic/analog return; walk the routed GND tree and compute
  shared-segment IR drop against a mV budget.
- APPLICABILITY: any board with a power stage (LED columns, relays,
  motors) plus logic — directly relevant to the thermometer's LED bank.

### G3 — Input signal return goes to the amplifier reference point
- THRESHOLD: qualitative (arrangements graded A best → D worst).
- WHY: any other 0-V connection point inserts a common impedance X–X in
  series with the wanted signal; autorouters cause this because they
  treat 0 V as one node, free to tap anywhere.
- WHERE: PDF p.17–19, §1.1.6, Fig 1.9.
- MACHINE FORM: per-topology "sense return" net attribute: the sensor/
  input GND pin must connect to the designated reference pad before
  joining bulk GND (tree-order check on the routed GND net).
- APPLICABILITY: ADC/sensor inputs (SHT31-class), audio, precision analog.

### G4 — Output/high-current return goes straight back to the source
- THRESHOLD: stability bound stated: inverting amp oscillates if
  A·Rs/(RL+Rs) < −1 (load-to-common-impedance ratio vs gain).
- WHY: output current through a conductor shared with the input return is
  tailor-made feedback; even below oscillation it warps the response.
- WHERE: PDF p.20–21, §1.1.7.
- MACHINE FORM: same shared-segment walk as G2 keyed by (driver net,
  input net) pairs within one feedback topology.
- APPLICABILITY: amplifier/driver stages; digital systems with analog
  input and controlled outputs too (explicitly stated).

### G5 — Single-point chassis/earth connection; star point discipline
- THRESHOLD: one dedicated stud; star point valid while connection count
  is small ("progressively messier as more connections are brought").
- WHY: multiple chassis taps put unpredictable circulating currents in
  the chassis; star grounding is an elegant local trick, not a substitute
  for analyzing return paths.
- WHERE: PDF p.11, §1.1.2; p.24, §1.1.9.
- MACHINE FORM: board-level: mounting-hole/shield nets must tie to GND
  at exactly one declared point (count check on chassis-net joins).
- APPLICABILITY: boards with shields, chassis-connected mounting holes,
  earthed connectors.

### G6 — Ground loops: minimize enclosed loop area
- THRESHOLD: worked example: 10 cm² loop in 10 µT 50 Hz field → 314 µV
  peak induced — significant for audio/instrumentation only.
- WHY: emf = −10⁻⁸·A·n·dB/dt; cures are: ground at one point, shrink
  loop area (route wire against ground/chassis), reorient, reduce source.
- WHERE: PDF p.13–14, §1.1.4.
- MACHINE FORM: compute signal-vs-return enclosed area for declared
  sensitive nets (polygon area between the two routed paths); warn above
  a per-class cm² budget.
- APPLICABILITY: low-level analog; also the EMC emission model (E9).

### G7 — Wire/track inductance is set by length, not width
- THRESHOLD: rule of thumb: ~20 nH per inch, ~7 nH per cm of wire; 1 m of
  16/0.2 wire = 38 mΩ but 1.5 µH → 4 A/µs generates 6 V across it.
- WHY: inductance grows with length and only logarithmically with
  diameter/width; fattening a track barely helps at HF — shortening and
  pairing with its return does.
- WHERE: PDF p.30–31, §1.2.1; p.71, §2.2.4.
- MACHINE FORM: report nH estimate (20 nH/in) for supply and
  high-di/dt nets; length budget check for decoupling loops (D2).
- APPLICABILITY: all HF/digital nets; basis for decoupling distance rules.

### G8 — Run signal and return close together (field cancellation)
- THRESHOLD: qualitative; "short, direct tracks running close to their
  ground returns make very inefficient aerials" (EMC restatement).
- WHY: maximizing mutual inductance of opposed currents subtracts it from
  total loop inductance; the single most effective ground/power
  inductance reduction on planeless boards. If compromise is needed,
  spend board space on the ground system and fix the power rail by
  decoupling.
- WHERE: PDF p.71–72, §2.2.4 Fig 2.20; p.383, §8.4.
- MACHINE FORM: router cost term: distance between a signal path and its
  return-net copper (reward paired routing); metric = max gap along path
  for declared high-di/dt nets.
- APPLICABILITY: 2-layer boards without planes — our exact class.

---

## 2. PCB layout craft (Ch2)

### P1 — Track width/spacing floor (fab capability)
- THRESHOLD: 0.1 mm track/gap possible, **0.15 mm preferred** (1 oz Cu);
  thicker copper needs wider (etch undercut). Min PTH drill 0.2 mm
  possible, **0.3 mm preferred**; aspect ratio 12:1 possible, **6:1
  preferred**; drill-to-pad registration 0.03 mm, layer-to-layer 0.075 mm.
- WHY: etch controllability and registration; narrowest widths OK in
  isolated pinches (between IC pads) but "harder to maintain over long
  distances".
- WHERE: PDF p.65–66, §2.2.1 Table 2.2.
- MACHINE FORM: already largely in project constraints; add "narrow-neck
  length" check — segments at minimum width should be shorter than a few
  mm (pad-escape scale), widen elsewhere.
- APPLICABILITY: all boards; tune per fab profile.

### P2 — Track current: self-heating limits, from BS6221 Pt 3 curves
- THRESHOLD: Fig 2.18 gives safe current vs width for 10 °C and 20 °C
  rise, 1 oz and 2 oz Cu, range 0–2.5 mm / 0–8 A (curve values are in a
  graphic; the text states the principle, and Fig 2.17 gives resistance:
  copper resistivity 1.8×10⁻⁸ Ω·m, ~2:1 manufacturing spread on final
  resistance, +temperature coefficient several % over ambient range).
  PTH > 0.8 mm dia presents < 1 mΩ.
- WHY: max current is set by track self-heating; resistance sets IR drop.
- WHERE: PDF p.66–67, §2.2.1 Figs 2.17–2.18 (abstracted from BS6221:Part
  3:1984).
- MACHINE FORM: current-rating check: width_mm ≥ f(I, ΔT_allowed, oz)
  using IPC-2152/2221 formulas (numerically compatible with these
  curves); PCBSmith already knows net currents from the calculator —
  wire them to the router's per-net min-width.
- APPLICABILITY: supply rails, LED column commons, heater/driver outputs.

### P3 — Voltage spacing: 1 mm per 200 V
- THRESHOLD: **1 mm per 200 V** adequate in a benign (dry, clean)
  environment, allowing manufacturing tolerance; mains → safety standards
  override. **< 0.5 mm spacing risks solder bridging** in wave soldering
  without resist.
- WHY: breakdown plus process yield.
- WHERE: PDF p.67, §2.2.1.
- MACHINE FORM: per-net-pair voltage clearance table feeding virtual DRC
  (already have mains isolation §10 machinery; add the 1 mm/200 V floor
  for sub-mains HV nets, e.g., flyback secondary spikes).
- APPLICABILITY: any net pair with >≈50 V difference.

### P4 — Crosstalk spacing: 1 mm rule of thumb
- THRESHOLD: **spacing > 1 mm → crosstalk < 10% of signal voltage** for
  most board configurations; electrically short connections may be much
  closer; a ground trace routed between two susceptible lines reduces it.
- WHY: track-to-track capacitance; exact values need field solvers, this
  is the stated design rule of thumb.
- WHERE: PDF p.67–68, §2.2.1.
- MACHINE FORM: parallelism check: accumulate parallel-run length ×
  1/spacing between declared aggressor (clock/switch node) and victim
  (analog/reset/crystal) nets; threshold on the integral; suggest guard
  trace insertion.
- APPLICABILITY: clock vs analog nets; switch node vs feedback on SMPS.

### P5 — Hole size: lead diameter + 0.15–0.3 mm
- THRESHOLD: hole = lead dia **+0.15 to +0.3 mm** for best solder;
  standardize few drills (0.8 mm DIL/small parts, 1.0 mm larger);
  specify diameter **after plating**; beware fat leads on power diodes
  and big capacitors.
- WHY: solder fill quality vs drill-count cost; undersize = production
  disaster (can't drill out multilayer).
- WHERE: PDF p.68–69, §2.2.2.
- MACHINE FORM: footprint-audit check: THT pad drill vs component lead
  diameter from the component card (evidence-backed lead dia) within
  +0.15/+0.3 window.
- APPLICABILITY: every THT part.

### P6 — Via and PTH pad sizing
- THRESHOLD: via aspect ratio ≤ 6:1 unplated-trouble-free; keep via drill
  equal to smallest component drill or one size smaller (e.g. 0.6 mm) to
  minimize drill count / false insertion. PTH pad for 0.8 mm hole:
  **1.3–1.5 mm** dia. Non-PTH: pad ≥ hole + 1 mm; pad/hole ratio ~2
  (epoxy glass), 2.5–3 (phenolic).
- WHY: plating reliability; PTH barrel reinforces adhesion so big pads
  are unnecessary.
- WHERE: PDF p.69, §2.2.2.
- MACHINE FORM: annular-ring check parameterized by PTH vs non-PTH;
  aspect-ratio check against board thickness (have min_through_hole —
  add aspect ratio).
- APPLICABILITY: all boards.

### P7 — Routing craft: short first, 45°, no acute angles, edge margin
- THRESHOLD: **first rule: minimize track length**; 45° bends preferred;
  right/acute angles are etchant traps (fillet acute joins); tracks
  **≥ 0.5 mm from board edge**.
- WHY: short tracks = less crosstalk/parasitics/radiation; acute angles
  corrode; edge clearance for routing/handling.
- WHERE: PDF p.70–71, §2.2.3.
- MACHINE FORM: already enforced (trace_corner_angle, board edge
  clearance). Add: net-length report vs Manhattan lower bound as a
  routing quality metric.
- APPLICABILITY: all boards — matches rulebook §11.

### P8 — Balance copper coverage between sides
- THRESHOLD: qualitative: "balance the total coverage of copper on both
  sides" of a double-sided board.
- WHY: differential strain → board warp (etch stress relief, thermal
  expansion); also assists plating.
- WHERE: PDF p.71, §2.2.3.
- MACHINE FORM: report |Cu_area_front − Cu_area_back| / board_area; warn
  above ~30–40% imbalance (knob).
- APPLICABILITY: double-sided; matters more as boards grow.

### P9 — Gridded ground for planeless double-sided boards
- THRESHOLD: qualitative but explicit: grid "can approach the performance
  of a ground plane"; a well-designed grid beats a poorly designed plane;
  NOT advisable for sensitive analog where you must control return paths;
  ground bus acceptable at low frequency/gain/current with high signal
  levels.
- WHY: several parallel current paths minimize common-impedance sections
  and inductance; regular IC layouts suit it best.
- WHERE: PDF p.71–72, §2.2.4.
- MACHINE FORM: GND-mesh metric: count independent loops in the routed
  GND graph (cyclomatic number) and max tree-path length between any two
  GND pads; propose stitching links where the grid is open. This is the
  book's core prescription for PCBSmith's 2-layer no-pour class.
- APPLICABILITY: digital/mixed 2-layer boards (thermometer, servo).

### P10 — Ground plane interruption rules (when pours/planes exist)
- THRESHOLD: individual holes harmless; **large slots divert return
  current** and raise inductance; interruptions tolerable only if they
  don't cut under tracks carrying high di/dt; "even a very narrow track
  interconnecting two segments of ground plane is better than none";
  HF return current concentrates under its signal track (least-flux path).
- WHY: return current wants to flow under the signal; slots force detour
  loops.
- WHERE: PDF p.72–73, §2.2.4 Figs 2.21–2.22.
- MACHINE FORM: (future pour work) slot-under-track check: project each
  high-di/dt track onto the return plane/pour and flag crossings of
  voids/slots.
- APPLICABILITY: boards with pours; deferred until pour analysis lands.

### P11 — Thermal relief: break pads out of copper areas
- THRESHOLD: connect a soldered pad to any large copper area via "one or
  more short lengths of narrow track" (spoke pattern); not needed for
  internal planes (PTH barrel adds thermal resistance).
- WHY: plane acts as heat sink during soldering → cold joints.
- WHERE: PDF p.73–74, §2.2.4 Fig 2.23.
- MACHINE FORM: when pours arrive: thermal-relief-required attribute on
  soldered pads joined to pours ≥ area threshold.
- APPLICABILITY: pour-bearing boards; exception: thermal pads that NEED
  solid connection (module EPs) — keep as explicit override.

### P12 — Four-layer stack: planes inside, close together
- THRESHOLD: planes on inner layers for ~"90% of designs"; the closer the
  power/ground planes, the better the distributed capacitance; outer
  planes only for low-component, track-dense boards (backplanes).
- WHY: component pads/leads pierce an outer "screen" anyway; inner plane
  pair gives inductance-free HF decoupling.
- WHERE: PDF p.74, §2.2.4 Fig 2.24.
- MACHINE FORM: stackup policy knob when PCBSmith grows 4-layer support.
- APPLICABILITY: future 4-layer topologies.

---

## 3. Digital switching noise and decoupling (Ch6)

### D1 — Ground bounce budget
- THRESHOLD: worked numbers: 74AC edge 1.6 V/ns into 30 pF ≈ 50 mA pulse;
  50 mA/ns through 20 nH (≈1 inch of track) = **1 V spike** — at the
  noise margin of fast logic. Octal bus switching #FF→#00 can exceed 1 A
  through the ground pin.
- WHY: ground-line spikes trip innocent gates; supply-side spikes are
  more forgivable (high-level noise immunity).
- WHERE: PDF p.269–270, §6.1.3.
- MACHINE FORM: per-IC ground-stub inductance estimate (20 nH/in × routed
  GND path length to the grid/plane) × di/dt class of the device →
  bounce estimate vs family noise margin; flags long ground necks on
  bus-driver ICs (74HC595s!).
- APPLICABILITY: shift registers, bus drivers, MCUs on planeless boards.

### D2 — Decoupling capacitor distance
- THRESHOLD: "close" = **< 0.5 inch (12.7 mm) for fast logic** (74AC,
  ECL, bus drivers), relaxing to "several inches" for slow CMOS (4000B).
  Too-long path ⇒ high-Q LC that rings "worse than no decoupling at all".
- WHY: capacitor must supply the edge current through minimal inductance.
- WHERE: PDF p.270–271, §6.1.4.
- MACHINE FORM: decoupling-proximity check: routed loop length (VCC pin →
  cap pad → GND pin) per IC vs speed-class budget; PCBSmith places
  100 nF per IC already — check the ROUTED loop, not just placement
  distance.
- APPLICABILITY: every logic IC; budget by family speed.

### D3 — Decoupling value and type
- THRESHOLD: value from C = I·t/ΔV (example: 0.4 A × 6 ns / 0.4 V =
  6 nF); recommended standard **10–100 nF, good compromise 22 nF**;
  smallest chip package best (0805/0603/0402) — lead inductance rules,
  not capacitance. Guidelines table: one 22 µF bulk per board; 1 µF per
  10 SSI/MSI packages or per 2–3 LSI; 10–100 nF per supply pin of
  multi-pin LSI, per octal/MSI package, per 4 SSI packages; plus
  10–47 µF at board power entry (kHz components) and 1–2 µF tantalums
  spread around (MHz ripple).
- WHY: matched reservoir hierarchy per frequency band.
- WHERE: PDF p.271–273, §6.1.4.
- MACHINE FORM: BOM-synthesis rule in composition: decoupling census per
  board (bulk at entry + per-IC ceramics + per-zone µF) — checkable as a
  design check counting caps per package class.
- APPLICABILITY: all digital/mixed topologies; already close to PCBSmith
  practice — encode the census so it can't regress.

### D4 — High-pin-count ICs: caps under the package / opposite side
- THRESHOLD: for very fast, high-current ICs the cap goes "underneath the
  chip, on the opposite side of the board", connected by vias between
  the device pads.
- WHY: package lead inductance already significant; only via length
  remains.
- WHERE: PDF p.272, §6.1.4.
- MACHINE FORM: placement rule: allow/prefer back-side decoupling under
  declared fast ICs on double-sided boards (dual-side placement machinery
  exists from flyback compaction).
- APPLICABILITY: MCU/RF modules; quantitative both-side placement
  guidance — this is the book's concrete use-the-back-side case.

### D5 — Unused inputs never float
- THRESHOLD: ALL unused CMOS inputs tied to VCC or GND, directly (no
  resistor needed unless supply is noisy).
- WHY: floating CMOS input sits in the linear region → class-A current
  drain, oscillation; preset/clear pins spike-sensitive.
- WHERE: PDF p.273, §6.1.5.
- MACHINE FORM: schematic check: no CMOS input pin left with no net
  (PCBSmith no-connect machinery already first-class — extend to
  require NC be a deliberate marker only on outputs/unused functions,
  inputs must have a net).
- APPLICABILITY: every logic part; already partially enforced via ERC.

### D6 — Analog/digital segregation and the single ground link
- THRESHOLD: separate analog and digital grounds joined at exactly ONE
  point — at the ADC for single-board/single-converter systems, at the
  PSU for multiboard; **no digital tracks traversing the analog section**
  and vice versa; never extend a digital ground plane over the analog
  section (capacitive coupling). Context: digital ground noise is tens
  to hundreds of mV; 12-bit/10 V LSB is 2.4 mV.
- WHY: quantization resolution vs ground noise; crossing tracks couple.
- WHERE: PDF p.274–276, §6.2.1 Fig 6.13, Table 6.1.
- MACHINE FORM: zone check: declare analog-region polygon + analog net
  set; flag (a) >1 tie point between AGND and DGND trees, (b) any
  digital-net copper inside the analog polygon.
- APPLICABILITY: ADC/sensor topologies (SHT31 I2C is digital, but the
  rule governs future true-analog front ends).

### D7 — Slow/analog edges into logic need hysteresis
- THRESHOLD: ordinary gate inputs need slew faster than ~5 V/µs; slower
  edges → comparator or Schmitt trigger, never a plain gate.
- WHY: ripple riding a slow edge multi-triggers the gate.
- WHERE: PDF p.272 (Fig 6.11), p.276, §6.2.2.
- MACHINE FORM: composition rule: RC-filtered or sensor-derived signals
  entering logic must pass a Schmitt/comparator role (topology
  validation, not geometry).
- APPLICABILITY: button debounce, threshold detectors — the servo/NE555
  family.

---

## 4. Passive real-world behavior affecting placement (Ch3)

### C1 — Electrolytic lifetime doubles per 10 °C cooler
- THRESHOLD: **life ×2 for each 10 °C drop** in operating temperature
  (non-solid aluminum electrolytics, drying-out mechanism); typical
  rating −40..85 °C, extended 105/125 °C. Ripple current heats the cap
  through ESR; ESR worsens dramatically below 0 °C (impedance ratio
  3–4× typical).
- WHY: electrolyte dry-out is the dominant PSU failure mode ("prime
  cause of power supply failure", §7.2.10).
- WHERE: PDF p.130–131, §3.3.3; p.340, §7.2.10.
- MACHINE FORM: placement check: electrolytic body-to-hot-part clearance
  (hot = regulator/power resistor/transformer roles with computed
  dissipation above threshold); pair with T4 (hot parts at edge). Knob:
  min clearance mm as f(neighbor watts).
- APPLICABILITY: any board with electrolytics + dissipators — AP2112
  near sensor case is the live example.

### C2 — Reliability derating: capacitor failure ∝ V⁵
- THRESHOLD: run a capacitor at **half rated voltage → 32× lower failure
  rate** (fifth-power law); resistors: ≥2× power derating normally
  enough; overall equipment failure rate ~doubles per 10 °C (Arrhenius,
  0.5 eV activation).
- WHY: quantified derating payoff.
- WHERE: PDF p.424–425, §9.5.3.
- MACHINE FORM: BOM check already partially exists (voltage margins);
  encode explicit derating factors: cap V_rated ≥ 2×V_applied preferred /
  ≥1.5× floor; resistor P_rated ≥ 2×P_dissipated.
- APPLICABILITY: all component selection in calculators/composition.

### C3 — Class-2 ceramic capacitance is a moving target
- THRESHOLD: X7R ±15% over temp, tan δ 0.025; Y5V/Z5U +22/−82% and
  +22/−56% over their (narrower) ranges; C0G/NP0 near-zero tempco,
  tan δ 0.001. (EIA 198 letter code table given.)
- WHY: timing/filter/load-cap values in Y5V drift wildly; C0G for
  crystal load caps and precision timing.
- WHERE: PDF p.126–127, §3.3.2 Table 3.5.
- MACHINE FORM: component-card check: dielectric class recorded as
  evidence; design check that crystal load caps / timing caps are
  C0G-class, decoupling may be X7R/Y5V.
- APPLICABILITY: all ceramic cap selection.

### C4 — Capacitor self-resonance; parallel small ceramics
- THRESHOLD: 47 µF tantalum SRF ≈ 500 kHz; 100 pF C0G chip ≈ 100 MHz;
  above SRF the cap is a lossy inductor. Parallel electrolytic +
  ~10 nF ceramic (SRF 10–100 MHz) for wideband; beware inter-component
  resonance.
- WHY: ESL from lead length INCLUDING connecting track — layout is part
  of the component.
- WHERE: PDF p.137–138, §3.3.9.
- MACHINE FORM: same as D2 (routed loop length into the ESL estimate);
  composition rule: bulk cap must be paired with local ceramic.
- APPLICABILITY: decoupling networks, SMPS output filters.

### C5 — Inductors: magnetics saturate, couple, and heat
- THRESHOLD: qualitative in this book (saturation/hysteresis B-H, wide
  tolerance, Curie point); no orientation-spacing numbers given.
- WHY: field-coupling between wound components is real but this book
  handles it under ground loops (G6: "reduce flux normal to the loop...
  toroidal transformer") rather than as a placement distance table.
- WHERE: PDF p.138–139, §3.4.1; p.14, §1.1.4.
- MACHINE FORM: placement hint only: keep wound components (transformer,
  power inductor roles) away from and orthogonal to loop-sensitive
  circuits; no defensible number from this source — mark `assumption`
  until a better reference (Ott) supplies one.
- APPLICABILITY: SMPS topologies (flyback).

### C6 — Crystal circuit layout
- THRESHOLD: total strays budget: amplifier input + pc track capacitance
  "at most 10 pF with good layout"; C2:C1 ≈ 3:1; Rf 10–15 MΩ; AT-cut
  drive ≤ 0.5–1 mW; design series-mode startup for 3× quoted motional R.
- WHY: extra capacitance across the crystal raises loop gain/instability;
  logic switching coupled into the high-impedance nodes causes jitter.
  Stated layout rules: minimize capacitance across the crystal; **ground
  traces around the crystal to buffer other tracks are advisable; on no
  account route logic signals near or through the oscillator circuit**.
- WHERE: PDF p.157–159, §3.5.2 ("Layout").
- MACHINE FORM: oscillator-zone check: declare crystal + load caps + MCU
  XIN/XOUT as a zone; forbid foreign switching nets inside/crossing it;
  optional guard-trace requirement around the zone; keep XIN/XOUT track
  length short enough that est. C_track (≈0.5–0.8 pF/cm) keeps total
  strays ≤ 10 pF.
- APPLICABILITY: any topology with a crystal/resonator (RTC, MCU).
  Note 32.768 kHz tuning-fork: −0.04 ppm/°C² parabolic, turnover 25 °C —
  keep it AWAY from hot parts if timekeeping matters (p.159, §3.5.3).

---

## 5. Analog IC layout (Ch5)

### A1 — Op-amp/comparator stability by layout
- THRESHOLD: comparator: stray feedback ≥ ~2 pF is hard to avoid; keep
  drive impedance **< 10 kΩ, preferably 10× lower** (2 pF·10 kΩ pole =
  8 MHz oscillation). Op-amp inverting-input stray 3–5 pF with normal
  layout. Capacitive loads: isolate with 10–100 Ω series R; CF ≈ 20 pF.
- WHY: output-to-noninverting-input coupling is positive feedback; rules:
  keep feedback/input components close to the amplifier, separate input
  and output components, short direct tracks, ground plane/shield tracks
  for sensitive circuits; don't run the output track back past the
  inputs.
- WHERE: PDF p.228–231, §5.2.10; p.252, §5.3.
- MACHINE FORM: proximity rule: feedback-network parts within X mm of
  their op-amp pins (placement check keyed by topology roles);
  parallelism check (P4) between output net and +input net.
- APPLICABILITY: LMV431/feedback chains, comparators, future analog
  front ends.

### A2 — Input guarding for high-impedance nodes
- THRESHOLD: guard ring connected to a low-impedance point at the same
  potential, on BOTH sides of a double-sided board; guard width
  unimportant for surface leakage, wider helps bulk.
- WHY: surface leakage varies with contamination/humidity; guard absorbs
  it before it reaches the high-Z node.
- WHERE: PDF p.85–86, §2.4.1 Fig 2.32.
- MACHINE FORM: topology-declared guard nets: generator emits a ring
  around declared high-Z pads on both layers; check ring continuity and
  correct driving potential.
- APPLICABILITY: pH probes, photodiode/electrometer inputs, >10 MΩ
  timing nodes — future topologies.

---

## 6. Power supply layout and regulator thermal design (Ch7)

### S1 — Reservoir capacitor connection: take all grounds from the cap
- THRESHOLD: worked example: peak ripple current ≈ 5× DC load; 10 mΩ of
  common track × 5 A peaks = 50 mV hum between grounds A and B, "at no
  additional cost". Bigger reservoir makes it WORSE (higher peaks).
  Diagnostic given: pulse-shaped output ripple = wiring problem,
  sawtooth = insufficient smoothing.
- WHY: transformer-diode-capacitor charging loop must not share copper
  with any load return; ground all supplied circuits on the supply side
  of the reservoir; residual common impedance = the cap's own ESR.
- WHERE: PDF p.343–344, §7.2.12 Figs 7.13–7.14.
- MACHINE FORM: rectifier-loop isolation check: identify the
  rectifier/reservoir charging loop nets; assert no other net's return
  path shares a copper segment with that loop (routed-tree walk, same
  engine as G2).
- APPLICABILITY: any AC-input or charge-pulse supply (flyback primary
  reservoir!); general form applies to SMPS input caps.

### S2 — Three-terminal regulator capacitors
- THRESHOLD: 78XX-class: **0.33–1 µF at input (stability), ~0.1 µF at
  output (transient response/HF noise)**.
- WHY: regulator oscillates without input cap; output cap trims transient
  response. (For AP2112-class LDOs the datasheet values govern — same
  structural rule.)
- WHERE: PDF p.345, §7.2.13.
- MACHINE FORM: composition census: regulator role requires input cap and
  output cap components within decoupling distance (D2 check applies).
- APPLICABILITY: every linear-regulator topology; already PCBSmith
  practice — encode as check.

### S3 — Regulator dissipation: worst case is not always full load
- THRESHOLD: peak series-pass dissipation occurs at less than full load
  when I_L·Rs > 0.5(V_oc − V_out); dropout can eat >50% of output power
  at low V_out; check low-load + max input for component VOLTAGE ratings
  (transformer regulation can exceed 20%).
- WHY: the calculator must sweep the input range and load range, not
  evaluate one corner.
- WHERE: PDF p.338–339, §7.2.8–7.2.9 Fig 7.11.
- MACHINE FORM: calculator discipline: report P_reg at (V_in_max,
  I_load_max), (V_in_max, I at peak-dissipation point), and V_ratings at
  (V_in_max, no load). Assert all three in hand-check tests.
- APPLICABILITY: linear regulator design chains (AP2112 card).

### S4 — Reservoir/rectifier ratings from ripple current
- THRESHOLD: C = I_L·t/V_ripple with t ≈ 8 ms (50 Hz FW) / 6 ms (60 Hz);
  RMS ripple current 2–3× DC load; worked example: 2 A load wanted
  5300 µF but ripple rating forces 22,000 µF, two parallel, or derating;
  rectifier rating ≥ full load current, preferably 2×; bridge
  I_rms = 1.8·I_dc, center-tap 1.2·I_dc.
- WHY: ripple current heating, not capacitance, sizes reservoir
  electrolytics above ~1 A.
- WHERE: PDF p.340, §7.2.10 Fig 7.9.
- MACHINE FORM: calculator check: chosen reservoir cap's I_R rating ≥
  computed RMS ripple at rated temperature (evidence-backed from
  datasheet); already the pattern used for flyback — generalize.
- APPLICABILITY: all rectifier-reservoir supplies.

### S5 — Switch-mode noise containment
- THRESHOLD: SMPS output ripple/noise typically **1% of rail, 100–200 mV**,
  significant harmonics to ≥10 MHz, often common-mode; differential
  spikes cut "dramatically" by series ferrite bead + small ceramic
  across the output cap.
- WHY: ESR/ESL of the output filter caps and ground-wiring inductance
  pass the edges; sensitive analog with bandwidth above the switching
  frequency suffers.
- WHERE: PDF p.343, §7.2.12.
- MACHINE FORM: composition option: post-filter (bead + ceramic) role on
  SMPS outputs feeding analog zones; layout: keep the loop
  switch-diode-cap minimal (see E9 loop-area metric).
- APPLICABILITY: buck/flyback outputs feeding sensors or amps.

---

## 7. Thermal management and placement (Ch9.6, Ch2.3.4)

### T1 — Junction temperature arithmetic is the design gate
- THRESHOLD: T_j = P_D·(ΣRθ) + T_A ≤ T_j(max); worked example: IRF640
  "rated" 125 W can only dissipate 35 W at T_A = 70 °C even on a
  0.5 °C/W heatsink (that heatsink ≈ 80 in² of area). Ratings are quoted
  at 25 °C case — "rely on derating curves, not the front-page watts".
- WHY: the absolute maximum power rating is a 25 °C-case fiction.
- WHERE: PDF p.430–432, §9.6.1.
- MACHINE FORM: per-dissipator design check: compute T_j from component
  card Rθj-a (or Rθj-c + attach model) at worst ambient; blocker if over
  datasheet limit, warning above a derated fraction (e.g. 0.8·T_j_max).
- APPLICABILITY: regulators, drivers, power resistors — every topology.

### T2 — Interface/mounting thermal resistances (TO-220 class)
- THRESHOLD: table: TO-220 metal-to-metal dry 1.2, greased 0.6; with
  2-mil mica 3.4 dry / 1.6 greased; 6-mil silicone rubber 1.8 °C/W;
  TO-3 dry 0.5 / greased 0.1. Mounting force ≥ 20 N; grease applied
  thinly (more is worse); vertical fins; horizontal mounting costs up to
  30% efficiency; black anodizing improves radiation 10–15× over
  polished; Rθ falls ~20% from 10 °C to 20 °C differential; altitude
  derates convection (90% at 5000 ft).
- WHY: attach quality dominates small heatsink budgets.
- WHERE: PDF p.435–441, §9.6.2–9.6.3 Tables 9.4–9.5.
- MACHINE FORM: attach-model library constants for the T1 check when a
  topology declares a heatsink + washer stack.
- APPLICABILITY: THT power stages; flyback-class boards.

### T3 — Parallel devices halve the per-junction rise
- THRESHOLD: two devices sharing the power → each junction rise halves
  (same Rθ each, half the heat flow each); stated as far cheaper than a
  bigger heatsink.
- WHY: thermal resistances in parallel.
- WHERE: PDF p.432, §9.6.1.
- MACHINE FORM: calculator suggestion path when T1 fails: propose N-way
  parallel output devices before proposing heatsink growth.
- APPLICABILITY: linear pass elements, LED ballast resistor banks.

### T4 — Thermal placement rules (the placement-engine payload)
- THRESHOLD/RULES (all stated, PDF p.442, §9.6.4):
  1. Mount PCBs vertically where possible; don't block airflow.
  2. **Hot components near the edge of the board**; if vertical, at the
     TOP of the board.
  3. **Keep hot components as far as possible from sensitive devices
     (precision op-amps) and high-failure-rate parts (electrolytic
     capacitors)**; put hot parts ABOVE such components if vertical.
  4. Heatsink near the air OUTLET, not the inlet (don't preheat the
     enclosure's air).
  5. High heat density → thermal ladder to board edge (FR4 conducts
     poorly).
  6. Sealed case = three convection stages; prefer conduction to case.
  Plus §2.3.2 (p.84): "precision components should not be next to ones
  that dissipate power."
- WHY: convection geometry + component reliability (C1, C2 Arrhenius).
- WHERE: PDF p.442, §9.6.4; p.84, §2.3.2.
- MACHINE FORM: placement scoring terms: (a) dissipator-to-edge distance
  reward, (b) pairwise penalty matrix hot-role × sensitive-role
  (electrolytic, crystal, precision-analog, temperature SENSOR) with
  distance thresholds as knobs, (c) orientation attribute if the intent
  declares vertical mounting.
- APPLICABILITY: every placement run. For the thermometer: AP2112 (and
  LED column) vs SHT31 is exactly rule 3 — a temperature sensor is the
  ultimate "sensitive device"; self-heating from neighbors corrupts the
  measurement itself, not just reliability.

### T5 — PCB copper as heatsink: NOT quantified in this book
- FINDING: the book has no copper-area-per-watt tables for SOT-23/
  SOT-89/SOT-223/DPAK-class packages (all four SOT mentions checked —
  package-pinout context only). Its thermal machinery is Rθ arithmetic
  (T1), conduction formula Rθ = L/kA (PDF p.87, §2.3.4), and the note
  that "PCB laminates have low thermal conductivity" (p.442). §7.4.2
  (p.354) only insists heat-sinking needs are positioned for airflow.
- MACHINE FORM: source SMD pad-as-heatsink area curves from vendor
  datasheets/appnotes per component card (AP2112 card should carry its
  own θja vs copper-area evidence); do not cite Williams for this.
- APPLICABILITY: honest-evidence discipline — mark the source gap.

---

## 8. EMC at board level (Ch8)

### E1 — Radiated emission scales with loop area and f²
- THRESHOLD: E = 131.6×10⁻¹⁶·(f²·A·I)/d V/m for a loop (far field);
  conductors approaching λ/4 (**1 m at 75 MHz**) stop being electrically
  small and couple efficiently.
- WHY: loop area × current × frequency² is the emission budget; the
  layout lever is A.
- WHERE: PDF p.383, §8.3.2.
- MACHINE FORM: loop-area metric (same computation as G6) applied to
  clock and switch-node nets vs their returns; report A·f² ranking of
  worst nets.
- APPLICABILITY: SMPS switch loops, clocks, bus groups.

### E2 — Slowest logic that works; series resistor on fast clocks
- THRESHOLD: 5 MHz clock, 8 ns vs 1 ns rise: ~**20 dB difference at
  200 MHz**; remedy: "a resistor of a few tens of ohms in series with
  the clock driver output"; keep fast clocks local; lowest clock
  frequency that does the job.
- WHY: harmonic envelope corner at 1/πt_r; slower edges kill the
  high-order harmonics where radiation is efficient.
- WHERE: PDF p.383–384, §8.4.1 Fig 8.9.
- MACHINE FORM: composition knob: series-R role (22–47 Ω) on declared
  clock/latch lines leaving a local zone (SRCLK/RCLK to the 74HC595s
  qualify); intent-level logic family choice note.
- APPLICABILITY: digital topologies with off-chip clocks.

### E3 — EMC layout checklist (board items)
- THRESHOLD/RULES (stated, PDF p.401, §8.8): segregate interference
  paths from sensitive circuits; minimize ground inductance with
  unbroken plane or ground GRID; **minimize loop areas in high-current
  or sensitive circuits**; minimize track and component leadout lengths;
  RF-decouple supplies; RC-limit signal bandwidths; resistor-buffer long
  clock/data lines; watchdog on every micro; earth straps length/width
  **< 3:1**.
- WHY: consolidated board-level EMC prescription; "majority of
  postdesign interference problems trace to poor grounding" (p.383).
- WHERE: PDF p.401–402, §8.8; p.383, §8.4.
- MACHINE FORM: umbrella — each item maps to G8/P9/E1/E2/D2 checks; the
  3:1 strap rule applies to any dedicated chassis-bond copper.
- APPLICABILITY: release-review checklist material for the report stage.

### E4 — Filter layout: capacitor faces high Z, inductor faces low Z
- THRESHOLD: discrete-component filters degrade above ~10 MHz (self
  resonance); larger parts break lower; filter I/O wiring must be kept
  separate (checklist); each filter group needs a good interface ground
  return.
- WHY: a filter whose input and output tracks run adjacent couples
  around itself.
- WHERE: PDF p.393, §8.6.1; p.402, §8.8.
- MACHINE FORM: filter-zone check: input-side and output-side nets of a
  declared filter role must not run parallel within the coupling
  threshold (P4 machinery).
- APPLICABILITY: USB/connector entry filtering, mains filters.

---

## 9. Assembly and producibility (Ch2.3)

### M1 — Soldering process constrains placement geometry
- THRESHOLD: wave soldering: IC packages oriented along board travel,
  rows of pins across the wave (bridging); pad spacing < 0.5 mm risks
  bridges without resist (P3); reflow: orientation not critical, surface
  tension self-aligns; mixed assembly puts SMD and THT on opposite sides;
  wave-side SMD height limited (parts can be washed off).
- WHY: process yield; wave vs reflow demand different pad dimensions.
- WHERE: PDF p.80–83, §2.3.1.
- MACHINE FORM: process attribute on the board (reflow assumed for
  PCBSmith SMD boards); if wave declared: orientation check on
  multi-pin packages + bottom-side height limit check.
- APPLICABILITY: mixed THT/SMD boards.

### M2 — Producibility placement conventions
- THRESHOLD (stated list, PDF p.84, §2.3.2): components on a well-defined
  grid, facing the same way; **all ICs same orientation (pin 1 toward
  the same corner); all polarized parts facing the same way**; uniform
  lead pitch for axial parts; spacing for test probes and insertion
  guides; clear "stacking edge" on one or two board edges; test nodes on
  dedicated ~1 mm pads on the far side from components, never probe on
  component leadouts (p.83–84, §2.3.1).
- WHY: pick-and-place efficiency, inspection speed, probe access; "the
  foremost [factor] is short, direct tracks" — placement iterates with
  routing.
- WHERE: PDF p.83–84, §2.3.1–2.3.2.
- MACHINE FORM: soft placement scoring: reward uniform IC rotation and
  uniform polarized-part orientation (report metric first, hard check
  later); testpoint synthesis rule for nets marked test-required.
- APPLICABILITY: all boards; scoring not blocking (density can override).

### M3 — Silkscreen legend rules
- THRESHOLD: never print over/near a hole or across track/pad edges;
  tent or fill vias in legend areas; polarity marks must be legible WITH
  the component in place; one consistent polarity convention per board
  set.
- WHY: print quality and service usability.
- WHERE: PDF p.85, §2.3.3.
- MACHINE FORM: silk checks exist (height, overlap); add: polarity-mark
  visibility — the marker glyph must fall outside the part's own body
  outline.
- APPLICABILITY: all boards with silk.

### M4 — Large ceramic parts crack on FR4
- THRESHOLD: do not use "the larger ceramic or LCC components" directly
  on epoxy fiberglass; small chips OK; leaded/J-lead packages OK
  (compliant leads).
- WHY: CTE mismatch ceramic vs FR4 cracks the part or its track under
  thermal cycling.
- WHERE: PDF p.83, §2.3.1.
- MACHINE FORM: BOM check: ceramic body length above ~1812-class on FR4
  → warning with derating/compliant-termination note.
- APPLICABILITY: big MLCCs in SMPS input filters — real modern failure
  mode (flex cracking).

---

## Extraction issues and gaps

1. Figure-bound numbers: track current-capacity values (Fig 2.18) and
   track resistance chart (Fig 2.17) are graphics; text extraction gives
   the axes/legend only (0–2.5 mm, 0–8 A, 1 oz/2 oz, 10/20 °C rise,
   source BS6221:Part 3:1984). Encode via IPC-2152/2221 formulas and
   cite both.
2. No copper-pour-per-watt data for SOT-class regulators (T5) — must
   come from component-card datasheet evidence instead.
3. No numeric inductor-to-inductor / transformer-to-circuit spacing
   rule (C5) — Ott (ott-emc cache) is the right source to close this.
4. Double-sided component placement is covered as process capability
   (M1, D4) — the only quantitative both-sides guidance is decoupling
   under the IC (D4) and wave-side height limits (no numbers given).
5. The 4th edition's grounding/decoupling/EMC numbers are unchanged
   Williams 2nd-edition material — ages well; capability table (P1) is
   "at the time of writing" (2016) and our fab profiles already exceed it.

---

## Top 10 most machine-encodable rules (ranked)

1. **T4 hot/sensitive placement matrix** — hot parts to board edge, and
   a pairwise distance penalty hot-role × {electrolytic, crystal,
   precision analog, temperature sensor}. Immediate value for the
   thermometer (AP2112 vs SHT31); pure placement-scoring arithmetic.
2. **D2 routed decoupling-loop length** — VCC pin → cap → GND pin loop
   length vs speed-class budget (12.7 mm fast logic). Routed-tree walk;
   catches regressions the current placement-distance heuristic misses.
3. **G2/S1 common-impedance return walk** — no copper segment shared
   between a high-current return loop (incl. rectifier/reservoir charge
   loop) and a logic/analog return; shared-segment mV budget from track
   resistance. One graph engine serves G2, G4, S1.
4. **P2 current-vs-width per net** — calculator net currents already
   exist; feed IPC-2152 width floors into the router per net. Blocker
   check, fully numeric.
5. **C6 oscillator keep-out zone** — no foreign switching nets crossing
   the crystal zone; stray-capacitance budget ≤ 10 pF; guard-trace
   option. Geometric zone check, thresholds stated in the book.
6. **T1 junction-temperature gate** — T_j from P_D·ΣRθ + T_A_max against
   datasheet limit with derating fraction; component-card evidence
   supplies Rθ. Pure arithmetic per dissipator role.
7. **D6 mixed-signal zone/single-tie check** — one AGND-DGND tie, no
   digital copper inside the analog polygon. Zone + tree-degree check.
8. **D3 decoupling census** — bulk at entry + per-IC ceramic + per-zone
   µF electrolytic, counted per package class. BOM-level check that
   can't false-positive.
9. **P4/E4 parallelism integral** — Σ(parallel length / spacing) between
   aggressor and victim nets, with the 1 mm / 10% rule of thumb as the
   calibration point; also enforces filter in/out separation.
10. **C2 derating check** — cap V_rated ≥ 2× applied (V⁵ law), resistor
    P_rated ≥ 2× dissipated, electrolytic temperature headroom (C1
    ×2/10 °C). BOM arithmetic with datasheet evidence.

---

## Verification (2026-07-12, spot-check, sonnet)

| rule | verdict | note |
|------|---------|------|
| D1 — ground bounce budget | VERIFIED | p0269: "74AC-series gate with a dV/dt of around 1.6 V/ns will require a 50 mA current pulse when charging a 30 pF node capacitance"; "A pulse with a di/dt of 50 mA/ns through a track inductance of 20 nH (one inch of track) will generate a voltage pulse of 1 V peak, which is approaching the noise margin of fast logic." p0270: octal-latch #FF→#00 "current pulse — exceeding an amp in fast systems." All numbers match exactly. |
| D2 — decoupling capacitor distance | VERIFIED | p0270-271: "'Close' in this context means less than half an inch for fast logic, such as 74AC or ECL... extending to several inches for low-current, slow devices such as 4000B-series CMOS." Matches 12.7 mm / relaxed-for-4000B threshold exactly. |
| G7 — wire/track inductance (20 nH/in, 7 nH/cm) | VERIFIED | p0031: "the inductance of a 1 in. length of ordinary equipment wire is around 20 nH and that of a 1 cm length is around 7 nH." Exact match. (Note: the "1 m of 16/0.2 wire = 38 mΩ but 1.5 µH" worked example cited alongside was not located on p0030-31; not one of the 8 spot-checked claims per rule but flagged for a future pass.) |
| P3 — voltage spacing 1 mm/200 V | VERIFIED | p0067: "For a benign environment — dry and free from conductive particles — a spacing of 1 mm per 200 V, allowing for manufacturing tolerances, is adequate for preventing breakdown... Spacings less than 0.5 mm risk solder bridging during wave soldering." Exact match, including the 0.5 mm bridging figure. |
| P4 — crosstalk spacing 1 mm rule | VERIFIED | p0067-068: "a track spacing greater than 1 mm will result in cross talk voltages less than 10% of signal voltages for most board configurations... Cross talk can be reduced by routing ground conductors between pairs of signal lines." Exact match. |
| C1 — electrolytic lifetime doubles per 10 °C | VERIFIED | p0131: "the life of these types can be doubled for each 10°C drop in operating temperature." p0130-131: temp range −40 to 85°C, extended −55 to 105/125°C; impedance ratio "usually around three or four" — all match. |
| C6 — crystal circuit stray/component budget | VERIFIED | p0157: "circuit strays (amplifier input and pc track capacitance, amounting to at most 10 pF with good layout)... ratio C2:C1 should generally be of the order of 3:1... Rf... Generally 10–15 MΩ." p0158: AT-cut "maximum drive level of 0.5–1 mW"; "design the circuit for assured start-up with a three times higher R than quoted." p0159: "on no account route logic signals near or through the oscillator circuit"; 32.768 kHz tuning fork "−0.04 ppm/°C²," turnover "around 25°C." Every number matches exactly. |
| C2 — reliability derating V⁵ law | VERIFIED | p0425: "failure rate increases as the fifth power of the voltage. Therefore, if you run the capacitor at half its rated voltage, you will observe a failure rate 32 times lower." Resistor "factor of 2, which is normally enough" matches "≥2× power derating." p0424: Arrhenius doubling ~10°C rise, activation energy "around 0.5 eV" — exact match. |

8/8 verified; mismatches: none.
