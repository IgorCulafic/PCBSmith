"""Versioned sensor-isolation declarations and exact fabrication evidence.

This first R6.1b slice evaluates only explicit slot, retained-web, and support-tab
geometry.  It does not infer laminate, inspect copper, or claim sensor performance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum
from fractions import Fraction
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    PlanarRelation,
    compound_inside_polygon,
    compound_relation,
)
from pcbsmith.rule_profiles import FabricationGeometryProfile
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticEvaluationContext,
    SemanticFinding,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticMetric,
    SemanticQuantity,
    SemanticRegion,
    SemanticVerification,
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


def _identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def _sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _canonical_strings(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(_identity(value, field_name) for value in values))
    if len(set(canonical)) != len(canonical):
        raise ValueError(f"{field_name} must contain unique identities")
    return canonical


class SensorIsolationFeatureKind(StrEnum):
    SLOT = "slot"
    RETAINED_WEB = "retained_web"
    SUPPORT_TAB = "support_tab"


class SensorIsolationLimitOrigin(StrEnum):
    """Typed origin of one selected sensor-isolation numeric constraint.

    The first five values may identify hard numeric authority when their
    applicability is complete.  The final three retain useful design context,
    but cannot instantiate a hard geometry or qualified-process constraint.
    """

    FABRICATOR_PROCESS_CAPABILITY = "fabricator_process_capability"
    ASSEMBLER_QUALIFICATION = "assembler_qualification"
    EXACT_PROJECT_DESIGN_AUTHORITY = "exact_project_design_authority"
    VALIDATED_PROJECT_REQUIREMENT = "validated_project_requirement"
    PROJECT_VERIFIED_REQUIREMENT = "project_verified_requirement"
    MANUFACTURER_RECOMMENDED_LAYOUT = "manufacturer_recommended_layout"
    APPLICATION_NOTE_EXAMPLE = "application_note_example"
    GENERIC_BOOK_OR_ADVICE = "generic_book_or_advice"


_HARD_NUMERIC_ORIGINS = frozenset(
    {
        SensorIsolationLimitOrigin.FABRICATOR_PROCESS_CAPABILITY,
        SensorIsolationLimitOrigin.ASSEMBLER_QUALIFICATION,
        SensorIsolationLimitOrigin.EXACT_PROJECT_DESIGN_AUTHORITY,
        SensorIsolationLimitOrigin.VALIDATED_PROJECT_REQUIREMENT,
        SensorIsolationLimitOrigin.PROJECT_VERIFIED_REQUIREMENT,
    }
)

_QUALIFIED_PROCESS_ORIGINS = frozenset(
    {
        SensorIsolationLimitOrigin.FABRICATOR_PROCESS_CAPABILITY,
        SensorIsolationLimitOrigin.ASSEMBLER_QUALIFICATION,
    }
)


class SensorIsolationNumericLimit(SemanticIrModel):
    """One selected constraint; ``limit_id`` is its stable constraint identity."""

    schema_id: Literal["pcbsmith-sensor-isolation-numeric-limit"] = (
        "pcbsmith-sensor-isolation-numeric-limit"
    )
    schema_version: Literal[1] = 1
    limit_id: str = Field(min_length=1)
    feature_kind: SensorIsolationFeatureKind
    minimum: SemanticQuantity
    origin: SensorIsolationLimitOrigin
    authority: SemanticAuthorityClass = SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
    applicability_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def limit_is_typed_and_applicable(self) -> Self:
        _identity(self.limit_id, "limit_id")
        minimum = SemanticQuantity.model_validate_json(self.minimum.model_dump_json())
        if minimum.unit != "mm" or minimum.value <= 0:
            raise ValueError("sensor-isolation minimum must be a positive quantity in mm")
        applicability = _canonical_strings(
            self.applicability_binding_ids, "applicability_binding_ids"
        )
        if not set(minimum.source_binding_ids).issubset(applicability):
            raise ValueError("numeric limit source must be covered by its applicability binding")
        if (
            self.authority is SemanticAuthorityClass.HARD_GEOMETRY
            and self.origin not in _HARD_NUMERIC_ORIGINS
        ):
            raise ValueError(
                "hard sensor-isolation numeric authority requires a qualified fabrication/"
                "assembly limit, exact project design authority, or validated project requirement"
            )
        if (
            self.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
            and self.origin not in _QUALIFIED_PROCESS_ORIGINS
        ):
            raise ValueError(
                "qualified-process sensor-isolation authority requires a qualified "
                "fabrication or assembly origin"
            )
        if self.authority is SemanticAuthorityClass.VALIDATION_REQUIRED:
            raise ValueError("validation evidence cannot instantiate a numeric geometry limit")
        if (
            self.origin not in _HARD_NUMERIC_ORIGINS
            and self.authority is not SemanticAuthorityClass.ADVISORY_HYPOTHESIS
        ):
            raise ValueError("manufacturer examples and generic advice are advisory-only")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "applicability_binding_ids", applicability)
        return self


class SensorIsolationProcessProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-isolation-process-profile"] = (
        "pcbsmith-sensor-isolation-process-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str = Field(min_length=1)
    fabrication_profile_id: str = Field(min_length=1)
    qualified_process_record_id: str = Field(min_length=1)
    limits: tuple[SensorIsolationNumericLimit, ...] = Field(min_length=1)
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def process_is_canonical(self) -> Self:
        for field_name in (
            "profile_id",
            "fabrication_profile_id",
            "qualified_process_record_id",
        ):
            _identity(getattr(self, field_name), field_name)
        limits = tuple(
            sorted(
                (
                    SensorIsolationNumericLimit.model_validate_json(item.model_dump_json())
                    for item in self.limits
                ),
                key=lambda item: item.limit_id,
            )
        )
        if len({item.limit_id for item in limits}) != len(limits):
            raise ValueError("sensor-isolation limit identities must be unique")
        evidence = _canonical_strings(self.evidence_binding_ids, "evidence_binding_ids")
        if any(not set(item.applicability_binding_ids).issubset(evidence) for item in limits):
            raise ValueError("process limit applicability must be selected by the process profile")
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "evidence_binding_ids", evidence)
        return self


class SensorIsolationFeature(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-isolation-feature"] = "pcbsmith-sensor-isolation-feature"
    schema_version: Literal[1] = 1
    feature_id: str = Field(min_length=1)
    feature_kind: SensorIsolationFeatureKind
    region_id: str = Field(min_length=1)
    measurement_axis: Literal["x", "y"]
    limit_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def feature_is_canonical(self) -> Self:
        for field_name in ("feature_id", "region_id", "limit_id", "rule_id"):
            _identity(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "source_binding_ids",
            _canonical_strings(self.source_binding_ids, "source_binding_ids"),
        )
        return self


class SensorIsolationValidationDeclaration(SemanticIrModel):
    """Performance-validation identities; execution is a later R6.1b slice."""

    schema_id: Literal["pcbsmith-sensor-isolation-validation-declaration"] = (
        "pcbsmith-sensor-isolation-validation-declaration"
    )
    schema_version: Literal[1] = 1
    thermal_requirement_id: str = Field(min_length=1)
    humidity_requirement_id: str | None = None
    enclosure_required: bool = True

    @model_validator(mode="after")
    def requirements_are_identified(self) -> Self:
        _identity(self.thermal_requirement_id, "thermal_requirement_id")
        if self.humidity_requirement_id is not None:
            _identity(self.humidity_requirement_id, "humidity_requirement_id")
        return self


class SensorIsolationCandidate(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-isolation-candidate"] = (
        "pcbsmith-sensor-isolation-candidate"
    )
    schema_version: Literal[1] = 1
    candidate_id: str = Field(min_length=1)
    sensor_reference: str = Field(min_length=1)
    features: tuple[SensorIsolationFeature, ...] = Field(min_length=1)
    validation: SensorIsolationValidationDeclaration
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def candidate_is_canonical(self) -> Self:
        _identity(self.candidate_id, "candidate_id")
        _identity(self.sensor_reference, "sensor_reference")
        features = tuple(
            sorted(
                (
                    SensorIsolationFeature.model_validate_json(item.model_dump_json())
                    for item in self.features
                ),
                key=lambda item: item.feature_id,
            )
        )
        if len({item.feature_id for item in features}) != len(features):
            raise ValueError("sensor-isolation feature identities must be unique")
        required_kinds = set(SensorIsolationFeatureKind)
        if {item.feature_kind for item in features} != required_kinds:
            raise ValueError(
                "candidate requires explicit slot, retained-web, and support-tab features"
            )
        object.__setattr__(self, "features", features)
        object.__setattr__(
            self,
            "validation",
            SensorIsolationValidationDeclaration.model_validate_json(
                self.validation.model_dump_json()
            ),
        )
        object.__setattr__(
            self,
            "source_binding_ids",
            _canonical_strings(self.source_binding_ids, "source_binding_ids"),
        )
        return self


class SensorIsolationCatalog(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-isolation-catalog"] = "pcbsmith-sensor-isolation-catalog"
    schema_version: Literal[1] = 1
    catalog_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    regions: tuple[SemanticRegion, ...] = Field(min_length=1)
    candidate: SensorIsolationCandidate
    process_profile: SensorIsolationProcessProfile

    @model_validator(mode="after")
    def catalog_is_bound(self) -> Self:
        _identity(self.catalog_id, "catalog_id")
        _identity(self.revision, "revision")
        regions = tuple(
            sorted(
                (
                    SemanticRegion.model_validate_json(item.model_dump_json())
                    for item in self.regions
                ),
                key=lambda item: item.region_id,
            )
        )
        if len({item.region_id for item in regions}) != len(regions):
            raise ValueError("sensor-isolation region identities must be unique")
        candidate = SensorIsolationCandidate.model_validate_json(self.candidate.model_dump_json())
        process = SensorIsolationProcessProfile.model_validate_json(
            self.process_profile.model_dump_json()
        )
        region_by_id = {item.region_id: item for item in regions}
        limit_by_id = {item.limit_id: item for item in process.limits}
        for feature in candidate.features:
            region = region_by_id.get(feature.region_id)
            limit = limit_by_id.get(feature.limit_id)
            if region is None or limit is None:
                raise ValueError("sensor-isolation feature references unknown region or limit")
            if (
                region.coordinate_space != "board"
                or region.verification is not SemanticVerification.EXACT
            ):
                raise ValueError("fabrication features require exact board-coordinate geometry")
            if feature.feature_kind is not limit.feature_kind:
                raise ValueError("sensor-isolation feature and numeric limit kinds differ")
            expected_layer = (
                "Edge.Cuts"
                if feature.feature_kind is SensorIsolationFeatureKind.SLOT
                else "Board.Material"
            )
            if region.layers != (expected_layer,):
                raise ValueError("sensor-isolation feature uses the wrong physical layer")
        selected_evidence = set(process.evidence_binding_ids)
        used_evidence = set(candidate.source_binding_ids)
        for region in regions:
            used_evidence.update(region.source_binding_ids)
        for feature in candidate.features:
            used_evidence.update(feature.source_binding_ids)
        for limit in process.limits:
            used_evidence.update(limit.applicability_binding_ids)
            used_evidence.update(limit.minimum.source_binding_ids)
        if not used_evidence.issubset(selected_evidence):
            raise ValueError("candidate geometry/limits use unselected process evidence")
        object.__setattr__(self, "regions", regions)
        object.__setattr__(self, "candidate", candidate)
        object.__setattr__(self, "process_profile", process)
        return self


class SensorIsolationFeatureEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-isolation-feature-evidence"] = (
        "pcbsmith-sensor-isolation-feature-evidence"
    )
    schema_version: Literal[1] = 1
    feature_id: str
    region_id: str
    rule_id: str
    limit_id: str
    span_numerator_mm: int
    span_denominator: int = Field(gt=0)
    minimum_numerator_mm: int
    minimum_denominator: int = Field(gt=0)
    live_cutout_match: bool | None
    board_material_contained: bool | None
    intersecting_cutout_fingerprints: tuple[str, ...] = ()
    authority_complete: bool
    disposition: SemanticDisposition
    metric_id: str
    finding_id: str

    @model_validator(mode="after")
    def evidence_is_reduced(self) -> Self:
        for field_name in (
            "feature_id",
            "region_id",
            "rule_id",
            "limit_id",
            "metric_id",
            "finding_id",
        ):
            _identity(getattr(self, field_name), field_name)
        cutout_fingerprints = tuple(
            sorted(
                _sha256(item, "intersecting_cutout_fingerprints")
                for item in self.intersecting_cutout_fingerprints
            )
        )
        if len(set(cutout_fingerprints)) != len(cutout_fingerprints):
            raise ValueError("intersecting cutout fingerprints must be unique")
        object.__setattr__(
            self,
            "intersecting_cutout_fingerprints",
            cutout_fingerprints,
        )
        span = Fraction(self.span_numerator_mm, self.span_denominator)
        minimum = Fraction(self.minimum_numerator_mm, self.minimum_denominator)
        if (span.numerator, span.denominator) != (
            self.span_numerator_mm,
            self.span_denominator,
        ) or (minimum.numerator, minimum.denominator) != (
            self.minimum_numerator_mm,
            self.minimum_denominator,
        ):
            raise ValueError("sensor-isolation evidence fractions must be reduced")
        return self


def _region_span(region: SemanticRegion, axis: Literal["x", "y"]) -> Fraction:
    assert region.compound is not None
    index = 0 if axis == "x" else 1
    coordinates = [
        Fraction(str(point[index]))
        for polygon in region.compound.polygons
        for loop in (polygon.outer, *polygon.holes)
        for point in loop
    ]
    return max(coordinates) - min(coordinates)


def _binding_complete(binding: EvidenceApplicabilityBinding) -> bool:
    return (
        bool(binding.required_conditions)
        and not binding.unmatched_conditions
        and set(binding.matched_conditions) == set(binding.required_conditions)
        and binding.geometry_source_fingerprint is not None
        and binding.reviewer_record_id is not None
        and all(
            item.source_status == "pinned"
            and item.local_sha256 is not None
            and item.locator_status in {"text_verified", "figure_verified"}
            and item.applicability_status == "confirmed"
            for item in binding.evidence
        )
    )


def _base_process_authority_complete(
    context: SemanticEvaluationContext,
    catalog: SensorIsolationCatalog,
    fabrication_profile_id: str,
) -> bool:
    process = catalog.process_profile
    assembly = context.assembly_profile
    if (
        fabrication_profile_id != process.fabrication_profile_id
        or assembly is None
        or assembly.profile_id != process.profile_id
    ):
        return False
    records = {item.record_id: item for item in assembly.qualification_records}
    record = records.get(process.qualified_process_record_id)
    if (
        record is None
        or record.status != "active"
        or record.effective_date > context.evaluation_date
        or (record.expiry_date is not None and record.expiry_date < context.evaluation_date)
    ):
        return False
    assembly_bindings = {item.binding_id: item for item in assembly.evidence_bindings}
    return set(record.applicability_binding_ids).issubset(assembly_bindings) and all(
        _binding_complete(assembly_bindings[item]) for item in record.applicability_binding_ids
    )


def _cited_binding_ids(catalog: SensorIsolationCatalog) -> set[str]:
    cited = {
        *catalog.candidate.source_binding_ids,
        *catalog.process_profile.evidence_binding_ids,
    }
    for region in catalog.regions:
        cited.update(region.source_binding_ids)
    for feature in catalog.candidate.features:
        cited.update(feature.source_binding_ids)
    for limit in catalog.process_profile.limits:
        cited.update(limit.applicability_binding_ids)
        cited.update(limit.minimum.source_binding_ids)
    return cited


def _feature_authority_complete(
    context: SemanticEvaluationContext,
    catalog: SensorIsolationCatalog,
    fabrication_profile_id: str,
    feature: SensorIsolationFeature,
    region: SemanticRegion,
    limit: SensorIsolationNumericLimit,
) -> bool:
    process = catalog.process_profile
    bindings = {item.binding_id: item for item in context.semantic_profile.evidence_bindings}
    semantic_regions = {item.region_id: item for item in context.semantic_profile.regions}
    context_region = semantic_regions.get(region.region_id)
    rule = {item.rule_id: item for item in context.semantic_profile.rules}.get(feature.rule_id)
    required_bindings = {
        *catalog.candidate.source_binding_ids,
        *feature.source_binding_ids,
        *region.source_binding_ids,
        *limit.applicability_binding_ids,
        *limit.minimum.source_binding_ids,
    }
    common_complete = (
        fabrication_profile_id == process.fabrication_profile_id
        and context_region is not None
        and context_region.semantic_fingerprint() == region.semantic_fingerprint()
        and rule is not None
        and feature.feature_id in rule.object_ids
        and required_bindings.issubset(process.evidence_binding_ids)
        and required_bindings.issubset(rule.evidence_binding_ids)
        and required_bindings.issubset(bindings)
        and all(_binding_complete(bindings[item]) for item in required_bindings)
    )
    if not common_complete or rule is None:
        return False
    if limit.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT:
        return (
            _base_process_authority_complete(context, catalog, fabrication_profile_id)
            and rule.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
            and rule.process_profile_id == process.profile_id
            and rule.qualified_process_record_id == process.qualified_process_record_id
        )
    if limit.authority is SemanticAuthorityClass.HARD_GEOMETRY:
        return (
            rule.authority is SemanticAuthorityClass.HARD_GEOMETRY
            and feature.region_id in rule.geometry_region_ids
        )
    return (
        limit.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
        and rule.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
    )


def _derive(
    context: SemanticEvaluationContext,
    catalog: SensorIsolationCatalog,
    fabrication_profile_id: str,
    board_outline: ExactPlanarCompound,
    live_cutouts: Sequence[ExactPlanarCompound],
) -> tuple[
    tuple[SensorIsolationFeatureEvidence, ...],
    tuple[SemanticMetric, ...],
    tuple[SemanticFinding, ...],
]:
    region_by_id = {item.region_id: item for item in catalog.regions}
    limit_by_id = {item.limit_id: item for item in catalog.process_profile.limits}
    if len(board_outline.polygons) != 1:
        raise ValueError("live board outline must contain exactly one polygon")
    outline_polygon = board_outline.polygons[0]
    known_binding_ids = {item.binding_id for item in context.semantic_profile.evidence_bindings}
    unknown_binding_ids = _cited_binding_ids(catalog) - known_binding_ids
    if unknown_binding_ids:
        raise ValueError(
            "sensor-isolation declarations cite unknown context evidence: "
            + ", ".join(sorted(unknown_binding_ids))
        )
    evidence_items: list[SensorIsolationFeatureEvidence] = []
    metrics: list[SemanticMetric] = []
    findings: list[SemanticFinding] = []
    for feature in catalog.candidate.features:
        region = region_by_id[feature.region_id]
        limit = limit_by_id[feature.limit_id]
        authority = _feature_authority_complete(
            context,
            catalog,
            fabrication_profile_id,
            feature,
            region,
            limit,
        )
        span = _region_span(region, feature.measurement_axis)
        minimum = Fraction(str(limit.minimum.value))
        cutout_match = (
            region.compound in live_cutouts
            if feature.feature_kind is SensorIsolationFeatureKind.SLOT
            else None
        )
        if feature.feature_kind is SensorIsolationFeatureKind.SLOT:
            board_material_contained = None
            intersecting_cutouts: tuple[str, ...] = ()
        else:
            assert region.compound is not None
            board_material_contained = compound_inside_polygon(region.compound, outline_polygon)
            intersecting_cutouts = tuple(
                sorted(
                    cutout.semantic_fingerprint()
                    for cutout in live_cutouts
                    if compound_relation(region.compound, cutout) is PlanarRelation.INTERIOR_OVERLAP
                )
            )
        geometry_passes = (
            span >= minimum
            and cutout_match is not False
            and board_material_contained is not False
            and not intersecting_cutouts
        )
        disposition = (
            SemanticDisposition.ADVISORY
            if limit.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
            else SemanticDisposition.UNVERIFIED
            if not authority
            else SemanticDisposition.PASS
            if geometry_passes
            else SemanticDisposition.FAIL
        )
        metric = SemanticMetric(
            metric_id=f"sensor-isolation:span:{feature.feature_id}",
            verification=SemanticVerification.EXACT,
            quantity=SemanticQuantity(
                quantity_id=f"sensor-isolation:measured-span:{feature.feature_id}",
                value=float(span),
                unit="mm",
                source_binding_ids=tuple(
                    sorted({*feature.source_binding_ids, *region.source_binding_ids})
                ),
            ),
            object_ids=(catalog.candidate.candidate_id, feature.feature_id),
        )
        message = (
            "Advisory numeric context is retained without hard pass/fail authority"
            if limit.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
            else "Selected fabrication/assembly or project authority is incomplete"
            if not authority
            else "Exact feature meets its selected numeric constraint"
            if geometry_passes
            else "Exact feature is below its selected constraint or the slot is absent"
        )
        finding = SemanticFinding(
            rule_id=feature.rule_id,
            authority=limit.authority,
            disposition=disposition,
            verification=SemanticVerification.EXACT,
            object_ids=(catalog.candidate.candidate_id, feature.feature_id),
            component_refs=(catalog.candidate.sensor_reference,),
            region_ids=(feature.region_id,),
            metric_ids=(metric.metric_id,),
            evidence_binding_ids=tuple(
                sorted(
                    {
                        *catalog.candidate.source_binding_ids,
                        *feature.source_binding_ids,
                        *region.source_binding_ids,
                        *limit.applicability_binding_ids,
                        *limit.minimum.source_binding_ids,
                    }
                )
            ),
            process_profile_id=(
                catalog.process_profile.profile_id
                if limit.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
                else None
            ),
            qualified_process_record_id=(
                catalog.process_profile.qualified_process_record_id
                if limit.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
                else None
            ),
            message=message,
            suggested_action=(
                "Retain as advisory context; select a qualified or project geometry constraint"
                if limit.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
                else "Bind the selected fabrication/assembly or project geometry authority"
                if not authority
                else "Increase the explicit feature span or provide the declared live cutout"
                if not geometry_passes
                else "Retain the exact declared geometry and selected authority"
            ),
        )
        evidence_items.append(
            SensorIsolationFeatureEvidence(
                feature_id=feature.feature_id,
                region_id=feature.region_id,
                rule_id=feature.rule_id,
                limit_id=feature.limit_id,
                span_numerator_mm=span.numerator,
                span_denominator=span.denominator,
                minimum_numerator_mm=minimum.numerator,
                minimum_denominator=minimum.denominator,
                live_cutout_match=cutout_match,
                board_material_contained=board_material_contained,
                intersecting_cutout_fingerprints=intersecting_cutouts,
                authority_complete=authority,
                disposition=disposition,
                metric_id=metric.metric_id,
                finding_id=finding.finding_id,
            )
        )
        metrics.append(metric)
        findings.append(finding)
    return (
        tuple(sorted(evidence_items, key=lambda item: item.feature_id)),
        tuple(sorted(metrics, key=lambda item: item.metric_id)),
        tuple(sorted(findings, key=lambda item: item.finding_id)),
    )


class SensorIsolationEvaluationResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-isolation-evaluation-result"] = (
        "pcbsmith-sensor-isolation-evaluation-result"
    )
    schema_version: Literal[1] = 1
    context: SemanticEvaluationContext
    catalog: SensorIsolationCatalog
    fabrication_profile: FabricationGeometryProfile
    fabrication_profile_fingerprint: str
    board_layout_fingerprint: str
    board_outline: ExactPlanarCompound
    live_cutouts: tuple[ExactPlanarCompound, ...]
    feature_evidence: tuple[SensorIsolationFeatureEvidence, ...]
    geometry_fingerprint: str
    source_fingerprint: str
    input_fingerprint: str
    metrics: tuple[SemanticMetric, ...]
    findings: tuple[SemanticFinding, ...]
    semantic_result: SemanticLayoutResult

    @field_validator(
        "fabrication_profile_fingerprint",
        "board_layout_fingerprint",
        "geometry_fingerprint",
        "source_fingerprint",
        "input_fingerprint",
    )
    @classmethod
    def hashes_are_sha256(cls, value: str, info: Any) -> str:
        return _sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_is_derived(self) -> Self:
        context = SemanticEvaluationContext.model_validate_json(self.context.model_dump_json())
        catalog = SensorIsolationCatalog.model_validate_json(self.catalog.model_dump_json())
        fabrication_profile = FabricationGeometryProfile.model_validate_json(
            self.fabrication_profile.model_dump_json()
        )
        expected_fabrication_fp = _fingerprint(fabrication_profile.model_dump(mode="json"))
        if self.fabrication_profile_fingerprint != expected_fabrication_fp:
            raise ValueError("sensor-isolation fabrication profile fingerprint is stale")
        board_outline = ExactPlanarCompound.model_validate_json(
            self.board_outline.model_dump_json()
        )
        if len(board_outline.polygons) != 1:
            raise ValueError("live board outline must contain exactly one polygon")
        cutouts = tuple(sorted(self.live_cutouts, key=lambda item: item.semantic_fingerprint()))
        expected_evidence, expected_metrics, expected_findings = _derive(
            context,
            catalog,
            fabrication_profile.profile_id,
            board_outline,
            cutouts,
        )
        evidence = tuple(
            sorted(
                (
                    SensorIsolationFeatureEvidence.model_validate_json(item.model_dump_json())
                    for item in self.feature_evidence
                ),
                key=lambda item: item.feature_id,
            )
        )
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
        if (
            evidence != expected_evidence
            or metrics != expected_metrics
            or findings != expected_findings
        ):
            raise ValueError("sensor-isolation result evidence/findings are not derived")
        geometry_fp = _fingerprint(
            {
                "board_outline": board_outline.model_dump(mode="json"),
                "cutouts": [item.model_dump(mode="json") for item in cutouts],
            }
        )
        source_fp = catalog.semantic_fingerprint()
        if self.geometry_fingerprint != geometry_fp or self.source_fingerprint != source_fp:
            raise ValueError("sensor-isolation geometry/source fingerprint is stale")
        inputs = {
            "context_fingerprint": context.semantic_fingerprint(),
            "catalog_fingerprint": source_fp,
            "fabrication_profile_id": fabrication_profile.profile_id,
            "fabrication_profile_fingerprint": self.fabrication_profile_fingerprint,
            "board_layout_fingerprint": self.board_layout_fingerprint,
            "geometry_fingerprint": geometry_fp,
        }
        if self.input_fingerprint != _fingerprint(inputs):
            raise ValueError("sensor-isolation input fingerprint is stale")
        semantic = SemanticLayoutResult.build(
            context_fingerprint=context.semantic_fingerprint(),
            declarations_fingerprint=source_fp,
            geometry_fingerprint=geometry_fp,
            metrics=metrics,
            findings=findings,
        )
        if (
            SemanticLayoutResult.model_validate_json(self.semantic_result.model_dump_json())
            != semantic
        ):
            raise ValueError("sensor-isolation semantic result is stale")
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "catalog", catalog)
        object.__setattr__(self, "fabrication_profile", fabrication_profile)
        object.__setattr__(self, "board_outline", board_outline)
        object.__setattr__(self, "live_cutouts", cutouts)
        object.__setattr__(self, "feature_evidence", evidence)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "semantic_result", semantic)
        return self

    @classmethod
    def build(
        cls,
        *,
        context: SemanticEvaluationContext,
        catalog: SensorIsolationCatalog,
        fabrication_profile: FabricationGeometryProfile,
        board_layout_fingerprint: str,
        board_outline: ExactPlanarCompound,
        live_cutouts: Sequence[ExactPlanarCompound],
    ) -> Self:
        validated_fabrication_profile = FabricationGeometryProfile.model_validate_json(
            fabrication_profile.model_dump_json()
        )
        fabrication_profile_fingerprint = _fingerprint(
            validated_fabrication_profile.model_dump(mode="json")
        )
        validated_board_outline = ExactPlanarCompound.model_validate_json(
            board_outline.model_dump_json()
        )
        if len(validated_board_outline.polygons) != 1:
            raise ValueError("live board outline must contain exactly one polygon")
        cutouts = tuple(sorted(live_cutouts, key=lambda item: item.semantic_fingerprint()))
        evidence, metrics, findings = _derive(
            context,
            catalog,
            validated_fabrication_profile.profile_id,
            validated_board_outline,
            cutouts,
        )
        geometry_fp = _fingerprint(
            {
                "board_outline": validated_board_outline.model_dump(mode="json"),
                "cutouts": [item.model_dump(mode="json") for item in cutouts],
            }
        )
        source_fp = catalog.semantic_fingerprint()
        inputs = {
            "context_fingerprint": context.semantic_fingerprint(),
            "catalog_fingerprint": source_fp,
            "fabrication_profile_id": validated_fabrication_profile.profile_id,
            "fabrication_profile_fingerprint": fabrication_profile_fingerprint,
            "board_layout_fingerprint": board_layout_fingerprint,
            "geometry_fingerprint": geometry_fp,
        }
        return cls(
            context=context,
            catalog=catalog,
            fabrication_profile=validated_fabrication_profile,
            fabrication_profile_fingerprint=fabrication_profile_fingerprint,
            board_layout_fingerprint=board_layout_fingerprint,
            board_outline=validated_board_outline,
            live_cutouts=cutouts,
            feature_evidence=evidence,
            geometry_fingerprint=geometry_fp,
            source_fingerprint=source_fp,
            input_fingerprint=_fingerprint(inputs),
            metrics=metrics,
            findings=findings,
            semantic_result=SemanticLayoutResult.build(
                context_fingerprint=context.semantic_fingerprint(),
                declarations_fingerprint=source_fp,
                geometry_fingerprint=geometry_fp,
                metrics=metrics,
                findings=findings,
            ),
        )
