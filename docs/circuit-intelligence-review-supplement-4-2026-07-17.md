# Circuit-intelligence root review supplement 4 — 2026-07-17

This file records decisions after
`circuit-intelligence-review-supplement-3-2026-07-17.md` until final ledger
reconciliation.

## Shared board snapshot authority — PROVEN (neutral utility)

`kicad/board_serialization.py` uses Pydantic TypeAdapters for the real
BoardLayout and BoardNetlist dataclasses, requires exact canonical
parse/reserialization, rejects non-finite or noncanonical JSON, and preserves
the established v1 snapshot fingerprint payload identities. It attaches no
placement, routing, render, DRC, or semantic claim.

Independent root evidence: 19 rich all-field round-trip/adversarial tests,
Ruff, and strict mypy. Integration replacing the duplicate R5/R6 helpers
remains open.

## R4.5B LCS core — PROVEN (sequence telemetry only)

`bus_lcs.py` provides a replay-bound, fixed-cell-budget, maximum-cardinality
LCS over semantic boundary order. Member/activity mismatches perform zero DP
work; work is checked before each cell; the complete lexicographic tuple
sequence breaks equal-cardinality ties. The result explicitly carries no
outlier layer, transition, lane, via, carrier, allocation, or route authority.

Independent root evidence: 21 warning-as-error tests, Ruff, strict mypy, and an
independent brute-force oracle over 153 source/target permutation cases through
five members. Certified outlier planning and physical integration remain open.
