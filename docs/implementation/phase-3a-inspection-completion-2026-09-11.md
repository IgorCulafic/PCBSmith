# Phase 3A — immutable inspection completion — 2026-09-11

Status: complete for the approved finished-job inspection scope. Phase 3B continues next.

## Change and purpose

The shared board-job owner now accepts an explicitly source-bound, finite inspection completion authorization for a finished job. It can publish an immutable successor containing actual inspection decisions; it cannot restart board work, reset retry counters, change CAD, replace renders, or manufacture engineering evidence. The existing production inspection/publication owners derive report status and validate the exact payload. Ordinary producers still require their live worker.

Implemented in `src/pcbsmith/inspection_completion.py`, `board_job.py`, and `production_workflow.py`; regression coverage is in `tests/unit/test_inspection_completion.py`. Authorization pins the job ledger, current pointer, predecessor manifest, generation artifacts, reviewer, mechanism and independent evaluation/execution allowances. Stale inputs, scope changes, expiry, repeated completion and changed CAD/check/render payloads fail closed. A rolled-back transaction returns failure.

## Actual B4 result

The current user's approval to continue the phases was recorded through the shared owner. B4 used 900 seconds evaluation and 180 seconds execution. All 32 current artifact decisions are accepted. The 21 retained PNGs were inspected in six contact pages; 11 SVG identities were individually matched to retained exact-artifact observations and their corresponding current PNGs reviewed. These are visual decisions only, not physical qualification.

The first metadata attempt exposed a legacy final publication without `component-review/execution.json`. No pointer or CAD mutation occurred. The shared owner now permits that already-existing absence only for the narrow final inspection completion result; it does not invent a component review. One exact failure-hash-bound resumption retained the initial failure, original authorization and elapsed execution. No clock reset, CAD retry or regeneration occurred. Other failures cannot use this special recovery.

The successor is `outputs/bounded-workflow-b4-2026-09-07/production-routed-final-2026-09-10/generations/inspection-complete-2026-09-11`. All 88 predecessor artifact payloads and the original job ledger remain unchanged. The successor preserves all 86 non-review payloads. Native board SHA-256 remains `f10eaefdc107ad72fba6f835f8647e656624c01173d036a98a5e8f6b8fbd181e`; copper SHA-256 remains `6aec6858b057abcdd0e77d04f57077965d7c4380e965bc95670b1a413a31252f`. The predecessor transaction manifest is retained separately from its artifact payloads. No native check or expensive render rerun was needed for unchanged inputs.

## Verification and timing

- 167 integrated tests pass, zero failures/errors/skips; JUnit: `outputs/phase-3a-2026-09-11/tests-final.xml`.
- Scoped Ruff and strict typing of the new owner pass. Caller audit passes all 196 registered entries with no unclassified callers.
- `outputs/phase-3a-2026-09-11/preservation-verification.json` records exact preservation and decisions; requests, observations, failed attempt, resumption and successor receipts remain available.
- Disjoint completion evaluation: 340.687 seconds; total execution including failed attempt: 1.159 seconds. The original successful receipt counted the initial 0.138-second failure in its evaluation interval as well; it is preserved, and the verification report derives disjoint totals. Shared accounting is corrected and tested. These figures exclude separately scoped platform development and are not a board build benchmark.

## Limits and disposition

B4-INSPECT-01 is closed for these exact inputs. Original B4 failed timing, all continuation history, DR7 and physical qualification remain unchanged. No CAD defect justified another correction. Plating/mask/model appearance is illustrative; actual continuity, purchased-part fit, supply behavior and four-step operation require measurements. No files were deleted or committed. Phase 3B will reduce manual routing/evidence preparation through existing owners.
