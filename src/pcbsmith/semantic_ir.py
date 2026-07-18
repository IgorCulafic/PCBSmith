"""Engine-neutral R6 semantic authority and provenance interchange models.

This module intentionally contains no board evaluator. It defines the frozen,
versioned values later R6 slices consume without conflating exact geometry,
qualified assembly authority, advisory evidence, or product validation state.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.placement_geometry import ExactPlanarCompound


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


def _require_identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _canonical_strings(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    items = tuple(_require_identity(value, field_name) for value in values)
    canonical = tuple(sorted(items))
    if len(set(canonical)) != len(canonical):
        raise ValueError(f"{field_name} must contain unique identities")
    return canonical


def _ordered_strings(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    return tuple(_require_identity(value, field_name) for value in values)


def _canonical_evidence(values: Sequence[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    normalized: list[EvidenceRef] = []
    for item in values:
        payload = item.model_dump()
        payload["required_conditions"] = _canonical_strings(
            item.required_conditions, "evidence required_conditions"
        )
        payload["exclusions"] = _canonical_strings(item.exclusions, "evidence exclusions")
        if item.local_sha256 is not None:
            _require_sha256(item.local_sha256, "evidence local_sha256")
        normalized.append(EvidenceRef.model_validate(payload))
    keyed = tuple(
        sorted(
            ((_canonical_json(item.model_dump(mode="json")), item) for item in normalized),
            key=lambda pair: pair[0],
        )
    )
    if len({key for key, _ in keyed}) != len(keyed):
        raise ValueError("evidence references must be unique")
    return tuple(item for _, item in keyed)


class SemanticIrModel(BaseModel):
    """Frozen extra-forbid value with deterministic complete semantic identity."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    def semantic_json(self) -> str:
        return _canonical_json(self.model_dump(mode="json"))

    def semantic_fingerprint(self) -> str:
        return hashlib.sha256(self.semantic_json().encode("utf-8")).hexdigest()


class SemanticAuthorityClass(StrEnum):
    HARD_GEOMETRY = "hard_geometry"
    QUALIFIED_PROCESS_REQUIREMENT = "qualified_process_requirement"
    ADVISORY_HYPOTHESIS = "advisory_hypothesis"
    VALIDATION_REQUIRED = "validation_required"


class SemanticVerification(StrEnum):
    EXACT = "exact"
    BOUNDED_APPROXIMATION = "bounded_approximation"
    UNSUPPORTED = "unsupported"


class SemanticDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ADVISORY = "advisory"
    UNVERIFIED = "unverified"
    VALIDATION_PENDING = "validation_pending"
    NOT_APPLICABLE = "not_applicable"


class SemanticResultOutcome(StrEnum):
    HARD_REJECTED = "hard_rejected"
    HARD_SCOPE_UNVERIFIED = "hard_scope_unverified"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_PENDING = "validation_pending"
    ADVISORY_REVIEW = "advisory_review"
    PASSED = "passed"
    NOT_APPLICABLE = "not_applicable"


class EvidenceApplicabilityBinding(SemanticIrModel):
    """One claim's evidence plus explicit, machine-visible applicability state."""

    schema_id: Literal["pcbsmith-evidence-applicability-binding"] = (
        "pcbsmith-evidence-applicability-binding"
    )
    schema_version: Literal[1] = 1
    binding_id: str = Field(min_length=1)
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    applicability_record_id: str = Field(min_length=1)
    required_conditions: tuple[str, ...] = ()
    excluded_conditions: tuple[str, ...] = ()
    matched_conditions: tuple[str, ...] = ()
    unmatched_conditions: tuple[str, ...] = ()
    geometry_source_fingerprint: str | None
    reviewer_record_id: str | None

    @model_validator(mode="after")
    def provenance_is_canonical_and_coherent(self) -> Self:
        for field_name in ("binding_id", "claim_id", "applicability_record_id"):
            _require_identity(getattr(self, field_name), field_name)
        required = _canonical_strings(self.required_conditions, "required_conditions")
        excluded = _canonical_strings(self.excluded_conditions, "excluded_conditions")
        matched = _canonical_strings(self.matched_conditions, "matched_conditions")
        unmatched = _canonical_strings(self.unmatched_conditions, "unmatched_conditions")
        if set(required) & set(excluded):
            raise ValueError("required and excluded conditions must be disjoint")
        if set(matched) & set(unmatched):
            raise ValueError("matched and unmatched conditions must be disjoint")
        if set(matched) | set(unmatched) != set(required):
            raise ValueError(
                "matched and unmatched conditions must exactly classify required conditions"
            )
        if self.geometry_source_fingerprint is not None:
            _require_sha256(self.geometry_source_fingerprint, "geometry_source_fingerprint")
        if self.reviewer_record_id is not None:
            _require_identity(self.reviewer_record_id, "reviewer_record_id")
        object.__setattr__(self, "evidence", _canonical_evidence(self.evidence))
        object.__setattr__(self, "required_conditions", required)
        object.__setattr__(self, "excluded_conditions", excluded)
        object.__setattr__(self, "matched_conditions", matched)
        object.__setattr__(self, "unmatched_conditions", unmatched)
        return self


class SemanticRegion(SemanticIrModel):
    """Exact, bounded, or explicitly unsupported semantic planar geometry."""

    schema_id: Literal["pcbsmith-semantic-region"] = "pcbsmith-semantic-region"
    schema_version: Literal[1] = 1
    region_id: str = Field(min_length=1)
    coordinate_space: Literal["board", "component_local"]
    owner_reference: str | None
    compound: ExactPlanarCompound | None
    layers: tuple[str, ...] = Field(min_length=1)
    verification: SemanticVerification
    maximum_error_mm: float | None
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def geometry_metadata_is_coherent(self) -> Self:
        _require_identity(self.region_id, "region_id")
        if self.coordinate_space == "component_local":
            if self.owner_reference is None:
                raise ValueError("component-local semantic regions require an owner_reference")
            _require_identity(self.owner_reference, "owner_reference")
        elif self.owner_reference is not None:
            raise ValueError("board-coordinate semantic regions cannot declare an owner_reference")
        if self.verification is SemanticVerification.EXACT:
            if self.compound is None or self.maximum_error_mm is not None:
                raise ValueError("exact semantic geometry requires a compound and no error bound")
        elif self.verification is SemanticVerification.BOUNDED_APPROXIMATION:
            if (
                self.compound is None
                or self.maximum_error_mm is None
                or not math.isfinite(self.maximum_error_mm)
                or self.maximum_error_mm <= 0
            ):
                raise ValueError(
                    "bounded semantic geometry requires a compound and positive finite error"
                )
        elif self.compound is not None or self.maximum_error_mm is not None:
            raise ValueError(
                "unsupported semantic geometry cannot carry geometry or an error bound"
            )
        object.__setattr__(self, "layers", _canonical_strings(self.layers, "layers"))
        object.__setattr__(
            self,
            "source_binding_ids",
            _canonical_strings(self.source_binding_ids, "source_binding_ids"),
        )
        return self


class SemanticQuantity(SemanticIrModel):
    """Evidence-bound finite physical number; bare untyped floats are invalid."""

    schema_id: Literal["pcbsmith-semantic-quantity"] = "pcbsmith-semantic-quantity"
    schema_version: Literal[1] = 1
    quantity_id: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def number_is_typed_and_bound(self) -> Self:
        _require_identity(self.quantity_id, "quantity_id")
        _require_identity(self.unit, "unit")
        if not math.isfinite(self.value):
            raise ValueError("semantic quantity value must be finite")
        object.__setattr__(
            self,
            "source_binding_ids",
            _canonical_strings(self.source_binding_ids, "source_binding_ids"),
        )
        object.__setattr__(self, "value", 0.0 if self.value == 0.0 else self.value)
        return self


class QualifiedProcessRecord(SemanticIrModel):
    """Assembler-signed process qualification; the only qualified hard authority."""

    schema_id: Literal["pcbsmith-qualified-process-record"] = "pcbsmith-qualified-process-record"
    schema_version: Literal[1] = 1
    record_id: str = Field(min_length=1)
    assembler_id: str = Field(min_length=1)
    process_revision: str = Field(min_length=1)
    qualification_record_id: str = Field(min_length=1)
    qualification_source_sha256: str
    applicability_binding_ids: tuple[str, ...] = Field(min_length=1)
    covered_conditions: tuple[str, ...] = Field(min_length=1)
    ordered_process_steps: tuple[str, ...] = Field(min_length=1)
    restriction_ids: tuple[str, ...] = ()
    effective_date: date
    expiry_date: date | None = None
    reviewer_record_id: str = Field(min_length=1)
    review_identity: str = Field(min_length=1)
    status: Literal["active", "suspended", "expired", "revoked"]

    @model_validator(mode="after")
    def qualification_is_complete(self) -> Self:
        for field_name in (
            "record_id",
            "assembler_id",
            "process_revision",
            "qualification_record_id",
            "reviewer_record_id",
            "review_identity",
        ):
            _require_identity(getattr(self, field_name), field_name)
        _require_sha256(self.qualification_source_sha256, "qualification_source_sha256")
        applicability = _canonical_strings(
            self.applicability_binding_ids, "applicability_binding_ids"
        )
        covered = _canonical_strings(self.covered_conditions, "covered_conditions")
        restrictions = _canonical_strings(self.restriction_ids, "restriction_ids")
        ordered = _ordered_strings(self.ordered_process_steps, "ordered_process_steps")
        if self.expiry_date is not None and self.expiry_date < self.effective_date:
            raise ValueError("qualification expiry_date cannot precede effective_date")
        object.__setattr__(self, "applicability_binding_ids", applicability)
        object.__setattr__(self, "covered_conditions", covered)
        object.__setattr__(self, "ordered_process_steps", ordered)
        object.__setattr__(self, "restriction_ids", restrictions)
        return self


class SemanticRuleDeclaration(SemanticIrModel):
    """Authority-separated rule declaration; authority classes are not aliases."""

    schema_id: Literal["pcbsmith-semantic-rule"] = "pcbsmith-semantic-rule"
    schema_version: Literal[1] = 1
    rule_id: str = Field(min_length=1)
    authority: SemanticAuthorityClass
    object_ids: tuple[str, ...] = ()
    geometry_region_ids: tuple[str, ...] = ()
    ordered_path_ids: tuple[str, ...] = ()
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)
    process_profile_id: str | None = None
    qualified_process_record_id: str | None = None
    validation_requirement_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def authority_contract_is_coherent(self) -> Self:
        _require_identity(self.rule_id, "rule_id")
        objects = _canonical_strings(self.object_ids, "object_ids")
        regions = _canonical_strings(self.geometry_region_ids, "geometry_region_ids")
        ordered = _ordered_strings(self.ordered_path_ids, "ordered_path_ids")
        evidence = _canonical_strings(self.evidence_binding_ids, "evidence_binding_ids")
        validations = _canonical_strings(
            self.validation_requirement_ids, "validation_requirement_ids"
        )
        process_id = self.process_profile_id
        record_id = self.qualified_process_record_id
        if process_id is not None:
            _require_identity(process_id, "process_profile_id")
        if record_id is not None:
            _require_identity(record_id, "qualified_process_record_id")
        if self.authority is SemanticAuthorityClass.HARD_GEOMETRY:
            if not regions or process_id is not None or record_id is not None or validations:
                raise ValueError(
                    "hard-geometry authority requires regions and forbids "
                    "process/validation substitution"
                )
        elif self.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT:
            if process_id is None or record_id is None or regions or validations:
                raise ValueError(
                    "qualified-process authority requires process/profile identity only"
                )
        elif self.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS:
            if record_id is not None or validations:
                raise ValueError(
                    "advisory authority cannot substitute qualification or validation identity"
                )
        elif process_id is not None or record_id is not None or not validations:
            raise ValueError(
                "validation authority requires validation identities and forbids "
                "process substitution"
            )
        object.__setattr__(self, "object_ids", objects)
        object.__setattr__(self, "geometry_region_ids", regions)
        object.__setattr__(self, "ordered_path_ids", ordered)
        object.__setattr__(self, "evidence_binding_ids", evidence)
        object.__setattr__(self, "validation_requirement_ids", validations)
        return self


class SemanticLayoutProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-semantic-layout-profile"] = "pcbsmith-semantic-layout-profile"
    schema_version: Literal[1] = 1
    profile_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    evidence_bindings: tuple[EvidenceApplicabilityBinding, ...] = ()
    regions: tuple[SemanticRegion, ...] = ()
    rules: tuple[SemanticRuleDeclaration, ...] = ()

    @model_validator(mode="after")
    def declarations_are_canonical_and_bound(self) -> Self:
        _require_identity(self.profile_id, "profile_id")
        _require_identity(self.revision, "revision")
        bindings = tuple(
            sorted(
                (
                    EvidenceApplicabilityBinding.model_validate_json(item.model_dump_json())
                    for item in self.evidence_bindings
                ),
                key=lambda item: item.binding_id,
            )
        )
        regions = tuple(
            sorted(
                (
                    SemanticRegion.model_validate_json(item.model_dump_json())
                    for item in self.regions
                ),
                key=lambda item: item.region_id,
            )
        )
        rules = tuple(
            sorted(
                (
                    SemanticRuleDeclaration.model_validate_json(item.model_dump_json())
                    for item in self.rules
                ),
                key=lambda item: item.rule_id,
            )
        )
        binding_ids = tuple(item.binding_id for item in bindings)
        region_ids_ordered = tuple(item.region_id for item in regions)
        rule_ids = tuple(item.rule_id for item in rules)
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("evidence binding identities must be unique")
        if len(set(region_ids_ordered)) != len(region_ids_ordered):
            raise ValueError("semantic region identities must be unique")
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("semantic rule identities must be unique")
        binding_by_id = {item.binding_id: item for item in bindings}
        region_ids = set(region_ids_ordered)
        for region in regions:
            if not set(region.source_binding_ids).issubset(binding_by_id):
                raise ValueError("semantic region references an unknown evidence binding")
            if region.verification is not SemanticVerification.UNSUPPORTED and not any(
                binding_by_id[item].geometry_source_fingerprint is not None
                for item in region.source_binding_ids
            ):
                raise ValueError("supported semantic geometry requires geometry provenance")
        for rule in rules:
            if not set(rule.evidence_binding_ids).issubset(binding_by_id):
                raise ValueError("semantic rule references an unknown evidence binding")
            if not set(rule.geometry_region_ids).issubset(region_ids):
                raise ValueError("semantic rule references an unknown geometry region")
        object.__setattr__(self, "evidence_bindings", bindings)
        object.__setattr__(self, "regions", regions)
        object.__setattr__(self, "rules", rules)
        return self


class AssemblyProcessProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-assembly-process-profile"] = "pcbsmith-assembly-process-profile"
    schema_version: Literal[1] = 1
    profile_id: str = Field(min_length=1)
    assembler_id: str | None
    process_revision: str = Field(min_length=1)
    sequence: Literal[
        "single_reflow",
        "double_reflow",
        "reflow_then_wave",
        "selective",
        "hand_assembly",
        "other",
    ]
    ordered_process_steps: tuple[str, ...] = Field(min_length=1)
    evidence_bindings: tuple[EvidenceApplicabilityBinding, ...] = ()
    qualification_records: tuple[QualifiedProcessRecord, ...] = ()

    @model_validator(mode="after")
    def process_and_qualifications_are_coherent(self) -> Self:
        _require_identity(self.profile_id, "profile_id")
        _require_identity(self.process_revision, "process_revision")
        assembler = self.assembler_id
        if assembler is not None:
            _require_identity(assembler, "assembler_id")
        ordered = _ordered_strings(self.ordered_process_steps, "ordered_process_steps")
        bindings = tuple(
            sorted(
                (
                    EvidenceApplicabilityBinding.model_validate_json(item.model_dump_json())
                    for item in self.evidence_bindings
                ),
                key=lambda item: item.binding_id,
            )
        )
        records = tuple(
            sorted(
                (
                    QualifiedProcessRecord.model_validate_json(item.model_dump_json())
                    for item in self.qualification_records
                ),
                key=lambda item: item.record_id,
            )
        )
        if len({item.binding_id for item in bindings}) != len(bindings):
            raise ValueError("assembly evidence binding identities must be unique")
        if len({item.record_id for item in records}) != len(records):
            raise ValueError("qualification record identities must be unique")
        known_bindings = {item.binding_id for item in bindings}
        for record in records:
            if assembler is None or record.assembler_id != assembler:
                raise ValueError("qualification assembler must match its assembly profile")
            if record.process_revision != self.process_revision:
                raise ValueError("qualification process revision must match its assembly profile")
            if not set(record.applicability_binding_ids).issubset(known_bindings):
                raise ValueError("qualification references an unknown applicability binding")
        object.__setattr__(self, "ordered_process_steps", ordered)
        object.__setattr__(self, "evidence_bindings", bindings)
        object.__setattr__(self, "qualification_records", records)
        return self


class EnclosureEnvironmentProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-enclosure-environment-profile"] = (
        "pcbsmith-enclosure-environment-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    enclosure_geometry_fingerprint: str
    environment_condition_ids: tuple[str, ...] = ()
    evidence_binding_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enclosure_identity_is_canonical(self) -> Self:
        _require_identity(self.profile_id, "profile_id")
        _require_identity(self.revision, "revision")
        _require_sha256(self.enclosure_geometry_fingerprint, "enclosure_geometry_fingerprint")
        object.__setattr__(
            self,
            "environment_condition_ids",
            _canonical_strings(self.environment_condition_ids, "environment_condition_ids"),
        )
        object.__setattr__(
            self,
            "evidence_binding_ids",
            _canonical_strings(self.evidence_binding_ids, "evidence_binding_ids"),
        )
        return self


class ValidationCampaignProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-validation-campaign-profile"] = (
        "pcbsmith-validation-campaign-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    validation_target_ids: tuple[str, ...] = Field(min_length=1)
    campaign_record_fingerprints: tuple[str, ...] = ()
    evidence_binding_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validation_identity_is_canonical(self) -> Self:
        _require_identity(self.profile_id, "profile_id")
        _require_identity(self.revision, "revision")
        targets = _canonical_strings(self.validation_target_ids, "validation_target_ids")
        records = tuple(
            sorted(
                _require_sha256(item, "campaign_record_fingerprints")
                for item in self.campaign_record_fingerprints
            )
        )
        if len(set(records)) != len(records):
            raise ValueError("campaign_record_fingerprints must be unique")
        object.__setattr__(self, "validation_target_ids", targets)
        object.__setattr__(self, "campaign_record_fingerprints", records)
        object.__setattr__(
            self,
            "evidence_binding_ids",
            _canonical_strings(self.evidence_binding_ids, "evidence_binding_ids"),
        )
        return self


class SemanticEvaluationContext(SemanticIrModel):
    schema_id: Literal["pcbsmith-semantic-evaluation-context"] = (
        "pcbsmith-semantic-evaluation-context"
    )
    schema_version: Literal[1] = 1
    pcb_profile_fingerprint: str
    evaluation_date: date
    semantic_profile: SemanticLayoutProfile
    assembly_profile: AssemblyProcessProfile | None
    enclosure_profile: EnclosureEnvironmentProfile | None
    validation_profile: ValidationCampaignProfile | None

    @field_validator("pcb_profile_fingerprint")
    @classmethod
    def pcb_fingerprint_is_sha256(cls, value: str) -> str:
        return _require_sha256(value, "pcb_profile_fingerprint")

    @model_validator(mode="after")
    def cross_profile_authority_is_resolved(self) -> Self:
        object.__setattr__(
            self,
            "semantic_profile",
            SemanticLayoutProfile.model_validate_json(self.semantic_profile.model_dump_json()),
        )
        if self.assembly_profile is not None:
            object.__setattr__(
                self,
                "assembly_profile",
                AssemblyProcessProfile.model_validate_json(self.assembly_profile.model_dump_json()),
            )
        if self.enclosure_profile is not None:
            object.__setattr__(
                self,
                "enclosure_profile",
                EnclosureEnvironmentProfile.model_validate_json(
                    self.enclosure_profile.model_dump_json()
                ),
            )
        if self.validation_profile is not None:
            object.__setattr__(
                self,
                "validation_profile",
                ValidationCampaignProfile.model_validate_json(
                    self.validation_profile.model_dump_json()
                ),
            )
        process_records = (
            {}
            if self.assembly_profile is None
            else {item.record_id: item for item in self.assembly_profile.qualification_records}
        )
        validation_targets = (
            set()
            if self.validation_profile is None
            else set(self.validation_profile.validation_target_ids)
        )
        for rule in self.semantic_profile.rules:
            if rule.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT:
                record_id = rule.qualified_process_record_id
                if (
                    self.assembly_profile is None
                    or rule.process_profile_id != self.assembly_profile.profile_id
                    or record_id is None
                    or record_id not in process_records
                    or process_records[record_id].status != "active"
                    or process_records[record_id].effective_date > self.evaluation_date
                    or (
                        (expiry_date := process_records[record_id].expiry_date) is not None
                        and self.evaluation_date > expiry_date
                    )
                ):
                    raise ValueError(
                        "qualified-process rule requires its active assembly qualification"
                    )
            if rule.authority is SemanticAuthorityClass.VALIDATION_REQUIRED and not set(
                rule.validation_requirement_ids
            ).issubset(validation_targets):
                raise ValueError("validation rule requires matching campaign targets")
        return self


class SemanticFinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-semantic-finding"] = "pcbsmith-semantic-finding"
    schema_version: Literal[1] = 1
    finding_id: str = ""
    rule_id: str = Field(min_length=1)
    authority: SemanticAuthorityClass
    disposition: SemanticDisposition
    verification: SemanticVerification
    object_ids: tuple[str, ...] = ()
    component_refs: tuple[str, ...] = ()
    net_refs: tuple[str, ...] = ()
    region_ids: tuple[str, ...] = ()
    metric_ids: tuple[str, ...] = ()
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)
    process_profile_id: str | None = None
    qualified_process_record_id: str | None = None
    validation_profile_id: str | None = None
    validation_requirement_ids: tuple[str, ...] = ()
    message: str = Field(min_length=1)
    suggested_action: str = Field(min_length=1)

    @model_validator(mode="after")
    def authority_disposition_and_identity_are_truthful(self) -> Self:
        _require_identity(self.rule_id, "rule_id")
        for field_name in (
            "object_ids",
            "component_refs",
            "net_refs",
            "region_ids",
            "metric_ids",
            "evidence_binding_ids",
            "validation_requirement_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _canonical_strings(getattr(self, field_name), field_name),
            )
        if self.verification is SemanticVerification.UNSUPPORTED:
            if self.disposition is not SemanticDisposition.UNVERIFIED:
                raise ValueError("unsupported verification must be unverified")
        else:
            allowed = {
                SemanticAuthorityClass.HARD_GEOMETRY: {
                    SemanticDisposition.PASS,
                    SemanticDisposition.FAIL,
                    SemanticDisposition.UNVERIFIED,
                    SemanticDisposition.NOT_APPLICABLE,
                },
                SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT: {
                    SemanticDisposition.PASS,
                    SemanticDisposition.FAIL,
                    SemanticDisposition.UNVERIFIED,
                    SemanticDisposition.NOT_APPLICABLE,
                },
                SemanticAuthorityClass.ADVISORY_HYPOTHESIS: {
                    SemanticDisposition.ADVISORY,
                    SemanticDisposition.UNVERIFIED,
                    SemanticDisposition.NOT_APPLICABLE,
                },
                SemanticAuthorityClass.VALIDATION_REQUIRED: {
                    SemanticDisposition.PASS,
                    SemanticDisposition.FAIL,
                    SemanticDisposition.VALIDATION_PENDING,
                    SemanticDisposition.UNVERIFIED,
                    SemanticDisposition.NOT_APPLICABLE,
                },
            }[self.authority]
            if self.disposition not in allowed:
                raise ValueError("finding disposition is incompatible with its authority")
        if self.authority is SemanticAuthorityClass.HARD_GEOMETRY and not self.region_ids:
            raise ValueError("hard-geometry findings require region identity")
        if self.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT:
            if self.process_profile_id is None or self.qualified_process_record_id is None:
                raise ValueError("qualified-process findings require process identity")
        if self.authority is SemanticAuthorityClass.VALIDATION_REQUIRED:
            if not self.validation_requirement_ids:
                raise ValueError("validation findings require validation requirement identity")
            if (
                self.disposition in {SemanticDisposition.PASS, SemanticDisposition.FAIL}
                and self.validation_profile_id is None
            ):
                raise ValueError(
                    "completed validation findings require validation profile identity"
                )
        for field_name in (
            "process_profile_id",
            "qualified_process_record_id",
            "validation_profile_id",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_identity(value, field_name)
        _require_identity(self.message, "message")
        _require_identity(self.suggested_action, "suggested_action")
        identity_payload = self.model_dump(
            mode="json", exclude={"finding_id", "message", "suggested_action"}
        )
        expected_id = f"semantic:{_fingerprint(identity_payload)}"
        if self.finding_id and self.finding_id != expected_id:
            raise ValueError("finding_id does not match semantic finding identity")
        object.__setattr__(self, "finding_id", expected_id)
        return self


class SemanticMetric(SemanticIrModel):
    schema_id: Literal["pcbsmith-semantic-metric"] = "pcbsmith-semantic-metric"
    schema_version: Literal[1] = 1
    metric_id: str = Field(min_length=1)
    verification: SemanticVerification
    quantity: SemanticQuantity | None
    object_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def metric_is_coherent(self) -> Self:
        _require_identity(self.metric_id, "metric_id")
        quantity = (
            None
            if self.quantity is None
            else SemanticQuantity.model_validate_json(self.quantity.model_dump_json())
        )
        if (self.verification is SemanticVerification.UNSUPPORTED) != (quantity is None):
            raise ValueError("unsupported metrics have no quantity; supported metrics require one")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "object_ids", _canonical_strings(self.object_ids, "object_ids"))
        return self


class SemanticResultSummary(SemanticIrModel):
    finding_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    hard_failure_count: int = Field(ge=0)
    qualified_process_failure_count: int = Field(ge=0)
    hard_scope_unverified_count: int = Field(ge=0)
    validation_failure_count: int = Field(ge=0)
    advisory_count: int = Field(ge=0)
    other_unverified_count: int = Field(ge=0)
    validation_pending_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    route_acceptance_blocked: bool

    @classmethod
    def from_findings(cls, findings: Sequence[SemanticFinding]) -> Self:
        hard_authorities = {
            SemanticAuthorityClass.HARD_GEOMETRY,
            SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
        }
        hard_failures = sum(
            item.authority is SemanticAuthorityClass.HARD_GEOMETRY
            and item.disposition is SemanticDisposition.FAIL
            for item in findings
        )
        qualified_failures = sum(
            item.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
            and item.disposition is SemanticDisposition.FAIL
            for item in findings
        )
        hard_unverified = sum(
            item.authority in hard_authorities
            and item.disposition is SemanticDisposition.UNVERIFIED
            for item in findings
        )
        return cls(
            finding_count=len(findings),
            pass_count=sum(item.disposition is SemanticDisposition.PASS for item in findings),
            hard_failure_count=hard_failures,
            qualified_process_failure_count=qualified_failures,
            hard_scope_unverified_count=hard_unverified,
            validation_failure_count=sum(
                item.authority is SemanticAuthorityClass.VALIDATION_REQUIRED
                and item.disposition is SemanticDisposition.FAIL
                for item in findings
            ),
            advisory_count=sum(
                item.disposition is SemanticDisposition.ADVISORY for item in findings
            ),
            other_unverified_count=sum(
                item.authority not in hard_authorities
                and item.disposition is SemanticDisposition.UNVERIFIED
                for item in findings
            ),
            validation_pending_count=sum(
                item.disposition is SemanticDisposition.VALIDATION_PENDING for item in findings
            ),
            not_applicable_count=sum(
                item.disposition is SemanticDisposition.NOT_APPLICABLE for item in findings
            ),
            route_acceptance_blocked=bool(hard_failures or qualified_failures or hard_unverified),
        )


def _result_outcome(findings: Sequence[SemanticFinding]) -> SemanticResultOutcome:
    if not findings or all(
        item.disposition is SemanticDisposition.NOT_APPLICABLE for item in findings
    ):
        return SemanticResultOutcome.NOT_APPLICABLE
    hard_authorities = {
        SemanticAuthorityClass.HARD_GEOMETRY,
        SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
    }
    if any(
        item.authority in hard_authorities and item.disposition is SemanticDisposition.FAIL
        for item in findings
    ):
        return SemanticResultOutcome.HARD_REJECTED
    if any(
        item.authority in hard_authorities and item.disposition is SemanticDisposition.UNVERIFIED
        for item in findings
    ):
        return SemanticResultOutcome.HARD_SCOPE_UNVERIFIED
    if any(
        item.authority is SemanticAuthorityClass.VALIDATION_REQUIRED
        and item.disposition is SemanticDisposition.FAIL
        for item in findings
    ):
        return SemanticResultOutcome.VALIDATION_FAILED
    if any(
        item.authority is SemanticAuthorityClass.VALIDATION_REQUIRED
        and item.disposition
        in {SemanticDisposition.VALIDATION_PENDING, SemanticDisposition.UNVERIFIED}
        for item in findings
    ):
        return SemanticResultOutcome.VALIDATION_PENDING
    if any(
        item.disposition in {SemanticDisposition.ADVISORY, SemanticDisposition.UNVERIFIED}
        for item in findings
    ):
        return SemanticResultOutcome.ADVISORY_REVIEW
    return SemanticResultOutcome.PASSED


class SemanticLayoutResult(SemanticIrModel):
    """Result whose counts, authority outcome, and collection hashes cannot lie.

    Cross-checking finding IDs against a concrete evaluation context and declaration
    graph belongs to the later evaluator slice; this common IR checks internal honesty.
    """

    schema_id: Literal["pcbsmith-semantic-layout-result"] = "pcbsmith-semantic-layout-result"
    schema_version: Literal[1] = 1
    context_fingerprint: str
    declarations_fingerprint: str
    geometry_fingerprint: str
    placement_candidate_fingerprint: str | None = None
    input_fingerprint: str
    metrics: tuple[SemanticMetric, ...]
    findings: tuple[SemanticFinding, ...]
    summary: SemanticResultSummary
    outcome: SemanticResultOutcome
    metrics_fingerprint: str
    findings_fingerprint: str

    @field_validator(
        "context_fingerprint",
        "declarations_fingerprint",
        "geometry_fingerprint",
        "input_fingerprint",
        "metrics_fingerprint",
        "findings_fingerprint",
    )
    @classmethod
    def required_fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @field_validator("placement_candidate_fingerprint")
    @classmethod
    def optional_fingerprint_is_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_sha256(value, "placement_candidate_fingerprint")

    @model_validator(mode="after")
    def result_is_canonical_and_truthful(self) -> Self:
        metrics = tuple(
            sorted(
                (
                    SemanticMetric.model_validate_json(item.model_dump_json())
                    for item in self.metrics
                ),
                key=lambda item: item.metric_id,
            )
        )
        findings = tuple(
            sorted(
                (
                    SemanticFinding.model_validate_json(item.model_dump_json())
                    for item in self.findings
                ),
                key=lambda item: item.finding_id,
            )
        )
        summary = SemanticResultSummary.model_validate_json(self.summary.model_dump_json())
        if len({item.metric_id for item in metrics}) != len(metrics):
            raise ValueError("semantic metric identities must be unique")
        if len({item.finding_id for item in findings}) != len(findings):
            raise ValueError("semantic finding identities must be unique")
        metric_ids = {item.metric_id for item in metrics}
        if any(not set(item.metric_ids).issubset(metric_ids) for item in findings):
            raise ValueError("semantic finding references an unknown metric")
        expected_summary = SemanticResultSummary.from_findings(findings)
        expected_outcome = _result_outcome(findings)
        expected_metrics_fp = _fingerprint([item.model_dump(mode="json") for item in metrics])
        expected_findings_fp = _fingerprint([item.model_dump(mode="json") for item in findings])
        expected_input_fp = _fingerprint(
            {
                "context_fingerprint": self.context_fingerprint,
                "declarations_fingerprint": self.declarations_fingerprint,
                "geometry_fingerprint": self.geometry_fingerprint,
                "placement_candidate_fingerprint": self.placement_candidate_fingerprint,
            }
        )
        if summary != expected_summary:
            raise ValueError("semantic result summary is not derived from findings")
        if self.outcome is not expected_outcome:
            raise ValueError("semantic result outcome is not derived from findings")
        if self.metrics_fingerprint != expected_metrics_fp:
            raise ValueError("semantic metrics fingerprint is stale")
        if self.findings_fingerprint != expected_findings_fp:
            raise ValueError("semantic findings fingerprint is stale")
        if self.input_fingerprint != expected_input_fp:
            raise ValueError("semantic input fingerprint is stale")
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "summary", summary)
        return self

    @classmethod
    def build(
        cls,
        *,
        context_fingerprint: str,
        declarations_fingerprint: str,
        geometry_fingerprint: str,
        placement_candidate_fingerprint: str | None = None,
        metrics: Sequence[SemanticMetric] = (),
        findings: Sequence[SemanticFinding] = (),
    ) -> Self:
        canonical_metrics = tuple(sorted(metrics, key=lambda item: item.metric_id))
        canonical_findings = tuple(sorted(findings, key=lambda item: item.finding_id))
        inputs = {
            "context_fingerprint": context_fingerprint,
            "declarations_fingerprint": declarations_fingerprint,
            "geometry_fingerprint": geometry_fingerprint,
            "placement_candidate_fingerprint": placement_candidate_fingerprint,
        }
        return cls(
            **inputs,
            input_fingerprint=_fingerprint(inputs),
            metrics=canonical_metrics,
            findings=canonical_findings,
            summary=SemanticResultSummary.from_findings(canonical_findings),
            outcome=_result_outcome(canonical_findings),
            metrics_fingerprint=_fingerprint(
                [item.model_dump(mode="json") for item in canonical_metrics]
            ),
            findings_fingerprint=_fingerprint(
                [item.model_dump(mode="json") for item in canonical_findings]
            ),
        )
