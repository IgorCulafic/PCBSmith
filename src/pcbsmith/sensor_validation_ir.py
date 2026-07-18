"""Replay-bound sensor performance validation authority.

This module is deliberately separate from sensor fabrication, copper-removal,
and bridge geometry authorities.  A campaign may validate only its explicitly
identified project requirement; it never rewrites upstream geometry evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.semantic_ir import (
    SemanticDisposition,
    SemanticFinding,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticQuantity,
)
from pcbsmith.sensor_bridge_ir import SensorBridgeEvaluationResult
from pcbsmith.sensor_copper_removal_ir import CopperRemovalEvaluationResult
from pcbsmith.sensor_isolation_ir import SensorIsolationEvaluationResult


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def canonical_identities(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    result = tuple(sorted(require_identity(item, field_name) for item in values))
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} must contain unique identities")
    return result


class SensorValidationKind(StrEnum):
    THERMAL = "thermal"
    HUMIDITY = "humidity"


class SensorEnclosureRevisionContext(SemanticIrModel):
    """Exact enclosure/environment revision used by a validation campaign."""

    schema_id: Literal["pcbsmith-sensor-enclosure-revision-context"] = (
        "pcbsmith-sensor-enclosure-revision-context"
    )
    schema_version: Literal[1] = 1
    enclosure_profile_id: str = Field(min_length=1)
    enclosure_revision: str = Field(min_length=1)
    enclosure_geometry_fingerprint: str
    ambient_chamber_id: str = Field(min_length=1)
    reference_instrumentation_ids: tuple[str, ...] = Field(min_length=1)
    airflow_state_id: str = Field(min_length=1)
    mounting_orientation_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def context_is_exact(self) -> Self:
        for field_name in (
            "enclosure_profile_id",
            "enclosure_revision",
            "ambient_chamber_id",
            "airflow_state_id",
            "mounting_orientation_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(
            self.enclosure_geometry_fingerprint,
            "enclosure_geometry_fingerprint",
        )
        object.__setattr__(
            self,
            "reference_instrumentation_ids",
            canonical_identities(
                self.reference_instrumentation_ids,
                "reference_instrumentation_ids",
            ),
        )
        return self


class SensorValidationRequirement(SemanticIrModel):
    """Project-owned target; the evaluator supplies no default numeric value."""

    schema_id: Literal["pcbsmith-sensor-validation-requirement"] = (
        "pcbsmith-sensor-validation-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str = Field(min_length=1)
    kind: SensorValidationKind
    target: SemanticQuantity
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def requirement_is_explicit(self) -> Self:
        require_identity(self.requirement_id, "requirement_id")
        target = SemanticQuantity.model_validate_json(self.target.model_dump_json())
        evidence = canonical_identities(self.evidence_binding_ids, "evidence_binding_ids")
        if not set(target.source_binding_ids).issubset(evidence):
            raise ValueError("validation target evidence must be selected by the requirement")
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "evidence_binding_ids", evidence)
        return self


class SensorValidationDeclaration(SemanticIrModel):
    """Opt-in authority binding performance requirements to exact upstream state."""

    schema_id: Literal["pcbsmith-sensor-validation-declaration"] = (
        "pcbsmith-sensor-validation-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str = Field(min_length=1)
    validation_profile_id: str = Field(min_length=1)
    validation_profile_revision: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    sensor_reference: str = Field(min_length=1)
    board_revision: str = Field(min_length=1)
    firmware_state_id: str = Field(min_length=1)
    radio_state_id: str = Field(min_length=1)
    load_state_id: str = Field(min_length=1)
    required_enclosure: SensorEnclosureRevisionContext
    requirements: tuple[SensorValidationRequirement, ...] = Field(min_length=1)
    isolation_result_fingerprint: str
    copper_removal_result_fingerprint: str | None = None
    sensor_bridge_result_fingerprint: str | None = None

    @model_validator(mode="after")
    def declaration_is_bound(self) -> Self:
        for field_name in (
            "declaration_id",
            "validation_profile_id",
            "validation_profile_revision",
            "candidate_id",
            "sensor_reference",
            "board_revision",
            "firmware_state_id",
            "radio_state_id",
            "load_state_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(self.isolation_result_fingerprint, "isolation_result_fingerprint")
        for field_name in (
            "copper_removal_result_fingerprint",
            "sensor_bridge_result_fingerprint",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_sha256(value, field_name)
        if (
            self.sensor_bridge_result_fingerprint is not None
            and self.copper_removal_result_fingerprint is None
        ):
            raise ValueError("bridge validation binding requires copper-removal binding")
        requirements = tuple(
            sorted(
                (
                    SensorValidationRequirement.model_validate_json(item.model_dump_json())
                    for item in self.requirements
                ),
                key=lambda item: item.requirement_id,
            )
        )
        if len({item.requirement_id for item in requirements}) != len(requirements):
            raise ValueError("validation requirement identities must be unique")
        if sum(item.kind is SensorValidationKind.THERMAL for item in requirements) != 1:
            raise ValueError("sensor validation requires exactly one thermal requirement")
        if sum(item.kind is SensorValidationKind.HUMIDITY for item in requirements) > 1:
            raise ValueError("sensor validation permits at most one humidity requirement")
        object.__setattr__(
            self,
            "required_enclosure",
            SensorEnclosureRevisionContext.model_validate_json(
                self.required_enclosure.model_dump_json()
            ),
        )
        object.__setattr__(self, "requirements", requirements)
        return self


class SensorValidationCampaignRecord(SemanticIrModel):
    """Reviewed test record with a canonical checksum over every authority field."""

    schema_id: Literal["pcbsmith-sensor-validation-campaign-record"] = (
        "pcbsmith-sensor-validation-campaign-record"
    )
    schema_version: Literal[1] = 1
    record_id: str = Field(min_length=1)
    validation_profile_id: str = Field(min_length=1)
    validation_profile_revision: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    kind: SensorValidationKind
    board_revision: str = Field(min_length=1)
    enclosure: SensorEnclosureRevisionContext
    firmware_state_id: str = Field(min_length=1)
    radio_state_id: str = Field(min_length=1)
    load_state_id: str = Field(min_length=1)
    stabilization_time_s: float = Field(gt=0)
    sample_count: int = Field(ge=1)
    target: SemanticQuantity
    passed: bool
    raw_data_sha256: str
    test_date: date
    reviewer_record_id: str = Field(min_length=1)
    reviewer_identity: str = Field(min_length=1)
    canonical_record_json: str
    canonical_record_sha256: str

    @classmethod
    def build(
        cls,
        *,
        record_id: str,
        validation_profile_id: str,
        validation_profile_revision: str,
        requirement_id: str,
        kind: SensorValidationKind,
        board_revision: str,
        enclosure: SensorEnclosureRevisionContext,
        firmware_state_id: str,
        radio_state_id: str,
        load_state_id: str,
        stabilization_time_s: float,
        sample_count: int,
        target: SemanticQuantity,
        passed: bool,
        raw_data_sha256: str,
        test_date: date,
        reviewer_record_id: str,
        reviewer_identity: str,
    ) -> Self:
        payload = {
            "record_id": record_id,
            "validation_profile_id": validation_profile_id,
            "validation_profile_revision": validation_profile_revision,
            "requirement_id": requirement_id,
            "kind": kind.value,
            "board_revision": board_revision,
            "enclosure": enclosure.model_dump(mode="json"),
            "firmware_state_id": firmware_state_id,
            "radio_state_id": radio_state_id,
            "load_state_id": load_state_id,
            "stabilization_time_s": stabilization_time_s,
            "sample_count": sample_count,
            "target": target.model_dump(mode="json"),
            "passed": passed,
            "raw_data_sha256": raw_data_sha256,
            "test_date": test_date.isoformat(),
            "reviewer_record_id": reviewer_record_id,
            "reviewer_identity": reviewer_identity,
        }
        record_json = canonical_json(payload)
        return cls(
            **payload,
            canonical_record_json=record_json,
            canonical_record_sha256=hashlib.sha256(record_json.encode("utf-8")).hexdigest(),
        )

    @model_validator(mode="after")
    def campaign_is_complete_and_untampered(self) -> Self:
        for field_name in (
            "record_id",
            "validation_profile_id",
            "validation_profile_revision",
            "requirement_id",
            "board_revision",
            "firmware_state_id",
            "radio_state_id",
            "load_state_id",
            "reviewer_record_id",
            "reviewer_identity",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(self.raw_data_sha256, "raw_data_sha256")
        require_sha256(self.canonical_record_sha256, "canonical_record_sha256")
        if not math.isfinite(self.stabilization_time_s):
            raise ValueError("stabilization_time_s must be finite")
        enclosure = SensorEnclosureRevisionContext.model_validate_json(
            self.enclosure.model_dump_json()
        )
        target = SemanticQuantity.model_validate_json(self.target.model_dump_json())
        payload = self.model_dump(
            mode="json",
            exclude={
                "schema_id",
                "schema_version",
                "canonical_record_json",
                "canonical_record_sha256",
            },
        )
        expected_json = canonical_json(payload)
        expected_sha = hashlib.sha256(expected_json.encode("utf-8")).hexdigest()
        if self.canonical_record_json != expected_json:
            raise ValueError("campaign canonical record differs from its typed fields")
        if self.canonical_record_sha256 != expected_sha:
            raise ValueError("campaign canonical record checksum is stale")
        object.__setattr__(self, "enclosure", enclosure)
        object.__setattr__(self, "target", target)
        return self


class SensorValidationFindingRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-validation-finding-record"] = (
        "pcbsmith-sensor-validation-finding-record"
    )
    schema_version: Literal[1] = 1
    requirement_id: str = Field(min_length=1)
    kind: SensorValidationKind
    matched_campaign_record_id: str | None = None
    disposition: Literal[
        SemanticDisposition.PASS,
        SemanticDisposition.FAIL,
        SemanticDisposition.VALIDATION_PENDING,
    ]
    mismatch_reasons: tuple[str, ...]
    semantic_finding_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def finding_record_is_coherent(self) -> Self:
        require_identity(self.requirement_id, "requirement_id")
        require_identity(self.semantic_finding_id, "semantic_finding_id")
        reasons = canonical_identities(self.mismatch_reasons, "mismatch_reasons")
        if self.disposition is SemanticDisposition.VALIDATION_PENDING:
            if self.matched_campaign_record_id is not None or not reasons:
                raise ValueError("pending validation requires mismatch reasons and no match")
        else:
            if self.matched_campaign_record_id is None or reasons:
                raise ValueError("completed validation requires exactly one matched campaign")
            require_identity(self.matched_campaign_record_id, "matched_campaign_record_id")
        object.__setattr__(self, "mismatch_reasons", reasons)
        return self


class SensorUpstreamIntegrityEvidence(SemanticIrModel):
    """Exact fingerprints proving validation did not replace geometry collections."""

    schema_id: Literal["pcbsmith-sensor-upstream-integrity-evidence"] = (
        "pcbsmith-sensor-upstream-integrity-evidence"
    )
    schema_version: Literal[1] = 1
    isolation_result_fingerprint: str
    isolation_metrics_fingerprint: str
    isolation_findings_fingerprint: str
    copper_removal_result_fingerprint: str | None
    copper_pair_evidence_fingerprint: str | None
    copper_source_evidence_fingerprint: str | None
    copper_findings_fingerprint: str | None
    sensor_bridge_result_fingerprint: str | None
    bridge_track_fingerprint: str | None
    bridge_budget_fingerprint: str | None
    bridge_findings_fingerprint: str | None

    @model_validator(mode="after")
    def hashes_are_complete_per_authority(self) -> Self:
        require_sha256(self.isolation_result_fingerprint, "isolation_result_fingerprint")
        require_sha256(self.isolation_metrics_fingerprint, "isolation_metrics_fingerprint")
        require_sha256(self.isolation_findings_fingerprint, "isolation_findings_fingerprint")
        groups = (
            (
                self.copper_removal_result_fingerprint,
                self.copper_pair_evidence_fingerprint,
                self.copper_source_evidence_fingerprint,
                self.copper_findings_fingerprint,
            ),
            (
                self.sensor_bridge_result_fingerprint,
                self.bridge_track_fingerprint,
                self.bridge_budget_fingerprint,
                self.bridge_findings_fingerprint,
            ),
        )
        for group in groups:
            if any(item is not None for item in group) != all(item is not None for item in group):
                raise ValueError("optional upstream integrity fingerprints must be all-or-none")
            for item in group:
                if item is not None:
                    require_sha256(item, "upstream integrity fingerprint")
        if (
            self.sensor_bridge_result_fingerprint is not None
            and self.copper_removal_result_fingerprint is None
        ):
            raise ValueError("bridge integrity requires copper-removal integrity")
        return self


class SensorValidationEvaluationResult(SemanticIrModel):
    """Replay-derived performance result retaining complete upstream authorities."""

    schema_id: Literal["pcbsmith-sensor-validation-evaluation-result"] = (
        "pcbsmith-sensor-validation-evaluation-result"
    )
    schema_version: Literal[1] = 1
    separation_statement: Literal[
        "performance validation is separate; upstream geometry metrics and findings are retained"
    ] = "performance validation is separate; upstream geometry metrics and findings are retained"
    isolation_result: SensorIsolationEvaluationResult
    copper_removal_result: CopperRemovalEvaluationResult | None = None
    sensor_bridge_result: SensorBridgeEvaluationResult | None = None
    declaration: SensorValidationDeclaration
    enclosure_context: SensorEnclosureRevisionContext | None
    campaigns: tuple[SensorValidationCampaignRecord, ...]
    upstream_integrity: SensorUpstreamIntegrityEvidence
    findings: tuple[SemanticFinding, ...]
    finding_records: tuple[SensorValidationFindingRecord, ...]
    input_fingerprint: str
    semantic_result: SemanticLayoutResult

    @field_validator("input_fingerprint")
    @classmethod
    def input_hash_is_sha256(cls, value: str) -> str:
        return require_sha256(value, "input_fingerprint")

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        from pcbsmith.kicad.sensor_validation import rederive_sensor_validation_result

        expected = rederive_sensor_validation_result(
            isolation_result=self.isolation_result,
            declaration=self.declaration,
            enclosure_context=self.enclosure_context,
            campaigns=self.campaigns,
            copper_removal_result=self.copper_removal_result,
            sensor_bridge_result=self.sensor_bridge_result,
        )
        expected_values: dict[str, Any] = dict(expected)
        compared = (
            "isolation_result",
            "copper_removal_result",
            "sensor_bridge_result",
            "declaration",
            "enclosure_context",
            "campaigns",
            "upstream_integrity",
            "findings",
            "finding_records",
            "input_fingerprint",
            "semantic_result",
        )
        if any(getattr(self, name) != expected_values[name] for name in compared):
            raise ValueError("sensor validation result is stale or not replay-derived")
        for name in compared:
            object.__setattr__(self, name, expected_values[name])
        return self
