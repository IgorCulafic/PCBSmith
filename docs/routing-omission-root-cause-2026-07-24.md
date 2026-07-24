# Routing omission root-cause audit — 2026-07-24

## Disposition

This is a confirmed systemic workflow regression, not merely a KiCad rendering
or layer-visibility problem.

Several recent deliverable boards contain no signal tracks at all. Their
review packages rendered the correct files, but those files were placement
boards with zero top-level `segment` records and zero `via` records. Pads,
zones, and ratsnest lines made some review views look electrically populated;
they did not constitute completed routing.

No affected placement-only output is routing, verification, manufacturing, or
release authority.

## Saved-board evidence

| Saved KiCad board | Segments | Vias | Zones | Actual state |
| --- | ---: | ---: | ---: | --- |
| `outputs/retro-pad-r002/retro-pad.kicad_pcb` | 457 | 78 | 2 | Routed |
| `outputs/retro-pad-r003/retro-pad-r003-placement.kicad_pcb` | 0 | 0 | 2 | Placement only |
| `outputs/retro-pad-3x3-r001/retro-pad-3x3-r001-placement.kicad_pcb` | 0 | 0 | 2 | Placement only |
| `outputs/bldc-esc-60a-r002/bldc-esc-60a-r002-thermal-placement.kicad_pcb` | 0 | 0 | 0 | Placement only |
| `outputs/protocol-analyzer-8ch-r001/protocol-analyzer-8ch-r001-placement.kicad_pcb` | 0 | 0 | 1 | Placement only |
| `outputs/protocol-analyzer-8ch-r001/rejected-routing/protocol-analyzer-8ch-r001-rejected.kicad_pcb` | 216 | 36 | 2 | Routed attempt, correctly rejected |
| `outputs/protocol-analyzer-8ch-r002/protocol-analyzer-8ch-r002-placement.kicad_pcb` | 0 | 0 | 2 | Placement only |
| `outputs/thermometer-production-r005/Thermometer_R005.kicad_pcb` | 567 | 99 | 1 | Routed |

The regression is therefore not that PCBSmith never routed a board. The
thermometer and Retro-Pad R002 prove that routed output was possible. The
regression begins where later project variants acquired specialized
placement-only generators without an equivalent routed generator or a
mandatory production-stage continuation.

## Exact failure chain

### 1. Placement and routing were intentionally separated

The intended workflow requires a saved and visually accepted placement before
routing. That is a sound design choice: placement review should be able to
reject connector orientation, component collisions, access, and board size
before routing time is spent.

The mistake was not the separation itself. The mistake was permitting the
placement checkpoint to become the last visible deliverable without an
unmistakable incomplete state.

### 2. Recent variant generators implemented only the placement half

- `retro_pad_r003_board.py` emits a layout with `segments=()` and `vias=()` and
  exposes only `generate_retro_pad_r003_placement_board`.
- `retro_pad_3x3_board.py` does the same.
- `bldc_esc_board.py` does the same.
- `protocol_analyzer_8ch_r002_board.py` does the same.
- The original `retro_pad_board.py` has both placement and real routed-board
  generation.
- The protocol-analyzer R001 module has both paths, but its routed candidate
  failed exact KiCad validation and was retained under `rejected-routing`.

Consequently, routing was not invoked for the affected recent boards. It did
not run successfully and then disappear during rendering.

### 3. Phase 17 has a pre-route gate but no complete post-route production path

`production_workflow.py` implements:

1. transactional placement persistence;
2. automatic placement review;
3. an accepted-placement routing-entry gate;
4. a library wrapper around the native router and exact checker.

It does not yet implement one end-to-end production operation that:

1. consumes the accepted placement transaction;
2. executes routing;
3. rejects incomplete routing;
4. persists the routed board transactionally;
5. reads it back;
6. runs KiCad DRC and connectivity verification;
7. generates and inspects a final-stage review package;
8. promotes only that exact routed board to the handoff.

The CLI reflects the same gap. It exposes placement review and routing-entry
gate commands, but no complete production routing/finalization command.

The workflow state-machine contract describes routing, review, verification,
and manufacturing stages, but the recent board scripts did not consume that
state machine as an operative end-to-end caller.

### 4. Placement acceptance and project completion were semantically blurred

The visual-review package permits `package_status="accepted"` at
`stage="placement"`. Within the review subsystem this means only “the required
placement views were accepted.” That state is useful and should remain
possible.

There is no sufficiently strong handoff guard preventing that phrase from
being interpreted or reported as “the PCB is accepted/completed.” The recent
work crossed that semantic boundary.

The board filenames did contain `placement`, and the manifests did record
`stage="placement"`, but those machine-readable warnings were not enforced at
the user-facing result boundary.

### 5. The standard visual package made the omission too easy to miss

The renderer always generates profiles called:

- `front-copper`;
- `back-copper`;
- `combined-copper`;
- `holes-vias`.

It does this for placement and final stages alike. `_profile_required()` does
not use the review stage and does not check whether routable signal nets have
actual track coverage.

On an unrouted board these images can still contain:

- component pads;
- filled zones;
- board outlines;
- plated holes;
- ratsnest context in interactive KiCad views.

The artifact names therefore imply routing evidence even when no routing
exists. The manifest records copper hashes but not visible segment count, via
count, routed-net coverage, or unconnected-item count.

Three-dimensional renders are also poor routing evidence because solder mask
normally hides copper. They should never be used to establish route
completion.

### 6. Existing tests prove components, not the complete deliverable

The repository has extensive tests for:

- A* and negotiated routing behavior;
- exact route acceptance;
- placement persistence and visual review;
- routing-entry preconditions;
- workflow identity transitions;
- selected live KiCad read-back/DRC fixtures.

Those tests do not yet prove that a user request to “build the PCB” cannot
terminate with a placement-only board. The missing test is an end-to-end
production-stage invariant across a real board variant.

This explains the apparently contradictory state: thousands of checks can
pass while the delivered board still has zero traces. The tested pieces were
not wired into the final caller.

### 7. The failed R001 routing attempt encouraged an unsafe fallback

The protocol-analyzer R001 route attempt produced 216 segments and 36 vias but
failed KiCad validation with 297 reported violations and 96 unconnected pads.
It was correctly rejected.

The immediate technical cause was invalid manually seeded/frozen fanout copper
being accepted before the same exact clearance checks applied to generated
routes. General routing then inherited bad geometry.

R002 corrected placement issues but stopped at placement rather than repairing
and exercising the routing/finalization path. Preserving R001 as rejected
evidence was correct; allowing a later placement-only result to look like
forward completion was not.

## Responsibility assessment

The user's observation is correct. This is not primarily a subtle KiCad issue
and not just a missing review image.

The system and the assistant should have made route state explicit at every
handoff. The assistant concentrated on placement, schematic readability, 3D
models, visual evidence, thermal semantics, and roadmap infrastructure, then
used success language without verifying actual copper presence. That is a
process and reporting failure.

The user missing it initially is understandable because the evidence package
did not clearly distinguish pads/zones/ratsnest from completed signal routing.
The safeguard belongs in the workflow, not in the user's vigilance.

## Required corrective design

### P0 — fail-closed artifact states

Introduce distinct deliverable classes:

- `placement_candidate`;
- `routed_candidate`;
- `verified_release_candidate`;
- `manufacturing_release`.

A placement review may be accepted, but it must remain visibly incomplete and
must never satisfy a request for a finished PCB.

### P0 — routed-board completion gate

Before any board is described as routed or complete, bind the same saved-board
hash to all of the following:

1. final/routed stage identity;
2. nonzero required signal-track evidence;
3. explicit routed-net coverage;
4. zero disallowed unrouted connections;
5. zero KiCad DRC violations;
6. zero KiCad unconnected items, except an explicit reviewed exemption model
   where electrically legitimate;
7. exact netlist/read-back equivalence;
8. accepted final visual review;
9. committed transactional output;
10. no `placement` artifact substituted as the handoff board.

Raw `segment_count > 0` is only a tripwire, not sufficient proof. A board could
contain one trace and still be almost entirely unrouted. Net-level coverage and
KiCad connectivity authority are mandatory.

### P0 — review-package truthfulness

For every visual package:

- record segment count, via count, routable-net count, routed-net count,
  routing coverage, DRC count, and unconnected count;
- watermark placement routing views as `UNROUTED PLACEMENT` when applicable;
- label routing artifacts `not_applicable` or `incomplete`, rather than normal
  generated evidence, if a routable board has no signal tracks;
- add segment-only front/back views with zones hidden;
- add zones-off copper views so tracks cannot be confused with planes;
- make routing completeness a required final-stage artifact;
- refuse a final-stage package when the saved board is placement-only.

### P0 — production caller closure

Implement and test one operative transaction:

`accepted placement -> route -> exact check -> save -> read back -> KiCad DRC
and connectivity -> final review -> verified promotion`

Any routing failure must fail closed and retain the candidate under a rejected
or incomplete path. It must not fall back to the placement board as a successful
result.

### P0 — variant capability regression guard

A variant derived from a routed design must either:

- reuse/implement a compatible routing path; or
- explicitly declare itself placement-only and remain in an incomplete state.

Add a conformance check that detects a predecessor capability regression such
as `routed -> placement-only`.

### P0 — handoff assertions

Every PCB handoff must state, from machine evidence:

- artifact state;
- exact board filename and SHA-256;
- segment and via counts;
- routed-net coverage;
- KiCad DRC violation count;
- KiCad unconnected-item count;
- final-review state.

The handoff must be rejected if the requested result is a routed PCB but the
canonical board filename or manifest stage is placement-only.

## Recovery order

1. Preserve and relabel current outputs; do not delete negative evidence.
2. Implement the artifact-state, finalization, review, and handoff gates before
   attempting another board.
3. Prove the gates reject the existing placement-only boards.
4. Prove the complete path on known routed fixtures such as Retro-Pad R002 and
   Thermometer R005 without changing their copper.
5. Route one currently placement-only design transactionally and require zero
   DRC violations and zero unintended unconnected items.
6. Only then resume the protocol-analyzer board.

## Immediate project status

- Retro-Pad R002 and Thermometer R005 retain routed evidence.
- Protocol Analyzer R001 routing remains rejected negative evidence.
- Retro-Pad R003, Retro-Pad 3x3 R001, BLDC ESC R002, Protocol Analyzer R001
  placement, and Protocol Analyzer R002 are placement-only.
- Protocol Analyzer R002 work remains paused while this workflow defect is
  addressed.
- Phase 17 is not complete. Its roadmap already says cross-board default-path
  proof remains open; this incident demonstrates that the missing proof is a
  real production blocker, not administrative cleanup.

## Corrective implementation outcome

The corrective work now proves that the omission can be detected and that two
previously placement-only Retro-Pad variants can be recovered without weakening
the completion gate.

- Saved-board evidence classifies placement-only, partially routed, and routed
  candidates from objective copper carriers.
- Final review and routed persistence refuse placement-only input.
- The routed transaction binds the exact board, exact DRC report, routing
  evidence, and final review before an atomic commit.
- Internal Edge.Cuts cutouts are router obstacles.
- Completed-net checkpoint sidecars permit exact resume and selective net
  rip-up instead of restarting every successful domain.
- Trace-width selection no longer silently forces whole long nets onto the
  fine grid.

The routing failures were not one bug. They were an interaction of ignored
cutouts, fine-grid overuse, alphabetical/repeated net ordering, duplicated GND
routing, interleaved USB-C fanout, MCU-pad escape topology, and placement that
put the ISP header across the board from the MCU. The stable R003 sequence is:

`USB-C local fanout -> protected USB -> clock -> ground -> matrix -> VCC ->
encoder -> LED chain -> reset -> ISP -> key diodes`

R003 additionally seeds and later prunes three temporary ISP-pad corridor
reservations. Moving the ISP header beside the MCU removed three unnecessary
cross-board routes and preserved the approved user-facing layout.

Exact retained results:

| Project | Board SHA-256 | Segments | Vias | Carrier coverage | KiCad DRC |
| --- | --- | ---: | ---: | ---: | --- |
| Retro-Pad 3x3 R001 | `176403c5e3663d11b1ff1a2a81489bb2277db35628e3f0d1d898b999a6e48f08` | 643 | 112 | 48/48 | 0 violations, 0 unconnected |
| Retro-Pad R003 | `f9c3fadede4fb976dc0bb10d0aa90d1d4a346b12365cf581a963b8ff49ae6b81` | 496 | 93 | 36/36 | 0 violations, 0 unconnected |

These are routed, exact-DRC-clean candidates. They are not manufacturing
releases: typed read-back/netlist evidence still needs to replace remaining
release booleans, generator migration remains incomplete, and the complete
required visual packages are not yet accepted. R003's top 3D orthographic image
is vertically misframed and is retained as an attention-required finding.
