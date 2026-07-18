# R4 replay-authority correction contract — 2026-07-17

## Root audit finding

The current R4 synthetic matrices are green (283 combined bus/group tests on
2026-07-17), but several result envelopes are only self-consistent, not
replay-bound. Opaque input fingerprints and nested carrier revalidation do not
prove that the retained result was derived from the exact bus, certificate,
allocation, geometry registries, layout/netlist, routing policies, ledger, and
budgets. These slices remain provisional until corrected.

## A. Generated transition-via authority

`BusTransitionGenerationResult` must replace its hash-only input binding with a
versioned preparation envelope retaining the complete BusGroup,
CorridorCapacityCertificate, BusLaneAllocationResult,
CertifiedLaneGeometryRegistry, full PcbRuleProfile, budget, and immutable
initial occupancy authority. Its validator reruns pure generation and requires
exact carrier/telemetry equality. A swap-containing allocation remains rejected
until a separate physical-swap plan exists.

## B. Generated escape/prefix authority

`BusEscapeGenerationResult` must retain canonical BoardLayout and BoardNetlist
snapshots through the shared neutral serializer, complete bus/certificate/
allocation/lane/escape registries, terminal sources, history/present costs,
cost/profile/clearance/forbidden-resource policies, all budgets, and the
initial occupancy claims. Its validator reruns pure escape, transition, prefix,
and candidate construction and requires exact equality. A canonical JSON object
containing only their fingerprints is not sufficient replay authority.

Ordered terminal search and prefix geometry remain ordered. Set-like resource,
history, clearance, and forbidden inputs canonicalize without changing route
order.

## C. Candidate and transaction binding

`BusCandidateResult` and `BusRouteBundle` must retain or be wrapped by the exact
certified prefixes/carriers from which each NegotiatedGridRoute was built.
Every member route must bind its member/net, prefix composition, resource
claims, expansion telemetry, and allocation. A bundle of route geometry alone
cannot prove which physical carrier authority produced it.

Atomic transaction evidence must retain canonical before/after route-map and
occupancy snapshots sufficient to recompute the reported fingerprints. Runtime
mutation rollback remains tested by injected failures; serialized telemetry may
not claim rollback from hashes that cannot be reconstructed.

## D. Exact checked commit

R4 exact checking must adopt the strengthened R2 boundary:

- detached layout/netlist callback inputs;
- before/after mutation checks on normal, exceptional, wrong-type, and invalid
  report paths;
- versioned evidence binding the exact materialized BoardLayout, checked
  BoardNetlist, checker ID, canonical findings/report, call inputs, and verdict;
- retained materialized layout and checked netlist sufficient for replay; and
- exact rejection distinct from algorithmic route failure, with complete atomic
  rollback and no implicit ordinary-net retry.

## E. Physical swaps and LCS integration

The accepted `bus_lcs.py` result is only sequence telemetry. It may constrain a
later layer planner only after A-D are replay-bound. Semantic BusSwapEvent
records remain unusable for prefix composition until every event has one
certified two-layer physical carrier under
`r4-physical-swap-architecture-2026-07-17.md`.

## Required implementation order

1. Transition preparation envelope and replay.
2. Escape/prefix preparation envelope and replay.
3. Prefix-to-candidate and transaction before/after snapshot binding.
4. R2-strength exact checked commit.
5. Certified physical adjacent-swap region/carrier/plan.
6. LCS complement outlier layer/transition/capacity/via planner.
7. Combined synthetic firing matrix, then staged thermometer pilots.

No step may change legacy/default routing or reinterpret an existing semantic
success as exact physical acceptance.
