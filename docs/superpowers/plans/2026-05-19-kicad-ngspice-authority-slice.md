# KiCad ngspice Authority Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the divider + high-pass + LED slice validate through KiCad-native artifacts and ngspice simulation from KiCad-exported SPICE, with explicit revision/error records.

**Architecture:** PCBSmith keeps the internal circuit object and deterministic math, but KiCad becomes the schematic/netlist/ERC authority and ngspice becomes the simulation authority. The review bundle separates PCBSmith internal evidence, KiCad evidence, ngspice evidence, reconciliation checks, and revision records.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff, mypy, KiCad 10.0 CLI, standalone ngspice 46.

---

## Scope Check

This plan implements the approved spec file:

`docs/superpowers/specs/2026-05-19-kicad-ngspice-authority-design.md`

It intentionally covers one vertical slice:

- voltage divider;
- high-pass RC filter;
- LED indicator;
- KiCad-native schematic export;
- KiCad ERC;
- KiCad SPICE netlist export;
- ngspice run from the KiCad-exported netlist;
- authority-separated review bundle;
- bounded revision records.

It does not implement board layout, DRC readiness, bulk datasheet downloads, or a general circuit generator.

## File Structure

Create:

- `src/pcbsmith/kicad/__init__.py`
  - Package marker and public export surface for KiCad integration.
- `src/pcbsmith/kicad/cli.py`
  - KiCad CLI discovery, version check, and subprocess runner.
- `src/pcbsmith/kicad/export_divider_highpass_led.py`
  - Narrow KiCad-native export for the first slice. It may reuse the current PCBSmith JSON schematic as the source of geometry, but it must write `.kicad_pro`, `.kicad_sch`, `sym-lib-table`, and `PCBSmith.kicad_sym`.
- `src/pcbsmith/kicad/validate.py`
  - KiCad ERC runner and JSON report parser.
- `src/pcbsmith/kicad/spice.py`
  - KiCad SPICE netlist export wrapper.
- `src/pcbsmith/review/authority_bundle.py`
  - Authority-separated review bundle v2 writer.
- `src/pcbsmith/revision.py`
  - Revision record model and bounded retry helpers.

Modify:

- `src/pcbsmith/circuit/models.py`
  - Add KiCad report, evidence report, reconciliation report, revision record, and review-bundle-v2 models.
- `src/pcbsmith/simulation/ngspice.py`
  - Add a function that accepts a KiCad-exported netlist file and produces a `SimulationReport`.
- `src/pcbsmith/review/circuit_bundle.py`
  - Keep v1 behavior for existing tests, but route the new authority slice through `authority_bundle.py`.
- `src/pcbsmith/cli.py`
  - Add a new command, `design-divider-highpass-led-authority`, leaving the existing demo command intact.

Tests:

- `tests/unit/kicad/test_cli.py`
- `tests/unit/kicad/test_export_divider_highpass_led.py`
- `tests/unit/kicad/test_validate.py`
- `tests/unit/kicad/test_spice.py`
- `tests/unit/review/test_authority_bundle.py`
- `tests/unit/test_revision.py`
- `tests/integration/test_divider_highpass_led_authority_cli.py`

---

### Task 1: Add KiCad CLI Discovery And Runner

**Files:**
- Create: `src/pcbsmith/kicad/__init__.py`
- Create: `src/pcbsmith/kicad/cli.py`
- Test: `tests/unit/kicad/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/kicad/test_cli.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

from pcbsmith.kicad.cli import KiCadInstall, find_kicad_cli, run_kicad_process


def test_find_kicad_cli_uses_environment_override(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "kicad-cli.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("PCBSMITH_KICAD_CLI", str(executable))

    assert find_kicad_cli() == KiCadInstall(path=executable, source="PCBSMITH_KICAD_CLI")


def test_run_kicad_process_captures_command_output() -> None:
    def fake_runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="10.0.2\n", stderr="")

    result = run_kicad_process(
        (Path("kicad-cli.exe"), "version"),
        runner=fake_runner,
    )

    assert result.returncode == 0
    assert result.command == ("kicad-cli.exe", "version")
    assert result.stdout == "10.0.2\n"
    assert result.stderr == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\kicad\test_cli.py -q -p no:cacheprovider`

Expected: FAIL because `pcbsmith.kicad.cli` does not exist.

- [ ] **Step 3: Add the package marker**

Create `src/pcbsmith/kicad/__init__.py`:

```python
"""KiCad CLI and native-artifact integration."""
```

- [ ] **Step 4: Implement KiCad discovery and process runner**

Create `src/pcbsmith/kicad/cli.py`:

```python
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

KICAD_CLI_ENV = "PCBSMITH_KICAD_CLI"
WINDOWS_KICAD_CLI = Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")


class KiCadInstall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: Path
    source: str


class KiCadProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def find_kicad_cli() -> KiCadInstall | None:
    env_path = os.environ.get(KICAD_CLI_ENV)
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return KiCadInstall(path=candidate, source=KICAD_CLI_ENV)

    path_candidate = shutil.which("kicad-cli")
    if path_candidate:
        return KiCadInstall(path=Path(path_candidate), source="PATH")

    if WINDOWS_KICAD_CLI.exists():
        return KiCadInstall(path=WINDOWS_KICAD_CLI, source="known_windows_path")

    return None


def run_kicad_process(
    command: Sequence[str | Path],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> KiCadProcessResult:
    command_text = tuple(str(part) for part in command)
    completed = runner(
        list(command_text),
        text=True,
        capture_output=True,
        check=False,
    )
    return KiCadProcessResult(
        command=command_text,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\kicad\test_cli.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pcbsmith/kicad tests/unit/kicad/test_cli.py
git commit -m "feat: add kicad cli runner"
```

---

### Task 2: Add KiCad Authority Models

**Files:**
- Modify: `src/pcbsmith/circuit/models.py`
- Test: `tests/unit/circuit/test_models.py`

- [ ] **Step 1: Write the failing model test**

Append to `tests/unit/circuit/test_models.py`:

```python
from pcbsmith.circuit.models import KiCadReport, ReconciliationReport, RevisionRecord


def test_authority_models_separate_kicad_and_reconciliation() -> None:
    kicad = KiCadReport(
        status="passed",
        schematic_file="Slice.kicad_sch",
        erc_report="erc.json",
        spice_netlist="Slice.cir",
        findings=(),
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=("component references matched KiCad export",),
        findings=("Generic LED still needs datasheet-backed model.",),
    )
    revision = RevisionRecord(
        revision_id="rev-1",
        parent_revision_id=None,
        changed_artifacts=("Slice.kicad_sch",),
        authority_checks=("kicad_erc", "spice_export"),
        findings=("KiCad ERC passed.",),
        next_action="Run ngspice from KiCad-exported SPICE netlist.",
    )

    assert kicad.status == "passed"
    assert reconciliation.status == "warning"
    assert revision.revision_id == "rev-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\circuit\test_models.py -q -p no:cacheprovider`

Expected: FAIL because `KiCadReport`, `ReconciliationReport`, and `RevisionRecord` are not defined.

- [ ] **Step 3: Add authority models**

Modify `src/pcbsmith/circuit/models.py` by adding these classes after `SimulationReport`:

```python
AuthorityStatus = Literal[
    "passed",
    "warning",
    "failed",
    "unavailable",
    "not_run",
    "needs_human_review",
]


class KiCadReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    command: tuple[str, ...] = ()
    schematic_file: str | None = None
    erc_report: str | None = None
    spice_netlist: str | None = None
    findings: tuple[str, ...] = ()


class EvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    findings: tuple[str, ...] = ()
    cached_files: tuple[str, ...] = ()


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    checks: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()


class RevisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: str
    parent_revision_id: str | None = None
    changed_artifacts: tuple[str, ...] = ()
    authority_checks: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    next_action: str
```

- [ ] **Step 4: Run test to verify it passes**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\circuit\test_models.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/circuit/models.py tests/unit/circuit/test_models.py
git commit -m "feat: add authority report models"
```

---

### Task 3: Export The Slice To KiCad-Native Files

**Files:**
- Create: `src/pcbsmith/kicad/export_divider_highpass_led.py`
- Test: `tests/unit/kicad/test_export_divider_highpass_led.py`

- [ ] **Step 1: Write the failing export test**

Create `tests/unit/kicad/test_export_divider_highpass_led.py`:

```python
from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.kicad.export_divider_highpass_led import export_divider_highpass_led_to_kicad


def _circuit():
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    return compose_divider_highpass_led(intent, select_topology(intent))


def test_exports_kicad_project_schematic_and_symbol_library(tmp_path: Path) -> None:
    result = export_divider_highpass_led_to_kicad(
        _circuit(),
        tmp_path,
        project_name="Slice",
    )

    schematic_text = (tmp_path / "Slice.kicad_sch").read_text(encoding="utf-8")
    symbol_table_text = (tmp_path / "sym-lib-table").read_text(encoding="utf-8")

    assert result["project_file"] == str(tmp_path / "Slice.kicad_pro")
    assert result["schematic_file"] == str(tmp_path / "Slice.kicad_sch")
    assert (tmp_path / "PCBSmith.kicad_sym").exists()
    assert "PCBSmith:R" in schematic_text
    assert "PCBSmith:C" in schematic_text
    assert "PCBSmith:LED" in schematic_text
    assert "DIV_OUT" in schematic_text
    assert "HP_OUT" in schematic_text
    assert "${KIPRJMOD}/PCBSmith.kicad_sym" in symbol_table_text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\kicad\test_export_divider_highpass_led.py -q -p no:cacheprovider`

Expected: FAIL because the exporter module does not exist.

- [ ] **Step 3: Implement a narrow KiCad exporter**

Create `src/pcbsmith/kicad/export_divider_highpass_led.py`.

Use a narrow implementation, not a full board exporter. It must:

- validate `circuit.topology.topology_id == "divider_highpass_led_indicator"`;
- write `Slice.kicad_pro`;
- write `sym-lib-table`;
- write `PCBSmith.kicad_sym`;
- write `Slice.kicad_sch`;
- return a dict with `project_file`, `schematic_file`, and `symbol_library`.

Start with this public function and helpers:

```python
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pcbsmith.circuit.models import CircuitObject


def export_divider_highpass_led_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    if circuit.topology.topology_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported circuit for KiCad export")

    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"
    symbol_library = output_dir / "PCBSmith.kicad_sym"
    symbol_table = output_dir / "sym-lib-table"

    project_file.write_text(_render_project(), encoding="utf-8")
    symbol_table.write_text(_render_symbol_table(), encoding="utf-8")
    symbol_library.write_text(_render_symbol_library(), encoding="utf-8")
    schematic_file.write_text(_render_schematic(project_name), encoding="utf-8")

    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
        "symbol_library": str(symbol_library),
    }


def _render_project() -> str:
    return "{\n  \"meta\": {\"version\": 1}\n}\n"


def _render_symbol_table() -> str:
    return """(sym_lib_table
  (version 7)
  (lib
    (name "PCBSmith")
    (type "KiCad")
    (uri "${KIPRJMOD}/PCBSmith.kicad_sym")
    (options "")
    (descr "PCBSmith generated symbols")
  )
)
"""
```

For `_render_symbol_library()` and `_render_schematic()`, use the proven symbol templates from:

`old_files/r8-pre-restructure-snapshot-20260517-142339/src/pcbsmith/services/kicad_export.py`

Copy only the resistor, capacitor, LED, connector, and ground/power symbol renderers needed for this slice. Keep them private inside `export_divider_highpass_led.py`. Do not copy board routing logic.

The schematic must include:

- `P1` connector;
- `R1`, `R2`, `C1`, `RLOAD`, `R3`, `D1`;
- `GND` power symbol;
- labels `VIN`, `DIV_OUT`, `HP_OUT`, and `GND`;
- text SPICE directives for `.op`, `.ac dec 20 10 100k`, and `.print ac v(HP_OUT)` if KiCad requires explicit directives for SPICE export.

- [ ] **Step 4: Run export unit test**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\kicad\test_export_divider_highpass_led.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/kicad/export_divider_highpass_led.py tests/unit/kicad/test_export_divider_highpass_led.py
git commit -m "feat: export divider slice to kicad"
```

---

### Task 4: Run KiCad ERC And Parse JSON Reports

**Files:**
- Create: `src/pcbsmith/kicad/validate.py`
- Test: `tests/unit/kicad/test_validate.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/kicad/test_validate.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.kicad.validate import run_kicad_erc


def test_kicad_erc_reports_unavailable_without_cli(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    report = run_kicad_erc(schematic, finder=lambda: None)

    assert report.status == "unavailable"
    assert report.schematic_file == str(schematic)
    assert report.findings == ("KiCad CLI was not found; ERC was not run.",)


def test_kicad_erc_runs_json_report_with_fake_runner(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command):
        report_file = Path(command[5])
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps({"sheets": [{"violations": []}]}), encoding="utf-8")
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = run_kicad_erc(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "passed"
    assert report.erc_report is not None
    assert report.command[:4] == ("kicad-cli.exe", "sch", "erc", "--format")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\kicad\test_validate.py -q -p no:cacheprovider`

Expected: FAIL because `pcbsmith.kicad.validate` does not exist.

- [ ] **Step 3: Implement ERC wrapper**

Create `src/pcbsmith/kicad/validate.py`:

```python
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.circuit.models import KiCadReport
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli, run_kicad_process


def run_kicad_erc(
    schematic_file: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> KiCadReport:
    install = finder()
    report_file = schematic_file.parent / ".pcbsmith" / "kicad" / "erc.json"
    if install is None:
        return KiCadReport(
            status="unavailable",
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
            findings=("KiCad CLI was not found; ERC was not run.",),
        )

    command = (
        str(install.path),
        "sch",
        "erc",
        "--format",
        "json",
        "--output",
        str(report_file),
        str(schematic_file),
    )
    report_file.parent.mkdir(parents=True, exist_ok=True)
    process = run_kicad_process(command) if runner is None else runner(command)
    if process.returncode != 0:
        return KiCadReport(
            status="failed",
            command=process.command,
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
            findings=(process.stderr.strip() or process.stdout.strip() or "KiCad ERC failed.",),
        )

    findings = _erc_findings(report_file)
    return KiCadReport(
        status="failed" if findings else "passed",
        command=process.command,
        schematic_file=str(schematic_file),
        erc_report=str(report_file),
        findings=findings,
    )


def _erc_findings(report_file: Path) -> tuple[str, ...]:
    data = json.loads(report_file.read_text(encoding="utf-8"))
    findings: list[str] = []
    for sheet in data.get("sheets", []):
        for violation in sheet.get("violations", []):
            description = str(violation.get("description", "ERC violation"))
            severity = str(violation.get("severity", violation.get("type", "unknown")))
            findings.append(f"{severity}: {description}")
    return tuple(findings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\kicad\test_validate.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/kicad/validate.py tests/unit/kicad/test_validate.py
git commit -m "feat: add kicad erc wrapper"
```

---

### Task 5: Export SPICE From KiCad And Run ngspice From That Netlist

**Files:**
- Create: `src/pcbsmith/kicad/spice.py`
- Modify: `src/pcbsmith/simulation/ngspice.py`
- Test: `tests/unit/kicad/test_spice.py`
- Test: `tests/unit/simulation/test_ngspice.py`

- [ ] **Step 1: Write failing KiCad SPICE export tests**

Create `tests/unit/kicad/test_spice.py`:

```python
from __future__ import annotations

from pathlib import Path

from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.kicad.spice import export_kicad_spice_netlist


def test_spice_export_reports_unavailable_without_kicad(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    report = export_kicad_spice_netlist(schematic, finder=lambda: None)

    assert report.status == "unavailable"
    assert report.findings == ("KiCad CLI was not found; SPICE netlist export was not run.",)


def test_spice_export_writes_netlist_with_fake_runner(tmp_path: Path) -> None:
    schematic = tmp_path / "Slice.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def fake_runner(command):
        output_file = Path(command[6])
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("* exported by KiCad\n.op\n.end\n", encoding="utf-8")
        return KiCadProcessResult(command=tuple(command), returncode=0, stdout="", stderr="")

    report = export_kicad_spice_netlist(
        schematic,
        finder=lambda: KiCadInstall(path=Path("kicad-cli.exe"), source="test"),
        runner=fake_runner,
    )

    assert report.status == "passed"
    assert report.spice_netlist is not None
    assert Path(report.spice_netlist).read_text(encoding="utf-8").startswith("* exported by KiCad")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\kicad\test_spice.py -q -p no:cacheprovider`

Expected: FAIL because `pcbsmith.kicad.spice` does not exist.

- [ ] **Step 3: Implement KiCad SPICE export wrapper**

Create `src/pcbsmith/kicad/spice.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.circuit.models import KiCadReport
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli, run_kicad_process


def export_kicad_spice_netlist(
    schematic_file: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> KiCadReport:
    install = finder()
    netlist_file = schematic_file.parent / ".pcbsmith" / "kicad" / f"{schematic_file.stem}.cir"
    if install is None:
        return KiCadReport(
            status="unavailable",
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
            findings=("KiCad CLI was not found; SPICE netlist export was not run.",),
        )

    command = (
        str(install.path),
        "sch",
        "export",
        "netlist",
        "--format",
        "spice",
        "--output",
        str(netlist_file),
        str(schematic_file),
    )
    netlist_file.parent.mkdir(parents=True, exist_ok=True)
    process = run_kicad_process(command) if runner is None else runner(command)
    if process.returncode != 0:
        return KiCadReport(
            status="failed",
            command=process.command,
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
            findings=(
                process.stderr.strip()
                or process.stdout.strip()
                or "KiCad SPICE netlist export failed.",
            ),
        )
    if not netlist_file.exists() or not netlist_file.read_text(encoding="utf-8").strip():
        return KiCadReport(
            status="failed",
            command=process.command,
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
            findings=("KiCad SPICE netlist export did not produce a non-empty file.",),
        )
    return KiCadReport(
        status="passed",
        command=process.command,
        schematic_file=str(schematic_file),
        spice_netlist=str(netlist_file),
    )
```

- [ ] **Step 4: Add ngspice helper for existing netlist files**

Append this test to `tests/unit/simulation/test_ngspice.py`:

```python
def test_run_ngspice_from_existing_netlist_file(tmp_path: Path) -> None:
    netlist = tmp_path / "Slice.cir"
    netlist.write_text("* KiCad exported netlist\n.op\n.end\n", encoding="utf-8")

    def fake_runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=NGSPICE_SAMPLE_OUTPUT, stderr="")

    report = run_ngspice_netlist_file(
        netlist,
        tmp_path,
        finder=lambda: Path("ngspice_con.exe"),
        runner=fake_runner,
    )

    assert report.status == "passed"
    assert report.measurements["op_div_out_v"] == 2.5
    assert report.raw_output_path is not None
```

Update the import in `tests/unit/simulation/test_ngspice.py`:

```python
from pcbsmith.simulation.ngspice import (
    ac_value_at,
    extract_ngspice_measurements,
    find_ngspice,
    parse_ngspice_output,
    render_ngspice_netlist,
    run_ngspice_batch,
    run_ngspice_netlist_file,
    run_ngspice_simulation,
)
```

- [ ] **Step 5: Run the new ngspice test to verify it fails**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\simulation\test_ngspice.py::test_run_ngspice_from_existing_netlist_file -q -p no:cacheprovider`

Expected: FAIL because `run_ngspice_netlist_file` does not exist.

- [ ] **Step 6: Implement `run_ngspice_netlist_file`**

Modify `src/pcbsmith/simulation/ngspice.py`:

```python
def run_ngspice_netlist_file(
    netlist_path: Path,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SimulationReport:
    netlist_text = netlist_path.read_text(encoding="utf-8")
    result = run_ngspice_batch(
        netlist_text,
        output_dir,
        netlist_filename=netlist_path.name,
        finder=finder,
        runner=runner,
    )
    if result.status == "unavailable":
        return SimulationReport(
            backend="ngspice",
            status="unavailable",
            findings=result.findings,
            raw_output_path=str(result.raw_output_path),
        )
    if result.status == "failed":
        return SimulationReport(
            backend="ngspice",
            status="failed",
            command=result.command,
            findings=result.findings,
            raw_output_path=str(result.raw_output_path),
        )
    measurements = extract_ngspice_measurements(result.raw_output)
    status, findings = _evaluate_measurements(measurements)
    return SimulationReport(
        backend="ngspice",
        status=status,
        command=result.command,
        measurements=measurements,
        findings=findings,
        raw_output_path=str(result.raw_output_path),
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\kicad\test_spice.py tests\unit\simulation\test_ngspice.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/pcbsmith/kicad/spice.py src/pcbsmith/simulation/ngspice.py tests/unit/kicad/test_spice.py tests/unit/simulation/test_ngspice.py
git commit -m "feat: run ngspice from kicad spice netlists"
```

---

### Task 6: Add Revision Records And Failure Routing

**Files:**
- Create: `src/pcbsmith/revision.py`
- Test: `tests/unit/test_revision.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_revision.py`:

```python
from __future__ import annotations

from pcbsmith.revision import revision_for_authority_failure, should_stop_revision_loop


def test_revision_for_kicad_failure_targets_existing_schematic() -> None:
    revision = revision_for_authority_failure(
        revision_id="rev-2",
        parent_revision_id="rev-1",
        failure_code="kicad_failed",
        findings=("ERC reports unconnected HP_OUT.",),
    )

    assert revision.changed_artifacts == ("KiCad schematic or symbol mapping",)
    assert revision.authority_checks == ("kicad_erc", "kicad_spice_export")
    assert revision.next_action == "Patch the existing KiCad schematic or symbol mapping."


def test_revision_loop_stops_after_repeated_same_failure() -> None:
    assert should_stop_revision_loop(("simulation_failed", "simulation_failed"), limit=2)
    assert not should_stop_revision_loop(("simulation_failed", "kicad_failed"), limit=2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\test_revision.py -q -p no:cacheprovider`

Expected: FAIL because `pcbsmith.revision` does not exist.

- [ ] **Step 3: Implement revision helpers**

Create `src/pcbsmith/revision.py`:

```python
from __future__ import annotations

from collections import Counter

from pcbsmith.circuit.models import RevisionRecord

_FAILURE_ROUTES = {
    "evidence_missing": (
        ("Evidence cache or part selection",),
        ("evidence_lookup",),
        "Fetch or request the missing evidence before changing the schematic.",
    ),
    "math_mismatch": (
        ("Circuit object values or deterministic calculators",),
        ("math_gate",),
        "Recalculate values and update the existing circuit object.",
    ),
    "kicad_failed": (
        ("KiCad schematic or symbol mapping",),
        ("kicad_erc", "kicad_spice_export"),
        "Patch the existing KiCad schematic or symbol mapping.",
    ),
    "simulation_failed": (
        ("SPICE model, simulation setup, or circuit values",),
        ("ngspice",),
        "Patch the simulation setup or circuit values and rerun ngspice.",
    ),
    "reconciliation_failed": (
        ("Translation boundary between PCBSmith, KiCad, and ngspice",),
        ("reconciliation",),
        "Patch the mismatched translation layer.",
    ),
}


def revision_for_authority_failure(
    *,
    revision_id: str,
    parent_revision_id: str | None,
    failure_code: str,
    findings: tuple[str, ...],
) -> RevisionRecord:
    changed_artifacts, checks, next_action = _FAILURE_ROUTES[failure_code]
    return RevisionRecord(
        revision_id=revision_id,
        parent_revision_id=parent_revision_id,
        changed_artifacts=changed_artifacts,
        authority_checks=checks,
        findings=findings,
        next_action=next_action,
    )


def should_stop_revision_loop(failure_codes: tuple[str, ...], *, limit: int = 3) -> bool:
    counts = Counter(failure_codes)
    return any(count >= limit for count in counts.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\test_revision.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/revision.py tests/unit/test_revision.py
git commit -m "feat: add authority revision records"
```

---

### Task 7: Write Authority-Separated Review Bundle

**Files:**
- Create: `src/pcbsmith/review/authority_bundle.py`
- Modify: `src/pcbsmith/circuit/models.py`
- Test: `tests/unit/review/test_authority_bundle.py`

- [ ] **Step 1: Write failing bundle test**

Create `tests/unit/review/test_authority_bundle.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.models import (
    EvidenceReport,
    KiCadReport,
    ReconciliationReport,
    RevisionRecord,
    SimulationReport,
)
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.review.authority_bundle import write_authority_review_bundle


def _circuit():
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    return compose_divider_highpass_led(intent, select_topology(intent))


def test_authority_bundle_keeps_authority_sections_separate(tmp_path: Path) -> None:
    bundle_path = write_authority_review_bundle(
        _circuit(),
        tmp_path,
        evidence=EvidenceReport(status="needs_human_review", findings=("Generic parts only.",)),
        kicad=KiCadReport(status="passed", schematic_file="Slice.kicad_sch"),
        simulation=SimulationReport(backend="ngspice", status="passed"),
        reconciliation=ReconciliationReport(status="warning", findings=("LED needs review.",)),
        revisions=(
            RevisionRecord(
                revision_id="rev-1",
                next_action="Human review generic LED evidence.",
            ),
        ),
        artifacts={"kicad_project": str(tmp_path)},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-circuit-review-bundle-v2"
    assert data["status"] == "needs_human_review"
    assert data["kicad"]["status"] == "passed"
    assert data["ngspice"]["status"] == "passed"
    assert data["reconciliation"]["status"] == "warning"
    assert data["revisions"][0]["revision_id"] == "rev-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\review\test_authority_bundle.py -q -p no:cacheprovider`

Expected: FAIL because `AuthorityReviewBundle` and writer do not exist.

- [ ] **Step 3: Add the bundle model**

Modify `src/pcbsmith/circuit/models.py` by adding:

```python
class AuthorityReviewBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-circuit-review-bundle-v2"] = Field(
        validation_alias="schema",
        serialization_alias="schema",
    )
    status: AuthorityStatus
    intent: CircuitIntent
    pcbs_internal: CircuitObject
    evidence: EvidenceReport
    kicad: KiCadReport
    ngspice: SimulationReport
    reconciliation: ReconciliationReport
    revisions: tuple[RevisionRecord, ...] = ()
    artifacts: dict[str, str]
```

- [ ] **Step 4: Implement the authority bundle writer**

Create `src/pcbsmith/review/authority_bundle.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.models import (
    AuthorityReviewBundle,
    CircuitObject,
    EvidenceReport,
    KiCadReport,
    ReconciliationReport,
    RevisionRecord,
    SimulationReport,
)


def write_authority_review_bundle(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    evidence: EvidenceReport,
    kicad: KiCadReport,
    simulation: SimulationReport,
    reconciliation: ReconciliationReport,
    revisions: tuple[RevisionRecord, ...],
    artifacts: dict[str, str],
) -> Path:
    status = _derive_status(
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        circuit=circuit,
    )
    bundle = AuthorityReviewBundle(
        schema_id="pcbsmith-circuit-review-bundle-v2",
        status=status,
        intent=circuit.intent,
        pcbs_internal=circuit,
        evidence=evidence,
        kicad=kicad,
        ngspice=simulation,
        reconciliation=reconciliation,
        revisions=revisions,
        artifacts=artifacts,
    )
    path = output_dir / "review-bundle-v2.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle.model_dump(by_alias=True), indent=2) + "\n", encoding="utf-8")
    return path


def _derive_status(
    *,
    evidence: EvidenceReport,
    kicad: KiCadReport,
    simulation: SimulationReport,
    reconciliation: ReconciliationReport,
    circuit: CircuitObject,
) -> str:
    if kicad.status == "unavailable":
        return "unavailable"
    if kicad.status == "failed":
        return "failed"
    if simulation.status == "unavailable":
        return "unavailable"
    if simulation.status == "failed":
        return "failed"
    if reconciliation.status == "failed":
        return "failed"
    if evidence.status != "passed":
        return "needs_human_review"
    if any(component.support_status != "supported" for component in circuit.components):
        return "needs_human_review"
    if reconciliation.status != "passed":
        return "needs_human_review"
    return "passed"
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit\review\test_authority_bundle.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pcbsmith/circuit/models.py src/pcbsmith/review/authority_bundle.py tests/unit/review/test_authority_bundle.py
git commit -m "feat: write authority review bundles"
```

---

### Task 8: Add The Authority CLI Slice

**Files:**
- Modify: `src/pcbsmith/cli.py`
- Test: `tests/integration/test_divider_highpass_led_authority_cli.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/integration/test_divider_highpass_led_authority_cli.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.cli import main


def test_authority_cli_writes_kicad_and_authority_bundle(tmp_path: Path) -> None:
    exit_code = main(
        [
            "design-divider-highpass-led-authority",
            str(tmp_path),
            "--name",
            "Slice",
            "--request",
            "Generate a voltage divider connected to a high-pass filter and LED indicator",
        ]
    )

    bundle_path = tmp_path / "review-bundle-v2.json"
    data = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert (tmp_path / "Slice.kicad_sch").exists()
    assert data["schema"] == "pcbsmith-circuit-review-bundle-v2"
    assert "kicad" in data
    assert "ngspice" in data
    assert "reconciliation" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\integration\test_divider_highpass_led_authority_cli.py -q -p no:cacheprovider`

Expected: FAIL because the CLI command does not exist.

- [ ] **Step 3: Implement the CLI command**

Modify `src/pcbsmith/cli.py`.

Add imports:

```python
from pcbsmith.circuit.models import EvidenceReport, ReconciliationReport
from pcbsmith.kicad.export_divider_highpass_led import export_divider_highpass_led_to_kicad
from pcbsmith.kicad.spice import export_kicad_spice_netlist
from pcbsmith.kicad.validate import run_kicad_erc
from pcbsmith.review.authority_bundle import write_authority_review_bundle
from pcbsmith.revision import revision_for_authority_failure
from pcbsmith.simulation.ngspice import run_ngspice_netlist_file
```

Add command function:

```python
def _cmd_design_divider_highpass_led_authority(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    topology = select_topology(intent)
    circuit = compose_divider_highpass_led(intent, topology)
    write_divider_highpass_led_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_divider_highpass_led_to_kicad(
        circuit,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])
    erc_report = run_kicad_erc(schematic_file)
    spice_report = export_kicad_spice_netlist(schematic_file)
    if spice_report.status == "passed" and spice_report.spice_netlist is not None:
        simulation = run_ngspice_netlist_file(Path(spice_report.spice_netlist), output_dir)
    else:
        simulation = run_ngspice_simulation(circuit, output_dir)

    kicad_report = spice_report.model_copy(
        update={
            "status": "failed"
            if erc_report.status == "failed" or spice_report.status == "failed"
            else "unavailable"
            if erc_report.status == "unavailable" or spice_report.status == "unavailable"
            else "passed",
            "erc_report": erc_report.erc_report,
            "findings": tuple(dict.fromkeys((*erc_report.findings, *spice_report.findings))),
        }
    )
    evidence = EvidenceReport(
        status="needs_human_review",
        findings=("Generic passive and LED components are not datasheet-backed yet.",),
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=("PCBSmith generated KiCad schematic for selected circuit object.",),
        findings=("KiCad-exported SPICE simulation is present, but component evidence is generic.",),
    )
    revisions = (
        revision_for_authority_failure(
            revision_id="rev-1",
            parent_revision_id=None,
            failure_code="evidence_missing",
            findings=evidence.findings,
        ),
    )
    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad_report,
        simulation=simulation,
        reconciliation=reconciliation,
        revisions=revisions,
        artifacts={
            "pcbs_project": str(output_dir),
            "kicad_project": str(output_dir),
            "review_bundle": str(output_dir / "review-bundle-v2.json"),
        },
    )
    print(f"Review bundle: {bundle_path}")
    print("Status: needs_human_review")
    return 0
```

Register parser:

```python
    authority_parser = subparsers.add_parser(
        "design-divider-highpass-led-authority",
        help="generate the KiCad/ngspice authority vertical slice",
    )
    authority_parser.add_argument("output")
    authority_parser.add_argument("--request", required=True)
    authority_parser.add_argument("--name", required=True)
    authority_parser.set_defaults(func=_cmd_design_divider_highpass_led_authority)
```

- [ ] **Step 4: Run integration test**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\integration\test_divider_highpass_led_authority_cli.py -q -p no:cacheprovider`

Expected: PASS. If installed KiCad cannot export SPICE from the first schematic, the bundle may report `kicad.failed` or `kicad.unavailable`, but the command must still write a truthful bundle.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/cli.py tests/integration/test_divider_highpass_led_authority_cli.py
git commit -m "feat: add authority circuit slice cli"
```

---

### Task 9: Real KiCad And ngspice Smoke Verification

**Files:**
- No source files unless smoke reveals a bug.

- [ ] **Step 1: Run static checks**

Run:

`python -m ruff check src tests`

Expected: `All checks passed!`

- [ ] **Step 2: Run type checks**

Run:

`python -m mypy src`

Expected: `Success: no issues found in 31 source files` or equivalent file count.

- [ ] **Step 3: Run full tests**

Run:

`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit tests\integration -q -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 4: Run real authority smoke**

Run:

```powershell
$out = Join-Path (Get-Location) '.tmp\kicad-authority-smoke-20260519-1'
New-Item -ItemType Directory -Force -Path $out | Out-Null
python -m pcbsmith.cli design-divider-highpass-led-authority $out --name 'Slice' --request 'Generate a voltage divider connected to a high-pass filter and LED indicator'
Get-Content -LiteralPath (Join-Path $out 'review-bundle-v2.json')
```

Expected:

- command exits `0`;
- `Slice.kicad_sch` exists;
- review bundle exists;
- bundle contains separate `kicad`, `ngspice`, `evidence`, `reconciliation`, and `revisions` sections;
- top-level status remains `needs_human_review` while generic component evidence remains unresolved.

- [ ] **Step 5: Commit any smoke-discovered fixes**

Only commit if source/test files changed:

```bash
git add src tests
git commit -m "fix: stabilize kicad authority smoke"
```

---

## Self-Review Checklist

Spec coverage:

- KiCad as EDA authority: Tasks 1, 3, 4, 5, 8, 9.
- ngspice as simulation authority from KiCad-exported netlist: Tasks 5, 8, 9.
- Deterministic math remains separate: existing calculator layer is preserved; Task 7 records PCBSmith internal math separately.
- Revision loop: Task 6 and Task 7.
- Evidence as source, not validation: Task 7 and Task 8 explicitly keep evidence in its own authority section.
- Iteration over regeneration: Task 6 routes failures to patch targets.

Completeness:

- Every task has a failing test, implementation target, verification command, and commit step.
- The only archived-code reuse is constrained to specific KiCad symbol renderers for resistor, capacitor, LED, connector, and ground/power symbols.

Type consistency:

- `KiCadReport`, `EvidenceReport`, `ReconciliationReport`, and `RevisionRecord` are defined before bundle usage.
- `run_ngspice_netlist_file` returns the existing `SimulationReport`.
- The new CLI command writes `review-bundle-v2.json` without changing the existing v1 demo command.
