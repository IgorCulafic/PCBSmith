# Phase 14 decoupling-loop evidence gate checkpoint

Date: 2026-07-22

## Outcome

The first narrow Phase 14 electrical-rule promotion is implemented without a
new geometry checker. The existing R6 routed-copper graph, path resolver, and
decoupling-loop evaluator remain the measurement authorities.

`DecouplingLoopPolicy` now distinguishes:

- `advisory`: exact metrics and candidate violations may be reported, but the
  result cannot claim PASS or FAIL;
- `sourced_hard`: PASS or FAIL is possible only after the evidence and
  applicability gate succeeds.

The hard gate requires all of the following:

1. a binding whose claim identity matches the policy;
2. non-empty required conditions, every condition matched, no unmatched
   conditions, and an identified reviewer record;
3. evidence with a source identity and revision, a valid pinned SHA-256 digest,
   a text- or figure-verified locator, confirmed applicability, and conditions
   covered by the binding;
4. a context fingerprint matching the exact retained board/netlist snapshots,
   routed graph, supply and return paths, pad-terminal roles, complete terminal
   inventory, nets, policy thresholds, mode, and intended consumer.

Missing, incomplete, invalid, or stale hard authority produces `UNVERIFIED` and
suppresses policy violations. This prevents a stale citation from authorizing a
changed threshold or changed board context.

## Verification

- `tests/unit/kicad/test_decoupling_loop.py`: 28 passed.
- Shared semantic and switching-loop regression selection: 85 passed.
- `uv lock --check`: passed.
- Ruff: passed across `src`, `tests`, and `tools`.
- Mypy: passed for both implementation modules. The older fixture test file is
  intentionally outside this focused type result because it already contains
  untyped helper debt unrelated to this change.
- Repository-wide mypy checked all 251 source files and reported its one known,
  unrelated assignment error in `kicad/retro_pad_3x3_schematic.py:112`; the two
  changed source modules remain clean.

Coverage includes threshold equality and failure, advisory behavior, absent
bindings, claim mismatch, incomplete applicability, stale context, missing
revision, unpinned sources, unverified locators, conditional applicability,
condition mismatch, replay/tamper rejection, incomplete terminal inventory,
daisy-chain detection, and non-simple projected loops.

## Deliberate limits

- This checkpoint does not define universal decoupling thresholds.
- Legacy bare policy schema v1 is rejected rather than silently promoted; any
  future migration must choose advisory mode or attach explicit hard authority.
- Fixture evidence proves evaluator behavior, not engineering applicability to
  a real component or production board.
- It does not complete connector-to-ESD ordering, oscillator evidence zones,
  switcher hot-loop membership, or stack-up/reference continuity.
- Cross-board exercise and retained failure evidence are still required before
  this can become a default production gate.

## Next increment

Promote connector-to-ESD ordering through its existing connector-zone and
routed-copper authorities. First audit whether those authorities already expose
the physical pad ordering and path evidence needed; do not create a parallel
distance-only check.
