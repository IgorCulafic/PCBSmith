# Production entry points

**Inspection/qualification follow-up - 2026-09-10:** Use the [explicit follow-up register](board-follow-up-register.md). Missing decisions require evidence closure, physical unknowns require measurements, and only diagnosed CAD defects enter correction cycles. Completed checks are not repeated without changed inputs or new findings. B4 metadata is closed by the exact immutable inspection successor; the fresh exact visual review is also closed. See docs/current-state.md for current dispositions.

**Ordinary board runs:** apply the [bounded-delivery policy](bounded-board-workflow-2026-09-06.md) before preparation: declare a total deadline/revision allowance, inspect and show the vector floorplan before native placement, and resolve existing shared assets before fetching. Preserve required engineering/native checks. Stop with the saved candidate and blocker when the allowance expires or required platform support is missing. Do not extend board work into unbounded framework repair. [B1 runtime guards](implementation/bounded-workflow-b1-2026-09-07.md) now require the same supervised job at supported CLI and producer boundaries. Individual execution profiles still do not replace the aggregate allowance. Start with `pcbsmith board-job start ROOT --rationale "..."`; invoke the production commands below as arguments to `pcbsmith board-job run ROOT --args ...`. Use `--module pcbsmith.native_project`, `--module pcbsmith.predesign_preparation` or `--module pcbsmith.production_routing` before `--args` for those module commands. B2/B3 pass their scoped software gates; the independent familiar fresh-board timing proof is complete. Original B4 timing remains failed; DR7 remains open.

The supported orchestration boundary is production_generators.py plus
production_workflow.py. Historical raw builders remain research utilities; invoking
one directly does not produce an accepted production candidate.

Run pcbsmith --help or pcbsmith COMMAND --help for exact argument syntax.
The maintained sequence is:

1. Prepare a PredesignReadinessBundle: approved overlays/brief, replayable component
   alternatives/support/power review and a mapping from every engineering evidence
   identifier to a retained relative file and SHA-256.
2. production-generate-board SCHEMATIC OUTPUT --predesign BUNDLE.json
   --predesign-artifacts EVIDENCE_ROOT runs the registered builder in a fresh directory.
   Inspect the candidate and its builder receipt. Provide all local input dependencies;
   a bare schematic is not an assurance that external libraries are complete.
3. Prepare PublicationReadinessRequest for the exact saved native inputs. Bind every
   populated reference to an approved intent, model preflight and required visual
   subject crops. Placement/routed review commands require --readiness-request and
   --readiness-artifacts, in addition to their existing review arguments.
4. The publication adapter recomputes measurable crop occupancy against the actual
   PNG files and retains engineering inputs plus review/design-readiness.json.
   It leaves visual acceptance pending; supplied human observations are not
   independently authenticated by the software.
5. Route gates and routed release gates require --generation-root and replay that
   retained evidence. The existing typed engineering, component, ERC/parity,
   routing-engine, read-back, netlist-equivalence and applicability checks still apply.
   Bounded local repairs keep their existing owners and invalidate affected evidence.
6. Manufacturing export seals producer receipts. Pass the exact production generation
   and release report to assemble_neutral_manufacturing_package through
   production_generation_root and production_release_report_file. Missing upstream
   evidence can produce only a blocked inspection package; stale supplied evidence
   is rejected. Separate human/fabricator/assembler approvals are still required.

Use the typed models in src/pcbsmith/production_readiness.py as the schema authority.
Their model_json_schema() output can be used to validate preparation tooling; do not
fill required evidence with dummy positive values. Source/crop/approval fixtures in
tests are explicitly synthetic and cannot qualify a board.

The generic path is integrated and tested. DR7 remains open until two materially
different new-board projects complete it with real engineering/review evidence.
No CLI command automatically chooses or approves a paused board.

## Automatic routing default (2026-09-12)

Use `pcbsmith board-job run ROOT --module pcbsmith.production_routing --args ...` after the approved engineering placement and existing entry checks. Omitting `--freerouting-config` now selects pinned Freerouting, not the native research router. Configuration resolution is explicit CLI path, then `PCBSMITH_FREEROUTING_CONFIG`, then the nearest ancestor `.pcbsmith/freerouting.json`, then this installation's `.pcbsmith/freerouting.json`. An explicit missing configuration fails closed. The configuration binds the downloaded JAR hashes, Java and KiCad Python paths, process timeout and pass cap. This installation uses Freerouting 2.3.0, 600 seconds and 30 passes; the shared job's execution/deadline limits still apply.

New jobs record policy `freerouting-one-retry-v1`: at most two routing invocations across the job. The retry requires changed component placement/footprints or connectivity, such as approved jumper planning. Budget/order changes, cosmetic edits and fresh directories do not qualify. Old job records retain their exact historical policy and counters. No automatic engine switch or manual finishing follows a partial result or failure. Preserve the result and diagnose the placement/jumper blocker once.

The production DSN bridge supports unrouted rectangular F.Cu-only and F.Cu/B.Cu boards. Single-sided jobs prohibit vias; two-layer jobs use the declared through-via geometry. Nonrectangular outlines, cutouts, existing routed copper/zones and native plane-pour routing constraints remain unsupported by this bridge and produce explicit blockers. Do not silently relax rules or select another engine. Source-bound native import/readback, DRC, opens, parity and existing review/release obligations remain required. Generate and inspect requested isolation channels after final routing; an autorouter result alone is not manufacturing acceptance.

Manual segment/via edits and the existing copper-cutting zero-ohm-link revision adapter require `BoardRevisionRequest.manual_routing_authorization` containing the user's actual explicit request. Retained routing repair additionally requires `--manual-routing-authorization` and an existing `--revalidate-result`. Placement and annotation edits retain their supported owners. These fields record authorization; software cannot authenticate a human statement. Historical accepted revisions still replay unchanged. `--legacy-native-reason` is an explicit research/reproduction escape hatch, never an ordinary fallback.

See [implementation and verification](implementation/automatic-routing-workflow-2026-09-12.md).

## Review engineering inputs before approval

Use `python -m pcbsmith.engineering_preview PREPARED_ROOT --engineering FACTS_JSON`
for a read-only diagnostic of typed declarations, alternatives, support, power and
source-file identities. Omitting `--engineering` prints the component worklist and
an explicit missing-input blocker. This CLI prints to stdout and runs outside the
board producer supervisor; it never grants an operation, approval or runtime.

The existing approval owner replays the same input checks. A diagnostic result
cannot replace a source-bound reviewer assertion, native/model checks, visual
inspection or physical qualification. Review source-page interpretations and
applicability completeness before making a decision. See the
[implementation and limits](implementation/engineering-preview-fix-2026-09-11.md).

## Retention and recovery
New candidate/export/review roots must not already exist. Builder failures stay in
their attempt; failed review work is retained under .failed-reviews with failure.json.
Safe project edits use the file_transaction journal; see its explicit recovery
entry point before manually altering a pending transaction. AI reviews return
attempt-specific paths instead of overwriting a previous transcript.


## Iterative edits to an existing native board

Use `production-inspect-board BOARD --output INSPECTION.json` to obtain exact source-input hashes, stable target IDs, poses, segment endpoints, reference-text positions and model offsets. The optional inspection output must be fresh and outside the source project. Copy its entire `source_inputs` mapping into a `BoardRevisionRequest`; do not invent hashes or drop library members.

For example, after inspection, a request can contain:

```json
{
  "schema_id": "pcbsmith-board-revision-request",
  "source_inputs": {"<each inspected relative path>": "<its exact SHA-256>"},
  "intent": "requested",
  "rationale": "Move the selected label to the reviewed position",
  "edits": [{"kind": "text", "target": "<inspected UUID>", "position_mm": [57, 28.7]}],
  "maximum_displacement_mm": 1,
  "maximum_changed_objects": 1
}
```

The placeholders are explanatory, not runnable evidence. `BoardRevisionRequest.model_json_schema()` and `NativeEdit` define the exact schema.

1. `production-edit-board BOARD --request REQUEST.json --output FRESH_ATTEMPT` retains an immutable predecessor, applies the declared delta to a copy and runs live native ERC/DRC including schematic parity. It creates `request.json`, `before/`, `design/`, `delta.json`, shared IF1Ã¢â‚¬â€œIF5 stage records/checkpoint, native check files and a revision receipt; failed attempts remain available.
2. Inspect the candidate and affected engineering/visual obligations. `digitally_checked_candidate` means the enabled native checks passed for a working CAD revision. It is not engineering, visual, routing-engine, fabrication or release acceptance. Model-offset edits additionally check model resolution; unregistered package/transform/visual qualification remains `attention_required`.
3. `production-apply-board-edit BOARD --revision ATTEMPT` recomputes the candidate from the retained predecessor and request, checks all bound input hashes, reruns live native checks and applies the board plus `.pcbsmith/accepted-board-edits.json` through the existing recoverable file transaction. A conflict does not overwrite intervening work. The output says `working_revision_applied`, with `production_accepted: false`.
4. Before stronger publication/release, refresh affected review/readiness/routing/manufacturing evidence through the existing boundaries above. Their old hashes cannot qualify the edited board. Restore through a checked inverse edit where supported; transaction recovery handles an interrupted application. Retained attempts and journal references are part of provenance and should not be removed casually.

Supported deltas in this increment are text/reference position and rotation, front-side component pose, straight-segment polyline replacement, via position, an existing model's local xyz offset, explicit `zone_refill`, and single-outline same-vertex-count `zone_outline` changes. Component/via moves stretch same-net segment endpoints exactly coincident with affected pad/via centres. Trace replacement preserves its existing connected ends, net, width and layer; added segments receive deterministic IDs. Positions use board millimetres, except reference text uses footprint-local millimetres and model offset uses model-local xyz millimetres.

An explicit requested move need not improve the generic topology score. `intent: optimize` currently supports component poses and requires that existing score to improve. Native checks do not establish analog behavior, return-path quality or mating access. Rotated pad/text angles are updated with their parent pose. Changes are budgeted and compared by native object identity/semantics; whole-file serialization is not board regeneration.

Use `mutable_zone_ids` to declare every zone whose computed fill may change. Inspection exposes each zone's native ID, net fields, layer, outline vertices and filled-region count. A `zone_refill` edit requires its target and no position; `zone_outline` supplies `points_mm` in existing vertex order. Refill uses the exact project rules and local dependencies. Only declared computed fill is imported; changed zone parameters or an undeclared zone block the attempt. The complete zone extent participates in region checks even when only one vertex or component moved. Application runs a fresh refill and requires the saved fill to match.

An optional `region` contains `initial_region` (`x_min_mm`, `y_min_mm`, `x_max_mm`, `y_max_mm`, `expansion_index: 0`), `maximum_expansions` (0Ã¢â‚¬â€œ8), and `expansion_margin_mm`. The existing region owner expands only after a retained geometric failure. `protected_regions` declare fixed geometric areas. These are geometric preflights for the requested delta, not route-search or return-path qualification; native ERC/DRC runs afterward. An optional source-bound `FindingObservation` identifies a diagnosed request; missing/upstream authority blocks it.

For an interrupted, nonterminal attempt use `production-edit-board BOARD --request REQUEST.json --output EXISTING_ATTEMPT --resume`. The request, source closure, predecessor, candidate and completed stage evidence must still match. Completed IF stages are reused and partial native/fill files are preserved before retry. Terminal failures need a fresh attempt with corrected inputs. An interrupted application uses the existing `pcbsmith.operations.file_transaction.recover_project_files(project_root)` recovery entry point; do not erase its pending marker or journal. Recovery rejects intervening manual file changes.

Supported retention includes recursive project-local schematic sheets, table-declared libraries and local model files, plus project/custom rules and accepted-edit history. Installed/external package and model qualification remains Phase 2 work. Unsupported changes stop with a reason: back-side component moves, attached arcs/locked copper, footprint/package substitutions and arbitrary outline/layer/architecture changes need their validated adapters or a justified rebuild. Off-centre attachments are not guessed; a resulting native disconnection blocks application. No failure silently invokes a generator or autorouter. See the [Phase 1 completion record](implementation/roadmap-phase-1-completion.md) for actual native coverage and remaining qualification obligations.


## Controlled rebuilding and research paths

Initial generation remains available when there is no native predecessor or accepted-edit journal. If a sibling PCB exists, `production-generate-board` requires `--rebuild-decision DECISION.json`. Prepare a `RebuildDecision` with `rebuild_input_hashes(board)`, an actual authorized reason, rationale, authorization reference, invalidated requirements and considered local alternatives. The decision must match the current native inputs and accepted-edit journal. A claim of exhausted local repairs additionally needs hashed retained failed edit records for that predecessor. This records the engineering decision; it does not authenticate its author or prove physical infeasibility.

The shared builder retains the predecessor, decision and native object comparison and writes a fresh candidate. If the predecessor cannot be compared, that limitation is retained. A rebuild does not overwrite the source or restore old review/release approval. Exact external package/model dependency qualification remains a separate obligation; generation and editing do not infer it from the presence of a library table.

Legacy `design-*` CLI commands require `--research` and emit an explicit research/compatibility warning. The frozen BenchLeaf recipe also requires `--research` and refuses repeated routed generation into an existing design/attempt root. Research opt-in is for explicitly authorized reproduction/diagnostics, not a way to satisfy an ordinary board request. Historical helper imports and other direct scripts are still callable; they are not production acceptance boundaries.

Run `python tools/audit_board_workflow.py` (also part of shared verification) before handing over new board work. Its classified potential callers expand the former 23-generator inventory across source and tools. Unknown callers, changed calls and stale classifications fail the audit. Classification does not prove execution through production gates; dynamic code, subprocesses and arbitrary local writes are not sandboxed by it. New DR7 proofs must still demonstrate the actual supported path.


## B2/B3 additions (2026-09-07)

Predesign preparation emits floorplan.json, floorplan.svg and floorplan.png from design-spec placements. Inspect and present the preview before approval. Add floorplan_review to the existing reviewer assertion, containing floorplan_sha256 (hash of floorplan.json), inspected: true, presented: true, reviewer_id, rationale, presentation_reference and corridor_rationale. These values must describe an actual review. SVG existence alone is insufficient. Declare floorplan_corridors in the spec using name, references (two component references), purpose (signal/return/access), and width_mm; omitted corridors need an explicit applicability rationale.

The new generic production placement gate consumes the derived layout_input and verifies native anchors/orientations/outline. Optional reference-text positions and labels may accompany it; alternate component geometry is rejected. Other generators require a validated adapter.

NativeProjectSpec accepts asset_pins entries with kind (symbol/footprint), library_id, sha256 and optional local_path. local_path is resolved from the invocation working directory; use an explicit absolute path for a reviewed external pin. Board packages retain their local dependency copies.

For a missing asset, run the existing supervised job with arguments:
asset-resolve PIN.json --intake INTAKE.json --repository-root . --private-asset-root PRIVATE --private-manifest PRIVATE_MANIFEST --public-manifest PUBLIC_MANIFEST --cache-dir CACHE

Use private paths for confidential sources. Omit --intake for local-only resolution. INTAKE uses the existing SourceIntakeRequest schema and must pin original downloaded bytes; PIN.sha256 targets normalized installed bytes. Configure PCBSMITH_PRIVATE_ASSET_ROOT for subsequent private-library reuse. The resolver reports local hit/installation, chosen path, installed hash and fetch count; conflicts fail without substitution.

## Diagnostic checkpoint

Use board-job diagnose-start ROOT --reason "..." before a broader assessment, then board-job diagnose-complete ROOT --assessment ASSESSMENT.json. One five-minute maximum window ends before the original verification reserve. The recommendation never grants more attempts or time. See [policy and schema requirements](bounded-board-workflow-2026-09-06.md#diagnostic-checkpoint-after-failed-corrections-agreed-2026-09-08).


## Explicit continuation after user approval

Use `board-job continue-authorized ROOT --request REQUEST.json` only for an explicit user continuation decision following a diagnosed local edit. `ContinuationRequest` in board_job.py binds the exact ledger, job-local diagnostic/evidence and authorization. It records one extra window (at most 30 minutes, at least 20 percent verification reserve), preserves all original history, allows each declared edit/apply-edit/routing operation once and grants no correction cycles. An ordinary second continuation is refused. A completed prior diagnostic, newly referenced explicit user authorization, substantive blocker_resolution and unchanged job-local resolved_evidence permit recovery through the same owner. All old windows, attempts, deadlines and correction limits are retained; previously consumed build operations cannot be repeated in the same correction cycle. See [current recovery implementation and trial](implementation/bounded-workflow-completion-2026-09-08.md).


## Early readiness source preparation

Before declaring component/model evidence absent, inspect relevant ignored previous-project outputs as well as shared libraries. Preserve the established prototype proxy policy where applicable; do not silently substitute exact manufacturing-package requirements.

The read-only command below prepares current-board inputs while preserving pending approval. All arguments are paths. Use a fresh output directory outside the native project:

```text
python -m pcbsmith.readiness_preflight --board BOARD --netlist-file NATIVE_XML --prior-component-input PRIOR_REVIEW_INPUT --registry-file MODEL_REGISTRY --requirements-file MODEL_REQUIREMENTS --output FRESH_PREFLIGHT
```

It emits a source-bound report, freshly evaluated model preflight and component-review draft with no approval responses. Historical electrical equivalence excludes only schematic UUID paths. A successful preparation exit is not readiness acceptance. Explicit source discovery and current visual/engineering review remain necessary. See [B4 proof and limitations](implementation/readiness-preflight-2026-09-08.md).


## Exact routed validation replay (2026-09-09)

`pcbsmith.production_routing` now requires `routed_engineering_source` and its SHA-256 in `RoutingGateInputs` when routed bypass checks were deferred. The pinned source lists explicit capacitor/load pin roles and project screening criteria. It must cover all deferred declarations before routing. Native copper execution can still reject or leave the engineering gate unverified.

To revalidate a retained complete candidate after fixing its checker, pass `--revalidate-result RESULT.json --revalidate-sha256 SHA256` together with the unchanged original routing inputs and a fresh output directory. Invoke this through the same `board-job run --module pcbsmith.production_routing`; it is the finite verification operation `routing-validation`. It checks the exact predecessor result/request/snapshot/source/candidate/log identities, invokes no routing engine and requires identical native board bytes. A partial route, changed input or changed candidate is rejected.

A resolved-blocker `continue-authorized` request may use `build_operations: []` for explicit verification-only recovery. It grants no editing, generation or routing. A distinct newly authorized routing retry requires `retry_failed_operations: {"routing": "EXACT_LATEST_FAILED_TOKEN"}`, changed effective inputs and the existing hashed resolution prerequisites. It retains all original counters, scopes and the lifetime operation limit. Neither mechanism renews itself or converts a failed timing trial into a pass. See the [implementation and actual remaining blocker](implementation/routing-acceptance-2026-09-09.md).


## Independent timing and approved envelope replay (2026-09-10)

New `board-job start` CLI jobs use separate clocks. `--evaluation-seconds` defaults to 1200; `--execution-seconds` defaults to the declared complexity's finite allowance (1800 for simple). Twenty percent of execution is reserved for verification. `status` reports `timing` alongside the existing state fields. Time between contained workers consumes evaluation; worker duration consumes execution. Both plus total wall time remain visible. No pause or caller-supplied phase is available. Existing ledgers are not migrated and retries never reset these clocks. Authorized continuation requests may declare `evaluation_seconds` explicitly.

For the approved exact-simple to conservative-envelope method change, use `--engineering-revision FILE --engineering-revision-sha256 SHA` with immutable `--revalidate-result` inputs. `ConservativeEnvelopeRevision` binds the prior source/result and exact candidate, explicit authorization reference and revised source. Thresholds, topology, terminal roles and coverage must remain identical. The updated policy and approval are retained under candidate verification, and all native/engineering checks run again. This is a geometry-screening method, not physical supply integrity or EMC qualification. See [implementation and current outcome](implementation/separate-timers-envelope-2026-09-10.md).

## Native preparation input closure (2026-09-10)

New native preparation records schematic-byte, exported-XML-byte and canonical specification hashes in netlist-vs-intent.json. Predesign replays component identities and per-pin connectivity against current inputs before creating its artifacts. A legacy unbound report or changed input stops preparation. Refresh through the supported native preparation within its authorized job; do not edit a passed report, reset a finished job or regenerate a completed PCB merely to add missing metadata. This check does not qualify manufacturer pin mapping or purchased-package dimensions. See [Phase 2A evidence](implementation/phase-2a-input-closure-2026-09-10.md).

## Pre-placement component evidence (2026-09-10)

Preparation now emits component-readiness.json and approval replays its current sources. Optional project-local component-pin-evidence.json and component-package-geometry.json map references to the source-bound schemas documented in [Phase 2B](implementation/phase-2b-readiness-2026-09-10.md). Relative source paths are native-project-relative. Default model resolution, nominal CAD geometry and pin-number equality are not package/physical approval. Review explicit gaps before sealing; old prepared drafts without the inventory binding need supported refresh. Existing committed generations and finished jobs remain unchanged.


New predesign approvals also require native-project-local `component-model-selection.json`: explicit applicability/rationale plus the existing model registry and per-reference requirements. Applicable models require hashes and expected transforms; every selected part reference must be covered. Relative registry local paths are native-project-relative. Approval replays this selection, and saved-board publication checks the same policy and model identities. See [schema, migration and limits](implementation/phase-2b-model-binding-2026-09-11.md). Previously committed bundles are retained as historical evidence; do not edit a finished job to refresh them.


Same-footprint part replacement is available as a separate `substitutions` list in the existing board revision request. Use `production-inspect-board --substitutions replacements.json` to bind complete source/qualification inputs first. The shared edit/apply transaction preserves copper and updates PCB, schematic, spec and evidence together; replacement still requires current checks and fresh release reviews. See [scope, schema, inputs and limits](implementation/phase-2b-substitution-2026-09-11.md).

### Phase 2B trial input lessons

When generating a model-preflight report for publication, pass the exact selected-model applicability and rationale as well as registry/requirements (including --model-applicability-rationale); publication replays that whole policy. Matching model hashes alone does not match a report with omitted rationale. Declare component tolerance/capability requirements explicitly before comparing alternatives. The [DividerLeaf trial](implementation/phase-2b-new-board-proof-2026-09-11.md) demonstrates both rejection paths and a real supported substitution. Edit/apply acceptance remains working-CAD status; a changed MPN/value invalidates old publication lineage even when copper is preserved.

## Supported circuit contracts (Phase 2C)

For new connector, supply-bypass and resistor/LED patterns in the supported scope, bind a `pcbsmith-circuit-patterns-v1` file as the `circuit-patterns` engineering evidence ID and cite it in mandatory support requirements. Bind exact native XML, selected parts and manufacturer page notes; declare operating limits and physical holds explicitly. Preview and ordinary approval/publication replay the shared consumer. Unverified or single-frequency-only data cannot satisfy a declared full operating envelope. Existing immutable no-pattern records retain their historical scope; they are not new pattern proofs.

See [the Phase 2C contract, examples, checks and limitations](implementation/phase-2c-circuit-patterns-2026-09-11.md). This supplements existing power-path/support reviews, native checks and bypass geometry; it does not replace them or grant a production approval.

## Finished-job inspection completion

`pcbsmith board-job authorize-inspection-completion ROOT --request REQUEST.json` records an explicit, finite, source-bound inspection-only authorization. The typed request is `InspectionCompletionRequest` in `pcbsmith.inspection_completion`; it pins the current pointer and review manifest, confined transaction root, successor ID, reviewer/mechanism and separate evaluation/execution allowances.

`pcbsmith board-job complete-inspection ROOT --decisions DECISIONS.json` records actual artifact SHA-256, inspection state and nonempty findings for every missing required view. It preserves the finished job and every non-review artifact in an immutable successor. No live board worker or correction allowance is created. The exceptional `--resume-failure-sha256` is only for the documented legacy final-publication missing-component-execution failure, once within the same original caps and identical decisions. All other failures require diagnosis rather than a repeat command. See the [Phase 3A record](implementation/phase-3a-inspection-completion-2026-09-11.md).

## Ordinary input preparation after local edits (Phase 3B)

Use these read-only preparations before committing a finite routing operation. Their computation is preparation/evaluation time in the existing job; they grant no worker or approval.

```text
python -m pcbsmith.kicad.layout_input --board BOARD --source-sha256 SHA --base-layout CANONICAL_LAYOUT --netlist CANONICAL_NETLIST --profile RULE_PROFILE --output NEW_PREPARATION
python -m pcbsmith.production_readiness models --board BOARD --bundle PREDESIGN_READINESS_BUNDLE --artifact-root RETAINED_SOURCES --output NEW_MODEL_REPORT
python -m pcbsmith.routing_preparation --request ROUTING_PREPARATION_REQUEST --output NEW_ROUTING_INPUTS
```

`RoutingPreparationRequest` in `routing_preparation.py` pins the current transaction fingerprint and source files. Each source has `path`, `sha256`, and optional JSON `pointer`; paths are relative to the command's working directory unless absolute. Layout/netlist/profile are whole canonical files. Review and component execution come from the current generation. A changed layout fingerprint requires the corresponding refreshed engineering review; do not copy an old approval to the new fingerprint. Keep the source files and prepare before routing so stale geometry does not consume a routing attempt.

| Stage | Existing command/owner | Required transition |
| --- | --- | --- |
| Define and prepare | `board-job start`, `pcbsmith.native_project`, `pcbsmith.predesign_preparation` | Same root, sourced specification, vector plan inspected before native placement. |
| Review facts | `pcbsmith.engineering_preview`, supported predesign approval | Resolve actual facts and alternatives before writing a genuine decision. |
| Create and publish placement | Registered production builder, `production-placement-review`, `production-visual-inspect` | Native/model/engineering checks and exact visual decisions. |
| Revise or resume | `production-edit-board`, `--resume` for an interrupted nonterminal attempt, `production-apply-board-edit` | Exact request/source/checkpoint; local delta and fresh applicable native checks. |
| Prepare routing | The three commands above plus existing engineering/component owners | Exact saved geometry and current typed sources; blocked input is not a router failure. |
| Route and publish | `board-job run --module pcbsmith.production_routing`, `production-routed-review` | Same job limits; full actual native validation and final inspection. |
| Export | Existing manufacturing/release and classified export commands above | Current release replay; digital prototype status is distinct from physical/fabrication acceptance. |

### Qualified substitution publication

`python -m pcbsmith.routing_revision --routing-result ORIGINAL_RESULT --routing-result-sha256 SHA --revision-directory CHECKED_REVISION --revision-sha256 REVISION_JSON_SHA --output NEW_PROOF` derives unchanged-copper provenance. It does not produce a new routing approval or restart a finished job.

For a revised board, `production-routed-review --routing-execution NEW_PROOF --revision-authority FRESH_AUTHORITY ...` additionally requires the typed `RevisionPublicationAuthority` in `routing_revision.py`. Supply the current canonical layout, rule profile, replay-derived engineering gate and component-review execution; refresh the usual readiness request and selected MPN/specification bindings. Retain all checked candidate inputs through `--support-file`. The original routing execution remains embedded unchanged. Publication replays the revision, checks exact support inputs and current geometry/authorities, and invokes its normal fresh native/readiness/visual owners. Missing source facts stay blocked. Legacy execution receipts retain their original interface.


## Recovery before the first native preparation

A stopped, diagnosed concept with zero previous attempts and no native files can use `continue-authorized` with `ContinuationRequest.pre_native_recovery`. Bind the explicit user's accepted SVG/PNG/structured-intent files through `PreNativeLayoutApproval`, the exact predecessor/diagnostic and separately verified resolution sources. Declare native-preparation, predesign-prepare, predesign-approve and placement plus any bounded optional routing/edit operations. All normal worker, source, review and production gates still apply. This one initial scope cannot renew itself, adopt existing native inputs or reset any history. See [repair and validation](implementation/pre-native-recovery-2026-09-12.md).


For a pre-native recovery's single missing-spec failure, `board-job resolve-native-preparation-input ROOT --token EXACT_FAILED_TOKEN` permits only the supported missing-input case after validating the corrected spec. The next native command and pinned spec must match. No time/cycle reset is granted. Other failure kinds retain the diagnostic requirement.


## Mandatory review and CAD handover (2026-09-15)

New preparation produces `mandatory-review.template.json` with unresolved applicability and blank observations. Complete it from real engineering review and bind the finished file as `mandatory-review` in engineering evidence before approval/publication. Missing declarations do not grant historical acceptance. Visual CLI decisions include exact image `sha256` and nonempty observations. For placement-changing revisions, retain the reviewed floorplan bundle and its files in `source_inputs`, and supply `floorplan_bundle_path` plus `floorplan_origin_mm`.

After the existing final review/release and requested exports, run `python -m pcbsmith.cli board-handover REQUEST` and retain its JSON result before delivery. A zero exit status means current CAD handover checks pass; it does not establish physical qualification. The request binds current native ERC/process evidence, exact delivered files, dependencies and requested isolation CAM. Follow [mandatory review workflow](implementation/mandatory-check-workflow-2026-09-15.md) for fields, compatibility and limitations. Routine reviews remain the designer's authorized work; this is not a new user approval loop.


## Combined native review and evidence completion (2026-09-21)

Run `python -m pcbsmith.cli native-review-preflight REQUEST.json` before final publication. Paths resolve relative to the request file. Required fields are `board`, `readiness_request`, `readiness_root`, `erc_report` and `drc_report`; each native report must accompany its `.process.json` receipt. The read-only command replays current native inputs and returns both ERC and DRC ignored/disabled/excluded inventories in one unresolved worklist. It never supplies an approval or N/A decision. Retained older DRC evidence may bind report bytes through its actual typed `.execution.json` receipt.

Registered routed publication now runs the shared all-severity ERC checker alongside its nonmutating DRC and retains `verification/native-rule-worklist.json`, ERC report/process, and DRC report/process/execution. Unresolved omissions block before final rendering. A required native rule remains mandatory even if an exception names it; KiCad 10 object-shaped ignored-check entries are recognized. Ordinary final `production-visual-inspect` no longer requires a placement component-execution artifact that routed generations do not necessarily contain; actual hash-bound decisions and immutable transaction checks still apply.

`routed-release-gate` assembles its mandatory DRC requirement from the actual producer-owned execution receipt and retains `OUTPUT.applicability.json`. It rejects conflicting/stale evidence and preserves every unrelated required or unresolved check. It does not synthesize passing executions.

For an already released, unchanged board with missing omission decisions, `board-handover` and `native-review-preflight` accept an optional `native_rule_review` file. The `pcbsmith-native-review-completion-v1` record pins `predecessor_review_sha256`, exact `native_inputs`, `reviewer`, `authorization_reference`, additive `rule_exceptions` and independent hashed `evidence_files`. The shared mandatory-review owner permits no other policy fields and no replacement of existing decisions. This is evidence-only completion: it grants no board runtime, CAD changes, rule relaxation or physical qualification. Keep the old generation and failed handover, and retain the new checker output. Any material revision still uses the ordinary revision/publication workflow and current source-based reviews.


### Diagnosed single-layer adapter recovery (2026-09-22)

Ordinary automatic retries still require a meaningful placement/connectivity change and remain limited to two total invocations. When an explicitly authorized, separately qualified shared adapter repair resolves a completed platform-work diagnosis, the same-root continuation may declare `routing_adapter_repair_sha256`. The request must bind the latest failed routing token and retained resolution evidence containing those exact adapter bytes; the shared owner checks the installed adapter and evidence again before the attempt. It grants no extra invocation, correction cycle, manual routing or automatic renewal. See [repair evidence and limitations](implementation/single-layer-routing-repair-2026-09-22.md).

New/revised handovers include the portable interactive HTML BOM by default, generated through the pinned owner with exact delivered-board lineage. Include the editable dimensioned vector floorplan and preview too. Report any missing deliverable explicitly; generation does not establish browser interaction qualification.


### Source-qualified SMD substitutions — 2026-09-22

The existing same-footprint substitution request also supports front-side SMD rectangular/roundrect pads through explicit `SmdPackageGeometryEvidence` (`mounting: "smd"`). Preparation and revision use the same typed source-bound validator. Both predecessor and replacement need genuine maximum body, guaranteed terminal contact and required land evidence; matching footprint names alone are insufficient. Legacy THT evidence remains compatible. The existing transaction preserves pads, placement and copper; native checks and fresh release reviews remain mandatory. See [schema fields, usage, tested scope and limits](implementation/smd-substitution-support-2026-09-22.md). No back-side, custom-pad or automatic package-remapping support is implied.


## Recurring files, pre-render checks and diagnostic reuse (2026-09-22)

New preparation approval, registered generation and publication require reviewed roles `pcb`, `schematic`, `project`, `interactive_bom`, `floorplan`, and `floorplan_preview`. Complete their source/requirement references in the generated mandatory worklist. Keep the iBOM producer receipt adjacent to the HTML as `NAME.receipt.json`. Handover replays its exact native/HTML lineage and compares both vector files against their reviewed evidence bindings. Historical role inventories remain readable; new publication cannot omit the recurring roles.

Before standalone final rendering, use `python -m pcbsmith.cli visual-review BOARD OUTPUT --stage final --features FEATURES --model-preflight MODELS --native-checks CHECK_DIRECTORY` inside the same supported board-job worker. CHECK_DIRECTORY contains exact current `erc.json`/`drc.json` plus their `.process.json` receipts (and the actual `.execution.json` where used). Missing/stale/failing checks stop before rendering. Placement reviews retain their separate pre-routing stage; the final release still performs all applicable mandatory/native review.

If an older failed visual manifest already has the current source images but is missing diagnostic copies, `python -m pcbsmith.cli visual-complete-diagnostics MANIFEST FRESH_OUTPUT --features FEATURES --model-preflight MODELS` uses the shared `diagnostic-completion` verification operation. It requires the same live authorized job, exact retained identities and unchanged declarations. It does not grant time, corrections or positive inspections, and performs no rendering. Do not use it to replace a changed or missing source image.

Requested isolation handover checks reviewed clearance/edge minima against a conservative native-copper enclosure, independently of nominal SVG spacing. Legacy front-only behavior is preserved. Explicit `--two-sided --copper-layer B.Cu --mirror-x` now supports rear traces, ordinary through vias and round-drilled plated lands on rectangular boards; front components only. Arcs, zones, slots, offset drills, blind/micro vias, custom/removed copper layers and other unsupported copper still block. `--full-clear-region X0 Y0 X1 Y1` removes floating background within board-local rectangles while retaining native circuit copper. A declared `--variants FILE.json` exports at most eight comparisons in one supervised operation; each requires exact review and handover replay. See the [two-sided extension and handover fields](implementation/two-sided-laser-cam-2026-10-01.md) and [original geometry bounds](implementation/consolidated-workflow-2026-09-22.md). Physical qualification remains separate.
