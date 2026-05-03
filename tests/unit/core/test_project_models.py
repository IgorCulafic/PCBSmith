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
