from __future__ import annotations

from datetime import date

from pcbsmith.workflow_conformance import (
    ApprovalKind,
    ArtifactConstraint,
    ConformanceDisposition,
    DeviationApproval,
    DeviationLevel,
    RequirementRisk,
    RequirementState,
    WorkflowArtifactObservation,
    WorkflowDeviation,
    WorkflowProfile,
    WorkflowRequirement,
    evaluate_workflow_conformance,
)

BOARD_HASH = "a" * 64
TODAY = date(2026, 7, 22)


def _requirement(*, risk: RequirementRisk = RequirementRisk.ORDINARY) -> WorkflowRequirement:
    return WorkflowRequirement(
        requirement_id="visual.3d.populated.rear-low",
        expected_artifact_id="3d:populated:rear-low",
        constraint=ArtifactConstraint(
            media_type="image/png",
            side="back",
            camera="rear-low",
            population="populated",
            minimum_long_edge_px=3840,
            board_sha256=BOARD_HASH,
            stage="final",
        ),
        rationale="Rear low-angle view reveals connector and model overhang.",
        risk=risk,
    )


def _profile(*, risk: RequirementRisk = RequirementRisk.ORDINARY) -> WorkflowProfile:
    return WorkflowProfile(
        profile_id="pcbsmith.visual-review.standard",
        profile_version=1,
        requirements=(_requirement(risk=risk),),
    )


def _observation(
    *,
    artifact_id: str = "3d:populated:rear-low",
    camera: str = "rear-low",
    side: str = "back",
    population: str = "populated",
    board_sha256: str = BOARD_HASH,
) -> WorkflowArtifactObservation:
    return WorkflowArtifactObservation(
        artifact_id=artifact_id,
        generated=True,
        media_type="image/png",
        side=side,
        camera=camera,
        population=population,
        pixel_size=(3840, 2160),
        board_sha256=board_sha256,
        stage="final",
        content_sha256="b" * 64,
    )


def _approval(
    *,
    kind: ApprovalKind = ApprovalKind.HUMAN,
    expires_on: date = date(2026, 8, 1),
) -> DeviationApproval:
    return DeviationApproval(
        approver_id="reviewer:fixture",
        approver_kind=kind,
        approved_on=date(2026, 7, 20),
        expires_on=expires_on,
    )


def test_exact_artifact_and_material_properties_are_required() -> None:
    report = evaluate_workflow_conformance(
        profile=_profile(),
        observations=(_observation(),),
        evaluated_on=TODAY,
    )

    assert report.disposition is ConformanceDisposition.CONFORMANT
    assert report.evaluations[0].state is RequirementState.SATISFIED


def test_renamed_wrong_camera_population_and_stale_board_cannot_pass() -> None:
    wrong = _observation(
        artifact_id="3d:populated:rear-low",
        camera="top",
        side="front",
        population="bare",
        board_sha256="c" * 64,
    )

    report = evaluate_workflow_conformance(
        profile=_profile(),
        observations=(wrong,),
        evaluated_on=TODAY,
    )

    assert report.disposition is ConformanceDisposition.NONCONFORMANT
    evaluation = report.evaluations[0]
    assert evaluation.state is RequirementState.INVALID
    assert any("camera mismatch" in finding for finding in evaluation.findings)
    assert any("population mismatch" in finding for finding in evaluation.findings)
    assert any("board_sha256 mismatch" in finding for finding in evaluation.findings)


def test_d0_addition_never_fills_a_missing_baseline_requirement() -> None:
    supplemental = _observation(artifact_id="supplemental:thermal:top")
    addition = WorkflowDeviation(
        deviation_id="dev:supplemental-thermal-top",
        level=DeviationLevel.ADDITION,
        artifact_id=supplemental.artifact_id,
        reason="Board-specific thermal review aid.",
        consequence="No reduction in baseline coverage.",
        residual_risk="Image is advisory only.",
    )

    report = evaluate_workflow_conformance(
        profile=_profile(),
        observations=(supplemental,),
        deviations=(addition,),
        evaluated_on=TODAY,
    )

    assert report.disposition is ConformanceDisposition.NONCONFORMANT
    assert report.evaluations[0].state is RequirementState.MISSING
    assert report.supplemental_artifact_ids == (supplemental.artifact_id,)


def test_d2_substitution_requires_matching_scope_and_retained_approval() -> None:
    substitute = _observation(artifact_id="custom:rear-low")
    deviation = WorkflowDeviation(
        deviation_id="dev:alternate-renderer",
        level=DeviationLevel.EQUIVALENT_SUBSTITUTION,
        requirement_id="visual.3d.populated.rear-low",
        artifact_id=substitute.artifact_id,
        reason="Alternate renderer used for model fidelity.",
        consequence="Renderer implementation differs.",
        residual_risk="Camera metadata may be interpreted differently.",
        approval=_approval(),
    )

    report = evaluate_workflow_conformance(
        profile=_profile(),
        observations=(substitute,),
        deviations=(deviation,),
        evaluated_on=TODAY,
    )

    assert report.disposition is ConformanceDisposition.CONFORMANT
    assert report.evaluations[0].state is RequirementState.SUBSTITUTED

    wrong_camera = substitute.model_copy(update={"camera": "top"})
    rejected = evaluate_workflow_conformance(
        profile=_profile(),
        observations=(wrong_camera,),
        deviations=(deviation,),
        evaluated_on=TODAY,
    )
    assert rejected.disposition is ConformanceDisposition.NONCONFORMANT


def test_expired_or_ai_approved_safety_waiver_is_rejected() -> None:
    expired = WorkflowDeviation(
        deviation_id="dev:expired",
        level=DeviationLevel.OMISSION,
        requirement_id="visual.3d.populated.rear-low",
        reason="Temporary renderer outage.",
        consequence="Rear overhang is not visible.",
        residual_risk="Mechanical interference may be missed.",
        approval=_approval(expires_on=date(2026, 7, 21)),
    )
    expired_report = evaluate_workflow_conformance(
        profile=_profile(),
        observations=(),
        deviations=(expired,),
        evaluated_on=TODAY,
    )
    assert expired_report.disposition is ConformanceDisposition.NONCONFORMANT
    assert "expired" in " ".join(expired_report.evaluations[0].findings).lower()

    ai_approved = expired.model_copy(
        update={
            "deviation_id": "dev:ai-safety-waiver",
            "approval": _approval(kind=ApprovalKind.AI),
        }
    )
    safety_report = evaluate_workflow_conformance(
        profile=_profile(risk=RequirementRisk.SAFETY_OR_RELEASE),
        observations=(),
        deviations=(ai_approved,),
        evaluated_on=TODAY,
    )
    assert safety_report.disposition is ConformanceDisposition.NONCONFORMANT
    assert "human approval" in " ".join(safety_report.evaluations[0].findings)


def test_valid_ordinary_d3_waiver_is_visible_in_disposition() -> None:
    waiver = WorkflowDeviation(
        deviation_id="dev:bounded-waiver",
        level=DeviationLevel.OMISSION,
        requirement_id="visual.3d.populated.rear-low",
        reason="Known renderer defect on this revision.",
        consequence="Rear low-angle review is deferred.",
        residual_risk="Connector overhang remains unreviewed.",
        approval=_approval(),
    )

    report = evaluate_workflow_conformance(
        profile=_profile(),
        observations=(),
        deviations=(waiver,),
        evaluated_on=TODAY,
    )

    assert report.disposition is ConformanceDisposition.CONFORMANT_WITH_WAIVERS
    assert report.evaluations[0].state is RequirementState.WAIVED
