from __future__ import annotations

from pcbsmith.kicad.fabrication import _fab_notes
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def test_default_fabrication_notes_name_compatibility_profile() -> None:
    notes = _fab_notes("demo", {"extent_mm": "10 x 20 mm"})

    assert "Material: FR-4" in notes
    assert "Overall thickness: 1.6 mm" in notes
    assert "outer copper thickness: 35 um" in notes
    assert "track width / ordinary copper clearance: 0.2 mm / 0.2 mm" in notes
    assert "pcbsmith-legacy-default-v1" in notes
    assert "not safety-insulation approval" in notes
    assert "IPC-6012" not in notes
    assert "current revision" not in notes
    assert "Package generation does not itself prove" in notes
    assert "+/- 10%" not in notes
    assert "ANSI/ESD" not in notes
    assert "RoHS compliance required" not in notes
    assert "Declared geometry limits" not in notes


def test_custom_fabrication_profile_changes_notes_without_safety_claim() -> None:
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={
            "substrate_description": "declared laminate",
            "board_thickness_mm": 0.8,
            "outer_copper_thickness_um": 70.0,
            "minimum_trace_width_mm": 0.15,
        }
    )
    spacing = DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
        update={
            "basis": "manufacturer_design_target",
            "minimum_copper_clearance_mm": 0.18,
        }
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "profile_id": "supplier-process-revision",
            "geometry": geometry,
            "fab_spacing": spacing,
        }
    )

    notes = _fab_notes("demo", {}, profile=profile)

    assert "Material: declared laminate" in notes
    assert "Overall thickness: 0.8 mm" in notes
    assert "outer copper thickness: 70 um" in notes
    assert "0.15 mm / 0.18 mm" in notes
    assert "supplier-process-revision (manufacturer_design_target)" in notes
    assert "not safety-insulation approval" in notes


def test_fabrication_notes_list_only_declared_geometry_limits() -> None:
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={
            "minimum_finished_hole_mm": 0.25,
            "minimum_annular_ring_mm": 0.12,
            "minimum_hole_to_hole_web_mm": 0.4,
            "minimum_component_body_to_edge_mm": 1.0,
        }
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(update={"geometry": geometry})

    notes = _fab_notes(
        "demo",
        {},
        drill_rows=((0.3, True, 2),),
        profile=profile,
    )

    assert "Minimum finished-hole minor axis: 0.25 mm" in notes
    assert "Minimum annular ring: 0.12 mm" in notes
    assert "Minimum hole-to-hole residual web: 0.4 mm" in notes
    assert "Minimum component-body to board-edge distance: 1 mm" in notes
    assert "maximum-axis nominal" in notes
    assert "| not declared |" in notes
    assert "+/-0.076 mm" not in notes
