# Circuit-intelligence root review supplement — 2026-07-17

This file records root-review decisions made after
`circuit-intelligence-completion-audit-2026-07-17.md` was created. It supersedes
only the named ledger rows until the final documentation reconciliation.

## Accepted narrow slices

### R4.5A — PROVEN (metrics authority only)

The replay-bound metrics report retains the bus bundle, capacity certificate,
lane-geometry registry, certified member prefixes, and validation context and
recomputes the complete report after serialization. Exact decisions use
rational `a + b*sqrt(2)` witnesses or exact squared pitch comparisons. Lattice
reconstruction is ULP-bounded. Pitch requires a constant perpendicular physical
translation. Boundary order uses explicit portal identities; semantic swaps and
permutations without physical carriers remain unverified. Pairwise eligible and
coherent lengths are named separately from certificate span, and empty
denominators are not applicable.

Root review rejected and then verified corrections for two late defects:

- adjacent pairs are now ordered by physical `order_index`, not lexical member
  identity; and
- incomplete internal activation/deactivation geometry cannot retain exact
  order authority.

Independent root evidence: 226 ordered-bus tests, focused Ruff, formatting, and
strict mypy. This does **not** complete physical swap realization, LCS layer
planning, or thermometer pilots.

### R5.6a — PROVEN (legacy rectangular compatibility only)

The adapter is opt-in and compatibility-only. It retains canonical immutable
layout/netlist snapshots, the full typed profile, policy, source authority, and
probe result. The corrected equivalence fixture calls the unchanged real legacy
`route_board`, sends the same rectangular case through the real R5 detailed
evaluator, requires exact `BoardLayout` equality, and then obtains R5.5 exact
acceptance. Shaped layouts/cutouts are rejected rather than treated as rectangle
authority.

Independent root evidence: 83 adjacent placement tests, focused Ruff and strict
mypy. Executor evidence additionally includes 39 legacy tests, 61 R5.0-R5.5
tests, and whole-source strict mypy. R5.6b-d remain open.

### R6.1b fixture 5 — PROVEN (slot/web/tab fabrication only)

The result replays exact declared slot/web/tab geometry, selected fabrication
profile, active assembly qualification, and per-feature evidence/applicability.
Slots must match live cutouts. Positive web/tab regions must be contained in the
retained live board material and cannot overlap cutout interiors. Equality and
one-micrometre-below behavior are pinned; generic advice cannot supply the
numeric authority.

Independent root evidence: 9 focused and 62 selected adjacent tests, Ruff, and
strict focused mypy; executor whole-source strict mypy was green. Copper
removal, bridge budgets, validation campaigns, and fixtures 6-9 remain open.

## Reviewed but awaiting stable combined rerun

### R3.8 replay-bound placement evidence

`VerifiedCorridorPlanSummary` now retains the full graph, normalized demands,
allocator plan, and derived summary and reruns `summarize_corridor_plan()` in its
validator. `PlacementCorridorEvidence` requires that envelope for READY and
UNSUPPORTED; ABSENT remains evidence-free. Bare fabricated summaries can no
longer influence R5.

Direct code review and the executor's 44 focused/78 adjacent/static gates are
green. Root's combined run overlapped the in-progress R2 result-schema change:
198 tests passed and three corridor exact-check tests failed because the R2
factory had not yet begun supplying its new evidence. R3.8 remains provisional
until the same matrix passes after R2 stabilizes.

## Newly frozen architecture contracts

- `r3-exchange-replay-architecture-2026-07-17.md`
- `r4-physical-swap-architecture-2026-07-17.md`
- `r4-lcs-layer-planning-architecture-2026-07-17.md`
- `r5-shaped-serialization-authority-2026-07-17.md`

These documents turn previously broad roadmap phrases into exact authority,
algorithm, rollback, budget, and firing-fixture requirements. They are designs,
not implementation completion claims.
