# PCBSmith LED Art And Library Roadmap Design

## Purpose

PCBSmith needs a revised roadmap that balances two truths:

- A visible showcase feature should come first so the project can be judged by
  real outputs.
- Long-term AI-assisted PCB design still needs a serious library, component
  knowledge, RAG, rule, and generated-geometry foundation.

The approved direction is to make LED art the `R0` showcase track while keeping
the KiCad library and AI knowledge roadmap intact.

## Architecture

The roadmap separates PCBSmith work into four cooperating layers:

1. KiCad-backed CAD output.
2. Component and library intelligence.
3. AI retrieval, planning, and review tooling.
4. Parametric board-feature generation.

KiCad remains the authoritative backend for real CAD files and manufacturing
outputs. PCBSmith should use KiCad libraries as symbol, footprint, pin, field,
description, datasheet-link, pad, and 3D-reference metadata. PCBSmith must not
assume KiCad libraries contain complete behavioral documentation for every
component.

## LED Art As R0

LED art becomes `R0` because it is visible, useful for demos, and exercises the
same pipeline needed later for custom geometry. The track starts with static
single-color 0603 LED boards and grows toward electrical grouping, interaction,
dimming, RGB effects, and fabrication profiles.

LED art should still produce real KiCad projects, not preview-only drawings. The
review bundle should include KiCad PCB files, visual SVGs, Gerbers, drill files,
laser-oriented copper SVG, and structured reports.

## Component Knowledge Strategy

The component knowledge system must be hierarchical:

- Core parts stay in the always-visible working set.
- Families expose short summaries and tags.
- Deep component profiles load only after the AI selects a candidate.
- Datasheets and app notes are queried only for specific facts.

Each part must carry a support status such as `well_supported`,
`metadata_only`, or `needs_datasheet_review`. This prevents the AI from treating
a found KiCad symbol as a fully understood component.

## Parametric Board Features

Custom PCB features such as LED paths, PCB coils, antennas, capacitive touch
pads, copper logos, shunts, and heaters are not ordinary imported components.
They should be modeled as generated geometry with parameters, checks, and
warnings.

The first generated-geometry work should stay with LED art, logos, mounting
holes, and touch pads. Coils, antennas, charging, RF, high-current, and
mains-related features require calculators, external references, simulation
hooks, or explicit expert-review warnings before they become trusted automated
features.

## Documentation Changes

This design is recorded in:

- `docs/roadmap.md`
- `docs/project-handoff.md`
- `docs/project-decision-log.md`
- `docs/presentation-brief.md`

The handoff document exists so future sessions can resume with less dependence
on compressed chat history.

## Success Criteria

- The roadmap starts with `R0: LED Art Showcase Track`.
- Library import, hierarchical component knowledge, AI retrieval, circuit rules,
  review loops, larger demos, and parametric board features remain in the plan.
- The roadmap distinguishes KiCad metadata from PCBSmith behavioral knowledge.
- The roadmap distinguishes normal library components from generated board
  features.
- The handoff document explains how to resume the project in a new chat.
