# Phase 14 stack-up/reference-continuity checkpoint

Date: 2026-07-22

## Outcome

The existing exact return-adjacency evaluator now requires an explicit stack-up
authority instead of treating caller-supplied `F.Cu`/`B.Cu` names as sufficient
proof of reference-layer adjacency.

A return-path declaration carries one of two typed contexts:

- `verified`: a board-layout-snapshot-bound two-layer order, explicit adjacent
  signal/reference layer pairs, permitted reference-net identities, intended
  consumer, and applicable source evidence;
- `unknown`: no invented layer order, adjacency, reference nets, or evidence,
  and advisory guidance only.

Exact containment, hard return thresholds, and transition-stitch requirements
cannot be declared under an unknown context. Under a verified context, every
declared layer pair must be present in the verified adjacency set and the
reference net must be named by that context.

## Evidence and replay binding

Verified stack-up evidence requires source identity and revision, a valid
pinned SHA-256, text- or figure-verified locator, confirmed applicability,
fully matched conditions, reviewer identity, matching claim identity, and a
fingerprint over the complete stack-up context.

The stack-up context's own semantic fingerprint is also included in every hard
return-threshold and transition-stitch context fingerprint. Consequently, a
previously approved hard limit cannot survive a changed layer order, adjacency,
reference-net set, evidence binding, board snapshot, or intended consumer.

The evaluator continues to reuse the exact routed-copper graph, selected signal
paths, final reference-fill provenance, segment containment, discontinuity, and
reference-stitch authorities. No duplicate geometry checker was introduced.

## Verification

- 15 focused return-adjacency tests passed.
- 152 shared regression tests passed across return adjacency, routed-copper
  graphs, decoupling loops, connector protection/zones, oscillator zones,
  switching hot loops, and shared semantic IR.
- Ruff passed for the changed IR and focused tests.
- Mypy passed for the return-adjacency IR and evaluator.

New coverage includes unknown-stack-up advisory behavior, exact-model rejection
without authority, stale stack-up evidence, mismatched claims, missing source
revision, absent verified layer adjacency, absent reference-net identity,
hard-threshold invalidation after a verified context change, and legacy-schema
fail-closed behavior.

## Deliberate limits

- The current verified context is exactly two-layer (`F.Cu`, `B.Cu`). It does
  not claim a general multilayer stack-up model.
- Copper order and adjacency do not establish dielectric thickness, Dk/Df,
  copper weight, impedance, loss, return-plane quality, cavity resonances, or
  electromagnetic performance.
- Controlled impedance, field solving, channel analysis, PDN analysis, and
  correlation to fabrication or measurement remain separate future work.
- Production-board integration and materially different cross-board proof
  remain open.

## Next increment

Do not add another universal rule family immediately. The narrow five-item
promotion slice is complete. Next bind these evaluators to named project
contexts and exercise them on materially different production candidates with
retained failure evidence, while keeping incomplete inventories and unsupported
analysis explicit.
