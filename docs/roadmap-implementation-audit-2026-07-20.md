# Roadmap implementation audit — 2026-07-20

## Purpose and standard of proof

This audit was triggered after the failed Retro-Pad attempt showed that a
checked roadmap item can still be absent from the production workflow. It uses
three distinct states:

1. **implemented authority** — typed code and focused tests exist;
2. **production-integrated** — a normal project caller invokes it at the
   required stage and preserves its evidence;
3. **proven on an unseen board** — the integrated path completed on a project
   that was not the fixture used to build it.

A library or CLI command does not establish states 2 or 3. A passed regression
does not prove that a board-specific generator called the capability.

## Audited status

| Roadmap scope | Implemented authority | Production-integrated | Unseen-board proof | Audit disposition |
|---|---:|---:|---:|---|
| Phase 0 knowledge base | yes | partially | not applicable | Complete within the frozen nine-source scope; later source work belongs to Phase 11. |
| R1 bounded mask/exposure slice | yes | partially | bounded fixtures | Complete only for the named slice. R1 overall remains open. |
| R2 negotiated routing | yes | no | bounded maze/compact board only | Accepted bounded authority; legacy routing remains the default in project generators. |
| R3 shaped capacity/corridors | yes | no | bounded shaped fixtures | Accepted bounded authority; no complete production-board adoption. |
| R4 ordered bus/lane path | yes | no | bounded fixtures | Accepted through neutral checked handoff; persisted project consumption remains open. |
| R5 placement path | yes | no | reduced fixtures/micro-pilot only | Accepted bounded authority; no full unseen-board placement adoption. |
| R6 semantic/process evaluators | yes | no | bounded fixtures | Accepted bounded authority; no board has supplied and exercised every applicable declaration. |
| R7 thermometer | board-specific yes | yes for R005/R006 | no generic inference | Complete and accepted. It must not be rerun or used to claim generic adoption. |
| Phase 10 continuity/environment | repository work yes | daily task unknown | not applicable | Repository normalization is complete; the unidentified user-owned daily automation remains outside this audit. |
| Phase 11 evidence/assets/review | APIs and CLI yes | incomplete | no | Source intake, asset install, model preflight, raster adapters, and review package exist. Automatic early use by every board does not. |
| Phase 12 execution/test stewardship | subprocess runner yes | incomplete | no | Verification profiles work. The generic work ledger is not consumed by routers, and the failed board bypassed the runner. |
| Phase 13 pre-design intake | first slice yes | approval pending | Retro-Pad pre-design only | Structured normalization, geometry examination, overlays, and a hash-bound approval gate now exist. Capacity/routing transaction work remains open. |

## Concrete Phase 11/12 failure evidence

- `generate_visual_review_package()` had production code and tests, but the
  failed Retro-Pad generator requested only `stage="final"` after routing. It
  did not persist an unrouted placement PCB and review package first.
- `preflight_board_models()` and source-intake commands existed, but their use
  remained board/tool-specific rather than an automatic component-selection
  and project-stage contract.
- `WorkBudgetLedger` existed only in `execution.py` and its unit tests. The
  A-star, negotiated, and corridor engines have their own budgets and
  telemetry, but the generic execution profile did not bind or aggregate them
  for the Retro-Pad run.
- The failed board was repeatedly launched through the raw project generator,
  not through the observable execution orchestrator. A subprocess heartbeat
  cannot help when the caller does not use it.
- The project directory ended with a newer schematic/project beside an older
  PCB and review set. `INCOMPLETE.md` documented the mismatch afterward, but
  generation was not transactional.
- The quick verification profile omitted `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`;
  this audit corrected it.

## Phase 13 implementation delivered by this audit

- `project_brief.py` defines a strict versioned brief whose values carry
  source, original source text, and `explicit|derived|assumed|decision_required|conflict`
  resolution. Natural-language extraction remains a human/AI boundary; the
  deterministic normalizer does not pretend to infer arbitrary prose.
- `concept_review.py` checks supplied-outline containment against real KiCad
  footprint body, courtyard, pad, hole, rectangle, and aperture envelopes.
- The generated front/back engineering overlays use the agreed status colors
  and explicitly state the back-view mirror convention.
- `predesign_gate.py` binds an approval to the exact normalized-brief and
  concept-review hashes. The existing Retro-Pad generator now stops before any
  write or routing work while approval is pending or stale.
- The Retro-Pad pre-design result is correctly **blocked** by the four literal
  mounting holes. The inward symmetric holes are blue engineering proposals,
  not silently accepted replacements.

## Still open before implementation resumes

1. The user must review and resolve the mounting-hole conflict, physical 2x2
   key arrangement, USB top-edge semantics, heart anchor tolerance, and current
   limit semantics.
2. Add a fast pre-route capacity probe that reports failing nets and work
   counters before full staged routing.
3. Split project generation into immutable generation identities and atomic
   placement/routing/final stage promotion.
4. Make post-placement review generation mandatory in the common project
   workflow rather than relying on each board script.
5. Bind router-specific expansion/pass telemetry to the selected execution
   profile and persist per-stage checkpoints.
6. Prove the complete intake-to-final path on Retro-Pad after approval and on a
   second materially different unseen board before making it the default.
