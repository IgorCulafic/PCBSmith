# Phase 16 workflow authority and migration contract

Date: 2026-07-23

Status: frozen contract v1; implementation authority is
`src/pcbsmith/workflow_authority.py`

This document records the consolidation boundary between the accepted bounded
Phase 1-15 work and the production-workflow implementation scheduled in Phase
17. It does not promote a callable library or historical board generator to a
production-default workflow.

## Frozen identities

- Phase 17 migration-contract version: `1`
- Canonical authority-registry fingerprint:
  `abda6f84ece542f90de2702ee7e9fa1169916fcfdf6d493396b11dd58c5acc93`
- Phase 1-15 capability-map fingerprint:
  `12d7b8a773d5ad23f80e57aaa31b4ecb7236efd16d04260182a0e779acf7f87e`

The fingerprints cover semantic content, not source-file bytes. A material
contract change requires a new version and an explicit compatibility decision;
editing a constant until a stale test turns green is prohibited.

## Workflow state machine

The only successful stage order is:

1. `raw_prompt`
2. `normalized_brief`
3. `concept_approval`
4. `schematic`
5. `placement`
6. `routing`
7. `review`
8. `verification`
9. `manufacturing_handoff`

Any active stage may enter an explicit `incomplete` or `failed` state without
changing stages. A failed state is terminal. An incomplete state may resume
only at the same stage and only with a retained checkpoint identity. Stage
bypass is invalid. `complete` is valid only at manufacturing handoff.

Every state is replay-bound to its predecessor and an identity ledger. The
ledger distinguishes raw-prompt, object, generation, brief, concept,
schematic, board, route, evidence, review, verification, and manufacturing
identities. Each downstream identity retains the exact upstream digest it
consumed. Replacing an upstream identity transitively invalidates downstream
identities; retaining an old route or review after a board change is rejected.

Phase 17 will implement transactions, budgets, and normal callers against this
state machine. Phase 16 defines the contract only.

## Shared project context

Every project context declares each category exactly once:

| Category | Scope |
| --- | --- |
| `interfaces` | External electrical/data interfaces, connectors, and mating behavior |
| `firmware_limits` | Firmware-controlled limits, modes, timing, and safety dependencies |
| `assembly` | Assembly sequence, process, side, accessibility, and rework constraints |
| `environment` | Temperature, humidity, contamination, altitude, airflow, and enclosure conditions |
| `safety_protection` | Hazards, fault behavior, protection, isolation, and release restrictions |
| `power_sequencing` | Rails, startup/shutdown, transients, regeneration, and sequencing |
| `timing_signals` | Frequency, edge rate, skew, jitter, impedance, and signal-class context |
| `validation` | Required calculation, simulation, measurement, and human-review evidence |
| `fabricator` | Stack-up, material, geometry, and process capabilities |
| `exact_part_evidence` | Exact MPNs, revisions, documents, footprints, models, and evidence |

Each record is explicitly `resolved`, `unresolved`, or `not_applicable`.
Resolved records require a payload identity and source bindings. Unresolved
records retain named missing inputs. Not-applicable records cannot quietly
carry partial authority. This prevents an absent context from being interpreted
as permission.

## Applicability protocol

An authority is `always`, `board_triggered`, `external`, or
`human_decision`. Its result is one of:

- `applicable`
- `not_applicable`
- `unresolved`
- `blocked_external`
- `blocked_human`
- `deprecated`

Only `applicable` authorizes the authority itself. No other disposition can
authorize a replacement or guessed substitute. In particular, unavailable
credentials, provider terms, or cache rights produce `blocked_external`; they
do not authorize a generic part, copied CAD model, or unsourced rule. Missing
human approval produces `blocked_human`, not an automated approval.

## Canonical Phase 1-15 capability map

| Origin | Capability | Canonical owner | Principal authority | Phase 17+ consumer | Retained limitation |
| ---: | --- | --- | --- | --- | --- |
| 1 | Fabrication/electrical profile | `pcbsmith.rule_profiles` | `fabrication.profile` | project context; Phase 18 manufacturing | Manufacturing breadth remains Phase 18 |
| 2 | Negotiated routing | `pcbsmith.kicad.group_negotiation` | `routing.negotiated` | routing | Not yet the default caller |
| 3 | Shaped corridor capacity | `pcbsmith.corridor_allocator` | `routing.corridor` | feasibility and routing | Guidance is not physical routability proof |
| 4 | Ordered bus routing | `pcbsmith.kicad.bus_integration` | `routing.ordered-bus` | routing | Saved/read-back adoption remains Phase 17 |
| 5 | Exact placement acceptance | `pcbsmith.kicad.placement_pilot_acceptance` | `placement.exact` | placement | Bounded pilots are not broad search proof |
| 6 | Semantic/process evaluation | `pcbsmith.semantic_ir` | `layout.semantic-process` | review; Phase 18 DFM | Applicability is declaration-scoped |
| 7 | Saved-board KiCad authority | `pcbsmith.kicad.validate` | `kicad.saved-board` | verification | R005 proves one accepted board, not generic workflow |
| 8 | 3D asset preflight | `pcbsmith.kicad.model_preflight` | `assets.model-preflight` | review; Phase 19 MCAD | Proxies are not fit or procurement evidence |
| 9 | Workflow requirements | `pcbsmith.workflow_conformance` | `workflow.conformance` | workflow gate | Callable conformance is not automatic invocation |
| 10 | Environment continuity | `pcbsmith.execution` | `environment.execution-baseline` | repository verification | User snapshot automation is external |
| 11 | Evidence/assets/review | source intake and visual-package owners | source, asset, and review authorities | evidence and review | Automatic production invocation remains Phase 17 |
| 12 | Execution/test health | `pcbsmith.execution` and stewardship audit | budgets and test ownership | execution and maintenance | Native algorithm budget binding remains Phase 17 |
| 13 | Project intake | `pcbsmith.project_brief` and `pcbsmith.predesign_gate` | brief and feasibility authorities | examiner and concept | Examiner and typed anchors remain Phase 17 |
| 14 | Engineering applicability | `pcbsmith.project_engineering_gate` | project gate plus five promoted families | review; Phase 20 analysis | Families remain narrow and input-completeness bounded |
| 15 | Workflow/multi-physics foundation | BLDC engineering and conformance owners | multi-physics foundation | Phases 20-21 | Exact physical inputs and correlation remain absent |

The machine-readable map contains the exact schemas, callers, tests, artifacts,
evidence requirements, and limitations. It covers every integer phase from 1
through 15 and rejects missing or duplicate capability identities.

## Duplicate-authority disposition

The audit distinguishes genuine duplicates from layered checks:

- `virtual_drc`, semantic design checks, and KiCad CLI DRC are not duplicates.
  They are respectively an underestimating early screen, design-intent policy,
  and saved-file tool authority.
- The project engineering gate does not replace the five Phase 14 evaluators;
  it derives applicability and composes their replay-valid results.
- Local fingerprint helpers remain implementation details of their existing
  evidence. The workflow identity ledger wraps them without rewriting or
  invalidating historical fingerprints.
- Per-topology generators remain data/compatibility surfaces. They are not
  alternate workflow authorities.

Three former authority-like shortcuts are formally deprecated:

| Deprecated identity | Replacement | Reason |
| --- | --- | --- |
| `legacy.review.preview-images` | `review.visual-package` | Ad-hoc images lack canonical manifest and inspection identity |
| `legacy.workflow.directory-existence` | `workflow.conformance` | Filesystem presence is not semantic workflow evidence |
| `legacy.routing.process-order` | `routing.negotiated` | Process/hash order is not a repository-stable routing contract |

The authority registry rejects two active owners for the same semantic scope.
A deprecated identity must name an active replacement with the same scope and
can never satisfy applicability.

## Compatibility adapters

The old authority-command family is preserved as a partial adapter. It lacks
normalized-brief, approved-concept, and transaction-wide identities and
therefore cannot claim Phase 17 verification coverage.

The accepted Retro-Pad R002 path has enough retained identities to describe its
bounded verification result, but its adapter records missing default execution
orchestration, transactional rollback, and route-domain checkpoints. Preserving
that evidence does not make it the future normal caller.

Compatibility adapters may expose only identities at or below their declared
stage. They cannot fill missing identities with filenames or inferred values.

## Test/check stewardship decisions

The Phase 16 audit upgrades the inventory to schema
`pcbsmith-test-check-stewardship-audit-v2`:

- measured JUnit runtimes can be attributed to tests and files;
- numeric coordinate/scale pins are separated from budget pins;
- production checks receive a canonical shared owner or an explicit
  `module-local` owner;
- lexical caller coverage is reported as triage evidence, not proof;
- Pydantic framework validators are distinguished from public entrypoints.

Coordinate and scale assertions are not deleted by age. The reviewed leading
groups cover exact physical transforms, mask/aperture geometry, KiCad
conventions, accepted pilot boundaries, and render scale. They remain valid
semantic or replay boundaries. Board-specific absolute coordinates remain
inside bounded board tests/adapters and do not become shared authority.
Incidental ordering or formatting pins may be replaced only when a failing
change demonstrates that they do not protect identity, geometry, capacity, or
evidence.

## Hypothesis incident disposition

The 2026-07-20 failure reported 1.27 seconds of Hypothesis draw time after two
valid examples in `test_point_add_sub_inverse`. The strategy is four independent
bounded integers with no filtering, composite strategy, recursion, external
I/O, or test-data construction during draws.

Phase 16 measurements on Python 3.12.12 and Hypothesis 6.156.6 found:

- 100 valid examples in 0.09 seconds in-process;
- typical example and draw time below 1 ms;
- zero invalid or filtered examples;
- 50 isolated pytest processes passed;
- process wall time ranged from 0.654 to 1.036 seconds;
- the `.hypothesis` directory currently has writable inherited ACLs.

Hypothesis measures draw time with wall-clock timing and explicitly disables
the slow-generation health check for overlapping threads because scheduling
may pause a thread arbitrarily. The historical signature—two trivial valid
draws consuming 1.27 seconds, followed by exact-seed and later full-suite
success—is therefore a transient host scheduling/preemption stall during a
draw, not slow strategy construction or a geometry defect. The original run
did not retain per-test/JUnit timing, so the competing host process cannot be
identified retrospectively.

The health check remains enabled. No suppression, deadline widening, or test
weakening is justified. Future full checkpoints retain JUnit runtime evidence,
allowing recurrence to be correlated with file/test timing and machine
telemetry instead of being diagnosed from one terminal message.

## Phase 17 entry conditions

Phase 17 may begin only after:

- the registry and capability-map fingerprints pass their architecture tests;
- ordered transitions, failure/resume behavior, identity invalidation,
  applicability, external/human blocking, duplicate-owner rejection, and
  adapter limits pass;
- focused and full repository gates are green;
- the Phase 16 completion audit and current-state/roadmap records agree.
