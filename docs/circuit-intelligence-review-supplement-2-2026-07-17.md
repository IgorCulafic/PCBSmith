# Circuit-intelligence root review supplement 2 — 2026-07-17

This file records root-review decisions made after
`circuit-intelligence-review-supplement-2026-07-17.md`. It supersedes that
supplement only for the named R2-A/B and R3.8 rows until final reconciliation.

## R2-A/B — PROVEN (exact-check binding and isolation)

The negotiated-board result now retains versioned exact-check evidence bound to
the complete materialized layout, canonical checked netlist, checker identity,
canonical findings/report, call inputs, and verdict. Exact callbacks receive
detached copies; mutation of either checker or caller inputs takes precedence
over normal, exceptional, wrong-type, and invalid-report outcomes. Exact
rejection remains separate from algorithmic routing success and never triggers
an implicit reroute. The pre-existing public exact-report fingerprint payload
is unchanged.

Independent root evidence: 317 combined R2/R3 routing, corridor, exchange, and
placement-surrogate tests, focused Ruff, and strict mypy. R2-C set-like
telemetry canonicalization remains a separate bounded correction.

## R3.8 — PROVEN (replay-bound corridor summary seam)

`VerifiedCorridorPlanSummary` retains the complete corridor graph, normalized
demands, allocator plan, and derived summary, and recomputes the summary after
reconstruction. `PlacementCorridorEvidence` requires this envelope for READY
and UNSUPPORTED states while ABSENT remains evidence-free. Bare or stale
summary objects cannot become R5 surrogate authority.

Independent root evidence: the same 317-test combined R2/R3 matrix, focused
Ruff, and strict mypy after the R2 evidence schema stabilized. R3.7 exchange
execution replay remains open.
