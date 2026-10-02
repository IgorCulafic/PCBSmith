"""Legacy v1 approval binding retained for historical evidence compatibility.

New production work must use :mod:`pcbsmith.predesign_contract`.  The sole
non-ready compatibility path in this module is hash-locked to the retained
Retro-Pad R002 brief, concept, and approved approval-record bytes and cannot be
selected or extended by a caller.  That operational byte identity does not
authenticate the recorded approver identity or consent.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pcbsmith.kicad.concept_review import ConceptReview
from pcbsmith.project_brief import NormalizedProjectBrief

_HISTORICAL_R002_PROJECT_ID = "retro-pad"
_HISTORICAL_R002_BRIEF_SHA256 = (
    "a8205d92764f1e726c9fc8fdaeb26610856190a9b2b8080776977c403458a574"
)
_HISTORICAL_R002_CONCEPT_SHA256 = (
    "50885076eaebe624e1c5153ea6021fc021ed0acb70fe5dde7fa8f760c13d7d40"
)
_HISTORICAL_R002_APPROVAL_SHA256 = (
    "973cc03a72b92abf71dd982f77fbee2e4ff415ca8f951aaffcf8d69516258d3e"
)


class ConceptApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_id: Literal["pcbsmith-concept-approval-v1"] = "pcbsmith-concept-approval-v1"
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    approved: bool = False
    approved_by: str | None = Field(default=None, min_length=1)
    approved_at: datetime | None = None
    normalized_brief_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    concept_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_decisions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def approval_metadata_is_typed(self) -> Self:
        decisions = tuple(item for item in self.accepted_decisions)
        if len(decisions) != len(set(decisions)) or any(
            not item or item.strip() != item for item in decisions
        ):
            raise ValueError("accepted legacy decisions must be unique trimmed text")
        if self.approved:
            if self.approved_by is None or self.approved_by.strip() != self.approved_by:
                raise ValueError("approved legacy record requires an approver identity")
            if (
                self.approved_at is None
                or self.approved_at.tzinfo is None
                or self.approved_at.utcoffset() is None
            ):
                raise ValueError("approved legacy record requires timezone-aware approved_at")
        return self


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_brief(path: Path) -> NormalizedProjectBrief:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"cannot read normalized brief JSON: {path}") from exc
    try:
        return NormalizedProjectBrief.model_validate_json(raw)
    except ValidationError as exc:
        raise RuntimeError(f"normalized brief is not a full typed artifact: {path}") from exc


def _load_concept(path: Path) -> ConceptReview:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"cannot read concept review JSON: {path}") from exc
    try:
        return ConceptReview.model_validate_json(raw)
    except ValidationError as exc:
        raise RuntimeError(f"concept review is not a full typed artifact: {path}") from exc


def _load_approval(path: Path) -> ConceptApproval:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"cannot read concept approval JSON: {path}") from exc
    try:
        return ConceptApproval.model_validate_json(raw)
    except ValidationError as exc:
        raise RuntimeError(f"concept approval is not a valid typed v1 record: {path}") from exc


def _is_hash_locked_historical_r002(approval: ConceptApproval) -> bool:
    """Return true only when a record cites the retained R002 brief and concept."""

    return (
        approval.project_id == _HISTORICAL_R002_PROJECT_ID
        and approval.normalized_brief_sha256 == _HISTORICAL_R002_BRIEF_SHA256
        and approval.concept_review_sha256 == _HISTORICAL_R002_CONCEPT_SHA256
    )


def _migration_error() -> RuntimeError:
    return RuntimeError(
        "legacy v1 approval accepts only records citing the exact retained Retro-Pad "
        "R002 brief and concept bytes; "
        "migrate this request to pcbsmith.predesign_contract v2"
    )


def _require_ready_artifacts(
    *,
    brief: NormalizedProjectBrief,
    concept: ConceptReview,
) -> None:
    if (
        brief.outcome != "ready_for_concept"
        or brief.unresolved_requirement_ids
        or any(finding.blocking for finding in brief.findings)
    ):
        raise RuntimeError("normalized brief is not approval-ready")
    if concept.outcome not in {"ready_for_approval", "needs_user_decision"}:
        raise RuntimeError("concept review is not approval-ready")
    if concept.hard_conflicts or any(item.status == "conflict" for item in concept.items):
        raise RuntimeError("concept review retains an unresolved conflict")


def write_approval_request(
    *,
    project_id: str,
    normalized_brief_file: Path,
    concept_review_file: Path,
    output_file: Path,
) -> ConceptApproval:
    brief = _load_brief(normalized_brief_file)
    concept = _load_concept(concept_review_file)
    if brief.draft.project_id != project_id or concept.project_id != project_id:
        raise RuntimeError("approval inputs belong to a different project")
    brief_hash = file_sha256(normalized_brief_file)
    concept_hash = file_sha256(concept_review_file)
    request = ConceptApproval(
        project_id=project_id,
        normalized_brief_sha256=brief_hash,
        concept_review_sha256=concept_hash,
    )
    if not _is_hash_locked_historical_r002(request):
        raise _migration_error()
    output_file.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    return request


def require_concept_approval(
    *,
    project_id: str,
    normalized_brief_file: Path,
    concept_review_file: Path,
    approval_file: Path,
) -> ConceptApproval:
    """Require the exact retained R002 brief, concept, and approved-record bytes."""

    if not approval_file.exists():
        raise RuntimeError(f"PCB generation requires concept approval: {approval_file}")
    approval = _load_approval(approval_file)
    if approval.project_id != project_id:
        raise RuntimeError("concept approval belongs to a different project")
    if not approval.approved or not approval.approved_by or not approval.approved_at:
        raise RuntimeError("concept approval is pending")
    if not _is_hash_locked_historical_r002(approval):
        raise _migration_error()
    if file_sha256(approval_file) != _HISTORICAL_R002_APPROVAL_SHA256:
        raise RuntimeError(
            "legacy v1 compatibility requires the exact retained Retro-Pad R002 "
            "approved approval-record bytes"
        )
    expected = (
        ("normalized brief", approval.normalized_brief_sha256, file_sha256(normalized_brief_file)),
        ("concept review", approval.concept_review_sha256, file_sha256(concept_review_file)),
    )
    for label, approved_hash, live_hash in expected:
        if approved_hash != live_hash:
            raise RuntimeError(f"{label} changed after concept approval")
    if not approval.accepted_decisions:
        raise RuntimeError("concept approval must record accepted decisions")
    brief = _load_brief(normalized_brief_file)
    concept = _load_concept(concept_review_file)
    if brief.draft.project_id != project_id or concept.project_id != project_id:
        raise RuntimeError("approval artifacts belong to a different project")
    _require_ready_artifacts(
        brief=brief,
        concept=concept,
    )
    return approval
