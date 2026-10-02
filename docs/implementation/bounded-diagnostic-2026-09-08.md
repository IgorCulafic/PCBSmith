# Bounded diagnostic checkpoint — 2026-09-08

User-approved scope: when corrections stop making progress or reach their limit, perform one bounded broader review and recommend the next action without minting more retries.

## Implementation

The existing BoardJob ledger retains one typed diagnostic checkpoint. Repeated failure, a failed final corrective cycle and exhausted correction/operation allowance queue it automatically. diagnose-start also supports reviewer-observed stagnation before those thresholds. It starts one window of at most 300 seconds, clipped at the original verification-reserve boundary.

diagnose-complete validates a structured assessment and hashes its job-relative evidence. It records one recommended action, estimated effort, alternatives, verification criteria and uncertainties. New build work stays blocked before and after completion. Timeouts, restart, cancellation/resume and completion cannot replenish the window or job counters. Existing verification can proceed within its original deadline. Legacy ledgers without the optional diagnostic field still load without a budget reset.

Changed owners: src/pcbsmith/board_job.py; src/pcbsmith/execution.py adds diagnostic tests to the maintained quick gate. Policy and production usage now document the commands and limits, and AGENTS.md includes the diagnostic rule so future tasks see it.

## Actual application to B4

[B4 retrospective assessment](bounded-diagnostic-b4-2026-09-08.md) used 89.35 seconds of a separately declared five-minute analysis window. B4 expired yesterday, so no live checkpoint or new board allowance was created for it. Its ledger and native candidate were hash-checked and remain byte-identical.

The recommendation is a single batch of local edits to R10/R11/R14/R15 after an explicit continuation allowance. No evidence supports rebuilding placement or circuit architecture. The two earlier corrections were workflow/input failures. The SVG's positive dimensions distinguish the observed PNG conversion failure from an unproven claim of invalid native geometry. Routing and final acceptance remain open.

## Verification and limitations

See outputs/bounded-diagnostic-2026-09-08/tests-final.xml and verification.json for exact final checks. Tests exercise automatic/early triggers, short reserve-clipped windows, expiry, restart, cancellation/resume, concurrent start, stale evidence, blank assessments, CLI submission, legacy records, and unchanged job counters. Existing execution tests cover process containment and deadlines.

This checkpoint records evidence-backed operator judgment; it does not discover all root causes automatically or authenticate the reviewer's reasoning. Runtime checks do not sandbox external tools or interrupt assistant reasoning. There is no automatic extension or release of the diagnostic hold. A future explicit continuation decision must retain the original history and use a supported allowance mechanism; editing the ledger or choosing a new root is not that mechanism.

No PCB edits, routing, fabrication exports, commits or publication were performed in this change.
