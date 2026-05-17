# PCBSmith R9 Template Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move reusable R9 circuit blocks into a discoverable template library that AI tools can compose into current projects.

**Architecture:** Create a focused `pcbsmith.templates` package with template metadata, registry lookup, and builders split by domain. Keep `operations.circuit_composer` as the AI-facing composition adapter, but make it call the registry instead of owning all template definitions.

**Tech Stack:** Python 3.12, Pydantic models, existing `CircuitDesign` models, pytest, ruff, mypy.

---

## File Structure

- Create `src/pcbsmith/templates/models.py`: template metadata, template use, and shared reference allocator.
- Create `src/pcbsmith/templates/basic.py`: power input, decoupling capacitor, MOSFET switch, GPIO LED templates.
- Create `src/pcbsmith/templates/led.py`: LED string template.
- Create `src/pcbsmith/templates/registry.py`: template registry, lookup, listing, and composition helpers.
- Create `src/pcbsmith/templates/__init__.py`: public exports.
- Modify `src/pcbsmith/operations/circuit_composer.py`: preserve existing public API while delegating to `pcbsmith.templates.registry`.
- Add `tests/unit/templates/test_registry.py`: registry metadata and composition tests.
- Update `tests/unit/operations/test_circuit_composer.py`: confirm backward-compatible operation behavior.
- Update `docs/roadmap.md`: state R9 templates live in `pcbsmith.templates`.

## Task 1: Template Metadata Registry

- [ ] Write failing tests in `tests/unit/templates/test_registry.py` for listing template metadata, looking up known templates, rejecting unknown templates, and composing repeated `led_string` templates without duplicate references or internal net collisions.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests\unit\templates\test_registry.py -q` and verify it fails because `pcbsmith.templates` does not exist.
- [ ] Add `src/pcbsmith/templates/models.py` with `TemplateParameter`, `TemplateNetPort`, `CircuitTemplate`, `CircuitTemplateUse`, `ReferenceAllocator`, and `CircuitTemplateBuilder`.
- [ ] Add `src/pcbsmith/templates/basic.py`, `src/pcbsmith/templates/led.py`, `src/pcbsmith/templates/registry.py`, and `src/pcbsmith/templates/__init__.py`.
- [ ] Run the focused template tests and verify they pass.

## Task 2: Operation Adapter Delegates To Templates

- [ ] Update `tests/unit/operations/test_circuit_composer.py` to assert `CircuitBlockUse` remains accepted and that block metadata is available through the new registry.
- [ ] Run the operation composer tests and verify any new assertion fails before the adapter change.
- [ ] Refactor `src/pcbsmith/operations/circuit_composer.py` to import and alias `CircuitTemplateUse` as `CircuitBlockUse`, then delegate `compose_circuit_blocks` to `compose_templates`.
- [ ] Run operation composer tests and verify they pass.

## Task 3: Documentation And Verification

- [ ] Update `docs/roadmap.md` R9 section to name `pcbsmith.templates` as the source of truth.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests\unit\templates\test_registry.py tests\unit\operations\test_circuit_composer.py -q`.
- [ ] Run `.\.venv\Scripts\python.exe -m ruff check src tests tools`.
- [ ] Run `.\.venv\Scripts\python.exe -m mypy src`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest -q`.
- [ ] Commit and push.

## Self-Review

The plan covers the approved R9 design: reusable source-controlled template files,
AI-discoverable metadata, repeated composition, and preservation of the current
composer API. There are no placeholders, and every behavior change has a
test-first step.
