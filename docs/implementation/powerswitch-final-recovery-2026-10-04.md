# PowerSwitch final automatic recovery — October 4, 2026

Subsequent update: the user-authorized [routing constraint and paste-pad software fixes](power-routing-constraints-fix-2026-10-04.md) are implemented and tested. No additional PowerSwitch route or release was performed; the rejected candidate and the history below remain unchanged.

PowerTrace remains delivered and unchanged. PowerSwitch is **not build-ready**. The explicitly authorized J3 move and final automatic attempt are complete; the result fails an engineering routing requirement independently of its software validation defect. No manufacturing package or final handover is claimed for PowerSwitch.

## Applied scope and actual result

The user's “do it” authorized the previously proposed bounded shared-controller recovery. The same root and original job identity were retained: `outputs/power-laser-tests-2026-10-04/02-powerswitch-12v`, job `88afbce7430d4f2ab6a395d3c6efb9e0`. The new window declared 3600 seconds evaluation plus 1800 seconds execution, with a 360-second verification reserve. Historical failures, expired diagnosis and predecessor windows remain intact.

Only J3 moved from board-local (60,20) to (56,20) mm; 90-degree rotation, electrical specification and all other native poses were preserved. The shared edit owner produced `placement-j3`; current native placement checks passed with the expected 11 unrouted connections. The refreshed editable vector and overlays were actually viewed before placement. All 37 source-bound placement artifacts were inspected, including MOSFET gate/source orientation, drain-tab contact, resistor seating and references. Eleven SVGs were independently rendered and compared with their PNG counterparts. The immutable inspected placement successor is `transactions-j3/generations/placement-j3-reviewed`.

The current native inputs, component/model readiness, mandatory review, source context, actual pose comparison and engineering applicability gate were checked through their shared owners. Earlier source documents were retained byte-for-byte for unchanged electrical observations; approvals were not blindly rebound to new files.

Pinned Freerouting 2.3.0 completed the second and final route in 3.594 seconds, producing 25 segments and two vias across all five nets. Native candidate checks report zero clearance violations, zero unconnected items and zero schematic parity findings. The routing transaction nevertheless correctly remains rejected because its pin-net-equivalence result failed. A separate actual-geometry inspection found the more significant power-path violation below.

| Artifact | SHA-256 |
| --- | --- |
| Reviewed moved placement | `219333cc50c0ed43db2c0b8599a4914021e56c8805ddd0b6c246e66b22f2094e` |
| Rejected routed candidate | `42fa069668abca429be029f2ef841a9b5a938d349f161a7240ac2f9150580a18` |
| Native DRC report | `876ed684ebc54e710a0ad517b3a7ba1beda2582e0ce9cf014f1b4500ed2afa8d` |
| Pin-net-equivalence report | `5c7f37fbf25f2e9c78e13beec85fad8309fbb6d22b64eeedc5e4f25759a38b67` |
| Independent native geometry observations | `da9bed8379f1cffde25045d2ba98c5facddcf9a414b7a763bdf5fe9545cd30e9` |

## Completed diagnosis and next prerequisite

The diagnostic started before wider analysis and completed in 153.578 seconds, within its five-minute limit. Its recommendation and exact evidence hashes are retained in `recovery-j3/final-diagnostic-assessment.json` and the shared-owner receipt `recovery-j3/final-diagnostic-complete.json`.

1. **Power routing constraints are not enforced by the current bridge.** The reviewed requirement specifies 5 mm F.Cu paths for J1–J3, J4–Q1 drain and Q1 source–J2 without relying on vias for load current. The actual P12 path uses rear copper and two 0.8 mm drilled / 1.8 mm diameter vias, at board-local (16.490,20) and (56,15.745) mm. Width-only routing options did not encode the front-only/no-via requirement. Native DRC cannot establish unmeasured plating ampacity or compliance with this additional engineering requirement.
2. **Pin-net comparison includes non-electrical apertures.** Four Q1 unnumbered, undrilled, paste-only apertures have an inherited DRAIN net but no copper. The comparison includes a spurious blank-number Q1 pin; the 16 actual electrical pad bindings match the intended netlist. This is a shared reader defect, not evidence that the candidate can be released: fixing it alone would leave the power-path violation.

Recommended separate platform scope: export enforceable per-net layer/via constraints to pinned Freerouting and reject returned copper that violates them; filter only proven non-electrical paste-only apertures from pin-net equivalence. Tests must retain numbered, copper and drilled-pad checks and prove that a DRC-clean candidate with forbidden power vias is rejected. Neither change was implemented inside this board recovery. Future board work requires a separately declared scope; no third routing attempt, manual copper, new root, timing reset or relaxed power requirement was used.

Unknown copper thickness, via plating, purchased-part fit, thermal performance, voltage drop and switching waveforms remain physical holds. No 3–5 A rating is claimed. PowerTrace's measurement guide and delivered laser/pad/drill files remain available.

## Shared recovery implementation and checks

`src/pcbsmith/board_job.py` now supports a one-time, explicitly authorized `automatic_retry_plan`: exact source hashes, one component pose within 5 mm, unchanged electrical specification, matching native object/delta, one failed prior route and the global two-route limit. It records the predecessor, preserves all counters and allows a fixed preparation/review/edit/routing/export inventory. It cannot renew itself. Prior completion inventories are counted within their own retained window rather than against later explicitly authorized work.

One placement-inspection invocation failed at argument parsing because three required arguments were omitted. Its failure remains in history. The narrowly scoped `resolve_inspection_argument_preflight` owner verifies the exact pre-output argparse error, unchanged decisions/current transaction and the exact corrected command. It grants no time, CAD change or routing attempt; the corrected genuine inspection passed. A later cancellation request was refused because the job was already terminal, leaving that stopped state unchanged.

Final verification: **243 focused tests passed** across board-job, automatic recovery, final rendering, placement follow-up and routing policy. Targeted Ruff and mypy passed. The workflow entrypoint audit passed with **213 classified entries** and no unclassified, stale or changed-call findings. These are software checks, not board release or physical qualification.

Through completed diagnosis: recovery wall 1553.505 seconds (25m53.505s), comprising 1236.859 seconds evaluation and 316.646 seconds supervised execution. Lifetime root wall at that checkpoint was 12427.396 seconds (3h27m7.396s). This does not pass or rewrite the original budget. Documentation and final regression follow-up occur after the stopped board checkpoint.

Receipts: `.tmp/powerswitch-recovery-final-tests.txt`, `.tmp/powerswitch-recovery-final-workflow-audit.json`, and the root's `recovery-j3/` records. No commit, push, unrelated cleanup or changes to the accepted PowerTrace files were performed.
