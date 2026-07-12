# IPC-A-610G — Acceptability of Electronic Assemblies (design-relevant distillation)

Provenance
- Standard: IPC-A-610G, October 2017 (supersedes 610F WAM1, Feb 2016)
- Source copy: `.book-cache/manifest.json` slug `ipc-a-610`,
  sha256 `e495a76e7fe300a4dcdad5529f09050007a9f4ed86c8c771cc99a5be6a7909a3`,
  440 PDF pages, text cache `.book-cache/ipc-a-610/p0001..p0440.txt`
- Distilled: 2026-07-11
- Page mapping used throughout: chapter page `c-N` → PDF page = chapter
  offset + N. Offsets: ch1 +14, ch4 +36, ch5 +68, ch7 +146, ch8 +220,
  ch10 +352, ch12 = PDF p.425, Appendix A = PDF p.429-430.

Reading note: 610G is an ACCEPTABILITY standard — it tells an inspector
when a built assembly passes. It constrains PCBSmith indirectly: our
land patterns, clearances, and placements must leave enough margin that
a normally-toleranced assembly process can produce Acceptable-Class-2
joints. Per §1.2, the assembly is presumed to already comply with
IPC-7351 (land patterns) and IPC-2221 (design) — those are the primary
design standards; 610 is the backstop that defines how much process
slop the design must absorb. We capture Class 2 primarily (Igor's
boards are dedicated-service electronics), with Class 3 deltas noted.

---

## 1. Framework rules

### R1. Class definitions
- THRESHOLD: Class 1 general electronics; Class 2 dedicated service
  (extended life, uninterrupted service desired, not critical); Class 3
  high performance (life support, cannot tolerate downtime). Customer
  picks the class; if unstated, manufacturer may.
- WHY: every numeric criterion below is class-indexed.
- WHERE: PDF p.17, §1.3.
- MACHINE FORM: a project-level `ipc_class` constraint (default 2) that
  parameterizes any 610-derived checks; report the class in the design
  bundle.
- APPLICABILITY: all boards.

### R2. Minimum electrical clearance is the universal trump
- THRESHOLD: "Any violation of minimum electrical clearance is a
  defect" — all classes. Clearance is defined by the design standard;
  absent one, Appendix A (= IPC-2221 Table 6-1) applies. Key Class-2
  relevant rows (uncoated external conductors, B2 column, sea level):
  0-15 V: 0.1 mm; 16-30 V: 0.1 mm; 31-100 V: 0.64 mm; 101-150 V:
  0.64 mm; 151-250 V: 1.25 mm; 301-500 V: 2.5 mm; >500 V: +0.005
  mm/V above the 500 V value. Internal layers (B1): 0.05 mm to 30 V,
  0.1 mm to 100 V, 0.2 mm to 300 V, 0.25 mm to 500 V. Uncoated
  component leads/terminations (A6): 0.13 mm to 15 V, 0.25 mm 16-30 V,
  0.4 mm 31-50 V, 0.5 mm 51-100 V, 0.8 mm 101-300 V, 1.5 mm 301-500 V.
- WHY: leakage, arcing, and shorts from condensed moisture; every
  overhang/protrusion criterion in 610 is bounded by this.
- WHERE: PDF p.20 §1.8.4; PDF p.429-430 Appendix A (IPC-2221 §6.3,
  Table 6-1); PDF p.38 §4.1.1.
- MACHINE FORM: already partially present as net-clearance in virtual
  DRC; extend to a voltage-aware clearance table — calculators know
  per-net worst-case voltage, so `design_checks` can assert trace
  spacing ≥ B2 row for the net-pair voltage. The flyback barrier
  machinery (rulebook §10) already covers the mains case; this
  generalizes the low-voltage floor.
- APPLICABILITY: all classes, all component families. B2 values assume
  no conformal coat — correct for PCBSmith output. Note 610's own
  design margin advice: overhang allowances below "may not violate"
  this clearance, so pad-to-pad gaps must budget for it (see R4).

### R3. Design must not rely on inspector mercy for tilted/raised parts
- THRESHOLD: tilt/raise acceptable only while it violates neither
  minimum electrical clearance nor max height; else defect (all
  classes).
- WHY: reflow tilt is normal process variation; the layout must leave
  clearance headroom for it.
- WHERE: PDF p.228 (8-8, chip components intro); PDF p.161 (7-15,
  radial tilt).
- MACHINE FORM: keep-out/height check inputs; courtyard margins already
  absorb XY, but max-height constraints (enclosure) should be recorded
  per component card.
- APPLICABILITY: all SMT and radial THT.

---

## 2. SMT solder joint geometry (bounds on pad spacing and courtyards)

The central design consequence: an Acceptable Class-2 chip joint may
sit with up to 50% of its termination width hanging off the pad
sideways. Worst-case copper-to-copper spacing between two adjacent
components is therefore NOT pad-gap but pad-gap minus both parts'
allowed overhang. Any pad-spacing floor we derive must survive maximum
acceptable misplacement of both neighbors.

### R4. Rectangular/square-end chip components (0402/0603/0805/1206…), Table 8-2
- THRESHOLD (Class 1,2 / Class 3):
  - Max side overhang A: 50% / 25% of min(termination width W, land
    width P); never violating electrical clearance.
  - End overhang B: not permitted (any class).
  - Min end joint width C: 50% / 75% of min(W, P).
  - Min end overlap J (lengthwise land-termination contact): required
    (C1) / 25% of termination length R (C2,3).
  - Min fillet height F: wetting evident on vertical termination face
    (C1,2); G + 25%·H or G + 0.5 mm, whichever less (C3). H =
    termination height.
  - Max fillet height E: may overhang land / climb metallization but
    must not touch component TOP body.
- WHY: side overhang beyond 50% → insufficient joint area and
  clearance risk; missing end overlap → tombstone-prone, weak joint;
  fillet touching chip top → crack path into ceramic body.
- WHERE: PDF p.235 (8-15, Table 8-2); side overhang detail PDF p.236
  (8-16); chip bottom-only variant Table 8-1 PDF p.228 (8-8) with the
  stricter J = 50% R (C2) / 75% R (C3).
- MACHINE FORM: two knobs. (a) Pad-spacing audit: adjacent-part
  copper gap check assumes ±50%·W lateral misplacement is still
  "shippable", so inter-pad clearance floor = electrical clearance +
  0.5·W_left + 0.5·W_right for Class 2 (25% each for Class 3). (b)
  Land-pattern audit: land length S must give ≥25%·R overlap with the
  termination even at IPC-7351 tolerance extremes — flags shrunken
  hand-drawn pads.
- APPLICABILITY: chip R/C/L and networks with 1/2/3/5-face
  terminations. Bottom-only terminations use Table 8-1 instead.

### R5. Billboarding / upside-down / tombstoning limits
- THRESHOLD: billboarded (on-side) chip acceptable Class 1,2 only if
  width:height ≤ 2:1 with 100% termination-land overlap and 3+
  termination faces; Class 3 additionally caps size at 1206 (larger
  needs 5 faces and W:H < 1.25:1). Upside-down 1/3/5-face chip =
  process indicator C2,3, defect for 2-face parts. Tombstoning =
  defect, all classes.
- WHY: these are process escapes, but the DESIGN lever is part
  selection: 2-side-termination chips have zero tolerance for flip or
  inversion.
- WHERE: PDF p.246 (8-26), p.248 (8-28), p.250 (8-30).
- MACHINE FORM: component-card note only — prefer 3+/5-face
  terminations for parts smaller than 0603 where tombstoning risk is
  highest; no board-geometry check possible.
- APPLICABILITY: chip components; "may not be acceptable" for high
  frequency/vibration even when 2:1 is met.

### R6. Cylindrical end cap (MELF), Table 8-3
- THRESHOLD: max side overhang 25% of min(W, P) — ALL classes (stricter
  than rectangular chips); end overhang not permitted; min end joint
  width 50% min(W,P) for C2,3; min side joint length 50% (C2) / 75%
  (C3) of min(R, S); min end overlap J 50% R (C2) / 75% R (C3); min
  fillet F = G + 25%·W or G + 1 mm (C3).
- WHY: round body gives line contact — less side-shift tolerance.
- WHERE: PDF p.253 (8-33, Table 8-3).
- MACHINE FORM: same pad-spacing audit as R4 but with the 25% overhang
  figure; MELF land length must support 50% R overlap.
- APPLICABILITY: MELF/mini-MELF diodes and resistors, all classes.

### R7. Castellated terminations (modules like ESP32-WROOM), Table 8-4
- THRESHOLD: max side overhang 50% W (C1,2) / 25% W (C3); end
  overhang not permitted; min end joint width 50% W (C1,2) / 75% W
  (C3); min side joint length = castellation depth (C2,3); min fillet
  height F = G + 25%·H (C2) / G + 50%·H (C3) up the castellation.
- WHY: module edge joints are the only inspectable connection; fillet
  must climb the castellation to be verifiable.
- WHERE: PDF p.262 (8-42, Table 8-4).
- MACHINE FORM: land-pattern audit for modules — pad must extend
  beyond module edge enough to FORM a visible fillet (IPC-7351 handles
  the number; here record the acceptance driver). Relevant to the
  thermometer's ESP32-C3-WROOM-02 footprint.
- APPLICABILITY: leadless castellated modules, LCC.

### R8. Flat gull wing leads (SOIC/SOT/QFP), Table 8-5
- THRESHOLD (Class 1,2 / Class 3):
  - Max side overhang A: 50% W or 0.5 mm (whichever less) / 25% W or
    0.5 mm.
  - Toe overhang B: allowed within electrical clearance (C1,2,3), but
    NOT permitted when foot length L < 3W (C2,3).
  - Min end joint width C: 50% W / 75% W.
  - Min side joint length D: for L ≥ 3W: 1W or 0.5 mm (C1); 3W or
    75% L, whichever longer (C2,3). For L < 3W: 100% L (C2,3).
  - Min heel fillet F: G + T (C2,3, lead thickness T ≤ 0.4 mm);
    G + 50% T when T > 0.4 mm (C2 only... table: C3 keeps G + T).
  - Max heel fillet E: solder must not touch package body (Note 4,
    with SOIC/SOT exceptions per 8.2.1).
- WHY: heel fillet carries the mechanical load; toe-only wetting is a
  latent opens factory. Side overhang cap bounds how much lateral
  placement error a fine-pitch pattern may absorb.
- WHERE: PDF p.267 (8-47, Table 8-5); coplanarity defect PDF p.279
  (8-59); body-contact exceptions PDF p.226 (8-6, §8.2.1).
- MACHINE FORM: fine-pitch pad-gap audit: adjacent-pin short margin
  must survive 25-50% W side shift on both pins → effective copper gap
  = pad gap − W (Class 2). For 0.5 mm-pitch parts this is the real
  reason IPC-7351 pads are narrow; encode as a warning when pad gap <
  W + electrical clearance.
- APPLICABILITY: all gull wing; round/coined leads use Table 8-6
  (PDF p.280, 8-60) with similar structure.

### R9. J leads (PLCC), Table 8-7
- THRESHOLD: max side overhang 50% W (C1,2) / 25% W (C3); min end
  joint width 50% W / 75% W; min side joint length 150% W (C2,3); min
  heel fillet G + 50% T (C1,2) / G + T (C3).
- WHY: same heel-load logic as gull wing.
- WHERE: PDF p.288 (8-68, Table 8-7).
- MACHINE FORM: same audit family as R8; PLCC rarely used in PCBSmith,
  low priority.
- APPLICABILITY: J-leaded packages.

### R10. BGA / area array, Tables 8-13/8-14/8-15
- THRESHOLD: ball offset and ball-to-anything spacing must not violate
  minimum electrical clearance (all classes); no bridging; continuous
  elliptical connection; voids ≤ 25-30% of ball X-ray area (Table 8-13:
  30% or less of any ball; design-induced voids from microvia-in-pad
  are EXCLUDED and need separate Manufacturer/User agreement); missing
  balls = defect unless by design.
- WHY: the microvia-in-pad exclusion is the design hook — via-in-pad
  under BGA moves void acceptance from standard to negotiation.
- WHERE: PDF p.309-313 (8-89..8-93).
- MACHINE FORM: design check: no unfilled/untented via inside a BGA
  land (would also wick); flag via-in-pad under area arrays as a
  `needs_human_review` finding referencing this clause.
- APPLICABILITY: BGA/LGA/CGA; PCBSmith currently has none — dormant
  rule, encode when first area array lands.

### R11. Bottom termination components (QFN/DFN/LGA), Table 8-16
- THRESHOLD: max side overhang 50% W (C1,2) / 25% W (C3); toe overhang
  (beyond outside edge) not permitted; min end joint width 50% W /
  75% W; side joint length "not a visually inspectable attribute";
  toe fillet not required when package has no continuous solderable
  side face. Thermal-plane (EP) void criteria: explicitly left to
  Manufacturer/User agreement.
- WHY: QFN joints hide under the body — acceptance rides on the small
  visible toe; designs must not block the only inspectable edge.
- WHERE: PDF p.316-317 (8-96/8-97, Table 8-16).
- MACHINE FORM: (a) keep-out audit: no tall part or silk within
  inspection sight-line of QFN edges is overkill for us — skip; (b)
  the real knob: EP paste/via design is unregulated by 610, so keep
  the existing `min_through_hole` + thermal-via craft from the
  thermometer (SHT31 DFN) and record void-risk as assumption-level
  evidence on the component card.
- APPLICABILITY: QFN/DFN/MLF/LGA (SHT31 on thermometer board).

### R12. Bottom thermal plane terminations (DPAK/TO-252 etc.), Table 8-17
- THRESHOLD: thermal pad side overhang ≤ 25% of termination width (all
  classes); end overhang: none; end joint width: 100% wetting in
  contact area; plane void criteria by agreement. Leads follow their
  own termination-type table.
- WHY: tab overhang beyond land is both a thermal and a clearance
  failure; land must be at least tab-sized plus placement tolerance.
- WHERE: PDF p.318-319 (8-98/8-99, Table 8-17).
- MACHINE FORM: land-pattern audit: DPAK tab land ≥ tab size; tab
  overhang also must not violate electrical clearance → clearance
  check from tab copper (not just land) to foreign nets.
- APPLICABILITY: any power package with soldered tab.

### R13. Tall bottom-only terminations (aluminum electrolytic SMT cans etc.), Table 8-11
- THRESHOLD: part qualifies as "tall" when height > 2× the lesser of
  width/thickness. Class 2: max side overhang 25% W, end overhang not
  permitted, min end joint width 75% W, min side joint length 50% R.
  Class 3: NO side overhang permitted, end joint width 100% W, side
  joint length 75% R.
- WHY: tall parts lever their joints; near-zero misplacement budget
  means the land pattern must be generous and placement accurate.
- WHERE: PDF p.306 (8-86, Table 8-11).
- MACHINE FORM: for SMT electrolytics: courtyard + land audit at the
  stricter figures; effectively "do not shave pads on tall cans".
- APPLICABILITY: V-chip electrolytics, tall inductors with bottom-only
  pads.

### R14. Solder must not touch plastic package bodies (with listed exceptions)
- THRESHOLD: default: no solder contact with package body/end seal.
  Exceptions: SOIC/SOT/SOD families; lead-top-to-body gap ≤ 0.15 mm;
  connectors (if solder stays out of cavity); leadless parts whose
  land extends past termination by design.
- WHY: fillet against body stresses the seal and hides the joint.
- WHERE: PDF p.226 (8-6, §8.2.1); referenced by every max-fillet Note 4.
- MACHINE FORM: land-pattern note: pad inner edge should not extend
  under-body further than IPC-7351 nominal for non-excepted packages;
  no live check (not measurable from our geometry alone).
- APPLICABILITY: plastic-bodied SMT.

---

## 3. Through-hole criteria (testpoint / connector / THT part choices)

### R15. PTH vertical solder fill, Table 7-4 — the 75% rule
- THRESHOLD (Class 2 and 3): vertical fill ≥ 75% of barrel; max 25%
  total depression counting both sides. Class 2 relaxations: leads
  connected to an internal thermal plane, or components with ≥14
  leads → 50% fill or 1.2 mm (whichever less) allowed, and for
  thermal-plane leads only if source-side wetting is 360°. Class 1:
  not specified. Source-side land coverage ≥ 75% wetted (C2,3);
  destination-side land coverage 0% required; circumferential wetting:
  source 270° (C2) / 330° (C3), destination 180° (C2) / 270° (C3).
- WHY (design side): a THT pin tied straight into a large copper
  plane without thermal relief will not reach 75% fill in wave/hand
  soldering — the standard even carves out the thermal-plane
  exception because of it.
- WHERE: PDF p.184-187 (7-38..7-41, Table 7-4 on 7-40).
- MACHINE FORM: design check: every PTH pad on a plane/pour-heavy net
  must have thermal relief (spoke) connection, not solid flood — the
  no-pour policy on isolated boards already sidesteps this; encode
  when pours land. Connector/testpoint choice: prefer PTH for parts
  needing mechanical strength since Class-2 fill is achievable; note
  ≥14-lead connectors get the relaxed 50% figure.
- APPLICABILITY: supported (plated) holes, all THT parts.

### R16. Lead protrusion limits, Table 7-3
- THRESHOLD: min = end discernible in solder; max = 2.5 mm (C2),
  1.5 mm (C3), "no danger of shorts" (C1). Exempt from max: connector,
  relay, tempered leads and >1.3 mm dia leads, provided clearance
  holds.
- WHY: protruding leads under the board are shorting hazards against
  enclosure or stacked boards; design consequence is bottom-side
  height budget near mounting/standoff zones.
- WHERE: PDF p.181 (7-35, Table 7-3).
- MACHINE FORM: bottom-side keep-out annotation: assume up to 2.5 mm
  lead protrusion under every THT part when checking enclosure or
  board-stack clearance (a bundle-report figure, not a DRC check).
- APPLICABILITY: THT in supported holes; high-frequency designs may
  need tighter control (610's own note).

### R17. Lead bend geometry, Tables 7-1 and seal-to-bend space
- THRESHOLD: min inside bend radius: 1×D for D < 0.8 mm; 1.5×D for
  0.8-1.2 mm; 2×D above. Bend must start ≥ 1 lead-dia and ≥ 0.8 mm
  from body/weld/solder bead (defect at Class 3 if less).
- WHY (design side): axial part hole-span must be ≥ body length +
  2×(0.8 mm + bend radius) — this sets minimum pitch for axial
  resistors/diodes in our footprint selection.
- WHERE: PDF p.152 (7-6, Table 7-1); PDF p.153 (7-7, §7.1.2.2).
- MACHINE FORM: footprint-selection check for axial THT: hole span −
  body length ≥ 2×(0.8 + R_bend) with datasheet body max. Cheap,
  deterministic, catches too-tight axial footprints at composition
  time.
- APPLICABILITY: axial leaded THT, all classes (defect grade varies).

### R18. Radial part standoff
- THRESHOLD: target base-to-board gap 0.3-2 mm; outside that range =
  process indicator (C2,3), not defect; tilt bounded by electrical
  clearance. Note: panel-mating parts (LEDs, switches, pots) may not
  tolerate tilt.
- WHY: informs whether spacers are needed; mostly process.
- WHERE: PDF p.161 (7-15, §7.1.6).
- MACHINE FORM: none (no board-geometry consequence); component-card
  note for LEDs that must seat flush against panels.
- APPLICABILITY: radial THT, vertical.

### R19. Component leads crossing foreign conductors
- THRESHOLD: a lead crossing an electrically noncommon conductor
  violating minimum electrical clearance = defect (all classes);
  sleeving is the assembly remedy.
- WHY (design side): don't route foreign traces under formed-lead
  spans (axial jumps, TO-220 bends) on the component side without
  mask+margin.
- WHERE: PDF p.157 (7-11, §7.1.3).
- MACHINE FORM: candidate virtual check: on the component side, flag
  foreign-net bare copper (untented via, exposed pad) within the
  lead-span corridor of formed THT parts. Low priority; solder mask
  usually covers this.
- APPLICABILITY: formed-lead THT.

---

## 4. Board-level (bare-board interface) criteria

### R20. Bow and twist
- THRESHOLD: post-solder bow/twist should not exceed 1.5% (THT
  boards) / 0.75% (SMT boards) of the diagonal; defect only when it
  damages or affects form/fit/function.
- WHY (design side): large thin boards and copper-imbalanced stacks
  warp; the 0.75% SMT figure is the budget reflow must stay inside.
- WHERE: PDF p.367 (10-15, §10.2.7).
- MACHINE FORM: report-level advisory: warn when board aspect/size
  crosses a heuristic (e.g. any dimension > 150 mm at 1.0 mm
  thickness) and note copper-balance; not a blocking check (no warp
  model).
- APPLICABILITY: all; SMT figure governs PCBSmith boards.

### R21. Board-edge to conductor margin (depanelization + haloing)
- THRESHOLD: edge nicks/routing intrusion acceptable up to 50% of the
  edge-to-nearest-conductor distance or 2.5 mm, whichever less;
  haloing penetration must stay ≥ min lateral conductor spacing (or
  0.1 mm if unspecified) away from the nearest conductive feature.
- WHY (design side): copper too close to the board edge has zero
  damage budget — the acceptability of routine depanel/rout damage is
  proportional to designed edge clearance.
- WHERE: PDF p.368 (10-16, §10.2.8); PDF p.362 (10-10, §10.2.4).
- MACHINE FORM: already have via-edge margin on shaped outlines
  (thermometer); generalize: trace/pour-to-edge ≥ 0.5 mm design floor
  so a 50%-depth nick still leaves the 0.25 mm class margin. Encode as
  `copper_edge_margin` virtual check.
- APPLICABILITY: all boards; tab-routed/panelized edges especially.

### R22. Conductor width reduction tolerance
- THRESHOLD: defect when width reduced > 20% (C2,3) / 30% (C1) by
  nicks/scratches; note that RF circuits may need tighter custom
  limits.
- WHY (design side): a trace sized exactly at the current-capacity
  minimum has no damage budget; size current-carrying traces so
  0.8×W still meets the IPC-2152/2221 ampacity requirement.
- WHERE: PDF p.370 (10-18, §10.3.1).
- MACHINE FORM: calculator knob: trace-width chain multiplies required
  width by 1.25 (so a 20% reduction still passes). Cheap and honest;
  cite this clause in the calculator references.
- APPLICABILITY: power-carrying traces, all classes; RF traces need
  their own criterion.

### R23. Solder balls / bridging / webbing are clearance-bounded
- THRESHOLD: attached solder balls and splashes acceptable only if
  they don't violate minimum electrical clearance; bridging between
  noncommon conductors = defect, all classes.
- WHY (design side): boards with sub-clearance pad gaps (fine pitch)
  convert ordinary process debris into defects — another reason the
  R4/R8 spacing audits use electrical clearance as the floor, not
  zero.
- WHERE: PDF p.79-81 (5-11..5-13, §5.2.7.1-5.2.7.3).
- MACHINE FORM: no new check — this WHY is embedded in R4/R8 spacing
  floors.
- APPLICABILITY: all.

### R24. Staking adhesive vs termination area (double-sided assembly)
- THRESHOLD: adhesive visible in the termination area with a
  sub-minimum joint = defect (C1,2); any adhesive extending into the
  termination area = defect at Class 3. 610G contains NO general
  requirement that bottom-side reflowed parts be glued — adhesive
  criteria only govern when adhesive IS used (wave-side chips).
- WHY (design side): if a build plan wave-solders bottom-side chips,
  the land pattern needs an adhesive dot gap under the body —
  affects courtyard/under-body via placement. For double-sided reflow
  (PCBSmith's flyback compaction), no 610 constraint beyond normal
  joint criteria applies to bottom-side parts.
- WHERE: PDF p.223 (8-3, §8.1.1); mechanical strength §8.1.2 (8-4).
- MACHINE FORM: none now; if a wave-soldered bottom side is ever
  declared, add an under-body keep-out (no vias where the glue dot
  goes). Record in assembly notes that dual-side reflow assumes
  surface-tension retention (standard practice for chips/SOIC-weight
  parts).
- APPLICABILITY: only assemblies using staking adhesive.

### R25. Nonpolarized orientation consistency (target only) and polarity
- THRESHOLD: polarized component mounted backwards = defect (all
  classes). Nonpolarized markings all reading the same way is TARGET,
  not requirement.
- WHY: polarity is enforced by netlist in PCBSmith (pad_for handles
  cathode/anode); the readable-marking target motivates keeping
  uniform rotations where routing permits.
- WHERE: PDF p.148-151 (7-2..7-5, §7.1.1).
- MACHINE FORM: existing pad_for(ref, net) discipline already makes
  electrical polarity a non-issue; optional aesthetic knob: prefer
  uniform 0/180 rotations for same-family passives in placement
  search scoring (zero-weight tiebreak).
- APPLICABILITY: all.

### R26. High voltage joints need field-shape-aware design
- THRESHOLD: HV criteria apply only when drawings require them; joints
  must have no sharp edges/points/icicles (corona mitigation); balled
  terminal profiles required.
- WHY (design side): on declared HV nets, prefer terminals/pads that
  produce rounded fillets; keep the rulebook §10 barrier machinery as
  primary control.
- WHERE: PDF p.425 (12-1, §12).
- MACHINE FORM: none new — mains/HV boards already carry standing
  SAFETY findings (law 4); cite this clause in those findings.
- APPLICABILITY: only when HV explicitly invoked in procurement docs.

---

## Sections skipped (no design implication for PCBSmith)

- §3 Handling / EOS-ESD (PDF p.29-40): factory handling practice only.
- §4.2-4.5 jackposts, wire bundles, lacing, cable routing (PDF
  p.51-70): wire/cable assembly workmanship.
- §5.1-5.2 soldering anomalies except 5.2.7 (PDF p.71-88): wetting,
  pinholes, disturbed/fractured solder — pure process outcomes.
- §6 Terminal connections (PDF p.89-146): turrets, bifurcated, hook,
  solder cup terminals — wire-termination workmanship.
- §7.5 / 8.6 jumper wires (PDF p.212-218, p.328-332): rework wires,
  per task instruction.
- §9 Component damage (PDF p.333-352): handling damage inspection;
  only latent design echo is chip-cap flex cracking, which belongs to
  layout-stress rules sourced elsewhere.
- §10.1, 10.2.1-10.2.6, 10.6 cleanliness, 10.5 marking, 10.7 mask
  workmanship (PDF p.354-366, p.380-404): bare-board fab and residue
  criteria — inspector territory; mask/marking impose no layout
  constraint beyond what IPC-7351/2221 already give (10.2.4 haloing
  and 10.2.8 extracted as R21).
- §10.8-10.9 conformal coating / encapsulation (PDF p.403-412): per
  task instruction.
- §11 Discrete wiring / solderless wrap (PDF p.413-424): wire-wrap
  technology, unused.
- §8.3.8 butt/I, 8.3.9 flat lug, 8.3.11 L-ribbon, 8.3.15 flattened
  post, 8.3.16 P-style (PDF p.297-305, p.307-308, p.320-325): exotic
  termination styles not in the PCBSmith part vocabulary; revisit if
  one appears.

---

## Top 10 most design-relevant criteria (ranked)

1. **R2 — Minimum electrical clearance table (Appendix A / IPC-2221
   Table 6-1)**: the one criterion every other clause defers to;
   directly encodable as a voltage-aware spacing floor.
2. **R4 — Chip component side overhang 50%/25% + end overlap 25% R
   (Table 8-2)**: sets the real worst-case copper gap between adjacent
   passives; drives the pad-spacing audit for 0402/0603/0805.
3. **R15 — PTH 75% vertical fill + thermal-plane exception (Table
   7-4)**: mandates thermal relief on plane-connected THT pads; the
   strongest 610 argument shaping pour policy.
4. **R8 — Gull wing side overhang and heel fillet (Table 8-5)**:
   bounds fine-pitch pad-gap design; explains why 0.5 mm-pitch escape
   margins are what they are.
5. **R21 — Copper-to-board-edge margin (depanel 50%-of-distance rule +
   haloing floor)**: directly encodable `copper_edge_margin` check;
   PCBSmith already half-built it for vias.
6. **R22 — 20% conductor-width damage budget**: one multiplier in the
   trace-width calculator makes every current-carrying trace
   damage-tolerant by construction.
7. **R12 — Thermal tab overhang ≤ 25% + 100% end wetting (Table
   8-17)**: land-size floor for DPAK-class power parts, where thermal
   and clearance failures compound.
8. **R11 — BTC/QFN visible-toe acceptance + unregulated EP voids
   (Table 8-16)**: justifies the thermal-via/paste craft already in
   the thermometer board and marks EP voiding as assumption-level.
9. **R16 — Lead protrusion max 2.5 mm (Class 2, Table 7-3)**: the
   bottom-side height budget under every THT part; feeds
   enclosure/stack reports.
10. **R17 — Axial bend radius + 0.8 mm seal-to-bend space (Table
    7-1)**: cheap deterministic footprint-span check that prevents
    picking too-short axial footprints at composition time.
