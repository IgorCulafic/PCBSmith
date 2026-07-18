# R5.6b/c shaped serialization and read-back authority — 2026-07-17

## Scope

R5.6a proves an opt-in compatibility seam for a legacy rectangle. R5.6b/c must
prove that a shaped placement/routing candidate survives actual KiCad emission,
read-back, and checks without losing fields that are invisible to route geometry.
An in-memory `BoardLayout` equality assertion is necessary but not sufficient.

This gate uses a small synthetic sentinel fixture before any thermometer pilot.
It changes no default generator or legacy placement/routing entrypoint.

## Sentinel fixture

The fixture contains at least:

- a non-rectangular outline and one typed internal cutout;
- front and back components with asymmetric arbitrary rotations;
- stable component UUID paths and nontrivial component fields;
- a filled-zone declaration, typed solder-mask aperture, raw graphic, hidden
  reference, and relocated/rotated reference label;
- fixed non-target front/back tracks and a via with explicit mask intent;
- target copper that is deliberately replaced by detailed routing; and
- explicit profile, target, width, clearance, R2/R3 policy, and fixed budgets.

Every `BoardLayout` dataclass field is classified as immutable-preserved,
declared-placement-transformable, or declared-target-route-replaceable.
Reflection fails closed when a future field is added without classification.

## `PlacementSerializationAuthority`

A versioned frozen envelope retains:

- canonical complete source BoardLayout and BoardNetlist snapshots that parse
  back to the actual dataclasses;
- the R5 probe, candidate, legalization, surrogate, detailed-routing, and exact
  result fingerprints;
- the final materialized BoardLayout and field-by-field preservation evidence;
- canonical KiCad board text/bytes and SHA-256 from two independent renders;
- stable toolchain/profile/policy/budget/input fingerprints; and
- read-back and check evidence described below.

Its validator recomputes source/final fingerprints, the allowed field delta,
rendered bytes, component/pad/net identities, and every derived report field.
Opaque source or output hashes without replayable snapshots are insufficient.

Target route replacement may remove only segments/vias on declared target nets.
Placement changes may affect only the explicitly movable references and the
matching pose fields. All other fields and fixed/non-target copper must remain
literal and byte-stable under the defined canonical renderer.

## KiCad read-back evidence

`KiCadBoardReadbackEvidence` records the exact emitted-board hash, KiCad version,
command/adapter ID, saved-board hash, parsed identities, and findings. It is
accepted only when all applicable parsers prove:

- reference, footprint, value, stable UUID/path, side, position, and rotation;
- outline and cutout loops with ordered geometry identity;
- zones and their net/layer intent;
- raw graphics, mask apertures, reference visibility/position, and label angle;
- tracks/vias with net/layer/size/mask intent; and
- net/component/pad connectivity identities needed by the exact checker.

If the local reader cannot parse a construct, that axis is `UNSUPPORTED` and
cannot yield reader equality. A successful KiCad CLI process alone is not proof
that every sentinel field survived.

Render-repeat means two clean emissions from the same immutable envelope have
identical bytes. KiCad save-roundtrip equality may use a canonical semantic
read-back fingerprint rather than literal bytes because KiCad can normalize
formatting; the normalization and compared fields must be explicit.

## Check aggregation

The stable exact-check record keeps these outcomes separate:

1. PCBSmith virtual DRC;
2. PCBSmith design/fabrication checks;
3. connectivity and target replacement checks;
4. reader semantic equality;
5. KiCad CLI DRC; and
6. deterministic render/save evidence.

Every sub-check has an ID, tool/version, input hash, findings, and verdict. The
aggregate checker passes only when every required sub-check passes. Missing
KiCad or an unsupported reader axis is routed-unchecked/unverified, never a
fabricated acceptance.

## Firing fixtures

1. A no-move/no-route shaped probe preserves every reflected field and emits
   identical bytes twice.
2. One allowed front transform and one allowed back transform preserve all
   unrelated side/rotation/label identities.
3. Target route replacement removes stale target copper and leaves every fixed
   non-target segment/via literal.
4. Outline, cutout, zone, graphic, aperture, flip, reference visibility,
   reference placement, UUID, component field, and via-mask tampering each fire
   their own preservation/read-back axis.
5. Source, final, render, save, reader, toolchain, profile, policy, and budget
   fingerprint tampering fails reconstruction.
6. Reversed construction of set-like inputs preserves fingerprints while
   ordered geometry changes them.
7. Reader equality and canonical save-roundtrip pass on the supported local
   KiCad version; missing KiCad remains explicit and non-accepted.
8. Virtual/design checks and KiCad DRC each have independent fail fixtures.
9. Exact rejection preserves algorithmic R2 success and all serialized evidence.
10. The resulting authority envelope round-trips through JSON and recomputes
    every derived field without referencing live mutable objects.

R5.6d's measured corpus is a separate reporting slice. It may compare proposals,
work, rejections, length, vias, runtime, reproducibility, and repair burden but
must not claim global superiority from this sentinel fixture.
