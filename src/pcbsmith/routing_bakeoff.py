"""Replay-bound same-board comparison and H1 eligibility evidence."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.routing_candidate_transaction import (
    RoutingCandidateTransactionResult,
    RoutingCandidateTransactionStatus,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.routing_ir import (
    PartialCandidateStatus,
    RouteConstraintDisposition,
    RouteFailureKind,
    RouteRequest,
    RouteSegmentGeometry,
    RouteTerminationState,
)
from pcbsmith.semantic_ir import SemanticIrModel


class RoutingBakeoffCase(SemanticIrModel):
    """One immutable board/request variant shared by every engine."""

    schema_id: Literal["pcbsmith-routing-bakeoff-case"] = (
        "pcbsmith-routing-bakeoff-case"
    )
    schema_version: Literal[1] = 1
    case_id: str
    board_variant: str
    board_sha256: str
    request_fingerprint: str
    input_snapshot_fingerprint: str

    @model_validator(mode="after")
    def case_is_pinned(self) -> Self:
        require_identity(self.case_id, "case_id")
        require_identity(self.board_variant, "board_variant")
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.request_fingerprint, "request_fingerprint")
        require_sha256(self.input_snapshot_fingerprint, "input_snapshot_fingerprint")
        return self


class RoutingBakeoffObservation(SemanticIrModel):
    """Normalized measurements for one engine/case/repetition."""

    schema_id: Literal["pcbsmith-routing-bakeoff-observation"] = (
        "pcbsmith-routing-bakeoff-observation"
    )
    schema_version: Literal[1] = 1
    case_id: str
    engine_id: str
    engine_version: str
    repeat_index: int = Field(ge=0)
    transaction_status: RoutingCandidateTransactionStatus
    partial_status: PartialCandidateStatus | None
    termination_state: RouteTerminationState | None
    geometry_fingerprint: str | None
    completed: bool
    unresolved_net_names: tuple[str, ...]
    kicad_violation_count: int | None = Field(default=None, ge=0)
    kicad_unconnected_count: int | None = Field(default=None, ge=0)
    kicad_parity_count: int | None = Field(default=None, ge=0)
    semantic_readback_accepted: bool | None
    protected_object_change_count: int = Field(ge=0)
    added_trace_count: int = Field(ge=0)
    added_via_count: int = Field(ge=0)
    removed_trace_count: int = Field(ge=0)
    removed_via_count: int = Field(ge=0)
    added_routed_length_mm: float = Field(ge=0.0)
    detour_ratio: float | None = Field(default=None, ge=0.0)
    runtime_seconds: float | None = Field(default=None, ge=0.0)
    unsupported_constraint_ids: tuple[str, ...]
    manual_repair_actions: int = Field(ge=0)
    visual_review_finding_ids: tuple[str, ...]
    blocker_kinds: tuple[RouteFailureKind, ...]
    observation_fingerprint: str

    @model_validator(mode="after")
    def observation_is_replay_bound(self) -> Self:
        require_identity(self.case_id, "case_id")
        require_identity(self.engine_id, "engine_id")
        require_identity(self.engine_version, "engine_version")
        if self.geometry_fingerprint is not None:
            require_sha256(self.geometry_fingerprint, "geometry_fingerprint")
        for field_name in (
            "unresolved_net_names",
            "unsupported_constraint_ids",
            "visual_review_finding_ids",
        ):
            values = tuple(sorted(getattr(self, field_name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique values")
            object.__setattr__(self, field_name, values)
        blocker_kinds = tuple(sorted(set(self.blocker_kinds), key=lambda item: item.value))
        object.__setattr__(self, "blocker_kinds", blocker_kinds)
        expected_completed = (
            self.transaction_status is RoutingCandidateTransactionStatus.ACCEPTED
            and self.partial_status is PartialCandidateStatus.COMPLETE
            and self.termination_state is RouteTerminationState.COMPLETED
            and self.kicad_violation_count == 0
            and self.kicad_unconnected_count == 0
            and self.kicad_parity_count == 0
            and self.semantic_readback_accepted is True
            and self.protected_object_change_count == 0
            and not self.unsupported_constraint_ids
            and not self.blocker_kinds
        )
        if self.completed != expected_completed:
            raise ValueError("bakeoff completion disposition is stale")
        require_sha256(self.observation_fingerprint, "observation_fingerprint")
        payload = self.model_dump(mode="json", exclude={"observation_fingerprint"})
        if self.observation_fingerprint != fingerprint(payload):
            raise ValueError("bakeoff observation fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> RoutingBakeoffObservation:
        fields = dict(values)
        for field_name in (
            "unresolved_net_names",
            "unsupported_constraint_ids",
            "visual_review_finding_ids",
        ):
            fields[field_name] = tuple(sorted(fields.get(field_name, ())))
        fields["blocker_kinds"] = tuple(
            sorted(set(fields.get("blocker_kinds", ())), key=lambda item: item.value)
        )
        fields["completed"] = (
            fields["transaction_status"] is RoutingCandidateTransactionStatus.ACCEPTED
            and fields["partial_status"] is PartialCandidateStatus.COMPLETE
            and fields["termination_state"] is RouteTerminationState.COMPLETED
            and fields.get("kicad_violation_count") == 0
            and fields.get("kicad_unconnected_count") == 0
            and fields.get("kicad_parity_count") == 0
            and fields.get("semantic_readback_accepted") is True
            and fields.get("protected_object_change_count", 0) == 0
            and not fields["unsupported_constraint_ids"]
            and not fields["blocker_kinds"]
        )
        provisional = cls.model_construct(**fields, observation_fingerprint="0" * 64)
        return cls(
            **fields,
            observation_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"observation_fingerprint"})
            ),
        )


def _segment_length(segment: RouteSegmentGeometry) -> float:
    return math.hypot(
        segment.end.x_mm - segment.start.x_mm,
        segment.end.y_mm - segment.start.y_mm,
    )


def observe_routing_transaction(
    *,
    case: RoutingBakeoffCase,
    request: RouteRequest,
    transaction: RoutingCandidateTransactionResult,
    repeat_index: int,
    ideal_connection_length_mm: float | None = None,
    manual_repair_actions: int = 0,
    visual_review_finding_ids: tuple[str, ...] = (),
) -> RoutingBakeoffObservation:
    """Normalize one retained transaction without trusting engine-local DRC."""

    if request.semantic_fingerprint() != case.request_fingerprint:
        raise ValueError("bakeoff observation request does not match its case")
    if transaction.request_fingerprint != case.request_fingerprint:
        raise ValueError("bakeoff transaction targets a different request")
    candidate = transaction.candidate
    if candidate is None:
        engine_id = "unavailable"
        engine_version = "unavailable"
        partial_status = None
        termination_state = None
        geometry_fingerprint = None
        added_trace_count = 0
        added_via_count = 0
        removed_trace_count = 0
        removed_via_count = 0
        added_length = 0.0
        runtime = None
        unresolved: set[str] = set()
        unsupported: set[str] = set()
        candidate_failure_kinds: set[RouteFailureKind] = set()
    else:
        engine_id = candidate.engine.engine_id
        engine_version = candidate.engine.engine_version
        partial_status = candidate.partial_status
        termination_state = candidate.termination.state
        geometry_fingerprint = fingerprint(
            {
                "segment_deltas": [
                    item.model_dump(mode="json") for item in candidate.segment_deltas
                ],
                "via_deltas": [
                    item.model_dump(mode="json") for item in candidate.via_deltas
                ],
                "zone_deltas": [
                    item.model_dump(mode="json") for item in candidate.zone_deltas
                ],
            }
        )
        added_trace_count = sum(
            item.operation.value == "add" for item in candidate.segment_deltas
        )
        added_via_count = sum(
            item.operation.value == "add" for item in candidate.via_deltas
        )
        removed_trace_count = sum(
            item.operation.value == "remove" for item in candidate.segment_deltas
        )
        removed_via_count = sum(
            item.operation.value == "remove" for item in candidate.via_deltas
        )
        added_length = sum(
            _segment_length(item.after)
            for item in candidate.segment_deltas
            if item.after is not None and item.operation.value == "add"
        )
        runtime = candidate.termination.elapsed_seconds
        unresolved = {
            net_name for failure in candidate.failures for net_name in failure.net_names
        }
        unsupported = {
            item.constraint_id
            for item in candidate.constraint_consumption
            if item.disposition
            in {
                RouteConstraintDisposition.UNSUPPORTED,
                RouteConstraintDisposition.REJECTED,
            }
        }
        candidate_failure_kinds = {item.kind for item in candidate.failures}
    validation = transaction.validation
    protected_changes = sum(
        failure.kind is RouteFailureKind.PROTECTED_OBJECT_MUTATION
        for failure in transaction.failures
    )
    blocker_kinds = candidate_failure_kinds | {
        item.kind for item in transaction.failures
    }
    detour_ratio = (
        None
        if ideal_connection_length_mm is None or ideal_connection_length_mm <= 0
        else added_length / ideal_connection_length_mm
    )
    return RoutingBakeoffObservation.build(
        case_id=case.case_id,
        engine_id=engine_id,
        engine_version=engine_version,
        repeat_index=repeat_index,
        transaction_status=transaction.status,
        partial_status=partial_status,
        termination_state=termination_state,
        geometry_fingerprint=geometry_fingerprint,
        unresolved_net_names=tuple(unresolved),
        kicad_violation_count=(
            None if validation is None else validation.kicad_drc.violation_count
        ),
        kicad_unconnected_count=(
            None if validation is None else validation.kicad_drc.unconnected_item_count
        ),
        kicad_parity_count=(
            None if validation is None else validation.kicad_drc.schematic_parity_count
        ),
        semantic_readback_accepted=(
            None if validation is None else validation.semantic_readback_accepted
        ),
        protected_object_change_count=protected_changes,
        added_trace_count=added_trace_count,
        added_via_count=added_via_count,
        removed_trace_count=removed_trace_count,
        removed_via_count=removed_via_count,
        added_routed_length_mm=added_length,
        detour_ratio=detour_ratio,
        runtime_seconds=runtime,
        unsupported_constraint_ids=tuple(unsupported),
        manual_repair_actions=manual_repair_actions,
        visual_review_finding_ids=visual_review_finding_ids,
        blocker_kinds=tuple(blocker_kinds),
    )


class EngineH1Eligibility(SemanticIrModel):
    """Derived H1 eligibility, separate from comparative winner selection."""

    schema_id: Literal["pcbsmith-engine-h1-eligibility"] = (
        "pcbsmith-engine-h1-eligibility"
    )
    schema_version: Literal[1] = 1
    engine_id: str
    evaluated_case_ids: tuple[str, ...]
    repeatable_case_ids: tuple[str, ...]
    eligible: bool
    blockers: tuple[str, ...]

    @model_validator(mode="after")
    def eligibility_is_canonical(self) -> Self:
        require_identity(self.engine_id, "engine_id")
        for field_name in ("evaluated_case_ids", "repeatable_case_ids"):
            values = tuple(sorted(getattr(self, field_name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique values")
            object.__setattr__(self, field_name, values)
        if self.eligible != (not self.blockers):
            raise ValueError("H1 eligibility disposition is stale")
        return self


class RoutingBakeoffReport(SemanticIrModel):
    """Exact comparison matrix with evidence-gated recommendation semantics."""

    schema_id: Literal["pcbsmith-routing-engine-bakeoff"] = (
        "pcbsmith-routing-engine-bakeoff"
    )
    schema_version: Literal[1] = 1
    cases: tuple[RoutingBakeoffCase, ...] = Field(min_length=1)
    expected_engine_ids: tuple[str, ...] = Field(min_length=1)
    required_repeats: int = Field(ge=2)
    observations: tuple[RoutingBakeoffObservation, ...]
    matrix_complete: bool
    eligibility: tuple[EngineH1Eligibility, ...]
    recommended_engine_id: str | None
    blockers: tuple[str, ...]
    report_fingerprint: str

    @model_validator(mode="after")
    def report_is_replay_bound(self) -> Self:
        cases = tuple(sorted(self.cases, key=lambda item: item.case_id))
        engines = tuple(sorted(self.expected_engine_ids))
        observations = tuple(
            sorted(
                self.observations,
                key=lambda item: (item.case_id, item.engine_id, item.repeat_index),
            )
        )
        object.__setattr__(self, "cases", cases)
        object.__setattr__(self, "expected_engine_ids", engines)
        object.__setattr__(self, "observations", observations)
        if len({item.case_id for item in cases}) != len(cases):
            raise ValueError("bakeoff case identities must be unique")
        if len(set(engines)) != len(engines):
            raise ValueError("expected bakeoff engine identities must be unique")
        keys = tuple(
            (item.case_id, item.engine_id, item.repeat_index) for item in observations
        )
        if len(keys) != len(set(keys)):
            raise ValueError("bakeoff observation identities must be unique")
        expected_complete = all(
            sum(
                item.case_id == case.case_id and item.engine_id == engine
                for item in observations
            )
            >= self.required_repeats
            for case in cases
            for engine in engines
        )
        if self.matrix_complete != expected_complete:
            raise ValueError("bakeoff matrix completeness is stale")
        if self.recommended_engine_id is not None:
            require_identity(self.recommended_engine_id, "recommended_engine_id")
            distinct_boards = {item.board_sha256 for item in cases}
            eligible = {item.engine_id for item in self.eligibility if item.eligible}
            if not self.matrix_complete or len(distinct_boards) < 2:
                raise ValueError("cannot recommend a routing winner from one board")
            if self.recommended_engine_id not in eligible:
                raise ValueError("recommended routing engine is not H1 eligible")
        require_sha256(self.report_fingerprint, "report_fingerprint")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("routing bakeoff report fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        cases: tuple[RoutingBakeoffCase, ...],
        expected_engine_ids: tuple[str, ...],
        required_repeats: int,
        observations: tuple[RoutingBakeoffObservation, ...],
        recommended_engine_id: str | None = None,
    ) -> RoutingBakeoffReport:
        by_engine_case: dict[
            tuple[str, str],
            list[RoutingBakeoffObservation],
        ] = defaultdict(list)
        for observation in observations:
            by_engine_case[(observation.engine_id, observation.case_id)].append(
                observation
            )
        eligibility: list[EngineH1Eligibility] = []
        for engine_id in sorted(expected_engine_ids):
            evaluated: list[str] = []
            repeatable: list[str] = []
            blockers: list[str] = []
            for case in sorted(cases, key=lambda item: item.case_id):
                runs = by_engine_case[(engine_id, case.case_id)]
                if runs:
                    evaluated.append(case.case_id)
                if len(runs) < required_repeats:
                    blockers.append(
                        f"{case.case_id}: fewer than {required_repeats} retained repeats"
                    )
                    continue
                geometry = {item.geometry_fingerprint for item in runs}
                if None in geometry or len(geometry) != 1:
                    blockers.append(f"{case.case_id}: candidate deltas are not repeatable")
                    continue
                repeatable.append(case.case_id)
                if any(not item.completed for item in runs):
                    blockers.append(
                        f"{case.case_id}: one or more repeats failed independent validation"
                    )
            if not evaluated:
                blockers.append("engine has no retained observations")
            eligibility.append(
                EngineH1Eligibility(
                    engine_id=engine_id,
                    evaluated_case_ids=tuple(evaluated),
                    repeatable_case_ids=tuple(repeatable),
                    eligible=not blockers,
                    blockers=tuple(blockers),
                )
            )
        matrix_complete = all(
            len(by_engine_case[(engine, case.case_id)]) >= required_repeats
            for case in cases
            for engine in expected_engine_ids
        )
        report_blockers: list[str] = []
        if not matrix_complete:
            report_blockers.append("same-board engine matrix is incomplete")
        if len({item.board_sha256 for item in cases}) < 2:
            report_blockers.append("one board cannot support a comparative winner")
        if not any(item.eligible for item in eligibility):
            report_blockers.append("no engine currently satisfies H1 eligibility")
        fields: dict[str, Any] = {
            "cases": tuple(sorted(cases, key=lambda item: item.case_id)),
            "expected_engine_ids": tuple(sorted(expected_engine_ids)),
            "required_repeats": required_repeats,
            "observations": tuple(
                sorted(
                    observations,
                    key=lambda item: (
                        item.case_id,
                        item.engine_id,
                        item.repeat_index,
                    ),
                )
            ),
            "matrix_complete": matrix_complete,
            "eligibility": tuple(eligibility),
            "recommended_engine_id": recommended_engine_id,
            "blockers": tuple(report_blockers),
        }
        provisional = cls.model_construct(**fields, report_fingerprint="0" * 64)
        return cls(
            **fields,
            report_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"report_fingerprint"})
            ),
        )
