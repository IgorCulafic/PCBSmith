# PCBSmith R0 Dense LED Boards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate physical VIR-LAB LED art boards for the dense 5 V and 12 V branch topologies already identified by the topology planner.

**Architecture:** Extend `led_art` so a selected topology produces real branch strings in the plan, then update the VIR-LAB generator to render one resistor per string and series LEDs per branch. Keep the existing one-resistor-per-LED topology available as the simple/debug option.

**Tech Stack:** Python, Pydantic, pytest, KiCad CLI, existing `KiCadBoardBuilder`.

---

### Task 1: Topology-Specific Plans

**Files:**
- Modify: `src/pcbsmith/services/led_art.py`
- Modify: `tests/unit/services/test_led_art.py`

- [x] Write failing tests for `build_led_art_plan_for_topology`.
- [x] Verify RED with `.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_led_art.py -q`.
- [x] Implement topology-specific string grouping.
- [x] Verify GREEN.

### Task 2: Physical Board Rendering

**Files:**
- Modify: `tools/generate_vir_lab_led_demo.py`
- Modify: `tests/unit/services/test_led_art.py`

- [x] Add CLI `--topology` with `5v_one_per_led`, `5v_two_led_dense`, and `12v_dense`.
- [x] Render one resistor per string and LED nets in series for dense topology plans.
- [x] Label the board with topology, supply voltage, resistor value, and LEDs per branch.
- [x] Keep existing simple output as the default for compatibility.

### Task 3: Generate Variants

**Files:**
- Runtime output only under `.tmp`.

- [x] Generate 5 V dense output.
- [x] Generate 12 V dense output.
- [x] Confirm KiCad ERC/DRC passes for both.
- [x] Confirm board SVG, assembly SVG, Gerbers, drill, and laser F.Cu SVG export.

### Task 4: Verification And Commit

**Files:**
- `src/pcbsmith/services/led_art.py`
- `tests/unit/services/test_led_art.py`
- `tools/generate_vir_lab_led_demo.py`
- `docs/superpowers/plans/2026-05-12-pcbsmith-r0-dense-led-boards.md`

- [x] Run focused pytest and Ruff.
- [x] Run `git diff --check`.
- [ ] Commit and push.
