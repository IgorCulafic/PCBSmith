# R3.7 exchange-to-detailed-routing replay architecture — 2026-07-17

## Current gap

`CorridorExchangeRoutingReport` currently retains graph/plan/guide/prefix/run
fingerprints, but not the graph, exchange plan, supplied prefixes, detailed
routing inputs, or preparation decision needed to reproduce those values. A
self-consistent reconstructed report can therefore outlive or disagree with its
source authority. The wrapper binds only the nested R2 run and exact result.

The correction separates pure deterministic preparation from the externally
executed detailed router/checker. It does not change ordinary R2 behavior or
retry an applied fine-prefix failure without the prefix.

## 1. Replayable preparation

`CorridorExchangePreparationInput` retains:

- complete canonical BoardLayout and BoardNetlist authority;
- the live `CorridorGraph` and `CorridorExchangePlanResult`;
- the exact supplied `GridRoutePrefix` set keyed by alternative ID;
- target nets, widths, profile, clearance groups, coarse/fine grids, and
  off-corridor penalty; and
- a versioned preparation-policy/algorithm ID.

The layout/netlist representation must be schema-validated and round-trip back
to the actual dataclasses; opaque hashes are insufficient. Set-like inputs are
canonicalized, while terminal order, exchange order, and prefix geometry remain
ordered.

`CorridorExchangePreparationResult` reruns the existing graph rebuild,
exchange-plan binding, guide build/projection, and prefix selection in its
after-validator. It retains:

- `APPLIED`, `PLAN_NOT_READY`, or `INCOMPATIBLE`;
- one typed incompatibility reason rather than swallowing `KeyError`/`ValueError`;
- the selected coarse alternatives and exact detailed prefixes;
- projected per-net `GridSoftGuide` values;
- every derived fingerprint; and
- the complete input envelope.

`APPLIED` requires exact graph freshness and complete selected-prefix authority.
`INCOMPATIBLE` retains no active guide/prefix map but does retain the rejected
input and typed cause. `PLAN_NOT_READY` performs no prefix authority claim.

## 2. Bound detailed execution

`CorridorExchangeRoutingInput` combines the verified preparation with every R2
call parameter and fixed budget. It records exactly whether guides/prefixes were
passed. Applied preparation passes them once. Incompatible/not-ready
preparation passes neither and invokes ordinary unguided R2 once.

`CorridorExchangeBoardRouteResult` retains this input, the complete strengthened
`NegotiatedBoardRouteResult`, and a versioned execution report. Its validator
requires:

- preparation disposition equals the actual guide/prefix call mode;
- route order, target nets, profile, widths, clearances, grids, policies, and
  budgets bind to one canonical call-input fingerprint;
- the nested R2 run/result/evidence validates independently;
- exact-check acceptance remains separate from R2 algorithmic success;
- report run/exact/layout/netlist fingerprints equal the nested authority; and
- every derived execution/report fingerprint recomputes after reconstruction.

The external checker callable is not serialized. Its stable ID, findings,
checked layout/netlist, and verdict are retained by the nested R2 exact evidence.
The report does not claim it can re-execute an arbitrary external tool; it does
prove which immutable materialized result that tool checked.

## Failure honesty

- A compatible applied prefix that later fails detailed routing remains
  `APPLIED` with the R2 failure. It is not silently retried prefix-free.
- A stale/missing/wrong prefix is `INCOMPATIBLE`; the ordinary unguided run is
  visibly distinct and is never labeled exchange-coherent.
- Coarse plan failure is `PLAN_NOT_READY` and remains nonblocking to ordinary
  R2 unless the caller separately declares a hard coarse requirement.
- Exact rejection does not become a net-routing failure or change preparation
  disposition.
- Algorithmic failure never invokes the exact checker.

## Firing fixtures

1. Compatible fine-prefix selection and ordinary-net routing bind exact guides,
   prefixes, run, and report after JSON reconstruction.
2. Missing, stale, extra, wrong-net, wrong-terminal, wrong-layer, and wrong-entry
   prefixes each retain their typed incompatibility reason and run unguided once.
3. Current-layout graph mismatch and stale exchange/base plan fail preparation
   without stale guide authority.
4. Non-ready coarse plan remains nonblocking and calls R2 without guides.
5. Applied detailed failure is not retried prefix-free.
6. Exact accept/reject/absent states stay independent of applied guidance;
   algorithmic failure makes zero exact calls.
7. Layout, netlist, graph, plan, prefix, target, width, profile, clearance,
   grid, penalty, budget, run, and exact-evidence tampering each fail the correct
   replay boundary.
8. Reversed construction of set-like maps produces identical preparation and
   execution fingerprints; ordered terminal/prefix geometry changes them.
9. Callback mutation isolation is inherited from strengthened R2 and remains
   green through this wrapper.
10. The six documented fine/ordinary exchange fixtures prove that no fallback
    is mislabeled coherent and that fixed/non-target copper remains unchanged.
