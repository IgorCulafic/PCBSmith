# VIR-LAB Demo Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the generated VIR-LAB 5V LED board demo so the board preview shows visible resistor bodies, denser LED lettering, and no misleading blank schematic preview.

**Architecture:** Keep this as a focused generator update in `tools/generate_vir_lab_led_demo.py`. The generated KiCad PCB remains the authoritative artifact; preview-only readability improvements use KiCad drawing layers without polluting fabrication layers.

**Tech Stack:** Python generator, KiCad PCB/SVG/Gerber CLI exports, PCBSmith validation/preview services.

---

### Task 1: Denser VIR-LAB LED Matrix

**Files:**
- Modify: `tools/generate_vir_lab_led_demo.py`

- [ ] Replace the current 3x5 `LETTER_PATTERNS` with 5x7 patterns for `VIR-LAB`.
- [ ] Increase board width and spacing so DRC clearances remain valid.
- [ ] Regenerate the demo and confirm KiCad DRC still passes.

### Task 2: Visible Preview Resistor Bodies

**Files:**
- Modify: `tools/generate_vir_lab_led_demo.py`

- [ ] Add resistor/LED body rectangles on `F.Fab`, not `F.SilkS`, so fabrication silkscreen remains DRC-clean.
- [ ] Export an additional preview SVG with `F.Cu,F.Fab,F.SilkS,Edge.Cuts`.
- [ ] Leave Gerber exports unchanged.

### Task 3: Schematic Output Clarity

**Files:**
- Modify: `tools/generate_vir_lab_led_demo.py`

- [ ] Keep the KiCad schematic file minimal for now.
- [ ] Stop treating the blank schematic SVG as a review artifact for this layout-generated demo.
- [ ] Write a short generated `README.md` in the output folder explaining that this is PCB-layout-first and schematic hierarchy is a later feature.

### Task 4: Verification and Commit

**Files:**
- Modify: `tools/generate_vir_lab_led_demo.py`
- Create: generated output under `.tmp/vir-lab-led-demo-20260511-03/kicad-review`

- [ ] Run `python tools/generate_vir_lab_led_demo.py --output .tmp\vir-lab-led-demo-20260511-03\kicad-review`.
- [ ] Run `python tools/dev_check.py`.
- [ ] Commit and push the generator plus this plan.
