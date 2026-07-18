"""Source-bound declarations and replay evidence for baseboard antenna cutouts.

This bounded R6.2 slice proves only the selected-cutout and module-support
geometry rules.  It does not infer a cutout, authorize component-wide
exceptions, inspect an enclosure, or claim RF performance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from math import gcd
from typing import Any, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from pcbsmith.antenna_edge_ir import (
    AntennaBoardMaterialAuthority,
    AntennaModuleSupportRegion,
    AntennaTransformedSupport,
    support_geometry_binding_fingerprint,
)
from pcbsmith.antenna_ir import AntennaModuleDeclaration, AntennaPlacementResult
from pcbsmith.kicad.board_region import BoardCutoutPolygon
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon, PlanarRelation
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


def board_cutout_identity(cutout_fingerprint: str) -> str:
    """Return the canonical identity for one typed ``BoardCutoutPolygon``."""

    require_sha256(cutout_fingerprint, "cutout_fingerprint")
    return f"board-cutout:{cutout_fingerprint}"


class AntennaSelectedBoardCutout(SemanticIrModel):
    """Explicit selection of one typed cutout in one retained board snapshot."""

    schema_id: Literal["pcbsmith-antenna-selected-board-cutout"] = (
        "pcbsmith-antenna-selected-board-cutout"
    )
    schema_version: Literal[1] = 1
    cutout_id: str = Field(min_length=1)
    cutout_fingerprint: str
    cutout_compound: ExactPlanarCompound
    board_layout_snapshot_fingerprint: str
    selection_fingerprint: str

    @model_validator(mode="after")
    def selected_cutout_is_typed_exact_and_snapshot_bound(self) -> Self:
        require_identity(self.cutout_id, "cutout_id")
        require_sha256(self.cutout_fingerprint, "cutout_fingerprint")
        require_sha256(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        require_sha256(self.selection_fingerprint, "selection_fingerprint")
        if len(self.cutout_compound.polygons) != 1 or self.cutout_compound.polygons[0].holes:
            raise ValueError("selected board cutout must be one hole-free polygon")
        typed = BoardCutoutPolygon(points=self.cutout_compound.polygons[0].outer)
        if self.cutout_fingerprint != typed.semantic_fingerprint():
            raise ValueError("selected cutout typed fingerprint is stale")
        if self.cutout_id != board_cutout_identity(self.cutout_fingerprint):
            raise ValueError("selected cutout identity is stale")
        payload = self.model_dump(mode="json", exclude={"selection_fingerprint"})
        if self.selection_fingerprint != fingerprint(payload):
            raise ValueError("selected cutout selection fingerprint is stale")
        return self


def build_selected_board_cutout(
    cutout: BoardCutoutPolygon, board_layout_snapshot_fingerprint: str
) -> AntennaSelectedBoardCutout:
    """Build an explicit companion selection from a caller-chosen typed cutout."""

    cutout_fp = cutout.semantic_fingerprint()
    cutout_id = board_cutout_identity(cutout_fp)
    cutout_compound = ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=cutout.points),))
    provisional = AntennaSelectedBoardCutout.model_construct(
        cutout_id=cutout_id,
        cutout_fingerprint=cutout_fp,
        cutout_compound=cutout_compound,
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint,
        selection_fingerprint="0" * 64,
    )
    selection_fp = fingerprint(
        provisional.model_dump(mode="json", exclude={"selection_fingerprint"})
    )
    return AntennaSelectedBoardCutout(
        cutout_id=cutout_id,
        cutout_fingerprint=cutout_fp,
        cutout_compound=cutout_compound,
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint,
        selection_fingerprint=selection_fp,
    )


class AntennaCutoutDeclaration(SemanticIrModel):
    """Companion authority for the baseboard-cutout strategy only."""

    schema_id: Literal["pcbsmith-antenna-cutout-declaration"] = (
        "pcbsmith-antenna-cutout-declaration"
    )
    schema_version: Literal[1] = 1
    cutout_declaration_id: str = Field(min_length=1)
    antenna_id: str = Field(min_length=1)
    module_reference: str = Field(min_length=1)
    antenna_declaration_fingerprint: str
    source_applicability_binding_id: str = Field(min_length=1)
    required_cutout_region_ids: tuple[str, ...] = Field(min_length=1)
    selected_cutout: AntennaSelectedBoardCutout
    support_regions: tuple[AntennaModuleSupportRegion, ...] = Field(min_length=1)
    support_geometry_binding: EvidenceApplicabilityBinding
    antenna_inside_cutout_rule_id: str = Field(min_length=1)
    support_inside_material_rule_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def companion_is_complete_and_source_bound(self) -> Self:
        for field_name in (
            "cutout_declaration_id",
            "antenna_id",
            "module_reference",
            "source_applicability_binding_id",
            "antenna_inside_cutout_rule_id",
            "support_inside_material_rule_id",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(self.antenna_declaration_fingerprint, "antenna_declaration_fingerprint")
        object.__setattr__(
            self,
            "required_cutout_region_ids",
            canonical_identities(self.required_cutout_region_ids, "required_cutout_region_ids"),
        )
        supports = tuple(sorted(self.support_regions, key=lambda item: item.support_region_id))
        support_ids = tuple(item.support_region_id for item in supports)
        provenance_ids = tuple(item.provenance_id for item in supports)
        if len(support_ids) != len(set(support_ids)):
            raise ValueError("antenna support region identities must be unique")
        if len(provenance_ids) != len(set(provenance_ids)):
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
        if binding.geometry_source_fingerprint != support_geometry_binding_fingerprint_from_fp(
            self.antenna_declaration_fingerprint, supports
        ):
            raise ValueError("support geometry binding fingerprint is stale")
        object.__setattr__(self, "support_regions", supports)
        return self


def support_geometry_binding_fingerprint_from_fp(
    antenna_declaration_fingerprint: str,
    support_regions: Sequence[AntennaModuleSupportRegion],
) -> str:
    """Mirror the shared support binding using an already pinned declaration digest."""

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


def support_binding_for_declaration(
    antenna_declaration: AntennaModuleDeclaration,
    support_regions: Sequence[AntennaModuleSupportRegion],
) -> str:
    """Public shared binding helper retained for fixture callers."""

    return support_geometry_binding_fingerprint(antenna_declaration, support_regions)


class ExactSquaredBoundaryClearance(SemanticIrModel):
    """Reduced exact squared boundary clearance in square millimetres."""

    schema_id: Literal["pcbsmith-exact-squared-boundary-clearance"] = (
        "pcbsmith-exact-squared-boundary-clearance"
    )
    schema_version: Literal[1] = 1
    numerator: StrictInt = Field(ge=0)
    denominator: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def fraction_is_reduced(self) -> Self:
        if gcd(self.numerator, self.denominator) != 1:
            raise ValueError("exact squared boundary clearance must be reduced")
        return self


class AntennaInsideSelectedCutoutEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-inside-selected-cutout-evidence"] = (
        "pcbsmith-antenna-inside-selected-cutout-evidence"
    )
    schema_version: Literal[1] = 1
    region_id: str
    selected_cutout_id: str
    selected_cutout_fingerprint: str
    rule_id: str
    evidence_binding_ids: tuple[str, ...] = Field(min_length=1)
    contained_in_selected_cutout_closed: bool | None
    selected_cutout_boundary_squared_clearance: ExactSquaredBoundaryClearance | None
    material_relation: PlanarRelation | None
    verification: SemanticVerification
    disposition: SemanticDisposition

    @model_validator(mode="after")
    def cutout_rule_is_coherent(self) -> Self:
        for field_name in ("region_id", "selected_cutout_id", "rule_id"):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(self.selected_cutout_fingerprint, "selected_cutout_fingerprint")
        if self.selected_cutout_id != board_cutout_identity(self.selected_cutout_fingerprint):
            raise ValueError("selected cutout evidence identity is stale")
        object.__setattr__(
            self,
            "evidence_binding_ids",
            canonical_identities(self.evidence_binding_ids, "evidence_binding_ids"),
        )
        if self.verification is SemanticVerification.BOUNDED_APPROXIMATION:
            if (
                self.contained_in_selected_cutout_closed is not None
                or self.selected_cutout_boundary_squared_clearance is not None
                or self.material_relation is not None
                or self.disposition is not SemanticDisposition.UNVERIFIED
            ):
                raise ValueError("bounded cutout evidence must be independently unverified")
            return self
        if self.verification is not SemanticVerification.EXACT:
            raise ValueError("cutout evidence verification must be exact or bounded")
        if (
            self.contained_in_selected_cutout_closed is None
            or self.selected_cutout_boundary_squared_clearance is None
            or self.material_relation is None
        ):
            raise ValueError("exact cutout evidence must retain every exact predicate")
        passed = (
            self.contained_in_selected_cutout_closed
            and self.selected_cutout_boundary_squared_clearance.numerator > 0
            and self.material_relation is PlanarRelation.DISJOINT
        )
        expected = SemanticDisposition.PASS if passed else SemanticDisposition.FAIL
        if self.disposition is not expected:
            raise ValueError("exact cutout disposition is stale")
        return self


class AntennaCutoutSupportEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-cutout-support-evidence"] = (
        "pcbsmith-antenna-cutout-support-evidence"
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
        cutouts = tuple(
            sorted(
                (
                    (require_identity(cutout_id, "cutout relation identity"), relation)
                    for cutout_id, relation in self.cutout_relations
                ),
                key=lambda item: item[0],
            )
        )
        if len({item[0] for item in cutouts}) != len(cutouts):
            raise ValueError("support cutout evidence identities must be unique")
        object.__setattr__(self, "cutout_relations", cutouts)
        if self.verification is SemanticVerification.BOUNDED_APPROXIMATION:
            if (
                self.contained_in_outer is not None
                or cutouts
                or self.disposition is not SemanticDisposition.UNVERIFIED
            ):
                raise ValueError("bounded support evidence must be independently unverified")
        else:
            if self.verification is not SemanticVerification.EXACT:
                raise ValueError("support evidence verification must be exact or bounded")
            if not cutouts:
                raise ValueError("exact cutout support evidence must cover every board cutout")
            passed = self.contained_in_outer is True and all(
                relation is PlanarRelation.DISJOINT for _, relation in cutouts
            )
            expected = SemanticDisposition.PASS if passed else SemanticDisposition.FAIL
            if self.contained_in_outer is None or self.disposition is not expected:
                raise ValueError("exact support disposition is stale")
        return self


class AntennaCutoutResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-antenna-cutout-result"] = "pcbsmith-antenna-cutout-result"
    schema_version: Literal[1] = 1
    placement_result: AntennaPlacementResult
    declaration: AntennaCutoutDeclaration
    board_material: AntennaBoardMaterialAuthority
    selected_cutout: AntennaSelectedBoardCutout
    transformed_supports: tuple[AntennaTransformedSupport, ...]
    cutout_evidence: tuple[AntennaInsideSelectedCutoutEvidence, ...]
    support_evidence: tuple[AntennaCutoutSupportEvidence, ...]
    evidence_fingerprint: str
    semantic_result: SemanticLayoutResult
    result_fingerprint: str

    @field_validator("evidence_fingerprint", "result_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        from pcbsmith.kicad.antenna_cutout import rederive_antenna_cutout

        expected = rederive_antenna_cutout(self.placement_result, self.declaration)
        compared = (
            "declaration",
            "board_material",
            "selected_cutout",
            "transformed_supports",
            "cutout_evidence",
            "support_evidence",
            "evidence_fingerprint",
            "semantic_result",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("antenna cutout evidence/result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("antenna cutout result fingerprint is stale")
        return self
