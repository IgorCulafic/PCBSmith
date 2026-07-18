"""Replay-bound physical-object authority for R6.2 antenna keepout clearance."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.antenna_ir import (
    AntennaObjectKind,
    AntennaPlacementResult,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, PlanarRelation
from pcbsmith.semantic_ir import (
    SemanticDisposition,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticVerification,
)
from pcbsmith.sensor_copper_removal_ir import ExactFilledZoneReaderPolicy


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
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


def canonical_identities(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(require_identity(value, field_name) for value in values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} must contain unique identities")
    return canonical


class AntennaUnsupportedObjectReason(StrEnum):
    ZONE_INTENT_WITHOUT_FINAL_FILL = "zone_intent_without_final_fill"
    OPAQUE_FOOTPRINT = "opaque_footprint"
    RAW_GRAPHIC = "raw_graphic"
    UNQUALIFIED_GEOMETRY = "unqualified_geometry"
    OTHER_TYPED_UNSUPPORTED = "other_typed_unsupported"


class QualifiedExactZoneFillProvenance(SemanticIrModel):
    """Canonical final-fill record from one project-qualified reader."""

    schema_id: Literal["pcbsmith-qualified-exact-zone-fill-provenance"] = (
        "pcbsmith-qualified-exact-zone-fill-provenance"
    )
    schema_version: Literal[1] = 1
    fill_provenance_id: str = Field(min_length=1)
    zone_source_provenance_id: str = Field(min_length=1)
    board_layout_snapshot_fingerprint: str
    exact_geometry_fingerprint: str
    reader_id: str = Field(min_length=1)
    reader_version: str = Field(min_length=1)
    reader_policy: ExactFilledZoneReaderPolicy
    source_artifact_id: str = Field(min_length=1)
    source_artifact_sha256: str
    status: Literal["active", "suspended", "revoked"]
    final_fill_record_json: str = Field(min_length=2)
    final_fill_record_sha256: str

    def record_payload(self) -> dict[str, Any]:
        return {
            "schema_id": "pcbsmith-antenna-final-zone-fill-record",
            "schema_version": 1,
            "fill_provenance_id": self.fill_provenance_id,
            "zone_source_provenance_id": self.zone_source_provenance_id,
            "board_layout_snapshot_fingerprint": self.board_layout_snapshot_fingerprint,
            "exact_geometry_fingerprint": self.exact_geometry_fingerprint,
            "reader_id": self.reader_id,
            "reader_version": self.reader_version,
            "reader_policy": self.reader_policy.model_dump(mode="json"),
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_sha256": self.source_artifact_sha256,
            "status": self.status,
        }

    @model_validator(mode="after")
    def final_fill_is_qualified_and_canonical(self) -> Self:
        for field_name in (
            "fill_provenance_id",
            "zone_source_provenance_id",
            "reader_id",
            "reader_version",
            "source_artifact_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        for field_name in (
            "board_layout_snapshot_fingerprint",
            "exact_geometry_fingerprint",
            "source_artifact_sha256",
            "final_fill_record_sha256",
        ):
            require_sha256(getattr(self, field_name), field_name)
        if self.status != "active" or self.reader_policy.status != "active":
            raise ValueError("exact zone fill requires an active qualified reader policy")
        if (
            self.reader_id != self.reader_policy.reader_id
            or self.reader_version != self.reader_policy.reader_version
        ):
            raise ValueError("exact zone fill reader identity differs from its qualified policy")
        expected = canonical_json(self.record_payload())
        if self.final_fill_record_json != expected:
            raise ValueError("final fill record JSON is noncanonical or stale")
        if self.final_fill_record_sha256 != hashlib.sha256(expected.encode()).hexdigest():
            raise ValueError("final fill record checksum is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        fill_provenance_id: str,
        zone_source_provenance_id: str,
        board_layout_snapshot_fingerprint: str,
        exact_geometry_fingerprint: str,
        reader_id: str,
        reader_version: str,
        reader_policy: ExactFilledZoneReaderPolicy,
        source_artifact_id: str,
        source_artifact_sha256: str,
    ) -> Self:
        fields = {
            "fill_provenance_id": fill_provenance_id,
            "zone_source_provenance_id": zone_source_provenance_id,
            "board_layout_snapshot_fingerprint": board_layout_snapshot_fingerprint,
            "exact_geometry_fingerprint": exact_geometry_fingerprint,
            "reader_id": reader_id,
            "reader_version": reader_version,
            "reader_policy": reader_policy.model_dump(mode="json"),
            "source_artifact_id": source_artifact_id,
            "source_artifact_sha256": source_artifact_sha256,
            "status": "active",
        }
        record = canonical_json(
            {
                "schema_id": "pcbsmith-antenna-final-zone-fill-record",
                "schema_version": 1,
                **fields,
            }
        )
        return cls(
            **fields,
            final_fill_record_json=record,
            final_fill_record_sha256=hashlib.sha256(record.encode()).hexdigest(),
        )


class AntennaPhysicalObject(SemanticIrModel):
    """One explicitly supplied physical object; no raw-object auto-ingestion."""

    schema_id: Literal["pcbsmith-antenna-physical-object"] = "pcbsmith-antenna-physical-object"
    schema_version: Literal[1] = 1
    object_id: str = Field(min_length=1)
    kind: AntennaObjectKind
    physical_layers: tuple[str, ...] = Field(min_length=1)
    source_provenance_id: str = Field(min_length=1)
    owner_component_ref: str | None = None
    owner_net_name: str | None = None
    board_layout_snapshot_fingerprint: str
    source_representation: Literal["physical_geometry", "zone_intent", "exact_final_zone_fill"]
    verification: Literal[SemanticVerification.EXACT, SemanticVerification.UNSUPPORTED]
    compound: ExactPlanarCompound | None
    unsupported_reason: AntennaUnsupportedObjectReason | None
    exact_zone_fill_provenance: QualifiedExactZoneFillProvenance | None = None

    @model_validator(mode="after")
    def object_authority_is_coherent(self) -> Self:
        require_identity(self.object_id, "object_id")
        require_identity(self.source_provenance_id, "source_provenance_id")
        require_sha256(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        object.__setattr__(
            self,
            "physical_layers",
            canonical_identities(self.physical_layers, "physical_layers"),
        )
        for field_name in ("owner_component_ref", "owner_net_name"):
            value = getattr(self, field_name)
            if value is not None:
                require_identity(value, field_name)
        if self.verification is SemanticVerification.EXACT:
            if self.compound is None or self.unsupported_reason is not None:
                raise ValueError(
                    "exact physical objects require geometry and no unsupported reason"
                )
        elif self.compound is not None or self.unsupported_reason is None:
            raise ValueError("unsupported physical objects require a typed reason and no geometry")
        if self.kind == "zone":
            if self.source_representation == "zone_intent":
                if (
                    self.verification is not SemanticVerification.UNSUPPORTED
                    or self.unsupported_reason
                    is not AntennaUnsupportedObjectReason.ZONE_INTENT_WITHOUT_FINAL_FILL
                    or self.exact_zone_fill_provenance is not None
                ):
                    raise ValueError("zone intent is unsupported and cannot claim exact fill")
            elif self.source_representation == "exact_final_zone_fill":
                provenance = self.exact_zone_fill_provenance
                if (
                    self.verification is not SemanticVerification.EXACT
                    or self.compound is None
                    or provenance is None
                    or provenance.zone_source_provenance_id != self.source_provenance_id
                    or provenance.board_layout_snapshot_fingerprint
                    != self.board_layout_snapshot_fingerprint
                    or provenance.exact_geometry_fingerprint != self.compound.semantic_fingerprint()
                ):
                    raise ValueError("exact filled zone provenance is stale or incomplete")
            else:
                raise ValueError("zone objects must identify intent or exact final fill")
        elif (
            self.source_representation != "physical_geometry"
            or self.exact_zone_fill_provenance is not None
        ):
            raise ValueError("non-zone objects require physical geometry representation")
        return self


class AntennaClearancePairEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-clearance-pair-evidence"] = (
        "pcbsmith-antenna-clearance-pair-evidence"
    )
    schema_version: Literal[1] = 1
    pair_id: str
    keepout_provenance_id: str
    keepout_region_id: str
    prohibited_object_rule_id: str
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)
    object_id: str
    object_kind: AntennaObjectKind
    keepout_layers: tuple[str, ...]
    object_layers: tuple[str, ...]
    applicable_layers: tuple[str, ...]
    kind_applicable: bool
    layer_applicable: bool
    relation: PlanarRelation | None
    verification: SemanticVerification
    disposition: SemanticDisposition

    @model_validator(mode="after")
    def pair_is_canonical_and_coherent(self) -> Self:
        for field_name in (
            "pair_id",
            "keepout_provenance_id",
            "keepout_region_id",
            "prohibited_object_rule_id",
            "object_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        for field_name in (
            "evidence_binding_ids",
            "keepout_layers",
            "object_layers",
            "applicable_layers",
        ):
            object.__setattr__(
                self, field_name, canonical_identities(getattr(self, field_name), field_name)
            )
        applicable = self.kind_applicable and self.layer_applicable
        if self.layer_applicable != bool(self.applicable_layers):
            raise ValueError("layer applicability differs from the retained intersection")
        if not applicable:
            if self.disposition is not SemanticDisposition.NOT_APPLICABLE or self.relation:
                raise ValueError("inapplicable clearance pair must be not applicable")
        elif self.verification in {
            SemanticVerification.UNSUPPORTED,
            SemanticVerification.BOUNDED_APPROXIMATION,
        }:
            if self.disposition is not SemanticDisposition.UNVERIFIED or self.relation:
                raise ValueError("non-exact applicable clearance pair must be unverified")
        elif self.relation is PlanarRelation.DISJOINT:
            if self.disposition is not SemanticDisposition.PASS:
                raise ValueError("disjoint exact clearance pair must pass")
        elif self.relation in {PlanarRelation.BOUNDARY_TOUCH, PlanarRelation.INTERIOR_OVERLAP}:
            if self.disposition is not SemanticDisposition.FAIL:
                raise ValueError("touching/overlapping exact clearance pair must fail")
        else:
            raise ValueError("exact applicable clearance pair requires an exact relation")
        return self


class AntennaClearanceResult(SemanticIrModel):
    """Complete replay-bound keepout × physical-object evaluation."""

    schema_id: Literal["pcbsmith-antenna-clearance-result"] = "pcbsmith-antenna-clearance-result"
    schema_version: Literal[1] = 1
    placement_result: AntennaPlacementResult
    physical_objects: tuple[AntennaPhysicalObject, ...]
    pair_evidence: tuple[AntennaClearancePairEvidence, ...]
    physical_objects_fingerprint: str
    pair_evidence_fingerprint: str
    semantic_result: SemanticLayoutResult
    result_fingerprint: str

    @field_validator(
        "physical_objects_fingerprint", "pair_evidence_fingerprint", "result_fingerprint"
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        from pcbsmith.kicad.antenna_clearance import rederive_antenna_clearance

        expected = rederive_antenna_clearance(self.placement_result, self.physical_objects)
        compared = (
            "physical_objects",
            "pair_evidence",
            "physical_objects_fingerprint",
            "pair_evidence_fingerprint",
            "semantic_result",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("antenna clearance evidence/result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("antenna clearance result fingerprint is stale")
        return self
