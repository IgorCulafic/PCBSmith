# Mandatory review and handover trial — 2026-09-15

The user authorized trying the recommendations in `mandatory-check-audit-2026-09-15.md`. This is separately scoped platform implementation. No board was created, rerouted, reapproved or repackaged; existing job clocks and accepted artifacts remain unchanged.

## Implemented behavior

- New predesign approval/publication requires retained `mandatory-review` evidence and an explicit component/model policy. Absence no longer selects the model legacy exception. Historical documents still parse; a new publication using old inputs must supply current evidence. No fabricated legacy authorization or retrospective approval is generated.
- Preparation writes `mandatory-review.template.json`, deliberately incomplete. It carries exact brief/component inventory hashes and profile minima, but leaves review observations blank and applicability unresolved. It also prints absolute floorplan SVG/PNG paths. The designer must inspect and show the preview before recording the existing floorplan decision.
- The review covers every brief component with observations for part/footprint, pinout/polarity, ratings and support circuits, bound to retained source files. It also inventories all five supported engineering rule families, all seven diagnostic-view families, circuit patterns and isolation CAM. Empty/missing/unresolved entries block. Explicit, source-backed not-applicable decisions remain valid.
- Routing checks that engineering feature declarations agree with that inventory. Publication checks that applicable diagnostic views were actually generated as required artifacts. Circuit-pattern omission requires an explicit not-applicable decision; declared patterns still run their existing electrical/source checks.
- Ordinary visual inspection rejects blank reviewer/mechanism/findings, unknown artifacts, invalid states, stale or missing image files and paths outside the review package. It validates the whole batch before writing. CLI decisions additionally require the viewed artifact's `sha256`. Final acceptance checks every required artifact's current bytes and observations, including inherited decisions.
- Native outline augmentation detects disconnected Edge.Cuts groups and closed shapes conservatively, requiring the mechanical detail views when extra loops or uncertain geometry exist. Native DRC still determines outline validity.
- Component moves and jumper placement revisions require `floorplan_bundle_path` and `floorplan_origin_mm`. The bundle and floorplan files must be included in the request's exact source closure. The reviewed floorplan is checked before work, then compared with the planned native delta before candidate copper/placement is written. Existing supported rectangular/front-side floorplan limits remain explicit. Same-footprint substitutions may reuse unchanged placement evidence.
- DRC and ordinary native validation request all enabled severities. Native validation now retains schematic/project input hashes and the resulting report hash. Final release checks required rule names, minimum clearance/width/edge settings, ignored checks, disabled rules and configured exclusions against the reviewed baseline. Exceptions identify the exact omitted value and require rationale plus a retained authorization reference; they cannot disable a rule listed as required.
- `board-handover` replays the existing exact production release and checks native inputs, current ERC evidence, the declared delivery roles and actual delivered bytes/dependencies. A finished job flag is not an acceptance input. Missing files or changed inputs block handover.
- When isolation CAM is requested, handover requires its exact native source identity, native copper SVG, removal SVG and geometry replay, plus an actual source-bound CAM inspection record. Unresolved physical qualification is retained separately with owner, method, acceptance criterion, inputs and board revision.

## Using the workflow

After preparation, complete the generated worklist from real source and visual review. Save it as `mandatory-review.json` and include it in `EngineeringInputs.evidence_files` under `mandatory-review`, with its relative path and SHA-256. The preparation owner adds its current `component-readiness` binding. Each review observation references independently retained evidence IDs; it cannot cite the mandatory review itself as its source. `deliverables` maps role names to the corresponding demand/location in the reviewed brief. Include `isolation_cam` when requested. The agent performs routine review; this is not a new requirement to ask the user to fill forms or repeatedly approve routine work.

For `visual-inspect` and `production-visual-inspect`, each decision now includes:

```json
{
  "artifact-id-from-manifest": {
    "sha256": "exact viewed artifact hash",
    "inspection": "attention_required",
    "findings": ["Specific observation from viewing this artifact."]
  }
}
```

An accepted decision requires a real inspection. The example is intentionally not an approval. Direct shared-owner callers also undergo retained-file/observation validation.

After final review/release and exports, run:

```text
python -m pcbsmith.cli board-handover handover-request.json
```

The read-only command prints a summary and returns zero only for `cad_handover_ready: true`. Save that output with the handover evidence. It does not finish a job, run native CAD, approve images or grant fabrication/physical acceptance. Native checks still run through the existing supported operation/worker and original job allowance.

The request contains paths `generation_root`, `board`, `release_report`, `delivery_root`, `erc_report`, `erc_process`; paths resolve relative to the request. `files` maps the reviewed role names to `{relative_path, sha256}` under the delivery root. Native roles are `pcb`, `schematic`, `project`. `physical_holds` contains records with `board_sha256`, `owner`, `method`, `acceptance_criterion`, `required_inputs`.

For isolation, also supply `isolation_manifest` and `isolation_inspection`. The latter records `svg_sha256`, `manifest_sha256`, `inspection`, `reviewer`, `mechanism`, `view_reference`, and nonempty `findings`. Only a real accepted CAM inspection satisfies handover. Use the supported `laser_artwork` output; merely naming an SVG is insufficient.

The native rule checker reports exact exception IDs as `kind:category:fingerprint(value)`. Review the actual omission before retaining an authorization; do not add exceptions merely to get a green result. Thresholds and declared required rules remain binding.

## Limits of this trial

- This is software enforcement of evidence completeness, identity and supported replay. It does not authenticate that a person/agent looked at an image, correctly interpreted a datasheet, or legitimately obtained an authorization merely because text says so. Those remain genuine review responsibilities, with explicit source/view references.
- The application cannot force an arbitrary chat message or external manual file copy through a CLI. The working instructions make the supported handover check mandatory for future deliveries. Job lifecycle completion remains separate to preserve diagnostics and historical jobs.
- Applicability outside objectively detected native features still requires engineering judgment. No blanket thermal/RF/3D requirement, automatic rerouting or repeated rendering was introduced.
- Existing accepted boards are preserved. Their historical evidence has not been migrated or declared compliant with this new policy. A fresh real-board trial remains distinct from the software tests; none is claimed here.
- The handover command currently reports physical qualification as not established and retains holds. It does not ingest a physical qualification campaign to grant manufacturing approval.

## Verification

Final verification: **236 tests passed in 44.40 seconds**, type checking passed for 11 changed modules, scoped lint passed, and the workflow audit passed for 209 callers. CircleBlink PCB/schematic hashes match their accepted identities. No changes were committed.

Regression results, workflow audit and source-change inventory are retained under `outputs/mandatory-check-implementation-2026-09-15/`. Software fixtures are explicitly synthetic and never substitute for board approval. The final result file records exact checks and limitations.

New owners: `mandatory_review` validates inputs/replays evidence; `board_handover` is a read-only release/delivery consumer; `require_native_floorplan_text` validates a planned in-memory delta. None is a new board producer or router. Existing preparation/review/edit/native validation owners retain their worker and transaction boundaries. Workflow entrypoint audit: 209 callers, no unclassified or changed call signatures at the audit boundary.
