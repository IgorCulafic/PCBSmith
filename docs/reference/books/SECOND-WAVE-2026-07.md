# Second-wave sources — distilled rules for PCBSmith (2026-07)

This file covers the sixteen sources added to `.book-cache/` after the
first nine book distillations. It groups related sources while retaining
source-specific locators. Status: **VERIFIED-TEXT** = checked against pinned
extraction; **FIGURE-BOUND** = page found but drawing needs visual review;
**CONTEXT-ONLY** = not a numeric rule; **UNPINNED** = no pinned primary
source. Authority classes: `standard-normative`, `standard-informative`,
`vendor-primary`, `experimental-secondary`, and `trade-guidance`.

> **Source-status reconciliation (2026-07-14):** IPC-2152 and IPC-7351 are no
> longer maintained; local 7351 is the 2005 original and IPC-7352:2023 is the
> current generic source. Sensirion v2 and the SMTA QFN paper are online-
> verified but locally unpinned. KLC is v3.0.67 with unknown upstream commit.

## 1. Brooks and Adam — trace/via current and temperature

Sources: `brooks-via-trace` (293p), `pcb-via-paper` (9p). Rule-dense:
book Ch.5 p.62–72, Ch.7 p.85–108, Ch.8 p.111–129; paper p.1–8.

### SW-B1 — IPC-2152 replaces old IPC-2221A fits

- THRESHOLD: no replacement single `k` is justified. Use an IPC-2152 model
  keyed by external/internal, copper thickness, environment, adjacent
  copper, and allowed temperature rise. The old
  `I=k*dT^0.44*A^0.725` is only a labeled legacy estimate.
- WHY: IPC-2152 is multidimensional measured data. Internal traces may run
  cooler than equal external traces through dielectric heat conduction;
  `internal k=0.024` / “half current” is not general.
- WHERE: book p.62 (`p0062.txt`); p.65–70; p.103–108.
- MACHINE FORM: until an evidence-backed thermal model is selected, label the
  current result legacy_ipc_2221a_external_fit and warn near limits. If
  IPC-2152 is later acquired, retain its no-longer-maintained status and use
  it only as historical measured validation.
- APPLICABILITY: steady-state heating, not fusing, pulses, flex, vacuum, or
  materially different stackups.
- AUTHORITY: Brooks/Adam are experimental-secondary interpretation of
  historical IPC-2152, not a current IPC-2152 implementation.
- CONFIDENCE: high conclusion; medium numeric fit. EXTRACTION: text + curves.
- VERIFICATION: VERIFIED-TEXT conclusion; FIGURE-BOUND curves.

### SW-B2 — via temperature is coupled to adjoining traces

- THRESHOLD: do not require via conducting area to equal trace area
  universally. Demonstrated: one ordinary 10 mil drill, ~1 oz wall via can
  transition a properly sized trace without being the bottleneck. This is
  not a universal current rating.
- WHY: adjoining traces heat-sink the barrel through copper/laminate.
- WHERE: book p.111–119, especially p.116–117 tables and p.119 test board;
  paper p.7–8.
- MACHINE FORM: model trace+via together; warn on unknown plating, neck-down,
  or inadequate adjoining copper. Multiple vias remain robustness margin.
- APPLICABILITY: intact PTH vias, substantial traces, steady state; not
  microvias, defects, fusing, pulses, or reliability qualification.
- AUTHORITY: experimental-secondary. CONFIDENCE: high mechanism, medium
  extrapolation. EXTRACTION: text/tables. VERIFICATION: VERIFIED-TEXT.

## 2. NASA EEE-INST-002 — opt-in reliability profile

Source: `nasa-eee-derating` (338p, cached file dated 5/03). This NASA GSFC
space-flight profile must not silently become a commercial default.

### SW-N1 — component stress derating

- THRESHOLD: ceramic capacitor voltage 0.60 (DC + peak ripple); common
  resistor power 0.5–0.6 and voltage 0.8, also `<=sqrt(Pderated*R)`;
  magnetics voltage 0.50 of DWV; digital/linear IC power 0.80/0.75;
  transistor power/current/voltage 0.60/0.75/0.75; general diode
  PIV/current/power 0.70/0.50/0.50.
- WHY: mission reliability margin for lot/environment/radiation uncertainty.
- WHERE: capacitor Table 4 p.44; magnetics p.170; ICs p.201; resistors p.256;
  diodes p.270; transistors p.271.
- MACHINE FORM: optional `reliability_profile="nasa_eee_2003"`; every
  finding names exact part class/table row.
- APPLICABILITY: opt-in space/high-reliability; commercial use advisory.
- AUTHORITY: standard-normative in NASA scope. CONFIDENCE: high values,
  medium currentness. EXTRACTION: tables. VERIFICATION: VERIFIED-TEXT;
  acquire current official revision/workbook.

### SW-N2 — absolute junction limits

- THRESHOLD: ICs `Tj <= min(110°C,Tjmax-40°C)`; discrete diodes/transistors
  `Tj <= min(125°C,Tjmax-40°C)`.
- WHY: a dimensionless factor can conceal unsafe absolute temperature.
- WHERE: p.201 Note 2; p.270 Note 1; p.271 Note 2.
- MACHINE FORM: apply only with package-specific thermal evidence.
- APPLICABILITY/AUTHORITY: same opt-in NASA profile, standard-normative.
- CONFIDENCE: high. EXTRACTION/VERIFICATION: direct text, VERIFIED-TEXT.

## 3. Espressif ESP32 / ESP32-C3 hardware guides

Sources: `espressif-esp32` (38p), `espressif-esp32c3` (30p).

### SW-E1 — module antenna at/beyond baseboard edge

- THRESHOLD: prefer antenna outside baseboard, feed near edge. If it cannot
  overhang, cut baseboard on both sides and below antenna; do not center the
  module and hollow all four sides. **15 mm is clearance to the final
  housing/objects in all directions, not a blanket PCB copper keepout.**
- WHY: board material, copper, housing, and objects detune/shield antenna.
- WHERE: C3 p.24–26; ESP32 p.30–32.
- MACHINE FORM: card declares feed/antenna polygon; prefer overhang; fallback
  vendor-figure cutout. Store `housing_clearance_mm=15` separately and
  require final RF throughput/range test.
- APPLICABILITY: modules with onboard PCB antenna; geometry is
  module-datasheet-specific.
- AUTHORITY: vendor-primary. CONFIDENCE: high text, medium figure geometry.
- EXTRACTION/VERIFICATION: text + figure, VERIFIED-TEXT/FIGURE-BOUND.

### SW-E2 — RF feed routing

- THRESHOLD: short constant-width unbranched outer-layer RF trace, no vias,
  complete adjacent plane, avoid traces beneath and clocks/crystal/USB/UART
  nearby. Guide requests sufficient GND copper/dense vias on baseboard
  **near** antenna; “no copper within 15 mm” is not valid.
- WHY: discontinuities/harmonics degrade match, EVM, and RX.
- WHERE: C3 p.22,p.25; ESP32 p.27,p.30.
- MACHINE FORM: RF class checks layer/vias/branch/reference/exclusion/fence;
  antenna cutout and RF-feed reference plane are distinct polygons.
- APPLICABILITY: RF feed; module placement uses SW-E1.
- AUTHORITY: vendor-primary. CONFIDENCE: high. EXTRACTION/VERIFICATION:
  direct text (geometry figure-bound), VERIFIED-TEXT.

### SW-E3 — ESP32-C3 USB

- THRESHOLD: 90 ohm differential ±10%, equal length, minimize transitions;
  transitions get paired return vias; continuous GND reference.
- WHY: impedance and return continuity. WHERE: C3 p.25.
- MACHINE FORM: pair class + reference/return-via checks.
- APPLICABILITY: C3 native USB; actual stackup is authoritative.
- AUTHORITY: vendor-primary. CONFIDENCE: high. VERIFICATION: VERIFIED-TEXT.

## 4. JESD51 thermal applicability

Sources: `jesd51-2a` (22p), `jesd51-7` (13p).

### SW-J1 — theta-JA is a test-system result

- THRESHOLD: none transfers alone. theta-JA evidence must carry test-board
  standard/construction, air/enclosure condition, power, and method.
- WHY: board copper and convection materially determine theta-JA.
- WHERE: 51-2A p.5,p.11–18; 51-7 p.5–8.
- MACHINE FORM: require `test_board_standard`, `air_condition`, locator;
  unknown conditions are context-only.
- APPLICABILITY: every datasheet theta-JA use.
- AUTHORITY: standard-normative measurement. CONFIDENCE: high.
- EXTRACTION/VERIFICATION: direct text, VERIFIED-TEXT.

### SW-J2 — JESD51-7 is a high-conductivity near-best case

- THRESHOLD: 2s2p board commonly 76.20 x 114.30 mm (package exceptions).
  Do not apply its theta-JA unchanged to a small 2-layer board.
- WHY: planes spread heat. WHERE: 51-7 p.5–8, size p.7.
- MACHINE FORM: 2s2p value used on 2-layer emits applicability warning or
  requires board-specific model.
- APPLICABILITY: leaded SMT thermal characterization.
- AUTHORITY/confidence: standard-normative, high. VERIFICATION: VERIFIED-TEXT.
- GAP: acquire JESD51-3 1s as closer simple-board baseline.

## 5. SOT-223 copper spreading

Sources: `richtek-an044` (10p), `onsemi-an1028` (15p), `ti-snva036` (13p).

### SW-T1 — copper area lowers theta-JA with diminishing returns

- THRESHOLD: Richtek ~135°C/W @16mm², 107 @100mm², 50 @2500mm².
  TI/onsemi ~110→40°C/W as top copper grows 0.0123→1in²; all-top copper
  ~10–15°C/W better than split copper in their layouts.
- WHY: tab spreads heat; returns diminish.
- WHERE: Richtek p.8–9; TI p.3–4; onsemi p.4–6.
- MACHINE FORM: package-specific interpolation clamped to measured range;
  solve required theta-JA/area from P,Ta,Tj and expose assumptions.
- APPLICABILITY: SOT-223, comparable tab bond/copper/board/convection; not
  generic SOT-23 or QFN.
- AUTHORITY: vendor-primary experimental. CONFIDENCE: high points, medium
  interpolation, low extrapolation. VERIFICATION: VERIFIED-TEXT points /
  FIGURE-BOUND curves.

### SW-T2 — junction temperature is the gate

- THRESHOLD: `Tj=Ta+P*thetaJA <= Tj_limit`; datasheet's lower limit wins.
- WHY: copper area is a means, Tj the gate.
- WHERE: Richtek p.10; TI p.2–4; onsemi p.3–6.
- MACHINE FORM: report predicted Tj/evidence quality; unquantified “large
  pour” is insufficient.
- APPLICABILITY: steady state. AUTHORITY: vendor-primary. CONFIDENCE: high.
- VERIFICATION: VERIFIED-TEXT.

Gap: cached sources do not establish wishlist SOT-23-6 53–70°C/W; acquire
package-specific evidence before encoding.

## 6. TI system-level ESD layout

Sources: `ti-slva680` (11p), `ti-sszb130` (25p).

### SW-D1 — connector -> TVS -> protected circuit

- THRESHOLD: TVS as close to entry as rules allow; protected IC much farther
  from TVS than TVS from connector; no stub; route through TVS node; avoid
  via before TVS.
- WHY: make protected-path inductance larger than shunt path and avoid pulse
  branching. WHERE: SLVA680 p.4,p.6,p.9.
- MACHINE FORM: ordinal check: connector-to-TVS distance < TVS-to-IC distance,
  no pre-TVS branch, first via after TVS.
- APPLICABILITY: external conductors with TVS.
- AUTHORITY: vendor-primary. CONFIDENCE: high. VERIFICATION: VERIFIED-TEXT.

### SW-D2 — shunt inductance dominates overshoot

- THRESHOLD: cited IEC event 30A/0.8ns gives ~4e10A/s; 0.25nH adds ~10V.
  TVS GND directly to same-layer GND with nearby multiple stitching vias;
  large drill/diameter lowers via impedance.
- WHY: `V=Vbr+I*Rdyn+L*dI/dt`. WHERE: SLVA680 p.4,p.7–9.
- MACHINE FORM: score/minimize entry+GND loop; 10V is explanatory, not a
  universal pass threshold.
- APPLICABILITY: IEC-like pulses; device selection/system test still apply.
- AUTHORITY: vendor-primary; IEC waveform secondary. CONFIDENCE: high.
- VERIFICATION: VERIFIED-TEXT; pin IEC 61000-4-2 for normative simulation.

## 7. Panelization/manufacturing

Sources: `altium-depanelization` (7p), `pcb-manufacturing-1` (20p),
`pcb-manufacturing-2` (25p).

### SW-P1 — dimensions belong in FabProfile

- THRESHOLD: no global numeric threshold verified from text. Mouse-bite
  holes tangent to edge with copper/component clearance; V-score requires
  straight accessible line and explicit groove angle/depth/web from fab.
- WHY: damage/tool access are process-dependent.
- WHERE: Altium p.2–4; manufacturing-guide panelization figures.
- MACHINE FORM: drill/pitch/tab/web/setbacks live in `FabProfile`; no global
  defaults from illustrations.
- APPLICABILITY: user-generated panels. AUTHORITY: trade-guidance.
- CONFIDENCE: high qualitative, low image numeric. VERIFICATION:
  VERIFIED-TEXT/FIGURE-BOUND.

### SW-P2 — depanel keepout for brittle parts

- THRESHOLD: direction supported; distance comes from assembler/fab.
- WHY: panel flex cracks MLCCs/stresses joints.
- WHERE: guide depanel sections; Altium p.3–4.
- MACHINE FORM: depanel features repel MLCC/crystal/BGA/large leadless.
- APPLICABILITY: scored/tab panels. AUTHORITY: trade-guidance.
- CONFIDENCE: medium. VERIFICATION: CONTEXT-ONLY pending fab data.

## 8. USB Type-C R2.5

Source: `usb-type-c-r2.5` (442p, March 2026). Only connector/board-interface
pages were targeted; this is not a protocol distillation.

### SW-U1 — reference footprints are informative

- THRESHOLD: p.57–63 Figures 3-5..3-11 cover multiple receptacle types and
  are explicitly **Informative**.
- WHY: constructions/tabs vary; generic geometry cannot replace selected
  manufacturer's land pattern.
- WHERE: p.57–63.
- MACHINE FORM: exact connector datasheet first; USB figure only type-class
  cross-check.
- APPLICABILITY: mechanical validation. AUTHORITY: standard-informative.
- CONFIDENCE: high status; dimensions need visual extraction.
- VERIFICATION: VERIFIED-TEXT/FIGURE-BOUND.

### SW-U2 — impedance/ground void are stackup-dependent

- THRESHOLD: mated connector target 85 ohm ±9 ohm at 40ps 20–80%; ground
  void examples depend on pad, mount, and stackup.
- WHY: launch discontinuity. WHERE: p.119 Figures 3-59/3-60.
- MACHINE FORM: SuperSpeed needs validated/3D launch; do not copy voids
  between stackups. USB2-only boards treat this target as context.
- APPLICABILITY: mated SuperSpeed launch, not every USB2 port.
- AUTHORITY: standard-informative. CONFIDENCE: high.
- VERIFICATION: VERIFIED-TEXT/FIGURE-BOUND.

### SW-U3 — shield/EMC continuity

- THRESHOLD: shielding pads connect to shell; absent shell requires means to
  connect shielding pad to ground.
- WHY: preserves shield path. WHERE: p.46 and p.145 Figure 3-79.
- MACHINE FORM: audit shell pads and connection per chassis/GND policy.
- APPLICABILITY: USB-C receptacles. AUTHORITY: standard-normative text.
- CONFIDENCE: high. VERIFICATION: VERIFIED-TEXT.

## Unclosed gaps

> **2026-07-18 intake update:** The numbered list preserves the second-wave
> technical gaps, but acquisition status has changed as noted below. See
> `LOCAL-SOURCE-INVENTORY-2026-07-18.md` for exact paths and hashes.

1. Sensirion v2 is now locally pinned and extracted; targeted integration is
   open, and the source still provides no universal moat geometry.
2. Use IPC-7352:2023 plus manufacturer geometry; quarantine the anomalous BGA
   middle courtyard pending official correction.
3. Acquire current applicable end-product safety and IEC insulation sources.
4. IPC-2152 is now locally pinned but remains no-longer-maintained; use it only
   as historical validation evidence.
5. IPC-7093A is now locally pinned; targeted distillation remains needed for
   directly assembled SHT31 DFN and MPU6050 QFN process gaps. ESP32-C3-WROOM is
   a module, not the QFN justification.
6. Books/klc-master is v3.0.67; upstream commit/acquisition is unknown.

## First-wave corrections required before hard-coding

- Bogatin R17: onset ~100kHz, not 10MHz; 3W/1% is §7.17/App.B, not §7.13.
- Johnson HSDD-D1 area is 1.35e-5in², not 1.35e-3.
- IPC-7351: Table 3-9 LCC likely 0.1/0.25/0.5; `Jg` belongs to 3-5, not 3-8.
- IPC-A-610 R4: solder must not touch component **top or side**.
- IPC-2221B A6 scopes exposed leads/terminations and uncoated soldered lands
  in B4 assembly; B3 6.4mm at 171–250V is uncoated **above 3050m**, not a
  generic reinforced-mains-isolation requirement.
