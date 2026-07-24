"""Caller-declared switching hot-loop path and projected-area authority."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.routed_copper_graph_ir import (
    CopperRadicalLengthTerm,
    ExactRational,
    ResolvedCopperPathResult,
    RoutedCopperGraphResult,
    canonical_decimal,
    fingerprint,
    require_identity,
    require_sha256,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticIrModel,
)

SwitchingTransitionRole = Literal[
    "input_energy_storage",
    "high_side_switch",
    "low_side_switch",
    "freewheel_rectifier",
    "transformer_primary",
    "output_rectifier",
    "return_path_element",
    "other_reviewed_transition",
]


class SwitchingHotLoopLegDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-switching-hot-loop-leg-declaration"] = (
        "pcbsmith-switching-hot-loop-leg-declaration"
    )
    schema_version: Literal[2] = 2
    leg_id: str
    role_id: str
    start_anchor_id: str
    start_pad_source_id: str
    end_anchor_id: str
    end_pad_source_id: str
    net_name: str
    path_result_fingerprint: str
    declared_parallel_component_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def leg_is_explicit(self) -> Self:
        for name in (
            "leg_id",
            "role_id",
            "start_anchor_id",
            "start_pad_source_id",
            "end_anchor_id",
            "end_pad_source_id",
            "net_name",
        ):
            require_identity(getattr(self, name), name)
        require_sha256(self.path_result_fingerprint, "path_result_fingerprint")
        if self.start_anchor_id == self.end_anchor_id:
            raise ValueError("switching-loop leg anchors must differ")
        parallel = tuple(
            sorted(
                require_identity(item, "declared_parallel_component_references")
                for item in self.declared_parallel_component_references
            )
        )
        if len(parallel) != len(set(parallel)):
            raise ValueError("declared parallel component references must be unique")
        object.__setattr__(self, "declared_parallel_component_references", parallel)
        return self


class SwitchingHotLoopTerminalTransition(SemanticIrModel):
    schema_id: Literal["pcbsmith-switching-hot-loop-terminal-transition"] = (
        "pcbsmith-switching-hot-loop-terminal-transition"
    )
    schema_version: Literal[2] = 2
    transition_id: str
    component_reference: str
    from_anchor_id: str
    from_pad_source_id: str
    to_anchor_id: str
    to_pad_source_id: str
    transition_role: SwitchingTransitionRole

    @model_validator(mode="after")
    def transition_is_declared(self) -> Self:
        for name in (
            "transition_id",
            "component_reference",
            "from_anchor_id",
            "from_pad_source_id",
            "to_anchor_id",
            "to_pad_source_id",
            "transition_role",
        ):
            require_identity(getattr(self, name), name)
        if self.from_anchor_id == self.to_anchor_id:
            raise ValueError("terminal transitions must join distinct declared pad anchors")
        if self.from_pad_source_id == self.to_pad_source_id:
            raise ValueError("terminal transitions must traverse distinct physical pads")
        return self


class SwitchingHotLoopLimitAuthority(SemanticIrModel):
    schema_id: Literal["pcbsmith-switching-hot-loop-limit-authority"] = (
        "pcbsmith-switching-hot-loop-limit-authority"
    )
    schema_version: Literal[2] = 2
    limit_id: str
    mode: Literal["advisory", "sourced_hard"]
    intended_consumer: str
    expected_transition_roles: tuple[SwitchingTransitionRole, ...] = Field(min_length=3)
    maximum_projected_area_mm2: ExactRational | None
    applicability_binding: EvidenceApplicabilityBinding | None

    @model_validator(mode="after")
    def limit_is_typed(self) -> Self:
        require_identity(self.limit_id, "limit_id")
        require_identity(self.intended_consumer, "intended_consumer")
        if (
            self.maximum_projected_area_mm2 is not None
            and self.maximum_projected_area_mm2.fraction() < 0
        ):
            raise ValueError("switching-loop maximum area cannot be negative")
        if self.mode == "advisory" and self.applicability_binding is not None:
            raise ValueError("advisory area limits cannot carry hard applicability authority")
        return self


def switching_hot_loop_context_fingerprint(
    *,
    graph_fingerprint: str,
    board_layout_snapshot_fingerprint: str,
    board_netlist_snapshot_fingerprint: str,
    topology_kind: str,
    legs: tuple[SwitchingHotLoopLegDeclaration, ...],
    transitions: tuple[SwitchingHotLoopTerminalTransition, ...],
    limit_id: str,
    mode: str,
    maximum_projected_area_mm2: ExactRational | None,
    intended_consumer: str,
    expected_transition_roles: tuple[SwitchingTransitionRole, ...],
) -> str:
    return fingerprint(
        {
            "schema_id": "pcbsmith-switching-hot-loop-source-context",
            "schema_version": 1,
            "graph_fingerprint": graph_fingerprint,
            "board_layout_snapshot_fingerprint": board_layout_snapshot_fingerprint,
            "board_netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint,
            "topology_kind": topology_kind,
            "legs": [item.model_dump(mode="json") for item in legs],
            "transitions": [item.model_dump(mode="json") for item in transitions],
            "limit_id": limit_id,
            "mode": mode,
            "intended_consumer": intended_consumer,
            "expected_transition_roles": expected_transition_roles,
            "maximum_projected_area_mm2": (
                None
                if maximum_projected_area_mm2 is None
                else maximum_projected_area_mm2.model_dump(mode="json")
            ),
        }
    )


class SwitchingHotLoopDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-switching-hot-loop-declaration"] = (
        "pcbsmith-switching-hot-loop-declaration"
    )
    schema_version: Literal[2] = 2
    declaration_id: str
    topology_kind: Literal["buck", "boost", "flyback", "other"]
    graph_fingerprint: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    legs: tuple[SwitchingHotLoopLegDeclaration, ...] = Field(min_length=3)
    transitions: tuple[SwitchingHotLoopTerminalTransition, ...] = Field(min_length=3)
    limit: SwitchingHotLoopLimitAuthority

    @model_validator(mode="after")
    def declaration_is_ordered_and_complete(self) -> Self:
        require_identity(self.declaration_id, "declaration_id")
        require_identity(self.topology_kind, "topology_kind")
        for name in (
            "graph_fingerprint",
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        if len(self.legs) != len(self.transitions):
            raise ValueError("switching-loop legs and terminal transitions must pair exactly")
        if len(self.limit.expected_transition_roles) != len(self.transitions):
            raise ValueError("expected transition roles must cover the complete switching cycle")
        if len({item.leg_id for item in self.legs}) != len(self.legs):
            raise ValueError("switching-loop leg identities must be unique")
        terminal_anchor_ids = {
            anchor_id
            for item in self.legs
            for anchor_id in (item.start_anchor_id, item.end_anchor_id)
        }
        if len(terminal_anchor_ids) < 3:
            raise ValueError(
                "switching-loop cycle requires at least three distinct physical terminal anchors"
            )
        if len({item.transition_id for item in self.transitions}) != len(self.transitions):
            raise ValueError("switching-loop transition identities must be unique")
        return self


class SwitchingHotLoopLegMetrics(SemanticIrModel):
    schema_id: Literal["pcbsmith-switching-hot-loop-leg-metrics"] = (
        "pcbsmith-switching-hot-loop-leg-metrics"
    )
    schema_version: Literal[1] = 1
    leg_id: str
    ordered_node_ids: tuple[str, ...]
    ordered_edge_ids: tuple[str, ...]
    ordered_source_ids: tuple[str, ...]
    ordered_layer_transitions: tuple[str, ...]
    via_count: int = Field(ge=0)
    via_source_ids: tuple[str, ...]
    minimum_track_width_mm: Decimal | None
    neck_edge_ids: tuple[str, ...]
    radical_length_terms: tuple[CopperRadicalLengthTerm, ...]

    @model_validator(mode="after")
    def widths_are_exact(self) -> Self:
        if self.minimum_track_width_mm is not None:
            object.__setattr__(
                self,
                "minimum_track_width_mm",
                canonical_decimal(self.minimum_track_width_mm, "minimum_track_width_mm"),
            )
        return self


class SwitchingHotLoopTransitionEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-switching-hot-loop-transition-evidence"] = (
        "pcbsmith-switching-hot-loop-transition-evidence"
    )
    schema_version: Literal[1] = 1
    transition_id: str
    from_anchor_id: str
    to_anchor_id: str
    squared_projected_length_mm2: ExactRational


class SwitchingHotLoopMetrics(SemanticIrModel):
    schema_id: Literal["pcbsmith-switching-hot-loop-metrics"] = (
        "pcbsmith-switching-hot-loop-metrics"
    )
    schema_version: Literal[2] = 2
    legs: tuple[SwitchingHotLoopLegMetrics, ...]
    transitions: tuple[SwitchingHotLoopTransitionEvidence, ...]
    combined_source_ids: tuple[str, ...]
    combined_via_count: int = Field(ge=0)
    combined_via_source_ids: tuple[str, ...]
    combined_minimum_track_width_mm: Decimal | None
    combined_neck_edge_ids: tuple[str, ...]
    combined_radical_length_terms: tuple[CopperRadicalLengthTerm, ...]
    projected_signed_area_mm2: ExactRational | None
    projected_absolute_area_mm2: ExactRational | None
    projected_polygon_verification: Literal["exact_simple", "unverified_non_simple"]
    transition_component_references: tuple[str, ...]
    transition_roles: tuple[SwitchingTransitionRole, ...]
    leg_terminal_component_references: tuple[tuple[str, tuple[str, ...]], ...]


class SwitchingHotLoopEvaluationResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-switching-hot-loop-evaluation-result"] = (
        "pcbsmith-switching-hot-loop-evaluation-result"
    )
    schema_version: Literal[2] = 2
    authority_statement: Literal[
        "declared topology membership and projected-area authority only; no electromagnetic claim"
    ] = "declared topology membership and projected-area authority only; no electromagnetic claim"
    graph: RoutedCopperGraphResult
    paths: tuple[ResolvedCopperPathResult, ...]
    declaration: SwitchingHotLoopDeclaration
    metrics: SwitchingHotLoopMetrics | None
    disposition: SemanticDisposition
    violation_ids: tuple[str, ...]
    unverified_reasons: tuple[str, ...]
    input_fingerprint: str
    result_fingerprint: str

    @field_validator("input_fingerprint", "result_fingerprint")
    @classmethod
    def hashes_are_valid(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.switching_hot_loop import rederive_switching_hot_loop

        expected = rederive_switching_hot_loop(self.graph, self.paths, self.declaration)
        compared = (
            "paths",
            "declaration",
            "metrics",
            "disposition",
            "violation_ids",
            "unverified_reasons",
            "input_fingerprint",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("switching hot-loop result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("switching hot-loop result fingerprint is stale")
        return self
