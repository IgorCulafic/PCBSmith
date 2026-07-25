"""Bounded automatic execution for per-component schematic review.

The runner invokes every obligation derived for every IC in one exact
``BoardNetlist``.  A missing response or reviewer exception is retained and
recovered conservatively as ``unverified``; it never disappears as omitted
coverage or becomes an implicit pass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.evidence.component_pin_evidence import ComponentPinEvidence
from pcbsmith.kicad.board import BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_netlist_snapshot_fingerprint,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.routed_copper_graph_ir import (
    fingerprint,
    require_identity,
    require_sha256,
)
from pcbsmith.schematic_review_ir import (
    ComponentReviewManifest,
    ComponentReviewNeighborhood,
    ComponentReviewObligation,
    ComponentReviewResult,
    ReviewApplicability,
    ReviewRunOutcome,
    build_component_review_manifest,
    build_component_review_neighborhood,
    derive_component_review_obligations,
)
from pcbsmith.semantic_ir import SemanticDisposition, SemanticIrModel


class ReviewAttemptStatus(StrEnum):
    DETERMINISTIC = "deterministic"
    SUBMITTED = "submitted"
    NO_SUBMISSION = "no_submission"
    EXCEPTION = "exception"
    INVALID = "invalid"
    CONSERVATIVE_RECOVERY = "conservative_recovery"


class ComponentReviewRequest(SemanticIrModel):
    schema_id: Literal["pcbsmith-component-review-request"] = "pcbsmith-component-review-request"
    schema_version: Literal[1] = 1
    project_id: str
    board_revision: str
    neighborhood: ComponentReviewNeighborhood
    obligation: ComponentReviewObligation
    neighbor_pin_evidence_fingerprints: tuple[tuple[str, str], ...]
    attempt: int = Field(ge=1)
    evidence_query_budget: int = Field(ge=0)

    @model_validator(mode="after")
    def request_is_bounded(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_identity(self.board_revision, "board_revision")
        if self.obligation.component_reference != self.neighborhood.component_reference:
            raise ValueError("component review request mixes component identities")
        allowed_neighbors = set(self.obligation.neighbor_component_references)
        evidence = tuple(
            sorted(
                (
                    require_identity(reference, "neighbor reference"),
                    require_sha256(value, "neighbor evidence fingerprint"),
                )
                for reference, value in self.neighbor_pin_evidence_fingerprints
            )
        )
        if len(evidence) != len({reference for reference, _value in evidence}):
            raise ValueError("neighbor evidence references must be unique")
        if not {reference for reference, _value in evidence}.issubset(allowed_neighbors):
            raise ValueError("review request contains unbounded neighbor evidence")
        object.__setattr__(self, "neighbor_pin_evidence_fingerprints", evidence)
        return self


class ComponentReviewAttemptTrace(SemanticIrModel):
    schema_id: Literal["pcbsmith-component-review-attempt-trace"] = (
        "pcbsmith-component-review-attempt-trace"
    )
    schema_version: Literal[1] = 1
    trace_id: str
    component_reference: str
    obligation_id: str
    attempt: int = Field(ge=0)
    status: ReviewAttemptStatus
    message: str
    evidence_query_count: int = Field(ge=0)
    evidence_query_budget: int = Field(ge=0)
    result_fingerprint: str | None = None
    trace_fingerprint: str

    @model_validator(mode="after")
    def trace_is_replay_bound(self) -> Self:
        for field_name in (
            "trace_id",
            "component_reference",
            "obligation_id",
            "message",
        ):
            require_identity(getattr(self, field_name), field_name)
        if self.evidence_query_count > self.evidence_query_budget:
            raise ValueError("trace evidence queries exceed the declared budget")
        if self.result_fingerprint is not None:
            require_sha256(self.result_fingerprint, "result_fingerprint")
        require_sha256(self.trace_fingerprint, "trace_fingerprint")
        payload = self.model_dump(mode="json", exclude={"trace_fingerprint"})
        if fingerprint(payload) != self.trace_fingerprint:
            raise ValueError("component review trace fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        trace_id: str,
        component_reference: str,
        obligation_id: str,
        attempt: int,
        status: ReviewAttemptStatus,
        message: str,
        evidence_query_count: int,
        evidence_query_budget: int,
        result: ComponentReviewResult | None,
    ) -> ComponentReviewAttemptTrace:
        fields: dict[str, Any] = {
            "trace_id": trace_id,
            "component_reference": component_reference,
            "obligation_id": obligation_id,
            "attempt": attempt,
            "status": status,
            "message": message,
            "evidence_query_count": evidence_query_count,
            "evidence_query_budget": evidence_query_budget,
            "result_fingerprint": (
                None if result is None else fingerprint(result.model_dump(mode="json"))
            ),
        }
        provisional = cls.model_construct(**fields, trace_fingerprint="0" * 64)
        return cls(
            **fields,
            trace_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"trace_fingerprint"})
            ),
        )


class ProjectComponentReviewExecution(SemanticIrModel):
    schema_id: Literal["pcbsmith-project-component-review-execution"] = (
        "pcbsmith-project-component-review-execution"
    )
    schema_version: Literal[1] = 1
    project_id: str
    board_revision: str
    board_netlist_snapshot_json: str
    board_netlist_snapshot_fingerprint: str
    required_component_references: tuple[str, ...]
    missing_pin_evidence_references: tuple[str, ...]
    manifests: tuple[ComponentReviewManifest, ...]
    traces: tuple[ComponentReviewAttemptTrace, ...]
    evidence_query_count: int = Field(ge=0)
    evidence_query_budget: int = Field(ge=0)
    outcome: ReviewRunOutcome
    ready_for_routing: bool
    execution_fingerprint: str

    @model_validator(mode="after")
    def execution_has_exact_coverage(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_identity(self.board_revision, "board_revision")
        require_sha256(
            self.board_netlist_snapshot_fingerprint,
            "board_netlist_snapshot_fingerprint",
        )
        if (
            board_netlist_snapshot_fingerprint(self.board_netlist_snapshot_json)
            != self.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("project component review netlist fingerprint is stale")
        required = _canonical_references(self.required_component_references)
        missing = _canonical_references(self.missing_pin_evidence_references)
        if not set(missing).issubset(required):
            raise ValueError("missing pin-evidence references are not required ICs")
        manifests = tuple(
            sorted(
                self.manifests,
                key=lambda item: item.neighborhood.component_reference,
            )
        )
        manifest_references = tuple(item.neighborhood.component_reference for item in manifests)
        if len(manifest_references) != len(set(manifest_references)):
            raise ValueError("component review manifests must be unique by reference")
        if set(manifest_references) != set(required) - set(missing):
            raise ValueError("component review execution does not cover every evidenced IC")
        for manifest in manifests:
            if (
                manifest.project_id != self.project_id
                or manifest.board_revision != self.board_revision
                or manifest.board_netlist_snapshot_fingerprint
                != self.board_netlist_snapshot_fingerprint
            ):
                raise ValueError("component review manifest belongs to another execution")

        traces = tuple(sorted(self.traces, key=lambda item: item.trace_id))
        trace_by_id = {item.trace_id: item for item in traces}
        if len(trace_by_id) != len(traces):
            raise ValueError("component review trace identities must be unique")
        for manifest in manifests:
            reference = manifest.neighborhood.component_reference
            for trace_id in manifest.trace_ids:
                trace = trace_by_id.get(trace_id)
                if trace is None or trace.component_reference != reference:
                    raise ValueError("component review manifest trace coverage is stale")
        if self.evidence_query_count > self.evidence_query_budget:
            raise ValueError("project component review exceeded its evidence-query budget")
        if self.evidence_query_count != sum(
            item.evidence_query_count
            for item in traces
            if item.status in {ReviewAttemptStatus.SUBMITTED, ReviewAttemptStatus.INVALID}
        ):
            raise ValueError("project evidence-query accounting is stale")

        expected_outcome = _project_outcome(manifests, missing)
        if self.outcome is not expected_outcome:
            raise ValueError("project component review outcome is stale")
        if self.ready_for_routing != (expected_outcome is ReviewRunOutcome.COMPLETE):
            raise ValueError("project component review routing readiness is stale")
        object.__setattr__(self, "required_component_references", required)
        object.__setattr__(self, "missing_pin_evidence_references", missing)
        object.__setattr__(self, "manifests", manifests)
        object.__setattr__(self, "traces", traces)
        require_sha256(self.execution_fingerprint, "execution_fingerprint")
        payload = self.model_dump(mode="json", exclude={"execution_fingerprint"})
        if fingerprint(payload) != self.execution_fingerprint:
            raise ValueError("project component review execution fingerprint is stale")
        return self


ComponentReviewer = Callable[[ComponentReviewRequest], ComponentReviewResult | None]


def execute_project_component_reviews(
    *,
    project_id: str,
    board_revision: str,
    netlist: BoardNetlist,
    pin_evidence_by_reference: Mapping[str, ComponentPinEvidence],
    reviewer: ComponentReviewer,
    max_attempts: int = 2,
    evidence_query_budget_per_obligation: int = 4,
) -> ProjectComponentReviewExecution:
    """Invoke every derived IC obligation with bounded conservative recovery."""

    if max_attempts < 1:
        raise ValueError("component review max_attempts must be positive")
    if evidence_query_budget_per_obligation < 0:
        raise ValueError("component review evidence-query budget cannot be negative")
    required = tuple(
        sorted(
            component.reference
            for component in netlist.components
            if component.reference.upper().startswith("U")
        )
    )
    extras = set(pin_evidence_by_reference) - set(required)
    if extras:
        raise ValueError(
            f"pin evidence was supplied for non-required component references: {sorted(extras)}"
        )
    missing = tuple(
        reference for reference in required if reference not in pin_evidence_by_reference
    )
    snapshot_json = canonical_board_netlist_snapshot_json(netlist)
    snapshot_fingerprint = board_netlist_snapshot_fingerprint(snapshot_json)
    manifests: list[ComponentReviewManifest] = []
    traces: list[ComponentReviewAttemptTrace] = []
    project_query_count = 0
    project_query_budget = 0

    for reference in required:
        pin_evidence = pin_evidence_by_reference.get(reference)
        if pin_evidence is None:
            continue
        neighborhood = build_component_review_neighborhood(
            netlist,
            pin_evidence,
            reference,
        )
        obligations = derive_component_review_obligations(neighborhood)
        results: list[ComponentReviewResult] = []
        manifest_trace_ids: list[str] = []
        for obligation in obligations:
            project_query_budget += evidence_query_budget_per_obligation
            remaining_query_budget = evidence_query_budget_per_obligation
            if obligation.applicability is ReviewApplicability.NOT_APPLICABLE:
                result = ComponentReviewResult(
                    obligation_id=obligation.obligation_id,
                    disposition=SemanticDisposition.NOT_APPLICABLE,
                    rationale=obligation.rationale,
                    evidence_query_count=0,
                    evidence_query_budget=evidence_query_budget_per_obligation,
                )
                trace = ComponentReviewAttemptTrace.build(
                    trace_id=_trace_id(reference, obligation, 0, "deterministic"),
                    component_reference=reference,
                    obligation_id=obligation.obligation_id,
                    attempt=0,
                    status=ReviewAttemptStatus.DETERMINISTIC,
                    message="obligation deterministically not applicable",
                    evidence_query_count=0,
                    evidence_query_budget=evidence_query_budget_per_obligation,
                    result=result,
                )
                traces.append(trace)
                manifest_trace_ids.append(trace.trace_id)
                results.append(result)
                continue

            accepted: ComponentReviewResult | None = None
            for attempt in range(1, max_attempts + 1):
                attempt_query_budget = remaining_query_budget
                request = ComponentReviewRequest(
                    project_id=project_id,
                    board_revision=board_revision,
                    neighborhood=neighborhood,
                    obligation=obligation,
                    neighbor_pin_evidence_fingerprints=tuple(
                        (
                            neighbor,
                            pin_evidence_by_reference[neighbor].semantic_fingerprint(),
                        )
                        for neighbor in obligation.neighbor_component_references
                        if neighbor in pin_evidence_by_reference
                    ),
                    attempt=attempt,
                    evidence_query_budget=attempt_query_budget,
                )
                try:
                    candidate = reviewer(request)
                except Exception as error:
                    trace = ComponentReviewAttemptTrace.build(
                        trace_id=_trace_id(reference, obligation, attempt, "exception"),
                        component_reference=reference,
                        obligation_id=obligation.obligation_id,
                        attempt=attempt,
                        status=ReviewAttemptStatus.EXCEPTION,
                        message=f"{type(error).__name__}: {error}",
                        evidence_query_count=0,
                        evidence_query_budget=attempt_query_budget,
                        result=None,
                    )
                    traces.append(trace)
                    manifest_trace_ids.append(trace.trace_id)
                    continue
                if candidate is None:
                    trace = ComponentReviewAttemptTrace.build(
                        trace_id=_trace_id(reference, obligation, attempt, "no-submission"),
                        component_reference=reference,
                        obligation_id=obligation.obligation_id,
                        attempt=attempt,
                        status=ReviewAttemptStatus.NO_SUBMISSION,
                        message="reviewer returned no submission",
                        evidence_query_count=0,
                        evidence_query_budget=attempt_query_budget,
                        result=None,
                    )
                    traces.append(trace)
                    manifest_trace_ids.append(trace.trace_id)
                    continue
                try:
                    candidate = _normalize_result(
                        candidate,
                        obligation=obligation,
                        evidence_query_budget=attempt_query_budget,
                    )
                except ValueError as error:
                    if candidate.evidence_query_count > attempt_query_budget:
                        raise ValueError(
                            "invalid review submission exceeded its assigned evidence-query budget"
                        ) from error
                    project_query_count += candidate.evidence_query_count
                    remaining_query_budget -= candidate.evidence_query_count
                    trace = ComponentReviewAttemptTrace.build(
                        trace_id=_trace_id(reference, obligation, attempt, "invalid"),
                        component_reference=reference,
                        obligation_id=obligation.obligation_id,
                        attempt=attempt,
                        status=ReviewAttemptStatus.INVALID,
                        message=str(error),
                        evidence_query_count=candidate.evidence_query_count,
                        evidence_query_budget=attempt_query_budget,
                        result=None,
                    )
                    traces.append(trace)
                    manifest_trace_ids.append(trace.trace_id)
                    continue
                accepted = candidate
                project_query_count += candidate.evidence_query_count
                remaining_query_budget -= candidate.evidence_query_count
                trace = ComponentReviewAttemptTrace.build(
                    trace_id=_trace_id(reference, obligation, attempt, "submitted"),
                    component_reference=reference,
                    obligation_id=obligation.obligation_id,
                    attempt=attempt,
                    status=ReviewAttemptStatus.SUBMITTED,
                    message="review result accepted",
                    evidence_query_count=candidate.evidence_query_count,
                    evidence_query_budget=attempt_query_budget,
                    result=candidate,
                )
                traces.append(trace)
                manifest_trace_ids.append(trace.trace_id)
                break

            if accepted is None:
                accepted = ComponentReviewResult(
                    obligation_id=obligation.obligation_id,
                    disposition=SemanticDisposition.UNVERIFIED,
                    rationale=(
                        "No valid review submission was produced within the "
                        "bounded attempt budget; conservative recovery retained."
                    ),
                    evidence_query_count=0,
                    evidence_query_budget=remaining_query_budget,
                )
                trace = ComponentReviewAttemptTrace.build(
                    trace_id=_trace_id(
                        reference,
                        obligation,
                        max_attempts + 1,
                        "recovery",
                    ),
                    component_reference=reference,
                    obligation_id=obligation.obligation_id,
                    attempt=max_attempts + 1,
                    status=ReviewAttemptStatus.CONSERVATIVE_RECOVERY,
                    message="bounded attempts exhausted; recovered as unverified",
                    evidence_query_count=0,
                    evidence_query_budget=remaining_query_budget,
                    result=accepted,
                )
                traces.append(trace)
                manifest_trace_ids.append(trace.trace_id)
            results.append(accepted)

        manifests.append(
            build_component_review_manifest(
                project_id=project_id,
                board_revision=board_revision,
                netlist=netlist,
                neighborhood=neighborhood,
                obligations=obligations,
                results=tuple(results),
                trace_ids=tuple(manifest_trace_ids),
            )
        )

    fields: dict[str, Any] = {
        "project_id": project_id,
        "board_revision": board_revision,
        "board_netlist_snapshot_json": snapshot_json,
        "board_netlist_snapshot_fingerprint": snapshot_fingerprint,
        "required_component_references": required,
        "missing_pin_evidence_references": missing,
        "manifests": tuple(manifests),
        "traces": tuple(traces),
        "evidence_query_count": project_query_count,
        "evidence_query_budget": project_query_budget,
        "outcome": _project_outcome(tuple(manifests), missing),
        "ready_for_routing": (
            not missing
            and all(manifest.outcome is ReviewRunOutcome.COMPLETE for manifest in manifests)
        ),
    }
    provisional = ProjectComponentReviewExecution.model_construct(
        **fields,
        execution_fingerprint="0" * 64,
    )
    return ProjectComponentReviewExecution(
        **fields,
        execution_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"execution_fingerprint"})
        ),
    )


def _normalize_result(
    result: ComponentReviewResult,
    *,
    obligation: ComponentReviewObligation,
    evidence_query_budget: int,
) -> ComponentReviewResult:
    if result.obligation_id != obligation.obligation_id:
        raise ValueError("review result targets another obligation")
    if result.evidence_query_budget != evidence_query_budget:
        raise ValueError("review result changed the assigned evidence-query budget")
    if (
        obligation.applicability is ReviewApplicability.APPLICABLE
        and result.disposition is SemanticDisposition.NOT_APPLICABLE
    ):
        raise ValueError("applicable obligation cannot be returned as not applicable")
    if obligation.applicability is ReviewApplicability.UNRESOLVED and result.disposition not in {
        SemanticDisposition.UNVERIFIED,
        SemanticDisposition.ADVISORY,
    }:
        raise ValueError("unresolved obligation cannot produce a hard verdict")
    evidence_by_fingerprint = {
        fingerprint(item.model_dump(mode="json")): item for item in result.evidence
    }
    return result.model_copy(
        update={
            "evidence": tuple(
                evidence_by_fingerprint[key] for key in sorted(evidence_by_fingerprint)
            )
        }
    )


def _trace_id(
    reference: str,
    obligation: ComponentReviewObligation,
    attempt: int,
    suffix: str,
) -> str:
    return f"component-review-trace:{reference}:{obligation.area.value}:{attempt:02d}:{suffix}"


def _canonical_references(values: tuple[str, ...]) -> tuple[str, ...]:
    references = tuple(sorted(require_identity(item, "component reference") for item in values))
    if len(references) != len(set(references)):
        raise ValueError("component references must be unique")
    return references


def _project_outcome(
    manifests: tuple[ComponentReviewManifest, ...],
    missing: tuple[str, ...],
) -> ReviewRunOutcome:
    if missing or any(manifest.outcome is ReviewRunOutcome.BLOCKED for manifest in manifests):
        return ReviewRunOutcome.BLOCKED
    if any(manifest.outcome is ReviewRunOutcome.UNVERIFIED for manifest in manifests):
        return ReviewRunOutcome.UNVERIFIED
    if any(manifest.outcome is ReviewRunOutcome.REVIEW for manifest in manifests):
        return ReviewRunOutcome.REVIEW
    return ReviewRunOutcome.COMPLETE
