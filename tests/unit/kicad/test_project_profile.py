from __future__ import annotations

import json

from pcbsmith.kicad.export_divider_highpass_led import _render_project
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def rules(text: str) -> dict[str, float]:
    payload = json.loads(text)
    return payload["board"]["design_settings"]["rules"]


def test_default_project_rules_match_compatibility_profile() -> None:
    rendered = rules(_render_project())

    assert rendered == {
        "min_clearance": 0.2,
        "min_copper_edge_clearance": 0.5,
        "min_hole_clearance": 0.25,
        "min_through_hole_diameter": 0.3,
        "min_track_width": 0.2,
        "min_via_diameter": 0.6,
    }


def test_project_rules_include_only_established_optional_limits() -> None:
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={
            "minimum_annular_ring_mm": 0.12,
            "minimum_hole_to_hole_web_mm": 0.45,
        }
    )
    spacing = DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
        update={"minimum_copper_clearance_mm": 0.18}
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={"geometry": geometry, "fab_spacing": spacing}
    )

    rendered = rules(_render_project(profile=profile))

    assert rendered["min_clearance"] == 0.18
    assert rendered["min_via_annular_width"] == 0.12
    assert rendered["min_hole_to_hole"] == 0.45


def test_footprint_specific_drill_override_does_not_mutate_profile() -> None:
    rendered = rules(_render_project(min_through_hole_mm=0.2))

    assert rendered["min_through_hole_diameter"] == 0.2
    assert DEFAULT_PCB_RULE_PROFILE.geometry.routing_via_drill_mm == 0.3
