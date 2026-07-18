"""Versioned record authority for source-specific antenna RF validation.

The models in this module carry tested conditions and reviewed measurements.
They never create a PCB geometry rule and never mutate layout geometry.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.antenna_enclosure_ir import AntennaEnclosureExclusionResult
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticFinding,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticVerification,
)

MetricComparator = Literal["greater_or_equal", "less_or_equal", "greater", "less", "equal"]
CampaignAvailability = Literal["complete", "incomplete", "unavailable"]


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot canonically serialize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _canonical_decimal(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be a finite exact decimal")
    if value == 0:
        return Decimal(0)
    normalized = value.normalize()
    exponent = normalized.as_tuple().exponent
    return (
        normalized.quantize(Decimal(1))
        if isinstance(exponent, int) and exponent > 0
        else normalized
    )


def _canonical_identities(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    result = tuple(sorted(require_identity(item, field_name) for item in values))
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must contain unique identities")
    return result


class AntennaRfCampaignContext(SemanticIrModel):
    """Every exact design and setup condition that an RF campaign must match."""

    schema_id: Literal["pcbsmith-antenna-rf-campaign-context"] = (
        "pcbsmith-antenna-rf-campaign-context"
    )
    schema_version: Literal[1] = 1
    antenna_id: str = Field(min_length=1)
    module_reference: str = Field(min_length=1)
    selected_footprint_library_id: str = Field(min_length=1)
    component_uuid_path: str = Field(min_length=1)
    component_revision: str = Field(min_length=1)
    module_source_sha256: str
    placement_result_fingerprint: str
    anchor_x_mm: Decimal
    anchor_y_mm: Decimal
    rotation_deg: Decimal
    side: Literal["front", "back"]
    board_layout_snapshot_fingerprint: str
    board_revision: str = Field(min_length=1)
    board_artifact_sha256: str
    enclosure_profile_id: str = Field(min_length=1)
    enclosure_id: str = Field(min_length=1)
    enclosure_revision: str = Field(min_length=1)
    enclosure_model_sha256: str
    firmware_artifact_id: str = Field(min_length=1)
    firmware_version: str = Field(min_length=1)
    firmware_sha256: str
    radio_mode: str = Field(min_length=1)
    band_id: str = Field(min_length=1)
    channel_id: str = Field(min_length=1)
    counterpart_id: str = Field(min_length=1)
    counterpart_revision: str = Field(min_length=1)
    range_id: str = Field(min_length=1)
    range_revision: str = Field(min_length=1)
    setup_id: str = Field(min_length=1)
    setup_artifact_sha256: str
    setup_config_json: str = Field(min_length=2)
    setup_config_sha256: str
    environment_profile_id: str = Field(min_length=1)
    environment_profile_sha256: str

    @model_validator(mode="after")
    def conditions_are_exact_and_canonical(self) -> Self:
        identities = (
            "antenna_id", "module_reference", "selected_footprint_library_id",
            "component_uuid_path", "component_revision", "board_revision",
            "enclosure_profile_id", "enclosure_id", "enclosure_revision",
            "firmware_artifact_id", "firmware_version", "radio_mode", "band_id",
            "channel_id", "counterpart_id", "counterpart_revision", "range_id",
            "range_revision", "setup_id", "environment_profile_id",
        )
        for name in identities:
            require_identity(getattr(self, name), name)
        hashes = (
            "module_source_sha256", "placement_result_fingerprint",
            "board_layout_snapshot_fingerprint", "board_artifact_sha256",
            "enclosure_model_sha256", "firmware_sha256", "setup_artifact_sha256",
            "setup_config_sha256", "environment_profile_sha256",
        )
        for name in hashes:
            require_sha256(getattr(self, name), name)
        for name in ("anchor_x_mm", "anchor_y_mm", "rotation_deg"):
            object.__setattr__(self, name, _canonical_decimal(getattr(self, name), name))
        try:
            config = json.loads(self.setup_config_json)
        except json.JSONDecodeError as error:
            raise ValueError("setup_config_json must contain valid JSON") from error
        canonical = canonical_json(config)
        if canonical != self.setup_config_json:
            raise ValueError("setup_config_json must use canonical JSON serialization")
        if fingerprint(config) != self.setup_config_sha256:
            raise ValueError("setup configuration SHA-256 is stale")
        return self


class AntennaRfMetricRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-rf-metric-requirement"] = (
        "pcbsmith-antenna-rf-metric-requirement"
    )
    schema_version: Literal[1] = 1
    metric_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    comparator: MetricComparator
    target: Decimal

    @model_validator(mode="after")
    def metric_is_exact(self) -> Self:
        require_identity(self.metric_id, "metric_id")
        require_identity(self.unit, "unit")
        object.__setattr__(self, "target", _canonical_decimal(self.target, "target"))
        return self


def rf_requirement_binding_fingerprint(
    *,
    requirement_id: str,
    validation_profile_id: str,
    validation_source_sha256: str,
    context: AntennaRfCampaignContext,
    metrics: Sequence[AntennaRfMetricRequirement],
) -> str:
    return fingerprint(
        {
            "schema_id": "pcbsmith-antenna-rf-requirement-binding-source",
            "schema_version": 1,
            "requirement_id": requirement_id,
            "validation_profile_id": validation_profile_id,
            "validation_source_sha256": validation_source_sha256,
            "context": context.model_dump(mode="json"),
            "metrics": [
                item.model_dump(mode="json")
                for item in sorted(metrics, key=lambda metric: metric.metric_id)
            ],
        }
    )


class AntennaRfCampaignRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-rf-campaign-requirement"] = (
        "pcbsmith-antenna-rf-campaign-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str = Field(min_length=1)
    validation_profile_id: str = Field(min_length=1)
    validation_source_sha256: str
    context: AntennaRfCampaignContext
    metrics: tuple[AntennaRfMetricRequirement, ...] = Field(min_length=1)
    applicability_binding: EvidenceApplicabilityBinding

    @model_validator(mode="after")
    def requirement_is_complete_and_reviewed(self) -> Self:
        require_identity(self.requirement_id, "requirement_id")
        require_identity(self.validation_profile_id, "validation_profile_id")
        require_sha256(self.validation_source_sha256, "validation_source_sha256")
        metrics = tuple(sorted(self.metrics, key=lambda item: item.metric_id))
        if len({item.metric_id for item in metrics}) != len(metrics):
            raise ValueError("RF metric requirement identities must be unique")
        binding = self.applicability_binding
        if (
            not binding.required_conditions
            or binding.unmatched_conditions
            or set(binding.matched_conditions) != set(binding.required_conditions)
            or binding.reviewer_record_id is None
        ):
            raise ValueError("RF requirement applicability must be complete and reviewed")
        expected_fp = rf_requirement_binding_fingerprint(
            requirement_id=self.requirement_id,
            validation_profile_id=self.validation_profile_id,
            validation_source_sha256=self.validation_source_sha256,
            context=self.context,
            metrics=metrics,
        )
        if binding.geometry_source_fingerprint != expected_fp:
            raise ValueError("RF requirement applicability fingerprint is stale")
        if not any(
            item.source_status == "pinned"
            and item.locator_status in {"text_verified", "figure_verified"}
            and item.applicability_status == "confirmed"
            and item.local_sha256 == self.validation_source_sha256
            for item in binding.evidence
        ):
            raise ValueError("RF validation source is not pinned and confirmed")
        object.__setattr__(self, "metrics", metrics)
        return self


class AntennaRfMeasuredMetric(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-rf-measured-metric"] = (
        "pcbsmith-antenna-rf-measured-metric"
    )
    schema_version: Literal[1] = 1
    metric_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    value: Decimal

    @model_validator(mode="after")
    def measurement_is_exact(self) -> Self:
        require_identity(self.metric_id, "metric_id")
        require_identity(self.unit, "unit")
        object.__setattr__(self, "value", _canonical_decimal(self.value, "value"))
        return self


def metric_requirement_passed(
    requirement: AntennaRfMetricRequirement, value: Decimal
) -> bool:
    return {
        "greater_or_equal": value >= requirement.target,
        "less_or_equal": value <= requirement.target,
        "greater": value > requirement.target,
        "less": value < requirement.target,
        "equal": value == requirement.target,
    }[requirement.comparator]


def canonical_rf_raw_result_json(
    record_id: str, measurements: Sequence[AntennaRfMeasuredMetric]
) -> str:
    return canonical_json(
        {
            "schema_id": "pcbsmith-antenna-rf-raw-result-record",
            "schema_version": 1,
            "record_id": record_id,
            "measurements": [
                item.model_dump(mode="json")
                for item in sorted(measurements, key=lambda metric: metric.metric_id)
            ],
        }
    )


class AntennaRfCampaignRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-rf-campaign-record"] = (
        "pcbsmith-antenna-rf-campaign-record"
    )
    schema_version: Literal[1] = 1
    record_id: str = Field(min_length=1)
    availability: CampaignAvailability
    requirement_id: str = Field(min_length=1)
    validation_profile_id: str = Field(min_length=1)
    requirement_fingerprint: str
    context: AntennaRfCampaignContext
    raw_data_artifact_id: str | None
    raw_data_artifact_sha256: str | None
    acquisition_tool: str | None
    acquisition_method: str | None
    acquisition_version: str | None
    raw_result_record_json: str | None
    raw_result_record_sha256: str | None
    measurements: tuple[AntennaRfMeasuredMetric, ...]

    @model_validator(mode="after")
    def record_is_canonical(self) -> Self:
        for name in ("record_id", "requirement_id", "validation_profile_id"):
            require_identity(getattr(self, name), name)
        require_sha256(self.requirement_fingerprint, "requirement_fingerprint")
        measurements = tuple(sorted(self.measurements, key=lambda item: item.metric_id))
        if len({item.metric_id for item in measurements}) != len(measurements):
            raise ValueError("RF measured metric identities must be unique")
        artifact_fields = (
            self.raw_data_artifact_id,
            self.raw_data_artifact_sha256,
            self.acquisition_tool,
            self.acquisition_method,
            self.acquisition_version,
            self.raw_result_record_json,
            self.raw_result_record_sha256,
        )
        if self.availability == "complete" and any(item is None for item in artifact_fields):
            raise ValueError("complete RF campaign record requires all raw-data authority")
        if self.availability == "unavailable" and (measurements or any(artifact_fields)):
            raise ValueError("unavailable RF campaign record cannot claim data or measurements")
        for name in (
            "raw_data_artifact_id", "acquisition_tool", "acquisition_method",
            "acquisition_version",
        ):
            value = getattr(self, name)
            if value is not None:
                require_identity(value, name)
        if self.raw_data_artifact_sha256 is not None:
            require_sha256(self.raw_data_artifact_sha256, "raw_data_artifact_sha256")
        if self.raw_result_record_sha256 is not None:
            require_sha256(self.raw_result_record_sha256, "raw_result_record_sha256")
        if self.raw_result_record_json is not None:
            expected = canonical_rf_raw_result_json(self.record_id, measurements)
            if self.raw_result_record_json != expected:
                raise ValueError(
                    "RF raw result record is noncanonical or differs from measurements"
                )
            if self.raw_result_record_sha256 != fingerprint(json.loads(expected)):
                raise ValueError("RF raw result record SHA-256 is stale")
        elif self.raw_result_record_sha256 is not None:
            raise ValueError("RF raw result hash cannot exist without its canonical record")
        object.__setattr__(self, "measurements", measurements)
        return self


class AntennaRfMetricEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-rf-metric-evidence"] = (
        "pcbsmith-antenna-rf-metric-evidence"
    )
    schema_version: Literal[1] = 1
    requirement: AntennaRfMetricRequirement
    measured: AntennaRfMeasuredMetric | None
    campaign_record_id: str | None
    disposition: SemanticDisposition
    verification: SemanticVerification
    pending_reason: str | None

    @model_validator(mode="after")
    def evidence_is_coherent(self) -> Self:
        if self.verification is not SemanticVerification.EXACT:
            raise ValueError("RF campaign metric evidence is an exact record authority")
        if self.disposition is SemanticDisposition.VALIDATION_PENDING:
            if self.measured is not None or self.campaign_record_id is not None:
                raise ValueError("pending RF metric cannot claim a completed measurement")
            if self.pending_reason is None:
                raise ValueError("pending RF metric requires a reason")
        elif self.disposition in {SemanticDisposition.PASS, SemanticDisposition.FAIL}:
            if self.measured is None or self.campaign_record_id is None:
                raise ValueError("completed RF metric requires its campaign measurement")
            if (
                self.pending_reason is not None
                or self.verification is not SemanticVerification.EXACT
            ):
                raise ValueError("completed RF metric evidence must be exact and non-pending")
            if (
                self.measured.metric_id != self.requirement.metric_id
                or self.measured.unit != self.requirement.unit
            ):
                raise ValueError("completed RF metric evidence is bound to another metric/unit")
            expected = (
                SemanticDisposition.PASS
                if metric_requirement_passed(self.requirement, self.measured.value)
                else SemanticDisposition.FAIL
            )
            if self.disposition is not expected:
                raise ValueError("completed RF metric disposition is stale")
        else:
            raise ValueError("RF metric evidence has an unsupported disposition")
        return self


class AntennaRfValidationResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-rf-validation-result"] = (
        "pcbsmith-antenna-rf-validation-result"
    )
    schema_version: Literal[1] = 1
    authority_statement: Literal[
        "RF campaign records do not create or mutate PCB geometry authority"
    ] = "RF campaign records do not create or mutate PCB geometry authority"
    enclosure_result: AntennaEnclosureExclusionResult
    requirement: AntennaRfCampaignRequirement
    campaign_record: AntennaRfCampaignRecord | None
    geometry_finding: SemanticFinding
    metric_evidence: tuple[AntennaRfMetricEvidence, ...]
    campaign_findings: tuple[SemanticFinding, ...]
    pcb_geometry_before_fingerprint: str
    pcb_geometry_after_fingerprint: str
    evidence_fingerprint: str
    semantic_result: SemanticLayoutResult
    result_fingerprint: str

    @field_validator(
        "pcb_geometry_before_fingerprint", "pcb_geometry_after_fingerprint",
        "evidence_fingerprint", "result_fingerprint",
    )
    @classmethod
    def hashes_are_valid(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.antenna_rf_validation import rederive_antenna_rf_validation

        expected = rederive_antenna_rf_validation(
            self.enclosure_result, self.requirement, self.campaign_record
        )
        compared = (
            "requirement", "campaign_record", "geometry_finding", "metric_evidence",
            "campaign_findings", "pcb_geometry_before_fingerprint",
            "pcb_geometry_after_fingerprint", "evidence_fingerprint", "semantic_result",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("antenna RF validation result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("antenna RF validation result fingerprint is stale")
        return self
