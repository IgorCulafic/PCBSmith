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

## R5: Review And Revision Loop

- Convert ERC, DRC, manufacturability checks, missing library bindings, and
  component-rule findings into a structured revision brief.
- Let the AI revise only through PCBSmith commands or approved generators.
- Preserve user approval before applying generated edits.
- Keep visual previews, machine-readable reports, and fabrication outputs in one
  review bundle.

## R6: Bigger Real Demos

- ATtiny or Arduino-style LED controller with programming header and IO labels.
- Sensor breakout board.
- MOSFET load driver.
- Regulator and power-entry board.
- Addressable LED badge.
- More realistic two-layer boards with vias, silkscreen, polarity, and
  fabrication exports.

## R7: Parametric PCB Features

Some board elements are not normal library components. PCBSmith should model
them as generated geometry with parameters, checks, and review warnings.

- LED paths and LED art.
- Copper text and logo geometry.
- Mounting holes, fiducials, test points, and edge connectors.
- Capacitive touch pads.
- PCB coils and spiral inductors.
- Meander antennas and RF structures.
- Copper heatsinks, shunts, spark gaps, and high-current pours.

Early R7 work should stay with visible and lower-risk features such as LED paths,
logos, mounting holes, and touch pads. Coils, antennas, charging, metal
detection, RF, high-current, and mains-related features need calculators,
external references, simulation hooks, or explicit expert-review warnings.

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
optional low-side MOSFET control. The next product-facing work should start
Phase 1 by turning this foundation into AI-callable design operations instead of
one-off scripts. In parallel, PCBSmith should keep building the R1 and R1.5
library foundation so the AI can choose real parts without being overloaded by
the full library at once.
