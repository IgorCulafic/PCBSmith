# Root architecture audit findings — 2026-07-17

This file records defects and required corrections found by direct root review.
It supplements the completion ledger; it is not a replacement for tests.

## R2 retrospective audit

Baseline independently rerun on the current combined worktree:

- `test_routing_ir.py`
- `test_negotiated_resources.py`
- `test_negotiated_graph.py`
- `test_negotiated_grid.py`
- `test_negotiated_board.py`
- Result: **101 passed** on 2026-07-17.

The green baseline proves the existing behavioral fixtures still fire. It does
not close the following architecture gaps.

### R2-A — exact-check input/result binding is incomplete

`route_board_negotiated` invokes an exact callback only after algorithmic
success and zero overuse, and `RoutingRunResult.accepted` correctly requires an
explicit accepting verdict. However, `NegotiatedBoardRouteResult` retains only
the verdict object; it does not retain a versioned evidence record binding that
verdict to the exact materialized `BoardLayout`, `BoardNetlist`, checker ID,
and canonical report fingerprint. A manually reconstructed or stale result can
therefore be internally coherent without proving which board was checked.

Required correction:

1. add versioned exact-check evidence containing materialized-layout,
   netlist, checker, canonical findings/report, and call-input fingerprints;
2. retain enough checked input authority for the board result to recompute the
   evidence after serialization/reconstruction;
3. require the run verdict, exact report, evidence, and retained layout/netlist
   identities to agree; and
4. add stale-layout, stale-netlist, wrong-checker/report, finding-order, and
   result-tamper fixtures.

### R2-B — checker isolation is weaker than R5.5

The R2 wrapper passes its materialized board and caller netlist directly to the
checker. The dataclasses are frozen but a callback can still mutate nested or
forcibly assigned state, and there is no before/after fingerprint check. R5.5
already establishes the stronger repository behavior.

Required correction:

1. pass isolated deep copies of layout and netlist;
2. verify both fingerprints before and after every normal, exceptional, wrong-
   type, and wrong-report path;
3. never return a normal exact verdict after checker input mutation; and
4. prove the caller's original layout/netlist remain unchanged.

### R2-C — set-like telemetry canonicalization needs explicit review

The producers generally emit deterministic order, but several Pydantic models
validate only uniqueness for set-like fields such as overuse net names and
resource summaries. The semantic fingerprint can therefore depend on manual
construction order even though the design describes these as canonical
summaries.

Required correction:

1. classify each sequence as semantic order or set-like order;
2. canonicalize only set-like sequences (`net_names`, resource summaries, and
   similar identities) without sorting route or attempt order;
3. preserve final-pass/run equality after canonicalization; and
4. add reversed-construction JSON/fingerprint tests.

### Root-written R2 correction contract

The implementation executor may not redesign routing schema v2 semantics:

- `success` remains algorithmic completion with zero unresolved nets/overuse.
- `accepted` remains `success and exact_check_accepted is True`.
- Exact rejection remains separate from algorithmic failure and does not drive
  rerouting in this slice.
- No legacy/default caller is migrated implicitly.
- The new evidence strengthens the board wrapper around schema v2; routing IR
  schema v3 remains reserved for exact-rejection-driven search.
- Existing 101-test behavior, corridor-guided authority separation, golden
  serialization, and legacy A* behavior must remain green.

## R4.5 review findings

The initial metrics implementation was rejected for missing replay inputs,
float-based hard comparisons, unsafe pitch interpretation, positional order
mapping, and mislabeled coherence denominator. The self-contained replay
envelope has since been accepted as a narrow slice (3 focused tests, Ruff, and
strict mypy independently green). Exact arithmetic/pitch/order/coherence remain
in progress under the contract in the completion ledger.

## R5.6a review findings

The first adapter implementation preserved fields and traversed the R5 pipeline
but its equivalence fixture used a stub R2 evaluator that returned a manually
chosen board. It therefore did not prove equality with unchanged legacy
`route_board`. Its serializable result also retained opaque source hashes rather
than canonical source snapshots. Both items were returned for correction.

## R6.1b fixture-5 review findings

The first result measured declared slot/web/tab regions and matched live slots,
but positive web/tab regions were not proven to exist in live board material;
an outside-board or inside-cutout declaration could pass. Binding completeness
was global and did not comprehensively connect every candidate/feature/region/
quantity source to the selected context. Both items were returned for live
outline/material retention and per-feature authority derivation.

