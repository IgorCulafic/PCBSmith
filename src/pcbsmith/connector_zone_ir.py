"""Replay-bound IR for exact R6 connector-zone geometry and typed requirements."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, PlacedCompoundTransform
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticIrModel,
    SemanticLayoutResult,
    SemanticQuantity,
    SemanticRegion,
    SemanticVerification,
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _identity(value: str, name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed identity")
    return value


def _sha(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _identities(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    result = tuple(sorted(_identity(value, name) for value in values))
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must contain unique identities")
    return result


def evidence_binding_is_complete(binding: EvidenceApplicabilityBinding) -> bool:
    return (
        binding.reviewer_record_id is not None
        and bool(binding.required_conditions)
        and not binding.unmatched_conditions
        and bool(binding.evidence)
        and all(
            item.source_status == "pinned"
            and item.local_sha256 is not None
            and item.locator_status in {"text_verified", "figure_verified", "figure_bound"}
            and item.applicability_status == "confirmed"
            for item in binding.evidence
        )
    )


def outline_edge_id(start: tuple[float, float], end: tuple[float, float]) -> str:
    """Stable orientation-independent identity for one actual outline segment."""

    canonical = tuple(sorted((start, end)))
    return f"outline-edge:{fingerprint(canonical)}"


def connector_threshold_context_fingerprint(
    layout_fingerprint: str,
    netlist_fingerprint: str,
    connector_references: tuple[str, ...],
    connector_role: ConnectorRole,
    zone_fingerprint: str,
    allowed_edge_ids: tuple[str, ...],
    hard_threshold_fingerprints: tuple[str, ...] = (),
) -> str:
    """Exact applicability context shared by every connector numeric threshold."""

    return fingerprint(
        {
            "layout": layout_fingerprint,
            "netlist": netlist_fingerprint,
            "connector_references": connector_references,
            "connector_role": connector_role,
            "zone": zone_fingerprint,
            "allowed_edge_ids": allowed_edge_ids,
            "hard_thresholds": tuple(sorted(hard_threshold_fingerprints)),
        }
    )


class ConnectorRole(StrEnum):
    OFF_BOARD_IO = "off_board_io"
    POWER_ENTRY = "power_entry"
    ON_BOARD_MODULE = "on_board_module"
    TEST_FIXTURE = "test_fixture"
    INTERNAL_HARNESS = "internal_harness"


class ConnectorRequirementKind(StrEnum):
    FILTER_CHAIN = "filter_chain"
    GROUND_PIN_SPREAD = "ground_pin_spread"
    OSCILLATOR_SEPARATION = "oscillator_separation"
    ENCLOSURE_ACCESS = "enclosure_access"


class ConnectorPadGeometry(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-pad-geometry"] = "pcbsmith-connector-pad-geometry"
    schema_version: Literal[1] = 1
    pad_id: str
    compound: ExactPlanarCompound
    layers: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_pad(self) -> Self:
        _identity(self.pad_id, "pad_id")
        object.__setattr__(self, "layers", _identities(self.layers, "layers"))
        return self


class ConnectorLocalGeometry(SemanticIrModel):
    """Exact connector-local body and pad source geometry, never a width/height box."""

    schema_id: Literal["pcbsmith-connector-local-geometry"] = "pcbsmith-connector-local-geometry"
    schema_version: Literal[1] = 1
    reference: str
    installed_footprint_id: str
    component_uuid_path: str
    source_file_sha256: str
    source_binding_id: str
    body_region_id: str
    body_compound: ExactPlanarCompound
    body_layers: tuple[str, ...] = Field(min_length=1)
    pads: tuple[ConnectorPadGeometry, ...] = Field(min_length=1)
    geometry_fingerprint: str

    @model_validator(mode="after")
    def source_and_geometry_are_exact(self) -> Self:
        for name in (
            "reference",
            "installed_footprint_id",
            "component_uuid_path",
            "source_binding_id",
            "body_region_id",
        ):
            _identity(getattr(self, name), name)
        _sha(self.source_file_sha256, "source_file_sha256")
        _sha(self.geometry_fingerprint, "geometry_fingerprint")
        object.__setattr__(self, "body_layers", _identities(self.body_layers, "body_layers"))
        pads = tuple(sorted(self.pads, key=lambda item: item.pad_id))
        if len({item.pad_id for item in pads}) != len(pads):
            raise ValueError("connector pad identities must be unique")
        object.__setattr__(self, "pads", pads)
        payload = self.model_dump(mode="json", exclude={"geometry_fingerprint"})
        if self.geometry_fingerprint != fingerprint(payload):
            raise ValueError("connector local geometry fingerprint is stale")
        return self


class ConnectorRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-zone-requirement"] = (
        "pcbsmith-connector-zone-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    rule_id: str
    kind: ConnectorRequirementKind
    authority: Literal[
        SemanticAuthorityClass.HARD_GEOMETRY,
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
    ]
    source_binding_ids: tuple[str, ...] = Field(min_length=1)
    expected_component_order: tuple[str, ...] = ()
    minimum_ground_pin_count: int | None = Field(default=None, ge=1)
    minimum_ground_pin_spread: SemanticQuantity | None = None
    minimum_separation: SemanticQuantity | None = None

    @model_validator(mode="after")
    def typed_requirement(self) -> Self:
        _identity(self.requirement_id, "requirement_id")
        _identity(self.rule_id, "rule_id")
        object.__setattr__(
            self,
            "source_binding_ids",
            _identities(self.source_binding_ids, "source_binding_ids"),
        )
        order = tuple(
            _identity(item, "expected_component_order") for item in self.expected_component_order
        )
        if len(order) != len(set(order)):
            raise ValueError("filter-chain expected order must contain unique references")
        object.__setattr__(self, "expected_component_order", order)
        if self.kind is ConnectorRequirementKind.FILTER_CHAIN:
            if (
                not order
                or self.minimum_ground_pin_count is not None
                or self.minimum_ground_pin_spread
                or self.minimum_separation
            ):
                raise ValueError("filter-chain requirement needs only an explicit expected order")
        elif self.kind is ConnectorRequirementKind.GROUND_PIN_SPREAD:
            if (
                self.minimum_ground_pin_count is None
                or self.minimum_ground_pin_spread is None
                or self.minimum_ground_pin_spread.unit != "mm"
                or self.minimum_ground_pin_spread.value < 0
                or order
                or self.minimum_separation
            ):
                raise ValueError(
                    "ground-pin requirement needs exact count and non-negative mm spread"
                )
        elif self.kind is ConnectorRequirementKind.OSCILLATOR_SEPARATION:
            if (
                self.minimum_separation is None
                or self.minimum_separation.unit != "mm"
                or self.minimum_separation.value < 0
                or order
                or self.minimum_ground_pin_count is not None
                or self.minimum_ground_pin_spread
            ):
                raise ValueError("oscillator separation needs only a non-negative mm threshold")
        elif (
            order
            or self.minimum_ground_pin_count is not None
            or self.minimum_ground_pin_spread
            or self.minimum_separation
        ):
            raise ValueError("enclosure-access requirement has no generic numeric surrogate")
        return self


class ConnectorRequirementModel(SemanticIrModel):
    """Optional exact supplied topology/model; names are never inferred."""

    schema_id: Literal["pcbsmith-connector-requirement-model"] = (
        "pcbsmith-connector-requirement-model"
    )
    schema_version: Literal[1] = 1
    model_id: str
    requirement_id: str
    kind: ConnectorRequirementKind
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    source_binding_ids: tuple[str, ...] = Field(min_length=1)
    ordered_component_refs: tuple[str, ...] = ()
    ground_pad_ids: tuple[str, ...] = ()
    exact_region: SemanticRegion | None = None

    @model_validator(mode="after")
    def explicit_model(self) -> Self:
        _identity(self.model_id, "model_id")
        _identity(self.requirement_id, "requirement_id")
        _sha(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        _sha(self.board_netlist_snapshot_fingerprint, "board_netlist_snapshot_fingerprint")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        order = tuple(
            _identity(item, "ordered_component_refs") for item in self.ordered_component_refs
        )
        if len(order) != len(set(order)):
            raise ValueError("supplied filter path must not repeat components")
        object.__setattr__(self, "ordered_component_refs", order)
        object.__setattr__(
            self, "ground_pad_ids", _identities(self.ground_pad_ids, "ground_pad_ids")
        )
        if self.kind is ConnectorRequirementKind.FILTER_CHAIN:
            if not order or self.ground_pad_ids or self.exact_region is not None:
                raise ValueError("filter model requires only exact ordered topology")
        elif self.kind is ConnectorRequirementKind.GROUND_PIN_SPREAD:
            if not self.ground_pad_ids or order or self.exact_region is not None:
                raise ValueError("ground model requires only explicit connector pad identities")
        else:
            region = self.exact_region
            if (
                region is None
                or region.coordinate_space != "board"
                or region.verification is not SemanticVerification.EXACT
                or order
                or self.ground_pad_ids
            ):
                raise ValueError("separation/access model requires one exact board region")
        return self


class ConnectorZoneDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-zone-declaration"] = (
        "pcbsmith-connector-zone-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str
    zone_id: str
    board_layout_snapshot_json: str
    board_netlist_snapshot_json: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    connector_references: tuple[str, ...] = Field(min_length=1)
    connector_role: ConnectorRole
    zone_region: SemanticRegion
    allowed_edge_ids: tuple[str, ...] = Field(min_length=1)
    maximum_body_to_edge_distance: SemanticQuantity | None = None
    maximum_edge_authority: Literal[
        SemanticAuthorityClass.HARD_GEOMETRY,
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
    ] = SemanticAuthorityClass.HARD_GEOMETRY
    connector_geometries: tuple[ConnectorLocalGeometry, ...] = Field(min_length=1)
    body_zone_rule_id: str
    pad_zone_rule_id: str
    body_material_rule_id: str
    pad_material_rule_id: str
    edge_rule_id: str
    filter_chain_requirement: ConnectorRequirement | None = None
    ground_pin_spread_requirement: ConnectorRequirement | None = None
    oscillator_separation_requirement: ConnectorRequirement | None = None
    enclosure_access_requirement: ConnectorRequirement | None = None
    evidence_bindings: tuple[EvidenceApplicabilityBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def replay_scope_is_complete(self) -> Self:
        for name in (
            "declaration_id",
            "zone_id",
            "body_zone_rule_id",
            "pad_zone_rule_id",
            "body_material_rule_id",
            "pad_material_rule_id",
            "edge_rule_id",
        ):
            _identity(getattr(self, name), name)
        layout = parse_canonical_board_layout_snapshot(self.board_layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.board_netlist_snapshot_json)
        if canonical_board_layout_snapshot_json(layout) != self.board_layout_snapshot_json:
            raise ValueError("BoardLayout snapshot is noncanonical")
        if canonical_board_netlist_snapshot_json(netlist) != self.board_netlist_snapshot_json:
            raise ValueError("BoardNetlist snapshot is noncanonical")
        if (
            board_layout_snapshot_fingerprint(self.board_layout_snapshot_json)
            != self.board_layout_snapshot_fingerprint
        ):
            raise ValueError("BoardLayout snapshot fingerprint is stale")
        if (
            board_netlist_snapshot_fingerprint(self.board_netlist_snapshot_json)
            != self.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("BoardNetlist snapshot fingerprint is stale")
        refs = {item.reference: item for item in netlist.components}
        connector_refs = _identities(self.connector_references, "connector_references")
        if not set(connector_refs).issubset(refs):
            raise ValueError("connector declaration references components absent from BoardNetlist")
        object.__setattr__(self, "connector_references", connector_refs)
        if (
            self.zone_region.region_id != self.zone_id
            or self.zone_region.coordinate_space != "board"
            or self.zone_region.verification is not SemanticVerification.EXACT
        ):
            raise ValueError("connector zone requires its exact board-coordinate SemanticRegion")
        outline = layout.outline or (
            (0.0, 0.0),
            (layout.width_mm, 0.0),
            (layout.width_mm, layout.height_mm),
            (0.0, layout.height_mm),
        )
        actual_edges = {
            outline_edge_id(outline[index], outline[(index + 1) % len(outline)])
            for index in range(len(outline))
        }
        allowed = _identities(self.allowed_edge_ids, "allowed_edge_ids")
        if not set(allowed).issubset(actual_edges):
            raise ValueError("allowed edge identity is absent from the actual shaped outline")
        object.__setattr__(self, "allowed_edge_ids", allowed)
        geometries = tuple(sorted(self.connector_geometries, key=lambda item: item.reference))
        if tuple(item.reference for item in geometries) != connector_refs:
            raise ValueError("connector geometry must exactly cover declared connector references")
        for geometry in geometries:
            component = refs[geometry.reference]
            if (
                geometry.installed_footprint_id != component.footprint
                or geometry.component_uuid_path != component.uuid_path
            ):
                raise ValueError("connector geometry source/component identity is stale")
        object.__setattr__(self, "connector_geometries", geometries)
        bindings = tuple(sorted(self.evidence_bindings, key=lambda item: item.binding_id))
        binding_by_id = {item.binding_id: item for item in bindings}
        if len(bindings) != len(binding_by_id):
            raise ValueError("evidence binding identities must be unique")
        required = set(self.zone_region.source_binding_ids)
        required.update(item.source_binding_id for item in geometries)
        requirements = (
            self.filter_chain_requirement,
            self.ground_pin_spread_requirement,
            self.oscillator_separation_requirement,
            self.enclosure_access_requirement,
        )
        expected_kinds = tuple(ConnectorRequirementKind)
        seen_ids: set[str] = set()
        for requirement, expected_kind in zip(requirements, expected_kinds, strict=True):
            if requirement is not None:
                if requirement.kind is not expected_kind:
                    raise ValueError("connector optional requirement is in the wrong typed slot")
                if requirement.requirement_id in seen_ids:
                    raise ValueError("connector requirement identities must be unique")
                seen_ids.add(requirement.requirement_id)
                required.update(requirement.source_binding_ids)
                if requirement.minimum_ground_pin_spread is not None:
                    required.update(requirement.minimum_ground_pin_spread.source_binding_ids)
                if requirement.minimum_separation is not None:
                    required.update(requirement.minimum_separation.source_binding_ids)
        if self.maximum_body_to_edge_distance is not None:
            maximum = self.maximum_body_to_edge_distance
            if maximum.unit != "mm" or maximum.value < 0:
                raise ValueError("maximum body-to-edge distance must be a non-negative mm quantity")
            required.update(maximum.source_binding_ids)
        if not required.issubset(binding_by_id):
            raise ValueError("connector geometry/requirements reference unknown evidence")
        hard_ids: set[str] = set()
        if (
            self.maximum_body_to_edge_distance is not None
            and self.maximum_edge_authority is SemanticAuthorityClass.HARD_GEOMETRY
        ):
            hard_ids.update(self.maximum_body_to_edge_distance.source_binding_ids)
        for requirement in requirements:
            if (
                requirement is not None
                and requirement.authority is SemanticAuthorityClass.HARD_GEOMETRY
            ):
                hard_ids.update(requirement.source_binding_ids)
                if requirement.minimum_ground_pin_spread is not None:
                    hard_ids.update(requirement.minimum_ground_pin_spread.source_binding_ids)
                if requirement.minimum_separation is not None:
                    hard_ids.update(requirement.minimum_separation.source_binding_ids)
        if any(not evidence_binding_is_complete(binding_by_id[item]) for item in hard_ids):
            raise ValueError(
                "hard connector requirements/thresholds require pinned applicable reviewed evidence"
            )
        context_fp = connector_declaration_context_fingerprint(self)
        if any(binding_by_id[item].geometry_source_fingerprint != context_fp for item in hard_ids):
            raise ValueError(
                "hard connector requirement/threshold evidence has stale or inexact context"
            )
        object.__setattr__(self, "evidence_bindings", bindings)
        return self


def connector_declaration_context_fingerprint(
    declaration: ConnectorZoneDeclaration,
) -> str:
    """Recompute the exact hard-rule and supplied-model provenance context."""

    requirements = (
        declaration.filter_chain_requirement,
        declaration.ground_pin_spread_requirement,
        declaration.oscillator_separation_requirement,
        declaration.enclosure_access_requirement,
    )
    hard_fingerprints = tuple(
        item
        for item in (
            (
                declaration.maximum_body_to_edge_distance.semantic_fingerprint()
                if declaration.maximum_body_to_edge_distance is not None
                and declaration.maximum_edge_authority is SemanticAuthorityClass.HARD_GEOMETRY
                else None
            ),
            *(
                requirement.semantic_fingerprint()
                for requirement in requirements
                if requirement is not None
                and requirement.authority is SemanticAuthorityClass.HARD_GEOMETRY
            ),
        )
        if item is not None
    )
    return connector_threshold_context_fingerprint(
        declaration.board_layout_snapshot_fingerprint,
        declaration.board_netlist_snapshot_fingerprint,
        declaration.connector_references,
        declaration.connector_role,
        declaration.zone_region.semantic_fingerprint(),
        declaration.allowed_edge_ids,
        hard_fingerprints,
    )


class ConnectorPlacedGeometry(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-placed-geometry"] = "pcbsmith-connector-placed-geometry"
    schema_version: Literal[1] = 1
    source_geometry: ConnectorLocalGeometry
    body_transform: PlacedCompoundTransform
    pad_transforms: tuple[tuple[str, PlacedCompoundTransform], ...]


class ConnectorGeometryEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-geometry-evidence"] = (
        "pcbsmith-connector-geometry-evidence"
    )
    schema_version: Literal[1] = 1
    evidence_id: str
    reference: str
    kind: Literal["body_zone", "pad_zone", "body_material", "pad_material", "edge_access"]
    rule_id: str
    edge_id: str | None = None
    squared_distance_numerator: int | None = None
    squared_distance_denominator: int | None = None
    body_witness: tuple[str, str] | None = None
    edge_witness: tuple[str, str] | None = None
    verification: SemanticVerification
    disposition: SemanticDisposition


class ConnectorRequirementEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-requirement-evidence"] = (
        "pcbsmith-connector-requirement-evidence"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    rule_id: str
    kind: ConnectorRequirementKind
    model_id: str | None = None
    effective_binding_ids: tuple[str, ...] = Field(min_length=1)
    measured_value: float | None = None
    measured_unit: str | None = None
    verification: SemanticVerification
    disposition: SemanticDisposition


class ConnectorZoneResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-zone-result"] = "pcbsmith-connector-zone-result"
    schema_version: Literal[1] = 1
    scope: Literal[
        "supplied_connector_geometry_and_topology_only_no_emc_cable_access_or_enclosure_completeness_claim"
    ] = (
        "supplied_connector_geometry_and_topology_only_no_emc_cable_access_or_"
        "enclosure_completeness_claim"
    )
    declaration: ConnectorZoneDeclaration
    requirement_models: tuple[ConnectorRequirementModel, ...]
    placed_geometries: tuple[ConnectorPlacedGeometry, ...]
    geometry_evidence: tuple[ConnectorGeometryEvidence, ...]
    requirement_evidence: tuple[ConnectorRequirementEvidence, ...]
    evidence_fingerprint: str
    semantic_result: SemanticLayoutResult
    result_fingerprint: str

    @field_validator("evidence_fingerprint", "result_fingerprint")
    @classmethod
    def valid_sha(cls, value: str, info: Any) -> str:
        return _sha(value, info.field_name)

    @model_validator(mode="after")
    def replay_derived(self) -> Self:
        from pcbsmith.kicad.connector_zone import rederive_connector_zone

        expected = rederive_connector_zone(self.declaration, self.requirement_models)
        names = (
            "requirement_models",
            "placed_geometries",
            "geometry_evidence",
            "requirement_evidence",
            "evidence_fingerprint",
            "semantic_result",
        )
        if any(getattr(self, name) != expected[name] for name in names):
            raise ValueError("connector-zone evidence/result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("connector-zone result fingerprint is stale")
        return self
