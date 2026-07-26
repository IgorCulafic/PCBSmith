# Phase 17 generator migration — 2026-07-26

## Outcome

The repository now has one explicit, fail-closed publication boundary for
KiCad board generators. All 19 public board-builder entry points across 15
`src/pcbsmith/kicad/*board.py` modules are registered. A source-AST audit fails
when an entry point is added, removed, or renamed without a publication
decision.

This migration does not convert historical placement studies into routed
boards. Fifteen entry points are registered for placement publication only.
Four explicitly routed-capable entry points may attempt routed publication:

- Protocol Analyzer 8-channel routed board;
- Retro-Pad 3x3 routed board;
- original Retro-Pad routed board; and
- Retro-Pad R003 routed board.

The saved KiCad board remains authoritative. A routed-capable registration is
permission to attempt the routed transaction, not evidence that routing, DRC,
review, or release gates pass.

## Production commands

`pcbsmith production-generator-audit` reports the complete registry and exits
nonzero on an unregistered or stale entry.

`pcbsmith production-placement-review` now requires the exact
`module:entrypoint` generator ID. It commits the board, automatic component
review execution, project support files, and canonical placement review in one
immutable transaction.

`pcbsmith production-routed-review` requires a routed-capable generator ID. It
commits one byte-exact board with:

- retained KiCad project/schematic/rule/library/local-model support files;
- objective saved-board routing inventory;
- non-mutating KiCad JSON DRC;
- standardized final 2D, tiled, and 3D review artifacts;
- exact DRC and routing evidence; and
- one transaction identity and `CURRENT.json` pointer.

The transaction rejects:

- unknown generators;
- placement-only generators presented as routed;
- incomplete saved copper-carrier coverage;
- DRC violations, unconnected items, or schematic-parity findings;
- DRC callbacks that rewrite the board after routing inspection;
- support files that overwrite the board or transaction-owned evidence paths;
- review manifests for another board revision;
- final reviews without exact routing evidence; and
- review packages whose generation failed or whose workflow is nonconformant.

Legacy `design-*` commands remain fast compatibility builders. Their result now
states explicitly that it is not a Phase 17 production transaction and directs
the caller to the production commands. This preserves historical workflows
without silently promoting their output.

## Project-context defect found during migration

The first live isolated DRC attempt copied only the R003 board and reported 188
violations. A non-mutating DRC beside the original matching KiCad project
reported zero. The discrepancy was not a board regression: the isolated
transaction had omitted the matching `.kicad_pro` and schematic, so KiCad used
a different rule context.

The transaction contract now accepts hash-retained support payloads and writes
them beside the isolated board before DRC or rendering. CLI support files use:

`--support-file SOURCE=GENERATION_RELATIVE_PATH`

The matching project, schematic, local rule/library files, and `${KIPRJMOD}`
assets must be included. They are committed with the same generation, so later
replay does not depend on ambient project state.

## Review-publication defect found during migration

The first context-correct live review deliberately declared `fast_bus` and
`power_ground` overlays without supplying their images. The visual system
correctly marked the package `generation_failed` and `nonconformant`, but the
routed transaction still committed it. That was an early-boundary defect:
the later release gate would reject the package, but a failed package should
never become the current routed-review candidate.

Both placement and routed transactions now reject failed or nonconformant
review packages before publication. A regression test retains this failure.

## Live migration proof

Retro-Pad R003 was replayed through the corrected registered boundary with its
matching project, schematic, and two local 3D proxies. The retained temporary
proof is under:

`.tmp/phase17-generator-migration-smoke/transactions-r2/`

Observed result:

- registered generator:
  `pcbsmith.kicad.retro_pad_r003_board:generate_retro_pad_r003_routed_board`;
- transaction status: `committed`;
- transaction stage: `review`;
- KiCad DRC: clean;
- saved routing: 496 segments and 93 vias;
- review workflow: conformant;
- review package: `generated_pending_inspection`;
- missing required review artifacts: zero;
- committed artifacts: 52, including board and four support files.

This is a generator-migration smoke proof, not a new electrical or production
release of R003. Its reduced feature declaration does not replace the complete
project applicability-to-execution manifest, exact route/read-back/netlist
verification, human inspection, current-path evidence, DFM/DFT, or
manufacturing approvals.

## Next unseen-board production exercise

The next user prompt must exercise the complete path rather than stopping at a
good-looking routed board:

1. prompt examination, refinement, feasibility, and concept images;
2. registered generator and immutable placement transaction;
3. exact component obligations, schematic review, applicability execution,
   and routing-entry gate;
4. bounded deterministic routing with saved checkpoints;
5. registered routed transaction with exact project support, DRC, and complete
   standardized review package;
6. human inspection and exact route/read-back/netlist release gate;
7. Phase 18 neutral manufacturing export, current-path and DFM/DFT evidence,
   interactive BOM, drawings, placement, Gerber/drill/netlist artifacts, and
   archive verification; and
8. explicit status separation between package generated, fabrication ready,
   and assembly ready.

Phase 17 remains open until two materially different complete default-path
proofs exist, including the post-freeze unseen board. Phase 18 remains complete
for its manufacturer-neutral two-layer scope; the new board will be its first
joint end-to-end exercise through the migrated Phase 17 boundary.

## Verification checkpoint

The migration checkpoint passed:

- repository-wide Ruff;
- strict mypy over 382 production source files;
- 86 focused production-workflow, CLI, and Phase 18 manufacturing-release
  tests; and
- the full warnings-as-errors suite: 3,340 collected cases, zero
  failures/errors, exit 0 in 516.532 seconds.

Retained full-suite evidence:

- `.pcbsmith/verification/phase17-generator-migration-2026-07-26/pytest.stdout.txt`;
- `.pcbsmith/verification/phase17-generator-migration-2026-07-26/pytest.stderr.txt`;
- `.pcbsmith/verification/phase17-generator-migration-2026-07-26/pytest.exit.txt`;
  and
- `.pcbsmith/verification/phase17-generator-migration-2026-07-26/pytest.elapsed-seconds.txt`.
