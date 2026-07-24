# Phase 14 connector-to-ESD ordering checkpoint

Date: 2026-07-22

## Outcome

The second narrow Phase 14 electrical promotion is implemented. It composes
two existing authorities instead of adding a distance surrogate:

1. `ConnectorZoneResult` supplies the replay-verified connector identity,
   board/netlist snapshots, role, and exact placed connector geometry.
2. `ResolvedCopperPathResult` supplies replay-verified routed legs between the
   connector, protection stages, and protected load.

The new ordering declaration names every copper-leg endpoint and physical pad,
plus every internal ingress-to-egress transition through an ESD or filter
component. The evaluator derives component order from those anchors; it does
not accept a caller-supplied order as measurement evidence.

For every involved net, graph terminal anchors must exactly cover the retained
netlist nodes. The hard ordering policy fails when it finds an undeclared
parallel or bypass component. A project may explicitly declare a known
parallel component on a leg, but that declaration is included in the hard
evidence context fingerprint and therefore cannot be added after review without
invalidating the binding.

## Evidence and applicability gate

A sourced-hard PASS or FAIL requires:

- policy and evidence claim identities to match;
- non-empty applicability conditions, all matched, with a reviewer record;
- source identity and revision, valid pinned SHA-256, verified text or figure
  locator, confirmed applicability, and covered evidence conditions;
- an exact context fingerprint covering the connector-zone result, board and
  netlist snapshots, connector references, every routed path fingerprint,
  physical-pad transition, expected stage order, transition roles, declared
  parallel nodes, and intended consumer.

Advisory policies report candidate violations without claiming acceptance.
Missing path completeness or hard authority returns `UNVERIFIED`; stale
authority suppresses PASS/FAIL.

## Verification

- 20 focused connector-protection tests passed.
- 105 tests passed across connector protection, connector zones, routed-copper
  graphs, decoupling loops, and shared semantic IR/integration.
- Ruff passed for the new IR, evaluator, and focused tests.
- Mypy passed for both new production modules.

The cases cover exact ordering, input-order determinism, non-ESD-first failure,
undeclared bypass detection, evidence-bound declared parallel nodes, incomplete
terminal inventories, advisory behavior, absent/stale/invalid hard evidence,
on-board-module non-applicability, path/pad/transition tampering, and result
replay tampering.

## Deliberate limits

- A transition role is a reviewed semantic declaration; this slice does not yet
  independently qualify the exact protection MPN, voltage, capacitance, surge
  rating, clamp behavior, or package pin mapping.
- It proves ordering on the declared signal chain, not physical ESD return-loop
  inductance, chassis strategy, cable behavior, EMC, or system immunity.
- Production-board and materially different cross-board proof remain open.
- Oscillator evidence zones, switcher hot-loop membership, and stack-up/
  reference continuity remain separate increments.

## Next increment

Audit the existing oscillator-zone authority. Promote its source/applicability
contract and exact keepout/placement evidence without duplicating the connector
oscillator-separation check or inventing universal distance thresholds.
