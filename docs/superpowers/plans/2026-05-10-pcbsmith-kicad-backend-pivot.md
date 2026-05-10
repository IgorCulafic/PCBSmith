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

## Task 4: KiCad Project Skeleton

**Files:**
- Create: `src/pcbsmith/services/kicad_project.py`
- Create: `tests/unit/services/test_kicad_project.py`
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `README.md`

- [x] **Step 1: Write failing skeleton service tests**

Cover project name sanitization, core KiCad file creation, generated metadata, schematic header/root UUID, board header/layers, and overwrite refusal.

- [x] **Step 2: Implement skeleton service**

Create `create_kicad_project_skeleton()` and render minimal `.kicad_pro`, `.kicad_sch`, and `.kicad_pcb` files using `PCBSmith` as generator.

- [x] **Step 3: Add CLI tests**

Cover `pcbsmith kicad-new <project> --name <name>` success and existing-directory refusal.

- [x] **Step 4: Implement `kicad-new`**

Wire the CLI command to `create_kicad_project_skeleton()`.

- [x] **Step 5: Update README**

Document the first KiCad handoff skeleton command and clarify that KiCad should canonicalize generated files later.

## Task 5: PCBSmith To KiCad Handoff Export

**Files:**
- Create: `src/pcbsmith/services/kicad_export.py`
- Create: `tests/unit/services/test_kicad_export.py`
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `README.md`

- [x] **Step 1: Write failing export service tests**

Cover creating a KiCad skeleton from an existing PCBSmith project, writing `pcbsmith_handoff.json`, preserving source project identity, and emitting ordered schematic commands.

- [x] **Step 2: Implement export service**

Create `export_pcbs_project_to_kicad()` and a versioned handoff manifest with source project metadata, KiCad skeleton filenames, and schematic intent commands.

- [x] **Step 3: Add CLI export test**

Cover `pcbsmith kicad-export <source-project> <output-project> --name <name>`.

- [x] **Step 4: Implement `kicad-export`**

Wire the CLI command to the export service.

- [x] **Step 5: Update README**

Document `kicad-export` and the `pcbsmith_handoff.json` contract.

## Task 6: KiCad Backend Doctor

**Files:**
- Create: `src/pcbsmith/services/kicad_doctor.py`
- Create: `tests/unit/services/test_kicad_doctor.py`
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `README.md`

- [x] **Step 1: Write failing doctor tests**

Cover missing KiCad, ready KiCad with version output, skipped version probing, and version probe failure.

- [x] **Step 2: Implement doctor service**

Create `run_kicad_doctor()` and `format_kicad_doctor_report()` around the existing KiCad CLI discovery boundary.

- [x] **Step 3: Add CLI command**

Add `pcbsmith kicad-doctor` and `--skip-version-check`.

- [x] **Step 4: Update README**

Document the readiness check and explain that skipped probing only checks discovery/configuration.

## Task 7: KiCad CLI Skeleton Validation

**Files:**
- Modify: `src/pcbsmith/services/kicad_project.py`
- Modify: `tests/unit/services/test_kicad_project.py`
- Modify: `README.md`

- [x] **Step 1: Run generated skeleton through KiCad CLI**

Installed KiCad through Scoop and ran `kicad-doctor`; KiCad 10.0.1 is discoverable through `PATH`.

- [x] **Step 2: Capture DRC failure**

KiCad parsed the generated skeleton, ERC reported 0 violations, and PCB DRC reported `invalid_outline` because the board had no `Edge.Cuts` geometry.

- [x] **Step 3: Add default board outline**

Added a starter 100 mm by 80 mm `gr_rect` on `Edge.Cuts`.

- [x] **Step 4: Verify with real KiCad CLI**

Reran `kicad-cli sch erc` and `kicad-cli pcb drc` on a fresh exported handoff; both reported 0 violations.

## Task 8: KiCad Validate Command

**Files:**
- Create: `src/pcbsmith/services/kicad_validate.py`
- Create: `tests/unit/services/test_kicad_validate.py`
- Create: `docs/kicad-setup.md`
- Modify: `src/pcbsmith/cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `README.md`
- Modify: `.gitignore`

- [x] **Step 1: Write failing validation tests**

Cover missing KiCad, skipped execution, clean ERC/DRC JSON reports, rule violations, and KiCad process failures.

- [x] **Step 2: Implement validation service**

Create `run_kicad_validation()` around KiCad CLI ERC/DRC commands with report parsing and structured exit codes.

- [x] **Step 3: Add CLI command**

Add `pcbsmith kicad-validate <project>` with `--skip-execution` for discovery/configuration checks.

- [x] **Step 4: Document setup and validation**

Add KiCad setup notes, validation examples, and ignored `.pcbsmith/` generated reports.

## Task 9: KiCad-Native Schematic Primitive Export

**Files:**
- Modify: `src/pcbsmith/services/kicad_export.py`
- Modify: `src/pcbsmith/services/kicad_project.py`
- Modify: `tests/unit/services/test_kicad_export.py`
- Modify: `README.md`

- [x] **Step 1: Write failing export tests**

Cover net labels and no-connect markers being written into the generated `.kicad_sch`.

- [x] **Step 2: Implement KiCad schematic item rendering**

Render PCBSmith `NetLabel` and `NoConnect` objects as KiCad `label` and `no_connect` records, converting nanometer coordinates to millimeters.

- [x] **Step 3: Keep symbols and wires deferred**

Leave symbols and wires in `pcbsmith_handoff.json` until the KiCad symbol/library mapping is ready.

- [x] **Step 4: Update README**

Document that `kicad-export` now writes safe native schematic primitives in addition to the handoff manifest.

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
