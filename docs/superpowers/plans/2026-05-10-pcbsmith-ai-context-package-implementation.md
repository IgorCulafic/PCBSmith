# PCBSmith AI Context Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a read-only JSON context package for future AI review of PCBSmith/KiCad projects.

**Architecture:** Add a focused `ai_context` service that loads project files, summarizes schematic state, optionally reads KiCad report and visual output folders, and writes deterministic JSON. Expose the service through a `kicad-context` CLI command.

**Tech Stack:** Python 3.12, pytest, ruff, existing PCBSmith project I/O.

---

## File Structure

- Create: `src/pcbsmith/services/ai_context.py`
- Create: `tests/unit/services/test_ai_context.py`
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `README.md`

## Task 1: Context Service

- [x] **Step 1: Write failing unit tests**

Tests cover project/schematic summaries, optional KiCad report/visual references, and JSON writing.

- [x] **Step 2: Verify red**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_ai_context.py -q -p no:cacheprovider --basetemp='.tmp\pytest-ai-context-red'
```

Expected: fails because `pcbsmith.services.ai_context` does not exist.

- [x] **Step 3: Implement service**

Create `build_ai_context()` and `write_ai_context()`.

- [x] **Step 4: Verify green**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_ai_context.py -q -p no:cacheprovider --basetemp='.tmp\pytest-ai-context-green'
```

## Task 2: CLI Command

- [x] **Step 1: Write failing CLI tests**

Tests cover `kicad-context <project> <output>` and `--kicad-project`.

- [x] **Step 2: Verify red**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_cli.py::test_kicad_context_writes_ai_context_package tests\integration\test_cli.py::test_kicad_context_can_include_kicad_project_refs -q -p no:cacheprovider --basetemp='.tmp\pytest-ai-context-cli-red'
```

- [x] **Step 3: Wire CLI**

Add `_cmd_kicad_context` and parser registration.

- [x] **Step 4: Verify green**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_cli.py::test_kicad_context_writes_ai_context_package tests\integration\test_cli.py::test_kicad_context_can_include_kicad_project_refs -q -p no:cacheprovider --basetemp='.tmp\pytest-ai-context-cli-green'
```

## Task 3: Docs And Verification

- [x] **Step 1: Update README**

Document `kicad-context` and `--kicad-project`.

- [x] **Step 2: Run focused and full checks**

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp='.tmp\pytest-ai-context-full'
```
