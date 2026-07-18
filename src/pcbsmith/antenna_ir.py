"""Versioned, module-specific antenna geometry and placement authority.

This first R6.2 slice retains and places source-derived module geometry.  It
does not inspect board objects, prove edge/cutout disposition, inspect an
enclosure, or claim RF performance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    PlacedCompoundTransform,
    PlacementTransform,
    PlacementTransformAuthority,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticIrModel,
    SemanticVerification,
)

AntennaObjectKind = Literal["track", "via", "pad", "zone", "footprint", "board_material"]
AntennaPlacementStrategy = Literal["edge_overhang", "baseboard_cutout"]
AntennaRegionRole = Literal["antenna", "feed", "keepout"]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def _sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _canonical_identities(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(_identity(value, field_name) for value in values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} must contain unique identities")
    return canonical


class AntennaLocalRegion(SemanticIrModel):
    """One exact source-derived antenna or feed region in module coordinates."""

    schema_id: Literal["pcbsmith-antenna-local-region"] = "pcbsmith-antenna-local-region"
    schema_version: Literal[1] = 1
    region_id: str = Field(min_length=1)
    role: Literal["antenna", "feed"]
    compound: ExactPlanarCompound
    layers: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonicalize(self) -> Self:
        _identity(self.region_id, "region_id")
        object.__setattr__(self, "layers", _canonical_identities(self.layers, "layers"))
        return self


class InstalledFootprintKeepoutProvenance(SemanticIrModel):
    """Exact keepout retained from one selected installed footprint revision."""

    schema_id: Literal["pcbsmith-installed-footprint-keepout-provenance"] = (
        "pcbsmith-installed-footprint-keepout-provenance"
    )
    schema_version: Literal[1] = 1
    provenance_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    selected_footprint_library_id: str = Field(min_length=1)
    component_uuid_path: str = Field(min_length=1)
    component_revision: str = Field(min_length=1)
    component_revision_field_name: str = Field(min_length=1)
    source_file_sha256: str
    module_guidance_binding_id: str = Field(min_length=1)
    prohibited_object_rule_id: str = Field(min_length=1)
    compound: ExactPlanarCompound
    layers: tuple[str, ...] = Field(min_length=1)
    prohibited_object_kinds: tuple[AntennaObjectKind, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonicalize(self) -> Self:
        for field_name in (
            "provenance_id",
            "region_id",
            "selected_footprint_library_id",
            "component_uuid_path",
            "component_revision",
            "component_revision_field_name",
            "module_guidance_binding_id",
            "prohibited_object_rule_id",
        ):
            _identity(getattr(self, field_name), field_name)
        _sha256(self.source_file_sha256, "source_file_sha256")
        object.__setattr__(self, "layers", _canonical_identities(self.layers, "layers"))
        kinds = tuple(sorted(self.prohibited_object_kinds))
        if len(kinds) != len(set(kinds)):
            raise ValueError("prohibited_object_kinds must contain unique values")
        object.__setattr__(self, "prohibited_object_kinds", kinds)
        return self


def antenna_geometry_source_fingerprint(
    antenna_region: AntennaLocalRegion,
    feed_region: AntennaLocalRegion,
    keepouts: Sequence[InstalledFootprintKeepoutProvenance],
) -> str:
    """Fingerprint the complete local geometry governed by module guidance."""

    return _fingerprint(
        {
            "schema_id": "pcbsmith-antenna-local-geometry-source",
            "schema_version": 1,
            "antenna_region": antenna_region.model_dump(mode="json"),
            "feed_region": feed_region.model_dump(mode="json"),
            "keepouts": [
                item.model_dump(mode="json")
                for item in sorted(keepouts, key=lambda value: value.region_id)
            ],
        }
    )


class AntennaModuleDeclaration(SemanticIrModel):
    """Exact identity and local geometry for one selected antenna module."""

    schema_id: Literal["pcbsmith-antenna-module-declaration"] = (
        "pcbsmith-antenna-module-declaration"
    )
    schema_version: Literal[1] = 1
    antenna_id: str = Field(min_length=1)
    module_reference: str = Field(min_length=1)
    selected_footprint_library_id: str = Field(min_length=1)
    component_uuid_path: str = Field(min_length=1)
    component_revision: str = Field(min_length=1)
    component_revision_field_name: str = Field(min_length=1)
    source_file_sha256: str
    module_guidance_binding: EvidenceApplicabilityBinding
    antenna_region: AntennaLocalRegion
    feed_region: AntennaLocalRegion
    keepouts: tuple[InstalledFootprintKeepoutProvenance, ...] = Field(min_length=1)
    placement_strategy: AntennaPlacementStrategy
    edge_or_cutout_requirement_id: str = Field(min_length=1)
    enclosure_exclusion_requirement_id: str = Field(min_length=1)
    rf_validation_requirement_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def declaration_is_complete_and_source_bound(self) -> Self:
        for field_name in (
            "antenna_id",
            "module_reference",
            "selected_footprint_library_id",
            "component_uuid_path",
            "component_revision",
            "component_revision_field_name",
            "edge_or_cutout_requirement_id",
            "enclosure_exclusion_requirement_id",
            "rf_validation_requirement_id",
        ):
            _identity(getattr(self, field_name), field_name)
        _sha256(self.source_file_sha256, "source_file_sha256")
        if self.antenna_region.role != "antenna" or self.feed_region.role != "feed":
            raise ValueError("antenna_region and feed_region roles must match their fields")
        keepouts = tuple(sorted(self.keepouts, key=lambda item: item.region_id))
        region_ids = (
            self.antenna_region.region_id,
            self.feed_region.region_id,
            *(item.region_id for item in keepouts),
        )
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("antenna region identities must be unique")
        provenance_ids = tuple(item.provenance_id for item in keepouts)
        if len(provenance_ids) != len(set(provenance_ids)):
            raise ValueError("installed-footprint keepout provenance identities must be unique")
        binding = self.module_guidance_binding
        if binding.unmatched_conditions or binding.reviewer_record_id is None:
            raise ValueError("module guidance applicability must be complete and reviewed")
        if binding.geometry_source_fingerprint is None:
            raise ValueError("module guidance must bind the exact local geometry source")
        if not any(
            evidence.source_status == "pinned"
            and evidence.locator_status in {"figure_bound", "figure_verified"}
            and evidence.applicability_status == "confirmed"
            and evidence.local_sha256 == self.source_file_sha256
            for evidence in binding.evidence
        ):
            raise ValueError("module guidance must pin the declared source file and figure")
        for keepout in keepouts:
            if (
                keepout.selected_footprint_library_id != self.selected_footprint_library_id
                or keepout.component_uuid_path != self.component_uuid_path
                or keepout.component_revision != self.component_revision
                or keepout.component_revision_field_name
                != self.component_revision_field_name
                or keepout.source_file_sha256 != self.source_file_sha256
                or keepout.module_guidance_binding_id != binding.binding_id
            ):
                raise ValueError("installed-footprint keepout provenance is stale")
        expected_geometry = antenna_geometry_source_fingerprint(
            self.antenna_region, self.feed_region, keepouts
        )
        if binding.geometry_source_fingerprint != expected_geometry:
            raise ValueError("module guidance geometry fingerprint is stale")
        object.__setattr__(self, "keepouts", keepouts)
        return self


class AntennaPlacedRegion(SemanticIrModel):
    """One local region plus the shared-kernel placed transform authority."""

    schema_id: Literal["pcbsmith-antenna-placed-region"] = "pcbsmith-antenna-placed-region"
    schema_version: Literal[1] = 1
    region_id: str
    role: AntennaRegionRole
    local_compound: ExactPlanarCompound
    layers: tuple[str, ...]
    prohibited_object_kinds: tuple[AntennaObjectKind, ...] = ()
    bounded_transform: PlacedCompoundTransform
    exact_transformed_compound: ExactPlanarCompound | None
    verification: SemanticVerification

    @model_validator(mode="after")
    def transform_claim_is_coherent(self) -> Self:
        _identity(self.region_id, "region_id")
        object.__setattr__(self, "layers", _canonical_identities(self.layers, "layers"))
        if self.role == "keepout" and not self.prohibited_object_kinds:
            raise ValueError("placed keepouts require prohibited object kinds")
        if self.role != "keepout" and self.prohibited_object_kinds:
            raise ValueError("antenna/feed regions cannot prohibit object kinds")
        kinds = tuple(sorted(self.prohibited_object_kinds))
        if len(kinds) != len(set(kinds)):
            raise ValueError("prohibited_object_kinds must contain unique values")
        object.__setattr__(self, "prohibited_object_kinds", kinds)
        if self.bounded_transform.authority is PlacementTransformAuthority.EXACT:
            if (
                self.verification is not SemanticVerification.EXACT
                or self.exact_transformed_compound != self.bounded_transform.compound
            ):
                raise ValueError("exact placed region must retain the exact transformed compound")
        elif (
            self.verification is not SemanticVerification.BOUNDED_APPROXIMATION
            or self.exact_transformed_compound is not None
        ):
            raise ValueError("bounded placed region cannot claim exact transformed vertices")
        return self


class AntennaPlacementResult(SemanticIrModel):
    """Replay-valid placement-only result for one module declaration."""

    schema_id: Literal["pcbsmith-antenna-placement-result"] = (
        "pcbsmith-antenna-placement-result"
    )
    schema_version: Literal[1] = 1
    declaration: AntennaModuleDeclaration
    transform: PlacementTransform
    placed_regions: tuple[AntennaPlacedRegion, ...]
    board_layout_snapshot_json: str = Field(min_length=2)
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_json: str = Field(min_length=2)
    board_netlist_snapshot_fingerprint: str
    result_fingerprint: str

    @model_validator(mode="after")
    def replay_and_fingerprint_are_exact(self) -> Self:
        layout = parse_canonical_board_layout_snapshot(self.board_layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.board_netlist_snapshot_json)
        if self.board_layout_snapshot_fingerprint != board_layout_snapshot_fingerprint(
            self.board_layout_snapshot_json
        ):
            raise ValueError("board layout snapshot fingerprint is stale")
        if self.board_netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            self.board_netlist_snapshot_json
        ):
            raise ValueError("board netlist snapshot fingerprint is stale")
        expected_transform, expected_regions = derive_antenna_placement(
            layout, netlist, self.declaration
        )
        if self.transform != expected_transform or self.placed_regions != expected_regions:
            raise ValueError("antenna placement result does not replay from retained snapshots")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != _fingerprint(payload):
            raise ValueError("antenna placement result fingerprint is stale")
        return self


def derive_antenna_placement(
    layout: Any, netlist: Any, declaration: AntennaModuleDeclaration
) -> tuple[PlacementTransform, tuple[AntennaPlacedRegion, ...]]:
    """Shared replay derivation, imported lazily to keep IR engine-neutral."""

    from pcbsmith.kicad.antenna_semantics import derive_antenna_placement as derive

    return derive(layout, netlist, declaration)


def antenna_placement_result_fingerprint(payload_without_fingerprint: Any) -> str:
    return _fingerprint(payload_without_fingerprint)
