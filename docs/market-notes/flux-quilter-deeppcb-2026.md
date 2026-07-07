# Market notes: Flux.ai, Quilter, DeepPCB (2026-07)

Prompted by the user sharing Flux's "AI PCB Design - Quick Start Guide
for Flux Copilot" video (youtube.com/watch?v=yXfFjHd4TGA). Sources:
Flux docs/blog (docs.flux.ai/reference/copilot, "Copilot: Under the
Hood", "8 New AI Capabilities"), Quilter's 2026 autonomous-PCB
comparison, review aggregators.

## What Flux.ai actually is

A browser-based ECAD editor (schematic + layout) with an LLM copilot
riding alongside. The copilot:

- chats about the ACTIVE design (grounded in the schematic graph,
  netlist, part properties, editor selection) plus a 750K-part library
  with datasheets;
- has narrow @-tools: `@library` (part search), `@file` (datasheet
  Q&A), `@calculator`, `@code` (sandboxed Python), `@simulator`
  (SPICE), `@help`;
- can EDIT the schematic with user approval (add/remove parts, wire
  connections, rename designators);
- one-click artifacts: FMEA report, test plan, pin-function tables,
  component comparisons, mermaid block diagram, BOM passive
  consolidation, "find issues" scan.

Layout/routing: manual placement with AI-assisted routing after the
user places parts and routes critical signals. Their own docs:
auto-layout is "not designed to fully autoroute every class of board";
sweet spot 2-4 layers, 40-100 components. Spring 2026 added a
"self-correcting agent" and better auto-layout.

Their own framing of the frontier: **"The vision of Prompt -> PCB
remains aspirational"**; "expect to guide and verify every step";
hallucinations (wrong pin maps, wrong values) are acknowledged as the
core failure mode, mitigated by grounding and (planned) uncertainty
surfacing.

## The landscape (per Quilter's comparison, discount for bias)

- **Flux**: assistive copilot inside a full editor. Broad, chatty,
  human-in-the-loop everywhere.
- **Quilter**: autonomous PLACEMENT + ROUTING as a point solution on
  top of existing ECAD (Altium/KiCad/...), reinforcement learning
  grounded in circuit PHYSICS (field solvers, PDN/differential-pair
  validation), generates MULTIPLE candidate layouts with physics
  scorecards; demonstrated 843-part 8-layer boards. Their thesis: "the
  only way to automate layout at production quality is to reason from
  physics."
- **DeepPCB**: RL placement/routing with geometric-only DRC, credit
  pricing, up to ~1,000 components, no circuit-aware verification.

## Where PCBSmith sits (and why this is validating)

Nobody in this landscape does what PCBSmith does: **full
prompt->fabricable-PCB with no human in the loop, for a constrained
set of topologies, with machine-verifiable truth at every stage.**
Flux — VC-backed, 750K parts — calls that "aspirational" because they
attempt it GENERATIVELY per design, so hallucination is their
ever-present tax. PCBSmith compiles the intelligence into
deterministic code once per topology; at design time nothing is
generated, so nothing can hallucinate. Narrow-but-total automation vs
broad-but-assistive. Both are legitimate; ours is the empty quadrant.

Also validating: their aspirational "uncertainty surfacing" is our
SHIPPED evidence-status system (assumption / datasheet_fact /
needs_human_review). Their "junior engineer, verify everything"
posture is our needs_human_review cap.

Our honest gaps vs Flux: breadth (9 topologies vs any circuit),
interactivity, library scale (750K parts+datasheets vs ~30 curated
cards), and UI.

## What to adopt (ranked, mapped to our backlog)

1. **Checks-as-scorecard for the A\* router (plan 2.3)** - Quilter's
   lesson. Our router should generate CANDIDATE placements/routings
   and score them with what we already own: virtual DRC + design
   checks + trace-current + creepage as the fitness function, physics
   checks as gates not afterthoughts. We have the scorecard; we lack
   the candidate generator. This reframes 2.3 from "an autorouter"
   to "candidates + our existing verifier."
2. **Deterministic review artifacts** (Flux's most-loved features are
   cheap for us because our design data is structured):
   - **Test plan** (test-plan.md): from calculator outputs + TP
     positions + sim expectations ("probe TP1: ~160VDC; output
     3.3V +/-3%; opto LED 2-20mA...").
   - **FMEA-style table**: per component role -> failure mode ->
     effect -> which machine check or finding covers it.
   - **Pin-function tables** from component cards into the bundle.
   - **Mermaid block diagram** from topology roles/nets.
   All deterministic - no LLM needed, unlike Flux.
3. **BOM passive-consolidation lint**: flag near-identical passives
   with different values/footprints that could merge (their #1
   shortcut; trivial on our grouped BOM).
4. **@-tool architecture for our dormant LLM paths** (4.6 datasheet
   extraction, 4.7 local models): when we wire an LLM, copy the shape
   - narrow tools over structured data, LLM proposes, deterministic
   checks verify. We already own the verify half; Flux doesn't.
5. **Library scale is the moat to respect**: their 750K parts with
   datasheets is the real asset. Our onboarding CLI + cards +
   ingest-reference are the seed; live Nexar access (needs creds)
   is how it compounds.

## What NOT to copy

- Chat-in-the-editor as the core interaction: their users still do
  the engineering; the AI advises. Our contract is stronger.
- Generative schematic editing without a deterministic verifier
  behind it - that is exactly the hallucination tax we architected
  away.
