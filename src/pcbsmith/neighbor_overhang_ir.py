"""Replay-bound IR for package/class-specific terminal neighbor overhang.

All thresholds and tolerances use integer micrometres.  Supplied planar
coordinates must lie on that grid; the geometry kernel still retains exact
rational witnesses for projections onto non-axis-aligned edges.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from fractions import Fraction
from math import isqrt
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.placement_geometry import ExactPlanarCompound
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticIrModel,
    SemanticVerification,
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


class PackageGeometryKind(StrEnum):
    CHIP = "chip"
    MELF = "melf"
    GULL_WING = "gull_wing"
    OTHER = "other"


class OverhangDirection(StrEnum):
    X_NEGATIVE = "x_negative"
    X_POSITIVE = "x_positive"
    Y_NEGATIVE = "y_negative"
    Y_POSITIVE = "y_positive"


class NeighborGeometryRole(StrEnum):
    PAD = "pad"
    TERMINAL = "terminal"
    ADJACENT_COPPER = "adjacent_copper"


class NeighborRuleVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    PROCESS_REVIEW_REQUIRED = "process_review_required"


class BoardCoordinateNeighborGeometry(SemanticIrModel):
    schema_id: Literal["pcbsmith-board-coordinate-neighbor-geometry"] = (
        "pcbsmith-board-coordinate-neighbor-geometry"
    )
    schema_version: Literal[1] = 1
    geometry_id: str
    source_geometry_id: str
    role: NeighborGeometryRole
    component_reference: str
    layer: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    verification: SemanticVerification
    compound: ExactPlanarCompound | None
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def exact_board_geometry_is_coherent(self) -> Self:
        for name in ("geometry_id", "source_geometry_id", "component_reference", "layer"):
            _identity(getattr(self, name), name)
        _sha(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        _sha(self.board_netlist_snapshot_fingerprint, "board_netlist_snapshot_fingerprint")
        if self.verification is SemanticVerification.EXACT:
            if self.compound is None:
                raise ValueError("exact neighbor geometry requires a compound")
            for polygon in self.compound.polygons:
                for boundary in (polygon.outer, *polygon.holes):
                    for x_mm, y_mm in boundary:
                        if (Fraction(str(x_mm)) * 1000).denominator != 1 or (
                            Fraction(str(y_mm)) * 1000
                        ).denominator != 1:
                            raise ValueError("neighbor geometry must lie on integer micrometres")
        elif self.verification is SemanticVerification.UNSUPPORTED:
            if self.compound is not None:
                raise ValueError("unsupported neighbor geometry cannot carry a compound")
        else:
            raise ValueError("bounded geometry cannot decide a hard neighbor constraint")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class NeighborToleranceModel(SemanticIrModel):
    schema_id: Literal["pcbsmith-neighbor-tolerance-model"] = (
        "pcbsmith-neighbor-tolerance-model"
    )
    schema_version: Literal[1] = 1
    tolerance_model_id: str
    placement_tolerance_um: int = Field(ge=0)
    fabrication_tolerance_um: int = Field(ge=0)
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def tolerance_is_bound(self) -> Self:
        _identity(self.tolerance_model_id, "tolerance_model_id")
        _sha(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        _sha(self.board_netlist_snapshot_fingerprint, "board_netlist_snapshot_fingerprint")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class ActiveElectricalClearance(SemanticIrModel):
    schema_id: Literal["pcbsmith-active-electrical-clearance"] = (
        "pcbsmith-active-electrical-clearance"
    )
    schema_version: Literal[1] = 1
    clearance_id: str
    clearance_um: int = Field(ge=0)
    clearance_domain_id: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def clearance_is_bound(self) -> Self:
        _identity(self.clearance_id, "clearance_id")
        _identity(self.clearance_domain_id, "clearance_domain_id")
        _sha(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        _sha(self.board_netlist_snapshot_fingerprint, "board_netlist_snapshot_fingerprint")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class NeighborAuthorityReview(SemanticIrModel):
    schema_id: Literal["pcbsmith-neighbor-authority-review"] = (
        "pcbsmith-neighbor-authority-review"
    )
    schema_version: Literal[1] = 1
    review_id: str
    reviewer_record_id: str
    reviewer_identity: str
    status: Literal["active", "suspended", "expired", "revoked"]
    full_context_fingerprint: str
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def review_is_pinned(self) -> Self:
        _identity(self.review_id, "review_id")
        _identity(self.reviewer_record_id, "reviewer_record_id")
        _identity(self.reviewer_identity, "reviewer_identity")
        _sha(self.full_context_fingerprint, "full_context_fingerprint")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class NeighborOverhangRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-neighbor-overhang-requirement"] = (
        "pcbsmith-neighbor-overhang-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    acceptance_class: str
    package_geometry_kind: PackageGeometryKind
    package_identity: str
    component_reference: str
    allowed_overhang_direction: OverhangDirection
    maximum_terminal_overhang_um: int | None = Field(default=None, ge=0)
    maximum_terminal_overhang_fraction_numerator: int | None = Field(default=None, ge=0)
    maximum_terminal_overhang_fraction_denominator: int | None = Field(default=None, gt=0)
    minimum_post_tolerance_copper_gap_um: int = Field(ge=0)
    tolerance_model_id: str
    clearance_id: str
    authority: SemanticAuthorityClass
    review: NeighborAuthorityReview | None = None
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def package_class_rule_is_explicit(self) -> Self:
        for name in (
            "requirement_id",
            "acceptance_class",
            "package_identity",
            "component_reference",
            "tolerance_model_id",
            "clearance_id",
        ):
            _identity(getattr(self, name), name)
        fraction = (
            self.maximum_terminal_overhang_fraction_numerator,
            self.maximum_terminal_overhang_fraction_denominator,
        )
        if (fraction[0] is None) != (fraction[1] is None):
            raise ValueError("overhang fraction numerator and denominator must appear together")
        if self.maximum_terminal_overhang_um is None and fraction[0] is None:
            raise ValueError("overhang rule requires an absolute or fractional maximum")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self

    def rule_context(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"review", "source_binding_ids"})


class ExactCopperGapWitness(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-copper-gap-witness"] = (
        "pcbsmith-exact-copper-gap-witness"
    )
    schema_version: Literal[1] = 1
    terminal_geometry_id: str
    adjacent_copper_geometry_id: str
    adjacent_copper_source_geometry_id: str
    relation: Literal["disjoint", "boundary_touch", "interior_overlap"]
    squared_distance_um2_numerator: int = Field(ge=0)
    squared_distance_um2_denominator: int = Field(gt=0)
    terminal_point_x_um: str
    terminal_point_y_um: str
    copper_point_x_um: str
    copper_point_y_um: str


class ExactPostToleranceGap(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-post-tolerance-gap"] = (
        "pcbsmith-exact-post-tolerance-gap"
    )
    schema_version: Literal[1] = 1
    measured_squared_um2_numerator: int = Field(ge=0)
    measured_squared_um2_denominator: int = Field(gt=0)
    tolerance_deduction_um: int = Field(ge=0)
    exact_measured_gap_um: int | None = None
    exact_post_tolerance_gap_um: int | None = None

    @model_validator(mode="after")
    def exact_linear_values_are_honest(self) -> Self:
        numerator = self.measured_squared_um2_numerator
        denominator = self.measured_squared_um2_denominator
        root_numerator = isqrt(numerator)
        root_denominator = isqrt(denominator)
        exact = (
            root_numerator * root_numerator == numerator
            and root_denominator * root_denominator == denominator
            and root_numerator % root_denominator == 0
        )
        measured = root_numerator // root_denominator if exact else None
        if self.exact_measured_gap_um != measured:
            raise ValueError("linear measured gap is not the exact square root")
        expected_post = None if measured is None else measured - self.tolerance_deduction_um
        if self.exact_post_tolerance_gap_um != expected_post:
            raise ValueError("post-tolerance gap is stale")
        return self


class NeighborOverhangFinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-neighbor-overhang-finding"] = (
        "pcbsmith-neighbor-overhang-finding"
    )
    schema_version: Literal[1] = 1
    finding_kind: Literal["terminal_overhang"] = "terminal_overhang"
    requirement_id: str | None
    acceptance_class: str | None
    package_geometry_kind: PackageGeometryKind
    component_reference: str
    direction: OverhangDirection | None
    measured_terminal_overhang_um: int | None
    terminal_span_um: int | None
    pad_span_um: int | None
    fraction_reference_span_um: int | None
    allowed_terminal_overhang_numerator_um: int | None
    allowed_terminal_overhang_denominator: int | None
    placement_tolerance_um: int | None
    fabrication_tolerance_um: int | None
    total_tolerance_deduction_um: int | None
    worst_case_terminal_overhang_um: int | None
    verdict: NeighborRuleVerdict
    disposition: SemanticDisposition
    verification: SemanticVerification
    reason_ids: tuple[str, ...] = ()


class NeighborCopperGapFinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-neighbor-copper-gap-finding"] = (
        "pcbsmith-neighbor-copper-gap-finding"
    )
    schema_version: Literal[1] = 1
    finding_kind: Literal["post_tolerance_copper_gap"] = "post_tolerance_copper_gap"
    requirement_id: str | None
    acceptance_class: str | None
    package_geometry_kind: PackageGeometryKind
    component_reference: str
    witness: ExactCopperGapWitness | None
    placement_tolerance_um: int | None
    fabrication_tolerance_um: int | None
    total_tolerance_deduction_um: int | None
    post_tolerance_gap: ExactPostToleranceGap | None
    minimum_rule_gap_um: int | None
    active_electrical_clearance_um: int | None
    verdict: NeighborRuleVerdict
    disposition: SemanticDisposition
    verification: SemanticVerification
    reason_ids: tuple[str, ...] = ()


def neighbor_full_context_fingerprint(
    *,
    board_layout_snapshot_fingerprint_value: str,
    board_netlist_snapshot_fingerprint_value: str,
    component_fingerprint: str,
    package_geometry_kind: PackageGeometryKind,
    package_identity: str,
    acceptance_class: str,
    geometries: tuple[BoardCoordinateNeighborGeometry, ...],
    tolerance: NeighborToleranceModel,
    clearance: ActiveElectricalClearance,
    requirement: NeighborOverhangRequirement,
) -> str:
    """Fingerprint the complete context a qualified review must cover."""

    return fingerprint(
        {
            "board_layout_snapshot_fingerprint": board_layout_snapshot_fingerprint_value,
            "board_netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint_value,
            "component_fingerprint": component_fingerprint,
            "package_geometry_kind": package_geometry_kind,
            "package_identity": package_identity,
            "acceptance_class": acceptance_class,
            "geometry_fingerprints": tuple(
                sorted(item.semantic_fingerprint() for item in geometries)
            ),
            "tolerance_fingerprint": tolerance.semantic_fingerprint(),
            "clearance_fingerprint": clearance.semantic_fingerprint(),
            "requirement_context": requirement.rule_context(),
        }
    )


class NeighborOverhangDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-neighbor-overhang-declaration"] = (
        "pcbsmith-neighbor-overhang-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str
    board_layout_snapshot_json: str
    board_netlist_snapshot_json: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    component_reference: str
    package_geometry_kind: PackageGeometryKind
    package_identity: str
    selected_acceptance_class: str | None
    geometries: tuple[BoardCoordinateNeighborGeometry, ...]
    tolerance_models: tuple[NeighborToleranceModel, ...]
    clearances: tuple[ActiveElectricalClearance, ...]
    requirements: tuple[NeighborOverhangRequirement, ...]
    evidence_bindings: tuple[EvidenceApplicabilityBinding, ...]

    @model_validator(mode="after")
    def complete_snapshot_scope_is_bound(self) -> Self:
        _identity(self.declaration_id, "declaration_id")
        _identity(self.component_reference, "component_reference")
        _identity(self.package_identity, "package_identity")
        if self.selected_acceptance_class is not None:
            _identity(self.selected_acceptance_class, "selected_acceptance_class")
        layout = parse_canonical_board_layout_snapshot(self.board_layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.board_netlist_snapshot_json)
        if canonical_board_layout_snapshot_json(layout) != self.board_layout_snapshot_json:
            raise ValueError("BoardLayout snapshot is noncanonical")
        if canonical_board_netlist_snapshot_json(netlist) != self.board_netlist_snapshot_json:
            raise ValueError("BoardNetlist snapshot is noncanonical")
        if (
            board_layout_snapshot_fingerprint(self.board_layout_snapshot_json)
            != self.board_layout_snapshot_fingerprint
            or board_netlist_snapshot_fingerprint(self.board_netlist_snapshot_json)
            != self.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("board snapshot fingerprint is stale")
        component_by_ref = {item.reference: item for item in netlist.components}
        placed_refs = {item.reference for item, _ in layout.placements}
        if (
            self.component_reference not in component_by_ref
            or self.component_reference not in placed_refs
        ):
            raise ValueError("neighbor component must exist and be placed")
        bindings = tuple(sorted(self.evidence_bindings, key=lambda item: item.binding_id))
        if len({item.binding_id for item in bindings}) != len(bindings):
            raise ValueError("evidence binding identities must be unique")
        binding_ids = {item.binding_id for item in bindings}
        geometries = tuple(sorted(self.geometries, key=lambda item: item.geometry_id))
        tolerances = tuple(
            sorted(self.tolerance_models, key=lambda item: item.tolerance_model_id)
        )
        clearances = tuple(sorted(self.clearances, key=lambda item: item.clearance_id))
        requirements = tuple(sorted(self.requirements, key=lambda item: item.requirement_id))
        identities = (
            (tuple(item.geometry_id for item in geometries), "geometry"),
            (tuple(item.source_geometry_id for item in geometries), "source geometry"),
            (tuple(item.tolerance_model_id for item in tolerances), "tolerance model"),
            (tuple(item.clearance_id for item in clearances), "clearance"),
            (tuple(item.requirement_id for item in requirements), "requirement"),
        )
        for values, label in identities:
            if len(values) != len(set(values)):
                raise ValueError(f"{label} identities must be unique")
        scoped_objects: tuple[Any, ...] = (*geometries, *tolerances, *clearances, *requirements)
        for item in scoped_objects:
            if not set(item.source_binding_ids).issubset(binding_ids):
                raise ValueError("neighbor context references an unknown evidence binding")
        for geometry in geometries:
            if (
                geometry.board_layout_snapshot_fingerprint
                != self.board_layout_snapshot_fingerprint
                or geometry.board_netlist_snapshot_fingerprint
                != self.board_netlist_snapshot_fingerprint
            ):
                raise ValueError("neighbor geometry is stale for this board")
            if geometry.component_reference not in component_by_ref or (
                geometry.component_reference not in placed_refs
            ):
                raise ValueError("neighbor geometry owner must exist and be placed")
            if (
                geometry.role in {NeighborGeometryRole.PAD, NeighborGeometryRole.TERMINAL}
                and geometry.component_reference != self.component_reference
            ):
                raise ValueError("pad and terminal geometry must belong to the subject")
        for item in tolerances:
            if (
                item.board_layout_snapshot_fingerprint != self.board_layout_snapshot_fingerprint
                or item.board_netlist_snapshot_fingerprint
                != self.board_netlist_snapshot_fingerprint
            ):
                raise ValueError("tolerance or clearance is stale for this board")
        for item in clearances:
            if (
                item.board_layout_snapshot_fingerprint != self.board_layout_snapshot_fingerprint
                or item.board_netlist_snapshot_fingerprint
                != self.board_netlist_snapshot_fingerprint
            ):
                raise ValueError("tolerance or clearance is stale for this board")
        for rule in requirements:
            if (
                rule.component_reference != self.component_reference
                or rule.package_identity != self.package_identity
            ):
                raise ValueError("neighbor requirement is stale for component or package")
        object.__setattr__(self, "evidence_bindings", bindings)
        object.__setattr__(self, "geometries", geometries)
        object.__setattr__(self, "tolerance_models", tolerances)
        object.__setattr__(self, "clearances", clearances)
        object.__setattr__(self, "requirements", requirements)
        return self


class NeighborOverhangResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-neighbor-overhang-result"] = (
        "pcbsmith-neighbor-overhang-result"
    )
    schema_version: Literal[1] = 1
    declaration: NeighborOverhangDeclaration
    overhang_finding: NeighborOverhangFinding
    copper_gap_finding: NeighborCopperGapFinding
    excluded_claims: tuple[str, ...]
    findings_fingerprint: str
    result_fingerprint: str

    @model_validator(mode="after")
    def result_replays_exactly(self) -> Self:
        from pcbsmith.kicad.neighbor_overhang import rederive_neighbor_overhang

        derived = rederive_neighbor_overhang(self.declaration)
        for name, expected in derived.items():
            if getattr(self, name) != expected:
                raise ValueError(f"neighbor overhang result has stale {name}")
        expected_result = fingerprint(
            self.model_dump(mode="json", exclude={"result_fingerprint"})
        )
        if self.result_fingerprint != expected_result:
            raise ValueError("neighbor overhang result fingerprint is stale")
        return self
