# Phase 2B - early package/dependency evidence - 2026-09-10

Status: pre-placement inventory, source-bound THT geometry screens and model-integrity hardening implemented and verified. This is a substantial completed software portion of 2B, not blanket package qualification or full Phase 2 completion. Remaining integration/qualification gates are explicit below.

## Confirmed problems and practical impact

1. Model registry/requirement dictionaries silently selected the last duplicate key, allowing one entry to replace another's classification policy. Non-finite transforms and infinite tolerances could escape numeric alignment comparisons; malformed XYZ clauses silently defaulted to valid coordinates. Eleven of twelve new negative controls failed before the change (NaN tolerance was already rejected). These were high-priority evidence-integrity defects, not evidence that retained physical models were wrong.
2. The declarative predesign adapter did not emit a component-by-component package/dependency inventory and labeled every component through-hole. This hid missing evidence and could misdescribe SMD selections. The new report derives mounting from the actual selected pads.
3. The normal footprint cache keys on path/mtime/size. A content-verification consumer could otherwise observe stale parsed geometry after equal-size, timestamp-preserving file edits. Readiness now explicitly requests an uncached read through the existing loader; normal performance caching is unchanged.

## Implementation

- New shared kicad/component_readiness.py calls the current native input-closure check and project-local footprint owner. It inventories each selected component, exact footprint file/hash, nominal CAD pads/holes/body drawing, default model path resolution and supplied pin sources. Missing procurement or model qualification remains explicitly unverified. The report grants no production acceptance.
- Optional component-pin-evidence.json maps reference to the existing ComponentPinEvidence schema. Check current source hash, selected MPN and pin-number coverage; consume no old reviewer decisions. Pin function/net semantics still require the existing component/circuit review.
- Optional component-package-geometry.json maps reference to PackageGeometryEvidence. Evidence names the exact selected part/procurement description, retained source hash/page and explicit footprint-local coordinate basis. For centered round THT pads it checks source pin positions/pitch, maximum lead diameter plus declared diametral clearance against the nominal CAD hole, and the declared body rectangle against the footprint courtyard. Wrong pin order, dimensions, hole fit and stale sources fail early. SMD land patterns, slotted/offset holes and repeated-number physical pads are unsupported by this narrow geometry screen and cannot gain a pass from it.
- predesign_preparation emits component-readiness.json before geometry preparation, hashes it into prepared-inputs.json, replays current inventory before approval and retains it in the readiness bundle. Altering a selected dependency or report after preparation blocks sealing. The reviewer assertion remains bound to prepared and engineering inputs; the inventory does not approve itself.
- model_preflight rejects normalized duplicate registry paths, duplicate requirements and footprint references; coordinate values and tolerances must be finite. Absent optional transform clauses retain defaults; malformed or duplicated clauses fail explicitly. Exact/proxy policy is preserved.

## Verification

146 integrated tests pass, including 31 new package/model controls and existing native closure, model, library, readiness, worker-guard and visual acceptance checks. The deliberately failing pre-fix model run is retained. Final lint passes for all six changed source/test files. Strict mypy passes for the new component-readiness and hardened model modules; older native/preparation typing debt from 2A is not declared resolved. The caller audit remains clean: 196 classified, no changed/unclassified/stale calls.

An isolated copy of the actual 32-component native project reopened successfully with its DIP library under vendor/nested/Package_DIP.pretty. Current hashes for both IC pin sources match; all 32 components are inventoried. The hardened saved-board model preflight still passes all 32 registered models under the existing proxy policy. The original board and original native files remain unchanged.

The first isolated replay failed because copied historical evidence paths were repository-relative. Only the copied input paths were explicitly rebased to verified absolute source paths; no source bytes or approvals changed. New inventory-relative evidence paths are project-relative. No search fallback or guessed file match was introduced. Initial lint/type formatting and one optional-hash assignment issue were fixed before final checks.

Evidence is under outputs/phase-2b-readiness-2026-09-10: model-before.xml, integrated-tests.xml, caller-audit.json, component-readiness.json, current-board-model-preflight.json, real-project-verification.json and verification-summary.json. JSON schemas for the optional evidence entries are retained there. CAD/native controls do not establish physical fit or operation.

## Use and migration

Run supported native preparation and predesign preparation in their authorized job as before. Supply optional current pin/geometry evidence beside design-spec.json before preparation. Relative evidence-source paths are resolved against that native project; existing repository-relative sources must be explicitly rebased or retained locally with their hashes. Keep source documents and their licensing/provenance; never fill missing facts with guessed dimensions.

Read component-readiness.json alongside the vector plan before approving. Its CAD fab bounds describe the library drawing, not a measurement. Its model list describes default footprint references, not the final selected/positioned board models. Missing evidence stays a specific obligation; applicable engineering/model/visual gates still apply later. An accepted proxy remains a proxy, not an exact-package claim.

Old prepared drafts lack the new inventory binding and must be refreshed through the supported preparation path before a new approval. Old committed generations, inspection records and job history were not edited. This does not reopen finished jobs, provide retry allowance or require regenerating completed PCBs.

## Remaining 2B gates

Update 2026-09-11: [the next implementation record](phase-2b-model-binding-2026-09-11.md) closes early selected-model binding and the complete positive software integration control. The original list below records this report's initial boundary; a new real-board production proof and qualified substitution are not claimed.

- Exercise a complete positive prepare/approval/publication sequence with the new bound inventory (this turn verified inventory replay and negative approval-consumer controls, not a new full board publication).
- Complete early selected-model policy/transform binding, beyond this inventory of default footprint models; preserve the saved-board model owner and avoid a competing approval path.
- Apply exact procurement/pin-function review and any required geometry evidence to the parts selected for the next proof boards. The real retained project had no new sourced geometry declarations, so its packages remain unqualified; software fixture geometry is not real procurement evidence.
- Verify a qualified substitution via the existing local-edit boundary before claiming the broader Phase 2 substitution exit. Additional geometry families need concrete part/process inputs and scoped tests.

No accepted board geometry, copper, ledger, published generation, paper or physical test result changed. B4 inspection metadata, physical qualification and DR7 remain open. Continue the remaining 2B gates before declaring it complete or advancing the main sequence to 2C.
