# PCBSmith AI Proposal Bundle Design

## Decision

PCBSmith will add a proposal bundle command for visual review of AI-generated edits before the source project is changed.

The command validates a candidate plan, copies the source PCBSmith project into a staged proposal folder, applies the plan only to that staged copy, exports the staged copy through the KiCad handoff path, and writes KiCad review artifacts.

## Why

Textual command summaries are not enough for PCB work. A user needs to see the schematic and board preview that KiCad would render before trusting an AI-generated change.

The proposal bundle keeps that review safe:

- The source PCBSmith project remains untouched.
- The staged PCBSmith project shows the exact candidate edit.
- The KiCad review folder contains generated KiCad files, validation output, previews, and AI context.

## Output

`ai-proposal-bundle` writes:

- `pcbs-project/` - staged copy of the PCBSmith project after applying the candidate plan.
- `kicad-review/` - KiCad handoff project, review reports, previews, and AI context.

## Acceptance Test

- Invalid candidate plans are rejected before creating the output folder.
- Existing output folders are refused.
- The source project remains unchanged.
- The staged copy contains the AI edit.
- The KiCad review handoff can be generated with execution skipped for offline tests.
