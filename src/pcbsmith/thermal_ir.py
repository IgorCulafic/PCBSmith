"""Engine-neutral declarations and self-validating results for R6.1a thermal semantics.

This module does not simulate heat flow. It separates hard geometric authority
from advisory theta-model estimates and keeps evidence, operating conditions,
and live placement identity explicit.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from fractions import Fraction
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    PlanarRelation,
    compound_distance_witness,
)
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticEvaluationContext,
    SemanticFinding,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticMetric,
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


def compose_thermal_position_error(*values: float) -> float:
    """Compose independent positional caps with directed-up float rounding."""

    positive = tuple(value for value in values if value > 0)
    if not positive:
        return 0.0
    result = sum(positive)
    return math.nextafter(result, math.inf) if len(positive) > 1 else result


def conservative_thermal_distance_mm(squared_distance: Fraction, maximum_error_mm: float) -> float:
    """Diagnostic distance rounded down, then reduced by the positional cap."""

    nominal = math.sqrt(float(squared_distance))
    rounded_down = math.nextafter(nominal, -math.inf)
    return max(
        0.0,
        math.nextafter(rounded_down - maximum_error_mm, -math.inf),
    )


class ThermalOperatingPoint(SemanticIrModel):
    """One explicit source load and its board/air/enclosure operating scope."""

    schema_id: Literal["pcbsmith-thermal-operating-point"] = "pcbsmith-thermal-operating-point"
    schema_version: Literal[1] = 1
    operating_point_id: str = Field(min_length=1)
    ambient_temperature_c: float
    dissipation_w: float = Field(ge=0)
    duty_cycle: float = Field(ge=0, le=1)
    pcb_profile_fingerprint: str
    enclosure_profile_fingerprint: str | None = None
    board_condition_ids: tuple[str, ...] = Field(min_length=1)
    air_condition_ids: tuple[str, ...] = Field(min_length=1)
    enclosure_condition_ids: tuple[str, ...] = ()
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def scope_is_explicit_and_canonical(self) -> Self:
        _identity(self.operating_point_id, "operating_point_id")
        _sha256(self.pcb_profile_fingerprint, "pcb_profile_fingerprint")
        if self.enclosure_profile_fingerprint is not None:
            _sha256(
                self.enclosure_profile_fingerprint,
                "enclosure_profile_fingerprint",
            )
        if not all(
            math.isfinite(value)
            for value in (
                self.ambient_temperature_c,
                self.dissipation_w,
                self.duty_cycle,
            )
        ):
            raise ValueError("thermal operating-point quantities must be finite")
        for field_name in (
            "board_condition_ids",
            "air_condition_ids",
            "enclosure_condition_ids",
            "evidence_binding_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _canonical_strings(getattr(self, field_name), field_name),
            )
        if (self.enclosure_profile_fingerprint is None) != (not self.enclosure_condition_ids):
            raise ValueError(
                "operating-point enclosure fingerprint and conditions must appear together"
            )
        return self


class ThermalPredictionModel(SemanticIrModel):
    """Explicitly scoped theta model; it remains advisory, never validation."""

    schema_id: Literal["pcbsmith-thermal-prediction-model"] = "pcbsmith-thermal-prediction-model"
    schema_version: Literal[1] = 1
    model_id: str = Field(min_length=1)
    model_kind: Literal["theta_ja"] = "theta_ja"
    theta_c_per_w: float = Field(gt=0)
    ambient_temperature_c: float
    dissipation_w: float = Field(ge=0)
    duty_cycle: float = Field(ge=0, le=1)
    pcb_profile_fingerprint: str
    enclosure_profile_fingerprint: str
    board_condition_ids: tuple[str, ...] = Field(min_length=1)
    air_condition_ids: tuple[str, ...] = Field(min_length=1)
    enclosure_condition_ids: tuple[str, ...] = Field(min_length=1)
    applicable_source_ids: tuple[str, ...] = Field(min_length=1)
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def model_scope_is_explicit_and_canonical(self) -> Self:
        _identity(self.model_id, "model_id")
        _sha256(self.pcb_profile_fingerprint, "pcb_profile_fingerprint")
        _sha256(self.enclosure_profile_fingerprint, "enclosure_profile_fingerprint")
        if not all(
            math.isfinite(value)
            for value in (
                self.theta_c_per_w,
                self.ambient_temperature_c,
                self.dissipation_w,
                self.duty_cycle,
            )
        ):
            raise ValueError("thermal prediction-model quantities must be finite")
        for field_name in (
            "board_condition_ids",
            "air_condition_ids",
            "enclosure_condition_ids",
            "applicable_source_ids",
            "evidence_binding_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _canonical_strings(getattr(self, field_name), field_name),
            )
        return self


class ThermalSourceDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-source-declaration"] = (
        "pcbsmith-thermal-source-declaration"
    )
    schema_version: Literal[1] = 1
    source_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    operating_point_id: str = Field(min_length=1)
    component_refs: tuple[str, ...] = ()
    net_refs: tuple[str, ...] = ()
    prediction_requested: bool = False
    prediction_model_id: str | None = None
    prediction_rule_id: str | None = None
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def source_identity_is_coherent(self) -> Self:
        for field_name in ("source_id", "region_id", "operating_point_id"):
            _identity(getattr(self, field_name), field_name)
        for field_name in ("component_refs", "net_refs", "evidence_binding_ids"):
            object.__setattr__(
                self,
                field_name,
                _canonical_strings(getattr(self, field_name), field_name),
            )
        if not self.component_refs and not self.net_refs:
            raise ValueError("thermal sources require component or net identity")
        if self.prediction_requested:
            if self.prediction_rule_id is None:
                raise ValueError("requested temperature prediction requires a rule identity")
            _identity(self.prediction_rule_id, "prediction_rule_id")
            if self.prediction_model_id is not None:
                _identity(self.prediction_model_id, "prediction_model_id")
        elif self.prediction_model_id is not None or self.prediction_rule_id is not None:
            raise ValueError("unrequested temperature prediction cannot carry model/rule identity")
        return self


class ThermalSensitiveDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-sensitive-declaration"] = (
        "pcbsmith-thermal-sensitive-declaration"
    )
    schema_version: Literal[1] = 1
    sensitive_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    component_refs: tuple[str, ...] = ()
    net_refs: tuple[str, ...] = ()
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def sensitive_identity_is_coherent(self) -> Self:
        _identity(self.sensitive_id, "sensitive_id")
        _identity(self.region_id, "region_id")
        for field_name in ("component_refs", "net_refs", "evidence_binding_ids"):
            object.__setattr__(
                self,
                field_name,
                _canonical_strings(getattr(self, field_name), field_name),
            )
        if not self.component_refs and not self.net_refs:
            raise ValueError("thermal sensitive declarations require component or net identity")
        return self


class ThermalSeparationRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-separation-requirement"] = (
        "pcbsmith-thermal-separation-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    sensitive_id: str = Field(min_length=1)
    authority: SemanticAuthorityClass
    minimum_separation_mm: float | None = Field(default=None, ge=0)
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def threshold_and_authority_are_coherent(self) -> Self:
        for field_name in ("requirement_id", "rule_id", "source_id", "sensitive_id"):
            _identity(getattr(self, field_name), field_name)
        if self.authority not in {
            SemanticAuthorityClass.HARD_GEOMETRY,
            SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        }:
            raise ValueError("thermal separation authority must be hard geometry or advisory")
        if (
            self.authority is SemanticAuthorityClass.HARD_GEOMETRY
            and self.minimum_separation_mm is None
        ):
            raise ValueError("hard thermal separation requires an explicit threshold")
        if self.minimum_separation_mm is not None and not math.isfinite(self.minimum_separation_mm):
            raise ValueError("thermal separation threshold must be finite")
        object.__setattr__(
            self,
            "evidence_binding_ids",
            _canonical_strings(self.evidence_binding_ids, "evidence_binding_ids"),
        )
        return self


class ThermalDeclarationCatalog(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-declaration-catalog"] = (
        "pcbsmith-thermal-declaration-catalog"
    )
    schema_version: Literal[1] = 1
    catalog_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    regions: tuple[SemanticRegion, ...] = Field(min_length=1)
    operating_points: tuple[ThermalOperatingPoint, ...] = Field(min_length=1)
    sources: tuple[ThermalSourceDeclaration, ...] = Field(min_length=1)
    sensitive_regions: tuple[ThermalSensitiveDeclaration, ...] = Field(min_length=1)
    separation_requirements: tuple[ThermalSeparationRequirement, ...] = Field(min_length=1)
    prediction_models: tuple[ThermalPredictionModel, ...] = ()

    @model_validator(mode="after")
    def declarations_are_canonical_and_bound(self) -> Self:
        _identity(self.catalog_id, "catalog_id")
        _identity(self.revision, "revision")
        specs: tuple[tuple[str, str, type[SemanticIrModel]], ...] = (
            ("regions", "region_id", SemanticRegion),
            ("operating_points", "operating_point_id", ThermalOperatingPoint),
            ("sources", "source_id", ThermalSourceDeclaration),
            ("sensitive_regions", "sensitive_id", ThermalSensitiveDeclaration),
            ("separation_requirements", "requirement_id", ThermalSeparationRequirement),
            ("prediction_models", "model_id", ThermalPredictionModel),
        )
        for field_name, identity_name, model_type in specs:
            items = tuple(
                sorted(
                    (
                        model_type.model_validate_json(item.model_dump_json())
                        for item in getattr(self, field_name)
                    ),
                    key=lambda item: str(getattr(item, identity_name)),
                )
            )
            identities = tuple(str(getattr(item, identity_name)) for item in items)
            if len(set(identities)) != len(identities):
                raise ValueError(f"{field_name} identities must be unique")
            object.__setattr__(self, field_name, items)
        regions = {item.region_id: item for item in self.regions}
        operating_points = {item.operating_point_id: item for item in self.operating_points}
        sources = {item.source_id: item for item in self.sources}
        sensitives = {item.sensitive_id: item for item in self.sensitive_regions}
        models = {item.model_id: item for item in self.prediction_models}
        for source in self.sources:
            if source.region_id not in regions or source.operating_point_id not in operating_points:
                raise ValueError("thermal source references unknown region/operating point")
            region = regions[source.region_id]
            if (
                region.coordinate_space == "component_local"
                and region.owner_reference not in source.component_refs
            ):
                raise ValueError("component-local thermal source must bind its region owner")
            if source.prediction_model_id is not None and source.prediction_model_id in models:
                if source.source_id not in models[source.prediction_model_id].applicable_source_ids:
                    raise ValueError("thermal prediction model does not cover its source")
        for sensitive in self.sensitive_regions:
            if sensitive.region_id not in regions:
                raise ValueError("thermal sensitive declaration references unknown region")
            region = regions[sensitive.region_id]
            if (
                region.coordinate_space == "component_local"
                and region.owner_reference not in sensitive.component_refs
            ):
                raise ValueError("component-local thermal sensitive region must bind its owner")
        for requirement in self.separation_requirements:
            if requirement.source_id not in sources or requirement.sensitive_id not in sensitives:
                raise ValueError("thermal separation references unknown source/sensitive identity")
        if any(
            source_id not in sources
            for model in self.prediction_models
            for source_id in model.applicable_source_ids
        ):
            raise ValueError("thermal prediction model references unknown source identity")
        return self

    def source_fingerprint(self) -> str:
        return _fingerprint(
            {
                "operating_points": [
                    item.model_dump(mode="json") for item in self.operating_points
                ],
                "sources": [item.model_dump(mode="json") for item in self.sources],
                "sensitive_regions": [
                    item.model_dump(mode="json") for item in self.sensitive_regions
                ],
                "prediction_models": [
                    item.model_dump(mode="json") for item in self.prediction_models
                ],
            }
        )


class ThermalPlacementBinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-placement-binding"] = "pcbsmith-thermal-placement-binding"
    schema_version: Literal[1] = 1
    component_ref: str = Field(min_length=1)
    uuid_path: str = Field(min_length=1)
    footprint: str = Field(min_length=1)
    anchor_x_mm: float
    anchor_y_mm: float
    rotation_deg: float = Field(ge=0, lt=360)
    side: Literal["front", "back"]

    @model_validator(mode="after")
    def placement_is_finite_and_identified(self) -> Self:
        for field_name in ("component_ref", "uuid_path", "footprint"):
            _identity(getattr(self, field_name), field_name)
        if not all(
            math.isfinite(value)
            for value in (self.anchor_x_mm, self.anchor_y_mm, self.rotation_deg)
        ):
            raise ValueError("thermal placement coordinates must be finite")
        return self


class ThermalResolvedRegion(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-resolved-region"] = "pcbsmith-thermal-resolved-region"
    schema_version: Literal[1] = 1
    region_id: str = Field(min_length=1)
    source_region_fingerprint: str
    coordinate_space: Literal["board", "component_local"]
    owner_reference: str | None
    placement_binding_fingerprint: str | None
    compound: ExactPlanarCompound | None
    verification: SemanticVerification
    maximum_error_mm: float | None

    @model_validator(mode="after")
    def resolved_geometry_is_coherent(self) -> Self:
        _identity(self.region_id, "region_id")
        _sha256(self.source_region_fingerprint, "source_region_fingerprint")
        if self.coordinate_space == "component_local":
            if self.owner_reference is None:
                raise ValueError("resolved local region requires owner identity")
            _identity(self.owner_reference, "owner_reference")
            if self.placement_binding_fingerprint is not None:
                _sha256(
                    self.placement_binding_fingerprint,
                    "placement_binding_fingerprint",
                )
        elif self.owner_reference is not None or self.placement_binding_fingerprint is not None:
            raise ValueError("resolved board region cannot carry component placement identity")
        if self.verification is SemanticVerification.EXACT:
            if self.compound is None or self.maximum_error_mm is not None:
                raise ValueError("exact resolved region requires geometry and no error")
        elif self.verification is SemanticVerification.BOUNDED_APPROXIMATION:
            if (
                self.compound is None
                or self.maximum_error_mm is None
                or not math.isfinite(self.maximum_error_mm)
                or self.maximum_error_mm <= 0
            ):
                raise ValueError("bounded resolved region requires positive finite error")
        elif self.compound is not None or self.maximum_error_mm is not None:
            raise ValueError("unsupported resolved region cannot carry geometry/error")
        return self


class ThermalRationalPoint(SemanticIrModel):
    """Canonical exact rational point suitable for JSON audit/revalidation."""

    schema_id: Literal["pcbsmith-thermal-rational-point"] = "pcbsmith-thermal-rational-point"
    schema_version: Literal[1] = 1
    x_numerator: int
    x_denominator: int = Field(gt=0)
    y_numerator: int
    y_denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def fractions_are_reduced(self) -> Self:
        x_value = Fraction(self.x_numerator, self.x_denominator)
        y_value = Fraction(self.y_numerator, self.y_denominator)
        if (x_value.numerator, x_value.denominator) != (
            self.x_numerator,
            self.x_denominator,
        ):
            raise ValueError("thermal rational x coordinate must be reduced")
        if (y_value.numerator, y_value.denominator) != (
            self.y_numerator,
            self.y_denominator,
        ):
            raise ValueError("thermal rational y coordinate must be reduced")
        return self

    @classmethod
    def from_point(cls, point: tuple[Fraction, Fraction]) -> Self:
        return cls(
            x_numerator=point[0].numerator,
            x_denominator=point[0].denominator,
            y_numerator=point[1].numerator,
            y_denominator=point[1].denominator,
        )

    def as_point(self) -> tuple[Fraction, Fraction]:
        return (
            Fraction(self.x_numerator, self.x_denominator),
            Fraction(self.y_numerator, self.y_denominator),
        )


class ThermalUnsupportedCauseKind(StrEnum):
    """Typed reason a separation witness could not be evaluated."""

    REGION_GEOMETRY_UNSUPPORTED = "region_geometry_unsupported"
    COMPONENT_MISSING_LAYOUT = "component_missing_layout"
    COMPONENT_MISSING_NETLIST = "component_missing_netlist"
    NETLIST_UNAVAILABLE = "netlist_unavailable"
    NET_MISSING_NETLIST = "net_missing_netlist"


class ThermalUnsupportedCause(SemanticIrModel):
    """Canonical, role-specific fail-closed cause retained for revalidation."""

    schema_id: Literal["pcbsmith-thermal-unsupported-cause"] = "pcbsmith-thermal-unsupported-cause"
    schema_version: Literal[1] = 1
    role: Literal["source", "sensitive"]
    kind: ThermalUnsupportedCauseKind
    identity: str = Field(min_length=1)

    @model_validator(mode="after")
    def cause_is_identified(self) -> Self:
        _identity(self.identity, "identity")
        return self

    def sort_key(self) -> tuple[str, str, str]:
        return (self.role, self.kind.value, self.identity)

    def message_token(self) -> str:
        return f"{self.role}:{self.kind.value}:{self.identity}"


def derive_thermal_unsupported_causes(
    source: ThermalSourceDeclaration,
    sensitive: ThermalSensitiveDeclaration,
    source_region: ThermalResolvedRegion,
    sensitive_region: ThermalResolvedRegion,
    *,
    layout_component_refs: Sequence[str],
    netlist_component_refs: Sequence[str] | None,
    netlist_net_refs: Sequence[str] | None,
) -> tuple[ThermalUnsupportedCause, ...]:
    """Derive every fail-closed cause from retained live identity and geometry state."""

    if (netlist_component_refs is None) != (netlist_net_refs is None):
        raise ValueError("thermal netlist identity inventories must be present together")
    layout_refs = set(layout_component_refs)
    netlist_components = None if netlist_component_refs is None else set(netlist_component_refs)
    netlist_nets = None if netlist_net_refs is None else set(netlist_net_refs)
    causes: list[ThermalUnsupportedCause] = []
    for role, declaration, region in (
        ("source", source, source_region),
        ("sensitive", sensitive, sensitive_region),
    ):
        if region.compound is None or region.verification is SemanticVerification.UNSUPPORTED:
            causes.append(
                ThermalUnsupportedCause(
                    role=role,
                    kind=ThermalUnsupportedCauseKind.REGION_GEOMETRY_UNSUPPORTED,
                    identity=region.region_id,
                )
            )
        causes.extend(
            ThermalUnsupportedCause(
                role=role,
                kind=ThermalUnsupportedCauseKind.COMPONENT_MISSING_LAYOUT,
                identity=reference,
            )
            for reference in declaration.component_refs
            if reference not in layout_refs
        )
        if netlist_components is not None:
            causes.extend(
                ThermalUnsupportedCause(
                    role=role,
                    kind=ThermalUnsupportedCauseKind.COMPONENT_MISSING_NETLIST,
                    identity=reference,
                )
                for reference in declaration.component_refs
                if reference not in netlist_components
            )
        if netlist_nets is None:
            causes.extend(
                ThermalUnsupportedCause(
                    role=role,
                    kind=ThermalUnsupportedCauseKind.NETLIST_UNAVAILABLE,
                    identity=net_name,
                )
                for net_name in declaration.net_refs
            )
        else:
            causes.extend(
                ThermalUnsupportedCause(
                    role=role,
                    kind=ThermalUnsupportedCauseKind.NET_MISSING_NETLIST,
                    identity=net_name,
                )
                for net_name in declaration.net_refs
                if net_name not in netlist_nets
            )
    return tuple(sorted(causes, key=lambda item: item.sort_key()))


class ThermalSeparationEvidence(SemanticIrModel):
    """Auditable closest-region witness retained beside semantic metrics/findings."""

    schema_id: Literal["pcbsmith-thermal-separation-evidence"] = (
        "pcbsmith-thermal-separation-evidence"
    )
    schema_version: Literal[1] = 1
    requirement_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    sensitive_id: str = Field(min_length=1)
    source_region_id: str = Field(min_length=1)
    sensitive_region_id: str = Field(min_length=1)
    authority: SemanticAuthorityClass
    verification: SemanticVerification
    relation: PlanarRelation | None
    nominal_squared_distance_numerator: int | None
    nominal_squared_distance_denominator: int | None = Field(default=None, gt=0)
    closest_source_point: ThermalRationalPoint | None
    closest_sensitive_point: ThermalRationalPoint | None
    maximum_error_mm: float | None = Field(default=None, ge=0)
    conservative_distance_mm: float | None = Field(default=None, ge=0)
    unsupported_causes: tuple[ThermalUnsupportedCause, ...] = ()
    disposition: SemanticDisposition
    metric_ids: tuple[str, ...] = Field(min_length=1)
    finding_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def witness_is_canonical_and_coherent(self) -> Self:
        for field_name in (
            "requirement_id",
            "rule_id",
            "source_id",
            "sensitive_id",
            "source_region_id",
            "sensitive_region_id",
            "finding_id",
        ):
            _identity(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "metric_ids",
            _canonical_strings(self.metric_ids, "metric_ids"),
        )
        source_point = (
            None
            if self.closest_source_point is None
            else ThermalRationalPoint.model_validate_json(
                self.closest_source_point.model_dump_json()
            )
        )
        sensitive_point = (
            None
            if self.closest_sensitive_point is None
            else ThermalRationalPoint.model_validate_json(
                self.closest_sensitive_point.model_dump_json()
            )
        )
        causes = tuple(
            sorted(
                (
                    ThermalUnsupportedCause.model_validate_json(item.model_dump_json())
                    for item in self.unsupported_causes
                ),
                key=lambda item: item.sort_key(),
            )
        )
        if len({item.sort_key() for item in causes}) != len(causes):
            raise ValueError("thermal unsupported causes must be unique")
        unsupported = self.verification is SemanticVerification.UNSUPPORTED
        exact_fields_missing = (
            self.relation is None
            or self.nominal_squared_distance_numerator is None
            or self.nominal_squared_distance_denominator is None
            or source_point is None
            or sensitive_point is None
            or self.conservative_distance_mm is None
        )
        if unsupported:
            if (
                not causes
                or any(
                    value is not None
                    for value in (
                        self.relation,
                        self.nominal_squared_distance_numerator,
                        self.nominal_squared_distance_denominator,
                        source_point,
                        sensitive_point,
                        self.maximum_error_mm,
                        self.conservative_distance_mm,
                    )
                )
                or self.disposition is not SemanticDisposition.UNVERIFIED
            ):
                raise ValueError("unsupported thermal evidence cannot fabricate geometry")
        else:
            if causes:
                raise ValueError("supported thermal evidence cannot carry unsupported causes")
            if exact_fields_missing:
                raise ValueError("supported thermal evidence requires exact witness geometry")
            assert self.nominal_squared_distance_numerator is not None
            assert self.nominal_squared_distance_denominator is not None
            assert self.relation is not None
            assert source_point is not None
            assert sensitive_point is not None
            squared = Fraction(
                self.nominal_squared_distance_numerator,
                self.nominal_squared_distance_denominator,
            )
            if (squared.numerator, squared.denominator) != (
                self.nominal_squared_distance_numerator,
                self.nominal_squared_distance_denominator,
            ):
                raise ValueError("thermal squared-distance fraction must be reduced")
            if (self.relation is PlanarRelation.DISJOINT) != (squared > 0):
                raise ValueError("thermal relation and exact squared distance disagree")
            if squared == 0 and source_point != sensitive_point:
                raise ValueError("zero-distance thermal closest points must coincide")
            if self.verification is SemanticVerification.EXACT:
                if self.maximum_error_mm is not None:
                    raise ValueError("exact thermal evidence cannot carry approximation error")
            elif self.maximum_error_mm is None or self.maximum_error_mm <= 0:
                raise ValueError("bounded thermal evidence requires positive maximum error")
        if (
            self.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
            and self.disposition is SemanticDisposition.FAIL
        ):
            raise ValueError("advisory thermal evidence cannot fail")
        object.__setattr__(self, "closest_source_point", source_point)
        object.__setattr__(self, "closest_sensitive_point", sensitive_point)
        object.__setattr__(self, "unsupported_causes", causes)
        return self

    def squared_distance(self) -> Fraction | None:
        if (
            self.nominal_squared_distance_numerator is None
            or self.nominal_squared_distance_denominator is None
        ):
            return None
        return Fraction(
            self.nominal_squared_distance_numerator,
            self.nominal_squared_distance_denominator,
        )


class ThermalEvaluationResult(SemanticIrModel):
    """Self-contained result with context, declarations, placed geometry, and semantics."""

    schema_id: Literal["pcbsmith-thermal-evaluation-result"] = "pcbsmith-thermal-evaluation-result"
    schema_version: Literal[1] = 1
    context: SemanticEvaluationContext
    declarations: ThermalDeclarationCatalog
    evaluation_date: date
    board_layout_fingerprint: str
    netlist_fingerprint: str | None = None
    netlist_component_refs: tuple[str, ...] | None = None
    netlist_net_refs: tuple[str, ...] | None = None
    placement_candidate_fingerprint: str | None = None
    placement_bindings: tuple[ThermalPlacementBinding, ...]
    resolved_regions: tuple[ThermalResolvedRegion, ...]
    separation_evidence: tuple[ThermalSeparationEvidence, ...]
    geometry_fingerprint: str
    source_fingerprint: str
    input_fingerprint: str
    metrics: tuple[SemanticMetric, ...]
    findings: tuple[SemanticFinding, ...]
    semantic_result: SemanticLayoutResult

    @field_validator(
        "board_layout_fingerprint",
        "geometry_fingerprint",
        "source_fingerprint",
        "input_fingerprint",
    )
    @classmethod
    def required_hash_is_sha256(cls, value: str, info: Any) -> str:
        return _sha256(value, info.field_name)

    @field_validator("netlist_fingerprint", "placement_candidate_fingerprint")
    @classmethod
    def optional_hash_is_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_is_self_contained_and_truthful(self) -> Self:
        context = SemanticEvaluationContext.model_validate_json(self.context.model_dump_json())
        declarations = ThermalDeclarationCatalog.model_validate_json(
            self.declarations.model_dump_json()
        )
        bindings = tuple(
            sorted(
                (
                    ThermalPlacementBinding.model_validate_json(item.model_dump_json())
                    for item in self.placement_bindings
                ),
                key=lambda item: item.component_ref,
            )
        )
        netlist_component_refs = (
            None
            if self.netlist_component_refs is None
            else _canonical_strings(self.netlist_component_refs, "netlist_component_refs")
        )
        netlist_net_refs = (
            None
            if self.netlist_net_refs is None
            else _canonical_strings(self.netlist_net_refs, "netlist_net_refs")
        )
        if (self.netlist_fingerprint is None) != (netlist_component_refs is None):
            raise ValueError("thermal netlist fingerprint and component inventory disagree")
        if (self.netlist_fingerprint is None) != (netlist_net_refs is None):
            raise ValueError("thermal netlist fingerprint and net inventory disagree")
        resolved = tuple(
            sorted(
                (
                    ThermalResolvedRegion.model_validate_json(item.model_dump_json())
                    for item in self.resolved_regions
                ),
                key=lambda item: item.region_id,
            )
        )
        separation_evidence = tuple(
            sorted(
                (
                    ThermalSeparationEvidence.model_validate_json(item.model_dump_json())
                    for item in self.separation_evidence
                ),
                key=lambda item: item.requirement_id,
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
        semantic_result = SemanticLayoutResult.model_validate_json(
            self.semantic_result.model_dump_json()
        )
        if self.evaluation_date != context.evaluation_date:
            raise ValueError("thermal result evaluation_date differs from semantic context")
        if len({item.component_ref for item in bindings}) != len(bindings):
            raise ValueError("thermal placement binding references must be unique")
        if len({item.region_id for item in resolved}) != len(resolved):
            raise ValueError("thermal resolved region identities must be unique")
        region_by_id = {item.region_id: item for item in declarations.regions}
        if set(region_by_id) != {item.region_id for item in resolved}:
            raise ValueError("thermal result must resolve every declared region exactly once")
        binding_by_ref = {item.component_ref: item for item in bindings}
        for resolved_region in resolved:
            source_region = region_by_id[resolved_region.region_id]
            if resolved_region.source_region_fingerprint != source_region.semantic_fingerprint():
                raise ValueError("thermal resolved region source fingerprint is stale")
            if (
                resolved_region.coordinate_space != source_region.coordinate_space
                or resolved_region.owner_reference != source_region.owner_reference
            ):
                raise ValueError("thermal resolved region coordinate binding is stale")
            if source_region.coordinate_space == "component_local":
                owner = source_region.owner_reference
                expected = None if owner not in binding_by_ref else binding_by_ref[owner]
                expected_fingerprint = None if expected is None else expected.semantic_fingerprint()
                if resolved_region.placement_binding_fingerprint != expected_fingerprint:
                    raise ValueError("thermal resolved region placement binding is stale")
        semantic_regions = {item.region_id: item for item in context.semantic_profile.regions}
        if any(
            region_id not in semantic_regions
            or semantic_regions[region_id].semantic_fingerprint() != region.semantic_fingerprint()
            for region_id, region in region_by_id.items()
        ):
            raise ValueError("thermal regions are not bound to the semantic context")
        evidence_ids = {item.binding_id for item in context.semantic_profile.evidence_bindings}
        declaration_evidence: set[str] = set()
        for region in declarations.regions:
            declaration_evidence.update(region.source_binding_ids)
        for collection in (
            declarations.operating_points,
            declarations.sources,
            declarations.sensitive_regions,
            declarations.separation_requirements,
            declarations.prediction_models,
        ):
            for declaration in collection:
                declaration_evidence.update(declaration.evidence_binding_ids)
        if not declaration_evidence.issubset(evidence_ids):
            raise ValueError("thermal declarations reference unknown evidence bindings")
        source_by_id = {item.source_id: item for item in declarations.sources}
        sensitive_by_id = {item.sensitive_id: item for item in declarations.sensitive_regions}
        context_rules = {item.rule_id: item for item in context.semantic_profile.rules}
        allowed_rule_ids: set[str] = set()
        for requirement in declarations.separation_requirements:
            rule = context_rules.get(requirement.rule_id)
            declared_source = source_by_id[requirement.source_id]
            declared_sensitive = sensitive_by_id[requirement.sensitive_id]
            expected_regions = {declared_source.region_id, declared_sensitive.region_id}
            if (
                rule is None
                or rule.authority is not requirement.authority
                or not expected_regions.issubset(rule.geometry_region_ids)
                or not set(requirement.evidence_binding_ids).issubset(rule.evidence_binding_ids)
            ):
                raise ValueError("thermal separation rule is not bound to semantic authority")
            allowed_rule_ids.add(requirement.rule_id)
        for prediction_source in declarations.sources:
            if not prediction_source.prediction_requested:
                continue
            rule = context_rules.get(prediction_source.prediction_rule_id or "")
            if (
                rule is None
                or rule.authority is not SemanticAuthorityClass.ADVISORY_HYPOTHESIS
                or not set(prediction_source.evidence_binding_ids).issubset(
                    rule.evidence_binding_ids
                )
            ):
                raise ValueError("thermal prediction rule is not bound to advisory authority")
            allowed_rule_ids.add(rule.rule_id)
        evidence_by_requirement = {item.requirement_id: item for item in separation_evidence}
        requirement_by_id = {
            item.requirement_id: item for item in declarations.separation_requirements
        }
        if len(evidence_by_requirement) != len(separation_evidence) or set(
            evidence_by_requirement
        ) != set(requirement_by_id):
            raise ValueError(
                "thermal result requires one separation evidence record per requirement"
            )
        finding_by_id = {item.finding_id: item for item in findings}
        metric_ids = {item.metric_id for item in metrics}
        metric_by_id = {item.metric_id: item for item in metrics}
        resolved_by_id = {item.region_id: item for item in resolved}
        for requirement_id, evidence in evidence_by_requirement.items():
            requirement = requirement_by_id[requirement_id]
            declared_source = source_by_id[requirement.source_id]
            declared_sensitive = sensitive_by_id[requirement.sensitive_id]
            resolved_source_region = resolved_by_id[declared_source.region_id]
            resolved_sensitive_region = resolved_by_id[declared_sensitive.region_id]
            if (
                evidence.rule_id != requirement.rule_id
                or evidence.source_id != requirement.source_id
                or evidence.sensitive_id != requirement.sensitive_id
                or evidence.source_region_id != declared_source.region_id
                or evidence.sensitive_region_id != declared_sensitive.region_id
                or evidence.authority is not requirement.authority
            ):
                raise ValueError("thermal separation evidence declaration binding is stale")
            finding = finding_by_id.get(evidence.finding_id)
            expected_object_ids = tuple(
                sorted((declared_source.source_id, declared_sensitive.sensitive_id))
            )
            expected_component_refs = tuple(
                sorted({*declared_source.component_refs, *declared_sensitive.component_refs})
            )
            expected_net_refs = tuple(
                sorted({*declared_source.net_refs, *declared_sensitive.net_refs})
            )
            expected_region_ids = tuple(
                sorted((declared_source.region_id, declared_sensitive.region_id))
            )
            expected_evidence_ids = tuple(
                sorted(
                    {
                        *declared_source.evidence_binding_ids,
                        *declared_sensitive.evidence_binding_ids,
                        *requirement.evidence_binding_ids,
                        *region_by_id[declared_source.region_id].source_binding_ids,
                        *region_by_id[declared_sensitive.region_id].source_binding_ids,
                    }
                )
            )
            if (
                finding is None
                or finding.rule_id != requirement.rule_id
                or finding.authority is not requirement.authority
                or finding.disposition is not evidence.disposition
                or finding.verification is not evidence.verification
                or finding.object_ids != expected_object_ids
                or finding.component_refs != expected_component_refs
                or finding.net_refs != expected_net_refs
                or finding.region_ids != expected_region_ids
                or finding.evidence_binding_ids != expected_evidence_ids
                or set(finding.metric_ids) != set(evidence.metric_ids)
                or not set(evidence.metric_ids).issubset(metric_ids)
            ):
                raise ValueError("thermal separation evidence finding/metric binding is stale")
            expected_causes = derive_thermal_unsupported_causes(
                declared_source,
                declared_sensitive,
                resolved_source_region,
                resolved_sensitive_region,
                layout_component_refs=tuple(binding_by_ref),
                netlist_component_refs=netlist_component_refs,
                netlist_net_refs=netlist_net_refs,
            )
            unsupported = bool(expected_causes)
            if unsupported:
                expected_metric_id = (
                    f"thermal:separation:{declared_source.source_id}:"
                    f"{declared_sensitive.sensitive_id}"
                )
                metric = metric_by_id.get(expected_metric_id)

                if (
                    evidence.verification is not SemanticVerification.UNSUPPORTED
                    or evidence.unsupported_causes != expected_causes
                    or evidence.disposition is not SemanticDisposition.UNVERIFIED
                    or evidence.relation is not None
                    or evidence.squared_distance() is not None
                    or evidence.closest_source_point is not None
                    or evidence.closest_sensitive_point is not None
                    or evidence.maximum_error_mm is not None
                    or evidence.conservative_distance_mm is not None
                    or evidence.metric_ids != (expected_metric_id,)
                    or metric is None
                    or metric.verification is not SemanticVerification.UNSUPPORTED
                    or metric.quantity is not None
                    or metric.object_ids != expected_object_ids
                    or finding.disposition is not SemanticDisposition.UNVERIFIED
                    or finding.verification is not SemanticVerification.UNSUPPORTED
                ):
                    raise ValueError("unsupported thermal evidence is not derived")
                expected_message = "Thermal separation is unverified: " + ", ".join(
                    item.message_token() for item in expected_causes
                )
                if (
                    finding.message != expected_message
                    or finding.suggested_action
                    != "Bind supported geometry and live component/net identities"
                ):
                    raise ValueError("unsupported thermal finding explanation is stale")
                continue
            if evidence.unsupported_causes:
                raise ValueError("supported thermal geometry cannot retain unsupported causes")
            assert resolved_source_region.compound is not None
            assert resolved_sensitive_region.compound is not None
            witness = compound_distance_witness(
                resolved_source_region.compound,
                resolved_sensitive_region.compound,
            )
            maximum_error = compose_thermal_position_error(
                resolved_source_region.maximum_error_mm or 0.0,
                resolved_sensitive_region.maximum_error_mm or 0.0,
            )
            expected_verification = (
                SemanticVerification.BOUNDED_APPROXIMATION
                if maximum_error > 0
                else SemanticVerification.EXACT
            )
            if (
                evidence.verification is not expected_verification
                or evidence.relation is not witness.relation
                or evidence.squared_distance() != witness.squared_distance
                or evidence.closest_source_point is None
                or evidence.closest_sensitive_point is None
                or evidence.closest_source_point.as_point() != witness.first_point
                or evidence.closest_sensitive_point.as_point() != witness.second_point
                or evidence.maximum_error_mm != (maximum_error if maximum_error > 0 else None)
                or evidence.conservative_distance_mm
                != conservative_thermal_distance_mm(
                    witness.squared_distance,
                    maximum_error,
                )
            ):
                raise ValueError("thermal separation evidence exact witness is stale")
            if requirement.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS:
                expected_disposition = SemanticDisposition.ADVISORY
            else:
                threshold = requirement.minimum_separation_mm
                if threshold is None:
                    expected_disposition = SemanticDisposition.UNVERIFIED
                elif maximum_error == 0:
                    required = Fraction(str(threshold))
                    expected_disposition = (
                        SemanticDisposition.PASS
                        if witness.squared_distance >= required * required
                        else SemanticDisposition.FAIL
                    )
                else:
                    required = Fraction(str(math.nextafter(threshold + maximum_error, math.inf)))
                    expected_disposition = (
                        SemanticDisposition.PASS
                        if witness.squared_distance >= required * required
                        else SemanticDisposition.UNVERIFIED
                    )
            if evidence.disposition is not expected_disposition:
                raise ValueError("thermal separation evidence disposition is not derived")
        if any(item.rule_id not in allowed_rule_ids for item in findings):
            raise ValueError("thermal finding references an undeclared thermal rule")
        if any(not set(item.evidence_binding_ids).issubset(evidence_ids) for item in findings):
            raise ValueError("thermal finding references unknown evidence")
        if any(
            item.quantity is not None
            and not set(item.quantity.source_binding_ids).issubset(evidence_ids)
            for item in metrics
        ):
            raise ValueError("thermal metric references unknown evidence")
        expected_geometry = _fingerprint([item.model_dump(mode="json") for item in resolved])
        if self.geometry_fingerprint != expected_geometry:
            raise ValueError("thermal geometry fingerprint is stale")
        if self.source_fingerprint != declarations.source_fingerprint():
            raise ValueError("thermal source fingerprint is stale")
        expected_semantic = SemanticLayoutResult.build(
            context_fingerprint=context.semantic_fingerprint(),
            declarations_fingerprint=declarations.semantic_fingerprint(),
            geometry_fingerprint=self.geometry_fingerprint,
            placement_candidate_fingerprint=self.placement_candidate_fingerprint,
            metrics=metrics,
            findings=findings,
        )
        if semantic_result != expected_semantic:
            raise ValueError("thermal semantic result is not derived from metrics/findings")
        inputs = {
            "board_layout_fingerprint": self.board_layout_fingerprint,
            "netlist_fingerprint": self.netlist_fingerprint,
            "netlist_component_refs": netlist_component_refs,
            "netlist_net_refs": netlist_net_refs,
            "placement_candidate_fingerprint": self.placement_candidate_fingerprint,
            "context_fingerprint": context.semantic_fingerprint(),
            "declarations_fingerprint": declarations.semantic_fingerprint(),
            "geometry_fingerprint": self.geometry_fingerprint,
            "source_fingerprint": self.source_fingerprint,
            "placement_binding_fingerprints": [item.semantic_fingerprint() for item in bindings],
            "separation_evidence_fingerprints": [
                item.semantic_fingerprint() for item in separation_evidence
            ],
        }
        if self.input_fingerprint != _fingerprint(inputs):
            raise ValueError("thermal input fingerprint is stale")
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "netlist_component_refs", netlist_component_refs)
        object.__setattr__(self, "netlist_net_refs", netlist_net_refs)
        object.__setattr__(self, "declarations", declarations)
        object.__setattr__(self, "placement_bindings", bindings)
        object.__setattr__(self, "resolved_regions", resolved)
        object.__setattr__(self, "separation_evidence", separation_evidence)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "semantic_result", semantic_result)
        return self

    @classmethod
    def build(
        cls,
        *,
        context: SemanticEvaluationContext,
        declarations: ThermalDeclarationCatalog,
        board_layout_fingerprint: str,
        netlist_fingerprint: str | None,
        netlist_component_refs: Sequence[str] | None,
        netlist_net_refs: Sequence[str] | None,
        placement_candidate_fingerprint: str | None,
        placement_bindings: Sequence[ThermalPlacementBinding],
        resolved_regions: Sequence[ThermalResolvedRegion],
        separation_evidence: Sequence[ThermalSeparationEvidence],
        metrics: Sequence[SemanticMetric],
        findings: Sequence[SemanticFinding],
    ) -> Self:
        canonical_bindings = tuple(sorted(placement_bindings, key=lambda item: item.component_ref))
        canonical_netlist_component_refs = (
            None
            if netlist_component_refs is None
            else _canonical_strings(netlist_component_refs, "netlist_component_refs")
        )
        canonical_netlist_net_refs = (
            None
            if netlist_net_refs is None
            else _canonical_strings(netlist_net_refs, "netlist_net_refs")
        )
        canonical_regions = tuple(sorted(resolved_regions, key=lambda item: item.region_id))
        canonical_evidence = tuple(
            sorted(separation_evidence, key=lambda item: item.requirement_id)
        )
        canonical_metrics = tuple(sorted(metrics, key=lambda item: item.metric_id))
        canonical_findings = tuple(sorted(findings, key=lambda item: item.finding_id))
        geometry_fingerprint = _fingerprint(
            [item.model_dump(mode="json") for item in canonical_regions]
        )
        source_fingerprint = declarations.source_fingerprint()
        inputs = {
            "board_layout_fingerprint": board_layout_fingerprint,
            "netlist_fingerprint": netlist_fingerprint,
            "netlist_component_refs": canonical_netlist_component_refs,
            "netlist_net_refs": canonical_netlist_net_refs,
            "placement_candidate_fingerprint": placement_candidate_fingerprint,
            "context_fingerprint": context.semantic_fingerprint(),
            "declarations_fingerprint": declarations.semantic_fingerprint(),
            "geometry_fingerprint": geometry_fingerprint,
            "source_fingerprint": source_fingerprint,
            "placement_binding_fingerprints": [
                item.semantic_fingerprint() for item in canonical_bindings
            ],
            "separation_evidence_fingerprints": [
                item.semantic_fingerprint() for item in canonical_evidence
            ],
        }
        semantic_result = SemanticLayoutResult.build(
            context_fingerprint=context.semantic_fingerprint(),
            declarations_fingerprint=declarations.semantic_fingerprint(),
            geometry_fingerprint=geometry_fingerprint,
            placement_candidate_fingerprint=placement_candidate_fingerprint,
            metrics=canonical_metrics,
            findings=canonical_findings,
        )
        return cls(
            context=context,
            declarations=declarations,
            evaluation_date=context.evaluation_date,
            board_layout_fingerprint=board_layout_fingerprint,
            netlist_fingerprint=netlist_fingerprint,
            netlist_component_refs=canonical_netlist_component_refs,
            netlist_net_refs=canonical_netlist_net_refs,
            placement_candidate_fingerprint=placement_candidate_fingerprint,
            placement_bindings=canonical_bindings,
            resolved_regions=canonical_regions,
            separation_evidence=canonical_evidence,
            geometry_fingerprint=geometry_fingerprint,
            source_fingerprint=source_fingerprint,
            input_fingerprint=_fingerprint(inputs),
            metrics=canonical_metrics,
            findings=canonical_findings,
            semantic_result=semantic_result,
        )
