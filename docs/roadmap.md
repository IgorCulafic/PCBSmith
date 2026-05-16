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
the centralized board-routing contract from `pcbsmith.services.board_intelligence`,
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
`led-current-limit`, `low-side-switch`, `555-timer`, `power-entry`,
`zener-protection`, `relay-switching`, and `isolated-power` into ranked
candidate components. This is intentionally above raw search: it prefers SMD
where requested, narrows broad tags to the correct family, and marks
metadata-only or safety-sensitive choices as `needs_review` with compact
warnings and next checks for the model.

AI context and planner packages now include this selection contract directly.
That means a local model can see the supported engineering intents during plan
generation, while the actual candidate lookup remains a PCBSmith tool call over
the component knowledge index.

Review bundles now write `revision-brief.json` directly. AI proposal bundles
also write a top-level proposal brief beside the staged project and nested KiCad
review bundle, while the nested KiCad bundle writes its own brief. The brief
summarizes plan-check, KiCad, preview, manufacturability, circuit-rule, and
advisory visual-review findings into a single revision queue that an AI can
revise against before the user approves any generated edits.
