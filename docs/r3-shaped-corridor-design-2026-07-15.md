# R3 shaped-corridor capacity-planning design

Date: 2026-07-15  
Scope: implementation design plus a precise R3.1-R3.6 checkpoint. The IR,
quantity ledger, exact/simple KiCad graph adapter, exact typed-cutout path,
negotiated coarse allocator, conservative pairwise demand derivation, and opt-in
soft detailed-route guidance exist. Coarse guidance still does not claim
physical legality; detailed acceptance remains the exact checker's authority.

## Executive decision

R3 should add one deterministic, conservative, two-layer coarse planner between
placement and the existing R2 detailed negotiated router. It should answer a
narrow question: **which shaped-board regions and portals appear to have enough
physical cross-section for the declared target-net demand, and which such
corridors should the detailed router prefer?**

The planner must not answer whether emitted copper is legal. A zero-overflow
corridor allocation means only that all coarse demands fit the planner's
conservative capacity model. It becomes a useful routing result only after R2
materializes detailed tracks and vias with zero fine-resource overuse, and it
becomes accepted only after the supplied exact checker accepts that board.

The smallest sound architecture is:

1. a versioned, engine-neutral corridor graph and result model;
2. a KiCad adapter that conservatively rasterizes the current `BoardLayout`,
   outline, footprint copper and holes, fixed tracks/vias, and declared zones;
3. a variable-capacity, whole-demand negotiated allocator with deterministic
   integer costs and budgets; and
4. an optional **soft** guidance adapter for `route_net_negotiated_candidate`.

Do not reuse R2's `OccupancyLedger` for corridor capacity. R2 resources have
capacity one and set-valued per-net claims. A corridor portal has a physical
span capacity, heterogeneous per-net demand, and potentially more than one lane.
It needs a separate quantity ledger while reusing R2's transaction, present/
history-cost, ordering, telemetry, and fingerprint principles.

R4 bus ordering and lane assignment remain out of scope. R3 represents a bus,
when one is eventually supplied, only as aggregate declared demand; it does not
invent member order, coupling spacing, swaps, or length matching.

## Implementation checkpoint

R3.1 is complete with 21 focused tests after adding canonical terminal-owner
identity to cells. It provides the versioned engine-neutral IR, validation,
canonical semantic fingerprints, and heterogeneous quantity/capacity ledger.
R3.2 is complete with 14 focused tests. Its exact/simple KiCad adapter supports
rectangular and concave outer outlines, conservative full cells, terminal/layer
ownership, orthogonal portals, center via sites, fixed tracks/vias/pads/holes/
zones, and profile-sensitive geometry and capacity. Raw graphics that might
contain Edge.Cuts and target-net zones remain explicit unsupported geometry.

R3.3 is complete. `BoardLayout` owns strictly canonical exact cutout polygons
with containment, boundary, and mutual-intersection validation. The serializer
emits each as a legal closed Edge.Cuts `gr_poly` with a semantic UUID; the
corridor adapter excludes cutouts exactly on both copper layers and from center-
via sites. Empty-default board bytes remain unchanged. The exact segment-to-cell
predicate was corrected to use symmetric segment distance. Bounded approximation
is deferred because no real two-sided uncertainty input carrier exists. R3.3
validation is 38 focused and 62 broader tests.

The empty 10 x 10 mm board on a 2 mm grid still pins graph fingerprint
`18792a2bded9dd69bc83f2bf7f270762696216904542c1e82d5be107e418f79a`
and build-result fingerprint
`6b0b5bab0591a2bb76b07ae99e8c6db0965c4eb4ddd99f1e0dbb60b5a5bff392`.
This is exact graph-construction evidence only, not allocation or routability.

R3.4 is complete. `src/pcbsmith/corridor_allocator.py` implements deterministic,
quantity-aware negotiated allocation of complete multi-terminal coarse trees.
It supports heterogeneous portal quantities and capacity-one via sites,
transactional whole-demand replacement, present/history cost, deterministic
prefix-plus-heuristic ordering, forbidden/allowed/required via policy, zero-work
semantics, fixed expansion/pass/stagnation budgets, and typed failure state.
Per-demand attempt telemetry and pass run-context fingerprints accompany
canonical allocation, ledger, history, pass, and result fingerprints.

The dedicated 19-test allocator matrix includes exact-fit and one-over-demand
bottlenecks, heterogeneous quantities, shared-trunk multi-terminal trees, via
policy, zero-work cases, rollback, reversal determinism, and exact budget
exhaustion. Literal authority fixtures pin first-order convergence in two passes
with expansion counts `15, 16` and overuse `p:1 -> 0`, and a cascading case in
three passes with expansion counts `22, 25, 24` and overuse
`p:1 -> s:1 -> 0`. Their pass/result fingerprints are literal assertions, not
runtime summaries.

R3.5 is complete. `src/pcbsmith/kicad/clearance_domains.py` supplies the one
canonical executable air-clearance-domain builder now shared by R2 and R3. The
corridor adapter includes a pairwise domain only when both endpoints survived
terminal mapping as actual multi-terminal demands, uses the maximum ordinary and
applicable clearance for each net, and retains all applicable domain IDs. Same-
side, absent, and single-terminal counterparts are unaffected. Selectors and
component exemptions cannot shrink un-emitted coarse copper; qualified air-
clearance enters once and creepage is excluded. Exact `Decimal` ceiling replaces
epsilon-biased float rounding so quantum-boundary span cannot be under-reserved.

The historical completed-R3.4 focused checkpoint was 85 passed. Combined R2/R3.5
authority is 104 passed, including corridor-planner 26/26. The pre-R3.6 full
suite was green in 195.4 seconds with ten intentional live/golden skips and only
the known pytest-cache warning; strict mypy was clean over 122 source files and
focused Ruff was clean.

R3.6 is complete. Versioned coarse guide/report artifacts and a versioned KiCad
grid projection represent selected cells, portals, and via sites as transition-
precise soft preferences. A separately accumulated non-negative guidance cost
does not change hard legality, the detailed heuristic, resource claims, or the
pad-stub exemption. `RoutingRunResult` remains schema v2. The opt-in wrapper
reports `ABSENT`, `PLAN_NOT_READY`, `INCOMPLETE_INPUT`, `INCOMPATIBLE`, or
`APPLIED`, falls back to unguided R2 for every non-applied state, and rebuilds
the current layout graph before application so stale guidance is incompatible.
R2 success and exact-check acceptance remain separate.

The broader R2/R3 cluster was 122 passed before final strengthening, and the
focused post-golden R3.6 set is 60 passed. The definitive post-R3.6 full suite
is green in 229 seconds with ten intentional skips and only the known pytest-
cache warning; strict mypy is clean over 124 source files. The real shaped
U-board integration golden pins 29 coarse and 4,876 detailed
expansions, five `F.Cu` segments, no vias, clean virtual DRC and connectivity,
use of the lower bottleneck, and stable graph/plan/guide/run fingerprints. R3.7
is next. `guidance_ready=True` still means only complete zero-overuse coarse
allocation, and guidance failure is not physical unroutability.

## Current contracts that constrain R3

The current code establishes several boundaries that R3 must preserve.

- `BoardLayout.outline` is one outer polygon or `None` for a rectangle, and
  `BoardLayout.cutouts` is a canonical tuple of exact simple internal polygons.
  Concave generated outer outlines and cutouts are scan-converted without convex
  substitution; typed board slots beyond polygons remain a separate concern.
- Footprint and via holes are available through `_collect_items` as exact round
  or oval stadiums, including offset, rotation, plating identity, and front/back
  placement transforms.
- Fixed tracks, vias, pads, and holes are hard geometry in `GridRouter`. Ordinary
  copper clearance, hole-to-copper clearance, copper-to-edge clearance, and
  routing-via geometry come from `PcbRuleProfile`.
- `FabElectricalSpacingProfile.pairwise_clearances` is directional in selector
  metadata but expanded into stable unordered pair-specific domains. The R2
  grid adapter conservatively ignores mask-state, role, and component-exemption
  narrowing during route search because a transition has no sound selector
  proof.
- R2 negotiated claims are layer-specific, include width/clearance halos, use
  complete-net transactional rip-up, fixed integer costs, stable tie-breaking,
  explicit budgets, and zero final overuse as algorithmic success.
- `route_board_negotiated` already separates algorithmic success from an exact
  checker verdict. R3 must not create a second or weaker acceptance path.
- The current placement probe constructs a rectangular `bare_layout` and loses
  outline, zones, graphics, mask apertures, and other template fields. R3 can
  later supply a placement overflow surrogate, but R5 must first repair that
  fidelity boundary. R3 must not silently bless those current probes as shaped-
  board-aware.

## Non-negotiable invariants

1. **Coarse planning is not exact legality.** No corridor type exposes an
   `accepted` property. The strongest R3 outcome is `guidance_ready=True`, which
   means complete coarse allocation with zero coarse overflow.
2. **Hard geometry stays hard in detailed routing.** Corridor guidance may add
   cost outside a preferred corridor; it may not unblock a `GridRouter` cell,
   via site, edge clearance, obstacle, or corner-cut guard.
3. **Default guidance is soft.** A coarse cell approximation can produce false
   negatives. R3 v1 must not prohibit a legal fine-grid route merely because it
   leaves the allocated coarse corridor.
4. **Layer identities never alias.** Front and back cell/portal capacities are
   distinct. They meet only through an explicit through-board via resource.
5. **Capacity and demand use integer units.** Free span rounds down; requested
   span rounds up. Float values are retained only as source/provenance fields.
6. **Fixed geometry and target demand are separate.** Existing generated copper
   for every target net is stripped before graph construction, exactly as in R2.
   Pads and other fixed terminals remain.
7. **A replacement is transactional.** Rip up all old claims for one demand,
   search a complete replacement tree, then commit it; restore on any failure.
8. **No frozen fine phase.** Fine-pitch escape and ordinary area demands share
   the same corridor ledger and can both be selected for whole-demand reroute.
9. **Unsupported geometry is explicit.** Unbounded geometry never becomes an
   empty obstacle or a numeric capacity. It produces a scoped typed issue and,
   when it can affect the planning region, prevents `guidance_ready=True`.
10. **Determinism covers semantics, not runtime.** Graph, demand, pass, result,
    and guidance fingerprints are canonical SHA-256 values. Tests pin those and
    expansion counts, never wall-clock duration.

## Smallest typed API

R3.1's engine-neutral models are committed in `src/pcbsmith/corridor_ir.py`;
R3.2's KiCad graph extraction is committed in
`src/pcbsmith/kicad/corridor_planner.py`; R3.3's exact typed cutouts are committed
across the board model, serializer, and corridor adapter; R3.4's allocator is
implemented in `src/pcbsmith/corridor_allocator.py`; and R3.5's shared domain
builder and conservative demand derivation are implemented in
`src/pcbsmith/kicad/clearance_domains.py` and the corridor adapter. R3.6's
versioned guide/report, KiCad grid projection, detailed cost seam, and opt-in
wrapper are implemented in `src/pcbsmith/corridor_guidance.py`,
`src/pcbsmith/kicad/corridor_guidance.py`,
`src/pcbsmith/kicad/negotiated_grid.py`, and
`src/pcbsmith/kicad/negotiated_board.py`. Contracts for R3.7+ below remain
design proposals. Splitting further before a second backend exists would add
ceremony without preserving another boundary.

### Geometry and graph identity

```python
CorridorLayer = Literal["F.Cu", "B.Cu"]
CorridorCellId = str
CorridorResourceId = str

class CorridorGeometryVerification(StrEnum):
    EXACT = "exact"
    BOUNDED_APPROXIMATION = "bounded_approximation"
    UNSUPPORTED = "unsupported"

class CorridorGeometryIssue(CorridorIrModel):
    source_id: str
    layer: CorridorLayer | None
    verification: CorridorGeometryVerification
    maximum_error_mm: float | None
    reason: str
    affected_cell_ids: tuple[CorridorCellId, ...]

class CorridorCell(CorridorIrModel):
    cell_id: CorridorCellId
    layer: CorridorLayer
    ix: int
    iy: int
    bounds_mm: tuple[float, float, float, float]

class CorridorPortal(CorridorIrModel):
    resource_id: CorridorResourceId
    layer: CorridorLayer
    cell_low: CorridorCellId
    cell_high: CorridorCellId
    orientation: Literal["horizontal_cut", "vertical_cut"]
    guaranteed_span_units: int
    possible_span_units: int
    verification: CorridorGeometryVerification
    maximum_error_mm: float | None

class CorridorViaPortal(CorridorIrModel):
    resource_id: CorridorResourceId
    front_cell_id: CorridorCellId
    back_cell_id: CorridorCellId
    guaranteed_site_count: int
    possible_site_count: int
    candidate_sites_mm: tuple[tuple[float, float], ...]
    verification: CorridorGeometryVerification

class CorridorGraph(CorridorIrModel):
    schema_id: Literal["pcbsmith-corridor-graph"]
    schema_version: Literal[1]
    profile_fingerprint: str
    layout_geometry_fingerprint: str
    coarse_grid_mm: float
    capacity_quantum_mm: float
    cells: tuple[CorridorCell, ...]
    portals: tuple[CorridorPortal, ...]
    via_portals: tuple[CorridorViaPortal, ...]
    issues: tuple[CorridorGeometryIssue, ...]
```

`cell_low`/`cell_high` are lexically canonical, not input-order dependent.
Resource IDs are hashes of schema version, layer, canonical cell IDs, portal
segment, geometry verification/error contract, grid, quantum, and profile
fingerprint. A graph must reject duplicate IDs with unequal content.

`guaranteed_span_units` is the conservative lower capacity used for allocation.
`possible_span_units` is a diagnostic upper envelope after bounded uncertainty;
it must be at least the guaranteed value. R3 v1 must not convert even an upper-
envelope shortage into an exact unroutable claim because coarse topology can
still omit a legal path. It may report `coarse_capacity_insufficient` only.

### Demand and claims

```python
class CorridorDemandKind(StrEnum):
    AREA = "area"
    FINE_ESCAPE = "fine_escape"

class CorridorViaPolicy(StrEnum):
    FORBIDDEN = "forbidden"
    ALLOWED = "allowed"
    REQUIRED = "required"

class CorridorTerminal(CorridorIrModel):
    terminal_id: str
    candidate_cell_ids: tuple[CorridorCellId, ...]

class CorridorNetDemand(CorridorIrModel):
    demand_id: str
    net_name: str
    kind: CorridorDemandKind
    width_mm: float
    allowed_layers: tuple[CorridorLayer, ...]
    via_policy: CorridorViaPolicy
    terminals: tuple[CorridorTerminal, ...]
    ordinary_span_units: int
    effective_clearance_mm: float
    pairwise_domain_ids: tuple[str, ...]

class CorridorResourceClaim(CorridorIrModel):
    resource_id: CorridorResourceId
    demand_units: int

class CorridorAllocation(CorridorIrModel):
    demand_id: str
    net_name: str
    cell_ids: tuple[CorridorCellId, ...]
    portal_claims: tuple[CorridorResourceClaim, ...]
    via_claims: tuple[CorridorResourceClaim, ...]
    base_cost_units: int
    congestion_cost_units: int
```

Terminals are candidate coarse cells touched by exact pad copper after board and
edge constraints. At least two distinct physical terminal identities are needed
for a routable demand; multiple physical pads in one cell remain distinct
terminals. A complete allocation is a connected coarse tree spanning every
terminal, not a two-pin-only path. The final tree has canonical unique edges, so
one demand claims a portal once even if more than one branch reuses the same
tree edge. If a later bus needs multiple lanes, its declared demand units are
larger; R3 must not infer that from a net name.

One planning run permits at most one `CorridorNetDemand` per physical net. A
fine-escape prefix and its area subtree are alternatives/subtrees inside that
one net-owned demand and allocation, not foreign demand records. Terminal-to-
cell attachment is a connectivity hint, not guaranteed escape capacity; the
detailed router must still prove every pad escape.

For the ordinary domain, calculate one lane's conservative span as:

```text
effective_clearance = max(
    profile.fab_spacing.minimum_copper_clearance_mm,
    applicable_conservative_pairwise_clearances,
)
ordinary_span_units = ceil((width_mm + effective_clearance) / quantum_mm)
```

This intentionally reserves one full clearance per lane. At corridor boundaries
it can waste up to one clearance, but it does not overstate capacity. Portal free
span is reduced by the applicable board-edge, fixed-copper, and hole boundary
clearance before rounding down. Track width is accounted for in demand, not
again in portal erosion.

Heterogeneous widths therefore exchange the same physical span units without
pretending they are interchangeable one-lane tokens. The first version does not
perform exact mixed-width lane packing or recover the unused terminal clearance.

### Pairwise domain policy

Pairwise spacing cannot be represented soundly by giving every rule an
independent portal capacity: those domains occupy the same physical cross-
section and independent ledgers would double-count it. Nor can R3 v1 decide
mask-state, copper-role, or component exemption selectors for copper that has
not been emitted.

Use this conservative v1 policy:

1. build the same canonical `PairwiseClearanceDomain` values as R2, including
   qualified air-clearance and caller groups;
2. retain only domains whose two nets are both target demands;
3. for each net, use the maximum clearance of every retained domain involving
   it as `effective_clearance_mm` for the whole coarse allocation;
4. ignore selector and exemption narrowing during planning, exactly as the R2
   net-wide claim adapter does; and
5. record all contributing domain IDs in the demand and fingerprints.

This is pessimistic when the counterpart chooses another corridor or a selector
would exclude emitted copper, but it cannot create false extra capacity. Same-
side nets in a group do not affect each other because domains remain pair-
specific. A future order-aware packing solver may reclaim the pessimism; it is
not needed for the first sound R3.

### Variable-capacity ledger and result

```python
class CorridorCapacityLedger:
    # resource -> capacity; demand -> quantity claims; transactional API
    def claims_for(self, demand_id: str) -> tuple[CorridorResourceClaim, ...]: ...
    def rip_up(self, demand_id: str) -> tuple[CorridorResourceClaim, ...]: ...
    def restore(self, demand_id: str, claims: ...) -> None: ...
    def commit(self, demand_id: str, claims: ...) -> None: ...
    def projected_overuse(self, demand_id: str, claim: ...) -> int: ...
    def overuse(self) -> tuple[ResourceOveruseSummary, ...]: ...

class CorridorFailureReason(StrEnum):
    GEOMETRY_BUDGET = "geometry_budget"
    UNSUPPORTED_GEOMETRY = "unsupported_geometry"
    TERMINAL_UNMAPPED = "terminal_unmapped"
    COARSE_CAPACITY_INSUFFICIENT = "coarse_capacity_insufficient"
    EXPANSION_BUDGET = "expansion_budget"
    PASS_BUDGET = "pass_budget"
    STAGNATION = "stagnation"

class CorridorBudget(CorridorIrModel):
    max_passes: int
    max_expansions: int
    max_expansions_per_demand: int
    max_stagnant_passes: int

class CorridorDemandAttemptTelemetry(CorridorIrModel):
    demand_id: str
    expansion_count: int

class CorridorPassTelemetry(CorridorIrModel):
    pass_index: int
    demand_order: tuple[str, ...]
    demand_attempts: tuple[CorridorDemandAttemptTelemetry, ...]
    expansion_count: int
    unresolved_demand_ids: tuple[str, ...]
    resource_overuse: tuple[ResourceOveruseSummary, ...]
    objective: tuple[int, int, int, int]
    history_fingerprint: str
    ledger_fingerprint: str
    allocation_fingerprint: str
    run_context_fingerprint: str
    present_factor_units: int
    stagnant: bool

class CorridorPlanResult(CorridorIrModel):
    schema_id: Literal["pcbsmith-corridor-plan"]
    schema_version: Literal[1]
    guidance_ready: bool
    failure_reason: CorridorFailureReason | None
    graph_fingerprint: str
    demand_fingerprint: str
    allocations: tuple[CorridorAllocation, ...]
    unresolved_demand_ids: tuple[str, ...]
    resource_overuse: tuple[ResourceOveruseSummary, ...]
    passes: tuple[CorridorPassTelemetry, ...]
    budget: CorridorBudget
```

`ResourceOveruseSummary.resource_kind` is `channel` for same-layer portals and
`via_site` for layer transitions. `capacity_units`, `demand_units`, and
`overuse_units` are physical span quanta for portals and integer site counts for
via resources. A resource never mixes those unit types.

`guidance_ready=True` requires: every demand allocated; no unsupported issue
affecting the planning scope; zero guaranteed-capacity overuse; no failure
reason; and all budgets respected. It does **not** imply
`RoutingRunResult.success`, `RoutingRunResult.accepted`, or DRC acceptance.

R3.4's implemented engine-neutral public entry point is
`negotiate_corridor_allocations(graph, demands, *, demand_order, budget,
cost_policy)`. R3.5 derives conservative demands inside the KiCad corridor graph
adapter. The combined board-level allocation/guidance convenience API below
remains a proposal for R3.7+; R3.6 instead exposes allocation input and the
opt-in detailed-routing wrapper as separate authority steps:

```python
def plan_board_corridors(
    layout: BoardLayout,
    netlist: BoardNetlist,
    demands: Sequence[CorridorNetDemand] | None = None,
    *,
    target_nets: Collection[str] | None = None,
    net_widths: Mapping[str, float] | None = None,
    default_width_mm: float = 0.4,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    clearance_groups: Sequence[ClearanceGroup] = (),
    coarse_grid_mm: float = 2.0,
    capacity_quantum_mm: float = 0.01,
    budget: CorridorBudget = DEFAULT_CORRIDOR_BUDGET,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
) -> CorridorPlanResult: ...
```

When `demands` is absent, the adapter derives one `AREA` demand per selected
routable net from pad terminals, widths, both current copper layers, and allowed
vias. Explicit demand values override derivation and are the only path for
`FINE_ESCAPE`, restricted layers, forbidden/required vias, or aggregate future
bus demand. Unknown target names are ignored only if the current R2 board API
also ignores them; explicit malformed demands are errors.

## Shaped geometry and conservative capacity construction

### Board region

Introduce an adapter-local `BoardRoutingRegion` with one simple outer polygon
and zero or more simple hole polygons. Validate finite vertices, at least three
non-collinear points, no self-intersection, canonical winding, holes strictly
inside the outer boundary, and no touching/intersecting holes. Concave outer and
hole polygons are supported by winding/segment predicates; do not run them
through the convex-only mask `Polygon` type.

For current generated boards:

- `layout.outline` becomes the exact outer polygon;
- otherwise the exact rectangle `(0,0)-(width,height)` is used;
- `layout.cutouts` supplies exact typed internal polygons on both layers and for
  via-site exclusion; none are inferred from `graphics` or silk/mask objects;
- every cutout serializes as a closed Edge.Cuts `gr_poly` with semantic identity;
  and
- footprint NPTH/PTH slots remain hard obstacles, not board-region holes.

Opaque raw graphics that may contain Edge.Cuts are `UNSUPPORTED`, not ignored.
Until layer-aware raw-graphic parsing exists, the adapter should accept an
explicit assertion that graphics are non-Edge.Cuts for generated layouts, or
decline guidance for imported/opaque layouts.

### Coarse cells

Use an axis-aligned grid anchored at board `(0,0)`. A same-layer cell is usable
only when its **closed square** is wholly inside the outer polygon after the
profile's copper-to-edge erosion, wholly outside every cutout after the same
erosion, and disjoint from all fixed hard obstacles after their applicable
inflation. Boundary-touching is blocked. This is deliberately conservative:
partly free cells are unavailable in v1.

Fixed geometry includes:

- foreign and non-target pad/track/via copper, inflated by ordinary or relevant
  net-specific clearance;
- exact round/oval PTH and NPTH hole stadiums, inflated by
  `minimum_hole_to_copper_mm`;
- routing-via keepout using the profile via radius;
- board outer/cutout edges using `minimum_copper_to_edge_mm`;
- declared fixed copper zones as their full rectangular extent; and
- explicit typed keepouts when such a BoardLayout field is later added.

Target routes are stripped. Target pads remain terminals and are not ordinary
blocked cells for their own demand; they are obstacles to other demands. Since
a single shared graph cannot encode that ownership exactly, terminal-containing
cells carry owner metadata and the per-demand search applies the exception.

Zones need special honesty. Current `BoardLayout.zones` are rectangles whose
final KiCad fill can depend on clearances and connectivity. Treating the full
declared rectangle as occupied is a conservative over-approximation suitable
for guidance. A target-net zone is unsupported as a terminal in v1 unless a
typed filled polygon is available; otherwise blocking it may be conservative
but cannot prove connectivity.

### Portals and lane capacity

A same-layer portal exists only between orthogonally adjacent usable cells.
Diagonal cell adjacency is omitted at the coarse level; the fine router may use
diagonals inside or across the chosen region.

The portal cross-section is the shared closed cell edge. Subtract intervals
occupied by conservatively inflated geometry and board/cutout exclusion. Keep
each contiguous free interval as a separate portal resource rather than summing
disconnected openings. Under the v1 whole-cell rule this is normally the entire
shared edge; the interval form preserves correct identity for later boundary-
cell refinement. For an exact free interval of length `L`:

```text
guaranteed_span_units = floor(L / capacity_quantum_mm)
possible_span_units   = ceil(L / capacity_quantum_mm)
```

Bounded approximation remains design-only after R3.3 because no current model
carries a real two-sided uncertainty envelope. When such an input exists, a
maximum Hausdorff/envelope error `e` should erode free space by `e` for the
guaranteed length and dilate it by `e` for the possible length, then round
guaranteed down and possible up. Record `e` on the portal. This interval is
diagnostic; allocation uses only guaranteed units.

Quantization is part of the semantic graph identity. With `q=0.01 mm`, each
portal loses less than `q` guaranteed span and each demand gains less than `q`.
Tests must assert these bounds. Do not choose `q` implicitly from platform float
behavior; convert `Decimal(str(mm))` or equivalent to integer quanta with named
floor/ceiling operations.

### Holes, cutouts, and polygons

- A round hole is an exact disc obstacle; an oval/slot is an exact capsule.
- A board cutout polygon removes space on both copper layers and blocks via
  transitions. Edge clearance is measured from every cutout edge.
- Concave polygons are exact only through simple-polygon point/segment and
  clipping predicates. Never replace them with a convex hull, which can erase a
  real corridor, or a bounding box and then label the result exact.
- A conservative convex hull/bounding box may be used as a bounded or one-sided
  over-approximation, explicitly labeled, when it only removes free space.
- An approximation without a numeric error bound may block a known bounding
  region but cannot contribute a numeric guaranteed capacity outside that
  region unless separation is independently proven. If its location is also
  unknown, the affected layer is unsupported for the run.

### Via transitions

The current exact router supports F.Cu/B.Cu and through vias. R3 v1 should reject
profiles/layouts requiring other routing layers even if
`copper_layer_count > 2`; inventing unnamed inner layers would be false fidelity.

For each front/back cell pair at the same coarse index, enumerate candidate via
centers on the existing detailed routing grid inside the cell. A site is
guaranteed only if the closed via disc and drill clearance satisfy both layer
obstacles, all holes, outer/cutout edge clearance, and the existing no-via-in-
own-pad policy. Canonicalize sites by `(ix, iy)` on the fine grid.

`guaranteed_site_count` is not simply the number of legal sample points because
nearby vias compete for space. In the smallest implementation use capacity one
when the canonical cell-center site is guaranteed legal, otherwise zero. This
is pessimistic but sound and deterministic. A later slice may pack multiple via
sites with a declared via-to-via rule. `possible_site_count` may record bounded
uncertainty but cannot guide a successful allocation.

A via-allowed demand consumes one site on every used layer transition. A
via-forbidden demand cannot traverse such an edge. A via-required demand must
use at least one transition in its complete tree; the constraint is checked on
the allocation, not inferred from endpoints.

## Negotiated corridor allocation

Use the R2 PathFinder shape with quantity-aware costs:

```text
other_demand = ledger.demand_without(resource, current_demand)
projected_demand = other_demand + claim.demand_units
projected_overuse = max(0, projected_demand - capacity[resource])
resource_cost = present_factor * projected_overuse + history[resource]
```

Charge only the incremental quantity not already present in the candidate tree.
For a portal tree edge, that is normally one `ordinary_span_units` claim. For a
via transition it is one site. Base cost is integer coarse distance plus via and
turn costs from `NegotiatedCostPolicy`, scaled explicitly to the coarse grid.

Initial demand order is deterministic: explicit order first, then decreasing
span demand, decreasing terminal count, estimated coarse HPWL, and demand ID.
After a pass, reroute demands touching the most overuse first, with baseline
rank and demand ID as stable ties. The objective remains:

```text
(unresolved_count, total_overuse_units, overused_resource_count, max_overuse)
```

History increases by `history_increment_units * overuse_units`. Present factor
uses the same rational ceiling growth as R2. Stop on zero overuse, typed search
failure, expansion budget, pass budget, or consecutive stagnation budget. Pass
and total fingerprints include graph, demands, policy, costs, selected trees,
ledger quantities, overuse, history, and budgets.

Search connects one terminal at a time to the current tree, using stable
terminal identity, then canonical cell/resource identity for all ties. Candidate
state must include the tree's already-claimed resource quantities so shared
trunks are not charged twice. As in R2, re-rasterize/canonicalize the final tree
before committing it; do not retain claims from pruned search branches.

## Detailed-router guidance

R3.6 implements separate immutable adapter types rather than placing coarse
state in `BoardLayout`. `CorridorRouteGuide` binds the plan, graph, layout-
geometry, per-net allocations, and non-negative off-corridor penalty.
`KiCadGridRouteGuide` then projects allocated cells plus only the selected
portals and selected via sites onto canonical detailed-grid nodes, track
transitions, and via cells. Both artifacts and the final
`CorridorGuidanceReport` are versioned and semantically fingerprinted.

The negotiated grid keeps guidance cost as a separate non-negative score and
telemetry quantity. A listed node pair is preferred only when its exact
transition was selected; via preference likewise requires a selected,
grid-aligned site on both allocated layers. Guidance never subtracts cost or
changes hard blocked maps, the A* heuristic, emitted resource claims, congestion
accounting, or physical acceptance. The legacy pad stub is emitted and claimed
as before but is not charged as an off-guide search transition. A detailed route
may leave the guide and remain a legal R2 candidate.

`RoutingRunResult` remains schema v2, avoiding a semantic/fingerprint migration.
The separate wrapper report binds the supplied plan and graph, the projected
guide when applied, the nested R2 run, and any exact-check result. The opt-in
wrapper uses the dispositions `ABSENT`, `PLAN_NOT_READY`, `INCOMPLETE_INPUT`,
`INCOMPATIBLE`, and `APPLIED`. Every non-applied state runs ordinary unguided R2.
For a ready plan it first rebuilds the current layout graph with the same coarse
parameters and applies guidance only on an exact fingerprint match; stale or
otherwise incompatible input therefore degrades safely to unguided routing.

The board orchestration sequence is:

1. construct/allocate the coarse plan;
2. if guidance is ready, pass per-net guides to R2;
3. if no guide is ready, R2 may still run unguided within its own budget;
4. require zero R2 overuse and complete detailed connectivity;
5. invoke the existing exact checker once on the final materialized board; and
6. report corridor, R2, and exact outcomes separately.

No exact-check result is copied into `CorridorPlanResult`.

## Fine-pitch and ordinary capacity exchange

The existing legacy flow permanently freezes successful fine-grid routes before
ordinary routing. R3 should replace that behavior only in the new negotiated
path.

Represent fine escape and area work in one ledger, but commit them as one
net-owned demand:

- a `FINE_ESCAPE` alternative connects exact fine-pitch terminals to one of
  several declared exchange portals at the boundary of an escape region;
- the area subtree connects the selected exchange endpoints and ordinary
  terminals through the rest of the board; and
- the prefix and area claims are unioned into one `CorridorAllocation` before
  the ledger charges the net. The exchange portal is assigned to exactly one
  side of the seam, so it is not double-counted.

The fine escape solver may generate several deterministic exit alternatives,
each recording exit portal, layer, terminal order, claimed capacity, and a
detailed-grid prefix route. The corridor allocator chooses an alternative. If
area overflow involves its exit, the entire fine escape allocation and prefix
route are eligible for the same whole-net transactional rip-up; locally legal
escape copper is not permanent until the combined run converges. Two planning
records for the same physical net must never compete in the ledger as if they
were foreign nets.

The smallest R3 implementation should first provide the exchange records and
shared ledger with synthetic alternatives. Do not attempt R4 member order or a
general fine-pitch escape algorithm in the same slice. Exact prefix copper still
enters the common R2 fine-resource ledger, and the final board still requires
the exact checker.

## Telemetry and fingerprints

Every versioned model uses canonical JSON (`sort_keys=True`, compact separators,
UTF-8, no NaN/Infinity) and SHA-256. At minimum pin:

- layout geometry fingerprint, including outline/cutouts, fixed geometry source
  IDs, profile, stripped target set, grid, quantum, and approximation contracts;
- graph fingerprint;
- demand fingerprint, including widths, terminals, layers, via policy,
  effective clearance, pairwise domains, and demand kind;
- per-pass history and ledger fingerprints;
- final allocation/result fingerprint; and
- each per-net guide fingerprint.

Pass telemetry records expansion count per demand and total, route order,
selected tree cost, overuse, objective, history/ledger fingerprints, present
factor, stagnation, and geometry issues. The fixed budget covers graph cell/
portal evaluations separately from allocation expansions; otherwise a giant
outline can consume unbounded work before `max_expansions` begins.

Add these explicit budget fields if needed:

```text
max_geometry_cells
max_geometry_portals
max_passes
max_expansions
max_expansions_per_demand
max_stagnant_passes
```

Budget exhaustion never returns a partial plan as guidance-ready. Partial graph
and allocations may be retained for diagnostics with the typed reason.

## Staged implementation and firing tests

Each slice ends with strict mypy, Ruff, focused tests, the full suite, and the
golden authority gate required by the project plan.

### R3.1 - corridor IR and quantity ledger - **COMPLETE**

Implemented: versioned models, validation, canonical identities including cell
terminal owners, and `CorridorCapacityLedger`; 21 focused tests are green.

Tests:

1. mixed portal capacities and heterogeneous quantity claims produce exact
   overuse summaries;
2. a demand's repeated identical claim is canonicalized, while different tree
   edges remain distinct;
3. rip-up/restore/commit is whole-demand transactional;
4. portal and via resources reject mixed unit kinds;
5. input-order reversal produces identical JSON/fingerprints;
6. invalid capacities, negative quantities, duplicate unequal IDs, non-finite
   geometry, and incoherent exact/bounded/unsupported metadata fail closed; and
7. one-less capacity unit produces exactly one overuse unit; and
8. terminal-owner net names are non-empty, canonical, and fingerprinted.

### R3.2 - exact/simple shaped graph adapter - **COMPLETE**

Implemented with 14 focused tests: rectangle/simple concave outer polygons, no
typed board cutouts yet,
exact fixed stadiums/rectangles, full-cell classification, orthogonal portals,
one center via site, and demand terminal mapping.

Fixtures/tests:

1. rectangular empty board with hand-calculated cell/portal counts;
2. thermometer-like narrow stem with a known portal span and capacity for two
   widths/clearances;
3. concave U/C outline where bounding-box routing would create a false portal;
4. outer polygon vertex/winding/input rotation invariance;
5. round NPTH, rotated oval slot, fixed track, via, and rectangular zone each
   reduce only the correct layer/resource capacity;
6. target copper is stripped but target pads remain mapped terminals;
7. front-only SMD obstacle leaves back capacity; THT hole affects both sides;
8. profile changes to copper edge, copper clearance, hole clearance, width, and
   via diameter change the expected graph fingerprint/capacity; and
9. raw possible Edge.Cuts or target-net zone yields a typed unsupported issue,
   never numeric success.

### R3.3 - exact typed cutouts - **COMPLETE**

Implemented exact typed board-cutout polygons, legal closed Edge.Cuts `gr_poly`
serialization with semantic UUIDs, and exact both-layer/corridor-via exclusion.
Validation rejects non-canonical winding/start points, non-finite or degenerate
polygons, self-intersection, boundary contact, containment failure, and mutual
intersection. Empty `cutouts=()` preserves prior serialized bytes. The corrected
symmetric segment-distance predicate prevents endpoint-order-dependent cell
classification. Bounded approximation remains deferred until a real two-sided
uncertainty carrier exists.

Firing validation is 38 focused and 62 broader tests, including donut and
multiple/concave cutouts, exact both-layer and via-site exclusion, serialization
identity/closure, invalid containment/intersection cases, empty-default byte
parity, and segment reversal symmetry.

### R3.4 - negotiated coarse allocation - **COMPLETE**

Implemented complete deterministic multi-terminal coarse trees, quantity-aware
present/history cost, whole-demand transactional reroute, explicit via policies,
zero-work semantics, fixed budgets, stagnation, typed failures, per-demand
telemetry, and run-context/pass/result fingerprints. The dedicated allocator
matrix is 19 focused tests.

Authority fixtures/tests:

1. single bottleneck whose known span fits exactly N equal-width demands;
2. N+1 demands yield deterministic coarse overuse, never exact-unroutable text;
3. heterogeneous fine/ordinary widths share physical span units correctly;
4. first-order and cascading alternatives mirror the R2 graph fixtures but use
   capacity greater than one and quantity demand;
5. every fixed demand order chooses a locally short overloaded portal while
   history converges to a zero-overflow allocation;
6. one-less pass, total/per-demand expansion exhaustion, zero patience, and
   geometry budget exhaustion return the exact typed reason and final state;
7. injected replacement failure restores the old complete tree and quantities;
8. multi-terminal shared trunk claims a portal once; two distinct portal edges
   are both claimed;
9. via-forbidden, via-allowed, and via-required demands behave explicitly; and
10. repeated and reversed-construction runs pin pass/result fingerprints.

### R3.5 - pairwise conservative demand - **COMPLETE**

Implemented the shared R2/R3 canonical air-clearance-domain builder and
conservative demand reduction over only actual multi-terminal demand endpoints.
The maximum ordinary/applicable clearance and every applicable domain ID are
retained. Same-side, absent, and single-terminal counterparts are unaffected;
selectors/exemptions cannot narrow un-emitted copper; qualified air enters once;
creepage is excluded; and exact `Decimal` ceiling prevents epsilon under-
reservation. Combined R2/R3.5 authority is 104 passed and the corridor-planner
set is 26/26.

Authority tests:

1. one pairwise domain increases only its two nets' effective span;
2. two nets on the same side of a group do not affect each other;
3. multiple applicable domains choose the maximum clearance and retain every
   contributing domain ID;
4. mask/role selectors and exemptions are not used to shrink un-emitted coarse
   demand;
5. qualified air-clearance and caller groups reach the planner once each;
6. creepage is absent; and
7. special-clearance pessimism may reject coarse guidance but never blocks an
   unguided exact-router attempt or claims physical unroutability.

### R3.6 - soft R2 guidance and exact authority gate - **COMPLETE**

Implemented versioned coarse-guide/report artifacts, exact KiCad grid
projection, transition-precise selected portal/via preferences, separate
non-negative guidance cost, and the opt-in board wrapper. Tests prove unchanged
hard legality, heuristic, resource claims, and pad-stub exemption; stable
zero-penalty behavior; deterministic preference; legal escape from a blocked
guide; partial-net guide reporting; and unguided fallback for absent, non-ready,
incomplete, mismatched, unsupported, or stale inputs. The wrapper rebuilds the
current-layout graph before applying guidance.

`RoutingRunResult` remains schema v2. Coarse readiness, detailed R2 zero-overuse
success, and exact-check acceptance are reported separately. Missing exact
checking is not accepted, exact rejection preserves algorithmic success, exact
acceptance is the only accepted outcome, and an algorithmic failure never calls
the exact checker.

The broader R2/R3 cluster was 122 passed before final strengthening, and the
focused post-golden R3.6 set is 60 passed. The definitive post-R3.6 full suite
is green in 229 seconds with ten intentional skips and only the known pytest-
cache warning; strict mypy is clean over 124 source files. The real shaped
U-board integration golden pins 29 coarse expansions, 4,876 detailed
expansions, five `F.Cu` segments, no vias, clean virtual DRC and connectivity,
use of the lower bottleneck, and stable graph, plan, projected-guide, and R2-run
fingerprints.

### R3.7 - fine/ordinary exchange seam

Use synthetic escape alternatives before a general escape generator.

Tests:

1. a locally shortest fine escape consumes the only viable area portal;
2. shared negotiation rips it up and selects a longer alternate exit;
3. its detailed prefix claims are also replaced transactionally in R2;
4. freezing the fine escape reproduces the expected coarse overflow/failure;
5. exit layer and via-site demand are accounted together; and
6. no individual fallback is silently labeled a coherent bus or successful
   exchange.

### R3.8 - placement surrogate seam, not full R5

Expose a read-only `CorridorPlanSummary` with total demand, guaranteed capacity,
overflow, unresolved demands, geometry issues, and fingerprint. Do not yet
rewrite the placement search.

The later R5 integration must test that a shorter-HPWL placement with worse
portal overflow ranks behind a longer but capacity-feasible placement, while
preserving the template outline, cutouts, zones, graphics, flips, rotations,
profiles, and every router budget.

## Resolved and unresolved choices

These decisions should remain explicit rather than guessed during coding.

1. **Typed board cutout ownership ? resolved in R3.3.** `BoardLayout.cutouts`
   owns canonical exact simple polygons; opaque graphics are not parsed
   opportunistically.
2. **Opaque graphics declaration.** Generated layouts need a reliable way to
   assert that raw graphics contain no Edge.Cuts. Recommended: a typed graphics
   layer/source model or explicit adapter flag whose value is fingerprinted;
   imported unknown data should remain unsupported.
3. **Zone fidelity.** Full declared rectangles are safely pessimistic but can
   erase useful corridors. Recommended: keep that v1 behavior and add typed
   filled-zone polygons only after KiCad fill parity is available.
4. **Via capacity above one.** No profile field currently declares via-to-via
   spacing. Recommended: center-site capacity one until such a rule is sourced;
   do not derive it from copper clearance without confirming applicability.
5. **Pairwise packing recovery.** Net-wide maximum clearance is conservative but
   can be very pessimistic. Recommended: ship it first; later use order-aware
   portal packing, never independent physical ledgers per pairwise domain.
6. **Capacity quantum.** `0.01 mm` is a reasonable default, not a fabrication
   claim. Recommended: make it an explicit planner parameter included in every
   fingerprint and compare 0.01/0.005 mm on fixtures before freezing a default.
7. **Coarse grid.** `2.0 mm` is an initial work/quality tradeoff, not evidence-
   derived. Recommended: explicit and fingerprinted; later adaptive subdivision
   can refine only boundary/bottleneck cells without changing the IR.
8. **Terminal ownership in shared cells.** Recommended: per-demand cell
   exceptions derived from exact source IDs; never globally unblock a cell
   because one target owns one pad there.
9. **Multi-layer future.** Recommended: type v1 to the two current named layers
   and fail closed for inner-layer routing. Generalize only with stackup and
   via-span models.
10. **Coarse failure use in placement.** A conservative graph can miss legal
    detailed routes. Recommended: treat overflow as a strong ranking/screening
    signal, not a final rejection, until a completeness/upper-bound proof exists.

## Recommended implementation order

R3.1-R3.6 are complete. R3.1-R3.3 establish trustworthy units and geometry;
R3.4 proves quantity-aware negotiation; R3.5 closes profile/pairwise demand
semantics; and R3.6 guides the existing detailed router without weakening its
authority. Implement R3.7 next. R3.8 remains an interface handoff to R5.

Do not start R4 lane ordering, bus coherence, leader/follower offsets, or length
matching in these slices. Also do not make corridor planning the default path
until the R2 board-level adversarial gates required by the R2 design memo and
the R3 shaped bottleneck/exact-check gates above all pass.
