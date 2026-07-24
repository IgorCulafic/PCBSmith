# PCBSmith R12 Validation And Reporting

## Goal

Make generated review bundles publish one consolidated validation report that
normalizes topology, component, calculator, KiCad, PCBSmith, and human-review
evidence.

## Scope

- Add a dedicated `pcbsmith.reporting` package.
- Add `validation-summary.json` and `validation-summary.md` report generation.
- Include KiCad ERC/DRC, preview exports, board manufacturability, circuit-rule
  findings, calculator results, selected component candidates, topology choice,
  and human-review items in one schema.
- Wire validation summaries into KiCad review bundles.
- Expose validation-report outputs through AI context and planner packages.
- Keep `revision-brief.json` as the repair queue; use validation summaries as
  the broader evidence report.

## Acceptance

- Review bundles write `.pcbsmith/reports/validation-summary.json`.
- Review bundles write `.pcbsmith/reports/validation-summary.md`.
- AI context references the validation summary when it exists.
- AI planner packages tell models to read validation reports before claiming a
  design is ready for fabrication.
- Tests cover report aggregation, Markdown output, review-bundle integration,
  and AI-facing tool contracts.
