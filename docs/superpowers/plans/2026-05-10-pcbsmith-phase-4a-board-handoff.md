# PCBSmith Phase 4A Board Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a KiCad-native board preview for the approved LED demo circuit.

**Architecture:** Extend the existing KiCad exporter so the schematic-derived native symbols also produce a compact `.kicad_pcb`. Keep footprints embedded and deterministic, then let the existing KiCad review bundle export the board SVG.

**Tech Stack:** Python, Pydantic models, KiCad 10 CLI, pytest, ruff.

---

### Task 1: Board Export Contract

**Files:**
- Modify: `tests/unit/services/test_kicad_export.py`

- [x] **Step 1: Write the failing test**

Add assertions to `test_export_writes_visible_led_series_circuit_fixture` that read the generated board file and require:

```python
board_text = result.skeleton.board_file.read_text(encoding="utf-8")
assert '(net 1 "VCC")' in board_text
assert '(net 2 "LED_A")' in board_text
assert '(net 3 "GND")' in board_text
assert '(footprint "PCBSmith_R_0603")' in board_text
assert '(footprint "PCBSmith_LED_0603")' in board_text
assert '(footprint "PCBSmith_POWER_PAD"' in board_text
assert '(property "Reference" "R1"' in board_text
assert '(property "Reference" "LED1"' in board_text
assert '(pad "1" smd roundrect' in board_text
assert '(net 1 "VCC")' in board_text
assert '(segment (start 14 20) (end 23 20) (width 0.25) (layer "F.Cu") (net 2)' in board_text
assert '(gr_rect' in board_text
assert '(end 50 35)' in board_text
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_kicad_export.py::test_export_writes_visible_led_series_circuit_fixture -q -p no:cacheprovider --basetemp='.tmp\pytest-phase4a-red'
```

Expected: FAIL because the board skeleton has no footprints, nets, or traces.

### Task 2: Minimal Embedded Board Renderer

**Files:**
- Modify: `src/pcbsmith/services/kicad_export.py`
- Modify: `src/pcbsmith/services/kicad_project.py`

- [x] **Step 1: Add board body support**

Change `render_kicad_board_file` to accept optional `board_body_items: Sequence[str] = ()` and a smaller outline end point `(50 35)` when body items are passed.

- [x] **Step 2: Render supported footprints**

In `kicad_export`, derive supported non-power native symbols and render generic embedded two-pad footprints:

```python
VCC/GND -> footprint "PCBSmith_POWER_PAD"
R1 -> footprint "PCBSmith_R_0603"
LED1 -> footprint "PCBSmith_LED_0603"
```

Each component footprint should include reference/value text and two SMD pads with net assignments. Each power terminal footprint should include one SMD pad with a net assignment.

- [x] **Step 3: Render board nets and traces**

For the LED demo, derive the same net names as the schematic:

```text
VCC: VCC symbol pin to R1 pin 1
LED_A: R1 pin 2 to LED1 pin 1
GND: LED1 pin 2 to GND symbol pin
```

Render net declarations and simple front-copper segments. It is acceptable for this phase to support only horizontal two-pin chains.

- [x] **Step 4: Write the board during export**

After writing the schematic, overwrite `skeleton.board_file` with `render_kicad_board_file(..., board_body_items=...)`.

### Task 3: Verify With KiCad

**Files:**
- Modify only if tests expose a bug.

- [x] **Step 1: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_kicad_export.py tests\unit\services\test_kicad_review_bundle.py tests\unit\services\test_kicad_preview.py -q -p no:cacheprovider --basetemp='.tmp\pytest-phase4a-focused'
```

Expected: PASS.

- [x] **Step 2: Generate a real review bundle**

Run the existing AI LED demo flow into `.tmp\ai-led-board-v1`, then run `kicad-review-bundle`.

Expected: validation passes and both schematic and board SVG previews are exported.

- [x] **Step 3: Run project checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe tools\dev_check.py
```

Expected: PASS.

### Task 4: Commit

**Files:**
- Stage the spec, plan, exporter, project renderer, and tests.

- [x] **Step 1: Commit and push**

Run:

```powershell
git add docs/superpowers/specs/2026-05-10-pcbsmith-phase-4a-board-handoff-design.md docs/superpowers/plans/2026-05-10-pcbsmith-phase-4a-board-handoff.md src/pcbsmith/services/kicad_export.py src/pcbsmith/services/kicad_project.py tests/unit/services/test_kicad_export.py
git commit -m "feat: add kicad board preview handoff"
git push
```

Expected: commit reaches `codex/phase-2-component-catalog`.
