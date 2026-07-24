# Phase 14 oscillator evidence-zone checkpoint

Date: 2026-07-22

## Outcome

The existing R6 oscillator-zone evaluator now has a fail-closed source and
applicability contract for hard rules. This promotes the authority boundary;
it does not replace the exact geometry, qualified final-fill, ground-coverage,
or capacitance-model evaluators already present.

Hard bindings now require:

- source identity and revision;
- a valid pinned SHA-256 digest;
- a text- or figure-verified locator;
- confirmed applicability with non-empty, completely matched conditions;
- a reviewer record;
- a claim identity matching the oscillator policy;
- an exact context fingerprint matching the full declaration.

The context includes canonical board/netlist snapshots, zone geometry,
oscillator/crystal/load-capacitor references, oscillator and allowed nets,
object/component exemptions, forbidden net-class membership, intrusion and
applicability rules, ground/stitch/separation/capacitance requirements,
authority classes, policy claim, and intended consumer. Changing any of those
inputs invalidates the old hard binding.

External-zone intrusion authority is now explicitly hard or advisory. An
advisory zone reports exact overlap evidence as `ADVISORY` and cannot block
route acceptance. A hard zone remains eligible for PASS/FAIL only after its
evidence contract validates.

## Verification

- 15 focused oscillator-zone tests passed.
- 118 cross-authority tests passed across oscillator, connector protection,
  connector zones, decoupling, switching hot loops, and shared semantic IR.
- Ruff passed for the oscillator IR, evaluator, and focused tests.
- Mypy passed for both oscillator production modules.

Coverage now includes advisory intrusion behavior, claim mismatch, missing
revision, stale binding fingerprint, changed consumer, changed component
exemption, changed ground threshold, changed forbidden-net membership, and
legacy-schema fail-closed behavior, in addition to the earlier exact-geometry,
qualified-fill, proof, replay, and tamper cases.

## Deliberate limits

- `OscillatorZoneResult.inventory_scope` remains
  `explicit_supplied_objects_only_not_complete_board_inventory`. This prevents
  the current evaluator from being represented as automatic whole-board
  extraction.
- A clean result applies only to the supplied physical-object set. Production
  integration must add a replay-bound complete-board object inventory before a
  project may use it as comprehensive clearance evidence.
- Stray capacitance still requires a separately qualified stack-up/model result;
  geometry does not fabricate a capacitance value.
- Device oscillation margin, startup, drive level, phase noise, EMI, and lab
  validation remain outside this placement-rule slice.

## Next increment

Audit switching hot-loop membership. The existing projected-area evaluator is
not enough by itself: the next slice must prove that the declared loop contains
the correct topology-specific switching transitions and excludes omitted or
bypassing power terminals before its area result can be authoritative.
