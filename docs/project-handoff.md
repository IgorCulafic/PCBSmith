# PCBSmith Project Handoff

This file exists so a future Codex chat can resume PCBSmith without relying on
compressed conversation memory.

## Current Direction

PCBSmith is a free, open-source KiCad-first AI companion for PCB design. It does
not replace KiCad. KiCad remains the source of truth for schematic, PCB, ERC,
DRC, Gerbers, drill files, 3D/library workflows, and fabrication exports.

PCBSmith owns:

- structured user intent;
- AI planning and command proposals;
- review and approval bundles;
- AI context packages;
- component/library indexing;
- circuit rules and safety checks;
- deterministic generators for useful examples;
- fabrication-profile helpers such as laser-oriented copper SVG.
- separated generators for silkscreen/artwork and physical board-outline
  geometry.

## Key Principle

The goal is not to make the model know PCB design perfectly. The goal is to make
the model operate PCBSmith tools that know PCB constraints.

## Current Proven Capabilities

- KiCad CLI discovery and validation.
- KiCad project skeleton generation.
- PCBSmith project creation and validation.
- KiCad-native schematic and board export for deterministic examples.
- ERC/DRC through KiCad CLI.
- SVG preview generation.
- Gerber and drill outputs.
- Laser-oriented front-copper SVG output.
- AI context packages and proposal/review bundles.
- Basic manufacturability report for PCBSmith board models.
- Reusable LED-art board rendering service with static strings, adjacent LED
  grouping, resistor labeling, and optional low-side MOSFET control.
- Structured LED-art design operation and `design-led-art` CLI command for
  generating KiCad review bundles from AI/user request fields.
- Structured R6 ATtiny LED-controller operation and
  `design-attiny-led-controller` CLI command for generating a KiCad review
  bundle with 5 V/GND input pads, ISP pads, reset pull-up, decoupling, GPIO
  labels, and one or two current-limited status LED outputs.
- Component knowledge index with explicit mounting summaries for SMD,
  through-hole, and virtual parts.
- Compact `component-knowledge-search` CLI for AI/local-model retrieval over
  the generated component knowledge index.
- Compact `component-selection` CLI for choosing ranked component candidates
  from engineering intents such as LED current limiting, MOSFET low-side
  switching, BJT stages, comparator thresholds, buzzer outputs, terminal power
  input, 555 timers, power entry, zener protection, relay switching, and isolated
  power.
- Compact `circuit-topologies` CLI for choosing circuit-family topology before
  part selection. The first supported non-demo topology is an LC oscillator metal
  detector path with PCB spiral coil math, BJT/comparator/output stages, and an
  explicit warning not to pick NE555 unless the topology and math justify it.
- Dedicated `pcbsmith.calculators` package for deterministic engineering math.
  The first calculators are `pcb-spiral-coil-estimate` and `lc-resonance`, both
  exposed through the `calculator` CLI and AI planner/context packages.
- AI context and planner packages now expose the same `component_selection`
  tool contract so hosted or local models can discover supported component
  intents before proposing symbols, footprints, or board edits.
- AI planner packages now expose a `circuit_topologies` contract before
  component selection, so models are told to choose topology and required math
  tools before choosing familiar parts.
- Circuit knowledge rules now exist as a compact `circuit-rules` CLI and
  AI-tool contract. The first supported intents are LED current limiting,
  voltage dividers, RC filters, NE555 astable/PWM assumptions, MOSFET low-side
  switching, and power entry.
- KiCad review bundles, AI proposal bundles, and `design-led-art` operations
  now write `revision-brief.json`. The brief merges plan validation where
  available, KiCad validation, preview export, manufacturability, circuit-rule
  findings, and advisory visual-review placeholders into one machine-readable
  revision queue.
- Roadmap now separates silkscreen/artwork requests from physical board-outline
  requests. Logos/text/labels go to `F.SilkS` or `B.SilkS`; custom board shapes,
  cutouts, and edge connector geometry go to `Edge.Cuts`.
- R7 groundwork now includes a `board_feature_intent` AI contract that classifies
  printed artwork separately from physical board-outline geometry before a model
  proposes edits.
- R7A groundwork now includes `silkscreen_artwork` and the
  `design-silkscreen-artwork` CLI operation, which validate front/back
  silkscreen text and simple line/rectangle graphic requests for readable size,
  stroke width, board-edge margin, and copper keepout before rendering them as
  KiCad-native board text and graphics.
- R7B groundwork now includes `board_outline_geometry`, which validates physical
  outline/cutout loops separately from silkscreen art and renders accepted loops
  as KiCad-native `Edge.Cuts` segments.
- Demos for LED circuits, voltage divider, RC filter, VIR-LAB LED art, NE555
  astable, and NE555 PWM dimmer.

## Important Corrections

- The custom PySide CAD GUI is not the serious path. KiCad-backed generation and
  review is the path.
- 45-degree or mitered routing is a strong CAD polish preference, not an
  overheating law.
- KiCad DRC/ERC and real manufacturability constraints are the gates.
- Silkscreen artwork and physical board outlines must not be conflated.
- Schematic visuals can be rough while PCB output is being proven, but final
  user-facing examples should still become readable over time.
- Abstract board SVGs are not enough. Real KiCad PCB files and KiCad-derived
  outputs matter.
- Preview images in chat can fail. Always provide absolute file paths for
  generated artifacts.

## Current Roadmap

See `docs/roadmap.md`.

The current priority is:

1. R0 LED Art Showcase Track.
2. R1 KiCad Library Import Foundation.
3. R1.5 Hierarchical Component Knowledge Index.
4. R2 Component Catalog Bridge.
5. R3 AI Retrieval Tools.
6. R4 Circuit Knowledge Rules.
7. R5 Review And Revision Loop.
8. R6 Bigger Real Demos.
9. R7 Parametric PCB Features.
10. R8 Project Restructure And Cleanup.
11. R9 Composable Circuit Blocks.
12. R10 Circuit Intelligence Layer.
13. R11 Deterministic Math Layer.
14. R12 Validation And Reporting Layer.
15. R13 Expanded Component And KiCad Library Integration.
16. R14 Local AI Integration.
17. R15 Metal Detector Prototype Track.

## KiCad Setup

The user has KiCad 10 installed. The known CLI path is:

`C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`

The usual environment variable is:

`PCBSMITH_KICAD_CLI=C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`

## Useful Commands

Run the full development check:

```powershell
.\.venv\Scripts\python.exe .\tools\dev_check.py
```

Run tests directly:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run --python 3.12 --extra dev python -m pytest -q
```

Check KiCad backend:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli kicad-doctor
```

Validate a KiCad project:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli kicad-validate <project-dir>
```

Generate a KiCad review bundle:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli kicad-review-bundle <source-project> <output-dir>
```

The review bundle writes `<output-dir>\revision-brief.json` beside the KiCad
project and `ai-context.json`.

Generate an AI proposal bundle with a revision brief:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli ai-proposal-bundle <source-project> <planner-package.json> <candidate-plan.json> <output-dir>
```

The top-level `<output-dir>\revision-brief.json` is the AI-facing "fix these
before approval" artifact for the proposal. The nested KiCad review bundle also
writes its own `<output-dir>\kicad-review\revision-brief.json`.

Generate a structured LED-art review bundle:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli design-led-art .tmp\r0-led-art-ai-operation\kicad-review --name "AI VIR LAB" --text "VIR-LAB" --topology 12v_dense --control low_side_mosfet
```

The generated `.pcbsmith/operation.json` is the AI-facing contract for this
operation. It records the request, output files, check status, and centralized
board-routing rules from `pcbsmith.rules.board_intelligence`. The generated
review directory also includes `revision-brief.json`.

Generate a structured R6 ATtiny LED-controller review bundle:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli design-attiny-led-controller .tmp\r6-attiny-led-controller-demo --name "R6 ATtiny Controller" --led-outputs 2
```

The generated `.pcbsmith/operation.json` records the controller request, output
files, centralized routing rules, KiCad validation/preview status, and revision
brief status.

Generate a structured R7A silkscreen artwork review bundle:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli design-silkscreen-artwork .tmp\r7a-silkscreen-demo --name "R7A Logo Placement" --text "VIR LAB" --x 18 --y 16
```

The generated `.pcbsmith/reports/silkscreen-preflight.json` records artwork
readability, board-edge, and copper-keepout checks before the board text is
written into the KiCad PCB.

Generate and query component knowledge:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli component-knowledge-index .tmp\component-knowledge.json
.\.venv\Scripts\python.exe -m pcbsmith.cli component-knowledge-search .tmp\component-knowledge.json --query "zener protection" --mounting smd
.\.venv\Scripts\python.exe -m pcbsmith.cli component-selection .tmp\component-knowledge.json low-side-switch
.\.venv\Scripts\python.exe -m pcbsmith.cli circuit-topologies metal-detector
.\.venv\Scripts\python.exe -m pcbsmith.cli calculator pcb-spiral-coil-estimate --param shape=square --param outer_diameter_mm=55 --param turns=24 --param trace_width_mm=0.3 --param trace_spacing_mm=0.3
.\.venv\Scripts\python.exe -m pcbsmith.cli calculator lc-resonance --param inductance_uH=35.56 --param capacitance_nF=10
.\.venv\Scripts\python.exe -m pcbsmith.cli circuit-rules led-current-limit --param supply_voltage_v=5 --param led_forward_voltage_v=2 --param resistor_ohms=330
```

## User Priorities

- Build visible showcase features first.
- LED art is the first custom PCB feature.
- Support multiple fabrication methods over time: professional fab, laser,
  CNC/isolation, and toner/etch.
- Later support capacitive switches, dimming, strobing, RGB effects, coils,
  antennas, charging structures, and other generated board geometry.
- Later support user-provided silkscreen artwork and user-provided/custom board
  outlines as separate feature paths.
- Local LLM support matters. The user has enough local GPU resources to test
  serious models later.
- The AI should have both structured project context and visual artifacts where
  possible.
- Multimodal review should become an optional visual QA layer for generated
  artifacts, below deterministic KiCad and PCBSmith checks.
- R8 has started. A pre-restructure archive snapshot is ignored under
  `old_files/`, generated project outputs belong under ignored `outputs/`, local
  model/RAG assets belong under ignored `ai_assets/`, and the former overloaded
  `pcbsmith.services` layer is being split into `ai`, `generators`, `kicad`,
  `knowledge`, `operations`, and `rules`.
- Before attempting more speculative circuits such as a PCB-coil metal detector,
  PCBSmith should strengthen topology selection, deterministic math, and
  validation/reporting so the AI cannot simply reuse a familiar demo pattern.
- The AI should not calculate engineering math on its own. It should call
  PCBSmith calculators and work from structured results.

## When Starting A New Chat

Read these files first:

- `docs/project-handoff.md`
- `docs/roadmap.md`
- `docs/project-decision-log.md`
- `docs/presentation-brief.md`
- latest files under `docs/superpowers/specs`
- latest files under `docs/superpowers/plans`

Then run `git status --short` and inspect the latest commits before making
changes.
