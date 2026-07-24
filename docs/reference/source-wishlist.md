# Source wishlist — NEW references beyond what we own & beyond the phase-0 addendum

> **Acquisition/status update (2026-07-14):** This ranking is a historical scout
> report, not the current source inventory. Espressif, USB-C R2.5, SOT-223
> thermal notes, TI ESD, JESD51-2A/-7, Brooks book/paper, panelization guides,
> and NASA EEE-INST-002 are now cached and distilled in
> docs/reference/books/SECOND-WAVE-2026-07.md. KLC v3.0.67 is cached but
> lacks an upstream commit pin. This paragraph records the 2026-07-14 state;
> the later filesystem reconciliation below supersedes its acquisition status.
> Use the second-wave note for corrected technical interpretation; in
> particular, 15 mm is Espressif housing clearance and USB-C reference
> footprints are informative.
>
> **Filesystem reconciliation (2026-07-18):** The full IPC-7352 May 2023 and
> IEC 60664-1:2020 base were already present, pinned, and synthesized; duplicate
> copies are byte-identical. Full IPC-2222 original (1998) and IEC 62368-1
> Edition 2.0 (2014) are newly verified older references. A later intake added
> full IPC-2152, IPC-7093/7093A, IPC-TM-650, IPC-2221A, and IPC-7525 original.
> The official Sensirion Version 2 guide and USB-IF USB 2.0 June 2025 bundle
> were downloaded automatically, hashed, and visually verified. The guide and
> USB base specification are registered; the full archive is inventoried.
> IPC-2231A and IPC-7525C remain absent: their preview-labelled files contain
> mismatched IPC-1401 text, and the file initially presented as IPC-2231A is
> actually IPC-2221A. The exact inventory and revised priorities are in
> `docs/reference/books/LOCAL-SOURCE-INVENTORY-2026-07-18.md`; the acquisition
> decision gate is `docs/evidence-acquisition-and-utilization-guide.md`.

Written 2026-07-12 by a research subagent. Scope: sources PCBSmith does
**not** already own (`docs/reference/books/README.md`) and that are
**not** already in the `docs/routing-placement-plan.md` phase-0 addendum
(IPC-2152, IPC-2222A, Archambeault, Ritchey, Johnson HSSP vol.2, USB 2.0
spec, JLCPCB/PCBWay capability pages, Sensirion SHT3x design-in guide,
IEC 62368-1). Those nine are already justified there — do not re-list.

Ranked by value-per-effort to the next two quarters: bus routing
(plan phase 2), placement-compatibility engine (phase 3), dual-side
assembly gate (phase 4), fab profiles (phase 0 addendum #7), and
thermometer r002 (phase 5). Availability URLs were verified by web
search on 2026-07-12; where a standard is paywalled the confirming
store URL is given, not a pirate mirror.

Every entry ends with the same discipline the books notes use: a rule
in here becomes a machine check or a knob, or it stays a wish
(law 1). At the time this scout was written none had been read. The dated
acquisition update above and `SECOND-WAVE-2026-07.md` now govern the sources
that were subsequently obtained and distilled.

---

## HIGH priority

### 1. Espressif "ESP Hardware Design Guidelines" (ESP32 / ESP32-C3) — FREE
- **Covers:** Mandatory antenna keep-out geometry (no copper on any
  layer under/beside the on-board PCB antenna; feed point at board
  edge; 15 mm clearance to enclosure/metal), RF-trace rules, module-
  on-baseboard placement, power/decoupling for the module.
- **Closes:** Plan **phase 3 item 2** (antenna keepout zones) and
  **phase 5 item 1** (rotate/replace U1 so the antenna faces the bulb
  edge over a copper-free zone). The roadmap currently reaches this
  rule only "via the research digest" — an unpinned web relay. This is
  the *primary* published source for the exact rule the thermometer
  r001 board VIOLATES (U1 antenna over bulb copper). Pin it next to the
  datasheets (sha256, per law 5) so the antenna-keepout check cites a
  fixed page, not a live URL.
- **Availability:** Free PDF, per-chip HTML.
  https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32c3/pcb-layout-design.html
  (C3 PCB layout) and the full PDF linked from the same docs site.
- **Priority justification:** Free, tiny, and it is the exact normative
  text behind two roadmap items and a known live violation — highest
  value-per-effort on the list.

### 2. IPC-7093A "Design and Assembly Process Implementation for Bottom Termination Components (BTCs)" — ACQUIRED 2026-07-18
- **Covers:** Land-pattern, thermal-pad (windowed/segmented paste),
  paste-coverage %, thermal-via array, mask-defined vs paste-defined
  pad, and voiding rules for QFN / DFN / LGA / SON leadless parts.
- **Closes:** IPC-7352 does not settle BTC paste, voiding, solder wicking,
  exposed-pad stencil design, or thermal-via assembly. Live direct cases are
  **SHT31 DFN** and **MPU6050 QFN**; ESP32-C3-WROOM is a module.
  Lessons-ledger already records live-DRC pain from the SHT31 exposed-
  pad copper lobe and a via parked on it (rulebook 5.4). This standard
  is the authority for exposed-pad paste windowing and the thermal-via
  drill/placement rules that the `min_through_hole` / custom-pad-extent
  machinery currently guesses.
- **Availability/status:** The full October 2020 revision is now local, hashed,
  visually verified, extracted, and registered. Targeted BTC distillation and
  production integration remain open. IPC shop:
  https://shop.ipc.org/IPC-7093-English-D ; free TOC:
  https://www.electronics.org/TOC/IPC-7093A-toc.pdf
- **Priority justification:** Directly governs the two hardest real
  footprints we already ship, where we are currently improvising.

### 3. NASA EEE-INST-002 "Instructions for EEE Parts Selection, Screening, Qualification, and Derating" — FREE
- **Covers:** Quantitative stress-derating tables per part class
  (capacitor voltage %, resistor power %, semiconductor junction-temp
  and voltage margins, inductor current). Self-contained numeric tables
  plus a derating-analysis workbook.
- **Closes:** The composition stage (`generation/*`, ComponentRole)
  today records ratings as evidence but runs **no derating check** —
  nothing verifies that a 25 V cap on a 24 V rail, or a resistor at 90%
  of rated power, is flagged. This is a clean new `design_checks.py`
  family: declare rail voltage / dissipation per role, assert margin
  against the table. Architecture "biggest improvements" doesn't list
  it, but it's a low-risk, high-coverage addition the calculators
  already have the numbers for.
- **Availability:** Free NASA PDF + XLSM workbook.
  https://nepp.nasa.gov/pages/EEE-INST-002.cfm (official; workbook and
  addendum linked there).
- **Priority justification:** Free, tabular, machine-encodable, and adds
  a whole new *electrical* check dimension we have zero coverage of.

### 4. USB Type-C Cable and Connector Specification (Release 2.x) — FREE (usb.org)
- **Covers:** Normative reference **footprints** and mounting-hole /
  shield / keep-out dimensions for USB-C receptacles (vertical, dual-row
  SMT right-angle, hybrid, mid-mount), plus CC/VBUS pin assignment.
- **Closes:** Our boards use a **16-pin USB-C** (thermometer) with an
  ad-hoc footprint. This is distinct from the phase-0 "USB 2.0 spec"
  (that's DP/DM eye/skew signalling); this one is the mechanical
  land + keepout authority for the connector itself, feeding a
  footprint-audit and an edge/keepout placement check (rule 1.x
  connector zoning, phase 3 item 6).
- **Availability:** Free PDF. https://www.usb.org/usb-type-cr-cable-and-connector-specification
  (Release 2.4/2.5 current; the R2.0 direct PDF is on usb.org too).
- **Priority justification:** Free, normative, and covers a connector we
  already place blind — cheap correctness win for USB-C boards.

### 5. Vendor SOT-223 / SOT-23 copper-spread thermal app notes — FREE
- **Covers:** Measured θJA-vs-copper-area curves for the small SMT
  power packages (SOT-223: ~135 °C/W at 16 mm² footprint dropping to
  ~40 °C/W at ~1 in²; SOT-23-6: ~53–70 °C/W on 2-layer). Exact numbers,
  including bottom-side copper + thermal-via contribution.
- **Closes:** Williams gap **T5** (recorded in
  `docs/reference/books/williams-cdc.md`: Williams gives the mechanism
  but *no copper-spread numbers*). Feeds a phase-3-style thermal
  placement/copper check for linear regulators and small FETs: required
  copper pour area for a given dissipation and ΔT. Complements JESD51
  (#8) which defines the test-board these numbers assume.
- **Availability:** Free. Richtek AN044
  https://www.richtek.com/Design%20Support/Technical%20Document/~/media/AN%20PDF/AN044_EN.ashx ;
  TI SNVA036 https://www.ti.com/lit/pdf/snva036 ;
  onsemi AN1028 http://www.onsemi.com/pub/Collateral/AN-1028.pdf.pdf
- **Priority justification:** Free, exact numbers, closes an explicitly
  recorded book gap with a directly machine-encodable curve.

---

## MEDIUM priority

### 6. TI "ESD Protection Layout Guide" (SLVA680) + companion system-level ESD guide — FREE
- **Covers:** Board-level ESD/TVS layout: TVS at the connector entry,
  minimize loop inductance to ground, protected-IC farther from TVS
  than TVS is from connector, via-ordering rules for the ESD path.
- **Closes:** Extends Ott's ESD chapter (which we own but is mechanism-
  heavy) with concrete placement/routing ordering rules — a phase-3
  placement-compatibility rule ("TVS between connector and IC, TVS-to-
  connector loop minimized") for any board with an external connector.
- **Availability:** Free. https://www.ti.com/lit/pdf/slva680 ;
  system-level guide https://www.ti.com/lit/pdf/sszb130
- **Priority justification:** Free and directly actionable, but only
  bites once we add TVS parts / connector-ESD topologies — not yet on
  the 10 topologies, so medium not high.

### 7. JEDEC JESD51-2A / JESD51-7 (thermal test-board & θJA method) — FREE (registration)
- **Covers:** Defines the standardized 1s0p / 2s2p test board and still-
  air environment that **every** vendor θJA number is measured on, plus
  θJB / ΨJT metric definitions.
- **Closes:** The *applicability range* (law 1) for entry #5 and any
  thermal check: a datasheet θJA is meaningless without knowing it's a
  JESD51 2s2p number, which our 2-layer boards do not replicate. This
  is the calibration source that keeps a copper-spread check honest
  rather than the primary rule source.
- **Availability:** Free from JEDEC (free account). Public mirror of
  51-7 e.g. https://community.infineon.com/gfawx74859/attachments/gfawx74859/mosfetsisic/4633/1/jesd51-7.PDF ;
  51-2A https://www.jedec.org/sites/default/files/docs/JESD51-2A.pdf
- **Priority justification:** Free; essential *context* for the thermal
  check but not itself a board rule, so it rides behind #5.

### 8. KiCad Library Convention (KLC) — FREE (web)
- **Covers:** Normative naming/geometry conventions for KiCad symbols
  and footprints: pin-1 marker, courtyard offsets, silk-to-pad
  clearance, reference-designator placement, fab-layer body outline,
  paste on exposed pads.
- **Closes:** Gives the footprint/symbol audit an external citation
  standard. Our custom symbols (UCC28881, LMV431) and any custom
  footprints are currently checked only against our own probes; KLC is
  the community-standard checklist to conform to, and its courtyard/silk
  rules cross-check the IPC-7351 courtyard audit that is phase-0 work.
- **Availability:** Free, always-current web. https://klc.kicad.org/
- **Priority justification:** Free and directly relevant to our own
  library hygiene, but it's convention (nice-to-have) rather than a
  physics/safety gap — medium.

### 9. Douglas Brooks & Johannes Adam — UltraCAD trace/via current papers (FREE) / book "PCB Trace and Via Currents and Temperatures" (PAID) — MIXED
- **Covers:** Experimentally-backed trace and **via** current-vs-
  temperature, fusing current, and the finding that IPC-2152's charts
  can be reproduced/extended (internal vs external, via heating).
- **Closes:** A **stopgap and cross-check** for IPC-2152 (phase-0 #1,
  which is paywalled ~$300): the free UltraCAD papers give us defensible
  via-current and fusing numbers *now*, and validate whatever 2152 fit
  we eventually encode. Our current formula is the old 2221A fit
  (phase-1 item 1 fixes the citation).
- **Availability:** Papers free (UltraCAD www.ultracad.com archive; e.g.
  the via-currents paper hosted at
  https://kicad-info.s3.dualstack.us-west-2.amazonaws.com/original/3X/c/b/cb1a2d223838a50bdbee35b28b1e917e912cd7aa.pdf).
  Book paid: https://www.amazon.com/PCB-Trace-Via-Currents-Temperatures/dp/1541213521
- **Priority justification:** The free papers are a cheap partial
  substitute for the expensive IPC-2152; buy the book only if 2152 is
  deferred.

### 10. IPC-2231A "DFX Guidelines" — PAID (~$300)
- **Covers:** A framework/checklist for design-for-test, -fabrication,
  -assembly, -cost, -reliability — including **testability / testpoint**
  guidance and panelization-readiness as review items.
- **Closes:** The task's testpoint/DFT gap: our boards place testpoints
  ad-hoc with no testability rule. IPC-2231 is the checklist-shaped
  authority to derive a "probe access / testpoint coverage" design check
  from. Caveat: it is a *process framework*, thin on hard numbers — its
  value is structuring a DFX review, not supplying thresholds.
- **Availability:** Paid. https://shop.ipc.org (IPC-2231A). Free TOC:
  https://www.electronics.org/TOC/IPC-2231A_TOC.pdf
- **Priority justification:** Real gap, but framework-not-numbers and
  paywalled — medium; buy after the number-bearing standards.

---

## LOW priority

### 11. PCB panelization / breakaway-tab DFM guidance — FREE (fab DFM pages; no single standard)
- **Covers:** Mouse-bite hole dia (~0.5–1.0 mm, 0.8 typical), hole pitch
  (~2.0 mm), tab placement, V-score component setback (3–4 mm), and the
  component-keepout-from-tab rule (~5 mm; ceramics crack on
  depanelization).
- **Closes:** Our **shaped** outlines will need fab tabs/mousebites, and
  a placement check ("no ceramic cap within 5 mm of a breakaway tab").
  But there is **no free-standing authoritative standard** — the numbers
  live in fab DFM pages, which overlaps the phase-0 addendum #7 fab-
  profile work. Best folded into the fab profile, not bought separately.
- **Availability:** Free vendor pages (Altium resource, JLCPCB/PCBWay
  DFM). E.g. https://resources.altium.com/p/mouse-bites-and-v-scores-how-depanelize-pcbs
- **Priority justification:** Real future need, but no acquirable
  standard — capture as data in the fab profile rather than as a source.

### 12. IPC-7525C "Stencil Design Guidelines" — PAID (~$128)
- **Covers:** Solder-paste stencil aperture design: area/aspect ratio,
  overprint, step stencils, home-plate/windowpane apertures for large
  pads.
- **Closes:** Marginally affects the paste geometry we emit — but KiCad
  footprints already carry paste apertures and the **stencil is the
  assembler's domain**, not the designer's. Only relevant if we ever
  emit custom paste for BTC thermal pads (where #2 IPC-7093 already
  gives the windowing rule).
- **Availability:** Paid. https://shop.ipc.org/ipc-7525/ipc-7525-standard-only/Revision-c/english
- **Priority justification:** Low — largely subsumed by IPC-7093 for the
  one case (BTC paste) where it would matter to us.

---

## Investigated and REJECTED (do not buy)

- **ANSI/ESD S20.20** — it is an ESD-*control-program* standard for
  handling/facilities (wrist straps, EPA), **not** board layout. The
  free TI/Silabs/Rohm ESD *layout* app notes (#6) are the right source
  for our need. Reject.
- **Dedicated silkscreen/assembly-drawing legibility standard** — none
  exists as a standalone worth buying. Legend legibility acceptance is
  in IPC-A-610 (owned) and silk geometry in KLC (#8) and our own
  `silk_text_height` check. Reject; nothing to acquire.
- **IPC-2612 (assembly/schematic drawing)** — documentation-drawing
  standard, orthogonal to a deterministic layout pipeline. Reject.
- **IPC-A-600 (acceptability of bare boards)** — inspection criteria for
  the *fabricated* board, not design rules; IPC-2221B (owned) already
  gives us the design-side numbers. Reject.

---

## Tally

- Entries listed: 12 (plus 4 rejected).
- **Free: 8** (#1 Espressif, #3 NASA EEE-INST-002, #4 USB Type-C spec,
  #5 SOT thermal app notes, #6 TI ESD guide, #7 JESD51, #8 KLC,
  #11 panelization pages; #9 papers free / book paid).
- **Paid: 4** (#2 IPC-7093 ~$300, #10 IPC-2231A ~$300, #12 IPC-7525C
  ~$128, #9 Brooks book ~$40 optional).
- **Next acquisition:** IPC-7093A is no longer an acquisition gap. Within this
  historical wishlist, IPC-2231A and current IPC-7525C remain the paid gaps;
  current priorities follow the July-18 local inventory and evidence guide.
