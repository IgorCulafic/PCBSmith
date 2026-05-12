# PCBSmith Project Decision Log

This log captures design decisions, mistakes, corrections, and lessons that should guide future PCBSmith work. It is intentionally concise: the goal is to prevent the project and its AI tooling from relearning the same lessons repeatedly.

## Product Direction

- PCBSmith is an open-source, free KiCad-first AI companion for PCB design.
- PCBSmith should not try to recreate KiCad's full schematic editor, PCB editor, DRC, library management, 3D preview, Gerber generation, or manufacturing export stack.
- KiCad is the authoritative CAD backend. PCBSmith should generate structured design intent, KiCad-compatible projects, review bundles, AI context packages, and approval workflows around KiCad.
- Commercial EDA tools such as Altium Designer, Cadence Allegro, EasyEDA, and draw.io are useful for UX inspiration, but PCBSmith should not copy closed-source code or build around closed-source dependencies.

## AI Operating Model

- The goal is not to make the model know PCB design perfectly.
- The goal is to make the model operate PCBSmith tools that know PCB constraints.
- AI outputs should be structured commands, plans, or circuit intents that PCBSmith validates before anything is applied.
- User approval remains mandatory before applying AI-generated edits.
- The AI should receive both machine-readable project context and visual review artifacts where possible.
- Local models should be supported later, but the near-term interface should stay provider-agnostic.

## Component And Library Strategy

- Prefer real components and real KiCad-compatible symbols/footprints over vague placeholder parts.
- Generic passives are acceptable for simple resistors, capacitors, LEDs, and diodes.
- ICs, connectors, MOSFETs, voltage regulators, displays, and specialized parts need explicit part identity, pin mapping, footprint mapping, and assumptions.
- KiCad libraries should remain on the table for open-source usage. If PCBSmith ever needs different licensing constraints, library ingestion can be revisited later.
- The component catalog should support tags and user-preferred component groups so models and users can choose from a known safe subset first.
- KiCad libraries provide CAD metadata and optional datasheet links, but PCBSmith must build or ingest component behavior knowledge separately.
- Component knowledge should be hierarchical: core parts always visible, family summaries searchable, deep profiles loaded on demand, and datasheets queried only for specific facts.
- Each component should eventually expose a support status such as `well_supported`, `metadata_only`, or `needs_datasheet_review`.
- Component selection should be intent-driven above raw search. The AI should ask
  for roles such as `led-current-limit` or `low-side-switch`, then PCBSmith
  should rank real catalog candidates and flag incomplete metadata or
  safety-sensitive parts before automated use.
- AI context and planner packages should expose tool contracts for constrained
  capabilities such as component selection. The model should discover the tool
  surface from PCBSmith instead of relying on remembered project details.

## Parametric Board Features

- LED art is the first showcase track and is now roadmap `R0`.
- Custom PCB features such as LED paths, capacitive touch pads, PCB coils, antennas, copper logos, shunts, heaters, and RF structures are generated board geometry, not ordinary library components.
- Generated board features need parameters, checks, and review warnings. Harder features such as coils, antennas, wireless charging, RF, high-current, and mains-related geometry should require calculators, external references, simulation hooks, or expert-review warnings.
- PCBSmith should support multiple fabrication profiles over time: professional fab, laser engraving, CNC/isolation, and toner/etch.

## Board Generation And Routing

- KiCad ERC/DRC results are hard gates.
- Trace width, clearance, current capacity, board edge clearance, net connectivity, and solder-mask conflicts are hard manufacturing constraints.
- 45-degree or mitered routing is a strong CAD polish preference, not an electrical law.
- 90-degree bends and T-junctions are not automatically unsafe; they may be acceptable if DRC and current/thermal constraints are satisfied.
- The default generated style should prefer 45-degree/mitered routing where practical.
- If 45-degree styling creates a DRC issue, DRC wins and the route must be adjusted.
- Power/load traces should be wider than signal traces. The board intelligence layer should classify net roles and choose widths consistently.

## Visual Review Lessons

- SVG previews embedded in chat are unreliable; provide absolute file paths to generated artifacts.
- Schematic SVG, board SVG, laser/copper SVG, Gerbers, drill files, and KiCad project files should be generated together when possible.
- Blank schematic or board previews should not be treated as successful review artifacts.
- Component text, silkscreen, polarity marks, pin-1 markers, board title, and component borders matter for visual judgment.
- Generated boards should be placed away from the top-left corner of the KiCad sheet and centered enough for review.

## Important Corrections

- The early custom PySide GUI was not a good path for serious EDA work. It was useful for learning interaction needs, but rebuilding KiCad-quality editing would be too costly and fragile.
- Draw.io is useful as an interaction reference for palettes and toolbars, but it is not a good architecture reference for PCB CAD.
- 45-degree routing should be documented as style preference, not as a false overheating rule.
- Generated labels such as `LED_A` and `OUT` should not be duplicated visibly on top of native KiCad reference/value text unless they are meaningful to the user.
- Board SVGs that show abstract traces without real KiCad board geometry are not enough; KiCad-native PCB files and KiCad exports are the real output.

## Current Proven Capabilities

- Create basic PCBSmith projects.
- Generate KiCad-native schematic and board files for simple examples.
- Export KiCad review bundles with visual SVGs, AI context, Gerbers, drill outputs, and laser-oriented F.Cu SVGs.
- Validate generated KiCad projects with KiCad CLI ERC/DRC.
- Generate current-limited LED, voltage divider, RC low-pass, VIR-LAB LED art, NE555 astable, and NE555 PWM dimmer demo outputs.
- Generate a two-layer NE555 astable demo with vias, front/back copper, silkscreen labels, polarity marks, and DRC-clean output.
- Generate a DRC-clean NE555 PWM dimmer board with potentiometer, steering diodes, gate resistor, pulldown, MOSFET/load switching, input/output terminals, Gerbers, drill files, and laser-oriented front-copper SVG.

## Near-Term Direction

- Build LED art as the first showcase custom PCB feature before attempting broad free-form board synthesis.
- Continue improving schematic symbol coverage for connectors, potentiometers, MOSFETs, and other non-passive parts so the source schematic does not need simplified placeholder symbols.
- Consider microcontroller-based boards such as an ATtiny/Arduino-style LED controller with programming header and IO labels.
- Grow the component catalog and board intelligence in parallel with each useful demo.
- Use `docs/roadmap.md` as the current roadmap and `docs/project-handoff.md` when starting a future chat.
