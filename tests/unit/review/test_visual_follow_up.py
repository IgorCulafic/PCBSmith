"""Follow-up disposition must not turn missing evidence into a CAD repair loop."""

from pathlib import Path

import pytest

from pcbsmith.review.visual_package import (
    RenderProfile,
    ReviewArtifact,
    VisualReviewManifest,
    _write_review_report,
)


def _manifest(status: str, inspection: str, state: str = "generated") -> VisualReviewManifest:
    return VisualReviewManifest.model_validate(
        dict(
            schema="pcbsmith-visual-review-manifest-v1",
            render_profile=RenderProfile(),
            stage="placement",
            board_file="board.kicad_pcb",
            board_sha256="a" * 64,
            copper_sha256="b" * 64,
            kicad_version="10",
            renderer_version="test",
            model_preflight_status="passed",
            package_status=status,
            artifacts=[
                ReviewArtifact.model_validate(
                    dict(
                        artifact_id="overview",
                        category="overview/front",
                        relative_path="view.png",
                        media_type="image/png",
                        required=True,
                        state=state,
                        inspection=inspection,
                    )
                )
            ],
        )
    )


@pytest.mark.parametrize(
    "status,inspection,state,expected",
    [
        (
            "generated_pending_inspection",
            "uninspected",
            "generated",
            "Missing decisions alone require no CAD edit",
        ),
        ("generation_failed", "uninspected", "missing", "Diagnose the exact missing artifact"),
        ("attention_required", "attention_required", "generated", "Only a confirmed defect"),
        ("accepted", "accepted", "generated", "Stop optional visual corrections"),
    ],
)
def test_report_routes_follow_up_without_new_allowance(
    tmp_path: Path, status, inspection, state, expected
):
    manifest = _manifest(status, inspection, state)
    before = manifest.model_dump_json()
    report = tmp_path / "review-report.md"
    _write_review_report(report, manifest)
    text = report.read_text(encoding="utf-8")
    assert expected in text
    assert "Physical qualification is not established" in text
    assert "grant no acceptance, retry or runtime extension" in text
    assert "finished or expired job stays closed" in text
    assert manifest.model_dump_json() == before


def test_inconsistent_accepted_record_does_not_instruct_completion(tmp_path: Path):
    report = tmp_path / "review-report.md"
    _write_review_report(report, _manifest("accepted", "uninspected"))
    text = report.read_text(encoding="utf-8")
    assert "Inspection records are pending" in text
    assert "Required visual inspection is complete" not in text


def test_rejected_and_uninspected_evidence_both_remain_visible(tmp_path: Path):
    manifest = _manifest("attention_required", "attention_required")
    pending = manifest.artifacts[0].model_copy(
        update={"artifact_id": "detail", "inspection": "uninspected"}
    )
    manifest = manifest.model_copy(update={"artifacts": (*manifest.artifacts, pending)})
    report = tmp_path / "review-report.md"
    _write_review_report(report, manifest)
    text = report.read_text(encoding="utf-8")
    assert "Review findings need diagnosis" in text
    assert "Inspection records are pending for: detail" in text
