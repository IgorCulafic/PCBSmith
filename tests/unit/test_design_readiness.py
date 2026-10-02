from __future__ import annotations

from pathlib import Path

import pytest

from pcbsmith.design_readiness import (
    AutomaticGateState,
    ComponentCandidate,
    ComponentUseIntent,
    DesignChangeKind,
    DesignReadinessStage,
    DesignReleaseState,
    InvalidatedArtifact,
    PowerConversionContract,
    PowerRailLoad,
    PowerSourceContract,
    ReadinessDisposition,
    ReleaseGateSnapshot,
    ScopedDesignChange,
    SourceCurrentAuthority,
    SupportObservation,
    SupportRequirement,
    SupportRequirementKind,
    VisualSubjectRequirement,
    derive_design_release,
    evaluate_design_readiness,
    inspect_visual_subject_crop,
    plan_dependency_scoped_invalidation,
    require_design_readiness,
    review_component_alternatives,
    review_power_path,
    review_support_circuits,
    review_visual_subjects,
    visual_model_state_from_preflight,
)
from pcbsmith.kicad.model_preflight import ModelPreflightReport, ModelResolution


def _led_intent() -> ComponentUseIntent:
    return ComponentUseIntent(
        intent_id="decorative-border-led",
        role_id="presentation_border",
        required_capabilities=("emits_light", "single_color"),
        forbidden_capabilities=("individually_addressable", "rgb"),
        preferred_mounting="smd",
        hand_assembly_required=True,
        maximum_body_width_mm=3.5,
        maximum_body_height_mm=3.5,
        maximum_pin_count=2,
        maximum_unit_current_a=0.025,
        evidence_ids=("user:two-pin-led-preference",),
    )


def _led_candidates() -> tuple[ComponentCandidate, ...]:
    return (
        ComponentCandidate(
            candidate_id="kingbright-apt1608sgc",
            manufacturer_part_number="APT1608SGC",
            capabilities=("emits_light", "single_color"),
            behavioral_capabilities=("emits_light",),
            mounting="smd",
            body_width_mm=1.6,
            body_height_mm=0.8,
            pin_count=2,
            maximum_unit_current_a=0.02,
            hand_assembly_suitable=True,
            model_classification="exact_package",
            support_requirement_ids=("led-current-limit",),
            evidence_ids=("kingbright:apt1608sgc:p1-2",),
        ),
        ComponentCandidate(
            candidate_id="generic-3528-two-pin",
            manufacturer_part_number="TBD-3528-2PIN",
            capabilities=("emits_light", "single_color"),
            behavioral_capabilities=("emits_light",),
            mounting="smd",
            body_width_mm=3.5,
            body_height_mm=2.8,
            pin_count=2,
            maximum_unit_current_a=0.02,
            hand_assembly_suitable=True,
            model_classification="proxy",
            support_requirement_ids=("led-current-limit",),
            evidence_ids=("package-envelope:3528",),
        ),
        ComponentCandidate(
            candidate_id="ws2812b-5050",
            manufacturer_part_number="WS2812B",
            capabilities=(
                "emits_light",
                "rgb",
                "individually_addressable",
            ),
            behavioral_capabilities=("emits_light", "individually_addressable", "rgb"),
            mounting="smd",
            body_width_mm=5.0,
            body_height_mm=5.0,
            pin_count=4,
            maximum_unit_current_a=0.06,
            hand_assembly_suitable=True,
            model_classification="exact_package",
            support_requirement_ids=("led-local-decoupling", "led-data-integrity"),
            evidence_ids=("worldsemi:ws2812b",),
        ),
    )


def _ready_support_review():
    requirements = (
        SupportRequirement(
            requirement_id="led-current-limit",
            subject_reference="D1-D35",
            kind=SupportRequirementKind.CURRENT_LIMITING,
            minimum_value=82.0,
            maximum_value=330.0,
            units="ohm",
            source_ids=("kingbright:apt1608sgc:p2",),
            rationale="A two-pin LED needs controlled forward current.",
        ),
        SupportRequirement(
            requirement_id="sensor-thermal-isolation",
            subject_reference="U4",
            kind=SupportRequirementKind.THERMAL_ISOLATION,
            source_ids=("sensirion:design-guide:p8-10",),
            rationale="Humidity accuracy depends on isolation from board heat.",
        ),
    )
    observations = (
        SupportObservation(
            requirement_id="led-current-limit",
            disposition="verified",
            supporting_references=("RLED1-RLED35",),
            observed_value=150.0,
            evidence_ids=("schematic:led-branches",),
            rationale="One calculated resistor is present in every LED branch.",
        ),
        SupportObservation(
            requirement_id="sensor-thermal-isolation",
            disposition="verified",
            supporting_references=("U4",),
            evidence_ids=("placement:sensor-edge-slot",),
            rationale="The sensor is at a vented edge on a thermally narrowed island.",
        ),
    )
    return review_support_circuits(requirements=requirements, observations=observations)


def _ready_power_review():
    return review_power_path(
        source=PowerSourceContract(
            source_id="bench-5v",
            rail_id="+5V",
            voltage_v=5.0,
            available_continuous_current_a=1.0,
            available_peak_current_a=1.2,
            current_authority=SourceCurrentAuthority.DEDICATED_SUPPLY,
            current_detection_verified=True,
            direct_input_capacitance_uf=10.0,
            direct_input_capacitance_limit_uf=10.0,
            evidence_ids=("supply:qualified-5v-1a",),
        ),
        loads=(
            PowerRailLoad(
                load_id="led-border",
                rail_id="+5V",
                continuous_current_a=0.18,
                peak_current_a=0.25,
                evidence_ids=("led-current-calculation",),
            ),
            PowerRailLoad(
                load_id="logic",
                rail_id="+3V3",
                continuous_current_a=0.12,
                peak_current_a=0.30,
                evidence_ids=("logic-current-budget",),
            ),
        ),
        conversions=(
            PowerConversionContract(
                conversion_id="reg-3v3",
                input_rail_id="+5V",
                output_rail_id="+3V3",
                input_voltage_v=5.0,
                output_voltage_v=3.3,
                kind="linear",
                efficiency=0.66,
                maximum_output_current_a=0.5,
                verified_dissipation_limit_w=0.5,
                evidence_ids=("regulator:datasheet-and-thermal-check",),
            ),
        ),
    )


def test_component_selection_blocks_requirement_creep_and_recommends_small_led() -> None:
    failed = review_component_alternatives(
        intent=_led_intent(),
        candidates=_led_candidates(),
        selected_candidate_id="ws2812b-5050",
    )
    assert failed.disposition is ReadinessDisposition.BLOCKED
    assert failed.recommended_candidate_id == "kingbright-apt1608sgc"
    assert "forbidden_capability:individually_addressable" in failed.blockers
    assert "body_width_exceeds_intent" in failed.blockers
    ready = review_component_alternatives(
        intent=_led_intent(),
        candidates=tuple(reversed(_led_candidates())),
        selected_candidate_id="kingbright-apt1608sgc",
    )
    assert ready.disposition is ReadinessDisposition.READY
    assert ready.recommended_candidate_id == "kingbright-apt1608sgc"


def test_support_review_fails_closed_on_missing_led_limit_and_sensor_thermal_evidence() -> None:
    requirements = _ready_support_review().requirements
    failed = review_support_circuits(
        requirements=requirements,
        observations=(
            SupportObservation(
                requirement_id="sensor-thermal-isolation",
                disposition="unverified",
                rationale="No sensor placement/thermal evidence was generated.",
            ),
        ),
    )
    assert failed.disposition is ReadinessDisposition.BLOCKED
    assert "led-current-limit:missing_observation" in failed.blockers
    assert "sensor-thermal-isolation:unverified" in failed.blockers
    assert _ready_support_review().disposition is ReadinessDisposition.READY


def test_power_path_flags_unproven_three_amp_usb_inrush_and_ldo_thermal_claim() -> None:
    failed = review_power_path(
        source=PowerSourceContract(
            source_id="usb-c-vbus",
            rail_id="+5V",
            voltage_v=5.0,
            available_continuous_current_a=3.0,
            available_peak_current_a=3.0,
            current_authority=SourceCurrentAuthority.UNRESOLVED,
            current_detection_verified=False,
            direct_input_capacitance_uf=110.0,
            direct_input_capacitance_limit_uf=10.0,
            inrush_limiting_verified=False,
            evidence_ids=("usb2:p205", "usb-type-c:p201"),
        ),
        loads=(
            PowerRailLoad(
                load_id="ws2812-full-white",
                rail_id="+5V",
                continuous_current_a=2.1,
                peak_current_a=2.1,
                evidence_ids=("legacy-led-budget",),
            ),
            PowerRailLoad(
                load_id="logic-and-display",
                rail_id="+3V3",
                continuous_current_a=0.56,
                peak_current_a=0.56,
                evidence_ids=("legacy-logic-budget",),
            ),
        ),
        conversions=(
            PowerConversionContract(
                conversion_id="ncp1117-3v3",
                input_rail_id="+5V",
                output_rail_id="+3V3",
                input_voltage_v=5.0,
                output_voltage_v=3.3,
                kind="linear",
                efficiency=0.66,
                maximum_output_current_a=1.0,
                verified_dissipation_limit_w=None,
                evidence_ids=("onsemi:ncp1117:p9",),
            ),
        ),
    )
    assert failed.disposition is ReadinessDisposition.BLOCKED
    assert "usb-c-vbus:source_current_authority_unresolved" in failed.blockers
    assert "usb-c-vbus:input_capacitance_requires_inrush_limiting" in failed.blockers
    assert "ncp1117-3v3:thermal_limit_unverified" in failed.blockers
    assert _ready_power_review().disposition is ReadinessDisposition.READY


def test_quantitative_visual_review_rejects_blank_crop_and_accepts_visible_subject(
    tmp_path: Path,
) -> None:
    pillow = pytest.importorskip("PIL.Image")
    image_file = tmp_path / "review.png"
    image = pillow.new("RGB", (160, 80), "white")
    for x in range(95, 125):
        for y in range(20, 60):
            image.putpixel((x, y), (20, 20, 20))
    image.save(image_file)
    blank = inspect_visual_subject_crop(
        image_file=image_file,
        subject_id="sensor",
        crop_px=(5, 5, 65, 70),
    )
    visible = inspect_visual_subject_crop(
        image_file=image_file,
        subject_id="sensor",
        crop_px=(80, 5, 145, 70),
    )
    requirement = VisualSubjectRequirement(
        subject_id="sensor",
        component_reference="U4",
        artifact_id="detail:back:sensor",
        minimum_crop_width_px=48,
        minimum_crop_height_px=48,
        minimum_occupancy_fraction=0.08,
    )
    failed = review_visual_subjects(requirements=(requirement,), observations=(blank,))
    passed = review_visual_subjects(requirements=(requirement,), observations=(visible,))
    assert failed.disposition is ReadinessDisposition.BLOCKED
    assert "sensor:subject_not_measurably_visible" in failed.blockers
    assert passed.disposition is ReadinessDisposition.READY


def test_model_presence_and_alignment_are_separate_visual_gates() -> None:
    requirement = VisualSubjectRequirement(
        subject_id="oled",
        component_reference="J2",
        artifact_id="3d:populated:top",
        minimum_crop_width_px=48,
        minimum_crop_height_px=48,
        minimum_occupancy_fraction=0.05,
        model_required=True,
        aligned_model_required=True,
    )
    from pcbsmith.design_readiness import VisualSubjectObservation

    observation = VisualSubjectObservation(
        subject_id="oled",
        artifact_sha256="a" * 64,
        crop_px=(0, 0, 100, 100),
        crop_width_px=100,
        crop_height_px=100,
        occupancy_fraction=0.4,
        model_presence="present",
        model_alignment="failed",
    )
    review = review_visual_subjects(requirements=(requirement,), observations=(observation,))
    assert review.disposition is ReadinessDisposition.BLOCKED
    assert review.blockers == ("oled:model_alignment_not_verified",)


def test_release_state_never_calls_pending_or_failed_candidate_finished() -> None:
    base = dict(
        candidate_generated=True,
        review_package_generated=True,
        routing=AutomaticGateState.PASSED,
        drc=AutomaticGateState.PASSED,
        design_readiness=AutomaticGateState.PASSED,
        model_preflight=AutomaticGateState.PASSED,
        release_approved=False,
    )
    pending = derive_design_release(
        ReleaseGateSnapshot(visual_inspection=AutomaticGateState.PENDING, **base)
    )
    failed = derive_design_release(
        ReleaseGateSnapshot(
            visual_inspection=AutomaticGateState.PASSED,
            **{**base, "drc": AutomaticGateState.FAILED},
        )
    )
    candidate = derive_design_release(
        ReleaseGateSnapshot(visual_inspection=AutomaticGateState.PASSED, **base)
    )
    assert pending.state is DesignReleaseState.INSPECTION_PENDING
    assert failed.state is DesignReleaseState.ENGINEERING_HOLD
    assert candidate.state is DesignReleaseState.RELEASE_CANDIDATE


def test_dependency_invalidation_preserves_unrelated_artifacts_for_local_change() -> None:
    plan = plan_dependency_scoped_invalidation(
        (
            ScopedDesignChange(
                change_id="fix-oled-model",
                kind=DesignChangeKind.MODEL,
                component_references=("J2",),
                rationale="Correct one model transform without rebuilding copper.",
            ),
        )
    )
    assert not plan.whole_board_restart_required
    assert InvalidatedArtifact.MODEL_PREFLIGHT in plan.invalidated_artifacts
    assert InvalidatedArtifact.ROUTING in plan.preserved_artifacts
    assert InvalidatedArtifact.SCHEMATIC in plan.preserved_artifacts
    architecture = plan_dependency_scoped_invalidation(
        (
            ScopedDesignChange(
                change_id="change-board-architecture",
                kind=DesignChangeKind.ARCHITECTURE,
                rationale="Layer-count or topology change requires full regeneration.",
            ),
        )
    )
    assert architecture.whole_board_restart_required
    assert set(architecture.invalidated_artifacts) == set(InvalidatedArtifact)


def test_model_preflight_adapter_separates_presence_from_alignment() -> None:
    report = ModelPreflightReport(
        schema="pcbsmith-kicad-model-preflight-v1",
        board_file="board.kicad_pcb",
        board_sha256="a" * 64,
        status="passed",
        applicability="applicable",
        models=(
            ModelResolution(
                reference="J2",
                footprint="Display:OLED",
                raw_path="oled.step",
                resolved_path="C:/models/oled.step",
                status="resolved",
                classification="proxy",
                transform_alignment="not_declared",
            ),
        ),
        required_references=("J2",),
    )
    assert visual_model_state_from_preflight(report, "J2") == (
        "present",
        "not_declared",
    )
    assert visual_model_state_from_preflight(report, "U3") == (
        "unverified",
        "not_applicable",
    )

def test_aggregate_readiness_is_enforceable() -> None:
    component = review_component_alternatives(
        intent=_led_intent(),
        candidates=_led_candidates(),
        selected_candidate_id="kingbright-apt1608sgc",
    )
    ready = evaluate_design_readiness(
        stage=DesignReadinessStage.PREDESIGN,
        component_reviews=(component,),
        support_review=_ready_support_review(),
        power_review=_ready_power_review(),
    )
    require_design_readiness(ready)
    blocked = evaluate_design_readiness(
        stage=DesignReadinessStage.SAVED_CANDIDATE,
        component_reviews=(component,),
        support_review=_ready_support_review(),
        power_review=_ready_power_review(),
    )
    assert blocked.blockers == ("visual:review_missing",)
    with pytest.raises(ValueError, match="design readiness gate blocked publication"):
        require_design_readiness(blocked)
