# Phase 2B: source-bound same-footprint substitution

Status: shared software implementation and synthetic transaction gates complete on 2026-09-11. A sourced real-part substitution through live native checks remains open. No accepted board, committed generation, existing job ledger or paper changed.

## Scope and implementation

The initial operation replaces a populated front-side part's MPN/value while preserving its footprint, pin numbering/functions, placement, pads, copper, models and object identities. It supports the existing centered round-hole THT geometry screen. It rejects remapping, package/footprint changes, back-side geometry, locked components, mixed edit/substitution requests and multi-sheet schematics. These are explicit scope limits, not rebuild instructions.

`kicad/part_substitution.py` adds a typed PartSubstitution. It requires the expected old MPN, replacement value, existing ComponentPinEvidence and PackageGeometryEvidence schemas, a hashed electrical-review document, reviewer/rationale and an explicit assertion of suitability for the current circuit. The board request binds all this to the exact predecessor. Hashes and assertions establish traceability, not the physical truth of a datasheet interpretation.

Planning checks both old and new source documents, exact MPN consistency, complete pin coverage and equal declared pin names/roles/functions. It checks the actual embedded footprint, including pin nets, body/courtyard and hole clearance, using the existing parser and geometry evaluator. It requires source/current model policy to pass; unchanged proxy models may be reused, while an exact-model substitution requires a future qualified model operation. Model presence alone never qualifies the replacement.

`board_revision.py` extends the existing inspect/edit/replay/apply flow. There is no new board producer or custom orchestration script. The ordinary native edit matrix is unchanged. Requests may contain a separate substitutions list; empty requests and mixed native/substitution deltas are rejected. Legacy requests without substitutions retain their previous semantic fingerprints.

Inspection retains additional confined project-local specification, pin/geometry/model-policy and review source files. The source closure must cover every dependency before a candidate is created. The same context survives interruption and replay. The candidate's PCB, schematic, specification and current pin/geometry maps are changed together with the existing recoverable file transaction. Unaffected source records and files remain preserved.

The native-check stage exports a fresh netlist from the changed schematic, runs the shared intent comparison and writes its computed closure report; it never edits an XML netlist into a positive result. Existing ERC/DRC/parity/opens checks still gate the candidate. Replay reconstructs the exact requested file deltas and checks the retained current closure, hashes, checkpoint and native-check evidence. Apply checks again, detects concurrent changes, and commits all changed source/derived files plus the existing working-edit journal as one recoverable transaction. This is working CAD application, not production publication.

`board_revision_workflow.py` includes the substitution record in diagnosis and qualification obligations. Old component/visual/engineering/manufacturing evidence remains invalidated. Physical qualification stays unverified. No router or PCB generator is invoked by this operation; native netlist export is an explicit verification step.

## Using the supported boundary

Keep source files inside the native project with confined relative paths. A substitution currently requires design-spec.json, netlist-vs-intent.json, the current native XML export, component-pin-evidence.json, component-package-geometry.json and component-model-selection.json. Pin/geometry maps must contain the original target part. Retain the new datasheet and circuit-specific electrical review before inspection. Absolute or escaping evidence paths are rejected by this portable transaction scope; copy licensed evidence locally and update its explicit path/hash first.

1. Create a JSON list of typed substitutions. The schema is retained in outputs/phase-2b-substitution-2026-09-11/part-substitution.schema.json.
2. Use `production-inspect-board BOARD --substitutions replacements.json --output inspection.json` to obtain the full source_inputs map. The read-only inspection does not grant runtime or part approval.
3. Create the normal BoardRevisionRequest with those source_inputs, rationale and substitutions. Leave edits empty. Run `production-edit-board` through the same live board-job owner and use `production-apply-board-edit` only after the candidate checks pass, under the same supported job.
4. Refresh affected engineering/visual/publication evidence before any release. Unchanged placement does not require regenerating an approved vector; reuse must still be exact and truthful.

No request, new directory, resumed chat or substitution grants an additional correction allowance. Required board-job controls remain in force. This implementation work did not start a real board job or claim a timing proof.

## Verification and failures encountered

226 integrated tests passed with zero failures/skips in 41.844 seconds. These include 26 new substitution controls plus existing revision, rebuild, native closure, model selection, readiness/publication, worker, caller audit and recoverable file-transaction tests.

New controls exercise complete multi-file replay/application, unchanged copper and predecessor preservation, pin/function/pitch/body/lead/source/metadata rejection, stale candidate files, missing qualification context, path confinement, live worker enforcement, failed native checks, same-transaction resume and rollback after a simulated mid-apply failure. The XML exporter and ERC/DRC are explicitly synthetic in these unit controls; they do not establish a real KiCad or physical qualification pass.

Lint passed for the six changed Python source/test files. Strict mypy passed for part_substitution.py, board_revision.py and board_revision_workflow.py. The caller audit passed for 196 entries after reviewing the added context-file write in the existing native primitive and updating that one policy entry. The new planner is read-only; its closure refresher consumes the existing guarded native exporter and does not produce a PCB. The CLI help exposes the new inspection option.

Initial verification caught a legacy fingerprint expectation needing the optional field excluded, test outputs incorrectly located inside the synthetic source project, and a test expecting ValueError instead of the shared FileTransactionError for path escape. These fixture expectations were corrected without relaxing the transaction guards. Typing/formatting issues were fixed before the final run.

Evidence is retained under outputs/phase-2b-substitution-2026-09-11: integrated-tests.xml, caller-audit.json, verification-summary.json, part-substitution.schema.json and real-part-source-review.json.

## Real-part source review and remaining gate

The retained TI TLC555 datasheet was reviewed for TLC555CP to TLC555IP as a possible isolated control, including pin/operating tables and the P-package drawing. Pages 3 and 29 identify the same 8-pin P package; page 4 gives different minimum supply voltages (2 V C, 3 V I), both compatible with the proposed retained 5 V operating point. Page 8 has a higher full-range maximum supply current for I (600 microamps versus 500 microamps C). A substitution must review such differences rather than treat matching pins as complete electrical equivalence. No broader temperature or timing accuracy qualification is inferred.

The page 41 package drawing gives maximum lead width but nominal thickness only. The current geometry schema requires a justified maximum circumscribed lead diameter; nominal thickness cannot establish that maximum. Lead forming and purchased-part/hole fit remain separate physical matters. Consequently no purportedly qualified real-part candidate was created from guessed dimensions, and no live native substitution pass is claimed.

To close this example, obtain a manufacturer-qualified maximum lead envelope/forming condition or inspect and qualify the intended purchased parts and fabrication process. Alternatively select another same-footprint part pair whose exact sources provide the needed bounds. Then run one isolated substitution through the supported live boundary, retain native checks and verify unaffected geometry/source identities. This is the remaining real-part proof; it does not justify revising accepted board geometry now.

Phase 2B remains open for that proof and exact procurement evidence. Phase 2C is not declared started. Physical fit/operation, B4 historical inspection metadata and DR7 remain separate holds.

## Completion update — new real board

[DividerLeaf real native proof](phase-2b-new-board-proof-2026-09-11.md) now completes the software/native substitution scope with source-complete Vishay PR01 resistors, exact copper/object preservation, live native checks, atomic apply, reopen and stale-readiness rejection. The TLC555-specific bound and physical procurement holds remain open. The revised working prototype is not a production release. Earlier open-proof statements above record the state before this trial.
