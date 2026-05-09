from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.core.catalog import CatalogPreferences
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


def test_project_rejects_unknown_json_fields() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate_json('{"name": "Voltage Divider", "schematicz": []}')


def test_project_defaults_catalog_preferences() -> None:
    assert Project(name="Existing").catalog_preferences == CatalogPreferences()


def test_project_loads_old_json_without_catalog_preferences() -> None:
    project = Project.model_validate({"name": "Existing"})

    assert project.catalog_preferences.enabled_group_ids == ()


def test_project_roundtrips_catalog_preferences() -> None:
    project = Project(
        name="Existing",
        catalog_preferences=CatalogPreferences(
            enabled_group_ids=("basic-components",),
            hidden_entry_ids=("pcbs:led_0603",),
        ),
    )

    roundtripped = Project.model_validate_json(project.model_dump_json())

    assert roundtripped.catalog_preferences == project.catalog_preferences
