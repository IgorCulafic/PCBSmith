# PCBSmith R0 LED Branch Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LED-art topology planner that compares resistor-per-LED, 5 V two-LED branches, and 12 V denser series branches before physical routing changes.

**Architecture:** Extend `pcbsmith.services.led_art` with topology option models and comparison helpers. Keep the existing VIR-LAB board renderer as resistor-per-LED for now, but add a topology comparison report beside the electrical report so the next board-generation slice can route a selected topology honestly.

**Tech Stack:** Python, Pydantic models, pytest, existing LED-art generator.

---

### Task 1: Topology Comparison Models

**Files:**
- Modify: `src/pcbsmith/services/led_art.py`
- Modify: `tests/unit/services/test_led_art.py`

- [ ] **Step 1: Write failing topology tests**

Add tests for `compare_led_art_topologies`. The tests should assert:

- 5 V one-led-per-resistor uses one LED per string and 680 ohm resistors.
- 5 V dense mode uses two LEDs per string and 220 ohm resistors.
- 12 V dense mode uses five LEDs per string and 470 ohm resistors.
- For 100 LEDs, the 12 V dense option uses 20 strings and about 100 mA total.
- The recommended option for `density` is the 12 V dense profile.

- [ ] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_led_art.py -q
```

Expected: failure because `compare_led_art_topologies` does not exist.

- [ ] **Step 3: Implement topology models and comparison helper**

Add:

- `LedArtTopologyOption`
- `LedArtTopologyComparison`
- `compare_led_art_topologies`

Use a minimum resistor headroom of 1 V when calculating dense series branch size:

```python
max_series_leds = floor((supply_voltage_v - 1.0) / led_forward_voltage_v)
```

Clamp branch size to at least 1. Use the existing E12 resistor selector.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_led_art.py -q
```

Expected: all LED-art tests pass.

### Task 2: Write Topology Comparison Reports

**Files:**
- Modify: `src/pcbsmith/services/led_art.py`
- Modify: `tools/generate_vir_lab_led_demo.py`
- Modify: `tests/unit/services/test_led_art.py`

- [ ] **Step 1: Write failing report test**

Add a test for `write_led_art_topology_comparison_reports`. Assert JSON and Markdown are written and include 5 V, 12 V, dense, branch count, resistor values, and the recommended profile.

- [ ] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_led_art.py::test_write_led_art_topology_comparison_reports -q
```

Expected: failure because the writer does not exist.

- [ ] **Step 3: Implement writer and wire generator**

Write:

- `.pcbsmith/reports/led-art-topology-comparison.json`
- `.pcbsmith/reports/led-art-topology-comparison.md`

The generator should still route the existing board as one resistor per LED, and the Markdown should explicitly say the dense options are planning alternatives for the next physical layout slice.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_led_art.py -q
```

Expected: all LED-art tests pass.

### Task 3: Generate R0 Topology Output

**Files:**
- Runtime output only: `.tmp/r0-led-topology-20260512-01/kicad-review`

- [ ] **Step 1: Regenerate the VIR-LAB bundle**

Run:

```powershell
$env:PCBSMITH_KICAD_CLI = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
.\.venv\Scripts\python.exe tools\generate_vir_lab_led_demo.py --output .tmp\r0-led-topology-20260512-01\kicad-review --name "R0 VIR LAB LED Topology"
```

Expected: KiCad ERC/DRC and preview exports pass.

- [ ] **Step 2: Inspect generated reports**

Confirm these files exist:

- `.tmp/r0-led-topology-20260512-01/kicad-review/.pcbsmith/reports/led-art-electrical.json`
- `.tmp/r0-led-topology-20260512-01/kicad-review/.pcbsmith/reports/led-art-topology-comparison.json`
- `.tmp/r0-led-topology-20260512-01/kicad-review/.pcbsmith/reports/led-art-topology-comparison.md`

Confirm the Markdown recommends the 12 V dense profile for density.

### Task 4: Verification And Commit

**Files:**
- `src/pcbsmith/services/led_art.py`
- `tests/unit/services/test_led_art.py`
- `tools/generate_vir_lab_led_demo.py`
- `docs/superpowers/plans/2026-05-12-pcbsmith-r0-led-branch-topology.md`

- [ ] **Step 1: Run checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_led_art.py tests/unit/services/test_circuit_examples.py -q
ruff check src tests tools
git diff --check
```

Expected: tests pass, Ruff passes, diff check passes.

- [ ] **Step 2: Commit**

Run:

```powershell
git add src/pcbsmith/services/led_art.py tests/unit/services/test_led_art.py tools/generate_vir_lab_led_demo.py docs/superpowers/plans/2026-05-12-pcbsmith-r0-led-branch-topology.md
git commit -m "feat: add LED art topology comparison"
```

- [ ] **Step 3: Push**

Run:

```powershell
git push
```

Expected: branch pushes to GitHub.

## Self-Review

- Spec coverage: Covers 5 V and 12 V branch topology comparison without claiming the physical board already uses those branches.
- Placeholder scan: No TBD/TODO placeholders.
- Type consistency: Topology model and writer names are introduced before use.
