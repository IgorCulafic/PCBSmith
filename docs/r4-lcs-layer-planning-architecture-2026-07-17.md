# R4.5B disordered-pin-row/LCS layer-planning architecture — 2026-07-17

## Scope

The ordered-bus literature summarized in
`routing-placement-research-update-2026-07-12.md` uses a longest common
subsequence (LCS) of source and target pin orders to guide layer assignment.
PCBSmith currently has separate fixtures for exact boundary permutations and
one-member layer transitions. Combining those two facts is not an LCS
optimizer: the router must select a maximum compatible stay-layer subset and
prove every outlier's layer, capacity, transition, via, and detailed geometry.

This slice is opt-in and companion-based so `BusGroup` schema v1, allocator
schema v2, existing fingerprints, and legacy/default routing do not change.

## Inputs

### `BusDisorderedPinLayerPolicy`

The versioned frozen policy binds:

- the exact bus, certificate, rule-profile, and boundary-pair identities;
- one declared base layer and one or more explicitly permitted outlier layers;
- per-member pad-access layers at both boundaries;
- certified source/target transition-window IDs for each possible outlier;
- per-member transition/via costs and maxima;
- combined via-count/spread limits compatible with `BusViaPolicy`;
- minimum stay-layer-member count or fraction when required; and
- fixed DP-state, layer-assignment, and transition-candidate budgets.

Missing pad-layer access, transition windows, profile authority, or via process
authority makes that member ineligible as an outlier. The planner never assumes
that a front-layer SMD pad can reach a back-layer corridor without a certified
escape/transition carrier.

### `BusDisorderedPinPlanInput`

The replay envelope retains the bus, capacity certificate, policy, exact source
and target boundary orders, current lane capability, transition capability, and
all budgets. Source and target sequences are semantic order and are never
sorted. Set-like capability declarations are canonicalized separately.

## Deterministic LCS and layer assignment

1. Require the two boundary orders to contain the same declared active member
   set. Activity/tap changes use the ordinary interval grammar and are not
   hidden inside this optimizer.
2. Build the LCS DP table with a work check before every cell. A zero budget
   performs zero cells. The result records exact cell count.
3. Compare candidate subsequences by this stable objective:
   - maximum number of base-layer members;
   - minimum total certified outlier transition/via cost;
   - minimum resulting maximum per-member via count;
   - minimum resulting via-count spread;
   - lexicographically smallest tuple of `(source_index, target_index,
     member_id)`; and
   - canonical plan fingerprint.
4. Members in the chosen subsequence stay on the declared base layer and retain
   their relative order at both boundaries.
5. Every remaining member receives an explicit outlier plan: assigned layer,
   source transition window/carrier, corridor lane/capacity claim, target
   transition window/carrier, exact added via count, and deterministic cost.
6. Select only a contiguous compatible lane block per layer unless the
   certificate explicitly proves a different grammar. Integer slot count alone
   is insufficient; width and every pairwise clearance domain must be
   supported.
7. Replay semantic allocation under these fixed layer constraints. A semantic
   success that cannot be realized by certified transition/pigtail/swap
   carriers is not a successful disordered-pin plan.

The algorithm does not enumerate permutations. Its bounded state is the LCS
table plus canonical layer/transition candidates for the complement.

## Result authority

`BusDisorderedPinLayerPlan` retains:

- schema and algorithm IDs;
- the complete input envelope;
- stay-layer sequence with source/target indices;
- ordered outlier plans and their physical carrier fingerprints;
- per-layer lane/capacity assignments;
- semantic and physical per-member via counts;
- DP/candidate work telemetry and budget exhaustion point;
- failure reason or complete success state; and
- a semantic fingerprint.

Its after-validator reruns the planner and requires exact JSON equality.
Success requires all retained physical carriers and combined via/capacity checks.
An LCS tuple without outlier carriers is planning telemetry, not a route.

Typed failure reasons include invalid boundary authority, member-set mismatch,
DP budget, insufficient stay-layer subset, outlier layer unavailable, source or
target transition unavailable, lane capacity/capability, via policy, physical
carrier failure, and exact-check rejection.

## Integration rules

- The plan constrains R4 lane allocation; it cannot rewrite declared boundary
  order or authorize an undeclared permutation.
- A certified physical swap plan may be another explicit realization choice,
  but semantic swaps without physical carriers remain unusable.
- R2/R3 present/history costs may rank already legal corridor alternatives but
  cannot change the selected member subsequence or create transition authority.
- Whole-bus transaction, materialization, and exact-check rollback remain
  atomic.
- Metrics report the stay-layer fraction, outlier count, transition/via work,
  routed length, physical order, pitch, and coherence without labeling the LCS
  fraction as electrical coherence.

## Firing fixtures

1. Identical four-member orders select all members, zero outliers, and zero
   transition work.
2. One disordered member selects the deterministic three-member LCS and emits
   certified source/target transition carriers for the outlier.
3. Two equal-length LCS choices exercise the complete tie-break and remain
   invariant under reversed construction of set-like capability inputs.
4. A lexical member order different from physical/source order proves sequence
   inputs were not sorted.
5. Missing source and missing target transition authority fail independently.
6. Back-layer slot count sufficient but width or pairwise domain unsupported
   fails capability rather than passing by count.
7. One-less base-layer and outlier-layer capacity fail independently.
8. Per-member combined via maximum and via-count spread fail independently.
9. Zero and one-less DP/candidate budgets stop before exceeding work and retain
   deterministic partial telemetry without a success plan.
10. A member-set mismatch and an activity/tap mismatch do not enter LCS work.
11. LCS planning success followed by physical carrier collision remains a typed
   physical failure and rolls back the complete group.
12. The combined disordered-pin-row fixture pins plan, allocation, carrier,
   route, metrics, exact-check, and rendered-board fingerprints across repeats.

Only after the synthetic matrix passes may this planner be used in the staged
thermometer bus pilots.
