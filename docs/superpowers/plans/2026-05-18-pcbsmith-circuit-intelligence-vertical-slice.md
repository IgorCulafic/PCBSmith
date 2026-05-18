# PCBSmith Circuit Intelligence Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first trustworthy circuit-intelligence slice: classify a request for a voltage divider feeding an AC-coupled high-pass filter and LED indicator, choose a supported topology with evidence, run deterministic calculations, generate a schematic-first circuit object, run ngspice where available, export/validate through KiCad, and write one review bundle.

**Architecture:** Keep KiCad authoritative for EDA artifacts and keep PCBSmith responsible for constrained intent, topology evidence, deterministic math, simulation orchestration, and consolidated review state. This slice should not claim general circuit synthesis; it should support exactly one composed topology and return explicit unsupported/human-review findings outside that boundary.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, KiCad CLI, ngspice subprocess integration, current Phase 0 PCBSmith project/netlist/ERC models.

---

## Audit Summary From 2026-05-18

- Requested root docs `docs/project-reset-handoff-2026-05-18.md`, `docs/project-handoff.md`, `docs/roadmap.md`, and `docs/presentation-brief.md` are not present in the live root docs folder.
- Older handoff docs are available only under `old_files/r8-pre-restructure-snapshot-20260517-142339/docs/`.
- Live tracked-looking source is Phase 0 scale: `src/pcbsmith/core`, `src/pcbsmith/services`, and `src/pcbsmith/cli.py`.
- Many directories under `src/pcbsmith` contain only `__pycache__`; do not treat those as implemented modules.
- `outputs/test-r14-local-vs-codex` contains generated KiCad demos, including the simple divider/high-pass/LED and buck converter. Treat them as historical demos, not trusted architecture.
- Current `git status --short` reports untracked `ai-context.json`, `ai_assets/`, `old_files/`, and `outputs/`. Do not stage or delete them unless the user explicitly asks.
- `python -m pytest -q` currently fails before collection due to active-environment `pytestqt`/Qt import failure, not due to a collected PCBSmith assertion.
- `kicad-cli` is discoverable, and `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe` exists.
- Standalone ngspice is available at `D:\AI\PCB designer\Spice64\bin\ngspice_con.exe`. This is the preferred automation binary for the first simulation runner.
- KiCad also includes ngspice integration files, but the first PCBSmith runner should use the standalone console executable so batch simulation is explicit and testable.

## File Structure

- Create `src/pcbsmith/circuit/__init__.py`: package exports for circuit-intelligence domain types.
- Create `src/pcbsmith/circuit/models.py`: pure Pydantic models for intent, topology selection, component roles, circuit objects, simulation reports, validation reports, and review bundles.
- Create `src/pcbsmith/circuit/intent.py`: deterministic classifier for the single supported vertical-slice request and explicit unsupported classifications.
- Create `src/pcbsmith/circuit/topologies.py`: topology catalogue and evidence references for `divider_highpass_led_indicator`.
- Create `src/pcbsmith/calculators/__init__.py`: package marker.
- Create `src/pcbsmith/calculators/passive.py`: deterministic voltage divider, RC high-pass, and LED current-limit math.
- Create `src/pcbsmith/simulation/__init__.py`: package marker.
- Create `src/pcbsmith/simulation/ngspice.py`: ngspice discovery, netlist rendering, subprocess runner, and report parser for this slice.
- Create `src/pcbsmith/generation/__init__.py`: package marker.
- Create `src/pcbsmith/generation/divider_highpass_led.py`: schematic-first generator from validated circuit object to PCBSmith JSON schematic/board placeholder.
- Create `src/pcbsmith/review/__init__.py`: package marker.
- Create `src/pcbsmith/review/circuit_bundle.py`: consolidated review bundle writer merging intent, topology, math, simulation, PCBSmith ERC, KiCad status, and unsupported warnings.
- Modify `src/pcbsmith/services/builtin_library.py`: add generic voltage source symbol only if needed for schematic generation; keep it explicitly marked generic/test-supported in comments or model metadata.
- Modify `src/pcbsmith/cli.py`: add one CLI command, `design-divider-highpass-led`, that runs the vertical slice and writes a review bundle.
- Create `tests/unit/circuit/test_intent.py`.
- Create `tests/unit/circuit/test_topologies.py`.
- Create `tests/unit/calculators/test_passive.py`.
- Create `tests/unit/simulation/test_ngspice.py`.
- Create `tests/unit/generation/test_divider_highpass_led.py`.
- Create `tests/unit/review/test_circuit_bundle.py`.
- Create `tests/integration/test_divider_highpass_led_cli.py`.
- Optional later restore/adapt only the narrow parts of old `kicad_project.py`, `kicad_validate.py`, and `kicad_review_bundle.py`; do not bulk-copy old prototype modules.

## Supported Slice Contract

The first slice supports exactly this request family:

```text
Generate a voltage divider connected to a high-pass filter and LED indicator.
```

Hard-coded engineering assumptions for the first implementation:

- Input supply: 5.0 V DC.
- Divider target output: 2.5 V nominal.
- Divider resistors: 10 kOhm top, 10 kOhm bottom, 1% generic resistor assumption.
- High-pass filter: series capacitor 100 nF and shunt resistor 10 kOhm.
- High-pass cutoff: `1 / (2*pi*R*C)`, expected about 159.155 Hz.
- LED indicator path: high-pass output drives a current-limited generic red indicator LED model for simulation/demo only.
- LED forward voltage assumption: 2.0 V.
- LED current target: about 5 mA where the deterministic resistor check applies.
- LED current-limit resistor: 680 Ohm for a 5 V rail indicator path; if the generated circuit connects the LED after AC coupling, the report must say the LED behavior is signal-dependent and simulation/human review is required.

This is intentionally not a universal analog-front-end generator. Anything outside this topology returns `unsupported` or `needs_human_review`.

---

### Task 1: Add Circuit Domain Models

**Files:**
- Create: `src/pcbsmith/circuit/__init__.py`
- Create: `src/pcbsmith/circuit/models.py`
- Test: `tests/unit/circuit/test_models.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitReviewBundle,
    ComponentRole,
    EvidenceRef,
    TopologySelection,
)


def test_circuit_intent_records_supported_scope() -> None:
    intent = CircuitIntent(
        raw_request="voltage divider to high-pass filter and LED indicator",
        intent_id="divider_highpass_led_indicator",
        status="supported",
        assumptions={"supply_voltage_v": 5.0},
        unsupported_reasons=(),
    )

    assert intent.intent_id == "divider_highpass_led_indicator"
    assert intent.status == "supported"
    assert intent.assumptions["supply_voltage_v"] == 5.0


def test_topology_selection_requires_evidence() -> None:
    selection = TopologySelection(
        topology_id="divider_highpass_led_indicator",
        title="Voltage divider, AC-coupled high-pass, LED indicator",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="textbook_formula",
                title="Voltage divider equation",
                locator="Vout = Vin * Rbottom / (Rtop + Rbottom)",
            ),
            EvidenceRef(
                kind="textbook_formula",
                title="RC high-pass cutoff equation",
                locator="fc = 1 / (2*pi*R*C)",
            ),
        ),
        warnings=("Generic LED model requires human review for real brightness.",),
    )

    assert len(selection.evidence) == 2
    assert selection.status == "selected"


def test_component_role_is_explicit_about_demo_support() -> None:
    role = ComponentRole(
        reference="D1",
        role="indicator_led",
        symbol_id="stdlib:LED",
        value="Generic red LED, Vf=2.0V assumption",
        support_status="demo_only",
        evidence=(
            EvidenceRef(
                kind="assumption",
                title="Generic indicator LED assumption",
                locator="Requires replacement with datasheet-backed part before fabrication.",
            ),
        ),
    )

    assert role.support_status == "demo_only"


def test_review_bundle_status_is_not_passed_when_human_review_is_required() -> None:
    bundle = CircuitReviewBundle(
        schema="pcbsmith-circuit-review-bundle-v1",
        intent_id="divider_highpass_led_indicator",
        status="needs_human_review",
        items=("Generic LED is demo-only.",),
        artifacts={},
    )

    assert bundle.status == "needs_human_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/circuit/test_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'pcbsmith.circuit'`.

- [ ] **Step 3: Implement models**

Create `src/pcbsmith/circuit/__init__.py`:

```python
from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    CircuitReviewBundle,
    ComponentRole,
    EvidenceRef,
    MathReport,
    SimulationReport,
    TopologySelection,
)

__all__ = [
    "CircuitIntent",
    "CircuitObject",
    "CircuitReviewBundle",
    "ComponentRole",
    "EvidenceRef",
    "MathReport",
    "SimulationReport",
    "TopologySelection",
]
```

Create `src/pcbsmith/circuit/models.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["supported", "unsupported", "selected", "passed", "warning", "failed", "unavailable", "needs_human_review"]
SupportStatus = Literal["supported", "demo_only", "needs_datasheet_review", "unsupported"]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    title: str
    locator: str


class CircuitIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_request: str
    intent_id: str
    status: Literal["supported", "unsupported"]
    assumptions: dict[str, float | str | bool] = Field(default_factory=dict)
    unsupported_reasons: tuple[str, ...] = ()


class TopologySelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    topology_id: str
    title: str
    status: Literal["selected", "unsupported"]
    evidence: tuple[EvidenceRef, ...]
    warnings: tuple[str, ...] = ()


class ComponentRole(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    role: str
    symbol_id: str
    value: str
    support_status: SupportStatus
    evidence: tuple[EvidenceRef, ...] = ()


class MathReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["passed", "warning", "failed"]
    calculations: dict[str, float]
    findings: tuple[str, ...] = ()


class SimulationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: Literal["ngspice"]
    status: Literal["passed", "warning", "failed", "unavailable"]
    command: tuple[str, ...] = ()
    measurements: dict[str, float] = Field(default_factory=dict)
    findings: tuple[str, ...] = ()
    raw_output_path: str | None = None


class CircuitObject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: CircuitIntent
    topology: TopologySelection
    components: tuple[ComponentRole, ...]
    nets: tuple[str, ...]
    math: MathReport


class CircuitReviewBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema: Literal["pcbsmith-circuit-review-bundle-v1"]
    intent_id: str
    status: Literal["passed", "warning", "failed", "unavailable", "needs_human_review"]
    items: tuple[str, ...]
    artifacts: dict[str, str]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/circuit/test_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/circuit tests/unit/circuit/test_models.py
git commit -m "feat: add circuit intelligence domain models"
```

### Task 2: Add Intent Classification And Topology Selection

**Files:**
- Create: `src/pcbsmith/circuit/intent.py`
- Create: `src/pcbsmith/circuit/topologies.py`
- Test: `tests/unit/circuit/test_intent.py`
- Test: `tests/unit/circuit/test_topologies.py`

- [ ] **Step 1: Write failing classifier tests**

```python
from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent


def test_classifies_supported_divider_highpass_led_request() -> None:
    intent = classify_circuit_intent(
        "Generate a voltage divider connected to a high-pass filter and LED indicator"
    )

    assert intent.status == "supported"
    assert intent.intent_id == "divider_highpass_led_indicator"
    assert intent.assumptions["supply_voltage_v"] == 5.0


def test_rejects_buck_converter_request_for_this_slice() -> None:
    intent = classify_circuit_intent("Generate a 12V to 5V buck converter")

    assert intent.status == "unsupported"
    assert intent.intent_id == "unsupported"
    assert "Only divider/high-pass/LED indicator is supported" in intent.unsupported_reasons[0]
```

- [ ] **Step 2: Write failing topology tests**

```python
from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology


def test_selects_topology_with_formula_evidence() -> None:
    intent = classify_circuit_intent(
        "voltage divider connected to a high-pass filter and led indicator"
    )

    topology = select_topology(intent)

    assert topology.topology_id == "divider_highpass_led_indicator"
    assert topology.status == "selected"
    assert [item.kind for item in topology.evidence] == [
        "textbook_formula",
        "textbook_formula",
        "engineering_assumption",
    ]
    assert topology.warnings == (
        "LED brightness and conduction after AC coupling require simulation and human review.",
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/unit/circuit/test_intent.py tests/unit/circuit/test_topologies.py -q`

Expected: FAIL because `intent.py` and `topologies.py` do not exist.

- [ ] **Step 4: Implement classifier and topology catalogue**

Create `src/pcbsmith/circuit/intent.py`:

```python
from __future__ import annotations

from pcbsmith.circuit.models import CircuitIntent


def classify_circuit_intent(raw_request: str) -> CircuitIntent:
    normalized = raw_request.lower()
    has_divider = "divider" in normalized
    has_highpass = "high-pass" in normalized or "high pass" in normalized or "highpass" in normalized
    has_led = "led" in normalized or "indicator" in normalized
    if has_divider and has_highpass and has_led:
        return CircuitIntent(
            raw_request=raw_request,
            intent_id="divider_highpass_led_indicator",
            status="supported",
            assumptions={
                "supply_voltage_v": 5.0,
                "divider_target_v": 2.5,
                "led_forward_voltage_v": 2.0,
                "led_target_current_ma": 5.0,
            },
        )
    return CircuitIntent(
        raw_request=raw_request,
        intent_id="unsupported",
        status="unsupported",
        unsupported_reasons=(
            "Only divider/high-pass/LED indicator is supported in this vertical slice.",
        ),
    )
```

Create `src/pcbsmith/circuit/topologies.py`:

```python
from __future__ import annotations

from pcbsmith.circuit.models import CircuitIntent, EvidenceRef, TopologySelection


def select_topology(intent: CircuitIntent) -> TopologySelection:
    if intent.intent_id != "divider_highpass_led_indicator" or intent.status != "supported":
        return TopologySelection(
            topology_id="unsupported",
            title="Unsupported topology",
            status="unsupported",
            evidence=(),
            warnings=("No supported topology matched the classified intent.",),
        )
    return TopologySelection(
        topology_id="divider_highpass_led_indicator",
        title="Voltage divider, AC-coupled high-pass, LED indicator",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="textbook_formula",
                title="Voltage divider equation",
                locator="Vout = Vin * Rbottom / (Rtop + Rbottom)",
            ),
            EvidenceRef(
                kind="textbook_formula",
                title="RC high-pass cutoff equation",
                locator="fc = 1 / (2*pi*R*C)",
            ),
            EvidenceRef(
                kind="engineering_assumption",
                title="Generic red LED indicator model",
                locator="Vf=2.0V demo assumption; replace with datasheet-backed LED before fabrication.",
            ),
        ),
        warnings=(
            "LED brightness and conduction after AC coupling require simulation and human review.",
        ),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/circuit/test_intent.py tests/unit/circuit/test_topologies.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pcbsmith/circuit/intent.py src/pcbsmith/circuit/topologies.py tests/unit/circuit/test_intent.py tests/unit/circuit/test_topologies.py
git commit -m "feat: classify first circuit topology"
```

### Task 3: Add Deterministic Passive Calculators

**Files:**
- Create: `src/pcbsmith/calculators/__init__.py`
- Create: `src/pcbsmith/calculators/passive.py`
- Test: `tests/unit/calculators/test_passive.py`

- [ ] **Step 1: Write failing tests**

```python
from __future__ import annotations

import pytest

from pcbsmith.calculators.passive import (
    led_current_limit,
    rc_highpass_cutoff_hz,
    voltage_divider,
)


def test_voltage_divider_calculates_output_and_current() -> None:
    result = voltage_divider(input_voltage_v=5.0, r_top_ohms=10_000.0, r_bottom_ohms=10_000.0)

    assert result == {
        "output_voltage_v": 2.5,
        "divider_current_ma": 0.25,
    }


def test_rc_highpass_cutoff_uses_standard_formula() -> None:
    assert rc_highpass_cutoff_hz(r_ohms=10_000.0, c_farads=100e-9) == 159.155


def test_led_current_limit_calculates_current_and_power() -> None:
    result = led_current_limit(
        supply_voltage_v=5.0,
        led_forward_voltage_v=2.0,
        resistor_ohms=680.0,
    )

    assert result == {
        "led_current_ma": 4.412,
        "resistor_power_w": 0.013,
    }


def test_led_current_limit_rejects_forward_voltage_above_supply() -> None:
    with pytest.raises(ValueError, match="LED forward voltage must be below supply voltage"):
        led_current_limit(
            supply_voltage_v=2.0,
            led_forward_voltage_v=2.1,
            resistor_ohms=680.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/calculators/test_passive.py -q`

Expected: FAIL because `pcbsmith.calculators.passive` does not exist.

- [ ] **Step 3: Implement calculators**

Create `src/pcbsmith/calculators/__init__.py`:

```python
"""Deterministic engineering calculators used by circuit-intelligence tools."""
```

Create `src/pcbsmith/calculators/passive.py`:

```python
from __future__ import annotations

import math


def voltage_divider(
    *,
    input_voltage_v: float,
    r_top_ohms: float,
    r_bottom_ohms: float,
) -> dict[str, float]:
    _positive(input_voltage_v, "input_voltage_v")
    _positive(r_top_ohms, "r_top_ohms")
    _positive(r_bottom_ohms, "r_bottom_ohms")
    total = r_top_ohms + r_bottom_ohms
    return {
        "output_voltage_v": _round(input_voltage_v * (r_bottom_ohms / total)),
        "divider_current_ma": _round((input_voltage_v / total) * 1000.0),
    }


def rc_highpass_cutoff_hz(*, r_ohms: float, c_farads: float) -> float:
    _positive(r_ohms, "r_ohms")
    _positive(c_farads, "c_farads")
    return _round(1.0 / (2.0 * math.pi * r_ohms * c_farads))


def led_current_limit(
    *,
    supply_voltage_v: float,
    led_forward_voltage_v: float,
    resistor_ohms: float,
) -> dict[str, float]:
    _positive(supply_voltage_v, "supply_voltage_v")
    _positive(led_forward_voltage_v, "led_forward_voltage_v")
    _positive(resistor_ohms, "resistor_ohms")
    if led_forward_voltage_v >= supply_voltage_v:
        raise ValueError("LED forward voltage must be below supply voltage")
    current_a = (supply_voltage_v - led_forward_voltage_v) / resistor_ohms
    return {
        "led_current_ma": _round(current_a * 1000.0),
        "resistor_power_w": _round((current_a * current_a) * resistor_ohms),
    }


def _positive(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _round(value: float) -> float:
    return round(value, 3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/calculators/test_passive.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/calculators tests/unit/calculators/test_passive.py
git commit -m "feat: add deterministic passive calculators"
```

### Task 4: Compose Validated Circuit Object

**Files:**
- Create: `src/pcbsmith/generation/__init__.py`
- Create: `src/pcbsmith/generation/divider_highpass_led.py`
- Test: `tests/unit/generation/test_divider_highpass_led.py`

- [ ] **Step 1: Write failing tests for circuit composition**

```python
from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led


def test_composes_circuit_object_with_explicit_roles_and_math() -> None:
    intent = classify_circuit_intent(
        "Generate a voltage divider connected to a high-pass filter and LED indicator"
    )
    topology = select_topology(intent)

    circuit = compose_divider_highpass_led(intent, topology)

    assert circuit.math.status == "warning"
    assert circuit.math.calculations["divider_output_voltage_v"] == 2.5
    assert circuit.math.calculations["highpass_cutoff_hz"] == 159.155
    assert [component.reference for component in circuit.components] == [
        "R1",
        "R2",
        "C1",
        "R3",
        "D1",
    ]
    assert "LED after AC coupling is signal-dependent" in circuit.math.findings[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/generation/test_divider_highpass_led.py -q`

Expected: FAIL because generator package does not exist.

- [ ] **Step 3: Implement circuit composition**

Create `src/pcbsmith/generation/__init__.py`:

```python
"""Schematic-first generation utilities."""
```

Create `src/pcbsmith/generation/divider_highpass_led.py` with:

```python
from __future__ import annotations

from pcbsmith.calculators.passive import (
    led_current_limit,
    rc_highpass_cutoff_hz,
    voltage_divider,
)
from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)


def compose_divider_highpass_led(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported intent for divider/high-pass/LED composition")
    if topology.topology_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported topology for divider/high-pass/LED composition")

    divider = voltage_divider(
        input_voltage_v=5.0,
        r_top_ohms=10_000.0,
        r_bottom_ohms=10_000.0,
    )
    led = led_current_limit(
        supply_voltage_v=5.0,
        led_forward_voltage_v=2.0,
        resistor_ohms=680.0,
    )
    calculations = {
        "divider_output_voltage_v": divider["output_voltage_v"],
        "divider_current_ma": divider["divider_current_ma"],
        "highpass_cutoff_hz": rc_highpass_cutoff_hz(r_ohms=10_000.0, c_farads=100e-9),
        "led_nominal_current_ma": led["led_current_ma"],
        "led_resistor_power_w": led["resistor_power_w"],
    }
    demo_evidence = (
        EvidenceRef(
            kind="assumption",
            title="Generic passive SMD roles",
            locator="0603 R/C/LED are demo bindings until KiCad/library evidence is restored.",
        ),
    )
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=(
            ComponentRole("R1", "divider_top", "stdlib:R", "10k", "demo_only", demo_evidence),
            ComponentRole("R2", "divider_bottom", "stdlib:R", "10k", "demo_only", demo_evidence),
            ComponentRole("C1", "highpass_series_capacitor", "stdlib:C", "100nF", "demo_only", demo_evidence),
            ComponentRole("R3", "led_current_limit", "stdlib:R", "680R", "demo_only", demo_evidence),
            ComponentRole("D1", "indicator_led", "stdlib:LED", "Generic red LED", "demo_only", demo_evidence),
        ),
        nets=("VIN", "DIV_OUT", "HP_OUT", "LED_K", "GND"),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=(
                "LED after AC coupling is signal-dependent; deterministic LED current is only a nominal rail-reference check.",
                "Generic LED/passive bindings are demo-only until backed by real KiCad library and datasheet evidence.",
            ),
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/generation/test_divider_highpass_led.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/generation tests/unit/generation/test_divider_highpass_led.py
git commit -m "feat: compose first validated circuit object"
```

### Task 5: Add ngspice Simulation Wrapper

**Files:**
- Create: `src/pcbsmith/simulation/__init__.py`
- Create: `src/pcbsmith/simulation/ngspice.py`
- Test: `tests/unit/simulation/test_ngspice.py`

- [ ] **Step 1: Write failing ngspice tests**

```python
from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.simulation.ngspice import render_ngspice_netlist, run_ngspice_simulation


def _circuit():
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    return compose_divider_highpass_led(intent, select_topology(intent))


def test_renders_netlist_with_ac_analysis_and_measurements() -> None:
    netlist = render_ngspice_netlist(_circuit())

    assert "V1 VIN 0 DC 5 AC 1" in netlist
    assert "R1 VIN DIV_OUT 10000" in netlist
    assert "C1 DIV_OUT HP_OUT 100n" in netlist
    assert ".ac dec 20 10 100k" in netlist
    assert ".print ac v(HP_OUT)" in netlist


def test_reports_unavailable_when_ngspice_missing(tmp_path: Path) -> None:
    report = run_ngspice_simulation(
        _circuit(),
        tmp_path,
        finder=lambda: None,
    )

    assert report.status == "unavailable"
    assert report.findings == (
        "ngspice executable was not found; set PCBSMITH_NGSPICE or install standalone ngspice before claiming simulation evidence.",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/simulation/test_ngspice.py -q`

Expected: FAIL because simulation package does not exist.

- [ ] **Step 3: Implement ngspice module**

Create `src/pcbsmith/simulation/__init__.py`:

```python
"""Simulation backend integrations."""
```

Create `src/pcbsmith/simulation/ngspice.py`:

```python
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, SimulationReport


def find_ngspice() -> Path | None:
    env_path = os.environ.get("PCBSMITH_NGSPICE")
    if env_path:
        configured_env_path = Path(env_path)
        if configured_env_path.exists():
            return configured_env_path
    configured = Path("D:/AI/PCB designer/Spice64/bin/ngspice_con.exe")
    if configured.exists():
        return configured
    path = shutil.which("ngspice_con") or shutil.which("ngspice")
    return Path(path) if path else None


def render_ngspice_netlist(circuit: CircuitObject) -> str:
    if circuit.topology.topology_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported circuit for ngspice rendering")
    return """* PCBSmith divider + high-pass + LED indicator vertical slice
V1 VIN 0 DC 5 AC 1
R1 VIN DIV_OUT 10000
R2 DIV_OUT 0 10000
C1 DIV_OUT HP_OUT 100n
RLOAD HP_OUT 0 10000
R3 HP_OUT LED_A 680
D1 LED_A 0 DRED
.model DRED D(IS=1e-14 N=2 RS=10 CJO=2p)
.op
.ac dec 20 10 100k
.print ac v(HP_OUT)
.end
"""


def run_ngspice_simulation(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_ngspice,
) -> SimulationReport:
    executable = finder()
    netlist_path = output_dir / ".pcbsmith" / "simulation" / "divider_highpass_led.cir"
    output_path = output_dir / ".pcbsmith" / "simulation" / "ngspice-output.txt"
    netlist_path.parent.mkdir(parents=True, exist_ok=True)
    netlist_path.write_text(render_ngspice_netlist(circuit), encoding="utf-8")
    if executable is None:
        return SimulationReport(
            backend="ngspice",
            status="unavailable",
            findings=(
                "ngspice executable was not found; set PCBSMITH_NGSPICE or install standalone ngspice before claiming simulation evidence.",
            ),
            raw_output_path=str(output_path),
        )
    completed = subprocess.run(
        [str(executable), "-b", "-o", str(output_path), str(netlist_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout or completed.stderr:
        output_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return SimulationReport(
            backend="ngspice",
            status="failed",
            command=(str(executable), "-b", "-o", str(output_path), str(netlist_path)),
            findings=(f"ngspice exited with code {completed.returncode}.",),
            raw_output_path=str(output_path),
        )
    return SimulationReport(
        backend="ngspice",
        status="warning",
        command=(str(executable), "-b", "-o", str(output_path), str(netlist_path)),
        findings=(
            "ngspice ran, but this slice only records execution status; measured pass/fail thresholds are not yet implemented.",
        ),
        raw_output_path=str(output_path),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/simulation/test_ngspice.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/simulation tests/unit/simulation/test_ngspice.py
git commit -m "feat: add ngspice simulation wrapper"
```

### Task 6: Generate Schematic-First PCBSmith Project

**Files:**
- Modify: `src/pcbsmith/generation/divider_highpass_led.py`
- Test: `tests/unit/generation/test_divider_highpass_led.py`

- [ ] **Step 1: Add failing project-generation test**

Append to `tests/unit/generation/test_divider_highpass_led.py`:

```python
from pathlib import Path

from pcbsmith.services.project_io import load_project, load_schematic
from pcbsmith.services.erc import run_erc
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.generation.divider_highpass_led import write_divider_highpass_led_project


def test_writes_schematic_first_project_that_passes_pcbs_erc(tmp_path: Path) -> None:
    intent = classify_circuit_intent(
        "Generate a voltage divider connected to a high-pass filter and LED indicator"
    )
    circuit = compose_divider_highpass_led(intent, select_topology(intent))

    write_divider_highpass_led_project(circuit, tmp_path, project_name="Slice")

    project = load_project(tmp_path)
    schematic = load_schematic(tmp_path, project.schematics[0])
    issues = run_erc(schematic, SYMBOLS)

    assert project.name == "Slice"
    assert [symbol.reference for symbol in schematic.symbols] == ["P1", "R1", "R2", "C1", "RLOAD", "R3", "D1", "GND1"]
    assert issues == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/generation/test_divider_highpass_led.py -q`

Expected: FAIL because `write_divider_highpass_led_project` does not exist.

- [ ] **Step 3: Implement schematic-first writer**

Add to `src/pcbsmith/generation/divider_highpass_led.py`:

```python
from pathlib import Path

from pcbsmith.core.board import Board
from pcbsmith.core.geom import Point
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire
from pcbsmith.services.project_io import save_board, save_project, save_schematic

NM = 1_000_000


def write_divider_highpass_led_project(
    circuit: CircuitObject,
    project_dir: Path,
    *,
    project_name: str,
) -> None:
    if circuit.topology.topology_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported circuit for project generation")
    project = Project(name=project_name)
    schematic = _schematic_for_divider_highpass_led()
    save_project(project_dir, project)
    save_schematic(project_dir, project.schematics[0], schematic)
    save_board(project_dir, project.boards[0], Board(id="main"))


def _schematic_for_divider_highpass_led() -> Schematic:
    return Schematic(
        id="main",
        symbols=(
            SymbolInstance(reference="P1", symbol_id="stdlib:CONN_01X02", value="5V input", position=Point(x=0, y=0)),
            SymbolInstance(reference="R1", symbol_id="stdlib:R", value="10k", position=Point(x=15 * NM, y=0)),
            SymbolInstance(reference="R2", symbol_id="stdlib:R", value="10k", position=Point(x=15 * NM, y=10 * NM), rotation_deg=90),
            SymbolInstance(reference="C1", symbol_id="stdlib:C", value="100nF", position=Point(x=30 * NM, y=0)),
            SymbolInstance(reference="RLOAD", symbol_id="stdlib:R", value="10k", position=Point(x=45 * NM, y=10 * NM), rotation_deg=90),
            SymbolInstance(reference="R3", symbol_id="stdlib:R", value="680R", position=Point(x=60 * NM, y=0)),
            SymbolInstance(reference="D1", symbol_id="stdlib:LED", value="Generic red LED", position=Point(x=75 * NM, y=0)),
            SymbolInstance(reference="GND1", symbol_id="stdlib:GND", value="GND", position=Point(x=15 * NM, y=20 * NM)),
        ),
        wires=(
            Wire(points=(Point(x=0, y=0), Point(x=9_920_000, y=0))),
            Wire(points=(Point(x=20_080_000, y=0), Point(x=24_920_000, y=0))),
            Wire(points=(Point(x=15_000_000, y=5_080_000), Point(x=15_000_000, y=20_000_000))),
            Wire(points=(Point(x=35_080_000, y=0), Point(x=54_920_000, y=0))),
            Wire(points=(Point(x=45_000_000, y=5_080_000), Point(x=45_000_000, y=20_000_000), Point(x=15_000_000, y=20_000_000))),
            Wire(points=(Point(x=65_080_000, y=0), Point(x=69_920_000, y=0))),
            Wire(points=(Point(x=80_080_000, y=0), Point(x=80_080_000, y=20_000_000), Point(x=15_000_000, y=20_000_000))),
            Wire(points=(Point(x=0, y=2_540_000), Point(x=0, y=20_000_000), Point(x=15_000_000, y=20_000_000))),
        ),
        labels=(
            NetLabel(name="VIN", position=Point(x=5 * NM, y=0)),
            NetLabel(name="DIV_OUT", position=Point(x=22 * NM, y=0)),
            NetLabel(name="HP_OUT", position=Point(x=50 * NM, y=0)),
            NetLabel(name="GND", position=Point(x=15 * NM, y=20 * NM)),
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/generation/test_divider_highpass_led.py -q`

Expected: PASS. If ERC fails because of exact pin-tip coordinates, fix only the schematic coordinates and add an assertion for the expected netlist names.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/generation/divider_highpass_led.py tests/unit/generation/test_divider_highpass_led.py
git commit -m "feat: generate schematic-first divider highpass led project"
```

### Task 7: Add Consolidated Review Bundle

**Files:**
- Create: `src/pcbsmith/review/__init__.py`
- Create: `src/pcbsmith/review/circuit_bundle.py`
- Test: `tests/unit/review/test_circuit_bundle.py`

- [ ] **Step 1: Write failing review bundle test**

```python
from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.review.circuit_bundle import write_circuit_review_bundle
from pcbsmith.simulation.ngspice import run_ngspice_simulation


def test_review_bundle_records_math_simulation_and_human_review_items(tmp_path: Path) -> None:
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    circuit = compose_divider_highpass_led(intent, select_topology(intent))
    simulation = run_ngspice_simulation(circuit, tmp_path, finder=lambda: None)

    bundle_path = write_circuit_review_bundle(
        circuit,
        tmp_path,
        simulation_report=simulation,
        kicad_status="not_run",
        artifacts={"pcbs_project": str(tmp_path)},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-circuit-review-bundle-v1"
    assert data["status"] == "needs_human_review"
    assert (
        "ngspice executable was not found; set PCBSMITH_NGSPICE or install standalone ngspice before claiming simulation evidence."
        in data["items"]
    )
    assert "Generic LED/passive bindings are demo-only until backed by real KiCad library and datasheet evidence." in data["items"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/review/test_circuit_bundle.py -q`

Expected: FAIL because review package does not exist.

- [ ] **Step 3: Implement review bundle writer**

Create `src/pcbsmith/review/__init__.py`:

```python
"""Review bundle writers."""
```

Create `src/pcbsmith/review/circuit_bundle.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, CircuitReviewBundle, SimulationReport


def write_circuit_review_bundle(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    simulation_report: SimulationReport,
    kicad_status: str,
    artifacts: dict[str, str],
) -> Path:
    items: list[str] = []
    items.extend(circuit.topology.warnings)
    items.extend(circuit.math.findings)
    items.extend(simulation_report.findings)
    if kicad_status != "passed":
        items.append(f"KiCad validation status: {kicad_status}.")
    if any(component.support_status != "supported" for component in circuit.components):
        items.append("One or more selected components are demo-only or need datasheet review.")

    status = "needs_human_review" if items else "passed"
    bundle = CircuitReviewBundle(
        schema="pcbsmith-circuit-review-bundle-v1",
        intent_id=circuit.intent.intent_id,
        status=status,
        items=tuple(dict.fromkeys(items)),
        artifacts=artifacts,
    )
    path = output_dir / "review-bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle.model_dump(), indent=2) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/review/test_circuit_bundle.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/review tests/unit/review/test_circuit_bundle.py
git commit -m "feat: write first circuit review bundle"
```

### Task 8: Add CLI Vertical Slice

**Files:**
- Modify: `src/pcbsmith/cli.py`
- Test: `tests/integration/test_divider_highpass_led_cli.py`

- [ ] **Step 1: Write failing CLI integration test**

```python
from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.cli import main


def test_design_divider_highpass_led_writes_review_bundle(tmp_path: Path) -> None:
    output_dir = tmp_path / "slice"

    exit_code = main(
        [
            "design-divider-highpass-led",
            str(output_dir),
            "--request",
            "Generate a voltage divider connected to a high-pass filter and LED indicator",
            "--name",
            "Trusted Slice",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "project.pcbsmith.json").exists()
    data = json.loads((output_dir / "review-bundle.json").read_text(encoding="utf-8"))
    assert data["status"] == "needs_human_review"
    assert data["artifacts"]["pcbs_project"] == str(output_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_divider_highpass_led_cli.py -q`

Expected: FAIL because the CLI subcommand does not exist.

- [ ] **Step 3: Implement CLI command**

Modify `src/pcbsmith/cli.py` imports:

```python
from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import (
    compose_divider_highpass_led,
    write_divider_highpass_led_project,
)
from pcbsmith.review.circuit_bundle import write_circuit_review_bundle
from pcbsmith.simulation.ngspice import run_ngspice_simulation
```

Add command function:

```python
def _cmd_design_divider_highpass_led(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    topology = select_topology(intent)
    circuit = compose_divider_highpass_led(intent, topology)
    write_divider_highpass_led_project(circuit, output_dir, project_name=args.name)
    simulation = run_ngspice_simulation(circuit, output_dir)
    bundle_path = write_circuit_review_bundle(
        circuit,
        output_dir,
        simulation_report=simulation,
        kicad_status="not_run",
        artifacts={"pcbs_project": str(output_dir), "review_bundle": str(output_dir / "review-bundle.json")},
    )
    print(f"Review bundle: {bundle_path}")
    print(f"Status: needs_human_review")
    return 0
```

Add parser entry:

```python
    design_parser = subparsers.add_parser(
        "design-divider-highpass-led",
        help="generate the first circuit-intelligence vertical slice",
    )
    design_parser.add_argument("output")
    design_parser.add_argument("--request", required=True)
    design_parser.add_argument("--name", required=True)
    design_parser.set_defaults(func=_cmd_design_divider_highpass_led)
```

- [ ] **Step 4: Run CLI integration test**

Run: `python -m pytest tests/integration/test_divider_highpass_led_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/cli.py tests/integration/test_divider_highpass_led_cli.py
git commit -m "feat: add circuit intelligence vertical slice cli"
```

### Task 9: Restore Minimal KiCad Validation Path

**Files:**
- Create: `src/pcbsmith/kicad/__init__.py`
- Create: `src/pcbsmith/kicad/validate.py`
- Modify: `src/pcbsmith/review/circuit_bundle.py`
- Modify: `src/pcbsmith/cli.py`
- Test: `tests/unit/kicad/test_validate.py`
- Test: `tests/integration/test_divider_highpass_led_cli.py`

- [ ] **Step 1: Write failing unit test with fake runner**

```python
from __future__ import annotations

from pathlib import Path

from pcbsmith.kicad.validate import KiCadProcessResult, run_kicad_validation


def test_kicad_validation_reports_unavailable_without_cli(tmp_path: Path) -> None:
    report = run_kicad_validation(tmp_path, finder=lambda: None)

    assert report.status == "unavailable"
    assert report.findings == ("KiCad CLI was not found; ERC/DRC were not run.",)


def test_kicad_validation_runs_planned_checks_with_fake_cli(tmp_path: Path) -> None:
    sch = tmp_path / "Demo.kicad_sch"
    pcb = tmp_path / "Demo.kicad_pcb"
    sch.write_text("(kicad_sch)", encoding="utf-8")
    pcb.write_text("(kicad_pcb)", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> KiCadProcessResult:
        commands.append(command)
        return KiCadProcessResult(returncode=0, stdout="", stderr="")

    report = run_kicad_validation(tmp_path, finder=lambda: Path("kicad-cli"), runner=runner)

    assert report.status == "passed"
    assert [command[1:3] for command in commands] == [("sch", "erc"), ("pcb", "drc")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/kicad/test_validate.py -q`

Expected: FAIL because `pcbsmith.kicad.validate` does not exist.

- [ ] **Step 3: Implement minimal validation wrapper**

Create `src/pcbsmith/kicad/__init__.py`:

```python
"""KiCad CLI integration."""
```

Create `src/pcbsmith/kicad/validate.py` with a minimal subprocess wrapper adapted from the archived `old_files/.../kicad_validate.py`, but simplified to:

```python
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class KiCadProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    stdout: str
    stderr: str


class KiCadValidationSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    findings: tuple[str, ...]


def find_kicad_cli() -> Path | None:
    path = shutil.which("kicad-cli")
    fallback = Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")
    if path:
        return Path(path)
    if fallback.exists():
        return fallback
    return None


def run_kicad_validation(
    project_dir: Path,
    *,
    finder: Callable[[], Path | None] = find_kicad_cli,
    runner: Callable[[tuple[str, ...]], KiCadProcessResult] | None = None,
) -> KiCadValidationSummary:
    cli = finder()
    if cli is None:
        return KiCadValidationSummary(
            status="unavailable",
            findings=("KiCad CLI was not found; ERC/DRC were not run.",),
        )
    schematic = _single_file(project_dir, "*.kicad_sch")
    board = _single_file(project_dir, "*.kicad_pcb")
    runner = _run if runner is None else runner
    commands = (
        (str(cli), "sch", "erc", str(schematic)),
        (str(cli), "pcb", "drc", str(board)),
    )
    findings: list[str] = []
    for command in commands:
        result = runner(command)
        if result.returncode != 0:
            findings.append(result.stderr.strip() or result.stdout.strip() or f"{command[1]} {command[2]} failed")
    return KiCadValidationSummary(status="failed" if findings else "passed", findings=tuple(findings))


def _single_file(project_dir: Path, pattern: str) -> Path:
    matches = sorted(project_dir.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {pattern} file in {project_dir}")
    return matches[0]


def _run(command: tuple[str, ...]) -> KiCadProcessResult:
    completed = subprocess.run(list(command), text=True, capture_output=True, check=False)
    return KiCadProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
```

- [ ] **Step 4: Wire report into review bundle**

Modify the CLI to call KiCad validation only when KiCad project export exists. For this first slice, if no KiCad exporter is implemented yet, keep `kicad_status="not_run"` and add a review item saying `KiCad native export is not implemented for this slice yet.`

This is an honest stopping point. Do not claim KiCad validation is global or complete unless Task 10 also implements KiCad export.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/unit/kicad/test_validate.py tests/integration/test_divider_highpass_led_cli.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pcbsmith/kicad src/pcbsmith/cli.py src/pcbsmith/review/circuit_bundle.py tests/unit/kicad/test_validate.py tests/integration/test_divider_highpass_led_cli.py
git commit -m "feat: add minimal kicad validation wrapper"
```

### Task 10: Optional KiCad Native Export For This Slice

**Files:**
- Create: `src/pcbsmith/kicad/project.py`
- Create: `src/pcbsmith/kicad/export_divider_highpass_led.py`
- Modify: `src/pcbsmith/cli.py`
- Test: `tests/unit/kicad/test_export_divider_highpass_led.py`
- Test: `tests/integration/test_divider_highpass_led_cli.py`

- [ ] **Step 1: Decide whether this is in-scope for the first execution batch**

This task is optional for the first implementation pass. If it is skipped, the review bundle must explicitly say:

```text
KiCad native schematic/PCB export is not implemented for this slice yet; PCBSmith JSON schematic and ERC are the only generated EDA artifacts.
```

- [ ] **Step 2: If in scope, write tests before implementation**

```python
from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.kicad.export_divider_highpass_led import export_divider_highpass_led_to_kicad


def test_exports_minimal_kicad_files(tmp_path: Path) -> None:
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    circuit = compose_divider_highpass_led(intent, select_topology(intent))

    result = export_divider_highpass_led_to_kicad(circuit, tmp_path, project_name="Slice")

    assert result["project_file"].endswith("Slice.kicad_pro")
    assert (tmp_path / "Slice.kicad_sch").exists()
    assert (tmp_path / "Slice.kicad_pcb").exists()
    assert "PCBSmith" in (tmp_path / "Slice.kicad_sch").read_text(encoding="utf-8")
```

- [ ] **Step 3: Implement by adapting only narrow skeleton rendering**

Adapt the old `kicad_project.py` skeleton functions into `src/pcbsmith/kicad/project.py`. Generate a minimal KiCad project and include only a simple board outline if real footprint placement is not implemented.

- [ ] **Step 4: Mark KiCad validation scope honestly**

If KiCad ERC/DRC passes on the minimal skeleton, the review bundle must still say:

```text
KiCad validation covers generated KiCad file syntax/EDA checks, not analog circuit correctness.
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/unit/kicad/test_export_divider_highpass_led.py tests/integration/test_divider_highpass_led_cli.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pcbsmith/kicad tests/unit/kicad/test_export_divider_highpass_led.py tests/integration/test_divider_highpass_led_cli.py
git commit -m "feat: export first circuit slice to kicad"
```

### Task 11: Local-AI Safe Tool Loop Contract

**Files:**
- Create: `src/pcbsmith/circuit/tool_contract.py`
- Test: `tests/unit/circuit/test_tool_contract.py`

- [ ] **Step 1: Write failing contract test**

```python
from __future__ import annotations

from pcbsmith.circuit.tool_contract import circuit_intelligence_tool_contract


def test_tool_contract_allows_one_safe_action_per_turn() -> None:
    contract = circuit_intelligence_tool_contract()

    assert contract["schema"] == "pcbsmith-circuit-intelligence-tool-contract-v1"
    assert contract["allowed_actions"] == [
        "classify_intent",
        "select_topology",
        "run_deterministic_math",
        "run_ngspice",
        "write_review_bundle",
    ]
    assert contract["rules"][0] == "Return exactly one JSON object, not an array of tool calls."
    assert "Do not generate PCB files before schematic-first circuit object validation." in contract["rules"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/circuit/test_tool_contract.py -q`

Expected: FAIL because contract module does not exist.

- [ ] **Step 3: Implement safe local-AI contract**

Create `src/pcbsmith/circuit/tool_contract.py`:

```python
from __future__ import annotations

from typing import Any


def circuit_intelligence_tool_contract() -> dict[str, Any]:
    return {
        "schema": "pcbsmith-circuit-intelligence-tool-contract-v1",
        "allowed_actions": [
            "classify_intent",
            "select_topology",
            "run_deterministic_math",
            "run_ngspice",
            "write_review_bundle",
        ],
        "rules": [
            "Return exactly one JSON object, not an array of tool calls.",
            "Do not generate PCB files before schematic-first circuit object validation.",
            "Treat ngspice unavailable or failed as a review blocker, not as success.",
            "Treat KiCad ERC/DRC as EDA validation, not proof of analog behavior.",
            "Unsupported topology requests must return unsupported with reasons.",
        ],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/circuit/test_tool_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pcbsmith/circuit/tool_contract.py tests/unit/circuit/test_tool_contract.py
git commit -m "feat: add safe circuit intelligence tool contract"
```

### Task 12: Verification And Documentation Update

**Files:**
- Modify: `README.md`
- Create or modify: `docs/project-handoff.md` only if the user wants the root docs restored now.

- [ ] **Step 1: Run targeted tests without Qt plugin pollution if possible**

Try:

```powershell
python -m pytest tests/unit/circuit tests/unit/calculators tests/unit/simulation tests/unit/generation tests/unit/review tests/integration/test_divider_highpass_led_cli.py -q
```

Expected: PASS, unless the active environment still fails during pytest plugin loading.

- [ ] **Step 2: If pytest still fails before collection, record exact blocker**

Add a verification note to the final implementation summary:

```text
Tests could not collect because the active Anaconda environment auto-loads pytestqt and fails importing QtCore. Set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 or use the project venv before rerunning.
```

- [ ] **Step 3: Run with plugin autoload disabled**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest tests/unit/circuit tests/unit/calculators tests/unit/simulation tests/unit/generation tests/unit/review tests/integration/test_divider_highpass_led_cli.py -q
```

Expected: PASS.

- [ ] **Step 4: Run CLI smoke**

```powershell
python -m pcbsmith.cli design-divider-highpass-led .tmp\divider-highpass-led-slice --name "Divider Highpass LED Slice" --request "Generate a voltage divider connected to a high-pass filter and LED indicator"
```

Expected:

```text
Review bundle: .tmp\divider-highpass-led-slice\review-bundle.json
Status: needs_human_review
```

- [ ] **Step 5: Inspect review bundle**

Confirm `review-bundle.json` includes:

- topology evidence;
- deterministic math findings;
- ngspice status, including `unavailable` when ngspice is absent;
- KiCad status as `not_run` unless Task 10 is completed;
- explicit demo-only/datasheet-review warnings.

- [ ] **Step 6: Update README**

Add a short section:

```markdown
## Circuit Intelligence Slice

`design-divider-highpass-led` is the first constrained circuit-intelligence vertical slice. It classifies one supported request family, selects a documented topology, runs deterministic passive calculations, writes a schematic-first PCBSmith project, attempts ngspice simulation, and writes `review-bundle.json`.

This command is not a general circuit generator. A `needs_human_review` result is expected while generic parts, absent ngspice, or missing KiCad-native export remain unresolved.
```

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: document first circuit intelligence slice"
```

---

## Self-Review

- Spec coverage:
  - Intent classification: Task 2.
  - Topology selection with evidence: Task 2.
  - Reference/datasheet evidence: Task 2 and Task 4 include explicit evidence, with demo-only warnings instead of pretending datasheets exist.
  - Deterministic math tools: Task 3 and Task 4.
  - ngspice simulation integration: Task 5.
  - Schematic-first generation: Task 6.
  - PCB/KiCad generation from validated objects: Task 10 is optional and must be reported as not implemented if skipped.
  - Consolidated validation/revision reports: Task 7.
  - Safe local-AI tool loop support: Task 11.
- Placeholder scan:
  - No `TBD` or `TODO` steps are used as implementation requirements.
  - Optional Task 10 has a defined honest fallback if skipped.
- Type consistency:
  - `CircuitIntent`, `TopologySelection`, `CircuitObject`, `SimulationReport`, and `CircuitReviewBundle` are defined before later tasks use them.
  - CLI uses the same function names introduced in earlier tasks.

## Execution Recommendation

Start with Tasks 1 through 8. That gives a working vertical slice with honest `ngspice unavailable` and `KiCad not_run` reporting. Then decide whether to include Task 10 immediately or leave KiCad-native export as the next slice; forcing KiCad export too early risks recreating the same “pretty board, weak evidence” failure mode.
