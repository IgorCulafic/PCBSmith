# Phase 17 production-workflow checkpoint

Date: 2026-07-23

Status: active; core workflow and retained migration evidence implemented;
post-freeze cross-board proof remains

Phase 17 began only after the Phase 16 contract fingerprints, focused tests,
and full 2,763-case checkpoint passed.

## Implemented

`src/pcbsmith/prompt_examiner.py` now provides:

- exact prompt character-span replay;
- explicit, derived, unknown, and conflict claim states;
- a no-invention rule for unknown values;
- typed edge-offset, center, spacing, tolerance, access, aperture,
  orientation, and side anchors;
- typed domain consequences and at least two spirit-preserving alternatives
  for every hard conflict;
- deterministic blocked/needs-decision/ready-for-concept outcomes;
- population of all ten shared project-context axes;
- explicit unresolved records for every absent context.

`src/pcbsmith/workflow_feasibility.py` now provides exact usable-region,
keepout, component/access-envelope containment, bounded deterministic
alternative-neck allocation, capacity records, and compact failing-net
diagnostics. Search-budget exhaustion is `unverified`, not a false
infeasibility claim. Typed concept observations compare the saved design to
approved edge, center, spacing, tolerance, side, orientation, access, and
aperture anchors.

`src/pcbsmith/production_workflow.py` now provides:

- immutable generation directories and an atomic `CURRENT.json` pointer;
- retained rollback generations without changing the previous pointer;
- exact artifact and canonical review-manifest binding;
- automatic placement-board persistence plus canonical review generation;
- inspection as a new immutable generation rather than in-place mutation;
- deterministic topological route-domain and net ordering;
- exact-accepted, board-chain-bound resumable route checkpoints;
- execution-profile bindings for placement, routing, rendering, and
  verification plus native work ledgers, heartbeats, time checks, and stage
  telemetry;
- a fail-closed routing-entry gate covering prompt, ten project contexts,
  feasibility, concept drift, saved-board review, transaction identity, and
  execution profile.

The CLI now exposes `workflow-examine`, `production-placement-review`,
`production-visual-inspect`, and `workflow-route-gate`. These are the Phase 17
production entrypoints; legacy topology commands remain compatibility paths
until migration evidence is complete.

The visual package gained:

- deterministic repeat-hash, physical-scale, tiling, mirroring, camera,
  layer, missing-model, and diagnostic-view golden coverage;
- typed triggered diagnostic declarations for stack-up/reference, return
  current, power domains, thermal/current density, high speed, BGA, and DFM;
- fail-closed unresolved applicable diagnostics;
- model-preflight board-revision binding; and
- registered 3D-model transform alignment with tolerances, so shifted models
  can no longer pass required-model preflight merely because their files
  resolve.

The focused checkpoint is 84 tests green across the new Phase 17
contracts, visual/model gates, migration evidence, and CLI regression set.
That run includes live KiCad 10.0.3 R2, R4, and R5 gates. Repository-wide Ruff
and strict mypy over 284 source files pass.

The final frozen-source repository checkpoint collected 2,799 tests: 2,781
passed, 18 intentional skips, zero failures, and zero errors in 647.047
seconds. The retained JUnit evidence is
`.pcbsmith/verification/phase17/full-suite-junit.xml`. The refreshed
stewardship inventory is
`.pcbsmith/verification/phase17/test-check-audit.{json,md}`: it identifies
2,069 authored test functions in 235 files, 244 parametrized functions, and 93
name-matched production check/validation candidates. The 2,799 count is not
2,799 independent PCB rules.

Subsequent migration work added:

- `routing_measured_corpus.py`, which retains a parser-readable serialized
  adversarial negotiated-routing maze plus a compact control case, exact-check
  identities, pass fingerprints, 16,427 measured adversarial expansions,
  routed lengths, and an explicit no-superiority/no-DRC inference boundary;
- a vendored minimal serialization footprint for that adversarial fixture;
- `bus_lcs_cost_persisted_handoff.py`, which consumes the exact-accepted R4
  neutral handoff, deterministically serializes it, requires KiCad
  save/read-back plus clean mandatory DRC, and rejects saved-revision
  substitution;
- a live R4 retained artifact at
  `.pcbsmith/verification/phase17/r4-persisted-handoff.json`, produced with
  KiCad 10.0.3 after correcting its fixture netlist;
- a live two-case R5 shaped-placement corpus at
  `.pcbsmith/verification/phase17/r5-measured-corpus.json`;
- a self-reconstructing R2 corpus at
  `.pcbsmith/verification/phase17/r2-measured-corpus.json`; its repository-owned
  synthetic terminal is resolved through the normal footprint library rather
  than a test-only monkeypatch;
- a six-category, source-hash-bound failure corpus at
  `.pcbsmith/verification/phase17/failure-corpus.json`;
- canonical ordering of independent KiCad DRC findings. Live R4 testing exposed
  that KiCad may emit identical violations in a different order; repeat
  verification now distinguishes this harmless order variance from changed
  findings; and
- a retained exact-MPN discovery exercise at
  `.pcbsmith/phase17-exact-part/sht31-discovery-report.json`. The SHT31-DIS
  official Sensirion datasheet and KiCad 10.0.3 footprint/symbol were retrieved
  into the validated private cache. The required 3D model remained explicitly
  `missing`; no proxy was invented or promoted. The downloaded document cache
  and private source manifest are explicitly gitignored; only the public,
  hash-bound discovery records are repository candidates.

The production routing-entry gate now also consumes the replay-derived project
engineering gate. It requires a complete reviewed inventory, a `ready`
applicability outcome, the same project, and the exact saved neutral-layout
fingerprint. Applicable R6 declarations or exact-part resources can therefore
no longer be omitted while routing is authorized. The native A* production
adapter consumes the selected profile's operative pass/expansion ceilings and
emits checkpoint-bound pass telemetry and heartbeats. Search success remains
insufficient: a caller-supplied exact checker must accept the routed board
before native routing telemetry may report completion.

## Not yet complete

The following Phase 17 work remains:

- complete operative profile binding for production placement and rendering;
- exercise R4/R5 applicability in the production default caller when the
  post-freeze board triggers them, rather than forcing those specialized
  authorities onto every board;
- populate and execute every applicable R6 declaration on the saved/read-back
  post-freeze proof board;
- evaluate KiCad Multi-Channel only when a repeated-channel proof board
  triggers it;
- two materially different end-to-end proofs, including one project whose
  prompt is unseen after implementation freezes.

The remaining work is therefore workflow acceptance on real boards, not an
unresolved repository-test failure. Canonical review packages for those proofs
must still be generated and inspected.

The final item requires a new user-supplied project. Existing thermometer,
Retro-Pad, and BLDC prompts cannot satisfy the post-freeze unseen condition.
