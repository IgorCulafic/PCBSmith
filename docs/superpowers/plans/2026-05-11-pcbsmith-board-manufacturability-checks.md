# PCBSmith Board Manufacturability Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight board manufacturability checker for PCBSmith board models.

**Architecture:** Create a focused `board_manufacturability` service that inspects `Board.traces` using `DesignRules`. Add CLI formatting around that service, while keeping KiCad DRC as the authoritative manufacturing gate.

**Tech Stack:** Python, Pydantic/dataclasses, pytest, existing PCBSmith CLI/project I/O.

---

### Task 1: Service Contract

**Files:**
- Create: `src/pcbsmith/services/board_manufacturability.py`
- Test: `tests/unit/services/test_board_manufacturability.py`

- [ ] Write failing tests for non-preferred trace angle, sharp route turn, clearance errors, and a clean board.
- [ ] Implement `ManufacturabilitySeverity`, `BoardManufacturabilityFinding`, `BoardManufacturabilityReport`, `inspect_board_manufacturability`, and `format_board_manufacturability_report`.
- [ ] Verify focused unit tests pass.

### Task 2: CLI Integration

**Files:**
- Modify: `src/pcbsmith/cli.py`
- Test: `tests/integration/test_cli.py`

- [ ] Write failing CLI tests for a clean project and a clearance-risk project.
- [ ] Add `pcbsmith board-check <project>` that loads the first board and project design rules.
- [ ] Print report lines and return exit code 1 only when findings contain errors.
- [ ] Verify focused CLI tests pass.

### Task 3: Demo Guardrail

**Files:**
- Modify: `tests/unit/services/test_circuit_examples.py`

- [ ] Add a regression assertion that the 555 PWM dimmer generated board has no error-severity manufacturability findings.
- [ ] Run focused tests, lint, the demo generator, and `tools/dev_check.py`.
- [ ] Commit and push the checkpoint.
