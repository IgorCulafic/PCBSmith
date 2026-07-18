# Root architecture audit — R3/R5 corridor authority seam

## Current evidence

The R3 plan and summary producers validate live graph, demand, plan, capacity,
overuse, and budget relationships. Existing focused tests cover shaped geometry,
allocation, cutouts, pairwise demand, soft guidance, and deterministic summary
construction. The following seam remains unproven despite those tests.

## Finding R3-A — a bare summary is not replayable authority

`summarize_corridor_plan(graph, demands, plan)` correctly validates the live R3
inputs before deriving `CorridorPlanSummary`. The summary retains graph, demand,
and plan fingerprints plus derived totals, but not the source objects needed to
replay those totals.

`PlacementCorridorEvidence` accepts a hand-constructed summary and validates
its internal readiness/overflow consistency. Production callers can therefore
provide a structurally valid zero-overflow summary without proving it came from
the named graph, demands, or plan. The R5 result then fingerprints that summary,
which preserves the claim but does not authenticate the calculation.

This does not prove that current repository-generated summaries are wrong. It
means the R3-to-R5 authority boundary is too weak for the final placement pilot.

## Root-written correction contract

Before R5.7:

1. Add an immutable, versioned verified-summary envelope retaining the
   canonical `CorridorGraph`, normalized demands, `CorridorPlanResult`, and
   derived `CorridorPlanSummary`.
2. Its after-validator must rerun `summarize_corridor_plan` and reject any stale
   graph/demand/plan/summary/fingerprint or changed derived total.
3. The production R5 `READY` and `UNSUPPORTED` corridor states must require the
   verified envelope. `ABSENT` remains a distinct no-input state.
4. A coarse non-ready/overflow result remains placement evidence only. It may
   affect ranking but cannot block the required unguided exact R2 attempt.
5. Fire forged-zero, stale graph, stale demand, stale plan, input-order reversal,
   nested mutation, serialization replay, and absent-versus-zero fixtures.
6. Preserve the current R3 graph/planner APIs for existing callers; provide an
   explicit adapter/migration instead of silently redefining bare summary
   semantics.

## Finding R3-B — exchange routing report is hash-bound, not replay-bound

`CorridorExchangeRoutingReport` retains graph/base-plan/exchange-plan/guide/run
fingerprints and the board wrapper checks the nested run and exact verdict. It
does not retain the graph, exchange plan, selected-prefix inputs, or guide
authority needed to rebuild the report after reconstruction.

Before accepting R3.7 as complete, add or require a versioned exchange input
envelope whose validator can replay selected prefixes, guide projection, run
binding, and fallback disposition. Fire stale-prefix, stale-plan, fabricated
`APPLIED`, and individual-fallback-mislabeled-as-coherent fixtures.

