# Roadmap open-item migration audit

Date: 2026-07-23

Status: scheduling authority for work migrated out of legacy Phases 0-15;
Phase 16 contract/consolidation completed 2026-07-23 and Phase 17 is next

The active roadmap now contains exactly 22 formal phases numbered 0 through 21.
Historical technical labels `R1`-`R7` remain aliases for Phases 1-7 because
they are embedded in code, tests, and dated evidence. Phase 8 is the R006 3D
asset onboarding pilot, and Phase 9 is the thermometer postmortem/workflow-
requirements closure.

## Purpose

The roadmap previously mixed completed bounded slices, long-running capability
tracks, optional product ideas, external dependencies, and unfinished
implementation under the same checkbox style. That made deliberate deferral
look like accidental omission and allowed later phases to begin without one
clear active queue.

This audit does not mark unfinished implementation complete. It removes
duplicate active checkboxes from historical phase records and assigns every
open item one of these dispositions:

- `P0 / Phase 16`: required authority consolidation and migration contracts;
- `P0 / Phase 17`: required production-workflow closure before another
  production-default board claim;
- `P1 / Phase 18-21`: required for the named later capability or release claim;
- `triggered`: implemented only when a board or product context requires it;
- `external`: cannot be completed from repository state alone;
- `standing rule`: continuing governance, not a finishable task.

## Legacy routing and visual-workflow items

| Origin | Previous open scope | Disposition | Destination |
| --- | --- | --- | --- |
| Phase 1 / R1 overall | Fabrication/electrical profiles, insulation context, IPC-2152 replacement data, exact geometry, stable identities | Split manufacturing implementation from identity migration | Phase 18 for manufacturing authority; Phase 16 for stable-identity contracts; Phase 17 for default-path integration |
| Phase 2 / R2.4 remainder | Serialized adversarial fixture, measured corpus, production/default caller migration | P0 | Phase 17 |
| Phase 4 / R4 production adoption | Persisted saved/read-back consumption and default caller migration | P0 | Phase 17 |
| Phase 5 / R5 production adoption | Full-template/fixed-neighbor preservation, persistence, equivalence, comparative proof | P0 | Phase 17 |
| Phase 6 / R6 production adoption | Complete board-specific declarations/evaluators on a materially different board | P0 | Phase 17 |
| Visual workflow | Automatic post-placement invocation before routing | P0 | Phase 17 |
| Visual workflow | Golden coverage for layers, scale, tiling, repeat hashes, missing models, and diagnostic overlays | P0 | Phase 17 |
| Visual workflow | Full-package inspected pilot and production-default promotion | P0 | Phase 17 |

Phase 0 itself remains complete within its frozen nine-source scope. The R1-R6
rows above were post-Phase-0 capability tracks placed nearby in the document;
they were not unfinished Phase 0 knowledge-base work.

## Phase 10-12 items

| Origin | Previous open scope | Disposition | Destination |
| --- | --- | --- | --- |
| Phase 10 | Audit the user-owned daily snapshot automation | External, non-blocking. No local Codex automation definition was visible on 2026-07-23. | External follow-up; requires exact task identity/location from the user |
| Phase 11 | Distill only claims with named consumers and acceptance evidence | Standing rule | Evidence governance; each concrete consumer is scheduled in its owning phase |
| Phase 11 | Optional rights-aware server-side evidence storage | Triggered product option | Unscheduled until a server/service architecture is selected |
| Phase 12 | Bind execution profiles and work ledgers to native board-algorithm budgets/telemetry | P0 | Phase 17 |
| Phase 12 | Investigate the 2026-07-20 Hypothesis slow-input incident | P0 reliability closure; later green runs do not establish cause | Phase 16 |
| Phase 12 | Apply R2-R6 plus Phase 11/12 workflow to a genuinely unseen board | P0 acceptance gate | Phase 17 |

## Phase 13 generalization items

All of these are required Phase 17 production-workflow closure. They are not optional
enhancements because they prevent ambiguity, stale mixed outputs, or repeated
late-stage failure.

| Previous open scope | Priority | Destination |
| --- | --- | --- |
| First-class interface, firmware-limit, assembly-process, and acceptance-gate records | P0 | Phase 17 |
| Prompt-to-structured-draft examiner/refiner with retained source spans | P0 | Phase 17 |
| Usable-region/neck capacity, mating access, keepouts, and routing envelopes | P0 | Phase 17 |
| Typed deviation consequences and multiple spirit-preserving alternatives for hard conflicts | P0 | Phase 17 |
| Schematic/PCB drift checks against the approved concept | P0 | Phase 17 |
| Typed edge, center, spacing, tolerance, access, and aperture anchors | P0 | Phase 17 |
| Generic pre-route capacity gate and compact failing-net diagnostics | P0 | Phase 17 |
| Transactional generation with incomplete-state identity and no mixed revisions | P0 | Phase 17 |
| Second materially different prompt-to-final proof | P0 acceptance | Phase 17 |
| Repository-owned deterministic router ordering and resumable route-domain checkpoints | P0 | Phase 17 |

## Phase 14 items

| Previous open scope | Disposition | Destination |
| --- | --- | --- |
| Live exact-MPN multi-role provider adapters beyond datasheets | Triggered/external: terms, credentials, cache rights, and exact-asset validation are prerequisites | Phase 17 only for one approved provider/board need; broader provider breadth remains triggered |
| Remaining fabricator, assembly, environment, safety, power-sequencing, interface/timing, and validation contexts | Split contract from implementation | Phase 16 defines the typed context contract; Phase 17 completes default-path population |
| Reconcile every promoted rule against exact guides/standards with applicability and evidence | Standing gate plus P0 exercise | Phase 16 shared promotion gate; repeated in owning phases |
| Impedance, IBIS/S-parameter, PDN, power-transient, and thermal/airflow analysis | P1, context-triggered | Phase 20 |
| Stack-up, return-current, power-domain, thermal/current-density, high-speed, BGA, and DFM diagnostic views | P0 for the common extensible framework; board-specific views remain triggered | Phase 17 framework; Phase 18/20 consumers |
| Cross-board proof and retained failure evidence for promoted rules | Split workflow acceptance from release qualification | Phase 17 workflow proof; additional Phase 21 release corpus |

Parent Phase 14 boxes were previously left open while their first child slices
were checked. The parent/child state was honest but visually ambiguous; the
active work is now scheduled only at the destinations above.

## Phase 15 items

| Previous open scope | Disposition | Destination |
| --- | --- | --- |
| Complete conduction, switching, dead-time, recovery, avalanche, copper, capacitor, connector, and cable loss/stress ledger | P1 engineering analysis | Phase 20 |
| Obtain a determinate one-phase electrothermal solution with bounded package/TIM/PCB/sink/ambient inputs | P1; foundation already exists, old "implement" wording was stale | Phase 20 |
| Extend to shared three-phase sink and exact cooling assembly | P1 | Phase 20 |
| Quantitative fault-energy, TVS/fuse/SOA, reverse-polarity, and shutdown coordination | P1 | Phase 20 |
| Measurement and model-correlation plan | P1 release prerequisite | Phase 21 |
| PDN/control, EMC/common-mode, structural, reliability/life, and manufacturing-corner adapters | Triggered P1 | Phase 20 analysis; Phase 21 correlation/release |

Phase 15 is complete only as a foundation slice. It does not establish thermal,
current, protection, lifetime, EMC, or release adequacy.

## Tooling-backlog migration

| Tool/capability | Destination | Adoption rule |
| --- | --- | --- |
| KiCad Multi-Channel / Repeat Layout | Phase 17 | Evaluate only on a repeated-channel board; preserve identity and post-copy DRC |
| Freerouting | Phase 17 | External candidate/oracle only until pinned, deterministic, benchmarked, and revalidated |
| KiKit | Phase 18 | Reproducible panelization/manufacturing packaging after single-board outputs are authoritative |
| InteractiveHtmlBom | Phase 18 | Assembly/review artifact generated from canonical board/BOM identity |
| Manufacturer fabrication adapters | Phase 18 | Optional adapters with golden side/rotation/part-mapping fixtures |
| Official `kicad-python` IPC API | Phase 19 | Interactive inspection/repair companion; never replace file generation or `kicad-cli` |
| KiCad StepUp / FreeCAD | Phase 19 | MCAD exchange only after KiCad 10 compatibility and deterministic export are proven |
| Structured ngspice harness | Phase 20 | Batch-mode authority first, with exact netlist/model/tool/result hashes |
| ngspice shared library | Phase 20 | Optional process-isolated optimization; batch remains fallback/oracle |
| Qucs-S | Phase 20 | Optional developer frontend, not production authority |
| XSPICE | Phase 20 | Triggered by mixed-signal model need |
| OpenVAF/OSDI | Phase 20 | Triggered by licensed Verilog-A model need with full ABI/tool provenance |

## Sequencing decision

1. Phase 16 consolidates workflow authority and freezes the migration contracts
   consumed by the production path.
2. Phase 17 closes the production workflow and proves its default path on
   materially different boards.
3. Phase 18 builds manufacturing and assembly outputs on that stable workflow.
4. Phase 19 adds MCAD/mechanical exchange and deterministic physical checks.
5. Phase 20 adds advanced electrical, thermal, protection, EMC, and simulation
   authority.
6. Phase 21 correlates models to measurements and governs release claims.

No later phase may retroactively claim an earlier foundation complete. Triggered
tools remain optional until their applicability and acceptance fixtures exist.
