# Phase 17-18 closure log — 2026-07-25

This log records implementation and verification performed during the Phase 17
and Phase 18 closure session. It is an execution record, not a substitute for
the roadmap acceptance gates or for human, fabricator, and assembler approval.

## Phase 17

### Retained routed-board release evidence

The routed-board release gate no longer accepts caller-supplied booleans for
exact-route acceptance, KiCad read-back, or netlist equivalence.

`RoutedBoardVerificationEvidence` now requires exactly one fingerprinted,
producer-identified record for each authority. Every record is bound to:

- the exact saved-board SHA-256;
- producer and tool-version identity;
- retained input SHA-256 identities;
- an explicit result code and limitations; and
- its own replay-checked fingerprint.

The bundle is also fingerprinted and must target the exact board inspected by
the release gate. Missing, duplicated, stale, wrong-board, or rejected evidence
fails closed. The CLI consumes the retained JSON bundle through
`--verification-evidence`; the former release booleans no longer exist.

Verification:

- focused Ruff format/check: passed;
- strict mypy for the changed production modules: passed;
- routed-board release-gate unit tests: 4 passed.

## Phase 18

Implementation has not yet been recorded in this session.
