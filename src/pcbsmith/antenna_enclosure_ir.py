"""Source-specific 3-D enclosure exclusion authority for antenna modules.

This companion IR deliberately does not alter or reinterpret any two-dimensional
PCB keepout, copper-clearance, edge, or cutout result.  It represents enclosure
objects and the antenna exclusion as exact planar compounds extruded through
exact decimal Z intervals.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.antenna_ir import AntennaModuleDeclaration, AntennaPlacementResult
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    PlacedCompoundTransform,
    PlacementTransformAuthority,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticVerification,
)

EnclosureMaterialClass = Literal["metal", "plastic", "glass", "foam", "air", "other"]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot canonically serialize {type(value).__name__}")


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


def canonical_identities(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    result = tuple(sorted(require_identity(item, field_name) for item in values))
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must contain unique identities")
    return result


def exact_fraction(value: Decimal) -> Fraction:
    return Fraction(value)


class ExactDecimalInterval(SemanticIrModel):
    """Closed interval whose endpoints serialize as exact decimal strings."""

    schema_id: Literal["pcbsmith-exact-decimal-interval"] = (
        "pcbsmith-exact-decimal-interval"
    )
    schema_version: Literal[1] = 1
    lower_mm: Decimal
    upper_mm: Decimal

    @model_validator(mode="after")
    def interval_is_finite_and_ordered(self) -> Self:
        if not self.lower_mm.is_finite() or not self.upper_mm.is_finite():
            raise ValueError("exact decimal interval endpoints must be finite")
        if self.lower_mm > self.upper_mm:
            raise ValueError("exact decimal interval lower endpoint exceeds upper endpoint")
        object.__setattr__(self, "lower_mm", Decimal(0) if self.lower_mm == 0 else self.lower_mm)
        object.__setattr__(self, "upper_mm", Decimal(0) if self.upper_mm == 0 else self.upper_mm)
        return self


class ExactRational(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-rational"] = "pcbsmith-exact-rational"
    schema_version: Literal[1] = 1
    numerator: int
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def fraction_is_reduced(self) -> Self:
        value = Fraction(self.numerator, self.denominator)
        if (value.numerator, value.denominator) != (self.numerator, self.denominator):
            raise ValueError("exact rational must be reduced with a positive denominator")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction) -> ExactRational:
        return cls(numerator=value.numerator, denominator=value.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class ExactRationalPoint2(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-rational-point-2d"] = (
        "pcbsmith-exact-rational-point-2d"
    )
    schema_version: Literal[1] = 1
    x_mm: ExactRational
    y_mm: ExactRational


class AntennaExclusionPrismDeclaration(SemanticIrModel):
    """One source-bound module-local planar exclusion extruded in local Z."""

    schema_id: Literal["pcbsmith-antenna-exclusion-prism-declaration"] = (
        "pcbsmith-antenna-exclusion-prism-declaration"
    )
    schema_version: Literal[1] = 1
    exclusion_id: str = Field(min_length=1)
    local_xy_compound: ExactPlanarCompound
    local_z_interval: ExactDecimalInterval

    @field_validator("exclusion_id")
    @classmethod
    def identity_is_valid(cls, value: str) -> str:
        return require_identity(value, "exclusion_id")


def exclusion_binding_fingerprint(
    antenna_declaration: AntennaModuleDeclaration,
    exclusion: AntennaExclusionPrismDeclaration,
    required_clearance_mm: Decimal,
    prohibited_material_classes: Sequence[EnclosureMaterialClass],
) -> str:
    return fingerprint(
        {
            "schema_id": "pcbsmith-antenna-enclosure-exclusion-binding-source",
            "schema_version": 1,
            "antenna_declaration_fingerprint": antenna_declaration.semantic_fingerprint(),
            "selected_footprint_library_id": antenna_declaration.selected_footprint_library_id,
            "component_uuid_path": antenna_declaration.component_uuid_path,
            "component_revision": antenna_declaration.component_revision,
            "source_file_sha256": antenna_declaration.source_file_sha256,
            "exclusion": exclusion.model_dump(mode="json"),
            "required_clearance_mm": required_clearance_mm,
            "clearance_unit": "mm",
            "prohibited_material_classes": sorted(prohibited_material_classes),
        }
    )


class AntennaEnclosureExclusionDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-enclosure-exclusion-declaration"] = (
        "pcbsmith-antenna-enclosure-exclusion-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str = Field(min_length=1)
    antenna_id: str = Field(min_length=1)
    module_reference: str = Field(min_length=1)
    selected_footprint_library_id: str = Field(min_length=1)
    component_uuid_path: str = Field(min_length=1)
    component_revision: str = Field(min_length=1)
    source_file_sha256: str
    antenna_declaration_fingerprint: str
    exclusion_requirement_id: str = Field(min_length=1)
    validation_profile_id: str = Field(min_length=1)
    exclusion: AntennaExclusionPrismDeclaration
    required_clearance_mm: Decimal = Field(gt=0)
    clearance_unit: Literal["mm"] = "mm"
    prohibited_material_classes: tuple[EnclosureMaterialClass, ...] = Field(min_length=1)
    enclosure_profile_id: str = Field(min_length=1)
    enclosure_id: str = Field(min_length=1)
    enclosure_revision: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_sha256: str
    applicability_binding: EvidenceApplicabilityBinding

    @model_validator(mode="after")
    def authority_is_complete(self) -> Self:
        for name in (
            "declaration_id", "antenna_id", "module_reference",
            "selected_footprint_library_id", "component_uuid_path", "component_revision",
            "exclusion_requirement_id", "validation_profile_id", "enclosure_profile_id",
            "enclosure_id", "enclosure_revision", "model_id",
        ):
            require_identity(getattr(self, name), name)
        require_sha256(self.source_file_sha256, "source_file_sha256")
        require_sha256(self.antenna_declaration_fingerprint, "antenna_declaration_fingerprint")
        require_sha256(self.model_sha256, "model_sha256")
        if not self.required_clearance_mm.is_finite():
            raise ValueError("required_clearance_mm must be finite")
        classes = tuple(sorted(self.prohibited_material_classes))
        if len(classes) != len(set(classes)):
            raise ValueError("prohibited_material_classes must be unique")
        binding = self.applicability_binding
        if binding.unmatched_conditions or binding.reviewer_record_id is None:
            raise ValueError("enclosure exclusion applicability must be complete and reviewed")
        if not binding.required_conditions or set(binding.matched_conditions) != set(
            binding.required_conditions
        ):
            raise ValueError("enclosure exclusion applicability conditions are incomplete")
        if binding.geometry_source_fingerprint is None:
            raise ValueError("enclosure exclusion binding must retain exact source geometry")
        if not any(
            item.source_status == "pinned"
            and item.locator_status in {"text_verified", "figure_bound", "figure_verified"}
            and item.applicability_status == "confirmed"
            and item.local_sha256 == self.source_file_sha256
            for item in binding.evidence
        ):
            raise ValueError("enclosure exclusion source is not pinned and applicable")
        object.__setattr__(self, "prohibited_material_classes", classes)
        return self


class EnclosureObject(SemanticIrModel):
    schema_id: Literal["pcbsmith-enclosure-object"] = "pcbsmith-enclosure-object"
    schema_version: Literal[1] = 1
    object_id: str = Field(min_length=1)
    enclosure_profile_id: str = Field(min_length=1)
    enclosure_id: str = Field(min_length=1)
    enclosure_revision: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_sha256: str
    material_class: EnclosureMaterialClass
    planar_compound: ExactPlanarCompound | None
    z_interval: ExactDecimalInterval | None

    @model_validator(mode="after")
    def object_is_source_identified(self) -> Self:
        for name in (
            "object_id", "enclosure_profile_id", "enclosure_id", "enclosure_revision", "model_id"
        ):
            require_identity(getattr(self, name), name)
        require_sha256(self.model_sha256, "model_sha256")
        if (self.planar_compound is None) != (self.z_interval is None):
            raise ValueError("enclosure object geometry must be wholly exact or wholly missing")
        return self


class EnclosureObjectProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-enclosure-object-profile"] = (
        "pcbsmith-enclosure-object-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str = Field(min_length=1)
    enclosure_id: str = Field(min_length=1)
    enclosure_revision: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_sha256: str
    model_geometry_status: Literal["available", "missing"]
    board_plane_z_mm: Decimal
    completeness: Literal["complete", "incomplete"]
    expected_object_ids: tuple[str, ...] = Field(min_length=1)
    objects: tuple[EnclosureObject, ...]

    @model_validator(mode="after")
    def profile_is_canonical(self) -> Self:
        for name in ("profile_id", "enclosure_id", "enclosure_revision", "model_id"):
            require_identity(getattr(self, name), name)
        require_sha256(self.model_sha256, "model_sha256")
        if not self.board_plane_z_mm.is_finite():
            raise ValueError("board_plane_z_mm must be finite")
        expected = canonical_identities(self.expected_object_ids, "expected_object_ids")
        objects = tuple(sorted(self.objects, key=lambda item: item.object_id))
        if len({item.object_id for item in objects}) != len(objects):
            raise ValueError("enclosure object identities must be unique")
        actual = {item.object_id for item in objects}
        if not actual.issubset(expected):
            raise ValueError("enclosure profile invents objects outside its expected inventory")
        if self.completeness == "complete" and actual != set(expected):
            raise ValueError("complete enclosure profile must contain its exact object inventory")
        if self.model_geometry_status == "missing" and (
            objects or self.completeness != "incomplete"
        ):
            raise ValueError(
                "missing enclosure model geometry requires an empty incomplete profile"
            )
        for item in objects:
            if (
                item.enclosure_profile_id != self.profile_id
                or item.enclosure_id != self.enclosure_id
                or item.enclosure_revision != self.enclosure_revision
                or item.model_id != self.model_id
                or item.model_sha256 != self.model_sha256
            ):
                raise ValueError("enclosure object identity/model authority is stale")
        object.__setattr__(self, "expected_object_ids", expected)
        object.__setattr__(self, "objects", objects)
        return self


class TransformedAntennaExclusionPrism(SemanticIrModel):
    schema_id: Literal["pcbsmith-transformed-antenna-exclusion-prism"] = (
        "pcbsmith-transformed-antenna-exclusion-prism"
    )
    schema_version: Literal[1] = 1
    exclusion_id: str
    bounded_xy_transform: PlacedCompoundTransform
    exact_xy_compound: ExactPlanarCompound | None
    exact_z_interval: ExactDecimalInterval
    board_plane_z_mm: Decimal
    verification: SemanticVerification

    @model_validator(mode="after")
    def transformed_claim_is_coherent(self) -> Self:
        require_identity(self.exclusion_id, "exclusion_id")
        if self.bounded_xy_transform.authority is PlacementTransformAuthority.EXACT:
            if (
                self.verification is not SemanticVerification.EXACT
                or self.exact_xy_compound != self.bounded_xy_transform.compound
            ):
                raise ValueError("exact transformed exclusion geometry is stale")
        elif (
            self.verification is not SemanticVerification.BOUNDED_APPROXIMATION
            or self.exact_xy_compound is not None
        ):
            raise ValueError("bounded transformed exclusion cannot claim exact XY geometry")
        return self


class AntennaEnclosureDistanceEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-enclosure-distance-evidence"] = (
        "pcbsmith-antenna-enclosure-distance-evidence"
    )
    schema_version: Literal[1] = 1
    object_id: str
    material_class: EnclosureMaterialClass | None
    applicable: bool | None
    object_geometry_fingerprint: str | None
    xy_squared_distance: ExactRational | None
    z_separation: ExactRational | None
    total_squared_distance: ExactRational | None
    required_squared_clearance: ExactRational
    exclusion_xy_point: ExactRationalPoint2 | None
    object_xy_point: ExactRationalPoint2 | None
    exclusion_z_point: ExactRational | None
    object_z_point: ExactRational | None
    verification: SemanticVerification
    disposition: SemanticDisposition
    pending_reason: str | None

    @model_validator(mode="after")
    def evidence_is_coherent(self) -> Self:
        require_identity(self.object_id, "object_id")
        exact_fields = (
            self.xy_squared_distance, self.z_separation, self.total_squared_distance,
            self.exclusion_xy_point, self.object_xy_point,
            self.exclusion_z_point, self.object_z_point,
        )
        if self.disposition is SemanticDisposition.NOT_APPLICABLE:
            if self.applicable is not False or any(item is not None for item in exact_fields):
                raise ValueError("non-applicable enclosure evidence cannot claim distance")
        elif self.disposition is SemanticDisposition.VALIDATION_PENDING:
            if self.applicable is False or any(item is not None for item in exact_fields):
                raise ValueError("pending enclosure evidence cannot claim exact distance")
            if self.pending_reason is None:
                raise ValueError("pending enclosure evidence requires a reason")
        elif self.disposition in {SemanticDisposition.PASS, SemanticDisposition.FAIL}:
            if self.applicable is not True or any(item is None for item in exact_fields):
                raise ValueError("completed enclosure evidence requires exact applicable witnesses")
            if (
                self.verification is not SemanticVerification.EXACT
                or self.pending_reason is not None
            ):
                raise ValueError("completed enclosure evidence must be exact and non-pending")
            assert self.total_squared_distance is not None
            expected = (
                SemanticDisposition.PASS
                if self.total_squared_distance.as_fraction()
                >= self.required_squared_clearance.as_fraction()
                else SemanticDisposition.FAIL
            )
            if self.disposition is not expected:
                raise ValueError("enclosure distance disposition is stale")
        else:
            raise ValueError("unsupported enclosure evidence disposition")
        return self


class AntennaEnclosureExclusionResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-enclosure-exclusion-result"] = (
        "pcbsmith-antenna-enclosure-exclusion-result"
    )
    schema_version: Literal[1] = 1
    separation_statement: Literal[
        "3-D enclosure exclusion is independent; 2-D PCB geometry is retained unchanged"
    ] = "3-D enclosure exclusion is independent; 2-D PCB geometry is retained unchanged"
    placement_result: AntennaPlacementResult
    declaration: AntennaEnclosureExclusionDeclaration
    enclosure_profile: EnclosureObjectProfile | None
    transformed_exclusion: TransformedAntennaExclusionPrism | None
    evidence: tuple[AntennaEnclosureDistanceEvidence, ...]
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
    def hash_is_valid(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.antenna_enclosure import rederive_antenna_enclosure_exclusion

        expected = rederive_antenna_enclosure_exclusion(
            self.placement_result, self.declaration, self.enclosure_profile
        )
        compared = (
            "declaration", "enclosure_profile", "transformed_exclusion", "evidence",
            "pcb_geometry_before_fingerprint", "pcb_geometry_after_fingerprint",
            "evidence_fingerprint", "semantic_result",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("antenna enclosure exclusion result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("antenna enclosure exclusion result fingerprint is stale")
        return self
