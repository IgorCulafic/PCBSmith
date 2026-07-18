# R2 negotiated-congestion design audit

Date: 2026-07-15  
Scope: originally a read-only audit and implementation design for
`astar_router.py`, `routing_ir.py`, routing tests, and
`docs/routing-placement-plan.md`. The checkpoint below records the subsequently
implemented R2.1-R2.3b slices without rewriting the original design rationale.

## Implementation checkpoint — complete through R2.3b

- **R2.1 complete:** canonical capacity-one resource keys and ledger,
  deterministic overuse/fingerprints, pair-specific clearance domains, exact
  grid-move/via claims, and arbitrary emitted-segment capsule raster claims.
- **R2.2a complete:** the synthetic candidate-graph negotiation kernel passes the
  first- and second-order fixtures with fixed integer present/history costs,
  complete-candidate replacement, budgets, stagnation, typed failures, and
  pinned pass/result fingerprints.
- **R2.2b complete:** the real grid adapter preserves legacy hard geometry while
  adding set-valued congestion-aware complete-net search and reconstructing
  final claims from emitted segments and vias.
- **R2.3a complete:** board orchestration strips target copper once, performs
  transactional whole-net rip-up/restore, updates history and deterministic
  reroute order, enforces pass/net/total/stagnation budgets, emits truthful
  schema-v2 telemetry, requires zero overuse, and keeps the exact-check callback
  separate from algorithmic success.
- **R2.3b complete:** `tests/unit/kicad/test_negotiated_board_maze.py` is a real
  in-memory board-maze proof. Both legacy sequential permutations fail. The
  negotiated route converges in three passes with total overuse `4 -> 5 -> 0`,
  consumes 16,427 expansions, repeats exactly, and pins pass fingerprints
  `6bf59d7fec8031f984f13102bc4a5dd112b53b4dc81c4f212bf13c5fba733a71`,
  `1884e9fd36b5af6a57709cf1311e8a7b31d4ec6c4328618bd2c620a1fa67234b`,
  and `0734b8883000f8c4460be48bdb3e387afd10022bee24a8af28c8bc26fd394161`.
  Its deterministic in-memory geometry checker accepts connected, clear,
  front-layer, via-free copper; this is not a serialized KiCad fixture or an
  exact `kicad-cli` DRC claim.
- **Authority checkpoint:** the negotiated cluster was 66 passed before the maze
  addition and the maze is 3 passed. After the R2.4a and R3.1 additions, the
  latest full suite completed with all collected tests green in 178.4 seconds,
  ten intentional live/golden skips, and only the known pytest-cache permission
  warning. Strict mypy is clean over 118 source files.
- **R2.4 partially complete:** a separate real two-resistor board now pins
  deterministic serialized KiCad bytes with SHA-256
  `e91a7464d702c821f6ac0bb659a30bd39ccecdbe52e79167164650ce907dc628`,
  exercises repository S-expression and placement read-back, and preserves all
  non-route `BoardLayout` fields. Its opt-in exact KiCad 10.0.3 DRC passed
  locally. It is a compact serialization/tool-authority gate, not an
  adversarial negotiation proof. Legacy `route_board` remains unchanged and
  default; a legal-geometry serialized adversarial board, measured performance/
  quality corpus, and deliberate caller/default migration remain open.

## Executive conclusion

The legacy/default router is a deterministic sequential hard-block router with
whole-pass retry and failed-net promotion. Its routing IR adapter accurately
says that it has no negotiated resource accounting: every pass and run emits an
empty `resource_overuse`, every pass is `stagnant=False`, and exact-check status
is `None`. That behavior and honesty remain unchanged.

The implemented R2.1-R2.3b path is a separate negotiated orchestration layer
around a generalized grid search. Fixed board geometry and every pad remain hard
obstacles. Copper generated for the target nets is removed from the hard-
obstacle layout and represented instead by a layer-specific occupancy ledger.
Each net is transactionally ripped up in full, rerouted against present/history
costs, and recommitted. A result is algorithmically successful only when every
net is connected and the final ledger has zero overuse. It is accepted only when
an explicitly supplied exact checker also returns `True`.

Do not migrate production callers or implement later R3/R4 behavior until the
relevant authority gates pass. Both synthetic resource fixtures and one real
in-memory board maze now pass deterministically at zero final overuse. The
separate compact R2.4a board has deterministic serialized KiCad coverage and a
locally passed opt-in KiCad 10.0.3 DRC, but adversarial legal-geometry
serialization, corpus measurement, and caller/default migration remain open.
R3.1's engine-neutral IR and quantity ledger are implemented; R3.2+ and all R4
behavior remain design-only.

## What the legacy/default adapter actually does

| Area | Implemented now | Not implemented now |
|---|---|---|
| Geometry search | Two-layer, 8-direction grid A*, via hops, corner-cut guards, shaped-outline blocking, profile-based hard obstacle inflation, pairwise keepouts, pad source/target handling, smoothing, emission, merge/prune cleanup | No shareable routing resource model and no capacity calculation |
| Other routed nets | Freshly routed segments/vias are appended to `BoardLayout`; the next net sees them as foreign hard obstacles through `_collect_items` | No temporary sharing, demand, capacity, or overuse |
| Retry | When a net fails, the entire pass is discarded and a new pass starts from the original phase layout with that failed net promoted to the front | No selected-net rip-up inside a persistent occupancy state; no history-guided reroute |
| Fine nets | Fine-pitch nets have their own phase and grid and may be reordered within that phase | A successful fine phase is frozen as hard copper before ordinary nets; ordinary congestion cannot rip it up |
| Ordering | Deterministic estimated-span order or explicit order; deterministic A* source and neighbor iteration | No congestion-driven ordering or conflict-set scheduling |
| Budgets | Fixed board expansion, per-net expansion, pass/restart budgets; typed `EXPANSION_BUDGET`, `PASS_BUDGET`, and `UNROUTABLE` outcomes | `max_stagnant_passes` is populated but not enforced; no actual stagnation detection |
| Telemetry | Per-pass/per-net expansion, segments, vias, length, unresolved nets, deterministic semantic fingerprint | `resource_overuse=()`, `stagnant=False`, no present/history cost telemetry |
| Acceptance | `success=True` means all sequential attempts completed; `exact_check_accepted=None`, therefore `accepted=False` | No exact post-route checker and no accepted route claim |

The retry behavior is broader than single-net rerouting because it throws away
all routes from the failed pass, but it is still ordering search, not negotiated
congestion. Each attempt treats earlier routes as forbidden geometry. Therefore
it cannot escape a case where whichever net goes first chooses a locally shortest
route that blocks every hard-legal route of the second net.

## Non-negotiable invariants

1. Static board geometry, board edge, pads, holes, fixed copper, and non-target
   nets remain hard obstacles. Negotiation applies only to routes owned by the
   target routing run.
2. Occupancy is layer-specific. F.Cu and B.Cu resources never alias except at an
   explicit via-site resource.
3. A net's demand is set-valued per resource: overlapping branches of one net do
   not consume capacity twice.
4. Track and via claims include physical width plus one half of the applicable
   symmetric clearance. Two nets' expanded claims then intersect at exactly
   `radius_a + radius_b + clearance` in the raster model.
5. Same-net copper may reuse its own claims without present/history penalty.
6. A route replacement is transactional: remove all old claims for the net,
   search and emit the complete multi-pad tree, then either commit the complete
   replacement or restore the old route and claims.
7. Tie-breaking, route order, resource IDs, halo enumeration, history update,
   and telemetry ordering are stable.
8. Fixed expansion/pass/stagnation budgets are checked before work that would
   exceed them, and all completed work is reported.
9. Temporary overuse exists only in the search model. Materialized success
   requires no unresolved nets and zero resource overuse.
10. Algorithmic success and exact-check acceptance stay separate. With no exact
    checker, `exact_check_accepted=None` and `accepted=False` even at zero overuse.

## Concrete internal API

Keep these models internal to `pcbsmith.kicad` initially. Do not put KiCad types
into `routing_ir.py`.

```python
LayerName = Literal["F.Cu", "B.Cu"]
ResourceKind = Literal["cell", "edge", "crossing", "via_site"]

@dataclass(frozen=True, order=True)
class RoutingResourceKey:
    domain_id: str          # ordinary, or rule + canonical affected net pair
    layer: LayerName | Literal["through"]
    kind: ResourceKind
    ix0: int
    iy0: int
    ix1: int = 0            # canonical normalized endpoint for edge resources
    iy1: int = 0

@dataclass(frozen=True)
class NetResourceClaims:
    net_name: str
    resources: frozenset[RoutingResourceKey]

@dataclass(frozen=True)
class NegotiatedRoute:
    result: RouteResult
    claims: NetResourceClaims
    base_cost_units: int
    congestion_cost_units: int

@dataclass(frozen=True)
class NegotiatedCostPolicy:
    length_units_per_grid: int
    diagonal_length_units: int
    via_cost_units: int
    turn_cost_units: int
    present_factor_units: int
    present_growth_numerator: int
    present_growth_denominator: int
    history_increment_units: int

class OccupancyLedger:
    def rip_up(self, net_name: str) -> NetResourceClaims: ...
    def restore(self, claims: NetResourceClaims) -> None: ...
    def commit(self, claims: NetResourceClaims) -> None: ...
    def demand_without(self, resource: RoutingResourceKey,
                       net_name: str) -> int: ...
    def overuse(self) -> tuple[ResourceOveruseSummary, ...]: ...
    def semantic_fingerprint(self) -> str: ...
```

`OccupancyLedger` should store both `net -> frozenset[resource]` and
`resource -> sorted set/net set`. Capacity is one for the R2 copper resources.
`demand_units` is the number of distinct nets claiming the resource and
`overuse_units=max(0, demand-capacity)`. Emit only positively overused resources
to keep telemetry bounded, sorted by canonical `resource_id`.

Add a new API first; do not silently change every existing caller:

```python
def route_board_negotiated(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    ...existing widths/profile/order/grid arguments...,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    max_passes: int,
    max_expansions: int,
    max_expansions_per_net: int,
    max_stagnant_passes: int,
    exact_checker: ExactRouteChecker | None = None,
) -> BoardRouteResult: ...

@dataclass(frozen=True)
class ExactRouteCheckResult:
    accepted: bool
    checker_id: str
    finding_fingerprints: tuple[str, ...] = ()

ExactRouteChecker = Callable[
    [BoardLayout, BoardNetlist], ExactRouteCheckResult
]
```

The checker callback keeps the search reusable and allows a fast virtual exact-
geometry checker in unit tests and a stronger pipeline checker in golden runs.
The checker ID and finding fingerprints should eventually be durable IR data;
do not infer acceptance merely because emission completed.

## Resource construction

### Static versus negotiable geometry

Before a run, strip segments and vias for every target net from the base layout.
Build the current profile-aware hard maps from that stripped layout. Pads are
not stripped because they come from the netlist/footprints and are fixed. This
prevents old generated copper from being counted both as a hard obstacle and as
negotiated demand.

The present `GridRouter` mixes hard-map construction and search. Split only the
minimum seam:

```python
class GridSearchEnvironment:
    blocked_by_width: Mapping[WidthClass, Mapping[LayerName, frozenset[Cell]]]
    via_blocked_by_size: Mapping[ViaClass, frozenset[Cell]]
    own_pad_nodes: Mapping[str, tuple[PadNodeSet, ...]]

def search_complete_net(
    environment: GridSearchEnvironment,
    net_name: str,
    ledger: OccupancyLedger,
    history: Mapping[RoutingResourceKey, int],
    present_factor_units: int,
    expansion_budget: int,
) -> NegotiatedRoute: ...
```

Width-dependent hard maps may remain cached separately at first. Prematurely
building a multi-width universal map risks changing current legality.

### Cell, edge, crossing, and via claims

For every emitted grid move, deterministically enumerate:

- layer cell resources intersected by the move's capsule halo;
- normalized layer edge resources traversed by the centerline;
- for diagonal moves, a canonical square-crossing resource so the two opposite
  diagonals through one grid square conflict even though they share no endpoint;
- for a via, a `through/via_site` resource plus front/back cell halos using the
  configured via radius.

Use a geometric supercover, not center-sample-only marking. A track halo radius
for ordinary symmetric clearance is `track_width/2 + clearance/2`; a via halo is
`via_diameter/2 + clearance/2`. Enumerate candidate cells/edges from the exact
capsule bounding box and retain those whose cell/edge geometry intersects the
capsule. Canonical edge endpoints are lexicographically sorted.

Ordinary spacing uses domain `ordinary`. Expand each declared pairwise rule into
canonical unordered affected-net pairs after exemptions. Each pair gets a stable
domain derived from the rule/profile identity plus those two net names, and only
those two nets add claims expanded by half that pairwise gap in that domain. A
single group-level domain would be wrong because two nets on the same side would
spuriously consume each other's special-clearance capacity. Pair-specific domains
avoid that error, avoid applying the largest special clearance to unrelated nets,
and avoid the false assumption that one net has one universal clearance radius.

When adapting to `ResourceOveruseSummary`, map internal cell resources to
`resource_kind="region"`, normalized moves and diagonal crossings to `"edge"`,
and via sites to `"via_site"`; keep the exact internal kind in the canonical
`resource_id`.

## Search cost and deterministic tie-breaking

Use fixed integer cost units. Floats are unnecessary for the negotiated term and
make equality/tie behavior harder to audit. An orthogonal move can be 1000 units,
a diagonal 1414, with via and turn values converted once from existing constants.

For a candidate transition, first derive the *new* resource claims it adds to
the current net tree. For each new resource `r`:

```text
other_demand = ledger.demand_without(r, current_net)
projected_overuse = max(0, other_demand + 1 - capacity[r])
resource_cost = present_factor * projected_overuse + history[r]
```

The move cost is base geometry cost plus the sum of those resource costs. Do not
charge resources already claimed by the same candidate tree. History is updated
only after a complete pass:

```text
history[r] += history_increment * overuse_units[r]
```

Present factor changes only at a pass boundary using a rational integer update;
record the effective value per pass when the IR grows that field.

Heap keys should be full deterministic tuples, for example:

```text
(f_total, g_congestion, via_count, turn_count, g_base,
 layer, ix, iy, incoming_dx, incoming_dy)
```

Sort source nodes and use one fixed neighbor sequence. Replace a predecessor only
on strict improvement of the complete cost tuple. An insertion counter may remain
as the final key but must never be the first distinction between semantically
different states.

## Pass algorithm

1. Determine target nets and a stable baseline order exactly once.
2. Strip all target routes, build hard environments, initialize empty ledger,
   history, and route map.
3. Initial pass: route every net against static obstacles while allowing claims
   already used by another target net. Commit each connected complete-net route.
   A search failure here is `UNROUTABLE` because other target routes are not hard
   obstacles.
4. Summarize unresolved nets and overuse. If both are zero, materialize the board
   and invoke the exact checker if supplied.
5. Otherwise increment history for overused resources. For the next pass, use a
   deterministic order such as descending overuse touched by the net, then
   baseline rank, then net name.
6. For each net, transactionally rip up all of its branches/vias/claims, search a
   complete replacement against the remaining ledger, then commit it. On search
   failure or expansion exhaustion restore the previous complete route and claims
   before producing terminal telemetry.
7. At pass end, update overuse, objective, history, and stagnation state. Repeat
   only within fixed pass, per-net expansion, and total expansion budgets.

Do not retain the present `fine` phase as permanently frozen copper in negotiated
mode. Fine-grid escape may use a distinct grid/environment, but its complete-net
claims must enter the common ledger and be eligible for whole-net rip-up until
R3 introduces explicit capacity/order exchange.

## Stagnation and terminal reason precedence

After each pass compute this deterministic objective:

```text
(unresolved_net_count, total_overuse_units,
 overused_resource_count, maximum_single_resource_overuse)
```

The first complete pass establishes the best objective and is not stagnant.
Later passes are `stagnant=True` unless they strictly improve the best objective;
reset the consecutive count on improvement. A changed occupancy fingerprint with
the same objective is still non-improvement: bounded patience permits such moves,
while history prevents silent endless oscillation.

Stop when the fixed consecutive-stagnant allowance is consumed. Because the IR
allows `max_stagnant_passes=0`, define zero as no reroute patience: after an
overused initial pass return `OVERUSE_REMAINING` without executing an unreportable
stagnant pass. For positive values, the terminal stagnant pass is recorded and
the run fails with `STAGNATION` when the count reaches the allowance.

Terminal precedence should be deterministic:

1. `EXPANSION_BUDGET` when the next expansion cannot be taken;
2. `UNROUTABLE` when a complete net has no path through static geometry;
3. `STAGNATION` when patience is consumed;
4. `PASS_BUDGET` when another pass is required but unavailable;
5. `OVERUSE_REMAINING` only for an explicit zero-patience/diagnostic stop that
   did not consume another pass.

The final pass overuse must exactly equal run-level overuse, as schema v2 already
requires.

## Routing IR and acceptance semantics

Schema v2 is sufficient for the first algorithmic slice:

- `NetRoutingTelemetry.routed=True` means a complete connected candidate was
  found; it may still participate in temporary pass overuse.
- Populate pass and final `ResourceOveruseSummary` from the ledger.
- Set `stagnant` from the rule above.
- Keep every net-level `exact_check_accepted=None`; exact checking is a board/run
  decision, not a fabricated per-net attempt.
- Set run `success=True` only for connected routes with zero overuse.
- If no checker is supplied: `exact_check_accepted=None`, `accepted=False`.
- If checker accepts: `exact_check_accepted=True`, `accepted=True`.
- If checker rejects a zero-overuse candidate under schema v2: preserve
  algorithmic `success=True`, set `exact_check_accepted=False`, leave the
  algorithmic `failure_reason=None`, and therefore `accepted=False`.

There is a real v2 modeling limitation: `EXACT_CHECK_REJECTION` is represented as
a net-attempt failure and the run validator requires `success=False`, while the
documented meaning of `success` is algorithmic completion independent of exact
acceptance. Do not work around this with a fake failed net. Before supporting
exact-rejection-driven reroute, introduce schema v3 with run/pass-level exact
check telemetry and a separate acceptance rejection reason, while retaining the
meaning of `success` and `accepted`.

Useful v3 additions, but not prerequisites for the core search, are
`occupancy_fingerprint`, effective present/history factors,
`congestion_cost_units`, exact checker ID/finding fingerprints, and a named
`reroute_pass_count` instead of overloading legacy `restart_count`.

## Adversarial fixtures that reordering cannot solve

Start with tiny synthetic resource-graph fixtures. They isolate negotiation from
PCB raster geometry and give a mathematical proof that a retry-by-order adapter
cannot pass. Each candidate path has a base cost and a resource set. Capacity is
one for every resource. Use a history increment greater than the three-unit
short/alternate cost difference in these fixtures.

### First-order fixture: crossed alternatives

File proposal: `tests/fixtures/routing/first_order_crossed_alternatives.json`

| Net | Locally shortest candidate | Alternate candidate |
|---|---|---|
| A | cost 2, `{p, q}` | cost 5, `{r}` |
| B | cost 2, `{p, r}` | cost 5, `{q}` |

Proof against reordering:

- A first chooses `{p,q}`. Both B candidates intersect it (`p` or `q`).
- B first chooses `{p,r}`. Both A candidates intersect it (`p` or `r`).
- Therefore neither of the two sequential orders can complete with hard blocks.
- The zero-overuse solution is A alternate `{r}`, B alternate `{q}`.

A negotiated run may initially overuse `p`; history then makes a locally longer
choice preferable, moves the conflict to `r` or `q`, and the next whole-net
reroute reaches the disjoint alternate pair. Assert exact pass fingerprints,
not runtime.

### Second-order fixture: cascading conflict

File proposal: `tests/fixtures/routing/second_order_cascade.json`

| Net | Locally shortest candidate | Alternate candidate |
|---|---|---|
| A | cost 2, `{p, q}` | cost 5, `{r}` |
| B | cost 2, `{p, r}` | cost 5, `{q, s}` |
| C | cost 2, `{s, t}` | cost 5, `{u}` |

The A/B subproblem already proves that every sequential permutation fails:
whichever of A or B appears first chooses its shortest candidate and blocks both
candidates of the other; inserting C anywhere cannot repair that. The unique
listed zero-overuse assignment is A alternate `{r}`, B alternate `{q,s}`, C
alternate `{u}`. Resolving the first-order A/B conflict moves demand onto `s`,
which then requires the second-order C rip-up. This catches implementations that
stop after one successful conflict relocation or update history only for the
first conflict set.

For both graph fixtures assert:

- legacy hard-block simulation fails for every net-order permutation;
- negotiated routing reaches zero overuse within fixed budgets;
- every committed route is a whole candidate, never a mix of old/new claims;
- history and pass fingerprints are byte-stable across repeated runs;
- one-less pass budget gives the expected typed terminal failure and exact final
  overuse summary;
- reversing input dictionary/list construction does not change the result.

The implemented R2.3b integration gate realizes the first-order ordering trap as
a real in-memory board maze with fixed copper walls, exact pads, and one
available routing layer. It is an integration gate, not a substitute for the
synthetic graph proof. Its tests assert:

- current `route_board` fails for every explicit `net_order` permutation;
- `route_board_negotiated` has zero final overuse;
- the selected deterministic in-memory exact geometry checker accepts the
  materialized copper;
- exact checker disabled yields algorithmic success but `accepted=False`;
- exact checker enabled and accepting yields `accepted=True`;
- hashes, segments, vias, pass telemetry, and expansion counts repeat exactly.

The committed test pins its dimensions, 2.0 mm grid, 0.2 mm track width, wall
geometry, terminal pad coordinates, one-layer restriction, cost policy, exact
checker identity, pass fingerprints, overuse sequence, expansion count, and
route lengths. It remains an in-memory proof. R2.4a's separate compact real
board supplies serialization/read-back/KiCad authority without claiming to
serialize this adversarial maze; a legal-geometry serialized adversarial board
remains R2.4 work.

## Smallest staged implementation

### R2.1 — ledger and claims, no orchestration — **COMPLETE**

1. Add canonical resource keys, occupancy ledger, resource IDs, overuse summary,
   and deterministic fingerprint.
2. Add capsule-supercover claims for orthogonal/diagonal edges and via sites,
   including diagonal-crossing collision tests, layers, widths, and clearances.
3. Add pairwise clearance-domain tests and same-net claim deduplication.
4. Add the two synthetic fixture files and prove every hard-block ordering fails.

### R2.2 — congestion-aware complete-net search — **COMPLETE**

R2.2a is the synthetic candidate-graph kernel; R2.2b is the real grid-search
adapter. Both are implemented and covered by deterministic fixtures.

1. Extract the minimal static environment/search seam from `GridRouter` while
   keeping legacy `route_net` behavior and tests unchanged.
2. Add integer present/history move costs and stable full-key tie-breaking.
3. Return a complete `NegotiatedRoute` with claims; test transactional whole-net
   rip-up/restore and per-attempt expansion caps.
4. Make both synthetic fixtures converge under fixed explicit policies.

### R2.3 — board orchestration and telemetry — **COMPLETE through R2.3b**

R2.3a is board orchestration/telemetry/exact-callback separation. R2.3b is the
real in-memory maze proof described above.

1. Add `route_board_negotiated`; keep legacy `route_board` during migration.
2. Implement pass history, stable conflict ordering, stagnation, total/pass/net
   budgets, typed terminal precedence, and truthful schema-v2 telemetry.
3. Add the real in-memory first-order board maze and exact checker callback;
   retain serialized/expanded golden-board authority for R2.4.
4. Verify zero overuse before materialization and preserve exact acceptance split.

### R2.4 — migration and authority gates — **PARTIALLY COMPLETE**

R2.4a adds a separate real two-resistor negotiated board with deterministic
serialized bytes, pinned SHA-256
`e91a7464d702c821f6ac0bb659a30bd39ccecdbe52e79167164650ce907dc628`,
repository read-back checks, and preservation of every non-route `BoardLayout`
field. Its version-aware opt-in live gate passed `kicad-cli pcb drc` locally on
KiCad 10.0.3. This is intentionally not the adversarial R2.3b maze; the precise
serialization gap is recorded in `docs/r2-kicad-golden-gap-2026-07-15.md`.

1. Run existing A*, flyback, servo, QFN, virtual DRC, strict typing, and golden
   suites without changing legacy expected outputs unintentionally.
2. Compare negotiated and legacy results on boards that need no negotiation; do
   not claim better performance, completion, length, or via count without corpus
   measurements.
3. Migrate callers deliberately, using `.accepted` where an accepted-board claim
   is required rather than legacy `.failed == ()`.
4. Only after exact rejection needs to drive rerouting, design and migrate routing
   IR schema v3 instead of corrupting v2 semantics.

## Explicit non-goals for R2

- No shaped-corridor or portal capacity graph (R3).
- No bus order, lane, skew, coupling, or timing semantics (R4).
- No placement optimization (R5).
- No claim that integer resource overuse is a substitute for exact geometry.
- No runtime, completion-rate, route-quality, or superiority claim until measured
  on a pinned board corpus with deterministic settings.
- No silent fallback to sequential hard blocking presented as negotiated success.

R3 and R4 have design records in
`docs/r3-shaped-corridor-design-2026-07-15.md` and
`docs/r4-ordered-bus-design-2026-07-15.md`. R3.1's engine-neutral IR, canonical
identities, validation, and quantity ledger are implemented with 20 focused
tests. R3.2+ and all R4 capability remain design-only.
