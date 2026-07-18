# Circuit-intelligence root review supplement 5 — 2026-07-17

This supplement records only slices independently reviewed on the combined
worktree after full filesystem access was restored. It does not close the whole
R3-R7 roadmap.

## Accepted: replay-checked R3.7 preparation to R2 execution

`corridor_exchange_preparation.py` now retains and exactly replays the complete
layout, netlist, graph, exchange plan, selected prefixes, projected soft guides,
profile, widths, clearance groups, and preparation controls. The companion
`corridor_exchange_execution.py` accepts only an `APPLIED` preparation and
executes ordinary R2 once per semantic evaluation. It has no unguided fallback
and makes no exact-check claim.

The execution envelope retains the complete preparation, deterministic R2
policy, materialized board result, run telemetry, and full-result fingerprints.
Its validator reruns R2 and requires exact typed equality. A firing fixture uses
the real R2 board orchestrator with a deterministic lower-level candidate seam;
the resulting route must retain the selected alternative and prefix
fingerprint. Focused execution tests (16) and the combined preparation,
execution, and legacy exchange-routing cluster (52 after the real-R2 fixture)
are green with warnings as errors. Focused Ruff and strict production mypy are
green.

Limitations: exact checking remains the strengthened R2 boundary rather than a
callback serialized inside the deterministic execution policy. The old
convenience wrapper still exists for compatibility; the replay-bound executor
is the authoritative opt-in path.

## Accepted: reconstructible R4 atomic transaction evidence

`BusRouteStateSnapshot` retains every route and every occupancy claim, including
foreign nets, in canonical order. It reconstructs a fresh route map and ledger,
recomputes both fingerprints, and rejects duplicate, missing, foreign-owned,
geometry-owner, route/claim, nested-value, and stale-fingerprint tampering.

`BusRouteTransactionTelemetry` schema version 2 retains complete before and
after snapshots. Its legacy fingerprint fields must equal those snapshots, and
rollback requires equality of the full reconstructible state rather than hash
equality alone. Existing transaction behavior is unchanged. The reviewed
transaction suite has 22 focused tests; its adjacent candidate and checked
commit clusters are green.

## Accepted: R4 exact checked-commit authority

The one-shot checked coordinator now passes detached board and route-map inputs
to materialization and detached board/netlist inputs to the exact checker.
Mutation checks run on normal, exceptional, wrong-type, and invalid-report
paths and cover both detached objects and the caller's originals. Canonical
materialization equality remains mandatory.

`BusCheckedCommitResult` schema version 2 retains the exact materialized
`BoardLayout`, checked `BoardNetlist`, canonical report, and
`ExactRouteCheckEvidence` for accepted and rejected checks. The validator
recomputes the evidence from those complete values. Candidate failure, missing
checker, exact rejection, exact acceptance, rollback, and algorithmic routing
remain distinct. The 52 focused tests and the 130-test board-serialization,
R2, candidate, transaction, and checked-commit cluster are green; Ruff and
strict production mypy are green.

Limitations: this coordinator remains replacement-only, one-shot, and does not
schedule or retry. Exact acceptance is not implied by algorithmic success or by
transaction commit.

## Accepted: replay-bound candidate-to-transaction bridge

`bus_candidate_transaction.py` adds an opt-in authority path without changing
the general transaction primitive. `ReplayBoundBusRouteBundle` retains the
complete escape replay and proves that its successful nested candidate, bundle,
member/net mapping, certified prefixes, prefix alternative IDs, and prefix
fingerprints are identical. `ReplayBoundBusTransactionResult` binds that
authority to complete committed before/after transaction snapshots.

Root review strengthened the fixture so the transaction replaces distinct old
routes instead of recommitting the same bundle. The focused and adjacent
escape-replay/transaction cluster has 60 green tests; Ruff and strict production
mypy are green.

Limitations: transaction commitment by itself is not exact board acceptance.

## Accepted: replay-bound candidate through exact checked commit

`bus_replay_checked_commit.py` closes the opt-in R4 authority chain without
changing the legacy coordinator. The bridge reconstructs the complete escape
replay authority, supplies only its retained static layout, netlist, bus,
allocation, and candidate to the strengthened one-shot checked transaction,
and verifies that stripped coordinator occupancy exactly equals replay initial
occupancy before releasing the candidate. Its result retains the complete
replay authority and the ordinary accepted, rejected, or checker-missing exact
result without redefining those dispositions.

Root source review and an independent 97-test replay/candidate/transaction/
checked-commit gate are green; Ruff and strict production mypy are green.

Limitations: the bridge is still replacement-only and one-shot. A missing
checker and an exact rejection remain noncommitting outcomes; replay success
never implies exact acceptance.

The replay-bound escape gate now also has a successful certified cross-layer
fixture. One member consumes the retained transition-via fragment while the
other retains its same-layer trunk; the real candidate succeeds, reversed
set-like terminal input is identical, JSON reconstruction replays exactly, and
the caller ledger remains unchanged. The 76-test transition/escape/replay/
candidate cluster is green with warnings as errors; focused Ruff is green.

## Accepted: R4 physical-swap declaration and global via feasibility

`kicad/bus_physical_swap.py` adds the fail-closed authority foundation for one
semantic adjacent-swap event. A `CertifiedBusSwapRegion` reconstructs and
cross-binds the neutral board/netlist snapshots, complete bus, capacity
certificate, exact semantic allocation replay, certified lane registry, rule
profile, swap event, two-layer keep-in graph, explicit via cells, member portal
identities, and physical policy. It deliberately contains no carrier, copper,
claims, or physical-success field. Opaque footprint obstacles, raw graphics,
and unresolved zone fill are rejected rather than inferred.

Root review caught and corrected initially event-local via accounting. The
accepted validator uses deterministic exact dynamic programming over the full
ordered event set to prove that some bridge-member assignment satisfies
cumulative physical, semantic-plus-physical, per-member, and final-spread
limits in both the physical policy and base bus via policy. A five-event case
that is locally feasible but globally impossible now fails. Equality and
one-less limits are covered independently. The root 99-test region/allocator/
geometry gate is green; Ruff and strict production mypy are green.

Limitations: this is only declaration/search-space authority. Multi-event plans,
prefix composition, and atomic exact commit remain separate work.

## Accepted: exact replay-bound R4 physical-swap carrier

`kicad/bus_swap_carrier.py` realizes one certified adjacent-swap event on the
declaration's explicit two-layer graph. It deterministically enumerates both
bridge-member choices and ordered via-cell pairs, emits exactly two vias on the
bridge member and none on the stationary member, reconstructs ordinary and
pairwise R2 claims, checks the certified static occupancy, and retains every
candidate attempt and typed failure. Legal-candidate ordering uses the retained
algebraic grid-length witness rather than a floating-point comparison.

Root review rejected the initial floating-point keep-in margin. The accepted
carrier retains a canonical per-track-capsule and per-via-circle witness with an
exact rational squared distance to the nearest polygon boundary, the exact
required squared radius, the selected boundary-edge identity, and the exact
inside/disposition result. Equality and one-micrometre-above/below cases fire for
both primitive kinds; evidence and replay tampering fail reconstruction. The
root 194-test carrier/declaration/replay/transaction/allocator/geometry gate is
green; Ruff and strict production mypy are green.

Limitations: one carrier covers exactly one semantic event. The separate plan
below can account for several carriers, but neither slice yet splices complete
routed member prefixes, mutates a live route transaction, runs the exact
checker, or claims rendered-board authority.

## Accepted: ordered multi-event R4 physical-swap accounting plan

`kicad/bus_physical_swap_plan.py` retains the complete neutral board and
netlist snapshots, bus, capacity certificate, replayed semantic allocation,
lane registry, rule profile, physical policy, foreign initial occupancy, and
an order-sensitive exact region sequence. Every declared semantic swap must
have exactly one region in the same order. Each carrier is generated against
the same retained foreign baseline, then all carrier claims are accumulated in
event order so ordinary, pairwise, and via-site conflicts between otherwise
legal isolated carriers become a typed whole-plan failure.

The plan separately retains semantic, physical-carrier, and combined via counts
for every member and rechecks the physical limits, base bus limits, and final
count-spread limits over the whole event sequence. Empty allocations require a
truly empty region and policy-window set; failed semantic allocations, stale
lane grids, extra windows, missing/reordered/duplicate regions, carrier
failures, cumulative-via failures, and cross-carrier overuse all fail closed.
Successful and failed outcomes replay from the complete input and reject
carrier, claim, occupancy, accounting, telemetry, failure-reason, and
fingerprint tampering.

Root review found that the first two-event fixture placed both swaps at one
section boundary while binding each carrier directly from the original section
assignment to the final next-section assignment. That is accounting, but not a
truthful sequential portal model. The corrected schema-v1 region and plan input
now reject more than one event per corridor section because no certified
intermediate event-state portals exist. The successful two-event fixture uses
successive `section:first`, `section:second`, and `section:following` authority;
the first carrier exits into the same middle-section geometry from which the
second carrier later departs. A replay-valid two-event same-section allocation
is explicitly rejected at both validation boundaries.

The corrected declaration/carrier/plan gate has 84 green tests with warnings as
errors; focused Ruff and strict production mypy are green. The broader R4
regression gate covers 504 tests without failure.

Limitations: this is an exact coverage, occupancy, conflict, and accounting
plan. It does not splice carriers into route prefixes, prove continuity across
event boundaries, commit a transaction, invoke an exact checker, or materialize
a board.

## Accepted: R6.1b fixture 6 copper-removal correction

The removal declaration now binds the exact accepted sensor-isolation result,
one dedicated complete geometry evidence binding, and one `HARD_GEOMETRY` rule.
Fabrication or assembly process evidence remains necessary context but cannot
authorize caller-selected removal geometry. Applicable findings cite only the
dedicated geometry authority; a source on the opposite layer is explicitly
`NOT_APPLICABLE`.

Exact filled-zone evidence now requires a typed active reader policy with
reader/tool identity, project qualification record, artifact SHA-256, and
reviewer. The complete policy is part of the canonical fill record and
checksum. Root review additionally corrected the known-evidence catalog to
include assembly-profile bindings consistently.

The 35 focused tests and 105-test adjacent semantic/process cluster were green
before the root catalog correction; the root reran the corrected transaction,
isolation, copper-removal, thermal, and copper-exposure cluster with 81 green
tests. Ruff and strict production mypy are green.

Limitations: bridge-net authorization, enclosure/performance campaigns, later
R6 topics, and thermometer integration are separate gates. Raw copper overlap
does not become an authorized bridge without a dedicated bridge declaration.

## Accepted: R6.1b fixture 7 sensor bridge companion evaluator

`sensor_bridge_ir.py` and `kicad/sensor_bridge.py` add a separate opt-in
hard-geometry exception authority. It binds the exact isolation result, exact
copper-removal declaration, a dedicated reviewed applicability binding, exact
track source identities, allowed net identities, maximum crossing-track count,
and an exact rational total-width maximum. Only positive-area-overlapping
outer-layer track geometry qualifies. Pads, vias, zones, opposite-layer tracks,
and nonoverlapping tracks cannot become bridge records.

Count, width, source, net, and layer checks have independent typed findings;
equality passes and one-decimal-unit-smaller width authority fails. Most
importantly, the upstream copper-removal result and its `HARD_REJECTED`
findings remain retained unchanged even when the separate bridge authority
passes. Root source review and the 62-test isolation/removal/bridge gate are
green; Ruff and strict production mypy are green.

Limitations: this slice proves only declared bridge geometry and budgets. It
does not prove thermal performance, enclosure behavior, or validation-campaign
success.

## Accepted: R6.1b fixture 8 validation-campaign separation

`sensor_validation_ir.py` and `kicad/sensor_validation.py` add a separate
performance authority that retains complete upstream isolation and optional
copper/bridge results. Missing or nonmatching enclosure/campaign records yield
typed `VALIDATION_PENDING`; they never turn into geometry success or failure.
Exact matching thermal and optional humidity campaign records pass or fail only
their named project requirements while upstream metrics, evidence, findings,
and fingerprints remain unchanged.

Records retain board/enclosure revisions, firmware/radio/load states, chamber,
reference instruments, airflow/orientation, stabilization time, sample count,
project target, reviewed pass/fail, raw-data SHA-256, test date, and reviewer.
The root 82-test R6.1 isolation/removal/bridge/validation gate is green; Ruff
and strict production mypy are green.

Limitations: the evaluator verifies record identity, context, checksum, and raw
artifact hash but does not inspect samples, recompute statistics, authenticate
a signature, supply a default target, or simulate thermal/humidity behavior.

## Accepted: R6.1b fixture 9 generic-advice rejection

Sensor-isolation numeric limits now retain a typed authority origin. Qualified
fabricator/assembler capabilities, exact project design authority, and
validated or retained legacy project requirements may become hard numeric
constraints only with their complete selected applicability authority.
Manufacturer recommended layouts, application-note examples, and generic
books/advice are advisory-only at schema validation; changing only the origin
of an otherwise identical numeric quantity cannot turn them into
`HARD_GEOMETRY` or qualified-process authority. Advisory values remain
retainable and measurable but cannot emit a hard `FAIL`.

Root review also corrected project-oriented finding language so it does not
mislabel project geometry as a process limit. The 121-test R6.0/R6.1 semantic,
thermal, isolation, removal, bridge, and validation gate is green; Ruff and
strict production mypy are green.

Limitations: the typed-origin correction currently applies to the fixture-5
slot/web/tab numeric-declaration boundary. It does not supply any universal
moat/bridge number or redesign later R6 declarations.

## Accepted: R6.2 module-local antenna placement authority

`antenna_ir.py` and `kicad/antenna_semantics.py` add the placement-only
foundation for an explicitly selected antenna module. The declaration binds the
module reference, installed footprint library identity, component UUID path and
revision field/value, source-file SHA-256, complete reviewed applicability
binding, asymmetric antenna/feed compounds, and the installed footprint's exact
multilayer keepout polygons, prohibited object kinds, and provenance. A generic
footprint name or stale module, footprint, UUID, revision, source, or geometry
binding cannot validate the declaration.

The evaluator retains canonical full `BoardLayout` and `BoardNetlist` snapshots,
requires the placed and netlisted component identities to agree exactly, and
uses the shared R5 transform. Front/back quarter turns retain exact compounds;
arbitrary angles retain the certified bounded transform and explicitly omit an
exact-vertex claim. JSON reconstruction reparses the snapshots, rederives every
placed region, and requires exact result equality. The root 86-test antenna,
placement-geometry, board-serialization, and semantic-IR gate is green; Ruff and
strict production mypy are green.

Limitations: this slice does not yet evaluate prohibited board objects,
edge-overhang or cutout strategy, module support/pads, source-approved
exceptions, enclosure geometry, nearby ground/stitching, RF campaigns, R5
ranking, or production defaults.

## Accepted: R6.2 exact antenna keepout/object clearance

`antenna_clearance_ir.py` and `kicad/antenna_clearance.py` consume only the
replay-valid placement authority and explicit typed physical objects. Every
installed keepout/object pair is retained. Applicability is exactly the
intersection of the keepout's declared prohibited kind and physical layers:
wrong-kind or wrong-layer pairs are `NOT_APPLICABLE`; an applicable bounded
placement or unsupported object is hard `UNVERIFIED`; exact disjoint geometry
passes; exact boundary contact or interior overlap fails conservatively.
Tracks, vias, foreign pads, exact final zone fill, foreign footprint bodies, and
explicit board material fire independently. No module-owner exemption is
inferred.

The exact-zone input reuses the accepted `ExactFilledZoneReaderPolicy`, requires
the top-level reader identity to match that complete active nested policy, and
retains the antenna-specific exact-compound fingerprint and canonical fill
record. Zone intent cannot claim exact fill. Physical owner component/net
identities must occur in the retained board netlist. The result contains common
hard-geometry findings and a `SemanticLayoutResult`; JSON reconstruction
re-evaluates the full pair matrix and rejects object, source/fill provenance,
placement, rule, pair, finding text, semantic-result, and fingerprint tampering.
The root 109-test antenna/semantic/geometry/serialization gate is green; Ruff
and strict production mypy are green.

Limitations: edge/cutout strategy, module support/pads, source-approved
exceptions, enclosure, ground/stitch requirements, RF validation, R5 ranking,
raw-object auto-ingestion, and default behavior remain separate slices.

## Accepted: R6.2 exact antenna edge-overhang material rules

`antenna_edge_ir.py` and `kicad/antenna_edge.py` add the edge-overhang strategy
without weakening the placement or object-clearance authorities. A companion
declaration binds the selected antenna declaration, the one required antenna
region, and separately sourced exact module body/pad-support compounds to
pinned reviewed evidence. Support identities, provenance identities, installed
footprint, UUID path, revision, source hash, applicability binding, and the
complete support-geometry fingerprint are all replay checked.

The evaluator reconstructs the exact concave outer outline and typed board
cutouts from the retained `BoardLayout` snapshot. At front/back quarter-turn
poses the antenna region must be strictly disjoint from board material:
boundary touch and interior overlap fail. Every declared support compound must
lie in the closed outer polygon and remain strictly disjoint from every cutout;
outer-edge equality is allowed, while cutout touch or intrusion fails. These
are independent hard findings and there is no whole-component exemption.
Arbitrary-angle placements retain the bounded transform but both rules become
hard `UNVERIFIED`, never an exact pass.

JSON reconstruction re-evaluates material, transforms, relations, findings,
messages, and fingerprints. Concave-outline, cutout intrusion/touch,
front/back quarter-turn, bounded-transform, stale source/binding, missing or
duplicate identity, reversal, and tamper fixtures are green. The root adjacent
antenna gate has 72 green tests with warnings as errors; focused Ruff and
strict production mypy are green.

Limitations: this slice proves only exact board-material edge overhang and
declared support containment. Baseboard-cutout strategy, source-approved
exceptions, enclosure, nearby ground/stitch rules, RF validation campaigns,
R5 ranking, and production defaults remain open.

## Accepted: R6.2 exact selected baseboard-cutout strategy

`antenna_cutout_ir.py` and `kicad/antenna_cutout.py` consume only a replay-valid
placement whose strategy is exactly `baseboard_cutout`. The caller must select
one typed `BoardCutoutPolygon` explicitly; the selection retains its
geometry-derived ID, semantic SHA-256, exact compound, board-layout snapshot
fingerprint, and complete selection fingerprint. The evaluator resolves
exactly one matching retained cutout and never chooses a nearest void.

For exact front/back quarter turns, the antenna compound must be contained in
the selected cutout and have a strictly positive exact rational squared
distance from every selected-cutout boundary. It must also be disjoint from the
reconstructed board material. Equality/touch, partial escape, or material
overlap fails. Declared body/pad supports independently require closed outer
containment and strict disjointness from every cutout, including nonselected
ones; outer-edge equality can pass while any cutout touch/intrusion fails.
Arbitrary-angle bounded transforms produce independent hard `UNVERIFIED`
findings.

The declaration reuses the reviewed support-geometry authority and binds the
module, footprint, UUID path, revision, source hash, support/provenance
identities, required antenna region, and selected board snapshot. Reconstruction
rederives material, selection, transforms, exact predicates, findings,
messages, and fingerprints. Root review and the 98-test four-module antenna
gate are green; the agent's broader antenna/semantic gate has 130 green tests.
Ruff and strict production mypy are green.

Limitations: current cutout IDs are geometry-derived because
`BoardCutoutPolygon` has no authored identity. Duplicate cutout geometry is
already invalid, and the resolver still requires exactly one match.
Source-approved exceptions, enclosure, ground/stitch rules, RF campaigns, R5
ranking, and defaults remain open.

## Accepted: R6.2 source-bound exact 3-D enclosure exclusion

`antenna_enclosure_ir.py` and `kicad/antenna_enclosure.py` add an independent
3-D enclosure check without changing or expanding any 2-D PCB placement,
keepout, clearance, edge, or cutout authority. The declaration binds the exact
module source/revision, local antenna exclusion prism, source-specific required
clearance and prohibited material classes, reviewed applicability evidence,
and the exact enclosure profile/revision/model SHA-256. No project-wide 15 mm
or other default clearance is synthesized.

At exact front/back quarter-turn placements, the evaluator uses the shared
exact planar transform, reflects the local Z interval about the declared board
plane, and computes exact product-set squared distance as the sum of an exact
planar-compound witness and exact interval separation squared. All arithmetic
retained in the verdict is rational. Equality at the required clearance passes;
lower clearance, contact, and overlap fail. Nonprohibited material is explicitly
`NOT_APPLICABLE`. Missing model/profile/object geometry and bounded arbitrary
angles are blocking `VALIDATION_PENDING`, never an exact pass.

The enclosure profile has a declared expected-object inventory and rejects
invented, duplicate, stale, or foreign objects. Root review additionally closed
an incomplete-inventory loophole: even when every currently named object is
present, a profile explicitly marked incomplete now retains independent
blocking pending evidence rather than allowing completed evidence to imply
whole-enclosure coverage. JSON reconstruction replays declarations, transforms,
inventory, exact witnesses, findings, and fingerprints. The retained before/
after 2-D PCB geometry fingerprints must be identical. The complete five-suite
antenna gate is green at 128 tests with warnings as errors; Ruff and strict
production mypy are green.

Limitations: this proves only the source-bound geometric enclosure exclusion.
RF campaign results, source-approved exceptions, nearby ground/stitching,
production integration, and project defaults remain separate authorities.

## Accepted: R6.2 condition-matched RF validation records

`antenna_rf_validation_ir.py` and `kicad/antenna_rf_validation.py` implement RF
performance as a separate validation-record authority, not as inferred geometry.
The requirement binds the exact module/source revision, installed footprint and
UUID path, replay-valid placement fingerprint and full pose, board snapshot plus
reviewed board revision/artifact SHA-256, enclosure profile/revision/model,
firmware artifact/version/SHA-256, radio mode, band/channel, counterpart,
range/revision, setup artifact and canonical configuration, environment profile,
validation source/profile, and exact-decimal metric targets/comparators/units.
Its applicability binding must be complete, reviewed, pinned, and fingerprinted
over all of those conditions. No radio, range, channel, clearance, or metric
default is inferred.

A complete campaign record must match the whole requirement context and retain
the raw-data artifact identity/hash, acquisition tool/method/version, canonical
raw result record/hash, and exact-decimal measurements. Metric evidence locally
rechecks its identity, unit, comparator, value, and PASS/FAIL disposition. A
missing, unavailable, or explicitly incomplete campaign is
`VALIDATION_PENDING`; even an incomplete record containing every currently
named metric cannot pass. Exact target equality follows the declared comparator.
Extra, duplicate, missing, stale-context, stale-target, stale-profile, stale-
setup, wrong-unit, and raw-record-hash cases reject or remain pending.

The upstream enclosure prerequisite is retained as a distinct validation
finding. RF PASS is possible only when that replay-valid prerequisite outcome is
`PASSED`; RF data cannot override pending or failed geometry. PCB placement,
keepout, and enclosure geometry are fingerprinted before/after and remain
unchanged. Root source review and the complete six-suite antenna gate are green
at 170 tests with warnings as errors; Ruff and strict production mypy are green.

Limitations: this fixture proves record binding and exact target evaluation, not
that a real RF laboratory campaign has been run for the thermometer. Nearby
ground/stitch declarations, source exceptions, integration, and production
defaults remain open.

## Accepted: R4 physical-swap-aware connected prefix composition

`kicad/bus_physical_swap_composition.py` consumes only a successful replay-bound
physical swap plan and retains the complete certified pigtail, semantic-via,
terminal-source, and physical carrier authorities. Each member's assigned lane
geometry is reconstructed in certified section order. Every adjacent boundary
is classified exactly: same point/layer is direct; same point with a layer
change consumes the exact semantic transition carrier; changed point on the same
layer consumes the unique matching physical carrier member; changed point plus
changed layer remains unsupported in schema v1.

The composer adds the certified lane, pigtail, semantic-via, and physical-swap
copper into a connected canonical `GridRoutePrefix` under a separate
`CertifiedPhysicalSwapBusMemberPrefix` wrapper. The ordinary
`CertifiedBusMemberPrefix` contract is unchanged. Global coverage requires every
pigtail, transition via, and physical carrier membership exactly once. Full
plan/input, section geometry, boundary, event, carrier, terminal-source, inner
prefix, member composition, and result fingerprints rederive after JSON.

The truthful successive-section two-event fixture produces three connected
member prefixes: member m0 consumes both swap carriers and four physical vias;
m1 and m2 each consume their one swap carrier and exact nonparticipant/tail
continuity, including their semantic transitions. Missing, duplicate, unused,
out-of-order, wrong-source, wrong-endpoint, changed-point/changed-layer, and
tampered nested authority cases reject. Root review, 13 focused tests, the 119-
test adjacent gate, and the complete 524-test R4 gate are green with warnings as
errors; Ruff and strict production mypy are green.

Limitations: this is prefix authority only; the next section supplies candidate
construction. Atomic transaction, exact checked commit, board materialization,
and the LCS-outlier consumer remain open. Schema v1 still rejects more than one
event per section and changed-point/changed-layer boundaries.

## Accepted: R4 replay-bound physical-swap candidate construction

`kicad/bus_physical_swap_candidate.py` consumes only a replay-valid successful
physical-swap prefix composition and calls a narrowly extracted private routing
kernel shared with the ordinary candidate builder. The ordinary public builder
keeps its original binding/prefix preflight order and behavior. Physical
prefixes are supplied directly as `GridRoutePrefix` values; they are never
counterfeited as ordinary `CertifiedBusMemberPrefix` records.

The versioned replay input retains the full composition, all member/total work
budgets, candidate policy, congestion history and present factor, negotiated
cost policy, and canonical clearance groups. The caller ledger must exactly
equal the physical plan's initial claims/fingerprint and remain immutable.
History and clearance identities are canonical; duplicate declarations and
nonfinite clearances reject. Successful results bind the exact bundle and every
member's composition, prefix alternative/fingerprint, and complete route
fingerprint. Certified prefix segment/via geometry—including net, width, via
dimensions, and mask modes—must be present in the resulting route. Failure
records carry no success-only bundle or member binding fields.

Fixtures cover the truthful three-member/two-swap composition (including m0's
four physical vias), foreign occupancy, all one-less member/per-member/total
budgets, strict/preserve caller overuse, target copper and member-claim
preflights, complete policy/profile/history/clearance replay tamper, missing or
reordered members, and prefix/bundle/geometry/fingerprint tamper. Root source
review and the 10 focused, 12 ordinary-candidate, and 13 composition tests are
green with warnings as errors; Ruff, formatting, strict production mypy, and
whitespace checks are green. Reusing the immutable canonical composition
reduced the focused runtime from roughly 399 seconds to 96 seconds while
external JSON/model-instance paths remain fail-closed.

Limitations: the trusted builder avoids a redundant second wrapper replay via
`model_construct`, but public replay-input reconstruction and external result
validation still perform the full nested replay. Atomic transaction, exact
checked materialization, board-generator integration, and LCS/outlier use are
still open.

## Accepted: R4 physical-swap transaction and exact checked-commit bridge

`kicad/bus_physical_swap_candidate_transaction.py` retains one successful
replay-bound physical-swap candidate as the sole replacement authority. The
retained route bundle must equal the candidate's exact bus and allocation,
candidate/composition result, member bindings, member prefix identities, and
fingerprints. Before replacement, the live ledger and route map must equal the
candidate's complete initial occupancy after accounting for the declared bus
members. The ordinary transaction coordinator remains unchanged: the adapter
uses its existing atomic replace boundary, requires exactly one callback, and
proves that stripping the replaced member claims leaves precisely the retained
foreign occupancy.

The committed result binds exact before/after ledger and route-map snapshots,
telemetry, bus/allocation/candidate/bundle identities, recomputed occupancy and
overuse, foreign-route preservation, and the one retained physical bundle.
Rejected callbacks, substituted routes or claims, stale telemetry, incomplete
replacement boundaries, direct overuse tamper, and callback mutation all fail
closed or restore the exact original state.

`kicad/bus_physical_swap_replay_checked_commit.py` composes the same authority
with the unchanged ordinary exact checked-commit coordinator. It runs the
retained candidate exactly once against a scratch ledger. Acceptance requires
the exact complete materialized route map, matching netlist, checker evidence,
layout fingerprint, and every physical prefix segment and via named by every
member binding. Rejection and missing-checker results retain no accepted state;
materializer or checker error/mutation rolls back exactly. The wrapper cannot
substitute an ordinary prefix candidate or silently omit physical carrier
copper.

Root source review and the final focused gates are green: 7/7 physical
transaction, 10/10 physical exact checked commit, 97/97 ordinary transaction/
candidate-transaction/checked-commit adjacency, 10/10 physical candidate,
13/13 physical composition, and 12/12 ordinary candidate. Ruff, formatting,
strict production mypy, and whitespace checks are green. Explicit cold/warm
cache-clear timings are 23.335/5.065 seconds for the transaction suite and
23.811/4.888 seconds for the exact checked suite.

Limitations: this closes the adjacent-swap candidate-to-commit/materialization
bridge only. LCS/outlier layer, transition, capacity, and via realization,
board-generator opt-in integration, thermometer bus declarations, and any
claim of routing or electrical superiority remain open.

## Accepted: R4 LCS/outlier physical-realization authority

`kicad/bus_lcs_physical_realization.py` is a companion validator over the
existing deterministic LCS/outlier sequence telemetry. It does not select a
different subsequence or allocate lanes. Its immutable replay input retains the
exact sequence result, bus, capacity certificate, successful replayed lane
allocation, replay-bound transition carriers, every certified member prefix,
complete rule profile, explicit base/outlier layer and per-member clearance/
transition policy, validation budget, and independent fingerprints.

Source and target order remain semantic sequence order and must equal the
active declared first/last bus boundaries; lexical member order cannot replace
them. Every stationary member must occupy the base layer in every section with
zero transition vias. Every outlier must occupy one contiguous declared inner
section interval on an allowed outlier layer, with distinct exact source and
target transition events, windows, replay-bound carriers, and prefix vias. The
allocation, carrier, and prefix via counts must agree exactly and satisfy both
the bus and stricter physical per-member/spread limits.

Each member must have one exact assignment in every section. Its assigned slot
must match net, layer, order index, maximum width, and every explicitly required
clearance-domain ID; an adequate slot count alone cannot pass. Used indices form
one contiguous block per section/layer. Prefixes revalidate against the exact
bus/certificate/allocation/geometry-registry roots and cover every declared
member once. The retained profile uses a versioned LCS-physical namespace;
bus profile identity, certificate profile fingerprint, and transition replay
profile must all agree.

Ordinary infeasibility returns typed sequence/member/authority/allocation,
source-transition, target-transition, layer, lane capability/capacity, via,
physical-carrier, or work-budget outcomes. Zero and one-less work budgets stop
before excess validation and retain only the attempted target-order prefix.
Nested replay/tamper, set-like reversal, source/target window, profile,
certificate, transition, prefix, width/domain, via/spread, member-order, JSON,
and caller-immutability cases are covered. Root source review and final gates
are green: 15/15 focused, 67/67 LCS/physical/replay, and 73/73 allocator/
transition/integration tests; Ruff, formatting, strict production mypy, and
whitespace checks are green. The focused suite runs in about 2.3 seconds.

Limitations: this validates one already successful allocation; it does not yet
optimize an LCS choice using physical transition cost, generate the allocation,
route/commit/exact-check the complete bus, or bind a board snapshot. Board-
geometry and static-obstacle freshness remain predecessor capacity-certificate
authority. A one-less certificate cannot be presented as a successful replayed
allocation—the allocator correctly fails first—so no contradictory capacity
fixture is fabricated.

## Accepted: R5 deterministic KiCad identities and save/read-back gate

The renderer now assigns deterministic collision-safe UUIDv5 identities to
footprints, properties, pads, footprint graphics, raw board graphics, and
synthetic schematic paths. Two clean renders parsed and saved independently by
KiCad 10.0.3 are byte-identical. The root also migrated emitted board copper
and pad net references to KiCad 10's named-net syntax; stale numeric-net test
expectations were corrected.

`kicad/placement_readback.py` retains the complete shaped serialization
authority, KiCad version, initial and saved bytes/hashes, canonical DRC JSON,
and a closed semantic snapshot of footprints, outline/cutout geometry, board
graphics, zones excluding generated fill tessellation, segments, vias, named
nets, used layers, and nondefault setup. It recognizes only demonstrated
syntax/default equivalences while retaining substantive geometry, net, layer,
mask/tenting, and setup changes. Fourteen nonlive tests and two explicitly run
live tests are green: a rotated nonrectangular board passes readback and DRC,
while the intentionally dirty preservation sentinel is rejected because KiCad
changes real net ownership during save. The adjacent 129-test board/
serialization/readback cluster is green with two live tests opt-in skipped.

The roundtrip schema explicitly removes only KiCad's top-level wall-clock DRC
`date`; retaining it made otherwise identical authorities differ. Every tool,
configuration, ignored-check, and finding field remains canonical and hashed.

## Accepted: narrow R5 stable aggregate exact-checker predecessor

`kicad/aggregate_exact_checker.py` evaluates one canonical `BoardLayout` and
`BoardNetlist` under a frozen versioned policy that contains the complete rule
profile, `DesignChecksSpec`, and canonical required/applicability list. It
recomputes virtual DRC (including connectivity findings) and deterministic
design checks from retained snapshots during JSON reconstruction. Their full
canonical results, finding fingerprints, the existing `ExactRouteCheckResult`,
and a stable checker identity derived from the complete policy are retained.

External checks are not serialized as callbacks or accepted as a bare boolean.
The narrow generic evidence carrier binds each external status/finding set to
the exact layout, netlist, and policy fingerprints and retains the source
artifact ID/hash, tool/version, canonical configuration/hash, result identity,
and canonical record/hash. Missing required evidence is blocking
`UNVERIFIED`; explicit policy-level `NOT_APPLICABLE` remains distinct; failed
or unverified evidence requires a finding. Extra, duplicate, stale, and
in-process-replacement records reject. In-process checks run on detached inputs
and mutation of retained or caller board, netlist, or policy state rejects.

Root source review and the 95-test focused/adjacent aggregate, placement-exact,
read-back/corpus, virtual-DRC, and design-check gate are green (92 passed and
three intended environment-gated skips). Ruff and strict production mypy are
green.

The first concrete external producer is now part of the aggregate authority.
`KiCadSaveRoundtripSubcheckEvidence` retains the complete existing
`PlacementKiCadSaveRoundtripAuthority`, requires an explicit reserved producer
ID in policy, and rebinds its serialization final layout and source netlist to
the aggregate's exact snapshots. PASS is derived only from passed DRC with no
findings, equal semantic read-back snapshots, equal repeated-save hashes, and
an enabled required DRC gate. A retained failure is `FAIL`; a clean authority
whose required gate was disabled remains `UNVERIFIED`. Generic external records
cannot satisfy the producer-specific requirement. The root aggregate,
serialization, read-back/corpus, and placement-exact gate has 113 passes and
three intended environment skips; Ruff and strict production mypy are green.

The second concrete producer is
`ReaderNetlistEqualitySubcheckEvidence`. It retains both machine and reader
schematic artifact identities/hashes, the complete exported KiCad XML texts and
hashes, reparsed canonical `BoardNetlist` snapshots, the complete machine and
reader `KiCadReport` ERC records, tool/version and canonical configuration, and
the derived comparison/status/findings. The machine parse must equal the
aggregate netlist exactly. The reader parse is compared with the existing
semantic reader comparator, so harmless source order and UUID-path differences
do not substitute for component, value, footprint, or net-node equality.

PASS requires both ERC reports to be passed with no findings and an empty
semantic comparison. Established ERC or netlist differences fail; unavailable,
not-run, warning, or human-review ERC states are `UNVERIFIED`. Generic evidence
and the KiCad save/read-back producer cannot impersonate the reserved reader
producer. XML/parser/snapshot/report/result reconstruction and nested aggregate
tamper tests are replay checked. Root review, 28 focused tests, and a 104-test
adjacent aggregate/roundtrip/reader/parser/serialization gate are green; Ruff
and strict production mypy are green.

The third concrete producer is `ThermometerNgspiceSubcheckEvidence` under the
reserved `pcbsmith.simulation.thermometer-ngspice-adapter` identity. It retains
the canonical `CircuitObject` snapshot/hash, circuit artifact identity/hash,
supported topology, explicit model-scope identity/note, regenerated SPICE
netlist text/hash, raw ngspice output text/artifact/hash, complete
`SimulationReport`, ngspice version, canonical configuration, parsed
measurements, aggregate bindings, and replay-derived status/findings. The raw
`.meas` output is reparsed and run through the same pure thermometer measurement
evaluator; the retained report must agree exactly for completed results.

PASS requires replayable measurements, a passing model evaluation, an
ngspice-identifying command, a retained raw-output path, and the complete model
scope. Replay-derived threshold/model failures are `FAIL`; unavailable,
not-run, incomplete, or tool-failed output without replayable measurements is
`UNVERIFIED`. The authority explicitly covers only the two modeled LED branches.
Registers, MCU/radio, sensor, and regulator remain datasheet/calculator scope and
are stated as not SPICE-simulated. Generic, save/read-back, and reader-equality
evidence cannot impersonate this producer. Root review, 33 focused tests, and
the 108-test aggregate/simulation gate are green; Ruff and strict production
mypy are green.

Limitations: this is a stable aggregate framework and synthetic firing fixture,
not the thermometer checker. Any other project-specific external result still
needs a typed producer/semantic adapter;
the generic record does not inspect their raw artifacts. The specialized KiCad
adapter was exercised with retained nonlive fixture authority in its ordinary
tests; the reader and simulation adapters likewise use retained nonlive fixture
reports/XML/output. This turn did not launch KiCad or ngspice for these adapters.
The simulation record intentionally does not claim `CircuitObject`-to-
`BoardNetlist` equivalence; the eventual consumer must bind it alongside the
reader authority for the same design. The aggregate still does not bind an
R3/R2 candidate manifest or establish thermometer policy, applicability, or
readiness.

## Accepted: R5 replay-bound placement acceptance manifest

`kicad/placement_acceptance_manifest.py` is the first consumer that composes
the placement-exact and stable-aggregate authorities for one identical
synthetic board. It requires exactly one accepted placement candidate, a
successful zero-overuse R2 detail record, and applied R3 guidance whose graph,
plan, guide, and routing-run fingerprints all cross-bind. The aggregate's
canonical layout and netlist snapshots must reproduce the accepted record's
materialized-layout, target-route-geometry, and netlist fingerprints.

The manifest policy requires exactly the reserved KiCad save/read-back, reader
netlist equality, and thermometer ngspice producers. Their specialized record
types, producer identities, subcheck fingerprints, nested serialization and
machine-netlist snapshots, and passing simulation status are retained and
revalidated. The placement exact report must equal the aggregate result in
accepted status, checker identity, canonical finding fingerprints, and a
freshly recomputed checker-report fingerprint; sharing only a checker ID and a
boolean cannot compose the authorities.

The schema permanently records that it makes neither a thermometer-readiness
claim nor a `CircuitObject`-to-`BoardNetlist` equivalence claim. Root review,
27 focused tests, and the 238-item aggregate/exact/detail/serialization/readback
matrix are green (235 passed and three intended environment-gated skips); Ruff,
strict production mypy, and whitespace checks are green.

Limitations: the current manifest firing fixture is nonlive and synthetic. It
has not yet been rebuilt around the capacity-two narrow-stem authority below
and does not replace thermometer geometry/policy declarations, live
KiCad/ngspice evidence for the eventual consumer, or real RF campaign evidence.

## Accepted: R5 named capacity-two narrow-stem R3/R2 authority

`tests/fixtures/routing/reduced_capacity_two_stem.py` and
`test_reduced_capacity_two_stem.py` provide the missing deterministic reduced
consumer predecessor without changing production algorithms. A shaped
wide-chamber/narrow-stem/wide-chamber board carries two independent front-
copper nets through a reviewed R3 graph. The named stem portal has exact coarse
interval x=[6,8] mm at y=10 mm, raw quantity capacity 20, and a 0.1 mm quantum.
Each demand derives eight units from `(0.6 mm width + 0.2 mm clearance) / 0.1
mm`, so its exact quantity capacity is `floor(20/8)=2` with four residual units.
Both allocations claim the named resource and the verified plan has zero
overuse.

The same proof retains and pins the source layout/netlist, graph, plan,
`VerifiedCorridorPlanSummary`, coarse/projected guidance, applied guidance
report, routed-unchecked ordinary R2 run, routed layout, and exact segment
snapshot. R2 uses reviewed ceilings of 20,000 total and 10,000 expansions per
net but consumes only 367 per net/734 total in one pass, with no vias and zero
overuse. Both nets are independently replay-checked for exact connectivity,
front-layer ownership, and physical stem crossing; that separate test checker
is not mislabeled as the later aggregate acceptance consumer. A total budget of
733 fails deterministically on the second net.

Reducing only the named portal to 15 units produces its sole one-unit overuse
and prevents guidance construction. Stale graph, summary, and projected-guide
bindings reject, and deleting the named coarse cut disconnects all terminal
pairs, proving there is no apparent shorter coarse evasion. The corrected 1 mm
detailed-grid fixture runs in about 0.6 seconds; the earlier exploratory
500,000-expansion run was terminated and discarded. Root review, three focused
tests in about 3.1 seconds, and the 135-test corridor/allocator/summary/guidance/
negotiated-board gate are green; Ruff, formatting, and strict production mypy
are green.

Limitations: this is a reusable test authority, not a placement search, real
thermometer declaration, aggregate-manifest firing, KiCad live run, or claim
that R3's named portal centerline is the exact detailed R2 trace location.

## Accepted: R5 complete placement-pilot input authority and reduced-stem probe

`placement_pilot_authority.py` adds a generic replay-bound input envelope for a
future placement pilot. It retains full canonical board-layout and netlist
snapshots, a complete placement geometry catalog, explicit bounded move and
legalization policies, target nets and one width per target, the full PCB rule
profile, clearance groups, independent placement/coarse/detailed grids and
corridor capacity quantum, and every typed proposal, surrogate, R3 graph/cost/
allocation, detail-selection, R2 routing/cost, and exact-check policy/budget.
The existing dataclass negotiated-cost policy is retained through a versioned
wrapper whose complete semantic payload must reconstruct the original policy
exactly. No callback, algorithm name, project default, or fake readiness ID is
serialized.

The validator reparses all snapshots and nested records, requires every
netlisted component to have an identical layout placement, and permits
additional fixed layout-only physical parts such as thermometer H1. Net nodes
cannot use those layout-only parts unless the components also exist in the
netlist. The geometry catalog covers every physical placement; every movable
body and courtyard must be exact and supported. Target/width, profile,
clearance, grid, policy, negotiated-cost, and all compatible parent/stage budget
fields cross-bind and fingerprint independently. Placement proposal step and
R3 coarse grid remain distinct reviewed inputs.

The reduced-stem firing fixture supplies exact rectangular body/courtyard
geometry for all four terminals and a bounded movable pair. Its no-change probe
and one legal translated candidate preserve outline, graphics, zones, mask,
cutouts, fixed copper, component identities, and router inputs. Authority,
base-candidate, and translated-candidate fingerprints are pinned; reversal and
repeat runs are identical. A fixed nonnetlisted mechanical placement passes,
while missing/mismatched netlisted parts, unsupported movable geometry,
omitted/extra widths, foreign clearances/references, illegal permissions,
stale nested policies/budgets/snapshots/fingerprints, and future unclassified
layout-field preservation fail closed. Root source review, 36 focused tests,
and the 130-test placement geometry/legalization/candidate/probe/surrogate/
detail/exact adjacency gate are green; Ruff, formatting, strict production
mypy, and whitespace checks are green.

Limitations: this is input and probe/candidate authority only. It performs no
R3/R2 detail evaluation, exact/aggregate check, acceptance-manifest firing,
real thermometer search, or readiness claim.

## Accepted: R5 reduced capacity-two stem acceptance firing

`kicad/placement_pilot_acceptance.py` composes the complete input authority,
candidate search, materialized probe snapshot and typed surrogate for every
candidate, each available replayed R3 graph/plan, the selected R3 guidance and
R2 run, exact result, stable aggregate evidence, and the existing acceptance
manifest. Every retained probe is independently rebuilt from the source layout
plus only its declared poses. Every graph is independently rebuilt from that
probe plus the retained profile, clearances, grids, graphics policy, and graph
budget. R3 targets, widths, allowed layers, via policy, cost policy, and budget
must match the input envelope exactly.

The input envelope now includes a versioned per-target corridor-demand policy.
For this fixture both stem nets are explicitly F.Cu-only with vias forbidden;
the evaluator no longer supplies those rules as unbound constants. The wrapper
requires source-to-candidate changes to be only declared pose fields and
candidate-to-final changes to be only target segments/vias. Fixed and foreign
copper, every other `BoardLayout` field, the complete netlist, exact checker
identity, aggregate producer records, findings, and manifest fingerprints must
remain unchanged.

Firing exposed three real inconsistencies in the earlier input-only fixture.
The graph builder preflights 126 cells before outline pruning, so the pinned
100-cell ceiling could never produce its retained 30-cell graph; the corrected
ceiling is exactly 126 and 125 fails before geometry work completes. The bare
`aggregate-exact-v1` checker name could never equal the stable aggregate
policy's deterministic `<policy>@<version>:<fingerprint>` identity; the exact
policy now pins that real identity and rejects the old/stale value. Finally,
the provisional off-corridor penalty 250 exhausted the 600-per-net budget,
whereas the already reviewed reduced-stem fixture uses 50. Aligning that policy
to 50 completes in 367 expansions per net/734 total without increasing the
600-per-net or 1,000-total ceilings; a 733 total ceiling fails exactly.

The final synthetic chain has two candidate inputs, one available R3/R2 detail
run, exactly one zero-overuse accepted candidate, and exactly the three required
nonlive specialized producer records. Its test-only terminal footprint is a
minimal deterministic one-pad fixture with explicit local provenance; it is not
installed-library or production footprint authority. The result literals
explicitly deny circuit-to-board equivalence, thermometer readiness, live-tool
execution, and superiority.

Root source review and final gates are green: 19/19 focused acceptance in about
1.55 seconds cold and under 0.05 seconds cached, 58/58 authority plus acceptance,
228/228 placement/exact/aggregate/manifest adjacency in 32.6 seconds, and 99/99
corridor adjacency. Ruff, formatting, strict production mypy, and whitespace
checks are green.

Limitations: this closes the reduced synthetic consumer only. The specialized
producers are deliberately nonlive and the simulation makes no equivalence
claim to this two-net board. Real KiCad/ngspice execution, thermometer geometry,
escape/order/policy/budget declarations, bounded thermometer search, semantic
R6 integration, and any scope-expansion decision remain open.

## Accepted: R6.3 routed-copper graph and exact path foundation

`routed_copper_graph_ir.py` and `kicad/routed_copper_graph.py` derive a
deterministic net/layer copper graph from full canonical board-layout and
netlist snapshots plus explicit terminal anchors bound to physical pad source
identities. Track, via, and qualified exact-zone edges retain deterministic
geometry source IDs. Vias retain their size separately; path minimum width and
neck identities are track-only. Track lengths retain exact rational squared
lengths and combine as canonical square-free radical terms rather than float
approximations.

A unique simple path may be selected automatically; multiple paths require an
exact ordered edge declaration. Foreign, stale, noncontiguous, and wrong-net
selections reject. Qualified rectangle/disc filled-zone geometry can establish
connectivity, but because it provides no trace-length authority the selected
path remains explicitly `UNVERIFIED` for metric use. Unsupported or unfilled
zone geometry likewise remains explicit rather than being treated as absent.

The endpoint graph deliberately does not invent segment splitting. Exact
rational same-net/same-layer anchor-on-track-interior, via-on-track-interior,
T-junction, crossing, and positive collinear-overlap contacts retain source IDs
and contact witnesses and make the relevant path `UNVERIFIED`; they can never
silently produce a false connected or disconnected verdict. Replay, tamper,
reversal, input-order determinism, and caller-input immutability are covered.
Root review, 18 focused tests, and the 100-test graph/board-serialization/zone/
routability/antenna-clearance gate are green; Ruff, strict production mypy,
and whitespace checks are green.

Limitations: this is graph/path evidence only. It does not yet declare or
evaluate decoupling hot loops, daisy-chain/dedicated topology, zoning/return
policy, impedance, current, capacitance, electromagnetic performance, or board
mutation.

## Accepted: R6.4 replay-bound decoupling-loop metrics and policy

`decoupling_loop_ir.py` and `kicad/decoupling_loop.py` compose two exact routed
paths into a declared electrical loop: source-power to load-power and
load-return to source-return. The declaration binds the complete routed graph,
board/netlist snapshots, path results, terminal role anchors, physical pad
source IDs, power/return nets, terminal inventory, and exact policy. Both path
records are reparsed and rederived; copied status fields cannot impersonate an
exact connected leg.

For exact-clean legs the evaluator retains each leg's ordered nodes, edges,
geometry sources, layers/transitions, vias, track-only minimum width/necks, and
canonical radical length terms. It also retains combined metrics and computes
projected loop area with exact rational shoelace arithmetic over the ordered
supply/return geometry plus two explicit endpoint-closure witnesses. Repeated,
backtracking, crossing, zero-area, or otherwise non-simple projected closures
are `UNVERIFIED`, never converted to a floating area.

Dedicated versus daisy-chain classification uses an explicit two-net terminal
inventory. A complete inventory must equal every component/pad node on both
nets in the retained canonical `BoardNetlist`, every relevant routed-graph
anchor, and every inventory entry, one-to-one. Hidden netlist nodes, invented
nodes, duplicate physical-pad sources, and duplicate component/pad aliases
reject. An incomplete inventory remains `UNVERIFIED` even when the selected
policy does not require a dedicated topology.

Policy thresholds use exact integers/rationals and canonical decimals; equality
passes. Established via-count, track-width, area, or daisy-chain violations
fail, while zone/contact/path/area/inventory uncertainty propagates as
`UNVERIFIED`. The result states that it is electrical/topological evidence only
and makes no electromagnetic, impedance, current, capacitance, or placement-
distance claim. Root review, 15 focused tests, and the 52-test decoupling/graph/
board-serialization gate are green; Ruff, strict production mypy, formatting,
and whitespace checks are green.

Limitations: this slice does not evaluate switching hot loops or switch-node
copper union, oscillator/connector zones, return-plane continuity, process
retention, or mutate the board.

## Accepted: R6.5 switching hot-loop path and projected-area authority

`switching_hot_loop_ir.py` and `kicad/switching_hot_loop.py` consume a caller-
declared ordered cycle of at least three distinct physical terminal anchors and
one replay-valid routed-copper path per leg. The declaration restricts topology
to buck, boost, flyback, or other and binds graph/layout/netlist snapshots,
terminal roles and physical pad IDs, ordered terminal transitions, exact nets,
and every path-result fingerprint. Every path is reparsed and rederived;
branches require the existing explicit ordered-edge selection, adjacent legs
must match their declared terminal transition, and the last transition must
close the cycle. The evaluator never selects the visually smallest loop.

Exact-clean legs retain ordered nodes/edges/sources/layers, radical lengths,
vias, and track-only width/necks. Combined metrics retain the same authorities
and exact rational signed and absolute projected polygon area. The proven
simple-polygon checks reject repeated, backtracking, crossing, and zero-area
closures as `UNVERIFIED`; zone/contact/path uncertainty propagates without a
floating substitute. A fixture holds one-dimensional cluster span constant
while changing exact loop area, demonstrating why the old span surrogate is
insufficient.

Limit authority has two noninterchangeable modes. Advisory metrics remain
`ADVISORY` even if a numeric comparison would exceed a supplied value. A
`sourced_hard` maximum requires an exact rational threshold and a complete
`EvidenceApplicabilityBinding`: matching claim identity and full graph/
declaration/threshold context, every required condition matched, reviewer
identity, and pinned SHA-256 text/figure-verified applicable sources. Missing,
stale, or inapplicable authority is `UNVERIFIED`; equality passes and one exact
area unit above fails. Evidence/context, leg/order, topology/cardinality,
non-simple, branch, replay/tamper, construction-order, and input-immutability
cases are covered. Root review, 15 focused tests, and the 68-test switching/
decoupling/copper-graph/serialization gate are green; Ruff, strict production
mypy, and whitespace checks are green.

Limitations: the authority explicitly covers paths and projected area only. It
does not yet compute exact switch-node copper union, electromagnetic/impedance/
current performance, oscillator/connector zoning, return-plane continuity, or
board mutation.

## Accepted: R6.6 restricted exact switch-node copper union foundation

`switch_node_copper_ir.py` and `kicad/switch_node_copper.py` bind declared
switch-node nets/layers to one replay-valid routed-copper graph and complete
board/netlist snapshots. Explicit placed-pad records carry deterministic source
IDs, component/pad/net/layer identity, graph/snapshot fingerprints, and exact
planar compounds. A complete pad authority must cover every retained
`BoardNetlist` node on the declared switch nets exactly once. Tracks, vias, and
qualified exact filled zones are included automatically from the retained graph;
unknown fill reasons and every included or unsupported source remain visible in
source coverage.

Exact schema-v1 geometry is deliberately restricted to rational axis-aligned
pad rectangles, axis-aligned round-ended track capsules, circular vias, and
quarter-turn rectangle or disc final fills. Rectangle union uses an exact
rational slab sweep. Curved geometry contributes only when it is identical,
provably contained in one rectangle, or exactly disjoint/touching with zero
interior-area overlap. Each decision retains canonical identity, containment,
disjointness, or sweep witnesses. Diagonal tracks, nonrectangular pad polygons,
unsupported fills, and partial curved overlaps yield explicit unsupported
evidence and no numeric total.

Area is evaluated separately on each physical copper layer as the symbolic
exact value `rational_mm2 + pi_coefficient_mm2*pi`, then summed across layers.
Identical front/back geometry therefore counts twice; identical sources on the
same layer contribute once; and a via spanning front/back participates once in
each layer's union. The required fixture retains pad, track, via, and filled-zone
sources fully contained by one rectangle and proves the union equals the zone
area once on that layer. Disjoint symbolic sums, cross-layer counting, same-
layer deduplication, partial overlap, missing/incomplete pads, unknown fills,
snapshot/net/layer/source tamper, replay/order determinism, and immutability are
covered. Root review, 12 focused tests, and the 147-test graph/copper-removal/
fill/serialization adjacency gate are green; Ruff, formatting, strict
production mypy, and whitespace checks are green.

Limitations: this is a restricted union metric only. It defines no sourced
maximum-area policy, exclusion authority, electromagnetic/thermal/current
claim, or board mutation; unsupported geometry remains open rather than being
approximated.

## Accepted: R6.7 sourced switch-node copper-area policy

`switch_node_area_policy_ir.py` and `kicad/switch_node_area_policy.py` consume
and replay the complete restricted copper-union result without recomputing or
weakening its geometry authority. The policy and result retain the declaration,
nets, layers, complete source coverage, per-layer and total symbolic
coefficients, union evidence/result fingerprints, exact threshold, policy,
applicability binding, context, comparator input, and final result fingerprint.
Nested per-layer, total, source, evidence, threshold, context, and outer-result
tamper are rejected on replay.

The comparator never converts the symbolic `a + b*pi` result through binary
floating point or `libm`. A versioned integer-only decimal enclosure retains
`314159265358979323846 / 10^20 < pi <
314159265358979323847 / 10^20`, and exposes both the pi and resulting area
bounds. A sourced hard limit passes only when the upper bound is at or below
the maximum, fails only when the lower bound is above it, and otherwise remains
`UNVERIFIED`; the rational `b=0` case is exact, including equality. Unsupported
union geometry propagates without numeric bounds.

Advisory mode never becomes a hard violation even when its displayed threshold
is exceeded. Sourced-hard mode requires a threshold, matching claim identity,
at least one fully matched required applicability condition, no unmatched
condition, reviewer identity, the exact full-union/threshold context, and only
SHA-pinned, text/figure-verified, confirmed-applicable evidence. Missing,
unpinned, locator-unverified, inapplicable, condition-incomplete, reviewerless,
wrong-claim, or stale-context authority is `UNVERIFIED`, not failure.

Root source review and final gates are green: 23/23 focused and 131/131 adjacent
switch-union, graph, fill, semantic, and hot-loop tests. Ruff, formatting,
strict production mypy, and whitespace checks are green.

Limitations: this is a planar copper-area comparison only. It makes no
electromagnetic, thermal, current-capacity, exclusion, component-selection,
placement, or board-mutation claim and does not substitute for condition-
matched converter validation.

## Accepted: R6.8 explicit oscillator keepout-zone semantics

`oscillator_zone_ir.py` and `kicad/oscillator_zone.py` evaluate one explicit
discrete-oscillator declaration over complete canonical board-layout/netlist
snapshots and one exact board-coordinate zone. Oscillator/crystal/load-cap
references, oscillator and allowed nets/components/objects, caller-supplied
exact forbidden net-class membership, ground/stitch requirements, scoped I/O
separation, optional capacitance policy/model, and every evidence binding are
retained and replayed. An internal-module oscillator with no declared external
crystal zone produces a typed `NOT_APPLICABLE` result and cannot acquire
invented geometry.

Every supplied copper, pad, via, or zone object binds stable source identity,
layers, owner component/net, both snapshots, verification, and exact geometry
or a typed unsupported reason. Exact final zone fill additionally requires the
accepted active qualified-reader provenance with artifact hash and exact
geometry binding; zone intent or a rectangle-only declaration is unsupported.
Intrusion evidence is per explicit supplied object: foreign applicable copper
touching/overlapping the zone fails, disjoint exact copper passes, local allowed
oscillator/ground objects are separately not applicable, and unsupported
geometry is unverified. The result explicitly says this is not a complete board
object inventory, so omission cannot become a global zone-clear claim.

Reference-ground and stitch count/placement findings are independent. Ground
coverage is evaluator-derived, never caller numeric authority: schema v1 proves
10,000 basis points only when the complete zone compound lies inside one exact
qualified fill polygon, proves zero only for exact disjoint sets, and leaves
partial/multi-island/unknown fill `UNVERIFIED`. Optional proof records retain
only the replayed containment/disjoint predicate and reject forged values.
Stitch evidence retains exact via source IDs, layers, count, and zone relation;
count and placement can therefore pass/fail independently.

I/O distance uses the exact planar distance witness under an explicit scoped
threshold. Stray capacitance remains `UNVERIFIED` without an active qualified
stackup/model result bound to the exact snapshots, zone, supplied-object root,
calculated value, and complete evidence. Sourced hard requirements require a
reviewer, nonempty fully matched applicability conditions, and only SHA-pinned,
verified-locator, confirmed-applicable evidence. Advisory requirements cannot
hard fail.

Root source review and final gates are green: 8/8 focused and 63/63 oscillator,
antenna, semantic, and switch-node adjacency tests in about 1.9 seconds. Ruff,
formatting, targeted strict production mypy, bytecode compilation, and
whitespace checks are green.

Limitations: this is explicit-object zoning evidence, not raw-board ingestion,
a completeness certificate, parasitic extraction, EMC/RF validation, connector
zoning, return-path analysis, or board mutation.

## Accepted: R5.6c/d measured shaped-placement corpus

`kicad/placement_measured_corpus.py` runs two or more canonical case IDs through
the mandatory real-KiCad save/readback/DRC gate. Each case retains the complete
roundtrip authority, exact neutral counts and front/back placement state,
cutout/mask/outline presence, exact rational outline/bounding/substrate areas,
and a conservative rational routed-length interval derived from decimalized
neutral coordinates. Case and corpus fingerprints rederive after JSON;
input-order reversal and three independent live runs are identical.

The live KiCad 10.0.3 corpus contains a front/rotated octagonal routed board
with two vias and a flipped/back octagonal board with an exact cutout. Both are
DRC-clean. Root review strengthened the project policy: only installed-library
copy mismatch is ignored, while KiCad's other default-ignored footprint,
courtyard, track/via-centering, and tuning-profile checks are explicitly
enabled as warnings. The canonical DRC report is cross-checked to prove its
only ignored check is the retained library-copy policy. Ten nonlive and one
multi-run live corpus tests are green; Ruff and strict production mypy are
green.

Limitations: the corpus proves reproducibility and KiCad compatibility only.
It authorizes no placement-quality, optimization, performance, or algorithm-
superiority inference; real placement pilots remain open.

## Accepted: R4 bounded cost-aware LCS planning

`bus_lcs_cost_plan.py` adds the missing bounded planning decision ahead of the
accepted LCS physical-realization validator. The immutable input retains the
exact bus, capacity certificate, rule profile, normalized source/target
boundaries, one complete per-active-member capability record, policy, work
budgets, and fingerprints for every authority root. Capability records retain
pad-access layers, assigned outlier layer or explicit absence, contiguous inner
sections, source/target transition windows and costs, physical via count, and
required clearance domains.

The planner evaluates a fixed rectangular LCS table and a separately bounded
candidate frontier. Its objective is deterministic and ordered: maximize the
stationary member count, minimize total outlier cost, minimize maximum member
via count, minimize via-count spread, then choose the lexically smallest stayed
member-ID tuple. Work stops before a forbidden DP cell or candidate. Member,
activity, capability-set, portal, profile, layer-policy, transition-window,
pad-access, width, clearance-domain, lane-capacity, minimum-stay, per-member
via, and via-spread failures are typed.

Successful results retain target-ordered stationary members and outlier
excursions, exact source/target indices, bracketing sections and windows,
target-relative contiguous lane-slot claims for every section/layer, per-member
via counts, cost and work telemetry, the complete input, and a canonical plan
fingerprint. The result validator fully replans. Missing capability records do
zero work; stationary members cannot evade clearance-domain checks; and a
nonalphabetic physical order proves the final lexical semantic tie-break.
Root review, 21 focused tests, and the 100-test adjacent LCS/outlier/allocator/
physical gate are green; Ruff and strict production mypy are green.

Limitations: this is planning-only authority. It does not allocate the claimed
slots, materialize carriers, route copper, commit a board, run an exact checker,
or prove that a successful plan was consumed by the physical-realization path.

## Accepted: R4 cost-plan-to-physical-realization bridge

`kicad/bus_lcs_cost_physical_realization.py` now consumes a successful
cost-aware LCS result directly, without translating it through the older
lexical LCS decision. The complete replay input retains the cost plan, exact
lane allocation, transition replay authority, one certified physical prefix
per member, a separate validation budget, and fingerprints for every root.
It proves exact equality between planned section/member slot claims and the
allocator's assignments, then checks slot layer/order/width/clearance support,
outlier/stationary layer behavior, planned/allocation transition counts,
physical carrier identity, prefix authority, transition windows/directions,
and both planner and bus via policies.

During integration, root review confirmed a real contradiction in the first
cost-planner version: every section's claim used final-target order while the
allocator necessarily uses that section's normalized entry-boundary order.
The planner now retains section-entry physical claims while leaving its LCS
selection and cost objective unchanged. A direct regression proves the outer
section differs from final-target order, and a source `(a,m,z)` to target
`(m,a,z)` fixture proves the cost choice `(m,z)` is physically realized rather
than silently replaced by the legacy lexical choice `(a,z)`.

Successful results retain target-ordered per-member assignments, transition
events, carrier fingerprints, certified-prefix fingerprint, via count, work
telemetry, restricted authority scope, and full replay. Missing/extra/stale
allocation, authority, carrier, prefix, layer, transition, via-policy, and
budget cases fail with typed reasons before unauthorized claims. Root review,
36 focused tests, and the agent's 175-test R4 adjacency gate are green; Ruff
and strict production mypy are green.

Limitations: this reaches physical validation but still creates no copper and
has no route, board, commit, or exact-check authority. Predecessor planner,
allocator, and transition replays retain and enforce their own work budgets;
the bridge budget covers its assignment/member validation work only.

## Accepted: R4 cost-aware replay route and exact checked commit

`kicad/bus_lcs_cost_replay_checked_commit.py` closes the generic cost-aware
chain from one successful `BusLcsCostPhysicalResult` to the existing
replay-bound route and atomic checked-commit authorities. The opt-in
`BusLcsCostReplayRouteAuthority` requires exact identity of the bus, capacity
certificate, rule profile, allocation, transition replay input, lane registry,
initial occupancy, and every certified member prefix. When the allocation has
layer transitions, the retained route and physical transition budgets must
also be identical.

`commit_bus_lcs_cost_replay_exact` delegates materialization, transaction
semantics, rollback, and exact checking to the already accepted checked-commit
path. Its result retains both the complete cost/route authority and the
ordinary accepted, rejected, or checker-missing checked result; cost-plan or
physical success does not imply exact acceptance. Focused tests cover
successful acceptance, rejection, a missing checker, rollback, and nested
authority tamper; the combined cost/route/commit gate is green with warnings
as errors, and focused Ruff and strict production mypy are green.

Limitations: this remains one-shot and replacement-only. The generic chain is
not a thermometer `BusGroup` declaration, does not select a thermometer
candidate, and does not persist a KiCad file.

## Accepted: R4 exact-accepted neutral board-layout handoff

`kicad/bus_lcs_cost_board_handoff.py` adds a read-only consumer for the layout
already retained by an exact-accepted, committed cost-aware transaction. The
handoff requires the accepted disposition, committed state, and materialized
layout; retains the complete checked authority; stores the canonical frozen
`BoardLayout` snapshot plus both serialization and layout fingerprints; and
reparses the snapshot to prove exact equality with the nested checked layout.
Rejected, checker-missing, uncommitted, missing-materialization, and tampered
authorities cannot produce the handoff.

The schema explicitly excludes saved or rendered KiCad artifacts, filesystem
writes, manufacturability, verification beyond the retained exact checker, and
alternate-candidate selection. Focused and combined cost-aware chain tests are
green with warnings as errors; focused Ruff and strict production mypy are
green.

Limitations: this is neutral in-memory board-layout consumption only. No board
generator calls it, no `.kicad_pcb` is saved or rendered, and no real
thermometer artifact or pilot is established.

## Accepted: condition-matched live KiCad producer for the reduced R5 stem

`kicad/placement_readback.py` now treats KiCad 10's explicit
`(duplicate_pad_numbers_are_jumpers no)` footprint clause as the implicit false
default it represents; `yes` remains part of the closed semantic surface and is
detected. Live runs also stage exact vendored footprint sources into a
project-local KiCad library table, preventing a test-only library nickname from
being misreported as a board DRC violation while leaving the embedded board
geometry and retained DRC report authoritative.

The accepted capacity-two reduced-stem candidate was then rerun through the
installed KiCad 10.0.3 executable twice. Both saves are byte-identical, the
initial and saved closed semantic snapshots are equal, and DRC passes with no
findings. `test_reduced_stem_acceptance_uses_condition_matched_live_kicad_evidence`
builds the specialized save-roundtrip subcheck from that exact accepted final
layout, probe layout, netlist, and aggregate policy, replaces the earlier
nonlive KiCad subcheck, reevaluates the aggregate, rebuilds the manifest, and
rebuilds `PlacementPilotAcceptance` with the same accepted candidate. The
nonlive placement-readback suite is 15/15 green plus two explicit live skips;
the reduced-stem suite is 19/19 green plus one explicit live skip, and the live
condition-matched test passes when enabled.

This paragraph is superseded by the routing-only applicability correction
below. No circuit-to-board equivalence, thermometer readiness, or algorithm
superiority is claimed.

## Accepted: deterministic live reader/ERC evidence and routing-only simulation N/A

The reduced capacity-two stem now uses the manifest's backward-compatible
routing-only v2 policy. KiCad save/readback/DRC and reader netlist/ERC remain
required specialized producers. Thermometer ngspice is explicitly
`NOT_APPLICABLE`; the aggregate retains the typed nonblocking
`MissingSubcheckEvidence` generated by that policy and rejects any supplied
simulation record. The unrelated synthetic thermometer circuit and its
nonlive simulation producer were removed from the reduced fixture entirely.

The live reader producer runs two distinct drawings from the same retained
reduced-stem schematic model through KiCad 10.0.3. It retains the two schematic
texts, path- and time-neutral canonical netlist XML, canonical ERC JSON, exact
vendored footprint sources, executable hash, version, and logical operations.
ERC status/findings replay from retained JSON, ambient-only footprints fail
closed, stale reports cannot authorize, and managed cleanup is confined beneath
the named output root. Identical inputs now produce identical evidence on a
reused output root and on a different root. This proves the producer plumbing
and dual-drawing netlist equality; it is not an independent real-thermometer
reader reconstruction.

The v1/default manifest remains unchanged in applicability: a real thermometer
acceptance still requires passing condition-matched live ngspice evidence in
addition to live KiCad and live reader/ERC. Routing-only v2 cannot be used with
a v1 aggregate, cannot omit or rewrite its simulation N/A record, and cannot
accept a fake simulation producer.

## Accepted: R6.9 explicit connector-zone geometry and requirement semantics

`connector_zone_ir.py` and `kicad/connector_zone.py` evaluate caller-declared
connector roles over complete canonical board-layout/netlist snapshots, exact
connector-local body/pad compounds, source footprint and component identities,
an exact board-coordinate zone, and stable orientation-independent IDs for
actual segments of the shaped board outline. The shared placement-pose
authority applies exact front/back transforms; bounded arbitrary transforms
remain unverified.

Body-in-zone, pads-in-zone, body-in-board-material, pads-in-board-material, and
edge access are separate evidence and findings. Material checks use the actual
shaped outer polygon and exact cutouts. Edge access retains the exact rational
squared-distance witness to an actual outline segment and requires its stable
edge ID to be allowed; an optional exact distance threshold is compared without
a square root. The shared compound-to-segment kernel now correctly returns zero
for boundary intersection or a segment contained in filled geometry while
respecting holes. On-board modules make external connector-zone and edge rules
explicitly `NOT_APPLICABLE` rather than passing them vacuously.

Four typed optional requirements remain independent: explicit filter-chain
order, ground-pad count/spread, connector-to-oscillator separation, and exact
enclosure-access intersection. Missing supplied topology/region models are
`UNVERIFIED`; names and paths are never inferred. Advisory requirements remain
advisory. Every hard connector requirement, including filter order and
enclosure access as well as numeric thresholds, participates in the exact
layout/netlist/role/zone/edge/rule context fingerprint. Hard rule and effective
model sources must all be known, SHA-pinned, locator-verified,
confirmed-applicable, reviewer-backed, and bound to that context. Result replay
also retains those effective source IDs in its findings.

Root review, 11 focused and 30 combined connector/placement-geometry tests, and
the agent's 59-test focused/adjacent gate are green. Ruff and strict production
mypy are green.

Limitations: this consumes explicit supplied connector geometry and topology;
it is not raw-footprint or complete-board ingestion. It proves no cable,
enclosure, EMC, signal-integrity, current, filter-performance, or connector-
selection completeness and performs no board mutation.

## Accepted: R6.10 restricted exact return-adjacency evidence

`return_adjacency_ir.py` and `kicad/return_adjacency.py` bind complete selected
signal paths to the accepted routed-copper graph, explicit signal/reference
layer pairs, an exact net-class identity, and exact final reference-zone fills.
Caller-supplied reference geometry cannot replace graph authority: each fill
must match one unique graph zone source, final-fill record hash, reader,
artifact, layer, net, and deterministically reconstructed exact geometry.
Restricted v1 accepts axis-aligned rectangular and safely disjoint polygonal
or compound fills; curves, non-orthogonal rotations, holes, and compounds that
need a polygon-union kernel remain `UNVERIFIED`.

Track checks use conservative square-ended width envelopes, including both
end caps, and require containment in one exact reference polygon. Disjoint,
partial, and unsupported relations remain distinct, with exact witness
locations where the restricted kernel can derive them. Signal-layer
transitions are evaluated separately. Stitch evidence is limited to exact
reference vias already present in the same graph, and every selection must
refer to a transition on a declared retained leg and retained stitch evidence;
dangling, foreign, duplicate, or requirement-free selections are rejected.

The only hard geometric model is the fixed exact-containment model. Fixed 3W,
3h, and one-trace-width identities are advisory only and cannot carry hard
thresholds. Optional complete-coverage, lateral-distance, discontinuity-run,
and transition-stitch requirements require nonempty fully matched conditions,
a reviewer, exact full-context binding, and only SHA-pinned,
locator-verified, confirmed-applicable evidence. Replay retains the full
declaration, fills, stitch authority, segment/discontinuity/transition records,
findings, exclusions, and result fingerprint and rejects nested tamper.

Root review added unique graph-zone-source enforcement and reran 10/10 focused
tests with warnings as errors. Ruff and strict production mypy are green; the
agent's wider 122-test graph/fill/return adjacency gate is also green.

Limitations: this is a bounded planar adjacency proof, not field solving,
impedance, current, IR-drop, common-impedance, EMC, raw-board ingestion, a
complete-board reference-plane inventory, or board mutation.

## Accepted: R6.11 process-scoped dual-side retention evidence

`assembly_retention_ir.py` and `kicad/assembly_retention.py` evaluate an
explicit assembly-process profile over complete canonical board-layout and
netlist snapshots and an exact declared component inventory. Front/back
placement never implies process sequence: only an explicit coherent double-
reflow declaration identifies the side inverted during the second pass.
Every unknown process field remains unknown.

Per-component evidence retains exact integer mass in micrograms, source kind,
explicit joint IDs, exact total wetted-interface perimeter in micrometres,
method identity, package/pad/paste/void/orientation facts, component side,
footprint, both board snapshots, and source bindings. Body perimeter is
rejected as wetted perimeter. Missing mass or wetted geometry remains
`UNVERIFIED`; the ratio is retained as its exact numerator/denominator, with a
deterministic integer-only diagnostic decimal.

The narrow SAC305 experiment is fixed as an advisory hypothesis and cannot be
relabelled to another alloy. Sequence, inverted side, alloy, paste, finish,
stencil, aperture process, oven, peak, liquidus time, conveyor, turbulence,
carrier, adhesive, handling, package, pad, paste aperture, void, orientation,
required conditions, and excluded conditions must all match before even an
advisory comparison appears. A QFN/DFN or other package label alone has no
hard effect.

Hard pass/fail is available only from an active date-valid qualified assembler
rule bound to the exact assembler, board, process profile, component evidence,
package, threshold, restrictions, and covered process conditions with no
deviations. Review, rule, package-measurement, and process sources each require
their own nonempty fully matched, reviewer-backed, SHA-pinned,
locator-verified, confirmed-applicable binding whose claim ID and geometry
fingerprint match that exact object. The qualification SHA must occur in the
review source itself. Otherwise the result is `process_review_required`.
Mass, wetted perimeter, exact ratio, advisory applicability/comparison,
assembler evidence/verdict, and final disposition remain separate and replay.

Root review, 44/44 focused tests, and the agent's 83-test semantic/sensor
adjacency gate are green; Ruff and strict production mypy are green.

Limitations: this does not predict solder reliability, voids, thermal profile,
adhesive performance, or universal package safety and performs no board
mutation. Package/class-specific neighbor-overhang and post-tolerance gap use
the separate accepted authority below; neither authority supplies the other.

## Accepted: R6.12 package/class-specific neighbor overhang and copper gap

`neighbor_overhang_ir.py` and `kicad/neighbor_overhang.py` add a replay-bound
authority for explicit pad, terminal, and adjacent-copper geometry on complete
canonical board-layout and netlist snapshots. Exact micrometre-grid geometry,
package class, direction, tolerance model, active electrical clearance, rule
authority, review identity, and evidence bindings remain separate. Pad and
terminal evidence must belong to the subject component; adjacent copper may
truthfully belong to a different placed component. Fractional overhang is
measured against the smaller of terminal and pad span while retaining the
terminal, pad, reference, measured, and tolerance-adjusted witnesses.

Hard evidence bindings must match the exact reviewer-record identity. A
qualified-process authority cannot make a hard decision without its retained
qualification record and otherwise yields
`qualified_process_record_missing`; generic sourced geometry remains a
`HARD_GEOMETRY` rule rather than being promoted to qualified process. Exact
terminal/copper overlap is a clearance failure, not an unverified result.
Reviewer, source, process, geometry, tolerance, clearance, result, and
fingerprint tampering fail replay. The focused neighbor suite and combined
R6 semantic adjacency gates are green with warnings as errors; focused Ruff
and strict production mypy are green.

Limitations: this consumes explicit exact geometry and reviewed rules. It is
not automatic footprint/raw-board ingestion, solder-process prediction,
manufacturability certification, or board mutation.

## Accepted: R6.13 replay-bound R5/R6 semantic integration envelope

`semantic_integration_ir.py` retains one placement candidate and complete
probe layout/netlist snapshots, ordered semantic declarations, per-phase
evaluator records, optional final routed layout, R2 detail record, and exact
record. It keeps hard-geometry, qualified-process, validation, advisory,
route, and exact outcomes separate. Every semantic result's geometry identity
must equal its retained phase-layout snapshot, preventing placement/routed
geometry substitution.

The comparison key preserves the caller-supplied R5 primary-safety prefix and
quality suffix, then adds typed semantic blocking, validation, and advisory
terms. Advisory rank terms are opt-in and must equal one retained advisory
metric's fingerprint, unit, and exact rational value; callers cannot fabricate
or relabel a ranking value. Empty declarations preserve the existing R5 key
and require an explicit not-applicable semantic result. Focused tests cover
empty and nonempty integration, hard blocking, routed/exact retention,
geometry substitution, and advisory-rank tamper; focused Ruff and strict
production mypy are green.

Limitations: the envelope validates caller-supplied semantic evaluation
records; it does not itself invoke every semantic evaluator or prove that the
declared set is complete. The primary-safety prefix partition is explicit
caller policy authority. No real thermometer candidate has entered this
integration path.

## Accepted: isolated production-data `/PWLED` offline micro-pilot

The production-derived local crop binds only R17, D17, and `/PWLED`, retaining
their real thermometer identities and coordinates in a reversible local frame.
Its source authority pins and replays the exact vendored KiCad 10 R0603 and
LED0805 body and courtyard geometry. The only reviewed placement delta is R17
-0.5 mm on X, and exact-body/courtyard legalization returns `LEGAL_EXACT`.

The literal front-copper, via-forbidden R3 demand produces a complete 56-cell,
82-portal graph and a zero-overuse plan in 202 expansions. Two conservative
bounded-roundrect graph issues intentionally prevent an exact corridor guide;
the guidance disposition is therefore truthfully `INCOMPATIBLE`, with `/PWLED`
unguided and no R3-guided-routing claim. The explicitly authorized ordinary-R2
fallback succeeds in 271 expansions and produces exactly five `/PWLED` F.Cu
segments and zero vias.

Serialization proves that the only changed fields are R17's pose and `/PWLED`
segments. The condition-matched offline aggregate contains virtual DRC and empty
design checks, both passing. Deterministic rebuild/JSON replay and nested tamper
tests bind the execution and reject substituted placement, copper, fingerprints,
or expanded claims.

The exact resource cliffs are also pinned: graph construction succeeds at a
120-cell/82-portal budget and fails closed at 119 cells or 81 portals; R3
planning succeeds at 49 expansions and fails at 48; ordinary R2 succeeds at
271 and fails at 270. The focused offline execution file records 19 passes and
one opt-in skip under the default environment, with its adjacent focused tests
green.

A separate opt-in KiCad 10 test materializes the accepted local result and
passes exact save/read-back, byte-identical repeated save, and DRC with zero
findings. This evidence intentionally remains external to the deterministic
offline execution wrapper, whose `kicad_live_checked` field remains false.

This acceptance is deliberately narrow. Every full-board, full-template,
fixed-neighbor, circuit/board-equivalence, thermometer-readiness,
R3-guided-routing, routing-superiority, reader, simulation, and live-KiCad claim
inside the offline wrapper is false. The separate live test does not broaden
that wrapper or imply reader/simulation evidence. It is not the 64-placement
thermometer pilot, a persisted production artifact, a default-caller migration,
or R7 completion. No full-board acceptance claim is made.

Focused offline gate:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error tests/unit/kicad/test_thermometer_pwled_micro_pilot.py tests/unit/kicad/test_thermometer_pwled_micro_pilot_execution.py
```

Separate live gate:

```powershell
$env:PCBSMITH_PWLED_MICRO_KICAD_GOLDEN='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -W error tests/unit/kicad/test_thermometer_pwled_micro_pilot_execution.py
Remove-Item Env:PCBSMITH_PWLED_MICRO_KICAD_GOLDEN
```

## Final combined-tree verification checkpoint

The final combined worktree was collected as 2,560 tests across 198 test files.
The complete default offline suite exited successfully in 843.6 seconds with
its intentional opt-in skips; this count is the collected population, not a
claim that opt-in cases ran under the default environment. Whole-tree Ruff
passed for `src` and `tests`, and strict mypy passed all 232 production source
files. The independent `/PWLED` live gate was then rerun with
`PCBSMITH_PWLED_MICRO_KICAD_GOLDEN=1` and passed exact KiCad 10 read-back,
byte-identical repeat save, and DRC with zero findings.

The final regression also resolved three compatibility observations without
broadening authority: the empty-board snapshot now reflects intentional
removal of the legacy `(net 0 "")` clause; typed mask apertures use the same
raw-board graphic renderer and occurrence ledger as equivalent raw graphics;
and embedded footprint pads retain KiCad 10's canonical named-net form. A live
KiCad A/B save proved numeric-plus-name and named-only pad-net inputs normalize
to byte-identical named-only output, so no R2 or reduced-pilot fingerprint
migration was required.

## Still open after this supplement

- Persisted board-generator consumption of the accepted cost-aware neutral
  layout handoff, including an actual saved/read-back KiCad artifact if that
  authority is required; the generic route/commit/exact and read-only layout
  handoff are complete;
- R5 full-thermometer placement declarations and pilot, condition-matched live
  ngspice, and any applicable reader/simulation evidence for the isolated
  `/PWLED` result (its separate live KiCad save/read-back/DRC gate passes; the
  reduced routing fixture's simulation is correctly N/A);
- R6 source-approved antenna exceptions and real condition-matched RF
  campaigns, plus real-thermometer semantic declarations/evaluations through
  the accepted generic integration envelope;
- the full 64-placement thermometer R7 pilot, persisted exact-accepted board,
  complete live/semantic/reader/simulation gates, and final visual review. The
  open-source tooling backlog, handoff reconciliation, and final combined-tree
  regression are recorded; they are no longer repository-wide gate gaps.
