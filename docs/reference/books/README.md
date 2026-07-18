# Layout-craft book knowledge base

The reference books live in `Books/` (gitignored, copyrighted); their
extracted text cache in `.book-cache/` (gitignored) with a sha256
manifest for locator stability. What IS committed: these per-book
notes — distilled rules with quantitative thresholds, chapter/page
locators against the pinned copy, and a "machine translation" for each
rule (what check/knob it becomes in PCBSmith). Notes are summaries and
short attributed quotes only, never reproductions.

Reading protocol (so we never pay for the same page twice):
1. TOC first; map chapters to PCBSmith rule areas.
2. Deep-read only rule-dense chapters; every extracted rule gets:
   THRESHOLD (number), WHY (mechanism), WHERE (page/section locator),
   MACHINE FORM (check/knob/router behavior), and APPLICABILITY
   (frequency/voltage/class limits — per the project law that a rule
   without its applicability range must not be encoded).
3. Contradictions between books are recorded, not silently resolved.
4. VERIFICATION STATUS: all seven distillations are subagent-
   produced and reviewed at summary level only. Verify a rule's
   page locator against `.book-cache/` before hard-coding its
   threshold; the systematic spot-check pass (random sample per
   book) is plan phase 0 work, and this table should record
   per-book verification when it happens.

| slug | book | status |
|------|------|--------|
| bogatin-spi | Bogatin, Signal and Power Integrity — Simplified, 3rd ed. | distilled + spot-verified 8/8 (1 correction applied: R17 100 kHz onset) |
| johnson-hsdd | Johnson & Graham, High-Speed Digital Design | distilled ([notes](johnson-hsdd.md)); OCR source - 7 thresholds flagged OCR-uncertain |
| ott-emc | Ott, Electromagnetic Compatibility Engineering | distilled + spot-verified 8/8 (1 false mismatch adjudicated: cache drops the micro glyph) |
| montrose-emc | Montrose, PCB Design Techniques for EMC Compliance, 2nd ed. | distilled + spot-verified 8/8 |
| williams-cdc | Williams, The Circuit Designer's Companion (4th ed.) | distilled + spot-verified 8/8 |
| ipc-2221b | IPC-2221B, Generic Standard on Printed Board Design | distilled + spot-verified 8/8 (incl. Table 6-1 clearance cells) |
| ipc-7351 | IPC-7351 (ORIGINAL, 2005 - not B!), Land Pattern Standard | distilled ([notes](ipc-7351.md)); exception tables need re-check vs a 7351B copy |
| ipc-a-610 | IPC-A-610G, Acceptability of Electronic Assemblies | distilled + spot-verified 8/8 (1 correction: fillet top-or-side) |
| coombs-pch | Coombs & Holden, Printed Circuits Handbook, 7th ed. | distilled + spot-verified 8/8 (1 locator corrected) |
