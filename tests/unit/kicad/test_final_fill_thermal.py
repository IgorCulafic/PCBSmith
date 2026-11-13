from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFilledRegionContactObservation,
    KiCadFinalFillConnectivityObservation,
)
from pcbsmith.kicad.final_fill_thermal import (
    ThermalSpokeDisposition,
    audit_kicad_thermal_spokes,
    thermal_rule_context,
)


@pytest.fixture(autouse=True)
def simulated_native_execution(monkeypatch):
    # Unit tests isolate audit decisions. Receipt/file replay is tested by the
    # fill-adapter tests and the opt-in live native suite.
    monkeypatch.setattr(
        "pcbsmith.kicad.final_fill_thermal.verify_native_fill_execution",
        lambda *_: {"board_sha256": "a" * 64, "kicad_version": "10.0.3", "fingerprint": "c" * 64},
    )


def _observation(*, thermal: tuple[str, ...] = (), unresolved: tuple[str, ...] = ()):
    return KiCadFinalFillConnectivityObservation(
        board_file="board.kicad_pcb",
        board_sha256="a" * 64,
        kicad_version="10.0.3",
        island_authority="ZONE.IsIsland(layer, filled_outline_index)",
        records=(
            KiCadFilledRegionContactObservation(
                region_id="region:1",
                zone_id="zone:1",
                zone_index=0,
                region_index=0,
                net_name="GND",
                layer="B.Cu",
                is_island=False,
                direct_contact_ids=("pad:J1.1",),
                connected_pad_ids=("J1.1",),
                reachable_pad_ids=("J1.1",),
                thermal_applicable_pad_ids=thermal,
                thermal_resolution_unverified_pad_ids=unresolved,
                pad_mapping_exact=True,
                pad_mapping_scope="integer_effective_shape_contact_graph",
            ),
        ),
        qualification_boundary="fixture",
    )


def _report(tmp_path: Path, violations: list[dict[str, object]]) -> Path:
    path = tmp_path / "drc.json"
    path.write_text(
        json.dumps(
            {
                "$schema": "https://schemas.kicad.org/drc.v1.json",
                "source": "board.kicad_pcb",
                "kicad_version": "10.0.3",
                "violations": violations,
                "unconnected_items": [],
                "schematic_parity": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _project(tmp_path):
    path = tmp_path / "board.kicad_pro"
    path.write_text(
        json.dumps(
            {
                "board_design_settings": {
                    "rule_severities": {"starved_thermal": "error"},
                    "drc_exclusions": [],
                }
            }
        )
    )
    return path


def test_applicable_thermal_passes_only_with_exact_revision_and_no_starvation(
    tmp_path: Path,
) -> None:
    audit = audit_kicad_thermal_spokes(
        _observation(thermal=("J1.1",)),
        _report(tmp_path, []),
        drc_report_board_sha256="a" * 64,
        project_file=_project(tmp_path),
    )
    assert audit.disposition is ThermalSpokeDisposition.PASS
    assert audit.evaluated_object_count == 1


def test_starved_thermal_fails_and_unknown_mode_is_unverified(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [{"type": "starved_thermal", "items": [{"uuid": "pad-uuid"}]}],
    )
    failed = audit_kicad_thermal_spokes(
        _observation(thermal=("J1.1",)),
        report,
        drc_report_board_sha256="a" * 64,
        project_file=_project(tmp_path),
    )
    assert failed.disposition is ThermalSpokeDisposition.FAIL
    unverified = audit_kicad_thermal_spokes(
        _observation(unresolved=("J1.1",)),
        report,
        drc_report_board_sha256="a" * 64,
        project_file=_project(tmp_path),
    )
    assert unverified.disposition is ThermalSpokeDisposition.FAIL
    assert unverified.unresolved_pad_ids == ("J1.1",)


def test_no_thermal_contacts_is_explicitly_not_applicable(tmp_path: Path) -> None:
    audit = audit_kicad_thermal_spokes(
        _observation(),
        _report(tmp_path, []),
        drc_report_board_sha256="a" * 64,
    )
    assert audit.disposition is ThermalSpokeDisposition.NOT_APPLICABLE
    assert audit.evaluated_object_count == 0


def test_foreign_revision_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="another board revision"):
        audit_kicad_thermal_spokes(
            _observation(),
            _report(tmp_path, []),
            drc_report_board_sha256="b" * 64,
        )


@pytest.mark.parametrize(
    "field",
    ["$schema", "source", "kicad_version", "violations", "unconnected_items", "schematic_parity"],
)
def test_missing_native_report_fields_cannot_be_clean_thermal_evidence(tmp_path, field):
    report = _report(tmp_path, [])
    data = json.loads(report.read_text())
    del data[field]
    report.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        audit_kicad_thermal_spokes(
            _observation(thermal=("J1.1",)), report, drc_report_board_sha256="a" * 64
        )


@pytest.mark.parametrize("problem", ["missing", "ignored", "excluded", "report_excluded"])
def test_thermal_coverage_requires_enabled_unexcluded_rule(tmp_path, problem):
    project = _project(tmp_path)
    data = json.loads(project.read_bytes())
    if problem == "ignored":
        data["board_design_settings"]["rule_severities"]["starved_thermal"] = "ignore"
    if problem == "excluded":
        data["board_design_settings"]["drc_exclusions"] = ["waived"]
    project.write_text(json.dumps(data))
    report = _report(
        tmp_path,
        [{"type": "starved_thermal", "excluded": True}] if problem == "report_excluded" else [],
    )
    with pytest.raises(ValueError):
        audit_kicad_thermal_spokes(
            _observation(thermal=("J1.1",)),
            report,
            drc_report_board_sha256="a" * 64,
            project_file=None if problem == "missing" else project,
        )


def test_reported_starvation_cannot_become_not_applicable_with_no_contacts(tmp_path):
    audit = audit_kicad_thermal_spokes(
        _observation(),
        _report(tmp_path, [{"type": "starved_thermal"}]),
        drc_report_board_sha256="a" * 64,
    )
    assert audit.disposition is ThermalSpokeDisposition.FAIL


def test_custom_rule_change_invalidates_thermal_baseline(tmp_path):
    project = _project(tmp_path)
    before = thermal_rule_context(project)
    project.with_suffix(".kicad_dru").write_text("(version 1)")
    with_rules = thermal_rule_context(project)
    assert before != with_rules
    project.with_suffix(".kicad_dru").write_text(
        "(version 1)\n(rule disabled (constraint min_resolved_spokes 0))"
    )
    assert thermal_rule_context(project) != with_rules
    with pytest.raises(ValueError, match="custom rule suppression"):
        audit_kicad_thermal_spokes(
            _observation(thermal=("J1.1",)),
            _report(tmp_path, []),
            drc_report_board_sha256="a" * 64,
            project_file=project,
        )
