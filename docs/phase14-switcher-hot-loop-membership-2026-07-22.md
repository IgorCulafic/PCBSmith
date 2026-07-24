# Phase 14 switcher hot-loop membership checkpoint

Date: 2026-07-22

## Outcome

The existing exact switching-hot-loop area evaluator now proves declared loop
membership before an area threshold can become authoritative.

Each loop leg retains its exact routed-copper path, net, terminal anchors, and
physical pad identities. Each adjacent-leg transition now additionally names:

- the component traversed between the two nets;
- ingress and egress physical pad source identities;
- a typed switching role such as high-side switch, freewheel rectifier, input
  energy storage, transformer primary, or output rectifier.

The evaluator verifies that both transition anchors belong to the same declared
component and exact pads. For every leg net, graph anchors must exactly cover
all retained netlist terminals. Undeclared third components are reported as
parallel/bypass membership violations; a reviewed project-specific parallel
node can be declared, but that declaration changes the source-context
fingerprint and therefore requires renewed authority.

## Evidence and disposition

The existing advisory/sourced-hard split now applies to both membership and
projected area. Candidate violations remain visible in advisory results but do
not claim PASS or FAIL.

Sourced-hard results require source identity and revision, valid pinned SHA-256,
verified locator, confirmed applicability, fully matched conditions, reviewer,
matching policy claim, and an exact context fingerprint. The fingerprint covers
topology kind, graph and board snapshots, all path and pad identities, typed
transition roles, declared parallel terminals, expected roles, area threshold,
and intended consumer.

Missing terminal inventory or stale authority produces `UNVERIFIED` and
suppresses violations.

## Verification

- 23 focused switching-hot-loop tests passed.
- 143 cross-authority tests passed across switching loops, oscillator zones,
  connector protection/zones, decoupling, routed-copper graphs, and shared
  semantic IR.
- Ruff passed for the switching-loop IR, evaluator, and focused tests.
- Mypy passed for both switching-loop production modules.

New coverage includes realistic same-component transitions, typed-role
membership failure, undeclared bypass detection, reviewed parallel nodes,
incomplete graph-terminal inventory, missing revision, stale membership policy,
physical transition-component tampering, advisory candidate violations, and
legacy-schema fail-closed behavior.

## Deliberate limits

- Typed transition roles and exact part/netlist snapshots do not independently
  qualify switch SOA, diode recovery, capacitor ripple rating, transformer
  construction, or driver timing.
- Projected planar area is a layout metric, not an electromagnetic field model.
- Switch-node copper union, vertical field coupling, package inductance, plane
  spreading, current sharing, thermal behavior, and lab correlation remain
  separate authorities.
- Production-board and materially different cross-board proof remain open.

## Next increment

Promote stack-up/reference continuity. First audit the existing return-adjacency,
routed-copper layer-transition, and board serialization authorities. The rule
must distinguish known reference layers and transition-via return support from
unknown stack-up; ordinary two-layer adjacency must not be generalized into a
controlled-impedance or SI signoff claim.
