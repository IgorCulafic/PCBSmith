# Solder-mask geometry architecture audit

Date: 2026-07-15  
Scope: read-only audit of the current repository. No production files were changed.

> **Implementation checkpoint (later 2026-07-15):** This document records the
> pre-implementation architecture snapshot; present-tense gap statements below
> are historical. The completed slice now includes the pure exact kernel,
> lossless pad mask parsing, a typed front-side board-disc bridge, per-side via
> intent/tenting serialization, the exact aperture collector, and the
> `fab.solder_mask_web`, `fab.mask_aperture_merge`, and
> `fab.solder_mask_web_unverified` design checks. Raw board/footprint mask
> graphics, exact custom/chamfered pads, ratio clauses, missing effective
> expansion, and inherited via policy remain explicitly unsupported/unverified;
> no numeric pass is fabricated. The later R1 exposure slice now derives
> per-side mask state and source role, applies ordinary pairwise selectors, and
> adds the `outer_copper_exposure` / `fab.copper_exposure_unverified` report
> gate. Exact custom/footprint graphics and safety/creepage authority remain
> incomplete.
>
> KiCad 10.0.3 serialization and Gerber behavior are pinned by the durable
> 88-file corpus (87 hash-covered artifacts plus the manifest) at
> `docs/reference/fixtures/kicad-mask-parity-10.0.3/`. Its hash manifest is
> `hashes.sha256` (manifest SHA-256
> `22B8B15D93D1E3472B7222E9A8FB55D7908D73DC5ABAB1BA69084C62A96BDF14`).
> It verifies board-global expansion, non-zero local replacement, local-zero
> inheritance, side-specific layer membership, KiCad 10.0.3 rejection of
> `solder_mask_margin_ratio`, and per-side via `none|yes|no` semantics.
> The earlier mask-kernel checkpoint had a green KiCad and full suite with nine
> gated golden skips. The later focused exposure/selector run is 106 passed and
> the report/design-check run is 26 passed; the full suite has not yet been
> rerun after those later slices.

## Executive result

The generated KiCad board usually retains more mask information than PCBSmith's
typed in-memory model. Imported footprint source trees are parsed and later
re-serialized almost intact, so pad mask layers and source-local mask settings can
survive into the `.kicad_pcb`. However, `PadSpec`, `FootprintSpec`, `ViaSpec`, and
`BoardLayout` do not expose enough of that information to calculate the physical
solder-mask apertures. Consequently:

1. `minimum_solder_mask_web_mm` is a declared profile field but has no consumer.
2. Current copper exposure labels are assumptions, not results derived from mask
   geometry.
3. Via tenting/opening state is not represented or explicitly rendered.
4. Board-level mask graphics are opaque KiCad strings, so the checker cannot
   combine them with pad apertures.

The correct next slice is a separate, engine-neutral mask-aperture model. It should
not be folded into `_Stadium`: copper/hole collision geometry, solder-mask
manufacturability, copper exposure, and electrical-insulation safety are distinct
domains.

## 1. What the source currently preserves and loses

### 1.1 Imported footprint source and round-trip rendering

What is preserved in the generated board:

- `load_footprint()` parses the complete `.kicad_mod` into an s-expression tree
  and retains it as `ImportedFootprint.tree`
  (`src/pcbsmith/kicad/library.py:289-325`).
- The renderer deep-copies that tree, strips only top-level version/generator and
  legacy identity clauses, then re-emits the remaining body
  (`src/pcbsmith/kicad/library.py:658-703`). Pad-local `(layers ...)`,
  `(solder_mask_margin ...)`, `(solder_mask_margin_ratio ...)`,
  `(roundrect_rratio ...)`, custom primitives, and footprint mask graphics are
  therefore retained if they exist in the source tree.
- Back-side placement recursively swaps `F.*` and `B.*` layer names
  (`src/pcbsmith/kicad/library.py:883-895`). Thus raw source mask-layer membership
  is also flipped in the emitted footprint.
- Pad UUIDs are rebased per placed footprint and pad-name occurrence
  (`src/pcbsmith/kicad/library.py:713-748`). This occurrence scheme is suitable
  for aligning future aperture identities with the emitted KiCad objects.

What is lost from the typed geometry:

- `PadSpec` retains name, location, kind, width/height, drill/hole, angle, and a
  shape string only (`src/pcbsmith/kicad/library.py:153-199`). It does **not**
  retain pad layer membership, `roundrect_rratio`, chamfer settings, mask margin,
  mask margin ratio, or custom primitives.
- The pad parser reads only name/kind/shape, `at`, `size`, and `drill`
  (`src/pcbsmith/kicad/library.py:344-402`).
- For custom pads, `_custom_pad_extents()` reduces all primitives to one bounding
  box (`src/pcbsmith/kicad/library.py:513-547`). `_measure()` then moves the typed
  pad centre to that box centre and replaces width/height with the box extent
  (`src/pcbsmith/kicad/library.py:373-389`). The original anchor and primitive
  topology cannot be reconstructed from `PadSpec` afterward.
- The vendored corpus already relies heavily on `roundrect_rratio` (for example
  `ai_assets/kicad_footprints/Capacitor_SMD__C_0603_1608Metric.kicad_mod:88-98`),
  but that ratio is absent from `PadSpec`.
- `FootprintSpec` has no typed mask graphics collection
  (`src/pcbsmith/kicad/library.py:222-246`). `_measure()` examines footprint
  graphics only for `F.CrtYd`, `F.Fab`, and a subset of `F.SilkS`; `F.Mask` and
  `B.Mask` graphics are ignored by the typed model
  (`src/pcbsmith/kicad/library.py:405-447`). They remain only in the raw tree.

Current corpus observation: the vendored footprints contain normal pad
`F.Mask` memberships and many round-rect ratios, but the repository search found
no vendored `solder_mask_margin` or `solder_mask_margin_ratio` clauses. The parser
must still support those clauses; relying on the current corpus would make the
model fail as soon as another official or project footprint is added.

### 1.2 Pad mask apertures

The emitted footprint generally preserves whether each source pad participates in
`F.Mask`/`B.Mask`, because the renderer retains raw pad clauses. The checker does
not know this:

- `_collect_items()` infers copper layers from hole presence and footprint flip,
  not from the pad's actual `(layers ...)` clause
  (`src/pcbsmith/kicad/virtual_drc.py:312-370`).
- It labels every non-NPTH pad copper item as `component_termination`
  (`src/pcbsmith/kicad/virtual_drc.py:356-369`), even if the source pad deliberately
  omits a mask layer or a larger board graphic exposes surrounding copper.
- Rectangular and round-rect pad geometry is represented by an underestimating or
  covering stadium for copper collision purposes
  (`src/pcbsmith/kicad/virtual_drc.py:326-345`). That approximation is not adequate
  for measuring a narrow mask dam at corners.

Therefore the current model cannot determine the actual aperture shape, the web
between two pad apertures, or whether a given pad is exposed on one or both sides.

### 1.3 Board-level mask graphics/openings

- `BoardLayout.graphics` is `tuple[str, ...]`, described as raw pre-rendered
  graphics (`src/pcbsmith/kicad/board.py:180-208`). The strings are appended to
  the board unchanged (`src/pcbsmith/kicad/board.py:727-728`).
- `mask_opening_disc()` creates a 96-point filled `gr_poly` on `F.Mask`; its UUID
  is deterministic from semantic circle parameters
  (`src/pcbsmith/kicad/shaped_board.py:401-433`). This is the only typed-looking
  mask helper, but it returns an opaque string and discards the analytic circle at
  the `BoardLayout` boundary.
- The metal-detector test checks only that some graphic string names `F.Mask`
  (`tests/unit/kicad/test_metal_detector_board.py:136-138`). It does not validate
  the aperture boundary, mask web, or resulting copper exposure.
- Fabrication discovery uses a text heuristic: any `gr_poly` plus `F.Mask` means
  the board has a mask opening (`src/pcbsmith/kicad/fabrication.py:71-73`). It does
  not understand side, shape, or which copper is exposed.
- Existing virtual-DRC graphic parsing is limited to front-silkscreen text and
  lines (`src/pcbsmith/kicad/virtual_drc.py:1107-1153`); it does not parse mask
  graphics.

The raw string channel can represent arbitrary KiCad graphics, but it is not a
safe geometry API. Future mask checks should consume typed board graphics and use
raw strings only as a compatibility fallback that yields an explicit
"unverified mask graphic" finding when parsing is incomplete.

### 1.4 Vias and tenting

- `ViaSpec` contains only x/y, net, copper diameter, and drill diameter
  (`src/pcbsmith/kicad/board.py:170-176`). There is no front/back mask opening,
  tenting policy, filled/capped status, or per-side override.
- `_via()` emits location, size, drill, copper layers, net, and UUID only
  (`src/pcbsmith/kicad/board.py:1455-1470`). It emits no explicit tenting or mask
  aperture intent.
- `_collect_items()` currently labels via copper on both outer layers
  `external_masked` (`src/pcbsmith/kicad/virtual_drc.py:414-444`). That label is not
  derived from KiCad mask settings or an aperture model.
- The board header declares F/B mask layers but no mask manufacturing defaults
  (`src/pcbsmith/kicad/board.py:1515-1538`). The generated `.kicad_pro` writes
  copper, hole, track, via, annular-ring, and hole-web rules, but no solder-mask
  expansion or tenting settings
  (`src/pcbsmith/kicad/export_divider_highpass_led.py:65-110`).

The engine must treat current via mask state as **unknown**, not masked, until a
typed policy is added and rendered explicitly. The exact KiCad syntax/settings
must be pinned with local KiCad/Gerber fixtures before production code writes it;
this audit intentionally does not guess a version-specific field.

### 1.5 Rule-profile and checking gap

- `FabricationGeometryProfile.minimum_solder_mask_web_mm` exists and is optional
  (`src/pcbsmith/rule_profiles.py:59-88`). There is no accompanying default mask
  expansion, pad/footprint override resolution policy, via mask policy, or
  merge/gang-relief policy.
- No production consumer references `minimum_solder_mask_web_mm`; current searches
  find it only in the profile and its default-value test.
- `CopperExposure` has masked, exposed, component-termination, and unknown labels
  (`src/pcbsmith/rule_profiles.py:25-31`), but `_Stadium.exposure` defaults to
  unknown and is currently assigned by object kind rather than computed from mask
  geometry (`src/pcbsmith/kicad/virtual_drc.py:87-101`, `356-444`).

If a profile declares `minimum_solder_mask_web_mm` today, the board can silently
pass without that constraint being evaluated. The implementation must eliminate
that silent-pass condition.

## 2. Proposed engine-neutral typed model

Create a module outside the KiCad serializer, for example
`src/pcbsmith/mask_geometry.py`. Keep all coordinates in board-space millimetres
after placement. Use frozen Pydantic models with `extra="forbid"` and an explicit
schema version, matching the repository's newer rule/routing IR approach.

Suggested types (names illustrative):

```text
MaskSide = front | back
MaskSourceKind = pad | via | footprint_graphic | board_graphic
MaskVerification = exact | bounded_approximation | unsupported

Disc(center, radius)
Capsule(a, b, radius)                         # oval and stroked line
OrientedRect(center, width, height, angle)
RoundedRect(center, width, height, corner_radius, angle)
Polygon(vertices)                             # validated simple polygon
ArcStroke(center, radius, start, sweep, width)
Compound(parts)                               # geometric union

MaskAperture:
    schema_version
    source_id
    parent_source_id
    source_kind
    side
    geometry
    owner_ref | None
    copper_source_ids
    merge_group_id | None
    verification
    unsupported_reason | None
```

Related input intent should remain separate from the derived aperture:

```text
PadMaskIntent:
    sides                       # parsed from pad layers
    local_margin_mm | None
    local_margin_ratio | None
    source_roundrect_ratio/chamfer/custom primitives

ViaMaskIntent:
    front = open | tented | inherit
    back  = open | tented | inherit

MaskProcessSettings:
    default_pad_expansion_mm | None
    default_via_policy
    minimum_web_mm | None
    accidental_merge_policy
```

`MaskProcessSettings` belongs to fabrication geometry, never to the insulation
profile. If the effective pad expansion or via policy remains inherited but no
explicit board/process default is available, aperture verification is
`unsupported` and the declared web rule produces a review/blocker finding rather
than a pass.

### 2.1 Stable source identities

Use the same semantic inputs already used by the board writer, but do not use list
position alone:

- Placed pad aperture: placed-footprint identity (`component.uuid_path` plus
  reference), pad name, duplicate-pad occurrence, and mask side. Duplicate pad
  occurrence must match `render_embedded_footprint()`'s counter
  (`src/pcbsmith/kicad/library.py:713-748`).
- Via aperture: canonical via identity (net, normalized x/y, size, drill) plus
  duplicate occurrence, matching `_via_identity()`
  (`src/pcbsmith/kicad/board.py:1408-1416`).
- Typed board graphic: semantic geometry, side, stroke/fill, and duplicate
  occurrence, matching the strategy already used by `mask_opening_disc()` and
  the shaped-graphic UUID test
  (`src/pcbsmith/kicad/shaped_board.py:415-424`,
  `tests/unit/kicad/test_shaped_graphic_identity.py:24-45`).
- Compound child: parent source ID plus a stable primitive path/occurrence.

A UUID5 string generated from these parts is acceptable, but give the mask schema
its own identity prefix (for example `mask-aperture-v1`) so it is not confused with
the KiCad object's file UUID. Store `parent_source_id` so primitives that form one
logical opening are never checked against each other.

## 3. Exact mask-web algorithm

### 3.1 Rule meaning and aperture grouping

The mask layer is negative: each `MaskAperture` is an area where mask is absent.
For each side independently:

1. Resolve every pad/via/process override to a concrete aperture or an explicit
   unsupported result.
2. Transform footprint-local apertures through pad angle, footprint placement
   rotation, translation, and back-side mirror. Back-side placement must also swap
   front/back mask sides, as the serializer already does.
3. Union all geometric parts with the same `parent_source_id`/`merge_group_id`.
4. Spatially index aperture bounds and evaluate only pairs closer than the declared
   minimum web.
5. Compute the exact Euclidean separation between the two **closed aperture
   regions**. For disjoint regions, that distance is the residual mask web.
6. If `0 < web < minimum`, emit `fab.solder_mask_web` blocker.
7. If regions touch/overlap, the physical result is one merged opening, not a
   narrow positive dam. Accept it only when both belong to a declared common
   `merge_group_id`; otherwise emit a distinct `fab.mask_aperture_merge` finding.
   This avoids falsely describing a deliberate gang opening as a sub-minimum web
   while still catching accidental loss of isolation between apertures.
8. Any unsupported aperture that could participate in a near pair emits
   `fab.solder_mask_web_unverified`; never silently pass it.

Do not compare child primitives within the same compound aperture. For a large
board graphic such as the detector coil disc, first union that graphic with any
pad openings it intentionally covers; internal overlaps are not mask dams.

### 3.2 Shape kernels

Implement a small convex-distance kernel rather than reusing the copper stadium
approximation. An analytic support function plus a deterministic GJK distance
solver is sufficient for all convex shapes below; concave polygons can be
validated and triangulated into a `Compound` of convex parts. Pin iteration and
distance tolerances in the model so results are deterministic.

- **Circle:** analytic disc. Pairwise disc gap is centre distance minus radii.
- **Oval:** exact capsule/stadium. Capsule-capsule gap is segment-segment distance
  minus radii; capsule versus other convex shapes uses the common support kernel.
- **Rectangle:** oriented rectangle with four exact corners; do not substitute a
  stadium. Rectangle-polygon separation is minimum edge/vertex distance unless
  the regions intersect.
- **Round-rectangle:** an inner oriented rectangle Minkowski-summed with a disc of
  the exact parsed corner radius. Its support function is the inner-rectangle
  support plus the radius in the query direction. Preserve
  `roundrect_rratio`; do not assume the current virtual-DRC value of 0.25.
- **Custom pad:** preserve the anchor shape and every primitive before the current
  bounding-box fold. Convert supported filled polygons/rectangles/circles and
  stroked lines into a `Compound` union. A positive isotropic mask expansion can
  be applied to each union part because dilation distributes over union. A
  negative margin (erosion) does **not** distribute over a union; mark compound
  custom pads with negative expansion unsupported until a robust boolean-offset
  implementation exists. Also mark custom pads unsupported when they contain
  unhandled arcs, self-intersecting polygons, subtractive/knockout semantics, or
  ambiguous anchor-only behaviour.
- **Board/footprint graphics:** represent fill and stroke separately and union
  them. Filled circle/rect/simple polygon are exact. A stroked line is a capsule;
  a stroked polyline is the union of segment capsules and vertex discs. A filled
  concave polygon is exact after validation/triangulation. A filled/stroked arc or
  ring requires an analytic `ArcStroke`; until that exists, report unsupported
  rather than using an unbounded tessellation. A bounded tessellation is acceptable
  only if it records maximum chord error and subtracts that error from the
  reported web, making the result conservative.

Pad mask expansion semantics and precedence must be parity-tested against the
installed KiCad version and exported Gerbers. The geometry model should retain
both the source pad and the resolved aperture so a wrong precedence assumption is
observable. Do not infer a zero margin merely because the source pad has no local
margin clause.

## 4. Copper exposure classification is a separate derived result

Mask-web manufacturability asks whether mask dams can be fabricated. Copper
exposure asks which outer copper areas are inside the final union of mask
apertures. They share aperture geometry but are not the same rule.

After aperture union is complete, intersect each outer-layer copper object with
the corresponding side's opening region:

- no intersection and fully covered by a verified mask model:
  `external_masked`;
- fully/partly inside an opening: `external_exposed` plus an explicit coverage
  relation (`full`/`partial`), or add `external_partially_exposed` to the current
  literal;
- pad termination exposed by its own pad aperture: preserve the semantic
  `component_termination` role, but record the verified side and coverage;
- unknown global expansion, via policy, or unsupported opening geometry:
  `unknown`.

At audit time, this would have corrected the then-current assumptions that all
tracks and vias were masked and all pads were component terminations
(`src/pcbsmith/kicad/virtual_drc.py:356-444` in that snapshot). The later R1
implementation replaced those hard-coded labels with source-derived roles and
per-side exposure results; it also activates the ordinary pairwise selectors.
The detector's F.Mask disc now classifies overlapping spiral tracks as exposed.
A through-hole termination or via can still differ front versus back.

Do not encode this by changing `_PhysicalItemKind`. That enum identifies copper,
holes, bare holes, and geometry proxies (`src/pcbsmith/kicad/virtual_drc.py:62-68`).
Exposure is a relationship between copper and a verified mask region.

## 5. Electrical-insulation safety is independent

`minimum_solder_mask_web_mm` is a fabrication capability/geometry constraint. It
does not prove electrical clearance, creepage, coating qualification, pollution
degree, material group, or an end-product safety standard. Solder mask must not be
credited as solid insulation or conformal coating merely because a mask web was
manufacturable.

The repository already correctly gates insulation clearance behind a qualified
insulation profile and states that creepage is unimplemented
(`docs/pcb-design-rules.md:307-321`). Keep the mask model under
`FabricationGeometryProfile`; only an independently qualified protection system
with explicit evidence could affect safety calculations.

In short:

- copper collision geometry -> electrical/fabrication spacing between conductors;
- mask aperture geometry -> mask web and copper exposure;
- qualified insulation geometry -> safety clearance/creepage review.

No result in one category should silently satisfy another.

## 6. Minimal implementation and test sequence

1. **Add the pure typed geometry kernel.**
   - New `src/pcbsmith/mask_geometry.py` with shapes, compound apertures,
     deterministic IDs, transforms, bounds, union grouping, and exact convex
     distance.
   - New `tests/unit/test_mask_geometry.py`: circle, rotated oval, oriented rect,
     non-0.25 roundrect, explicit concave-polygon rejection/convex-compound input,
     compound grouping,
     overlap/merge, and deterministic IDs.

2. **Make footprint parsing lossless for mask purposes.**
   - Extend `PadSpec`/`FootprintSpec` in `src/pcbsmith/kicad/library.py` with
     defaults so existing constructors remain compatible.
   - Preserve layers, roundrect/chamfer values, original anchor, local mask
     overrides, custom primitives, and footprint-level F/B.Mask graphics.
   - Add synthetic parser fixtures to `tests/unit/kicad/test_hole_geometry.py` or a
     new `test_mask_parsing.py`, covering omitted mask layers, per-pad margins,
     duplicate pad names, flipped footprints, and custom primitives.

3. **Introduce typed board graphics without breaking raw graphics.**
   - Add `BoardLayout.mask_apertures` or a general typed `board_graphics` field;
     keep `graphics: tuple[str, ...]` temporarily for compatibility.
   - Change `mask_opening_disc()` to construct a true typed disc and render it at
     the serializer boundary. Pin its existing UUID and emitted 96-point KiCad
     representation in `test_shaped_graphic_identity.py`.
   - Raw F/B.Mask strings that cannot be parsed must generate an unverified
     finding when a mask-web rule is active.

4. **Represent via mask intent explicitly.**
   - Add per-side `open|tented|inherit` fields to `ViaSpec` and include them in
     semantic identity.
   - Verify KiCad syntax and Gerber output for all four front/back combinations
     before changing `_via()`. Add byte-stability and Gerber aperture tests.

5. **Resolve process settings explicitly.**
   - Extend `FabricationGeometryProfile` with the mask expansion/tenting inputs
     needed to derive apertures. Keep them optional; an active minimum-web rule
     plus unresolved inputs must be unverified, not zero-defaulted.
   - Render verified settings into the KiCad project/board and add project-profile
     tests beside `tests/unit/kicad/test_project_profile.py`.

6. **Collect apertures and enforce the rule.**
   - Add an aperture collector parallel to `_collect_items()`, not inside it.
   - Add profile-scoped `fab.solder_mask_web`, `fab.mask_aperture_merge`, and
     `fab.solder_mask_web_unverified` findings in
     `src/pcbsmith/kicad/design_checks.py`.
   - Tests: `minimum_solder_mask_web_mm=None` has no behavioural change; deliberate
     positive sliver fails; declared gang opening passes; accidental merge is
     distinct; unsupported nearby custom/arc geometry cannot pass.

7. **Derive exposure from the same final aperture union.**
   - Replace hard-coded exposure assignments in `_collect_items()` with a
     post-processing relation. Test detector spiral exposure, masked ordinary
     track, pad without a mask layer, partial exposure, and asymmetric via sides.

8. **Run KiCad/Gerber parity fixtures, then the full suite.**
   - Generate one fixture per supported pad shape and via state, export F/B mask
     Gerbers with `kicad-cli`, and compare measured aperture bounds/webs to the
     engine model within a pinned tolerance.
   - Run focused unit tests, all KiCad tests, full pytest, and gated goldens.

## 7. Conservative unsupported cases for the first production slice

The checker should emit review/blocker findings, not numeric passes, for:

- missing effective board/process mask expansion while the web rule is active;
- inherited/unspecified via tenting;
- raw F.Mask/B.Mask graphic strings not losslessly parsed;
- custom pads after lossy bbox-only parsing;
- custom compounds with negative mask margin;
- subtractive/knockout custom primitives or self-intersecting polygons;
- arc/ring strokes without an analytic or error-bounded implementation;
- unknown KiCad mask-margin precedence or ratio semantics;
- any version-specific KiCad construct absent from the pinned parity corpus.

Unsupported geometry far beyond the spatial search radius need not block unrelated
web checks, but the final board-level report should list it as unverified if the
profile asserts comprehensive mask-web compliance.

## 8. Conflict and regression risks

- **Custom-pad centre mutation:** current parsing changes `x_mm/y_mm` to the custom
  bbox centre (`library.py:373-389`). New primitive parsing must preserve the
  original anchor before that mutation or transforms will be applied twice.
- **Positional `PadSpec` construction:** add only defaulted fields after existing
  fields or migrate constructors explicitly; many tests and library builders use
  the current dataclass.
- **Raw `BoardLayout.graphics`:** shaped-board generators populate strings directly.
  Removing the field in one step would cause broad breakage. Use a compatibility
  bridge and reject only unparsed mask strings when the mask rule is active.
- **Coordinate frames:** `BoardLayout` uses board-local coordinates while emitted
  graphics add `BOARD_SHEET_ORIGIN_MM`; imported pads are footprint-local until
  placement. Perform checking in board-local space and add the sheet origin only
  during KiCad rendering.
- **Back-side transforms:** `_flip_tree()` negates x/angle and swaps layers, while
  virtual geometry uses `_back_offset`. One shared transform test must prove typed
  and emitted apertures coincide.
- **Identity concurrency:** the repository is actively replacing random KiCad
  UUIDs with semantic UUID5 identities. Reuse the final identity helper/prefixes;
  do not create a second incompatible occurrence counter.
- **Pydantic profile copies:** tests frequently use `model_copy(update=...)`, which
  does not provide the same construction-validation guarantee as rebuilding a
  model. Add direct-construction validator tests for incompatible mask settings.
- **Ordinary clearance filters:** `CopperExposure` is already used by pairwise
  clearance requirements. Changing hard-coded labels to verified/unknown can alter
  which requirements apply; add regression tests for both masked and exposed
  selectors.
- **Intentional merged openings:** a naïve `distance < minimum` rule would flag the
  detector's large opening and any gang relief. Preserve merge intent and report
  accidental aperture merge separately from a narrow positive web.
- **KiCad setting names/semantics:** the current project writer does not emit mask
  settings. Do not add guessed JSON or board syntax; pin it using installed-KiCad
  board and Gerber round trips first.

## Recommended decision

Implement the mask geometry as the final R1 fabrication-geometry slice, before
claiming `minimum_solder_mask_web_mm` is enforced or using exposure-specific
ordinary-clearance rules as authoritative. The smallest honest milestone is:

- exact circle/oval/rect/roundrect pad apertures;
- typed filled disc/rect/polygon board openings;
- explicit via front/back intent;
- positive-web and accidental-merge findings;
- unsupported findings for unresolved defaults/custom/arc cases;
- exposure derived after aperture union.

That milestone closes the current silent rule gap without conflating mask geometry
with copper clearance or safety insulation.
