from __future__ import annotations

from pcbsmith.automatic_review_gate import ProductionMarkingAudit, qualify_automatic_review
from pcbsmith.review.visual_package import RenderProfile, ReviewArtifact, VisualReviewManifest

BOARD = "a" * 64


def _artifact(
    artifact_id: str,
    *,
    generated: bool = True,
    inspection: str = "accepted",
) -> ReviewArtifact:
    return ReviewArtifact(
        artifact_id=artifact_id,
        category="fixture",
        relative_path=f"{artifact_id.replace(':', '-')}.png",
        media_type="image/png",
        required=True,
        state="generated" if generated else "missing",
        inspection=inspection if generated else "uninspected",
        sha256="b" * 64 if generated else None,
    )


def _manifest(*artifacts: ReviewArtifact) -> VisualReviewManifest:
    return VisualReviewManifest(
        schema="pcbsmith-visual-review-manifest-v1",
        render_profile=RenderProfile(),
        stage="final",
        board_file="board.kicad_pcb",
        board_sha256=BOARD,
        copper_sha256="c" * 64,
        kicad_version="10.0.3",
        renderer_version="10.0.3",
        model_preflight_status="passed",
        workflow_conformance_status="conformant",
        package_status="accepted",
        artifacts=artifacts,
    )


def _canonical(*extra: ReviewArtifact) -> VisualReviewManifest:
    return _manifest(
        _artifact("2d:front-design:png"),
        _artifact("2d:back-design:png"),
        _artifact("2d:front-copper:png"),
        _artifact("2d:back-copper:png"),
        _artifact("2d:combined-copper:png"),
        *extra,
    )


def _audit(**changes: object) -> ProductionMarkingAudit:
    values: dict[str, object] = {
        "board_sha256": BOARD,
        "drc_report_sha256": "1" * 64,
        "requirements_fingerprint": "2" * 64,
        "inventory_fingerprint": "3" * 64,
        "inspected_mark_count": 8,
    }
    values.update(changes)
    return ProductionMarkingAudit.build(**values)


def test_canonical_final_views_and_exact_marking_audit_can_pass() -> None:
    result = qualify_automatic_review(
        manifest=_canonical(),
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(),
    )
    assert result.accepted
    assert result.visual_package_complete
    assert result.exact_gate_passed


def test_missing_canonical_image_blocks_final_review() -> None:
    manifest = _canonical()
    artifacts = tuple(
        _artifact(item.artifact_id, generated=False)
        if item.artifact_id == "2d:back-copper:png"
        else item
        for item in manifest.artifacts
    )
    result = qualify_automatic_review(
        manifest=manifest.model_copy(update={"artifacts": artifacts}),
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(),
    )
    assert not result.accepted
    assert "missing_review_artifact:2d:back-copper:png" in result.blocker_ids


def test_triggered_crop_becomes_required() -> None:
    result = qualify_automatic_review(
        manifest=_canonical(_artifact("detail:front:power-neck")),
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(),
    )
    assert result.triggered_artifact_ids == ("detail:front:power-neck",)
    assert result.accepted


def test_silkscreen_finding_blocks_review_without_changing_placement_evidence() -> None:
    placement_evidence = "e" * 64
    result = qualify_automatic_review(
        manifest=_canonical(),
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(silk_over_copper_finding_ids=("silk:C1",)),
        proposed_repair_request_fingerprints=("f" * 64,),
    )
    assert not result.accepted
    assert result.blocker_ids == ("production_marking:silk:C1",)
    assert placement_evidence == "e" * 64
    assert result.proposed_repair_request_fingerprints == ("f" * 64,)


def test_zero_inspected_marks_cannot_be_an_exact_pass() -> None:
    result = qualify_automatic_review(
        manifest=_canonical(),
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(inspected_mark_count=0),
    )
    assert not result.exact_gate_passed
    assert not result.accepted


def test_unverified_polarity_or_mating_check_blocks_exact_pass() -> None:
    result = qualify_automatic_review(
        manifest=_canonical(),
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(unverified_check_ids=("polarity:D1",)),
    )
    assert not result.exact_gate_passed
    assert result.blocker_ids == ("production_marking_unverified:polarity:D1",)


def test_generated_but_uninspected_package_is_unverified_not_accepted() -> None:
    manifest = _canonical()
    artifacts = tuple(
        item.model_copy(update={"inspection": "uninspected"}) for item in manifest.artifacts
    )
    pending = manifest.model_copy(
        update={"artifacts": artifacts, "package_status": "generated_pending_inspection"}
    )

    result = qualify_automatic_review(
        manifest=pending,
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(),
    )

    assert result.visual_package_complete
    assert not result.accepted
    assert "visual_package_unverified:generated_pending_inspection" in result.blocker_ids
    assert any(item.startswith("visual_inspection_unverified:") for item in result.blocker_ids)


def test_attention_required_inspection_is_a_hard_visual_blocker() -> None:
    manifest = _canonical()
    artifacts = tuple(
        item.model_copy(update={"inspection": "attention_required"})
        if item.artifact_id == "2d:front-design:png"
        else item
        for item in manifest.artifacts
    )
    attention = manifest.model_copy(
        update={"artifacts": artifacts, "package_status": "attention_required"}
    )

    result = qualify_automatic_review(
        manifest=attention,
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(),
    )

    assert "visual_inspection:2d:front-design:png" in result.blocker_ids
    assert "visual_package:attention_required" in result.blocker_ids


def test_nonconformant_workflow_cannot_pass_with_complete_images() -> None:
    manifest = _canonical().model_copy(
        update={
            "workflow_conformance_status": "nonconformant",
            "package_status": "generation_failed",
        }
    )
    result = qualify_automatic_review(
        manifest=manifest,
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(),
    )

    assert not result.accepted
    assert "visual_workflow:nonconformant" in result.blocker_ids


def test_contradictory_accepted_status_with_uninspected_image_fails_closed() -> None:
    manifest = _canonical()
    artifacts = tuple(
        item.model_copy(update={"inspection": "uninspected"})
        if item.artifact_id == "2d:back-design:png"
        else item
        for item in manifest.artifacts
    )
    contradictory = manifest.model_copy(update={"artifacts": artifacts})

    result = qualify_automatic_review(
        manifest=contradictory,
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(),
    )

    assert "visual_package:accepted_status_inconsistent" in result.blocker_ids
    assert not result.accepted


def test_contradictory_passed_images_cannot_hide_failed_model_preflight() -> None:
    manifest = _canonical().model_copy(update={"model_preflight_status": "failed"})

    result = qualify_automatic_review(
        manifest=manifest,
        manifest_fingerprint="d" * 64,
        marking_audit=_audit(),
    )

    assert not result.accepted
    assert "model_preflight:failed" in result.blocker_ids
