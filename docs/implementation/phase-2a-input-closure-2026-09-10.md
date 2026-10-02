# Phase 2A - current native input closure - 2026-09-10

Status: implemented; focused software and native-export controls passed. Full module type checking remains open with existing typing debt (detailed below). Phase 2 is not complete: package/procurement closure and supported circuit-pattern work remain in [the revised plan](../phase-2-3-revision-2026-09-10.md).

## Confirmed problem and impact

Previously, native_project.prepare_native_project compared only named-net terminal lists and recorded the schematic hash. predesign_preparation._prepare_predesign_inputs checked that stored positive status and schematic hash, then independently parsed a cached XML netlist. The XML and current declarative specification were not bound to that report; component reference/value/footprint/MPN equivalence was not replayed there. A stale or modified XML could therefore influence pre-placement feasibility and derived inputs before a later gate rejected it. This is a high-priority input-integrity gap, not evidence that an accepted board was electrically wrong.

## Implemented change

- native_project.inspect_native_input_closure compares exact native component coverage, value, footprint and MPN text, all connected terminals and intentional NC semantics. Duplicate references, fields, nets and terminals are rejected; unknown references that the board-oriented parser would otherwise filter are explicitly checked.
- New preparation reports bind SHA-256 of the native schematic bytes, exported XML bytes and validated specification serialization. The specification hash is canonical model serialization, not the whitespace formatting of design-spec.json. Reports retain failed findings and still state production_accepted=false.
- native_project.require_native_input_closure checks those bindings and replays semantic equivalence. A manually relabeled passed status cannot override a mismatch. Both the native producer and predesign consumer use the same check.
- Predesign invokes this check before creating its output directory. Existing worker authorization, project-local library checks and later engineering/native/release gates remain in place.

## Compatibility and migration

Old committed reports, boards, job clocks and approvals were not rewritten. The new check applies when preparing new predesign inputs. Legacy reports lacking bindings stop explicitly; refresh preparation through an authorized supported native operation rather than editing hashes into an old report or regenerating a completed PCB. Failed/finished jobs retain their existing stop and continuation rules. This change provides no new authority to reset them. Source equality is not an authenticated reviewer signature or an OS sandbox.

## Verification

- 91 distinct focused tests passed, including 18 new closure cases and adjacent readiness, project-library and job-boundary tests. Initial and final runs are retained. Tests cover changed schematic/XML/specification, wrong values/footprints/MPNs, connected and NC pins, unknown/duplicate references or nets, relabeled positive reports, legacy rejection and consumer rejection before output creation.
- A real fresh KiCad XML export on an isolated copy of the retained fresh-cornerstep schematic passed current closure: 32 components and 27 nets. Every original source file hash was verified unchanged. The native export control is not a fresh board, routing proof or physical test.
- Final lint passed for both changed source modules and the new test file. Caller audit passed for 196 classified callers with no changed, stale or unclassified calls.
- Full mypy did not pass. New local variable type collisions were corrected. A shadow-file comparison reconstructing only the exact pre-change sections reports 38 previous diagnostics versus 37 current diagnostics, with no new normalized error messages. Logs and the reconstructed sections are retained. This is evidence of no added diagnostics, not a clean type gate. Remaining annotations and older adapter call typing need a separately scoped cleanup with runtime regression checks.
- Evidence: outputs/phase-2a-input-closure-2026-09-10/verification-summary.json, final-tests.xml, closure-final-tests.xml, native-export-verification.json, caller-audit.json, current-types.log, baseline-types.log and type-comparison.json. Initial lint failures were formatting/unused imports; corrected before final lint.

## Limits and next work

MPN string equality is not manufacturer pin-map verification. No dimensional/procurement/model qualification, new circuit pattern, hardware measurement, changed board geometry or general phase completion is claimed. The next implementation slice is 2B: reconcile existing package, nested-dependency and model evidence owners into early closure, first verifying which gaps still reproduce. B4's separate metadata hold, physical qualification and DR7 remain open.
