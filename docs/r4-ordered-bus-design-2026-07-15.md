# R4 ordered bus and lane-routing implementation design

Date: 2026-07-15  
Scope: implementation design plus the bounded implementation checkpoint below.
The original design remains the target; status annotations distinguish shipped
semantic/transaction primitives from geometry and authority gates still open.

> **Implementation checkpoint (2026-07-16):** R3.7 and R3.8 are complete.
> R4.0, R4.1a, R4.1b, R4.2a, and R4.2b are complete. R4.2c integration is in
> progress. Nothing in these slices is an exact-checked committed bus route.
> Full LCS/disordered-pin-row optimization, hard pairwise pitch enforcement,
> generated pigtails, transition-via geometry, group/ordinary negotiation,
> thermometer pilots, and exact-checked commit remain unimplemented.

## Executive decision

R4 must be a group transaction built on two authorities that already have, or
will have, narrower responsibilities:

1. R2 owns exact-grid candidate search, complete-net rip-up, capacity-one
   physical resource claims, negotiated present/history costs, fixed work
   budgets, deterministic ordering, zero-overuse completion, and the separation
   between algorithmic completion and exact-check acceptance.
2. R3 must own shaped-outline corridor discovery and issue a versioned capacity
   certificate for a named route demand. R4 must not estimate that a corridor is
   wide enough from a bounding box, a leader path, or the success of one member.

Given a current R3 certificate, R4 may allocate ordered lanes, connect terminals
to those lanes, realize detailed copper, and validate the complete group with
the same physical obstacle and exact-check authorities as ordinary routes. A
leader plus offsets is an optional local realization of an already allocated
lane plan. It is not a global planner and it must never be used to manufacture a
capacity proof.

The group outcome has three distinct states:

- `routed`: every member is connected, every hard bus constraint is satisfied,
  negotiated physical overuse is zero, and the exact checker accepts the board;
- `degraded`: an explicitly authorized individual-route fallback connected the
  members and exact checking accepted the board, but one or more requested bus
  properties were not realized;
- `failed`: capacity, boundary compatibility, escape, detailed realization,
  resource, budget, or exact-check requirements were not met.

Only `routed` is a successful bus route. `degraded` may be a usable PCB result,
but it must remain visible in authority reports and must not satisfy a hard
coherence, timing, or coupling requirement.

## Repository facts this design preserves

The current production shapes constrain the new design:

- `routing_ir.py` schema v2 truthfully records per-net/pass work, unresolved
  nets, resource overuse, stagnation, typed terminal reasons, and board-level
  exact acceptance. It does not represent bus plans, lane allocation, degraded
  fallback, or group-level exact rejection.
- `negotiated_resources.py` has canonical layer-specific cell, edge, crossing,
  and via-site resource keys; set-valued whole-net claims; capacity-one
  occupancy; deterministic overuse; ordinary and pair-specific clearance
  domains; and exact capsule supercovers for emitted track geometry.
- `negotiated_grid.py` searches one complete net against the R2 ledger and
  history, returns `NegotiatedGridRoute`, and reconstructs claims from final
  emitted segments and vias. Pairwise mask/role/exemption selectors are
  intentionally conservative and net-wide during search.
- `negotiated_board.py` strips all target copper once, transactionally reroutes
  complete nets, materializes only the current route map, enforces fixed
  expansion/pass/stagnation budgets, requires zero final overuse, and invokes an
  optional board-level exact checker only after algorithmic success.
- `BoardLayout` can preserve shaped outlines, front/back placement, zones,
  graphics, and mask apertures while emitting only `TrackSegment` and `ViaSpec`
  route geometry. R4 must preserve all non-route fields exactly as R2 does.
- The thermometer is a 46 mm by 158 mm shaped board with a 24 mm-wide stem. It
  currently uses sequential `route_board`, explicit control-net priority, 0.2 mm
  SEG/control widths, and hand-tuned placement comments documenting repeated
  corridor failures. It is a firing fixture, not evidence that a proposed bus
  algorithm works.
- Thermometer control topology is heterogeneous: `/SER` runs from U1 to U2,
  while `/SRCLK`, `/RCLK`, and `/OE` connect U1, U2, and U3. The output buses are
  also physically fragmented: each 74HC595 has QA on one package side and the
  other seven outputs on the opposite side. A model that assumes one common
  source row and one common target row for every member would misrepresent the
  actual board.

R4 must remain a new API until its fixtures and authority gates pass. It must not
silently change legacy `route_board` or the existing R2 entry point.

## Hard separation of meanings

R4 handles four related but non-equivalent ideas:

| Concern | Meaning | Hard only when |
|---|---|---|
| Connectivity | Every declared member terminal belongs to one connected copper tree for that net. | Always. |
| Lane order | Active members cross each certified boundary in a permitted permutation and use permitted swap/reversal transitions. | Always for a declared ordered bus. |
| Coherence | Members share the intended corridor, pitch, bend structure, layer behavior, and overlapping trunk extent. | A numeric threshold is declared with confirmed applicability evidence; otherwise report only. |
| Timing/coupling | Delay spread, skew, parallel exposure, return geometry, and crosstalk/noise remain within an interface-specific budget. | The budget is complete, evidence-backed, and explicitly promoted to a hard requirement. |

Equal routed length does not prove timing, bundle appearance does not prove
crosstalk, and same-cycle switching does not justify minimum same-bus spacing.
The physical fabrication profile remains a hard floor in every case.

## Proposed engine-neutral declarations

These are design shapes, not committed names. Use frozen, `extra="forbid"`
models with finite numeric validation, canonical semantic JSON, and SHA-256
fingerprints, following `RoutingIrModel` and `EvidenceRef` conventions.

### Member terminals and boundary fragments

```python
class BusTerminalRef(RoutingIrModel):
    terminal_id: str
    net_name: str
    component_ref: str
    pad_number: str
    role: Literal["source", "sink", "tap", "passive_endpoint"]

class BusMember(RoutingIrModel):
    member_id: str
    net_name: str
    terminals: tuple[BusTerminalRef, ...]
    width_mm: float

class BoundaryMemberRef(RoutingIrModel):
    member_id: str
    terminal_ids: tuple[str, ...]

class BusBoundary(RoutingIrModel):
    boundary_id: str
    corridor_portal_id: str
    orientation: Literal["forward", "reverse"]
    ordered_members: tuple[BoundaryMemberRef, ...]
    inactive_member_ids: tuple[str, ...] = ()
```

A boundary order is the order in which member centerlines intersect an oriented
R3 portal, from the portal's canonical low endpoint to high endpoint. It is not
component pin-number order and not declaration insertion order. `orientation`
allows a human-readable terminal boundary to be related to the portal's
canonical orientation without changing the stored ordered tuple.

`ordered_members` may contain a subset of the bus. This is required for a trunk
whose member exits at an intermediate tap. An `inactive_member_id` is legal only
if the member has already ended at a declared terminal/tap on the preceding
corridor section. It cannot disappear in free space. A member may have multiple
terminals because R2 routes a complete net tree rather than a two-pin path.

Package sides should be represented as separate boundary fragments when there
is no common physical escape row. For example, QA and QB-QH on a 74HC595 should
not be forced into one fictitious boundary. R3/R4 may join fragment escapes into
one downstream corridor after each fragment is legal.

### Permitted permutations

```python
class BusPermutationPolicy(RoutingIrModel):
    allow_whole_bundle_reversal: bool = False
    allowed_boundary_permutations: tuple[tuple[str, tuple[str, ...]], ...] = ()
    swap_windows: tuple["BusSwapWindow", ...] = ()

class BusSwapWindow(RoutingIrModel):
    window_id: str
    corridor_region_id: str
    allowed_adjacent_pairs: tuple[tuple[str, str], ...]
    allowed_layers: tuple[Literal["F.Cu", "B.Cu"], ...]
    maximum_swaps: int
```

Reversal means one complete active order becomes its reverse at a declared
boundary or corridor orientation change. It is not a sequence of free member
swaps. Arbitrary permutation is forbidden by default. Explicit boundary
permutations cover pin-compatible logical remapping only when the schematic and
functional intent permit it. Geometric lane swaps are allowed only inside named
R3 windows, as adjacent transpositions, on declared layers, and within a fixed
count. Each swap must be realized and exact-checked; a tuple alone is not proof
that traces can cross.

The allocator rejects duplicate/missing members, undeclared permutations,
reversal applied to only part of the active order, and a swap involving an
inactive member.

### Layer and via policy

```python
class BusViaPolicy(RoutingIrModel):
    mode: Literal[
        "forbidden",
        "escape_only",
        "declared_transition_windows",
        "independent_bounded",
        "synchronous",
    ]
    transition_window_ids: tuple[str, ...] = ()
    maximum_vias_per_member: int = 0
    maximum_via_count_spread: int | None = None

class BusLayerPolicy(RoutingIrModel):
    allowed_layers: tuple[Literal["F.Cu", "B.Cu"], ...]
    preferred_layers: tuple[Literal["F.Cu", "B.Cu"], ...] = ()
    via_policy: BusViaPolicy
```

`synchronous` means every member active through a transition changes layer in
the same window; it does not mean the vias occupy one physical site. A via-count
spread is a timing/coherence constraint only if the associated evidence makes it
hard. Otherwise it is a reported metric. R4 must claim ordinary and pairwise
R2 via resources for every emitted `ViaSpec`.

### Timing, coupling, and coherence evidence

Do not encode one generic `spacing_class` as a substitute for interface facts.
Use separate declarations:

```python
class ConstraintAuthority(RoutingIrModel):
    enforcement: Literal["advisory", "hard"]
    evidence: tuple[EvidenceRef, ...]
    applicability_conditions: tuple[str, ...]
    validation_method_ids: tuple[str, ...] = ()

class BusTimingBudget(RoutingIrModel):
    clock_or_toggle_frequency_hz: float | None
    driver_rise_time_ns: float | None
    maximum_skew_ps: float | None
    maximum_delay_spread_ps: float | None
    maximum_length_spread_mm: float | None
    propagation_model_id: str | None
    authority: ConstraintAuthority

class BusCouplingBudget(RoutingIrModel):
    signal_swing_v: float | None
    acceptable_noise_v: float | None
    acceptable_noise_fraction: float | None
    maximum_parallel_run_mm: float | None
    reference_structure_id: str | None
    stackup_id: str | None
    adjacent_member_clearance_mm: float | None
    foreign_net_clearance_mm: float | None
    victim_class_ids: tuple[str, ...] = ()
    authority: ConstraintAuthority

class BusCoherencePolicy(RoutingIrModel):
    minimum_coherence_fraction: float | None
    maximum_pitch_deviation_mm: float | None
    maximum_order_violations: int = 0
    authority: ConstraintAuthority
```

Promotion to `hard` requires at least one checksum-pinned or otherwise durable
source/simulation/measurement reference whose locator is verified and whose
applicability is confirmed for the declared interface, edge rate, stackup,
reference return, voltage swing, and relevant run length. A model validator
must reject `hard` with missing operative numeric limits or incomplete
applicability. A design-review workflow may promote an advisory; the router must
not infer promotion from a familiar interface name.

The existing literature values remain calibration hypotheses:

- 3W is at most a craft/readability floor without a matching stackup and
  coupling derivation; on the current thick two-layer geometry it does not prove
  a particular noise fraction.
- 9.1 mm is a conditional estimate using a 1.6 mm reference distance, a
  continuous opposite-side ground return, and a less-than-3-percent coupling
  target. It is not a universal sensitive-net clearance.
- a bundle-coherence percentage is a reported metric until a bus declares an
  evidence-backed threshold.
- same-cycle 74HC595 outputs are not automatically exempt from coupling review.
  Their edge rates, simultaneous switching, shared return, load behavior, and
  coupled distance still matter.

Every lane center-to-center pitch must satisfy the fabrication/electrical floor:

```text
pitch(i,j) >= width_i/2 + required_edge_clearance(i,j) + width_j/2
```

`required_edge_clearance` is the maximum applicable hard ordinary, pairwise,
qualified-clearance, and promoted bus-coupling requirement. Selective mask/role
rules remain conservatively net-wide during R4 search until a transition-level
proof exists, matching R2 behavior. Creepage is not a lane claim.

### Bus group

```python
class BusFallbackPolicy(RoutingIrModel):
    allow_individual_fallback: bool = False
    maximum_fallback_members: int = 0
    hard_constraints_may_degrade: bool = False  # must remain False in v1

class BusGroup(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-group"] = "pcbsmith-bus-group"
    schema_version: Literal[1] = 1
    bus_id: str
    members: tuple[BusMember, ...]
    boundaries: tuple[BusBoundary, ...]
    permutation_policy: BusPermutationPolicy
    layer_policy: BusLayerPolicy
    timing_budget: BusTimingBudget | None = None
    coupling_budget: BusCouplingBudget | None = None
    coherence_policy: BusCoherencePolicy | None = None
    fallback_policy: BusFallbackPolicy = BusFallbackPolicy()
    rule_profile_id: str
```

Member, terminal, boundary, portal, window, and bus IDs must be unique. Every
net must exist in `BoardNetlist`; every terminal component/pad must be a node of
that net; every member must be active on at least one boundary; and terminal
activity must form a connected interval over the ordered corridor sections
except at a declared branch/tap region. Widths must be finite, positive, and no
smaller than the active fabrication profile minimum.

## Required R3 capacity-certificate contract

R4 must not start lane allocation without a certificate carrying at least the
following semantics. The exact R3 class names remain an R3 decision.

```python
class CertifiedLaneSlot(RoutingIrModel):
    slot_id: str
    section_id: str
    layer: Literal["F.Cu", "B.Cu"]
    order_index: int
    centerline_geometry_id: str
    maximum_track_width_mm: float
    supported_clearance_domain_ids: tuple[str, ...]

class CertifiedCorridorSection(RoutingIrModel):
    section_id: str
    entry_portal_id: str
    exit_portal_id: str
    lane_slots: tuple[CertifiedLaneSlot, ...]
    swap_window_ids: tuple[str, ...] = ()
    transition_window_ids: tuple[str, ...] = ()

class CorridorCapacityCertificate(RoutingIrModel):
    schema_id: Literal["pcbsmith-corridor-capacity-certificate"]
    schema_version: int
    certificate_id: str
    board_geometry_fingerprint: str
    static_obstacle_fingerprint: str
    rule_profile_fingerprint: str
    demand_fingerprint: str
    corridor_graph_fingerprint: str
    grid_mm: float
    sections: tuple[CertifiedCorridorSection, ...]
    reserved_demand_ids: tuple[str, ...]
    exact_capacity_proof_id: str
```

The certificate demand fingerprint must include active member sets by section,
member widths, all hard clearance-domain IDs and radii, allowed layers, via
policy, portal/boundary requirements, and pre-reserved ordinary/non-bus demand.
It must describe usable ordered lane slots, not only an integer `capacity=8`;
R4 needs slot continuity between sections and exact centerline/keep-in geometry
to realize a plan.

Before use, R4 recomputes and compares every input fingerprint. A changed
outline, pad placement, fixed track, zone/keepout authority, profile, width,
clearance rule, grid, target-net set, or R2 reservation makes the certificate
stale. Stale and insufficient certificates are typed failures. R4 must not
quietly shrink spacing, omit a member, change a layer policy, or fall back to an
uncertified geometric offset.

The certificate is a coarse/planning proof, not final copper acceptance. Every
realized segment and via still passes R2 claim reconstruction, zero-overuse
accounting, and the board exact checker.

## Deterministic lane allocation

### Normalization

1. Canonicalize bus declarations by IDs, without changing the semantic order of
   boundaries or members within a declared boundary.
2. Validate terminal ownership and active-member intervals against the netlist.
3. Derive hard pitch for every adjacent active member pair.
4. Validate the R3 certificate and filter slots by width, clearance domains,
   allowed layer, transition policy, and reservations.
5. Project each boundary's declared orientation onto its certified portal and
   enumerate only explicitly permitted initial orders: original, whole reversal
   when allowed, and named pin-compatible permutations.

### State and transitions

For the common no-swap case, allocation is linear: map the active ordered tuple
to consecutive compatible slots on each section, preserving member-to-slot
continuity. This scales to the 16-member thermometer group without factorial
search.

When declared swap windows exist, use bounded dynamic programming over corridor
sections. A state is:

```text
(section_index,
 active_member_order,
 member_to_slot_ids,
 member_layers,
 via_counts,
 swaps_used_by_window)
```

Transitions may retain lanes, shift the whole active bundle into another
consecutive slot block, activate/deactivate a member at a terminal/tap, make an
allowed synchronous or bounded independent layer transition, or apply one
declared adjacent transposition inside the current swap window. Never enumerate
arbitrary permutations. Deduplicate equivalent states by their complete
semantic key.

Use fixed integer costs and a complete tie key. A recommended initial objective
is lexicographic, not a weighted float:

```text
(hard_violation_count,               # always zero for retained states
 overflow_units,                     # always zero for a certified allocation
 swap_count,
 layer_transition_count,
 total_lateral_slot_shift,
 nonpreferred_layer_sections,
 estimated_escape_cost_units,
 canonical_state_key)
```

The allocator must not trade a hard pitch, boundary order, or capacity
violation for shorter geometry. Candidate construction order, dictionary order,
and input reversal must not alter the selected semantic result.

### Allocation output

The immutable output records, per section and member, lane slot, layer,
centerline geometry ID, entry/exit portal point, terminal activation/deactivation,
and any swap/via transition. It also records unused certified capacity and all
rejected-candidate reason counts. The allocation fingerprint covers the bus,
certificate, normalized boundary choices, and full assignment.

## Detailed realization

### Order of work

1. Strip every target member's old segments and vias once, as R2 does.
2. Reserve the certified lane assignment as a group plan; do not yet present it
   as copper.
3. Route terminal escape pigtails from exact pads to the assigned entry/exit or
   tap ports. Pigtails use the exact R2 hard obstacle kernel, ordinary/pairwise
   claim domains, fixed expansion budgets, and stable tie-breaking. Escape
   regions/portals from R3 are keep-ins, not permission to cross obstacles.
4. Realize corridor trunks from certified lane centerlines.
5. Join pigtails and trunks into one complete tree per net, prune only copper
   proven redundant, reconstruct final R2 claims from emitted segments/vias,
   and verify every declared terminal is connected.
6. Commit all member claims as one transaction, negotiate conflicts with other
   target routes at group granularity, require zero overuse, materialize the
   board, then invoke exact checking.

One member failure rolls back every provisional member route, claim, lane
reservation, and emitted geometry from that group attempt. No old/new mixture
may survive in either the ledger or materialized layout.

### Optional leader plus offsets

Leader-plus-offset realization is permitted only when all active followers:

- use the same certified section sequence and layer;
- retain a constant lane order and certified pitch through the realized span;
- have no swap or independent transition in that span;
- can be derived from the certificate's lane centerlines without leaving their
  exact keep-ins; and
- pass exact obstacle, minimum-segment, corner, and resource-claim validation.

Prefer generating every follower from the certified spine and its explicit slot
offset, not recursively offsetting follower N from follower N-1. Canonicalize
H/V/45 bends, intersect adjacent offset rays deterministically, cap or bevel
miters using fixed geometry rules, and reject self-intersection, reversed short
segments, concave-corner escape, or an offset that changes section order.

If these preconditions fail, realize lane centerlines independently while
retaining the same allocation. Do not count that as degradation: leader offsets
are an implementation technique, not a requested property.

### Pigtails, collisions, and replanning

Pigtails may fan into the certified portal but may not reorder members outside a
declared boundary fragment/swap region. Their search state must include the
chosen portal/slot so a cheap connection to the wrong lane cannot win.

On a pigtail or trunk collision, replan in this fixed nesting order:

1. alternate pigtail candidate for the same lane allocation;
2. alternate certified contiguous slot block for the same corridor;
3. alternate allowed boundary reversal/permutation;
4. alternate R3 corridor certificate candidate;
5. bounded group-level negotiated rip-up/retry with other target routes;
6. explicitly authorized individual fallback.

Each level has an independent budget and deterministic candidate order. Replan
the complete affected group, not just the colliding follower, because changing
one lane can invalidate order, pitch, capacity, and coupled-length accounting.

### Degraded fallback

Individual R2 routing may run only when `allow_individual_fallback=True`, no hard
bus constraint is being waived, and the member-count budget permits it. It uses
the original profile and exact checks; fallback is never permission to weaken a
clearance or safety rule.

The result must list every fallback member, the first bus-plan failure reason,
which advisory properties were lost, and the independently routed geometry's
measured metrics. It returns `degraded`, not `routed`, even if the board is fully
connected and DRC-clean. If a hard lane-order, timing, coupling, or coherence
constraint cannot be met, fallback is forbidden and the group fails.

## Interaction with R2 negotiation

R4 needs group-aware orchestration but should reuse R2 physical claims and
search costs:

- the occupancy ledger continues to count distinct net owners, not bus groups;
- same-net branches remain set-valued and never double consume a resource;
- different bus members remain different nets and must not share ordinary or
  applicable pairwise resources;
- every final trunk, pigtail, and via is rasterized through the existing capsule
  and via claim builders;
- a bus attempt owns a tuple of complete `NegotiatedGridRoute`-equivalent member
  routes plus a lane allocation; commit/rip-up/restore is atomic across that
  tuple;
- R2 present/history penalties may select among already capacity-certified R4
  plans, but may not create an uncertified lane or permutation;
- ordinary nets and buses need one deterministic global reroute schedule. A
  conflict score should rank a bus by the union of overuse touched by its member
  claims, then by stable baseline rank and bus ID. Rerouting that bus removes all
  of its member claims before searching a replacement.

Initial R4 should not mutate `RoutingRunResult` schema v2 to pretend a bus is one
net. Either add a separate bus result embedded beside the existing run result or
design routing IR schema v3 explicitly. Net/pass telemetry must remain truthful
for physical work even when a group attempt later rolls back.

## Metrics and authority checks

Report, but do not automatically enforce, the following deterministic metrics:

- allocated and realized corridor length per section and member;
- coherent length: the measure along the certified spine where every currently
  active member is present, in its assigned order, within pitch tolerance, and
  on the assigned layer;
- coherence fraction: coherent length divided by the certificate's total span
  over which at least two members are active (define empty denominator as
  `not_applicable`, never 100%);
- member routed lengths, maximum length spread, modeled delay spread, and skew;
- per-member and spread of via counts and layer transitions;
- declared versus realized swaps/reversals and any order violation;
- minimum/maximum adjacent pitch and pitch deviation;
- pairwise parallel/coupled length by layer, spacing band, and reference-return
  structure;
- bundle-to-foreign-net parallel exposure by applicable clearance/victim class;
- pigtail length and expansion work separately from trunk work;
- individual-fallback member count and lost-property IDs.

Timing checks must use the declared propagation model, not convert millimeters
to picoseconds with a universal constant. Coupling checks must use the declared
stackup/reference and validation method. When an input is absent, the result is
`unverified`/advisory, not a numeric pass.

## Result, telemetry, fingerprints, and budgets

### Typed terminal reasons

Use a bus-specific reason enum rather than overloading `UNROUTABLE`:

```text
invalid_bus_declaration
missing_capacity_certificate
stale_capacity_certificate
capacity_insufficient
boundary_order_incompatible
lane_assignment_unavailable
via_policy_incompatible
escape_unroutable
trunk_realization_collision
connectivity_rejection
resource_overuse_remaining
expansion_budget
allocation_state_budget
realization_attempt_budget
pass_budget
stagnation
exact_check_rejection
fallback_not_authorized
hard_constraint_unverified
```

Precedence follows work causality: invalid/stale input before search; the first
exhausted work budget before a later generic routing failure; exact rejection
only after connected zero-overuse materialization; and fallback status only
after the primary bus failure is preserved.

### Fixed budgets

```python
class BusRoutingBudget(RoutingIrModel):
    max_corridor_candidates: int
    max_allocation_states: int
    max_group_negotiation_passes: int
    max_group_realization_attempts: int
    max_pigtail_candidates_per_terminal: int
    max_expansions_per_pigtail: int
    max_expansions_per_member: int
    max_total_expansions: int
    max_stagnant_passes: int
    max_exact_check_rejections: int
    max_fallback_members: int
```

Zero must have an explicit meaning for every field, and work must be checked
before an operation that would exceed its budget. Allocation-state count,
pigtail expansions, grid expansions, group passes, rollback count, exact-check
calls, and fallback work are all separately reported.

### Telemetry layers

Recommended immutable records are:

- `BusAllocationAttemptTelemetry`: certificate/corridor ID, boundary choice,
  states expanded, candidate assignment fingerprint, outcome/reason;
- `BusMemberRealizationTelemetry`: member/net, pigtail and trunk work, segments,
  vias, length, claims fingerprint, connectivity result;
- `BusGroupAttemptTelemetry`: attempt/pass index, lane allocation, member
  telemetry, atomic commit/rollback, R2 overuse, metrics, failure reason;
- `BusRoutingResult`: versioned input fingerprints, final status, primary and
  fallback outcomes, allocation, metrics, exact verdict, all attempts, and
  budgets.

An attempt that emitted provisional geometry and rolled it back still reports
its work. A member is `connected=True` only for a complete tree. Board-level
exact acceptance is not copied onto every member.

### Fingerprints

At minimum pin these SHA-256 semantic fingerprints:

1. bus declaration;
2. board/netlist geometry relevant to the route;
3. rule profile and executable clearance domains;
4. R3 certificate and demand;
5. allocation policy and fixed budgets;
6. each lane allocation attempt;
7. each member's emitted segments/vias and reconstructed claims;
8. atomic group route map and occupancy ledger per pass;
9. final materialized layout route geometry;
10. exact checker ID and finding fingerprints.

Canonical segment identity must normalize only representations proven
geometrically equivalent; it must not sort away branch order before stable route
emission is defined. Reversed input mappings, set iteration, or fixture JSON
construction must produce identical semantic fingerprints and board bytes.

## Staged firing fixtures and tests

R4 must be introduced in slices. Every slice ends with strict typing, Ruff,
focused tests, the full suite, and deterministic repeats. Board-level tests add
the exact checker; unit fixtures do not substitute for it.

### R4.0 - declarations and certificate handshake - **COMPLETE 2026-07-16**

No router behavior yet.

Implemented in `bus_ir.py`: versioned declarations, active-member intervals,
permutation/layer/via/fallback policies, evidence-aware timing/coupling/
coherence authority, capacity certificates, and a fail-closed context handshake
for terminal ownership, profile width, freshness, grid, portal, swap-window,
and transition-window references. This is evidence validation, not routing.

- valid straight two-boundary bus with unique members/terminals;
- duplicate net/member/terminal/boundary rejection;
- terminal pad does not belong to net;
- member disappears without declared tap;
- width below profile minimum;
- hard budget without complete evidence/applicability;
- missing, stale board, stale profile, stale demand, and wrong-grid certificate;
- exact semantic JSON/fingerprint under reversed construction order.

### R4.1 - boundary compatibility and lane allocation - **R4.1a/b COMPLETE 2026-07-16**

`bus_allocator.py` now emits schema-v2 semantic allocation results. It supports
same/reversed order, exact declared boundary permutations, bounded adjacent
swaps only in declared certificate-listed windows, and source/tap/sink member
activation/deactivation. Certified semantic layer transitions honor forbidden,
synchronous, declared-window, and independent-bounded via policy, including
per-member count/spread limits; no physical via is emitted. Every swap and lane
state expansion checks the fixed state budget first. Telemetry/fingerprints bind
orders, permutation boundaries, activations, swaps, transitions, and via counts.

The straight four-member fixture pins result fingerprint
`3417223856291e6ce0ff43939468d84d18f222070bc94ff5383b57a261c359e1`
and allocation-decision fingerprint
`34190f2212eedabeae24186cd6a855e55e20585712e7c8a04c3f0c5f27eb4366`.
The bus-IR plus allocator matrix is 61 passed. The designed combined
LCS/disordered-pin-row optimizer is not present: exact declared permutation and
one-member outlier-transition fixtures are separate and must not be described
as full LCS support. Hard pairwise pitch enforcement is also still open.

Use tiny JSON fixtures with literal expected assignments and fingerprints:

1. same-order four-member bus, one layer, exact capacity four;
2. reversed target order with reversal forbidden (typed failure);
3. the same target with whole-bundle reversal allowed (success, no swaps);
4. one adjacent inversion with no swap window (failure);
5. the same inversion with one declared swap window (one deterministic swap);
6. a disordered pin row where an LCS-compatible subset stays on one layer and
   declared outliers use a transition window;
7. capacity N-1 for N members (failure before detailed routing);
8. extra slots on both sides with two equal-cost slot blocks (stable canonical
   choice);
9. mixed member widths/clearances where integer slot count alone would pass but
   slot capability rejects the plan;
10. member terminating at an intermediate tap while the remaining active order
    continues unchanged;
11. one-less allocation-state budget and zero-state budget typed outcomes;
12. input-order and repeated-run fingerprint equality.

### R4.2 - detailed realization and transactionality - **R4.2a/b COMPLETE; R4.2c IN PROGRESS**

R4.2a (`bus_geometry.py`) realizes exact caller-certified straight, one-bend,
and multi-bend trunk centerlines inside fingerprinted keep-ins and reconstructs
ordinary/pairwise R2 resource claims. It validates exact bus/allocation/
certificate/profile/registry bindings and active section subsets. It performs
zero search and emits no pad pigtails, transition vias, board mutation, or exact
verdict. The straight fixture pins geometry, claim, and realization fingerprints
`3667a89d37849bc4b17166bca1f5fbf769e983ca053da489fcc5e601f0b9a852`,
`003bcd7fb5e0b117913e407a2aaa4b19152726981cb4dd59f40a8abf88ab3195`,
and `7f50715d306290fc8906027bffc0cf5929d7f5e652491cd158c3b22f5a644bc1`.

R4.2b (`kicad/bus_transaction.py`) validates complete per-member route bundles
and atomically replaces all member routes/claims in one ledger and route-map
transaction. Late follower failure or arbitrary exception restores the exact
old routes, claims, ledger fingerprint, and route-map fingerprint. A committed
candidate may still report resource overuse; commit telemetry is deliberately
not an exact-check or acceptance verdict. The committed fixture bundle pins
`8e137ab2503406ca2983a7f0bc17b43fefa0ce003951e55f88ae14ec3eac121e`.

R4.2c integration is in progress. A partial pure composition module may validate
caller-supplied pigtail/transition geometry, but generated pigtail search,
transition-via realization, board materialization, negotiated retries, and an
exact-checked atomic commit are not complete and carry no completion claim.

Synthetic shaped-board fixtures should cover:

- straight, one-bend, and multi-bend certified corridors;
- constant-pitch leader offsets matching independent lane realization;
- a concave/miter case where offset realization is rejected and independent
  certified lanes succeed;
- pigtails that can reach only their assigned portal and cannot cross to a
  cheaper wrong lane;
- synchronous layer transition with distinct via sites;
- forbidden and escape-only via failures;
- diagonal-crossing and via-site R2 resource conflicts;
- a late follower collision rolling back every earlier member claim and segment;
- alternate slot-block replan succeeding after the first detailed collision;
- injected exception restoring the old complete group route and ledger exactly;
- final claims reconstructed exactly from emitted `TrackSegment`/`ViaSpec`;
- zero overuse plus accepting exact checker, no checker (`accepted=False`), and
  rejecting exact checker with no fabricated net failure;
- one-less pigtail, member, total expansion, realization-attempt, pass, and
  stagnation budget outcomes;
- deterministic board bytes, geometry, telemetry, and fingerprints.

### R4.3 - group/ordinary negotiated interaction

- a bus and two ordinary nets compete for two R3 corridors; every sequential
  hard-block order fails, while group-level negotiated replacement reaches a
  certified zero-overuse assignment;
- moving one member alone would appear cheaper but violates group lane order;
  the complete bus transaction moves instead;
- group reroute failure restores all old member routes;
- pairwise special-clearance domains remain pair-specific and conservative;
- non-target and fixed copper remain hard obstacles and byte-identical;
- a requested advisory coherence target misses: exact board is connected but
  result is visibly degraded only when fallback was explicitly authorized;
- a hard timing/coupling target misses: fallback is forbidden and result fails.

### R4.4 - thermometer pilots

Do not begin until the R2 adversarial board mazes and R3 capacity certificate
fixtures pass.

Pilot in increasing topology difficulty:

1. `/SEG2` through `/SEG8` as the seven-output U2 package-side fragment to its
   resistor boundary;
2. `/SEG10` through `/SEG16` as the corresponding U3 fragment;
3. add `/SEG1` and `/SEG9` through separately declared QA boundary fragments,
   joining each register's downstream certified corridor without inventing a
   common pin row;
4. `/SRCLK`, `/RCLK`, and `/OE` as a common U1-U2-U3 multi-tap trunk;
5. add `/SER` as a member that exits at U2 while the other three continue to U3;
6. only then evaluate grouping the two SEG banks or the `/LK` LED-side nets if
   their capacity and electrical declarations justify it.

The fixture must pin the real netlist terminal/pad identities, shaped outline,
placements, profile, 0.2 mm widths, R3 certificate, active-member set per stem
section, and expected allocation/route fingerprints. Do not merely assert that
all nets routed. Assert boundary orders, member activation/taps, lane slots,
zero R2 overuse, exact/virtual DRC acceptance, no lost non-route `BoardLayout`
fields, stable bytes, and truthful metrics.

The final thermometer authority gate additionally requires KiCad DRC, reader
equality, schematic/ERC and simulation authorities already required by the
project, visual review, and comparison against the legacy baseline without a
claim of superiority unless a pinned corpus measures completion, length, vias,
runtime, reproducibility, and manual repair burden.

## Recommended implementation slices

1. **R4.0 - model/evidence contract - COMPLETE.** Engine-neutral declarations,
   validators, semantic fingerprints, evidence authority, and the narrow R3
   certificate handshake are implemented. No geometry belongs to this slice.
2. **R4.1 - deterministic allocator - R4.1a/b COMPLETE.** Same/reversed and
   exact declared orders, bounded certified adjacent swaps, activity intervals,
   semantic transitions, deterministic telemetry, and budget fixtures are
   implemented within the limitations above.
3. **R4.2 - certified-lane realization - PARTIAL.** R4.2a certified trunks and
   claim reconstruction plus R4.2b atomic group rollback are complete. R4.2c
   pigtail/transition integration, materialization, and exact checking are in
   progress. Leader offsets remain future work.
4. **R4.3 - negotiated group orchestration - PENDING.** Interleave bus and
   ordinary targets using atomic group claims, present/history costs,
   deterministic conflict order, and truthful bus telemetry.
5. **R4.4 - thermometer pilot - PENDING.** Fire package-side SEG fragments,
   then the homogeneous three-net control trunk, then heterogeneous taps/QA
   fragments.
6. **R4.5 - evidence-backed electrical enforcement - PENDING.** Add timing/
   coupling and coherence hard gates only for interfaces with complete
   applicability and a validated calculation, field-solver, simulation, or
   measurement method.

## Unresolved choices requiring decisions before production code

1. **R3 certificate schema and geometry carrier - resolved for R4.0/R4.2a.**
   `CorridorCapacityCertificate` carries the capacity/freshness contract and the
   separately fingerprinted certified-lane geometry registry carries exact
   centerlines and keep-ins. R4.2c still must finish exact portal/pigtail and
   transition-via integration without duplicating those authorities.
2. **IR placement - resolved for v1.** Engine-neutral bus and certificate
   declarations live in `bus_ir.py`; allocator/geometry records remain outside
   `CircuitObject`. Circuit serialization migration is still a separate future
   decision.
3. **Routing schema v3 versus companion result - partially resolved.** R4.1 uses
   a companion schema-v2 bus allocation result and R4.2b uses separate
   transaction telemetry, leaving `RoutingRunResult` unchanged. A unified routing
   schema and caller migration remain open until integrated exact-checked commit.
4. **Global R2/R3/R4 schedule.** The deterministic policy for interleaving
   ordinary nets, several buses, and fine-pitch escape needs a reviewed baseline
   order and objective. Permanent fine-phase freezing would violate the current
   R2/R3 direction.
5. **Multi-terminal corridor grammar - chain resolved, tree open.** V1 implements
   a canonical section chain with validated source/tap/sink activity intervals.
   Branching bus corridor trees remain unsupported and require a separate grammar.
6. **Swap realization - semantic allocation complete, geometry open.** R4.1b
   allocates bounded adjacent swaps only in exact declared, certificate-listed
   windows and reports them truthfully. R4.2 still needs an exact geometry
   template or local detailed solver; no emitted copper currently realizes a
   semantic swap.
7. **Promotion authority.** The exact process and reviewer record that promotes
   advisory timing/coupling/coherence evidence to a hard route constraint is not
   yet modeled outside safety insulation. Reuse `EvidenceRef`; do not invent a
   hard number in the router.
8. **Coherence denominator for branches.** This design recommends measuring only
   spans with at least two simultaneously active members. That definition must
   be approved and pinned before golden metrics.
9. **Thermometer electrical declarations.** Actual 74HC595 output rise time,
   firmware shift/latch rate, stackup/return continuity, acceptable LED-control
   noise/skew, and relevant coupled lengths are not yet a complete hard budget.
   The initial thermometer bus goal is ordered craft and routability; electrical
   thresholds remain advisory until those facts are pinned.

The active next action is to finish and fire R4.2c without widening authority:
connect exact pad pigtails and declared transition vias to certified trunks,
reconstruct complete claims, preserve atomic rollback, then materialize and run
the separate exact checker. Only after that should R4.3 group/ordinary
negotiation and the staged thermometer pilots begin.
