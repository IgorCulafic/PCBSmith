# PCBSmith Layer-Aware Board Groundwork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit board-layer capabilities and simple top-silkscreen text to generated KiCad review boards.

**Architecture:** Keep KiCad as the renderer and validator. Extend `kicad_export` with small board-layer constants and a KiCad-native `gr_text` renderer, then expose the supported layer list through `ai_context`.

**Tech Stack:** Python, pytest, KiCad `.kicad_pcb` text generation, existing PCBSmith CLI/review bundle.

---

## File Structure

- Modify `src/pcbsmith/services/kicad_export.py`: define board layer constants, use them for copper segments and silkscreen, and emit a `PCBSmith Demo` `gr_text` item when a board has footprints.
- Modify `src/pcbsmith/services/ai_context.py`: expose board layer metadata in the optional KiCad context block.
- Modify `tests/unit/services/test_kicad_export.py`: assert the generated board contains top silkscreen text and no generated back-copper routing.
- Modify `tests/unit/services/test_ai_context.py`: assert the KiCad context includes supported board layers.

## Task 1: Export Silkscreen Text and Named Layers

**Files:**
- Modify: `tests/unit/services/test_kicad_export.py`
- Modify: `src/pcbsmith/services/kicad_export.py`

- [ ] **Step 1: Write the failing board export assertions**

Add assertions to `test_export_writes_visible_led_series_circuit_fixture`:

```python
    assert '(gr_text "PCBSmith Demo"' in board_text
    assert '(layer "F.SilkS")' in board_text
    assert '(layer "B.Cu") (net' not in board_text
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_kicad_export.py::test_export_writes_visible_led_series_circuit_fixture -q -p no:cacheprovider --basetemp .tmp\pytest-layer-groundwork-red
```

Expected: FAIL because the generated board does not contain `gr_text "PCBSmith Demo"`.

- [ ] **Step 3: Implement minimal board-layer constants and silkscreen renderer**

In `src/pcbsmith/services/kicad_export.py`, add constants:

```python
KICAD_LAYER_FRONT_COPPER = "F.Cu"
KICAD_LAYER_BACK_COPPER = "B.Cu"
KICAD_LAYER_FRONT_SILK = "F.SilkS"
KICAD_LAYER_BACK_SILK = "B.SilkS"
KICAD_LAYER_EDGE_CUTS = "Edge.Cuts"
```

Use `KICAD_LAYER_FRONT_COPPER` in `_render_board_segment`, use `KICAD_LAYER_FRONT_SILK` in footprint reference properties and silkscreen text, and add `_render_board_silkscreen_text(...)` that emits KiCad `gr_text`.

- [ ] **Step 4: Run focused export tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_kicad_export.py -q -p no:cacheprovider --basetemp .tmp\pytest-layer-groundwork-export
```

Expected: all `test_kicad_export.py` tests pass.

## Task 2: Expose Layer Capabilities in AI Context

**Files:**
- Modify: `tests/unit/services/test_ai_context.py`
- Modify: `src/pcbsmith/services/ai_context.py`

- [ ] **Step 1: Write the failing AI context assertion**

Update `test_build_ai_context_includes_kicad_reports_and_visual_refs` so `context["kicad"]` includes:

```python
        "board_layers": [
            {"id": "F.Cu", "role": "front_copper", "routing": True},
            {"id": "B.Cu", "role": "back_copper", "routing": False},
            {"id": "F.SilkS", "role": "front_silkscreen", "routing": False},
            {"id": "B.SilkS", "role": "back_silkscreen", "routing": False},
            {"id": "Edge.Cuts", "role": "board_outline", "routing": False},
        ],
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_ai_context.py::test_build_ai_context_includes_kicad_reports_and_visual_refs -q -p no:cacheprovider --basetemp .tmp\pytest-layer-groundwork-context-red
```

Expected: FAIL because `board_layers` is missing.

- [ ] **Step 3: Implement the AI context metadata**

In `src/pcbsmith/services/ai_context.py`, add a private `_board_layers()` helper returning the layer list above and include it in `_kicad_context(...)`.

- [ ] **Step 4: Run focused context tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_ai_context.py -q -p no:cacheprovider --basetemp .tmp\pytest-layer-groundwork-context
```

Expected: all `test_ai_context.py` tests pass.

## Task 3: Verify and Produce Review Artifact

**Files:**
- No source changes expected beyond Tasks 1 and 2.

- [ ] **Step 1: Run lint and focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_kicad_export.py tests\unit\services\test_ai_context.py -q -p no:cacheprovider --basetemp .tmp\pytest-layer-groundwork-focused
```

Expected: ruff passes and focused tests pass.

- [ ] **Step 2: Run the full dev check**

Run:

```powershell
$env:PCBSMITH_KICAD_CLI = 'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe'
.\.venv\Scripts\python.exe tools\dev_check.py
```

Expected: dev check completes successfully.

- [ ] **Step 3: Generate a fresh visual bundle**

Run:

```powershell
$env:PCBSMITH_KICAD_CLI = 'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe'
.\.venv\Scripts\python.exe -m pcbsmith.cli new .tmp\visual-proposal-source-layer-groundwork-20260511 --name "Layer Groundwork Demo"
.\.venv\Scripts\python.exe -m pcbsmith.cli ai-proposal-bundle .tmp\visual-proposal-source-layer-groundwork-20260511 .tmp\dev-check-ai-planner-package.json .tmp\dev-check-candidate-plan.json .tmp\visual-ai-proposal-layer-groundwork-20260511
```

Expected: validation passes and SVG previews are exported.

- [ ] **Step 4: Commit and push**

Run:

```powershell
git add docs/superpowers/plans/2026-05-11-pcbsmith-layer-aware-board-groundwork.md src/pcbsmith/services/kicad_export.py src/pcbsmith/services/ai_context.py tests/unit/services/test_kicad_export.py tests/unit/services/test_ai_context.py
git commit -m "feat: add layer-aware board groundwork"
git push
```
