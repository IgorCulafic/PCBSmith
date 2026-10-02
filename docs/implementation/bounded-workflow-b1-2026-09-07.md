# B1 — bounded board execution — 2026-09-07

B1 is implemented and passes its scoped software gate for the supported command/producer boundaries listed below. B2 (vector planning), B3 (shared asset integration) and B4 (fresh-board timing acceptance) remain OPEN. This is not a successful new-board timing demonstration or manufacturing approval.

## Changes and practical effect

- [board_job.py](../../src/pcbsmith/board_job.py) stores one integrity-checked job ledger at the stable workspace's `.pcbsmith/board-job.json`. It records classification/rationale, start/deadline, verification reserve, correction/escalation counts, worker leases, command/input identities, outcomes and cancellation/resume events. Repeated start and copied-ledger roots are rejected. No automatic reset or deadline extension exists.
- `pcbsmith board-job start/status/run/correct/cancel/resume/finish` exposes the workflow. [CLI dispatch](../../src/pcbsmith/cli.py) derives operation identity and phase from the supported command rather than accepting an arbitrary stage label. A new output folder does not count as a changed input.
- One initial build plus two declared correction cycles are permitted, with one strategy escalation. Each build operation runs at most once per cycle, three times total. Changed candidates can be verified without inventing correction cycles, but each verification operation is also limited to three attempts. An unchanged retry is rejected; the same retained failure signature after correction stops the job.
- Build processes receive only the time before the 20% verification reserve; verification can use the remaining allowance. The original UTC deadline survives restarts and gaps between commands. In-process monotonic timing also applies. Clock rollback and invalid/missing state stop execution.
- [execution.py](../../src/pcbsmith/execution.py) supervises the whole child process tree with the existing OS limiter, cancellation polling and a bounded 30-second cleanup allowance. A supported worker waits for the containment receipt before executing its command. Missing OS containment fails closed. Windows virtual-environment redirector processes are explicitly handled.
- Managed [revision checkpoints](../../src/pcbsmith/board_revision.py) retain their job identity. Resume and application reject a different/missing job. Gracefully interrupted work can resume only within its original deadline, without refunding attempts. A cancellation cannot relabel a deadline/repeated-failure stop into a fresh allowance.
- Source boards, native checks, engineering requirements and release criteria are preserved. A successful subprocess means its command exited successfully; `finish` closes execution only and never grants board acceptance.

## Enforcement coverage

The supervisor covers native project preparation, predesign prepare/approve, saved-placement routing, and these main CLI operations: production generation; placement/routed review; component-review repair; edit/apply; board/visual inspection; generator audit.

Fifteen direct producer entry points also require the same live contained worker, so importing a supported Python producer no longer skips the job requirement:

- native project preparation and both predesign preparation/approval functions;
- registered generation and registered placement/routed persistence;
- budgeted placement review, placement/routed review persistence, component-review repair, generation commit and native routing in production_workflow;
- saved-placement routing and revision create/apply.

Tests exercise rejection before producer work, not just the CLI wrapper. Existing inner-contract tests explicitly isolate this outer guard using module-scoped fixtures; they remain synthetic contract tests, not real supervised-board proofs.

Raw KiCad primitives, research scripts, external shell commands and deliberate source/ledger tampering are not an OS security sandbox target. Existing producer classification and engineering/release replay remain required. The ledger checksum detects corruption; it is not a signature authenticating user approval.

## Verification

- Expanded regression suite: **185 tests, zero failures/errors/skips**. JUnit results (local reference `../../outputs/bounded-workflow-b1-2026-09-07/tests-final.xml`, not included in this public snapshot). After the final input-preflight correction, the affected board-job/execution suite passed **64 tests**, including two new cases proving expiry prevents hashing and large inputs check the budget between chunks. Follow-up results (local reference `../../outputs/bounded-workflow-b1-2026-09-07/input-preflight-tests.xml`, not included in this public snapshot). These are overlapping suites, not 249 distinct tests.
- Real subprocess tests: successful supervised inventory command; forced whole-job deadline; a hung child; cancellation of a process with a descendant. Missing-containment injection proves the worker is not authorized.
- Deterministic cases: time between stages, new attempt paths, copied ledgers, concurrency, stale leases, corruption, rollback, deep-profile expiry, correction/escalation exhaustion, repeated failures, verification reserve, same-budget resume and cross-job checkpoint rejection.
- Existing generation, review, native input, routing transaction, edit/resume and caller-audit regressions remain exercised. The earlier missing-library fixture failed while constructing a rebuild decision before reaching its intended generator assertion. Its setup now uses a separate initial-generation source so the intended retained-failure behavior is actually tested. The failed run (local reference `../../outputs/bounded-workflow-b1-2026-09-07/tests-attempt-02-failed.xml`, not included in this public snapshot) is retained.
- Producer inventory: 196 callers, no unclassified/stale/changed calls (local reference `../../outputs/bounded-workflow-b1-2026-09-07/workflow-audit-final.json`, not included in this public snapshot). This remains static inventory, not electrical validation.
- Ruff passes across source/tests/tools; focused Mypy passes for the new ledger and modified execution owner. This is not a new full-standard-suite or whole-repository typing claim.
- CornerStep's accepted board SHA-256 remains `54652c98f30a697520b8b0c5a0a797264088bf2a1e81e3bfac53bf0764962786`. No board redesign or fabrication export was performed.

The B1 test module is included in the quick verification gate to prevent later work from silently dropping these controls.

## Use and migration

Start exactly once, before investigation/preparation, in a stable board workspace. Example commands below are templates, not a board generated by this phase:

```powershell
pcbsmith board-job start outputs/new-board --complexity simple --rationale "Familiar two-layer circuit"
pcbsmith board-job status outputs/new-board
pcbsmith board-job run outputs/new-board --module pcbsmith.native_project --args SPEC.json outputs/new-board/input-01 --symbol-root KICAD_SYMBOL_ROOT
pcbsmith board-job run outputs/new-board --args production-generate-board SCHEMATIC outputs/new-board/placement-01 --predesign BUNDLE.json --predesign-artifacts EVIDENCE_ROOT
pcbsmith board-job correct outputs/new-board --reason "Recorded obstruction" --change "Move the affected component and its local route"
pcbsmith board-job run outputs/new-board --module pcbsmith.production_routing --args --board BOARD --layout LAYOUT --netlist NETLIST --profile RULES --gate-inputs GATES --output outputs/new-board/route-01
```

Keep using the same job root for later attempts. Command-specific inputs and native checks still apply. Existing direct board CLI invocations now intentionally reject; wrap them with `board-job run`. Supported producer functions cannot be used in ad-hoc scripts without their real supervised worker. Use the shared command adapter when a capability is missing.

After graceful cancellation, `board-job resume ROOT --reason "..."` retains the deadline and spent attempts. A repeated operation then requires an eligible correction and changed inputs. A hard-killed supervisor can leave an unsettled lease: the system fails closed rather than guessing its worker is dead or resetting counters. Automatic crash recovery of that lease, user-wait pauses and authorized deadline-extension tooling are not implemented; none silently grants extra time.

## Remaining risk and next phase

The deadline can stop an unfinished board; it cannot guarantee a correct board will finish in 30 minutes. Native and visual quality are still subject to their real checks. Retry identity hashes explicit input files and settings; directory dependency closure remains owned by the existing production checks. Identical last-line failure signatures trigger the repeated-failure stop; different diagnostics remain bounded by counts/deadline rather than being assumed equivalent.

B2 is next: make the dimensioned vector floorplan an explicit inspected/presented input before native placement, using existing concept/overlay code. B3 follows with consistent cache-first asset resolution. B4 must then demonstrate a fresh simple board within its budget, with actual native and review evidence.
