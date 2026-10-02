# Early readiness preparation and B4 correction — 2026-09-08

Status: shared read-only preflight implemented; B4 source reuse verified and review inputs prepared. Component decisions, visual publication and routing remain open. This was a separate 20-minute preparation/platform scope, not a board-job extension. Exact elapsed time including handover is in outputs/readiness-preflight-2026-09-08/verification.json.

## Correction to the previous diagnostic

The preceding B4 trial searched its immediate inputs and tracked registry filenames. It missed the ignored outputs/cornerstep-r001-2026-09-06/placement-03/model-registry.json and model-requirements.json. That prior workflow explicitly accepted generic visualization proxies for this prototype. The B4 trial instead declared exact_package for every reference. That was an unnecessarily strict assistant-selected requirement, not a demonstrated requirement of the user's brief.

The prior preflight failed truthfully under its supplied inputs, but its result did not establish that reusable registry evidence was unavailable or that exact-package qualification was required before this prototype's visual review. Those files and failed findings remain retained as historical evidence. This correction supersedes the broader blocker interpretation; it does not erase the old record or relax a required physical qualification.

## Verified reuse

The old and current canonical netlists differ only in the 32 schematic uuid_path fields. All component values, footprints, part fields and every net match. The current saved board's connected pad nets and component value/footprint/available MPN fields were compared with its native XML. These comparisons do not replace ERC/DRC or schematic-source parity.

The existing model registry was replayed against the current board. All 32 referenced model files match the registered hashes and transforms and pass their existing proxy requirements. No download, new model classification, geometry edit or manufacturing-package assertion was made. Proxy classification and physical fit limitations remain explicit.

Both IC pin-evidence records match their retained source PDF hashes and declared part numbers: U1 TLC555CP and U2 CD4022BE. The source PDFs remain in the earlier engineering folder. The revised circuit-analysis document and all fourteen prior rationales were inspected as historical evidence; no earlier review result was inserted into the fresh request.

## Shared implementation

src/pcbsmith/readiness_preflight.py adds a reusable read-only preparation command over the existing native-project, netlist, model-preflight and pin-evidence owners. It validates current connectivity/component identity, compares historical electrical intent with only schematic UUIDs excluded, rejects ambiguous model registries and incomplete reference requirements, validates pinned datasheets, and checks that inputs did not change during preparation.

Outputs are report.json, model-preflight.json and component-review-input.json. The draft binds the current board hash and netlist and always has an empty results_by_obligation mapping. The report is review_required with production_accepted false, including when asset checks pass. CLI exit zero means preparation completed, never board approval. It refuses an existing output directory or output inside the native project.

This is an explicit preflight command, not an automatic producer prerequisite or an acceptance gate. Native production/review/routing boundaries remain unchanged. It requires explicit source paths and does not claim universal automatic discovery of historical ignored output. The maintained working instructions now require checking relevant ignored prior outputs before declaring reusable evidence absent and preserving the applicable proxy/exact-package policy.

## B4 prepared work

Final-code output is outputs/readiness-preflight-2026-09-08/b4-prepared-final/. Model preflight passes for 32 proxies; both IC pin sources are available. The existing component evaluator ran with no review responses: outcome unverified, ready_for_routing false, fourteen applicable decisions pending and two deterministically not applicable. The exact obligation worklist is component-review-worklist.json.

Next work is to review those fourteen current-board obligations using the verified facts, record fresh responses, and prepare exact-board visual subject crops and the placement publication transaction. Model-file discovery does not need repeating. Preserve proxy limitations and routed/physical holds. Routing still requires the committed upstream package and an explicitly supported allowance; this scope grants no board runtime.

## Verification and limitations

35 focused and adjacent tests pass, including nine new tests for stale sources, changed electrical intent, connectivity disagreement, duplicate netlist terminals, model hash mismatch, vacuous requirements, native preservation, output retention and exclusion of old approvals. Ruff, scoped mypy and the 196-caller audit pass. The new tests are included in the maintained quick gate.

B4's current native board and stopped job ledger match their start-of-scope hashes byte-for-byte. No PCB edits, routing, rendering, fabrication exports, commits or publication occurred. The first component-evaluator invocation used an incorrect --request flag; argparse rejected it before evaluation. After reading its positional-argument contract, one corrected invocation produced the intended unverified coverage record. Initial formatting/type-name issues were corrected in the same bounded platform pass.
