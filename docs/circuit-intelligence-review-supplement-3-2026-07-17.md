# Circuit-intelligence root review supplement 3 — 2026-07-17

This file records the R2-C decision after
`circuit-intelligence-review-supplement-2-2026-07-17.md` and supersedes the
earlier R2-C pending note until final reconciliation.

## R2-C — PROVEN (set-like telemetry canonicalization)

Only set-like telemetry is canonicalized: overuse net names, unresolved-net
identities, and per-pass/final resource summaries. Semantic route order, pass
order, net-attempt order, and attempt indices remain ordered and continue to
produce distinct fingerprints. Duplicate identities fail before sorting, and
the independently canonicalized final pass and run summaries must agree.

Independent root evidence: 144 focused and adjacent R2/corridor tests, Ruff,
and strict mypy. Executor evidence additionally includes 121 adjacent tests and
whole-source strict mypy across 163 source files.

## R6.1b fixture 6 — ROOT REVIEW REQUIRED

The bounded copper-removal candidate has green focused/adjacent/static evidence
and the intended PASS/FAIL/UNVERIFIED distinctions, but it is not accepted.
Its adapter currently duplicates the canonical BoardLayout/BoardNetlist
snapshot parser now available from the R5.6b schema-driven serialization seam.
Root review requires consolidation onto that shared authority before evaluating
the remaining copper-specific logic.
