"""Engine-neutral, versioned placement probe interchange models.

R5.0 defines only canonical poses, target/probe policy, fixed budgets, and
lossless-probe audit records.  It deliberately contains no KiCad geometry,
legalization, candidate generation, surrogate scoring, or routing behavior.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pcbsmith.edge_interface_ir import EdgeInterfaceAuthorityResult
from pcbsmith.placement_geometry import ExactPlanarCompound


def _require_identity(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a canonical non-empty identity")
    return value


def _canonical_identities(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(values))
    if len(set(canonical)) != len(canonical):
        raise ValueError(f"{field_name} must contain unique identities")
    return tuple(_require_identity(value, field_name) for value in canonical)


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


class PlacementIrModel(BaseModel):
    """Frozen placement IR with canonical semantic serialization."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    def semantic_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def semantic_fingerprint(self) -> str:
        return hashlib.sha256(self.semantic_json().encode("utf-8")).hexdigest()


class ComponentPose(PlacementIrModel):
    """One exact declared board pose with explicit front/back semantics."""

    schema_id: Literal["pcbsmith-component-pose"] = "pcbsmith-component-pose"
    schema_version: Literal[1] = 1
    reference: str = Field(min_length=1)
    x_mm: float
    y_mm: float
    rotation_deg: float
    side: Literal["front", "back"]

    @field_validator("reference")
    @classmethod
    def reference_is_canonical(cls, value: str) -> str:
        return _require_identity(value, "reference")

    @field_validator("x_mm", "y_mm")
    @classmethod
    def coordinate_is_finite(cls, value: float, info: Any) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be finite")
        return value

    @field_validator("rotation_deg")
    @classmethod
    def rotation_is_finite_and_canonical(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("rotation_deg must be finite")
        normalized = value % 360.0
        return 0.0 if normalized == 0.0 else normalized


class PlacementTargetPolicy(PlacementIrModel):
    """Exact known-net universe and selected route-stripping target set."""

    schema_id: Literal["pcbsmith-placement-target-policy"] = "pcbsmith-placement-target-policy"
    schema_version: Literal[1] = 1
    known_net_names: tuple[str, ...] = Field(min_length=1)
    target_net_names: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def nets_are_canonical_and_known(self) -> Self:
        known = _canonical_identities(self.known_net_names, "known_net_names")
        targets = _canonical_identities(self.target_net_names, "target_net_names")
        unknown = tuple(sorted(set(targets) - set(known)))
        if unknown:
            raise ValueError(f"target nets are absent from the known net set: {unknown!r}")
        object.__setattr__(self, "known_net_names", known)
        object.__setattr__(self, "target_net_names", targets)
        return self


class PlacementProbePolicy(PlacementIrModel):
    """R5.0 pose-map completeness and lossless mutation policy."""

    schema_id: Literal["pcbsmith-placement-probe-policy"] = "pcbsmith-placement-probe-policy"
    schema_version: Literal[1] = 1
    required_references: tuple[str, ...] = ()
    allow_unchanged_non_target_references: bool = False
    pose_semantics_id: Literal["sparse-template-preserving-v1"] = "sparse-template-preserving-v1"

    @model_validator(mode="after")
    def references_are_canonical(self) -> Self:
        object.__setattr__(
            self,
            "required_references",
            _canonical_identities(self.required_references, "required_references"),
        )
        return self


class PlacementBudget(PlacementIrModel):
    """Full fixed R5 work budget; R5.0 records but does not consume later stages."""

    schema_id: Literal["pcbsmith-placement-budget"] = "pcbsmith-placement-budget"
    schema_version: Literal[1] = 1
    max_proposals: int = Field(ge=0)
    max_legalization_evaluations: int = Field(ge=0)
    max_surrogate_evaluations: int = Field(ge=0)
    max_corridor_plans: int = Field(ge=0)
    max_detailed_candidates: int = Field(ge=0)
    max_exact_checks: int = Field(ge=0)
    max_r3_geometry_cells_per_candidate: int = Field(ge=0)
    max_r3_geometry_portals_per_candidate: int = Field(ge=0)
    max_r3_expansions_per_candidate: int = Field(ge=0)
    max_r2_passes_per_candidate: int = Field(ge=0)
    max_r2_expansions_per_candidate: int = Field(ge=0)
    max_r2_expansions_per_net: int = Field(ge=0)
    max_r2_stagnant_passes: int = Field(ge=0)


class PlacementProbeTelemetry(PlacementIrModel):
    """Deterministic audit record for one lossless template probe build."""

    schema_id: Literal["pcbsmith-placement-probe-telemetry"] = "pcbsmith-placement-probe-telemetry"
    schema_version: Literal[1] = 1
    template_fingerprint: str
    target_policy_fingerprint: str
    probe_policy_fingerprint: str
    budget_fingerprint: str
    pose_fingerprint: str
    probe_layout_fingerprint: str
    template_reference_order: tuple[str, ...] = Field(min_length=1)
    explicit_pose_references: tuple[str, ...]
    preserved_pose_references: tuple[str, ...]
    changed_layout_fields: tuple[str, ...]
    stripped_segment_count: int = Field(ge=0)
    stripped_via_count: int = Field(ge=0)

    @field_validator(
        "template_fingerprint",
        "target_policy_fingerprint",
        "probe_policy_fingerprint",
        "budget_fingerprint",
        "pose_fingerprint",
        "probe_layout_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def collections_are_canonical(self) -> Self:
        order = self.template_reference_order
        if len(set(order)) != len(order):
            raise ValueError("template_reference_order must contain unique references")
        explicit = _canonical_identities(
            self.explicit_pose_references,
            "explicit_pose_references",
        )
        preserved = _canonical_identities(
            self.preserved_pose_references,
            "preserved_pose_references",
        )
        if set(explicit) & set(preserved):
            raise ValueError("explicit and preserved pose references must be disjoint")
        if set(explicit) | set(preserved) != set(order):
            raise ValueError("explicit and preserved poses must cover the template")
        changed = _canonical_identities(self.changed_layout_fields, "changed_layout_fields")
        object.__setattr__(self, "explicit_pose_references", explicit)
        object.__setattr__(self, "preserved_pose_references", preserved)
        object.__setattr__(self, "changed_layout_fields", changed)
        return self


class PlacementProbeResult(PlacementIrModel):
    """Versioned semantic result paired with a KiCad materialized probe."""

    schema_id: Literal["pcbsmith-placement-probe-result"] = "pcbsmith-placement-probe-result"
    schema_version: Literal[1] = 1
    target_policy: PlacementTargetPolicy
    probe_policy: PlacementProbePolicy
    budget: PlacementBudget
    poses: tuple[ComponentPose, ...] = Field(min_length=1)
    telemetry: PlacementProbeTelemetry

    @model_validator(mode="after")
    def nested_fingerprints_and_poses_are_coherent(self) -> Self:
        poses = tuple(sorted(self.poses, key=lambda item: item.reference))
        if len({pose.reference for pose in poses}) != len(poses):
            raise ValueError("placement probe poses must have unique references")
        if {pose.reference for pose in poses} != set(self.telemetry.template_reference_order):
            raise ValueError("placement probe poses must exactly cover template references")
        if self.telemetry.target_policy_fingerprint != self.target_policy.semantic_fingerprint():
            raise ValueError("target policy fingerprint is stale")
        if self.telemetry.probe_policy_fingerprint != self.probe_policy.semantic_fingerprint():
            raise ValueError("probe policy fingerprint is stale")
        if self.telemetry.budget_fingerprint != self.budget.semantic_fingerprint():
            raise ValueError("placement budget fingerprint is stale")
        pose_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "schema_id": "pcbsmith-placement-pose-set",
                    "schema_version": 1,
                    "poses": [pose.model_dump(mode="json") for pose in poses],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if self.telemetry.pose_fingerprint != pose_fingerprint:
            raise ValueError("placement pose fingerprint is stale")
        object.__setattr__(self, "poses", poses)
        return self


def placement_pose_set_fingerprint(poses: tuple[ComponentPose, ...]) -> str:
    """Fingerprint a unique canonical complete pose set."""

    canonical = tuple(sorted(poses, key=lambda item: item.reference))
    if len({pose.reference for pose in canonical}) != len(canonical):
        raise ValueError("placement pose set references must be unique")
    return hashlib.sha256(
        json.dumps(
            {
                "schema_id": "pcbsmith-placement-pose-set",
                "schema_version": 1,
                "poses": [pose.model_dump(mode="json") for pose in canonical],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class PlacementRegionVerification(StrEnum):
    EXACT = "exact"
    BOUNDED_APPROXIMATION = "bounded_approximation"
    UNSUPPORTED = "unsupported"


class PlacementOccupancySpan(StrEnum):
    PLACED_SIDE = "placed_side"
    BOTH = "both"


class FootprintPlacementRegion(PlacementIrModel):
    """Lossless or truthfully bounded local body/courtyard geometry."""

    schema_id: Literal["pcbsmith-footprint-placement-region"] = (
        "pcbsmith-footprint-placement-region"
    )
    schema_version: Literal[1] = 1
    region_id: str = Field(min_length=1)
    purpose: Literal["body", "courtyard"]
    occupancy_span: PlacementOccupancySpan
    local_compound: ExactPlanarCompound | None
    verification: PlacementRegionVerification
    maximum_error_mm: float | None = Field(default=None, ge=0)
    source_layers: tuple[str, ...]
    source_fingerprint: str

    @field_validator("region_id")
    @classmethod
    def region_id_is_canonical(cls, value: str) -> str:
        return _require_identity(value, "region_id")

    @field_validator("source_fingerprint")
    @classmethod
    def source_fingerprint_is_sha256(cls, value: str) -> str:
        return _require_sha256(value, "source_fingerprint")

    @model_validator(mode="after")
    def verification_has_truthful_geometry(self) -> Self:
        layers = _canonical_identities(self.source_layers, "source_layers")
        if self.verification is PlacementRegionVerification.EXACT:
            if self.local_compound is None:
                raise ValueError("exact placement region requires local_compound")
            if self.maximum_error_mm is not None:
                raise ValueError("exact placement region cannot declare approximation error")
        elif self.verification is PlacementRegionVerification.BOUNDED_APPROXIMATION:
            if self.local_compound is None:
                raise ValueError("bounded placement region requires local_compound")
            if self.maximum_error_mm is None or self.maximum_error_mm <= 0:
                raise ValueError("bounded placement region requires positive maximum_error_mm")
        elif self.maximum_error_mm is not None:
            raise ValueError("unsupported placement region cannot declare bounded error")
        if self.verification is not PlacementRegionVerification.UNSUPPORTED and not layers:
            raise ValueError("exact/bounded placement region requires source_layers")
        object.__setattr__(self, "source_layers", layers)
        return self


class ComponentPlacementGeometry(PlacementIrModel):
    schema_id: Literal["pcbsmith-component-placement-geometry"] = (
        "pcbsmith-component-placement-geometry"
    )
    schema_version: Literal[1] = 1
    reference: str = Field(min_length=1)
    footprint: str = Field(min_length=1)
    component_identity_fingerprint: str
    regions: tuple[FootprintPlacementRegion, ...] = Field(min_length=2, max_length=2)

    @field_validator("reference", "footprint")
    @classmethod
    def identities_are_canonical(cls, value: str, info: Any) -> str:
        return _require_identity(value, info.field_name)

    @field_validator("component_identity_fingerprint")
    @classmethod
    def component_fingerprint_is_sha256(cls, value: str) -> str:
        return _require_sha256(value, "component_identity_fingerprint")

    @model_validator(mode="after")
    def body_and_courtyard_are_complete(self) -> Self:
        regions = tuple(sorted(self.regions, key=lambda item: (item.purpose, item.region_id)))
        if {region.purpose for region in regions} != {"body", "courtyard"}:
            raise ValueError("component geometry requires body and courtyard regions")
        if len({region.region_id for region in regions}) != len(regions):
            raise ValueError("component placement region IDs must be unique")
        object.__setattr__(self, "regions", regions)
        return self

    def region(self, purpose: Literal["body", "courtyard"]) -> FootprintPlacementRegion:
        return next(region for region in self.regions if region.purpose == purpose)


class PlacementGeometryCatalog(PlacementIrModel):
    """Complete geometry catalog bound to one exact BoardLayout template."""

    schema_id: Literal["pcbsmith-placement-geometry-catalog"] = (
        "pcbsmith-placement-geometry-catalog"
    )
    schema_version: Literal[1] = 1
    template_fingerprint: str
    components: tuple[ComponentPlacementGeometry, ...] = Field(min_length=1)

    @field_validator("template_fingerprint")
    @classmethod
    def template_fingerprint_is_sha256(cls, value: str) -> str:
        return _require_sha256(value, "template_fingerprint")

    @model_validator(mode="after")
    def components_are_canonical(self) -> Self:
        components = tuple(sorted(self.components, key=lambda item: item.reference))
        if len({component.reference for component in components}) != len(components):
            raise ValueError("placement geometry catalog references must be unique")
        object.__setattr__(self, "components", components)
        return self


class PlacementSidePermission(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-side-permission"] = "pcbsmith-placement-side-permission"
    schema_version: Literal[1] = 1
    reference: str = Field(min_length=1)
    allowed_sides: tuple[Literal["front", "back"], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def values_are_canonical(self) -> Self:
        object.__setattr__(self, "reference", _require_identity(self.reference, "reference"))
        object.__setattr__(self, "allowed_sides", tuple(sorted(set(self.allowed_sides))))
        return self


class PlacementEdgeException(PlacementIrModel):
    """Explicitly scoped outer-edge exception backed by replayed interface geometry."""

    schema_id: Literal["pcbsmith-placement-edge-exception"] = "pcbsmith-placement-edge-exception"
    schema_version: Literal[2] = 2
    reference: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    waive_outer_edge_containment: bool = False
    waive_courtyard_outer_edge_containment: bool = False
    minimum_outer_edge_clearance_mm: float = Field(default=0.0, ge=0)
    interface_authority: EdgeInterfaceAuthorityResult | None = None

    @model_validator(mode="after")
    def identities_and_authority_are_canonical(self) -> Self:
        object.__setattr__(self, "reference", _require_identity(self.reference, "reference"))
        object.__setattr__(self, "rule_id", _require_identity(self.rule_id, "rule_id"))
        waives = (
            self.waive_outer_edge_containment
            or self.waive_courtyard_outer_edge_containment
        )
        if waives and self.interface_authority is None:
            raise ValueError("outer-edge containment waiver requires interface authority")
        if self.interface_authority is not None:
            declaration = self.interface_authority.declaration
            if not self.interface_authority.approved:
                raise ValueError("edge-interface authority must be approved")
            if declaration.reference != self.reference:
                raise ValueError("edge-interface authority reference is stale")
            if declaration.exception_rule_id != self.rule_id:
                raise ValueError("edge-interface authority rule is stale")
        return self


class PlacementLegalizationPolicy(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-legalization-policy"] = (
        "pcbsmith-placement-legalization-policy"
    )
    schema_version: Literal[1] = 1
    policy_id: str = Field(min_length=1)
    minimum_body_spacing_mm: float = Field(gt=0)
    minimum_courtyard_spacing_mm: float = Field(ge=0)
    minimum_body_outer_edge_clearance_mm: float = Field(gt=0)
    minimum_body_cutout_clearance_mm: float = Field(gt=0)
    require_courtyard_containment: bool
    minimum_courtyard_outer_edge_clearance_mm: float = Field(ge=0)
    side_permissions: tuple[PlacementSidePermission, ...] = ()
    edge_exceptions: tuple[PlacementEdgeException, ...] = ()

    @model_validator(mode="after")
    def collections_are_canonical(self) -> Self:
        object.__setattr__(self, "policy_id", _require_identity(self.policy_id, "policy_id"))
        permissions = tuple(sorted(self.side_permissions, key=lambda item: item.reference))
        if len({item.reference for item in permissions}) != len(permissions):
            raise ValueError("side permissions must have unique references")
        exceptions = tuple(
            sorted(self.edge_exceptions, key=lambda item: (item.reference, item.rule_id))
        )
        if len({item.reference for item in exceptions}) != len(exceptions):
            raise ValueError("edge exceptions must have unique references")
        if len({item.rule_id for item in exceptions}) != len(exceptions):
            raise ValueError("edge exception rule IDs must be unique")
        object.__setattr__(self, "side_permissions", permissions)
        object.__setattr__(self, "edge_exceptions", exceptions)
        return self


class PlacementLegalizationFindingKind(StrEnum):
    POLICY_SIDE = "policy_side"
    BODY_COLLISION = "body_collision"
    COURTYARD_COLLISION = "courtyard_collision"
    OUTER_EDGE_VIOLATION = "outer_edge_violation"
    CUTOUT_VIOLATION = "cutout_violation"
    COURTYARD_CONTAINMENT = "courtyard_containment"
    REGION_UNSUPPORTED = "region_unsupported"
    BOARD_GEOMETRY_UNSUPPORTED = "board_geometry_unsupported"
    EDGE_INTERFACE_AUTHORITY = "edge_interface_authority"
    LEGALIZATION_BUDGET = "legalization_budget"


class PlacementFindingDisposition(StrEnum):
    VIOLATION = "violation"
    UNVERIFIED = "unverified"
    NOT_EVALUATED = "not_evaluated"


class PlacementLegalizationFinding(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-legalization-finding"] = (
        "pcbsmith-placement-legalization-finding"
    )
    schema_version: Literal[1] = 1
    kind: PlacementLegalizationFindingKind
    disposition: PlacementFindingDisposition
    references: tuple[str, ...]
    region_ids: tuple[str, ...] = ()
    rule_id: str
    verification: PlacementRegionVerification | None = None
    required_clearance_mm: float | None = Field(default=None, ge=0)
    diagnostic_clearance_mm: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def identities_are_canonical(self) -> Self:
        object.__setattr__(self, "references", _canonical_identities(self.references, "references"))
        object.__setattr__(self, "region_ids", _canonical_identities(self.region_ids, "region_ids"))
        object.__setattr__(self, "rule_id", _require_identity(self.rule_id, "rule_id"))
        return self


class PlacementLegalizationOutcome(StrEnum):
    LEGAL_EXACT = "legal_exact"
    LEGAL_BOUNDED = "legal_bounded"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"
    BUDGET_EXHAUSTED = "budget_exhausted"


def placement_findings_fingerprint(findings: tuple[PlacementLegalizationFinding, ...]) -> str:
    canonical = tuple(sorted(findings, key=lambda item: item.semantic_json()))
    return hashlib.sha256(
        json.dumps(
            {
                "schema_id": "pcbsmith-placement-legalization-findings",
                "schema_version": 1,
                "findings": [finding.model_dump(mode="json") for finding in canonical],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class PlacementLegalizationTelemetry(PlacementIrModel):
    """Versioned fingerprints and fixed-budget accounting for one evaluation."""

    schema_id: Literal["pcbsmith-placement-legalization-telemetry"] = (
        "pcbsmith-placement-legalization-telemetry"
    )
    schema_version: Literal[1] = 1
    template_fingerprint: str
    probe_layout_fingerprint: str
    pose_fingerprint: str
    catalog_fingerprint: str
    policy_fingerprint: str
    budget_fingerprint: str
    input_fingerprint: str
    findings_fingerprint: str
    transform_verification: PlacementRegionVerification
    effective_geometry_verification: PlacementRegionVerification
    maximum_transform_error_mm: float | None = Field(default=None, ge=0)
    maximum_effective_error_mm: float | None = Field(default=None, ge=0)
    legalization_evaluations_limit: int = Field(ge=0)
    legalization_evaluations_consumed_before: int = Field(ge=0)
    legalization_evaluations_consumed_after: int = Field(ge=0)
    legalization_evaluations_remaining: int = Field(ge=0)

    @field_validator(
        "template_fingerprint",
        "probe_layout_fingerprint",
        "pose_fingerprint",
        "catalog_fingerprint",
        "policy_fingerprint",
        "budget_fingerprint",
        "input_fingerprint",
        "findings_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def budget_and_transform_are_coherent(self) -> Self:
        before = self.legalization_evaluations_consumed_before
        after = self.legalization_evaluations_consumed_after
        limit = self.legalization_evaluations_limit
        if before > limit or after < before or after > limit or after - before > 1:
            raise ValueError("legalization budget accounting is incoherent")
        if self.legalization_evaluations_remaining != limit - after:
            raise ValueError("legalization remaining budget is stale")
        if self.transform_verification is PlacementRegionVerification.EXACT:
            if self.maximum_transform_error_mm is not None:
                raise ValueError("exact transform cannot declare approximation error")
        elif self.transform_verification is PlacementRegionVerification.BOUNDED_APPROXIMATION:
            if self.maximum_transform_error_mm is None or self.maximum_transform_error_mm <= 0:
                raise ValueError("bounded transform requires positive maximum error")
        elif self.maximum_transform_error_mm is not None:
            raise ValueError("unsupported transform cannot declare bounded error")
        if self.effective_geometry_verification is PlacementRegionVerification.EXACT:
            if self.maximum_effective_error_mm is not None:
                raise ValueError("exact effective geometry cannot declare approximation error")
        elif (
            self.effective_geometry_verification
            is PlacementRegionVerification.BOUNDED_APPROXIMATION
        ):
            if self.maximum_effective_error_mm is None or self.maximum_effective_error_mm <= 0:
                raise ValueError("bounded effective geometry requires positive maximum error")
        elif self.maximum_effective_error_mm is not None:
            raise ValueError("unsupported effective geometry cannot declare bounded error")
        if (
            self.maximum_transform_error_mm is not None
            and self.maximum_effective_error_mm is not None
            and self.maximum_effective_error_mm < self.maximum_transform_error_mm
        ):
            raise ValueError("effective geometry error cannot understate transform error")
        return self


class PlacementLegalizationResult(PlacementIrModel):
    """Deterministic semantic result for one exact or conservative evaluation."""

    schema_id: Literal["pcbsmith-placement-legalization-result"] = (
        "pcbsmith-placement-legalization-result"
    )
    schema_version: Literal[1] = 1
    outcome: PlacementLegalizationOutcome
    findings: tuple[PlacementLegalizationFinding, ...]
    applied_edge_exception_rule_ids: tuple[str, ...] = ()
    telemetry: PlacementLegalizationTelemetry

    @model_validator(mode="after")
    def outcome_and_findings_are_coherent(self) -> Self:
        findings = tuple(
            sorted(
                (
                    PlacementLegalizationFinding.model_validate_json(item.model_dump_json())
                    for item in self.findings
                ),
                key=lambda item: item.semantic_json(),
            )
        )
        telemetry = PlacementLegalizationTelemetry.model_validate_json(
            self.telemetry.model_dump_json()
        )
        object.__setattr__(self, "telemetry", telemetry)
        if len({item.semantic_fingerprint() for item in findings}) != len(findings):
            raise ValueError("legalization findings must be unique")
        if self.telemetry.findings_fingerprint != placement_findings_fingerprint(findings):
            raise ValueError("legalization findings fingerprint is stale")
        dispositions = {finding.disposition for finding in findings}
        expected: PlacementLegalizationOutcome
        if PlacementFindingDisposition.NOT_EVALUATED in dispositions:
            if dispositions != {PlacementFindingDisposition.NOT_EVALUATED}:
                raise ValueError("not-evaluated findings cannot mix with evaluated findings")
            expected = PlacementLegalizationOutcome.BUDGET_EXHAUSTED
        elif PlacementFindingDisposition.VIOLATION in dispositions:
            expected = PlacementLegalizationOutcome.REJECTED
        elif PlacementFindingDisposition.UNVERIFIED in dispositions:
            expected = PlacementLegalizationOutcome.UNVERIFIED
        elif not findings:
            if self.telemetry.effective_geometry_verification is PlacementRegionVerification.EXACT:
                expected = PlacementLegalizationOutcome.LEGAL_EXACT
            elif (
                self.telemetry.effective_geometry_verification
                is PlacementRegionVerification.BOUNDED_APPROXIMATION
            ):
                expected = PlacementLegalizationOutcome.LEGAL_BOUNDED
            else:
                raise ValueError("unsupported effective geometry requires an unverified finding")
        else:
            raise ValueError("legalization findings have no recognized disposition")
        if self.outcome != expected:
            raise ValueError(
                "legalization outcome is inconsistent with findings/effective verification"
            )
        delta = (
            self.telemetry.legalization_evaluations_consumed_after
            - self.telemetry.legalization_evaluations_consumed_before
        )
        expected_delta = 0 if self.outcome is PlacementLegalizationOutcome.BUDGET_EXHAUSTED else 1
        if delta != expected_delta:
            raise ValueError("legalization evaluation budget delta is inconsistent with outcome")
        applied = _canonical_identities(
            self.applied_edge_exception_rule_ids,
            "applied_edge_exception_rule_ids",
        )
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "applied_edge_exception_rule_ids", applied)
        return self
