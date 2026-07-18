# R5 placement fidelity and routability-surrogate design

Date: 2026-07-15  
Scope: implementation design only. This document does not claim that R5 is
implemented, that a surrogate proves routability, or that an accepted placement
exists for the thermometer board.

## Executive decision

R5 should be a new, explicitly selected placement-search path built around a
lossless `BoardLayout` template. It must not mutate the behavior or defaults of
the current `bare_layout`, `search_placements`, `climb_placements`, legacy
`route_board`, or negotiated `route_board_negotiated` entry points.

The new path has five ordered stages:

1. construct a probe by replacing only declared component poses and explicitly
   selected target-net copper in an existing board template;
2. legalize exact placed component body and courtyard geometry against the
   shaped board and other placed geometry;
3. compute deterministic, placement-only routability surrogates;
4. send a deterministic Pareto subset through R3 coarse planning and R2
   detailed negotiated routing, when those capabilities are available; and
5. invoke one supplied exact board checker on each algorithmically complete
   detailed result.

The strongest placement result is `accepted=True`, which requires complete
detailed routing, zero R2 resource overuse, and an affirmative exact-check
verdict. Legalization, favorable surrogate values, zero R3 overflow, or R2
algorithmic success without a checker are not acceptance.

R5 must repair a concrete fidelity defect before adding optimization. The
current `bare_layout` constructs a new rectangular layout and retains only
placements, dimensions, rotations, flips, and reference-label offsets. It loses
the shaped outline, zones, graphics, mask apertures, hidden-reference state,
existing tracks/vias, and any future `BoardLayout` fields. That object is not a
valid probe for shaped-board placement. The new API must accept a template and
use field-preserving replacement; it must never reconstruct a board from a
hand-maintained subset of fields.

## Dependencies and authority boundaries

R5 depends on the contracts designed in R3 and R4, but it must remain useful in
their absence.

- R2 supplies complete-net detailed negotiated routing, fixed work budgets,
  resource overuse, truthful algorithmic success, and a separate exact-check
  verdict.
- R3 supplies shaped-corridor capacity, portal overflow, unresolved demand,
  geometry issues, optional soft per-net guidance, and a planning fingerprint.
  R3 is a conservative screening signal, not a final unroutability proof.
- R4 declarations, when implemented, supply explicit bus member/boundary order
  for the order-conflict surrogate. R5 must not invent bus membership from net
  names. R4 detailed lane realization remains a later authority path.
- `run_virtual_drc`, `run_design_checks`, and ultimately KiCad DRC remain exact
  or higher-authority checks after materialized routing. Placement-only
  surrogates do not replace them.

If R3 is unavailable, a candidate may still be selected for unguided R2
routing. Telemetry records `corridor_state="not_run"`; it must not manufacture
zero overflow. If an exact checker is unavailable, a complete R2 candidate has
`algorithmic_success=True`, `exact_check_accepted=None`, and `accepted=False`.

## Current repository contracts that R5 must preserve

`BoardLayout` currently carries:

- ordered `BoardComponent` placement objects and x anchors;
- per-reference y anchors, rotation, and front/back placement;
- fixed track segments and vias;
- rectangular dimensions and an optional shaped outer polygon;
- rectangular copper-zone declarations;
- opaque raw board graphics;
- hidden-reference and footprint-local reference-label state; and
- typed board-level solder-mask apertures.

Placement transforms are already established by live KiCad parity:

```text
front local point: rotate_offset(local, footprint_rotation)
back local point:  mirror_x(rotate_offset(local, -footprint_rotation))
board point:       anchor + transformed local point
```

The same transform is used for pads, holes, body geometry, courtyard geometry,
and footprint-local labels. A new legalization kernel must call one shared
public transform rather than copy `_back_offset`, `back_offset`, or `_placed`
from separate modules.

`FootprintSpec` currently retains a convex `courtyard_hull` and convex
`fab_hull`, with rectangle fallbacks. Those are useful filters but are not
lossless exact body/courtyard geometry. The current courtyard check also shrinks
the hull by 0.02 mm to avoid floating noise. R5 exact legalization cannot call
that private approximation and describe the result as exact.

## Non-negotiable invariants

1. **A probe is a template derivative.** Every field unrelated to the declared
   pose changes and target-route stripping is byte-for-byte/equality preserved.
2. **No stale target copper.** A candidate that changes a target terminal pose
   strips every segment and via owned by the selected target nets before any
   surrogate or routing stage. Non-target copper remains fixed.
3. **No accidental component loss.** Template placement order and exact
   `BoardComponent` objects remain authoritative. Unknown pose references,
   duplicate template references, or missing required references fail closed.
4. **Sides are explicit.** Front and back transforms and same-side courtyard
   conflicts never alias. A side flip is a semantic pose change, not only a
   renderer flag.
5. **Legalization uses exact or explicitly bounded geometry.** Unsupported
   geometry cannot become an empty body/courtyard or a numeric pass.
6. **Surrogates are not proofs.** HPWL, crossing count, pin alignment, and R3
   overflow are ranking/screening information. Only hard geometric
   legalization may reject before routing.
7. **HPWL is secondary.** It may break a tie or rank candidates on the same
   Pareto front; it may not outrank unresolved demand, portal overflow, escape
   failure, or declared order conflict.
8. **Coarse failure is not exact unroutability.** A conservative R3 failure may
   strongly deprioritize a candidate, but a configured exploration quota may
   still send it to R2.
9. **Detailed routing is deterministic and bounded.** The complete R2/R3
   policies and budgets are inputs, fingerprinted, and copied unchanged to
   every candidate evaluation.
10. **Acceptance is singular.** There is one final exact-check result per
    materialized candidate. Exact rejection preserves algorithmic routing
    success and its finding fingerprints.
11. **No silent fallback.** R3 unavailable, R3 unsupported, unguided R2,
    legacy-router compatibility evaluation, and R4-not-implemented are distinct
    telemetry states.
12. **Determinism covers semantics, not elapsed time.** Tests pin canonical
    SHA-256 fingerprints, candidate order, selected subset, work counts, and
    emitted geometry, never wall-clock duration.

## Proposed module and API boundary

Put engine-neutral declarations/results in `src/pcbsmith/placement_ir.py` and
KiCad template/geometry/surrogate orchestration in
`src/pcbsmith/kicad/placement_routability.py`. Do not expand the current
`placement_search.py` until the new path has parity and firing fixtures.

The public entry point should be separate:

```python
def search_placements_routability(
    template: BoardLayout,
    netlist: BoardNetlist,
    policy: PlacementSearchPolicy,
    budget: PlacementBudget,
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    target_nets: Collection[str] | None = None,
    net_widths: Mapping[str, float] | None = None,
    clearance_groups: Sequence[ClearanceGroup] = (),
    corridor_policy: CorridorPolicy | None = None,
    bus_groups: Sequence[BusGroup] = (),
    exact_checker: ExactRouteChecker | None = None,
) -> PlacementSearchResult: ...
```

The template is mandatory. Width and height are read from it, not repeated in
the call. The policy declares movable, rotatable, flippable, and fixed
references plus allowed translations/angles/sides. The API rejects conflicting
sets, unknown references, duplicate bus ownership, and a target net absent from
the netlist. Unlike the current R2 convenience behavior, placement optimization
must not silently ignore a misspelled explicit target because that changes
which stale copper is stripped.

## Lossless template-preserving probe construction

### Canonical component pose

Normalize every placed component into a versioned record:

```python
class ComponentPose(PlacementIrModel):
    reference: str
    x_mm: float
    y_mm: float
    rotation_deg: float       # canonical [0, 360)
    side: Literal["front", "back"]
```

Coordinates and angles must be finite. Preserve full float values in semantic
records; do not round before geometry. A serialization quantum, if later
needed, is a declared policy value and cannot be an implicit `round(..., 4)`.

The base pose map is derived from the template using `placement_y`,
`placement_rotation`, and `part_flip`. Candidate pose maps must contain every
template placement exactly once. Board-only mounting holes may be declared
fixed but remain in the map and geometry.

### Probe operation

Probe construction performs these operations, in this order:

1. validate the template has unique placement references and that every
   netlist component being optimized has one matching template component;
2. validate the candidate pose map and policy permissions;
3. retain the template's placement order and replace only each placement's x,
   y, rotation, and flip state;
4. remove target-net segments and vias, retaining all non-target copper in its
   original relative order;
5. preserve every other template field unchanged; and
6. verify a lossless-probe invariant before returning.

Use `dataclasses.replace(template, ...)` with only `placements`, `part_y_mm`,
`part_rotation`, `part_flip`, `segments`, and `vias` named. Do not create a new
`BoardLayout(...)` from a field list. Preserve explicit zero-valued y/rotation
records only if they were semantically present in the template; candidate
normalization should otherwise produce one canonical representation. Choose
one rule and include it in the schema version so equal poses cannot fingerprint
differently.

The lossless invariant compares every dataclass field not in the six-field
mutation allowlist for equality. A test should enumerate
`BoardLayout.__dataclass_fields__`; adding a future field automatically expands
the preservation check instead of silently dropping it.

Target-route stripping is by exact net identity. It does not remove target pads,
zones, mask apertures, graphics, board holes, or footprint objects. A target-net
zone cannot be assumed to be replaceable routed copper; R3's existing
unsupported/zone policy remains authoritative.

### Template and candidate fingerprints

Create two distinct fingerprints:

- `template_fingerprint`: all placement-independent board semantics, all base
  component identities, the original poses, fixed copper, outline/cutouts,
  zones, graphics authority, mask apertures, profile fingerprint, netlist
  topology fingerprint, and target-net set;
- `candidate_fingerprint`: schema ID/version, template fingerprint, canonical
  candidate poses, proposal provenance, and all legalization/surrogate policies.

Opaque graphics are fingerprinted as exact strings in order. They are preserved
but not interpreted as geometry unless a typed parser supplies a verification
contract. When raw graphics may contain Edge.Cuts, R3 may remain unsupported;
R5 must report that state rather than substitute the rectangular dimensions.

## Exact body and courtyard geometry

### Required footprint representation

Before calling placement legalization exact, extend the footprint loader to
retain lossless placement geometry rather than only convex hulls:

```python
class PlacementRegionVerification(StrEnum):
    EXACT = "exact"
    BOUNDED_APPROXIMATION = "bounded_approximation"
    UNSUPPORTED = "unsupported"

class FootprintPlacementRegion(PlacementIrModel):
    region_id: str
    purpose: Literal["body", "courtyard"]
    local_compound: ExactPlanarCompound | None
    verification: PlacementRegionVerification
    maximum_error_mm: float | None
    source_layers: tuple[str, ...]
    source_fingerprint: str
```

`ExactPlanarCompound` retains canonical simple polygon boundaries. Direct
line/arc/circle primitive authority is outside the current placed-transform
kernel: curved source geometry must first use a proven-error polygonization and
remain `BOUNDED_APPROXIMATION`; it cannot be relabeled exact. Multiple disjoint
bodies and interior voids cannot be collapsed to a convex hull.
Where the KiCad footprint has no courtyard, the configured courtyard construction
rule (for example a
fab-body offset) is labeled derived and records its source/profile; it is not
called the exact source courtyard.

Existing `courtyard_hull` and `fab_hull` remain compatibility filters. They may
reject an obvious collision conservatively, but their non-overlap cannot prove
exact legality. The 0.02 mm centroid shrink in `_courtyard_polygon` is forbidden
in the exact kernel. Numeric robustness comes from canonical fixed-point board
units or exact orientation predicates plus a declared tolerance policy.

### One shared placed transform

Introduce a public transform function used by pads, holes, masks, bodies,
courtyards, and pin vectors:

```text
front point  = anchor + R(rotation) local
back point   = anchor + Mx(R(-rotation) local)
front vector = R(rotation) local_vector
back vector  = Mx(R(-rotation) local_vector)
```

Quarter turns use rational decimal-coordinate arithmetic through anchor addition
and are exact for the serialized coordinate semantics used by the geometry
predicates. Arbitrary angles use the dependency-free rational interval kernel:
a proven enclosure of pi, quadrant reduction, and alternating-series sine/cosine
bounds produce nominal polygon vertices plus a conservative maximum positional
error. This is bounded authority, not analytic exactness and not `libm`
authority. Direct arcs/circles are unsupported by this kernel and must arrive as
separately bounded polygonization. Reflection reverses winding; canonicalize
placed polygon winding without changing its point set. A back-side test must use
an asymmetric, non-origin-centered region at a non-right angle so an inverse-angle
or mirror-order bug cannot hide.

### Legalization rules

Legalization returns all findings, not only the first. It evaluates:

1. finite, valid component poses and policy permissions;
2. exact same-side courtyard interior overlap;
3. exact same-side physical-body overlap under the selected assembly/process
   rules;
4. body-to-outer-edge and body-to-cutout distance/containment using the active
   fabrication profile and declared connector/breakaway exceptions;
5. courtyard containment where the selected assembly policy requires it;
6. through-board body, lead, hole, or keepout interactions when typed geometry
   says they occupy both sides; and
7. unsupported or bounded geometry scopes.

Front and back courtyards do not collide merely because their 2-D projections
overlap. Same-side body/courtyard rules use side identity. Through-hole bodies
and mechanical keepouts need explicit side/span metadata; footprint `attr` alone
is not enough to infer a 3-D collision.

Touching semantics are rule specific. Courtyard boundary contact with zero
interior overlap is legal unless an assembly profile requires positive spacing.
Body-to-edge and body-to-body clearance use the declared positive rule.
Boundary contact is never decided by visually shrinking geometry.

For a bounded approximation, inflate occupied geometry and deflate the allowed
board region by `maximum_error_mm` for a conservative hard result. An
unsupported region affecting a movable component produces
`legalization_unverified`; default policy excludes it from the accepted Pareto
pool but may retain it diagnostically. It cannot be reported as legal.

## Deterministic candidate generation

### Policy

```python
class PlacementMovePolicy(PlacementIrModel):
    movable_references: tuple[str, ...]
    rotatable_references: tuple[str, ...]
    flippable_references: tuple[str, ...]
    translation_step_mm: float
    maximum_translation_steps: int
    allowed_rotation_deg: tuple[float, ...]
    pair_move_limit: int
    seed: int
    generator_id: Literal["canonical-neighborhood-v1"]
```

The base placement is always candidate zero. Enumerate single-component moves
in canonical reference order, then move-kind order, then signed displacement,
rotation, and side. Pair moves use canonical reference pairs and a versioned
counter-based permutation keyed by `(seed, template_fingerprint)`. Do not rely
on the implementation-specific call sequence of `random.Random`; inserting a
new draw must not renumber every later candidate.

Deduplicate by candidate fingerprint before charging a legalization budget.
Candidate display names are derived from the first 12 fingerprint hex digits,
not loop indices that change when an earlier duplicate disappears. Proposal
provenance retains parent fingerprint, moved references, and exact move clauses.

The generator may use a shaped-board feasible-anchor region to avoid obvious
off-board moves, but this is only an enumeration optimization. It must not clamp
x/y independently to a rectangular bounding box as `perturb` and
`propose_move` currently do. Every emitted pose still passes exact legalization.

### Budgets

Use one immutable, fingerprinted budget:

```python
class PlacementBudget(PlacementIrModel):
    max_proposals: int
    max_legalization_evaluations: int
    max_surrogate_evaluations: int
    max_corridor_plans: int
    max_detailed_candidates: int
    max_exact_checks: int
    max_r3_geometry_cells_per_candidate: int
    max_r3_geometry_portals_per_candidate: int
    max_r3_expansions_per_candidate: int
    max_r2_passes_per_candidate: int
    max_r2_expansions_per_candidate: int
    max_r2_expansions_per_net: int
    max_r2_stagnant_passes: int
```

Zero is meaningful at every stage. Work counts are charged before an operation
whose attempt consumes that budget, and terminal reasons distinguish proposal,
legalization, surrogate, corridor, detailed-routing, and exact-check
exhaustion. Child R2/R3 budgets are passed unchanged; R5 must not silently split
or grow them after seeing a difficult candidate.

## Placement-only routability surrogates

Return the raw integer/fixed-point metrics and evidence records. Avoid a single
weighted scalar whose units and priorities are opaque.

### Net-separation margin

Compute the minimum same-layer separation headroom among exact placed terminal
copper belonging to different nets:

```text
margin = exact boundary distance - applicable required clearance
```

Use the ordinary fabrication profile, conservative pairwise clearance domains,
qualified air-clearance groups, and caller groups exactly once. Creepage is not
a Euclidean separation surrogate. For not-yet-emitted copper, mask-state and
role selectors cannot safely narrow a requirement; apply the same conservative
net-wide policy as R2/R3 and record contributing domain IDs.

Report minimum margin, the responsible source IDs/nets/layer, and counts below
zero and below configured review bands. A negative exact terminal-copper margin
is a hard placement finding because the pads themselves already violate
clearance. Positive margin is not a global reward to maximize: after hard
violations are absent it is a robustness diagnostic and a late tie-breaker.

This metric is not the current `_min_cross_net_margin`, which examines already
routed `_Stadium` approximations at only the minimum ordinary clearance. R5 must
operate on exact placed pad copper before routing and preserve pairwise rules.

### Crossing and order conflicts

Build a deterministic placement demand sketch, not provisional copper:

1. map every exact pad terminal center and source ID;
2. for each multi-terminal net, construct a canonical rectilinear minimum-span
   sketch using terminal source ID for ties;
3. count proper intersections between sketches of different nets on each
   candidate layer, excluding shared endpoints and uncertain overlaps;
4. separately count boundary-order inversions at shaped bottlenecks or R3
   portals; and
5. when a `BusGroup` exists, compare terminal order only against its declared
   boundary fragments and allowed permutations.

Report geometric crossing count, overlapping-collinear ambiguity count,
pairwise net IDs, and declared bus-order conflict count separately. A sketch
crossing is a congestion predictor, not a copper collision and not a hard
rejection. An impossible declared bus boundary permutation may be a hard R4
declaration conflict, but only when the declaration and certified boundary are
both available.

Do not infer ordered buses from `/SEG1` naming or component pin numbering. Do
not use a factorial permutation search for a 16-member group; R4's allowed
reversal/named-permutation policy is the only search space.

### HPWL as a weak secondary term

For each routable net, compute half-perimeter wire length over exact physical
terminal centers:

```text
hpwl(net) = (max_x - min_x) + (max_y - min_y)
```

Record total, maximum-net, and per-net fixed-point micrometre values. Single-
terminal nets contribute zero. HPWL ignores obstacles, shaped boundaries,
layers, vias, width, terminal escape, and topology, so it ranks only after
legalization, unresolved escape/demand, portal overflow, and crossing/order
conflicts. It must never defeat a capacity-feasible placement merely because a
shorter placement points through a cutout or narrow stem.

### Portal overflow and unresolved demand

When R3 exists, request a fresh `CorridorPlanSummary` from the exact probe,
profile, widths, target set, clearance groups, and full R3 budget. Retain:

- total demand and guaranteed capacity units;
- total and maximum-resource overflow units;
- overflowing portal/resource IDs and contributing demands;
- unresolved demand IDs;
- terminal-unmapped and unsupported geometry issues; and
- graph, demand, allocation, and summary fingerprints.

Compare overflow only within the same quantum/profile/grid contract. The Pareto
axes are unresolved-demand count, unsupported-scope count, total overflow, and
maximum portal overflow. Because R3 is conservative and may omit a fine legal
path, these axes strongly rank but do not prove failure. Reserve a configured
`coarse_failure_exploration_slots` quota in the detailed subset so the design
can detect useful false negatives.

### Pin-escape alignment

Derive a local outward escape frame for each terminal from exact pad geometry
and exact body boundary. If the footprint supplies an explicit pin escape
vector, use it. Otherwise enumerate the finite set of outward normals at the
nearest body boundary and mark ambiguity rather than choosing by pin number.

For each allowed layer and via policy, probe a fixed, fingerprinted set of short
escape rays/turns using the R2 hard-obstacle kernel. Report:

- terminals with no legal first transition;
- terminals with only one legal escape alternative;
- fine-grid snap residual in integer grid quanta;
- angular misalignment between preferred outward direction and the nearest
  open corridor/portal;
- escape alternatives that consume a constrained R3 portal; and
- ambiguous or unsupported direction/geometry.

The score tuple is `(unescaped_count, constrained_count,
alignment_penalty_units, grid_residual_units, ambiguous_count)`. Counts precede
angle or grid preference. This is a local surrogate: a legal first transition
does not prove connection, and an off-grid terminal can still route through an
exact pad stub. R2 remains authoritative.

## Pareto screening and detailed evaluation

### Surrogate dominance

After exact legalization, define the primary minimization vector:

```text
(
  terminal_clearance_violations,
  unescaped_terminal_count,
  unresolved_corridor_demand_count,
  unsupported_corridor_scope_count,
  total_portal_overflow_units,
  maximum_portal_overflow_units,
  declared_order_conflict_count,
  geometric_crossing_count,
  constrained_escape_count,
)
```

One candidate dominates another only if it is no worse on every primary axis
and strictly better on at least one. Do not include HPWL in dominance. Within a
front, use this stable secondary key:

```text
(hpwl_total_um, -minimum_net_separation_margin_um,
 candidate_fingerprint)
```

If no exact terminal margin exists, use an explicit `unknown` rank after known
non-negative values, not a fabricated zero.

### Deterministic diversity subset

Select detailed candidates front by front until `max_detailed_candidates` is
filled. Within a front:

1. take the stable secondary-key leader;
2. take one leader from each distinct corridor allocation fingerprint;
3. take one leader from each distinct flip-set and coarse portal-overflow
   bucket; and
4. fill remaining slots by the stable secondary key.

The exact selection policy and bucket boundaries belong in the schema and
fingerprint. Always include the legal base placement if budget permits. Reserve
the explicit coarse-failure exploration quota before ordinary fill; unused
quota returns to the normal pool.

### R3 and R2 evaluation sequence

For each selected candidate in candidate-fingerprint order:

1. reuse its already fingerprint-matched R3 plan, if guidance-ready;
2. pass per-net soft corridor guides and the exact R3/R2 policies to R2;
3. when R3 is unavailable or not guidance-ready, run unguided R2 if policy and
   remaining budget allow;
4. require every target net to have a complete result and zero R2 overuse;
5. materialize candidate routes over the probe's preserved non-target copper;
6. run the supplied exact checker exactly once; and
7. retain all algorithmic and exact outcomes separately.

No route from one placement candidate may seed another unless a future API
declares an explicit transformed-route reuse proof. R2 history/ledger state is
fresh per candidate. Candidate evaluation order cannot affect another
candidate's geometry, cost, or result.

When R4 detailed routing becomes available, a declared bus group may be routed
as a transactional group before or inside shared R2 negotiation according to
the R4 contract. Until then R5 preserves bus declarations and scores order
conflicts, but must label detailed bus realization `not_run`, not success.

## Result and telemetry contract

Suggested engine-neutral models:

```python
class PlacementCandidateState(StrEnum):
    PROPOSED = "proposed"
    LEGALIZATION_REJECTED = "legalization_rejected"
    LEGALIZATION_UNVERIFIED = "legalization_unverified"
    SURROGATE_SCORED = "surrogate_scored"
    NOT_SELECTED_FOR_DETAIL = "not_selected_for_detail"
    CORRIDOR_FAILED = "corridor_failed"
    ROUTING_FAILED = "routing_failed"
    ROUTED_UNCHECKED = "routed_unchecked"
    EXACT_REJECTED = "exact_rejected"
    ACCEPTED = "accepted"

class PlacementFailureReason(StrEnum):
    INVALID_TEMPLATE = "invalid_template"
    INVALID_POSE = "invalid_pose"
    BODY_COLLISION = "body_collision"
    COURTYARD_COLLISION = "courtyard_collision"
    EDGE_OR_CUTOUT_VIOLATION = "edge_or_cutout_violation"
    GEOMETRY_UNVERIFIED = "geometry_unverified"
    PROPOSAL_BUDGET = "proposal_budget"
    LEGALIZATION_BUDGET = "legalization_budget"
    SURROGATE_BUDGET = "surrogate_budget"
    CORRIDOR_BUDGET = "corridor_budget"
    DETAILED_ROUTING_BUDGET = "detailed_routing_budget"
    DETAILED_ROUTING_FAILED = "detailed_routing_failed"
    EXACT_CHECK_BUDGET = "exact_check_budget"
    EXACT_CHECK_REJECTION = "exact_check_rejection"
```

Each `PlacementCandidateTelemetry` records:

- candidate and parent fingerprints, proposal provenance, canonical poses;
- template, netlist, profile, target, policy, and budget fingerprints;
- legalization findings with exact/bounded/unsupported verification;
- net-separation evidence, crossing/order conflicts, HPWL, corridor summary,
  and pin-escape evidence;
- Pareto front, dominance witnesses, diversity bucket, and selection reason;
- R3 plan/guide fingerprints and all R3 work counts/reason;
- R2 `RoutingRunResult`, expansions, passes, overuse, unresolved nets, route
  length, segment count, via count, and emitted-layout fingerprint;
- exact checker ID, acceptance, and finding fingerprints; and
- final state, failure reason, `algorithmic_success`, and `accepted`.

`accepted=True` validates all of the following: legalization exact or safely
bounded and clear; target routing complete; zero fine-resource overuse; R2
algorithmic success; exact check present and accepted; no exact rejection
finding; and all fingerprints coherent with the emitted layout. R3
guidance-readiness is not required for acceptance because R2 may route legally
without it.

`PlacementSearchPassTelemetry` records counts proposed, deduplicated,
legalized, rejected, scored, R3-planned, detailed-routed, exact-checked, and
accepted; budget consumed/remaining at every stage; Pareto-front sizes; selected
candidate fingerprints; and stage fingerprints. The final result includes all
candidate telemetry, not only winners, plus a stable ranked accepted tuple.

Canonical JSON uses sorted keys, compact separators, UTF-8, no NaN/Infinity,
and SHA-256. Semantic tuple order is preserved for bus members/boundaries and
candidate ranking; set-like collections are canonicalized by stable identity.

## Safe migration plan

1. Add the new IR, exact footprint placement geometry, shared transform, and
   template-probe helper without changing any existing entry point.
2. Add `search_placements_routability` as opt-in. It requires a template and
   explicit policy/budget.
3. Keep current `search_placements` and `climb_placements` behavior, signatures,
   `random.Random` candidate sequence, legacy router choice, score ordering, and
   defaults unchanged. Existing golden tests must remain byte-identical.
4. Mark `bare_layout` as compatibility-only in documentation after the new
   path ships. Do not redirect it to a template path because it has no template
   argument and callers may rely on its empty rectangular board.
5. Provide an explicit compatibility adapter that creates a rectangular
   template only when the caller requests legacy semantics. Its telemetry says
   `template_source="legacy_rectangular_adapter"`.
6. Pilot one shaped generated board through the opt-in path. Compare every
   preserved field, exact-check result, emitted KiCad bytes, runtime work
   counts, and deterministic fingerprints.
7. Migrate a board generator only through a reviewed call-site change. Never
   change the global default router or placement search as a side effect.
8. Consider changing a default only after a measured multi-board corpus shows
   no authority regression and the project owner explicitly approves it.

## Staged implementation and firing fixtures

Every slice ends with strict mypy, Ruff, focused tests, the full suite, stable
fingerprint checks, and the applicable serialized KiCad/DRC golden gate.

### R5.0 - lossless probe and schema

Implement the IR, policy/budget validation, template fingerprint, canonical
poses, and field-preserving probe only.

Firing fixtures:

1. a `sentinel_shaped_template` containing a concave outline, front/back parts,
   rotations, non-target and target tracks/vias, zones, opaque graphics, hidden
   references, label offsets, and typed mask apertures;
2. moving/flipping/rotating one target component changes only the six allowed
   fields and strips only selected target copper;
3. non-target copper order and every sentinel field remain equal;
4. a synthetic future dataclass field causes the preservation test to fail
   until explicitly classified;
5. unknown/missing/duplicate references and unknown target nets fail closed;
6. input mapping order produces identical probe and fingerprints; and
7. base probe round-trips to the template except for explicitly stripped target
   copper.

### R5.1 - exact and bounded transforms and legalization

Implement lossless body/courtyard extraction, shared exact-quarter/bounded-angle
placed transforms, shaped containment, error composition, and findings.

Firing fixtures:

1. an asymmetric L-shaped body and disjoint courtyard at 37 degrees on front
   and back, with pinned nominal vertices contained by certified intervals;
2. quarter turns remain exact without anchor-addition residue; reflection
   reverses winding but preserves the canonical placed point set;
3. same-side overlap fires while the identical opposite-side projection does
   not;
4. exact courtyard boundary touch is distinguished from interior overlap;
5. concave C/U outline contains the body but rejects the same anchor when a
   lobe crosses the notch;
6. a donut/cutout fixture rejects body intrusion even when its bounding box is
   inside the outer outline;
7. connector/breakaway edge exception is scoped by reference and rule ID;
8. bounded geometry uses its maximum-error envelope; unsupported geometry is
   unverified, never legal; and
9. the current convex hull and 0.02 mm shrink produce a deliberately different
   result, proving the authoritative transform path does not call them.

### R5.2 - deterministic candidates and budgets

Implement canonical neighborhood enumeration, deduplication, identities, and
stage budgets.

Firing fixtures:

1. repeated runs and reversed input set/map order pin candidate IDs/order;
2. adding a duplicate move does not renumber later candidates;
3. base candidate remains first;
4. a shaped edge move is rejected by legalization, not rectangle clamping;
5. front/back/rotation permissions fire independently;
6. zero and one-less proposal/legalization/surrogate budgets return exact typed
   reasons and work counts; and
7. changing seed, move policy, template, profile, or target set changes only the
   expected fingerprints.

### R5.3 - surrogate firing set

Implement exact terminal margin, HPWL, crossing/order, R3 summary seam, and pin
escape alignment.

Firing fixtures:

1. two pads violate a pairwise rule while clearing ordinary minimum; terminal
   margin fires with the pairwise domain ID;
2. qualified clearance and caller groups arrive exactly once; creepage is
   absent;
3. a two-net cross has one proper sketch crossing and a moved terminal removes
   it without changing HPWL priority semantics;
4. a declared bus boundary inversion fires, while an explicitly allowed whole
   reversal does not;
5. a shorter-HPWL placement overloads the only shaped portal and ranks behind a
   longer zero-overflow placement;
6. R3 unsupported/absent is distinct from zero overflow;
7. a fine-pitch pad facing a blocked body has no first transition; rotation or
   flip exposes a legal escape;
8. an off-grid pad stub remains diagnostically misaligned but is not declared
   unroutable; and
9. every evidence item and surrogate fingerprint is invariant to construction
   order.

### R5.4 - Pareto subset and R2/R3 detailed routing

Implement dominance, deterministic diversity selection, and per-candidate R2
evaluation.

Firing fixtures:

1. non-dominated candidates survive while a strictly dominated candidate does
   not consume a detailed slot;
2. equal fronts select distinct corridor fingerprints before near-duplicates;
3. the legal base and configured coarse-failure exploration candidate are
   retained when budget permits;
4. zero R3 penalties reproduce unguided R2 geometry and work counts except for
   explicit guide telemetry;
5. R3 guidance steers a symmetric detailed choice but cannot unblock a hard
   obstacle;
6. R3 coarse failure can still reach accepted unguided R2 routing;
7. fresh R2 ledger/history makes candidate result independent of evaluation
   order;
8. zero/one-less R3 and R2 budgets return their exact stage reason;
9. target routes replace stale target copper while fixed non-target geometry is
   preserved; and
10. repeated runs pin subset, R3/R2 telemetry, route geometry, and fingerprints.

### R5.5 - exact rejection and result honesty

Firing fixtures:

1. algorithmic R2 failure never invokes the exact checker;
2. algorithmic success without a checker is routed-unchecked and not accepted;
3. exact rejection retains R2 success, checker ID, and finding fingerprints;
4. exact acceptance is the only accepted state;
5. exact-check budget zero leaves a truthful routed-unchecked candidate;
6. a checker result for a mismatched materialized-layout fingerprint is
   rejected as incoherent; and
7. changing only exact findings changes result fingerprints but not proposal,
   legalization, surrogate, R3, or R2 fingerprints.

### R5.6 - compatibility and serialized authority

Firing fixtures:

1. all current `placement_search` tests and deterministic seeded outcomes remain
   unchanged;
2. legacy `route_board` and default board generators remain unchanged;
3. opt-in R5 on a rectangular fixture preserves all fields and reaches the same
   exact accepted board where geometrically equivalent;
4. serialized shaped fixture retains outline, zones, graphics, mask openings,
   side/rotation/labels, stable UUIDs, and non-target copper;
5. reader equality and render-repeat hashes pass;
6. virtual/design checks and `kicad-cli` DRC pass; and
7. a measured corpus records proposals, R3/R2 work, exact rejections, route
   length/vias, and acceptance without claiming global superiority.

### R5.7 - thermometer pilot

Do not run placement optimization on the thermometer until the prerequisites
below are met. First run a reduced synthetic stem fixture, then the real board.

Firing sequence:

1. preserve the current thermometer outline, 63-part placement identities,
   front/back split, graphics, label offsets, mounting hole, and all declared
   widths/order inputs in the base probe;
2. move only a small declared set around one register/resistor/LED stem region;
3. demonstrate the shorter-HPWL/overloaded-portal fixture before trusting HPWL;
4. score SEG and control declarations without inferring bus semantics;
5. route a deterministic Pareto subset through R3-guided R2;
6. require zero R2 overuse, complete target connectivity, virtual/design checks,
   reader equality, simulation where applicable, and exact KiCad DRC;
7. pin candidate, corridor, route, report, and rendered-board fingerprints; and
8. expand movable scope only after work counts and failure evidence remain
   reviewable.

## Thermometer integration prerequisites

The thermometer must not be the first proof of any R5 primitive. Required
before its pilot:

1. R2 negotiated caller migration is available as an opt-in board-generator
   path, including exact checker plumbing and serialized maze authority.
2. R3 graph, quantity ledger, shaped outline/portal capacity, soft R2 guidance,
   and `CorridorPlanSummary` are implemented and firing on a narrow-stem
   synthetic board.
3. Exact lossless body and courtyard geometry exists for every movable
   thermometer footprint; unsupported geometry excludes that reference from
   optimization.
4. The shared front/back transform passes asymmetric arbitrary-angle fixtures.
5. The template probe proves preservation of thermometer outline, graphics,
   mask data, zones, fixed copper, reference labels, flips, and every router
   input.
6. `PcbRuleProfile`, net widths, fine-pitch target set, clearance groups, R2/R3
   grids, policies, and budgets are explicit and fingerprinted.
7. SEG/control bus groups and allowed order/reversal are declared if order
   conflicts are to affect ranking. Until R4 declarations exist, those metrics
   remain unavailable rather than guessed.
8. Pin escape vectors are explicit or exact-body-derived for the 0.5 mm USB-C,
   DFN, and 0.65 mm TSSOP pads, with ambiguity telemetry.
9. The exact checker aggregates virtual DRC, design checks, connectivity,
   reader equality, and KiCad DRC under a stable checker ID and finding
   fingerprint policy.
10. A fixed pilot budget is reviewed against the 63-part search size. Start with
    a bounded movable subset; never open all translations/rotations/flips at
    once and call budget exhaustion a board failure.

## Unresolved decisions before production code

1. **Exact placement geometry representation.** Recommended: a shared planar
   compound with exact line/arc/circle primitives and bounded polygonization,
   not another placement-only polygon type.
2. **Missing courtyard policy.** Recommended: profile-declared derived offset
   with explicit provenance; do not hard-code 0.25 mm as universally exact.
3. **Body definition.** F.Fab/B.Fab may omit real overhangs and height. Decide
   whether a component-card mechanical envelope can override footprint fab
   geometry before calling body collision exact.
4. **Board cutouts.** `BoardLayout` has no typed cutout field. Recommended: add
   typed polygon cutouts before R3/R5 donut fixtures; do not parse arbitrary raw
   graphics opportunistically.
5. **Opaque graphics authority.** Decide how a generated layout asserts that raw
   graphics contain no Edge.Cuts/keepouts. The assertion must be typed and
   fingerprinted.
6. **Zone geometry.** Current rectangle declarations are not final filled-zone
   polygons. Recommended: retain R3's conservative rectangle treatment and
   avoid using target zones as connectivity.
7. **Terminal escape direction.** Recommended: explicit footprint pin-vector
   metadata wins; exact-body nearest normals are fallback and can be ambiguous.
8. **Counter-based candidate permutation.** Select and pin a small algorithm
   (for example a SHA-256 counter ordering) rather than rely on Python RNG call
   sequence.
9. **Coarse-failure exploration quota.** Calibrate on synthetic false-negative
   fixtures before choosing a default. Keep it explicit and fingerprinted.
10. **Pareto diversity buckets.** Portal-overflow bucket thresholds and flip-set
    diversity need corpus evidence. Defaults must be algorithm policy, not fab
    claims.
11. **Exact checker aggregation.** Decide whether KiCad CLI is one aggregate
    checker or a sequence whose sub-fingerprints are retained. R5 needs one
    coherent final verdict either way.
12. **R4 timing.** R5 may consume `BusGroup` declarations before R4 detailed
    realization exists, but must not imply ordered copper was produced.
13. **3-D dual-side body collision.** Courtyard layers are side-specific, but
    tall through-board/mechanical interference needs z envelopes and assembly
    process data. Keep it unsupported until modeled.
14. **Candidate caching.** Cache keys must include template, profile, target,
    R3/R2 policy/budget, and toolchain fingerprints. Recommended: implement only
    after uncached determinism is proven.

## Recommended implementation order

Implement R5.0 through R5.6 in order. Fidelity and exact legalization precede
candidate generation; candidate generation precedes surrogates; surrogates
precede Pareto selection; and detailed routing precedes exact-check acceptance.
R5.7 is a consumer pilot, not an implementation shortcut.

Do not change an existing placement default, route the thermometer, or claim
placement quality improvement while this document is the only R5 artifact.
