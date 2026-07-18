# R6.1b fixture 6 copper-removal correction contract — 2026-07-17

## Root review decision

The first fixture-6 candidate is not accepted. Its geometry intersection kernel
and PASS/FAIL/UNVERIFIED split are useful, but three authority errors and one
duplication problem must be corrected before the slice is proven.

## 1. One shared board snapshot authority

R6 must reuse the schema-driven `TypeAdapter` canonical BoardLayout and
BoardNetlist parse/reserialize helpers established by R5.6b. The bespoke manual
snapshot/parser in `kicad/sensor_copper_removal.py` must be removed. R6 may add
only copper-specific fingerprints around the shared canonical snapshots.

This is a dependency on a lower-level shared serialization utility, not on R5
placement behavior. If necessary, move the generic snapshot helpers into a
neutral `kicad/board_serialization.py` module and have both R5 and R6 import it.

## 2. Removal geometry is explicit hard design geometry

A caller-selected removal shape cannot borrow qualified slot-process authority.
The removal declaration is a separate exact design constraint:

- its rule authority is `HARD_GEOMETRY`, not
  `QUALIFIED_PROCESS_REQUIREMENT`;
- it binds the selected isolation candidate, the accepted exact slot feature,
  and the complete fixture-5 isolation-result fingerprint;
- it names a dedicated geometry evidence/applicability binding;
- that binding's `geometry_source_fingerprint` equals
  `declaration.geometry.semantic_fingerprint()`;
- the binding is complete, reviewer-bound, checksum-pinned, applicability-
  complete, and is cited by the hard-geometry semantic rule; and
- the rule names the declaration/source feature and exact board region it
  governs.

The selected fabrication profile remains necessary to prove the physical slot
candidate, but it does not magically authorize an arbitrary copper-removal
shape. Generic Sensirion advice cannot create this geometry binding.

Incomplete, stale, wrong-rule, wrong-candidate, wrong-feature, or geometry-
fingerprint-mismatched authority is `UNVERIFIED`, never PASS.

## 3. Applicability is not success

A physical copper source on a layer with no applicable removal declaration is
`NOT_APPLICABLE`, not PASS. `CopperRemovalSourceEvidence` must enforce:

- empty applicable-declaration identities => `NOT_APPLICABLE`;
- one or more applicable declarations => PASS, FAIL, or UNVERIFIED only; and
- the board aggregate ignores non-applicable sources while preserving their
  explicit records.

Opposite via lands therefore remain distinct physical sources and the
non-declared side is explicitly non-applicable.

## 4. Exact final-zone-fill provenance

An exact filled-zone carrier must bind the complete layout, live zone index,
zone source ID, net, layer, geometry, source artifact checksum, reader/tool ID
and version, and canonical record checksum. It must additionally bind a typed
supported reader policy or explicit project tool qualification; arbitrary
non-empty reader strings cannot establish exact authority.

Unflooded BoardLayout zone intent remains `UNVERIFIED` whenever relevant. A
final-fill carrier never changes or hides the retained zone intent identity.

## Required firing fixtures

1. Track, front/back via lands, transformed front/back pad, and exact filled
   zone overlap the bound removal region and FAIL.
2. Separation PASSes and deterministic boundary touching follows the explicit
   no-positive-interior-overlap policy.
3. Opposite-layer physical copper with no declaration is NOT_APPLICABLE.
4. Unflooded zone intent and unsupported pad geometry are UNVERIFIED when
   applicable.
5. Wrong candidate/feature/isolation fingerprint, qualified-process rule
   substitution, missing/incomplete geometry binding, and geometry fingerprint
   mismatch are UNVERIFIED.
6. Arbitrary reader/tool identity, stale artifact/layout/zone/net/layer, and
   record tamper are rejected.
7. Reversed set-like inputs are deterministic; ordered geometry remains
   sensitive; complete JSON reconstruction reruns every derived record.
8. No bridge-count/width, validation campaign, performance, antenna, or later
   R6 claim is added in this slice.
