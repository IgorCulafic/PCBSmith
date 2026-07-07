# Survey: projects attempting prompt/code -> PCB (2026-07)

Follow-up to `flux-quilter-deeppcb-2026.md`. Question asked: who else
has tried what PCBSmith does? Answer: a whole family — and the
best-funded ones independently converged on OUR architecture
(LLM proposes code, deterministic compiler + checks verify).

## 1. Code-as-schematic open source (closest kin)

- **atopile** (YC, open source, github.com/atopile/atopile): a
  Python-inspired `.ato` DSL + COMPILER — "the compiler handles
  component selection, constraint validation, and KiCad project
  generation"; equations captured in the design; automatic parametric
  part picking; CI + JLCPCB ordering from the build. Deterministic
  compilation of design intent = our philosophy, generalized into a
  language instead of per-topology Python.
- **tscircuit** (MIT license, tscircuit.com): React/TypeScript
  components ("React for electronics"), rendering to
  schematic/PCB/3D; automatic part selection, AUTOROUTING, AI
  footprint generation; public demos of Codex driving it prompt->PCB.
  A registry of reusable circuit packages.
- **SKiDL** (devbisme): the veteran — Python circuit description,
  ERC, netlists, and (recently) KiCad schematic generation. The
  substrate PCBSchemaGen builds on.
- **Zener** (Diode Computers, MIT, github.com/diodeinc/pcb):
  Starlark-based schematic DSL + Rust compiler ("compiles schematics
  from code in milliseconds"), KiCad output. Explicitly inspired by
  atopile and tscircuit.

## 2. LLM-writes-code + deterministic verification (our architecture, funded)

- **Diode Computers** (YC S24, $11.4M a16z Series A): Claude writes
  Zener; deterministic tooling verifies — automatic SPICE (filter
  response, stability, power stages), static analysis (power paths,
  signal directionality, floating pins); simulation is "ground truth"
  because "models can sound confident about circuits that would never
  work"; a Registry of PROVEN reference modules Claude composes from
  (~250 modules drafted in two weeks); human sign-off retained.
  Business: design + manufacture as a service (robotics/medical/
  aerospace, US manufacturing angle). Customers: Physical
  Intelligence, Saronic.
- **JITX** (Sequoia Series A): requirements/stackup/SI targets ->
  design CODE the team inspects and compiles; AI edits the code while
  JITX generates schematics, dispatches HFSS simulations, runs
  checks. Claims 2.5-6x faster; Honeywell, Lockheed, OpenAI as users.

## 3. Requirements -> schematic/BOM SaaS (no full layout)

- **CELUS** and **Circuit Mind**: high-level requirements (even a
  whiteboard sketch) -> architecture, component selection, schematic,
  BOM, PCB floorplan into native EDA formats. LANL benchmarked a
  medium board: 60-80 h conventional vs ~4 h AI-assisted. They stop
  before layout/routing.

## 4. Academic (directly on-point)

- **PCBSchemaGen** (arxiv 2602.00510): OUR LOOP AS A PAPER.
  Training-free: LLM synthesizes SKiDL programs -> a deterministic
  5-LAYER REWARD ORACLE verifies (electrical invariants, pin-role
  compatibility from a 32-role datasheet-derived ontology, subcircuit
  templates, topology signatures via VF2 subgraph isomorphism, power
  invariants) with PIN-LEVEL ERROR LOCALIZATION -> Thompson-sampling
  bandit refines candidates. Benchmarks: PCBBench (62 tasks),
  Open-Schematics-Eval (165). Headline: **Gemma-4-31B reaches 81.3%
  pass** (+39pp over baseline) — a model we have ON DISK in
  ai_assets/models. Stated limits: ontology breadth, library scaling,
  reward-hacking surface.
- Analog siblings: AnalogCoder (LLM->PySpice code, feedback loop),
  LaMAGIC (fine-tuned power-converter synthesis), AMSnet/GENIE-ASI
  (netlist datasets/benchmarks), Schemato (netlist->schematic).

## 5. Practitioner consensus (eddiesamuels.com/blog/ai-pcbs)

Three camps: design-with-code (JITX/Diode/atopile/tscircuit),
chat-assist (Flux), blackbox autorouters (Quilter/DeepPCB). Schematic
capture is ~40% of design time and is where code generation shines.
KiCad's verbose s-expressions are the enemy of LLM effectiveness
(we agree — PCBSmith's answer is that no LLM ever touches board
files). Across ALL code platforms "you are still routing manually" —
routing remains the open frontier. The space "needs new ideas" and
rewards open, transparent tooling.

## Implications for PCBSmith

1. **We are independently converged-upon, not idiosyncratic.** Diode
   (a16z-funded, Anthropic-partnered) runs exactly our division of
   labor: LLM composes, deterministic compiler + simulation verify,
   human signs off. PCBSchemaGen proves it academically. Our
   difference: we are further along on VERIFICATION DEPTH (live
   kicad-cli DRC + parity, virtual DRC, isolation/creepage rules,
   golden regeneration) and further behind on breadth and library.
2. **The generality path is now clear** — the "new topology = new
   Python module" bottleneck is solved everywhere else by
   LLM-writes-the-code + verifier gates. Our plan 4.7 (local model
   harness) should become: LLM (even local Gemma-4-31B, per
   PCBSchemaGen's 81%) proposes a composition/exporter/board module;
   our existing findings with positions ARE the reward oracle with
   error localization; golden suite is the acceptance gate. The
   verifier is the hard part and WE ALREADY HAVE IT.
3. **Module/registry idea** (Diode Registry, atopile packages,
   tscircuit registry): our topologies + component cards are the seed
   of a proven-modules registry; compositions should become
   composable blocks rather than monoliths.
4. **Routing stays the frontier** (everyone routes manually; Quilter
   is the exception via physics-scored RL). Reinforces plan 2.3 as
   candidates + our checks-as-scorecard.
5. **Business patterns**: design+manufacture service (Diode), per-seat
   + credits (Flux), per-board (Quilter). Noted for later; not a
   current concern.
