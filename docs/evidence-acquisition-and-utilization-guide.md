# Evidence acquisition and utilization guide

This is the durable reminder for turning books, standards, datasheets,
manufacturer guidance, CAD assets, and measured results into PCBSmith behavior.
The objective is not to maximize the size of the library. The objective is to
close a named engineering gap with traceable, scoped, production-exercised
evidence.

The implemented acquisition, KiCad asset, review-package, and execution
commands are documented in
`docs/evidence-assets-review-execution-guide.md`. This file remains the policy
authority; that guide is the operational interface.

The dated local inventory is
`docs/reference/books/LOCAL-SOURCE-INVENTORY-2026-07-18.md`. The current
technical synthesis remains
`docs/reference/current-materials-knowledge-base-2026-07-14.md`; older
distillations must be reconciled with that authority before promotion.

## Operating policy

1. Prefer production integration over another broad reading wave while the
   existing R2-R7 machinery is not yet the default end-to-end path.
2. Acquire exact selected-part, module, fabricator, assembler, and enclosure
   evidence before another general textbook when those inputs block a live
   board.
3. When an approved gap has a freely downloadable official primary source,
   attempt retrieval automatically before reporting it as absent. Record a
   blocked state only for a real paywall, authentication, license, robots,
   network, or identity problem; include the attempted official URL and reason.
4. Buy or obtain a paid standard only when a named check, profile, component
   card, artifact, or acceptance gate will consume it.
5. A source never becomes a universal rule merely because it is reputable.
   Applicability, revision, process, geometry, and product scope travel with
   every extracted claim.
6. Older revisions can support proof-of-concept architecture, historical
   interpretation, and conservative review. They cannot support a claim of
   current contractual, regulatory, safety, or manufacturing conformance
   without a revision-delta review and the currently applicable authority.
7. Books and licensed standards remain under `Books/` and extracted caches
   remain gitignored. Commit summaries, short attributed excerpts, locators,
   hashes, and derived rule records - never the copyrighted source.

## Source precedence by question

| Engineering question | First authority | Supporting authority | Do not substitute |
|---|---|---|---|
| Exact symbol, pinout, footprint, and 3D body | Current selected-part manufacturer data/CAD | IPC-7352, KLC, verified distributor data | A visually similar package or module |
| Fabrication legality | Selected fabricator profile and stackup | IPC-2221/2222 family, process handbook | A global minimum copied from another fab |
| Assembly and stencil process | Selected assembler/process profile and package guidance | IPC-7093/7525 family, IPC-A-610 for finished-joint acceptance | Land-pattern guidance alone |
| Electrical and thermal behavior | Current component data plus actual board geometry and validated model/test | Textbooks, app notes, measured literature | Naked theta-JA or fixed amps-per-via |
| RF/module placement | Exact module guide, module drawing, enclosure inputs, final test | EMC/SI texts | Generic antenna folklore |
| Product safety | Current applicable product standard and insulation-coordination analysis | IEC 60664 family, ordinary PCB guidance | IPC spacing table alone |
| Routing/placement algorithm | Primary paper/source implementation plus representative benchmark corpus | Textbooks and secondary explanation | A single synthetic success |
| Visual/layout craft | Standard render package, comparison images, recorded review | Books and experienced-review heuristics | DRC as a substitute for inspection |

## Acquisition decision gate

Before downloading or buying a source, record:

- the exact live problem or unsupported claim;
- the intended consumer: rule, profile, component card, router behavior,
  simulation, footprint/model, review artifact, or human-review finding;
- why the current library cannot close it;
- whether a free current primary source or manufacturer document exists;
- required revision, product/process scope, and licensing constraints;
- the acceptance fixture or production board that will prove utilization.

If those fields cannot be named, defer acquisition. Discovery links may remain
on the wishlist, but they are not implementation commitments.

## Intake and identity workflow

1. Inventory the file and detect duplicates by SHA-256, not filename.
2. Verify title, edition/revision, date, page count, language, and completeness
   from the document itself. Render the cover and rule-dense tables when text
   extraction is absent, OCR-sensitive, or geometrically important.
3. Classify the copy as `current`, `older_but_usable`, `historical`, `preview`,
   `mismatched`, or `unverified` for the intended question.
4. Pin the source identity in the local manifest with its relative path, hash,
   extraction method, and known limitations. Do not silently replace a pinned
   revision.
5. Map the table of contents to active PCBSmith gaps. Deep-read only relevant
   chapters unless the source is itself the subject of a full audit.
6. Extract each candidate with `THRESHOLD`, `WHY`, `WHERE`, `MACHINE FORM`, and
   `APPLICABILITY`, plus source class, revision, units, confidence, and any
   image/table dependency.
7. Record contradictions and anomalies explicitly. Never average incompatible
   numbers or silently repair suspicious source text.

## Utilization workflow

Use a vertical slice for every promoted claim:

```text
source identity
-> scoped evidence record
-> contradiction/applicability review
-> rule, profile, model, or advisory
-> deliberate passing and firing fixtures
-> production caller integration
-> saved KiCad artifact and exact checks
-> visual evidence where applicable
-> regression and source-to-code trace
```

A source is not "used" merely because it was downloaded or summarized. Track
the following status ladder:

1. `discovered`
2. `local_unverified`
3. `identity_verified`
4. `pinned`
5. `distilled`
6. `reconciled`
7. `implemented`
8. `firing_tested`
9. `production_exercised`
10. `revision_monitored`

Only `production_exercised` evidence should be presented as closing a live
product gap. Earlier states are still useful, but must be named honestly.

## Resource priorities for the current project

### Acquire or pin first

- Exact MPNs, current datasheets, mechanical drawings, land patterns, errata,
  reference designs, and STEP/WRL assets for parts actually selected.
- Exact OLED module identity and geometry; exact SHT31/SHT3x package/model data.
- Selected-fabricator and selected-assembler evidence, captured as versioned
  process profiles rather than mutable web links.
- Versioned JLCPCB/PCBWay or selected-supplier fabrication and assembly profiles.
- The selected Espressif module datasheet and hardware/layout guide.

The official Sensirion SHT/STS Design Guide Version 2 (March 2024) and USB-IF
USB 2.0 June 2025 bundle were downloaded, hashed, and visually verified on
2026-07-18. The Sensirion guide and USB base specification are in the extraction
manifest; the complete USB archive hash and contents are recorded in the dated
inventory. Their remaining work is targeted distillation and integration, not
acquisition.

### Conditional paid acquisition

- Current IPC-2221/2222 material when completing general fabrication authority.
- IPC-7525C when stencil generation becomes a production deliverable.
- Current IEC/product standards only when a board makes a safety or compliance
  claim that invokes them.

IPC-7093A is now present in full and pinned. Distill only the sections consumed
by directly assembled DFN/QFN/BTC footprints, paste, voiding, exposed-pad,
thermal-via, inspection, or process-profile work.

### Defer while integration is the bottleneck

- another broad EMC/SI textbook wave;
- more routing theory without a new measured failure that the current
  negotiated/corridor architecture cannot explain;
- broad IPC-2152 rule promotion: the full historical standard is now pinned,
  but it is validation evidence rather than a current universal model;
- standards unrelated to a selected board, process, interface, or compliance
  target.

## Session reminder

At the start of research work:

- [ ] Name the live gap and intended consumer.
- [ ] Check the local inventory and hashes before searching or downloading.
- [ ] Prefer the current primary/manufacturer/process source.
- [ ] If an approved free official source is absent, attempt automatic download
  and verification before recording a blocked/absent result.
- [ ] Define the acceptance board or firing fixture before extraction.

Before declaring the research useful:

- [ ] Record revision, applicability, units, and contradictions.
- [ ] Connect the result to a generic rule/profile/model or explicit advisory.
- [ ] Run both passing and deliberate-violation tests where deterministic.
- [ ] Exercise it through a production caller and inspect the resulting artifact.
- [ ] Update the roadmap/source-to-code status and leave older authority labelled.

## Health metrics

Review these periodically rather than counting documents:

- sources stalled at `distilled` without an intended implementation;
- implemented rules without firing fixtures;
- rules never exercised by a production caller;
- production findings supported only by previews, old revisions, or web relays;
- component cards missing exact MPN, footprint, model, or manufacturer evidence;
- duplicate files and stale live URLs;
- full-regression cost added by source-specific checks that should be focused or
  data-driven.

The desired direction is fewer orphaned summaries, fewer one-off checks, and
more short source-to-production vertical slices.
