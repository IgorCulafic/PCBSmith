# PCBSmith Presentation Brief

## One-Sentence Summary

PCBSmith is an open-source AI companion for KiCad that turns user intent into reviewable, validated PCB design artifacts instead of trying to replace professional EDA tools.

## The Problem

PCB design is powerful but difficult for beginners. A user may know what they want to build, such as an LED sign, timer, dimmer, sensor board, or controller, but not know the right schematic structure, component choices, footprints, routing rules, design checks, or manufacturing files.

General-purpose LLMs can describe circuits, but they can also hallucinate parts, pins, footprints, and unsafe layouts. A serious PCB tool needs guardrails, real CAD files, validation, and reviewable outputs.

## The PCBSmith Approach

PCBSmith does not ask an AI to draw arbitrary pixels or directly edit board files blindly. Instead, it gives the AI structured tools and project context, then validates the result through KiCad.

Core principle:

> The goal is not to make the model know PCB design perfectly. The goal is to make the model operate PCBSmith tools that know PCB constraints.

## Why KiCad-First

The project originally explored building a custom PCB editor UI. That quickly showed the risk of recreating weaker versions of mature EDA features: schematic editing, PCB layout, routing, DRC, library management, 3D preview, Gerbers, drill files, and manufacturing exports.

The corrected architecture is KiCad-first:

- KiCad remains the authoritative CAD backend.
- PCBSmith generates KiCad-compatible projects and review bundles.
- KiCad CLI performs ERC/DRC validation.
- PCBSmith focuses on AI planning, structured commands, approval workflows, project context, and automation.

## What Works Now

- Project creation and validation.
- KiCad project skeleton generation.
- KiCad ERC/DRC checks through KiCad CLI.
- AI context packages that summarize project files, KiCad reports, visual artifacts, and routing rules.
- Deterministic circuit demos including:
  - current-limited LED circuit;
  - voltage divider;
  - RC low-pass filter;
  - VIR-LAB 5V LED art board;
  - NE555 astable LED blinker;
  - NE555 PWM LED dimmer;
  - ATtiny-style LED controller board with programming header and GPIO labels.
- KiCad review bundles with:
  - schematic SVG;
  - board SVG;
  - laser-oriented front-copper SVG;
  - Gerbers;
  - drill files;
  - AI context JSON;
  - revision brief JSON.

## Recent Technical Milestone

The NE555 demos now generate KiCad-native, validation-clean boards with:

- real schematic-backed nets;
- front and back copper;
- vias;
- wider power/ground routing;
- 45-degree/mitered routing as a CAD polish preference;
- silkscreen labels;
- component outlines;
- polarity markers;
- IC pin-1 marker;
- Gerber and drill outputs.

The newer PWM dimmer demo adds potentiometer control, steering diodes, MOSFET/load switching, input/output terminals, wider load traces, and laser-oriented front-copper SVG output.

An important correction was made during this milestone: 45-degree routing is useful for CAD polish and professional style, but it is not a universal electrical hard rule. KiCad DRC, trace width, clearance, current capacity, and connectivity are the real hard gates.

## AI Safety And Review Model

PCBSmith treats AI-generated work as a proposal until validated and approved.

- The AI proposes structured operations.
- PCBSmith checks symbols, footprints, nets, routing assumptions, and design rules.
- KiCad verifies ERC/DRC.
- PCBSmith writes a machine-readable `revision-brief.json` for generated review
  bundles and proposal bundles.
- The user reviews generated visual and manufacturing artifacts.
- Only approved changes should be applied.
- Optional multimodal review can later inspect generated visuals for issues
  such as missing logos, text overlap, unreadable labels, bad centering, and
  mismatch with user intent. It is advisory; KiCad and PCBSmith checks remain
  authoritative.

## Why This Matters

This workflow can help non-expert users create useful electronics while still producing files that can be inspected, edited, manufactured, or rejected using professional tooling.

It also creates a path toward future multimodal workflows, such as giving the AI an image or logo and asking it to place LEDs along that shape, while still generating real KiCad outputs and manufacturing files.

## Next Milestones

Near-term:

- R0 LED art showcase: stronger text/SVG-to-LED boards with current-limiting, input pads, silkscreen, KiCad PCB, Gerbers, drill files, and laser-oriented copper SVG.
- LED electrical grouping: choose series/parallel groups from supply voltage, LED forward voltage, target current, resistor values, and total current warnings.
- KiCad library indexing plus a hierarchical component knowledge layer so the AI can search families first and load deep component profiles only when needed.
- Better AI constraints for current, voltage, trace width, polarity, component choice, and fabrication method.
- More R6 real demos such as sensor breakouts, MOSFET load drivers, regulator/power-entry boards, and addressable LED badges.

Later:

- Image-to-LED PCB workflows.
- Local model support.
- Optional multi-agent AI planning/review.
- Broader KiCad library integration.
- Parametric board features such as capacitive touch pads, PCB coils, antennas, and fabrication-specific outputs.
- Separate silkscreen/artwork features from physical board-shape features:
  logos, text, and labels are printed on silkscreen, while custom outlines,
  cutouts, badge shapes, and edge-connector geometry live on `Edge.Cuts`.
- Simulation hooks for checking circuit behavior where practical.

## Demo Narrative

1. Start with a plain-language user request.
2. Show that PCBSmith converts the request into structured circuit intent.
3. Generate KiCad-native schematic and PCB files.
4. Run KiCad ERC/DRC.
5. Show board SVG and schematic SVG.
6. Show Gerber, drill, and laser front-copper SVG outputs.
7. Explain that the AI is not trusted blindly; it operates constrained tools and KiCad validates the result.
