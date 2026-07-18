"""Versioned declarations and replay evidence for sensor copper removal.

This R6.1b fixture checks only whether exact outer-layer copper intersects an
explicitly declared removal region.  Boundary-only contact is retained as
``touching`` and passes because no positive-area copper lies in the removed
interior.  Unflooded zone intent and unsupported physical geometry fail closed
as unverified whenever they are relevant to a declared removal layer.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.copper_exposure import CopperGeometryVerification
from pcbsmith.mask_geometry import ApertureRelation, MaskGeometry
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticFinding,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticRuleDeclaration,
    SemanticVerification,
)
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


def canonical_identities(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(sorted(require_identity(value, field_name) for value in values))
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} must contain unique identities")
    return result


class CopperRemovalSourceKind(StrEnum):
    TRACK = "track"
    VIA_LAND = "via_land"
    PAD = "pad"
    ZONE_INTENT = "zone_intent"
    EXACT_FILLED_ZONE = "exact_filled_zone"


class CopperRemovalRegionDeclaration(SemanticIrModel):
    """One exact removal region on one physical outer copper layer."""

    schema_id: Literal["pcbsmith-copper-removal-region-declaration"] = (
        "pcbsmith-copper-removal-region-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    source_feature_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    layer: Literal["F.Cu", "B.Cu"]
    geometry: MaskGeometry
    isolation_result_fingerprint: str
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)
    applicability_binding_ids: tuple[str, ...] = Field(min_length=1)
    geometry_evidence_binding: EvidenceApplicabilityBinding
    geometry_rule: SemanticRuleDeclaration

    @model_validator(mode="after")
    def declaration_is_canonical(self) -> Self:
        for field_name in (
            "declaration_id",
            "candidate_id",
            "source_feature_id",
            "region_id",
            "rule_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(self.isolation_result_fingerprint, "isolation_result_fingerprint")
        object.__setattr__(
            self,
            "evidence_binding_ids",
            canonical_identities(self.evidence_binding_ids, "evidence_binding_ids"),
        )
        object.__setattr__(
            self,
            "applicability_binding_ids",
            canonical_identities(self.applicability_binding_ids, "applicability_binding_ids"),
        )
        return self


class ExactFilledZoneReaderPolicy(SemanticIrModel):
    """Project-qualified exact-fill reader identity and review record."""

    schema_id: Literal["pcbsmith-exact-filled-zone-reader-policy"] = (
        "pcbsmith-exact-filled-zone-reader-policy"
    )
    schema_version: Literal[1] = 1
    policy_id: str = Field(min_length=1)
    reader_id: str = Field(min_length=1)
    reader_version: str = Field(min_length=1)
    project_qualification_record_id: str = Field(min_length=1)
    project_qualification_artifact_sha256: str
    reviewer_record_id: str = Field(min_length=1)
    status: Literal["active", "suspended", "revoked"]

    @model_validator(mode="after")
    def qualification_is_typed_and_complete(self) -> Self:
        for field_name in (
            "policy_id",
            "reader_id",
            "reader_version",
            "project_qualification_record_id",
            "reviewer_record_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(
            self.project_qualification_artifact_sha256,
            "project_qualification_artifact_sha256",
        )
        return self


class ExactFilledZoneCopper(SemanticIrModel):
    """Exact final zone fill with a canonical reader/export provenance record."""

    schema_id: Literal["pcbsmith-exact-filled-zone-copper"] = "pcbsmith-exact-filled-zone-copper"
    schema_version: Literal[1] = 1
    board_layout_fingerprint: str
    zone_source_id: str = Field(min_length=1)
    zone_index: int = Field(ge=0)
    zone_net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    geometry: MaskGeometry
    reader_id: str = Field(min_length=1)
    reader_version: str = Field(min_length=1)
    reader_policy: ExactFilledZoneReaderPolicy
    source_artifact_id: str = Field(min_length=1)
    source_artifact_sha256: str
    final_fill_record_json: str = Field(min_length=1)
    final_fill_record_sha256: str

    @field_validator(
        "board_layout_fingerprint",
        "source_artifact_sha256",
        "final_fill_record_sha256",
    )
    @classmethod
    def hashes_are_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    def record_payload(self) -> dict[str, Any]:
        return {
            "schema_id": "pcbsmith-final-zone-fill-record",
            "schema_version": 1,
            "board_layout_fingerprint": self.board_layout_fingerprint,
            "zone_source_id": self.zone_source_id,
            "zone_index": self.zone_index,
            "zone_net_name": self.zone_net_name,
            "layer": self.layer,
            "geometry": self.geometry.model_dump(mode="json"),
            "reader_id": self.reader_id,
            "reader_version": self.reader_version,
            "reader_policy": self.reader_policy.model_dump(mode="json"),
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_sha256": self.source_artifact_sha256,
        }

    @model_validator(mode="after")
    def record_is_canonical_and_bound(self) -> Self:
        for field_name in (
            "zone_source_id",
            "reader_id",
            "reader_version",
            "source_artifact_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        if self.reader_policy.status != "active":
            raise ValueError("exact final fill requires an active qualified reader policy")
        if (
            self.reader_id != self.reader_policy.reader_id
            or self.reader_version != self.reader_policy.reader_version
        ):
            raise ValueError("exact final fill reader identity differs from its qualified policy")
        try:
            parsed = json.loads(self.final_fill_record_json)
        except json.JSONDecodeError as error:
            raise ValueError("final fill record JSON is invalid") from error
        expected_json = canonical_json(self.record_payload())
        if self.final_fill_record_json != expected_json or parsed != self.record_payload():
            raise ValueError("final fill record is noncanonical or stale")
        if self.final_fill_record_sha256 != hashlib.sha256(expected_json.encode()).hexdigest():
            raise ValueError("final fill record checksum is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        board_layout_fingerprint: str,
        zone_source_id: str,
        zone_index: int,
        zone_net_name: str,
        layer: Literal["F.Cu", "B.Cu"],
        geometry: MaskGeometry,
        reader_id: str,
        reader_version: str,
        reader_policy: ExactFilledZoneReaderPolicy,
        source_artifact_id: str,
        source_artifact_sha256: str,
    ) -> Self:
        payload = {
            "schema_id": "pcbsmith-final-zone-fill-record",
            "schema_version": 1,
            "board_layout_fingerprint": board_layout_fingerprint,
            "zone_source_id": zone_source_id,
            "zone_index": zone_index,
            "zone_net_name": zone_net_name,
            "layer": layer,
            "geometry": geometry.model_dump(mode="json"),
            "reader_id": reader_id,
            "reader_version": reader_version,
            "reader_policy": reader_policy.model_dump(mode="json"),
            "source_artifact_id": source_artifact_id,
            "source_artifact_sha256": source_artifact_sha256,
        }
        record = canonical_json(payload)
        return cls(
            board_layout_fingerprint=board_layout_fingerprint,
            zone_source_id=zone_source_id,
            zone_index=zone_index,
            zone_net_name=zone_net_name,
            layer=layer,
            geometry=geometry,
            reader_id=reader_id,
            reader_version=reader_version,
            reader_policy=reader_policy,
            source_artifact_id=source_artifact_id,
            source_artifact_sha256=source_artifact_sha256,
            final_fill_record_json=record,
            final_fill_record_sha256=hashlib.sha256(record.encode()).hexdigest(),
        )


class CopperRemovalPhysicalSource(SemanticIrModel):
    schema_id: Literal["pcbsmith-copper-removal-physical-source"] = (
        "pcbsmith-copper-removal-physical-source"
    )
    schema_version: Literal[1] = 1
    source_id: str = Field(min_length=1)
    parent_source_id: str | None = None
    source_kind: CopperRemovalSourceKind
    net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    geometry: MaskGeometry | None = None
    verification: CopperGeometryVerification
    unsupported_reason: str | None = None
    final_fill_record_sha256: str | None = None

    @model_validator(mode="after")
    def physical_source_is_coherent(self) -> Self:
        require_identity(self.source_id, "source_id")
        if self.parent_source_id is not None:
            require_identity(self.parent_source_id, "parent_source_id")
        if self.verification is CopperGeometryVerification.EXACT:
            if self.geometry is None or self.unsupported_reason is not None:
                raise ValueError(
                    "exact physical copper requires geometry and no unsupported reason"
                )
        elif self.geometry is not None or not self.unsupported_reason:
            raise ValueError("unsupported physical copper requires only an unsupported reason")
        if self.source_kind is CopperRemovalSourceKind.EXACT_FILLED_ZONE:
            if self.final_fill_record_sha256 is None:
                raise ValueError("exact filled-zone copper requires its provenance checksum")
            require_sha256(self.final_fill_record_sha256, "final_fill_record_sha256")
        elif self.final_fill_record_sha256 is not None:
            raise ValueError("only exact filled-zone copper may carry a fill checksum")
        return self


class CopperRemovalPairEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-copper-removal-pair-evidence"] = (
        "pcbsmith-copper-removal-pair-evidence"
    )
    schema_version: Literal[1] = 1
    source_id: str = Field(min_length=1)
    declaration_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    relation: ApertureRelation | None
    authority_complete: bool
    verification: SemanticVerification
    disposition: SemanticDisposition
    finding_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def pair_is_coherent(self) -> Self:
        for field_name in ("source_id", "declaration_id", "rule_id", "finding_id"):
            require_identity(getattr(self, field_name), field_name)
        if self.disposition not in {
            SemanticDisposition.PASS,
            SemanticDisposition.FAIL,
            SemanticDisposition.UNVERIFIED,
        }:
            raise ValueError("copper-removal pair disposition must be pass/fail/unverified")
        if self.verification is SemanticVerification.UNSUPPORTED:
            if self.relation is not None or self.disposition is not SemanticDisposition.UNVERIFIED:
                raise ValueError("unsupported copper-removal pair must be unverified")
        elif self.relation is None:
            raise ValueError("exact copper-removal pair requires its exact relation")
        elif self.relation not in {
            ApertureRelation.SEPARATED,
            ApertureRelation.TOUCHING,
            ApertureRelation.OVERLAP,
        }:
            raise ValueError("copper-removal pair has an inapplicable geometry relation")
        if not self.authority_complete and self.disposition is not SemanticDisposition.UNVERIFIED:
            raise ValueError("incomplete copper-removal authority must be unverified")
        if self.relation is ApertureRelation.OVERLAP and self.authority_complete:
            if self.disposition is not SemanticDisposition.FAIL:
                raise ValueError("authoritative positive-area overlap must fail")
        if self.relation in {ApertureRelation.SEPARATED, ApertureRelation.TOUCHING}:
            expected = (
                SemanticDisposition.PASS
                if self.authority_complete
                else SemanticDisposition.UNVERIFIED
            )
            if self.disposition is not expected:
                raise ValueError("separated/touching relation has a stale disposition")
        return self


class CopperRemovalSourceEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-copper-removal-source-evidence"] = (
        "pcbsmith-copper-removal-source-evidence"
    )
    schema_version: Literal[1] = 1
    source_id: str = Field(min_length=1)
    source_kind: CopperRemovalSourceKind
    net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    applicable_declaration_ids: tuple[str, ...]
    disposition: SemanticDisposition

    @model_validator(mode="after")
    def source_evidence_is_canonical(self) -> Self:
        require_identity(self.source_id, "source_id")
        object.__setattr__(
            self,
            "applicable_declaration_ids",
            canonical_identities(self.applicable_declaration_ids, "applicable_declaration_ids"),
        )
        if self.disposition not in {
            SemanticDisposition.NOT_APPLICABLE,
            SemanticDisposition.PASS,
            SemanticDisposition.FAIL,
            SemanticDisposition.UNVERIFIED,
        }:
            raise ValueError(
                "copper-removal source disposition must be not-applicable/pass/fail/unverified"
            )
        if not self.applicable_declaration_ids:
            if self.disposition is not SemanticDisposition.NOT_APPLICABLE:
                raise ValueError("source without applicable declarations must be not applicable")
        elif self.disposition is SemanticDisposition.NOT_APPLICABLE:
            raise ValueError("applicable source cannot be not applicable")
        return self


class CopperRemovalEvaluationResult(SemanticIrModel):
    """Complete replay-bound result for the copper-crossing firing fixture."""

    schema_id: Literal["pcbsmith-copper-removal-evaluation-result"] = (
        "pcbsmith-copper-removal-evaluation-result"
    )
    schema_version: Literal[1] = 1
    isolation_result: SensorIsolationEvaluationResult
    board_layout_snapshot_json: str
    board_netlist_snapshot_json: str
    board_layout_fingerprint: str
    board_layout_snapshot_fingerprint: str
    board_netlist_fingerprint: str
    declarations: tuple[CopperRemovalRegionDeclaration, ...] = Field(min_length=1)
    exact_filled_zones: tuple[ExactFilledZoneCopper, ...] = ()
    physical_sources: tuple[CopperRemovalPhysicalSource, ...]
    pair_evidence: tuple[CopperRemovalPairEvidence, ...]
    source_evidence: tuple[CopperRemovalSourceEvidence, ...]
    source_geometry_fingerprint: str
    input_fingerprint: str
    findings: tuple[SemanticFinding, ...]
    semantic_result: SemanticLayoutResult

    @field_validator(
        "board_layout_fingerprint",
        "board_layout_snapshot_fingerprint",
        "board_netlist_fingerprint",
        "source_geometry_fingerprint",
        "input_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        # Lazy import avoids an import cycle while keeping replay in the frozen
        # result itself rather than trusting a one-time adapter invocation.
        from pcbsmith.kicad.sensor_copper_removal import rederive_copper_removal_result

        expected = rederive_copper_removal_result(
            isolation_result=SensorIsolationEvaluationResult.model_validate_json(
                self.isolation_result.model_dump_json()
            ),
            board_layout_snapshot_json=self.board_layout_snapshot_json,
            board_netlist_snapshot_json=self.board_netlist_snapshot_json,
            declarations=self.declarations,
            exact_filled_zones=self.exact_filled_zones,
        )
        expected_values: dict[str, Any] = dict(expected)
        compared = (
            "board_layout_fingerprint",
            "board_layout_snapshot_fingerprint",
            "board_netlist_fingerprint",
            "physical_sources",
            "pair_evidence",
            "source_evidence",
            "source_geometry_fingerprint",
            "input_fingerprint",
            "findings",
            "semantic_result",
        )
        if any(getattr(self, field_name) != expected_values[field_name] for field_name in compared):
            raise ValueError("copper-removal evidence/findings are stale or not replay-derived")
        for field_name in compared:
            object.__setattr__(self, field_name, expected_values[field_name])
        object.__setattr__(
            self,
            "declarations",
            expected["declarations"],
        )
        object.__setattr__(self, "exact_filled_zones", expected["exact_filled_zones"])
        object.__setattr__(self, "isolation_result", expected["isolation_result"])
        return self
