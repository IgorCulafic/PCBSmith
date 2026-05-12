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
- Demos for LED circuits, voltage divider, RC filter, VIR-LAB LED art, NE555
  astable, and NE555 PWM dimmer.

## Important Corrections

- The custom PySide CAD GUI is not the serious path. KiCad-backed generation and
  review is the path.
- 45-degree or mitered routing is a strong CAD polish preference, not an
  overheating law.
- KiCad DRC/ERC and real manufacturability constraints are the gates.
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

## User Priorities

- Build visible showcase features first.
- LED art is the first custom PCB feature.
- Support multiple fabrication methods over time: professional fab, laser,
  CNC/isolation, and toner/etch.
- Later support capacitive switches, dimming, strobing, RGB effects, coils,
  antennas, charging structures, and other generated board geometry.
- Local LLM support matters. The user has enough local GPU resources to test
  serious models later.
- The AI should have both structured project context and visual artifacts where
  possible.

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
