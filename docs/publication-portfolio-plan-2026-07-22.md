# PCBSmith Publication Portfolio

## Revised conference-paper sequence and journal synthesis plan

**Status:** Working publication plan, 2026-07-22
**Scope:** Topics, contribution boundaries, evidence needs, and proposed publication order.
**Purpose:** Publish defensible parts of the research as they mature, then use those papers as concise foundations for a substantially expanded journal synthesis.

This plan supersedes the sequencing in `docs/paper-topics.pdf`. The older document remains useful historical brainstorming, but it predates the staged visual-review system, concept feasibility overlays, Retro-Pad failure and success evidence, 3D-model preflight, source-intake hardening, semantic PCB authorities, execution profiles, and the 2,597-case test-stewardship audit.

The portfolio is intentionally modular. Each conference paper owns one primary research question, one principal experiment, and one recognizable contribution. The later journal paper will not concatenate them. It will add the unified architecture, a larger longitudinal corpus, cross-paper analysis, expanded failure evidence, and an integrated account of how human judgment and deterministic authorities interact.

<!-- pagebreak -->

## Portfolio principles

1. **Publish measured slices, not promises.** A topic enters writing only after its central mechanism and evaluation artifacts exist.
2. **One paper, one principal question.** Shared boards and infrastructure are acceptable; duplicated research questions and duplicated primary tables are not.
3. **Separate generation from authority.** AI may propose, interpret, select, or revise. KiCad, simulation, geometric checks, evidence identities, and recorded human inspection remain explicit authorities for their scoped claims.
4. **Preserve failures and dead ends.** Failed sessions, rejected layouts, stale assumptions, false positives, and rule escapes are experimental evidence rather than material to hide.
5. **Do not overclaim generality.** The thermometer and Retro-Pad establish valuable case evidence. They do not alone prove universal autonomous PCB design.
6. **Instrument before comparing.** Time, tokens, retries, iterations, findings, human interventions, artifact identities, and verification outcomes must be recorded consistently before controlled experiments begin.
7. **Keep the journal paper standalone.** Conference papers may be cited for detailed algorithms and experiments, but the journal paper must still explain the complete method sufficiently for an independent reader.

## What materially changed since the earlier plan

- Concept images became a useful planning artifact, but are now separated from dimensionally authoritative feasibility overlays.
- Placement and final review packages are standardized, high resolution, layer-aware, tiled, and hash recorded.
- Rendering cannot approve itself; inspection decisions are explicit records.
- Missing, proxy, and misaligned 3D models now have a preflight and classification path.
- The failed thermometer and Retro-Pad sessions provide real evidence about late inspection, infeasible prompts, stale scale assumptions, and missing artifacts.
- Retro-Pad R002 provides a successful staged intake-to-final case with separate placement and final acceptance.
- The routing, placement, semantic, mask, execution, and evidence systems are considerably deeper, but many remain bounded authorities rather than universal defaults.
- Test volume has been audited: 2,597 collected cases came from 1,885 authored test functions, so paper claims must distinguish test cases, authored tests, and production checks.

<!-- pagebreak -->

## Proposed publication order

| Order | Working paper | Earliest responsible start | Main dependency | Relative effort |
|---|---|---|---|---|
| 1 | Render Before Route: Staged Visual Planning and Inspection | Soon | Complete review-artifact inventory and replay protocol | Low to moderate |
| 2 | Golden Regression and the Failure-Driven Verification Ratchet | Soon, parallel with Paper 1 | Complete catch and false-positive inventory | Low to moderate |
| 3 | Constraint-Guided AI Design Loops | After instrumentation | Clean ablation switches and isolated feedback conditions | Moderate |
| 4 | From Prompt to Feasible Board | After a second unseen intake case | Prompt variants, amendments, and feasibility outcomes | Moderate |
| 5 | Tool-Using AI under Hard Engineering Oracles | After benchmark freeze | Multi-condition harness, model budget, independent oracles | High |
| 6 | Evidence and CAD Asset Provenance for Generated Hardware | After exact-MPN discovery slice | Revision-role discovery and more onboarding cases | Moderate |
| 7 | Sound Pre-Filters for Expensive EDA Verification | After divergence corpus audit | Formal models and KiCad comparison corpus | Moderate |
| 8 | Safety- and Semantics-Aware PCB Routing | After external baselines | FreeRouting or comparable baseline and multi-board evaluation | High |
| 9 | Context-Gated Advanced PCB Intelligence | After several rule families are production-proven | Cross-board semantic-rule corpus and expert review | High |
| J | PCBSmith journal synthesis | After a defensible subset of conference results | Frozen architecture and expanded longitudinal evaluation | Very high |

Papers 1 and 2 are the most practical early submissions. Papers 3 and 4 should begin only after their experimental instrumentation is designed. Paper 5 is important but should not be rushed: its credibility depends on condition isolation, multiple models, independent scoring, and a frozen benchmark. Papers 8 and 9 mature with the engineering project rather than delaying the early publications.

<!-- pagebreak -->

## Paper 1 - Render Before Route

### Staged visual planning and inspection for human-in-the-loop PCB generation

**Primary question:** Does structured visual planning and staged inspection find consequential PCB-design defects earlier and reduce wasted downstream work compared with final-only rendering?

**Short description:** The method combines a spirit-preserving concept image with an engineering feasibility overlay, then requires separate placement and final review packages. The packages include high-resolution front and back views, layer-isolated renders, tiled details, declared electrical overlays, populated and bare-board 3D cameras, model-preflight status, artifact hashes, and recorded inspection decisions.

**Distinct contribution:** A reproducible visual-review protocol for generated engineering artifacts in which images are intermediate design evidence, not decoration and not self-approval.

**Existing evidence:**

- The thermometer effort shows the cost of omitted early renders, missing PCB artifacts, small parts hidden in full-board views, and silently absent 3D models.
- Retro-Pad R001 shows how insufficient feasibility review and mixed-stage artifacts waste implementation time.
- Retro-Pad R002 shows concept approval, separate placement review, a 35-artifact final package, model preflight, and explicit visual acceptance.

**Evaluation to prepare:** Replay historical defects under final-only, placement-plus-final, and full staged-review conditions. Measure detection stage, rework time, downstream computation wasted, accepted/rejected revisions, and defects invisible to ERC/DRC. Add seeded cases such as missing silkscreen, mirrored geometry, off-board pins, model-transform errors, cramped placement, and misleading whole-board scale. A small independent-reviewer study would strengthen the result; otherwise present it honestly as a structured case study.

**Image-generation ablation added 2026-07-23:** The reduced 8-channel
protocol-analyzer pre-design produced a useful four-condition experiment:

1. text/constraints only, with no planning image;
2. an unconstrained generated planning image;
3. a deterministic primitive/vector floorplan;
4. a generated planning image conditioned on the vector floorplan.

The exploratory examples show a plausible mechanism: unconstrained generation
communicates overall product intent quickly but can invent or reorder pins,
parts, and copper; the vector locks board geometry, connector population,
functional order, and approximate courtyards; the combined condition retains
more of that structure while adding presentation realism. The current examples
are case evidence, not a controlled comparison. A paper experiment must rerun
all four conditions from fresh contexts with the same brief, fixed model/tool
budgets, frozen outputs, blind scoring, and explicit geometry/topology-drift
metrics. The retained study and artifact inventory are in
`docs/paper1-vector-conditioned-image-study-2026-07-23.md`.

**Boundary:** This paper evaluates visual planning and inspection. It does not claim that image generation performs electrical verification or that attractive concept art is dimensional authority.

<!-- pagebreak -->

## Paper 2 - Golden Regression and the Failure-Driven Verification Ratchet

**Primary question:** How should a generative engineering system retain failures and convert recurring escapes into a tiered, maintainable regression system?

**Short description:** PCBSmith combines unit checks, semantic checks, virtual DRC, live KiCad authority, simulation, deterministic artifact identities, visual evidence, execution budgets, and full-board regeneration. This paper studies what each tier catches, what it cannot catch, how failures become permanent regression evidence, and how test growth is governed rather than celebrated as a raw number.

**Distinct contribution:** A stewardship method for regression testing when the generated artifact is an editable engineering design and correctness spans structure, geometry, simulation, fabrication, and human inspection.

**Existing evidence:** The repository has a retained test audit, several complete verification checkpoints, historical DRC escapes, false-positive repairs, stale board-specific assertions, a Hypothesis timing incident, and accepted failed-board evidence.

**Evaluation to prepare:** Enumerate every documented full-board catch and checker false positive; classify detection tier, defect family, runtime, and downstream cost avoided. Report authored tests separately from parameterized cases. Compare quick, standard, and deep verification profiles and identify redundant, stale, or harmful checks without reducing distinct failure coverage.

**Boundary:** This paper owns longitudinal regression and test stewardship. The formal underestimation properties of fast pre-filters belong to Paper 7, and AI-loop convergence belongs to Paper 3.

## Paper 3 - Constraint-Guided AI Design Loops

### Constraint systems as an efficiency mechanism for engineering agents

**Primary question:** When and how do explicit constraints, localized findings, bounded search, and typed failure states reduce iterations, tokens, wall time, and invalid downstream tool calls?

**Short description:** Instead of treating constraints as restrictions on creativity, the paper treats them as information that changes the search problem. It evaluates prompt normalization, feasibility gates, geometric constraints, semantic declarations, resource budgets, and verifier feedback at different stages of an AI-assisted design loop.

**Distinct contribution:** A measured account of constraint placement and feedback granularity: early versus late constraints, localized findings versus binary failure, bounded versus unbounded search, and staged promotion versus end-only verification.

**Evaluation to prepare:** Create isolated ablations over perturbed design tasks. Disable one constraint family without allowing its findings to leak through another evaluator. Compare no structured constraints, end-only authority, staged binary feedback, and staged localized feedback. Record iterations, tokens, tool invocations, time-to-valid-artifact, failure modes, and human interventions.

**Boundary:** This paper asks whether constraint architecture improves convergence and cost. It does not compare the factual utility of individual tools; that is Paper 5.

<!-- pagebreak -->

## Paper 4 - From Prompt to Feasible Board

### Spirit-preserving requirement refinement before PCB implementation

**Primary question:** Can a pre-design process expose impossible or underspecified PCB requests while preserving the user's product intent instead of silently rewriting it?

**Short description:** The method converts informal prompts and supplied images into a provenance-carrying brief, separates hard requirements from preferences and assumptions, produces a concept visualization, overlays exact footprint and board geometry, identifies conflicts, proposes explicit amendments, and binds approval to artifact hashes before placement or routing begins.

**Distinct contribution:** A mixed visual-formal contract between user intent and engineering feasibility, with explicit amendments rather than hidden specification drift.

**Existing evidence:** Retro-Pad exposed conflicting corner-hole and outline requirements, repeated board-size amendments, off-boundary pins, crowded components, silkscreen placement choices, and successful resolution through user-approved changes.

**Evaluation to prepare:** Use unseen prompts with controlled ambiguity and conflict classes. Compare raw implementation, text-only normalization, and normalization plus exact visual feasibility overlay. Measure conflicts found before implementation, unintended requirement changes, clarification burden, time wasted after routing starts, and user-rated preservation of design intent.

**Boundary:** This paper owns requirement interpretation and feasibility. Paper 1 begins once visual artifacts are used for staged design inspection.

## Paper 5 - Tool-Using AI under Hard Engineering Oracles

**Primary question:** Which tool-access patterns improve engineering correctness, reduce hallucination, and control cost when outcomes can be judged by independent deterministic authorities?

**Short description:** An AI agent may use document retrieval, evidence extraction, calculators, component and footprint discovery, geometry queries, KiCad generation, simulation, model preflight, and visual inspection support. The paper compares tool configurations while keeping the scoring oracle separate from the tools available to the agent.

**Distinct contribution:** A tool-use benchmark grounded in editable PCB artifacts and independent engineering outcomes rather than an LLM judge.

**Evaluation to prepare:** Freeze perturbed tasks and compare at least pure generation, bare code-writing, curated tools without verifier feedback, and curated tools with verifier feedback. Use fresh contexts and prevent artifact leakage. Run multiple models if making cross-model claims. Score exact component facts, valid topology, ERC/DRC, simulation criteria, fabrication checks, evidence identity, iterations, tokens, wall time, and unsupported assertions.

**Boundary:** This paper asks which tools and orchestration patterns improve correctness. Paper 3 asks how constraints and feedback affect convergence, even when the tool set is held constant.

<!-- pagebreak -->

## Paper 6 - Evidence and CAD Asset Provenance for Generated Hardware

**Primary question:** How can an automated hardware-design workflow acquire and use changing technical documents and CAD assets without silently accepting the wrong revision, package, license state, or 3D proxy?

**Short description:** The system combines approved-host retrieval, retries and telemetry, rights-aware local caching, payload identity, revision-role records, exact-part metadata, symbol and footprint validation, 3D-model classification, and public/private evidence projections.

**Distinct contribution:** A fail-closed evidence and asset supply chain connecting source identity to the exact downstream design decision it supports.

**Evaluation to prepare:** Exercise network failures, redirects, authentication, stale revisions, wrong document roles, corrupt archives, package mismatches, missing models, proxies, and incorrect model transforms. Measure correct rejection, recovery, cache reuse, provenance completeness, and false acceptance. Add several exact-MPN onboarding studies.

**Boundary:** This paper owns provenance and trustworthy acquisition. Tool-selection performance belongs to Paper 5; electrical rule correctness belongs to Paper 9.

## Paper 7 - Sound Pre-Filters for Expensive EDA Verification

**Primary question:** Can fast approximate engineering checks safely reject definite failures while leaving final acceptance to a slower authoritative EDA tool?

**Short description:** PCBSmith uses conservative geometric and structural models before KiCad round trips, while recording divergences and repairing consumers or models without falsely promoting the approximation to final authority.

**Distinct contribution:** Multiple formalized instances of an underestimating pre-filter plus external authority pattern, supported by an escape and repair taxonomy.

**Evaluation to prepare:** Construct a poisoned-board corpus and compare every pre-filter outcome with KiCad. Report runtime, definite-failure precision, missed defects, divergence categories, and repair history. Formalize the containment or underestimation argument separately for pads, courtyards, masks, silkscreen, copper, and connectivity where justified.

**Boundary:** This paper studies verifier architecture and approximation. Paper 2 studies regression stewardship across all verification tiers.

<!-- pagebreak -->

## Paper 8 - Safety- and Semantics-Aware PCB Routing

**Primary question:** How can routing and placement algorithms account for constraints that ordinary clearance optimization does not express, including creepage, isolation barriers, return paths, hot loops, antenna regions, ordered buses, and shaped-board capacity?

**Short description:** This paper family should begin narrowly. The first defensible version can focus on safety and isolation-aware routing; later work may expand to negotiated capacity, corridor exchange, ordered lanes, and semantic copper paths.

**Distinct contribution:** First-class semantic constraints in route construction plus independent post-route authority checks and retained failed candidates.

**Evaluation to prepare:** Compare against at least one external router on identical placements and netlists. Report completion, length, vias, runtime, determinism, safety violations, semantic violations, and human repair. Use multiple materially different boards and ablate each constraint mechanism.

**Boundary:** Do not combine every routing authority into one early paper. A narrow safety-routing paper is preferable to an unvalidated universal-router claim.

## Paper 9 - Context-Gated Advanced PCB Intelligence

**Primary question:** How can PCB design rules become executable without turning context-dependent engineering guidance into unsafe universal thresholds?

**Short description:** Rules carry applicability, source revision, authority, consumer, classification, required project context, and verification evidence. Initial families include decoupling-loop topology, connector-to-ESD ordering, oscillator evidence zones, switching hot-loop membership, and stack-up/reference continuity. Later families address PDN, DDR, SerDes, RF, thermal, isolation, HDI, reliability, and test planning.

**Distinct contribution:** A context-gated rule architecture that distinguishes hard, derived, advisory, and simulation-bound claims and refuses unsupported signoff.

**Evaluation to prepare:** Promote one family at a time and test it on materially different boards, exact device guidance, applicable standards, poisoned examples, and expert review. Measure true defects found, inappropriate activations, unresolved-context blocks, and cases requiring simulation or human judgment.

**Boundary:** This paper cannot be written credibly from the rule catalog alone. It requires production exercise and negative evidence across several rule families.

<!-- pagebreak -->

## Journal paper - PCBSmith as an evidence-backed, human-supervised engineering system

The journal paper should be the synthesis, not a compressed project diary and not a pasted collection of conference papers.

### Core journal contribution

A unified architecture for moving from informal intent to inspectable PCB artifacts through evidence-backed decisions, staged deterministic authorities, bounded search, provenance, visual-human gates, failure retention, and explicit limits on autonomous claims.

### Material that should be new in the journal version

- A substantially larger and more varied board corpus.
- One coherent architecture and terminology reconciled across the conference papers.
- Longitudinal analysis of failures, dead ends, interventions, check growth, runtime, and convergence.
- Cross-paper experiments connecting feasibility, constraints, tools, visual review, regression, provenance, and semantic rules.
- Expanded comparisons and ablations that were too large for individual conference papers.
- A taxonomy of what is machine-authoritative, evidence-authoritative, simulation-bound, advisory, or human-reviewed.
- Negative results and unresolved capability boundaries.
- A reproducibility package describing which artifacts can be distributed and which remain private for licensing or copyright reasons.

Conference papers may be cited for detailed algorithms and full experiment descriptions, allowing the journal to summarize those components concisely. Nevertheless, every method necessary to understand the journal's claims must remain intelligible inside the journal paper, and reuse must comply with the rules of the eventual venues and publisher.

<!-- pagebreak -->

## Shared experimental preparation for the next two weeks

Detailed experiment design can wait until the planned paper-focused period, but project instrumentation should preserve the data now.

### Record during ordinary development

- Stage start and finish times, retries, timeouts, and resource budgets.
- Prompt and normalized-brief identities, amendments, and approvals.
- Tool calls, tool results, model and configuration identity, token usage where available, and feedback shown to the agent.
- Every generated PCB, schematic, manifest, render, inspection decision, DRC/ERC report, simulation result, and relevant hash.
- Human corrections with stage, reason, affected artifact, and whether a machine check could reasonably have caught the issue.
- Failed candidates, dead ends, stale-test incidents, and recovery actions.
- Which exact rule, source, revision, and project context supported each promoted engineering claim.

### Design later, before running comparisons

- Frozen research questions and hypotheses.
- Independent variables, ablations, baselines, and contamination controls.
- A perturbed task corpus resistant to memorized solutions.
- Independent scoring authorities and adjudication rules.
- Sample-size and repeated-run rationale.
- Predeclared exclusions, failure handling, and stopping rules.
- A contribution-ownership matrix showing which figures, tables, and experiments belong to each paper.

## Immediate recommendation

Resume PCBSmith implementation after adopting this portfolio as a working map. Do not interrupt the engineering roadmap to manufacture paper results. Preserve structured evidence during development, then begin Paper 1 and Paper 2 preparation in parallel when the two-week writing and experiment-planning window begins. Instrument Paper 3 now, but run its ablations only after the conditions can be isolated cleanly. Keep Paper 5 behind a benchmark freeze and compute plan.
