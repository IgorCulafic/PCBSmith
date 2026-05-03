# PCBSmith Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the PDF-aligned Phase 0 foundation for PCBSmith: package skeleton, pure domain model, project I/O, netlist derivation, minimal ERC, CLI, fixtures, and verification.

**Architecture:** Keep `core/` pure and UI-free, put side effects in `services/`, and expose Phase 0 through `pcbsmith.cli`. The data model is JSON/Pydantic-first, uses integer nanometre coordinates, and keeps schematic and board domains separate with netlists as the contract.

**Tech Stack:** Python 3.11+, Pydantic 2.x, pytest, Hypothesis, Ruff, mypy, import-linter, argparse, JSON project folders.

---

## Source References

- Product design: `docs/superpowers/specs/2026-05-03-pcbsmith-phase-0-design.md`
- Full reference PDF: `docs/reference/PCB_Application_Specification.pdf`
- Relevant PDF sections: Chapter 4 architecture/data model, Chapter 5 stack/skeleton, Chapter 6 Phase 0 tasks, Chapter 17 testing strategy.

## File Structure

Create this layout:

```text
pyproject.toml
README.md
LICENSE
src/pcbsmith/__init__.py
src/pcbsmith/cli.py
src/pcbsmith/core/__init__.py
src/pcbsmith/core/ids.py
src/pcbsmith/core/geom.py
src/pcbsmith/core/library.py
src/pcbsmith/core/schematic.py
src/pcbsmith/core/board.py
src/pcbsmith/core/project.py
src/pcbsmith/core/netops.py
src/pcbsmith/services/__init__.py
src/pcbsmith/services/builtin_library.py
src/pcbsmith/services/project_io.py
src/pcbsmith/services/erc.py
tests/conftest.py
tests/fixtures/voltage_divider/project.pcbsmith.json
tests/fixtures/voltage_divider/schematics/main.sch.json
tests/fixtures/voltage_divider/boards/main.brd.json
tests/unit/core/test_ids.py
tests/unit/core/test_geom.py
tests/unit/core/test_library_models.py
tests/unit/core/test_schematic_models.py
tests/unit/core/test_board_models.py
tests/unit/core/test_project_models.py
tests/unit/core/test_netops.py
tests/unit/services/test_builtin_library.py
tests/unit/services/test_project_io.py
tests/unit/services/test_erc.py
tests/integration/test_cli.py
```

Responsibilities:

- `ids.py`: typed string IDs and ID factory helpers.
- `geom.py`: integer nanometre units and geometry primitives.
- `library.py`: reusable symbol/footprint template models.
- `schematic.py`: logical schematic objects only.
- `board.py`: physical board objects only.
- `project.py`: project root, design rules, file references.
- `netops.py`: pure netlist derivation.
- `builtin_library.py`: small development library for tests and Phase 0 examples.
- `project_io.py`: project folder creation, loading, saving, and validation.
- `erc.py`: minimal electrical rule checks over schematic plus netlist.
- `cli.py`: command-line entry point.

## Task 1: Repository Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `LICENSE`
- Create: `src/pcbsmith/__init__.py`
- Create: `src/pcbsmith/core/__init__.py`
- Create: `src/pcbsmith/services/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create package directories**

Create the directories listed in the file structure. Keep `ui/` absent for Phase 0; the CLI is enough.

- [ ] **Step 2: Add project configuration**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "pcbsmith"
version = "0.1.0"
description = "Prompt-aware PCB design foundation with validated schematic and board data models."
readme = "README.md"
requires-python = ">=3.11,<3.14"
license = "AGPL-3.0-or-later"
authors = [{ name = "PCBSmith contributors" }]
dependencies = [
  "pydantic>=2.7,<3",
]

[project.optional-dependencies]
dev = [
  "hypothesis>=6.100",
  "import-linter>=2.0",
  "mypy>=1.10",
  "pytest>=8.0",
  "ruff>=0.5",
]

[project.scripts]
pcbsmith = "pcbsmith.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/pcbsmith"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"
plugins = ["pydantic.mypy"]

[tool.importlinter]
root_package = "pcbsmith"

[[tool.importlinter.contracts]]
name = "Core does not import services or CLI"
type = "forbidden"
source_modules = ["pcbsmith.core"]
forbidden_modules = ["pcbsmith.services", "pcbsmith.cli"]

[[tool.importlinter.contracts]]
name = "Services do not import CLI"
type = "forbidden"
source_modules = ["pcbsmith.services"]
forbidden_modules = ["pcbsmith.cli"]
```

- [ ] **Step 3: Add README**

Create `README.md`:

```markdown
# PCBSmith

PCBSmith is an open-source PCB design application foundation. The long-term goal is to let users describe circuits in natural language or code-like text, validate that intent as structured intermediate data, and turn it into schematic and PCB project data.

Phase 0 is deliberately headless. It builds the data model, project I/O, netlist derivation, minimal ERC, and CLI before any GUI or LLM workflow.

## Hard Rules

- Schematic and PCB are separate domains linked by a netlist.
- The data model is structured JSON/Pydantic. SVG, Gerber, PDF, and manufacturing files are export-only.
- Future LLM features must emit validated intermediate representation before project state changes.
- Core code has no UI or service imports.
- Coordinates are stored as signed integer nanometres.
- Unknown parts, pins, and values are surfaced as errors instead of fabricated.

## License

PCBSmith is licensed under AGPL-3.0-or-later.
```

- [ ] **Step 4: Add package markers**

Create `src/pcbsmith/__init__.py`:

```python
"""PCBSmith package."""

__all__ = ["__version__"]

__version__ = "0.1.0"
```

Create `src/pcbsmith/core/__init__.py`:

```python
"""Pure PCBSmith domain models and functions."""
```

Create `src/pcbsmith/services/__init__.py`:

```python
"""PCBSmith application services."""
```

Create `tests/conftest.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
```

- [ ] **Step 5: Add license file**

Create `LICENSE` with this header:

```text
GNU AFFERO GENERAL PUBLIC LICENSE
Version 3, 19 November 2007

PCBSmith is licensed under AGPL-3.0-or-later.

Use the canonical license text from the Free Software Foundation for the full
AGPL-3.0 license body before public distribution:
https://www.gnu.org/licenses/agpl-3.0.txt
```

- [ ] **Step 6: Run initial checks**

Run:

```powershell
python -m pytest
```

Expected: pytest starts and reports no tests collected or passes an empty suite.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml README.md LICENSE src tests
git commit -m "chore: scaffold pcbsmith package"
```

## Task 2: IDs And Geometry

**Files:**
- Create: `src/pcbsmith/core/ids.py`
- Create: `src/pcbsmith/core/geom.py`
- Test: `tests/unit/core/test_ids.py`
- Test: `tests/unit/core/test_geom.py`

- [ ] **Step 1: Write ID tests**

Create `tests/unit/core/test_ids.py`:

```python
from __future__ import annotations

from pcbsmith.core.ids import make_id


def test_make_id_uses_prefix_and_slug() -> None:
    assert make_id("sym", "Resistor 10k") == "sym:resistor-10k"


def test_make_id_strips_repeated_separators() -> None:
    assert make_id("fp", "  SOIC--8 / Wide  ") == "fp:soic-8-wide"
```

- [ ] **Step 2: Write geometry tests**

Create `tests/unit/core/test_geom.py`:

```python
from __future__ import annotations

from hypothesis import given, strategies as st

from pcbsmith.core.geom import Box, Point, Vec, mm_to_nm, nm_to_mm, snap


def test_point_from_mm_round_trips_to_nm() -> None:
    assert Point.from_mm(12.7, 0.0) == Point(12_700_000, 0)


def test_mm_nm_rounding_policy() -> None:
    assert mm_to_nm(0.0000005) == 1
    assert mm_to_nm(0.0000004) == 0
    assert nm_to_mm(1_000_000) == 1.0


@given(
    x=st.integers(-10**12, 10**12),
    y=st.integers(-10**12, 10**12),
    dx=st.integers(-10**12, 10**12),
    dy=st.integers(-10**12, 10**12),
)
def test_point_add_sub_inverse(x: int, y: int, dx: int, dy: int) -> None:
    point = Point(x, y)
    vector = Vec(dx, dy)
    assert (point + vector) - point == vector


@given(x=st.integers(0, 10**9), y=st.integers(0, 10**9))
def test_snap_is_idempotent(x: int, y: int) -> None:
    grid = 1_270_000
    point = Point(x, y)
    once = snap(point, grid)
    twice = snap(once, grid)
    assert once == twice
    assert once.x % grid == 0
    assert once.y % grid == 0


def test_box_contains_closed_edges() -> None:
    box = Box(0, 0, 1000, 1000)
    assert box.contains(Point(0, 0))
    assert box.contains(Point(1000, 1000))
    assert not box.contains(Point(1001, 1000))


def test_box_intersection_counts_touching_edges() -> None:
    left = Box(0, 0, 100, 100)
    right = Box(100, 0, 200, 100)
    far = Box(101, 0, 200, 100)
    assert left.intersects(right)
    assert not left.intersects(far)
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/unit/core/test_ids.py tests/unit/core/test_geom.py -q
```

Expected: FAIL because `pcbsmith.core.ids` and `pcbsmith.core.geom` do not exist.

- [ ] **Step 4: Implement IDs**

Create `src/pcbsmith/core/ids.py`:

```python
from __future__ import annotations

import re
from typing import NewType

ProjectId = NewType("ProjectId", str)
SchematicId = NewType("SchematicId", str)
BoardId = NewType("BoardId", str)
SymbolId = NewType("SymbolId", str)
FootprintId = NewType("FootprintId", str)
NetId = NewType("NetId", str)


def make_id(prefix: str, text: str) -> str:
    slug = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise ValueError("Cannot create an id from empty text")
    return f"{prefix}:{slug}"
```

- [ ] **Step 5: Implement geometry**

Create `src/pcbsmith/core/geom.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

NM_PER_MM = 1_000_000


def mm_to_nm(value: float) -> int:
    return int(value * NM_PER_MM + (0.5 if value >= 0 else -0.5))


def nm_to_mm(value: int) -> float:
    return value / NM_PER_MM


class Vec(BaseModel):
    model_config = ConfigDict(frozen=True)

    dx: int
    dy: int


class Point(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: int
    y: int

    @classmethod
    def from_mm(cls, x: float, y: float) -> Point:
        return cls(x=mm_to_nm(x), y=mm_to_nm(y))

    def __add__(self, vector: Vec) -> Point:
        return Point(x=self.x + vector.dx, y=self.y + vector.dy)

    def __sub__(self, other: Point) -> Vec:
        return Vec(dx=self.x - other.x, dy=self.y - other.y)


class Box(BaseModel):
    model_config = ConfigDict(frozen=True)

    left: int
    top: int
    right: int
    bottom: int

    def contains(self, point: Point) -> bool:
        return self.left <= point.x <= self.right and self.top <= point.y <= self.bottom

    def intersects(self, other: Box) -> bool:
        return not (
            self.right < other.left
            or other.right < self.left
            or self.bottom < other.top
            or other.bottom < self.top
        )


def snap(point: Point, grid_nm: int) -> Point:
    if grid_nm <= 0:
        raise ValueError("grid_nm must be positive")
    return Point(
        x=round(point.x / grid_nm) * grid_nm,
        y=round(point.y / grid_nm) * grid_nm,
    )
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/unit/core/test_ids.py tests/unit/core/test_geom.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/pcbsmith/core/ids.py src/pcbsmith/core/geom.py tests/unit/core/test_ids.py tests/unit/core/test_geom.py
git commit -m "feat: add core ids and geometry"
```

## Task 3: Library Models

**Files:**
- Create: `src/pcbsmith/core/library.py`
- Test: `tests/unit/core/test_library_models.py`

- [ ] **Step 1: Write tests**

Create `tests/unit/core/test_library_models.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.core.geom import Point
from pcbsmith.core.library import (
    Footprint,
    Pad,
    PadShape,
    Pin,
    PinElectricalType,
    Symbol,
)


def test_symbol_pin_lookup_by_number() -> None:
    symbol = Symbol(
        id="stdlib:R",
        name="Resistor",
        pins=[
            Pin(number="1", name="A", position=Point(x=0, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="B", position=Point(x=10, y=0), electrical_type=PinElectricalType.PASSIVE),
        ],
    )
    assert symbol.pin_by_number("2").name == "B"


def test_symbol_rejects_duplicate_pin_numbers() -> None:
    with pytest.raises(ValidationError):
        Symbol(
            id="bad:dup",
            name="Bad",
            pins=[
                Pin(number="1", name="A", position=Point(x=0, y=0), electrical_type=PinElectricalType.PASSIVE),
                Pin(number="1", name="B", position=Point(x=1, y=0), electrical_type=PinElectricalType.PASSIVE),
            ],
        )


def test_footprint_pad_lookup_by_number() -> None:
    footprint = Footprint(
        id="stdlib:R_0603",
        name="R_0603",
        pads=[
            Pad(number="1", position=Point(x=-500_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
            Pad(number="2", position=Point(x=500_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
        ],
    )
    assert footprint.pad_by_number("1").position.x == -500_000
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/unit/core/test_library_models.py -q
```

Expected: FAIL because `pcbsmith.core.library` does not exist.

- [ ] **Step 3: Implement library models**

Create `src/pcbsmith/core/library.py`:

```python
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pcbsmith.core.geom import Point


class PinElectricalType(StrEnum):
    PASSIVE = "passive"
    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    POWER_IN = "power_in"
    POWER_OUT = "power_out"
    NO_CONNECT = "no_connect"


class PadShape(StrEnum):
    RECT = "rect"
    ROUND = "round"
    OVAL = "oval"
    CIRCLE = "circle"


class Pin(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: str
    name: str
    position: Point
    electrical_type: PinElectricalType = PinElectricalType.PASSIVE


class Symbol(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    pins: list[Pin] = Field(default_factory=list)
    default_footprint_id: str | None = None

    @field_validator("pins")
    @classmethod
    def pin_numbers_are_unique(cls, pins: list[Pin]) -> list[Pin]:
        numbers = [pin.number for pin in pins]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Symbol pin numbers must be unique")
        return pins

    def pin_by_number(self, number: str) -> Pin:
        for pin in self.pins:
            if pin.number == number:
                return pin
        raise KeyError(f"Symbol {self.id!r} has no pin {number!r}")


class Pad(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: str
    position: Point
    size_x: int
    size_y: int
    shape: PadShape = PadShape.RECT
    drill: int | None = None


class Footprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    pads: list[Pad] = Field(default_factory=list)

    @field_validator("pads")
    @classmethod
    def pad_numbers_are_unique(cls, pads: list[Pad]) -> list[Pad]:
        numbers = [pad.number for pad in pads]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Footprint pad numbers must be unique")
        return pads

    def pad_by_number(self, number: str) -> Pad:
        for pad in self.pads:
            if pad.number == number:
                return pad
        raise KeyError(f"Footprint {self.id!r} has no pad {number!r}")
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/unit/core/test_library_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/core/library.py tests/unit/core/test_library_models.py
git commit -m "feat: add library models"
```

## Task 4: Schematic, Board, And Project Models

**Files:**
- Create: `src/pcbsmith/core/schematic.py`
- Create: `src/pcbsmith/core/board.py`
- Create: `src/pcbsmith/core/project.py`
- Test: `tests/unit/core/test_schematic_models.py`
- Test: `tests/unit/core/test_board_models.py`
- Test: `tests/unit/core/test_project_models.py`

- [ ] **Step 1: Write schematic tests**

Create `tests/unit/core/test_schematic_models.py`:

```python
from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire


def test_schematic_rejects_duplicate_references() -> None:
    first = SymbolInstance(reference="R1", symbol_id="stdlib:R", value="10k", position=Point(x=0, y=0))
    second = SymbolInstance(reference="R1", symbol_id="stdlib:R", value="1k", position=Point(x=1, y=0))
    try:
        Schematic(id="main", symbols=[first, second])
    except ValueError as exc:
        assert "Duplicate reference" in str(exc)
    else:
        raise AssertionError("duplicate references should fail")


def test_schematic_accepts_wires_and_labels() -> None:
    schematic = Schematic(
        id="main",
        symbols=[SymbolInstance(reference="R1", symbol_id="stdlib:R", value="10k", position=Point(x=0, y=0))],
        wires=[Wire(points=[Point(x=0, y=0), Point(x=100, y=0)])],
        labels=[NetLabel(name="VIN", position=Point(x=0, y=0))],
    )
    assert schematic.labels[0].name == "VIN"
```

- [ ] **Step 2: Write board tests**

Create `tests/unit/core/test_board_models.py`:

```python
from __future__ import annotations

from pcbsmith.core.board import Board, FootprintInstance, Layer, Trace, Via
from pcbsmith.core.geom import Point


def test_board_keeps_footprints_and_traces_separate_from_symbols() -> None:
    board = Board(
        id="main",
        footprints=[
            FootprintInstance(reference="R1", footprint_id="stdlib:R_0603", position=Point(x=0, y=0))
        ],
        traces=[
            Trace(net_name="OUT", layer=Layer.F_CU, points=[Point(x=0, y=0), Point(x=10, y=0)], width=150_000)
        ],
        vias=[Via(net_name="OUT", position=Point(x=5, y=0), drill=300_000, diameter=600_000)],
    )
    assert board.footprints[0].reference == "R1"
    assert board.traces[0].layer == Layer.F_CU
```

- [ ] **Step 3: Write project tests**

Create `tests/unit/core/test_project_models.py`:

```python
from __future__ import annotations

from pcbsmith.core.project import DesignRules, Project


def test_project_defaults_are_phase_0_safe() -> None:
    project = Project(name="Voltage Divider")
    assert project.version == 1
    assert project.design_rules.min_trace_width == 150_000


def test_design_rules_reject_non_positive_clearance() -> None:
    try:
        DesignRules(min_clearance=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("zero clearance should fail")
```

- [ ] **Step 4: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/unit/core/test_schematic_models.py tests/unit/core/test_board_models.py tests/unit/core/test_project_models.py -q
```

Expected: FAIL because the model modules do not exist.

- [ ] **Step 5: Implement schematic models**

Create `src/pcbsmith/core/schematic.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.core.geom import Point


class SymbolInstance(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference: str
    symbol_id: str
    value: str
    position: Point
    rotation_deg: int = 0
    footprint_id: str | None = None


class Wire(BaseModel):
    model_config = ConfigDict(frozen=True)

    points: list[Point] = Field(min_length=2)


class Junction(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: Point


class NetLabel(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    position: Point


class NoConnect(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: Point


class Schematic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    symbols: list[SymbolInstance] = Field(default_factory=list)
    wires: list[Wire] = Field(default_factory=list)
    junctions: list[Junction] = Field(default_factory=list)
    labels: list[NetLabel] = Field(default_factory=list)
    no_connects: list[NoConnect] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_unique(self) -> Schematic:
        references = [symbol.reference for symbol in self.symbols]
        if len(references) != len(set(references)):
            raise ValueError("Duplicate reference designator in schematic")
        return self
```

- [ ] **Step 6: Implement board models**

Create `src/pcbsmith/core/board.py`:

```python
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.geom import Point


class Layer(StrEnum):
    F_CU = "F.Cu"
    B_CU = "B.Cu"
    F_SILK = "F.SilkS"
    B_SILK = "B.SilkS"
    EDGE_CUTS = "Edge.Cuts"


class FootprintInstance(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference: str
    footprint_id: str
    position: Point
    rotation_deg: int = 0


class Trace(BaseModel):
    model_config = ConfigDict(frozen=True)

    net_name: str
    layer: Layer
    points: list[Point] = Field(min_length=2)
    width: int


class Via(BaseModel):
    model_config = ConfigDict(frozen=True)

    net_name: str
    position: Point
    drill: int
    diameter: int


class Zone(BaseModel):
    model_config = ConfigDict(frozen=True)

    net_name: str
    layer: Layer
    outline: list[Point] = Field(min_length=3)


class Board(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    footprints: list[FootprintInstance] = Field(default_factory=list)
    traces: list[Trace] = Field(default_factory=list)
    vias: list[Via] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
```

- [ ] **Step 7: Implement project models**

Create `src/pcbsmith/core/project.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DesignRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_trace_width: int = 150_000
    min_clearance: int = 150_000
    min_drill: int = 300_000

    @field_validator("min_trace_width", "min_clearance", "min_drill")
    @classmethod
    def values_are_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Design rule values must be positive")
        return value


class LibraryRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    path: str | None = None


class Project(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = 1
    name: str
    schematics: list[str] = Field(default_factory=lambda: ["schematics/main.sch.json"])
    boards: list[str] = Field(default_factory=lambda: ["boards/main.brd.json"])
    libraries: list[LibraryRef] = Field(default_factory=lambda: [LibraryRef(id="stdlib")])
    design_rules: DesignRules = Field(default_factory=DesignRules)
```

- [ ] **Step 8: Run tests**

Run:

```powershell
python -m pytest tests/unit/core/test_schematic_models.py tests/unit/core/test_board_models.py tests/unit/core/test_project_models.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add src/pcbsmith/core/schematic.py src/pcbsmith/core/board.py src/pcbsmith/core/project.py tests/unit/core/test_schematic_models.py tests/unit/core/test_board_models.py tests/unit/core/test_project_models.py
git commit -m "feat: add schematic board and project models"
```

## Task 5: Netlist Derivation

**Files:**
- Create: `src/pcbsmith/core/netops.py`
- Test: `tests/unit/core/test_netops.py`

- [ ] **Step 1: Write netlist tests**

Create `tests/unit/core/test_netops.py`:

```python
from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Pin, PinElectricalType, Symbol
from pcbsmith.core.netops import derive_netlist
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire


def test_derive_netlist_connects_pin_tips_through_wire() -> None:
    symbols = {
        "stdlib:R": Symbol(
            id="stdlib:R",
            name="Resistor",
            pins=[
                Pin(number="1", name="A", position=Point(x=0, y=0), electrical_type=PinElectricalType.PASSIVE),
                Pin(number="2", name="B", position=Point(x=10, y=0), electrical_type=PinElectricalType.PASSIVE),
            ],
        )
    }
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(reference="R1", symbol_id="stdlib:R", value="10k", position=Point(x=0, y=0)),
            SymbolInstance(reference="R2", symbol_id="stdlib:R", value="20k", position=Point(x=100, y=0)),
        ],
        wires=[Wire(points=[Point(x=10, y=0), Point(x=100, y=0)])],
        labels=[NetLabel(name="OUT", position=Point(x=50, y=0))],
    )
    netlist = derive_netlist(schematic, symbols)
    assert netlist.net_by_name("OUT").pins == frozenset({("R1", "2"), ("R2", "1")})


def test_derive_netlist_raises_for_unknown_symbol() -> None:
    schematic = Schematic(
        id="main",
        symbols=[SymbolInstance(reference="U1", symbol_id="missing:part", value="IC", position=Point(x=0, y=0))],
    )
    try:
        derive_netlist(schematic, {})
    except KeyError as exc:
        assert "missing:part" in str(exc)
    else:
        raise AssertionError("unknown symbols should fail")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/unit/core/test_netops.py -q
```

Expected: FAIL because `pcbsmith.core.netops` does not exist.

- [ ] **Step 3: Implement netlist derivation**

Create `src/pcbsmith/core/netops.py`:

```python
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Hashable

from pydantic import BaseModel, ConfigDict

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Symbol
from pcbsmith.core.schematic import Schematic

PinRef = tuple[str, str]
Anchor = tuple[int, int]


class Net(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    pins: frozenset[PinRef]


class Netlist(BaseModel):
    model_config = ConfigDict(frozen=True)

    nets: tuple[Net, ...]

    def net_by_name(self, name: str) -> Net:
        for net in self.nets:
            if net.name == name:
                return net
        raise KeyError(name)


@dataclass
class UnionFind:
    parent: dict[Hashable, Hashable]
    rank: dict[Hashable, int]

    def __init__(self) -> None:
        self.parent = {}
        self.rank = {}

    def add(self, item: Hashable) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0

    def find(self, item: Hashable) -> Hashable:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: Hashable, right: Hashable) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            self.parent[left_root] = right_root
        elif self.rank[left_root] > self.rank[right_root]:
            self.parent[right_root] = left_root
        else:
            self.parent[right_root] = left_root
            self.rank[left_root] += 1


def _anchor(point: Point) -> Anchor:
    return (point.x, point.y)


def _pin_tip(instance_position: Point, pin_position: Point) -> Anchor:
    return (instance_position.x + pin_position.x, instance_position.y + pin_position.y)


def _point_on_segment(point: Anchor, start: Anchor, end: Anchor) -> bool:
    px, py = point
    sx, sy = start
    ex, ey = end
    cross = (px - sx) * (ey - sy) - (py - sy) * (ex - sx)
    if cross != 0:
        return False
    return min(sx, ex) <= px <= max(sx, ex) and min(sy, ey) <= py <= max(sy, ey)


def derive_netlist(schematic: Schematic, symbols: dict[str, Symbol]) -> Netlist:
    uf = UnionFind()
    pin_at_anchor: dict[Anchor, list[PinRef]] = defaultdict(list)
    label_at_anchor: dict[Anchor, str] = {}

    for instance in schematic.symbols:
        symbol = symbols[instance.symbol_id]
        for pin in symbol.pins:
            anchor = _pin_tip(instance.position, pin.position)
            uf.add(anchor)
            pin_at_anchor[anchor].append((instance.reference, pin.number))

    for wire in schematic.wires:
        wire_anchors = [_anchor(point) for point in wire.points]
        for anchor in wire_anchors:
            uf.add(anchor)
        for start, end in zip(wire_anchors, wire_anchors[1:]):
            uf.union(start, end)
            for pin_anchor in pin_at_anchor:
                if _point_on_segment(pin_anchor, start, end):
                    uf.union(start, pin_anchor)

    for junction in schematic.junctions:
        anchor = _anchor(junction.position)
        uf.add(anchor)
        for wire in schematic.wires:
            wire_anchors = [_anchor(point) for point in wire.points]
            for start, end in zip(wire_anchors, wire_anchors[1:]):
                if _point_on_segment(anchor, start, end):
                    uf.union(anchor, start)

    for label in schematic.labels:
        anchor = _anchor(label.position)
        uf.add(anchor)
        label_at_anchor[anchor] = label.name
        for wire in schematic.wires:
            wire_anchors = [_anchor(point) for point in wire.points]
            for start, end in zip(wire_anchors, wire_anchors[1:]):
                if _point_on_segment(anchor, start, end):
                    uf.union(anchor, start)

    grouped_pins: dict[Hashable, set[PinRef]] = defaultdict(set)
    grouped_names: dict[Hashable, list[str]] = defaultdict(list)
    for anchor, pins in pin_at_anchor.items():
        grouped_pins[uf.find(anchor)].update(pins)
    for anchor, name in label_at_anchor.items():
        grouped_names[uf.find(anchor)].append(name)

    nets: list[Net] = []
    unnamed_index = 1
    for root, pins in grouped_pins.items():
        if not pins:
            continue
        names = sorted(set(grouped_names.get(root, [])))
        name = names[0] if names else f"N${unnamed_index}"
        if not names:
            unnamed_index += 1
        nets.append(Net(name=name, pins=frozenset(pins)))

    return Netlist(nets=tuple(sorted(nets, key=lambda net: net.name)))
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/unit/core/test_netops.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/core/netops.py tests/unit/core/test_netops.py
git commit -m "feat: derive schematic netlists"
```

## Task 6: Built-In Development Library

**Files:**
- Create: `src/pcbsmith/services/builtin_library.py`
- Test: `tests/unit/services/test_builtin_library.py`

- [ ] **Step 1: Write tests**

Create `tests/unit/services/test_builtin_library.py`:

```python
from __future__ import annotations

from pcbsmith.services.builtin_library import FOOTPRINTS, SYMBOLS, get_symbol


def test_builtin_library_contains_resistor_led_and_power_symbols() -> None:
    assert "stdlib:R" in SYMBOLS
    assert "stdlib:LED" in SYMBOLS
    assert "stdlib:VCC" in SYMBOLS
    assert "stdlib:GND" in SYMBOLS


def test_builtin_resistor_has_matching_default_footprint() -> None:
    symbol = get_symbol("stdlib:R")
    assert symbol.default_footprint_id == "stdlib:R_0603"
    assert symbol.default_footprint_id in FOOTPRINTS
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/unit/services/test_builtin_library.py -q
```

Expected: FAIL because `builtin_library.py` does not exist.

- [ ] **Step 3: Implement library**

Create `src/pcbsmith/services/builtin_library.py` with resistor, capacitor, LED, VCC, GND, and connector entries:

```python
from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Footprint, Pad, PadShape, Pin, PinElectricalType, Symbol

SYMBOLS: dict[str, Symbol] = {
    "stdlib:R": Symbol(
        id="stdlib:R",
        name="Resistor",
        default_footprint_id="stdlib:R_0603",
        pins=[
            Pin(number="1", name="A", position=Point(x=-5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="B", position=Point(x=5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
        ],
    ),
    "stdlib:C": Symbol(
        id="stdlib:C",
        name="Capacitor",
        default_footprint_id="stdlib:C_0603",
        pins=[
            Pin(number="1", name="A", position=Point(x=-5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="B", position=Point(x=5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
        ],
    ),
    "stdlib:LED": Symbol(
        id="stdlib:LED",
        name="LED",
        default_footprint_id="stdlib:LED_0603",
        pins=[
            Pin(number="1", name="K", position=Point(x=-5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="A", position=Point(x=5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
        ],
    ),
    "stdlib:VCC": Symbol(
        id="stdlib:VCC",
        name="Power Flag VCC",
        pins=[
            Pin(number="1", name="VCC", position=Point(x=0, y=0), electrical_type=PinElectricalType.POWER_OUT),
        ],
    ),
    "stdlib:GND": Symbol(
        id="stdlib:GND",
        name="Power Flag GND",
        pins=[
            Pin(number="1", name="GND", position=Point(x=0, y=0), electrical_type=PinElectricalType.POWER_OUT),
        ],
    ),
    "stdlib:CONN_01X02": Symbol(
        id="stdlib:CONN_01X02",
        name="Connector 1x02",
        default_footprint_id="stdlib:PinHeader_1x02_P2.54mm",
        pins=[
            Pin(number="1", name="Pin_1", position=Point(x=0, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="Pin_2", position=Point(x=0, y=2_540_000), electrical_type=PinElectricalType.PASSIVE),
        ],
    ),
}

FOOTPRINTS: dict[str, Footprint] = {
    "stdlib:R_0603": Footprint(
        id="stdlib:R_0603",
        name="R_0603",
        pads=[
            Pad(number="1", position=Point(x=-800_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
            Pad(number="2", position=Point(x=800_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
        ],
    ),
    "stdlib:C_0603": Footprint(
        id="stdlib:C_0603",
        name="C_0603",
        pads=[
            Pad(number="1", position=Point(x=-800_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
            Pad(number="2", position=Point(x=800_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
        ],
    ),
    "stdlib:LED_0603": Footprint(
        id="stdlib:LED_0603",
        name="LED_0603",
        pads=[
            Pad(number="1", position=Point(x=-800_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
            Pad(number="2", position=Point(x=800_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
        ],
    ),
    "stdlib:PinHeader_1x02_P2.54mm": Footprint(
        id="stdlib:PinHeader_1x02_P2.54mm",
        name="PinHeader_1x02_P2.54mm",
        pads=[
            Pad(number="1", position=Point(x=0, y=0), size_x=1_700_000, size_y=1_700_000, shape=PadShape.CIRCLE, drill=1_000_000),
            Pad(number="2", position=Point(x=0, y=2_540_000), size_x=1_700_000, size_y=1_700_000, shape=PadShape.CIRCLE, drill=1_000_000),
        ],
    ),
}


def get_symbol(symbol_id: str) -> Symbol:
    return SYMBOLS[symbol_id]


def get_footprint(footprint_id: str) -> Footprint:
    return FOOTPRINTS[footprint_id]
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/unit/services/test_builtin_library.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/services/builtin_library.py tests/unit/services/test_builtin_library.py
git commit -m "feat: add built-in development library"
```

## Task 7: Project I/O And Fixtures

**Files:**
- Create: `src/pcbsmith/services/project_io.py`
- Create: `tests/fixtures/voltage_divider/project.pcbsmith.json`
- Create: `tests/fixtures/voltage_divider/schematics/main.sch.json`
- Create: `tests/fixtures/voltage_divider/boards/main.brd.json`
- Test: `tests/unit/services/test_project_io.py`

- [ ] **Step 1: Write project I/O tests**

Create `tests/unit/services/test_project_io.py`:

```python
from __future__ import annotations

from pathlib import Path

from pcbsmith.core.project import Project
from pcbsmith.services.project_io import create_project, load_project, save_project


def test_create_project_writes_expected_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    create_project(project_dir, "Demo")
    assert (project_dir / "project.pcbsmith.json").exists()
    assert (project_dir / "schematics" / "main.sch.json").exists()
    assert (project_dir / "boards" / "main.brd.json").exists()


def test_project_round_trip(tmp_path: Path) -> None:
    project_dir = tmp_path / "roundtrip"
    project = Project(name="Round Trip")
    save_project(project_dir, project)
    loaded = load_project(project_dir)
    assert loaded == project
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/unit/services/test_project_io.py -q
```

Expected: FAIL because `project_io.py` does not exist.

- [ ] **Step 3: Implement project I/O**

Create `src/pcbsmith/services/project_io.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic

PROJECT_FILE = "project.pcbsmith.json"


class ProjectIOError(RuntimeError):
    pass


def _write_json(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data + "\n", encoding="utf-8")


def save_project(project_dir: Path, project: Project) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    _write_json(project_dir / PROJECT_FILE, project.model_dump_json(indent=2))


def load_project(project_dir: Path) -> Project:
    path = project_dir / PROJECT_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Project.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Project file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid project file: {path}") from exc


def save_schematic(project_dir: Path, relative_path: str, schematic: Schematic) -> None:
    _write_json(project_dir / relative_path, schematic.model_dump_json(indent=2))


def load_schematic(project_dir: Path, relative_path: str) -> Schematic:
    path = project_dir / relative_path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Schematic.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Schematic file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid schematic file: {path}") from exc


def save_board(project_dir: Path, relative_path: str, board: Board) -> None:
    _write_json(project_dir / relative_path, board.model_dump_json(indent=2))


def load_board(project_dir: Path, relative_path: str) -> Board:
    path = project_dir / relative_path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Board.model_validate(raw)
    except FileNotFoundError as exc:
        raise ProjectIOError(f"Board file not found: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProjectIOError(f"Invalid board file: {path}") from exc


def create_project(project_dir: Path, name: str) -> Project:
    project = Project(name=name)
    save_project(project_dir, project)
    save_schematic(project_dir, project.schematics[0], Schematic(id="main"))
    save_board(project_dir, project.boards[0], Board(id="main"))
    return project
```

- [ ] **Step 4: Add voltage divider fixture**

Create `tests/fixtures/voltage_divider/project.pcbsmith.json`:

```json
{
  "version": 1,
  "name": "Voltage Divider",
  "schematics": ["schematics/main.sch.json"],
  "boards": ["boards/main.brd.json"],
  "libraries": [{"id": "stdlib", "path": null}],
  "design_rules": {
    "min_trace_width": 150000,
    "min_clearance": 150000,
    "min_drill": 300000
  }
}
```

Create `tests/fixtures/voltage_divider/schematics/main.sch.json`:

```json
{
  "id": "main",
  "symbols": [
    {"reference": "V1", "symbol_id": "stdlib:VCC", "value": "VCC", "position": {"x": 0, "y": 0}, "rotation_deg": 0, "footprint_id": null},
    {"reference": "R1", "symbol_id": "stdlib:R", "value": "10k", "position": {"x": 5080000, "y": 0}, "rotation_deg": 0, "footprint_id": "stdlib:R_0603"},
    {"reference": "R2", "symbol_id": "stdlib:R", "value": "10k", "position": {"x": 20320000, "y": 0}, "rotation_deg": 0, "footprint_id": "stdlib:R_0603"},
    {"reference": "G1", "symbol_id": "stdlib:GND", "value": "GND", "position": {"x": 30480000, "y": 0}, "rotation_deg": 0, "footprint_id": null}
  ],
  "wires": [
    {"points": [{"x": 0, "y": 0}, {"x": 0, "y": 0}]},
    {"points": [{"x": 10160000, "y": 0}, {"x": 15240000, "y": 0}]},
    {"points": [{"x": 25400000, "y": 0}, {"x": 30480000, "y": 0}]}
  ],
  "junctions": [],
  "labels": [
    {"name": "VCC", "position": {"x": 0, "y": 0}},
    {"name": "OUT", "position": {"x": 15240000, "y": 0}},
    {"name": "GND", "position": {"x": 30480000, "y": 0}}
  ],
  "no_connects": []
}
```

Create `tests/fixtures/voltage_divider/boards/main.brd.json`:

```json
{
  "id": "main",
  "footprints": [],
  "traces": [],
  "vias": [],
  "zones": []
}
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/unit/services/test_project_io.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/services/project_io.py tests/unit/services/test_project_io.py tests/fixtures/voltage_divider
git commit -m "feat: add project io and fixtures"
```

## Task 8: Minimal ERC

**Files:**
- Create: `src/pcbsmith/services/erc.py`
- Test: `tests/unit/services/test_erc.py`

- [ ] **Step 1: Write ERC tests**

Create `tests/unit/services/test_erc.py`:

```python
from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Pin, PinElectricalType, Symbol
from pcbsmith.core.schematic import Schematic, SymbolInstance, Wire
from pcbsmith.services.erc import run_erc


def test_erc_reports_unconnected_pin() -> None:
    symbols = {
        "stdlib:R": Symbol(
            id="stdlib:R",
            name="Resistor",
            pins=[
                Pin(number="1", name="A", position=Point(x=0, y=0), electrical_type=PinElectricalType.PASSIVE),
                Pin(number="2", name="B", position=Point(x=10, y=0), electrical_type=PinElectricalType.PASSIVE),
            ],
        )
    }
    schematic = Schematic(
        id="main",
        symbols=[SymbolInstance(reference="R1", symbol_id="stdlib:R", value="10k", position=Point(x=0, y=0))],
        wires=[Wire(points=[Point(x=0, y=0), Point(x=20, y=0)])],
    )
    issues = run_erc(schematic, symbols)
    assert any(issue.code == "ERC001" and issue.where == "R1.2" for issue in issues)


def test_erc_reports_power_output_conflict() -> None:
    symbols = {
        "stdlib:PWR": Symbol(
            id="stdlib:PWR",
            name="Power",
            pins=[Pin(number="1", name="PWR", position=Point(x=0, y=0), electrical_type=PinElectricalType.POWER_OUT)],
        )
    }
    schematic = Schematic(
        id="main",
        symbols=[
            SymbolInstance(reference="P1", symbol_id="stdlib:PWR", value="PWR", position=Point(x=0, y=0)),
            SymbolInstance(reference="P2", symbol_id="stdlib:PWR", value="PWR", position=Point(x=100, y=0)),
        ],
        wires=[Wire(points=[Point(x=0, y=0), Point(x=100, y=0)])],
    )
    issues = run_erc(schematic, symbols)
    assert any(issue.code == "ERC002" for issue in issues)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/unit/services/test_erc.py -q
```

Expected: FAIL because `erc.py` does not exist.

- [ ] **Step 3: Implement ERC**

Create `src/pcbsmith/services/erc.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from pcbsmith.core.library import PinElectricalType, Symbol
from pcbsmith.core.netops import derive_netlist
from pcbsmith.core.schematic import Schematic


@dataclass(frozen=True)
class ERCIssue:
    code: str
    message: str
    where: str


def run_erc(schematic: Schematic, symbols: dict[str, Symbol]) -> list[ERCIssue]:
    netlist = derive_netlist(schematic, symbols)
    connected = {pin_ref for net in netlist.nets for pin_ref in net.pins}
    issues: list[ERCIssue] = []

    for instance in schematic.symbols:
        symbol = symbols[instance.symbol_id]
        for pin in symbol.pins:
            pin_ref = (instance.reference, pin.number)
            if pin.electrical_type != PinElectricalType.NO_CONNECT and pin_ref not in connected:
                issues.append(
                    ERCIssue(
                        code="ERC001",
                        message=f"Unconnected pin {instance.reference}.{pin.number}",
                        where=f"{instance.reference}.{pin.number}",
                    )
                )

    for net in netlist.nets:
        power_outputs = []
        for reference, pin_number in net.pins:
            instance = next(symbol for symbol in schematic.symbols if symbol.reference == reference)
            pin = symbols[instance.symbol_id].pin_by_number(pin_number)
            if pin.electrical_type == PinElectricalType.POWER_OUT:
                power_outputs.append(f"{reference}.{pin_number}")
        if len(power_outputs) > 1:
            issues.append(
                ERCIssue(
                    code="ERC002",
                    message=f"Power output conflict on net {net.name}: {', '.join(power_outputs)}",
                    where=net.name,
                )
            )

    return issues
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/unit/services/test_erc.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/pcbsmith/services/erc.py tests/unit/services/test_erc.py
git commit -m "feat: add minimal erc"
```

## Task 9: CLI And Acceptance Fixture

**Files:**
- Create: `src/pcbsmith/cli.py`
- Test: `tests/integration/test_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Write CLI integration tests**

Create `tests/integration/test_cli.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.conftest import FIXTURES


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pcbsmith.cli", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_cli_info_on_fixture() -> None:
    result = run_cli("info", str(FIXTURES / "voltage_divider"))
    assert result.returncode == 0
    assert "Voltage Divider" in result.stdout


def test_cli_netlist_on_fixture() -> None:
    result = run_cli("netlist", str(FIXTURES / "voltage_divider"))
    assert result.returncode == 0
    assert "OUT" in result.stdout


def test_cli_new_creates_project(tmp_path: Path) -> None:
    result = run_cli("new", str(tmp_path / "demo"), "--name", "Demo Board")
    assert result.returncode == 0
    assert (tmp_path / "demo" / "project.pcbsmith.json").exists()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/integration/test_cli.py -q
```

Expected: FAIL because `pcbsmith.cli` does not exist.

- [ ] **Step 3: Implement CLI**

Create `src/pcbsmith/cli.py`:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pcbsmith.core.netops import derive_netlist
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.services.erc import run_erc
from pcbsmith.services.project_io import (
    ProjectIOError,
    create_project,
    load_project,
    load_schematic,
)


def _cmd_new(args: argparse.Namespace) -> int:
    create_project(Path(args.project), args.name)
    print(f"Created PCBSmith project: {args.project}")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    project_dir = Path(args.project)
    project = load_project(project_dir)
    print(f"Name: {project.name}")
    print(f"Version: {project.version}")
    print(f"Schematics: {len(project.schematics)}")
    print(f"Boards: {len(project.boards)}")
    return 0


def _cmd_netlist(args: argparse.Namespace) -> int:
    project_dir = Path(args.project)
    project = load_project(project_dir)
    schematic = load_schematic(project_dir, project.schematics[0])
    netlist = derive_netlist(schematic, SYMBOLS)
    for net in netlist.nets:
        pins = ", ".join(f"{ref}.{pin}" for ref, pin in sorted(net.pins))
        print(f"{net.name}: {pins}")
    return 0


def _cmd_erc(args: argparse.Namespace) -> int:
    project_dir = Path(args.project)
    project = load_project(project_dir)
    schematic = load_schematic(project_dir, project.schematics[0])
    issues = run_erc(schematic, SYMBOLS)
    for issue in issues:
        print(f"{issue.code} {issue.where}: {issue.message}")
    return 1 if issues else 0


def _cmd_validate(args: argparse.Namespace) -> int:
    project_dir = Path(args.project)
    project = load_project(project_dir)
    for schematic_path in project.schematics:
        load_schematic(project_dir, schematic_path)
    print("Project is valid")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcbsmith")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("project")
    new_parser.add_argument("--name", required=True)
    new_parser.set_defaults(func=_cmd_new)

    for name, func in {
        "info": _cmd_info,
        "netlist": _cmd_netlist,
        "erc": _cmd_erc,
        "validate": _cmd_validate,
    }.items():
        subparser = subparsers.add_parser(name)
        subparser.add_argument("project")
        subparser.set_defaults(func=func)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (KeyError, ProjectIOError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Update README CLI section**

Append to `README.md`:

~~~markdown
## Phase 0 CLI

```powershell
python -m pcbsmith.cli new demo --name "Demo Board"
python -m pcbsmith.cli info demo
python -m pcbsmith.cli validate demo
python -m pcbsmith.cli netlist demo
python -m pcbsmith.cli erc demo
```
~~~

- [ ] **Step 5: Run CLI tests**

Run:

```powershell
python -m pytest tests/integration/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/pcbsmith/cli.py tests/integration/test_cli.py README.md
git commit -m "feat: add phase 0 cli"
```

## Task 10: Verification, Reference PDF, And Final Polish

**Files:**
- Add: `docs/reference/PCB_Application_Specification.pdf`

- [ ] **Step 1: Confirm the PDF is local**

Run:

```powershell
Get-Item docs/reference/PCB_Application_Specification.pdf
```

Expected: the file exists and has non-zero length.

- [ ] **Step 2: Run all tests**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run import-linter**

Run:

```powershell
python -m lint_imports
```

Expected: PASS with contracts satisfied.

- [ ] **Step 4: Run Ruff**

Run:

```powershell
python -m ruff check src tests
```

Expected: PASS.

- [ ] **Step 5: Run mypy**

Run:

```powershell
python -m mypy src
```

Expected: PASS.

- [ ] **Step 6: Run an end-to-end CLI smoke test**

Run:

```powershell
python -m pcbsmith.cli info tests/fixtures/voltage_divider
python -m pcbsmith.cli netlist tests/fixtures/voltage_divider
python -m pcbsmith.cli validate tests/fixtures/voltage_divider
```

Expected: `info` prints `Voltage Divider`, `netlist` prints `VCC`, `OUT`, and `GND`, and `validate` prints `Project is valid`.

- [ ] **Step 7: Commit**

```powershell
git add .
git commit -m "test: verify phase 0 foundation"
```

## Self-Review

Spec coverage:

- Package skeleton: Task 1.
- Layered architecture and import-linter: Tasks 1 and 10.
- Integer nanometre geometry: Task 2.
- Library, schematic, board, and project models: Tasks 3 and 4.
- Netlist derivation: Task 5.
- Built-in development library: Task 6.
- Project folder I/O: Task 7.
- Minimal ERC: Task 8.
- CLI commands: Task 9.
- Fixtures and acceptance testing: Tasks 7, 9, and 10.
- README license and LLM IR rule: Task 1 and Task 9.

No spec requirements are intentionally deferred from Phase 0.

Type consistency:

- `Point`, `Vec`, and `Box` are Pydantic models with integer fields.
- `Symbol`, `Footprint`, `Schematic`, `Board`, and `Project` use Pydantic models consistently.
- `derive_netlist()` accepts `Schematic` and `dict[str, Symbol]`, and returns `Netlist`.
- `run_erc()` accepts the same schematic and symbol map, and returns `list[ERCIssue]`.
- CLI commands load project JSON through `project_io` and never import test fixtures directly.
