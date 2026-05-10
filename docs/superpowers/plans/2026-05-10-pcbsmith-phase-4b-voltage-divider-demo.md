# PCBSmith Phase 4B Voltage Divider Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second complete deterministic AI demo circuit and make board traces generic for horizontal chains.

**Architecture:** Extend `ai_demo_plan` with a voltage-divider branch. Refactor the KiCad board exporter so segments are drawn from generated pad coordinates grouped by net, replacing LED-specific trace logic.

**Tech Stack:** Python, KiCad 10 CLI, pytest, ruff.

---

### Task 1: Voltage Divider Plan Contract

**Files:**
- Modify: `tests/unit/services/test_ai_demo_plan.py`

- [x] **Step 1: Write the failing test**

Add a test that calls:

```python
build_ai_demo_plan(_planner_package(request="Create a voltage divider"))
```

Expected plan:

- description `Demo plan: create a voltage divider`;
- VCC, R1 `10k`, R2 `10k`, GND symbols;
- three wires;
- labels `VCC`, `OUT`, `GND`.

- [x] **Step 2: Verify red**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_ai_demo_plan.py::test_build_ai_demo_plan_can_create_voltage_divider -q -p no:cacheprovider --basetemp='.tmp\pytest-phase4b-plan-red'
```

Expected: FAIL because the branch does not exist yet.

### Task 2: Generic Board Trace Contract

**Files:**
- Modify: `tests/unit/services/test_kicad_export.py`

- [x] **Step 1: Add board assertions for voltage-divider fixture**

In `test_export_writes_native_symbols_wires_and_connected_net_labels`, read `board_text` and assert:

```python
assert '(net 1 "OUT")' in board_text
assert '(net 2 "GND")' in board_text
assert '(footprint "PCBSmith_R_0603"' in board_text
assert '(segment (start 14 20) (end 23 20) (width 0.25) (layer "F.Cu") (net 1)' in board_text
assert '(segment (start 31 20) (end 45 20) (width 0.25) (layer "F.Cu") (net 2)' in board_text
```

- [x] **Step 2: Verify red**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_kicad_export.py::test_export_writes_native_symbols_wires_and_connected_net_labels -q -p no:cacheprovider --basetemp='.tmp\pytest-phase4b-board-red'
```

Expected: FAIL because only `LED_A`, VCC, and GND traces are hardcoded.

### Task 3: Implementation

**Files:**
- Modify: `src/pcbsmith/services/ai_demo_plan.py`
- Modify: `src/pcbsmith/services/kicad_export.py`

- [x] **Step 1: Add voltage-divider plan**

Add `_requests_voltage_divider` and `_voltage_divider_plan`. Use stable positions:

```text
VCC: 0 mm
R1: 15.24 mm
R2: 30.48 mm
GND: 45.72 mm
```

Wire VCC to R1 pin 1, R1 pin 2 to R2 pin 1, and R2 pin 2 to GND. Label the middle wire `OUT`.

- [x] **Step 2: Refactor board traces**

Add a small board pad coordinate model. Render segments by grouping generated pads by net number and drawing straight horizontal segments between adjacent pads. This keeps the existing LED board output but also handles `OUT`.

- [x] **Step 3: Verify green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_ai_demo_plan.py tests\unit\services\test_kicad_export.py -q -p no:cacheprovider --basetemp='.tmp\pytest-phase4b-green'
```

Expected: PASS.

### Task 4: KiCad Proof

**Files:**
- Modify only if KiCad reports a real issue.

- [x] **Step 1: Generate voltage-divider review bundle**

Create `.tmp\ai-voltage-divider-v1`, run the AI flow with request text `Create a voltage divider`, and export `.tmp\ai-voltage-divider-review-v1`.

Expected: KiCad validation passes and both schematic and board SVG previews are exported.

- [x] **Step 2: Final checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe tools\dev_check.py
```

Expected: PASS.

### Task 5: Commit

**Files:**
- Stage spec, plan, tests, and implementation.

- [x] **Step 1: Commit and push**

Run:

```powershell
git add docs/superpowers/specs/2026-05-10-pcbsmith-phase-4b-voltage-divider-demo-design.md docs/superpowers/plans/2026-05-10-pcbsmith-phase-4b-voltage-divider-demo.md src/pcbsmith/services/ai_demo_plan.py src/pcbsmith/services/kicad_export.py tests/unit/services/test_ai_demo_plan.py tests/unit/services/test_kicad_export.py
git commit -m "feat: add voltage divider ai demo"
git push
```

Expected: commit reaches `codex/phase-2-component-catalog`.
