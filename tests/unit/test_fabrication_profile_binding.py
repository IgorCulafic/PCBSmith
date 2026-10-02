from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.fabrication_profile_binding import FabricationProfilePropagation
from pcbsmith.rule_profiles import (
    HOME_2LAYER_PCB_RULE_PROFILE,
    pcb_rule_profile_fingerprint,
)


def _values(digest: str) -> dict[str, str]:
    return {
        "placement_profile_sha256": digest,
        "routing_profile_sha256": digest,
        "kicad_project_profile_sha256": digest,
        "drc_profile_sha256": digest,
        "current_analysis_profile_sha256": digest,
        "manufacturing_profile_sha256": digest,
    }


def test_home_profile_declares_process_limits_without_claiming_ampacity() -> None:
    geometry = HOME_2LAYER_PCB_RULE_PROFILE.geometry

    assert geometry.copper_layer_count == 2
    assert geometry.minimum_trace_width_mm == 0.3
    assert geometry.solder_mask_process == "none"
    assert geometry.silkscreen_process == "none"
    assert geometry.plated_through_vias_available is False
    assert geometry.via_process == "manual_rivet_or_wire"
    assert geometry.assembly_process == "hand_soldering"
    assert geometry.trace_thermal_model_id == "not_declared"


def test_profile_fingerprint_is_deterministic_and_content_sensitive() -> None:
    first = pcb_rule_profile_fingerprint(HOME_2LAYER_PCB_RULE_PROFILE)
    second = pcb_rule_profile_fingerprint(HOME_2LAYER_PCB_RULE_PROFILE)
    changed = HOME_2LAYER_PCB_RULE_PROFILE.model_copy(
        update={"profile_id": "changed-profile"}
    )

    assert first == second
    assert first != pcb_rule_profile_fingerprint(changed)


def test_profile_mismatch_fails_before_physical_design_consumers_diverge() -> None:
    digest = pcb_rule_profile_fingerprint(HOME_2LAYER_PCB_RULE_PROFILE)
    propagation = FabricationProfilePropagation(**_values(digest))
    assert propagation.profile_sha256 == digest

    mismatched = _values(digest)
    mismatched["routing_profile_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="profile mismatch"):
        FabricationProfilePropagation(**mismatched)
