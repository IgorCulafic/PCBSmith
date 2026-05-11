# PCBSmith Board Intelligence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reusable board-intelligence rules for net roles, placement frames, and 45-degree mitered routing, then regenerate the 555 demo through those helpers.

**Architecture:** Keep KiCad as the authoritative backend. Add a focused service module that converts intent-level board decisions into deterministic geometry helpers; demos call those helpers rather than hand-writing every copper segment.

**Tech Stack:** Python, Pydantic-free service helpers, existing `KiCadBoardBuilder`, pytest, KiCad CLI validation.

---

### Task 1: Board Intelligence Rules

**Files:**
- Create: `src/pcbsmith/services/board_intelligence.py`
- Test: `tests/unit/services/test_board_intelligence.py`

- [ ] Add tests for net-role classification: `VCC`/`5V` are power, `GND` is ground, `TIMING` is timing, `LED_A` is LED string, `CTRL` is control, and unknown nets are signal.
- [ ] Add tests for `BoardPlacementFrame` converting local board coordinates into review-page coordinates.
- [ ] Implement `NetRole`, `classify_net_role`, and `BoardPlacementFrame`.
- [ ] Run `python -m pytest tests/unit/services/test_board_intelligence.py -q`.

### Task 2: 45-Degree Routing Helpers

**Files:**
- Modify: `src/pcbsmith/services/board_intelligence.py`
- Test: `tests/unit/services/test_board_intelligence.py`

- [ ] Add a test that a right-angle path is expanded into horizontal, 45-degree, vertical, 45-degree, horizontal segments.
- [ ] Add a test that straight routes are unchanged.
- [ ] Implement `mitered_route_points`, `route_segments`, and `segment_angle_degrees`.
- [ ] Run `python -m pytest tests/unit/services/test_board_intelligence.py -q`.

### Task 3: 555 Demo Refactor

**Files:**
- Modify: `src/pcbsmith/services/circuit_examples.py`
- Modify: `tests/unit/services/test_circuit_examples.py`

- [ ] Refactor `_render_timer_555_astable_board` to use `BoardPlacementFrame` and `mitered_route_points`.
- [ ] Add a test assertion that the generated 555 board contains diagonal 45-degree copper segments.
- [ ] Preserve KiCad ERC/DRC clean output.
- [ ] Run focused circuit example tests.

### Task 4: Verify Generated Output

**Files:**
- Generated review bundle under `.tmp/`

- [ ] Run `tools/generate_schematic_backed_555_astable_demo.py` into a new timestamped output folder.
- [ ] Confirm KiCad reports `ERC: passed (0 violations)` and `DRC: passed (0 violations, 0 unconnected)`.
- [ ] Run `tools/dev_check.py`.
- [ ] Commit and push the milestone.
