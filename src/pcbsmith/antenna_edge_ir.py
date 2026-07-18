"""Source-bound declarations and replay evidence for antenna edge overhang."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.antenna_ir import AntennaModuleDeclaration, AntennaPlacementResult
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacedCompoundTransform,
    PlacementTransformAuthority,
    PlanarRelation,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticVerification,
)


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


def canonical_identities(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(require_identity(value, field_name) for value in values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} must contain unique identities")
    return canonical


class AntennaModuleSupportRegion(SemanticIrModel):
    """One exact module-local body or pad-support region from a pinned source."""

    schema_id: Literal["pcbsmith-antenna-module-support-region"] = (
        "pcbsmith-antenna-module-support-region"
    )
    schema_version: Literal[1] = 1
    support_region_id: str = Field(min_length=1)
    provenance_id: str = Field(min_length=1)
    role: Literal["body_support", "pad_support"]
    compound: ExactPlanarCompound
    layers: tuple[str, ...] = Field(min_length=1)
    installed_footprint_id: str = Field(min_length=1)
    component_uuid_path: str = Field(min_length=1)
    component_revision: str = Field(min_length=1)
    source_file_sha256: str
    source_binding_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def support_source_is_canonical(self) -> Self:
        for field_name in (
            "support_region_id",
            "provenance_id",
            "installed_footprint_id",
            "component_uuid_path",
            "component_revision",
            "source_binding_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(self.source_file_sha256, "source_file_sha256")
        object.__setattr__(self, "layers", canonical_identities(self.layers, "layers"))
        return self


def support_geometry_binding_fingerprint(
    antenna_declaration: AntennaModuleDeclaration,
    support_regions: Sequence[AntennaModuleSupportRegion],
) -> str:
    return _support_geometry_binding_fingerprint(
        antenna_declaration.semantic_fingerprint(), support_regions
    )


def _support_geometry_binding_fingerprint(
    antenna_declaration_fingerprint: str,
    support_regions: Sequence[AntennaModuleSupportRegion],
) -> str:
    return fingerprint(
        {
            "schema_id": "pcbsmith-antenna-support-geometry-binding",
            "schema_version": 1,
            "antenna_declaration_fingerprint": antenna_declaration_fingerprint,
            "support_regions": [
                item.model_dump(mode="json")
                for item in sorted(support_regions, key=lambda value: value.support_region_id)
            ],
        }
    )


class AntennaEdgeOverhangDeclaration(SemanticIrModel):
    """Companion authority for edge-overhang geometry only, never cutout strategy."""

    schema_id: Literal["pcbsmith-antenna-edge-overhang-declaration"] = (
        "pcbsmith-antenna-edge-overhang-declaration"
    )
    schema_version: Literal[1] = 1
    edge_declaration_id: str = Field(min_length=1)
    antenna_id: str = Field(min_length=1)
    module_reference: str = Field(min_length=1)
    antenna_declaration_fingerprint: str
    source_applicability_binding_id: str = Field(min_length=1)
    required_outside_region_ids: tuple[str, ...] = Field(min_length=1)
    support_regions: tuple[AntennaModuleSupportRegion, ...] = Field(min_length=1)
    support_geometry_binding: EvidenceApplicabilityBinding
    antenna_outside_rule_id: str = Field(min_length=1)
    support_inside_rule_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def companion_is_complete_and_source_bound(self) -> Self:
        for field_name in (
            "edge_declaration_id",
            "antenna_id",
            "module_reference",
            "source_applicability_binding_id",
            "antenna_outside_rule_id",
            "support_inside_rule_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(self.antenna_declaration_fingerprint, "antenna_declaration_fingerprint")
        object.__setattr__(
            self,
            "required_outside_region_ids",
            canonical_identities(self.required_outside_region_ids, "required_outside_region_ids"),
        )
        supports = tuple(sorted(self.support_regions, key=lambda item: item.support_region_id))
        ids = tuple(item.support_region_id for item in supports)
        provenance = tuple(item.provenance_id for item in supports)
        if len(ids) != len(set(ids)):
            raise ValueError("antenna support region identities must be unique")
        if len(provenance) != len(set(provenance)):
            raise ValueError("antenna support provenance identities must be unique")
        binding = self.support_geometry_binding
        if binding.unmatched_conditions or binding.reviewer_record_id is None:
            raise ValueError("support geometry applicability must be complete and reviewed")
        if any(item.source_binding_id != binding.binding_id for item in supports):
            raise ValueError("support region source binding is stale")
        for support in supports:
            if not any(
                evidence.source_status == "pinned"
                and evidence.locator_status in {"figure_bound", "figure_verified"}
                and evidence.applicability_status == "confirmed"
                and evidence.local_sha256 == support.source_file_sha256
                for evidence in binding.evidence
            ):
                raise ValueError("support geometry source file is not pinned by its binding")
        if binding.geometry_source_fingerprint != _support_geometry_binding_fingerprint(
            self.antenna_declaration_fingerprint, supports
        ):
            raise ValueError("support geometry binding fingerprint is stale")
        object.__setattr__(self, "support_regions", supports)
        return self


class AntennaBoardMaterialAuthority(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-board-material-authority"] = (
        "pcbsmith-antenna-board-material-authority"
    )
    schema_version: Literal[1] = 1
    board_layout_snapshot_fingerprint: str
    outer_polygon: ExactPlanarPolygon
    outer_compound: ExactPlanarCompound
    cutout_compounds: tuple[ExactPlanarCompound, ...]
    material_compound: ExactPlanarCompound
    board_material_fingerprint: str

    @model_validator(mode="after")
    def material_is_exact_and_fingerprinted(self) -> Self:
        require_sha256(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        require_sha256(self.board_material_fingerprint, "board_material_fingerprint")
        if self.outer_compound != ExactPlanarCompound(polygons=(self.outer_polygon,)):
            raise ValueError("board material outer compound is stale")
        expected_material = ExactPlanarCompound(
            polygons=(
                ExactPlanarPolygon(
                    outer=self.outer_polygon.outer,
                    holes=tuple(item.polygons[0].outer for item in self.cutout_compounds),
                ),
            )
        )
        if self.material_compound != expected_material:
            raise ValueError("board material compound is stale")
        payload = self.model_dump(mode="json", exclude={"board_material_fingerprint"})
        if self.board_material_fingerprint != fingerprint(payload):
            raise ValueError("board material fingerprint is stale")
        return self


class AntennaTransformedSupport(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-transformed-support"] = (
        "pcbsmith-antenna-transformed-support"
    )
    schema_version: Literal[1] = 1
    support_region: AntennaModuleSupportRegion
    bounded_transform: PlacedCompoundTransform
    exact_transformed_compound: ExactPlanarCompound | None
    verification: SemanticVerification

    @model_validator(mode="after")
    def transform_claim_is_coherent(self) -> Self:
        if self.bounded_transform.authority is PlacementTransformAuthority.EXACT:
            if (
                self.verification is not SemanticVerification.EXACT
                or self.exact_transformed_compound != self.bounded_transform.compound
            ):
                raise ValueError("exact support transform evidence is stale")
        elif (
            self.verification is not SemanticVerification.BOUNDED_APPROXIMATION
            or self.exact_transformed_compound is not None
        ):
            raise ValueError("bounded support transform cannot claim exact vertices")
        return self


class AntennaOutsideMaterialEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-outside-material-evidence"] = (
        "pcbsmith-antenna-outside-material-evidence"
    )
    schema_version: Literal[1] = 1
    region_id: str
    rule_id: str
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)
    material_relation: PlanarRelation | None
    verification: SemanticVerification
    disposition: SemanticDisposition

    @model_validator(mode="after")
    def outside_rule_is_coherent(self) -> Self:
        require_identity(self.region_id, "region_id")
        require_identity(self.rule_id, "rule_id")
        object.__setattr__(
            self,
            "evidence_binding_ids",
            canonical_identities(self.evidence_binding_ids, "evidence_binding_ids"),
        )
        if self.verification is SemanticVerification.BOUNDED_APPROXIMATION:
            if (
                self.material_relation is not None
                or self.disposition is not SemanticDisposition.UNVERIFIED
            ):
                raise ValueError("bounded outside evidence must be unverified")
        elif self.material_relation is PlanarRelation.DISJOINT:
            if self.disposition is not SemanticDisposition.PASS:
                raise ValueError("strictly outside exact antenna region must pass")
        elif self.material_relation in {
            PlanarRelation.BOUNDARY_TOUCH,
            PlanarRelation.INTERIOR_OVERLAP,
        }:
            if self.disposition is not SemanticDisposition.FAIL:
                raise ValueError("touching/overlapping board material must fail")
        else:
            raise ValueError("exact outside evidence requires a material relation")
        return self


class AntennaSupportMaterialEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-support-material-evidence"] = (
        "pcbsmith-antenna-support-material-evidence"
    )
    schema_version: Literal[1] = 1
    support_region_id: str
    rule_id: str
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)
    contained_in_outer: bool | None
    cutout_relations: tuple[tuple[str, PlanarRelation], ...]
    verification: SemanticVerification
    disposition: SemanticDisposition

    @model_validator(mode="after")
    def support_rule_is_coherent(self) -> Self:
        require_identity(self.support_region_id, "support_region_id")
        require_identity(self.rule_id, "rule_id")
        object.__setattr__(
            self,
            "evidence_binding_ids",
            canonical_identities(self.evidence_binding_ids, "evidence_binding_ids"),
        )
        cutouts = tuple(sorted(self.cutout_relations, key=lambda item: item[0]))
        if len({item[0] for item in cutouts}) != len(cutouts):
            raise ValueError("support cutout evidence identities must be unique")
        object.__setattr__(self, "cutout_relations", cutouts)
        if self.verification is SemanticVerification.BOUNDED_APPROXIMATION:
            if (
                self.contained_in_outer is not None
                or cutouts
                or self.disposition is not SemanticDisposition.UNVERIFIED
            ):
                raise ValueError("bounded support evidence must be unverified")
        else:
            passed = self.contained_in_outer is True and all(
                relation is PlanarRelation.DISJOINT for _, relation in cutouts
            )
            expected = SemanticDisposition.PASS if passed else SemanticDisposition.FAIL
            if self.contained_in_outer is None or self.disposition is not expected:
                raise ValueError("exact support material disposition is stale")
        return self


class AntennaEdgeOverhangResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-edge-overhang-result"] = (
        "pcbsmith-antenna-edge-overhang-result"
    )
    schema_version: Literal[1] = 1
    placement_result: AntennaPlacementResult
    declaration: AntennaEdgeOverhangDeclaration
    board_material: AntennaBoardMaterialAuthority
    transformed_supports: tuple[AntennaTransformedSupport, ...]
    outside_evidence: tuple[AntennaOutsideMaterialEvidence, ...]
    support_evidence: tuple[AntennaSupportMaterialEvidence, ...]
    evidence_fingerprint: str
    semantic_result: SemanticLayoutResult
    result_fingerprint: str

    @field_validator("evidence_fingerprint", "result_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        from pcbsmith.kicad.antenna_edge import rederive_antenna_edge_overhang

        expected = rederive_antenna_edge_overhang(self.placement_result, self.declaration)
        compared = (
            "declaration",
            "board_material",
            "transformed_supports",
            "outside_evidence",
            "support_evidence",
            "evidence_fingerprint",
            "semantic_result",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("antenna edge-overhang evidence/result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("antenna edge-overhang result fingerprint is stale")
        return self
