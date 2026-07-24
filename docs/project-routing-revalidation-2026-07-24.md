# Project routing revalidation — 2026-07-24

## Scope and rule

PCBSmith inspected every canonical `.kicad_pcb` under `outputs/`, excluding
history, render-input, intake/reference, review, evidence, and deliberately
rejected directories. It then copied every routed candidate plus available
project/rule configuration into an isolated temporary directory and reran
KiCad 10 DRC with schematic parity disabled.

This is a routing and saved-board triage, not release qualification.

- Copper-carrier presence does not prove electrical connectivity.
- Clean isolated KiCad DRC does not replace exact netlist/read-back,
  final visual review, or transactional release authority.
- No result below is called a successful released PCB.

Machine-readable evidence:

- `outputs/routing-audit-canonical-drc-2026-07-24.json`
- `outputs/routing-audit-inventory-2026-07-24.json` (includes derived,
  historical, reference, and rejected artifacts)

## Results

The canonical inventory contains 54 board files across 47 output project
directories.

| Disposition | Board files | Project directories |
| --- | ---: | ---: |
| Routed candidate, isolated KiCad DRC clean, unreleased | 38 | 35 |
| Routed candidate, isolated KiCad DRC failed | 5 | 4 |
| Placement only | 11 | 8 |

### Routed candidates with clean isolated KiCad DRC

These projects have at least one canonical board with signal tracks, copper
carriers for every detected multi-pad net, zero KiCad DRC violations, and zero
KiCad unconnected items under the copied project/rule configuration:

`buck-review-smoke`, `bunny-led-freerouting-r001`, `bunny-led-pcb-r001`,
`bunny-led-pcb-r002-simple`, `clover-r001`, `dejan-led-pcb-r001`,
`divider-led-r002`, `divider-led-r003`, `first-board`, `flyback-r001`,
`flyback-r002`, `led-art-igorc-r002`, `led-art-igorc-r003`,
`led-art-igorc-r004`, `led-art-igorc-r005`, `led-art-igorc-r006`,
`lm2596-buck-demo-20260518`, `lm2596-buck-r004`, `lm2596-buck-r005`,
`lm2596-buck-r006`, `lm2596-buck-r007`, `lm2596-buck-r008`,
`lm2596-buck-r009`, `lm2596-buck-r010`, `lm2596-buck-r011`,
`metal-detector-r001`, `mpu6050-r001`, `mpu6050-r002`, `pear-r001`,
`r8-smoke-vir-lab-5v`, `retro-pad-r002`, `servo555-tester`,
`test-r14-local-vs-codex`, `thermometer-3d-model-test-r006`, and
`thermometer-production-r005`.

They remain **unreleased** until exact route/read-back/netlist evidence and a
hash-matched accepted final review are retained. Historical projects may not
have the newer evidence package, so regenerating all of it is a separate
cost/benefit decision.

### Routed candidates that fail isolated KiCad DRC

| Project | Violation state | Interpretation |
| --- | --- | --- |
| `r8-smoke-vir-lab-12v` | 82 violations, 0 unconnected | Test fixture; remains negative evidence unless intentionally repaired. |
| `retro-pad-r001` | 104 violations, 18 unconnected | Not route-complete and not successful. R002 supersedes it. |
| `thermometer-production-r003-route-probe` | 15 violations, 0 unconnected | Historical route probe; remains negative/intermediate evidence. |
| `thermometer-production-r004` | 12–14 violations depending on retained probe board, 0 unconnected | Historical intermediate revision; R005 supersedes it. |

The superseding Retro-Pad R002 and Thermometer R005 candidates are both clean
under this audit.

### Placement-only projects

| Project | Required treatment |
| --- | --- |
| `bldc-esc-60a-r002` | Not a routed ESC; route only after its unresolved power, thermal, gate-driver, and exact-part obligations are selected. |
| `bldc-esc-60a-schematic-r001` | Historical placement-only predecessor; do not promote. |
| `protocol-analyzer-8ch-r001` | Placement rejected; routed experiment remains separately retained negative evidence. |
| `protocol-analyzer-8ch-r002` | Placement rejected and routing absent; revise placement/orientation first, then route. |
| `retro-pad-3x3-r001` | Accepted concept/placement work is not a completed PCB; requires routing and final verification. |
| `retro-pad-r003` | Accepted placement/3D work is not a completed PCB; requires routing and final verification. |
| `thermometer-production-r002` | Historical placement checkpoint; superseded by routed R005. |
| `thermometer-silk-probe` | Purpose-specific silk probe, not a routed product board. |

## Corrected project-success policy

A project can be called a routed PCB success only when the same exact board
revision satisfies all of the following:

1. `routed_candidate` saved-board evidence with nonzero segments;
2. copper-carrier coverage for every detected multi-pad net;
3. mandatory exact route checker acceptance;
4. deterministic KiCad save/read-back evidence;
5. intended-netlist equivalence;
6. zero KiCad DRC violations;
7. zero unintended KiCad unconnected items;
8. accepted final-stage visual review;
9. a committed transaction containing the exact board and review hashes;
10. the routed-board release gate allows promotion.

Placement acceptance remains useful, but its only meaning is permission to
start routing.

## Rerouting order

1. Prove the new release gate on clean Retro-Pad R002 and Thermometer R005
   without altering their copper.
2. Route Retro-Pad R003 and Retro-Pad 3x3 because their circuit families and
   routing precedent are already available.
3. Correct Protocol Analyzer R002 placement/orientation, then repair the
   invalid seeded-fanout architecture and route it.
4. Do not route the BLDC ESC merely to obtain traces. Its unresolved exact
   power-stage, protection, thermal, clamp/heatsink, current, and gate-driver
   obligations can materially change placement and copper. Routing before
   those decisions would produce another visually complete but
   non-authoritative board.

## First bounded rerouting trials

After the inventory, the shared Retro-Pad routing sequence was generalized and
given a shared standard budget of 500,000 expansions, 100 passes, and 100,000
expansions per net.

- Retro-Pad R003 stopped in the fine-pitch USB domain at
  `/USB_DP_CONN`.
- Retro-Pad 3x3 initially stopped at `/USB_DM_CONN`.
- Moving its USB ESD/immediate resistor chain to the connector side allowed
  later USB nets to be attempted, but the revised candidate still stopped at
  `/USB_DM_MCU`, then `/VBUS_RAW`, and then `/CC2` as routing domains were
  separated.

No routed candidate was emitted or promoted. The repeated failures establish
that these accepted visual placements were not proven routable. Continuing to
increase the A* budget would recreate the earlier loop failure. The next action
is a routability-informed USB escape/placement revision, followed by a new
placement review, not an unbounded retry.

## Implementation verification

- 84 focused routing-evidence, release-gate, visual-review, production-workflow,
  CLI, A*, and virtual-DRC tests passed.
- Strict mypy passed for the changed workflow/review/evidence and Retro-Pad
  routing modules.
- Ruff and `git diff --check` passed for the changed scope.
- A repository-wide pytest run reached 28% without a failure, then was
  deliberately stopped at its time checkpoint while a known slow
  routing/property region was still consuming CPU. This is incomplete
  repository-wide evidence and is not recorded as a pass.

## Post-audit recovery addendum

The placement-only table above is a time-stamped audit result, not the current
status of every project. Two entries were subsequently repaired:

| Project | Current routed candidate | Exact result | Review state |
| --- | --- | --- | --- |
| `retro-pad-3x3-r001` | 643 segments, 112 vias, 48/48 carrier nets | clean KiCad DRC; 0 unconnected | canonical final package generated; inspected front/back 2D accepted; package still incomplete |
| `retro-pad-r003` | 496 segments, 93 vias, 36/36 carrier nets | clean KiCad DRC; 0 unconnected | canonical final package generated; inspected 2D and bottom 3D accepted; top 3D camera framing requires attention |

The R003 recovery also corrected the placement cause: the back-side ISP header
was moved beside the MCU. USB-C and ISP local fanouts are deterministic, and
the route script retains exact completed-net checkpoints plus selective
net-rip-up support. This supersedes the earlier statement that both projects
remain placement-only, but it does not promote either project to manufacturing
release.
