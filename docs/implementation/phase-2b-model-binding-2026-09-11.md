# Phase 2B selected-model binding and workflow integration

Completed 2026-09-11; work and evidence directory started 2026-09-10.

Status: the early selected-model binding and positive software integration gates are complete. Phase 2B remains active for qualified substitution and exact part/procurement evidence. This report grants no physical, fabrication, visual or DR7 acceptance.

## Changes and reasons

- `kicad/model_preflight.py` now exposes one shared inventory evaluator. Both selected footprint model clauses and saved-board preflight use the same path, hash, classification and transform checks. The existing saved-board report schema and board identity remain intact; an early inventory cannot substitute for it.
- `kicad/component_readiness.py` accepts `component-model-selection.json` beside the native specification. Applicable policy requires the exact component-reference set, accepted classifications, model hashes and expected transforms. Registry local paths are explicitly native-project-relative or absolute. An explicit not-applicable policy requires a rationale and contains no required models. Unknown selection remains visible during inventory, but cannot seal a new preparation.
- Every selected model must resolve and meet its declared transform. The report records the policy, computed assessment and model source hashes alongside footprint/native inputs. Changed inputs block the approval replay. Registered proxies retain proxy status; no exact-package requirements were imposed on the retained prototype scope.
- `production_readiness.py` checks the bound selection at the predesign boundary and replays it on the actual saved board at publication. Model references, footprint identifiers, raw paths, hashes, classifications and multiplicity must match the early selection; transforms must satisfy the original tolerances. The submitted final model report must match the replay. Dropping a requirement, altering a transform, removing/adding a model or changing a file cannot silently weaken the new binding.
- `predesign_preparation.py` no longer constructs a multi-terminal routing demand for a one-terminal net. Native pin/net input closure remains unchanged. A project containing no multi-terminal net is explicitly unsupported by the current routing-feasibility contract and stops before creating output. The integration fixture exposed this previously untested case.
- `kicad/library.py` no longer loads a known lazy footprint merely to answer membership. A listed but unavailable asset remains listed, and actual retrieval reports its asset error. Unknown dynamically resolvable keys still use the existing lookup. The existing lazy-library regression reproduced this defect during the broader gate.

## Verification

210 integrated tests passed, with zero skips or failures, including 18 new selection/integration controls. One additional public-boundary regression then verified that the publication entry point itself rejects a weakened report; all 19 selection tests passed together after that addition. Checks cover early hash/classification/transform/coverage failures, undeclared policy, explicit not-applicable scope, saved-board weakening attempts, successful complete preparation/approval/publication/retained replay and the no-routing-demand blocker. The wider set includes native input closure, library retention/geometry/cache, supported worker guards and visual/readiness consumers.

The complete workflow control uses real preparation, approval and publication adapters with explicitly synthetic native input, model bytes, review assertion and render fixture; the worker guard is mocked only inside the test. It proves software integration, not a real KiCad/native or human-reviewed production board. No board-specific production script or new producer was introduced.

Read-only replay of the isolated actual 32-component native project passed early policy checks and all 32 saved-board models using retained official KiCad assets and the existing prototype proxy policy. The original accepted board SHA-256 remains `f41e25a55cf66f388102637123d90100509e1dc5c827af8393502f59c1b1c13a`. Only the isolated control acquired a policy file; no accepted board, closed job or published generation was changed.

Lint passed for all six changed source/test files. Strict mypy passed for the three readiness/model modules. Existing native/preparation typing debt is not declared resolved. The caller audit passed: 196 classified callers, no changed/unclassified/stale entries. Final test runtime was approximately 23.5 seconds; this is test-run time, not board creation time.

Evidence: `outputs/phase-2b-model-binding-2026-09-10/` contains integrated-tests.xml, selection-tests.xml, verification-summary.json, caller-audit.json, selected-model-policy.schema.json, component-readiness.json, saved-model-replay.json and real-project-verification.json. The broader run's pre-fix lazy-library failure is retained separately. Initial test construction errors (a hash field name and an unsupported assertion role) were corrected; no production checks were weakened to pass them.

## Use and migration

Provide component-model-selection.json before supported predesign preparation. Its fields are applicability, rationale, registry and requirements; registry/requirements reuse the existing model schemas. Supply sourced classifications and expected transforms, never guessed approvals. A source-bound policy records the declared engineering scope; it does not establish that an exact-package claim is physically true.

New prepared drafts must include and replay this policy before approval. Old inventory-only drafts require supported preparation refresh. Previously committed bundles without the component inventory keep their original limited acceptance and are not retrospectively migrated. This compatibility does not make legacy evidence a new-path timing or qualification proof. Finished board jobs stay finished.

## Remaining Phase 2B work

Update: [the substitution implementation record](phase-2b-substitution-2026-09-11.md) supersedes the unsupported-software status below. Software and synthetic transaction controls are complete; a sourced real-part native proof remains open.

Qualified substitution remains unsupported by the native edit matrix. Inspection confirmed that its replay/commit expects only the PCB file to change; a real part substitution also needs atomic schematic/specification and evidence changes. Add this to the shared edit transaction, with exact source and replacement qualification, invalidated checks, conflict handling and stable preservation of unaffected objects. Do not implement it as a board-only footprint swap or another orchestration script. Begin with a narrowly specified pin-compatible package family, then verify both positive and rejected replacements.

Exact procurement geometry, pin functions and purchased-part fit remain subject to sourced review and measurements. The retained real project has not acquired new geometry qualification merely from these model checks. New real-board end-to-end proofs, B4 historical inspection metadata and DR7 remain separate open work.
