# Phase 17-18 closure log — 2026-07-25

This log records implementation and verification performed during the Phase 17
and Phase 18 closure session. It is an execution record, not a substitute for
the roadmap acceptance gates or for human, fabricator, and assembler approval.

## Phase 17

### Connected canonical schematic review

`generate_connected_schematic_review` now exports a complete-project PDF plus
an explicit SVG and PDF for every root/hierarchical schematic page. It retains
the raw whole-project ERC and KiCad XML netlist, their exact hashes, and
canonical hashes with wall-clock/host-path instability removed. Every page and
electrical artifact is bound to the exact root schematic, KiCad version, and
one replay-checked manifest published atomically.

The exporter discovers page count from KiCad but re-exports every retained page
with an explicit page selector. Missing, duplicate, or non-contiguous pages,
missing outputs, unsafe paths, absent KiCad, and stale identities fail closed.
ERC findings remain visible and make the package not ready for review without
discarding the visual evidence.

Verification:

- three-page root/hierarchical unit fixture: passed;
- deliberate missing-page and ERC-failure fixtures: passed;
- CLI registration: passed;
- live KiCad 10.0.3 Retro-Pad 3x3 root-page SVG/PDF, whole-project PDF, ERC,
  and netlist export: passed with clean ERC.

### Retained routed-board release evidence

The routed-board release gate no longer accepts caller-supplied booleans for
exact-route acceptance, KiCad read-back, or netlist equivalence.

`RoutedBoardVerificationEvidence` now requires exactly one fingerprinted,
producer-identified record for each authority. Every record is bound to:

- the exact saved-board SHA-256;
- producer and tool-version identity;
- retained input SHA-256 identities;
- an explicit result code and limitations; and
- its own replay-checked fingerprint.

The bundle is also fingerprinted and must target the exact board inspected by
the release gate. Missing, duplicated, stale, wrong-board, or rejected evidence
fails closed. The CLI consumes the retained JSON bundle through
`--verification-evidence`; the former release booleans no longer exist.

Verification:

- focused Ruff format/check: passed;
- strict mypy for the changed production modules: passed;
- routed-board release-gate unit tests: 4 passed.

### Project applicability-to-execution coverage

`ProjectApplicabilityExecutionManifest` now distinguishes a repository check
from a check actually executed on one exact saved design. It binds every
declared check to rule IDs, applicability authority, exact input hashes,
producer/tool version, evaluated-object count, result hash, disposition, and
limitations.

The manifest fails closed for unresolved applicability, missing applicable
execution, unjustified zero-object execution, stale or conflicting inputs,
failed/unverified/blocked results, execution of a not-applicable check, and an
execution without a declaration. The routed-board release gate now requires a
ready same-board manifest. A CLI builder derives the saved-design hash directly
from the file and emits the replay-bound manifest.

Verification:

- focused Ruff format/check: passed;
- strict mypy for the changed production modules: passed;
- applicability/execution and routed-release tests: 11 passed.

### Operative placement and per-artifact rendering budgets

The shared production placement/review entry point now accepts only placement
and rendering bindings from one selected execution profile. The placement
producer receives a live `NativeStageController` and must account for at least
one pass and expansion. The review producer receives a separate rendering
controller and must account for at least one pass per emitted artifact.

Timeout, deterministic-work-budget exhaustion, missing accounting, callback
failure, and transaction failure all block publication. Placement and rendering
telemetry retain actual passes, expansions, heartbeats, termination, and
findings. The exact placement board and review package are committed only after
both stages complete.

This closes the shared production caller. The separate roadmap migration item
for legacy one-off board generators remains open until each generator is moved
behind the shared transaction.

Verification:

- focused Ruff format/check: passed;
- strict mypy for the production workflow: passed;
- production-workflow tests: 15 passed, including success and omitted
  per-artifact accounting.

### Typed review conventions

The supplied schematic/PCB review guidance now has a typed convention model
that separates release requirements, conditional electrical/layout guidance,
and presentation preferences. Each convention is source-span and
source-document bound and has explicit always, board-triggered,
space-conditional, or human-decision applicability.

Only an applicable release-class failure or unresolved required release check
can block release. A presentation preference cannot become a universal blocker,
and a dormant RF/antenna/high-current-style trigger cannot affect an unrelated
board. Exact saved-design check evidence is required for applicable execution.

Verification:

- focused Ruff format/check: passed;
- strict mypy: passed;
- convention applicability tests: 3 passed.

## Phase 18

### Manufacturing authority and neutral package

The first production slice is implemented:

- complete typed fabrication/electrical process profiles, including stack-up,
  impedance declarations, finish, insulation basis, and condition-specific
  IPC-2152 context;
- complete current-path coverage declarations for tracks, planes/zones, vias,
  pads, neck-downs, parallel sharing, and connectors, with voltage-drop,
  loss, waveform, duty, and thermal context;
- saved-board-derived stable identities for footprints, components, pads,
  holes, mask/paste apertures, BOM rows, and placement rows;
- complete ten-category DFM/DFT evidence/report contracts;
- an atomic manufacturer-neutral package with exact board/profile/identity/
  current-path/DFM/tool binding, content-recognition checks, artifact hashes,
  `SHA256SUMS`, manifest, and ZIP;
- version-pinned KiKit 1.8.0 and InteractiveHtmlBom 2.11.2 adapters that fail
  closed while the tools are unavailable; and
- guarded release language: package generation is not fabrication approval,
  fabrication readiness requires exact human-engineering and fabricator
  approvals, and assembly readiness additionally requires assembler approval.

Unknown conductor geometry remains unverified. A role label cannot disguise
arbitrary bytes as Gerber, Excellon, IPC-D-356, PDF, CSV, or HTML.

Verification:

- focused Ruff format/check: passed;
- strict mypy for both manufacturing modules: passed;
- manufacturing release tests: 9 passed, including deliberate invalid
  V-cut, version-mismatch, unknown-current-path, fake-Gerber, and approval
  failure cases.

The pinned tool runtime was then installed locally. Corrected headless
InteractiveHtmlBom execution and live KiCad neutral export succeeded on the
regular Retro-Pad 3x3 and irregular Retro-Pad R003 candidates. A first
InteractiveHtmlBom launcher caused a wxWidgets action-plugin assertion because
it omitted `INTERACTIVE_HTML_BOM_CLI_MODE`; the launcher now forces both CLI
mode and no-display mode and has a dedicated regression test.

Baseline DFM/DFT execution now automatically consumes exact saved-board
identities and KiCad DRC for courtyard/process clearance, checks SMD/paste
aperture coverage, checks explicit test-point identities, and reports every
unsupported category as unverified unless exact supplemental evidence is
retained. Unsupported thermal-via, panel-feature, probe-access, orientation,
assembly-sequence, or rework scopes cannot become green by omission.

KiKit generated both proof panels, but panel DRC rejected both. These failures
are retained as corrective evidence, not counted as completion.

Open acceptance work:

- correct panel configuration and pass panel-level DRC;
- complete current-path and unsupported DFM/DFT evidence for both boards;
- assemble and inspect the regular and irregular/cutout package manifests;
- collect actual human, fabricator, and assembler approvals only when a package
  is genuinely released.

## End-of-session closure classification

Neither phase is marked complete merely because its core machinery now works.
The remaining roadmap items have different owners:

| Phase | Remaining scope | Classification |
| --- | --- | --- |
| 17 | Automatic component-review invocation/recovery | production integration |
| 17 | Every legacy board generator behind shared transactions | migration |
| 17 | Protocol Analyzer R002 correction/routing | known failed-board repair |
| 17 | Complete R6/default path on a post-freeze unseen board | new user project evidence |
| 17 | Two complete package inspections | human visual acceptance |
| 17 | Multi-Channel, Freerouting, automatic CAD responsibility regions | trigger-dependent, not universally required |
| 18 | Regular and irregular panel DRC | failed proof requiring correction |
| 18 | Complete current-path and unsupported DFM/DFT evidence | board-specific engineering evidence |
| 18 | Neutral package reinspection on both proof boards | independent/human acceptance |
| 18 | Manufacturer adapter | dormant until a manufacturer is selected |
| 18 | Human/fabricator/assembler approval records | external release authority |

This classification prevents long-lead or externally owned evidence from being
confused with skipped implementation, while also preventing implemented schemas
from being mistaken for completed production proof.
