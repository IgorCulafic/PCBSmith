# Cross-source synthesis: authority, agreements, conflicts, and encoding holds

Date: 2026-07-14

## Purpose and limits

This is the durable analysis of the PCB reference material currently available
to PCBSmith. It consolidates the 31 exact sources pinned in
`.book-cache/manifest.json`, the local KiCad Library Convention snapshot, the
historical application specification, the archived Claude chats, and official
online edition/status checks performed on 2026-07-14.

It is deliberately an **analysis artifact**, not an executable rulebook. Its
job is to preserve:

- what each source actually supports;
- the source's legitimate role and revision status;
- page, chapter, or section locators where already verified;
- agreements and conflicts between sources;
- applicability conditions lost by short summaries;
- claims that must not be encoded yet; and
- the remaining acquisition and verification work.

It does not authorize product-code changes, certify regulatory compliance, or
replace engineering review. Copyrighted books and standards remain private,
gitignored local research copies. This committed file contains only
paraphrases, short equations, numerical checks, and locators.

The first-wave notes were spot-verified, not exhaustively verified. The
second-wave material contains explicitly figure-bound items. Newly ingested
standards have been text-extracted and sampled, but still need their final
canonical, table-by-table integration. Any safety, compliance, or
OCR-sensitive threshold must be rechecked in the pinned page image before it
becomes a design blocker.

## Executive conclusion

The collection is already strong enough to support a defensible PCB knowledge
model. It is not yet safe to compile every distilled number into a universal
blocker. The strongest repeatable findings are mechanistic:

- fast-current return paths and loop geometry dominate many SI/EMC failures;
- mounted connection inductance matters more than raw component proximity;
- electrical length must be calculated from edge rate per net;
- trace, via, package, and board thermal behavior are coupled;
- selected-part manufacturer data outranks generic footprint examples;
- safety and EU EMC conformity require declared product/environment profiles;
- manufacturing limits belong to a selected fab/assembly profile.

Most audited numbers were transcribed correctly. The main residual risk is
**scope inflation**: a historical example, a single measured geometry, a
vendor-specific instruction, an acceptance criterion, or a test standard is
sometimes promoted into a general design law.

Three distinctions must precede encoding:

1. source authority is separate from source verification;
2. source statement is separate from applicability and project policy; and
3. a verified number is separate from a justified blocker severity.

No numeric claim recovered only from the chat archive or failed web-research
verifier campaign is ready to encode. The July workflow extracted 114 claims,
but all 25 three-voter panels failed under infrastructure/session limits. It
therefore independently verified zero claims. Its `[HIGH]` labels are discovery
triage, not evidence.

## Evidence and authority vocabulary

### Evidence state

| Field | Suggested values | Meaning |
|---|---|---|
| `source_status` | `pinned`, `unpinned`, `lead_only` | Whether the exact primary source is locally identified and hashed |
| `locator_status` | `text_verified`, `figure_verified`, `figure_bound`, `ocr_ambiguous` | Whether the supporting text/table/figure was directly checked |
| `applicability_status` | `confirmed`, `conditional`, `inferred`, `unknown` | Whether the project case matches the source preconditions |
| `implementation_status` | `candidate`, `proposed`, `implemented`, `tested` | Product state, independent of evidence state |
| `policy_severity` | `information`, `advisory`, `review`, `blocker` | Consequence after authority and applicability are resolved |

A statement can be text-verified and still be unsafe as a blocker because the
geometry, process, environment, product class, or interface does not match.
Conversely, a vendor requirement may be a strong blocker for one exact part
while remaining irrelevant to every other design.

### Source roles and precedence

No single ranking applies to every question. The controlling source depends on
the decision:

| Role | Legitimate use | Cannot establish alone |
|---|---|---|
| Applicable product-safety standard | Required insulation system and evaluation for the declared product/use | Generic routing quality or EMC performance |
| Horizontal safety standard | Insulation-coordination vocabulary and procedure within scope | End-product conformity without the applicable product standard |
| EMC emissions/immunity standard | Product/port test setup, phenomena, limits, and performance criteria | A universal trace-spacing or placement recipe |
| PCB design standard/guideline | Generic board geometry, construction, or land-pattern models | Product safety approval or actual supplier capability |
| Acceptance standard | Observable criteria for a completed assembly | Design synthesis or process qualification |
| Measurement standard | Reproducible measurement conditions and comparison | Direct prediction on a materially different board |
| Vendor-primary guide/datasheet | Validated requirement for the named device/package/topology | Generalization to unrelated parts or stackups |
| Experimental secondary source | Measured physical trends and model criticism | Normative compliance or universal extrapolation |
| Textbook/handbook | Mechanisms, equations, review screens, and worked examples | Compliance or guaranteed fabrication limits |
| Fabricator/assembler profile | Actual limits for the selected process | General safety or electrical performance |
| Historical/trade/chat source | Provenance, discovery, and sanity checks | A blocker without current primary verification |

Decision precedence follows the question:

- selected-part footprint: current manufacturer drawing first, generic
  IPC-7352 method as a cross-check;
- fab legality: selected fabricator and assembler profile first;
- reinforced/mains insulation: applicable product standard plus current
  insulation-coordination analysis first;
- EU EMC: current applicable/harmonized standard and declared product scope;
- assembly acceptability: IPC-A-610 for observed finished-joint criteria only;
- electrical/thermal behavior: component data and actual geometry, then
  validated models and source measurements.

## Exact pinned inventory: 31 sources

The count below is the exact set in `.book-cache/manifest.json` on 2026-07-14.
Every entry has a SHA-256 identity in the manifest. PDF counts are pages; EPUB
sources use extracted chapters rather than page counts.

### A. Design, safety, compliance, acceptance, and interface standards (10)

| # | Manifest key | Exact source/revision in the collection | Size | Role and current use |
|---:|---|---|---:|---|
| 1 | `ipc-2221b` | IPC-2221B, *Generic Standard on Printed Board Design* | 184 pp | Generic design guidance. Local B is superseded by IPC-2221C (2023); not end-product safety authority. |
| 2 | `ipc-7351` | IPC-7351 original, 2005, land-pattern standard | 85 pp | Historical generic land-pattern source. It is not revision B and IPC marks the series no longer maintained. |
| 3 | `ipc-a-610` | IPC-A-610G, *Acceptability of Electronic Assemblies*, 2017 | 440 pp | Acceptance criteria, not footprint synthesis or process qualification. |
| 4 | `usb-type-c-r2.5` | USB Type-C Cable and Connector Specification, Release 2.5, March 2026 | 442 pp | Current local interface/mechanical reference; targeted review only. Informative footprints do not override connector data. |
| 5 | `iec-60664-1` | IEC 60664-1:2020, *Insulation coordination ... Part 1* | 171 pp | Horizontal insulation-coordination basis. Local base omits AMD1:2025 and cannot replace the applicable product standard. |
| 6 | `ipc-7352` | IPC-7352, *Generic Guideline for Land Pattern Design*, local cover May 2023 | 62 pp | Current IPC generic land-pattern guideline; process- and part-specific adjustment still required. |
| 7 | `en-55032-2015` | BS EN 55032:2015, multimedia-equipment emission requirements | 110 pp | Compliance-test standard. Recovered using pypdfium2 after malformed final PDF cross-reference syntax. Base lacks later amendments. |
| 8 | `en-55035-2017` | BS EN 55035:2017, multimedia-equipment immunity requirements | 90 pp | Port-based compliance-test and performance-criteria source; local base lacks A11:2020. |
| 9 | `en-61000-6-1-2002` | DIN EN 61000-6-1:2002-08, generic residential/commercial/light-industrial immunity | 19 pp | Historical national adoption, not current authority. |
| 10 | `en-61000-6-1-2007` | DIN EN 61000-6-1:2007-10, generic residential/commercial/light-industrial immunity | 22 pp | Later historical adoption, still superseded by IEC 61000-6-1:2016. |

### B. Measurement and reliability standards (3)

| # | Manifest key | Source | Size | Role and current use |
|---:|---|---|---:|---|
| 11 | `jesd51-2a` | JEDEC JESD51-2A, natural-convection junction-to-ambient thermal measurement | 22 pp | Measurement context; theta-JA must retain board/air/method metadata. |
| 12 | `jesd51-7` | JEDEC JESD51-7, high-effective-thermal-conductivity test board | 13 pp | 2s2p near-best-case board context; must not be transferred unchanged to a small two-layer board. |
| 13 | `nasa-eee-derating` | NASA GSFC EEE-INST-002, original May 2003, Addendum 1 incorporated April 2008 | 338 pp | Opt-in space/high-reliability derating profile only; currentness and program applicability required. |

### C. Core textbooks and handbooks (6)

| # | Manifest key | Source | Size | Audit status |
|---:|---|---|---:|---|
| 14 | `johnson-hsdd` | Howard Johnson and Martin Graham, *High-Speed Digital Design: A Handbook of Black Magic*, 1993 | 446 pp | OCR source; rule-dense sections audited, equations/units need visual care. |
| 15 | `ott-emc` | Henry W. Ott, *Electromagnetic Compatibility Engineering*, 2009 | 862 pp | Text audited; extractor loses the micro glyph on some pages. |
| 16 | `montrose-emc` | Mark I. Montrose, *Printed Circuit Board Design Techniques for EMC Compliance*, 2nd ed. | 340 pp | Text audited; historical safety tables are context only. |
| 17 | `bogatin-spi` | Eric Bogatin, *Signal and Power Integrity - Simplified*, 3rd ed., 2018 | EPUB | 33 extracted chapters; figures are not preserved by text extraction. |
| 18 | `williams-cdc` | Tim Williams, *The Circuit Designer's Companion*, local 4th-edition copy | 480 pp | Text audited; filename metadata is poor but content identity is pinned. |
| 19 | `coombs-pch` | Clyde F. Coombs Jr. and Happy T. Holden, *Printed Circuits Handbook*, 7th ed., 2016 | EPUB | 108 extracted chapters; chapter 23 thermal content newly recovered. |

### D. Experimental thermal/current sources (2)

| # | Manifest key | Source | Size | Role |
|---:|---|---|---:|---|
| 20 | `brooks-via-trace` | Douglas Brooks and Johannes Adam, *PCB Design Guide to Via and Trace Currents and Temperatures*, 2021 | 293 pp | Experimental/modeling interpretation of trace/via heating; curves remain figure-bound. |
| 21 | `pcb-via-paper` | Douglas G. Brooks and Johannes Adam, *Via Currents and Temperatures*, July 2015 | 9 pp | Experimental/simulation paper; supports coupled trace-via thermal mechanism, not a universal via current rating. |

### E. Vendor-primary application and design guides (7)

| # | Manifest key | Source | Size | Scope |
|---:|---|---|---:|---|
| 22 | `espressif-esp32` | Espressif, ESP32 Hardware Design Guidelines | 38 pp | ESP32 module/RF/power/layout guidance; antenna geometry is module-specific. |
| 23 | `espressif-esp32c3` | Espressif, ESP32-C3 Hardware Design Guidelines | 30 pp | ESP32-C3 module/RF/native-USB guidance. |
| 24 | `richtek-an044` | Richtek AN044, SOT-223 thermal/copper-area application note | 10 pp | Package-specific measured thermal guidance. |
| 25 | `onsemi-an1028` | onsemi AN-1028, SOT-223 thermal application note | 15 pp | Package/test-board-specific copper-spreading data. |
| 26 | `ti-snva036` | Texas Instruments/National SNVA036B, SOT-223 thermal guidance | 13 pp | Package/test-board-specific copper-spreading data. |
| 27 | `ti-slva680` | Texas Instruments SLVA680A, system-level ESD protection/layout | 11 pp | Connector-TVS-protected-circuit topology and ESD-loop guidance. |
| 28 | `ti-sszb130` | Texas Instruments SSZB130E, *System-Level ESD Protection Guide*, Aug. 2025 | 25 pp | Device-selection/application context; does not replace IEC system testing. |

### F. Trade/manufacturing guidance (3)

| # | Manifest key | Source | Size | Scope |
|---:|---|---|---:|---|
| 29 | `altium-depanelization` | Altium, *Mouse Bites and V-Scores: How to Depanelize PCBs* | 7 pp | Qualitative trade guidance; dimensions belong to the selected process profile. |
| 30 | `pcb-manufacturing-1` | *Navigating PCB Manufacturing - Part 1* | 20 pp | Manufacturing-process overview; publisher/provenance metadata incomplete. |
| 31 | `pcb-manufacturing-2` | *Navigating PCB Manufacturing - Part 2* | 25 pp | Manufacturing-process overview; figure-derived dimensions are not authority. |

## Supporting local material outside the 31-source manifest

### KiCad Library Convention snapshot

`Books/klc-master` contains KiCad Library Convention v3.0.67. Its embedded
history identifies v3.0.67 as 2026-06-20, but the copied directory has no `.git`
metadata. The exact upstream commit and local acquisition date are therefore
unknown. Treat it as a versioned style/contribution snapshot, not an electrical,
safety, or manufacturing standard. Particularly relevant areas include:

- symbol and footprint naming/orientation conventions;
- courtyard and BGA courtyard expectations;
- finished-hole semantics;
- exposed/heatsink pad and thermal-via properties;
- solid zone connections for heatsink/thermal vias; and
- library contribution quality, not product compliance.

Before machine enforcement, pin the upstream commit corresponding to this
snapshot and record the official repository URL and acquisition date.

### Historical application specification

`docs/reference/PCB_Application_Specification.pdf` is a 192-page early product
and architecture specification. It remains useful for goals, vocabulary, and
decision history. It is **not empirical PCB authority**. Important portions are
superseded: it recommends manual/FreeRouting workflows and says not to build a
custom router, whereas the current canonical project deliberately uses a
deterministic custom-routing architecture. Cite it only as historical product
context and resolve every conflict in favor of the current canonical handoff,
architecture, roadmap, and tested implementation.

### Claude chat archive and web workflow

The 278 files under `Old Chat Logs` (including 127 JSONL files and eight PDFs)
are discovery/history material. The July engineering session recovered useful
source URLs and contradiction history, but its verifier stage failed. Cryptic
`webfetch-*.pdf` artifacts lack durable title/revision/URL/license mapping and
must not be cited. Reacquire important leads from official publishers, hash
them, and record metadata before promotion.

## Edition, integrity, and provenance audit

### Content identity and extraction

- All six core book hashes checked during the audit match the manifest.
- The complete 31-entry manifest now provides stable file hashes and cache
  directories, but generally lacks title, author, revision, official URL,
  acquisition date, rights status, authority, and extractor-version fields.
- EPUB text does not preserve figures. Figure-based values in Bogatin and
  Coombs require visual access to the source.
- Johnson is OCR-derived; equations, exponents, and unit glyphs need page-image
  verification.
- Ott extraction drops the micro symbol on some pages. The common-mode table
  ambiguity was closed by dimensional arithmetic and page adjudication;
  microamps, not milliamps, is the supported interpretation.
- EN 55032's local PDF has a malformed final cross-reference/EOF line.
  `pypdf` failed, while `pypdfium2` opened it and recovered text from all 110
  pages. Retain that recovery note with the manifest entry.
- National BS/DIN adoptions are useful only after matching their base IEC/CISPR
  edition, amendments, national deviations, and current EU harmonized status.

### Revision status that changes authority

| Local source | Official status checked 2026-07-14 | Consequence |
|---|---|---|
| IPC-2221B | IPC revision table lists IPC-2221C, Dec. 2023 | B remains useful but must not be called current. Obtain C before final generic design-rule implementation. |
| IPC-7351 original 2005 | IPC says IPC-7351 is no longer maintained | Historical/corroborative only; use IPC-7352 and selected-part manufacturer data. |
| IPC-7352:2023 | Local cover says May 2023; IPC revision table lists original publication 7/23 | Current IPC generic land-pattern guideline in the collection. |
| IPC-2152 | IPC revision table says no longer maintained | Still important measured historical data, but do not describe it as an actively maintained current standard. |
| IEC 60664-1:2020 | IEC current consolidated version is 2020 + AMD1:2025 | Local hash predates and therefore lacks COR1:2020 and AMD1:2025. COR1 replaces informative Figure G.1 (2 of 2), not Table F.5. Current official edition must lead safety work. |
| EN/BS 55032:2015 | CISPR current valid base is 2015 + AMD1:2019; EU EN reference includes A11:2020 | Local 2015 base is incomplete for current conformity. |
| EN/BS 55035:2017 | EU harmonized reference includes EN 55035:2017/A11:2020 | Local base lacks A11:2020. |
| DIN EN 61000-6-1:2002/2007 | IEC current publication is IEC 61000-6-1:2016 | Both local copies are historical. Generic standard applies only when no relevant product/product-family standard exists. |
| IPC-A-610G:2017 | Later IPC revisions exist | Retain as pinned acceptance history; obtain current revision before class-specific final acceptance rules. |
| NASA EEE-INST-002 local copy | Dated profile/currentness unresolved | Opt-in only; never a silent commercial default. |

### Rights and redistribution

Several local filenames identify LibGen/Z-Library sources. Hashes prove content
identity, not lawful acquisition or redistribution rights. Keep source files
and extracted caches private and gitignored. For a redistributable evidence
bundle, use official public NASA/vendor/standards status pages, permitted short
summaries, and independently written machine rules.


## Detailed cross-source synthesis

### Edge rate, bandwidth, and electrical length

The sources are not actually contradictory; they use different frequency
definitions:

- Bogatin uses `0.35 / tr` as signal bandwidth (section 2.10).
- Johnson uses `0.5 / tr` as a conservative knee-frequency screen (PDF
  pp. 11-14, Eq. 1.1).
- Ott and Montrose discuss principal content near `1 / (pi * tr)`.
- Montrose's `10 / (pi * tr)` is a conservative tenth-harmonic emissions
  extent (PDF pp. 73-75), not a general SI or PDN operating frequency.

The implementation must use separate, explicitly named helpers. Reusing the
emissions extent for impedance, termination, via, or power-integrity decisions
would silently overstate frequency by an order of magnitude.

Johnson's `l/6` electrical-length criterion (PDF pp. 16-17, Eqs. 1.3-1.4)
and Bogatin's 20%-of-rise-time criterion (section 8.9) converge near
`25.4 * tr_ns mm` on ordinary FR-4. At a 3 ns edge this is about 76 mm, not
150 mm. Crossing the value means **review the interconnect as a transmission
line**. It does not mean "automatically terminate." The final decision needs
actual driver impedance, receiver/load, topology, routed delay, and noise
budget. Use the fastest credible device edge, not only clock frequency.

### Crosstalk and spacing

Montrose's 3-W centerline rule (PDF pp. 150-151) is a 2-W edge gap for
equal-width traces, consistent with Bogatin's example. Johnson adds the missing
reference-plane-height dependence: coupling/return distribution follows a
D/H-dependent relationship (PDF p. 198, Eq. 5.1; worked bound pp. 209,
Eqs. 5.14-5.15).

Use D/H-aware geometry or a field solver when a continuous close plane exists.
A 2-W gap is only a craft floor when the stack is unknown. Coupled length,
aggressor edge, switching direction, victim impedance, and allowed noise also
matter. A distant, slotted, necked, or fragmented reference plane breaks the
assumptions. "Same bus" does not imply harmless coupling: adjacent bits may
switch in opposite directions and still lose timing/noise/EMC margin.

### Return paths and reference continuity

Johnson, Ott, Montrose, Bogatin, Williams, and Coombs converge strongly:

- high-frequency return current follows the lowest-inductance geometry close
  to the signal;
- slots, plane voids, merged antipads, and layer changes without a return
  transition enlarge the loop;
- shared return impedance couples high-current and sensitive circuits;
- connector pin fields need distributed returns and continuous copper webs;
- fast-signal reference changes need a nearby stitching via/capacitor selected
  for the actual reference transition.

Ott's 1.5-inch slot example increased the cited signal from 15 mV to 75 mV
(PDF pp. 650-651), but the exact 5x result is geometry-specific. Use it as
mechanism evidence, not a multiplier. Continuous reference copper is the
default. A split/moat/single bridge is allowed only when a declared isolation,
converter, or vendor architecture requires it and every signal/return crossing
is controlled.

Bogatin contains both a rough total-return-width shortcut of `3w` and a more
geometry-general statement of about `3h` extension on each side for the cited
1% impedance target (section 7.17). Do not encode total `3w` as an exact rule.

### Mixed-signal grounding

Williams and Montrose describe split-ground/single-bridge arrangements, but
also allow carefully laid-out common ground. Ott and Bogatin favor continuous
reference copper with functional zoning and controlled current paths. Montrose
notes that parts with internally joined AGND/DGND need a common solid plane.

Resolution: default to a continuous ground reference. Use placement, current
path, filtering, and local routing to separate noisy and sensitive functions.
Permit a split only as an explicit architecture with controlled crossings and
return-path proof. Do not make the earlier generic mixed-signal moat proposal a
default rule.

### Decoupling and power integrity

The books agree on the mechanism more than on capacitor-count folklore:

- Johnson and Williams emphasize short connections and local energy.
- Ott quantifies mounted connection inductance: example mounting choices range
  from roughly 2.8 nH to 0.4-0.5 nH (PDF pp. 481-482).
- Bogatin makes target impedance and connection inductance primary (chapter
  13).
- Ott warns that uncontrolled value spreading can create antiresonance
  (PDF pp. 460-467).

Grade the routed pin-cap-return loop, via count, and mounted geometry before
raw XY distance. Equal small local MLCC values plus separately damped bulk
energy are a defensible default, not a universal law. Mixed-value high-frequency
arrays require an impedance model or measurement. The exact component/package
datasheet overrides generic counts such as "two or four capacitors per IC."

### Two-layer speed and EMC

Johnson restricts grid-style references to small low-speed logic
(PDF pp. 204-208). Ott treats one/two-layer boards below roughly 10 MHz clocks
as the normal EMC region and 20-25 MHz success as an expert exception
(PDF pp. 659-660). Bogatin instead supplies per-interconnect edge, delay,
discontinuity, and return criteria.

Use two distinct gates:

1. a per-net SI review based on edge time, routed delay, topology, impedance,
   crosstalk, discontinuities, and return continuity; and
2. a system EMC advisory based on periodic sources, cables, enclosure, board
   dimensions, return geometry, and the applicable test profile.

Ott's 10 MHz statement is an architecture review trigger, not a hard electrical
ceiling. A layout checklist cannot guarantee EN 55032/55035 compliance.

### Trace, via, package, and board thermal behavior

JESD51-2A and JESD51-7 define measurement context. JESD51-7's 2s2p
high-conductivity test board intentionally approaches a favorable package
environment; its theta-JA is not portable to a small two-layer application
board. Coombs chapter 23 likewise states that theta-JA is not a component
constant and can move by 2x or more with PCB construction.

Brooks and Adam show that trace and via temperature depends on adjoining copper,
dielectric conduction, plating, stack, and nearby heat spreading. The old
"internal trace gets half current" shortcut and a universal amps-per-via table
are not valid models. IPC-2152 is now marked "No Longer Maintained" by IPC, but
its measured multidimensional data remains better historical evidence than
mislabeling the legacy IPC-2221A `k` equation as IPC-2152.

Newly recovered Coombs chapter 23 anchors:

- use solid rather than thermal-relief connections for heat-conducting vias;
- a common exposed-pad example uses about 0.3 mm drill, 1.0-1.2 mm pitch, and
  at least 0.025 mm plating;
- its worked 0.3 mm drill / 25 um plating / 0.38 mm length example is about
  45 C/W per via, so a 4x4 ideal parallel array is about 2.8 C/W;
- 15 um plating changes that example to about 73 C/W per via;
- through thermal vias need filling/protection where solder wicking matters.

These are calculator anchors and mechanism checks, not a universal footprint.
The same applies to Coombs' example of diminishing returns beyond 15 mm copper.

The Richtek SOT-223 curve and the TI/onsemi legacy curve show strong benefit
from copper area, but they are package/board/convection specific. TI SNVA036B
and onsemi/Fairchild AN-1028 share the same legacy data lineage and must count
as one experiment, not two independent confirmations.

### Manufacturing and land patterns

The selected manufacturer's current package drawing is primary for a real
component. IPC-7352 supplies a generic tolerance/process framework and explicitly
permits application-specific adjustment. Its density A/B/C labels mean
maximum/median/minimum land protrusion, not IPC assembly Classes 3/2/1.

IPC-7352 limitations that must remain attached:

- heat dissipation and shock/vibration are not solved by the generic land
  pattern;
- its courtyard method is reflow-oriented;
- other solder processes may need adjustment;
- the component datasheet can differ from the generic outline;
- manufacturing/assembly/test allowance beyond the courtyard is not defined by
  IPC-7352 and must be agreed with the process owner;
- default mask/paste concepts do not settle exposed-pad stencil segmentation,
  voiding, solder wicking, or BTC/QFN thermal-via construction.

KLC 3.0.67 is a separate library-policy layer. It controls naming, metadata,
artwork, origins, and consistent library defaults; it does not prove electrical
safety, fabricability, or finished-board acceptance. Its 0.15 mm annular-ring
and courtyard conventions do not replace IPC tolerance analysis or a
fabricator capability declaration.

Coombs' 8:1/10:1 aspect-ratio discussion is a process warning, not a universal
hard cap. Via-in-pad filling/capping is strongly supported for solderable lands,
but the actual structure must be declared in the fab/assembly profile.

### ESD and connector entry

TI SLVA680A supports the ordinal topology connector -> TVS -> protected
circuit, no branch/stub before the TVS, and the first via after the shunt
device (pp. 4, 6, 9). In its cited IEC pulse example, 0.25 nH contributes
about 10 V of inductive overshoot. The number explains why shunt inductance
matters; it is not a universal clamp-voltage limit.

Layout can reduce stress but cannot claim IEC 61000-4-2 system compliance.
That requires the exact test edition, level, coupling method, operating mode,
and pass/fail behavior.

Williams' one-point chassis bond addresses a low-frequency/common-impedance
case. Ott's multiple short RF bonds and 360-degree shield termination address
high-frequency shield current. They become consistent once frequency and
current path are declared.

### RF, antenna, USB, oscillator, and sensors

Espressif supports module antenna placement at or beyond the baseboard edge or
a module-specific cutout when overhang is impossible. The often-repeated 15 mm
value is clearance to enclosure/nearby objects, not a blanket PCB-copper or
board-edge keepout. Final range/throughput testing remains required.

Keep USB profiles separate:

- ESP32-C3 native USB: vendor 90 ohm differential target, matched routing,
  continuous reference, few vias, and paired ground-return vias.
- USB Type-C R2.5: connector/type-specific mechanics, shielding, and mated
  launch context.
- Type-C's informative reference footprint never overrides the selected
  connector drawing.
- A Type-C SuperSpeed launch target is not a USB 2.0 routing number.
- USB-IF's USB 2.0 base package and electrical compliance specification are
  separate sources from the Type-C connector specification.

Official online sources verified during this audit add useful scoped evidence:

- TI SPRAAR7J (Nov. 2018, revised Feb. 2023) is a modern high-speed interface
  layout guide. It separates USB2 from faster differential interfaces and
  covers reference planes, via discontinuities, symmetry, stubs, and ESD/EMI.
- TI SNVA021C (1999, revised 2013) is useful for switcher loop, feedback, input
  capacitor, and noisy-inductor mechanisms. Its "15 mil per amp" and "one
  standard via per 200 mA" statements are old rules of thumb and are
  quarantined by the stronger electrothermal evidence.
- NXP AN2536 Rev. 2 (Apr. 2006) is an i.MX/PC100 memory-bus case study, not a
  universal high-speed standard.
- ST AN2867 is current enough to be actively revised; ST product pages showed
  Rev. 24 dated Mar. 2026. Acquire the current revision rather than the older
  chat-linked revision.

Sensirion's official *Design Guide for Humidity and Temperature Sensors*,
D1 Version 2, March 2024, was text-verified online. At 90% RH it states that a
1 C sensor temperature error can create a 5% RH signal error (PDF p. 8). It
recommends distance from heat sources, thin metal connections, removing
unnecessary metal, milled/etched slits, shielding from heated airflow, and
coupling the sensor to ambient air (pp. 8-11). This verifies the mechanism and
headline sensitivity, but **does not specify one universal moat width, slot
pattern, or bridge geometry**.

The SMTA paper *Weight Limits for Double Sided Reflow of QFNs* by Smith,
Connell, and Christian was also reviewed online. For its SAC305 experiment it
reports failure near 0.0269 g/mm of component mass per total wetted perimeter
and recommends a 20% buffer, yielding 0.0215 g/mm (PDF pp. 5-8). The experiment
used only two QFN types, OSP, a 100 um stencil, no-clean SAC305, specific pad
patterns/void accounting, and a 244 C peak; oven turbulence and board reuse
were acknowledged limitations. The authors explicitly request broader package
and oven validation. Preserve the result as primary experimental evidence, not
a universal retention blocker.

### Corners

Bogatin and Montrose find ordinary PCB corners negligible for SI/EMI at the
project's nanosecond-scale edges. Williams repeats acid-trap lore; Coombs
explains why modern etching reduces that fabrication concern. Do not create a
general right-angle SI blocker. Avoid acute trace-to-pad entries and prefer
45-degree/rounded routing for craft, density, or a declared HV/fabrication
reason, labeled honestly.


## Standards-specific extraction

### IEC 60664-1:2020 base: insulation coordination

**Edition warning:** the local file is the 2020 base. IEC's current consolidated
publication is IEC 60664-1:2020+AMD1:2025 (edition 3.1). The pinned hash does
not contain AMD1:2025, and COR1:2020 incorporation was not independently
confirmed. The following facts must be checked against the current official
edition before a conformity claim.

Scope and decision inputs:

- rated voltage up to 1,000 VAC or 1,500 VDC;
- fundamental frequency up to 30 kHz;
- table values through 2,000 m, with higher-altitude guidance;
- it is a horizontal/basic safety publication and does not displace the
  applicable end-product standard;
- clearance depends on impulse/peak/temporary voltage, overvoltage category,
  field distribution, pollution and altitude;
- creepage depends on long-term RMS working voltage, pollution degree,
  material group/CTI, orientation/geometry, time and insulation function;
- creepage cannot be less than the associated clearance.

Pollution degree definitions (local PDF p. 22, 4.5.2):

- PD1: no pollution or only dry, nonconductive pollution;
- PD2: normally nonconductive pollution, with temporary conductivity from
  occasional condensation expected;
- PD3: conductive pollution, or dry pollution that becomes conductive through
  expected condensation;
- PD4: persistent conductivity. Creepage cannot be assigned by the normal
  method for this condition.

Material groups by CTI (local PDF p. 30, 5.3.2.4):

| Material group | CTI |
|---|---:|
| I | >= 600 |
| II | 400 to <600 |
| IIIa | 175 to <400 |
| IIIb | 100 to <175 |

Other high-value rules:

- inhomogeneous-field Case A is the conservative default; homogeneous Case B
  needs controlled geometry and withstand verification if its smaller values
  are used (PDF p. 28);
- reinforced clearance uses one preferred rated-impulse step above basic, or
  160% of the basic withstand voltage where the value is not in the preferred
  series (PDF p. 29);
- reinforced creepage is twice basic creepage (PDF p. 33);
- printed-wiring reduced values are limited to PD1/PD2 conditions; PD2 may
  require added pollution protection. Solder mask cannot be assumed to turn an
  arbitrary board into PD1 or reinforced insulation;
- a slot/groove changes measured creepage only if its geometry meets the
  standard's rules; a decorative narrow slot is not automatically effective;
- a switching/flyback waveform above 30 kHz needs IEC 60664-4 or applicable
  product-standard treatment. IEC 60664-4:2005 covers periodic stress above
  30 kHz through 10 MHz when used with Part 1/5.

Useful local-base table examples, **not standalone design rules**:

- for a 230/400 V supply, Table F.1 maps the rationalized 300 V system level to
  1.5 kV (OVC I), 2.5 kV (OVC II), 4 kV (OVC III), and 6 kV (OVC IV);
- Table F.2 Case A shows 1.5 mm for 2.5 kV, 3.0 mm for 4 kV, and 5.5 mm for
  6 kV at the stated base altitude/conditions;
- Table F.5 text extraction at 250 V gives PCB columns of 0.56 mm (PD1) and
  1.0 mm (PD2), while general-material PD2 values are 1.25/1.8/2.5 mm for
  groups I/II/III and PD3 values 3.2/3.6/4.0 mm;
- design altitude multipliers above 2,000 m in the local base are 1.14 at
  3,000 m, 1.29 at 4,000 m, 1.48 at 5,000 m, 1.70 at 6,000 m, 1.95 at
  7,000 m, 2.25 at 8,000 m, 2.62 at 9,000 m, and 3.02 at 10,000 m.

Never compile these as a bare voltage-to-distance lookup. The input tuple must
include controlling product standard, insulation function, RMS/peak/frequency,
supply/OVC, pollution degree, CTI/material group, altitude, field case, and
coating/encapsulation regime.

### IPC-2221B

The local Table 6-1 values remain useful for revision-B generic printed-board
spacing when the exact row/column category is retained. They do not map
directly to IEC pollution degree, material group, or basic/reinforced
insulation. The earlier 6.4 mm confusion is resolved: that value is the
uncoated-external-conductor cell above 3,050 m, not a generic reinforced-mains
requirement.

IPC-2221C (Dec. 2023) is current. IPC says it revised or added material/copper
selection, palletization, edge plating, clearance/corona/creepage, impedance
tolerance, plane clearance, feature tolerances, compliant pins and backdrilling.
Any rule in those areas needs a C-edition check before being called current.

### IPC-7352:2023

IPC-7352 says manufacturer package data is primary and table values are
guidelines rather than absolutes. Density levels may be mixed where the
application requires it.

Selected table values below are retained as research data in millimetres,
formatted A / B / C. **They were independently text-extracted but the dense
table pages could not be visually inspected during this run because the Windows
sandbox renderer failed. Do not machine-encode them until rendered-page QA.**

| Termination family | Toe | Heel | Side | Courtyard excess | Locator |
|---|---:|---:|---:|---:|---|
| Gullwing / flat-ribbon L | 0.55 / 0.35 / 0.15 | 0.45 / 0.35 / 0.25 | 0.05 / 0.03 / 0.00 | 0.50 / 0.25 / 0.10 | p.19, Table 3-1 |
| Rectangular/square end, width >=0.5 mm | 0.55 / min(25% height,0.50) / 0.15 | 0 | 0.05 / 0 / 0 | 0.50 / 0.25 / 0.10 | p.20, Table 3-3 |
| Rectangular/square end, width <0.5 mm | 100% / 50% / 25% of height | 0 | 0 | 0.20 / 0.15 / 0.10 | p.20, Table 3-4 |
| MELF | min(100% diameter,1.0) / 0.40 / 0.20 | 0.20 / 0.10 / 0.02 | 0.55 / 0.35 / 0.15 | 0.50 / 0.25 / 0.10 | p.20, Table 3-5 |
| Concave/castellated | 0.25 / 0.15 / 0.05 | max(50% height,0.65) / max(25% height,0.45) / 0.45 | 0.05 / 0 / 0 | 0.50 / 0.25 / 0.10 | p.20, Table 3-6 |
| Flat no-lead with solderable vertical surface | 120% / 110% / 100% of lead height | 0 | 0 | 0.50 / 0.25 / 0.10 | p.21, Table 3-10 |
| Electrolytic/two-pin crystal, height <10 mm | 0.70 / 0.50 / 0.30 | 0 | 0.50 / 0.40 / 0.30 | 1.0 / 0.5 / 0.25 | p.22, Table 3-14 |
| Small-outline flat lead | 0.30 / 0.20 / 0.10 | 0 | 0.05 / 0 / 0 | 0.20 / 0.15 / 0.10 | p.23, Table 3-15 |

The BGA Table 3-11 extraction renders its middle courtyard as `100 mm`.
A 600 dpi Poppler render of the local source was inspected directly on
2026-07-14 and the page itself visibly prints **`100 mm`**: this is not a lost
decimal introduced by OCR or text extraction. The value is physically
implausible between 2.00 mm (Level A) and 0.50 mm (Level C). KiCad's public KLC
discussion independently describes the nominal BGA value as 1 mm, but no
official IPC erratum or corrected licensed copy was found. **Do not encode
either 100 mm or an inferred 1.00 mm as an authoritative rule.** Quarantine the
Level-B BGA courtyard value pending an IPC correction or corrected source.

Courtyard is the maximum component/land extent plus family excess.
Manufacturing allowance is additional and is not defined by IPC-7352. A global
0.25 mm Level-B courtyard is therefore false. KLC's default 0.25 mm is a
library convention, not the IPC family table.

### KLC 3.0.67 details

Useful library conventions, subject to manufacturer override:

- manufacturer package/datasheet recommendations win over generic KLC geometry;
- connected thermal copper/vias use the same electrical pad number;
- encode datasheet keepouts as named rule areas with explanatory comments;
- footprint/pad local clearances default to zero unless the datasheet requires
  an override; board manufacturing rules remain separate;
- silkscreen nominal graphic line 0.12 mm and reference text 1.0 mm high /
  0.15 mm stroke; preserve visible pin-1/polarity information;
- fabrication outline nominal 0.10 mm and body-centred SMD origins unless the
  datasheet defines otherwise;
- courtyard is a closed 0.05 mm line on a 0.01 mm grid, with KLC family/style
  defaults and explicit connector mating allowance;
- exposed-pad paste is commonly windowed and thermal-via variants are distinct;
  vias share the exposed-pad number and use solid zone connection;
- KLC THT hole/ring values are library construction policy, not finished-board
  acceptance.

The archive reports v3.0.67 and contains an embedded history date, but has no
upstream Git commit. Store the pin as version known, exact commit/acquisition
provenance unknown; do not imply a reproducible upstream snapshot until the
commit is recorded.

### IPC-A-610G and NASA workmanship

IPC-A-610G is an acceptance standard for a finished assembly, not a footprint
generator. The local revision-G rectangular/square-end criterion requires that
solder not contact the top or side of the component body. The familiar 75%
PTH vertical-fill item is an acceptance criterion for the applicable
class/termination, not a land-pattern formula. IPC-A-610J (Mar. 2024) is
current according to IPC's revision table; use the contractually invoked
revision and pair it with the appropriate J-STD-001 process/material
requirements.

NASA-STD-8739.2 and NASA-STD-8739.3 are cancelled. Current NASA
NASA-STD-8739.6B states that cancellation and uses IPC J-STD-001GS. The old
NASA PDFs remain useful historical workmanship references, but they are not
current free replacements for J-STD-001/A-610.

NASA EEE-INST-002 Addendum 1 is a separate parts-derating source. Its numeric
derating can be an opt-in aerospace/high-reliability profile only; it must not
be a silent commercial default.

### EN 55032 emissions and EN 55035 immunity

These documents define equipment-level compliance tests, not universal PCB
geometry.

Selected EN 55032:2015 base values retained for test-profile modeling:

- each applicable port is measured; an omitted test needs documented
  inapplicability (Clause 8);
- upper radiated test frequency depends on the highest internal frequency:
  up to 108 MHz -> 1 GHz; up to 500 MHz -> 2 GHz; up to 1 GHz -> 5 GHz;
  above 1 GHz -> five times the highest frequency capped at 6 GHz; unknown ->
  6 GHz;
- Class B radiated OATS/SAC at 10 m: 30 dBuV/m from 30-230 MHz and 37 dBuV/m
  from 230-1,000 MHz; at 3 m: 40 and 47 dBuV/m;
- Class B above 1 GHz at 3 m: average 50 dBuV/m at 1-3 GHz and 54 dBuV/m at
  3-6 GHz; peak 70/74 dBuV/m;
- Class B AC-mains conducted: 0.15-0.5 MHz quasi-peak 66->56 and average
  56->46 dBuV; 0.5-5 MHz 56/46; 5-30 MHz 60/50;
- a dedicated external AC/DC adapter is tested as part of the AC-mains-powered
  equipment configuration.

Do not mix OATS/SAC with FAR limits or detector/bandwidth/distance classes.

Selected EN 55035:2017 base immunity profile:

- enclosure RF 80-1,000 MHz 3 V/m, plus 1.8/2.6/3.5/5 GHz spot frequencies
  at 3 V/m, performance criterion A;
- enclosure ESD +/-4 kV contact and +/-8 kV air, criterion B;
- applicable long signal/data ports use conducted RF and +/-0.5 kV EFT;
- applicable outdoor DC network ports use +/-0.5 kV line-to-ground surge;
- AC mains uses +/-1 kV line-line and +/-2 kV line-earth surge, +/-1 kV EFT,
  plus defined voltage dips/interruptions and criteria.

The functional annex and declared product performance decide what degradation
is allowed. A/B/C shorthand cannot replace an exact function and pass/fail
record.

Currency caveats:

- local EN 55032 base lacks CISPR 32 AMD1:2019 and EN A11:2020;
- local EN 55035 base lacks EN A11:2020;
- local DIN EN 61000-6-1 copies are obsolete; IEC 61000-6-1:2016 is current;
- generic EN/IEC 61000-6-1 applies only when no relevant product or
  product-family standard exists. Multimedia equipment normally routes to
  EN 55035;
- harmonized-standard status must be rechecked in EUR-Lex/Official Journal at
  the actual declaration-of-conformity date.


## Cross-source conflict resolutions

| Topic | Tempting merge | Resolution |
|---|---|---|
| Mains spacing | "IPC-2221B says 6.4 mm, therefore reinforced insulation" | Derive IEC/product-standard clearance and creepage separately. The cited IPC cell has altitude/exposure context. |
| Solder mask | "Mask means coated or PD1" | Coating/protection requires the applicable IEC/product-standard construction and qualification. |
| Clearance vs creepage | One voltage-to-distance table | Clearance is impulse/field/altitude driven; creepage is long-term RMS/pollution/CTI driven; creepage is never below clearance. |
| IPC density vs class | IPC-7352 A/B/C equals IPC Classes 3/2/1 | Density/protrusion and assembly class are different axes. |
| Courtyard | Global 0.25 mm Level B | Use the selected IPC family table or versioned KLC project policy, plus mating/manufacturing allowance. |
| KLC annular ring | KLC 0.15 mm proves board acceptance | KLC is library policy; tolerance analysis and invoked fab/acceptance standard still control. |
| Assembly acceptance | IPC-A-610 creates footprint geometry | Manufacturer drawing and land-pattern/process evidence generate geometry; A-610 inspects the result. |
| EMC standards | EN 55032/55035 values become trace DRC | They create equipment/port test profiles; layout books and vendor data explain mitigation mechanisms. |
| Theta-JA | Datasheet theta-JA is a component constant | Carry package, board, orientation, ambient and test-method metadata; model the real board. |
| Via ampacity | Fixed amps per via | Use coupled trace/via/board electrothermal inputs and fabrication tolerance. |
| Espressif antenna | 15 mm PCB-edge keepout | It is enclosure/object clearance in the cited context; use exact module geometry and RF validation. |
| Double-sided QFN | 0.0215 g/mm is universally safe | It is a useful SAC305 experiment with a narrow package/process set; require an assembly profile and broader validation. |
| Sensor moat | A fixed slot width follows from the 5%RH finding | The sensitivity and isolation mechanism are verified; geometry remains board/housing/process specific. |
| TI/onsemi SOT-223 | Two independent experiments | SNVA036B and AN-1028 share a legacy data lineage; count once. |
| Corners | 90-degree bends are a general SI/EMI defect | No general blocker for ordinary project edges; retain craft/HV/fab-specific policy only. |

## Do-not-encode docket

These statements are either rejected or must remain advisory/review-only until
the named evidence closes.

| Claim or policy | Why it is not ready | Release condition |
|---|---|---|
| Bare voltage -> spacing lookup | Omits insulation function, waveform/frequency, OVC, PD, CTI, altitude, field and product standard. | Complete insulation profile and current applicable standards. |
| IEC Table F.5 values as machine rules | Base-edition 250 V row and footnotes were visually checked at 600 dpi; the local copy still lacks AMD1:2025. | AMD1:2025 comparison before encoding a current safety rule. |
| IPC-7352 BGA middle courtyard | The local page visibly and literally says `100 mm`; it is a source-document anomaly, not an OCR failure. | Obtain an official IPC correction or corrected licensed copy; do not silently substitute 1.00 mm. |
| Universal 0.25 mm Level-B courtyard | IPC-7352 values vary by termination family. | Package-family selection plus manufacturer/process data. |
| Old IPC-7351 table mappings | Local copy is original 2005 and some OCR tables are ambiguous. | Use IPC-7352/current manufacturer drawing; preserve revision labels. |
| Generic QFN/DFN/BTC paste, voiding or thermal-via recipe | IPC-7352 does not solve the assembly process and IPC-7093A is absent. | IPC-7093A Rev A 10/20 or equivalent package/assembler evidence. |
| Universal double-sided QFN retention blocker | Two QFN types and one defined SAC305 process do not span all assemblies. | Process profile plus wider package/oven validation. |
| Fixed 1.0 mm sensor moat/bridge | Sensirion supports isolation but gives no universal dimensions. | Exact sensor/housing thermal target, fab limit and validation. |
| "No termination below 150 mm at 3 ns" | Johnson/Bogatin review threshold is near 76 mm and is not a termination command. | Per-net transmission-line analysis. |
| Use `10/(pi*tr)` for every high-frequency check | It is emissions extent, not SI/PDN bandwidth. | Never release as a generic helper; keep separate definitions. |
| Same-bus traces may always use manufacturing minimum | Opposite switching, timing, noise and emissions still matter. | Per-bus electrical/coupling budget and validation. |
| Default mixed-signal moat/split plane | Cross-source evidence favors a continuous reference by default. | Declared architecture and proof of every crossing/return. |
| Exact total `3w` return corridor | Source contains a more geometry-aware `3h`-per-side statement. | Geometry-specific model/solver or scoped use. |
| Universal 2-layer 10 MHz blocker | Ott's statement is an EMC architecture recommendation. | Keep advisory; use per-net SI and product-level EMC gates. |
| Universal two/four decaps per IC | Package, rail and target impedance vary. | Datasheet/package constraints and impedance evidence. |
| One unvarying capacitor value per rail | Equal small values help antiresonance control, but bulk/damping needs differ. | PDN model or measured impedance for stronger claims. |
| Universal connector co-location blocker | Isolation, safety, mechanics or function may require separation. | System architecture and common-mode review. |
| Generic 20 dB guard/return-via benefit | Measured result is geometry specific. | Match geometry or model/measure the actual stack. |
| Universal 20-H plane inset | Benefit is geometry/resonance dependent and disputed. | Declared cavity problem and analysis. |
| Legacy IPC-2221A `k` equation called IPC-2152 | IPC-2152 is measured multidimensional data and is now historical/no-longer-maintained. | Label the chosen empirical model honestly with its limits. |
| TI SNVA021 15 mil/A | Old topology note rule of thumb lacks full thermal inputs. | Use a declared thermal/current model. |
| TI SNVA021 one via/200 mA | "Standard via" is undefined and conflicts with coupled via evidence. | Actual via/plating/stack/copper thermal analysis. |
| Generic current rating from one 10 mil via example | Via heating is coupled to traces, planes and fabrication. | Actual geometry/process electrothermal model. |
| JESD51-7 theta-JA copied to small 2-layer board | 2s2p test board is intentionally high conductivity. | Board-specific model/test or closer test-board evidence. |
| SOT-223 curve generalized to other packages | Package/tab/board/convection specific. | Package-specific vendor data/model. |
| USB-C 85-ohm launch target copied to USB2/ESP32 | Different interface and measurement context. | Separate USB2, SuperSpeed and device-native profiles. |
| Type-C informative footprint copied to connector | Tabs, shell and pads vary by MPN. | Exact connector drawing. |
| Right-angle corner SI/EMI blocker | Cross-source physics does not support it at ordinary edges. | Only a declared craft/fab/HV reason. |
| Universal one-point chassis bond | Low-frequency and RF shield currents require different structures. | Frequency/current-path/chassis policy. |
| Panel/tab/V-score dimensions from trade figures | Fabricator and process dependent. | Approved supplier panel profile. |
| NASA 8739.2/8739.3 as current IPC replacement | Both are cancelled. | Use current NASA/contract requirement, e.g. applicable J-STD-001 space addendum. |
| Chat `[HIGH]` label as verified evidence | The intended verifier panels returned no independent results. | Primary source pinned and checked. |

## Strong implementation candidates after policy decisions

These mechanisms have strong evidence, but severity and applicability still
need explicit project policy:

1. Detect fast/sensitive routes crossing reference gaps or changing reference
   without a nearby return transition.
2. Detect shared return copper between high-current loops and sensitive
   analog/logic references; calculate the relevant voltage-drop budget.
3. Grade the routed decoupling pin-cap-return loop and mounted connection
   geometry, not only Euclidean placement.
4. Trigger per-net electrical-length review from actual minimum rise/fall time
   and routed delay.
5. Enforce connector -> TVS -> protected-circuit order with no pre-TVS branch
   for declared protected ports.
6. Apply module-specific ESP32 antenna polygons and keep enclosure/object
   clearance distinct from PCB copper geometry.
7. Require thermal evidence metadata; reject naked theta-JA as transferable.
8. Make selected-part manufacturer geometry primary and use IPC-7352/KLC as
   explicit cross-check/policy layers.
9. Reject floating guards/pours as return structures; require stitching where
   they are intended to carry high-frequency return current.
10. Keep bend style as craft unless a declared fabrication or electric-field
    requirement makes it functional.

## Evidence-aware rule record

A future canonical rule should resemble:

```yaml
rule_id: stable_identifier
source_statement: "What the source actually supports"
source:
  title: "..."
  revision: "..."
  organization_or_author: "..."
  authority: vendor_primary
  locator: "PDF p. 25, Figure ..."
  official_url: "..."
  local_sha256: "..."
  source_status: pinned
  locator_status: figure_verified
applicability:
  required_conditions:
    - named package_or_interface
    - declared stackup_or_process
  exclusions:
    - unrelated package families
    - unreferenced geometry
  status: confirmed
project_policy:
  check: "Machine-evaluable interpretation"
  severity: review
  override_requires:
    - manufacturer evidence
    - approved process profile
implementation:
  status: proposed
  tests: []
```

This prevents a verified quotation from silently becoming a universal blocker
and preserves why project policy can be stricter or looser than a source
example.

## Online primary sources and current-status checks

Checked on 2026-07-14:

- [IPC document revision table](https://www.ipc.org/ipc-document-revision-table):
  IPC-2221C Dec. 2023; IPC-A-610J Mar. 2024; J-STD-001J Apr. 2024;
  IPC-7351 and IPC-2152 no longer maintained; IPC-7352 original 2023;
  IPC-7093A Rev A Oct. 2020.
- [IEC 60664-1 official publication](https://webstore.iec.ch/en/publication/59671):
  current consolidated edition includes AMD1:2025; base scope is up to 30 kHz.
- [IEC 60664-4:2005](https://webstore.iec.ch/en/publication/2804):
  high-frequency insulation stress above 30 kHz through 10 MHz, used with
  Part 1/5.
- [IEC 61000-6-1:2016](https://webstore.iec.ch/en/publication/25631):
  current generic residential/commercial/light-industrial immunity base.
- [CISPR 32:2015+AMD1:2019](https://webstore.iec.ch/en/publication/65836).
- [EUR-Lex EU 2020/1630](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32020D1630):
  EN 55032:2015/A11:2020 reference.
- [EUR-Lex EU 2021/455](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX:32021D0455):
  EN 55035:2017/A11:2020 reference.
- [NASA inactive/cancelled standards](https://standards.nasa.gov/NASA-inactive-cancelled-standards)
  and [NASA-STD-8739.6B](https://standards.nasa.gov/sites/default/files/standards/NASA/B/0/nasa-std-87396b.pdf):
  8739.2/8739.3 cancelled; current implementation invokes IPC J-STD-001GS.
- [Sensirion Design Guide, v2, Mar. 2024](https://sensirion.com/media/documents/FC5BED84/662B494D/Sensirion_Humidity_Temperature_Design_Guide.pdf).
- [SMTA QFN double-sided-reflow paper](https://www.circuitinsight.com/pdf/weight_limit_qfn_smta.pdf).
- [TI SPRAAR7J](https://www.ti.com/lit/pdf/spraar7),
  [TI SNVA021C](https://www.ti.com/lit/pdf/snva021),
  [NXP AN2536](https://www.nxp.com/docs/en/application-note/AN2536.pdf), and
  [ST AN2867](https://www.st.com/resource/en/application_note/an2867-guidelines-for-oscillator-design-on-stm8afals-and-stm32-mcusmpus-stmicroelectronics.pdf).
- [USB-IF USB 2.0 package](https://www.usb.org/document-library/usb-20-specification),
  dated 2025-06-03, and [USB 2.0 electrical compliance specification](https://www.usb.org/document-library/usb-20-electrical-compliance-test-specification),
  version 1.08 dated 2026-04-21.
- [IPC-7352 official TOC](https://www.ipc.org/TOC/IPC-7352-TOC.pdf).
- [IPC-7093A official TOC](https://www.ipc.org/TOC/IPC-7093A-toc.pdf).

These URLs establish publisher identity and status but do not replace pinning
the exact source, hash, revision, and rights/acquisition record.

## Ranked evidence and acquisition priorities

1. **Applicable end-product safety standard per generated design family.**
   Without it, IEC insulation coordination can be parameterized and flagged
   but not declared compliant.
2. **IEC 60664-1 AMD1:2025/consolidated edition plus IEC 60664-4:2005** for
   flyback/high-frequency insulation.
3. **IPC-2221C and IPC-2222B** for current generic/rigid-board design.
4. **IPC-7093A** for BTC/QFN/DFN paste, voiding, exposed-pad and thermal-via
   decisions.
5. **Current IPC-A-610J and J-STD-001J** only if PCBSmith will make current
   assembly acceptance/process claims.
6. **EN 55032 A11/CISPR AMD1 and EN 55035 A11**, selected by actual product
   scope, plus current OJEU status at declaration time.
7. **USB-IF USB 2.0 base/electrical sources** for USB2 profiles; keep separate
   from Type-C mechanics and SuperSpeed.
8. **Current selected-part vendor sources**, including exact Espressif guide
   revisions, ST AN2867 Rev. 24 where relevant, connector drawings and crystal
   data.
9. **Local pinning of the verified Sensirion and SMTA papers**, with hashes and
   full metadata. Their text is now verified online; local provenance is not.
10. **Selected fabricator/assembler capability profiles**, including finished
    hole, registration, mask, paste, via-fill, panel and reflow constraints.

IPC-2152 remains valuable historical measured data but IPC now marks it no
longer maintained. Acquire it if accessible for model validation, but describe
its status accurately.

## Research-process requirements

1. Expand `.book-cache/manifest.json` (or a successor index) with authority,
   complete title, organization/author, revision/date, official URL,
   acquisition and rights status, extractor name/version, exact locator,
   applicability, and implementation state.
2. Keep text, OCR and visual verification separate. A table can be readable in
   extracted text but still have a shifted column or footnote.
3. Require independent evidence only when the sources are truly independent;
   republished vendor notes do not create two votes.
4. Store failed verification campaigns as provenance, not confidence.
5. Recheck time-sensitive law, harmonization, revision and product data at use
   time.
6. Never allow an unreviewed condensed note to outrank its primary source.
7. Build regression tests from the source assumptions, not only the resulting
   number.

## Visual-QA re-verification from this run

The normal local image viewer and Windows-control fallback still failed with a
sandbox-helper refresh error. A separate high-resolution path succeeded:
Poppler rendered the key pages and exact table crops were base64-forwarded to
the image channel for direct inspection.

IEC 60664-1 Table F.5's 250 V row, column mapping, and footnotes were checked at
600 dpi. IPC-7352 pages 19-23 and targeted package-family rows were checked, and
Table 3-11 visibly says `100 mm`. The earlier suspicion of an OCR-dropped
decimal was therefore wrong; the anomaly exists in the source page itself.

IEC's COR1:2020 replaces informative Figure G.1 (2 of 2). The local file was
downloaded before that corrigendum and does not include it, but COR1 does not
change Table F.5. The current controlling publication remains
IEC 60664-1:2020+AMD1:2025, which was not locally available for comparison.
See `docs/reference/standards-table-reverification-2026-07-14.md` for the exact
verified row mapping, methods, evidence hashes, and safe disposition.

## Bottom line

The current material is enough to build a strong evidence-aware engineering
layer. It is not enough to justify one monolithic "safe PCB" rule set. The
dominant reusable knowledge is mechanistic and cross-source: preserve short
return paths and loop geometry, model mounted inductance, make SI edge-rate
aware per net, make thermal decisions board/process aware, prefer current
manufacturer geometry, and keep safety, compliance, acceptance and
manufacturing constraints in separate domains.

The next phase should review this analysis and decide policy. It should not
start by transferring every number into code.
