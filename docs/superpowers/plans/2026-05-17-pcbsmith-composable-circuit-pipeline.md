# PCBSmith Composable Circuit Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore schematic-backed generation and make PCBSmith compose reusable circuit blocks instead of relying on board-specific scripts.

**Architecture:** Add a circuit-intent layer between user/AI requests and KiCad output. Generators produce reusable `CircuitDesign` fragments with components, pins, nets, and layout hints; operations compose those fragments, export a real KiCad schematic, then generate or revise the PCB layout from the same electrical source of truth. R9 broad composition builds on the same fragment API so prebuilt arrays and common circuits can be combined.

**Tech Stack:** Python 3.12, Pydantic models, existing `pcbsmith.core.schematic`, `pcbsmith.kicad.kicad_export`, KiCad CLI validation/preview, pytest/ruff/mypy.

---

## File Structure

- Create `src/pcbsmith/core/circuit.py`: reusable electrical intent models: components, pins, nets, fragments, and composition validation.
- Create `tests/unit/core/test_circuit.py`: unit tests for fragment composition, net merging, duplicate reference detection, and reusable block reuse.
- Create `src/pcbsmith/generators/led_art_circuit.py`: convert `LedArtPlan` into a `CircuitDesign` with LED strings, current-limit resistors, power input, optional MOSFET control, and schematic layout hints.
- Create `tests/unit/generators/test_led_art_circuit.py`: tests for 5V and 12V LED-art circuit topology correctness.
- Create `src/pcbsmith/kicad/circuit_schematic.py`: convert `CircuitDesign` into existing `Schematic` and KiCad schematic body items.
- Create `tests/unit/kicad/test_circuit_schematic.py`: tests for real symbols, wires, labels, and non-empty KiCad schematic exports.
- Modify `src/pcbsmith/operations/design_operations.py`: use the circuit-schematic path for LED-art operations before layout export.
- Modify `tests/unit/operations/test_design_operations.py`: assert LED-art operations write real schematic content, not only a placeholder.
- Later modify `src/pcbsmith/generators/led_art_board.py`: consume circuit net names from `CircuitDesign` so PCB and schematic agree.

---

## Task 1: Core Composable Circuit Model

**Files:**
- Create: `src/pcbsmith/core/circuit.py`
- Test: `tests/unit/core/test_circuit.py`

- [ ] **Step 1: Write failing tests for reusable circuit fragments**

```python
from __future__ import annotations

import pytest

from pcbsmith.core.circuit import (
    CircuitComponent,
    CircuitDesign,
    CircuitNet,
    CircuitPin,
    compose_circuit_designs,
)


def test_compose_circuit_designs_merges_named_nets_and_preserves_components() -> None:
    led_block = CircuitDesign(
        name="led-block",
        components=(
            CircuitComponent(
                reference="R1",
                symbol_id="stdlib:R",
                value="680",
                pins=(CircuitPin(number="1", net="VCC"), CircuitPin(number="2", net="LED_A")),
            ),
            CircuitComponent(
                reference="LED1",
                symbol_id="stdlib:LED",
                value="Red LED",
                pins=(CircuitPin(number="1", net="LED_A"), CircuitPin(number="2", net="GND")),
            ),
        ),
        nets=(CircuitNet(name="VCC"), CircuitNet(name="LED_A"), CircuitNet(name="GND")),
    )
    power_block = CircuitDesign(
        name="power",
        components=(
            CircuitComponent(
                reference="J1",
                symbol_id="stdlib:CONN_01X02",
                value="5V IN",
                pins=(CircuitPin(number="1", net="VCC"), CircuitPin(number="2", net="GND")),
            ),
        ),
        nets=(CircuitNet(name="VCC"), CircuitNet(name="GND")),
    )

    design = compose_circuit_designs("combined", power_block, led_block)

    assert [component.reference for component in design.components] == ["J1", "R1", "LED1"]
    assert sorted(net.name for net in design.nets) == ["GND", "LED_A", "VCC"]


def test_compose_circuit_designs_rejects_duplicate_references() -> None:
    first = CircuitDesign(
        name="a",
        components=(CircuitComponent(reference="R1", symbol_id="stdlib:R", value="1k"),),
    )
    second = CircuitDesign(
        name="b",
        components=(CircuitComponent(reference="R1", symbol_id="stdlib:R", value="330"),),
    )

    with pytest.raises(ValueError, match="Duplicate circuit component reference"):
        compose_circuit_designs("bad", first, second)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\core\test_circuit.py -q
```

Expected: import failure because `pcbsmith.core.circuit` does not exist.

- [ ] **Step 3: Implement the minimal circuit model**

Create `src/pcbsmith/core/circuit.py` with frozen Pydantic models:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CircuitPin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str
    net: str | None = None
    role: str | None = None


class CircuitComponent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    symbol_id: str
    value: str
    footprint_id: str | None = None
    pins: tuple[CircuitPin, ...] = ()


class CircuitNet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    role: str | None = None


class CircuitDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    components: tuple[CircuitComponent, ...] = ()
    nets: tuple[CircuitNet, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def references_are_unique(self) -> CircuitDesign:
        references = [component.reference for component in self.components]
        if len(references) != len(set(references)):
            raise ValueError("Duplicate circuit component reference")
        return self


def compose_circuit_designs(name: str, *designs: CircuitDesign) -> CircuitDesign:
    components = tuple(component for design in designs for component in design.components)
    nets_by_name: dict[str, CircuitNet] = {}
    notes: list[str] = []
    for design in designs:
        notes.extend(design.notes)
        for net in design.nets:
            nets_by_name.setdefault(net.name, net)
        for component in design.components:
            for pin in component.pins:
                if pin.net is not None:
                    nets_by_name.setdefault(pin.net, CircuitNet(name=pin.net))
    return CircuitDesign(
        name=name,
        components=components,
        nets=tuple(nets_by_name.values()),
        notes=tuple(notes),
    )
```

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\core\test_circuit.py -q
```

Expected: tests pass.

---

## Task 2: LED Art Electrical Intent To Circuit Design

**Files:**
- Create: `src/pcbsmith/generators/led_art_circuit.py`
- Test: `tests/unit/generators/test_led_art_circuit.py`

- [ ] **Step 1: Write failing tests for LED-art circuit composition**

```python
from pcbsmith.generators.led_art import LedArtSpec, build_led_art_plan_for_topology
from pcbsmith.generators.led_art_circuit import led_art_plan_to_circuit_design


def test_led_art_5v_circuit_contains_input_resistors_and_leds() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="V"), "5v_one_per_led")

    circuit = led_art_plan_to_circuit_design(plan, control_mode="none")

    assert circuit.name == "V LED art"
    assert any(component.reference == "J1" for component in circuit.components)
    assert sum(1 for component in circuit.components if component.symbol_id == "stdlib:R") == len(plan.strings)
    assert sum(1 for component in circuit.components if component.symbol_id == "stdlib:LED") == len(plan.pixels)
    assert {"VCC", "GND"}.issubset({net.name for net in circuit.nets})


def test_led_art_mosfet_control_adds_switching_component_and_control_net() -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text="I"), "5v_one_per_led")

    circuit = led_art_plan_to_circuit_design(plan, control_mode="low_side_mosfet")

    assert any(component.reference == "Q1" and component.symbol_id == "stdlib:NMOS" for component in circuit.components)
    assert "CTRL" in {net.name for net in circuit.nets}
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\generators\test_led_art_circuit.py -q
```

Expected: import failure because `led_art_circuit` does not exist.

- [ ] **Step 3: Implement LED-art circuit builder**

Create components for one input connector, each resistor, each LED, optional MOSFET, and nets from the LED strings. Keep schematic layout separate for the next task.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\generators\test_led_art_circuit.py -q
```

Expected: tests pass.

---

## Task 3: Circuit Design To Real Schematic

**Files:**
- Create: `src/pcbsmith/kicad/circuit_schematic.py`
- Test: `tests/unit/kicad/test_circuit_schematic.py`

- [ ] **Step 1: Write failing tests for schematic export**

Test that a tiny composed circuit becomes a `Schematic` with real symbols, wires, labels, and renderable KiCad text using existing `render_kicad_schematic_items`.

- [ ] **Step 2: Implement deterministic schematic layout**

Map components to rows, wire pins by shared net, and place labels for `VCC`, `GND`, and named signal nets. This first layout only needs to be readable and electrically correct; visual polish comes after.

- [ ] **Step 3: Verify with KiCad schematic SVG export**

Generate a small fixture schematic and confirm the SVG contains actual component text such as `R1`, `LED1`, and `J1`.

---

## Task 4: Make 5V LED Art Operation Schematic-Backed

**Files:**
- Modify: `src/pcbsmith/operations/design_operations.py`
- Test: `tests/unit/operations/test_design_operations.py`

- [ ] **Step 1: Add failing test**

Assert `generate_led_art_design(... topology="5v_one_per_led")` writes a `.kicad_sch` containing LED/resistor/input symbols and no board-only placeholder.

- [ ] **Step 2: Route LED-art operation through circuit builder**

Build the `CircuitDesign`, convert it to a real schematic, and write the KiCad schematic before writing the PCB.

- [ ] **Step 3: Verify operation output**

Run:

```powershell
.\.venv\Scripts\python.exe -m pcbsmith.cli design-led-art outputs\r8-smoke-vir-lab-5v --name "R8 Smoke VIR LAB 5V" --text "VIR-LAB" --topology 5v_one_per_led --control low_side_mosfet --overwrite
```

Expected: validation passes, schematic SVG is not blank, board SVG still exports.

---

## Task 5: Fix 12V Dense As A Circuit-Backed Layout Problem

**Files:**
- Modify: `src/pcbsmith/generators/led_art_board.py`
- Test: `tests/unit/generators/test_led_art_board.py`

- [ ] **Step 1: Keep 12V DRC failure as regression target**

Add a test or captured revision fixture proving current dense string routing creates unsafe via/track clearance.

- [ ] **Step 2: Move string routing away from via-in-pad style joins**

Use a shared-string path with deliberate pad escapes and clearance from adjacent nets.

- [ ] **Step 3: Verify DRC**

Run the 12V operation and require KiCad DRC to pass before treating it as a valid demo.

---

## Task 6: R9 General Circuit Composer

**Files:**
- Create: `src/pcbsmith/operations/circuit_composer.py`
- Test: `tests/unit/operations/test_circuit_composer.py`

- [ ] **Step 1: Add reusable block registry**

Define named blocks such as `power_input_2pin`, `led_string`, `low_side_mosfet_switch`, `decoupling_capacitor`, and `gpio_led_output`.

- [ ] **Step 2: Add composition API**

Expose a function that takes a structured request with block names and net bindings, composes a single `CircuitDesign`, and rejects duplicate references or incompatible nets.

- [ ] **Step 3: Add CLI/AI operation**

Add a future `design-circuit` operation that accepts a JSON request, composes blocks, generates a schematic, and only then generates a PCB layout when a supported layout strategy exists.

---

## Self-Review

- Spec coverage: covers schematic-backed LED art, composable circuit blocks, reusable arrays, R9 block composition, validation, and the current board-first regression.
- Placeholder scan: no implementation step depends on undefined future behavior without naming the file and test that introduces it.
- Scope check: the plan is intentionally staged. Tasks 1-4 restore coherence for 5V LED art; Task 5 fixes the known 12V dense DRC issue; Task 6 starts R9 broad composition.
