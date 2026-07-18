# Routing and placement research update (2026-07-12)

Status: engineering research memo reconciled into the canonical R1-R7 roadmap in
`docs/routing-placement-plan.md`. The active plan governs implementation order and
acceptance gates; this memo preserves the audit evidence, source review, and
rationale. It does not define a competing sequence.

Non-negotiable constraint: the production design loop remains fully
deterministic. No LLM chooses placements, routes, costs, constraints, or pass
conditions. LLMs may help maintain code and documentation, but generated boards
must be reproducible from declared topology data, rules, and a fixed seed.

## Executive decision

Only Phase 0 of the current routing/placement plan is complete. Phases 1-5 are
largely proposals, not implemented behavior.

The most important roadmap correction is to put **negotiated congestion and
global capacity planning before geometric bus offsets**. The thermometer
failure is a global allocation problem in a narrow, shaped-board corridor. A
leader route plus offset followers can produce orderly geometry only after the
system proves that a corridor has enough capacity, assigns compatible lanes,
and resolves terminal ordering. It cannot by itself discover which earlier net
must move to make a later group feasible.

The corresponding placement correction is to add cheap, deterministic
routability surrogates before expensive detailed routing. Net separation,
crossing/order conflicts, and corridor-capacity overflow should screen many
candidate moves. Exact routing should judge only the most promising legal
candidates.

These conclusions are engineering inferences from the audited code and the
sources below. The sources support the underlying algorithms and reported
results; they do not claim that a particular PCBSmith implementation will route
the thermometer without measurement.

## 1. Implementation audit

Audit baseline: clean worktree at commit `e0e057a` (`Phase 0 COMPLETE:
consolidated cross-book rule table`). The repository collected 435 tests. A
focused set of 56 router, placement, design-check, reader-schematic, and
thermometer tests passed. The environment-gated golden suite was not run during
this audit.

### Phase 0 - complete

The book knowledge base and consolidated rule table exist, with verification
history in the commits immediately preceding this memo. This is the only phase
whose implementation state matches "complete."

### Phase 1 - code not implemented at audit baseline

Evidence:

- `calculators/electronics.py:trace_current_capacity` still uses the legacy
  IPC-2221A external fit while describing it generically as IPC-2221.
- A historical roadmap draft proposed adding the old internal `k=0.024`
  coefficient. The reconciled active plan prohibits that branch. Brooks and
  Adam's IPC-2152 analysis rejects it as a future authority: equivalent internal
  traces can run cooler than external traces because the dielectric spreads heat.
  See `.book-cache/brooks-via-trace/p0062.txt` through `p0071.txt` and the
  explicit mechanism at `p0116.txt`.
- `kicad/virtual_drc.py` still uses one global `CLEARANCE_MM = 0.2` value.
- `kicad/design_checks.py:DesignChecksSpec` has no net-voltage declarations.
- There are no implemented checks or deliberate-violation fixtures for the
  proposed annular-ring minimum, component-body-to-edge distance, or residual
  laminate between holes.
- At the audit baseline, `docs/pcb-design-rules.md` still contained the stale
  pollution-degree wording identified by the IPC-2221B audit. That wording fix is
  now complete: Section 6.4 is a conservative project minimum, not a universal
  reinforced-insulation mandate.

Engineering implication: Phase 1 must establish two deliberately separate
authorities. `FabElectricalSpacingProfile` governs ordinary non-safety
fabrication/electrical spacing. `InsulationProfile` evaluates safety insulation
from the full declared context, including standard edition, RMS/peak and transient
voltage, insulation type, pollution degree, material group/CTI, altitude, coating,
overvoltage category when applicable, and the relevant creepage/clearance path.
A bare-voltage lookup must never produce a safety pass. Trace thermal limits,
widths, holes, annular rings, board-edge requirements, routing legality, virtual
DRC, calculators, and semantic checks must consume the appropriate shared
authority instead of substituting one profile for the other or re-encoding limits.

### Phase 2 - not implemented

`kicad/astar_router.py:route_board` supports width maps, clearance groups,
explicit order, restarts, grid selection, skipped nets, and fine-pitch nets. It
does not accept bus groups, lane assignments, capacity regions, or congestion
history. Routing is sequential per net. When routing fails, the failed net is
promoted to the front and the pass restarts.

That retry scheme can fix first-order ordering mistakes, but it cannot reliably
discover second-order conflicts in which a currently legal, non-failing net
must move because of congestion exposed elsewhere. This limitation is both
visible in the thermometer history and explained by the PathFinder source in
Section 2.

### Phase 3 - only a generic seed exists

`kicad/placement_search.py` already supports deterministic nudge, rotation, and
side-flip moves. It pre-gates courtyard/silkscreen failures, routes surviving
candidates, and ranks them with `layout_score`. The current score prioritizes
hard violations, then trace length plus a via cost, then the parts bounding box.

The proposed compatibility engine is absent: there are no thermal, antenna,
decoupling-loop, oscillator, hot-loop, connector-zone, or ground-return
placement terms.

Two API gaps prevent the existing search from faithfully optimizing the
thermometer:

1. `placement_search.bare_layout` builds a rectangular layout and does not
   preserve the shaped outline, zones, or board graphics.
2. `search_placements` does not forward the thermometer's fine-pitch-net or
   explicit net-order inputs to `route_board`.

The architecture guide says placement search still needs coupling to
routability probes. That wording is stale: the code already performs full
routing probes. What is missing is faithful topology geometry, all routing
options, cheap congestion surrogates, and domain-specific compatibility rules.

### Phase 4 - not implemented

Placement search may toggle a caller-declared flippable reference. It has no
footprint mass/wetted-perimeter data, solder-retention calculation, heavy-part
reflow-side gate, or neighbor-overhang allowance. A caller's `flippable` set is
currently the only physical permission model.

### Phase 5 - thermometer r002 not implemented

`kicad/thermometer_board.py` still contains static `PLACEMENTS` and
`FLIPPED_REFS` and calls the ordinary fine-pitch router. It does not declare bus
groups, use placement search, provide the planned sensor moat, or enforce an
antenna keepout. `generation/thermometer.py` truthfully records the antenna
orientation/copper problem.

The fast thermometer tests cover outline shape, the common scale function,
placement-anchor containment, declarations, and fine-pitch-net membership.
They do not route the board. Their module docstring says the full route lives in
the golden suite, but `tests/golden/test_regenerate_all.py` contains nine
topologies and omits the thermometer. This is stale documentation and leaves
the failed goal without an end-to-end regression.

Anchor containment is also weaker than body/courtyard containment: a rotated
part's anchor can be inside the outline while its body crosses the edge.

### Adjacent architecture debt

Only flyback, servo555, and thermometer have reader-schematic exporters. Seven
of ten authority topologies still lack the reader/netlist-equality path. The
pipeline summary in `docs/architecture.md` overgeneralizes reader coverage,
although its improvement list correctly records the gap.

`src/pcbsmith/cli.py` contains ten near-copy authority commands. Shared board
and reader helpers reduce some duplication, but orchestration, status,
artifacts, and report construction remain repeated. The divider authority
command has the strongest integration coverage; topology-wide descriptor tests
would reduce drift after routing work stabilizes.

## 2. Primary-source algorithm findings

Each subsection separates the source's claim from the implementation inference
for PCBSmith.

### 2.1 Negotiated congestion (PathFinder)

Source: McMurchie and Ebeling, [PathFinder: A Negotiation-Based
Performance-Driven Router for FPGAs](https://janders.eecg.utoronto.ca/1387/readings/pathfinder.pdf).

Sourced claim: routing resources form a graph whose nodes have base, present
congestion, and historical congestion costs. Every global iteration rips up and
reroutes each net. Present cost gradually separates nets sharing a resource;
historical cost makes repeatedly congested resources permanently less
attractive. The paper explicitly demonstrates why obstacle avoidance is
ordering-sensitive and why present cost alone cannot solve second-order
congestion.

Source: [OrthoRoute](https://github.com/bbenchoff/OrthoRoute), an MIT-licensed
Python/KiCad PCB router.

Sourced claim: OrthoRoute applies PathFinder to PCB nodes and edges. Nets are
routed sequentially against a shared congestion map, and repeated passes raise
the price of oversubscribed resources until no node or edge is overused. Its
implementation targets large Manhattan-lattice, multilayer boards and uses GPU
Dijkstra for speed.

PCBSmith inference: the existing grid router is already close enough to host a
small deterministic PathFinder-style outer loop. PCBSmith should borrow the
cost negotiation, not OrthoRoute's GPU and backplane assumptions.

Proposed resource cost, subject to fixture calibration:

```text
resource_cost =
    base_length_cost
    + via_or_bend_cost
    + history_weight * historical_overuse
    + present_weight(pass) * max(0, occupancy + demand - capacity)
```

Implementation requirements:

- Keep the current exact outline, pad, hole, track, and via obstacle model.
- Track occupancy on layer-specific cells and/or edges. A route consumes its
  width-and-clearance halo, not only its centerline cell.
- Temporarily shared resources exist only inside the search model. Never emit
  overlapping copper, and accept a result only when resource overuse is zero
  and the normal exact checks pass.
- Rip up the complete previous tree for a net before rerouting it. Preserve the
  current growing-tree behavior for multi-terminal nets.
- Use fixed iteration and expansion budgets, stable net order, stable priority
  queue tie-breaking, and deterministic arithmetic/rounding.
- Record pass telemetry: total overuse, overused resources, worst resource,
  per-net cost, rip-ups, unresolved nets, and stagnation reason.

Source: official [Freerouting repository](https://github.com/freerouting/freerouting)
and [release history](https://github.com/freerouting/freerouting/releases).

Sourced claim: Freerouting is a GPL-3 DSN/SES PCB autorouter. Recent releases
document deterministic maze-queue tie-breaking, bounded work, repeated batch
passes, score-based stagnation detection, and benchmark fixtures.

PCBSmith inference: Freerouting is most useful first as an external oracle and
comparison tool. Whole-engine integration would add a Java process, format
adapter, and a much larger failure surface. Generated PCBSmith boards can be
exported through DSN, routed externally, then compared on completion, length,
vias, and DRC without making Freerouting part of the authority claim.

### 2.2 Capacity and corridor planning

Source: MIT-licensed [tscircuit capacity autorouter](https://github.com/tscircuit/tscircuit-autorouter)
and its author-maintained [HyperGraph autorouting explanation](https://blog.autorouting.com/p/hypergraph-autorouting).

Sourced claim: the implementation exposes an adaptive capacity depth and a
global-to-detailed routing pipeline. The explanation represents empty regions
and their ports as a smaller graph, prices bottlenecks and crossings globally,
then applies detailed solvers inside smaller regions.

PCBSmith inference: an adaptive hypergraph is not required for the first
version. A coarse capacity map over the existing exact geometry can answer the
key thermometer question: how many width-plus-clearance lanes can cross each
stem section on each layer?

Suggested first implementation:

1. Rasterize or scan-convert free space at a coarser resolution than detailed
   routing, preserving the true shaped outline.
2. Identify portals between coarse regions or evaluate explicit cross-sections.
3. Compute per-layer capacity in lane units for the relevant width/clearance
   class.
4. Route net or bus demands over this capacity graph with negotiated costs.
5. Use the selected coarse corridor as a heuristic or soft keep-in for detailed
   A*; exact detailed routing remains authoritative.

The tscircuit public interchange shown in its repository uses rectangular
obstacles. Directly substituting that engine would discard PCBSmith's custom-pad
and shaped-outline fidelity unless an exact adapter is built.

Source: Lin et al., [A Complete PCB Routing Methodology with Concurrent
Hierarchical Routing](https://doi.org/10.1109/DAC18074.2021.9586143).

Sourced claim: the method separates simultaneous escape, post-escape
refinement, and gridless area routing. Layer assignment and escape ordering are
chosen to support downstream area routing; length matching and differential
pairs are handled throughout the hierarchy.

PCBSmith inference: fine-pitch escape and global area routing should exchange
capacity/order information. Treating completed fine-pitch routes as immutable
obstacles may reserve a globally bad corridor even when every local escape is
legal.

### 2.3 Ordered bus escape and lane assignment

Source: Yan, Ma, and Wong, [Advances in PCB
Routing](https://www.jstage.jst.go.jp/article/imt/7/2/7_535/_pdf).

Sourced claim: PCB routing distinguishes unordered, ordered, and simultaneous
escape. Simultaneous escape must preserve compatible route ordering at the two
boundaries to admit planar routing. Bus-level methods first plan non-overlapping
routing regions; projection/layer planning can produce shorter, straighter,
more balanced escape than forcing all routes through one layer.

Source: Zhang et al., [Layer Assignment and Equal-length Routing for
Disordered Pins in PCB Design](https://www.jstage.jst.go.jp/article/imt/10/3/10_395/_pdf).

Sourced claim: the method uses the longest common subsequence of source and
target pin orders to guide layer assignment, single-commodity flow for base
routes, and later geometric flips for length adjustment.

PCBSmith inference: `BusGroup` needs more structure than an ordered tuple of net
names. A useful deterministic declaration includes:

- member order at both terminal boundaries;
- whether reversal or lane swaps are allowed;
- allowed layers and via policy;
- trace width plus its ordinary fabrication/electrical spacing profile;
- a declared per-bus coupling/timing budget derived from timing, edge rate,
  stackup and return-path geometry, parallel length, and acceptable noise/skew;
- optional, separately justified coherence and length constraints.

The same-bus spacing must not default to a generic manufacturing minimum merely
because the nets share a bundle. 3W spacing, 9.1 coupling, and coherence targets
are advisory/calibration hypotheses until their applicability is declared and
validated for the selected stackup and interface.

The router should then:

1. Detect terminal-order compatibility and crossings.
2. Allocate a corridor whose demand is approximately `members * pitch`.
3. Assign each member a layer/lane through the corridor.
4. Route fine-grid escape pigtails to lane entry/exit ports.
5. Realize legal detailed geometry and validate it through the same obstacle
   kernel.

A leader and geometric followers become a local realization technique inside
an allocated corridor, not the global planning algorithm. Offset polylines can
self-conflict at concave/mitered bends and cannot decide lane swaps or layer
changes. If a member collides, re-plan the group. An individual-A* fallback must
be reported as degraded bundle coherence, not silently accepted as a successful
bus route.

Source: Fang et al., [Obstacle-Aware Length-Matching Routing for Any-Direction
Traces in PCB](https://arxiv.org/abs/2407.19195).

Sourced claim: length matching can be decomposed into assigning non-overlapping
regions and meandering traces inside their regions while preserving existing
any-angle routing.

PCBSmith inference: this is useful for a future electrically justified
length-matching feature, but not the primary thermometer remedy. The HC595
segment/control group may request coherence or matching only when its declared
coupling/timing budget justifies them. Visual neatness alone is not an electrical
constraint.

### 2.4 Routability-aware placement

Source: Cheng, Ho, and Holtz, [Net Separation-Oriented PCB Placement via Margin
Maximization](https://arxiv.org/pdf/2210.14259).

Sourced claim: NS-Place uses an SVM-like maximum-margin net-separation
objective, alternating/coordinate descent for global placement, and MILP
legalization for boundary and overlap constraints. On 14 PCBs evaluated with
Freerouting and KiCad, the authors report improved routed wirelength/via counts
and approximately 79-80% fewer design-rule violations plus unrouted nets versus
manual or wirelength-oriented baselines. Some MILP cases reached a four-hour
limit, and one high-utilization board did not improve.

PCBSmith inference: adopt the cheap objective concepts, not the full optimizer
initially. The current discrete local search can screen moves with:

- pairwise net-separation margin;
- estimated crossing count and incompatible terminal order;
- half-perimeter wirelength as a weak secondary term;
- coarse portal/corridor overflow;
- pin escape-direction alignment;
- exact courtyard/body/outline legality;
- existing semantic penalties and hard gates.

Then run detailed negotiated routing for a small Pareto set. This is more
scalable than routing every random candidate and more truthful than optimizing
wirelength alone.

Every candidate should carry a deterministic routability certificate:

- cheap score components;
- estimated portal demand/capacity and overflow;
- net-order conflicts;
- overuse after a fixed number of negotiated-routing passes;
- unresolved nets, trace length, and via count after a completed probe;
- exact rejection reason when legalization or routing fails.

Semantic layout rules remain topology/card declarations, never inferred by the
optimizer: antenna and thermal zones, decoupling loops, oscillator keepouts,
switching hot loops, connector zoning, return paths, and reflow-side limits.

## 3. Canonical R1-R7 reconciliation

The recommendations below are now folded into `docs/routing-placement-plan.md`.
That plan is the canonical implementation order; this section summarizes the
evidence-backed rationale and does not supersede it.

### R1 - authority, lossless geometry, and deterministic artifacts

Introduce separate `FabElectricalSpacingProfile` and full-context
`InsulationProfile` authorities. Prohibit bare-voltage safety lookup and prohibit
substitution between the profiles. Correct the legacy IPC-2221A trace-fit citation,
keep the external fit only as a labeled interim if needed, and reject the old
`k=0.024` internal branch. Make routing, virtual DRC, design checks, calculators,
and project output consume the appropriate authority. Preserve typed item kind,
complete drill/slot shape, and exact body/courtyard geometry. Replace uncontrolled
`uuid4()` artifact identities with stable deterministic identifiers and prove
byte/hash repeatability.

### R2 - negotiated congestion core

Add resource occupancy, width/clearance halos, present/history costs, complete-net
rip-up, stable tie-breaking, fixed budgets, stagnation detection, typed failures,
and pass telemetry around the existing detailed router. Do not add bus semantics
until canonical congestion fixtures pass.

### R3 - capacity and corridor planning

Add a shaped-outline-aware coarse capacity graph. Estimate per-layer portal
capacity for each rule class and guide detailed routing through selected corridors.
Allow fine-pitch escape and area routing to negotiate instead of freezing locally
valid but globally harmful routes.

### R4 - ordered bus and lane routing

Introduce explicit `BusGroup` terminal order, layers, via policy, widths, lane
policy, and a declared per-bus coupling/timing budget. Derive that budget from
timing, edge rate, stackup/return path, parallel length, and acceptable noise/skew.
Treat 3W, 9.1 coupling, and coherence as advisories/calibration hypotheses unless
applicability is declared. Allocate corridors and lanes before local leader/follower
realization. Keep length matching separate and report degraded/failure results.

### R5 - placement fidelity, surrogates, and certificates

Preserve shaped outlines, zones, graphics, component bodies/courtyards, fine-pitch
declarations, net order, bus groups, options, and selected profiles through every
placement probe. Use exact legalization plus deterministic net-separation, crossing/
order, and capacity-overflow surrogates. Route only the best candidates under a
fixed probe budget and emit a placement certificate explaining legality and scores.

### R6 - semantic and process-scoped gates

Implement thermal, antenna, decoupling, crystal, hot-loop, connector, return-path,
and assembly-retention metrics against the same candidate representation. Select
sensor-moat geometry from the chosen fabrication/assembly profile and pinned device
guidance, then validate it in the built enclosure; 1 mm is not universal. Treat QFN
retention during inverted second reflow as a process-scoped advisory based on paste,
finish, package, oven, orientation, handling, and assembler capability, not a
universal gate.

### R7 - thermometer r002 and authority regression

Use exact antenna geometry, the selected sensor profile, R2-R4 routing, and R5-R6
placement/semantic gates. Add the thermometer to the live golden suite only after
it genuinely passes ERC, reader equality, routing, virtual and semantic checks, and
KiCad DRC. Extract descriptor-driven tooling only after routing correctness is
stable.

## 4. Required deterministic tests

### Authority, geometry, and artifact prerequisites

1. Prove ordinary fabrication/electrical spacing and safety insulation profiles
   cannot be substituted and that voltage alone cannot produce a safety pass.
2. Round-trip typed item kind, circular/oval/slotted drill geometry, and exact
   body/courtyard geometry without scalar or bounding-box loss.
3. Add deliberate Phase 1 violations for annular ring, body-to-edge distance,
   residual laminate, ordinary spacing, and incomplete insulation context.
4. Assert stable identifiers and byte/hash-identical artifacts across repeated runs.

### Negotiated congestion

1. Reproduce first-order and second-order congestion cases from PathFinder in a
   tiny graph/grid. Prove the existing order-promotion scheme fails the
   second-order case and historical cost converges.
2. Verify width/clearance halos consume the correct shared resources.
3. Verify via occupancy/capacity and layer transitions.
4. Assert identical routes, costs, telemetry, and failure reasons across
   repeated runs.
5. Bound expansion count and global passes; test stagnation and budget failure.
6. Require zero final overuse plus exact virtual DRC legality.

### Capacity and buses

1. Shaped-outline bottleneck with a known cut capacity.
2. Ordered endpoints with a legal planar lane assignment.
3. Reversed/disordered endpoints requiring layer allocation or a declared
   failure.
4. Insufficient corridor capacity detected before detailed routing.
5. Obstacle-induced lane re-plan; no silent individual fallback.
6. Concave/mitered follower bends checked by exact geometry.
7. Multi-terminal member and fine-pitch pigtail coverage.
8. Bundle-coherence is tested independently of length matching and never blocks
   routing without a calibrated, declared applicability basis.

### Placement

1. A placement with shorter HPWL but worse capacity overflow loses to a more
   routable placement.
2. Net-separation/crossing score correlates with fixed-budget router overuse on
   a controlled fixture.
3. Rotated courtyard/body containment against a shaped outline, not only anchor
   containment.
4. Placement probes preserve all topology geometry and routing options.
5. Hard semantic rules cannot be traded away by a lower routing cost.
6. Candidate certificates contain every score and rejection reason.

### Thermometer

1. Fast assertion for stem portal demand/capacity before the full route.
2. Bounded negotiated-routing test showing non-increasing best overuse across
   passes with a fixed seed.
3. Full live golden case only after r002 is genuinely routable.
4. Remove or correct the stale claim that the current thermometer route already
   lives in the golden suite.

## 5. External implementations and their role

- [OrthoRoute](https://github.com/bbenchoff/OrthoRoute): study and selectively
  adapt MIT PathFinder cost/occupancy concepts. Its GPU, Manhattan, and
  many-layer assumptions are not PCBSmith requirements.
- [tscircuit autorouter](https://github.com/tscircuit/tscircuit-autorouter):
  study MIT capacity planning, stepwise solver state, telemetry, and visual
  debugging. Do not sacrifice exact footprint/outline geometry to its simpler
  interchange model.
- [tscircuit autorouting benchmark repository](https://github.com/tscircuit/autorouting):
  archived, but useful for seeded synthetic multi-net fixtures and benchmark
  metrics. Translate representative bottlenecks into native PCBSmith tests.
- [Freerouting](https://github.com/freerouting/freerouting): use as a mature
  external routing oracle via DSN/SES and compare completion, length, vias, and
  DRC. Avoid making it an implicit authority source.
- [KiCad PNS router source documentation](https://docs.kicad.org/doxygen/pns__router_8h.html):
  authoritative open-source reference for interactive push-and-shove,
  differential-pair, and tuning geometry. It is not a batch global router and
  does not replace congestion negotiation.

## 6. Success criteria

The research update is successful only when it leads to measurable engineering
gates, not when algorithms merely exist:

- all routing and placement runs are reproducible, with stable identifiers and
  byte/hash-identical artifacts;
- every limit and cost is declared and recorded;
- ordinary fabrication/electrical spacing and safety insulation use separate
  profiles, and no voltage-only query can produce a safety pass;
- typed item kind, complete drill/slot shape, and exact body/courtyard geometry
  survive every relevant handoff;
- the router distinguishes infeasible, budget-exhausted, stagnated, and degraded
  results;
- temporary congestion never becomes accepted copper;
- placement uses the real board geometry, options, selected profiles, and routing
  contract;
- bus coupling/timing, coherence, and length matching remain distinct declared
  concerns; 3W, 9.1 coupling, and coherence are advisory until calibrated;
- sensor-moat geometry is selected-profile and built-enclosure-validation scoped;
- QFN inverted-second-reflow retention is process-scoped advisory evidence, not a
  universal gate;
- the thermometer reaches a clean authority bundle and live golden regression;
- the authority status remains capped at `needs_human_review`.
