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

## Non-Goals

- Forking KiCad immediately.
- Recreating KiCad's editor widgets in PySide.
- Pixel-driving KiCad as the primary automation method.
- Supporting proprietary EDA tools beyond UX inspiration.

## Open Questions

- Which KiCad major version should be the first supported baseline?
- Should PCBSmith initially target file generation, IPC API, or both?
- Should the first AI UX be a KiCad plugin panel, a companion desktop app, or a CLI-first workflow?
