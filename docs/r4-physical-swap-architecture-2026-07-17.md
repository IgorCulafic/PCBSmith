# R4 physical adjacent-swap architecture — 2026-07-17

## Status and problem statement

R4.1 may emit a deterministic `BusSwapEvent`, but that record is only a semantic
lane-order decision. It does not contain crossover copper, does not consume the
two physical vias normally needed to exchange two same-layer traces on a
two-layer board, and cannot prove clearance, connectivity, or containment. The
current `generate_certified_bus_transition_vias()` rejection of allocations
containing swaps is therefore correct. It must remain fail-closed until the
authority below exists.

This design adds a companion physical authority. It does not reinterpret an
existing semantic swap as geometry and does not change legacy/default routing.

## Required authority layers

### 1. `CertifiedBusSwapRegion`

A versioned, frozen declaration binds one semantic swap window to:

- the live bus, certificate, allocation, lane-geometry registry, rule profile,
  board/static-obstacle, and swap-event fingerprints;
- an exact lattice keep-in compound for the crossover;
- explicit allowed nodes and transitions on each permitted copper layer;
- explicit allowed via cells and the permitted bridge layer;
- the incoming and outgoing lane-geometry identities and their exact portal
  points; and
- a fixed search budget and deterministic region fingerprint.

The region is an input certificate, not a successful route. Unknown zone fill,
opaque obstacle geometry, a stale profile, a window not named by both the bus
and corridor section, or incomplete incoming/outgoing endpoints makes the
region unsupported rather than permissive.

### 2. `CertifiedBusSwapCarrier`

One carrier binds exactly one `BusSwapEvent` and contains:

- the two adjacent member identities and their pre/post lane endpoints;
- one explicitly selected bridge member and one stationary member;
- exact `TrackSegment` fragments for both members;
- exactly two `ViaSpec` objects for the bridge member on a two-layer crossover;
- reconstructed ordinary and pairwise R2 resource claims;
- exact containment, connectivity, clearance, and obstacle-check evidence;
- work telemetry and a canonical carrier fingerprint; and
- typed failure when no candidate fits the fixed budget.

The bridge member leaves the event layer at the first certified via cell,
crosses on the declared bridge layer, and returns at the second certified via
cell. The stationary member remains on the event layer. A zero-via same-layer
crossing is never a valid adjacent swap. More general stackups or jumpers need
separate templates and cannot be inferred from this two-layer carrier.

### 3. `BusPhysicalSwapPlan`

The plan retains the complete bus, certificate, semantic allocation, geometry
registry, rule profile, every swap region, every carrier, combined semantic and
physical via counts, exact claims, budgets, telemetry, and final fingerprint.
Its after-validator deterministically regenerates every carrier and requires
exact equality after JSON reconstruction.

Coverage is exact: every semantic swap event has one carrier in sequence order,
and no carrier exists without an event. An allocation with swaps cannot enter
prefix composition, transaction commit, metrics `EXACT` order authority, or an
exact checker without this plan.

Schema v1 deliberately permits at most one physical swap event in a corridor
section. The allocation may contain several events only when they occur in
successive certified sections. A second event at the same section boundary
would need explicit intermediate event-state portals and nonparticipant
pass-through geometry; binding both events from the original section assignment
directly to the final next-section assignment is not a sequential realization
and must fail closed.

### 4. `CertifiedPhysicalSwapBusMemberPrefix`

Prefix composition consumes only a successful replay-bound plan. For every bus
member it derives every assigned section fragment from the certified lane
registry, then classifies each adjacent-section boundary exactly:

- equal point and equal layer is direct continuity;
- equal point and changed layer requires the existing certified semantic
  transition-via carrier;
- changed point and equal layer requires the one physical swap-carrier member
  whose region names those exact incoming/outgoing geometry and portal
  identities; and
- changed point and changed layer is unsupported by schema v1.

The composer adds the already-certified terminal pigtails, semantic transition
vias, and physical carrier fragments, constructs one connected
`GridRoutePrefix`, and retains the complete plan, member, geometry, pigtail,
transition, carrier, terminal-source, prefix, and composition fingerprints.
Every carrier membership and every discontinuous boundary must be consumed
exactly once. Missing, duplicate, out-of-order, or unused carrier geometry is a
hard composition failure. The result is prefix authority only; it is not a
transaction or exact-board verdict.

## Via and policy accounting

Existing `BusLaneAllocationResult.via_counts` describes semantic inter-section
layer transitions. Physical crossover vias are reported separately and then
combined before acceptance. This avoids silently changing schema-v2 allocation
meaning.

A companion `BusPhysicalSwapPolicy` must explicitly map each semantic swap
window to a certified physical region and declare the bridge layer, allowed via
process, per-swap via count, per-member combined maximum, combined via-count
spread, and fixed search budget. It is fingerprinted with the plan. It cannot
weaken the bus `BusViaPolicy`; `forbidden` and `escape_only` reject corridor
crossovers, and all other modes must explicitly authorize the relevant physical
window. The combined physical plus semantic counts must satisfy both policies.

For each event, legal bridge-member choices are enumerated. The deterministic
choice minimizes, in order: policy violations (which must be zero), resulting
maximum member via count, resulting spread, total path length witness, total
expansions, bridge member ID, via-cell tuple, and geometry fingerprint.

## Deterministic realization

1. Replay `allocate_bus_lanes()` and require the exact semantic result.
2. Resolve the event's incoming and outgoing assignments and certified lane
   endpoints by explicit section/window/member identities.
3. Validate that the event members are adjacent before the event and exchange
   order afterward; unrelated permutations are rejected.
4. Enumerate canonical bridge-member and ordered via-cell pairs.
5. Route the stationary fragment on the event layer and the bridge fragment on
   the declared bridge layer over the region's explicit graph. Check the work
   budget before every expansion.
6. Reconstruct exact claims from emitted segments/vias and reject any ordinary,
   pairwise, foreign-copper, keep-in, or via-site conflict.
7. Select the canonical legal candidate and retain all attempted work.
8. Compose the carrier between certified member fragments. Prefix continuity is
   checked against the carrier endpoints instead of requiring the pre/post lane
   portal points to be equal.
9. Commit the complete bus atomically. Any carrier, later member, materializer,
   or checker failure restores every previous route and claim.

## Metrics and acceptance

- `allocation_swap_count` remains semantic telemetry.
- `physical_swap_count` is derived only from replayed carriers.
- Declared/semantic/physical counts and event identities must agree before order
  authority can be `EXACT`.
- Carrier segments and crossover vias contribute to routed length, delay, via
  count, coupled length, clearance, and R2 resource claims.
- Missing physical regions/carriers, incomplete obstacle authority, or an
  exhausted budget yields `HARD_CONSTRAINT_UNVERIFIED` or a typed routing
  failure; it cannot serialize as a pass.

## Firing fixtures

1. One adjacent inversion without a physical policy remains rejected.
2. A declared semantic window without a certified physical region remains
   rejected.
3. A two-member, two-layer exact crossover emits two vias on one member, swaps
   physical exit order, reconstructs claims, and passes exact checking.
4. One-less allowed via count and one-less via-spread limit fail independently.
5. A stale window, event, certificate, registry, profile, obstacle, endpoint, or
   carrier fingerprint fails reconstruction.
6. A same-layer zero-via crossing and a single-via carrier are rejected.
7. A blocked first bridge member selects the deterministic legal alternative;
   both blocked returns a typed physical-swap failure.
8. Via-site, segment, pairwise-clearance, keep-in, and foreign-copper conflicts
   fire independently.
9. Two ordered swap events preserve sequence and cannot be commuted by
   canonicalization.
10. Zero/one-less expansion and candidate budgets stop before exceeding work.
11. Input reversal and repeated runs preserve geometry, telemetry,
    fingerprints, and rendered board bytes.
12. Injected late failure and checker rejection restore the complete prior bus
    transaction without fabricating an ordinary-net failure.

Only after these fixtures pass may the LCS/disordered-pin-row layer planner use
physical swaps as one of its certified realization choices.
