# PCBSmith KiCad AI Companion Design

Date: 2026-05-10

## Decision

PCBSmith will pivot from building a full custom PCB CAD GUI to becoming an AI companion and command layer for mature open-source EDA tools, starting with KiCad.

The PySide6 editor remains useful as a prototype and test harness for command semantics, but it is no longer the primary product direction. Recreating KiCad-quality schematic editing, PCB layout, routing, DRC, library management, exports, and 3D tooling inside PCBSmith would be too slow and too fragile.

## Goal

Build a serious open-source AI-assisted PCB workflow by letting KiCad handle CAD editing and manufacturing-grade project behavior while PCBSmith handles:

- natural language intent capture
- structured command generation
- safe previews and user approval
- project analysis
- ERC/DRC orchestration
- component/library search helpers
- AI action logs
- repeatable automation

## Architecture

PCBSmith should keep a command-first architecture:

```text
User prompt -> AI planner -> validated commands -> KiCad backend -> KiCad project files/UI
                          -> validation report -> user approval/log
```

The command layer is the shared contract. A human-facing UI, CLI, or future LLM tool should all produce the same command objects. Commands are validated before they mutate a project.

## AI Context Model

PCBSmith should not make the AI reason from chat text alone. For useful PCB help, the AI needs both structured project state and visual context:

- structured schematic and PCB data: symbols, footprints, nets, traces, zones, board outline, selected objects, cursor/tool state, and user preferences
- validation data: ERC, DRC, manufacturing checks, netlist summaries, power/current budget checks, and unresolved warnings
- rendered visual data: schematic previews, board previews, SVG/PNG exports, and optional user reference images

The structured data is the source of truth for electrical and manufacturing reasoning. Rendered images are used for human-like review: layout clarity, logo/path matching, silkscreen overlaps, visual spacing, and board aesthetics.

For image-shaped LED boards, PCBSmith should combine these sources:

```text
reference image -> extracted paths/points -> proposed LED/component placement
                -> structured KiCad edits -> ERC/DRC/manufacturing checks
                -> rendered preview -> AI/user review
```

The AI should propose structured operations, not draw directly into board files as pixels. Example operations include placing LEDs along extracted paths, grouping LEDs into strings, calculating current-limiting resistors, routing power rails, enforcing edge clearance, and adding silkscreen labels.

## Intent Expansion

Users may not know electronics terminology, so PCBSmith should expand simple user requests into engineering-grade briefs before touching CAD state.

Example: "Make an LED board in the shape of this logo" should become an internal brief covering supply voltage, LED type and current, resistor topology, power connector, board size, manufacturing constraints, placement along paths, edge clearance, silkscreen, ERC/DRC, and preview approval.

This expansion step should make assumptions explicit and ask for user input only when a missing decision is important or risky. PCBSmith should say what it assumes, such as "assuming 5 V USB power, red 0603 LEDs at 5 mA, and one resistor per LED string."

## AI Orchestration Strategy

The first production AI flow should use one reliable AI planner/controller. This supports local models, is easier to debug, and reduces conflicting agent behavior.

The architecture should still allow deeper multi-agent review later:

- planner: turns user intent into a structured engineering brief and command plan
- circuit reviewer: checks schematic logic, values, polarity, missing resistors, and power budget
- layout reviewer: checks placement, clearances, routing, thermal/current concerns, and visual clarity
- manufacturing reviewer: checks DRC, board outline, drill holes, silkscreen, exports, and fab readiness
- vision reviewer: compares rendered previews against reference images or intended visual shapes

Agents should suggest changes rather than directly mutating the board. A single controller applies approved structured operations, then KiCad validation checks the result.

User-facing AI modes can be added later:

- Fast/Local: one model, reduced context, best for simple tasks and local inference
- Balanced: one stronger model with structured data and rendered previews
- Deep Review: specialized reviewers inspect the same proposed change before apply
- Developer Mode: the AI may suggest missing PCBSmith tools, catalog entries, or integrations

## KiCad Integration Strategy

The first integration target is `kicad-cli` and KiCad project files because this is easy to detect and script. Once KiCad is installed, PCBSmith should be able to:

- locate `kicad-cli`
- create or open a KiCad project workspace
- run KiCad validation/export commands where available
- call into KiCad-oriented generation tools from PCBSmith commands

The second integration target is KiCad's IPC API and official `kicad-python` bindings. That path should be used for live interaction with a running KiCad instance and future plugin behavior.

PCBSmith should avoid modifying KiCad source until the companion/plugin route proves insufficient.

## Why KiCad First

KiCad already provides the serious CAD functions PCBSmith would otherwise need to recreate:

- schematic editor
- PCB layout editor
- footprint libraries
- interactive routing
- DRC/ERC workflows
- manufacturing exports
- 3D viewing
- Python/API/plugin support

KiCad is GPLv3-or-later compatible with PCBSmith's open-source direction.

## Existing PCBSmith Code Status

Keep:

- project and command experiments
- component catalog lessons
- schematic command service
- tests around command validation
- AI-oriented command model direction

Demote:

- custom PySide schematic canvas as main GUI
- custom routing/selection/PCB canvas work

Stop expanding:

- custom component placement UX
- custom wire/trace editor
- custom CAD toolbar imitation

## Next Implementation Phases

### Phase K0: KiCad Backend Detection

- Detect `kicad-cli` from `PCBSMITH_KICAD_CLI`, `PATH`, or known Windows install paths.
- Add `pcbsmith kicad-status`.
- Document how users should install/configure KiCad.

### Phase K1: KiCad Project Skeleton

- Generate a minimal KiCad project directory from PCBSmith.
- Keep generated files clearly marked.
- Validate with `kicad-cli` when available.

### Phase K2: Command Mapping

- Map PCBSmith commands to KiCad schematic/project edits.
- Start with simple components and nets.
- Prefer stable file/API paths over GUI automation.

### Phase K3: AI Approval Loop

- AI proposes commands.
- PCBSmith shows the command list and expected result.
- User approves.
- PCBSmith applies commands to KiCad and runs checks.

### Phase K4: AI Context and Review

- Export structured project state for AI review.
- Generate schematic and board previews for vision-capable models.
- Feed ERC/DRC and rendered previews into the AI approval loop.
- Keep all AI actions explainable as validated PCBSmith/KiCad operations.

### Phase K5: Image-to-LED Board Workflow

- Accept a user reference image.
- Extract paths or placement points from the image.
- Propose LED placement and electrical topology.
- Validate spacing, power, current limiting, ERC, DRC, and manufacturing constraints.
- Show visual previews before applying or exporting manufacturing files.

## Non-Goals

- Forking KiCad immediately.
- Recreating KiCad's editor widgets in PySide.
- Pixel-driving KiCad as the primary automation method.
- Supporting proprietary EDA tools beyond UX inspiration.

## Open Questions

- Which KiCad major version should be the first supported baseline?
- Should PCBSmith initially target file generation, IPC API, or both?
- Should the first AI UX be a KiCad plugin panel, a companion desktop app, or a CLI-first workflow?
- Which local model providers should be supported first?
- What minimum context package should every AI review receive?
