"""Exact electrical/topological declarations for decoupling current loops."""

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
from pcbsmith.semantic_ir import SemanticDisposition, SemanticIrModel


class DecouplingTerminalInventoryEntry(SemanticIrModel):
    schema_id: Literal["pcbsmith-decoupling-terminal-inventory-entry"] = (
        "pcbsmith-decoupling-terminal-inventory-entry"
    )
    schema_version: Literal[1] = 1
    anchor_id: str
    physical_pad_source_id: str
    component_reference: str
    pad_number: str
    net_name: str

    @model_validator(mode="after")
    def identity_is_explicit(self) -> Self:
        for name in (
            "anchor_id",
            "physical_pad_source_id",
            "component_reference",
            "pad_number",
            "net_name",
        ):
            require_identity(getattr(self, name), name)
        return self


class DecouplingTerminalInventory(SemanticIrModel):
    schema_id: Literal["pcbsmith-decoupling-terminal-inventory"] = (
        "pcbsmith-decoupling-terminal-inventory"
    )
    schema_version: Literal[1] = 1
    inventory_id: str
    graph_fingerprint: str
    power_net_name: str
    return_net_name: str
    completeness: Literal["complete", "incomplete"]
    entries: tuple[DecouplingTerminalInventoryEntry, ...]

    @model_validator(mode="after")
    def inventory_is_canonical(self) -> Self:
        for name in ("inventory_id", "power_net_name", "return_net_name"):
            require_identity(getattr(self, name), name)
        require_sha256(self.graph_fingerprint, "graph_fingerprint")
        if self.power_net_name == self.return_net_name:
            raise ValueError("decoupling power and return nets must differ")
        entries = tuple(sorted(self.entries, key=lambda item: item.anchor_id))
        if len({item.anchor_id for item in entries}) != len(entries):
            raise ValueError("terminal inventory anchor identities must be unique")
        if len({item.physical_pad_source_id for item in entries}) != len(entries):
            raise ValueError("terminal inventory physical pad source identities must be unique")
        pad_nodes = tuple((item.component_reference, item.pad_number) for item in entries)
        if len(set(pad_nodes)) != len(pad_nodes):
            raise ValueError("terminal inventory component/pad identities must be unique")
        object.__setattr__(self, "entries", entries)
        return self


class DecouplingLoopPolicy(SemanticIrModel):
    schema_id: Literal["pcbsmith-decoupling-loop-policy"] = "pcbsmith-decoupling-loop-policy"
    schema_version: Literal[1] = 1
    policy_id: str
    maximum_via_count: ExactRational
    minimum_track_width_mm: Decimal | None
    maximum_projected_loop_area_mm2: ExactRational | None
    require_dedicated: bool

    @model_validator(mode="after")
    def policy_is_exact(self) -> Self:
        require_identity(self.policy_id, "policy_id")
        maximum = self.maximum_via_count.fraction()
        if maximum < 0 or maximum.denominator != 1:
            raise ValueError("maximum via count must be a non-negative exact integer")
        if self.minimum_track_width_mm is not None:
            minimum = canonical_decimal(self.minimum_track_width_mm, "minimum_track_width_mm")
            if minimum <= 0:
                raise ValueError("minimum track width must be positive")
            object.__setattr__(self, "minimum_track_width_mm", minimum)
        if (
            self.maximum_projected_loop_area_mm2 is not None
            and self.maximum_projected_loop_area_mm2.fraction() < 0
        ):
            raise ValueError("maximum projected loop area cannot be negative")
        return self


class DecouplingLoopDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-decoupling-loop-declaration"] = (
        "pcbsmith-decoupling-loop-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str
    graph_fingerprint: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    supply_path_result_fingerprint: str
    return_path_result_fingerprint: str
    source_power_anchor_id: str
    source_power_pad_source_id: str
    load_power_anchor_id: str
    load_power_pad_source_id: str
    load_return_anchor_id: str
    load_return_pad_source_id: str
    source_return_anchor_id: str
    source_return_pad_source_id: str
    expected_power_net_name: str
    expected_return_net_name: str
    terminal_inventory: DecouplingTerminalInventory
    policy: DecouplingLoopPolicy

    @model_validator(mode="after")
    def declaration_is_bound(self) -> Self:
        identities = (
            "declaration_id",
            "source_power_anchor_id",
            "source_power_pad_source_id",
            "load_power_anchor_id",
            "load_power_pad_source_id",
            "load_return_anchor_id",
            "load_return_pad_source_id",
            "source_return_anchor_id",
            "source_return_pad_source_id",
            "expected_power_net_name",
            "expected_return_net_name",
        )
        for name in identities:
            require_identity(getattr(self, name), name)
        for name in (
            "graph_fingerprint",
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
            "supply_path_result_fingerprint",
            "return_path_result_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        anchor_ids = (
            self.source_power_anchor_id,
            self.load_power_anchor_id,
            self.load_return_anchor_id,
            self.source_return_anchor_id,
        )
        if len(set(anchor_ids)) != len(anchor_ids):
            raise ValueError("decoupling terminal roles require four distinct anchors")
        if self.expected_power_net_name == self.expected_return_net_name:
            raise ValueError("decoupling power and return nets must differ")
        return self


class DecouplingPathLegMetrics(SemanticIrModel):
    schema_id: Literal["pcbsmith-decoupling-path-leg-metrics"] = (
        "pcbsmith-decoupling-path-leg-metrics"
    )
    schema_version: Literal[1] = 1
    leg: Literal["supply", "return"]
    ordered_node_ids: tuple[str, ...]
    ordered_edge_ids: tuple[str, ...]
    ordered_source_ids: tuple[str, ...]
    ordered_layer_transitions: tuple[str, ...]
    via_count: int = Field(ge=0)
    via_source_ids: tuple[str, ...]
    minimum_track_width_mm: Decimal | None
    neck_edge_ids: tuple[str, ...]
    radical_length_terms: tuple[CopperRadicalLengthTerm, ...]


class DecouplingClosureSegment(SemanticIrModel):
    schema_id: Literal["pcbsmith-decoupling-closure-segment"] = (
        "pcbsmith-decoupling-closure-segment"
    )
    schema_version: Literal[1] = 1
    closure_id: Literal["load-endpoint-closure", "source-endpoint-closure"]
    start_node_id: str
    end_node_id: str
    squared_length_mm2: ExactRational


class DecouplingLoopMetrics(SemanticIrModel):
    schema_id: Literal["pcbsmith-decoupling-loop-metrics"] = "pcbsmith-decoupling-loop-metrics"
    schema_version: Literal[1] = 1
    supply: DecouplingPathLegMetrics
    return_leg: DecouplingPathLegMetrics
    combined_via_count: int = Field(ge=0)
    combined_via_source_ids: tuple[str, ...]
    combined_minimum_track_width_mm: Decimal | None
    combined_neck_edge_ids: tuple[str, ...]
    combined_radical_length_terms: tuple[CopperRadicalLengthTerm, ...]
    projected_loop_area_mm2: ExactRational | None
    closure_segments: tuple[DecouplingClosureSegment, ...]
    projected_closure_verification: Literal["exact_simple", "unverified_non_simple"]
    terminal_classification: Literal["dedicated", "daisy_chain", "unverified"]
    interior_anchor_ids: tuple[str, ...]


class DecouplingLoopEvaluationResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-decoupling-loop-evaluation-result"] = (
        "pcbsmith-decoupling-loop-evaluation-result"
    )
    schema_version: Literal[1] = 1
    authority_statement: Literal[
        "electrical topology metrics only; no electromagnetic or placement-distance claim"
    ] = "electrical topology metrics only; no electromagnetic or placement-distance claim"
    graph: RoutedCopperGraphResult
    supply_path: ResolvedCopperPathResult
    return_path: ResolvedCopperPathResult
    declaration: DecouplingLoopDeclaration
    metrics: DecouplingLoopMetrics | None
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
        from pcbsmith.kicad.decoupling_loop import rederive_decoupling_loop

        expected = rederive_decoupling_loop(
            self.graph, self.supply_path, self.return_path, self.declaration
        )
        compared = (
            "declaration",
            "metrics",
            "disposition",
            "violation_ids",
            "unverified_reasons",
            "input_fingerprint",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("decoupling loop result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("decoupling loop result fingerprint is stale")
        return self
