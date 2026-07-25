from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pcbsmith.kicad.routing_evidence import inspect_saved_board_routing
from pcbsmith.production_workflow import (
    GenerationArtifact,
    GenerationTransactionManifest,
    RoutedBoardVerificationEvidence,
    RoutedVerificationKind,
    RoutedVerificationRecord,
    evaluate_routed_board_release_gate,
)
from pcbsmith.review.visual_package import RenderProfile, VisualReviewManifest
from pcbsmith.workflow_authority import WorkflowStage


def _board_text(*, routed: bool) -> str:
    segment = (
        """
  (segment
    (start 1 1)
    (end 5 1)
    (width 0.25)
    (layer "F.Cu")
    (net 1)
  )
"""
        if routed
        else ""
    )
    return f"""(kicad_pcb
  (version 20260206)
  (net 1 "SIG")
  (footprint "Test:A"
    (layer "F.Cu")
    (at 1 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  (footprint "Test:B"
    (layer "F.Cu")
    (at 5 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  {segment}
)
"""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _review(board: Path) -> VisualReviewManifest:
    evidence = inspect_saved_board_routing(board)
    return VisualReviewManifest(
        schema="pcbsmith-visual-review-manifest-v1",
        render_profile=RenderProfile(),
        stage="final",
        board_file=str(board.resolve()),
        board_sha256=evidence.board_sha256,
        copper_sha256="1" * 64,
        routing_evidence=evidence,
        kicad_version="10.0.3",
        renderer_version="test",
        model_preflight_status="passed",
        workflow_conformance_status="conformant",
        package_status="accepted",
        artifacts=(),
    )


def _transaction(
    board: Path,
    review: VisualReviewManifest,
) -> GenerationTransactionManifest:
    review_payload = (
        json.dumps(review.model_dump(mode="json", by_alias=True), indent=2) + "\n"
    ).encode("utf-8")
    artifacts = (
        GenerationArtifact(
            artifact_id="release-1.0001",
            role="board",
            relative_path=board.name,
            content_sha256=_sha256(board.read_bytes()),
        ),
        GenerationArtifact(
            artifact_id="release-1.0002",
            role="review",
            relative_path="review/manifest.json",
            content_sha256=_sha256(review_payload),
        ),
    )
    return GenerationTransactionManifest.build(
        project_id="release-test",
        generation_id="release-1",
        generation_sha256="2" * 64,
        stage=WorkflowStage.REVIEW,
        status="committed",
        artifacts=artifacts,
    )


def _clean_drc(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "violations": [],
                "unconnected_items": [],
                "schematic_parity": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _verification(
    board: Path,
    *,
    accepted: bool = True,
) -> RoutedBoardVerificationEvidence:
    board_sha256 = _sha256(board.read_bytes())
    records = tuple(
        RoutedVerificationRecord.build(
            kind=kind,
            board_sha256=board_sha256,
            producer_id=f"test.{kind.value}",
            tool_version="test-1",
            input_sha256s=(board_sha256, _sha256(kind.value.encode("utf-8"))),
            accepted=accepted,
            result_code="accepted" if accepted else "rejected",
        )
        for kind in RoutedVerificationKind
    )
    return RoutedBoardVerificationEvidence.build(
        board_sha256=board_sha256,
        records=records,
    )


def test_release_gate_accepts_only_the_exact_verified_routed_revision(
    tmp_path: Path,
) -> None:
    board = tmp_path / "release-candidate.kicad_pcb"
    board.write_text(_board_text(routed=True), encoding="utf-8")
    review = _review(board)

    report = evaluate_routed_board_release_gate(
        board_file=board,
        drc_report_file=_clean_drc(tmp_path / "drc.json"),
        final_review=review,
        committed_transaction=_transaction(board, review),
        verification_evidence=_verification(board),
    )

    assert report.allowed
    assert report.blockers == ()


def test_release_gate_cannot_promote_an_accepted_placement_manifest(
    tmp_path: Path,
) -> None:
    board = tmp_path / "candidate-placement.kicad_pcb"
    board.write_text(_board_text(routed=False), encoding="utf-8")
    review = _review(board)

    report = evaluate_routed_board_release_gate(
        board_file=board,
        drc_report_file=_clean_drc(tmp_path / "drc.json"),
        final_review=review,
        committed_transaction=_transaction(board, review),
        verification_evidence=_verification(board),
    )

    assert not report.allowed
    assert "canonical handoff board is still named as a placement artifact" in report.blockers
    assert "saved board routing state is placement_only" in report.blockers
    assert "saved board contains no track segments" in report.blockers


def test_release_gate_rejects_unretained_or_wrong_board_verification(
    tmp_path: Path,
) -> None:
    board = tmp_path / "release-candidate.kicad_pcb"
    board.write_text(_board_text(routed=True), encoding="utf-8")
    other = tmp_path / "other.kicad_pcb"
    other.write_text(_board_text(routed=True) + "\n", encoding="utf-8")
    review = _review(board)

    rejected = evaluate_routed_board_release_gate(
        board_file=board,
        drc_report_file=_clean_drc(tmp_path / "drc.json"),
        final_review=review,
        committed_transaction=_transaction(board, review),
        verification_evidence=_verification(board, accepted=False),
    )
    wrong_board = evaluate_routed_board_release_gate(
        board_file=board,
        drc_report_file=tmp_path / "drc.json",
        final_review=review,
        committed_transaction=_transaction(board, review),
        verification_evidence=_verification(other),
    )

    assert not rejected.allowed
    assert "mandatory exact route checker did not accept the board" in rejected.blockers
    assert "saved KiCad board read-back is not verified" in rejected.blockers
    assert not wrong_board.allowed
    assert "routed verification evidence targets a different saved board" in wrong_board.blockers


def test_routed_verification_bundle_rejects_missing_authority(
    tmp_path: Path,
) -> None:
    board = tmp_path / "release-candidate.kicad_pcb"
    board.write_text(_board_text(routed=True), encoding="utf-8")
    bundle = _verification(board)

    with pytest.raises(ValueError, match="requires exactly one"):
        RoutedBoardVerificationEvidence.build(
            board_sha256=bundle.board_sha256,
            records=bundle.records[:-1],
        )
