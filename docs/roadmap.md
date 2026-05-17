# PCBSmith Roadmap

This roadmap is the working path for PCBSmith after the KiCad-first pivot.
PCBSmith is an open-source AI companion for KiCad: KiCad remains the
authoritative CAD, validation, and fabrication backend, while PCBSmith builds
the AI-facing planning, review, library, and generation layers around it.

## Guiding Principles

- Build showcaseable, real KiCad outputs before broad free-form synthesis.
- Treat AI output as a proposal until PCBSmith and KiCad checks pass.
- Prefer constrained tools, indexed knowledge, and explicit rules over asking an
  LLM to "just know PCB design."
- Keep KiCad ERC/DRC as hard gates for manufacturability.
- Keep PCBSmith checks advisory or preflight unless they cover hard physical
  constraints such as clearance or invalid connectivity.
- Use KiCad libraries as CAD metadata, not as complete component behavior docs.
- Load component knowledge in tiers so local and hosted models are not flooded
  with irrelevant parts.

## R0: LED Art Showcase Track

LED art becomes the first public-facing custom PCB feature because it is visible,
easy to judge, and exercises the same machinery later needed for image-driven
boards, generated geometry, silkscreen, laser outputs, and real fabrication
exports.

### R0.1 Static Single-Color LED Art

- Generate LED placement from text, simple paths, or SVG input.
- Support 0603 LEDs first.
- Add current-limiting resistors, input pads, net names, silkscreen labels, and
  polarity markers.
- Export KiCad PCB, schematic where useful, board SVG, Gerbers, drill files, and
  laser-oriented copper SVG.
- Keep designs DRC-clean and visually centered.

### R0.2 Electrical Grouping

- Choose series, parallel, or grouped LED strings based on supply voltage, LED
  forward voltage, target current, and total current.
- Calculate resistor values and power warnings.
- Flag designs that exceed reasonable USB, battery, or connector current.
- Keep one clear review report that explains the chosen grouping.

### R0.3 Basic Interaction

- Add simple on/off control first.
- Add capacitive touch only after the controller or IC choice is explicit.
- Keep touch-pad geometry as a generated board feature, not a fake component.

### R0.4 Dimming And Strobing

- Support simple analog dimming where appropriate.
- Add MOSFET PWM load switching for higher-current LED art.
- Use 555-based PWM as an intermediate non-microcontroller option.

### R0.5 RGB And Addressable LEDs

- Add WS2812/SK6812-style addressable LEDs after static LED art is stable.
- Include data-line resistor, local decoupling, power injection warnings, and
  controller/header assumptions.
- Treat animation logic as firmware intent, not PCB geometry.

### R0.6 Fabrication Profiles

- Professional fab: Gerbers, drill, DRC, solder mask, silkscreen, BOM path.
- Laser engraving: front/back copper SVG or DXF, wider traces, simple layers,
  few or no vias when requested.
- CNC isolation: tool diameter, isolation spacing, and minimum feature checks.
- Toner/etch: wider traces, fewer fine features, beginner-friendly defaults.

## R1: KiCad Library Import Foundation

- Index KiCad symbols, footprints, and 3D model references from the local KiCad
  installation.
- Parse symbol fields, descriptions, keywords, datasheet links, pins, pin
  numbers, and electrical pin types.
- Parse footprint pads, pad numbers, pad types, layers, attributes, and 3D model
  references.
- Store the index locally as a stable machine-readable artifact.
- Keep source paths and KiCad version metadata so results are reproducible.

## R1.5: Hierarchical Component Knowledge Index

The component library must be tiered. A flat list of every symbol and footprint
would overwhelm both users and models.

- Tier 1: core working set always visible to the AI, such as resistors,
  capacitors, LEDs, diodes, switches, connectors, VCC, GND, basic MOSFETs,
  regulators, and 555 timers.
- Tier 2: family index with short summaries for timers, microcontrollers,
  op-amps, regulators, MOSFETs, connectors, sensors, displays, logic ICs, and
  power-management parts.
- Tier 3: deep component profiles loaded only when a candidate part is selected.
- Tier 4: datasheet and app-note archive queried for specific facts, not dumped
  into the main prompt.
- Each entry must expose a coverage status such as `well_supported`,
  `metadata_only`, or `needs_datasheet_review`.

## R2: Component Catalog Bridge

- Map PCBSmith catalog entries to KiCad symbols and footprints.
- Support multiple compatible footprints per logical component.
- Add tags for package, role, polarity, family, mounting style, and support
  status.
- Keep user-preferred component lists separate from the full KiCad universe.
- Allow PCBSmith to reject AI-chosen parts when a required symbol, footprint, or
  pin mapping is missing.

## R3: AI Retrieval Tools

- Add AI-callable commands for component search, family browsing, part
  explanation, footprint resolution, and compatibility checks.
- Return compact, relevant results by default.
- Allow the AI to request deeper profiles only for selected candidates.
- Include retrieved component evidence in AI context packages and approval
  bundles.

## R4: Circuit Knowledge Rules

- Add explicit rule templates for circuits PCBSmith supports well.
- Start with LED resistor, voltage divider, RC filter, 555 astable, 555 PWM,
  MOSFET low-side switch, regulator support capacitors, and connector power
  entry.
- Rules should produce structured findings, not vague prose.
- Rules should explain assumptions such as supply voltage, LED forward voltage,
  current, package choice, and trace width.

The first R4 slice is implemented as `circuit-rules`, with an AI-tool contract
embedded into AI context and planner packages. It checks parameterized
assumptions for LED current limiting, voltage dividers, RC filters, 555
astable/PWM circuits, MOSFET low-side switches, and power entry. This is not a
replacement for ERC/DRC; it is the model-facing electrical assumption layer that
turns vague ideas into structured warnings, errors, and calculated values.

## R5: Review And Revision Loop

- Convert ERC, DRC, manufacturability checks, missing library bindings, and
  component-rule findings into a structured revision brief.
- Let the AI revise only through PCBSmith commands or approved generators.
- Preserve user approval before applying generated edits.
- Keep visual previews, machine-readable reports, and fabrication outputs in one
  review bundle.

R5 is implemented as `revision-brief.json` in KiCad review bundles, AI proposal
bundles, and structured design operations such as `design-led-art`. It combines
AI plan validation where available, KiCad ERC/DRC status, preview export errors,
board manufacturability findings, circuit-rule findings, and advisory visual
review placeholders into one machine-readable list of revision items with
concrete next actions. This gives hosted or local models a constrained "fix
these issues next" target instead of asking them to infer problems from
scattered logs.

## R5.5: Optional Multimodal Visual Review

Multimodal review is a lower-authority quality-control layer. It should help the
AI and user spot visible problems, but it must never replace deterministic
checks.

- Feed schematic SVGs, board SVGs, laser/copper SVGs, and targeted screenshots
  into a multimodal model when available.
- Ask visual review to look for text overlap, unreadable polarity labels,
  missing logos, board centering, poor visual balance, odd routing aesthetics,
  unexpected blank previews, and mismatch with the user's visual request.
- Keep ERC, DRC, circuit rules, geometry checks, and fabrication checks above
  visual review in authority.
- Keep the interface provider-agnostic so hosted models and local multimodal
  models can both be used later.
- Record visual review findings in the revision brief as advisory items unless a
  deterministic checker confirms the same issue.

## R6: Bigger Real Demos

- ATtiny or Arduino-style LED controller with programming header and IO labels.
- Sensor breakout board.
- MOSFET load driver.
- Regulator and power-entry board.
- Addressable LED badge.
- More realistic two-layer boards with vias, silkscreen, polarity, and
  fabrication exports.

The first R6 slice is implemented as `design-attiny-led-controller`. It
generates a KiCad review bundle for an ATtiny-style 5 V LED controller with
power pads, ISP pads, reset pull-up, decoupling capacitor, one or two
current-limited status LED outputs, GPIO labels, silkscreen labels, KiCad
validation/preview outputs, `operation.json`, and `revision-brief.json`. The
generator uses the centralized routing-intelligence helpers so its traces follow
the same cardinal/45-degree CAD polish preference recorded in AI-facing
operation summaries.

## R7: Parametric PCB Features

Some board elements are not normal library components. PCBSmith should model
them as generated geometry with parameters, checks, and review warnings.

- LED paths and LED art.
- Mounting holes, fiducials, test points, and edge connectors.
- Capacitive touch pads.
- PCB coils and spiral inductors.
- Meander antennas and RF structures.
- Copper heatsinks, shunts, spark gaps, and high-current pours.

Early R7 work should stay with visible and lower-risk features such as LED paths,
logos, mounting holes, and touch pads. Coils, antennas, charging, metal
detection, RF, high-current, and mains-related features need calculators,
external references, simulation hooks, or explicit expert-review warnings.

### R7A: Silkscreen And Board Artwork

Silkscreen features are printed artwork on `F.SilkS` or `B.SilkS`. They are not
the physical shape of the board.

- Logos, decorative text, QR codes, component reference labels, polarity marks,
  pin-1 markers, assembly notes, and component courtyard-style visual borders.
- Import SVG/text artwork and place it as KiCad silkscreen geometry.
- Check that silkscreen stays inside the board outline, avoids pads and exposed
  copper, respects readable line/text sizes, and can be disabled or minimized
  for professional boards.
- Keep a decorative/showcase mode separate from a minimal/professional mode.

The first R7A foundation is implemented as `silkscreen_artwork` and
`design-silkscreen-artwork`. It models front/back silkscreen text/artwork
requests, checks readable size, stroke width, board-edge margin, and copper
keepout, then renders accepted requests through KiCad-native `BoardText` and
simple `BoardGraphic` line/rectangle primitives. AI context and planner packages
now advertise this as a separate `silkscreen_artwork` contract below the
`board_feature_intent` classifier.

### R7B: Board Outline And Cutout Geometry

Board outline features are physical geometry on `Edge.Cuts`. They are not
silkscreen artwork.

- Logo-shaped boards, badge outlines, custom object outlines, rounded or
  irregular board shapes, mounting slots, notches, holes, and cutouts.
- Import SVG/DXF/path outlines, simplify geometry, scale to real units, and
  generate closed KiCad `Edge.Cuts` loops.
- Check minimum neck width, copper/silkscreen edge clearance, manufacturable
  curves and corners, valid closed outlines, mounting-hole clearance, and
  fabrication-profile compatibility.
- Treat USB edge connectors, card-edge contacts, and other mechanical connector
  outlines as specific connector features with their own dimensional rules, not
  as generic decorative shapes.

The first R7B foundation is implemented as `board_outline_geometry`. It models
physical outline and cutout loops separately from silkscreen art, checks minimum
outline size, Edge.Cuts stroke width, cutout placement, and copper edge
clearance, then renders accepted loops as KiCad-native `Edge.Cuts` segments.
When custom edge loops exist, PCBSmith suppresses the generic rectangular board
outline so the physical shape has a single source of truth.

## R8: Project Restructure And Cleanup

R8 is the deliberate cleanup pass after the early prototype and demo-heavy
work. The goal is not to delete useful history casually; the goal is to make the
repository look like a serious open-source project instead of an active scratch
workspace.

- Separate committed source, docs, tests, and stable tools from generated
  review bundles, temporary KiCad outputs, cache folders, old pytest workspaces,
  and abandoned prototype artifacts.
- Keep `.tmp`, cache folders, broken virtual environments, old phase workspaces,
  and one-off generated outputs out of the project root.
- Move any historically useful generated demos into a documented examples or
  release-artifacts area only when they are intentionally curated.
- Keep repeatable commands in `tools/`, with one startup/dev check that proves
  the environment, tests, KiCad backend, library index, and review-bundle flow
  still work.
- Update `.gitignore`, cleanup tooling, README, project handoff, and
  presentation docs so a new contributor can understand the project quickly.
- Do not run destructive cleanup blindly. The cleanup tool should default to a
  dry run or archive mode before deletion.

The first R8 foundation is in place. A pre-restructure workspace snapshot lives
under ignored `old_files/`, generated review bundles belong under ignored
`outputs/`, local model/RAG assets belong under ignored `ai_assets/`, and future
integrations have an `extensions/` placeholder. The old overloaded
`pcbsmith.services` package has been split into focused packages:

- `pcbsmith.ai` for planner packages, approval/review helpers, and local/remote
  model-facing contracts.
- `pcbsmith.generators` for reusable board and circuit generators.
- `pcbsmith.kicad` for KiCad project, validation, export, preview, library, and
  review-bundle adapters.
- `pcbsmith.knowledge` for built-in components, catalog metadata, and
  retrieval/selection indexes.
- `pcbsmith.operations` for AI-callable/user-callable design operations and
  project mutation workflows.
- `pcbsmith.rules` for ERC, circuit rules, routing/manufacturing conventions,
  silkscreen checks, and board outline geometry.

## R9: Composable Circuit Blocks

R9 turns repeated circuit patterns into reusable blocks that can be combined by
AI tools instead of recreated as board-specific scripts. A block is electrical
intent: components, pins, nets, parameters, and net bindings. Layout remains a
separate step so the same block can later appear in different board shapes,
LED-art arrays, or controller designs.

- Start with `power_input_2pin`, `decoupling_capacitor`, `led_string`,
  `low_side_mosfet_switch`, and `gpio_led_output`.
- Let callers bind local block nets such as `vcc`, `gnd`, `return`, `control`,
  or `signal` onto shared circuit nets.
- Auto-allocate conventional references such as `J1`, `R1`, `LED1`, `C1`, and
  `Q1` so multiple instances of the same block can coexist.
- Namespace internal nets by block instance so prebuilt arrays can be reused
  safely.
- Generate a real schematic from the composed circuit before PCB layout.
- Add a future JSON/CLI operation that accepts block composition requests and
  only attempts PCB layout when a supported layout strategy exists.

The first R9 foundation is implemented as the `pcbsmith.templates` package. It
contains source-controlled template metadata and builders for the initial power,
LED, and switching blocks, while `compose_circuit_blocks` remains as a backward
compatible operation adapter. The AI-facing source of truth is the template
registry: generated KiCad projects and demo boards are outputs or regression
fixtures, not reusable template definitions. This is the direction for local and
hosted models: they should operate PCBSmith's constrained template tools, not
invent ad hoc PCB Python files for every prompt.

## R10: Circuit Intelligence Layer

R10 prevents the AI from choosing familiar parts before it has chosen a valid
circuit topology. This directly addresses the metal detector lesson: a model may
reach for a known NE555 pattern even when the request needs an LC sensing
topology, coil geometry, gain/threshold stages, and actual math.

- Select a circuit topology before choosing parts or laying out a board.
- Record component intents, required math tools, required user inputs,
  validation gates, and do-not-use rules per topology.
- Expose topology selection through an AI-facing tool contract and CLI.
- Treat unsupported circuit families as unsupported, not as an invitation to
  improvise.
- Require rationale when a familiar part is selected despite a topology warning.

The first R10 foundation is implemented as `circuit-topologies`. The initial
supported metal-detector topology is an LC oscillator/sensing path with a PCB
spiral coil, BJT gain/switching support, trim adjustment, comparator threshold,
buzzer output, LED indication, and terminal power input. The AI planner package
now includes this topology contract before component selection, so models see
the circuit-family guardrail before they see individual parts.

## R11: Deterministic Math Layer

R11 moves engineering calculations into reliable code. The AI may request a
calculation, supply assumptions, and explain tradeoffs, but it should not freehand
the math for values that determine whether hardware works.

- LED resistor and string grouping calculations.
- Ohm's law, resistor power, and connector current checks.
- RC time constant, cutoff frequency, and 555 timing checks.
- MOSFET gate/base resistor and pull resistor checks.
- BJT bias checks for simple switching/amplifier stages.
- Comparator threshold and hysteresis calculations.
- PCB spiral coil inductance/resistance estimates and LC resonance estimates.
- Geometry checks for trace width, spacing, vias, edge clearance, and fab
  profile limits.

The tool boundary is intentional: the AI can ask "calculate the coil estimate
for these dimensions"; PCBSmith returns structured values, warnings, and blocked
states.

The first R11 foundation is implemented in the dedicated `pcbsmith.calculators`
package so math tools do not get scattered across one-off board generators. It
adds:

- `pcb-spiral-coil-estimate` for square/hexagonal/octagonal/circular PCB spiral
  estimates using the modified Wheeler expression from Mohan, Hershenson, Boyd,
  and Lee, plus approximate trace length and DC resistance.
- `lc-resonance` for frequency from L/C or required capacitance from target
  frequency.
- A `calculator` CLI tool and AI planner/context contract so hosted or local
  models call deterministic math instead of inventing values.

## R12: Validation And Reporting Layer

R12 makes every generated design explain itself. A successful output should
include what topology was chosen, which calculators ran, which library parts were
selected, what KiCad checked, what PCBSmith checked, and what still needs human
review.

- Add topology, component-selection, math, ERC/DRC, manufacturability, and
  fabrication-profile status to review bundles.
- Distinguish hard failures, warnings, advisory visual findings, and human-review
  items.
- Keep simulation hooks lower priority than ERC/DRC and deterministic checks
  until the relevant simulator path is proven.
- Keep schematic readability as a quality target without blocking board-first
  geometry demos when the board artifact is the authoritative result.

The first R12 foundation is implemented as the `pcbsmith.reporting` package.
KiCad review bundles now write both
`.pcbsmith/reports/validation-summary.json` and
`.pcbsmith/reports/validation-summary.md`. The summary gathers KiCad
validation, preview exports, PCBSmith manufacturability findings, circuit-rule
findings, calculator outputs, component candidates, topology choice, and
human-review items into one status:

- `passed` when no findings exist;
- `needs_review` when warnings or advisories exist;
- `blocked` when hard errors exist.

AI context and planner packages now advertise this validation-report contract,
so a hosted or local model should read the consolidated evidence before claiming
a board is fabrication-ready or proposing revisions.

## R13: Expanded Component And KiCad Library Integration

R13 broadens the catalog and library bridge in a controlled way. KiCad provides
symbols, footprints, and many 3D model references, but it does not provide
complete behavioral knowledge for every component.

- Index more KiCad symbol/footprint families needed by real beginner circuits:
  BJTs, op-amps, comparators, buzzers, terminal blocks, regulators, batteries,
  sensors, switches, connectors, and common microcontrollers.
- Map those entries into PCBSmith families with tags, mounting style, package,
  pin roles, support status, and datasheet/app-note links where available.
- Keep `well_supported`, `metadata_only`, and `needs_datasheet_review` visible to
  the model.
- Use KiCad library data for CAD availability; use datasheets, app notes, and
  curated examples for behavior and design rules.

The first R13 slice expanded the built-in catalog with NPN/PNP BJTs, LM393,
LM358, active buzzer, and a 2-pin terminal block, all with KiCad bindings where
available.

The second R13 slice broadens the reusable core set for controller, power, and
sensor-style boards. The catalog now includes 0805 resistor/capacitor/LED
variants, a SOD-323 Schottky diode, AMS1117-3.3 SOT-223 regulator, CR2032 SMD
battery holder, SMD tactile switch, 3225 crystal, ATtiny85 SOIC-8, and a 1x06
2.54 mm programming header. The component-selection tool also exposes new
intents for battery power, regulated power, user input buttons, programming
headers, clock sources, small 8-bit microcontrollers, and reverse-polarity
protection. This keeps local and hosted models choosing from known PCBSmith
roles instead of inventing parts.

## R14: Local AI Integration

R14 connects the same constrained workflow to local models. The local model
should not receive a giant dump of every symbol and datasheet. It should receive
the request, current project context, topology options, compact component
families, selected deep profiles, calculator outputs, and review findings.

- Support OpenAI-compatible local endpoints first, including KoboldCPP or other
  GGUF-backed servers when they expose compatible chat APIs.
- Keep model assets under ignored local folders such as `ai_assets/`.
- Add configuration for model path, context size, temperature, JSON mode support,
  timeout, and whether multimodal input is available.
- Add optional multimodal visual review later for schematic/PCB previews, below
  deterministic checks in authority.
- Preserve the same approval loop for hosted and local models.

The first R14 foundation is implemented as a local OpenAI-compatible endpoint
adapter. PCBSmith does not load GGUF files directly yet; KoboldCPP, llama.cpp
server, LM Studio, or another local runtime should host the model and expose
`/v1/chat/completions`. PCBSmith now has:

- `local-ai-config-template` to write a safe editable local endpoint config;
- `local-ai-config-check` to print endpoint/model settings without contacting
  the server;
- `local-ai-review` to run the existing request -> brief -> planner package ->
  model candidate -> approval-preview flow using local model settings;
- a `local_ai` tool contract in AI context and planner packages so models see
  that local execution is still governed by PCBSmith tools and the approval
  loop.

Direct in-process inference can be added later as a separate adapter if it is
worth the CUDA/native dependency cost on Windows.

## R15: Metal Detector Prototype Track

R15 resumes the metal detector request after R10-R12 are strong enough to stop
unjustified part choices.

- Use a PCB spiral coil generated as board geometry, not a pile of unrelated
  circles.
- Calculate coil geometry and LC resonance before choosing the sensing circuit.
- Choose a topology such as LC oscillator plus gain/threshold/output stages.
- Include power input, trim adjustment, LED/buzzer indication, and silkscreen
  labels.
- Mark the prototype as educational/experimental until calculator, ERC/DRC,
  and human review agree that the design is plausible.

## User Contribution Path

The most valuable user help is collecting trusted examples and requirements:

- LED art examples, logos, and target effects.
- Preferred power sources such as USB 5 V, battery, 12 V input, or external
  driver.
- Fabrication method priorities for each demo: fab, laser, CNC, or etch.
- Datasheets, app notes, and example circuits for parts PCBSmith should support.
- Board photos or KiCad projects that show layouts worth learning from.
- Priority list for custom PCB features after LED art.

## Current Priority

R0.1 and R0.2 now have a reusable foundation: text-driven VIR-LAB LED art,
adjacent LED string grouping, resistor labeling, KiCad review bundles, and
optional low-side MOSFET control. Phase 1 has started with a structured
`design-led-art` operation that turns AI/user request fields into a KiCad review
bundle without creating a new generator script. The operation summary now embeds
the centralized board-routing contract from `pcbsmith.rules.board_intelligence`,
so AI-facing tools inherit the same 45-degree routing preference, DRC authority,
trace-width, and manufacturability guidance instead of carrying one-off rules.
The next work should keep expanding this AI-callable operation layer, then
continue the R1 and R1.5 library foundation so the AI can choose real parts
without being overloaded by the full library at once.

The component catalog now distinguishes SMD, through-hole, and virtual parts in
the AI-facing knowledge index. The default direction is SMD-first, while common
through-hole alternatives remain visible for parts where physical assembly or
real-world connectors matter. Current common entries include fuses, inductors,
zener diodes, photoresistors, potentiometers, MOSFETs, NE555, relays, and
transformers, with safety-sensitive electromechanical/magnetic parts marked for
deeper review before automated use.

The first retrieval slice is a compact `component-knowledge-search` command. It
lets local or hosted models query the generated index by text, mounting style,
support status, and required tags instead of reading the entire component
catalog into context.

The next selection slice now exists as `component-selection`, with
`component-select` as a shorter alias. It turns engineering intents such as
`led-current-limit`, `low-side-switch`, `bjt-npn-amplifier`,
`comparator-threshold`, `buzzer-output`, `terminal-power-input`, `555-timer`,
`power-entry`, `zener-protection`, `relay-switching`, and `isolated-power` into
ranked candidate components. This is intentionally above raw search: it prefers
SMD where requested, narrows broad tags to the correct family, and marks
metadata-only, datasheet-sensitive, or safety-sensitive choices as
`needs_review` with compact warnings and next checks for the model.

AI context and planner packages now include this selection contract directly.
That means a local model can see the supported engineering intents during plan
generation, while the actual candidate lookup remains a PCBSmith tool call over
the component knowledge index.

The newest guardrail is `circuit-topologies`. Before the AI chooses parts, it
must choose a supported topology for the circuit family. The first R10 topology
targets the metal-detector problem: use an LC oscillator/sensing approach with a
PCB spiral coil, deterministic coil/resonance math, BJT/comparator/output
stages, and a clear rule not to select NE555 unless that choice is justified by
the topology and math.

Review bundles now write `revision-brief.json` directly. AI proposal bundles
also write a top-level proposal brief beside the staged project and nested KiCad
review bundle, while the nested KiCad bundle writes its own brief. The brief
summarizes plan-check, KiCad, preview, manufacturability, circuit-rule, and
advisory visual-review findings into a single revision queue that an AI can
revise against before the user approves any generated edits.
