# PCBSmith Phase 1 AI Design Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first AI-facing operation that turns a structured LED-art request into a KiCad review bundle through reusable PCBSmith services.

**Architecture:** Keep the board-generation rules in `pcbsmith.services.led_art` and `pcbsmith.services.led_art_board`. Add a thin operation service that validates request fields, writes the KiCad project/reports/operation summary, and optionally runs KiCad validation and preview exports. Add a CLI wrapper for local and future AI use.

**Tech Stack:** Python, Pydantic, argparse CLI, existing KiCad project/validation/preview helpers.

---

### Task 1: Add LED-Art Operation Service

**Files:**
- Create: `src/pcbsmith/services/design_operations.py`
- Test: `tests/unit/services/test_design_operations.py`

- [x] **Step 1: Write failing tests**

Test that a request writes a KiCad project, board file, reports, README, and machine-readable operation summary without invoking KiCad execution.

- [x] **Step 2: Implement request/result models**

Define `LedArtDesignRequest`, `DesignOperationResult`, and helpers for request validation and output file layout.

- [x] **Step 3: Implement generation**

Use `build_led_art_plan_for_topology`, `render_led_art_board`, `render_kicad_project_file`, `render_kicad_schematic_file`, and LED-art report writers.

### Task 2: Add CLI Command

**Files:**
- Modify: `src/pcbsmith/cli.py`
- Test: `tests/integration/test_cli.py`

- [x] **Step 1: Write failing CLI test**

Test `pcbsmith design-led-art <output> --text VIR-LAB --voltage 12 --control low_side_mosfet --skip-execution`.

- [x] **Step 2: Add command wrapper**

Wire CLI args into `LedArtDesignRequest` and print stable output paths plus validation/preview status.

### Task 3: Verify And Commit

**Files:**
- Modify: `docs/roadmap.md`
- Modify: `docs/project-handoff.md`

- [x] **Step 1: Update docs**

Record that Phase 1 has a structured LED-art operation path and no longer depends on one-off scripts.

- [x] **Step 2: Run checks**

Run targeted tests, full pytest, and ruff on changed files.
