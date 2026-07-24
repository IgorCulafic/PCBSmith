"""Fail-closed approval binding between concept review and PCB generation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConceptApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-concept-approval-v1"] = "pcbsmith-concept-approval-v1"
    project_id: str
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None
    normalized_brief_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    concept_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_decisions: tuple[str, ...] = ()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_approval_request(
    *,
    project_id: str,
    normalized_brief_file: Path,
    concept_review_file: Path,
    output_file: Path,
) -> ConceptApproval:
    request = ConceptApproval(
        project_id=project_id,
        normalized_brief_sha256=file_sha256(normalized_brief_file),
        concept_review_sha256=file_sha256(concept_review_file),
    )
    output_file.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    return request


def require_concept_approval(
    *,
    project_id: str,
    normalized_brief_file: Path,
    concept_review_file: Path,
    approval_file: Path,
) -> ConceptApproval:
    """Require explicit approval bound to the exact brief and concept bytes."""

    if not approval_file.exists():
        raise RuntimeError(f"PCB generation requires concept approval: {approval_file}")
    approval = ConceptApproval.model_validate_json(approval_file.read_text(encoding="utf-8"))
    if approval.project_id != project_id:
        raise RuntimeError("concept approval belongs to a different project")
    if not approval.approved or not approval.approved_by or not approval.approved_at:
        raise RuntimeError("concept approval is pending")
    expected = (
        ("normalized brief", approval.normalized_brief_sha256, file_sha256(normalized_brief_file)),
        ("concept review", approval.concept_review_sha256, file_sha256(concept_review_file)),
    )
    for label, approved_hash, live_hash in expected:
        if approved_hash != live_hash:
            raise RuntimeError(f"{label} changed after concept approval")
    if not approval.accepted_decisions:
        raise RuntimeError("concept approval must record accepted decisions")
    return approval
