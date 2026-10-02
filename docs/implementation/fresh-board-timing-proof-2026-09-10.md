# Prospective fresh-board timing proof — 2026-09-10

Status: supported final publication and formal visual inspection completed. Frozen timing is recorded below and in the trial handover.

## Trial definition

User-authorized familiar four-corner 555/CD4022 sequential LED circuit, 32 through-hole components, 80 x 65 mm, regulated 5 V input. New project fresh-cornerstep, new job c8eedd036b37475fa05b1cb2f5fb7510 under outputs/fresh-cornerstep-timing-2026-09-10. Started before inspecting/preparing trial-specific sources. Declared estimates 15–20 minutes evaluation and 10–15 minutes execution; finite independent caps 1,200 and 1,800 seconds, including 360 execution seconds reserved for verification. One initial candidate and at most two corrective cycles. No pause, new-root reset or extension.

This is a familiar-design repetition, not a novel-circuit benchmark. It reuses verified schematic intent, placement decisions, the four known label offsets and exact existing library/datasheet sources. It creates a new native schematic, netlist, project, vector plan, approvals, candidate and route. No old board/copper or positive approval result was copied as new evidence.

## Observed progress

- All 20 pinned asset entries hash-match existing local sources; no network fetch. Fresh native dependency copies remain with the project.
- Fresh native netlist matches declared per-pin intent. ERC has zero findings. Current 24-clock ideal decoding and timing/DC calculations are in predesign/design-calculations.json, not a simulation or measurement.
- New editable dimensioned floorplan.json/SVG/PNG generated, inspected and shown before native placement. Current support/power/component alternatives were reviewed and sealed by the shared predesign owner.
- One production placement, no correction. Native placement DRC/parity zero; 60 expected pre-route opens. All 96 native position/orientation anchors match the current approved vector.
- Current 14 IC review obligations executed. All 11 2D and 10 3D placement views plus 32 component crops inspected; current placement readiness/publication and routing-entry gate pass.
- New routing search completed in 35.969 seconds on its first attempt, under the finite deep profile. Actual native DRC, opens, parity, pin-net equivalence and explicit conservative bypass-loop screening pass. Exact routed candidate SHA-256 f41e25a55cf66f388102637123d90100509e1dc5c827af8393502f59c1b1c13a.
- Final exact native visual inspection and publication completed. All 32 final manifest artifacts are accepted. Total evaluation/execution/wall times are frozen in the handover.

## Limits and interpretation

Unbuilt prototype under the established proxy-model and home-fabrication scope. Actual two-sided solder/wire continuity, purchased-package fit, LED brightness, reset behavior, supply integrity, thermal behavior and EMI remain physical verification. This trial cannot close DR7's requirement for two materially different new-board proofs. Original B4 failed timing and recovery windows remain retained and are not relabeled.


## Completion update - 2026-09-10

The independent fresh-cornerstep trial completed supported final publication at outputs/fresh-cornerstep-timing-2026-09-10/production-final/generations/fresh-final-01. All 32 final visual artifacts have sealed accepted inspection decisions; enabled native DRC, opens, parity, pin-net equivalence and conservative bypass-loop screening pass. One initial placement and routing candidate, zero corrective cycles, no deadline extension. The frozen timing and exact identities are in outputs/fresh-cornerstep-timing-2026-09-10/handover.json and docs/implementation/fresh-board-timing-proof-2026-09-10.md. The 240 distinct focused tests pass; strict typing on six changed source modules and lint on ten changed source/test files pass; the workflow caller audit has 196 classified callers and no outstanding findings.

B4 distinction: its retained copper passed routing/native/engineering acceptance and its local prototype publication committed. Actual visual observations are retained separately, but its older committed visual manifest remains generated_pending_inspection with 32 uninspected artifacts. Therefore full formal B4 visual acceptance is still pending; publication alone does not establish it. Its finished ledger and immutable generation were preserved. The fresh trial has the complete formal inspection record. Original failed B4 timing remains failed. Physical qualification and DR7 remain open; later roadmap phases await review.

## Frozen timing

- scope_wall_seconds: 1826.942 seconds.
- total_wall_seconds: 1826.942 seconds.
- execution_seconds: 668.479 seconds.
- evaluation_seconds: 1158.463 seconds.

No extension or corrective cycle. Both independent caps were met. Execution includes worker setup/checking and two approximately 4.8-minute native camera render runs; the routing search itself took 35.969 seconds. Evaluation includes preparation, review and written handover, including context recovery. Final report serialization records the already-completed result.
