# Layout-craft book knowledge base

The reference books live in `Books/` (gitignored, copyrighted); their
extracted text cache in `.book-cache/` (gitignored) with a sha256
manifest for locator stability. What IS committed: these per-book
notes — distilled rules with quantitative thresholds, chapter/page
locators against the pinned copy, and a "machine translation" for each
rule (what check/knob it becomes in PCBSmith). Notes are summaries and
short attributed quotes only, never reproductions.

The current cross-source entry point is
[`../current-materials-knowledge-base-2026-07-14.md`](../current-materials-knowledge-base-2026-07-14.md),
with table-image disposition in
[`../standards-table-reverification-2026-07-14.md`](../standards-table-reverification-2026-07-14.md).
[`CONSOLIDATED.md`](CONSOLIDATED.md) is historical first-wave candidate data;
it must be reconciled with the July 14 authority, applicability, and
do-not-encode decisions before any threshold is promoted.

Reading protocol (so we never pay for the same page twice):
1. TOC first; map chapters to PCBSmith rule areas.
2. Deep-read only rule-dense chapters; every extracted rule gets:
   THRESHOLD (number), WHY (mechanism), WHERE (page/section locator),
   MACHINE FORM (check/knob/router behavior), and APPLICABILITY
   (frequency/voltage/class limits — per the project law that a rule
   without its applicability range must not be encoded).
3. Contradictions between books are recorded, not silently resolved.
4. VERIFICATION STATUS: the original nine distillations were produced
   with delegated extraction and then spot-verified. The 72-rule pass
   raises confidence but is not exhaustive. Verify OCR-sensitive or
   unsampled thresholds before hard-coding; open corrections are listed
   below and in `SECOND-WAVE-2026-07.md`.

| slug | book | status |
|------|------|--------|
| bogatin-spi | Bogatin, Signal and Power Integrity — Simplified, 3rd ed. | distilled + spot-verified 8/8 (1 correction applied: R17 100 kHz onset) |
| johnson-hsdd | Johnson & Graham, High-Speed Digital Design | distilled ([notes](johnson-hsdd.md)); OCR source - 7 thresholds flagged OCR-uncertain |
| ott-emc | Ott, Electromagnetic Compatibility Engineering | distilled + spot-verified 8/8 (1 false mismatch adjudicated: cache drops the micro glyph) |
| montrose-emc | Montrose, PCB Design Techniques for EMC Compliance, 2nd ed. | distilled + spot-verified 8/8 |
| williams-cdc | Williams, The Circuit Designer's Companion (4th ed.) | distilled + spot-verified 8/8 |
| ipc-2221b | IPC-2221B, Generic Standard on Printed Board Design | distilled + spot-verified 8/8 (incl. Table 6-1 clearance cells) |
| ipc-7351 | IPC-7351 original (2005), Land Pattern Standard | historical distillation; IPC-7351 is no longer maintained, so use pinned IPC-7352 plus selected-part manufacturer data for current work |
| ipc-a-610 | IPC-A-610G, Acceptability of Electronic Assemblies | distilled + spot-verified 8/8 (1 correction: fillet top-or-side) |
| coombs-pch | Coombs & Holden, Printed Circuits Handbook, 7th ed. | distilled + spot-verified 8/8 (1 locator corrected) |

## Historical second-wave sources (2026-07)

The second wave added sixteen sources after the original nine. Their historical
grouped distillation is [SECOND-WAVE-2026-07.md](SECOND-WAVE-2026-07.md).
At the second-wave checkpoint the manifest contained 31 exact sources; six
standards/status sources were integrated by the July 14 current-materials
synthesis rather than this second-wave note. The later July 18 intake brings
the local extraction manifest to 41 registered documents, as described below.

| group | manifest slugs | status |
|---|---|---|
| Trace/via thermal | `brooks-via-trace`, `pcb-via-paper` | distilled; curves remain figure-bound |
| Reliability derating | `nasa-eee-derating` | opt-in NASA profile; current revision metadata needed |
| Espressif layout | `espressif-esp32`, `espressif-esp32c3` | distilled; antenna figures geometry-bound |
| Thermal applicability | `jesd51-2a`, `jesd51-7` | distilled; acquire JESD51-3 comparison |
| SOT-223 spreading | `richtek-an044`, `onsemi-an1028`, `ti-snva036` | points text-verified; curves figure-bound |
| ESD layout | `ti-slva680`, `ti-sszb130` | placement/order rules text-verified |
| Panelization | `altium-depanelization`, `pcb-manufacturing-1`, `pcb-manufacturing-2` | qualitative; dimensions fab-profile-bound |
| USB Type-C | `usb-type-c-r2.5` | targeted distillation; footprints informative |

### Later standards/status sources now pinned

| manifest slug | current disposition |
|---|---|
| `iec-60664-1` | 2020 base pinned; COR1 exclusion verified; AMD1:2025 and the applicable product standard still required for current safety work |
| `ipc-7352` | current generic land-pattern guideline in the collection; family tables visually sampled, BGA Level-B anomaly quarantined |
| `en-55032-2015` | historical base emission test source; later amendment/EU status required at use time |
| `en-55035-2017` | historical base immunity test source; A11/current EU status required at use time |
| `en-61000-6-1-2002` | historical national adoption, not current authority |
| `en-61000-6-1-2007` | historical national adoption, superseded by IEC 61000-6-1:2016 |

### Local additions and official-source intake (2026-07-18)

The dated audit is
[`LOCAL-SOURCE-INVENTORY-2026-07-18.md`](LOCAL-SOURCE-INVENTORY-2026-07-18.md).
It verifies full IPC-2222 original (1998), IEC 62368-1 Edition 2.0 (2014),
IPC-2152 (2009), IPC-7093/7093A (2011/2020), IPC-TM-650 compilation snapshot,
IPC-2221A (2003), and IPC-7525 original (2000) additions. The official
Sensirion Version 2 design guide and USB-IF USB 2.0 June 2025 bundle were also
downloaded and verified. These ten document sources, including the USB base
specification rather than the ZIP container, are registered in the now
41-source extraction manifest; registration means pinned/extracted, not
necessarily distilled or promoted into production rules. The complete USB
archive hash and contents are retained in the dated inventory.

IPC-7352 and IEC 60664-1 were already pinned; newly added copies are exact
duplicates. The file initially presented as IPC-2231A is actually IPC-2221A and
was renamed after cover inspection. Files labelled as IPC-2231A and IPC-7525C
previews contain mismatched IPC-1401 text and must not be counted as those
sources. The valid IPC-7525 addition is the original revision, not revision C.

### Verification debt and resolved corrections

Johnson HSDD-D1 is corrected to `1.35e-5 in^2`; IPC-2221B B3's 6.4 mm cell is
confirmed as uncoated operation above 3050 m, not generic reinforced mains
insulation. Bogatin R17, IPC-A-610 R4, and the Coombs locator are corrected but
retain audit history. Open holds are the IPC-7352 BGA Level-B printed anomaly,
IEC 60664-1 AMD1:2025/current product-standard comparison, SMTA local
provenance, current selected-part/fab/assembler profiles, targeted distillation
of newly pinned sources, and every figure-bound or OCR-sensitive threshold
named in the July 14 synthesis.
