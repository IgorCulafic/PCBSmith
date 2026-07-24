# CONSOLIDATED — machine-encodable rules across the nine sources

Written 2026-07-12 (Claude, PCBSmith developer agent), fulfilling
`routing-placement-plan.md` phase 0. This is the single deduplicated
table of every machine-encodable rule found in
`docs/reference/books/` (bogatin-spi, johnson-hsdd, ott-emc,
montrose-emc, williams-cdc, ipc-2221b, ipc-7351, ipc-a-610,
coombs-pch), organized by the PLAN PHASE each rule serves. Every row
carries its sources with locators and each source's **verification
status** (verified / unverified / OCR-uncertain), the threshold
**evaluated for our board class**, the concrete machine form, and its
implementation STATUS against the rulebook (`docs/pcb-design-rules.md`)
and `design_checks.py` / `virtual_drc.py`.

> **2026-07-14 superseding hold:** do not promote universal courtyard,
> same-bus minimum-spacing, fixed-moat, universal-QFN-retention, or global
> corner claims. The July-14 current-materials knowledge base governs.

Honesty rules obeyed here: contradicting numbers are NEVER averaged —
they are reconciled by identifying what each bounds (see the
Contradiction Docket). OCR-uncertain thresholds stay marked. Every
formula evaluation shows its substitution.

## Our board class — the shared screen (evaluate once)

2-layer, 1.6 mm FR-4, 3.3–5 V logic, edges **>= 3 ns** (slowest
allowed), clocks **<= 50 MHz**, I2C/SPI/USB-FS; plus the **mains
flyback** exception (171–250 V DC-peak primary). FR-4 microstrip
signal speed **v ≈ 150 mm/ns** (6 in/ns; 170 ps/in). Dielectric height
to a back-side pour **h ≈ 1.6 mm**.

| Screen quantity | Formula | Value at RT = 3 ns | Source (status) |
|---|---|---|---|
| Bandwidth (emission/decoupling knob) | BW = 1/(π·RT) | **106 MHz** | ott (verified) |
| Bandwidth (Bogatin usage) | 0.35/RT | 117 MHz | bogatin (verified) |
| Knee (conservative "flat-enough" screen) | Fknee = 0.5/RT | 167 MHz | johnson HSDD-K1 (verified) |
| Edge spatial extent l | RT·v | 450 mm (~18 in) | bogatin R3, johnson (verified) |
| Lumped cutoff / max unterminated | l/6 ≈ 25.4·RT[ns] mm | **76 mm** | bogatin R4, johnson K2 (both verified, agree — CB2) |
| Crosstalk saturation length | ½·RT·v | 225 mm | bogatin R13 (verified) |
| Bypass cooperation radius | l/12 | 37 mm | johnson P2 (verified) |
| H-aware crosstalk spacing for <3% | D > h·√((1/x)−1), x=0.03 → D>5.7h | **9.1 mm** c-c | johnson X1 (verified) |

**What the numbers force for our class:** on boards <= ~100 mm, with
3-ns edges, reflections/terminations/via-parasitics/corners are all
DORMANT (every trace is < 76 mm lumped). The LIVE risks are exactly
four: **crosstalk on long parallel runs, return-path continuity,
decoupling loop area, and connector/cable EMI.** Every threshold below
still carries its formula so the checks stay valid if a sub-1-ns part
ever lands.

---

# Phase 1 — IPC audit fixes (cheap, do immediately)

### P1-1. Voltage-banded electrical clearance (replace flat 0.2 mm)
- SOURCES: ipc-2221b Table 6-1 (PDF p.69, **verified**); ipc-a-610 R2
  Appendix A (PDF p.429-430, **verified**, = same table); williams P3
  "1 mm / 200 V" (p.67, **verified**) as the sub-mains corroborator.
- THRESHOLD for our class (DC-or-AC-peak between conductors): coated
  copper track-to-track uses **B4**; uncoated pad/land-to-foreign-copper
  uses **A6**. B4: 0.05 mm (0–30 V), 0.13 mm (31–100 V). A6: 0.13 mm
  (0–15 V), **0.25 mm (16–30 V), 0.4 mm (31–50 V), 0.5 mm (51–100 V)**.
  Flyback primary 171–250 V: B3 (uncoated, altitude) = **6.4 mm** —
  the cell our declared barrier already uses. Our current flat
  `CLEARANCE_MM = 0.2` is SAFE for coated ≤100 V but **LOOSER than A6
  for any pad-to-foreign net > 15 V** (24 V rails want 0.25–0.5 mm).
- MACHINE FORM: `DesignChecksSpec` gains per-net worst-case voltage;
  clearance check keys pad-pad on A6 column, track-track on B4 column;
  0.2 mm stays the floor for ≤15 V logic.
- STATUS: **propose-new** (plan 1.2). Existing `CLEARANCE_MM`
  constant is the thing being upgraded.

### P1-2. Trace-current model and citation
- SOURCES: IPC-2221B section 6.2 (PDF p.68, **verified**) defers to
  IPC-2152; the existing `I = 0.048*dT^0.44*A^0.725` external fit is the
  legacy IPC-2221A Figure 6-4 curve. Brooks/Adam Ch.5 (second-wave SW-B1,
  text-verified against `p0062`-`p0071` and mechanism at `p0116`) reports
  IPC-2152's internal traces may run cooler than equivalent external traces
  because dielectric conduction can exceed surface convection/radiation.
  IPC-A-610 R22 (**verified**) supplies a separate 20% width-damage budget.
- THRESHOLD for our class: the legacy external fit may remain only as a
  labeled interim at dT=10 C and 35 um. Do not add k=0.024 as a future
  internal authority. IPC-2152 is now pinned but remains no longer maintained;
  use it only as historical measured validation while selecting a separately
  versioned model with explicit layer, copper, environment, stackup/plane and
  temperature-rise inputs.
- MACHINE FORM: label current results legacy_ipc_2221a_external_fit; expose
  model/profile and evidence; keep damage allowance separate. Unknown and
  near-limit cases stay advisory/needs-review.
- STATUS: the current trace_current check still needs the model-label change;
  no evidence-backed replacement thermal model is implemented.

### P1-3. Rulebook section 10 barrier citation fix
- SOURCES: IPC-2221B audit (**verified**) shows section 10.1's
  pollution-degree citation is wrong: IPC-2221B has no such table. Table 6-1
  B3 gives 6.4 mm at 171-250 V specifically for uncoated operation above
  3050 m. IEC 62368-1 or the applicable end-product safety standard must
  determine pollution degree, CTI, insulation type, clearance, and creepage.
- MACHINE FORM: text-only edit to rulebook §10.1 wording; value
  unchanged.
- STATUS: **exists** (§10.1 value); citation is the fix (plan 1.3).

### P1-4. Annular-ring minimum (land = a + 2b + c)
- SOURCES: ipc-2221b §9.1.1 + Tables 9-1/9-2 (PDF p.107-109,
  **verified**).
- THRESHOLD for our class (Class 2): land_min = max_hole + 2·ring + c.
  External supported ring b = 0.05 mm; fabrication allowance c =
  **Level B 0.25 / Level C 0.2 mm**. Our via (0.6 mm land / 0.3 mm
  drill) satisfies the equation only at **Level C** (0.3+0.1+0.2=0.6)
  — legal but must be declared; a Level-B fab wants 0.75 mm pads on
  0.3 mm holes.
- MACHINE FORM: new `annular_ring` check over every PTH pad/via keyed
  on a declared producibility level; flag Level-C-only geometry.
- STATUS: **propose-new** (plan 1.4).

### P1-5. Component body-to-edge >= 1.5 mm
- SOURCES: ipc-2221b §8.1.2 (PDF p.86, **verified**).
- THRESHOLD: component body (or land-pattern edge on leaded sides) >=
  **1.5 mm** from board outline. We only police *copper*-to-edge
  (0.5 mm) today; this is the body clearance for placement/solder/test.
- MACHINE FORM: new `component_edge_clearance` check (body hull vs
  outline).
- STATUS: **propose-new** (plan 1.4).

### P1-6. Residual laminate between holes >= 0.5 mm
- SOURCES: ipc-2221b §9.2.7 (PDF p.113, **verified**); coombs §5.3
  (drill fragility, **verified** direction).
- THRESHOLD: hole-edge-to-hole-edge >= **0.5 mm** (in addition to land
  spacing).
- MACHINE FORM: new hole-edge spacing check next to the existing
  `~hole:` obstacle machinery.
- STATUS: **propose-new** (plan 1.4).

### P1-7. Copper-to-board-edge margin (depanel + haloing)
- SOURCES: ipc-a-610 R21 (PDF p.368/p.362, **verified**): edge damage
  acceptable up to 50% of the edge-to-conductor distance or 2.5 mm;
  williams P7 (≥0.5 mm, **verified**); coombs §4.1 (routed edges expose
  glass, **verified** mechanism).
- THRESHOLD: trace/pour-to-edge **>= 0.5 mm** design floor so a
  50%-depth nick still leaves the 0.25 mm class margin.
- MACHINE FORM: generalize the existing via-edge margin to all copper
  → `copper_edge_margin` virtual check.
- STATUS: **partially exists** (via edge margin on shaped outlines,
  §5.3) — generalize to tracks/pours.

### P1-8. Solder-mask dam / sliver
- SOURCES: ipc-2221b Table 4-16 (PDF p.49, **verified**): LPI 0.051 mm
  clearance / **0.1 mm dam**; coombs §36.4.4.2 (2.5–3.0 mil typical,
  **verified**); ipc-7351 audit (LPI matches).
- THRESHOLD: warn when the gap between adjacent mask openings < **0.1 mm**
  (merge to gang-relief); bites at 0.5 mm-pitch parts (0.3 mm pads →
  0.2 mm gap is OK; below 0.1 mm dam is lost).
- MACHINE FORM: new `mask_sliver` warning on fine-pitch footprints.
- STATUS: **propose-new**.

---

# Phase 2 — bus routing + crosstalk spacing (the core machinery)

### P2-1. Spacing CLASSES — the bus-routing decision (see Docket #1)
- SOURCES: montrose §1.1 3-W (PDF p.150, **verified**); bogatin R11/R12
  edge-gap ≥ 2W ↔ NEXT 5/2/1% at s=w/2w/3w (10.11, **verified**, with
  its own large-h caveat); johnson HSDD-X1 crosstalk ≤ 1/(1+(D/H)²),
  1–3% band (PDF p.209, **verified**); montrose §1.4 Eq 4.24
  `K/(1+(D/H)²)` (**verified**); NXP AN2536 4W + edge≥3h (research
  digest, **[MED]**, unverified); coombs §6.2 NEXT/FEXT flatten
  ~7 mil (0.18 mm, **verified** direction).
- THRESHOLD for our class — **three classes** (resolution of Docket #1):
  - **Same-bus intra-bundle:** no global exemption. Manufacturing minimum
    requires per-bus edge/switching/timing/noise/EMC/coupled-length and
    stackup evaluation.
  - **Generic foreign logic net** near a bundle: **≥ 3W centerline**
    (0.6 mm at a 0.2 mm trace) as a CRAFT floor (montrose ~70% flux).
    Honesty caveat: on our thick 2-layer dielectric 3W does NOT prove
    <3% coupling (bogatin R11 caveat) — it is a readability/area floor,
    not a coupling guarantee.
  - **Sensitive victim** (clock/periodic aggressor, analog, reset,
    crystal, high-Z feedback, I2C near a switch node): **≥ 5.7h ≈
    9.1 mm center-to-center** WITH a continuous back-side GND pour
    under the run (johnson X1 for <3% at h=1.6 mm); without a pour,
    worse — move the aggressor to the opposite layer or add a stitched
    guard (P2-4). Substitution: 1/(1+(D/1.6)²) = 0.03 → D = 1.6·√(32.3)
    = 9.1 mm.
- MACHINE FORM: `bus_groups` net classes with per-class spacing;
  `crosstalk_spacing` virtual check accumulating parallel-run length ×
  the class rule (see P2-3 for severity scaling).
- STATUS: **propose-new** (plan 2.3, rulebook candidate 11.8).

### P2-2. Bus-bundle coherence
- SOURCES: research digest §2 (**[HIGH]** craft, not SI); montrose §1.6
  parallelism discipline (**verified**); johnson HSDD-T3 (never bundle a
  bus away from its return, **verified** ratios).
- THRESHOLD: declared buses may route as bundles. Coherence remains a
  reported metric until the bus supplies an evidence-backed threshold.
- MACHINE FORM: `route_board(bus_groups=...)`; new `bundle_coherence`
  check; followers validated against the SAME blocked sets, A* fallback
  logged (no silent degradation).
- STATUS: **propose-new** (plan 2.1-2.3, rulebook candidate 11.6).

### P2-3. Crosstalk severity scaling (turns spacing binary → quantitative)
- SOURCES: bogatin R13 saturation length + R12 NEXT table (10.8/10.11,
  **verified**); johnson HSDD-X3 near/far split (**verified**, mostly
  dormant for us since nets are lumped).
- THRESHOLD for our class: severity = min(1, coupled_len /
  (RT·v/2)) × NEXT_table(s/w) × swing, saturating at **225 mm**
  (½·3·150). Below that, coupling scales linearly with length; a 76 mm
  bus is 76/225 = 34% of the saturated value. FEXT only bites past
  ~450 mm at s=w (dormant).
- MACHINE FORM: severity term inside `crosstalk_spacing`; threshold at
  2% of swing per aggressor.
- STATUS: **propose-new**.

### P2-4. Guard traces — niche 2-layer tool only
- SOURCES: bogatin R15, johnson HSDD-X2/V2, montrose §1.7 — all three
  converge (CB3, all **verified**): a guard helps ONLY on no-plane
  boards, must be grounded at BOTH ends (+ interval vias ≤ RT·v/3 ≈
  75 mm at 3 ns), a floating guard makes crosstalk WORSE, and over a
  solid plane a guard is "nothing but trouble" (use spacing instead).
  Guard must be closer to the signal than the return plane is
  (montrose).
- MACHINE FORM: `guard` net role legal only on boards flagged
  no-solid-plane; require both-end grounding + via pitch; reject
  floating guards.
- STATUS: **propose-new**.

### P2-5. Corner-angle honesty (CRAFT not SI — see Docket #6)
- SOURCES: bogatin R9 2 fF/mil (8.16, **verified**); johnson 0.012 pF /
  0.3% at 100 ps (**verified** digest); montrose §1.8 measured +2-5 dB
  only ≥700 MHz, SI only <50 ps edges (**verified**); coombs §1.1
  acid-trap obsolete, keep no-acute-pad-entry (**content-verified**,
  one locator fix); ott n/a.
- THRESHOLD: 90° corners are NOT an SI/EMI issue below multi-GHz for
  our class. 45° discipline is justified by fabrication/appearance/path
  ONLY. **HV exception**: field concentration at sharp corners degrades
  creepage — keep sharp-corner avoidance on declared HV nets (flyback
  primary).
- MACHINE FORM: enable only for declared craft/fabricator/HV applicability.
- STATUS: global trace_corner_angle scope is **policy-held**.

---

# Phase 3 — placement-compatibility engine

### P3-1. Decoupling connection quality (the ONE policy — see Docket #3)
- SOURCES: bogatin R21 "proximity weak, loop area first-order" (13.15,
  **verified**); ott D5 mounting-inductance table + ≥2 caps/IC (PDF
  p.481, **verified**); williams D2 <0.5 in / D3 census (**verified**);
  johnson P1/P2/P3 (SMT ≤1206, radius l/12, fat short vias,
  **verified**); montrose §6.4 (**verified**).
- THRESHOLD for our class: (1) VALUE — one decoupling value per rail
  (100 nF X7R), no decade pairs (Docket #3); (2) PACKAGE — ≤0603;
  (3) METRIC — grade the ROUTED loop VCC-pin→cap→GND-pin: length **≤
  12.7 mm**, own via/short-fat trace, not daisy-chained (this is the
  first-order lever); (4) DISTANCE floor l/12 ≈ 37 mm trivially met.
  On 2-layer, cap directly to IC pins is explicitly OK (ott D5).
- MACHINE FORM: `decap_connection` check on the routed loop (first-order
  blocker); `decap_proximity` advisory only; per-IC census.
- STATUS: **partially exists** (2.1 places 100 nF per IC — proximity
  only; the routed-loop grade is new). Plan 3.3.

### P3-2. Decoupling census (bulk + per-IC + per-zone)
- SOURCES: williams D3 (**verified**): 22 µF bulk/board, 10–100 nF per
  supply pin, 10–47 µF at entry; ott D6 bulk > Σ decaps at entry + far
  corner (**verified**); montrose §6.1 (decoupling mandatory <2 ns
  edges, provision all, **verified**).
- THRESHOLD for our class: bulk at power entry AND farthest-from-entry
  corner; per-IC ceramic; cap V_rated ≥ 2× rail (williams C2).
- MACHINE FORM: composition census check counting caps per package
  class; bulk presence at entry + far corner.
- STATUS: **partially exists** (buck adds CIN2/COUT2, rule 2.1) —
  generalize to a census check.

### P3-3. Series damping on fast clocks
- SOURCES: ott C3 (**verified**): 33 Ω (or ferrite) at source for
  clocks **≥ 20 MHz**, even short traces; if len[in] ≥ 3·RT[ns] use
  R = Z0 − Rdrv; williams E2 (**verified**): 22-47 Ω, ~20 dB at 200 MHz
  8 ns vs 1 ns.
- THRESHOLD: clock-class net ≥ 20 MHz without a source series R/ferrite
  = finding. (SRCLK/RCLK on the 74HC595s qualify if driven ≥20 MHz.)
- MACHINE FORM: composition check for a series element on clock-class
  nets; part of the Docket #4 mitigation bundle.
- STATUS: **propose-new**.

### P3-4. Crystal / oscillator keep-out zone
- SOURCES: ott C4 (**verified**): local ground pour under crystal, ≥2
  stitch vias, no foreign traces under/through, **≥ 13 mm from I/O**,
  ferrite in osc Vcc, crystal > packaged osc on 1-2 layer; williams C6
  (**verified**): strays ≤ 10 pF, C2:C1 ≈ 3:1, ground traces around,
  never route logic near/through; montrose §4.1 (**verified**):
  localized plane, not socketed, keep-out; digest ≥2 mm from clock
  traces (Espressif, **[MED]**).
- THRESHOLD: crystal + load caps + XIN/XOUT declared as a zone;
  foreign switching nets out of the zone; ≥13 mm to I/O; ≥2 stitch
  vias; total XIN/XOUT stray ≤ 10 pF.
- MACHINE FORM: `clock_zone` region check (dormant until a discrete
  crystal board — ESP32 module carries its own).
- STATUS: **propose-new** (plan 3.4).

### P3-5. Temperature/humidity sensor thermal isolation
- SOURCES: Williams T4 supports separating heat sources from sensitive parts.
  Sensirion Design Guide v2 is now locally pinned and extracted and supports
  the sensitivity/isolation mechanism, not a universal slot geometry.
  Coombs supports rounded manufacturable slots only within a fab context.
- THRESHOLD: none global. The sensor, board, housing, fabricator profile and
  thermal-error target determine distance, copper and any slot/moat geometry;
  validate the assembled design.
- MACHINE FORM: sensor thermal/isolation objective with evidence and test
  result; no fixed min_slot_width_mm.
- STATUS: **proposed, policy-held** pending design-specific geometry and
  validation.

### P3-6. Module antenna placement and enclosure clearance
- SOURCES: pinned Espressif ESP32/ESP32-C3 hardware guides
  (`SECOND-WAVE-2026-07.md` SW-E1/E2, vendor-primary, text-verified; figure
  geometry pending visual/module-specific confirmation). Prefer antenna outside
  the baseboard with feed near the edge; fallback cuts baseboard on both sides
  and below. The **15 mm value is final-housing/object clearance**, not a
  blanket PCB copper keepout. The guide also asks for ground copper/vias near
  the antenna outside the cutout.
- THRESHOLD: declare module-specific antenna/feed and fallback-cutout polygons;
  store `housing_clearance_mm=15` separately; require final throughput/range
  test. Thermometer r001 points into the interior over copper and violates the
  placement intent.
- MACHINE FORM: board-edge/overhang or exact cutout check plus separate
  enclosure-review finding; never synthesize antenna geometry from 15 mm.
- STATUS: **propose-new** (plan 3.2, plan 5.1); exact module drawing still
  needs pinning/visual validation.

### P3-7. Switching hot-loop area metric
- SOURCES: ott SW1/SW2 (**verified**): input-cap ESL sets DM emission
  (V_DM = 2·F0·L_F·I_P), minimize switch-node copper area; montrose
  loop-area rules; digest ADI AN-139 (**[HIGH]**): hot loop = input cap
  + switches, enclosed area directly minimizable; williams E1/S5
  (**verified**): E ∝ f²·A·I.
- THRESHOLD: for buck/flyback, compute enclosed area of the
  input-cap→switch→diode→ground loop; minimize + report; FB routed away
  from SW/inductor (≥8 mm, rule 3.3).
- MACHINE FORM: `hot_loop_area` metric on the declared loop nets;
  SW-net-area metric.
- STATUS: **partially exists** (rule 3.1 does 1-D loop-length; 2-D area
  is new). Plan 3.5.

### P3-8. Connector / I/O zoning (rule 1.1 gains its WHY)
- SOURCES: ott IO1 (**verified**, after µ-glyph adjudication): all
  connectors in ONE I/O zone; ~**5 µA CM at 50 MHz on 1 m cable fails
  FCC B**, and a few mV of ground noise supplies it; johnson C1/C2
  (**verified**): spread grounds THROUGH connectors (coupling ∝
  1/(1+N²)), no signal >0.2 in from a ground pin, don't create remote
  return loops; montrose §4.3 (**verified**) functional zoning; williams
  E3 (**verified**).
- THRESHOLD: all off-board connectors within one declared I/O-edge
  zone; clock-class parts ≥13 mm (ott) / conditionally 50–76 mm
  (montrose §4.2, edge-rate gated) from the I/O zone; connector ground
  pins interspersed, not at ends.
- MACHINE FORM: polygon-containment on connector placements;
  `io_zone` + zoning distance checks; connector-ground-pin spread check.
- STATUS: **partially exists** (rule 1.1 places connectors at edges) —
  single-zone + WHY + ground-pin spread are new. Plan 3.6.

### P3-9. Hot / sensitive placement matrix (thermal + reliability)
- SOURCES: williams T1-T4 (**verified**): T_j = P_D·ΣRθ + T_A gate; hot
  parts to edge, ≥ distance from electrolytics/crystal/precision-analog/
  temperature-sensor; C1 electrolytic life ×2 per −10 °C (**verified**);
  ipc-a-610 R16 lead protrusion 2.5 mm (**verified**, bottom-side
  budget).
- THRESHOLD: placement penalty matrix hot-role × {electrolytic, crystal,
  precision-analog, temperature-sensor} with distance knobs; T_j gate
  per dissipator vs datasheet limit (blocker over max, warn > 0.8·max).
- MACHINE FORM: placement scoring terms + `junction_temp` design check.
- STATUS: **propose-new** (plan 3.1).

### P3-10. Common-impedance return walk (shared-copper defect)
- SOURCES: williams G1/G2/G4/S1 (**verified**): separate supply returns,
  reservoir-charge loop must not share copper with logic/analog return;
  ott MX6 hi-current-lo-freq return (**verified**); williams D1 ground
  bounce (50 mA/ns × 20 nH = 1 V, **verified**).
- THRESHOLD: high-current return (>~250 mA, incl. LED-column common,
  rectifier/reservoir loop) must reach the source without sharing
  tracked copper with a logic/analog return; shared-segment IR-drop mV
  budget. Directly relevant to the thermometer LED bank.
- MACHINE FORM: routed-GND-tree walk; `common_impedance` check keyed by
  (high-current net, low-level return) pairs.
- STATUS: **propose-new**.

---

# Phase 4 — dual-side placement gate

### P4-1. Side-assignment retention review
- SOURCES: Coombs verifies the retention mechanism and gives no numeric gate.
  The online-verified, locally unpinned SMTA/SAC305 paper reports about
  0.0269 g/mm for its narrow package/process population. IPC-A-610 R24 is
  acceptance context, not a universal placement rule.
- THRESHOLD: none universal. Use actual package mass/wetted geometry, alloy,
  paste, profile, orientation and assembler validation. No package family,
  including QFN/DFN, is automatically safe.
- MACHINE FORM: an explicit assembly profile and per-package retention review;
  the historical ratio may be reported only inside its demonstrated range and
  is not a global blocker.
- STATUS: **proposed, policy-held**. Existing placement_search side flips are
  the implementation hook once evidence is supplied.

### P4-2. Neighbor-gap overhang budget
- SOURCES: ipc-a-610 R4/R6/R8 (**verified**, R4 minor fillet-side note):
  chip side overhang 50%W (Class 2), MELF 25%, gull-wing 50%W-or-0.5 mm;
  ipc-a-610 R2 electrical clearance is the floor.
- THRESHOLD: worst-case inter-part copper gap = electrical clearance +
  0.5·W_left + 0.5·W_right (Class 2; 0.25·W each Class 3). Fine-pitch
  short margin = pad_gap − W; warn when pad_gap < W + clearance.
- MACHINE FORM: pad-spacing audit on adjacent parts using the overhang
  budget.
- STATUS: **propose-new** (plan 4.2).

### P4-3. Back-side decoupling under fast ICs
- SOURCES: williams D4 (**verified**): fast high-current ICs get the cap
  underneath on the opposite side via pads-between-pads; digest
  (**[HIGH]**) confirms.
- THRESHOLD: allow/prefer back-side decap directly under declared fast
  ICs on double-sided boards (via loop only).
- MACHINE FORM: placement rule using existing dual-side machinery.
- STATUS: **propose-new**.

---

# Phase 5 — board-level ground + EMC

### P5-1. Ground-grid / mesh cell metric (see Docket #5)
- SOURCES: ott GR1 grid cell **≤ 0.5 in (12.7 mm)** (PDF p.413,
  **verified**, Smith & Paul); montrose §5.4 grid loop area **≤ 1.5 in²
  (967 mm²)** (PDF p.43, **verified**, book's own cm² unit-errata
  noted); williams P9 gridded ground / cyclomatic (**verified**);
  johnson HSDD-G2 grid > fingers > none (**verified**).
- THRESHOLD for our class — ONE graph, consistent thresholds
  (resolution of Docket #5): build the GND-copper graph both layers;
  **primary: max mesh cell span ≤ 12.7 mm** (Ott, linear, = "grid
  spacing"); **fallback for irregular meshes: cell area ≤ 967 mm²**
  (Montrose); **precondition: ≥2 independent GND loops, no long single
  tree path** (Williams cyclomatic). A 12.7 mm cell = 161 mm² passes the
  area rule with 6× margin, so the thresholds never conflict.
- MACHINE FORM: `ground_grid` post-route check reporting max cell span
  and area.
- STATUS: **partially exists** (buck has a full B.Cu pour = the grid's
  limiting case; the mesh-cell metric for grids is new). Plan 3.7.

### P5-2. Return-path continuity — no slots under fast nets
- SOURCES: ott R1 (**verified**): 1.5 in slot raised local ground 5×
  (14 dB); a line of non-overlapping holes raised 0%; johnson G4/G5
  (**verified**): slot LENGTH not width hurts, connector pin-fields are
  the slot people miss; williams P10 (**verified**); montrose §3.3
  (**verified**).
- THRESHOLD: no routed net crosses a slot/gap in its return copper;
  keep a same-direction GND corridor ≥ 3W under fast nets (bogatin R17,
  onset **~100 kHz** not 10 MHz — spot-check correction carried
  forward); connector pin clearances must leave continuous pour webs
  between pins (ties to the 0.25 mm hole-to-copper rule).
- MACHINE FORM: extend the `~hole:` obstacle model to the return layer;
  `return_path_continuity` + connector-pour-web checks (blocker when a
  trace crosses a slot).
- STATUS: **partially exists** (hole-obstacle model, §5.3) — return-layer
  slot detection is new. Plan 3.7.

### P5-3. Layer-jump / stitch-via discipline
- SOURCES: ott R3/GR5 (**verified**): critical-net via wants a ground
  stitch via nearby; ≥2 vias per critical ground transition; johnson V1
  (**verified**): ground via beside every signal via; montrose §3.2
  (**verified**).
- THRESHOLD: every critical-net layer change has a ground stitch via
  within a set radius; ≥2 stitch vias on critical ground transitions and
  decoupling grounds.
- MACHINE FORM: router layer-change penalty for critical nets +
  post-route stitch-via presence check.
- STATUS: **propose-new**.

### P5-4. Ground fill stitched, never floating
- SOURCES: ott R5 (**verified**): fill connected ≥2 points, no floating
  islands, delete islands below min area; montrose §3.3 image-plane
  integrity (**verified**).
- THRESHOLD: every ground-fill polygon ≥2 connections; auto-delete
  islands below a min area.
- MACHINE FORM: `ground_fill_stitch` check (lands when pours arrive on
  digital boards).
- STATUS: **propose-new** (isolated boards currently forbid pours, §10).

### P5-5. Clock guard-return traces + one return per 8 bus bits
- SOURCES: ott C2 (**verified**): clocks routed first, min loop, ground
  return trace(s) both sides = 20+ dB; ott L4 (**verified**): ≥1 GND
  return trace per 8 bus bits, next to the LSB; montrose §5.4
  return-adjacency within one trace width (**verified**).
- THRESHOLD: clock-class nets get a parallel GND companion (both sides
  where possible), stitched at ends; parallel buses (74HC595 SEG lines)
  get an accompanying GND trace per 8 members.
- MACHINE FORM: `guard_return_nets=` router feature + post-route
  adjacency check.
- STATUS: **propose-new** (part of Docket #4 bundle).

### P5-6. Mixed-signal single-ground partition (moat + bridge)
- SOURCES: ott MX1 (**verified**): ONE ground, partition don't split,
  100% routing discipline; montrose §4.4 moat ≥ 0.25 mm all layers,
  single bridge, converter centered on bridge (**verified**); williams
  D6 (**verified**): one AGND-DGND tie, no digital copper in analog
  region.
- THRESHOLD: declare analog region polygon + analog net set; ≤1
  AGND-DGND tie; no digital copper inside the analog polygon; bridging
  part centered. (Dormant until a true analog front-end; SHT31 I2C is
  digital.)
- MACHINE FORM: reuse the mains-isolation region machinery for a
  `mixed_signal_region` check.
- STATUS: **propose-new** (isolation machinery, §10, is the template).

### P5-7. Power-entry / cable filter
- SOURCES: ott D7/IO3 (**verified**): π filter + ferrite 50–100 Ω +
  CM element at DC input; every off-board line filtered at the I/O zone;
  johnson C3 (**verified**): slow/filter off-board drivers, source-side
  cap only; montrose §4.5 filter AT the connector (**verified**).
- THRESHOLD: every net leaving the board (USB-C) passes a
  filter/protection element inside the I/O zone; power entry gets a
  bulk + ceramic + optional ferrite.
- MACHINE FORM: `power-entry-filter` composition block + presence check
  when a cable leaves the board.
- STATUS: **propose-new**.

---

# Not-yet-planned (encode when the triggering feature lands)

| Rule | Sources (status) | Threshold for our class | Status |
|---|---|---|---|
| **Termination trigger** — terminate when 2·tpd·len > tr | montrose §2.1 (**verified**, k=3.49 in/ns microstrip); bogatin R4, johnson K2 (**verified**, CB2 agree) | Max unterminated ≈ **76 mm**; DORMANT — no net on our boards needs it at 3 ns | propose-new (dormant) |
| **Testpoint geometry** — land ≥0.6 mm, 0.6 mm keepout, ≥3 mm from edge, mask-free, one/node | ipc-2221b §3.6.5 (**verified**); ipc-a-610 R15 PTH 75% fill (**verified**) | encode when PCBSmith emits testpoints; today a per-net probe-access advisory | propose-new (dormant) |
| **Via-in-pad forbidden** unless filled+capped both sides | coombs §3.4 (**verified**); ipc-a-610 R10 (**verified**) | blocker: via barrel intersecting an SMD paste opening | propose-new |
| **Drill aspect ratio ≤ 8:1** (throwing power 100% at 3:1 → 33% at 15:1) | coombs §5.1 (**verified**) | 1.6 mm / 0.2 mm drill = AR 8, at the flag line; our `min_through_hole` 0.2 mm is consistent | partially exists (§5.5) |
| **ESD guard band** — 3.2 mm band, 0.5 mm clearance, 12.7 mm via pitch, segmented, no mask, grounding by enclosure | montrose §5.5 (**verified**); montrose §5.6 (**verified**) | opt-in outline generator; grounding policy switched on enclosure declaration | propose-new |
| **20-H power-plane inset** = 20× interplane gap | montrose §8 (**verified**, book hedges heavily, negative-benefit literature noted) | KNOB, never a blocker; only "very high-speed" + board dim ≥ λ-fraction; dormant on 2-layer | propose-new (knob) |
| **CAF spacing** L⁴/V² for high-DC-bias nets | coombs §6.4 (**verified**, no single number) | add margin to hole-to-hole spacing on >48 V nets; ties into §10 isolation | propose-new (flyback) |
| **Reflow edge keep-out** for pin-chain conveyors | coombs §2.4 (**verified**, no number); ipc-7351 (**verified**) | 3–5 mm along conveyor edges (assumption pending assembler data) | propose-new |
| **Courtyard policy** | IPC-7352:2023 family tables + manufacturer/KLC/process evidence | no global 0.25 mm Level-B value; add process allowance; quarantine anomalous BGA middle value | global interpretation held |
| **Reliability derating** — cap V_rated ≥ 2× (V⁵ law), R P_rated ≥ 2×, electrolytic ×2 life/−10 °C | williams C1/C2 (**verified**) | BOM arithmetic with datasheet evidence | partially exists (voltage margins) |
| **Unused CMOS inputs never float** | williams D5 (**verified**) | tie to VCC/GND; NC only a deliberate marker on outputs | partially exists (ERC / no-connect machinery) |
| **Axial bend span** — hole span − body ≥ 2·(0.8 mm + R_bend) | ipc-a-610 R17 (**verified**) | footprint-selection check for axial THT | propose-new |
| **Bow/twist advisory** 0.75% SMT | ipc-a-610 R20 (**verified**); williams P8 copper balance (**verified**) | warn at any dim >150 mm at ≤1.0 mm thickness + copper imbalance >~35% | propose-new (advisory) |
| **Tombstone thermal symmetry** on chip passives | coombs §2.5 (**verified**) | flag chip pad with one side to a pour, other to a thin trace; thermal-relief spokes | propose-new |
| **Trace-into-pad ≤60% pad width** | coombs §3.3 (**verified**) | neck power polygons before SMD pad entry (0.2-0.3 mm into ≥0.5 mm pads already comply) | propose-new (advisory) |

---

# CONTRADICTION DOCKET (resolved explicitly)

## Docket #1 — Crosstalk spacing (DECIDES phase-2 spacing classes)

**The positions.**
- **Montrose 3-W** (§1.1, PDF p.150, **verified**): centerline ≥ 3×W,
  edge-to-edge ≥ 2×W; the "~70% flux boundary at logic current levels".
  Explicit let-out: "if the reference plane is physically closer to the
  trace than the trace-to-trace spacing," the plane captures the flux
  and 3-W is conservative.
- **NXP AN2536 4-W** (research digest, **[MED] unverified**): centerline
  ≥ 4×W **plus edge ≥ 3× dielectric height**.
- **Johnson D/H law** (HSDD-X1, PDF p.209, **verified**): coupling ≤
  1/(1+(D/H)²), 1–3% acceptable; at h = 1.6 mm needs D ≈ 5.7·h = **9.1 mm
  center-to-center** for <3%.
- **Bogatin NEXT table** (R11/R12, 10.11, **verified**): edge-gap ≥ 2W ↔
  NEXT 5/2/1% at s = w/2w/3w — WITH his own caveat that on a thick
  2-layer stack (h >> w) the w-based shortcut UNDERSTATES coupling
  because fringe fields extend farther than "2×w".

**What each actually bounds.** The W-based rules (3-W, the 4-W
center-to-center term, Bogatin's s/w table) are proxies for spacing
measured in **dielectric heights h**, valid ONLY when w ≈ 2h — i.e. a
50-Ω microstrip with a CLOSE reference plane. Our 2-layer stack has
h ≈ 1.6 mm and w ≈ 0.2 mm, so **w << 2h and the plane is FAR**. In that
regime the W-rules do not bound coupling at all (Bogatin says so
explicitly). The only rule that exposes h — the physical driver — is
Johnson's D/H law. Note that NXP's *second* clause (edge ≥ 3h = 4.8 mm)
is H-aware and agrees in direction with Johnson; only its W term is a
proxy.

**Resolution for our board class — three spacing classes:**

| Class | Centerline spacing | Basis / status |
|---|---|---|
| **Characterized bus** | project-selected | same-bus alone is not an exemption |
| **Generic foreign logic net** | ≥ 3W ≈ 0.6 mm (craft floor) | montrose 3-W **verified**; HONEST CAVEAT: does NOT prove <3% coupling on our thick dielectric — a readability/area floor only |
| **Sensitive victim** (clock aggressor / analog / reset / crystal / high-Z FB) | ≥ 5.7·h ≈ **9.1 mm** c-c with a back-side GND pour; else move aggressor to opposite layer or add a stitched guard | johnson X1 **verified**; substitution 1/(1+(D/1.6)²)=0.03 → D=9.1 mm |

Numbers are not averaged: the craft floor and plane-backed sensitive-victim
bound address different risks. Same-bus membership is not an exemption;
tighter spacing requires a declared per-bus switching, timing/noise/EMC,
coupled-length and stackup budget.

## Docket #2 — Bandwidth definition (Fknee 0.5/Tr vs 0.35/Tr vs 1/(π·Tr))

**Positions** (all **verified**, CB1): Johnson **0.5/Tr** (167 MHz @ 3 ns,
deliberately conservative "flat-enough" screen); Bogatin **0.35/Tr**
(117 MHz); Ott **1/(π·Tr) = 0.318/Tr** (106 MHz). Bogatin and Ott
nearly agree; Johnson is ~50% higher by design.

**Resolution:** PCBSmith stores ONE knob, **BW = 1/(π·Tr)** (Ott,
median-to-conservative for emissions/decoupling-band checks). The
lumped-vs-distributed / termination screen does NOT use any BW
definition — it uses the length rule (len > 25.4·rt_ns mm), which is
BW-definition-independent and where Johnson and Bogatin already agree
(CB2). Johnson's 0.5/Tr is recorded as the conservative "is the circuit
flat enough" screen, exposed but not silently unified. **Why it barely
matters:** at 3 ns all three land 106–167 MHz, far below the point where
anything on a <100 mm 2-layer board becomes distributed-critical (the
binding screen is the 76 mm length rule). This is definitional, not a
real disagreement.

## Docket #3 — Decoupling policy (the ONE policy for planeless 2-layer)

**Positions:** Ott D2 (**verified**) — same-value caps, avoid
decade-spread (measured +25 dB antiresonance, Archambeault). Decade-pair
lore (0.1 µF + 1 nF) — Montrose §6.3 (**verified**) says only ~6 dB
benefit, narrowband, with an antiresonance hazard; 100× spacing if
paralleled. Bogatin R21 (**verified**) — proximity is a weak (log)
lever; loop area / connection quality is first-order (6.1 nH → 3.7 nH →
1.8 nH by connection, not distance). Williams D2 (**verified**) — <0.5 in
(12.7 mm) for fast logic, and the ROUTED loop is part of the component.

**Resolution — one policy, no contradiction once you separate the
four axes it governs:**
1. **Value:** one decoupling value per rail (100 nF X7R), no decade
   pairs unless declared (Ott D2 wins on measured basis).
2. **Package:** ≤0603 — mounting inductance dominates above ~50 MHz
   (johnson P1, ott D4, montrose §6.2, all **verified**).
3. **Metric (the first-order lever):** grade the ROUTED loop
   VCC-pin→cap→GND-pin length + via count ≤ 12.7 mm; short fat traces,
   own via; on 2-layer connect straight to IC pins (ott D5 explicit).
   This is Bogatin's "loop area first-order" made checkable.
4. **Distance floor:** l/12 ≈ 37 mm (johnson P2) / 0.5 in (williams D2)
   — trivially met on small boards; the loop grade, not the distance,
   is the blocker.

Bogatin, Williams, Johnson and Ott are not in conflict — Bogatin sets
the METRIC (loop, not proximity), Williams/Johnson set the DISTANCE
FLOOR (easily met), Ott sets the VALUE policy. Decade pairs are the only
genuine disagreement, and Ott's measured antiresonance data resolves it.

## Docket #4 — 2-layer clock ceiling (Ott ~10 MHz vs our 50 MHz)

**Positions:** Ott (PDF p.660, **verified**) caps 2-layer at ~10 MHz
clocks (20–25 MHz "with strong EMC expertise"); Johnson HSDD-G2
(**verified**) calls the power-and-ground grid adequate only for "small
low-speed CMOS and ordinary TTL," inadequate for high-speed logic. Our
class allows ≤50 MHz on 2-layer.

**Resolution (CB6):** a **standing advisory finding** (non-blocking,
capped `needs_human_review` per Law 4) fires when a clock-class net
> 10 MHz sits on a 2-layer board. The finding is only satisfiable when
the FULL mitigation bundle is present, ALL required not optional:
(a) gridded GND pour both layers, cell ≤ 12.7 mm (P5-1 / ott GR1);
(b) guard/companion return traces on clock-class nets (P5-5 / ott C2/L4);
(c) series damping 33 Ω at source for ≥20 MHz clocks (P3-3 / ott C3);
(d) same-value decoupling per Docket #3;
(e) sensitive-victim crosstalk spacing per Docket #1.
This honestly reflects that our 50 MHz / 3 ns 2-layer class rides at the
edge of what both authors endorse — it is defensible with the bundle,
never auto-passed.

## Docket #5 — Ground topology metric (grid cell vs loop area vs cyclomatic)

**Positions** (all **verified**): Ott GR1 grid cell ≤ 0.5 in (12.7 mm);
Montrose §5.4 grid loop area ≤ 1.5 in² (967 mm²; the book's "3.8 cm²" is
a documented unit error — 1.5 in² = 9.68 cm²); Williams P9 gridded
ground expressed as cyclomatic connectivity + max path length.

**Resolution — ONE graph, three consistent readings:** build the GND
copper graph on both layers. **Primary metric = max mesh cell span ≤
12.7 mm** (Ott — linear, and literally what "grid spacing" means).
**Fallback for irregular meshes = cell area ≤ 967 mm²** (Montrose).
**Precondition = ≥2 independent GND loops, no long single tree path**
(Williams cyclomatic). These never conflict: a 12.7 × 12.7 mm cell is
161 mm², which passes the 967 mm² area rule with 6× margin. So the
checker computes span (primary), area (coarse fallback), and loop count
(precondition) from the same graph — not three competing thresholds.

## Docket #6 — Corner angles (cross-book unanimity + HV exception)

**Positions:** Bogatin R9 2 fF/mil, matters only ~3 ps edges
(**verified**); Johnson 0.012 pF / 0.3% at 100 ps (**verified** digest);
Montrose §1.8 measured +2–5 dB only ≥700 MHz, SI effect only <50 ps
edges (**verified**); Coombs §1.1 acid-trap physics real but obsolete at
modern spray-etch / our 0.2 mm geometry (**content-verified**, locator
corrected 37.6→37.2); research digest **[HIGH]**; electromigration at
right angles no worse than 45° (IRPS 2013). **Unanimous.**

**Resolution (superseded scope):** 90° corners are not a general SI/EMI
problem for this board class. H/V/45 may remain a craft style. A selected
fabricator or declared HV-net policy may justify scoped angle enforcement.
This does not validate the existing global trace_corner_angle blocker; that
scope remains held until applicability is explicit.

**Residual corrections remain.** The second-wave audit corrected the
Espressif 15 mm interpretation, rejected the old internal-trace coefficient,
and scoped IPC-2221B B3 to altitude. IPC-7351 Tables 3-6/3-9 remain
OCR-ambiguous pending a readable current copy. SHT3x thermal-error numbers
remain unpinned. Docket #1's absolute coupling on a no-pour 2-layer board also
needs a field solver or measurement: Johnson's D/H law assumes a plane, so the
current sensitive-victim distance is only a plane-backed bound.
---

# ai-rule-suggestions candidates (policy-held entries are not promotion-ready)

Entry format per `docs/ai-rule-suggestions.md`. All `status: proposed`.

## 2026-07-12 Voltage-banded electrical clearance (P1-1)
- status: proposed
- proposed_by: claude, CONSOLIDATED.md phase-0 synthesis
- rule: new (upgrade of `CLEARANCE_MM`)
- suggestion: replace the flat 0.2 mm clearance with an IPC-2221B
  Table 6-1 lookup keyed on per-net worst-case DC/AC-peak voltage — B4
  column for coated track-to-track, A6 for uncoated pad/land-to-foreign
  copper. Encode A6: 0.25 mm (16–30 V), 0.4 (31–50 V), 0.5 (51–100 V);
  0.2 mm stays the floor for ≤15 V logic; flyback primary uses the
  171–250 V B3 cell (6.4 mm).
- evidence: ipc-2221b Table 6-1 (verified); audit shows the current
  flat 0.2 mm is LOOSER than A6 for any pad-to-foreign net >15 V.
- decision_note:

## 2026-07-12 Annular-ring minimum + producibility-level declaration (P1-4)
- status: proposed
- proposed_by: claude
- rule: new
- suggestion: add an `annular_ring` check asserting PTH land_min =
  max_hole + 2·(0.05) + c with c = 0.25 (Level B) / 0.2 (Level C); emit
  the declared producibility level into the bundle. Our 0.6/0.3 vias are
  Level-C-only and must say so.
- evidence: ipc-2221b Tables 9-1/9-2 (verified).
- decision_note:

## 2026-07-12 Bus routing as a bundle with spacing classes (P2-1, P2-2)
- status: proposed (**policy-held 2026-07-14**)
- proposed_by: claude
- rule: new 11.6 (bundle) + 11.8 (spacing)
- suggestion: preserve leader/follower bundle routing as craft/area machinery.
  Historical note: same-bus-at-manufacturing-minimum is superseded. Each bus
  requires a declared electrical/coupling budget; generic 3W remains only a
  craft floor and plane-backed sensitive spacing remains conditional.
- evidence: Montrose, Bogatin and Johnson plus the July-14 conflict resolution.
- decision_note:

## 2026-07-12 Decoupling connection-quality metric + census (P3-1, P3-2)
- status: proposed
- proposed_by: claude
- rule: new (extends 2.1)
- suggestion: grade the ROUTED loop VCC→cap→GND (length + via count ≤
  12.7 mm, own via, short fat trace) as the first-order decoupling
  check; keep proximity as advisory only; one decoupling value per rail
  (no decade pairs); census bulk at power entry + far corner.
- evidence: bogatin R21 (loop first-order, proximity weak), ott D2/D5,
  williams D2/D3, johnson P1/P2 (all verified); Docket #3 resolution.
- decision_note:

## 2026-07-12 Sensor thermal isolation + milled moat (P3-5)
- status: proposed (**policy-held; no universal moat**)
- proposed_by: claude
- rule: new
- suggestion: temperature/humidity sensor cards declare heat-source isolation,
  thin/low-copper entry, and moat candidacy. A 1.0 mm rounded slot is a Coombs
  manufacturing floor for the current concept, not a universal sensor rule.
- evidence: Williams T4 and Coombs slot floor (verified). The current Sensirion
  SHT/STS design guide is now pinned; complete targeted locator/applicability
  review before encoding the digest's `1 C ~= 5 %RH at 90 %RH` claim. The
  guide does not support a universal moat geometry.
- decision_note:

## 2026-07-12 Module antenna placement/cutout (P3-6)
- status: proposed; corrected by pinned second-wave source audit
- proposed_by: claude
- rule: new
- suggestion: module cards declare antenna/feed and vendor cutout polygons;
  prefer antenna overhang/feed at edge, otherwise cut baseboard on both sides
  and below. Store 15 mm as enclosure/object clearance and require final RF
  range/throughput test; do not turn it into a blanket PCB copper setback.
- evidence: pinned Espressif guides, SW-E1/E2; thermometer r001 violates the
  placement intent because U1 points into the interior over bulb copper.
- decision_note:

## 2026-07-12 Return-path continuity (no slot under fast nets) (P5-2)
- status: proposed
- proposed_by: claude
- rule: new
- suggestion: extend the `~hole:` obstacle model to the return layer;
  blocker when a routed net crosses a slot/gap in its return copper;
  require continuous pour webs between connector pins.
- evidence: ott R1 (14 dB @1.5 in slot), johnson G4/G5, williams P10,
  montrose §3.3 (all verified).
- decision_note:

## 2026-07-12 Ground-grid mesh-cell metric (P5-1)
- status: proposed
- proposed_by: claude
- rule: new
- suggestion: build the GND copper graph both layers; check max mesh
  cell span ≤ 12.7 mm (primary), area ≤ 967 mm² (fallback), ≥2
  independent loops (precondition).
- evidence: ott GR1, montrose §5.4, williams P9 (all verified);
  Docket #5 resolution (one graph, consistent thresholds).
- decision_note:

## 2026-07-12 Standing 2-layer clock-ceiling advisory + mitigation bundle (Docket #4)
- status: proposed
- proposed_by: claude
- rule: new (standing advisory, capped needs_human_review)
- suggestion: fire a non-blocking finding when a clock-class net >10 MHz
  sits on a 2-layer board, satisfiable only with the full bundle: grid
  pour, guard returns, 33 Ω source damping (≥20 MHz), same-value
  decoupling, sensitive-victim spacing.
- evidence: ott 2-layer ~10 MHz cap, johnson HSDD-G2 (both verified,
  CB6); our class rides at the edge of endorsed practice.
- decision_note:

## 2026-07-12 Dual-side side-assignment retention review (P4-1)
- status: proposed (**policy-held 2026-07-14**)
- proposed_by: claude
- rule: new 4.x
- suggestion: evaluate side assignment with the actual package and assembler
  process. Historical note: the 0.0269 g/mm ratio and QFN-safe package list are
  superseded as global rules; the narrow experiment is applicability-bounded
  evidence only.
- evidence: Coombs mechanism plus online-verified, locally unpinned SMTA paper.
- decision_note:

## 2026-07-12 Series damping on ≥20 MHz clocks (P3-3)
- status: proposed
- proposed_by: claude
- rule: new
- suggestion: clock-class net ≥20 MHz without a source series R/ferrite
  (33 Ω, or R = Z0 − Rdrv when len[in] ≥ 3·RT[ns]) is a finding.
- evidence: ott C3, williams E2 (both verified).
- decision_note:

## 2026-07-12 Common-impedance return walk (P3-10)
- status: proposed
- proposed_by: claude
- rule: new
- suggestion: high-current returns (>~250 mA, incl. LED-column common
  and rectifier/reservoir charge loops) must not share tracked copper
  with a logic/analog return; grade the shared-segment IR drop vs a mV
  budget on the routed GND tree.
- evidence: williams G1/G2/S1, ott MX6, williams D1 ground bounce (all
  verified); thermometer LED bank is the live case.
- decision_note:
