# PCB Smith competitor and doctoral dossier audit - 2026-07-14

## Purpose and evidence boundary

This document audits the supplied 43-page `PCB Smith Competitive and Doctoral
Research Dossier` against current product documentation, public repositories,
official paper records, released benchmarks, and the implemented PCBSmith
architecture.

Evidence cutoff: **2026-07-14**. Product claims were desk-audited. Open
repositories were cloned and source-inspected at pinned commits, but the
competitor applications were not operated and no competitor-generated boards
were fabricated in this pass.

The supplied Markdown and PDF are consistent versions of the same dossier. The
PDF has 43 non-empty pages and about 99% normalized vocabulary coverage of the
Markdown. The files are suitable as a research brief.

## Executive verdict

The dossier's central conclusion survives, but the market is broader and the
academic evidence is weaker than its single-letter grades imply.

Credible systems exist at almost every layer: architecture/schematic synthesis,
circuit-as-code, EDA tool execution, placement, routing, verification, and
manufacturing export. Trace and Cherry Blossom make the clearest integrated
conversational claims. Circuit Mind, Quilter, Diode, JITX, Flux, CELUS,
tscircuit, atopile, SKiDL, circuit-synth, and KiCad control bridges each cover
substantial parts of the chain.

The unclosed public-evidence gap is:

> A reproducibly evaluated system that accepts broad hardware intent, grounds
> component and datasheet decisions, produces editable native schematics and
> manufacturable layouts, passes engine and domain checks, abstains safely when
> evidence is insufficient, and demonstrates reliability on an independently
> fabricated and bench-tested suite.

That is narrower than "few people are doing AI PCB design," but it is a much
stronger doctoral target.

The dossier is a research proposal, not the current implementation contract.
PCBSmith's canonical pipeline is deterministic with no LLM in the generated
design loop. The dossier's multi-agent synthesis/repair architecture should be
treated as an experimental comparison or offline authoring condition, not
silently substituted into the working project.

## Correct the evidence method

The dossier defines A/B/C/D, then uses undefined grades such as `A-`, `B+`, and
`A-/research`. One letter also conflates unrelated evidence dimensions. Replace
it with separate fields:

| Field | Suggested values |
|---|---|
| Product status | claimed / beta / released / service |
| Method visibility | marketing / documented / partial source / open source |
| Evaluation | none / vendor test / external report / peer reviewed / locally reproduced |
| Physical evidence | none / vendor fabricated / independent fabricated / bench tested |
| Coverage | requirements / schematic / placement / routing / manufacturing / test |
| Human input | copilot / constrained automation / engineering service / autonomous claim |
| Confidence | low / medium / high, with source and date |

A public repository proves implementation exists, not that its private AI makes
correct boards. A vendor-run fabrication challenge is stronger than screenshots
but is not independent replication. An arXiv benchmark is self-reported until
reproduced, even when code or data are released.

## Corrected product picture

| System | Evidence-backed capability | Important boundary | Disposition |
|---|---|---|---|
| Trace | KiCad 10 fork, AI-oriented formats, local typed tool execution, schematic/PCB operations, ERC/DRC and exports | Physical-design quality not independently evaluated; advanced features partly roadmap; public CLI is planned, not available | Closest visible integrated product; primary hands-on target |
| Cherry Blossom | Plain-English schematic/PCB/Gerber/BOM claims, downloadable beta, tscircuit ecosystem | Central app private; no neutral native-project/fabrication benchmark | Missing emerging direct competitor |
| Circuit Mind ACE | Structured requirements to candidate architecture, schematic, BOM, analyses and ECAD export | No PCB layout; LANL report records real errors and corrections | Strong external schematic review; reject absolute "error-free" claims |
| Quilter | Autonomous placement/routing from existing project, documented constraints and native/manufacturing outputs | Does not synthesize circuit; critical structures can need pre-work; Speedrun is company-run | Strong physical-design specialist, not end-to-end synthesis |
| Diode | Engineering service plus open Zener DSL/compiler/checking stack | Human engineers review and finish layout/manufacturing; project counts are company-reported | More transparent and technically substantial than dossier rating |
| JITX | Code-defined constraints spanning schematic, board structure, routing/pin assignment and simulation integration | Enterprise/code-first; performance mostly vendor-described | Important omitted generative-EDA baseline |
| Flux | Project-grounded, action-taking schematic copilot plus separate auto-layout | Official docs limit Copilot's PCB-position/trace understanding; work is stepwise and approval-driven | Capable copilot, not one-prompt autonomy |
| CELUS | Functional-block/component-to-schematic/BOM/export platform | Own terms call results machine-generated rough drafts not quality-checked by CELUS; no layout | Important Circuit Mind-adjacent baseline |
| Cadence Allegro X AI | Enterprise placement, power-plane and critical-net routing automation | Not unrestricted prompt-to-circuit synthesis | Required incumbent physical-design baseline |

Important claim corrections:

1. Trace's CLI page explicitly says the CLI is **in development**.
2. Trace's large commit count is mostly inherited KiCad history.
3. Trace docs and GitHub Releases disagreed about public 1.3 availability.
4. Quilter now documents native CAD and manufacturing deliverables.
5. Quilter Project Speedrun is meaningful vendor-run fabrication, not a neutral
   success rate.
6. Diode's public Zener stack makes it less opaque than the dossier states.
7. Konnect now documents 185 beta tools; tool count is action coverage, not
   design correctness.
8. GerberGPT's old placeholder-phone observation is stale. Its durable problem
   is inconsistent official statistics and absent inspectable validation.
9. Helektron now has founders, university/incubator support, product modes and
   pricing, but its core technical claims still lack inspectable evidence.
10. PCB Designer AI is not separately countable while its calls to action lead
    to Quilter and no distinct product evidence exists.

Watch but do not yet use as scientific baselines: IntelCAD.ai, Conductor,
Tracer, Ziro Designer, iOrchestra, PCBai, GerberGPT, and Helektron.

## Missing open infrastructure

The dossier mentions some of these only in passing, but they are central to the
implementation landscape:

- **atopile:** declarative electronics language/compiler with graph types,
  symbolic unit-aware constraints, validation, deterministic naming and
  incremental KiCad synchronization. Normal routing remains downstream.
- **tscircuit:** typed Circuit JSON interchange, deterministic render phases,
  pure validation transforms, routing interfaces and an active heuristic
  autorouter ecosystem.
- **SKiDL:** mature Python circuit capture, reuse, ERC and netlist generation;
  no general autonomous physical design.
- **circuit-synth:** model-facing circuit-as-code/KiCad framework; layout and
  routing normally continue in KiCad.
- **KiCAD MCP/Konnect:** extensive typed tool execution. The attached model or
  deterministic controller supplies design intelligence.
- **Diode Zener:** typed hardware DSL/compiler/checking and KiCad tooling; the
  public stack is only part of Diode's private registry and service.

These projects do not invalidate PCBSmith. They show that representation,
compiler, synchronization and tool-execution problems already have strong
partial solutions that should be learned from rather than reinvented blindly.

## What the open source actually teaches us

The strongest open projects were shallow-cloned under `tmp/competitor-repos/`
and inspected at pinned commits: atopile `619eda7f`; tscircuit `e302cb8f`
(core `892db46f`, Circuit JSON `ed97194c`, checks `2bb7afd6`, capacity router
`e39c542b`); Circuit-Synth `3aaff18c`; SKiDL `e19d9a6a`; KiCAD-MCP
`a4127c12`; Konnect `672fbb9e`; Diode Zener `788404f0`; and PCBSchemaGen v2
`e07c545f`. These were source inspections, not builds. All listed repositories
reported MIT licenses except Konnect, which is AGPL-3.0 and must not be copied
without a deliberate compatibility decision.

### Patterns worth adopting

1. **Staged, serializable compiler boundaries.** atopile separates parsing,
   graph AST, type linking, deferred operations, validation, and instantiated
   design. tscircuit defines ordered phases with downstream invalidation.
2. **Provenance embedded in the IR.** atopile carries source/file/chunk objects
   through instantiation and tracebacks. Every PCBSmith object and constraint
   should retain stable origin IDs and exact source spans.
3. **Typed definition graph before instantiated graph.** Validate child
   declarations, link endpoints and interfaces before materializing KiCad.
4. **Immutable/pass-oriented constraint transforms.** Produce auditable new
   states rather than mutating hidden shared state.
5. **Separate rich constraint IR from resolved interchange IR.** tscircuit's
   Circuit JSON is excellent for caches, diffs, fixtures and solver interfaces,
   but is not a symbolic constraint language.
6. **Diagnostics are data.** Diode and PCBSchemaGen retain code, severity,
   phase, component, pin, net, constraint, suggestion and fingerprint. Free text
   should be adapted into this schema, not used as the repair protocol.
7. **Asymmetric source/layout synchronization.** Diode treats netlist identity
   as source-authoritative while preserving placement, routing, zones and
   artwork as destination-authored complements, with idempotence laws.
8. **Owned-object tagging and incremental KiCad reconciliation.** atopile uses
   stable addresses/UUIDs and minimizes board mutation so human work survives.
9. **Backend/session pinning and optimistic concurrency.** KiCAD-MCP exposes
   backend identity and rejects overwrite after external change. Every patch
   should include its base artifact hash.
10. **Atomic observable execution.** Konnect records calls/errors and uses
    temp-file, flush, fsync and atomic rename. Combine this with semantic
    preconditions and artifact hashes.
11. **Solver-independent routing contract.** tscircuit normalizes outline,
    layers, clearances, obstacles, widths, terminals and vias into a portable
    routing problem. Use this boundary for A*, bus routing and FreeRouting.
12. **Region-scoped repair.** tscircuit replaces only declared reroute objects;
    Diode renames nets only on unique connectivity-signature matches.
13. **Deterministic naming and tie-breakers.** atopile tests frozen rebuilds for
    no layout changes. PCBSmith needs stable keys for every candidate and repair.
14. **Replayable solver failures.** tscircuit stores failing route inputs,
    immutable stages, snapshots and bug fixtures. Every router failure should
    become a permanent regression fixture.
15. **Layered semantic verification.** PCBSchemaGen progresses from electrical
    invariants through pin roles, IC templates, topology motifs and power
    domains. Extend this with evidence, simulation, physical and manufacturing
    layers rather than one scalar reward.

### Patterns not to copy blindly

- atopile's numerical solving/optimization remains work in progress, its type
  checks are not complete PCB semantics, and it has no general native router.
- tscircuit's global phase graph and fast-moving packages add async/version-skew
  risk; Circuit JSON lacks atopile-style source spans and symbolic constraints.
- tscircuit's heuristic router has excellent failure fixtures but substantial
  edge complexity; it is not a universal routing proof.
- circuit-synth, SKiDL, KiCAD-MCP and Konnect are infrastructure, not design
  intelligence or verification authority.
- Diode's full compiler is too large to adopt casually, and its physical layout
  work does not prove general routing optimization.
- PCBSchemaGen contains part/task/name-specific exceptions and documented
  false-positive workarounds. Convert useful rules into versioned declarative
  knowledge; do not copy benchmark special cases.

Additional integrated-product boundaries:

- Trace was inspected at `e48d9a7` (2026-05-11). It is a roughly 4,800-path
  snapshot on inherited KiCad parent `3ac37aa`; the 50,803-commit history is
  inherited. The small `trace/` AI/IR converter layer is explicitly All Rights
  Reserved and the hosted reasoning system is absent. Learn from the IR/tool
  boundary, but do not copy proprietary code or count inherited history as
  product validation.
- A PCBWorld repository could not be located during this audit despite the
  paper describing the environment as open source. Its 58-API environment and
  metrics can inform a future reproduction only when the artifact is available.
- Cherry Blossom's release repository was inspected at `e14e895`. Lightweight
  version tags point to the same README commit, while downloadable updater
  binaries do not provide public source provenance. Its public organization is
  chiefly tscircuit forks; the application and AI remain private.

The practical synthesis is: atopile-style provenance and staged typing;
tscircuit-style resolved IR, solver boundary and replayable local repair;
Diode-style diagnostics and layout synchronization laws; PCBSchemaGen-style
layered graph verification; and KiCad bridge patterns for backend pinning,
artifact hashes, observability and atomic writes.
## Academic evidence corrections

### pcbGPT

pcbGPT is an arXiv-only schematic-generation system, not an end-to-end board
system. It reports 20 tasks and 400 runs, uses an exact-match exemplar criterion,
and compares against a singular expert label. No public code was found during
this audit, and reported token use is large. Treat the scores as a self-reported
baseline requiring reproduction.

### SchGen

SchGen releases code/model/data and demonstrates that semantic operations beat
raw KiCad emission. The dossier's 82% number means executable output with zero
critical ERC, not functional correctness. Reported netlist Jaccard is 49.08%
and expert functional correctness 60.5%.

Its ICLR 2026 OpenReview entry is marked **Conference Desk Rejected
Submission**. The data split is also a research concern: random splitting after
fourfold augmentation can permit same-design family leakage. Use source-project
or design-family held-out splits when reproducing it.

### PCBSchemaGen

Pin this work to **arXiv:2602.00510v2, 17 June 2026**. Several indexes still
show v1. The v2 claims are real: six authors, 227 tasks across 22 domains, a
five-layer deterministic verifier, pin-localized feedback, a 32-role ontology,
bandit refinement, an 81.3% reported Gemma-4-31B PCBBench result, and a 5 kW
case study.

The paper explicitly excludes downstream schematic cleanup, PCB layout and
fabrication from its contribution. Its public repository releases benchmarks,
knowledge graphs and verifier material, but not a complete reproduction of the
LLM/bandit pipeline. The 5 kW case must not be summarized as autonomous
prompt-to-fabricated-board evidence.

### PCBWorld

PCBWorld is accepted at a KDD 2026 non-archival workshop and reports a KiCad
engine environment, 58 APIs, and 679 real boards. The headline corpus size
should not obscure the evaluated subset: main real-board experiments use 99
small and 10 medium boards. PPO beats FreeRouting on small clean pass
(0.86 vs 0.80) but loses on medium (0.45 vs 0.78); evaluated LLMs score 0.00.
Best-of-five rollout selection also matters. The defensible lesson is that
engine grounding helps, not that learned routing has surpassed mature routers.

### OmniLayout

OmniLayout reports 1,681 open-hardware, EAGLE-derived layouts and 77.24K
placement instances. It is placement-focused. Its "electrical functionality"
metric is based on relative spatial displacement against schematic/reference
relationships, not electrical simulation or bench verification. Qualify
"industrial-grade" and do not treat the benchmark as proof of function.

### 2026 GenAI PCB survey

The survey is a useful taxonomy, not current novelty evidence. Its search froze
on 2025-08-08 and therefore omits the important 2026 systems discussed here.

## Missing research baselines

| Work | Relevance |
|---|---|
| PCB-Bench, ICLR 2026 | About 3,700 text questions, 500 multimodal tasks and 174 projects; comprehension benchmark, not generation success |
| TypedSchematics | Typed reusable blocks, connection-error detection, composition, user study and three PCBs; highly relevant to Hardware Design Intent IR |
| PCB-QA | PCB-domain knowledge/comprehension; separates knowledge from execution |
| OmniSch, ECCV 2026 | Schematic image-to-graph/visual reasoning; useful for legacy import |
| PCBAgent, ASP-DAC 2025 | Agentic high-density placement baseline |
| Cypress, ISPD 2025 | Open PCB placement baseline |
| ModuPlace, DAC 2026 | LLM-derived placement constraint graphs |
| PCB-Migrator, DATE 2026 | Cross-board/design migration baseline |
| Smart-PCLib, DATE 2026 | PCB library/component intelligence baseline |

Check dataset licenses, redistribution rights, leakage, and source-project
splits before ingestion.

## Doctoral verdict

The doctorate remains viable if it claims a verified synthesis method and
reproducible evidence, not "the first AI that makes PCBs."

A defensible research question is:

> How can ambiguous hardware intent be compiled into sourceable, electrically
> and physically constrained PCB artifacts with machine-checkable provenance,
> calibrated abstention, localized repair, and reproducible physical
> evaluation?

Strong contribution candidates:

1. Typed Hardware Design Intent IR with requirements, interfaces, domains,
   pin roles, support obligations, sourcing, mechanical/physical constraints,
   uncertainty and provenance.
2. Datasheet/standard/manufacturer evidence compiled into versioned executable
   predicates with exact applicability and locators.
3. Verified schematic composition with localized failures and safe abstention.
4. Compilation of electrical semantics into placement/routing constraints.
5. Engine-grounded physical design using conventional optimization and routing.
6. A held-out, fabrication-based benchmark with a public failure ledger.

Avoid universal novelty claims. A desk audit cannot grant doctoral novelty;
that requires a systematic review and the university's examination process.

## Reconcile with deterministic PCBSmith

The repository currently requires no LLM in the design loop and caps clean
output at `needs_human_review`. The dossier proposes agents throughout the
pipeline. Treat these as different hypotheses:

1. Keep canonical generation deterministic.
2. Share the typed IR, provenance, obligation ledger, constraint graph, KiCad
   authority checks and benchmark across all variants.
3. Permit LLMs only as an offline authoring/research condition that proposes
   requirements, topology data or repairs.
4. Compile every proposal into the same IR and apply identical gates.
5. Compare deterministic composition, LLM proposals, retrieval-only and hybrid
   variants under frozen briefs and budgets.
6. Never let an experimental agent self-approve fabrication authority.

This turns the architectural disagreement into a useful experiment rather than
destabilizing the working project.

## Evaluation requirements

- Stage-separate requirement, component, schematic, physical, manufacturing and
  bench outcomes.
- Use obligation-based scoring that allows multiple valid circuits.
- Hold out source projects, component families and design families, not only
  random augmented examples.
- Preregister task suites, fixed tool/token/time budgets and failure policy.
- Run at least five stochastic seeds with confidence intervals where models are
  used.
- Mutation-test the verifier so high pass rates cannot come from a weak oracle.
- Compare direct LLM, RAG, IR, pcbGPT, PCBSchemaGen, SchGen, deterministic
  PCBSmith, Cypress, FreeRouting, PCBWorld, ModuPlace and human baselines where
  access permits.
- Fabricate a stratified subset and report CAM acceptance, assembly, first
  power, interfaces, rails, current, thermal behavior, fixes and cleanup time.
- Preserve failed attempts; do not report only best-of-many successful boards.

## Immediate priorities

1. Finish PCBSmith's current placement/routing roadmap. The thermometer failure
   is evidence that physical constraint solving, not more agent roles, is the
   current bottleneck.
2. Specify the shared Hardware Design Intent IR without adding an LLM runtime.
3. Add dated multidimensional competitor records and quarterly re-audits.
4. Reproduce selected open baselines before adopting headline scores.
5. Build a frozen benchmark before tuning the system to it.
6. Plan staged fabrication and publish the failure ledger.

## Primary sources

### Products and repositories

- [Trace documentation](https://docs.buildwithtrace.com/introduction)
- [Trace CLI status](https://docs.buildwithtrace.com/resources/cli)
- [Flux Copilot](https://www.flux.ai/Copilot)
- [Circuit Mind ACE](https://www.circuitmind.io/product)
- [Quilter](https://www.quilter.ai/)
- [Diode Zener repository](https://github.com/diodeinc/pcb)
- [KiCAD MCP Server](https://github.com/mixelpixx/KiCAD-MCP-Server)
- [Konnect](https://github.com/mixelpixx/Konnect)
- [atopile](https://github.com/atopile/atopile)
- [tscircuit](https://github.com/tscircuit/tscircuit)
- [SKiDL](https://github.com/devbisme/skidl)
- [Cherry Blossom](https://www.trycherryblossom.com/)

### Papers and benchmarks

- [pcbGPT](https://arxiv.org/abs/2606.01188)
- [SchGen](https://arxiv.org/abs/2605.30345)
- [SchGen OpenReview](https://openreview.net/forum?id=TyWs6rWWHb)
- [PCBSchemaGen v2](https://arxiv.org/abs/2602.00510v2)
- [PCBWorld](https://arxiv.org/abs/2607.05915)
- [OmniLayout](https://arxiv.org/abs/2607.03261)
- [PCB-Bench, ICLR 2026](https://iclr.cc/virtual/2026/poster/10009621)
- [TypedSchematics](https://arxiv.org/abs/2509.14576)
- [GenAI PCB survey](https://arxiv.org/abs/2606.17074)

## Bottom line

The dossier is a strong research brief after correction, not an implementation
handoff. The market is more advanced than it records, especially in circuit as
code, tool execution, structured schematic synthesis and specialist layout.
That raises the bar but does not close the public evidence gap.

PCBSmith's differentiator should remain verified, deterministic, evidence-aware
hardware synthesis with honest abstention and physical validation. Agentic
alternatives are worth studying, but should be measured against that system,
not assumed to be the architecture.
