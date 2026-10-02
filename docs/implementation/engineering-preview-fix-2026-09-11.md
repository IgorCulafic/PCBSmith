# Engineering input review fix — 2026-09-11

## Implemented

Added `pcbsmith.engineering_preview`, a read-only diagnostic CLI. It reads existing prepared inputs and optional engineering declarations, prints a source-linked report/worklist, and never consumes a board operation, writes an approval assertion or grants runtime. It reports `authority=diagnostic_only` and `approval_granted=false`, including when declared-data checks pass. Missing files, stale sources, escaped paths, duplicate references/intents, omitted declared support and failed component/power checks are rejected. Unknown top-level approval/outcome fields are forbidden by the typed input schema. Optional source notes link an evidence ID, page/section locator and caller interpretation; they remain interpretations requiring review.

The existing predesign approval owner now uses the same typed evaluator and source-validation helper. Engineering failures and stale source evidence are rejected before a floorplan review file is retained. Existing source-hashed assertions, native inventory/model checks, visual inspection, production boundaries and runtime controls remain required. The preview is not a replacement for any of them. It cannot detect arbitrary omissions in an incomplete support inventory or prove source claims true; these are explicit manual-review gaps.

Fixed a component-selection bug in `design_readiness.py`: candidate ID was a final tie-breaker in display ranking and was also used to reject an otherwise equally scored selected part. Candidate ID now affects deterministic ordering only. A selected part with identical substantive scores is allowed; larger/nonminimal, missing-capability and other incompatible selections remain blocked. Existing reports are not edited or automatically reapproved.

## Verification

87 focused tests pass, including new diagnostic controls and the existing native-input/model/approval/publication integration. The integration now also verifies that source drift and power overload fail before partial approval records are written. Strict typing passes for the new module; scoped lint and the196-caller audit pass. The new entry point is classified here as diagnostic: it consumes pure shared evaluators, performs no native generation/edit/routing/publication, and prints to stdout. No production caller inventory change was needed.

Read-only replay on real retained data: TwinLight's existing engineering inputs pass the scoped declaration/source checks while remaining nonapproving; FilterLeaf produces a9-reference worklist and explicit missing-input blocker; PulseLeaf produces an11-reference worklist and explicit missing-input blocker. All644 files across those board roots, including ledgers and accepted artifacts, were hash-identical before/after. Evidence: `outputs/engineering-preview-platform-2026-09-11/`.

## Usage

```powershell
.venv/Scripts/python.exe -B -m pcbsmith.engineering_preview outputs/filterleaf-2026-09-11/predesign
.venv/Scripts/python.exe -B -m pcbsmith.engineering_preview PREPARED_ROOT --engineering FACTS_JSON
```

Missing or invalid inputs return exit1 with diagnostics; a completed declared-data check returns0 but grants no approval. Do not pass reviewer assertions or feed the preview report into the approval input. The existing supported approval operation consumes the original typed facts and an independently recorded genuine source-bound decision after actual review.

## Current limit and next work

This repairs avoidable comparison/input-validation problems. It does not control or disable the external automatic approval reviewer, and does not prove that a future real-board approval action will be accepted. The denied action was not retried or disguised. Existing user consent remains recorded; no repeated consent request was made.

FilterLeaf review notes (local reference `../../outputs/engineering-preview-platform-2026-09-11/filterleaf-review-notes.md`, not included in this public snapshot) correct the LED/alternative reasoning using retained official datasheets and identify assembly/source gaps. Complete that facts-only review before a supported approval attempt. Resume stopped board jobs only through a valid finite scope under the shared owner, preserving history. TwinLight's documented completion stands; FilterLeaf/PulseLeaf still have no PCB. Physical qualification and DR7 remain open.
