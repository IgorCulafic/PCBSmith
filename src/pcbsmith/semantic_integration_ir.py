"""Replay-bound, opt-in R6.6 semantic integration over retained R5 evidence.

This module does not run placement, routing, exact checking, or a semantic
evaluator.  It binds their already-produced immutable records, keeps their
outcomes separate, and derives one comparison key which a caller may choose to
consume.  Existing R5 ranking is therefore unchanged unless this result is
explicitly used.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from enum import StrEnum
from fractions import Fraction
from typing import Any, Literal, Self

from pydantic import Field, StrictInt, model_validator

from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.placement_exact import placement_exact_netlist_fingerprint
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.placement_candidate_ir import PlacementCandidateRecord
from pcbsmith.placement_detail_ir import PlacementCandidateDetailRecord
from pcbsmith.placement_exact_ir import (
    PlacementExactCandidateRecord,
    PlacementExactDisposition,
)
from pcbsmith.placement_ir import PlacementIrModel, PlacementProbeResult
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticLayoutResult,
    SemanticResultOutcome,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_identity(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty canonical identity")
    return value


def _require_sha256(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


class SemanticIntegrationPhase(StrEnum):
    PLACEMENT = "placement"
    ROUTED = "routed"


class SemanticAxisKind(StrEnum):
    THERMAL = "thermal"
    SENSOR_ISOLATION = "sensor_isolation"
    ANTENNA = "antenna"
    DECOUPLING_LOOP = "decoupling_loop"
    OSCILLATOR = "oscillator"
    SWITCHING_HOT_LOOP = "switching_hot_loop"
    CONNECTOR_ZONE = "connector_zone"
    RETURN_PATH = "return_path"
    SIDE_ASSIGNMENT = "side_assignment"
    NEIGHBOR_OVERHANG = "neighbor_overhang"
    OTHER = "other"


ROUTED_ONLY_AXIS_KINDS = frozenset(
    {
        SemanticAxisKind.DECOUPLING_LOOP,
        SemanticAxisKind.SWITCHING_HOT_LOOP,
        SemanticAxisKind.RETURN_PATH,
    }
)


class SemanticAxisEvaluationState(StrEnum):
    EVALUATED = "evaluated"
    DEFERRED_TO_ROUTED = "deferred_to_routed"
    NOT_APPLICABLE = "not_applicable"


class SemanticBlockingOutcome(StrEnum):
    REJECTED = "rejected"
    UNVERIFIED = "unverified"
    PASSED = "passed"
    NOT_APPLICABLE = "not_applicable"


class SemanticAdvisoryOutcome(StrEnum):
    REVIEW = "review"
    UNVERIFIED = "unverified"
    CLEAR = "clear"
    NOT_APPLICABLE = "not_applicable"


class SemanticValidationOutcome(StrEnum):
    FAILED = "failed"
    UNVERIFIED = "unverified"
    PENDING = "pending"
    PASSED = "passed"
    NOT_APPLICABLE = "not_applicable"


class RetainedR2RouteOutcome(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    FAILED = "failed"
    SUCCEEDED_WITH_OVERUSE = "succeeded_with_overuse"
    SUCCEEDED_ZERO_OVERUSE = "succeeded_zero_overuse"


class RetainedExactOutcome(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    NOT_ELIGIBLE = "not_eligible"
    CHECKER_UNAVAILABLE = "checker_unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CHECKER_ERROR = "checker_error"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


class SemanticRankDirection(StrEnum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"


class ExactRankValue(PlacementIrModel):
    """One reduced exact rational comparison-key element."""

    numerator: StrictInt
    denominator: StrictInt = Field(default=1, gt=0)

    @model_validator(mode="after")
    def reduced(self) -> Self:
        if math.gcd(self.numerator, self.denominator) != 1:
            raise ValueError("rank values must be reduced exact rationals")
        if self.numerator == 0 and self.denominator != 1:
            raise ValueError("zero rank values must use denominator one")
        return self

    @classmethod
    def build(cls, value: int | Fraction | ExactRankValue) -> ExactRankValue:
        if isinstance(value, cls):
            return cls.model_validate_json(value.model_dump_json())
        if isinstance(value, bool):
            raise TypeError("rank values cannot be booleans")
        if isinstance(value, Fraction):
            fraction = value
        elif isinstance(value, int):
            fraction = Fraction(value)
        else:
            raise TypeError("rank values must be integers or exact fractions")
        return cls(numerator=fraction.numerator, denominator=fraction.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class SemanticDeclarationBinding(PlacementIrModel):
    """One ordered evaluator declaration/catalog identity."""

    declaration_id: str = Field(min_length=1)
    axis_kind: SemanticAxisKind
    authority: SemanticAuthorityClass
    declaration_fingerprint: str

    @model_validator(mode="after")
    def valid(self) -> Self:
        _require_identity(self.declaration_id, "declaration_id")
        _require_sha256(self.declaration_fingerprint, "declaration_fingerprint")
        return self


class SemanticEvaluatorIdentity(PlacementIrModel):
    evaluator_id: str = Field(min_length=1)
    evaluator_revision: str = Field(min_length=1)
    implementation_fingerprint: str
    phase: SemanticIntegrationPhase

    @model_validator(mode="after")
    def valid(self) -> Self:
        _require_identity(self.evaluator_id, "evaluator_id")
        _require_identity(self.evaluator_revision, "evaluator_revision")
        _require_sha256(self.implementation_fingerprint, "implementation_fingerprint")
        return self


class SemanticAxisEvaluation(PlacementIrModel):
    """One semantic result bound to a declaration, evaluator, and phase snapshot."""

    axis_id: str = Field(min_length=1)
    declaration_id: str = Field(min_length=1)
    declaration_fingerprint: str
    axis_kind: SemanticAxisKind
    authority: SemanticAuthorityClass
    phase: SemanticIntegrationPhase
    state: SemanticAxisEvaluationState
    evaluator: SemanticEvaluatorIdentity
    evaluator_fingerprint: str
    phase_layout_snapshot_fingerprint: str
    phase_netlist_snapshot_fingerprint: str
    context_fingerprint: str
    placement_candidate_fingerprint: str
    semantic_result: SemanticLayoutResult
    semantic_result_fingerprint: str
    evaluation_input_fingerprint: str
    axis_record_fingerprint: str

    @model_validator(mode="after")
    def replay_bound(self) -> Self:
        for name in (
            "declaration_fingerprint",
            "evaluator_fingerprint",
            "phase_layout_snapshot_fingerprint",
            "phase_netlist_snapshot_fingerprint",
            "context_fingerprint",
            "placement_candidate_fingerprint",
            "semantic_result_fingerprint",
            "evaluation_input_fingerprint",
            "axis_record_fingerprint",
        ):
            _require_sha256(getattr(self, name), name)
        _require_identity(self.axis_id, "axis_id")
        _require_identity(self.declaration_id, "declaration_id")
        evaluator = SemanticEvaluatorIdentity.model_validate_json(self.evaluator.model_dump_json())
        result = SemanticLayoutResult.model_validate_json(self.semantic_result.model_dump_json())
        if evaluator.phase is not self.phase:
            raise ValueError("semantic evaluator phase is stale")
        if self.evaluator_fingerprint != evaluator.semantic_fingerprint():
            raise ValueError("semantic evaluator fingerprint is stale")
        if result.context_fingerprint != self.context_fingerprint:
            raise ValueError("semantic result context is stale")
        if result.declarations_fingerprint != self.declaration_fingerprint:
            raise ValueError("semantic result declaration is stale")
        if result.placement_candidate_fingerprint != self.placement_candidate_fingerprint:
            raise ValueError("semantic result candidate is stale")
        if result.geometry_fingerprint != self.phase_layout_snapshot_fingerprint:
            raise ValueError("semantic result geometry differs from its phase snapshot")
        authorities = {finding.authority for finding in result.findings}
        if authorities and authorities != {self.authority}:
            raise ValueError("semantic axis result crosses authority classes")
        inactive = self.state in {
            SemanticAxisEvaluationState.DEFERRED_TO_ROUTED,
            SemanticAxisEvaluationState.NOT_APPLICABLE,
        }
        if inactive and (
            result.outcome is not SemanticResultOutcome.NOT_APPLICABLE
            or result.findings
            or result.metrics
        ):
            raise ValueError("inactive semantic axes require a complete empty result")
        if self.state is SemanticAxisEvaluationState.EVALUATED and (
            result.outcome is SemanticResultOutcome.NOT_APPLICABLE
        ):
            raise ValueError("evaluated semantic axes cannot claim not-applicable")
        if (
            self.phase is SemanticIntegrationPhase.PLACEMENT
            and self.axis_kind in ROUTED_ONLY_AXIS_KINDS
            and self.state is SemanticAxisEvaluationState.EVALUATED
        ):
            raise ValueError("placement cannot claim routed loop or return evaluation")
        expected_input = _fingerprint(
            {
                "schema_id": "pcbsmith-semantic-axis-evaluation-input",
                "schema_version": 1,
                "axis_id": self.axis_id,
                "declaration_id": self.declaration_id,
                "declaration_fingerprint": self.declaration_fingerprint,
                "axis_kind": self.axis_kind,
                "authority": self.authority,
                "phase": self.phase,
                "state": self.state,
                "evaluator_fingerprint": self.evaluator_fingerprint,
                "phase_layout_snapshot_fingerprint": self.phase_layout_snapshot_fingerprint,
                "phase_netlist_snapshot_fingerprint": self.phase_netlist_snapshot_fingerprint,
                "context_fingerprint": self.context_fingerprint,
                "placement_candidate_fingerprint": self.placement_candidate_fingerprint,
            }
        )
        if self.evaluation_input_fingerprint != expected_input:
            raise ValueError("semantic axis evaluation input fingerprint is stale")
        expected_result = result.semantic_fingerprint()
        if self.semantic_result_fingerprint != expected_result:
            raise ValueError("semantic axis result fingerprint is stale")
        expected_record = _fingerprint(
            {
                "evaluation_input_fingerprint": expected_input,
                "semantic_result_fingerprint": expected_result,
            }
        )
        if self.axis_record_fingerprint != expected_record:
            raise ValueError("semantic axis record fingerprint is stale")
        object.__setattr__(self, "evaluator", evaluator)
        object.__setattr__(self, "semantic_result", result)
        return self

    @classmethod
    def build(
        cls,
        *,
        axis_id: str,
        declaration: SemanticDeclarationBinding,
        phase: SemanticIntegrationPhase,
        state: SemanticAxisEvaluationState,
        evaluator: SemanticEvaluatorIdentity,
        phase_layout_snapshot_fingerprint: str,
        phase_netlist_snapshot_fingerprint: str,
        context_fingerprint: str,
        placement_candidate_fingerprint: str,
        semantic_result: SemanticLayoutResult,
    ) -> SemanticAxisEvaluation:
        evaluator_fingerprint = evaluator.semantic_fingerprint()
        inputs = {
            "schema_id": "pcbsmith-semantic-axis-evaluation-input",
            "schema_version": 1,
            "axis_id": axis_id,
            "declaration_id": declaration.declaration_id,
            "declaration_fingerprint": declaration.declaration_fingerprint,
            "axis_kind": declaration.axis_kind,
            "authority": declaration.authority,
            "phase": phase,
            "state": state,
            "evaluator_fingerprint": evaluator_fingerprint,
            "phase_layout_snapshot_fingerprint": phase_layout_snapshot_fingerprint,
            "phase_netlist_snapshot_fingerprint": phase_netlist_snapshot_fingerprint,
            "context_fingerprint": context_fingerprint,
            "placement_candidate_fingerprint": placement_candidate_fingerprint,
        }
        input_fingerprint = _fingerprint(inputs)
        result_fingerprint = semantic_result.semantic_fingerprint()
        return cls(
            axis_id=axis_id,
            declaration_id=declaration.declaration_id,
            declaration_fingerprint=declaration.declaration_fingerprint,
            axis_kind=declaration.axis_kind,
            authority=declaration.authority,
            phase=phase,
            state=state,
            evaluator=evaluator,
            evaluator_fingerprint=evaluator_fingerprint,
            phase_layout_snapshot_fingerprint=phase_layout_snapshot_fingerprint,
            phase_netlist_snapshot_fingerprint=phase_netlist_snapshot_fingerprint,
            context_fingerprint=context_fingerprint,
            placement_candidate_fingerprint=placement_candidate_fingerprint,
            semantic_result=semantic_result,
            semantic_result_fingerprint=result_fingerprint,
            evaluation_input_fingerprint=input_fingerprint,
            axis_record_fingerprint=_fingerprint(
                {
                    "evaluation_input_fingerprint": input_fingerprint,
                    "semantic_result_fingerprint": result_fingerprint,
                }
            ),
        )


class SemanticAdvisoryRankTerm(PlacementIrModel):
    axis_id: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    metric_fingerprint: str
    quantity_unit: str = Field(min_length=1)
    direction: SemanticRankDirection
    value: ExactRankValue

    @model_validator(mode="after")
    def valid(self) -> Self:
        _require_identity(self.axis_id, "axis_id")
        _require_identity(self.metric_id, "metric_id")
        _require_sha256(self.metric_fingerprint, "metric_fingerprint")
        _require_identity(self.quantity_unit, "quantity_unit")
        object.__setattr__(
            self, "value", ExactRankValue.model_validate_json(self.value.model_dump_json())
        )
        return self

    def comparison_value(self) -> ExactRankValue:
        value = self.value.as_fraction()
        if self.direction is SemanticRankDirection.HIGHER_IS_BETTER:
            value = -value
        return ExactRankValue.build(value)


def _blocking_outcome(
    records: Sequence[SemanticAxisEvaluation], authority: SemanticAuthorityClass
) -> SemanticBlockingOutcome:
    dispositions = tuple(
        finding.disposition
        for record in records
        if record.authority is authority
        for finding in record.semantic_result.findings
    )
    if SemanticDisposition.FAIL in dispositions:
        return SemanticBlockingOutcome.REJECTED
    if SemanticDisposition.UNVERIFIED in dispositions:
        return SemanticBlockingOutcome.UNVERIFIED
    if SemanticDisposition.PASS in dispositions:
        return SemanticBlockingOutcome.PASSED
    return SemanticBlockingOutcome.NOT_APPLICABLE


def _advisory_outcome(records: Sequence[SemanticAxisEvaluation]) -> SemanticAdvisoryOutcome:
    dispositions = tuple(
        finding.disposition
        for record in records
        if record.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
        for finding in record.semantic_result.findings
    )
    if SemanticDisposition.UNVERIFIED in dispositions:
        return SemanticAdvisoryOutcome.UNVERIFIED
    if SemanticDisposition.ADVISORY in dispositions:
        return SemanticAdvisoryOutcome.REVIEW
    if dispositions:
        return SemanticAdvisoryOutcome.CLEAR
    return SemanticAdvisoryOutcome.NOT_APPLICABLE


def _validation_outcome(records: Sequence[SemanticAxisEvaluation]) -> SemanticValidationOutcome:
    dispositions = tuple(
        finding.disposition
        for record in records
        if record.authority is SemanticAuthorityClass.VALIDATION_REQUIRED
        for finding in record.semantic_result.findings
    )
    if SemanticDisposition.FAIL in dispositions:
        return SemanticValidationOutcome.FAILED
    if SemanticDisposition.UNVERIFIED in dispositions:
        return SemanticValidationOutcome.UNVERIFIED
    if SemanticDisposition.VALIDATION_PENDING in dispositions:
        return SemanticValidationOutcome.PENDING
    if SemanticDisposition.PASS in dispositions:
        return SemanticValidationOutcome.PASSED
    return SemanticValidationOutcome.NOT_APPLICABLE


def _route_outcome(
    detail: PlacementCandidateDetailRecord | None,
) -> RetainedR2RouteOutcome:
    if detail is None or detail.routing_run is None:
        return RetainedR2RouteOutcome.NOT_EVALUATED
    if not detail.algorithmic_success:
        return RetainedR2RouteOutcome.FAILED
    if not detail.zero_overuse:
        return RetainedR2RouteOutcome.SUCCEEDED_WITH_OVERUSE
    return RetainedR2RouteOutcome.SUCCEEDED_ZERO_OVERUSE


def _exact_outcome(exact: PlacementExactCandidateRecord | None) -> RetainedExactOutcome:
    if exact is None:
        return RetainedExactOutcome.NOT_EVALUATED
    return {
        PlacementExactDisposition.NOT_ELIGIBLE: RetainedExactOutcome.NOT_ELIGIBLE,
        PlacementExactDisposition.CHECKER_UNAVAILABLE: RetainedExactOutcome.CHECKER_UNAVAILABLE,
        PlacementExactDisposition.BUDGET_EXHAUSTED: RetainedExactOutcome.BUDGET_EXHAUSTED,
        PlacementExactDisposition.CHECKER_ERROR: RetainedExactOutcome.CHECKER_ERROR,
        PlacementExactDisposition.EXACT_REJECTED: RetainedExactOutcome.REJECTED,
        PlacementExactDisposition.EXACT_ACCEPTED: RetainedExactOutcome.ACCEPTED,
    }[exact.disposition]


_BLOCKING_RANK = {
    SemanticBlockingOutcome.NOT_APPLICABLE: 0,
    SemanticBlockingOutcome.PASSED: 0,
    SemanticBlockingOutcome.UNVERIFIED: 1,
    SemanticBlockingOutcome.REJECTED: 2,
}
_VALIDATION_RANK = {
    SemanticValidationOutcome.NOT_APPLICABLE: 0,
    SemanticValidationOutcome.PASSED: 0,
    SemanticValidationOutcome.PENDING: 1,
    SemanticValidationOutcome.UNVERIFIED: 2,
    SemanticValidationOutcome.FAILED: 3,
}
_ADVISORY_RANK = {
    SemanticAdvisoryOutcome.NOT_APPLICABLE: 0,
    SemanticAdvisoryOutcome.CLEAR: 0,
    SemanticAdvisoryOutcome.REVIEW: 1,
    SemanticAdvisoryOutcome.UNVERIFIED: 2,
}


class SemanticCandidateIntegration(PlacementIrModel):
    """Complete replay-bound R5/R6 candidate envelope."""

    schema_id: Literal["pcbsmith-semantic-candidate-integration"] = (
        "pcbsmith-semantic-candidate-integration"
    )
    schema_version: Literal[1] = 1
    context_fingerprint: str
    candidate_record: PlacementCandidateRecord
    candidate_record_fingerprint: str
    probe_result: PlacementProbeResult
    probe_result_fingerprint: str
    probe_layout_snapshot_json: str = Field(min_length=2)
    probe_layout_snapshot_fingerprint: str
    probe_layout_fingerprint: str
    netlist_snapshot_json: str = Field(min_length=2)
    netlist_snapshot_fingerprint: str
    netlist_fingerprint: str
    declarations: tuple[SemanticDeclarationBinding, ...]
    ordered_declaration_fingerprints: tuple[str, ...]
    declarations_fingerprint: str
    axis_evaluations: tuple[SemanticAxisEvaluation, ...]
    final_routed_layout_snapshot_json: str | None = None
    final_routed_layout_snapshot_fingerprint: str | None = None
    final_routed_layout_fingerprint: str | None = None
    detail_record: PlacementCandidateDetailRecord | None = None
    detail_record_fingerprint: str | None = None
    exact_record: PlacementExactCandidateRecord | None = None
    exact_record_fingerprint: str | None = None
    existing_r5_rank_key: tuple[ExactRankValue, ...]
    primary_safety_key_length: int = Field(ge=0)
    advisory_rank_terms: tuple[SemanticAdvisoryRankTerm, ...] = ()
    empty_semantic_result: SemanticLayoutResult | None = None
    hard_geometry_outcome: SemanticBlockingOutcome
    qualified_process_outcome: SemanticBlockingOutcome
    advisory_outcome: SemanticAdvisoryOutcome
    validation_outcome: SemanticValidationOutcome
    route_outcome: RetainedR2RouteOutcome
    exact_outcome: RetainedExactOutcome
    semantic_route_acceptance_blocked: bool
    semantic_comparison_key: tuple[ExactRankValue, ...]
    input_fingerprint: str

    @model_validator(mode="after")
    def replay_bound(self) -> Self:
        fingerprint_names = (
            "context_fingerprint",
            "candidate_record_fingerprint",
            "probe_result_fingerprint",
            "probe_layout_snapshot_fingerprint",
            "probe_layout_fingerprint",
            "netlist_snapshot_fingerprint",
            "netlist_fingerprint",
            "declarations_fingerprint",
            "final_routed_layout_snapshot_fingerprint",
            "final_routed_layout_fingerprint",
            "detail_record_fingerprint",
            "exact_record_fingerprint",
            "input_fingerprint",
        )
        for name in fingerprint_names:
            value = getattr(self, name)
            if value is not None:
                _require_sha256(value, name)
        candidate = PlacementCandidateRecord.model_validate_json(
            self.candidate_record.model_dump_json()
        )
        probe = PlacementProbeResult.model_validate_json(self.probe_result.model_dump_json())
        probe_layout = parse_canonical_board_layout_snapshot(self.probe_layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)
        if self.candidate_record_fingerprint != candidate.semantic_fingerprint():
            raise ValueError("candidate record fingerprint is stale")
        if self.probe_result_fingerprint != probe.semantic_fingerprint():
            raise ValueError("probe result fingerprint is stale")
        if candidate.poses != probe.poses:
            raise ValueError("candidate and complete probe poses differ")
        if candidate.probe_layout_fingerprint != probe.telemetry.probe_layout_fingerprint:
            raise ValueError("candidate and complete probe identity differ")
        if self.probe_layout_snapshot_fingerprint != board_layout_snapshot_fingerprint(
            self.probe_layout_snapshot_json
        ):
            raise ValueError("probe layout snapshot fingerprint is stale")
        if self.probe_layout_fingerprint != board_layout_fingerprint(probe_layout):
            raise ValueError("probe layout fingerprint is stale")
        if self.probe_layout_fingerprint != candidate.probe_layout_fingerprint:
            raise ValueError("retained probe layout does not belong to the candidate")
        if self.netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            self.netlist_snapshot_json
        ):
            raise ValueError("netlist snapshot fingerprint is stale")
        if self.netlist_fingerprint != placement_exact_netlist_fingerprint(netlist):
            raise ValueError("R5 netlist fingerprint is stale")

        declarations = tuple(
            SemanticDeclarationBinding.model_validate_json(item.model_dump_json())
            for item in self.declarations
        )
        declaration_ids = tuple(item.declaration_id for item in declarations)
        if len(set(declaration_ids)) != len(declaration_ids):
            raise ValueError("ordered semantic declarations require unique identities")
        ordered_declaration_fingerprints = tuple(
            item.declaration_fingerprint for item in declarations
        )
        if self.ordered_declaration_fingerprints != ordered_declaration_fingerprints:
            raise ValueError("ordered semantic declaration fingerprints are stale")
        expected_declarations_fp = _fingerprint(
            {
                "schema_id": "pcbsmith-semantic-declaration-sequence",
                "schema_version": 1,
                "declarations": [item.model_dump(mode="json") for item in declarations],
            }
        )
        if self.declarations_fingerprint != expected_declarations_fp:
            raise ValueError("ordered semantic declaration fingerprint is stale")

        records = tuple(
            sorted(
                (
                    SemanticAxisEvaluation.model_validate_json(item.model_dump_json())
                    for item in self.axis_evaluations
                ),
                key=lambda item: (
                    item.axis_kind,
                    item.declaration_id,
                    item.phase,
                    item.axis_id,
                    item.evaluator_fingerprint,
                ),
            )
        )
        record_keys = tuple((item.declaration_id, item.phase) for item in records)
        if len(set(record_keys)) != len(record_keys):
            raise ValueError("one declaration may have at most one record per phase")
        axis_ids_by_declaration: dict[str, set[str]] = {}
        for record in records:
            axis_ids_by_declaration.setdefault(record.declaration_id, set()).add(record.axis_id)
        if any(len(axis_ids) != 1 for axis_ids in axis_ids_by_declaration.values()):
            raise ValueError("one declaration must retain one stable semantic axis identity")
        by_declaration = {item.declaration_id: item for item in declarations}
        if {item.declaration_id for item in records} != set(by_declaration):
            raise ValueError("semantic axis records must cover every declaration")
        for record in records:
            declaration = by_declaration[record.declaration_id]
            if (
                record.declaration_fingerprint != declaration.declaration_fingerprint
                or record.axis_kind is not declaration.axis_kind
                or record.authority is not declaration.authority
            ):
                raise ValueError("semantic axis record does not match its declaration")
            if record.context_fingerprint != self.context_fingerprint:
                raise ValueError("semantic axis context differs from the envelope")
            if record.placement_candidate_fingerprint != candidate.candidate_fingerprint:
                raise ValueError("semantic axis candidate differs from the envelope")
            expected_layout_fp = (
                self.probe_layout_snapshot_fingerprint
                if record.phase is SemanticIntegrationPhase.PLACEMENT
                else self.final_routed_layout_snapshot_fingerprint
            )
            if expected_layout_fp is None or record.phase_layout_snapshot_fingerprint != (
                expected_layout_fp
            ):
                raise ValueError("semantic axis is bound to a stale phase layout snapshot")
            if record.phase_netlist_snapshot_fingerprint != self.netlist_snapshot_fingerprint:
                raise ValueError("semantic axis is bound to a stale netlist snapshot")

        final_fields = (
            self.final_routed_layout_snapshot_json,
            self.final_routed_layout_snapshot_fingerprint,
            self.final_routed_layout_fingerprint,
        )
        if any(value is None for value in final_fields) != all(
            value is None for value in final_fields
        ):
            raise ValueError("final routed snapshot and fingerprints are all-or-none")
        final_layout: BoardLayout | None = None
        if self.final_routed_layout_snapshot_json is not None:
            final_layout = parse_canonical_board_layout_snapshot(
                self.final_routed_layout_snapshot_json
            )
            if self.final_routed_layout_snapshot_fingerprint != (
                board_layout_snapshot_fingerprint(self.final_routed_layout_snapshot_json)
            ):
                raise ValueError("final routed snapshot fingerprint is stale")
            if self.final_routed_layout_fingerprint != board_layout_fingerprint(final_layout):
                raise ValueError("final routed layout fingerprint is stale")

        detail = (
            None
            if self.detail_record is None
            else PlacementCandidateDetailRecord.model_validate_json(
                self.detail_record.model_dump_json()
            )
        )
        if (detail is None) != (self.detail_record_fingerprint is None):
            raise ValueError("detail record and fingerprint are all-or-none")
        if detail is not None:
            if detail.candidate_fingerprint != candidate.candidate_fingerprint:
                raise ValueError("detail record belongs to another candidate")
            if self.detail_record_fingerprint != detail.semantic_fingerprint():
                raise ValueError("detail record fingerprint is stale")
            if detail.routing_run is not None:
                if final_layout is None:
                    raise ValueError("R2 detail telemetry requires an explicit final snapshot")
                if detail.materialized_layout_fingerprint != self.final_routed_layout_fingerprint:
                    raise ValueError("final snapshot differs from retained R2 materialization")
            elif final_layout is not None:
                raise ValueError("a final routed snapshot cannot be inferred without R2 telemetry")
        elif final_layout is not None:
            raise ValueError("a final routed snapshot requires retained R2 telemetry")

        exact = (
            None
            if self.exact_record is None
            else PlacementExactCandidateRecord.model_validate_json(
                self.exact_record.model_dump_json()
            )
        )
        if (exact is None) != (self.exact_record_fingerprint is None):
            raise ValueError("exact record and fingerprint are all-or-none")
        if exact is not None:
            if detail is None or exact.detail_record != detail:
                raise ValueError("exact record does not retain the same R2 detail record")
            if exact.candidate_fingerprint != candidate.candidate_fingerprint:
                raise ValueError("exact record belongs to another candidate")
            if self.exact_record_fingerprint != exact.semantic_fingerprint():
                raise ValueError("exact record fingerprint is stale")

        if final_layout is not None:
            routed_declarations = {
                item.declaration_id
                for item in declarations
                if item.axis_kind in ROUTED_ONLY_AXIS_KINDS
            }
            routed_records = {
                item.declaration_id
                for item in records
                if item.phase is SemanticIntegrationPhase.ROUTED
            }
            if not routed_declarations.issubset(routed_records):
                raise ValueError("final routing requires routed semantic records")

        existing_key = tuple(
            ExactRankValue.model_validate_json(item.model_dump_json())
            for item in self.existing_r5_rank_key
        )
        comparison_key = tuple(
            ExactRankValue.model_validate_json(item.model_dump_json())
            for item in self.semantic_comparison_key
        )
        if self.primary_safety_key_length > len(existing_key):
            raise ValueError("primary safety prefix exceeds the supplied R5 rank key")
        terms = tuple(
            sorted(
                (
                    SemanticAdvisoryRankTerm.model_validate_json(item.model_dump_json())
                    for item in self.advisory_rank_terms
                ),
                key=lambda item: (item.axis_id, item.metric_id),
            )
        )
        term_keys = tuple((item.axis_id, item.metric_id) for item in terms)
        if len(set(term_keys)) != len(term_keys):
            raise ValueError("advisory rank terms must be unique")
        records_by_axis: dict[str, list[SemanticAxisEvaluation]] = {}
        for axis_record in records:
            records_by_axis.setdefault(axis_record.axis_id, []).append(axis_record)
        for term in terms:
            rank_records = records_by_axis.get(term.axis_id, [])
            if not rank_records or any(
                rank_record.authority is not SemanticAuthorityClass.ADVISORY_HYPOTHESIS
                for rank_record in rank_records
            ):
                raise ValueError("only advisory semantic axes may supply rank terms")
            matching_metrics = tuple(
                metric
                for rank_record in rank_records
                for metric in rank_record.semantic_result.metrics
                if metric.metric_id == term.metric_id
            )
            if len(matching_metrics) != 1:
                raise ValueError("advisory rank term references an unknown metric")
            metric = matching_metrics[0]
            if metric.quantity is None:
                raise ValueError("unsupported advisory metrics cannot supply rank terms")
            if (
                term.metric_fingerprint != metric.semantic_fingerprint()
                or term.quantity_unit != metric.quantity.unit
                or term.value.as_fraction() != Fraction(str(metric.quantity.value))
            ):
                raise ValueError("advisory rank term does not equal its retained metric")

        hard = _blocking_outcome(records, SemanticAuthorityClass.HARD_GEOMETRY)
        process = _blocking_outcome(records, SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT)
        advisory = _advisory_outcome(records)
        validation = _validation_outcome(records)
        route = _route_outcome(detail)
        exact_outcome = _exact_outcome(exact)
        blocked = hard in {
            SemanticBlockingOutcome.REJECTED,
            SemanticBlockingOutcome.UNVERIFIED,
        } or process in {
            SemanticBlockingOutcome.REJECTED,
            SemanticBlockingOutcome.UNVERIFIED,
        }
        empty = (
            None
            if self.empty_semantic_result is None
            else SemanticLayoutResult.model_validate_json(
                self.empty_semantic_result.model_dump_json()
            )
        )
        if declarations:
            if empty is not None:
                raise ValueError("non-empty declarations cannot retain an empty envelope")
            prefix = existing_key[: self.primary_safety_key_length]
            quality = existing_key[self.primary_safety_key_length :]
            expected_comparison = (
                *prefix,
                ExactRankValue.build(_BLOCKING_RANK[hard]),
                ExactRankValue.build(_BLOCKING_RANK[process]),
                ExactRankValue.build(_VALIDATION_RANK[validation]),
                *quality,
                ExactRankValue.build(_ADVISORY_RANK[advisory]),
                *(item.comparison_value() for item in terms),
            )
        else:
            if records or terms:
                raise ValueError("empty declarations cannot retain semantic records or rank terms")
            if empty is None:
                raise ValueError("empty declarations require a not-applicable semantic result")
            if (
                empty.outcome is not SemanticResultOutcome.NOT_APPLICABLE
                or empty.context_fingerprint != self.context_fingerprint
                or empty.declarations_fingerprint != self.declarations_fingerprint
                or empty.geometry_fingerprint != self.probe_layout_snapshot_fingerprint
                or empty.placement_candidate_fingerprint != candidate.candidate_fingerprint
            ):
                raise ValueError("empty semantic result is stale")
            expected_comparison = existing_key
        if comparison_key != expected_comparison:
            raise ValueError("semantic comparison key is stale")
        expected_outcomes = (
            hard,
            process,
            advisory,
            validation,
            route,
            exact_outcome,
            blocked,
        )
        actual_outcomes = (
            self.hard_geometry_outcome,
            self.qualified_process_outcome,
            self.advisory_outcome,
            self.validation_outcome,
            self.route_outcome,
            self.exact_outcome,
            self.semantic_route_acceptance_blocked,
        )
        if actual_outcomes != expected_outcomes:
            raise ValueError("semantic, route, or exact outcomes are stale")
        expected_input = _fingerprint(
            {
                "schema_id": "pcbsmith-semantic-candidate-integration-input",
                "schema_version": 1,
                "context_fingerprint": self.context_fingerprint,
                "candidate_record_fingerprint": self.candidate_record_fingerprint,
                "probe_result_fingerprint": self.probe_result_fingerprint,
                "probe_layout_snapshot_fingerprint": self.probe_layout_snapshot_fingerprint,
                "probe_layout_fingerprint": self.probe_layout_fingerprint,
                "netlist_snapshot_fingerprint": self.netlist_snapshot_fingerprint,
                "netlist_fingerprint": self.netlist_fingerprint,
                "ordered_declaration_fingerprints": list(self.ordered_declaration_fingerprints),
                "declarations_fingerprint": self.declarations_fingerprint,
                "axis_record_fingerprints": [item.axis_record_fingerprint for item in records],
                "final_routed_layout_snapshot_fingerprint": (
                    self.final_routed_layout_snapshot_fingerprint
                ),
                "final_routed_layout_fingerprint": self.final_routed_layout_fingerprint,
                "detail_record_fingerprint": self.detail_record_fingerprint,
                "exact_record_fingerprint": self.exact_record_fingerprint,
                "existing_r5_rank_key": [item.model_dump(mode="json") for item in existing_key],
                "primary_safety_key_length": self.primary_safety_key_length,
                "advisory_rank_terms": [item.model_dump(mode="json") for item in terms],
            }
        )
        if self.input_fingerprint != expected_input:
            raise ValueError("semantic integration input fingerprint is stale")
        object.__setattr__(self, "candidate_record", candidate)
        object.__setattr__(self, "probe_result", probe)
        object.__setattr__(self, "declarations", declarations)
        object.__setattr__(self, "axis_evaluations", records)
        object.__setattr__(self, "detail_record", detail)
        object.__setattr__(self, "exact_record", exact)
        object.__setattr__(self, "existing_r5_rank_key", existing_key)
        object.__setattr__(self, "advisory_rank_terms", terms)
        object.__setattr__(self, "empty_semantic_result", empty)
        object.__setattr__(self, "semantic_comparison_key", comparison_key)
        return self

    @property
    def probe_layout(self) -> BoardLayout:
        return parse_canonical_board_layout_snapshot(self.probe_layout_snapshot_json)

    @property
    def netlist(self) -> BoardNetlist:
        return parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)

    @property
    def final_routed_layout(self) -> BoardLayout | None:
        if self.final_routed_layout_snapshot_json is None:
            return None
        return parse_canonical_board_layout_snapshot(self.final_routed_layout_snapshot_json)

    def comparison_key(self) -> tuple[Fraction, ...]:
        return tuple(item.as_fraction() for item in self.semantic_comparison_key)

    @classmethod
    def build(
        cls,
        *,
        context_fingerprint: str,
        candidate_record: PlacementCandidateRecord,
        probe_result: PlacementProbeResult,
        probe_layout: BoardLayout,
        netlist: BoardNetlist,
        declarations: Sequence[SemanticDeclarationBinding] = (),
        axis_evaluations: Sequence[SemanticAxisEvaluation] = (),
        final_routed_layout: BoardLayout | None = None,
        detail_record: PlacementCandidateDetailRecord | None = None,
        exact_record: PlacementExactCandidateRecord | None = None,
        existing_r5_rank_key: Sequence[int | Fraction | ExactRankValue] = (),
        primary_safety_key_length: int = 0,
        advisory_rank_terms: Sequence[SemanticAdvisoryRankTerm] = (),
    ) -> SemanticCandidateIntegration:
        declaration_tuple = tuple(declarations)
        ordered_declaration_fingerprints = tuple(
            item.declaration_fingerprint for item in declaration_tuple
        )
        declarations_fingerprint = _fingerprint(
            {
                "schema_id": "pcbsmith-semantic-declaration-sequence",
                "schema_version": 1,
                "declarations": [item.model_dump(mode="json") for item in declaration_tuple],
            }
        )
        records = tuple(
            sorted(
                axis_evaluations,
                key=lambda item: (
                    item.axis_kind,
                    item.declaration_id,
                    item.phase,
                    item.axis_id,
                    item.evaluator_fingerprint,
                ),
            )
        )
        terms = tuple(sorted(advisory_rank_terms, key=lambda item: (item.axis_id, item.metric_id)))
        existing_key = tuple(ExactRankValue.build(item) for item in existing_r5_rank_key)
        probe_json = canonical_board_layout_snapshot_json(probe_layout)
        netlist_json = canonical_board_netlist_snapshot_json(netlist)
        probe_snapshot_fp = board_layout_snapshot_fingerprint(probe_json)
        probe_fp = board_layout_fingerprint(probe_layout)
        netlist_snapshot_fp = board_netlist_snapshot_fingerprint(netlist_json)
        netlist_fp = placement_exact_netlist_fingerprint(netlist)
        final_json = (
            None
            if final_routed_layout is None
            else canonical_board_layout_snapshot_json(final_routed_layout)
        )
        final_snapshot_fp = (
            None if final_json is None else board_layout_snapshot_fingerprint(final_json)
        )
        final_fp = (
            None if final_routed_layout is None else board_layout_fingerprint(final_routed_layout)
        )
        hard = _blocking_outcome(records, SemanticAuthorityClass.HARD_GEOMETRY)
        process = _blocking_outcome(records, SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT)
        advisory = _advisory_outcome(records)
        validation = _validation_outcome(records)
        route = _route_outcome(detail_record)
        exact_outcome = _exact_outcome(exact_record)
        blocked = hard in {
            SemanticBlockingOutcome.REJECTED,
            SemanticBlockingOutcome.UNVERIFIED,
        } or process in {
            SemanticBlockingOutcome.REJECTED,
            SemanticBlockingOutcome.UNVERIFIED,
        }
        empty_result = (
            SemanticLayoutResult.build(
                context_fingerprint=context_fingerprint,
                declarations_fingerprint=declarations_fingerprint,
                geometry_fingerprint=probe_snapshot_fp,
                placement_candidate_fingerprint=candidate_record.candidate_fingerprint,
            )
            if not declaration_tuple
            else None
        )
        if declaration_tuple:
            prefix = existing_key[:primary_safety_key_length]
            quality = existing_key[primary_safety_key_length:]
            comparison_key = (
                *prefix,
                ExactRankValue.build(_BLOCKING_RANK[hard]),
                ExactRankValue.build(_BLOCKING_RANK[process]),
                ExactRankValue.build(_VALIDATION_RANK[validation]),
                *quality,
                ExactRankValue.build(_ADVISORY_RANK[advisory]),
                *(item.comparison_value() for item in terms),
            )
        else:
            comparison_key = existing_key
        candidate_fp = candidate_record.semantic_fingerprint()
        probe_result_fp = probe_result.semantic_fingerprint()
        detail_fp = None if detail_record is None else detail_record.semantic_fingerprint()
        exact_fp = None if exact_record is None else exact_record.semantic_fingerprint()
        inputs = {
            "schema_id": "pcbsmith-semantic-candidate-integration-input",
            "schema_version": 1,
            "context_fingerprint": context_fingerprint,
            "candidate_record_fingerprint": candidate_fp,
            "probe_result_fingerprint": probe_result_fp,
            "probe_layout_snapshot_fingerprint": probe_snapshot_fp,
            "probe_layout_fingerprint": probe_fp,
            "netlist_snapshot_fingerprint": netlist_snapshot_fp,
            "netlist_fingerprint": netlist_fp,
            "ordered_declaration_fingerprints": list(ordered_declaration_fingerprints),
            "declarations_fingerprint": declarations_fingerprint,
            "axis_record_fingerprints": [item.axis_record_fingerprint for item in records],
            "final_routed_layout_snapshot_fingerprint": final_snapshot_fp,
            "final_routed_layout_fingerprint": final_fp,
            "detail_record_fingerprint": detail_fp,
            "exact_record_fingerprint": exact_fp,
            "existing_r5_rank_key": [item.model_dump(mode="json") for item in existing_key],
            "primary_safety_key_length": primary_safety_key_length,
            "advisory_rank_terms": [item.model_dump(mode="json") for item in terms],
        }
        return cls(
            context_fingerprint=context_fingerprint,
            candidate_record=candidate_record,
            candidate_record_fingerprint=candidate_fp,
            probe_result=probe_result,
            probe_result_fingerprint=probe_result_fp,
            probe_layout_snapshot_json=probe_json,
            probe_layout_snapshot_fingerprint=probe_snapshot_fp,
            probe_layout_fingerprint=probe_fp,
            netlist_snapshot_json=netlist_json,
            netlist_snapshot_fingerprint=netlist_snapshot_fp,
            netlist_fingerprint=netlist_fp,
            declarations=declaration_tuple,
            ordered_declaration_fingerprints=ordered_declaration_fingerprints,
            declarations_fingerprint=declarations_fingerprint,
            axis_evaluations=records,
            final_routed_layout_snapshot_json=final_json,
            final_routed_layout_snapshot_fingerprint=final_snapshot_fp,
            final_routed_layout_fingerprint=final_fp,
            detail_record=detail_record,
            detail_record_fingerprint=detail_fp,
            exact_record=exact_record,
            exact_record_fingerprint=exact_fp,
            existing_r5_rank_key=existing_key,
            primary_safety_key_length=primary_safety_key_length,
            advisory_rank_terms=terms,
            empty_semantic_result=empty_result,
            hard_geometry_outcome=hard,
            qualified_process_outcome=process,
            advisory_outcome=advisory,
            validation_outcome=validation,
            route_outcome=route,
            exact_outcome=exact_outcome,
            semantic_route_acceptance_blocked=blocked,
            semantic_comparison_key=comparison_key,
            input_fingerprint=_fingerprint(inputs),
        )
