# Phase 17-18 completion-readiness audit — 2026-07-25

## Outcome

Phase 18 is complete for the currently selected scope: manufacturer-neutral,
two-layer, non-impedance-controlled output generation. Its reusable authority,
panel adapters, neutral package, independent archive checks, and regular plus
irregular board proofs are implemented. This does not make either proof board
fabrication-ready; their manifests correctly remain blocked by missing
board-specific current-path and DFM/DFT evidence.

Phase 17 is not complete. Most shared contracts and production gates are
implemented, but two acceptance obligations cannot be replaced by more unit
tests:

1. retained legacy board generators still bypass the shared production
   transaction; and
2. the complete default path has not been proven on two materially different
   boards, including one whose prompt arrived after the implementation freeze.

Calling Phase 17 complete before both conditions are satisfied would repeat the
earlier mistake of treating available checks as proof that normal callers used
them.

## Phase 17 implemented foundation

The following shared capabilities are implemented and covered by focused
tests:

- exact-span prompt examination and no-invention handling;
- typed project contexts, spatial anchors, feasibility, and conflict
  alternatives;
- automatic placement review and routed-board release transactions;
- applicability-to-execution and component-review manifests;
- deterministic routing order, capacity diagnostics, bounded execution,
  telemetry, checkpoints, and transaction rollback;
- connected schematic review packages;
- exact-route, read-back, netlist-equivalence, DRC, and visual-review gates;
- saved/read-back R2, R4, and R5 compatibility proofs;
- controlled edge-interface authority; and
- deliberate ambiguity, capacity, asset, routing, review-omission, and
  rollback failures.

These are real reusable mechanisms. They are not yet proof that every
historical generator enters through them.

## Generator migration audit

The source inventory contains 18 board-generation entry points across 15
`src/pcbsmith/kicad/*board.py` modules. None of those modules directly invokes
`persist_routed_board_and_generate_review`,
`persist_placement_and_generate_review`, or
`run_production_placement_review`.

Eight normal CLI paths converge on the legacy `_finish_board_authority`
function. That function runs virtual DRC, KiCad DRC, previews, a review image,
and returns `needs_human_review`, but it does not create the Phase 17
transaction, applicability manifest, component-review execution, exact route
evidence, or one-generation artifact identity. The standalone scripts for the
Retro-Pad and BLDC ESC families also call board builders directly.

This is the principal code-migration blocker. The correct next implementation
slice is:

1. add one inventory/registration rule so a new board generator cannot appear
   without an explicit production-transaction or deliberately blocked
   placement-only classification;
2. replace `_finish_board_authority` with a production adapter that gathers the
   exact required evidence and calls the shared transaction;
3. move the standalone Retro-Pad routed candidates through that adapter;
4. keep BLDC ESC placement-only until its electrical, power, thermal, and
   mechanical inputs are selected; and
5. retain fail-closed compatibility adapters for historical outputs rather
   than silently promoting them.

## Cross-board proof blocker

The required proof is intentionally not satisfiable with another hard-coded
Retro-Pad rerun. Completion requires:

- two materially different prompt-to-final default-path executions;
- at least one prompt first seen after the implementation freeze;
- complete R6 declarations/evaluators bound to the saved/read-back identity;
- exact prompt, concept, schematic, routed board, execution, transaction, DRC,
  and review-package identities;
- full human visual inspection of both canonical review packages; and
- retained failures if the first candidate is infeasible or violates an
  applicable gate.

The next user-supplied board can satisfy the post-freeze half of this proof.
The corrected Protocol Analyzer may supply the second board, but it is not
mandatory if a different materially distinct board completes the same
evidence. Its existing rejected USB orientation, oversize placement, and
missing-routing history should remain in the failure corpus either way.

## Trigger-dependent items that do not block Phase 17

- KiCad Multi-Channel / Repeat Layout is evaluated only when a repeated-channel
  proof board triggers it.
- Freerouting remains an external candidate/oracle and has no release
  authority. Evaluation waits for a deliberate selection, pinning,
  deterministic benchmarks, cleanup, and KiCad revalidation.
- KiCad 11 PCB diff/merge waits for a stable or pinned release candidate.
- Supplier-CAD-derived edge responsibility regions and full 3D
  mating/enclosure proof belong to the Phase 19 mechanical authority.
- BLDC ESC routing remains blocked by missing selected power-stage, thermal,
  protection, heatsink, and current-path inputs. Preserving that blocked state
  is correct behavior, not unfinished routing.

## Phase 18 completion boundary

Completed current-scope evidence:

- typed fabrication/electrical and stack-up authority;
- full conductor-kind current-path records with fail-closed unknowns;
- saved-board manufacturing identities;
- ten-category DFM/DFT contracts;
- pinned KiCad 10.0.3, KiKit 1.8.0, and InteractiveHtmlBom 2.11.2 adapters;
- zero-finding regular mouse-bite, irregular mouse-bite, and regular V-cut
  panel proofs;
- schema-v2 neutral packages for regular R001 and irregular R003;
- independent ZIP/file-set/hash/source-binding/model reload checks;
- visual inspection of six final assembly and drill-map PDFs; and
- guarded human/fabricator/assembler release language.

Open work is either triggered capability expansion or per-board release
qualification:

- physical impedance coupons are required only after a selected stack-up has
  an impedance requirement;
- manufacturer-specific adapters remain dormant until a manufacturer is
  selected;
- R003's present ground pour must be corrected before that source board can use
  mouse-bite tabs;
- actual operating currents and exact conductor geometry must close the
  current-path records; and
- selected fabrication/assembly processes must close DFM/DFT and approval
  records.

Those open release records must not be converted to green placeholders merely
to make the phase heading look complete.

## Paper-use consequence

Phase 18 methods and failure progression can enter an evidence freeze now,
provided the papers describe structural package/panel proof rather than
fabrication readiness. Phase 17 workflow results can also be drafted, but any
claim about default-path adoption or generalization must wait for the generator
migration and post-freeze cross-board experiment.

## Verification checkpoint

- `uv lock --check`: passed;
- repository Ruff over `src`, `tests`, and `tools`: passed;
- strict mypy: passed across 381 source files;
- focused manufacturing-release tests: 17 passed;
- full warnings-as-errors pytest: 3,312 passed, 18 intentional skips, zero
  failures/errors; 3,330 total in 620.251 seconds; and
- documentation and patch whitespace check: passed.

Retained full-suite output:

- `.pcbsmith/verification/phase17-18/full-suite-2026-07-25-r1/pytest.stdout.txt`;
- `.pcbsmith/verification/phase17-18/full-suite-2026-07-25-r1/pytest.stderr.txt`;
  and
- `.pcbsmith/verification/phase17-18/full-suite-2026-07-25-r1/pytest.exit.txt`.
