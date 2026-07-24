# PCBSmith live handoff bootstrap

This is intentionally short. Volatile implementation history does not belong
in a copied prompt that silently ages into false authority.

## Required reading order

1. `CLAUDE.md` — stable engineering laws, environment, and workflow.
2. `docs/current-state.md` — the dated current acceptance boundary and active
   work.
3. `docs/routing-placement-plan.md` — the active numbered roadmap and completion
   ledger.
4. `docs/lessons-and-pitfalls.md` — failure classes and durable corrections.
5. `docs/architecture.md` and `docs/pcb-design-rules.md` — system boundaries and
   enforced design policy.
6. For source-dependent work,
   `docs/reference/current-materials-knowledge-base-2026-07-14.md`,
   `docs/reference/books/LOCAL-SOURCE-INVENTORY-2026-07-18.md`, and
   `docs/evidence-acquisition-and-utilization-guide.md`.
7. For the implemented Phase 11/12 commands,
   `docs/evidence-assets-review-execution-guide.md`.
8. Before any new board work, `docs/project-intake-and-concept-review-guide.md`
   and `docs/roadmap-implementation-audit-2026-07-20.md`.

Documents under `docs/archive/` and files explicitly labelled historical or
superseded are context only. They never outrank current code, retained
verification evidence, the active roadmap, or the dated current-state record.

## Immediate operating rules

- The thermometer project is complete and accepted as the R005 routed
  proof-of-concept. R006 is a 3D visualization pilot. Do not reroute or
  retrofit the thermometer merely to prove newer generic machinery.
- Retro-Pad is the current unseen project. Its first route attempt failed and
  its Phase 13 pre-design review is blocked by the literal mounting-hole
  conflict. Do not resume schematic/PCB generation before explicit user
  approval of the normalized concept decisions.
- Preserve completed roadmap scopes. Add new work under the next sequential
  phase; attach dated errata when evidence invalidates an older completion
  claim.
- Keep copyrighted books and licensed standards local. Commit only permitted
  metadata, hashes, short locators, paraphrased derived facts, applicability,
  and implementation status.
- Use focused gates during iteration and one full regression at a checkpoint.
  Never describe a snapshot commit as accepted unless its recorded gates pass.
- A callable library is not production adoption. Confirm that the normal board
  caller invokes each required placement, review, budget, and verification
  stage before checking off workflow integration.
- KiCad remains the saved-board/ERC/DRC authority; visual inspection and user
  review remain separate required evidence where applicable.

## Historical preservation

The previous long handoff is preserved verbatim, with an archival warning, at
`docs/archive/handoffs/handoff-prompt-2026-07-18.md`. Consult it only when
recovering historical rationale that is absent from current documents.
