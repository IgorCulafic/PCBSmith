# PCBSmith Training Data

This directory is the dataset spine for future local-model tuning, evaluation, and regression testing. It stores small, structured records that describe what the user asked for, what the model/tool proposed, what PCBSmith validated, and whether the result was accepted.

Large generated artifacts should stay in `outputs/` or another artifact store and be referenced by path. Do not embed KiCad projects, rendered images, model weights, API keys, private absolute paths, or large binary assets in JSONL rows.

## Directory Layout

- `schema/` contains JSON Schema documents for run logs and training samples.
- `logs/runs/` contains chronological run event logs. These preserve the step-by-step workflow for replay and analysis.
- `datasets/` contains curated JSONL datasets derived from run logs.
- `artifacts/` is a placeholder for small dataset artifact manifests. Large files should be referenced, not copied here.

## Dataset Files

- `datasets/tool_use.jsonl`: positive or negative examples of tool/action formatting.
- `datasets/repair_examples.jsonl`: failed validation report plus the next successful repair action.
- `datasets/negative_examples.jsonl`: wrong outputs labeled with the reason they failed.
- `datasets/accepted_designs.jsonl`: accepted designs with validation/export outcomes and artifact references.

## What To Log

Each run should capture:

- user request and intent
- current design snapshot or compact project summary
- available tools and components
- raw model output
- parsed PCBSmith action if parsing succeeds
- deterministic calculator outputs
- KiCad ERC/DRC/export results
- visual QA findings when available
- human approval, rejection, or correction notes

## Negative Examples

Wrong outputs are useful. Keep them when they are labeled clearly:

- `invalid_json`: output cannot be parsed as JSON.
- `invalid_tool_contract`: model used unsupported tool names or wrong action shape.
- `failed_schema_validation`: JSON parsed but did not match the PCBSmith plan schema.
- `failed_erc`: KiCad ERC rejected the design.
- `failed_drc`: KiCad DRC rejected the board.
- `unsafe_electrical_assumption`: component choice/math was unsafe or unjustified.
- `bad_visual_layout`: visible overlap, unreadable labels, poor routing, or misleading silkscreen.

Negative rows should include enough context to teach the model the correct behavior, but not so much that the dataset becomes noisy.

## Privacy And Safety

Before exporting this dataset outside the local machine:

- strip absolute local paths or replace them with workspace-relative paths
- remove API keys, endpoint secrets, user names, and private repo URLs
- keep local model paths out of exported rows unless explicitly needed
- include license/source fields for any external component data

## Continuous Update Rule

Every AI-assisted PCB run should append to `logs/runs/`. Curated examples can then be copied into one or more `datasets/*.jsonl` files after review. The run log is raw-ish history; the dataset files are training-quality records.
