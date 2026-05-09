# PCBSmith Phase 2 Component Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PCBSmith-native component catalog with searchable tagged Basic Components, preferred-part profiles, catalog-based placement, and safe missing-part/developer proposal paths.

**Architecture:** Keep the existing `ui -> services -> core` boundary. Add UI-free catalog and preference models in `core`, catalog/search/validation services in `services`, and a focused Qt component browser in `ui` that calls the service rather than raw symbol dictionaries. Schematic files continue storing existing symbol/footprint fields; Phase 2 resolves catalog entries into those fields during placement.

**Tech Stack:** Python 3.12+, Pydantic, PySide6, pytest, ruff, existing PCBSmith core/service/UI modules.

---

## File Structure

- Create `src/pcbsmith/core/catalog.py`: Pydantic catalog models, tag normalization, profile/preference models, missing-part and developer-proposal models.
- Modify `src/pcbsmith/core/project.py`: add optional catalog preferences while keeping old project JSON valid.
- Create `tests/unit/core/test_catalog_models.py`: validation tests for catalog data, tags, profiles, requests, and proposals.
- Modify `tests/unit/core/test_project_models.py`: backward compatibility and preference persistence tests.
- Create `src/pcbsmith/services/component_catalog.py`: built-in catalog access, validation, search, preferred-profile resolution, missing-part request creation.
- Modify `src/pcbsmith/services/builtin_library.py`: add symbols/footprints required for Basic Components and keep `SYMBOLS`/`FOOTPRINTS` available.
- Create `tests/unit/services/test_component_catalog.py`: search, validation, preference, placement lookup, and missing-part service tests.
- Modify `src/pcbsmith/ui/editor_state.py`: add symbol-prefix support for new built-in symbols.
- Modify `src/pcbsmith/ui/schematic_scene.py`: add generic catalog placement and component tool support.
- Create `src/pcbsmith/ui/component_browser.py`: search box, preferred-only toggle, component list, and selection signal.
- Modify `src/pcbsmith/ui/main_window.py`: replace flat library dock with browser, wire More Components and toolbar shortcuts to catalog placement.
- Modify `tests/unit/ui/test_editor_state.py`: references for new component families.
- Modify `tests/integration/test_gui_phase1b.py` or create `tests/integration/test_gui_phase2.py`: GUI catalog browser and placement tests.
- Modify `README.md`: document Phase 2 library basics after implementation.

## Task 1: Core Catalog Models

**Files:**
- Create: `src/pcbsmith/core/catalog.py`
- Modify: `src/pcbsmith/core/project.py`
- Test: `tests/unit/core/test_catalog_models.py`
- Test: `tests/unit/core/test_project_models.py`

- [ ] **Step 1: Write failing catalog model tests**

Add `tests/unit/core/test_catalog_models.py`:

```python
import pytest
from pydantic import ValidationError

from pcbsmith.core.catalog import (
    CatalogEntry,
    CatalogGroup,
    CatalogSearchQuery,
    ComponentFamily,
    ComponentVariant,
    DeveloperLibraryProposal,
    MissingPartRequest,
    PreferredPartsProfile,
    SourceInfo,
    normalize_tag,
)


def test_normalize_tag_accepts_common_user_terms() -> None:
    assert normalize_tag("Through Hole") == "through-hole"
    assert normalize_tag("  P2.54MM  ") == "p2.54mm"
    assert normalize_tag("SMD") == "smd"


def test_catalog_entry_normalizes_tags_and_aliases() -> None:
    entry = CatalogEntry(
        id="pcbs:resistor_0603",
        family=ComponentFamily(id="resistor", name="Resistor"),
        variant=ComponentVariant(name="Resistor 0603", package="0603"),
        symbol_id="stdlib:R",
        footprint_id="stdlib:R_0603",
        tags=("Passive", "SMD", "0603", "basic"),
        aliases=("chip resistor", "R 0603"),
        group_ids=("basic-components",),
    )

    assert entry.tags == ("passive", "smd", "0603", "basic")
    assert entry.aliases == ("chip-resistor", "r-0603")
    assert entry.search_text == "resistor resistor 0603 0603 passive smd 0603 basic chip-resistor r-0603"


def test_catalog_entry_rejects_non_namespaced_ids() -> None:
    with pytest.raises(ValidationError, match="Catalog ids must be namespaced"):
        CatalogEntry(
            id="resistor_0603",
            family=ComponentFamily(id="resistor", name="Resistor"),
            variant=ComponentVariant(name="Resistor 0603", package="0603"),
            symbol_id="stdlib:R",
        )


def test_preferred_profile_defaults_are_deduplicated() -> None:
    profile = PreferredPartsProfile(
        enabled_group_ids=("basic-components", "basic-components"),
        hidden_entry_ids=("pcbs:led_0603", "pcbs:led_0603"),
    )

    assert profile.enabled_group_ids == ("basic-components",)
    assert profile.hidden_entry_ids == ("pcbs:led_0603",)


def test_search_query_normalizes_text_and_tags() -> None:
    query = CatalogSearchQuery(text=" Through Hole LED ", tags=("Basic", "P2.54MM"))

    assert query.text == "through-hole-led"
    assert query.tags == ("basic", "p2.54mm")


def test_missing_part_request_records_user_need() -> None:
    request = MissingPartRequest(
        requested_name="555 timer DIP-8",
        reason="User asked for a timer IC that is not in the catalog",
        requested_tags=("IC", "DIP-8"),
    )

    assert request.requested_name == "555 timer DIP-8"
    assert request.requested_tags == ("ic", "dip-8")


def test_developer_proposal_is_not_a_catalog_entry() -> None:
    proposal = DeveloperLibraryProposal(
        requested_name="NE555 DIP-8",
        proposed_entry_id="pcbs:ne555_dip8",
        source=SourceInfo(name="developer", source_id="manual"),
        notes="Add after chip-specific pin mapping exists.",
    )

    assert proposal.proposed_entry_id == "pcbs:ne555_dip8"
    assert proposal.status == "draft"
```

- [ ] **Step 2: Write failing project preference tests**

Append to `tests/unit/core/test_project_models.py`:

```python
from pcbsmith.core.catalog import CatalogPreferences
from pcbsmith.core.project import Project


def test_project_defaults_to_empty_catalog_preferences() -> None:
    project = Project(name="Existing")

    assert project.catalog_preferences == CatalogPreferences()


def test_project_loads_without_catalog_preferences_for_backward_compatibility() -> None:
    project = Project.model_validate(
        {
            "version": 1,
            "name": "Old Project",
            "schematics": ["schematics/main.sch.json"],
            "boards": ["boards/main.brd.json"],
            "libraries": [{"id": "stdlib"}],
            "design_rules": {
                "min_trace_width": 150000,
                "min_clearance": 150000,
                "min_drill": 300000,
            },
        }
    )

    assert project.catalog_preferences.enabled_group_ids == ()


def test_project_persists_catalog_preferences() -> None:
    project = Project(
        name="Preferred",
        catalog_preferences=CatalogPreferences(
            enabled_group_ids=("basic-components",),
            hidden_entry_ids=("pcbs:led_0603",),
        ),
    )

    restored = Project.model_validate_json(project.model_dump_json())

    assert restored.catalog_preferences.enabled_group_ids == ("basic-components",)
    assert restored.catalog_preferences.hidden_entry_ids == ("pcbs:led_0603",)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/core/test_catalog_models.py tests/unit/core/test_project_models.py -q --basetemp=.tmp/pytest-phase2-task1-red
```

Expected: FAIL because `pcbsmith.core.catalog` and `Project.catalog_preferences` do not exist yet.

- [ ] **Step 4: Implement core catalog models**

Create `src/pcbsmith/core/catalog.py`:

```python
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TAG_SEPARATOR = re.compile(r"[\s_]+")


def normalize_tag(value: str) -> str:
    tag = _TAG_SEPARATOR.sub("-", value.strip().lower())
    tag = re.sub(r"-+", "-", tag)
    if not tag:
        raise ValueError("Tags cannot be empty")
    return tag


def _dedupe_normalized(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        tag = normalize_tag(value)
        if tag not in seen:
            seen.add(tag)
            normalized.append(tag)
    return tuple(normalized)


class SourceInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "pcbs"
    source_id: str | None = None
    license: str | None = None
    url: str | None = None


class ComponentFamily(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str = ""


class ComponentVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    package: str | None = None
    mounting: Literal["smd", "through-hole", "virtual"] | None = None
    default_value: str | None = None


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    family: ComponentFamily
    variant: ComponentVariant
    symbol_id: str
    footprint_id: str | None = None
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    source: SourceInfo = Field(default_factory=SourceInfo)
    normal_user_visible: bool = True

    @field_validator("id")
    @classmethod
    def id_is_namespaced(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("Catalog ids must be namespaced")
        return value

    @field_validator("tags", "aliases", "group_ids")
    @classmethod
    def normalize_tokens(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_normalized(tuple(values))

    @property
    def search_text(self) -> str:
        values = [
            self.family.name,
            self.variant.name,
            self.variant.package or "",
            *self.tags,
            *self.aliases,
        ]
        return " ".join(value for value in values if value)


class CatalogGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str = ""
    default_enabled: bool = False

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_tag(value)


class PreferredPartsProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled_group_ids: tuple[str, ...] = ()
    visible_entry_ids: tuple[str, ...] = ()
    hidden_entry_ids: tuple[str, ...] = ()

    @field_validator("enabled_group_ids", "visible_entry_ids", "hidden_entry_ids")
    @classmethod
    def normalize_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_normalized(tuple(values))


class CatalogPreferences(PreferredPartsProfile):
    pass


class CatalogSearchQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = ""
    tags: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    preferred_only: bool = False

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return normalize_tag(value) if value.strip() else ""

    @field_validator("tags", "group_ids")
    @classmethod
    def normalize_filters(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_normalized(tuple(values))


class MissingPartRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_name: str
    reason: str
    requested_tags: tuple[str, ...] = ()
    user_visible: bool = True

    @field_validator("requested_tags")
    @classmethod
    def normalize_requested_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_normalized(tuple(values))


class DeveloperLibraryProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_name: str
    proposed_entry_id: str
    source: SourceInfo = Field(default_factory=SourceInfo)
    notes: str = ""
    status: Literal["draft", "reviewed", "accepted", "rejected"] = "draft"

    @model_validator(mode="after")
    def proposed_id_is_namespaced(self) -> DeveloperLibraryProposal:
        if ":" not in self.proposed_entry_id:
            raise ValueError("Developer proposals must use namespaced catalog ids")
        return self
```

Modify `src/pcbsmith/core/project.py` to import and add preferences:

```python
from pcbsmith.core.catalog import CatalogPreferences
```

Then add to `Project`:

```python
    catalog_preferences: CatalogPreferences = Field(default_factory=CatalogPreferences)
```

- [ ] **Step 5: Run Task 1 tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/core/test_catalog_models.py tests/unit/core/test_project_models.py -q --basetemp=.tmp/pytest-phase2-task1-green
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add src/pcbsmith/core/catalog.py src/pcbsmith/core/project.py tests/unit/core/test_catalog_models.py tests/unit/core/test_project_models.py
git commit -m "feat: add component catalog models"
```

## Task 2: Catalog Service, Built-In Entries, And Validation

**Files:**
- Create: `src/pcbsmith/services/component_catalog.py`
- Modify: `src/pcbsmith/services/builtin_library.py`
- Test: `tests/unit/services/test_component_catalog.py`
- Test: `tests/unit/services/test_builtin_library.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/unit/services/test_component_catalog.py`:

```python
import pytest

from pcbsmith.core.catalog import CatalogPreferences, CatalogSearchQuery
from pcbsmith.services import component_catalog


def test_builtin_catalog_contains_basic_components() -> None:
    catalog = component_catalog.builtin_catalog()

    ids = {entry.id for entry in catalog.entries}

    assert "pcbs:resistor_0603" in ids
    assert "pcbs:capacitor_0603" in ids
    assert "pcbs:led_0603" in ids
    assert "pcbs:diode_0603" in ids
    assert "pcbs:push_button_th" in ids
    assert "pcbs:switch_spst_th" in ids
    assert "pcbs:pin_header_1x02_p2.54mm" in ids


def test_validate_builtin_catalog_passes() -> None:
    component_catalog.validate_catalog(component_catalog.builtin_catalog())


def test_search_matches_name_package_tags_and_aliases() -> None:
    catalog = component_catalog.builtin_catalog()

    assert component_catalog.search_catalog(catalog, CatalogSearchQuery(text="0603"))
    assert [entry.id for entry in component_catalog.search_catalog(catalog, CatalogSearchQuery(text="led"))] == ["pcbs:led_0603"]
    assert [entry.id for entry in component_catalog.search_catalog(catalog, CatalogSearchQuery(text="button"))] == ["pcbs:push_button_th"]
    assert component_catalog.search_catalog(catalog, CatalogSearchQuery(tags=("smd",)))
    assert component_catalog.search_catalog(catalog, CatalogSearchQuery(text="through hole"))


def test_preferred_only_uses_default_and_project_preferences() -> None:
    catalog = component_catalog.builtin_catalog()
    profile = CatalogPreferences(
        enabled_group_ids=("basic-components",),
        hidden_entry_ids=("pcbs:led_0603",),
    )

    results = component_catalog.search_catalog(
        catalog,
        CatalogSearchQuery(preferred_only=True),
        project_preferences=profile,
    )

    ids = {entry.id for entry in results}
    assert "pcbs:resistor_0603" in ids
    assert "pcbs:led_0603" not in ids


def test_entry_by_id_rejects_unknown_ids() -> None:
    catalog = component_catalog.builtin_catalog()

    with pytest.raises(KeyError, match="Unknown catalog entry"):
        component_catalog.entry_by_id(catalog, "pcbs:missing")


def test_create_missing_part_request() -> None:
    request = component_catalog.create_missing_part_request(
        "NE555 DIP-8",
        reason="Timer IC is not in the catalog",
        tags=("ic", "dip-8"),
    )

    assert request.requested_name == "NE555 DIP-8"
    assert request.requested_tags == ("ic", "dip-8")
```

- [ ] **Step 2: Run service tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/services/test_component_catalog.py -q --basetemp=.tmp/pytest-phase2-task2-red
```

Expected: FAIL because `component_catalog` does not exist yet.

- [ ] **Step 3: Add missing Basic Components symbols and footprints**

Modify `src/pcbsmith/services/builtin_library.py` by adding these `SYMBOLS` entries:

```python
    "stdlib:D": Symbol(
        id="stdlib:D",
        name="Diode",
        default_footprint_id="stdlib:D_0603",
        pins=(
            Pin(number="1", name="K", position=Point(x=-5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="A", position=Point(x=5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
        ),
    ),
    "stdlib:SW_PUSH": Symbol(
        id="stdlib:SW_PUSH",
        name="Push Button",
        default_footprint_id="stdlib:SW_PUSH_TH",
        pins=(
            Pin(number="1", name="A", position=Point(x=-5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="B", position=Point(x=5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
        ),
    ),
    "stdlib:SW_SPST": Symbol(
        id="stdlib:SW_SPST",
        name="Switch SPST",
        default_footprint_id="stdlib:SW_SPST_TH",
        pins=(
            Pin(number="1", name="A", position=Point(x=-5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
            Pin(number="2", name="B", position=Point(x=5_080_000, y=0), electrical_type=PinElectricalType.PASSIVE),
        ),
    ),
```

Add these `FOOTPRINTS` entries:

```python
    "stdlib:D_0603": Footprint(
        id="stdlib:D_0603",
        name="D_0603",
        pads=(
            Pad(number="1", position=Point(x=-800_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
            Pad(number="2", position=Point(x=800_000, y=0), size_x=800_000, size_y=900_000, shape=PadShape.RECT),
        ),
    ),
    "stdlib:SW_PUSH_TH": Footprint(
        id="stdlib:SW_PUSH_TH",
        name="SW_PUSH_TH",
        pads=(
            Pad(number="1", position=Point(x=-2_540_000, y=0), size_x=1_700_000, size_y=1_700_000, shape=PadShape.CIRCLE, drill=1_000_000),
            Pad(number="2", position=Point(x=2_540_000, y=0), size_x=1_700_000, size_y=1_700_000, shape=PadShape.CIRCLE, drill=1_000_000),
        ),
    ),
    "stdlib:SW_SPST_TH": Footprint(
        id="stdlib:SW_SPST_TH",
        name="SW_SPST_TH",
        pads=(
            Pad(number="1", position=Point(x=-2_540_000, y=0), size_x=1_700_000, size_y=1_700_000, shape=PadShape.CIRCLE, drill=1_000_000),
            Pad(number="2", position=Point(x=2_540_000, y=0), size_x=1_700_000, size_y=1_700_000, shape=PadShape.CIRCLE, drill=1_000_000),
        ),
    ),
```

- [ ] **Step 4: Implement component catalog service**

Create `src/pcbsmith/services/component_catalog.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from pcbsmith.core.catalog import (
    CatalogEntry,
    CatalogGroup,
    CatalogPreferences,
    CatalogSearchQuery,
    ComponentFamily,
    ComponentVariant,
    MissingPartRequest,
)
from pcbsmith.services.builtin_library import FOOTPRINTS, SYMBOLS


@dataclass(frozen=True)
class ComponentCatalog:
    groups: tuple[CatalogGroup, ...]
    entries: tuple[CatalogEntry, ...]


def _family(id: str, name: str) -> ComponentFamily:
    return ComponentFamily(id=id, name=name)


def builtin_catalog() -> ComponentCatalog:
    basic = CatalogGroup(
        id="basic-components",
        name="Basic Components",
        description="Starter PCB components for common schematic work.",
        default_enabled=True,
    )
    entries = (
        CatalogEntry(
            id="pcbs:resistor_0603",
            family=_family("resistor", "Resistor"),
            variant=ComponentVariant(name="Resistor 0603", package="0603", mounting="smd", default_value="10k"),
            symbol_id="stdlib:R",
            footprint_id="stdlib:R_0603",
            tags=("resistor", "passive", "smd", "0603", "basic", "beginner", "common"),
            aliases=("r", "chip resistor"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:capacitor_0603",
            family=_family("capacitor", "Capacitor"),
            variant=ComponentVariant(name="Capacitor 0603", package="0603", mounting="smd", default_value="100nF"),
            symbol_id="stdlib:C",
            footprint_id="stdlib:C_0603",
            tags=("capacitor", "passive", "smd", "0603", "decoupling", "basic", "beginner", "common"),
            aliases=("c", "bypass capacitor"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:led_0603",
            family=_family("led", "LED"),
            variant=ComponentVariant(name="LED 0603", package="0603", mounting="smd", default_value="LED"),
            symbol_id="stdlib:LED",
            footprint_id="stdlib:LED_0603",
            tags=("led", "diode", "indicator", "smd", "0603", "basic", "beginner", "common"),
            aliases=("light", "indicator led"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:diode_0603",
            family=_family("diode", "Diode"),
            variant=ComponentVariant(name="Diode 0603", package="0603", mounting="smd", default_value="D"),
            symbol_id="stdlib:D",
            footprint_id="stdlib:D_0603",
            tags=("diode", "smd", "0603", "basic", "common"),
            aliases=("signal diode",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:push_button_th",
            family=_family("button", "Push Button"),
            variant=ComponentVariant(name="Push Button Through Hole", package="through-hole", mounting="through-hole", default_value="Button"),
            symbol_id="stdlib:SW_PUSH",
            footprint_id="stdlib:SW_PUSH_TH",
            tags=("button", "switch", "input", "through-hole", "basic", "beginner"),
            aliases=("momentary switch", "pushbutton"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:switch_spst_th",
            family=_family("switch", "Switch"),
            variant=ComponentVariant(name="SPST Switch Through Hole", package="through-hole", mounting="through-hole", default_value="Switch"),
            symbol_id="stdlib:SW_SPST",
            footprint_id="stdlib:SW_SPST_TH",
            tags=("switch", "input", "through-hole", "spst", "basic", "beginner"),
            aliases=("toggle", "on off"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:pin_header_1x02_p2.54mm",
            family=_family("connector", "Connector"),
            variant=ComponentVariant(name="Pin Header 1x02 P2.54mm", package="p2.54mm", mounting="through-hole", default_value="Header"),
            symbol_id="stdlib:CONN_01X02",
            footprint_id="stdlib:PinHeader_1x02_P2.54mm",
            tags=("connector", "header", "through-hole", "p2.54mm", "basic", "beginner", "common"),
            aliases=("2 pin header", "terminal", "power connector"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:vcc_power",
            family=_family("power", "Power Symbol"),
            variant=ComponentVariant(name="VCC Power Symbol", mounting="virtual", default_value="VCC"),
            symbol_id="stdlib:VCC",
            tags=("power", "vcc", "supply", "virtual", "basic"),
            aliases=("positive supply",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:gnd_power",
            family=_family("power", "Power Symbol"),
            variant=ComponentVariant(name="Ground Symbol", mounting="virtual", default_value="GND"),
            symbol_id="stdlib:GND",
            tags=("power", "ground", "gnd", "virtual", "basic"),
            aliases=("0v", "earth"),
            group_ids=("basic-components",),
        ),
    )
    catalog = ComponentCatalog(groups=(basic,), entries=entries)
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: ComponentCatalog) -> None:
    group_ids = {group.id for group in catalog.groups}
    seen_ids: set[str] = set()
    for entry in catalog.entries:
        if entry.id in seen_ids:
            raise ValueError(f"Duplicate catalog entry: {entry.id}")
        seen_ids.add(entry.id)
        if entry.symbol_id not in SYMBOLS:
            raise ValueError(f"Catalog entry {entry.id} references missing symbol {entry.symbol_id}")
        if entry.footprint_id is not None and entry.footprint_id not in FOOTPRINTS:
            raise ValueError(f"Catalog entry {entry.id} references missing footprint {entry.footprint_id}")
        missing_groups = set(entry.group_ids) - group_ids
        if missing_groups:
            raise ValueError(f"Catalog entry {entry.id} references missing groups {sorted(missing_groups)}")


def entry_by_id(catalog: ComponentCatalog, entry_id: str) -> CatalogEntry:
    for entry in catalog.entries:
        if entry.id == entry_id:
            return entry
    raise KeyError(f"Unknown catalog entry: {entry_id}")


def search_catalog(
    catalog: ComponentCatalog,
    query: CatalogSearchQuery,
    *,
    global_preferences: CatalogPreferences | None = None,
    project_preferences: CatalogPreferences | None = None,
) -> tuple[CatalogEntry, ...]:
    entries = catalog.entries
    if query.preferred_only:
        preferred_ids = _preferred_entry_ids(catalog, global_preferences, project_preferences)
        entries = tuple(entry for entry in entries if entry.id in preferred_ids)
    if query.group_ids:
        entries = tuple(entry for entry in entries if set(entry.group_ids) & set(query.group_ids))
    if query.tags:
        entries = tuple(entry for entry in entries if set(query.tags).issubset(entry.tags))
    if query.text:
        terms = query.text.split("-")
        entries = tuple(
            entry
            for entry in entries
            if all(term in entry.search_text.lower().replace(" ", "-") for term in terms)
        )
    return entries


def _preferred_entry_ids(
    catalog: ComponentCatalog,
    global_preferences: CatalogPreferences | None,
    project_preferences: CatalogPreferences | None,
) -> set[str]:
    enabled_groups = {group.id for group in catalog.groups if group.default_enabled}
    visible_ids: set[str] = set()
    hidden_ids: set[str] = set()
    for preferences in (global_preferences, project_preferences):
        if preferences is None:
            continue
        enabled_groups.update(preferences.enabled_group_ids)
        visible_ids.update(preferences.visible_entry_ids)
        hidden_ids.update(preferences.hidden_entry_ids)
    preferred = {
        entry.id
        for entry in catalog.entries
        if set(entry.group_ids) & enabled_groups or entry.id in visible_ids
    }
    return preferred - hidden_ids


def create_missing_part_request(
    requested_name: str,
    *,
    reason: str,
    tags: tuple[str, ...] = (),
) -> MissingPartRequest:
    return MissingPartRequest(
        requested_name=requested_name,
        reason=reason,
        requested_tags=tags,
    )
```

- [ ] **Step 5: Run Task 2 tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/services/test_component_catalog.py tests/unit/services/test_builtin_library.py -q --basetemp=.tmp/pytest-phase2-task2-green
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add src/pcbsmith/services/component_catalog.py src/pcbsmith/services/builtin_library.py tests/unit/services/test_component_catalog.py tests/unit/services/test_builtin_library.py
git commit -m "feat: add built-in component catalog"
```

## Task 3: Catalog-Based Editor Placement

**Files:**
- Modify: `src/pcbsmith/ui/editor_state.py`
- Modify: `src/pcbsmith/ui/schematic_scene.py`
- Test: `tests/unit/ui/test_editor_state.py`
- Test: `tests/integration/test_gui_phase2.py`

- [ ] **Step 1: Write failing editor placement tests**

Append to `tests/unit/ui/test_editor_state.py`:

```python
from pcbsmith.core.geom import Point


def test_place_symbol_uses_prefix_for_new_basic_symbols() -> None:
    state = EditorState.blank("main")

    state = state.place_symbol("stdlib:D", "D", Point(x=0, y=0), footprint_id="stdlib:D_0603")
    state = state.place_symbol("stdlib:SW_PUSH", "Button", Point(x=2_540_000, y=0), footprint_id="stdlib:SW_PUSH_TH")
    state = state.place_symbol("stdlib:SW_SPST", "Switch", Point(x=5_080_000, y=0), footprint_id="stdlib:SW_SPST_TH")

    assert [symbol.reference for symbol in state.symbols] == ["D1", "SW1", "SW2"]
```

Create `tests/integration/test_gui_phase2.py`:

```python
from pcbsmith.core.geom import Point
from pcbsmith.services import component_catalog
from pcbsmith.ui.schematic_scene import SchematicScene


def test_scene_places_catalog_component(qtbot) -> None:
    scene = SchematicScene()
    catalog = component_catalog.builtin_catalog()
    entry = component_catalog.entry_by_id(catalog, "pcbs:capacitor_0603")

    item = scene.place_catalog_entry(entry, Point(x=0, y=0))

    symbol = scene.editor_state.symbols[0]
    assert item.symbol.reference == "C1"
    assert symbol.symbol_id == "stdlib:C"
    assert symbol.value == "100nF"
    assert symbol.footprint_id == "stdlib:C_0603"
```

- [ ] **Step 2: Run placement tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/ui/test_editor_state.py tests/integration/test_gui_phase2.py -q --basetemp=.tmp/pytest-phase2-task3-red
```

Expected: FAIL because new prefixes and `place_catalog_entry` do not exist.

- [ ] **Step 3: Add reference prefixes**

Modify `_PREFIX_BY_SYMBOL` in `src/pcbsmith/ui/editor_state.py`:

```python
_PREFIX_BY_SYMBOL = {
    "stdlib:R": "R",
    "stdlib:C": "C",
    "stdlib:LED": "LED",
    "stdlib:D": "D",
    "stdlib:SW_PUSH": "SW",
    "stdlib:SW_SPST": "SW",
    "stdlib:VCC": "PWR",
    "stdlib:GND": "PWR",
    "stdlib:CONN_01X02": "J",
}
```

- [ ] **Step 4: Add generic scene placement**

Modify imports in `src/pcbsmith/ui/schematic_scene.py`:

```python
from pcbsmith.core.catalog import CatalogEntry
```

Add method to `SchematicScene`:

```python
    def place_catalog_entry(self, entry: CatalogEntry, position: Point) -> SymbolItem:
        state = self._editor_state.place_symbol(
            entry.symbol_id,
            entry.variant.default_value or entry.family.name,
            snap(position, GRID_NM),
            footprint_id=entry.footprint_id,
        )
        self.apply_editor_state(state)
        return self._symbol_items[-1]
```

Update `place_resistor` to use the catalog service:

```python
    def place_resistor(self, position: Point, value: str = "10k") -> SymbolItem:
        state = self._editor_state.place_symbol(
            "stdlib:R",
            value,
            snap(position, GRID_NM),
            footprint_id="stdlib:R_0603",
        )
        self.apply_editor_state(state)
        return self._symbol_items[-1]
```

- [ ] **Step 5: Run Task 3 tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/ui/test_editor_state.py tests/integration/test_gui_phase2.py -q --basetemp=.tmp/pytest-phase2-task3-green
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add src/pcbsmith/ui/editor_state.py src/pcbsmith/ui/schematic_scene.py tests/unit/ui/test_editor_state.py tests/integration/test_gui_phase2.py
git commit -m "feat: place schematic components from catalog"
```

## Task 4: Searchable Component Browser UI

**Files:**
- Create: `src/pcbsmith/ui/component_browser.py`
- Modify: `src/pcbsmith/ui/main_window.py`
- Test: `tests/integration/test_gui_phase2.py`

- [ ] **Step 1: Write failing browser UI tests**

Append to `tests/integration/test_gui_phase2.py`:

```python
from PySide6.QtCore import Qt

from pcbsmith.ui.component_browser import ComponentBrowser
from pcbsmith.ui.main_window import MainWindow


def test_component_browser_filters_by_search_text(qtbot) -> None:
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    browser.search_box.setText("led")

    assert browser.visible_entry_ids() == ("pcbs:led_0603",)


def test_component_browser_preferred_only_can_hide_entries(qtbot) -> None:
    browser = ComponentBrowser()
    qtbot.addWidget(browser)

    browser.set_project_preferences(hidden_entry_ids=("pcbs:led_0603",))
    browser.preferred_only.setChecked(True)
    browser.search_box.setText("led")

    assert browser.visible_entry_ids() == ()


def test_main_window_places_selected_browser_component(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.component_browser.search_box.setText("capacitor")
    window.component_browser.select_entry("pcbs:capacitor_0603")
    window.place_selected_component_at_origin()

    symbol = window.scene.editor_state.symbols[0]
    assert symbol.symbol_id == "stdlib:C"
    assert symbol.value == "100nF"
```

- [ ] **Step 2: Run browser tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase2.py -q --basetemp=.tmp/pytest-phase2-task4-red
```

Expected: FAIL because `ComponentBrowser` and main-window wiring do not exist.

- [ ] **Step 3: Implement component browser**

Create `src/pcbsmith/ui/component_browser.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QLineEdit, QListWidget, QVBoxLayout, QWidget

from pcbsmith.core.catalog import CatalogEntry, CatalogPreferences, CatalogSearchQuery
from pcbsmith.services import component_catalog


class ComponentBrowser(QWidget):
    entry_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog = component_catalog.builtin_catalog()
        self.project_preferences = CatalogPreferences()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search components")
        self.preferred_only = QCheckBox("Preferred")
        self.component_list = QListWidget()

        layout = QVBoxLayout(self)
        layout.addWidget(self.search_box)
        layout.addWidget(self.preferred_only)
        layout.addWidget(self.component_list)

        self.search_box.textChanged.connect(self.refresh)
        self.preferred_only.toggled.connect(self.refresh)
        self.component_list.itemDoubleClicked.connect(
            lambda item: self.entry_activated.emit(item.data(32))
        )
        self.refresh()

    def set_project_preferences(
        self,
        *,
        enabled_group_ids: tuple[str, ...] = (),
        visible_entry_ids: tuple[str, ...] = (),
        hidden_entry_ids: tuple[str, ...] = (),
    ) -> None:
        self.project_preferences = CatalogPreferences(
            enabled_group_ids=enabled_group_ids,
            visible_entry_ids=visible_entry_ids,
            hidden_entry_ids=hidden_entry_ids,
        )
        self.refresh()

    def refresh(self) -> None:
        self.component_list.clear()
        query = CatalogSearchQuery(
            text=self.search_box.text(),
            preferred_only=self.preferred_only.isChecked(),
        )
        for entry in component_catalog.search_catalog(
            self.catalog,
            query,
            project_preferences=self.project_preferences,
        ):
            item_text = entry.variant.name
            self.component_list.addItem(item_text)
            self.component_list.item(self.component_list.count() - 1).setData(32, entry.id)

    def visible_entry_ids(self) -> tuple[str, ...]:
        return tuple(
            self.component_list.item(index).data(32)
            for index in range(self.component_list.count())
        )

    def select_entry(self, entry_id: str) -> None:
        for index in range(self.component_list.count()):
            item = self.component_list.item(index)
            if item.data(32) == entry_id:
                self.component_list.setCurrentItem(item)
                return
        raise ValueError(f"Catalog entry is not visible: {entry_id}")

    def selected_entry(self) -> CatalogEntry | None:
        item = self.component_list.currentItem()
        if item is None:
            return None
        return component_catalog.entry_by_id(self.catalog, item.data(32))
```

- [ ] **Step 4: Wire browser into main window**

Modify `src/pcbsmith/ui/main_window.py` imports:

```python
from pcbsmith.services import component_catalog, erc, project_io
from pcbsmith.ui.component_browser import ComponentBrowser
```

Replace `self.library_list = QListWidget()` with:

```python
        self.component_browser = ComponentBrowser()
```

Update `_create_library_dock`:

```python
    def _create_library_dock(self) -> None:
        self.component_browser.entry_activated.connect(self.place_catalog_entry_by_id)
        self.library_dock.setWidget(self.component_browser)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)
```

Add methods:

```python
    def place_catalog_entry_by_id(self, entry_id: str) -> None:
        try:
            entry = component_catalog.entry_by_id(self.component_browser.catalog, entry_id)
        except KeyError as exc:
            self.show_error(str(exc))
            return
        self.scene.place_catalog_entry(entry, Point(x=0, y=0))
        self.console.append(f"Placed {entry.variant.name}")

    def place_selected_component_at_origin(self) -> None:
        entry = self.component_browser.selected_entry()
        if entry is None:
            self.show_error("No component is selected")
            return
        self.scene.place_catalog_entry(entry, Point(x=0, y=0))
        self.console.append(f"Placed {entry.variant.name}")
```

In `_create_toolbar`, add actions for capacitor, LED, and More Components:

```python
        place_capacitor_action = QAction("Place C", self)
        place_capacitor_action.triggered.connect(
            lambda: self.place_catalog_entry_by_id("pcbs:capacitor_0603")
        )
        toolbar.addAction(place_capacitor_action)

        place_led_action = QAction("Place LED", self)
        place_led_action.triggered.connect(
            lambda: self.place_catalog_entry_by_id("pcbs:led_0603")
        )
        toolbar.addAction(place_led_action)

        more_components_action = QAction("More Components", self)
        more_components_action.triggered.connect(self.component_browser.search_box.setFocus)
        toolbar.addAction(more_components_action)
```

Keep existing resistor, wire, label, no-connect, undo, redo, delete, rotate, fit, and ERC actions.

- [ ] **Step 5: Run Task 4 tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase2.py -q --basetemp=.tmp/pytest-phase2-task4-green
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git add src/pcbsmith/ui/component_browser.py src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase2.py
git commit -m "feat: add searchable component browser"
```

## Task 5: Project Preference Resolution In The GUI

**Files:**
- Modify: `src/pcbsmith/ui/main_window.py`
- Modify: `src/pcbsmith/services/project_io.py`
- Test: `tests/integration/test_gui_phase2.py`
- Test: `tests/unit/services/test_project_io.py`

- [ ] **Step 1: Write failing preference integration tests**

Append to `tests/integration/test_gui_phase2.py`:

```python
from pcbsmith.core.catalog import CatalogPreferences
from pcbsmith.core.project import Project
from pcbsmith.services import project_io


def test_open_project_applies_project_catalog_preferences(qtbot, tmp_path) -> None:
    project_dir = tmp_path / "preferred-project"
    project = project_io.create_project(project_dir, "Preferred")
    project_io.save_project(
        project_dir,
        project.model_copy(
            update={
                "catalog_preferences": CatalogPreferences(
                    enabled_group_ids=("basic-components",),
                    hidden_entry_ids=("pcbs:led_0603",),
                )
            }
        ),
    )

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_dir)
    window.component_browser.preferred_only.setChecked(True)
    window.component_browser.search_box.setText("led")

    assert window.component_browser.visible_entry_ids() == ()
```

- [ ] **Step 2: Run preference integration test to verify it fails**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase2.py::test_open_project_applies_project_catalog_preferences -q --basetemp=.tmp/pytest-phase2-task5-red
```

Expected: FAIL because opening a project does not apply catalog preferences to the browser.

- [ ] **Step 3: Apply project preferences on open**

In `src/pcbsmith/ui/main_window.py`, inside `open_project` after `self.project = project`, add:

```python
        self.component_browser.set_project_preferences(
            enabled_group_ids=project.catalog_preferences.enabled_group_ids,
            visible_entry_ids=project.catalog_preferences.visible_entry_ids,
            hidden_entry_ids=project.catalog_preferences.hidden_entry_ids,
        )
```

- [ ] **Step 4: Run Task 5 tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/integration/test_gui_phase2.py tests/unit/services/test_project_io.py -q --basetemp=.tmp/pytest-phase2-task5-green
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git add src/pcbsmith/ui/main_window.py tests/integration/test_gui_phase2.py
git commit -m "feat: apply project component preferences"
```

## Task 6: Missing-Part And Developer Proposal Service

**Files:**
- Modify: `src/pcbsmith/services/component_catalog.py`
- Test: `tests/unit/services/test_component_catalog.py`

- [ ] **Step 1: Write failing proposal service tests**

Append to `tests/unit/services/test_component_catalog.py`:

```python
def test_create_developer_proposal() -> None:
    proposal = component_catalog.create_developer_proposal(
        requested_name="NE555 DIP-8",
        proposed_entry_id="pcbs:ne555_dip8",
        notes="Needs exact pin map before normal-user placement.",
    )

    assert proposal.requested_name == "NE555 DIP-8"
    assert proposal.proposed_entry_id == "pcbs:ne555_dip8"
    assert proposal.status == "draft"


def test_developer_proposal_rejects_non_namespaced_id() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        component_catalog.create_developer_proposal(
            requested_name="Bad",
            proposed_entry_id="bad",
            notes="Invalid id",
        )
```

- [ ] **Step 2: Run proposal tests to verify they fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/services/test_component_catalog.py::test_create_developer_proposal tests/unit/services/test_component_catalog.py::test_developer_proposal_rejects_non_namespaced_id -q --basetemp=.tmp/pytest-phase2-task6-red
```

Expected: FAIL because `create_developer_proposal` does not exist.

- [ ] **Step 3: Implement developer proposal service**

Modify imports in `src/pcbsmith/services/component_catalog.py`:

```python
    DeveloperLibraryProposal,
```

Add:

```python
def create_developer_proposal(
    *,
    requested_name: str,
    proposed_entry_id: str,
    notes: str,
) -> DeveloperLibraryProposal:
    return DeveloperLibraryProposal(
        requested_name=requested_name,
        proposed_entry_id=proposed_entry_id,
        notes=notes,
    )
```

- [ ] **Step 4: Run Task 6 tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest tests/unit/services/test_component_catalog.py -q --basetemp=.tmp/pytest-phase2-task6-green
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

Run:

```powershell
git add src/pcbsmith/services/component_catalog.py tests/unit/services/test_component_catalog.py
git commit -m "feat: add missing part proposal services"
```

## Task 7: Documentation, Full Verification, And Polish

**Files:**
- Modify: `README.md`
- Test: full test suite and lint

- [ ] **Step 1: Update README with Phase 2 catalog behavior**

Modify `README.md` to add this concise section near the current feature overview:

```markdown
## Component Catalog

PCBSmith includes a native component catalog for real CAD components. The first
catalog group, Basic Components, provides generic real variants such as 0603
resistors, 0603 capacitors, 0603 LEDs, diodes, switches, push buttons, headers,
and power symbols.

Catalog entries carry tags and aliases so users and future AI tools can search
by names, families, packages, and common terms. Simple starter parts use generic
real variants; chips and specialized components will use exact designations when
they are added.

External libraries such as LibrePCB and KiCad are future import sources. PCBSmith
keeps its own internal catalog schema so those sources can be adapted without
changing project files or the UI contract.
```

- [ ] **Step 2: Run ruff**

Run:

```powershell
& '.tmp\phase1a-venv2\Scripts\python.exe' -m ruff check src tests
```

Expected: PASS with no lint errors.

- [ ] **Step 3: Run full test suite**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest -q --basetemp=.tmp/pytest-phase2-full
```

Expected: PASS for the complete suite.

- [ ] **Step 4: Run GUI startup smoke**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -c "from PySide6.QtWidgets import QApplication; app = QApplication([]); from pcbsmith.ui.app import main; raise SystemExit(main(['pcbsmith-gui']))"
```

Expected: exits successfully without import or startup errors.

- [ ] **Step 5: Commit documentation**

Run:

```powershell
git add README.md
git commit -m "docs: document component catalog"
```

- [ ] **Step 6: Request review before final branch completion**

Use `superpowers:requesting-code-review` after all implementation commits and verification pass. The review should check:

- Catalog entries cannot point at missing symbols or footprints.
- Search behaves predictably for tags and aliases.
- Old projects load without catalog preference data.
- The UI places catalog components through the service path.
- The AI-facing service cannot invent components.

## Final Verification Commands

Run these before calling Phase 2 complete:

```powershell
git status --short --branch
& '.tmp\phase1a-venv2\Scripts\python.exe' -m ruff check src tests
$env:QT_QPA_PLATFORM='offscreen'
& '.tmp\phase1a-venv2\Scripts\python.exe' -m pytest -q --basetemp=.tmp/pytest-phase2-final
& '.tmp\phase1a-venv2\Scripts\python.exe' -c "from PySide6.QtWidgets import QApplication; app = QApplication([]); from pcbsmith.ui.app import main; raise SystemExit(main(['pcbsmith-gui']))"
```

Expected:

- Git branch is `codex/phase-2-component-catalog`.
- Working tree is clean except for intentional review artifacts before final commit.
- Ruff passes.
- Pytest passes.
- GUI startup smoke exits successfully.

## Plan Self-Review

Spec coverage:

- PCBSmith-native catalog model: Task 1.
- Basic Components group: Task 2.
- Generic real starter variants: Task 2.
- Tags and search: Tasks 1, 2, and 4.
- Preferred global/project profiles: Tasks 1, 2, and 5.
- UI component browser and shortcuts: Tasks 3 and 4.
- AI-safe shared service layer: Tasks 2, 3, and 6.
- Missing-part requests and developer proposals: Tasks 1, 2, and 6.
- Adapter-ready source metadata and namespaced ids: Tasks 1 and 2.
- Backward compatibility: Tasks 1, 5, and 7.

Placeholder scan:

- The plan contains no unresolved placeholder markers, empty error-handling
  instruction, or unspecified test task.

Type consistency:

- `CatalogEntry`, `CatalogGroup`, `CatalogPreferences`, `CatalogSearchQuery`,
  `MissingPartRequest`, and `DeveloperLibraryProposal` are defined in Task 1 and
  reused with the same names in later tasks.
- `component_catalog.builtin_catalog`, `validate_catalog`, `search_catalog`,
  `entry_by_id`, `create_missing_part_request`, and `create_developer_proposal`
  are defined before later tasks depend on them.
- `ComponentBrowser` exposes `visible_entry_ids`, `select_entry`,
  `set_project_preferences`, and `selected_entry` before `MainWindow` tests rely
  on those methods.
