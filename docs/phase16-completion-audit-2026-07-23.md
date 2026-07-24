# Phase 16 completion audit

Date: 2026-07-23

Scope: workflow authority consolidation and migration contracts only

## Outcome

Phase 16 is complete within its stated contract/consolidation scope. Its full
checkpoint completed before Phase 17 implementation began; the later Phase 17
prompt-examiner slice does not alter this retained checkpoint.

The implementation adds one replay-bound contract layer around the accepted
Phase 1-15 authorities without rewriting their historical evidence:

- `src/pcbsmith/workflow_authority.py`
- `tests/unit/test_workflow_authority.py`
- `docs/phase16-workflow-authority-contract-2026-07-23.md`
- stewardship audit schema v2 in `tools/audit_test_and_check_suite.py`

## Roadmap-item evidence

| Phase 16 obligation | Evidence | Result |
| --- | --- | --- |
| Publish a Phase 1-15 capability map | 15 validated records, one for every integer phase; contract document and `build_phase16_capability_map()` | Complete |
| Assign owner, schema, caller, test, artifact, evidence, and limitation | Required fields on every capability record; validation rejects omissions and duplicates | Complete |
| Remove or deprecate duplicate authorities | Registry permits one active owner per semantic scope; three one-off shortcuts are deprecated with same-scope replacements | Complete |
| Define one workflow state machine | Nine ordered stages with explicit active/incomplete/failed/complete states | Complete |
| Define shared project context | Ten mandatory categories, each resolved/unresolved/not-applicable exactly once | Complete |
| Define applicability | Always, board-triggered, external, and human-decision modes; six non-substituting dispositions | Complete |
| Reconcile identities | Twelve typed identities with exact dependency digests and transitive invalidation | Complete |
| Complete test/check ownership and runtime attribution | Stewardship audit v2 adds ownership, caller triage, assertion categories, and JUnit runtime ingestion | Complete |
| Close Hypothesis incident by cause class | Strategy statistics, 50-process reproduction attempt, ACL check, and scheduler-preemption diagnosis retained in the contract report | Complete |
| Freeze Phase 17 migration contract | Version 1 plus pinned registry/map semantic fingerprints | Complete |
| Preserve historical generators through adapters | Two bounded legacy adapters retain evidence and expose known gaps without production promotion | Complete |

## Canonical authority registry

- 29 contracts total
- 26 active canonical owners
- 3 deprecated one-off authorities
- registry fingerprint:
  `abda6f84ece542f90de2702ee7e9fa1169916fcfdf6d493396b11dd58c5acc93`
- capability-map fingerprint:
  `12d7b8a773d5ad23f80e57aaa31b4ecb7236efd16d04260182a0e779acf7f87e`

The three deprecated identities are ad-hoc preview images, directory-existence
workflow checks, and process/hash-dependent routing order. Their replacements
are respectively the canonical visual package, semantic workflow conformance,
and negotiated routing authority.

The audit explicitly retains virtual DRC, semantic design checks, and KiCad
CLI DRC as layered authorities rather than deleting them as apparent
duplicates.

## Architecture-test evidence

The focused Phase 16 cluster proves:

- ordered transitions and stage-bypass rejection;
- incomplete/failure behavior and checkpoint-bound resume;
- terminal failed states;
- upstream identity replacement and transitive downstream invalidation;
- stale dependency rejection when a caller bypasses invalidation;
- complete project-context composition;
- unresolved context preventing authorization;
- external-provider and human-decision blocking without substitutes;
- board-triggered not-applicable behavior;
- duplicate active semantic-owner rejection;
- deprecated-authority rejection;
- exact Phase 1-15 coverage and pinned contract fingerprints;
- context-fingerprint tamper rejection;
- bounded legacy-adapter claims.

The completed focused workflow/context/execution cluster passed 45 tests,
including the deprecated-authority case.

## Test/check stewardship results

The post-implementation inventory records:

- 2,763 collected pytest cases;
- 2,033 authored test functions across 229 files;
- 244 parametrized authored functions;
- 88 name-matched production check/validation candidates;
- 52 module-level public candidate entrypoints;
- 5 framework validators distinguished from explicit callers;
- 112 numeric assertions mentioning coordinate/scale fields;
- 141 numeric assertions mentioning work/time/memory budgets;
- no lexically unobserved module-level public candidate entrypoint.

The 112 coordinate/scale candidates are review leads, not 112 obsolete tests.
The highest-count files were manually sampled. They protect exact KiCad
rotation/mirroring, mask and aperture transforms, GLB alignment, visual-package
physical scale, placement proposals, and the accepted thermometer micro-pilot
boundary. None was removed merely because it contains an absolute value.
Board-specific pins remain bounded to their board or compatibility adapter and
do not define shared scale authority.

## Hypothesis incident

The original `test_point_add_sub_inverse` strategy has four independent bounded
integer draws and no filtering or composite computation. Current statistics
showed 100 valid examples in 0.09 seconds, typical generation below 1 ms, and
no invalid examples. Fifty isolated pytest processes passed; their total
process wall times ranged from 0.654 to 1.036 seconds. The historical
1.27-second draw-time event after only two valid examples is consistent with a
host scheduling/preemption pause during a timed draw. Hypothesis itself excludes
the health check under overlapping threads because scheduling can arbitrarily
pause a thread.

The health check remains enabled. The test, example count, deadline, and
strategy were not weakened. Future full runs retain JUnit per-test timing so a
recurrence has usable attribution evidence.

## Verification

- `uv lock --check`: passed
- Ruff over the repository: passed
- strict mypy over `src` and the stewardship tool: passed across 279 source files
- focused workflow/context/execution tests: passed
- full warnings-as-errors pytest with JUnit runtime evidence: 2,746 passed,
  17 intentional skips, zero failures/errors; 2,763 total in 788.832 seconds
- documentation whitespace check: passed

The summed JUnit testcase time was 782.392 seconds. The slowest individual
tests were existing routing/geometry contracts: the flyback reroute verifier
(38.354 seconds), negotiated-grid layer steering (37.815 seconds), and full
flyback routing from bare placements (34.180 seconds). This measured evidence
replaces source-size guesses and does not justify deleting those contracts.

Retained runtime evidence:

- `.pcbsmith/verification/phase16-full-2026-07-23/pytest-junit.xml`
- `.pcbsmith/verification/phase16-full-2026-07-23/pytest.stdout.txt`
- `.pcbsmith/audits/phase16-test-check-inventory.{json,md}`
- `.pcbsmith/audits/phase16-test-check-full-runtime.{json,md}`

## Scope boundary and Phase 17 handoff

Phase 16 proves the architecture contracts and ownership topology. It does not
prove that normal board generators invoke them. Phase 17 must implement:

- prompt examination and typed anchors;
- default project-context population;
- pre-route capacity and failing-net diagnostics;
- automatic post-placement persistence/review;
- native algorithm budgets, checkpoints, and heartbeats;
- transaction-wide generation identity and rollback;
- deterministic routing order and route-domain resume;
- saved/read-back R2-R6 adoption;
- two materially different prompt-to-final default-path proofs.

No manufacturing, MCAD, advanced-simulation, or correlated-release claim is
created by this completion.
