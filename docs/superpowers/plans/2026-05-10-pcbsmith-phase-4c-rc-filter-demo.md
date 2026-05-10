# PCBSmith Phase 4C RC Filter Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an RC low-pass filter deterministic demo and preserve visible user-facing net labels.

**Architecture:** Extend `ai_demo_plan` with an RC filter branch before the generic capacitor fallback. Adjust the KiCad exporter label rule so internal helper labels are hidden but `OUT` remains visible.

**Tech Stack:** Python, KiCad 10 CLI, pytest, ruff.

---

### Task 1: Tests

**Files:**
- Modify: `tests/unit/services/test_ai_demo_plan.py`
- Modify: `tests/unit/services/test_kicad_export.py`

- [x] **Step 1: Add RC filter planner test**

Assert `Create an RC low-pass filter` produces VCC, R, C, GND, three wires, and labels `VCC`, `OUT`, `GND`.

- [x] **Step 2: Add visible OUT label export test**

Create a minimal RC filter schematic in the exporter test and assert the schematic contains visible `(label "OUT"` while `LED_A` remains hidden in the LED fixture test.

### Task 2: Implementation

**Files:**
- Modify: `src/pcbsmith/services/ai_demo_plan.py`
- Modify: `src/pcbsmith/services/kicad_export.py`

- [x] **Step 1: Add RC filter detection and plan**

Recognize `rc filter`, `low-pass`, and `low pass` before the generic capacitor branch. Use R1 `10k`, C1 `100nF`, and net label `OUT`.

- [x] **Step 2: Adjust hidden label rule**

Hide interior wire labels only when they look internal, currently names containing `_`. Keep labels such as `OUT` visible even if placed on a wire interior.

### Task 3: KiCad Proof

**Files:**
- Modify only if KiCad reports an issue.

- [x] **Step 1: Generate RC filter review bundle**

Create `.tmp\ai-rc-filter-v1` from request `Create an RC low-pass filter` and export `.tmp\ai-rc-filter-review-v1`.

Expected: KiCad validation passes and both SVG previews export.

- [x] **Step 2: Run checks**

Run focused tests, `ruff`, and `tools/dev_check.py`.

### Task 4: Commit

**Files:**
- Stage spec, plan, tests, and implementation.

- [x] **Step 1: Commit and push**

Commit with `feat: add rc filter ai demo` and push to `codex/phase-2-component-catalog`.
