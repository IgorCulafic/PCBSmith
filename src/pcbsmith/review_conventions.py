"""Typed applicability and release semantics for review conventions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class ConventionDomain(StrEnum):
    SCHEMATIC = "schematic"
    PCB = "pcb"


class ConventionClass(StrEnum):
    RELEASE = "release"
    CONDITIONAL_ELECTRICAL_LAYOUT = "conditional_electrical_layout"
    PRESENTATION = "presentation"


class ConventionApplicability(StrEnum):
    ALWAYS = "always"
    BOARD_TRIGGERED = "board_triggered"
    SPACE_CONDITIONAL = "space_conditional"
    HUMAN_DECISION = "human_decision"


class ConventionCheckDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"


class ReviewConvention(SemanticIrModel):
    convention_id: str
    domain: ConventionDomain
    convention_class: ConventionClass
    applicability: ConventionApplicability
    summary: str
    trigger_ids: tuple[str, ...] = ()
    authority_id: str
    source_document_sha256: str
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)

    @model_validator(mode="after")
    def convention_is_exact_and_scoped(self) -> Self:
        for name in ("convention_id", "summary", "authority_id"):
            require_identity(getattr(self, name), name)
        require_sha256(self.source_document_sha256, "source_document_sha256")
        if self.source_end <= self.source_start:
            raise ValueError("review convention source span is empty")
        triggers = tuple(sorted(self.trigger_ids))
        if len(triggers) != len(set(triggers)):
            raise ValueError("review convention trigger IDs must be unique")
        if self.applicability is ConventionApplicability.BOARD_TRIGGERED:
            if not triggers:
                raise ValueError("board-triggered convention requires trigger IDs")
        elif triggers:
            raise ValueError("only board-triggered conventions may declare triggers")
        if (
            self.convention_class is ConventionClass.PRESENTATION
            and self.applicability is ConventionApplicability.ALWAYS
        ):
            raise ValueError("presentation convention cannot be an unconditional release rule")
        object.__setattr__(self, "trigger_ids", triggers)
        return self


class ConventionApplicabilityContext(SemanticIrModel):
    saved_design_sha256: str
    board_trigger_ids: tuple[str, ...] = ()
    space_available: bool | None = None
    approved_human_decision_ids: tuple[str, ...] = ()
    context_fingerprint: str

    @model_validator(mode="after")
    def context_is_replay_bound(self) -> Self:
        require_sha256(self.saved_design_sha256, "saved_design_sha256")
        for name in ("board_trigger_ids", "approved_human_decision_ids"):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            object.__setattr__(self, name, values)
        require_sha256(self.context_fingerprint, "context_fingerprint")
        payload = self.model_dump(mode="json", exclude={"context_fingerprint"})
        if self.context_fingerprint != fingerprint(payload):
            raise ValueError("review convention context fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        saved_design_sha256: str,
        board_trigger_ids: tuple[str, ...] = (),
        space_available: bool | None = None,
        approved_human_decision_ids: tuple[str, ...] = (),
    ) -> ConventionApplicabilityContext:
        fields: dict[str, Any] = {
            "saved_design_sha256": saved_design_sha256,
            "board_trigger_ids": tuple(sorted(board_trigger_ids)),
            "space_available": space_available,
            "approved_human_decision_ids": tuple(sorted(approved_human_decision_ids)),
        }
        provisional = cls.model_construct(**fields, context_fingerprint="0" * 64)
        return cls(
            **fields,
            context_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"context_fingerprint"})
            ),
        )


class ConventionCheckResult(SemanticIrModel):
    convention_id: str
    saved_design_sha256: str
    producer_id: str
    tool_version: str
    disposition: ConventionCheckDisposition
    evaluated_object_count: int = Field(ge=0)
    evidence_sha256: str
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def result_is_retained(self) -> Self:
        for name in ("convention_id", "producer_id", "tool_version"):
            require_identity(getattr(self, name), name)
        require_sha256(self.saved_design_sha256, "saved_design_sha256")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        if (
            self.disposition in {ConventionCheckDisposition.PASS, ConventionCheckDisposition.FAIL}
            and self.evaluated_object_count < 1
        ):
            raise ValueError("executed convention check must evaluate an object")
        return self


class ConventionEvaluation(SemanticIrModel):
    convention_id: str
    applicable: bool | None
    check_disposition: ConventionCheckDisposition
    release_blocker: bool
    rationale: str


class ReviewConventionReport(SemanticIrModel):
    saved_design_sha256: str
    context_fingerprint: str
    evaluations: tuple[ConventionEvaluation, ...]
    ready: bool
    blockers: tuple[str, ...]
    report_fingerprint: str

    @model_validator(mode="after")
    def report_is_replay_bound(self) -> Self:
        require_sha256(self.saved_design_sha256, "saved_design_sha256")
        require_sha256(self.context_fingerprint, "context_fingerprint")
        evaluations = tuple(sorted(self.evaluations, key=lambda item: item.convention_id))
        if len({item.convention_id for item in evaluations}) != len(evaluations):
            raise ValueError("convention evaluations must be unique")
        expected = tuple(
            f"{item.convention_id}: {item.rationale}"
            for item in evaluations
            if item.release_blocker
        )
        if self.blockers != expected or self.ready != (not expected):
            raise ValueError("review convention report disposition is stale")
        object.__setattr__(self, "evaluations", evaluations)
        require_sha256(self.report_fingerprint, "report_fingerprint")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("review convention report fingerprint is stale")
        return self


def evaluate_review_conventions(
    *,
    conventions: tuple[ReviewConvention, ...],
    context: ConventionApplicabilityContext,
    results: tuple[ConventionCheckResult, ...],
) -> ReviewConventionReport:
    """Evaluate conventions without promoting advice into universal blockers."""

    by_result = {item.convention_id: item for item in results}
    if len(by_result) != len(results):
        raise ValueError("convention check results must be unique")
    evaluations: list[ConventionEvaluation] = []
    known_ids = {item.convention_id for item in conventions}
    extra = sorted(set(by_result) - known_ids)
    if extra:
        raise ValueError(f"convention results have no declaration: {extra}")
    for convention in sorted(conventions, key=lambda item: item.convention_id):
        applicable = _resolve_applicability(convention, context)
        result = by_result.get(convention.convention_id)
        if applicable is False:
            disposition = ConventionCheckDisposition.NOT_APPLICABLE
            rationale = "declared applicability conditions are not active"
            blocker = False
            if result is not None and result.disposition is not disposition:
                raise ValueError(
                    f"{convention.convention_id} has conflicting non-applicable result"
                )
        elif applicable is None:
            disposition = ConventionCheckDisposition.UNVERIFIED
            rationale = "applicability authority is unresolved"
            blocker = convention.convention_class is ConventionClass.RELEASE
        elif result is None:
            disposition = ConventionCheckDisposition.UNVERIFIED
            rationale = "applicable convention was not executed"
            blocker = convention.convention_class is ConventionClass.RELEASE
        else:
            if result.saved_design_sha256 != context.saved_design_sha256:
                raise ValueError(f"{convention.convention_id} result targets another design")
            disposition = result.disposition
            rationale = (
                "; ".join(result.findings)
                if result.findings
                else f"check disposition is {result.disposition.value}"
            )
            blocker = (
                convention.convention_class is ConventionClass.RELEASE
                and result.disposition
                in {
                    ConventionCheckDisposition.FAIL,
                    ConventionCheckDisposition.UNVERIFIED,
                }
            )
        evaluations.append(
            ConventionEvaluation(
                convention_id=convention.convention_id,
                applicable=applicable,
                check_disposition=disposition,
                release_blocker=blocker,
                rationale=rationale,
            )
        )
    blockers = tuple(
        f"{item.convention_id}: {item.rationale}" for item in evaluations if item.release_blocker
    )
    fields: dict[str, Any] = {
        "saved_design_sha256": context.saved_design_sha256,
        "context_fingerprint": context.context_fingerprint,
        "evaluations": tuple(evaluations),
        "ready": not blockers,
        "blockers": blockers,
    }
    provisional = ReviewConventionReport.model_construct(**fields, report_fingerprint="0" * 64)
    return ReviewConventionReport(
        **fields,
        report_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"report_fingerprint"})
        ),
    )


def _resolve_applicability(
    convention: ReviewConvention,
    context: ConventionApplicabilityContext,
) -> bool | None:
    if convention.applicability is ConventionApplicability.ALWAYS:
        return True
    if convention.applicability is ConventionApplicability.BOARD_TRIGGERED:
        return bool(set(convention.trigger_ids) & set(context.board_trigger_ids))
    if convention.applicability is ConventionApplicability.SPACE_CONDITIONAL:
        return context.space_available
    return True if convention.authority_id in context.approved_human_decision_ids else None
