"""Opt-in, replay-bound authority for intentional sensor-region track bridges.

This authority is deliberately separate from copper-removal evaluation.  It
does not change a copper-removal finding; it records whether exact, explicitly
named track sources satisfy a separately reviewed bridge exception.
"""

from __future__ import annotations

from enum import StrEnum
from fractions import Fraction
from math import gcd
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.mask_geometry import ApertureRelation, MaskGeometry
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticRuleDeclaration,
)
from pcbsmith.sensor_copper_removal_ir import (
    CopperRemovalEvaluationResult,
    CopperRemovalRegionDeclaration,
    canonical_identities,
    fingerprint,
    require_identity,
    require_sha256,
)
from pcbsmith.sensor_isolation_ir import SensorIsolationEvaluationResult


class ExactRationalMillimetres(SemanticIrModel):
    """A canonical exact rational length, avoiding binary-float budget math."""

    schema_id: Literal["pcbsmith-exact-rational-millimetres"] = (
        "pcbsmith-exact-rational-millimetres"
    )
    schema_version: Literal[1] = 1
    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)
    unit: Literal["mm"] = "mm"

    @model_validator(mode="after")
    def fraction_is_canonical(self) -> Self:
        if gcd(self.numerator, self.denominator) != 1:
            raise ValueError("exact rational millimetres must be in lowest terms")
        return self

    @classmethod
    def from_value(cls, value: str | int | float | Fraction) -> Self:
        if isinstance(value, Fraction):
            fraction = value
        elif isinstance(value, float):
            fraction = Fraction(str(value))
        else:
            fraction = Fraction(value)
        if fraction < 0:
            raise ValueError("exact rational millimetres cannot be negative")
        return cls(numerator=fraction.numerator, denominator=fraction.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


def bridge_authority_fingerprint(
    *,
    declaration_id: str,
    isolation_result_fingerprint: str,
    copper_removal_declaration: CopperRemovalRegionDeclaration,
    allowed_bridge_net_names: tuple[str, ...],
    allowed_track_source_ids: tuple[str, ...],
    maximum_bridge_track_count: int,
    maximum_total_bridge_width_mm: ExactRationalMillimetres,
) -> str:
    """Fingerprint every fact authorized by one bridge declaration."""

    return fingerprint(
        {
            "schema_id": "pcbsmith-sensor-bridge-authority-payload",
            "schema_version": 1,
            "declaration_id": declaration_id,
            "isolation_result_fingerprint": isolation_result_fingerprint,
            "copper_removal_declaration": copper_removal_declaration.model_dump(mode="json"),
            "allowed_bridge_net_names": sorted(allowed_bridge_net_names),
            "allowed_track_source_ids": sorted(allowed_track_source_ids),
            "maximum_bridge_track_count": maximum_bridge_track_count,
            "maximum_total_bridge_width_mm": maximum_total_bridge_width_mm.model_dump(mode="json"),
        }
    )


def _binding_is_complete(binding: EvidenceApplicabilityBinding) -> bool:
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


class SensorBridgeDeclaration(SemanticIrModel):
    """One explicit hard-geometry exception for tracks in one removal region."""

    schema_id: Literal["pcbsmith-sensor-bridge-declaration"] = (
        "pcbsmith-sensor-bridge-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str = Field(min_length=1)
    isolation_result_fingerprint: str
    copper_removal_declaration: CopperRemovalRegionDeclaration
    copper_removal_declaration_fingerprint: str
    allowed_bridge_net_names: tuple[str, ...] = Field(min_length=1)
    allowed_track_source_ids: tuple[str, ...] = Field(min_length=1)
    maximum_bridge_track_count: int = Field(ge=0)
    maximum_total_bridge_width_mm: ExactRationalMillimetres
    authority_evidence_binding: EvidenceApplicabilityBinding
    bridge_rule: SemanticRuleDeclaration

    @model_validator(mode="after")
    def exception_authority_is_complete_and_separate(self) -> Self:
        require_identity(self.declaration_id, "declaration_id")
        require_sha256(self.isolation_result_fingerprint, "isolation_result_fingerprint")
        require_sha256(
            self.copper_removal_declaration_fingerprint,
            "copper_removal_declaration_fingerprint",
        )
        nets = canonical_identities(self.allowed_bridge_net_names, "allowed_bridge_net_names")
        sources = canonical_identities(
            self.allowed_track_source_ids, "allowed_track_source_ids"
        )
        if any(not item.startswith("track:") for item in sources):
            raise ValueError("allowed bridge sources must be exact track source identities")
        if self.maximum_total_bridge_width_mm.as_fraction() <= 0:
            raise ValueError("maximum total bridge width must be positive")
        copper = self.copper_removal_declaration
        if (
            self.copper_removal_declaration_fingerprint != copper.semantic_fingerprint()
            or self.isolation_result_fingerprint != copper.isolation_result_fingerprint
        ):
            raise ValueError("bridge declaration is stale for its isolation/removal authority")
        expected_authority_fingerprint = bridge_authority_fingerprint(
            declaration_id=self.declaration_id,
            isolation_result_fingerprint=self.isolation_result_fingerprint,
            copper_removal_declaration=copper,
            allowed_bridge_net_names=nets,
            allowed_track_source_ids=sources,
            maximum_bridge_track_count=self.maximum_bridge_track_count,
            maximum_total_bridge_width_mm=self.maximum_total_bridge_width_mm,
        )
        binding = self.authority_evidence_binding
        rule = self.bridge_rule
        expected_objects = tuple(
            sorted(
                {
                    self.declaration_id,
                    copper.declaration_id,
                    copper.candidate_id,
                    copper.source_feature_id,
                    *sources,
                }
            )
        )
        if not _binding_is_complete(binding):
            raise ValueError("bridge authority requires complete reviewed applicability evidence")
        if binding.geometry_source_fingerprint != expected_authority_fingerprint:
            raise ValueError("bridge evidence is stale for the exact authorized constraints")
        if binding.binding_id in {
            copper.geometry_evidence_binding.binding_id,
            *copper.evidence_binding_ids,
            *copper.applicability_binding_ids,
        }:
            raise ValueError("bridge authority must use a dedicated evidence binding")
        if (
            rule.authority is not SemanticAuthorityClass.HARD_GEOMETRY
            or rule.rule_id == copper.rule_id
            or rule.object_ids != expected_objects
            or rule.geometry_region_ids != (copper.region_id,)
            or rule.evidence_binding_ids != (binding.binding_id,)
            or rule.process_profile_id is not None
            or rule.qualified_process_record_id is not None
            or rule.validation_requirement_ids
        ):
            raise ValueError("bridge exception requires its separate exact hard-geometry rule")
        object.__setattr__(self, "allowed_bridge_net_names", nets)
        object.__setattr__(self, "allowed_track_source_ids", sources)
        return self


class SensorBridgeTrackRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-bridge-track-record"] = (
        "pcbsmith-sensor-bridge-track-record"
    )
    schema_version: Literal[1] = 1
    declaration_id: str = Field(min_length=1)
    copper_removal_declaration_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    segment_index: int = Field(ge=0)
    net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    width_mm: ExactRationalMillimetres
    geometry: MaskGeometry
    relation: Literal[ApertureRelation.OVERLAP] = ApertureRelation.OVERLAP
    source_declared: bool
    net_allowed: bool
    layer_authority_exact: bool
    count_budget_passed: bool
    total_width_budget_passed: bool
    disposition: SemanticDisposition

    @model_validator(mode="after")
    def record_is_coherent(self) -> Self:
        for name in ("declaration_id", "copper_removal_declaration_id", "source_id"):
            require_identity(getattr(self, name), name)
        if self.source_id != f"track:{self.segment_index}":
            raise ValueError("bridge track identity differs from its exact segment index")
        expected = (
            SemanticDisposition.PASS
            if all(
                (
                    self.source_declared,
                    self.net_allowed,
                    self.layer_authority_exact,
                    self.count_budget_passed,
                    self.total_width_budget_passed,
                )
            )
            else SemanticDisposition.FAIL
        )
        if self.disposition is not expected:
            raise ValueError("bridge track disposition is stale")
        return self


class SensorBridgeBudgetEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-bridge-budget-evidence"] = (
        "pcbsmith-sensor-bridge-budget-evidence"
    )
    schema_version: Literal[1] = 1
    declaration_id: str = Field(min_length=1)
    bridge_track_source_ids: tuple[str, ...]
    actual_bridge_track_count: int = Field(ge=0)
    maximum_bridge_track_count: int = Field(ge=0)
    actual_total_bridge_width_mm: ExactRationalMillimetres
    maximum_total_bridge_width_mm: ExactRationalMillimetres
    count_budget_passed: bool
    total_width_budget_passed: bool

    @model_validator(mode="after")
    def evidence_is_exact(self) -> Self:
        require_identity(self.declaration_id, "declaration_id")
        sources = canonical_identities(self.bridge_track_source_ids, "bridge_track_source_ids")
        if self.actual_bridge_track_count != len(sources):
            raise ValueError("bridge count differs from exact overlapping source identities")
        if self.count_budget_passed != (
            self.actual_bridge_track_count <= self.maximum_bridge_track_count
        ):
            raise ValueError("bridge count budget disposition is stale")
        if self.total_width_budget_passed != (
            self.actual_total_bridge_width_mm.as_fraction()
            <= self.maximum_total_bridge_width_mm.as_fraction()
        ):
            raise ValueError("bridge total-width budget disposition is stale")
        object.__setattr__(self, "bridge_track_source_ids", sources)
        return self


class SensorBridgeCheckKind(StrEnum):
    SOURCE_AUTHORIZED = "source_authorized"
    NET_AUTHORIZED = "net_authorized"
    LAYER_REMOVAL_AUTHORITY = "layer_removal_authority"
    TRACK_COUNT_BUDGET = "track_count_budget"
    TOTAL_WIDTH_BUDGET = "total_width_budget"


class SensorBridgeTypedFinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-sensor-bridge-typed-finding"] = (
        "pcbsmith-sensor-bridge-typed-finding"
    )
    schema_version: Literal[1] = 1
    declaration_id: str = Field(min_length=1)
    check_kind: SensorBridgeCheckKind
    source_id: str | None = None
    disposition: Literal[SemanticDisposition.PASS, SemanticDisposition.FAIL]
    semantic_finding_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def typed_identity_is_coherent(self) -> Self:
        require_identity(self.declaration_id, "declaration_id")
        require_identity(self.semantic_finding_id, "semantic_finding_id")
        per_track = self.check_kind in {
            SensorBridgeCheckKind.SOURCE_AUTHORIZED,
            SensorBridgeCheckKind.NET_AUTHORIZED,
            SensorBridgeCheckKind.LAYER_REMOVAL_AUTHORITY,
        }
        if per_track != (self.source_id is not None):
            raise ValueError("per-track bridge checks require exactly one track source identity")
        if self.source_id is not None:
            require_identity(self.source_id, "source_id")
        return self


class SensorBridgeEvaluationResult(SemanticIrModel):
    """Frozen result whose replay leaves copper-removal findings untouched."""

    schema_id: Literal["pcbsmith-sensor-bridge-evaluation-result"] = (
        "pcbsmith-sensor-bridge-evaluation-result"
    )
    schema_version: Literal[1] = 1
    exception_scope_statement: Literal[
        "separate bridge authority; copper-removal findings are retained and not overwritten"
    ] = "separate bridge authority; copper-removal findings are retained and not overwritten"
    isolation_result: SensorIsolationEvaluationResult
    copper_removal_result: CopperRemovalEvaluationResult
    board_layout_snapshot_json: str
    board_netlist_snapshot_json: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    declarations: tuple[SensorBridgeDeclaration, ...] = Field(min_length=1)
    bridge_tracks: tuple[SensorBridgeTrackRecord, ...]
    budget_evidence: tuple[SensorBridgeBudgetEvidence, ...]
    geometry_fingerprint: str
    input_fingerprint: str
    findings: tuple[SemanticFinding, ...]
    typed_findings: tuple[SensorBridgeTypedFinding, ...]
    semantic_result: SemanticLayoutResult

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        from pcbsmith.kicad.sensor_bridge import rederive_sensor_bridge_result

        expected = rederive_sensor_bridge_result(
            isolation_result=self.isolation_result,
            copper_removal_result=self.copper_removal_result,
            board_layout_snapshot_json=self.board_layout_snapshot_json,
            board_netlist_snapshot_json=self.board_netlist_snapshot_json,
            declarations=self.declarations,
        )
        expected_values: dict[str, Any] = dict(expected)
        compared = (
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
            "declarations",
            "bridge_tracks",
            "budget_evidence",
            "geometry_fingerprint",
            "input_fingerprint",
            "findings",
            "typed_findings",
            "semantic_result",
        )
        if any(getattr(self, name) != expected_values[name] for name in compared):
            raise ValueError("sensor bridge evidence/findings are stale or not replay-derived")
        for name in compared:
            object.__setattr__(self, name, expected_values[name])
        object.__setattr__(self, "isolation_result", expected["isolation_result"])
        object.__setattr__(self, "copper_removal_result", expected["copper_removal_result"])
        return self
