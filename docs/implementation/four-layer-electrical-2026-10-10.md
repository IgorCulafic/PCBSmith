# Four-layer electrical analysis — October 10, 2026

The user authorized continuing toward a finished board until a genuine blocker and selected **standard factory fabrication** for the first four-layer example. This update completes the routed-track electrical model and identifies the remaining filled-plane integration blocker. **No finished four-layer board is delivered.** The retained native fixture remains a software test, with no new board acceptance or manufacturing claim.

## Implemented and checked

- Routed graphs retain the physical F.Cu/In1.Cu/In2.Cu/B.Cu order in their replay-bound identity. Inner copper requires an explicit stack; changing even an unused stack invalidates its fingerprint. Existing two-layer serialization keeps its default field omitted.
- Through-vias and plated pads connect all declared copper layers. A star representation avoids fictitious parallel paths. Path metrics count each physical barrel once, including an In1-to-In2 path that traverses two graph edges. Planar path length excludes barrel depth.
- Exact contact splitting also handles vias landing on the interior of inner-layer tracks. Coincident points on different layers remain disconnected without actual interlayer copper.
- Source-bound return contexts require a matching physical stack and genuinely adjacent layer pairs. F.Cu cannot claim B.Cu as its adjacent reference on a four-layer board. The existing restricted exact fill/slot checks now accept inner reference layers.
- Signal transitions coalesce the graph's barrel spans before comparing reference layers and stitch proximity. This prevents a fictitious reference change at the graph hub. Stitch evidence remains bound to the actual physical source and its layer span; proximity alone is not proof of connected reference planes.
- The production decoupling adapter passes the actual profile stack into its graph. Native terminal readback now supports orthogonal footprints on either outer face, using saved pad coordinates and exact net membership. An independent KiCad comparison checks 16 pad positions across both faces and four rotations.

## Verification and retained evidence

The focused electrical and downstream regression run passes **278 tests, zero failures/errors/skips**, in 15.029 seconds. It includes routed graphs, return adjacency, reference continuity, decoupling, switching loops, connector ordering, production engineering/readiness, four-layer routing contracts, final fill and manufacturing release. This is a separate run from the earlier foundation regression count. Lint passes; mypy passes for all seven changed source modules. The workflow audit passes with 213 classified callers and no changed or unclassified calls.

Evidence under `outputs/four-layer-logic-2026-10-10/`:

- `electrical-regressions.xml` and `electrical-workflow-audit.json`.
- `electrical-proof-01/native-electrical-replay.json`: read-only reconstruction of both nets on the previously routed native fixture, using native pad readback and imported tracks. The front/back SMD path retains exactly two physical vias. The source PCB hash remains `63a3dc4008116ba0deb3dc7f3a9c710aabe3c5226e572fcecb87b763ff633d94`; no reroute or native save occurred.
- `electrical-proof-01/native-pad-positions-verified/`: independently parsed KiCad pad positions and actual copper layer sets match the text reader for all 16 pads.
- `electrical-blocker.json`: exact source identities for the remaining production restrictions and selected fabrication direction.

Two opt-in live checks passed separately from the 278-test run. The earlier fixture's retained footprint-library warning remains; this work does not waive it or add schematic/ERC/production approval.

Failures corrected during development: a synthetic stackup fixture initially hashed unsorted adjacency pairs; the retained native replay exposed the front-only terminal reader; the independent test initially queried `PAD.GetLayer()` rather than the pad's copper layer set. The corrected native comparison uses `GetLayerSet().CuStack()`, with the first output retained in `native-pad-positions/`. One regression invocation named a nonexistent test file and stopped before executing tests; the corrected invocation above is the completed run.

## Actual blocker and next implementation

Historical phase boundary: the three implementation blockers below are superseded by the native-plane integration section at the end of this report. The real board/review/manufacturing proof remains a separate outstanding obligation.

Ordinary four-layer release remains deliberately blocked. This is an unimplemented production capability, not a rejected board or a missing user approval:

1. `production_routing.py` rejects a plane-pour request on the default Freerouting path. The existing plane constraint is native-router-specific; enabling a fallback would violate the automatic-routing workflow. A shared, declarative post-routing plane stage must preserve the exact routed tracks and source-bound plane intent, then fill and validate natively.
2. `production_decoupling.py` rejects layouts with zones, and its selected-path logic rejects plane shortcuts. `ExactFilledZoneCopper` currently carries the mask primitive geometry vocabulary, not native polygon contours with holes/islands. Native filled planes need a qualified bridge into the electrical model that preserves separate islands, clearances, pad/via contacts and thermal spokes. Broadening layer names is insufficient.
3. The native `kicad_board_part4_bridge.py` reference-continuity producer and its typed acceptance contract remain two-layer-only. Four-layer acceptance requires explicit source-bound reference roles and actual filled-plane connectivity; an opposite-outer-layer assumption is invalid. Return/loop claims must remain limited to the geometry actually proved.

Completion criteria are an automatically routed and natively filled four-layer test, independent preservation checks, positive and negative plane/island/void/stitch cases, and exact engineering replay. Only then remove the production publication guard for that qualified scope and start the real board job. Start its timer before component/design/vector preparation, retain an editable inspected floorplan, and finish with ERC/DRC/parity, all inner-layer visual reviews, four Gerbers, drills, BOM/iBOM, release and mandatory handover.

The first real example will target factory fabrication with an explicit sourced stackup. No fabricator/order has been selected and no purchase is authorized or made. Inner-layer current rating, controlled impedance, blind/buried vias and physical lamination/plating qualification are not established by these tests. Existing power-board deliveries and all old board-job histories are unchanged. No prospective board job was opened or prebuilt during this separately scoped platform work.

## Check-system review and implementation scope

The user subsequently requested a review of the inner-plane validations and connections we need to add. This section is the consolidated implementation scope, not a new competing roadmap. It refines the blocker above: **several useful fill/contact/thermal owners already exist** and should be extended and connected to production, rather than replaced. No runtime or board was changed in this review.

### Existing checks to reuse

| Existing owner | What it already supplies | What still needs qualification/integration |
| --- | --- | --- |
| `kicad/final_fill_adapter.py` | Isolated native refill, source/rule preservation, zone intent and exact saved fill records, stale-fill flag. | Require every intended plane to have explained output; canonicalize native holes/islands into usable electrical geometry. |
| `kicad_final_fill_connectivity_bridge.py` and `kicad/final_fill_connectivity.py` | Per-outline island state, same-net effective-shape contacts, pad reachability and source-pad classification. | Live inner-layer tests, full transitive source reachability, explicit layer span/flash behavior and physical-pad UUIDs. Do not assume the existing native connectivity query is a complete transitive walk without a firing test. |
| `kicad/final_fill_thermal.py` | Native starved-thermal results bound to a board revision and enumerated thermal contacts. | Complete intended-contact inventory, resolved rule coverage and per-pad/per-zone/per-layer results. A zero-contact pad must not disappear from applicability. |
| `routed_copper_graph` / `return_adjacency` | Four-layer tracks and barrels, source-bound adjacency, restricted exact reference geometry and transition policy. | Native filled-region topology without invented straight-line current paths; actual connection of a selected stitch to both relevant reference regions. |
| `kicad/reference_continuity.py` and `kicad_board_part4_bridge.py` | Exact straight-centerline coverage and a scoped transition-proximity observation. | Explicit four-layer reference roles, revision/rule/stackup binding, and supported geometric return paths. The current opposite-layer assumption and fixed 2 mm policy cannot become a universal multilayer rule. |
| `whole_board_qualification_adapter.py`, mandatory review and handover | Combined gates, explicit applicability, current native evidence and delivery checks. | Close the gaps below and make four-layer evidence mandatory through the normal production/release path. |
| Manufacturing and visual owners | Ordered copper stack checks, four distinct copper Gerbers and required inner-layer views. | Full live board handover, inner copper/drill registration checks and comparison of exported geometry against the same filled native revision. |

### Confirmed gate defects to repair first

Two synthetic reproductions against the existing `_fill_gate` produced these results:

| Input | Actual gate result | Required result |
| --- | --- | --- |
| One retained region, `refilled_by_kicad=False`, `stale_fill=True` | `pass` | Block as stale/unverified. |
| One declared zone, zero filled regions, `stale_fill=True` | `not_applicable` | Block the required missing plane. N/A is permissible only when no plane is required and absence is consistent with current intent. |

Evidence: `outputs/four-layer-logic-2026-10-10/check-system-audit.json`. These are isolated gate-input diagnostics, not evidence that a delivered board failed or that an entire release passed incorrectly. Existing fill, thermal, whole-board and reference checks still pass **24 baseline tests**, retained in `check-system-baseline.xml`; those tests do not cover these two negative cases.

Additional source-review findings to address in the same gate repair:

- The whole-board fill adapter checks board hashes but does not itself replay region-set/contact/classification consistency. It should consume a verified shared-owner receipt, not merely a collection of separately valid models.
- `ReferenceContinuityEvidence` lacks its own board/stackup/rules identity, and `qualify_production_board` does not include that evidence in its board-hash check. Add and enforce those bindings before enabling four-layer reference acceptance.
- The thermal reader accepts an absent `violations` field as an empty list. Validate the complete native report and enabled-rule/exclusion baseline; absence of findings alone cannot prove execution.
- The native contact bridge visits `zone.GetLayer()` once, identifies pads by reference and number, and enumerates thermal applicability only for contacts it found. Qualify one-zone-per-layer initially; reject unsupported multi-layer zone declarations explicitly. Preserve separate UUIDs for duplicate-number pads and inspect intended but disconnected thermal contacts.

### Mandatory four-layer checks

These checks run for every four-layer delivery. Applicability is decided from saved copper and declared design intent; missing evidence is a blocker, never automatic N/A.

| Check | Acceptance requirement | Representative failure test |
| --- | --- | --- |
| Stackup and layer roles | Exact ordered copper/dielectric stack and fabrication limits; every plane has an explicit net, layer and role. | Swap inner layers, omit a plane, or use a different stackup revision. |
| Fresh final fill | Native refill completed on the final candidate; intent, rules and source preserved; expected zones/regions accounted for. | Stale cache, fully cleared required plane, changed priority or keepout after review. |
| Plane connectivity | Each required island and terminal reaches its intended source through actual same-net copper contacts. | An island touches a load pad but has no source connection; two disconnected islands have the same net name. |
| Pad/via-to-plane connection | Exact copper on each layer, actual plated barrel and retained/removed annular pads, clearances to other nets and NPTH holes. | Unflashed inner pad, disabled layer connection, through-via hitting a foreign power plane, or missing via in a multi-hop path. |
| Thermal connections | Resolved connection mode and applicable spoke requirements for every intended contact; actual native starvation findings retained. | Zero-spoke contact, inadequate spokes, narrowed bridge, ignored starvation rule, or pad-level override. Solid connections need explicit applicability rather than an invented thermal pass. |
| Copper geometry | Native all-layer shorts/opens, clearance, edge/hole/keepout, annular-ring and minimum connection-width checks against the fabrication profile. | Narrow plane neck, foreign-net overlap, edge clearance violation or drill breakout. Geometric minimums do not establish ampacity. |
| Return and decoupling paths | Every declared signal/reference relationship is evaluated against actual filled regions; transitions have a valid return connection; each required decoupler has complete supply/return connectivity. | Trace crosses a reference void, nearby stitch is on the wrong net/island, or capacitor ground is disconnected. A geometric graph edge through a plane is not a measured current path or loop inductance. |
| Publication and fabrication | Same final board revision feeds checks, inner-layer previews, all four Gerbers, drill data and handover; required iBOM/vector remain included. | Missing/mislabeled inner Gerber, stale prefill image, changed rule file, or mismatched drill origin. |

For native geometric checks, reuse KiCad's resolved constraints and DRC rather than maintaining a competing clearance engine. Its documented rules cover copper connections and thermal-spoke requirements; zone settings also affect island removal. The four-layer baseline must enumerate the applicable rules and their effective severities/exclusions. [KiCad 10 PCB Editor manual](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html).

Return-path analysis must use actual reference regions and declared signal requirements. Edge rate and route geometry matter, so a low repetition frequency alone is not a reason to skip the review. Avoid unsupported assertions of impedance or EMC compliance from continuity tests. [Texas Instruments, High-Speed Layout Guidelines, sections 1.2, 1.6 and 2.2–2.4](https://www.ti.com/lit/an/scaa082a/scaa082a.pdf).

### Conditional checks and practical limits

- Current/temperature and voltage-drop qualification become required when a design claims a current rating. Inner copper, plane necks, thermal spokes and plated barrels need suitable material/process inputs and a model qualified for that geometry. An outer-track formula or multiplying one via's rating by the via count is insufficient. The existing current-environment gate remains unverified for unsupported claims.
- Controlled impedance, delay/skew and detailed SI/EMC checks are required only when the interfaces/specification demand them, using the selected stackup and device requirements. Do not add a general field solver to unblock the first example.
- Blind/buried/microvias, plane changes between different reference nets and unusual pad stacks remain explicitly unsupported for the first qualified scope. In particular, never substitute a stitching via between different power/ground nets; any reference-transfer network needs its own circuit and frequency-dependent review.
- Suggested initial scope: outer signal routing, two inner ground planes, ordinary plated through-vias, solid plane fills and no controlled-impedance or high-current claim. This exercises multilayer connections and reference changes while keeping the first production proof manageable. It is a proposed capability scope, not an already prepared board or selected fabricator stackup.

### One implementation order

1. Repair stale/missing-fill and evidence-binding gates; add regression tests that reject the two reproduced failures and mismatched board/stackup/rule evidence.
2. Qualify the existing native fill/contact/thermal owners on all four layers. Use paired passing/failing fixtures for source reachability, holes, islands, pad overrides, annular pads, multi-hop via paths and thermal starvation. Prove original tracks/placement/rules are preserved.
3. Connect native filled-region evidence to the electrical graph and reference/decoupling checks. Preserve islands and holes, keep unsupported geometry unverified, and never model a plane as an arbitrary zero-length or straight-line return shortcut.
4. Integrate declarative plane creation/refill after the bounded automatic route through the shared production owner, with atomic candidate validation. No native-router fallback, manual coordinate repair or retry reset.
5. Run one normal four-layer board job through the vector, route, fill, native/electrical checks, visual review, release and handover. Only this final proof permits publication within the qualified scope.

At the end of the review, these changes were proposals only. The subsequent user-authorized implementation is recorded below; the four-layer publication guard remains active.

## Check-system implementation, October 10

The user authorized the sequence above. This is separately scoped platform work: no prospective board job was started, no real board was prebuilt, and no existing delivery or job clock was changed.

### Stage 1 — repaired and verified

- The whole-board fill gate rejects stale/unperformed refill and declared zones with no copper. It replays the exact region/contact inventory against explicit source pads instead of trusting an earlier positive classification. Region/zone identity, source hash, producer version and native zone index must agree. Missing source proof remains unverified.
- Final-fill snapshots reject duplicate identities and regions from a different net, layer, zone or board. Multi-layer zone declarations and rule-area zones are explicitly outside this reader's qualified scope.
- Native refill now retains `final-fill-execution.json`, binding the final PCB, native project/rule/dependency hashes, DRC report, snapshot and KiCad version. Thermal audit replays this receipt; changing the report or rules after execution invalidates it. The already validated DRC report supplies the producer version, avoiding a redundant native version process.
- Thermal reports require the native schema, correct source/version and all DRC sections. Applicable audits require explicit enabled `starved_thermal` severity, no project/report exclusions and no custom suppression. Both project and custom-rule presence/content are bound. A reported failure takes precedence over missing contacts or unresolved applicability. These are scoped geometric checks, not thermal/current ratings.
- Reference evidence can now retain exact board, native input, stackup and policy identities. A fresh bounded native observer binds them only after checking that the inputs stayed unchanged; it cannot upgrade cached unbound evidence. New whole-board reference acceptance requires the expected context. The reference producer's two-layer acceptance limit remains unchanged.
- Shared native process calls now have a finite default timeout (180 seconds); nonpositive and nonfinite values are rejected. These are process bounds, not board-job allowance extensions.

### Stage 2 — native cases verified; full reader qualification remains open

The existing native bridge now retains physical pad UUIDs, actual per-layer `FlashLayer` results, and an intended pad/zone/layer contact inventory. Duplicate logical pad numbers remain separate physical objects. Native footprint/pad connection inheritance is queried; custom zone-connection rules remain unverified. An intended thermal contact is enumerated even when it has no surviving spokes. Observed pad contacts must be fully covered by the new inventory.

Native saved fill uses fractured contour walks. The bridge applies KiCad's `Unfracture()` to a copy of each region and records integer-nanometre outer contours and holes; a region that cannot remain one polygon with holes is rejected. No board is saved by this observer. The contour data is not yet connected to the routed electrical graph or accepted as a plane current path.

Final native test record: `outputs/four-layer-logic-2026-10-10/fill-native-tests-final.xml`, **6 passed**, with source and output files in `fill-proof-06/`. Each fixture contains four copper layers, a multi-segment source path crossing through a via, duplicate-number plated pads, a pad with no zone connection, unconnected-pad removal, a foreign-net pad/via and an NPTH opening.

| Native fixture | Required / observed fill gate result |
| --- | --- |
| Connected planes | Pass |
| Broken source via | Unverified; cannot establish declared source reachability |
| Wholly isolated inner zone | Unverified; no contact or reachable source, irrespective of the native island flag |
| Four-spoke inner thermal | Pass |
| Starved inner thermal | Fail; native starvation retained |
| Zero-spoke inner thermal | Fail; intended contact remains in the audit inventory |

Each test independently compares saved footprint, trace, via, edge and layer records before/after native refill, checks the original source and read-only observation hashes, tests valid reference coverage and rejection inside NPTH/foreign-net voids, and verifies the removed inner pad is not reported as a contact. Deliberate negative fixtures retain native opens/warnings; these test outcomes are not clean-board DRC or fabrication approval.

**Open native integration issue:** KiCad 10.0.6's `ZONE.IsIsland()` is false for the retained wholly isolated zone. Inspection of the matching native source shows the filler bypasses island marking when all layers of a zone are isolated; the flag cannot be used as a complete classification authority. A read-only probe of `FillIsolatedIslandsMap({})` fails with a SWIG `TypeError`. Inspection then found `board.m_ZoneIsolatedIslandsMap`: the native call accepts this handle, but Python exposes it only as an opaque `SwigPyObject`, with no iteration, indexing or mapping access. Computing that map does not update `ZONE.IsIsland()`; all five saved fixture zones still report false. The source-reachability gate correctly stays unverified and blocks the isolated case. Do not change it to a pass or mark this reader generally qualified. See [KiCad 10.0.6 zone filler](https://gitlab.com/kicad/code/kicad/-/raw/10.0.6/pcbnew/zone_filler.cpp) and [native connectivity implementation](https://gitlab.com/kicad/code/kicad/-/raw/10.0.6/pcbnew/connectivity/connectivity_data.cpp).

The remaining stage-2 work is a qualified per-region isolation result, including same-net zone-to-zone contacts and fragmented zones, without relying on that incomplete flag or conflating all outlines of a zone. Existing conservative rejection stays in force. Stage 3's graph/reference/decoupling integration, stage 4's shared post-Freerouting plane transaction and stage 5's real-board proof remain pending in that order. A native flag limitation does not justify a new router, manual copper or relaxing publication.

### Verification and retained failures

- **196 regression tests passed**, no skips or failures: `check-system-regressions-final.xml`. These cover fill/contact/thermal/reference gates, electrical graph/adjacency, production decoupling, native zone edits, report integrity, mandatory review and manufacturing lineage. Three synthetic tamper tests emitted Pydantic serializer warnings while deliberately constructing mismatched region inputs; the required rejection assertions passed.
- **6 native positive/negative tests passed** in the final run. Earlier outputs are retained: `fill-proof-01/` includes the initial duplicate-pad observation; `fill-proof-03/` and `fill-proof-04/` retain the failed assertion that `IsIsland()` must report the wholly isolated zone. The corrected test asserts the independently required blocked gate outcome and explicitly retains the unresolved classification limitation. `fill-proof-05/` verifies that isolated case alone.
- The first fixture setup exposed KiCad binding differences for layer sets and unconnected-pad modes; these were corrected before claiming a native result. Two native processes stalled after writing files under restricted registry access. Only those identified test processes were stopped; subsequent bounded native tests used the authorized normal local KiCad environment. No failed output was relabeled as completed evidence.
- Ruff and mypy pass for the changed source scope. `check-workflow-audit.json` passes for 213 classified callers. Static classification is not engineering acceptance.
- Boundary review: the final-fill adapter remains the shared isolated native producer; the connectivity bridge and reference observer are read-only evidence producers; thermal and whole-board adapters consume source-bound observations. The new fixture generator is synthetic test infrastructure, not an ordinary board path. No production release guard was removed.

Current outcome: stage 1 complete; stage 2 has useful verified coverage and an explicit remaining native isolation limitation. No finished four-layer board, manufacturing handover, current rating, impedance or SI/EMC qualification is claimed.

## Isolation blocker repair, October 10

The user's follow-up authorized fixing the native isolation limitation. This section supersedes the open isolation issue above, retaining its original diagnostic and failed evidence. This remains platform work; no production board/job, existing delivery or history was changed.

### Implemented repair

The read-only bridge now builds a complete contact graph within an explicitly checked scope. Native `GetConnectedItems(item, EXCLUDE_ZONES)` supplies same-net track/pad/via components. Every saved filled outline remains a separate region, with its unfractured contour and holes. Native integer shape collisions supply region-to-item and same-layer/same-net region-to-region contacts. A region can therefore reach a pad through another zone, while disconnected outlines of the same zone never become connected merely by sharing a zone UUID. The native connectivity call's zone-exclusion semantics are confirmed in the [KiCad 10.0.6 implementation](https://gitlab.com/kicad/code/kicad/-/raw/10.0.6/pcbnew/connectivity/connectivity_data.cpp).

The observation retains native item components and region contacts. The shared consumer independently replays this graph, rejects inconsistent inventories/foreign-net or cross-layer links, and binds a classified region to the whole supporting observation. An empty reachable-pad set from this complete graph establishes **floating copper**, which fails the existing gate. A pad-bearing region still needs a declared reachable source; otherwise it remains unverified and blocked. This does not infer a source from a net label.

`ZONE.IsIsland()` remains a raw native observation for history; new graph-backed classification does not depend on it. Old observations without the complete graph keep their prior conservative behavior and gain no retroactive completeness claim. No C++ memory access, patched KiCad binary or opaque-map conversion is needed. Native `GetConnectedItems` sometimes exposes vias as `PCB_TRACK` Python proxies; component identity is therefore resolved by physical UUID against the typed saved-board inventory.

The first qualified scope uses individual copper-layer zones, normal non-custom SMD/plated-pad stacks and ordinary through-vias. Copper graphics, net ties, logical jumper groups, custom pad shapes/stacks, unsupported plating types, multi-copper-layer SMD pads, blind/buried vias and backdrilled/post-machined barrels are rejected before claiming a complete inventory. Existing multi-layer-zone/rule-area rejection and unresolved custom zone-connection rules remain. NPTH holes are not conductive contacts. These limits are explicit; unsupported boards cannot silently pass as complete.

### Verification

Final native evidence: `outputs/four-layer-logic-2026-10-10/isolation-fix-native-final.xml`, **16 passed**, with exact boards, observations, snapshots, audits and gate reports in `isolation-fix-proof-04/`.

| Native case | Observed result |
| --- | --- |
| Connected four-layer planes / healthy thermal | Source reachable; fill gate passes |
| Missing source via | Required source not reachable; gate stays unverified |
| Wholly isolated zone, native island flag false | Floating; gate fails |
| Region connected only through an overlapping same-net zone | Source reachable; gate passes |
| Separated zones / region lying in another zone's hole | Floating; gate fails |
| Identical projection on different copper layers | Only the physically connected layer reaches the source; isolated layer fails |
| Two overlapping zones with no pad connection | Both floating; gate fails |
| One zone split by foreign-net clearance | Connected fragment reaches the source; empty fragment is floating and fails |
| Split zone with duplicate-number physical pads | Only the source fragment passes; disconnected pad-bearing fragment stays unverified |
| Split zone connected through a back-layer track and plated pads | Both fragments reach the source; gate passes |
| Starved / zero-spoke thermals | Native starvation retained; gates fail |
| Copper graphic / logical jumper fixtures | Observer rejects unsupported conductor scope without emitting evidence |

The native tests also retain the prior exact source-preservation, per-layer flashing, void-coverage and contact-inventory assertions. These are synthetic positive/negative fixtures; deliberate opens and native violations are not manufacturing acceptance.

**210 regression tests pass**, with no failures/skips: `isolation-fix-regressions-final.xml`. Fourteen new cases check graph consistency, foreign-net/layer links, missing geometry/items, invented reachability and compatibility with older observations. The three pre-existing serializer warnings from deliberate snapshot-tamper fixtures remain. Ruff and mypy pass for the changed scope. `isolation-fix-workflow-audit.json` passes for 213 classified callers. The shared producer/consumer boundary is unchanged: read-only observation and evidence replay, plus synthetic test infrastructure; no new production path or guard exception.

Retained repair iterations: `isolation-fix-proof-01/` exposed the native via proxy identity mismatch; the UUID binding repair passed all 12 initial cases in `isolation-fix-proof-02/`. The expanded run in `isolation-fix-proof-03/` passed seven cases before its new fixture used `ZONE.Duplicate()` without the required boolean argument; the corrected test builder then passed the final 16 cases. The first unit run also caught a fixture mixing its numeric legacy net identity with a hardcoded name; the test now derives its component net from the snapshot. Earlier outputs remain intact.

Stage 2's isolation/contact/thermal reader is qualified for this scope. The following section records the subsequent stage 3/4 work. Contact edges prove connectivity only; they are not current-path lengths, impedance, ampacity or loop-inductance evidence.

## Native plane integration and production transaction (October 10)

Stages 3 and 4 are implemented and exercised through the shared production transaction. The user authorized sustained implementation without repeated routine permission questions. No ordinary board job was opened or prebuilt during these platform tests, and no historical delivery or job ledger changed.

- `NativeFilledCopperInput` retains exact saved bytes, final-fill snapshot and native contact graph. The graph owner replays their bindings against actual zone intent, polygons, pads, tracks, vias and layer stack. Separate islands/holes remain separate; plane contact edges are explicitly non-metric. Trace/barrel paths can still provide geometric loop measurements. A plane-only return stays unverified for length and loop area. A selected traced path and the existing terminal-interior/daisy-chain classification do not establish an exclusive physical return-current path or loop inductance.
- The native four-layer reference owner uses F.Cu → In1.Cu and B.Cu → In2.Cu, explicit same-net source pads, actual source-reachable filled regions and holes. Layer-changing signal vias require nearby reference vias touching both local reference regions. Wrong-net, disconnected, distant and source-orphaned stitches fail. Any transition antipad allowance must be explicit and bounded in the reviewed policy; it is applied only after the connected-stitch proof. All non-reference tracks are inventoried. Signal plated pads, arcs and inner signal routing remain outside this reference scope.
- `PostRoutePlanePlan` adds two declared inner rectangles only after a complete external result. Original tracks, vias, external termination, constraints and logs are retained. Conflicting per-net copper restrictions are rejected. Native fill, actual source/region/thermal checks, reference coverage, DRC/opens/parity, pad-net equivalence and native preservation are mandatory before the existing transaction commits a candidate. Failed candidates never create the accepted pointer. No manual routing or native-router fallback is introduced.
- The native saved candidate is retained only after exact geometry/electrical/UUID-preservation comparison. KiCad can reorder zone objects on save: the new `uuid-bound-zone-intent-v2` snapshot compares the exact per-UUID intent while retaining physical file indices in the observation. UUID, layer, priority, net, outline and clearance changes still fail. Legacy snapshots retain their old serialized fields/fingerprints. A separate serializer fix puts hatch/priority clauses in native order.
- The blanket publication prohibition becomes a mandatory `FourLayerPublicationEvidence` gate. Unrouted placement needs a declared plan/source policy. Routed publication additionally replays native filled copper, the exact raw fill report/execution receipt, source/thermal checks and the reference result against the actual delivered inputs. The existing readiness owner retains the policy/report/receipt files. Omission, changed board bytes, changed rules/report, changed plane geometry/plan or a failed check blocks publication. This qualifies a software path; it does not replace component, vector, visual, ERC, manufacturing or handover review.
- `RouteNetLayerConstraint.allowed_trace_layers` can restrict signal tracks to the two outer faces while `allowed_layers` explicitly permits the complete through-via copper span. DSN translation, native import and the independent candidate validator all enforce it. Plane and via permissions are unchanged; absent new fields preserve historical fingerprints. Legacy native routing still rejects per-net restrictions rather than ignoring them.

### Verification and preserved failures

Evidence remains under `outputs/four-layer-logic-2026-10-10/`:

| Evidence | Result and scope |
| --- | --- |
| `plane-integration-regressions-final.xml` | 299 passed, no failures/skips, 21.026 s. Three existing Pydantic serializer warnings come from deliberate snapshot-tamper fixtures. |
| `plane-and-outer-trace-regressions-final.xml` | Final combined scope: 329 passed, no failures/skips, 16.917 s; same three deliberate-tamper serializer warnings. |
| `plane-integration-native-final.xml` and matching folder | 11 passed, 48.834 s: real Freerouting/native fill/atomic acceptance, wrong-source rejection, publication retention/stale/plan checks, traced versus plane-only return and seven reference/stitch cases. |
| `outer-trace-policy-unit-01.xml` | 49 passed, including seven new trace-subset cases; full via-span restrictions and historical serialization stay enforced. |
| `outer-trace-policy-native-02/` and `.xml` | Installed pinned Freerouting routes a front/back SMD net using outer tracks and through-vias; another net remains constrained to In1.Cu. Four Gerbers and drills export. This older interchange fixture retains its documented flipped-footprint library warning, has no schematic/ERC/production approval, and is not a delivery. |
| `plane-integration-audit-final.json` | 213 explicitly classified native callers pass static audit; this is not engineering acceptance. |
| `plane-final-quality-checks.json` and `plane-and-outer-trace-audit-final.json` | Ruff passes for 24 changed source/test files, mypy for 15 source files, and final 213-caller audit passes. Exact reports and source hashes are sealed in `plane-integration-implementation-result.json`. |

The production-transaction test has a real matching synthetic schematic and actual native checks, but its pre-route entry authority is a schema-valid **test fixture**. It cannot serve as genuine predesign or review evidence for the first user board. The positive native transaction has zero DRC/opens/parity findings; the wrong-source candidate is retained and rejected. Publication replay is read-only and performs no new native save, routing or rendering.

Retained development failures: `electrical-fill-proof-01` exposed hatch/priority ordering; `-02` exposed ambiguous plane-only path selection; `-03` passed. The initial reference proof passed all seven cases. Production test iterations `production-plane-proof-01` through `-06` retain missing schematic input, incomplete schematic parity/BOM fixture data, a conflicting ground-layer restriction, incomplete synthetic entry metadata and the real native zone-order issue. `-07` passes both atomic cases. `plane-publication-proof-01` caught native rectangle encoding and a test-output directory collision; `-02` passes. The first outer-trace native fixture stopped before routing on tuple/list handling; `-02` passes. Sandbox regressions `plane-integration-regressions-02/03` failed temporary-directory setup or stalled and were stopped; the normal-environment successor passed. None of these is erased or relabeled as an ordinary board attempt.

Boundary review: the existing native fill primitive still owns isolated KiCad execution; the existing routing transaction owns all new copper and atomic acceptance. `production_planes` supplies a declarative post-stage and read-only checks. `native_fill_graph`, `native_reference_continuity` and `four_layer_publication` are source-bound consumers, not alternate builders or approval writers. New native/contact tests are explicitly synthetic research infrastructure. Current typed/lint/audit reports and source hashes are retained in the integration result record.

The subsequent real board job is **LogicBridge**, started on `outputs/logicbridge-four-layer-2026-10-10` with timing recorded **before** component/asset/design/vector preparation. Its schematic, genuine component review, inspected editable vector and native placement are complete. It remains unrouted at a diagnosed metadata-encoding checkpoint; see the [exact board record](logicbridge-checkpoint-2026-10-10.md). Remaining obligations are actual placement/final visual reviews, automatic routing, both inner-layer inspections, exact native ERC/DRC/parity and plane proof, four copper Gerbers, drills, BOM/iBOM, release and mandatory handover. Factory stackup confirmation and physical validation remain separate; no controlled-impedance, 3–5 A, blind/buried-via or four-layer laser capability is claimed.
