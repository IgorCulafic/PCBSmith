"""Deterministic Phase 17 prompt examination and typed spatial anchors.

The module validates a structured transcription against exact source spans.
Natural-language interpretation may be prepared by a person or an external AI,
but no extracted claim can enter the production workflow without replaying
against the original prompt bytes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.workflow_authority import (
    ALL_PROJECT_CONTEXT_CATEGORIES,
    ProjectContextBundle,
    ProjectContextCategory,
    ProjectContextRecord,
    ProjectContextStatus,
)


class PromptResolution(StrEnum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class SourceSpan(SemanticIrModel):
    schema_id: Literal["pcbsmith-prompt-source-span"] = "pcbsmith-prompt-source-span"
    schema_version: Literal[1] = 1
    span_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    exact_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def span_is_ordered(self) -> Self:
        require_identity(self.span_id, "span_id")
        if self.end <= self.start:
            raise ValueError("source span end must exceed start")
        return self


class ExaminedClaim(SemanticIrModel):
    schema_id: Literal["pcbsmith-examined-prompt-claim"] = (
        "pcbsmith-examined-prompt-claim"
    )
    schema_version: Literal[1] = 1
    claim_id: str
    field_path: str
    value: str | int | float | bool | None
    unit: str | None = None
    resolution: PromptResolution
    source_span_ids: tuple[str, ...] = ()
    rationale: str | None = None

    @model_validator(mode="after")
    def claim_is_truthful(self) -> Self:
        require_identity(self.claim_id, "claim_id")
        require_identity(self.field_path, "field_path")
        spans = tuple(sorted(self.source_span_ids))
        if len(spans) != len(set(spans)):
            raise ValueError("claim source spans must be unique")
        object.__setattr__(self, "source_span_ids", spans)
        if self.resolution is PromptResolution.EXPLICIT:
            if self.value is None or not spans or self.rationale is not None:
                raise ValueError(
                    "explicit claim requires value/source span and no derived rationale"
                )
        elif self.resolution is PromptResolution.DERIVED:
            if self.value is None or not spans or self.rationale is None:
                raise ValueError(
                    "derived claim requires value, source span, and rationale"
                )
            require_identity(self.rationale, "rationale")
        elif self.resolution is PromptResolution.UNKNOWN:
            if self.value is not None or spans:
                raise ValueError("unknown claim cannot invent a value or source span")
            if self.rationale is None:
                raise ValueError("unknown claim requires a missing-information rationale")
        elif self.value is not None:
            raise ValueError("conflicting claim must not choose a value")
        return self


class AnchorKind(StrEnum):
    EDGE_OFFSET = "edge_offset"
    CENTER = "center"
    SPACING = "spacing"
    TOLERANCE = "tolerance"
    ACCESS = "access"
    APERTURE = "aperture"
    ORIENTATION = "orientation"
    SIDE = "side"


class TypedSpatialAnchor(SemanticIrModel):
    schema_id: Literal["pcbsmith-typed-spatial-anchor"] = (
        "pcbsmith-typed-spatial-anchor"
    )
    schema_version: Literal[1] = 1
    anchor_id: str
    kind: AnchorKind
    subject_ids: tuple[str, ...] = Field(min_length=1)
    reference_id: str
    value_mm: float | None = Field(default=None, ge=0)
    tolerance_mm: float | None = Field(default=None, ge=0)
    edge: Literal["top", "bottom", "left", "right"] | None = None
    axis: Literal["x", "y", "both"] | None = None
    side: Literal["front", "back", "either"] | None = None
    orientation_deg: float | None = None
    source_span_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def anchor_matches_kind(self) -> Self:
        require_identity(self.anchor_id, "anchor_id")
        require_identity(self.reference_id, "reference_id")
        subjects = tuple(sorted(self.subject_ids))
        spans = tuple(sorted(self.source_span_ids))
        if len(subjects) != len(set(subjects)) or len(spans) != len(set(spans)):
            raise ValueError("anchor subjects and source spans must be unique")
        object.__setattr__(self, "subject_ids", subjects)
        object.__setattr__(self, "source_span_ids", spans)
        if self.kind is AnchorKind.EDGE_OFFSET:
            if self.edge is None or self.value_mm is None:
                raise ValueError("edge-offset anchor requires edge and distance")
        elif self.kind in {AnchorKind.CENTER, AnchorKind.SPACING}:
            if self.axis is None:
                raise ValueError("center/spacing anchor requires an axis")
            if self.kind is AnchorKind.SPACING and self.value_mm is None:
                raise ValueError("spacing anchor requires a distance")
        elif self.kind is AnchorKind.TOLERANCE and self.tolerance_mm is None:
            raise ValueError("tolerance anchor requires tolerance_mm")
        elif self.kind is AnchorKind.SIDE and self.side is None:
            raise ValueError("side anchor requires a side")
        elif self.kind is AnchorKind.ORIENTATION and self.orientation_deg is None:
            raise ValueError("orientation anchor requires orientation_deg")
        return self


class ConflictConsequence(SemanticIrModel):
    schema_id: Literal["pcbsmith-prompt-conflict-consequence"] = (
        "pcbsmith-prompt-conflict-consequence"
    )
    schema_version: Literal[1] = 1
    consequence_id: str
    domain: Literal[
        "geometry",
        "electrical",
        "thermal",
        "mechanical",
        "manufacturing",
        "assembly",
        "verification",
    ]
    affected_claim_ids: tuple[str, ...] = Field(min_length=1)
    effect: str

    @model_validator(mode="after")
    def consequence_is_typed(self) -> Self:
        require_identity(self.consequence_id, "consequence_id")
        require_identity(self.effect, "effect")
        claims = tuple(sorted(self.affected_claim_ids))
        if len(claims) != len(set(claims)):
            raise ValueError("consequence claim identities must be unique")
        object.__setattr__(self, "affected_claim_ids", claims)
        return self


class PromptIssue(SemanticIrModel):
    schema_id: Literal["pcbsmith-prompt-issue"] = "pcbsmith-prompt-issue"
    schema_version: Literal[1] = 1
    issue_id: str
    severity: Literal["info", "warning", "error"]
    message: str
    claim_ids: tuple[str, ...] = ()
    hard_conflict: bool = False
    consequences: tuple[ConflictConsequence, ...] = ()
    spirit_preserving_alternatives: tuple[str, ...] = ()

    @model_validator(mode="after")
    def issue_is_actionable(self) -> Self:
        require_identity(self.issue_id, "issue_id")
        require_identity(self.message, "message")
        claims = tuple(sorted(self.claim_ids))
        consequences = tuple(
            sorted(self.consequences, key=lambda item: item.consequence_id)
        )
        alternatives = tuple(self.spirit_preserving_alternatives)
        if len(claims) != len(set(claims)):
            raise ValueError("issue claim identities must be unique")
        if self.hard_conflict:
            if (
                self.severity != "error"
                or not consequences
                or len(alternatives) < 2
            ):
                raise ValueError(
                    "hard conflict requires error severity, typed consequences, "
                    "and at least two alternatives"
                )
            for alternative in alternatives:
                require_identity(alternative, "spirit_preserving_alternative")
        elif alternatives or consequences:
            raise ValueError(
                "only a hard conflict may prescribe consequences or alternatives"
            )
        if any(
            not set(item.affected_claim_ids).issubset(claims)
            for item in consequences
        ):
            raise ValueError("conflict consequence references an unaffected claim")
        object.__setattr__(self, "claim_ids", claims)
        object.__setattr__(self, "consequences", consequences)
        return self


class PromptExamination(SemanticIrModel):
    schema_id: Literal["pcbsmith-prompt-examination"] = "pcbsmith-prompt-examination"
    schema_version: Literal[1] = 1
    project_id: str
    original_text: str = Field(min_length=1)
    original_text_sha256: str
    spans: tuple[SourceSpan, ...]
    claims: tuple[ExaminedClaim, ...]
    anchors: tuple[TypedSpatialAnchor, ...] = ()
    issues: tuple[PromptIssue, ...] = ()
    outcome: Literal["blocked", "needs_decision", "ready_for_concept"]
    examination_fingerprint: str

    @model_validator(mode="after")
    def examination_replays_against_prompt(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_sha256(self.original_text_sha256, "original_text_sha256")
        if fingerprint({"text": self.original_text}) != self.original_text_sha256:
            raise ValueError("original prompt identity is stale")
        spans = tuple(sorted(self.spans, key=lambda item: item.span_id))
        claims = tuple(sorted(self.claims, key=lambda item: item.claim_id))
        anchors = tuple(sorted(self.anchors, key=lambda item: item.anchor_id))
        issues = tuple(sorted(self.issues, key=lambda item: item.issue_id))
        identity_sets = (
            ("span", tuple(item.span_id for item in spans)),
            ("claim", tuple(item.claim_id for item in claims)),
            ("anchor", tuple(item.anchor_id for item in anchors)),
            ("issue", tuple(item.issue_id for item in issues)),
        )
        for name, values in identity_sets:
            if len(values) != len(set(values)):
                raise ValueError(f"{name} identities must be unique")
        span_ids = {item.span_id for item in spans}
        for span in spans:
            if span.end > len(self.original_text):
                raise ValueError("source span exceeds original prompt")
            if self.original_text[span.start : span.end] != span.exact_text:
                raise ValueError("source span does not replay against original prompt")
        if any(not set(item.source_span_ids).issubset(span_ids) for item in claims):
            raise ValueError("claim references an unknown source span")
        if any(not set(item.source_span_ids).issubset(span_ids) for item in anchors):
            raise ValueError("anchor references an unknown source span")
        claim_ids = {item.claim_id for item in claims}
        if any(not set(item.claim_ids).issubset(claim_ids) for item in issues):
            raise ValueError("issue references an unknown claim")
        expected_outcome = (
            "blocked"
            if any(item.hard_conflict for item in issues)
            else (
                "needs_decision"
                if any(
                    item.resolution in {PromptResolution.UNKNOWN, PromptResolution.CONFLICT}
                    for item in claims
                )
                else "ready_for_concept"
            )
        )
        if self.outcome != expected_outcome:
            raise ValueError("prompt examination outcome is not derived from its issues")
        object.__setattr__(self, "spans", spans)
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "anchors", anchors)
        object.__setattr__(self, "issues", issues)
        require_sha256(self.examination_fingerprint, "examination_fingerprint")
        payload = self.model_dump(mode="json", exclude={"examination_fingerprint"})
        if self.examination_fingerprint != fingerprint(payload):
            raise ValueError("prompt examination fingerprint is stale")
        return self


def examine_prompt(
    *,
    project_id: str,
    original_text: str,
    spans: tuple[SourceSpan, ...],
    claims: tuple[ExaminedClaim, ...],
    anchors: tuple[TypedSpatialAnchor, ...] = (),
    issues: tuple[PromptIssue, ...] = (),
) -> PromptExamination:
    outcome: Literal["blocked", "needs_decision", "ready_for_concept"] = (
        "blocked"
        if any(item.hard_conflict for item in issues)
        else (
            "needs_decision"
            if any(
                item.resolution in {PromptResolution.UNKNOWN, PromptResolution.CONFLICT}
                for item in claims
            )
            else "ready_for_concept"
        )
    )
    fields: dict[str, Any] = {
        "project_id": project_id,
        "original_text": original_text,
        "original_text_sha256": fingerprint({"text": original_text}),
        "spans": tuple(sorted(spans, key=lambda item: item.span_id)),
        "claims": tuple(sorted(claims, key=lambda item: item.claim_id)),
        "anchors": tuple(sorted(anchors, key=lambda item: item.anchor_id)),
        "issues": tuple(sorted(issues, key=lambda item: item.issue_id)),
        "outcome": outcome,
    }
    provisional = PromptExamination.model_construct(
        **fields, examination_fingerprint="0" * 64
    )
    return PromptExamination(
        **fields,
        examination_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"examination_fingerprint"})
        ),
    )


class ContextPopulationInput(SemanticIrModel):
    schema_id: Literal["pcbsmith-context-population-input"] = (
        "pcbsmith-context-population-input"
    )
    schema_version: Literal[1] = 1
    category: ProjectContextCategory
    payload_sha256: str | None = None
    source_binding_ids: tuple[str, ...] = ()
    reviewer_record_id: str | None = None
    rationale: str
    unresolved_ids: tuple[str, ...] = ()
    not_applicable: bool = False


def populate_project_context(
    *,
    examination: PromptExamination,
    generation_sha256: str,
    inputs: tuple[ContextPopulationInput, ...],
) -> ProjectContextBundle:
    """Populate all context axes; absent inputs become explicit unresolved records."""

    by_category = {item.category: item for item in inputs}
    if len(by_category) != len(inputs):
        raise ValueError("context population inputs must have unique categories")
    records: list[ProjectContextRecord] = []
    for category in ALL_PROJECT_CONTEXT_CATEGORIES:
        item = by_category.get(category)
        if item is None:
            records.append(
                ProjectContextRecord(
                    category=category,
                    context_id=f"{examination.project_id}.{category.value}",
                    status=ProjectContextStatus.UNRESOLVED,
                    rationale="Prompt examination did not resolve this context.",
                    unresolved_ids=(f"context.missing.{category.value}",),
                )
            )
        elif item.not_applicable:
            records.append(
                ProjectContextRecord(
                    category=category,
                    context_id=f"{examination.project_id}.{category.value}",
                    status=ProjectContextStatus.NOT_APPLICABLE,
                    rationale=item.rationale,
                )
            )
        elif item.unresolved_ids:
            records.append(
                ProjectContextRecord(
                    category=category,
                    context_id=f"{examination.project_id}.{category.value}",
                    status=ProjectContextStatus.UNRESOLVED,
                    payload_sha256=item.payload_sha256,
                    source_binding_ids=item.source_binding_ids,
                    reviewer_record_id=item.reviewer_record_id,
                    rationale=item.rationale,
                    unresolved_ids=item.unresolved_ids,
                )
            )
        else:
            records.append(
                ProjectContextRecord(
                    category=category,
                    context_id=f"{examination.project_id}.{category.value}",
                    status=ProjectContextStatus.RESOLVED,
                    payload_sha256=item.payload_sha256,
                    source_binding_ids=item.source_binding_ids,
                    reviewer_record_id=item.reviewer_record_id,
                    rationale=item.rationale,
                )
            )
    return ProjectContextBundle.build(
        project_id=examination.project_id,
        generation_sha256=generation_sha256,
        records=tuple(records),
    )
