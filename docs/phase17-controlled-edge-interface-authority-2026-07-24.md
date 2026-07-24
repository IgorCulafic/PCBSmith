# Phase 17 controlled edge-interface authority

Date: 2026-07-24
Status: implemented bounded first slice; production-candidate and MCAD
integration remain open

## Problem

PCBSmith's normal component-to-outline clearance is correct for ordinary
components. Connectors, jacks, side buttons, sockets, and similar user-facing
parts are different: their mating or actuation portion often must reach or
protrude beyond the board outline. The previous
`PlacementEdgeException` could waive the whole body-containment rule for one
reference, but it did not prove:

- which outline edge was intended;
- whether the pads and mechanically retained body stayed on board;
- whether the exposed portion projected far enough to be usable;
- whether the projection was bounded;
- whether another edge or corner was crossed; or
- whether the exception still described the current layout.

That coarse exception could therefore hide a backwards/recessed connector,
inaccessible side button, pad overhang, excessive body protrusion, or stale
placement.

## Implemented contract

`edge_interface_ir.py` introduces a source- and replay-bound declaration for
five explicit interface classes: connector, jack, actuated switch, socket, and
user control. A declaration divides footprint-local polygonal geometry into:

1. retained support regions;
2. pad/copper regions; and
3. one user-facing overhang region.

The evaluator in `kicad/edge_interface.py` proves, for the exact canonical
`BoardLayout`:

- retained support is inside board material and respects its declared edge
  clearance;
- every declared pad is inside board material and respects its independent
  edge clearance;
- the overhang touches the selected real outline segment;
- it touches no other outline segment;
- it boundary-touches but does not overlap board material; and
- its farthest exact polygon boundary point lies between the declared minimum
  useful and maximum allowed projection.

Arbitrary-angle transforms remain bounded approximations and cannot grant the
exception. Orthogonal front/back transforms use the existing rational exact
geometry authority.

The result retains the exact layout snapshot/fingerprint, component reference,
footprint ID, UUID path, source-file SHA-256, source binding, local-geometry
fingerprint, transformed geometry, findings, evidence fingerprint, and a
replay-validated result fingerprint.

## Legalization integration

`PlacementEdgeException` is now schema version 2. A body or courtyard
containment waiver requires an approved `EdgeInterfaceAuthorityResult` whose
reference and exception rule match. R5 legalization compares the authority's
canonical board-snapshot fingerprint with the current probe layout before
applying it.

Consequently:

- the ordinary edge-clearance rule remains unchanged for every undeclared
  component;
- a caller cannot request a raw whole-body containment waiver;
- a passed authority may waive body and, explicitly, courtyard containment for
  its one component;
- moving the component or otherwise changing the layout invalidates the grant;
  and
- an invalid/stale authority adds an
  `EDGE_INTERFACE_AUTHORITY` legalization violation and leaves normal edge
  containment active.

## Verification

Focused fixtures cover:

- exact selected-left-edge USB-style overhang;
- successful conversion to a placement exception;
- too-large and too-small projections;
- body intrusion into board material;
- wrong-edge selection;
- pad overhang;
- non-orthogonal unverified transforms;
- stale geometry and result tampering;
- rejection of a raw waiver without authority; and
- same-layout acceptance versus moved-layout rejection in R5 legalization.

## Deliberate limitations

This is a 2D placement authority, not a claim of connector usability or
mechanical adequacy. It does not yet prove:

- supplier-CAD-derived responsibility-region completeness;
- connector orientation or pin/net correctness;
- mating connector insertion/extraction sweep;
- finger, tool, knob, cable, or bend-radius clearance;
- panel opening and enclosure-wall geometry;
- retention force, strain relief, clamp load, or solder-joint stress;
- z-height, top/bottom access, collision, or heatsink interaction; or
- fabrication/assembly house edge-clearance exceptions.

Those obligations remain separate. The next production step is to derive or
review the three responsibility regions from pinned supplier mechanical
evidence, make the placement generator use the authority while proposing edge
anchors, and add standard edge-interface visual crops. Full 3D mating and
enclosure proof belongs to Phase 19.
