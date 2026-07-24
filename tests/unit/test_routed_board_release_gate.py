from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcbsmith.kicad.routing_evidence import inspect_saved_board_routing
from pcbsmith.production_workflow import (
    GenerationArtifact,
    GenerationTransactionManifest,
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
        exact_route_accepted=True,
        readback_verified=True,
        netlist_equivalent=True,
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
        exact_route_accepted=True,
        readback_verified=True,
        netlist_equivalent=True,
    )

    assert not report.allowed
    assert "canonical handoff board is still named as a placement artifact" in report.blockers
    assert "saved board routing state is placement_only" in report.blockers
    assert "saved board contains no track segments" in report.blockers
