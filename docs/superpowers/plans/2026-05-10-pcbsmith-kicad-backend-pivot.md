# PCBSmith KiCad Backend Pivot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot PCBSmith from custom PCB GUI development toward a KiCad-backed AI companion architecture.

**Architecture:** Add a small KiCad backend boundary under `pcbsmith.services`, expose a CLI status command, and document KiCad as the first real CAD backend. This keeps the existing command-spine work while avoiding further investment in a custom CAD canvas.

**Tech Stack:** Python 3.12, pytest, ruff, KiCad CLI/IPC API in later phases.

---

## File Structure

- Create: `src/pcbsmith/services/kicad_backend.py`
- Create: `tests/unit/services/test_kicad_backend.py`
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`
- Create: `docs/superpowers/specs/2026-05-10-pcbsmith-kicad-ai-companion-design.md`
- Modify: `README.md`

## Task 1: KiCad CLI Detection

**Files:**
- Create: `src/pcbsmith/services/kicad_backend.py`
- Create: `tests/unit/services/test_kicad_backend.py`

- [x] **Step 1: Write failing detection tests**

Cover explicit environment override, `PATH` lookup, known Windows install path lookup, and unavailable KiCad.

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_kicad_backend.py -q -p no:cacheprovider --basetemp=".tmp/pytest-kicad-backend-red"
```

Expected: FAIL because `pcbsmith.services.kicad_backend` does not exist.

- [x] **Step 3: Implement detection service**

Create immutable `KiCadInstall` and `find_kicad_cli()`.

- [x] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_kicad_backend.py -q -p no:cacheprovider --basetemp=".tmp/pytest-kicad-backend-green"
```

Expected: PASS.

## Task 2: CLI Status Command

**Files:**
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`

- [x] **Step 1: Add CLI integration test**

Test that `pcbsmith kicad-status` reports an explicit `PCBSMITH_KICAD_CLI` path.

- [x] **Step 2: Implement `kicad-status`**

Add a subcommand that prints the detected KiCad CLI path or tells the user how to configure it.

## Task 3: Document Pivot

**Files:**
- Create: `docs/superpowers/specs/2026-05-10-pcbsmith-kicad-ai-companion-design.md`
- Modify: `README.md`

- [x] **Step 1: Write design note**

Document KiCad as the real CAD backend/editor and PCBSmith as the AI command layer.

- [x] **Step 2: Update README**

Add KiCad backend direction, `kicad-status`, and install/configuration notes.

## Verification

Run before commit:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=".tmp/pytest-kicad-pivot-full"
```

## Self-Review

- Spec coverage: covers the pivot decision, first detection boundary, CLI status, and docs.
- Placeholder scan: no implementation placeholders remain.
- Type consistency: `find_kicad_cli`, `KiCadInstall`, and `PCBSMITH_KICAD_CLI` names are consistent.
