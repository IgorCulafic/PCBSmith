from __future__ import annotations

from pathlib import Path

import pytest

from pcbsmith.predesign_gate import require_concept_approval, write_approval_request


def test_approval_is_pending_and_bound_to_exact_inputs(tmp_path: Path) -> None:
    brief = tmp_path / "brief.json"
    concept = tmp_path / "concept.json"
    approval = tmp_path / "approval.json"
    brief.write_text("{}", encoding="utf-8")
    concept.write_text("{}", encoding="utf-8")
    write_approval_request(
        project_id="fixture",
        normalized_brief_file=brief,
        concept_review_file=concept,
        output_file=approval,
    )

    with pytest.raises(RuntimeError, match="pending"):
        require_concept_approval(
            project_id="fixture",
            normalized_brief_file=brief,
            concept_review_file=concept,
            approval_file=approval,
        )


def test_approval_rejects_drift(tmp_path: Path) -> None:
    brief = tmp_path / "brief.json"
    concept = tmp_path / "concept.json"
    approval_file = tmp_path / "approval.json"
    brief.write_text("{}", encoding="utf-8")
    concept.write_text("{}", encoding="utf-8")
    pending = write_approval_request(
        project_id="fixture",
        normalized_brief_file=brief,
        concept_review_file=concept,
        output_file=approval_file,
    )
    accepted = pending.model_copy(
        update={
            "approved": True,
            "approved_by": "user",
            "approved_at": "2026-07-20T00:00:00Z",
            "accepted_decisions": ("fixture decision",),
        }
    )
    approval_file.write_text(accepted.model_dump_json(indent=2), encoding="utf-8")
    concept.write_text('{"changed":true}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after concept approval"):
        require_concept_approval(
            project_id="fixture",
            normalized_brief_file=brief,
            concept_review_file=concept,
            approval_file=approval_file,
        )
