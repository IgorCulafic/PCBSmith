# PCBSmith KiCad Approval Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a dry-run/apply approval loop for structured schematic command packages.

**Architecture:** Create a focused `kicad_plan` service that parses command-package JSON, applies existing schematic commands only when requested, and writes append-only action logs. Expose it through a `kicad-plan` CLI command without coupling it to KiCad export or validation yet.

**Tech Stack:** Python 3.12, Pydantic, pytest, existing PCBSmith project I/O and schematic command services.

---

## File Structure

- Create: `src/pcbsmith/services/kicad_plan.py`
- Create: `tests/unit/services/test_kicad_plan.py`
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `README.md`

## Task 1: Command Package Service

**Files:**
- Create: `src/pcbsmith/services/kicad_plan.py`
- Create: `tests/unit/services/test_kicad_plan.py`

- [x] **Step 1: Write failing service tests**

Cover package parsing, dry-run no-op behavior, apply behavior, and action-log JSONL.

- [x] **Step 2: Run service tests red**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_kicad_plan.py -q -p no:cacheprovider --basetemp='.tmp\pytest-kicad-plan-red'
```

Expected: fail because `pcbsmith.services.kicad_plan` does not exist.

- [x] **Step 3: Implement service**

Create immutable models for `KiCadPlanPackage`, `KiCadPlanCommand`, `KiCadPlanResult`, parse JSON from disk, summarize commands, and apply via `apply_schematic_command`.

- [x] **Step 4: Run service tests green**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\services\test_kicad_plan.py -q -p no:cacheprovider --basetemp='.tmp\pytest-kicad-plan-green'
```

Expected: pass.

## Task 2: CLI Command

**Files:**
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`

- [x] **Step 1: Write failing CLI tests**

Cover `kicad-plan <project> <package>` dry-run output and `--apply` writing the schematic/action log.

- [x] **Step 2: Run CLI tests red**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_cli.py -q -p no:cacheprovider --basetemp='.tmp\pytest-kicad-plan-cli-red'
```

Expected: fail because `kicad-plan` is not registered.

- [x] **Step 3: Wire CLI**

Add `_cmd_kicad_plan`, import the service, print result lines, and return service exit code.

- [x] **Step 4: Run CLI tests green**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_cli.py -q -p no:cacheprovider --basetemp='.tmp\pytest-kicad-plan-cli-green'
```

Expected: pass.

## Task 3: Docs And Verification

**Files:**
- Modify: `README.md`

- [x] **Step 1: Update README**

Document the command-package approval loop and give one short JSON example.

- [x] **Step 2: Run verification**

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp='.tmp\pytest-kicad-plan-full'
```

- [x] **Step 3: Commit and push**

Commit with `feat: add kicad command approval loop`, then push the current branch.
