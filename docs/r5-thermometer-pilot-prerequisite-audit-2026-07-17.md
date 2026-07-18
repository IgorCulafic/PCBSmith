# R5.7 thermometer pilot prerequisite evidence audit — 2026-07-17

## Scope and verification basis

This is a read-only prerequisite audit of the current worktree. It does not
select a placement algorithm, define thermometer pilot defaults, generate a
board, or claim that R5.7 is ready.

The audited requirements are the eight firing steps at
`docs/r5-placement-routability-design-2026-07-15.md` lines 819–830 and the ten
integration prerequisites at lines 837–861. Statuses below describe current
evidence, not the design document's intended future state.

The audit collected 387 focused tests. After the intentional
deterministic-UUID/KiCad-10 named-net serializer migration was reconciled in
the R2 golden, the combined run produced 383 passes, four environment-gated
skips, and no failures. The compact serialized board now repeatably pins
SHA-256
`57a7a75093b056971ca37651d6227806d896b02da56c9a062cef0738fe2bb505`;
its live KiCad 10.0.3 DRC/read-back golden also passes when enabled. The 28 R2
unit tests and 29 thermometer composition, board-invariant, and reader tests
pass independently. With
`PCBSMITH_R5_KICAD_GOLDEN=1`, all 27 placement read-back and measured-corpus
tests pass against installed KiCad 10.0.3.

Status meanings used below:

- `PROVEN`: the stated prerequisite or firing step has direct current evidence.
- `NARROWLY_PROVEN`: a generic or smaller part is proven, but not the complete
  thermometer prerequisite.
- `OPEN`: required evidence or thermometer source declarations are absent.
- `BLOCKED_BY_PREDECESSOR`: the row cannot close before an explicitly unfinished
  predecessor closes.

## Ten thermometer integration prerequisites

| Requirement | Status | Exact production symbols and focused tests | Authority actually established | Smallest missing evidence | Dependencies |
|---|---|---|---|---|---|
| 1. Opt-in R2 board-generator caller, exact checker, and serialized maze authority | NARROWLY_PROVEN | `pcbsmith.kicad.negotiated_board.route_board_negotiated`, `route_board_corridor_guided`, `ExactRouteCheckResult`, `ExactRouteCheckEvidence`, `NegotiatedBoardRouteResult`; `pcbsmith.kicad.corridor_exchange_execution.execute_prepared_corridor_exchange`; `tests/unit/kicad/test_negotiated_board.py` (25), `tests/unit/kicad/test_negotiated_board_maze.py` (3), `tests/unit/kicad/test_corridor_exchange_execution.py::test_prepared_execution_drives_real_r2_orchestration_once_per_replay`, `tests/golden/test_r2_negotiated_kicad.py` (2) | R2 is opt-in; its exact verdict is separate from algorithmic success; exact inputs/findings are replay-bound; R3 preparation can fire the real R2 orchestration; the adversarial maze is unit-tested. The compact KiCad-10 named-net serialization is deterministic, readable, SHA-pinned, and live-DRC/read-back proven. | A board-generator opt-in caller that combines the existing maze authority, exact checker, serialization, read-back, and DRC for one identical routed input. The compact serialization golden is not itself a serialized maze proof. | Real KiCad live gate. No R4/R6 dependency for the narrow R2 proof. |
| 2. R3 graph, quantity ledger, shaped portal capacity, soft R2 guidance, and verified summary fire on a narrow stem | PROVEN | `build_corridor_graph`, `negotiate_corridor_allocations`, `verify_corridor_plan_summary`, `build_corridor_route_guide`, `project_corridor_route_guide`, `route_board_corridor_guided`; `tests/fixtures/routing/reduced_capacity_two_stem.py`; `tests/unit/kicad/test_reduced_capacity_two_stem.py` and `test_reduced_stem_placement_acceptance.py` | One shaped two-net fixture binds the source layout/netlist, exact named F.Cu portal interval, 20 raw capacity units, two eight-unit demands, quantity capacity two with four residual units, zero-overuse allocation, replay-verified summary, projected guidance, and a deterministic routed R2 result. Both nets independently replay-check connected through the physical stem with no vias; actual work is 367 expansions each. The complete reduced result is composed into placement acceptance with live applicable KiCad and reader/ERC producers. Reducing only the portal to 15 units yields its sole one-unit overuse; a 733 total R2 budget fails one expansion before completion. | None for this reduced synthetic prerequisite. Translation to thermometer-specific declarations remains open. | R2 prerequisite 1 for eventual thermometer board authority. No R4/R6 dependency for the reduced fixture. |
| 3. Exact lossless body and courtyard geometry for every movable thermometer footprint; unsupported references excluded | OPEN | Generic geometry/legalization authorities and tests; `tests/unit/kicad/test_thermometer_pwled_micro_pilot.py` | The R17/D17 micro-pilot pins and replays exact vendored KiCad 10 R0603/LED0805 body and courtyard geometry. The remaining thermometer library footprints expose only the older catalog data. | Extend exact source-bound geometry or explicit unsupported declarations beyond the literal R17/D17 crop. That crop is not every movable thermometer footprint. | Thermometer-specific footprint source data. No R4 dependency. |
| 4. Shared front/back transform passes asymmetric arbitrary-angle fixtures | PROVEN | `pcbsmith.placement_geometry.transform_point_bounded`, `transform_compound_bounded`, `transform_compound`; `tests/unit/test_placement_geometry.py::test_arbitrary_front_back_transform_is_pinned_but_not_called_analytic_exact`, `::test_bounded_arbitrary_transform_contains_pinned_37_degree_nominals`, `::test_reflection_recanonicalizes_winding_and_preserves_asymmetric_point_set`; `tests/unit/kicad/test_placement_legalization.py::test_far_front_and_back_arbitrary_placements_are_legal_bounded` | Front/back 37-degree asymmetric transforms have deterministic bounded rational authority; back reflection is canonical; quarter turns remain exact; legalization consumes the shared transform. | None for this prerequisite. Thermometer footprint catalog coverage remains prerequisite 3, not a transform gap. | None. |
| 5. Thermometer template probe preserves outline, graphics, mask, zones, fixed copper, labels, flips, and router inputs | OPEN | Generic symbols: `build_placement_probe`, `PlacementProbe`, `build_placement_pose_authority`, `build_placement_serialization_authority`, `PlacementSerializationAuthority`; `tests/unit/kicad/test_placement_routability.py` (7), `tests/unit/test_placement_pose_authority.py` (30), `tests/unit/kicad/test_placement_serialization.py` (51) | Generic probes preserve every reflected `BoardLayout` field except six declared pose/target-route fields, reject future unclassified fields, preserve fixed copper, and serialize a shaped sentinel. | Run the actual `_unrouted_layout` thermometer template through a no-change/base probe and a bounded declared-move probe, and separately bind every non-`BoardLayout` router input. Current thermometer mask, zones, cutouts, and fixed copper are empty, so preservation must truthfully prove emptiness rather than imply populated data. | Prerequisite 3 for moved-candidate legalization; thermometer router declarations from prerequisite 6. |
| 6. Explicit fingerprinted profile, widths, target set, clearance groups, R2/R3 grids, policies, and budgets | OPEN | Generic policy/budget types; `tests/unit/kicad/test_thermometer_pwled_micro_pilot.py`; current full-board width symbols | The `/PWLED` micro-pilot binds its 0.25 mm target width, grids, front-only/via-forbidden demand, move policy, and bounded R3/R2 budgets. The legacy full-board caller separately supplies widths/order entries and `max_restarts=16`. | Extend the reviewed authority to the full intended thermometer subset, including all effective widths, clearance groups, bus/order policy, and every applicable stage budget. The micro-pilot values are not default authority. | Thermometer-specific policy review. R4 declarations affect bus/order policy; real KiCad does not choose these values. |
| 7. SEG/control groups and allowed order/reversal declared before order metrics | OPEN | Generic order-surrogate symbols plus the physical-swap plan/composition/candidate/transaction/checked-commit chain, `plan_bus_lcs_cost`, `validate_bus_lcs_cost_physical_realization`, `commit_bus_lcs_cost_replay_exact`, and `consume_accepted_bus_lcs_cost_board_layout`; physical-swap, LCS-cost/physical, replay/commit, and handoff focused suites | Declared order/reversal metrics are fail-closed. The generic cost-aware LCS path now plans, binds exact physical realization to the replayed route, preserves atomic exact acceptance/rollback, and exposes only the accepted neutral `BoardLayout`. It explicitly does not save or render a KiCad artifact. | Thermometer `BusGroup`/boundary declarations for `/SEG1`–`/SEG16` and `/SER`, `/SRCLK`, `/RCLK`, `/OE`, including allowed reversal/permutation, followed by a thermometer-specific authority instance. | Thermometer declarations and application. Generic R4 plan-to-route/commit/exact/handoff is no longer the blocker. |
| 8. Explicit or exact-body-derived USB-C, DFN, and TSSOP escape vectors with ambiguity telemetry | OPEN | Generic symbols: `PlacedTerminalCopper`, `EscapeRay`, `PinEscapeEvidence`, `evaluate_placement_surrogates`; `tests/unit/kicad/test_placement_surrogates.py::test_blocked_first_transition_and_rotation_exposing_escape_fire`, `::test_off_grid_stub_is_diagnostic_but_not_unroutable`, `::test_escape_obstacles_are_exact_filled_layer_scoped_compounds_with_holes` | Cardinal escape alternatives, constrained portal IDs, off-grid residuals, zero-alternative failures, and ambiguity counts are deterministic and typed. | Terminal-level escape declarations or an exact derivation adapter for J1's 0.5 mm USB-C pads, U4's 0.5 mm DFN pads, and U2/U3's 0.65 mm TSSOP pads, bound to actual side/rotation and complete obstacles. | Prerequisite 3 if vectors are body-derived; thermometer pad/source data otherwise. |
| 9. Stable aggregate exact checker for virtual DRC, design checks, connectivity, reader equality, simulation, and KiCad DRC | NARROWLY_PROVEN | Existing aggregate/manifest symbols, reduced-stem live acceptance, and `tests/unit/kicad/test_thermometer_pwled_micro_pilot_execution.py` | The capacity-two reduced stem passes its condition-matched live gates. The production-derived `/PWLED` micro-pilot passes its offline aggregate and a separate opt-in KiCad 10 exact read-back/repeated-save/clean-DRC test. Reader, simulation, and live-KiCad claims inside the offline wrapper remain false. | Construct full-thermometer authority with condition-matched live ngspice, reader, and R6 evidence; keep the separate live micro-pilot record scoped literally. | Full thermometer declarations, live ngspice, reader, and applicable R6 evidence. |
| 10. Reviewed fixed pilot budget for a bounded subset of the 63-part search | NARROWLY_PROVEN | Generic budget authorities and boundary tests; both `/PWLED` micro-pilot test files | The reviewed literal subset is R17 movable, D17 fixed, and `/PWLED` targeted; it records move/grid/capacity and R3/R2 budgets plus actual 202/271 expansion work. | Review budgets and declarations before any expansion beyond R17/D17 and `/PWLED`; the accepted values are not full-board defaults. | Prerequisites 3 and 6. R4 if an expanded subset uses order/swap metrics. |

## Eight R5.7 firing steps

| Firing step | Status | Exact production symbols and focused tests | Authority actually established | Smallest missing evidence | Dependencies |
|---|---|---|---|---|---|
| 1. Preserve current outline, 63 identities, side split, graphics, labels, mounting hole, widths, and order inputs in the base probe | OPEN | Thermometer source: `PLACEMENTS`, `FLIPPED_REFS`, `REFERENCE_AT`, `thermometer_outline`, `thermometer_silk_graphics`, `_hanging_hole`, `_unrouted_layout`, `FINE_PITCH_NETS`, `compute_thermometer_board_layout`; `tests/unit/kicad/test_thermometer_board.py` (6); generic probe/serialization suites above | Current static thermometer invariants are tested, and generic probes preserve their synthetic templates. No thermometer base probe exists. | Construct and replay a no-change thermometer probe that retains all 63 netlisted identities plus H1 and a separate fingerprinted router-input envelope. | Prerequisites 3, 5, and 6. |
| 2. Move only a small declared register/resistor/LED stem set | NARROWLY_PROVEN | Generic candidate/legalization authorities; both `/PWLED` micro-pilot test files | The production-derived local subset fixes D17, moves only R17 by reviewed -0.5 mm on X, returns `LEGAL_EXACT`, passes exact resource cliffs, and has separate opt-in live KiCad evidence. | Expand only after defining the next exact movable set, fixed neighbors, target routes, policies, and budgets. | Literal R17/D17 prerequisite-3 and prerequisite-6 evidence; no bus-order metric is used. |
| 3. Demonstrate shorter-HPWL/overloaded-portal behavior before trusting HPWL | NARROWLY_PROVEN | `evaluate_placement_surrogates`; `pcbsmith.kicad.placement_detail._primary`, `_secondary`, `_fronts`; `tests/unit/kicad/test_placement_surrogates.py::test_shorter_hpwl_portal_overload_stays_separate_from_longer_zero_overflow`; `tests/unit/kicad/test_placement_detail.py::test_absent_corridor_evidence_cannot_rank_as_ready_zero_overflow` | The surrogate retains a shorter HPWL with nonzero portal overflow separately from a longer zero-overflow case; detail selection puts corridor readiness/overflow in the primary vector and HPWL in the secondary key. | One end-to-end selection test using those same two candidates and a replay-bound verified R3 summary, directly asserting that the longer zero-overflow candidate ranks ahead. | Prerequisite 2. |
| 4. Score declared SEG/control order without inferred bus semantics | OPEN | `BusBoundaryOrderObservation`, `BusOrderEvidence`, `evaluate_placement_surrogates`; declared inversion/reversal test named in prerequisite 7; accepted generic R4 cost-aware route/commit/handoff chain | The evaluator scores only caller-supplied member order and allowed reversal; absent declarations produce no guessed conflict. Generic R4 physical realization, route, atomic exact commit, and neutral layout handoff are available. | Thermometer bus/boundary/order declarations and their mapping to observed physical boundaries. | Thermometer prerequisite 7; no unfinished generic R4 predecessor remains. |
| 5. Route a deterministic Pareto subset through R3-guided R2 | NARROWLY_PROVEN | Existing detail adapter, reduced-stem acceptance, and the `/PWLED` execution test | The synthetic reduced stem proves the guided chain. The real-data `/PWLED` candidate produces a zero-overuse R3 plan, but exact guidance is truthfully `INCOMPATIBLE`; its explicitly authorized ordinary-R2 fallback routes in 271 expansions. It makes no R3-guided or superiority claim. | Resolve or formally retain the guidance boundary for the next subset; do not relabel this fallback as R3-guided routing. | Literal micro-pilot prerequisites 2, 3, 6, and 10; full-board prerequisites remain open. |
| 6. Require zero overuse, connectivity, virtual/design/read-back/simulation/KiCad checks | NARROWLY_PROVEN | Existing exact/aggregate/live-producer symbols, reduced-stem acceptance, and the `/PWLED` execution test | The reduced stem passes its live gates. The `/PWLED` micro-pilot has zero overuse, five F.Cu segments, zero vias, passing offline checks, and a separate opt-in KiCad 10 exact read-back/repeated-save/zero-finding DRC pass. Reader, simulation, and live-KiCad claims in the offline wrapper remain false. | Run any applicable reader/simulation evidence and the full thermometer with condition-matched live ngspice and R6 evidence. | Full thermometer declarations, ngspice, reader, and semantic integration. |
| 7. Pin candidate, corridor, route, report, and rendered-board fingerprints | NARROWLY_PROVEN | Existing authorities, reduced-stem live producers, and both `/PWLED` micro-pilot test files | The `/PWLED` execution fingerprint, replay, and tamper tests bind the offline result. The separate live test proves exact read-back and byte-identical repeated save but intentionally does not mutate the offline wrapper's false live flag or claim a persisted production board. | Create a distinct retained live authority or production artifact only if later scope explicitly requires one. | Thermometer firing steps 1, 5, and 6. |
| 8. Expand scope only after work/failure evidence remains reviewable | NARROWLY_PROVEN | Generic telemetry, reduced-stem evidence, and both `/PWLED` micro-pilot test files | The real-data micro-pilot retains its 202-expansion R3 plan, exact graph/R3/R2 cliffs, `INCOMPATIBLE` guidance, 271-expansion fallback, five segments, zero vias, offline checks, serialization delta, replay, and separate live result. This does not authorize expansion. | Declare and review each wider subset before execution. | Thermometer firing steps 1–7; prerequisite 7 if ordered-bus behavior is included. |

## Current thermometer generator and artifact inventory

### Post-table authority update: cost-aware chain and live reduced-stem evidence

The tables above have been reconciled to the accepted implementation state.
The following notes make the remaining scope boundaries explicit:

- Requirement 7 now has the complete generic cost-aware path through bounded
  planning, exact physical realization, replay-bound route authority, atomic
  checked commit, and a read-only exact-accepted `BoardLayout` handoff. The
  handoff explicitly excludes saving, rendering, filesystem writes,
  manufacturability, and verification beyond the retained exact checker. The
  requirement remains `OPEN` for the thermometer because its `BusGroup`,
  boundary, order/reversal, and authority-instance declarations are absent;
  unfinished generic R4 integration is no longer the blocker.
- Requirement 1 is still only `NARROWLY_PROVEN`: the new cost-aware consumer
  exposes an accepted neutral layout but no board generator consumes it and no
  `.kicad_pcb` artifact is saved, rendered, or read back from that handoff.
- Requirement 9 now has both applicable condition-matched live producers. The identical
  accepted reduced-stem layout/netlist passes real KiCad 10.0.3 parse/save,
  closed semantic read-back, a second byte-identical save, and clean DRC.
  Its two distinct retained schematic drawings also pass real KiCad ERC and
  export the exact accepted netlist; canonical XML/ERC evidence is repeatable
  across reused and different output roots. The routing-only v2 manifest makes
  thermometer simulation explicitly `NOT_APPLICABLE` and retains a typed N/A
  record, so no unrelated ngspice result is used.
- Firing step 6 therefore includes live KiCad and live reader/ERC for every
  applicable reduced-fixture producer. This does not satisfy the real
  thermometer: v1 still requires condition-matched live ngspice plus applicable
  R6 semantic evidence. Firing step 7 additionally pins the real tool versions,
  executable/dependency identities, board hashes, repeated-save hash, semantic
  snapshots, and canonical DRC/ERC reports. Firing step 8 remains synthetic and
  cannot authorize thermometer expansion.

| Inventory item | Verified current state |
|---|---|
| Composition and schematic | `pcbsmith.generation.thermometer.compose_thermometer` produces 63 circuit components. `pcbsmith.kicad.export_thermometer.INSTANCES` supplies the machine schematic table; `THERMOMETER_READER_SPEC` supplies the human reader schematic. The reader equality test is `tests/unit/kicad/test_reader_schematic.py::test_thermometer_reader_spec_reproduces_the_machine_table`. |
| Board generator | `pcbsmith.kicad.thermometer_board._unrouted_layout` builds the static template. `compute_thermometer_board_layout` still calls legacy `route_board`, not R5/R3-guided R2. `generate_thermometer_board` exports the schematic netlist, routes, and renders. |
| Physical placement count and side split | `PLACEMENTS` contains the same 63 schematic references. `_hanging_hole` adds H1, so the board has 64 physical placements. `FLIPPED_REFS` contains 39 back-side references. Therefore the physical board has 39 back and 25 front placements; the 63 schematic components split 39 back and 24 front, with front-side H1 outside the schematic netlist. |
| Shape and preserved board fields | The template is 46 mm by 158 mm. `thermometer_outline()` returns 93 vertices. It contains 266 raw board graphics, four `part_reference_at` entries, 39 flips, and H1. It currently contains zero cutouts, zero typed mask apertures, zero zones, zero segments, and zero vias. Consequently there is no pre-existing fixed copper in the unrouted template. |
| Footprint availability | The 63 schematic components use 12 unique loaded library footprints: 27 R0603, 17 LED0805, five C0603, three C0805, two 1x04 headers, two TSSOP-16, two test points, and one each USB-C, 1206 fuse, SOT-23-5, ESP32-C3-WROOM-02, and SHT31 DFN. H1's mounting-hole footprint also loads. Every loaded spec exposes `fab_rect` and a nonempty `courtyard_hull`, but no thermometer `PlacementGeometryCatalog` exists and the hulls are not accepted as exact-lossless R5 geometry by this audit. |
| Nets and target declarations | The live composition-derived board netlist has 53 named nets. `FINE_PITCH_NETS` declares 11 width-prioritized nets: `/DP`, `/DM`, `/VBUS`, `/VBUSF`, `/CC1`, `/CC2`, `/SDA1`, `/SCL1`, `/CAS`, `/VCC`, and `/GND`. No R5 target-net set has been selected. |
| SEG/control declarations | `/SEG1`–`/SEG16`, `/SER`, `/SRCLK`, `/RCLK`, and `/OE` exist and receive 0.2 mm widths in `compute_thermometer_board_layout`; the four control nets are also a legacy `net_order`. There is no thermometer `BusGroup`, `BusBoundary`, allowed order/reversal declaration, or `BusBoundaryOrderObservation`. |
| Profile, grids, clearance, and budgets | The legacy route uses the default `PcbRuleProfile`, `SIG_W=0.25`, `POWER_W=0.4`, the widths above, no caller clearance groups, and `max_restarts=16`. The comments describe a 0.1 mm fine pass and 0.2 mm main pass inside `route_board`, but no fingerprinted thermometer R3 grid, R2 grid, negotiated cost policy, placement budget, detail budget, or exact budget exists. |
| Checks and simulation | `thermometer_checks_spec` declares power currents, component cards, tie nets, connector exceptions, and allowed open pins. The CLI separately runs ERC, reader equality, `run_thermometer_simulation`, design checks, virtual/KiCad board authority, and review packaging. These are not combined under a stable placement exact-checker ID. |
| Source evidence | `ai_assets/evidence/thermometer.manifest.json` SHA-pins five local datasheets for SHT31, ESP32-C3-WROOM-02, SN74HC595PW, AP2112K-3.3, and the Kingbright LED. Its extraction jobs are still marked `pending_extraction`. |
| Checked-in generated/golden artifacts | No thermometer `.kicad_pcb`, `.kicad_sch`, `.kicad_pro`, rendered image, simulation output, or thermometer-specific file is present in `tests/golden`. The CLI can generate them, but none is a current checked-in R5.7 authority artifact. The only checked-in thermometer artifact outside code/tests/docs found by name is the evidence manifest above. |
| Recorded audit regression baseline | The thermometer composition/board/reader group was 29/29 green. The recorded 387-test prerequisite matrix was 383 passed, four environment-gated skips, and zero failures. The R2 compact serialization/read-back golden passed against live KiCad 10.0.3 when enabled, and the real R5 KiCad read-back/corpus group was 27/27 green when explicitly enabled. Later accepted slices have their own focused gates; this row is not a claim that a new full-repository regression has run. |

## Earliest safe next slice

### Accepted isolated `/PWLED` update — 2026-07-18

The production-derived R17/D17 `/PWLED` local crop has advanced beyond input
authority and now completes a narrowly bounded offline execution. It uses exact
vendored R0603/LED0805 body and courtyard geometry; moves only R17 by reviewed
-0.5 mm on X with `LEGAL_EXACT`; builds a 56-cell/82-portal, F.Cu-only,
via-forbidden, zero-overuse R3 plan in 202 expansions; and truthfully marks
exact corridor guidance `INCOMPATIBLE` because of conservative bounded-roundrect
issues. The explicitly authorized ordinary-R2 fallback succeeds in 271
expansions with five `/PWLED` F.Cu segments and zero vias.

Serialization proves that only R17's pose and `/PWLED` segments changed. Offline
virtual DRC and empty design checks pass, and deterministic replay plus tamper
rejection are covered. This does not establish full-template or fixed-neighbor
preservation, circuit/board equivalence, reader or simulation checks,
thermometer readiness, routing superiority, a persisted production artifact/
default migration, or R7 completion. The offline wrapper retains a false live
flag. Separately, exact boundary tests pin graph 120 cells/82 portals against
one-less 119/81, R3 planning 49 against 48 expansions, and R2 271 against 270.
An opt-in KiCad 10 test passes exact read-back, byte-identical repeated save,
and clean DRC with zero findings.

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

The reduced synthetic narrow-stem R5 consumer now exists and is accepted. The
following earlier authorities remain useful predecessors and regression
fixtures:

- `tests/unit/kicad/test_corridor_guided_shaped.py` provides a deterministic
  shaped one-net `BoardLayout`/`BoardNetlist`, exact terminal footprint,
  target width, coarse/detailed grids, R3 graph and plan, projected guide,
  R2 result, virtual/connectivity exact checker, and pinned fingerprints. Its
  geometry is a U-notch bottleneck, not the required capacity-two
  thermometer-like stem.
- `tests/unit/kicad/test_placement_surrogates.py` provides replay-bound R3
  summaries, portal-overload evidence, the shorter-HPWL/overloaded case,
  declared order observations, terminal escape rays, and ambiguity/off-grid
  telemetry.
- `tests/unit/kicad/test_placement_detail.py` provides deterministic Pareto
  selection, `KiCadPlacementR2Evaluator`, target-route replacement,
  fixed-copper preservation, R3/R2 budgets, and fresh evaluation-order
  behavior.
- `tests/unit/kicad/test_placement_readback.py` and
  `tests/unit/kicad/test_placement_measured_corpus.py` provide the current real
  KiCad 10.0.3 serialization/read-back/DRC authority gate for shaped synthetic
  boards.

The accepted reduced-stem consumer retains the complete synthetic input envelope,
two candidate/probe/surrogate records, available R3 graph/plan authority, one
734-expansion zero-overuse R2 result, exact/aggregate/manifest evidence, and
condition-matched live KiCad plus live reader/ERC producers. Its routing-only v2
policy records thermometer simulation as typed `NOT_APPLICABLE`; there is no
synthetic or unrelated ngspice producer. The isolated real-data `/PWLED` route
above does not close the remaining full-thermometer geometry, escape, bus/order,
policy, budget, or semantic declarations. The earliest safe next slice is
review of the separate live evidence followed by deliberate expansion only
after the literal micro-pilot remains reviewable. A full thermometer run
remains blocked by the remaining declarations; full-board application of the
accepted generic R4 chain; condition-matched live ngspice; and the still-open
source-approved antenna exceptions, real RF campaign evidence, and
thermometer-specific R6 semantic declarations/evaluations. Generic return
adjacency, process retention, neighbor-overhang, and R5/R6 integration
authorities exist, but no real thermometer candidate has supplied their
required evidence or entered the integration envelope. The ordinary-R2 fallback
is authorized only for the literal `/PWLED` micro-pilot and is not a default
algorithm choice or superiority result. Nothing in this audit establishes
readiness to run the full board.
