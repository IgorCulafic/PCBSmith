# Outer-copper exposure from final solder-mask apertures

## Decision

Replace the current hand-written `_Stadium.exposure` labels with a two-axis result:

1. **physical mask state**: `masked`, `partially_exposed`, `fully_exposed`, or `unknown`; and
2. **copper role**: `component_termination`, `routed_conductor`, `via_land`, `copper_pour`, `board_copper_graphic`, or `unknown`.

The role is determined by the copper source. It is never inferred from the mask opening. A pad remains a component termination whether its own aperture is absent, negatively expanded, fully open, or supplemented by a board-level gang opening. Conversely, a track exposed by the detector's board-level disc remains a routed conductor; it must not become a component termination.

This is a nominal geometry result, not a fabrication-tolerance or electrical-insulation claim. The final KiCad DRC/fabrication outputs remain authoritative.

## Implementation status — 2026-07-15

The R1 exposure, selector, and report-gate slice described by this design is now
implemented. The design discussion below is retained as the implementation
rationale; its pre-implementation descriptions of hard-coded exposure labels and
dead selectors are historical.

- `src/pcbsmith/mask_geometry.py` supplies the exact overlap and conservative
  containment proofs used by exposure classification.
- `src/pcbsmith/copper_exposure.py` owns the versioned outer-copper/result models
  and deterministic `masked|partially_exposed|fully_exposed|unknown`
  classifier.
- `src/pcbsmith/kicad/copper_identity.py`,
  `src/pcbsmith/kicad/mask_apertures.py`, and
  `src/pcbsmith/kicad/copper_exposure.py` provide stable copper identities,
  aperture provenance, KiCad outer-copper collection, and the exposure index.
- `src/pcbsmith/kicad/virtual_drc.py` applies source-derived role and mask-state
  selectors and emits `ordinary_pairwise_clearance_scope_unverified` when an
  unknown state prevents definitive selector scoping.
- `src/pcbsmith/kicad/design_checks.py` reuses the per-run aperture collection,
  records `outer_copper_exposure`, and emits
  `fab.copper_exposure_unverified` for relevant unknown classifications.
- Focused coverage is in `tests/unit/test_mask_geometry_containment.py`,
  `tests/unit/test_copper_exposure.py`,
  `tests/unit/kicad/test_mask_apertures.py`,
  `tests/unit/kicad/test_copper_exposure.py`,
  `tests/unit/kicad/test_profile_integration.py`,
  `tests/unit/kicad/test_metal_detector_board.py`, and
  `tests/unit/kicad/test_copper_exposure_checks.py`.

Safety correction to the original localization proposal: an
`UNSUPPORTED` aperture has no quantitative error contract. Its uncertainty
therefore poisons every not-already-proven-fully-exposed copper result on the
same side, even when the aperture carries targeted copper IDs or nominal
geometry; neither hint bounds the omitted geometry. A
`BOUNDED_APPROXIMATION` is different: its geometry is evaluated with the
`maximum_error_mm` envelope, so it is relevant when the nominal separation is
within that maximum error. A separately proven `fully_exposed` result remains
valid because adding another mask opening cannot reduce exposed area.

Latest focused validation at this checkpoint: the R1 exposure/selector set is
`106 passed`, and the report/design-check set is `26 passed`. These are focused
runs; the full suite has not yet been rerun after this checkpoint.

## Local evidence and current gaps

- `src/pcbsmith/mask_geometry.py:1-9` deliberately excludes copper exposure. Keep that boundary: add only neutral geometry predicates there; put exposure policy in a separate module.
- `MaskAperture.copper_source_ids` exists at `src/pcbsmith/mask_geometry.py:194-205`, but the collector never fills it. `collect_mask_apertures` explicitly discards the netlist at `src/pcbsmith/kicad/mask_apertures.py:58-71`.
- Exact pad apertures are emitted at `src/pcbsmith/kicad/mask_apertures.py:74-128` and exact/open via apertures at `:262-311`, both without copper linkage.
- Typed board apertures are passed through at `src/pcbsmith/kicad/mask_apertures.py:319-348`; raw board and footprint mask graphics are retained as unlocated `UNSUPPORTED` sources at `:351-390`.
- `_Stadium.exposure` defaults to `"unknown"` at `src/pcbsmith/kicad/virtual_drc.py:97-112`, but pad copper is unconditionally stamped `"component_termination"` at `:367-382`, tracks `"external_masked"` at `:411-425`, and vias `"external_masked"` at `:427-459`. These assignments occur without collecting mask apertures.
- `OrdinaryClearanceRequirement.exposures_a/b` is declared at `src/pcbsmith/rule_profiles.py:34-56`, but is dead configuration: `_check_pairwise_clearance` drops both selectors at `src/pcbsmith/kicad/virtual_drc.py:614-631`, and `_check_group_clearances` checks only nets, owners, layers, kind, and distance at `:562-611`.
- The A* router similarly converts pairwise requirements only to net groups, distance, and exemptions at `src/pcbsmith/kicad/astar_router.py:163-181`. It currently applies the distance to the entire net pair, which is conservative if an exposure selector would narrow it.
- `run_design_checks` collects mask apertures only when a minimum web is declared (`src/pcbsmith/kicad/design_checks.py:173-182`). The web checker correctly treats same-side apertures as physical unions for measurement while separately flagging unreviewed merges (`:765-884`), but no exposure consumer exists.
- The detector spiral is front copper at `src/pcbsmith/kicad/metal_detector_board.py:246-252`; the exact typed front-mask disc is installed at `:268-272`. Its `MaskAperture` is constructed without copper links at `src/pcbsmith/kicad/board_mask.py:26-53`. This is the first important spatial (not own-pad) exposure case.
- Existing tests preserve the wrong assumption for tracks (`tests/unit/kicad/test_virtual_drc.py:409-416`). Profile tests only prove that exposure selector values serialize (`tests/unit/kicad/test_rule_profiles.py:170-183`), not that they affect a check.

## Public data model

Add the following public types to `rule_profiles.py` (or a dependency-neutral `surface_models.py` imported by it):

```python
OuterCopperMaskState = Literal[
    "masked",
    "partially_exposed",
    "fully_exposed",
    "unknown",
]

CopperRole = Literal[
    "component_termination",
    "routed_conductor",
    "via_land",
    "copper_pour",
    "board_copper_graphic",
    "unknown",
]
```

Do not retain `component_termination` inside a physical exposure enum. The current `CopperExposure` alias conflates two independent properties and cannot represent partial exposure. There are no production uses of `exposures_a/b` in the current tree; only the model and one serialization test use them, so a schema correction is preferable to permanently ambiguous compatibility behavior.

Change `OrdinaryClearanceRequirement` to:

```python
mask_states_a: tuple[OuterCopperMaskState, ...] = ()
mask_states_b: tuple[OuterCopperMaskState, ...] = ()
roles_a: tuple[CopperRole, ...] = ()
roles_b: tuple[CopperRole, ...] = ()
```

An empty tuple is a wildcard. Within one side, mask-state and role selectors are ANDed. Direction is preserved: an item in `nets_a` is evaluated against the `*_a` selectors and an item in `nets_b` against `*_b`; the selectors swap when the physical item order is reversed.

Add an engine-neutral, frozen/versioned result model in a new `src/pcbsmith/copper_exposure.py`:

```python
class CopperGeometryVerification(StrEnum):
    EXACT = "exact"
    UNSUPPORTED = "unsupported"

class OuterCopperRegion(BaseModel):
    source_id: str
    parent_source_id: str | None = None
    side: MaskSide
    net_name: str
    owner_ref: str | None = None
    role: CopperRole
    geometry: MaskGeometry | None
    verification: CopperGeometryVerification
    unsupported_reason: str | None = None

class CopperExposureResult(BaseModel):
    copper_source_id: str
    side: MaskSide
    state: OuterCopperMaskState
    role: CopperRole
    aperture_source_ids: tuple[str, ...] = ()
    unresolved_aperture_source_ids: tuple[str, ...] = ()
    reason: str | None = None
```

Use the same frozen, `extra="forbid"`, deterministic semantic-JSON conventions as `mask_geometry.py`. `aperture_source_ids` contains every exact opening part that positively overlaps or fully contains the copper. Touch-only aperture IDs may be retained in a separate diagnostic field if useful, but they do not make copper exposed.

KiCad integration belongs in a new `src/pcbsmith/kicad/copper_exposure.py` with these narrow APIs:

```python
def collect_outer_copper_regions(
    layout: BoardLayout,
    netlist: BoardNetlist,
) -> tuple[OuterCopperRegion, ...]: ...

def classify_outer_copper_exposure(
    copper: tuple[OuterCopperRegion, ...],
    apertures: tuple[MaskAperture, ...],
) -> tuple[CopperExposureResult, ...]: ...

def exposure_index(
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
) -> dict[str, CopperExposureResult]: ...
```

`exposure_index` is the convenience boundary: collect apertures once, collect exact outer copper once, classify once, and reject duplicate unequal copper IDs. `_collect_items` should remain nominal physical geometry for routing and clearance. `run_virtual_drc` applies the exposure index to its copper stadia by `source_id` before exposure-scoped checks. Do not make every router/scoring call reparse mask geometry.

## Copper geometry and source-ID contract

Use exact copper geometry, not the virtual-DRC stadium approximation, for exposure classification:

- track segment: `Capsule(a, b, width/2)`, or `Disc` for a zero-length segment;
- via land: one `Disc` on each outer side using `size_mm/2`;
- circle/oval/rect/roundrect pad: reuse a public pad-shape builder with expansion `0.0`, then apply the same placement transform used by `mask_apertures.py`;
- custom/chamfered/unpreserved pad: an `UNSUPPORTED` copper region, never a routing bounding box presented as exact copper;
- zones: initially emit an explicit unsupported copper-pour region per declared outer-layer zone because `BoardLayout.zones` is an unflooded rectangle intent and KiCad's clipped final fill is not represented by `_collect_items` (`virtual_drc.py:7-15`). Do not silently omit zones from an exposure claim;
- any future board copper graphic follows the same explicit exact/unsupported rule.

Introduce shared source-ID helpers used by both `_collect_items` and aperture collection; do not duplicate string construction:

```python
pad_copper_source_id(component, pad_index, layer) -> str
track_copper_source_id(segment, occurrence, layer) -> str
via_copper_source_id(via, occurrence, layer) -> str
```

The current IDs (`pad:{ref}:{index}:copper:{layer}`, `track:{index}`, `via:{index}:copper:{layer}`) are sufficient for a first in-memory join only if all collectors share the helper and preserve the same iteration order. Prefer deterministic semantic UUID5 IDs with an explicit duplicate occurrence, matching the established mask identity pattern. Do not use pad names alone: duplicate and unnamed pads already exist. Persistent object IDs remain a later improvement because a semantic track ID changes when the track moves.

Populate `MaskAperture.copper_source_ids` as follows:

- a pad's own aperture links only to that pad's copper region on the aperture's physical side;
- an open or unresolved-inherit via aperture links only to that via land on that side;
- a board/footprint graphic normally has no direct copper links and applies spatially;
- an unsupported pad/via aperture must still carry its target copper ID, so uncertainty remains local rather than poisoning an entire side;
- `parent_source_id` continues to mean logical aperture parent for web de-duplication. Do not overload it as a copper link.

## Side mapping and role semantics

The only valid physical mapping is:

```text
MaskSide.FRONT -> F.Cu
MaskSide.BACK  -> B.Cu
```

Never compare a front aperture with back copper. A through-hole pad and via therefore have two independently classified outer-copper regions. Inner copper, when supported later, is `internal` by stackup and is outside this four-state outer-mask classification.

Role comes only from the copper source:

- any electrically active pad land -> `component_termination` (including through-hole lands);
- routed segment -> `routed_conductor`;
- via land -> `via_land`;
- flooded zone -> `copper_pour`;
- explicit copper graphic -> `board_copper_graphic`.

A pad's own mask aperture is semantically an opening intended for a component termination, but it does not set the role. Its direct `copper_source_ids` link only scopes uncertainty and records provenance. Negative mask expansion can therefore produce `{role=component_termination, state=partially_exposed}`. A pad with no mask layer remains a component termination and is `masked` unless another same-side aperture exposes it.

## Classification algorithm

For one exact copper region and all final aperture sources on the same side:

1. Flatten `Compound` aperture parts and all separate exact apertures into one physical opening union. `merge_group_id` affects the fabrication merge review only; it never changes the physical union used for exposure.
2. Partition unsupported sources into:
   - **targeted**: `copper_source_ids` names this copper region;
   - **spatially bounded**: geometry/bounds exist and can affect this region;
   - **unlocated**: no geometry and no copper links. An unlocated raw mask source makes every not-already-fully-exposed copper region on that side `unknown`.
3. Exact relation uses positive-area interior overlap. `ApertureRelation.OVERLAP` means exposed area exists. `TOUCHING` is nominal zero-area contact and counts as `masked`, while the provenance may report the boundary contact. `SEPARATED` is masked with respect to that opening.
4. Return `fully_exposed` if the exact aperture union is proven to contain the entire copper region. Additional unresolved openings cannot reduce exposure, so a proven full result remains full.
5. Return `unknown` if copper geometry is unsupported, or if a relevant unresolved opening could change a result that is not already proven full.
6. Return `masked` if there is no positive-area exact overlap and no relevant unresolved source.
7. Return `partially_exposed` only when positive-area overlap is proven and non-containment of the entire exact union is also proven. Never turn “containment not implemented” into partial exposure.

This monotonic treatment matters: mask apertures can only add exposed area. Unknown aperture geometry cannot change `fully_exposed` back to another state, but it can change `masked` or `partially_exposed`.

### Compounds and multiple openings

`Compound` is an exact finite union (`mask_geometry.py:167-177`), and multiple `MaskAperture` objects also form one physical union. Exposure classification must not stop after the first overlap. Two partial openings may jointly cover a copper item.

For the narrow first implementation, use a conservative proof matrix:

- if any single exact primitive contains the copper, `fully_exposed` is proven;
- if no primitive has positive-area overlap, `masked` is proven;
- if exactly one primitive has positive-area overlap and exact primitive containment returns false, `partially_exposed` is proven;
- if two or more primitives overlap and none individually contains the copper, return `unknown` until exact union-difference/union-containment is implemented.

This correctly handles the current detector disc while refusing to make a false claim for overlapping gang apertures or multi-part compounds.

### Copper overlap and unions

Classify each physical copper source independently. Do not union an entire net: one routed net can be exposed in the detector head and masked on the handle. Same-net overlapping track/pad/via sources retain their own states and roles. Clearance checks already skip same-net pairs, so duplicated physical coverage does not create a pairwise violation.

If duplicate records share one copper `source_id`, identical records may be de-duplicated; unequal records are an integrity error and yield `unknown`. Do not silently union unequal duplicate IDs.

## Geometry-kernel capability and minimal additions

The present kernel can compute exact bounds (`geometry_bounds`, `mask_geometry.py:271-279`) and exact separated/touching/overlap relation between supported finite unions (`measure_geometry`, `:290-305`). It cannot answer containment, intersection area, set difference, or “covered by the union.” `measure_geometry` returns immediately on any overlapping part and therefore cannot distinguish partial from full exposure.

Keep `mask_geometry.py` copper-neutral and add only:

```python
def geometry_has_interior_overlap(first: MaskGeometry, second: MaskGeometry) -> bool:
    # exact; true iff measure_geometry(...).relation is OVERLAP

class ContainmentProof(StrEnum):
    CONTAINED = "contained"
    NOT_CONTAINED = "not_contained"
    UNKNOWN = "unknown"

def primitive_contains(
    container: MaskPrimitive,
    candidate: MaskPrimitive,
) -> ContainmentProof:
    # exact for the supported proof matrix; UNKNOWN otherwise
```

The minimum exact proof matrix needed for current production is:

- `Disc` contains `Disc` or `Capsule`: the maximum endpoint distance from the disc center plus candidate radius is at most the container radius;
- `Capsule` contains `Disc` or `Capsule`: the maximum distance of candidate core endpoints from the container segment plus candidate radius is at most the container radius;
- convex `Polygon`/`OrientedRect` contains a `Disc`/`Capsule`: both candidate core endpoints satisfy every inward half-plane offset by the candidate radius;
- own-pad pairs generated from one source shape: circle/oval/rect/roundrect at expansion zero versus the corresponding aperture. Positive/zero expansion proves containment; a collapsed aperture stays unsupported; negative expansion plus positive overlap proves non-containment;
- exact semantic equality always proves containment.

For `RoundedRect` and general convex-core-plus-radius combinations, implement only mathematically proven cases (for example, candidate radius no greater than container radius and every candidate-core vertex lies in the appropriately reduced convex offset). Return `UNKNOWN` for the remainder. Do not use sampled boundary points to label an exact result.

An exact general `union_contains_geometry(union, candidate)` requires set difference or a complete boundary arrangement. That is not in the current kernel and is not a minimal prerequisite for the detector slice. Add it later if arbitrary compound/gang openings must receive full/partial rather than unknown.

## Virtual DRC and ordinary pairwise filters

Remove all three hard-coded assignments in `_collect_items`; copper items start with `mask_state="unknown"` and a source-derived `role`. Holes have neither state nor role selectors.

Before `_check_pairwise_clearance`, `run_virtual_drc` resolves the exposure index and annotates copper items by source ID. `_check_group_clearances` should accept complete `OrdinaryClearanceRequirement` objects (or an equivalent typed internal selector), not flatten them to five-tuples.

For a directionally matched A/B pair:

1. apply net groups and component exemptions;
2. apply role selectors, which are always source-derived;
3. apply physical mask-state selectors;
4. check the distance only if both sides match.

If a non-empty mask-state selector is present and a candidate item's state is `unknown`, do not silently skip it. Emit a deterministic `ordinary_pairwise_clearance_scope_unverified` finding naming the requirement, copper source ID, side, and unresolved aperture IDs. If the profile explicitly includes `unknown`, it matches normally. A role mismatch is definitive and may be skipped.

The current router may continue to enforce exposure-scoped pairwise distances across the entire named net groups. That is conservative and preserves router/verifier safety at the cost of route freedom. Document this explicitly at `astar_router.py:163-181`; do not pretend the router honors mask selectors until candidate-route exposure is integrated.

Qualified insulation clearance must not be narrowed by these ordinary exposure/role selectors. It continues to use its separately reviewed barrier geometry and evidence gate.

## Design-check integration

Avoid collecting/parsing the same apertures once for webs and again for exposure. Introduce a small per-run physical-mask context or pass the already collected tuple to both consumers.

When any ordinary requirement has non-empty mask-state selectors, `run_design_checks` should add `outer_copper_exposure` to `checks_run` and emit `fab.copper_exposure_unverified` warnings for relevant `unknown` copper regions. The finding should include:

- copper source ID and side;
- net and component reference when known;
- role;
- targeted and unlocated unresolved aperture IDs/reasons;
- the requirement IDs whose scope cannot be decided.

This is separate from `fab.solder_mask_web_unverified`: one concerns copper exposure classification, the other fabrication web validation. Do not enable either check merely because an unrelated profile field is set.

## Staged test plan

### Stage 1: pure geometry proofs

Add `tests/unit/test_mask_geometry_containment.py`:

1. disc contains smaller disc; tangent internal boundary counts contained;
2. disc does not contain a capsule whose far end crosses the boundary;
3. capsule contains a smaller coaxial capsule and rejects a side-offset capsule;
4. oriented rectangle/polygon contains a track capsule only when its radius clears every edge;
5. positive-area overlap versus external touching is distinct;
6. unsupported containment combinations return `UNKNOWN`, never false;
7. a compound with two overlapping parts is not claimed to contain a candidate merely because both overlap.

### Stage 2: copper IDs and own apertures

Extend `tests/unit/kicad/test_mask_apertures.py`:

1. pad aperture `copper_source_ids` exactly matches front/back pad copper IDs, including duplicate and unnamed pads;
2. flipped front pad links to `B.Cu` copper;
3. open via links to its same-side via land;
4. inherit via remains unsupported but targeted to only that via land;
5. raw board/footprint graphics remain unlocated and have no invented copper IDs;
6. repeated collection is byte-for-byte deterministic.

Add `tests/unit/kicad/test_copper_exposure.py`:

1. zero/positive pad expansion -> fully exposed component termination;
2. negative pad expansion -> partially exposed component termination;
3. pad without a mask layer -> masked component termination;
4. custom pad copper or custom aperture -> unknown, with exact reason;
5. tented via -> masked unless another board aperture exposes it;
6. open via -> fully exposed via land;
7. inherit via -> only that via land unknown, not every item on the side;
8. front/back results differ for asymmetric intent;
9. touching-only aperture -> masked nominally;
10. unequal duplicate copper IDs -> unknown integrity result.

### Stage 3: detector spatial exposure

Use the real detector layout:

1. front spiral segments wholly inside the disc are `fully_exposed` and retain role `routed_conductor`;
2. any boundary-crossing segment is `partially_exposed` (add a synthetic segment if the current spiral is wholly inside);
3. handle-side front tracks outside the disc are `masked`;
4. the B.Cu return trace remains masked because the disc is front-only;
5. the inner via is classified independently on front and back according to via intent plus spatial disc;
6. no segment is relabeled `component_termination` by the disc;
7. adding a second overlapping disc that jointly might cover a segment returns `unknown` until union containment exists.

### Stage 4: pairwise selector execution

Extend `tests/unit/kicad/test_profile_integration.py`:

1. a requirement scoped to `fully_exposed` fires for two exposed detector/synthetic tracks and not for two proven masked tracks;
2. `partially_exposed` is independently selectable;
3. `component_termination` role selector matches pads regardless of full/partial/masked state;
4. directional A/B mask and role selectors are not accidentally symmetric;
5. empty selectors retain today's net-group behavior;
6. unknown state emits `ordinary_pairwise_clearance_scope_unverified` rather than disappearing;
7. the A* router remains conservatively net-wide for a scoped requirement and the exact verifier accepts the result.

### Stage 5: raw/unsupported and design-report behavior

1. targeted unsupported pad/via source produces one local exposure warning;
2. unlocated raw F.Mask graphic makes non-full front copper unknown but does not affect back copper;
3. an already fully exposed copper region remains full in the presence of an unresolved additional opening;
4. `fab.copper_exposure_unverified` and `fab.solder_mask_web_unverified` are separate findings with separate triggering conditions;
5. zones are explicitly reported unsupported/unverified until final filled geometry is available.

## Recommended implementation order

1. Correct the public two-axis selector schema and add shared copper source-ID helpers.
2. Populate `copper_source_ids` for pad and via aperture sources, including unsupported targeted sources.
3. Add exact outer-copper collection and the conservative geometry proof functions.
4. Implement exposure classification and detector tests.
5. Annotate virtual-DRC items only at the exposure-scoped checking boundary; remove hard-coded labels.
6. Make ordinary pairwise selectors executable and surface unknown scope.
7. Share one aperture collection with design checks and add rich unverified findings.
8. Defer general exact union containment and exact KiCad-filled zones, keeping their outputs explicitly `unknown` meanwhile.

This order closes the current false-label gap without making unsupported compound, raw-graphic, via-inherit, or zone geometry look exact.
