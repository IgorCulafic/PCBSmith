"""Restricted exact R6 return-adjacency and transition-continuity interchange."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.antenna_clearance_ir import QualifiedExactZoneFillProvenance
from pcbsmith.placement_geometry import ExactPlanarCompound
from pcbsmith.routed_copper_graph_ir import (
    ExactRational,
    ResolvedCopperPathResult,
    RoutedCopperGraphResult,
    canonical_decimal,
    canonical_json,
    fingerprint,
    require_identity,
    require_sha256,
)
from pcbsmith.semantic_ir import EvidenceApplicabilityBinding, SemanticDisposition, SemanticIrModel

ADVISORY_3W_MODEL_ID = "pcbsmith-return-advisory-3w-v1"
ADVISORY_3H_MODEL_ID = "pcbsmith-return-advisory-3h-v1"
ADVISORY_ONE_TRACE_WIDTH_MODEL_ID = "pcbsmith-return-advisory-one-trace-width-v1"
EXACT_CONTAINMENT_MODEL_ID = "pcbsmith-return-exact-containment-v1"
ADVISORY_MODEL_IDS = frozenset(
    {ADVISORY_3W_MODEL_ID, ADVISORY_3H_MODEL_ID, ADVISORY_ONE_TRACE_WIDTH_MODEL_ID}
)


def _ids(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    result = tuple(sorted(require_identity(value, name) for value in values))
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must contain unique identities")
    return result


def complete_hard_binding(binding: EvidenceApplicabilityBinding) -> bool:
    return (
        bool(binding.required_conditions)
        and set(binding.matched_conditions) == set(binding.required_conditions)
        and not binding.unmatched_conditions
        and binding.geometry_source_fingerprint is not None
        and binding.reviewer_record_id is not None
        and all(
            item.source_status == "pinned"
            and item.local_sha256 is not None
            and item.locator_status in {"text_verified", "figure_verified", "figure_bound"}
            and item.applicability_status == "confirmed"
            for item in binding.evidence
        )
    )


class ReturnSignalClass(StrEnum):
    CLOCK = "clock"
    DIFFERENTIAL = "differential"
    BUS = "bus"
    SWITCHING = "switching"
    OTHER = "other"


class ReturnLayerPair(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-layer-pair"] = "pcbsmith-return-layer-pair"
    schema_version: Literal[1] = 1
    signal_layer: Literal["F.Cu", "B.Cu"]
    reference_layer: Literal["F.Cu", "B.Cu"]


class ReturnPathLeg(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-path-leg"] = "pcbsmith-return-path-leg"
    schema_version: Literal[1] = 1
    leg_id: str
    signal_net_name: str
    complete_selected_path: ResolvedCopperPathResult

    @model_validator(mode="after")
    def path_is_complete_and_exact(self) -> Self:
        require_identity(self.leg_id, "leg_id")
        require_identity(self.signal_net_name, "signal_net_name")
        path = self.complete_selected_path
        if path.selection.net_name != self.signal_net_name:
            raise ValueError("return leg selected path belongs to another signal net")
        if path.connectivity_state == "disconnected" or not path.ordered_edge_ids:
            raise ValueError("return leg requires a complete selected signal path")
        if path.selection.ordered_edge_ids is not None and (
            path.selection.ordered_edge_ids != path.ordered_edge_ids
        ):
            raise ValueError("explicit ordered-edge selection differs from resolved path")
        return self


def return_requirement_context_fingerprint(
    *,
    declaration_id: str,
    graph: RoutedCopperGraphResult,
    signal_net_names: tuple[str, ...],
    signal_class: ReturnSignalClass,
    exact_net_class_id: str,
    reference_net_name: str,
    layer_pairs: tuple[ReturnLayerPair, ...],
    legs: tuple[ReturnPathLeg, ...],
    adjacency_model_id: str,
    requirement_id: str,
    requirement_kind: str,
    requirement_value: Decimal | None,
) -> str:
    """Build the evidence pin for one full graph/declaration/model requirement context."""

    payload = {
        "schema_id": "pcbsmith-return-hard-context",
        "schema_version": 1,
        "declaration_id": declaration_id,
        "graph_fingerprint": graph.graph_fingerprint,
        "layout_fingerprint": graph.board_layout_snapshot_fingerprint,
        "netlist_fingerprint": graph.board_netlist_snapshot_fingerprint,
        "signal_net_names": tuple(sorted(signal_net_names)),
        "signal_class": signal_class.value,
        "exact_net_class_id": exact_net_class_id,
        "reference_net_name": reference_net_name,
        "layer_pairs": [
            item.model_dump(mode="json")
            for item in sorted(layer_pairs, key=lambda item: item.signal_layer)
        ],
        "legs": [
            [item.leg_id, item.complete_selected_path.evidence_fingerprint]
            for item in sorted(legs, key=lambda item: item.leg_id)
        ],
        "adjacency_model_id": adjacency_model_id,
        "threshold_id": requirement_id,
        "threshold_kind": requirement_kind,
        "threshold_value": None if requirement_value is None else str(requirement_value),
    }
    return fingerprint(payload)


class ReturnHardThreshold(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-hard-threshold"] = "pcbsmith-return-hard-threshold"
    schema_version: Literal[1] = 1
    threshold_id: str
    kind: Literal[
        "complete_coverage",
        "maximum_lateral_distance_mm",
        "maximum_discontinuity_length_mm",
    ]
    value_mm: Decimal | None
    evidence_binding: EvidenceApplicabilityBinding

    @model_validator(mode="after")
    def threshold_is_typed(self) -> Self:
        require_identity(self.threshold_id, "threshold_id")
        if self.kind == "complete_coverage":
            if self.value_mm is not None:
                raise ValueError("complete-coverage threshold has no numeric value")
        elif self.value_mm is None or self.value_mm < 0:
            raise ValueError("distance thresholds require a non-negative exact decimal")
        if self.value_mm is not None:
            object.__setattr__(self, "value_mm", canonical_decimal(self.value_mm, "value_mm"))
        return self


class TransitionStitchRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-transition-stitch-requirement"] = (
        "pcbsmith-return-transition-stitch-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    maximum_distance_mm: Decimal = Field(ge=0)
    evidence_binding: EvidenceApplicabilityBinding

    @model_validator(mode="after")
    def requirement_is_exact(self) -> Self:
        require_identity(self.requirement_id, "requirement_id")
        object.__setattr__(
            self,
            "maximum_distance_mm",
            canonical_decimal(self.maximum_distance_mm, "maximum_distance_mm"),
        )
        return self


class ReturnPathDeclaration(SemanticIrModel):
    """A complete, graph-bound declaration; it does not choose copper paths."""

    schema_id: Literal["pcbsmith-return-path-declaration"] = "pcbsmith-return-path-declaration"
    schema_version: Literal[1] = 1
    declaration_id: str
    graph: RoutedCopperGraphResult
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    signal_net_names: tuple[str, ...] = Field(min_length=1)
    signal_class: ReturnSignalClass
    exact_net_class_id: str
    reference_net_name: str
    layer_pairs: tuple[ReturnLayerPair, ...] = Field(min_length=1)
    legs: tuple[ReturnPathLeg, ...] = Field(min_length=1)
    adjacency_model_id: str
    hard_thresholds: tuple[ReturnHardThreshold, ...] = ()
    transition_stitch_requirement: TransitionStitchRequirement | None = None

    def hard_context_fingerprint(self, threshold: ReturnHardThreshold) -> str:
        return return_requirement_context_fingerprint(
            declaration_id=self.declaration_id,
            graph=self.graph,
            signal_net_names=self.signal_net_names,
            signal_class=self.signal_class,
            exact_net_class_id=self.exact_net_class_id,
            reference_net_name=self.reference_net_name,
            layer_pairs=self.layer_pairs,
            legs=self.legs,
            adjacency_model_id=self.adjacency_model_id,
            requirement_id=threshold.threshold_id,
            requirement_kind=threshold.kind,
            requirement_value=threshold.value_mm,
        )

    def stitch_context_fingerprint(self) -> str | None:
        requirement = self.transition_stitch_requirement
        if requirement is None:
            return None
        return return_requirement_context_fingerprint(
            declaration_id=self.declaration_id,
            graph=self.graph,
            signal_net_names=self.signal_net_names,
            signal_class=self.signal_class,
            exact_net_class_id=self.exact_net_class_id,
            reference_net_name=self.reference_net_name,
            layer_pairs=self.layer_pairs,
            legs=self.legs,
            adjacency_model_id=self.adjacency_model_id,
            requirement_id=requirement.requirement_id,
            requirement_kind="transition_stitch_maximum_distance_mm",
            requirement_value=requirement.maximum_distance_mm,
        )

    @model_validator(mode="after")
    def declaration_is_replay_bound(self) -> Self:
        for name in (
            "declaration_id",
            "exact_net_class_id",
            "reference_net_name",
            "adjacency_model_id",
        ):
            require_identity(getattr(self, name), name)
        require_sha256(self.board_layout_snapshot_fingerprint, "board_layout_snapshot_fingerprint")
        require_sha256(
            self.board_netlist_snapshot_fingerprint, "board_netlist_snapshot_fingerprint"
        )
        if self.board_layout_snapshot_fingerprint != self.graph.board_layout_snapshot_fingerprint:
            raise ValueError("return declaration is bound to another BoardLayout snapshot")
        if self.board_netlist_snapshot_fingerprint != self.graph.board_netlist_snapshot_fingerprint:
            raise ValueError("return declaration is bound to another BoardNetlist snapshot")
        object.__setattr__(
            self, "signal_net_names", _ids(self.signal_net_names, "signal_net_names")
        )
        pairs = tuple(sorted(self.layer_pairs, key=lambda item: item.signal_layer))
        if len({item.signal_layer for item in pairs}) != len(pairs):
            raise ValueError("each signal layer must have exactly one declared reference layer")
        object.__setattr__(self, "layer_pairs", pairs)
        legs = tuple(sorted(self.legs, key=lambda item: item.leg_id))
        if len({item.leg_id for item in legs}) != len(legs):
            raise ValueError("return leg identities must be unique")
        if {item.signal_net_name for item in legs} != set(self.signal_net_names):
            raise ValueError("declared signal nets must each have complete selected path coverage")
        if any(item.complete_selected_path.graph != self.graph for item in legs):
            raise ValueError("return selected path is bound to another routed graph result")
        object.__setattr__(self, "legs", legs)
        thresholds = tuple(sorted(self.hard_thresholds, key=lambda item: item.threshold_id))
        if len({item.threshold_id for item in thresholds}) != len(thresholds):
            raise ValueError("return hard-threshold identities must be unique")
        if self.adjacency_model_id in ADVISORY_MODEL_IDS and thresholds:
            raise ValueError("3W/3h/one-trace-width advisory models cannot carry hard thresholds")
        if self.adjacency_model_id not in {*ADVISORY_MODEL_IDS, EXACT_CONTAINMENT_MODEL_ID}:
            raise ValueError("unknown return-adjacency model identity")
        object.__setattr__(self, "hard_thresholds", thresholds)
        for threshold in thresholds:
            binding = threshold.evidence_binding
            if not complete_hard_binding(binding):
                raise ValueError(
                    "hard return threshold requires complete pinned applicable evidence"
                )
            if binding.geometry_source_fingerprint != self.hard_context_fingerprint(threshold):
                raise ValueError("hard return threshold evidence is stale for its full context")
        requirement = self.transition_stitch_requirement
        if requirement is not None:
            binding = requirement.evidence_binding
            if not complete_hard_binding(binding):
                raise ValueError("transition stitch requirement requires complete pinned evidence")
            if binding.geometry_source_fingerprint != self.stitch_context_fingerprint():
                raise ValueError("transition stitch evidence is stale for its full context")
        return self


class QualifiedReferenceFill(SemanticIrModel):
    schema_id: Literal["pcbsmith-qualified-return-reference-fill"] = (
        "pcbsmith-qualified-return-reference-fill"
    )
    schema_version: Literal[1] = 1
    reference_fill_id: str
    zone_source_id: str
    reference_net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    exact_geometry: ExactPlanarCompound
    provenance: QualifiedExactZoneFillProvenance
    routed_graph_final_fill_record_sha256: str

    @model_validator(mode="after")
    def fill_is_exact_and_provenanced(self) -> Self:
        require_identity(self.reference_fill_id, "reference_fill_id")
        require_identity(self.zone_source_id, "zone_source_id")
        require_identity(self.reference_net_name, "reference_net_name")
        require_sha256(
            self.routed_graph_final_fill_record_sha256,
            "routed_graph_final_fill_record_sha256",
        )
        if self.provenance.zone_source_provenance_id != self.zone_source_id:
            raise ValueError("reference polygon differs from final-fill source provenance")
        if self.provenance.exact_geometry_fingerprint != self.exact_geometry.semantic_fingerprint():
            raise ValueError("reference polygon geometry differs from final-fill provenance")
        return self


class ReferenceStitchEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-reference-stitch-evidence"] = "pcbsmith-reference-stitch-evidence"
    schema_version: Literal[1] = 1
    stitch_evidence_id: str
    source_id: str
    source_kind: Literal["reference_via"] = "reference_via"
    reference_net_name: str
    reference_layers: tuple[Literal["F.Cu", "B.Cu"], Literal["F.Cu", "B.Cu"]]
    x_mm: Decimal
    y_mm: Decimal
    exact_source_authority_json: str
    exact_source_authority_fingerprint: str

    def authority_payload(self) -> dict[str, Any]:
        return {
            "schema_id": "pcbsmith-exact-reference-stitch-source-authority",
            "schema_version": 1,
            "stitch_evidence_id": self.stitch_evidence_id,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "reference_net_name": self.reference_net_name,
            "reference_layers": self.reference_layers,
            "x_mm": str(self.x_mm),
            "y_mm": str(self.y_mm),
        }

    @model_validator(mode="after")
    def stitch_is_explicit(self) -> Self:
        for name in ("stitch_evidence_id", "source_id", "reference_net_name"):
            require_identity(getattr(self, name), name)
        require_sha256(
            self.exact_source_authority_fingerprint, "exact_source_authority_fingerprint"
        )
        if self.reference_layers[0] == self.reference_layers[1]:
            raise ValueError("reference stitch must explicitly join two reference layers")
        object.__setattr__(self, "reference_layers", ("F.Cu", "B.Cu"))
        object.__setattr__(self, "x_mm", canonical_decimal(self.x_mm, "x_mm"))
        object.__setattr__(self, "y_mm", canonical_decimal(self.y_mm, "y_mm"))
        expected = canonical_json(self.authority_payload())
        if self.exact_source_authority_json != expected:
            raise ValueError("reference stitch source authority JSON is noncanonical or stale")
        if self.exact_source_authority_fingerprint != fingerprint(self.authority_payload()):
            raise ValueError("reference stitch source authority fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        stitch_evidence_id: str,
        source_id: str,
        source_kind: Literal["reference_via"] = "reference_via",
        reference_net_name: str,
        reference_layers: tuple[Literal["F.Cu", "B.Cu"], Literal["F.Cu", "B.Cu"]],
        x_mm: Decimal,
        y_mm: Decimal,
    ) -> Self:
        fields = {
            "stitch_evidence_id": stitch_evidence_id,
            "source_id": source_id,
            "source_kind": source_kind,
            "reference_net_name": reference_net_name,
            "reference_layers": ("F.Cu", "B.Cu"),
            "x_mm": canonical_decimal(x_mm, "x_mm"),
            "y_mm": canonical_decimal(y_mm, "y_mm"),
        }
        payload = {
            "schema_id": "pcbsmith-exact-reference-stitch-source-authority",
            "schema_version": 1,
            **{**fields, "x_mm": str(fields["x_mm"]), "y_mm": str(fields["y_mm"])},
        }
        return cls(
            **fields,
            exact_source_authority_json=canonical_json(payload),
            exact_source_authority_fingerprint=fingerprint(payload),
        )


class TransitionStitchSelection(SemanticIrModel):
    schema_id: Literal["pcbsmith-transition-stitch-selection"] = (
        "pcbsmith-transition-stitch-selection"
    )
    schema_version: Literal[1] = 1
    signal_transition_source_id: str
    stitch_evidence_id: str

    @model_validator(mode="after")
    def selection_is_explicit(self) -> Self:
        require_identity(self.signal_transition_source_id, "signal_transition_source_id")
        require_identity(self.stitch_evidence_id, "stitch_evidence_id")
        return self


class ReturnSegmentEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-segment-evidence"] = "pcbsmith-return-segment-evidence"
    schema_version: Literal[1] = 1
    leg_id: str
    edge_id: str
    signal_source_id: str
    signal_layer: str
    reference_layer: str
    reference_fill_id: str | None
    state: Literal["covered", "uncovered", "unverified", "transition"]
    relation: Literal["contained", "disjoint", "partial_overlap", "unsupported", "transition"]
    witness_point_x: ExactRational | None = None
    witness_point_y: ExactRational | None = None
    exact_length_mm: ExactRational | None = None
    unknown_reason: str | None = None


class ReturnDiscontinuityEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-discontinuity-evidence"] = (
        "pcbsmith-return-discontinuity-evidence"
    )
    schema_version: Literal[1] = 1
    discontinuity_id: str
    leg_id: str
    signal_source_ids: tuple[str, ...] = Field(min_length=1)
    reference_fill_source_ids: tuple[str, ...]
    location_x: ExactRational
    location_y: ExactRational
    exact_length_mm: ExactRational | None
    state: Literal["wholly_uncovered", "partial_or_unknown"]


class ReturnTransitionEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-transition-evidence"] = (
        "pcbsmith-return-transition-evidence"
    )
    schema_version: Literal[1] = 1
    leg_id: str
    signal_via_source_id: str
    from_signal_layer: str
    to_signal_layer: str
    from_reference_layer: str
    to_reference_layer: str
    stitch_evidence_id: str | None
    squared_stitch_distance_mm2: ExactRational | None
    stitch_state: Literal["not_required", "stitched", "unstitched", "unverified"]


class ReturnFinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-finding"] = "pcbsmith-return-finding"
    schema_version: Literal[1] = 1
    finding_id: str
    kind: Literal["adjacency", "discontinuity", "transition_stitch", "advisory_model"]
    disposition: SemanticDisposition
    source_ids: tuple[str, ...]
    message: str


class ReturnAdjacencyResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-return-adjacency-result"] = "pcbsmith-return-adjacency-result"
    schema_version: Literal[1] = 1
    declaration: ReturnPathDeclaration
    reference_fills: tuple[QualifiedReferenceFill, ...]
    stitch_evidence: tuple[ReferenceStitchEvidence, ...]
    stitch_selections: tuple[TransitionStitchSelection, ...]
    segment_evidence: tuple[ReturnSegmentEvidence, ...]
    discontinuities: tuple[ReturnDiscontinuityEvidence, ...]
    transitions: tuple[ReturnTransitionEvidence, ...]
    findings: tuple[ReturnFinding, ...]
    scope_exclusions: tuple[
        Literal[
            "impedance",
            "current",
            "ir_drop",
            "common_impedance",
            "board_mutation",
        ],
        ...,
    ]
    board_mutation_performed: Literal[False] = False
    result_fingerprint: str

    @field_validator("result_fingerprint")
    @classmethod
    def hash_is_valid(cls, value: str) -> str:
        return require_sha256(value, "result_fingerprint")

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.return_adjacency import rederive_return_adjacency

        expected = rederive_return_adjacency(
            self.declaration,
            self.reference_fills,
            self.stitch_evidence,
            self.stitch_selections,
        )
        compared = (
            "segment_evidence",
            "discontinuities",
            "transitions",
            "findings",
            "scope_exclusions",
            "board_mutation_performed",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("return-adjacency result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("return-adjacency result fingerprint is stale")
        return self
