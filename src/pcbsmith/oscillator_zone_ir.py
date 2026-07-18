"""Replay-bound IR for explicit R6 oscillator-zone semantics."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.antenna_clearance_ir import QualifiedExactZoneFillProvenance
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, PlanarRelation
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


def _binding_is_complete(binding: EvidenceApplicabilityBinding) -> bool:
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


class OscillatorObjectKind(StrEnum):
    COPPER = "copper"
    PAD = "pad"
    VIA = "via"
    FILLED_ZONE = "filled_zone"


class OscillatorUnsupportedReason(StrEnum):
    ZONE_INTENT_WITHOUT_FINAL_FILL = "zone_intent_without_final_fill"
    RECTANGLE_ONLY_ZONE = "rectangle_only_zone"
    UNQUALIFIED_GEOMETRY = "unqualified_geometry"
    OTHER_TYPED_UNSUPPORTED = "other_typed_unsupported"


class ExactNetClassMembership(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-net-class-membership"] = (
        "pcbsmith-exact-net-class-membership"
    )
    schema_version: Literal[1] = 1
    net_class_id: str
    net_names: tuple[str, ...] = Field(min_length=1)
    board_netlist_snapshot_fingerprint: str
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_membership(self) -> Self:
        _identity(self.net_class_id, "net_class_id")
        _sha(self.board_netlist_snapshot_fingerprint, "board_netlist_snapshot_fingerprint")
        object.__setattr__(self, "net_names", _identities(self.net_names, "net_names"))
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class ReferenceGroundRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-reference-ground-requirement"] = (
        "pcbsmith-oscillator-reference-ground-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    rule_id: str
    ground_net_name: str
    required_layers: tuple[str, ...] = Field(min_length=1)
    minimum_coverage_basis_points: int = Field(ge=0, le=10_000)
    authority: Literal[
        SemanticAuthorityClass.HARD_GEOMETRY,
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
    ]
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_requirement(self) -> Self:
        for name in ("requirement_id", "rule_id", "ground_net_name"):
            _identity(getattr(self, name), name)
        object.__setattr__(
            self, "required_layers", _identities(self.required_layers, "required_layers")
        )
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class StitchViaRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-stitch-via-requirement"] = (
        "pcbsmith-oscillator-stitch-via-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    count_rule_id: str
    placement_rule_id: str
    ground_net_name: str
    minimum_count: int = Field(ge=0)
    required_layers: tuple[str, ...] = Field(min_length=1)
    require_touch_or_intersection: bool = True
    authority: Literal[
        SemanticAuthorityClass.HARD_GEOMETRY,
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
    ]
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_requirement(self) -> Self:
        for name in ("requirement_id", "count_rule_id", "placement_rule_id", "ground_net_name"):
            _identity(getattr(self, name), name)
        object.__setattr__(
            self, "required_layers", _identities(self.required_layers, "required_layers")
        )
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class IoSeparationRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-io-separation-requirement"] = (
        "pcbsmith-oscillator-io-separation-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    rule_id: str
    io_region: SemanticRegion
    minimum_separation: SemanticQuantity
    authority: Literal[
        SemanticAuthorityClass.HARD_GEOMETRY,
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
    ]

    @model_validator(mode="after")
    def exact_scoped_requirement(self) -> Self:
        _identity(self.requirement_id, "requirement_id")
        _identity(self.rule_id, "rule_id")
        if (
            self.io_region.coordinate_space != "board"
            or self.io_region.verification is not SemanticVerification.EXACT
        ):
            raise ValueError("I/O separation requires an exact board-coordinate region")
        if self.minimum_separation.unit != "mm" or self.minimum_separation.value < 0:
            raise ValueError("I/O separation threshold must be a non-negative mm quantity")
        return self


class StrayCapacitanceRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-stray-capacitance-requirement"] = (
        "pcbsmith-oscillator-stray-capacitance-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    rule_id: str
    maximum_capacitance: SemanticQuantity
    authority: Literal[
        SemanticAuthorityClass.HARD_GEOMETRY,
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
    ]

    @model_validator(mode="after")
    def typed_threshold(self) -> Self:
        _identity(self.requirement_id, "requirement_id")
        _identity(self.rule_id, "rule_id")
        if self.maximum_capacitance.unit != "pF" or self.maximum_capacitance.value < 0:
            raise ValueError("stray-capacitance threshold must be a non-negative pF quantity")
        return self


class QualifiedCapacitanceModelResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-qualified-oscillator-capacitance-model-result"] = (
        "pcbsmith-qualified-oscillator-capacitance-model-result"
    )
    schema_version: Literal[1] = 1
    model_id: str
    model_version: str
    stackup_model_id: str
    stackup_model_fingerprint: str
    qualification_record_id: str
    status: Literal["active", "suspended", "revoked"]
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    zone_geometry_fingerprint: str
    physical_objects_fingerprint: str
    calculated_capacitance: SemanticQuantity
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def qualified_and_bound(self) -> Self:
        for name in (
            "model_id",
            "model_version",
            "stackup_model_id",
            "qualification_record_id",
        ):
            _identity(getattr(self, name), name)
        for name in (
            "stackup_model_fingerprint",
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
            "zone_geometry_fingerprint",
            "physical_objects_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if self.calculated_capacitance.unit != "pF" or self.calculated_capacitance.value < 0:
            raise ValueError("calculated capacitance must be a non-negative pF quantity")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class OscillatorZoneDeclaration(SemanticIrModel):
    """One declaration over one exact pair of canonical board snapshots."""

    schema_id: Literal["pcbsmith-oscillator-zone-declaration"] = (
        "pcbsmith-oscillator-zone-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str
    board_layout_snapshot_json: str
    board_netlist_snapshot_json: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    has_external_discrete_zone: bool
    zone_id: str
    zone_region: SemanticRegion | None
    oscillator_reference: str
    crystal_reference: str | None = None
    load_capacitor_references: tuple[str, ...] = ()
    oscillator_net_names: tuple[str, ...] = ()
    allowed_object_ids: tuple[str, ...] = ()
    allowed_component_refs: tuple[str, ...] = ()
    allowed_net_names: tuple[str, ...] = ()
    forbidden_net_class_ids: tuple[str, ...] = ()
    net_class_memberships: tuple[ExactNetClassMembership, ...] = ()
    intrusion_rule_id: str
    applicability_rule_id: str
    reference_ground_requirement: ReferenceGroundRequirement | None = None
    stitch_via_requirement: StitchViaRequirement | None = None
    io_separation_requirement: IoSeparationRequirement | None = None
    stray_capacitance_requirement: StrayCapacitanceRequirement | None = None
    evidence_bindings: tuple[EvidenceApplicabilityBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def replay_scope_is_complete(self) -> Self:
        for name in (
            "declaration_id",
            "zone_id",
            "oscillator_reference",
            "intrusion_rule_id",
            "applicability_rule_id",
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
        refs = {item.reference for item in netlist.components}
        nets = {item.name for item in netlist.nets}
        declared_refs = {
            self.oscillator_reference,
            *self.load_capacitor_references,
            *self.allowed_component_refs,
        }
        if self.crystal_reference is not None:
            _identity(self.crystal_reference, "crystal_reference")
            declared_refs.add(self.crystal_reference)
        if not declared_refs.issubset(refs):
            raise ValueError(
                "oscillator declaration references a component absent from BoardNetlist"
            )
        for name in (
            "load_capacitor_references",
            "oscillator_net_names",
            "allowed_object_ids",
            "allowed_component_refs",
            "allowed_net_names",
            "forbidden_net_class_ids",
        ):
            object.__setattr__(self, name, _identities(getattr(self, name), name))
        if not set((*self.oscillator_net_names, *self.allowed_net_names)).issubset(nets):
            raise ValueError("oscillator declaration references a net absent from BoardNetlist")
        if self.has_external_discrete_zone:
            if (
                self.zone_region is None
                or self.zone_region.region_id != self.zone_id
                or self.zone_region.coordinate_space != "board"
                or self.zone_region.verification is not SemanticVerification.EXACT
            ):
                raise ValueError("external oscillator zones require their exact board region")
        elif self.zone_region is not None:
            raise ValueError("non-external oscillators cannot invent a zone region")
        bindings = tuple(sorted(self.evidence_bindings, key=lambda item: item.binding_id))
        binding_ids = {item.binding_id for item in bindings}
        if len(binding_ids) != len(bindings):
            raise ValueError("evidence binding identities must be unique")
        memberships = tuple(sorted(self.net_class_memberships, key=lambda item: item.net_class_id))
        membership_ids = {item.net_class_id for item in memberships}
        if len(membership_ids) != len(memberships):
            raise ValueError("net class membership identities must be unique")
        if set(self.forbidden_net_class_ids) != membership_ids:
            raise ValueError("forbidden net classes require exact caller-supplied membership")
        for membership in memberships:
            if (
                membership.board_netlist_snapshot_fingerprint
                != self.board_netlist_snapshot_fingerprint
            ):
                raise ValueError("net class membership is bound to another BoardNetlist")
            if not set(membership.net_names).issubset(nets):
                raise ValueError("net class membership contains a net absent from BoardNetlist")
            if not set(membership.source_binding_ids).issubset(binding_ids):
                raise ValueError("net class membership references unknown evidence")
        required_bindings: set[str] = set()
        if self.zone_region is not None:
            required_bindings.update(self.zone_region.source_binding_ids)
        for requirement in (self.reference_ground_requirement, self.stitch_via_requirement):
            if requirement is not None:
                if requirement.ground_net_name not in nets:
                    raise ValueError("ground requirement net is absent from BoardNetlist")
                required_bindings.update(requirement.source_binding_ids)
        if self.io_separation_requirement is not None:
            required_bindings.update(self.io_separation_requirement.io_region.source_binding_ids)
            required_bindings.update(
                self.io_separation_requirement.minimum_separation.source_binding_ids
            )
        if self.stray_capacitance_requirement is not None:
            required_bindings.update(
                self.stray_capacitance_requirement.maximum_capacitance.source_binding_ids
            )
        if not required_bindings.issubset(binding_ids):
            raise ValueError("declaration geometry/threshold references unknown evidence")
        binding_by_id = {item.binding_id: item for item in bindings}
        hard_threshold_bindings: set[str] = set()
        if (
            self.reference_ground_requirement is not None
            and self.reference_ground_requirement.authority is SemanticAuthorityClass.HARD_GEOMETRY
        ):
            hard_threshold_bindings.update(self.reference_ground_requirement.source_binding_ids)
        if (
            self.stitch_via_requirement is not None
            and self.stitch_via_requirement.authority is SemanticAuthorityClass.HARD_GEOMETRY
        ):
            hard_threshold_bindings.update(self.stitch_via_requirement.source_binding_ids)
        if (
            self.io_separation_requirement is not None
            and self.io_separation_requirement.authority is SemanticAuthorityClass.HARD_GEOMETRY
        ):
            hard_threshold_bindings.update(
                self.io_separation_requirement.minimum_separation.source_binding_ids
            )
        if (
            self.stray_capacitance_requirement is not None
            and self.stray_capacitance_requirement.authority is SemanticAuthorityClass.HARD_GEOMETRY
        ):
            hard_threshold_bindings.update(
                self.stray_capacitance_requirement.maximum_capacitance.source_binding_ids
            )
        if any(
            not _binding_is_complete(binding_by_id[binding_id])
            for binding_id in hard_threshold_bindings
        ):
            raise ValueError("hard sourced thresholds require pinned applicable reviewed evidence")
        object.__setattr__(self, "evidence_bindings", bindings)
        object.__setattr__(self, "net_class_memberships", memberships)
        return self


class OscillatorPhysicalObject(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-physical-object"] = (
        "pcbsmith-oscillator-physical-object"
    )
    schema_version: Literal[1] = 1
    object_id: str
    kind: OscillatorObjectKind
    source_id: str
    layers: tuple[str, ...] = Field(min_length=1)
    owner_component_ref: str | None = None
    owner_net_name: str | None = None
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    source_representation: Literal["physical_geometry", "zone_intent", "exact_final_fill"]
    verification: Literal[SemanticVerification.EXACT, SemanticVerification.UNSUPPORTED]
    compound: ExactPlanarCompound | None
    unsupported_reason: OscillatorUnsupportedReason | None = None
    exact_final_fill_provenance: QualifiedExactZoneFillProvenance | None = None

    @model_validator(mode="after")
    def explicit_object_is_coherent(self) -> Self:
        _identity(self.object_id, "object_id")
        _identity(self.source_id, "source_id")
        _sha(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        _sha(self.board_netlist_snapshot_fingerprint, "board_netlist_snapshot_fingerprint")
        object.__setattr__(self, "layers", _identities(self.layers, "layers"))
        for name in ("owner_component_ref", "owner_net_name"):
            if (value := getattr(self, name)) is not None:
                _identity(value, name)
        if self.verification is SemanticVerification.EXACT:
            if self.compound is None or self.unsupported_reason is not None:
                raise ValueError("exact objects require geometry and no unsupported reason")
        elif self.compound is not None or self.unsupported_reason is None:
            raise ValueError("unsupported objects require a typed reason and no geometry")
        if self.kind is OscillatorObjectKind.FILLED_ZONE:
            expected = (
                "exact_final_fill"
                if self.verification is SemanticVerification.EXACT
                else "zone_intent"
            )
            if self.source_representation != expected:
                raise ValueError("filled zones must distinguish final fill from zone intent")
            if self.verification is SemanticVerification.EXACT:
                provenance = self.exact_final_fill_provenance
                if (
                    provenance is None
                    or self.compound is None
                    or provenance.zone_source_provenance_id != self.source_id
                    or provenance.board_layout_snapshot_fingerprint
                    != self.board_layout_snapshot_fingerprint
                    or provenance.exact_geometry_fingerprint != self.compound.semantic_fingerprint()
                ):
                    raise ValueError(
                        "exact final fill requires active reader/artifact/geometry provenance"
                    )
            elif self.exact_final_fill_provenance is not None:
                raise ValueError("unsupported zone intent cannot carry final-fill provenance")
        elif self.source_representation != "physical_geometry":
            raise ValueError("non-zone objects require physical geometry representation")
        elif self.exact_final_fill_provenance is not None:
            raise ValueError("non-zone objects cannot carry final-fill provenance")
        return self


class ReferenceGroundCoverageProof(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-ground-coverage-proof"] = (
        "pcbsmith-oscillator-ground-coverage-proof"
    )
    schema_version: Literal[1] = 1
    proof_id: str
    calculation_id: str
    ground_object_id: str
    ground_source_id: str
    layer: str
    zone_geometry_fingerprint: str
    ground_geometry_fingerprint: str
    predicate: Literal["zone_inside_single_fill_polygon", "exact_sets_disjoint"]
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_inputs_are_bound(self) -> Self:
        for name in ("proof_id", "calculation_id", "ground_object_id", "ground_source_id", "layer"):
            _identity(getattr(self, name), name)
        _sha(self.zone_geometry_fingerprint, "zone_geometry_fingerprint")
        _sha(self.ground_geometry_fingerprint, "ground_geometry_fingerprint")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class OscillatorIntrusionEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-intrusion-evidence"] = (
        "pcbsmith-oscillator-intrusion-evidence"
    )
    schema_version: Literal[1] = 1
    object_id: str
    source_id: str
    layers: tuple[str, ...]
    applicable_layers: tuple[str, ...]
    owner_component_ref: str | None
    owner_net_name: str | None
    forbidden_net_class_ids: tuple[str, ...]
    exemption: (
        Literal["object", "component", "oscillator_net", "allowed_net", "local_ground"] | None
    )
    relation: PlanarRelation | None
    verification: SemanticVerification
    disposition: SemanticDisposition


class OscillatorRequirementEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-requirement-evidence"] = (
        "pcbsmith-oscillator-requirement-evidence"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    finding_kind: Literal[
        "reference_ground", "stitch_count", "stitch_placement", "io_separation", "stray_capacitance"
    ]
    object_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    layers: tuple[str, ...] = ()
    measured_value: float | None = None
    measured_unit: Literal["basis_points", "count", "mm", "pF"] | None = None
    relation: PlanarRelation | None = None
    verification: SemanticVerification
    disposition: SemanticDisposition

    @model_validator(mode="after")
    def evidence_is_canonical(self) -> Self:
        _identity(self.requirement_id, "requirement_id")
        for name in ("object_ids", "source_ids", "layers"):
            object.__setattr__(self, name, _identities(getattr(self, name), name))
        if (self.measured_value is None) != (self.measured_unit is None):
            raise ValueError("measured value and unit must be present together")
        if self.measured_value is not None and not math.isfinite(self.measured_value):
            raise ValueError("measured value must be finite")
        return self


class OscillatorZoneResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-oscillator-zone-result"] = "pcbsmith-oscillator-zone-result"
    schema_version: Literal[1] = 1
    inventory_scope: Literal["explicit_supplied_objects_only_not_complete_board_inventory"] = (
        "explicit_supplied_objects_only_not_complete_board_inventory"
    )
    declaration: OscillatorZoneDeclaration
    physical_objects: tuple[OscillatorPhysicalObject, ...]
    coverage_proofs: tuple[ReferenceGroundCoverageProof, ...]
    capacitance_model_result: QualifiedCapacitanceModelResult | None
    intrusion_evidence: tuple[OscillatorIntrusionEvidence, ...]
    requirement_evidence: tuple[OscillatorRequirementEvidence, ...]
    physical_objects_fingerprint: str
    coverage_proofs_fingerprint: str
    evidence_fingerprint: str
    semantic_result: SemanticLayoutResult
    result_fingerprint: str

    @field_validator(
        "physical_objects_fingerprint",
        "coverage_proofs_fingerprint",
        "evidence_fingerprint",
        "result_fingerprint",
    )
    @classmethod
    def valid_fingerprint(cls, value: str, info: Any) -> str:
        return _sha(value, info.field_name)

    @model_validator(mode="after")
    def exact_replay_equality(self) -> Self:
        from pcbsmith.kicad.oscillator_zone import rederive_oscillator_zone

        expected = rederive_oscillator_zone(
            self.declaration,
            self.physical_objects,
            self.coverage_proofs,
            self.capacitance_model_result,
        )
        names = (
            "physical_objects",
            "coverage_proofs",
            "capacitance_model_result",
            "intrusion_evidence",
            "requirement_evidence",
            "physical_objects_fingerprint",
            "coverage_proofs_fingerprint",
            "evidence_fingerprint",
            "semantic_result",
        )
        if any(getattr(self, name) != expected[name] for name in names):
            raise ValueError("oscillator zone result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("oscillator zone result fingerprint is stale")
        return self
