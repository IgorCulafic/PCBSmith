# PCBSmith 555 PWM Dimmer Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DRC-clean KiCad-native NE555 PWM LED dimmer demo that introduces potentiometer behavior, steering diodes, MOSFET/load switching, input/output terminals, and wider load routing.

**Architecture:** Extend the existing deterministic circuit examples rather than adding a free-form planner. Keep KiCad as the authoritative output and use the board intelligence routing helpers for style preferences and trace widths. Add a small generator script that mirrors the existing 555 astable review-bundle flow.

**Tech Stack:** Python, existing PCBSmith project models, `KiCadBoardBuilder`, KiCad CLI validation, pytest, ruff.

---

### Task 1: Document The Project Lessons

**Files:**
- Create: `docs/project-decision-log.md`
- Create: `docs/presentation-brief.md`

- [x] Add a concise internal decision log for architecture choices, mistakes, corrections, routing policy, and current capabilities.
- [x] Add a presentation-facing brief that explains PCBSmith, the KiCad-first pivot, current outputs, validation model, and next milestones.

### Task 2: Add PWM Circuit API And Tests

**Files:**
- Modify: `tests/unit/services/test_circuit_examples.py`
- Modify: `src/pcbsmith/services/circuit_examples.py`

- [x] Add a failing test for `Timer555PwmDimmerCircuit`, `create_timer_555_pwm_dimmer_project`, and `export_timer_555_pwm_dimmer_kicad_project`.
- [x] Verify the test fails because the PWM API does not exist.
- [x] Implement the minimal circuit model, source project generation, and KiCad project export.
- [x] Verify the test passes.

### Task 3: Add PWM Board Geometry

**Files:**
- Modify: `src/pcbsmith/services/kicad_board_builder.py`
- Modify: `src/pcbsmith/services/circuit_examples.py`
- Modify: `tests/unit/services/test_circuit_examples.py`

- [x] Add or reuse board-builder primitives for a three-pad control/load footprint.
- [x] Generate a board containing NE555, timing passives, two steering diodes, a potentiometer footprint, gate resistor, pulldown, MOSFET footprint, input pads, output pads, silkscreen labels, and wider load traces.
- [x] Verify the generated board text includes MOSFET/load nets, diode footprints, and wide power/load trace widths.

### Task 4: Add Review Bundle Generator

**Files:**
- Create: `tools/generate_555_pwm_dimmer_demo.py`

- [x] Add a generator script matching the existing 555 astable script shape.
- [x] Generate `.tmp/555-pwm-dimmer-demo-YYYYMMDD-NN/kicad-review`.
- [x] Write AI context, SVG previews, Gerbers, drill files, and laser F.Cu SVG through existing KiCad preview tooling.

### Task 5: Verify And Commit

**Files:**
- Generated output under `.tmp/`

- [x] Run focused tests and ruff checks.
- [x] Run the PWM generator with KiCad CLI.
- [x] Confirm `ERC: passed` and `DRC: passed`.
- [x] Run `tools/dev_check.py`.
- [ ] Commit and push the milestone.
