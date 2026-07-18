# R5.6b shaped-serialization root review corrections — 2026-07-17

The first R5.6b candidate remains bounded to canonical schema round-trip,
declared layout deltas, and deterministic render repeat. It makes no reader,
save-roundtrip, DRC, or corpus claim.

Before acceptance it must complete these corrections:

1. Keep the sentinel within the real renderer's supported surface. The current
   renderer supports the typed front disc aperture used by the fixture; it does
   not support the added back aperture. Unsupported input must be a rejection
   fixture, not part of the passing sentinel.
2. Tamper tests operate on `model_dump(mode="python")` dictionaries and must
   mutate dictionaries rather than call Pydantic methods on them.
3. Pose maps are closed, unique records. Source and final `part_y_mm` and
   `part_rotation` may contain at most one entry per placed reference;
   `part_flip` may contain each reference at most once. A movable reference may
   change its one pose/side record but may not gain duplicate or shadow records.
4. Placement component order, component identity/UUID/fields, fixed pose
   records, immutable fields, and literal fixed/non-target segment/via order
   remain unchanged. Only declared target-net copper may be replaced.
5. Complete TypeAdapter parse plus exact canonical reserialization remains the
   authority for every BoardLayout and BoardNetlist field. Future unclassified
   BoardLayout fields must fail the reflected policy gate.

Acceptance requires focused and adjacent placement tests, explicit duplicate
pose-map fixtures, Ruff, strict focused mypy, deterministic repeated render,
and reconstruction/tamper replay.
