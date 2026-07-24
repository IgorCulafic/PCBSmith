# PCBSmith R0 LED Art Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing VIR-LAB demo into the first reusable R0 LED-art foundation with text-to-pixel layout and an electrical review report.

**Architecture:** Add a focused `led_art` service that owns text glyph layout, LED pixel references, resistor selection, per-string current estimates, and review report writing. Keep the KiCad board rendering in the existing VIR-LAB tool for this slice, but make that tool consume the reusable service and write LED-art electrical reports into the review bundle.

**Tech Stack:** Python, Pydantic models, pytest, existing `KiCadBoardBuilder`, existing VIR-LAB KiCad generator.

---

### Task 1: LED Art Planning Service

**Files:**
- Create: `src/pcbsmith/services/led_art.py`
- Test: `tests/unit/services/test_led_art.py`

- [ ] **Step 1: Write failing layout and electrical tests**

Add tests that import `LedArtSpec`, `build_led_art_plan`, and `select_led_resistor_ohms`. Assert that `VIR-LAB` produces LED pixels, stable `R1`/`LED1` references, 680 ohm default resistors for 5 V red LEDs at 5 mA target current, and a high-current warning for the whole VIR-LAB board.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
uv run --python 3.12 --extra dev python -m pytest tests/unit/services/test_led_art.py -q
```

Expected: import failure because `pcbsmith.services.led_art` does not exist.

- [ ] **Step 3: Implement the service**

Create `LedArtSpec`, `LedArtPixel`, `LedArtString`, `LedArtElectricalReport`, `LedArtPlan`, `select_led_resistor_ohms`, `build_led_art_plan`, and `write_led_art_reports`.

The service should:

- support `VIR-LAB` and other text using the current 5x7 uppercase glyphs;
- generate one pixel per lit glyph cell;
- keep one LED plus one resistor per string for this first R0 slice;
- calculate resistor value, string current, total current, and total estimated power;
- warn when total current exceeds `usb_warning_current_ma`;
- expose board width/height hints derived from the rendered text.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
uv run --python 3.12 --extra dev python -m pytest tests/unit/services/test_led_art.py -q
```

Expected: all tests in `test_led_art.py` pass.

### Task 2: Wire The VIR-LAB Generator To The Service

**Files:**
- Modify: `tools/generate_vir_lab_led_demo.py`
- Test: `tests/unit/services/test_led_art.py`

- [ ] **Step 1: Add failing report-writing test**

Extend `test_led_art.py` to call `write_led_art_reports` and assert that JSON and Markdown reports include the schema, text, resistor value, total LED count, total current, grouping strategy, and warning.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
uv run --python 3.12 --extra dev python -m pytest tests/unit/services/test_led_art.py::test_write_led_art_reports_writes_json_and_markdown -q
```

Expected: failure until report-writing behavior exists.

- [ ] **Step 3: Update the generator**

Replace the local glyph and pixel model in `generate_vir_lab_led_demo.py` with `build_led_art_plan`. Keep the existing board appearance and KiCad exports, but write reports to:

- `.pcbsmith/reports/led-art-electrical.json`
- `.pcbsmith/reports/led-art-electrical.md`

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
uv run --python 3.12 --extra dev python -m pytest tests/unit/services/test_led_art.py -q
```

Expected: all LED-art service tests pass.

### Task 3: Generate And Validate A New R0 Output

**Files:**
- Runtime output only: `.tmp/r0-led-art-foundation-20260512-01/kicad-review`

- [ ] **Step 1: Run the generator**

Run:

```powershell
$env:PCBSMITH_KICAD_CLI = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
uv run --python 3.12 --extra dev python tools/generate_vir_lab_led_demo.py --output .tmp/r0-led-art-foundation-20260512-01/kicad-review --name "R0 VIR LAB LED Art"
```

Expected: KiCad ERC/DRC and preview exports complete without a nonzero exit.

- [ ] **Step 2: Inspect output files**

Confirm these files exist:

- `.tmp/r0-led-art-foundation-20260512-01/kicad-review/.pcbsmith/reports/led-art-electrical.json`
- `.tmp/r0-led-art-foundation-20260512-01/kicad-review/.pcbsmith/reports/led-art-electrical.md`
- `.tmp/r0-led-art-foundation-20260512-01/kicad-review/.pcbsmith/visual/R0_VIR_LAB_LED_Art-board.svg`
- `.tmp/r0-led-art-foundation-20260512-01/kicad-review/R0_VIR_LAB_LED_Art.kicad_pcb`

- [ ] **Step 3: Run regression checks**

Run:

```powershell
uv run --python 3.12 --extra dev python -m pytest tests/unit/services/test_led_art.py tests/unit/services/test_circuit_examples.py -q
ruff check src tests tools
```

Expected: tests pass and Ruff reports no issues.

### Task 4: Commit And Push

**Files:**
- `src/pcbsmith/services/led_art.py`
- `tests/unit/services/test_led_art.py`
- `tools/generate_vir_lab_led_demo.py`
- `docs/superpowers/plans/2026-05-12-pcbsmith-r0-led-art-foundation.md`

- [ ] **Step 1: Review diff**

Run:

```powershell
git diff --check
git status --short
```

Expected: no diff check errors; only intentional files modified.

- [ ] **Step 2: Commit**

Run:

```powershell
git add src/pcbsmith/services/led_art.py tests/unit/services/test_led_art.py tools/generate_vir_lab_led_demo.py docs/superpowers/plans/2026-05-12-pcbsmith-r0-led-art-foundation.md
git commit -m "feat: add R0 LED art planning report"
```

- [ ] **Step 3: Push**

Run:

```powershell
git push
```

Expected: branch `codex/phase-2-component-catalog` pushes to GitHub.

## Self-Review

- Spec coverage: Covers R0.1 static text-to-LED layout foundation and R0.2 first electrical grouping/reporting step.
- Placeholder scan: No placeholder steps; commands and file paths are explicit.
- Type consistency: `LedArtSpec`, `LedArtPixel`, `LedArtString`, `LedArtElectricalReport`, and `LedArtPlan` are introduced in Task 1 and reused consistently.
