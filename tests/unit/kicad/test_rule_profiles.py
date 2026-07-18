from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    FabricationGeometryProfile,
    InsulationBarrier,
    InsulationProfile,
    OrdinaryClearanceRequirement,
    QualifiedInsulationReview,
    StandardEditionRef,
)


def verified_evidence() -> EvidenceRef:
    return EvidenceRef(
        kind="standard",
        title="Applicable safety standard",
        locator="table and clause",
        source_status="pinned",
        locator_status="text_verified",
        local_sha256="b" * 64,
        applicability_status="confirmed",
    )


def qualified_values(
    evidence: EvidenceRef | None = None,
    *,
    high_frequency_basis: tuple[str, ...] = ("hf-derivation",),
) -> dict[str, object]:
    source = evidence or verified_evidence()
    product_standard = StandardEditionRef(
        identifier="applicable product standard",
        edition="declared edition",
        evidence=(source,),
    )
    coordination_standard = StandardEditionRef(
        identifier="coordination standard",
        edition="declared edition",
        evidence=(source,),
    )
    barrier = InsulationBarrier(
        barrier_id="primary-to-secondary",
        nets_a=("/PRIMARY",),
        nets_b=("/SECONDARY",),
        insulation_type="reinforced",
        working_voltage_rms_v=230.0,
        working_voltage_peak_v=325.0,
        temporary_overvoltage_v=1200.0,
        rated_impulse_voltage_v=2500.0,
        maximum_working_frequency_hz=65_000.0,
        required_creepage_mm=6.4,
        required_clearance_mm=4.0,
        clearance_path_ids=("air-path-1",),
        creepage_path_ids=("surface-path-1",),
        derivation_rule_ids=("qualified-derivation",),
        high_frequency_basis_rule_ids=high_frequency_basis,
    )
    return {
        "profile_id": "qualified-product-case",
        "status": "qualified",
        "product_standard": product_standard,
        "coordination_standards": (coordination_standard,),
        "pollution_degree": 2,
        "material_group": "IIIa",
        "minimum_cti_v": 175.0,
        "maximum_altitude_m": 2000.0,
        "overvoltage_category": "II",
        "field_case": "inhomogeneous",
        "protection_regime": "none",
        "barriers": (barrier,),
        "review": QualifiedInsulationReview(
            status="qualified_review_complete",
            reviewer="named qualified reviewer",
            review_record_id="review-record-1",
            reviewed_on=date(2026, 7, 14),
        ),
    }


def test_default_profile_preserves_legacy_geometry_without_safety_claim() -> None:
    profile = DEFAULT_PCB_RULE_PROFILE

    assert profile.geometry.minimum_trace_width_mm == 0.2
    assert profile.geometry.routing_via_diameter_mm == 0.6
    assert profile.geometry.routing_via_drill_mm == 0.3
    assert profile.geometry.power_via_diameter_mm == 0.8
    assert profile.geometry.power_via_drill_mm == 0.4
    assert profile.fab_spacing.minimum_copper_clearance_mm == 0.2
    assert profile.fab_spacing.minimum_copper_to_edge_mm == 0.5
    assert profile.fab_spacing.minimum_hole_to_copper_mm == 0.25
    assert profile.insulation.status == "not_applicable"


def test_optional_geometry_limits_remain_unset_until_profiled() -> None:
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry

    assert geometry.minimum_annular_ring_mm is None
    assert geometry.minimum_hole_to_hole_web_mm is None
    assert geometry.minimum_solder_mask_web_mm is None


def test_via_diameter_must_exceed_drill() -> None:
    with pytest.raises(ValidationError, match="diameter must exceed"):
        FabricationGeometryProfile(
            profile_id="invalid",
            routing_via_diameter_mm=0.3,
            routing_via_drill_mm=0.3,
        )


def test_bare_voltage_cannot_qualify_insulation_profile() -> None:
    barrier = InsulationBarrier(
        barrier_id="bare-voltage-shortcut",
        nets_a=("/A",),
        nets_b=("/B",),
        insulation_type="reinforced",
        working_voltage_rms_v=230.0,
    )
    with pytest.raises(ValidationError, match="missing"):
        InsulationProfile(
            profile_id="unsafe-shortcut",
            status="qualified",
            barriers=(barrier,),
        )


def test_qualified_insulation_requires_pinned_verified_evidence() -> None:
    unpinned = verified_evidence().model_copy(update={"source_status": "unpinned"})

    with pytest.raises(ValidationError, match="checksum-pinned"):
        InsulationProfile.model_validate(qualified_values(unpinned))


def test_complete_context_can_be_marked_qualified() -> None:
    profile = InsulationProfile.model_validate(qualified_values())

    assert profile.status == "qualified"
    assert profile.missing_qualification_context() == ()


def test_default_profile_captures_legacy_stackup_and_routing_preferences() -> None:
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry

    assert geometry.default_signal_trace_width_mm == 0.3
    assert geometry.default_power_trace_width_mm == 0.8
    assert geometry.board_thickness_mm == 1.6
    assert geometry.copper_layer_count == 2
    assert geometry.outer_copper_thickness_um == 35.0
    assert geometry.substrate_description == "FR-4"
    assert geometry.trace_thermal_model_id == "legacy_ipc_2221a_external_fit"
    assert geometry.trace_temperature_rise_c == 10.0


def test_pairwise_ordinary_clearance_requires_disjoint_net_groups() -> None:
    with pytest.raises(ValidationError, match="net groups overlap"):
        OrdinaryClearanceRequirement(
            requirement_id="invalid-overlap",
            nets_a=("/A", "/SHARED"),
            nets_b=("/SHARED", "/B"),
            minimum_clearance_mm=0.5,
        )


def test_pairwise_ordinary_clearance_keeps_scope_and_provenance() -> None:
    requirement = OrdinaryClearanceRequirement(
        requirement_id="declared-interface-spacing",
        nets_a=("/A",),
        nets_b=("/B",),
        minimum_clearance_mm=0.5,
        mask_states_a=("masked",),
        mask_states_b=("partially_exposed", "fully_exposed"),
        roles_a=("routed_conductor",),
        roles_b=("component_termination",),
        exempt_component_refs=("U1",),
        rule_ids=("ordinary.spacing.example",),
    )

    assert requirement.minimum_clearance_mm == 0.5
    assert requirement.rule_ids == ("ordinary.spacing.example",)
    assert requirement.mask_states_a == ("masked",)
    assert requirement.mask_states_b == (
        "partially_exposed",
        "fully_exposed",
    )
    assert requirement.roles_a == ("routed_conductor",)
    assert requirement.roles_b == ("component_termination",)


def test_pairwise_ordinary_clearance_rejects_legacy_exposure_fields() -> None:
    with pytest.raises(ValidationError, match="exposures_a"):
        OrdinaryClearanceRequirement.model_validate(
            {
                "requirement_id": "legacy-ambiguous-scope",
                "nets_a": ("/A",),
                "nets_b": ("/B",),
                "minimum_clearance_mm": 0.5,
                "exposures_a": ("external_masked",),
            }
        )


def test_creepage_cannot_be_below_clearance() -> None:
    with pytest.raises(ValidationError, match="creepage cannot be below"):
        InsulationBarrier(
            barrier_id="invalid-distances",
            nets_a=("/A",),
            nets_b=("/B",),
            insulation_type="basic",
            required_clearance_mm=4.0,
            required_creepage_mm=3.0,
        )


def test_qualified_high_frequency_barrier_requires_named_basis() -> None:
    with pytest.raises(ValidationError, match="above 30 kHz"):
        InsulationProfile.model_validate(qualified_values(high_frequency_basis=()))


def test_qualified_insulation_requires_confirmed_applicability() -> None:
    conditional = verified_evidence().model_copy(update={"applicability_status": "conditional"})

    with pytest.raises(ValidationError, match="applicability-confirmed"):
        InsulationProfile.model_validate(qualified_values(conditional))


def test_qualified_insulation_requires_evidence_checksum() -> None:
    no_checksum = verified_evidence().model_copy(update={"local_sha256": None})

    with pytest.raises(ValidationError, match="checksum-pinned"):
        InsulationProfile.model_validate(qualified_values(no_checksum))


def test_qualified_insulation_requires_explicit_temporary_overvoltage() -> None:
    values = qualified_values()
    barrier = values["barriers"][0].model_copy(update={"temporary_overvoltage_v": None})
    values["barriers"] = (barrier,)

    with pytest.raises(ValidationError, match="temporary_overvoltage_v"):
        InsulationProfile.model_validate(values)


def test_credited_protection_requires_qualification_rules() -> None:
    values = qualified_values()
    values["protection_regime"] = "conformal_coating"

    with pytest.raises(ValidationError, match="credits protection"):
        InsulationProfile.model_validate(values)


def test_default_trace_widths_cannot_be_below_profile_minimum() -> None:
    with pytest.raises(ValidationError, match="trace widths"):
        FabricationGeometryProfile(
            profile_id="invalid-width",
            minimum_trace_width_mm=0.25,
            default_signal_trace_width_mm=0.2,
        )


def test_generated_vias_must_meet_declared_hole_and_annular_limits() -> None:
    with pytest.raises(ValidationError, match="finished hole"):
        FabricationGeometryProfile(
            profile_id="invalid-hole",
            minimum_finished_hole_mm=0.35,
        )
    with pytest.raises(ValidationError, match="annular ring"):
        FabricationGeometryProfile(
            profile_id="invalid-ring",
            minimum_annular_ring_mm=0.16,
        )
