"""Replay-bound routed-copper graph and declared path interchange models."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from fractions import Fraction
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.semantic_ir import SemanticIrModel, SemanticVerification
from pcbsmith.sensor_copper_removal_ir import ExactFilledZoneCopper


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot canonically serialize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
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


def canonical_decimal(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be a finite exact decimal")
    if value == 0:
        return Decimal(0)
    normalized = value.normalize()
    exponent = normalized.as_tuple().exponent
    return (
        normalized.quantize(Decimal(1))
        if isinstance(exponent, int) and exponent > 0
        else normalized
    )


class ExactRational(SemanticIrModel):
    schema_id: Literal["pcbsmith-copper-exact-rational"] = "pcbsmith-copper-exact-rational"
    schema_version: Literal[1] = 1
    numerator: int
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def value_is_reduced(self) -> Self:
        value = Fraction(self.numerator, self.denominator)
        if (value.numerator, value.denominator) != (self.numerator, self.denominator):
            raise ValueError("exact rational must be reduced")
        return self

    @classmethod
    def build(cls, value: Fraction) -> ExactRational:
        return cls(numerator=value.numerator, denominator=value.denominator)

    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class CopperTerminalAnchorBinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-copper-terminal-anchor-binding"] = (
        "pcbsmith-copper-terminal-anchor-binding"
    )
    schema_version: Literal[1] = 1
    anchor_id: str = Field(min_length=1)
    physical_pad_source_id: str = Field(min_length=1)
    component_reference: str = Field(min_length=1)
    pad_number: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    layer: Literal["F.Cu", "B.Cu"]
    x_mm: Decimal
    y_mm: Decimal

    @model_validator(mode="after")
    def binding_is_exact(self) -> Self:
        for name in (
            "anchor_id",
            "physical_pad_source_id",
            "component_reference",
            "pad_number",
            "net_name",
        ):
            require_identity(getattr(self, name), name)
        object.__setattr__(self, "x_mm", canonical_decimal(self.x_mm, "x_mm"))
        object.__setattr__(self, "y_mm", canonical_decimal(self.y_mm, "y_mm"))
        return self


class RoutedCopperNode(SemanticIrModel):
    schema_id: Literal["pcbsmith-routed-copper-node"] = "pcbsmith-routed-copper-node"
    schema_version: Literal[1] = 1
    node_id: str
    net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    x_mm: Decimal
    y_mm: Decimal
    anchor_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def node_is_canonical(self) -> Self:
        require_identity(self.node_id, "node_id")
        require_identity(self.net_name, "net_name")
        anchors = tuple(sorted(require_identity(item, "anchor_ids") for item in self.anchor_ids))
        if len(anchors) != len(set(anchors)):
            raise ValueError("node anchor identities must be unique")
        object.__setattr__(self, "anchor_ids", anchors)
        object.__setattr__(self, "x_mm", canonical_decimal(self.x_mm, "x_mm"))
        object.__setattr__(self, "y_mm", canonical_decimal(self.y_mm, "y_mm"))
        return self


class RoutedCopperEdge(SemanticIrModel):
    schema_id: Literal["pcbsmith-routed-copper-edge"] = "pcbsmith-routed-copper-edge"
    schema_version: Literal[1] = 1
    edge_id: str
    source_id: str
    kind: Literal["track", "via", "exact_zone_fill"]
    net_name: str
    start_node_id: str
    end_node_id: str
    width_mm: Decimal | None
    via_size_mm: Decimal | None
    planar_squared_length: ExactRational | None
    final_fill_record_sha256: str | None = None

    @model_validator(mode="after")
    def edge_is_coherent(self) -> Self:
        for name in ("edge_id", "source_id", "net_name", "start_node_id", "end_node_id"):
            require_identity(getattr(self, name), name)
        if self.start_node_id >= self.end_node_id:
            raise ValueError("copper edge endpoints must use canonical node order")
        if self.kind == "exact_zone_fill":
            if (
                self.width_mm is not None
                or self.via_size_mm is not None
                or self.planar_squared_length is not None
            ):
                raise ValueError("zone connectivity cannot fabricate width or path length")
            if self.final_fill_record_sha256 is None:
                raise ValueError("exact zone edge requires its final-fill record")
            require_sha256(self.final_fill_record_sha256, "final_fill_record_sha256")
        elif self.kind == "track":
            if (
                self.width_mm is None
                or self.via_size_mm is not None
                or self.planar_squared_length is None
            ):
                raise ValueError("track edges require exact trace width and squared length")
            object.__setattr__(self, "width_mm", canonical_decimal(self.width_mm, "width_mm"))
            if self.final_fill_record_sha256 is not None:
                raise ValueError("track edge cannot cite zone-fill authority")
        else:
            if (
                self.width_mm is not None
                or self.via_size_mm is None
                or self.planar_squared_length is None
            ):
                raise ValueError("via edges require exact via size and squared planar length")
            object.__setattr__(
                self, "via_size_mm", canonical_decimal(self.via_size_mm, "via_size_mm")
            )
            if self.final_fill_record_sha256 is not None:
                raise ValueError("via edge cannot cite zone-fill authority")
        return self


class RoutedCopperUnknownZoneReason(SemanticIrModel):
    schema_id: Literal["pcbsmith-routed-copper-unknown-zone-reason"] = (
        "pcbsmith-routed-copper-unknown-zone-reason"
    )
    schema_version: Literal[1] = 1
    zone_source_id: str
    net_name: str
    layer: str
    reason: Literal[
        "zone_intent_without_exact_fill",
        "exact_fill_geometry_not_supported_for_point_connectivity",
    ]


class RoutedCopperUnverifiedContact(SemanticIrModel):
    """Exact contact that an endpoint-only graph refuses to invent as an edge."""

    schema_id: Literal["pcbsmith-routed-copper-unverified-contact"] = (
        "pcbsmith-routed-copper-unverified-contact"
    )
    schema_version: Literal[1] = 1
    issue_id: str
    net_name: str
    layer: str
    source_ids: tuple[str, ...] = Field(min_length=1)
    x: ExactRational
    y: ExactRational
    reason: Literal[
        "anchor_on_track_interior",
        "via_on_track_interior",
        "track_t_junction",
        "track_crossing",
        "collinear_track_overlap",
    ]

    @model_validator(mode="after")
    def issue_is_canonical(self) -> Self:
        require_identity(self.issue_id, "issue_id")
        require_identity(self.net_name, "net_name")
        require_identity(self.layer, "layer")
        sources = tuple(sorted(require_identity(item, "source_ids") for item in self.source_ids))
        if len(sources) != len(set(sources)):
            raise ValueError("unverified contact source identities must be unique")
        object.__setattr__(self, "source_ids", sources)
        return self


class RoutedCopperGraphResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-routed-copper-graph-result"] = (
        "pcbsmith-routed-copper-graph-result"
    )
    schema_version: Literal[1] = 1
    board_layout_snapshot_json: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_json: str
    board_netlist_snapshot_fingerprint: str
    terminal_anchors: tuple[CopperTerminalAnchorBinding, ...]
    exact_filled_zones: tuple[ExactFilledZoneCopper, ...]
    nodes: tuple[RoutedCopperNode, ...]
    edges: tuple[RoutedCopperEdge, ...]
    unknown_zone_reasons: tuple[RoutedCopperUnknownZoneReason, ...]
    unverified_contacts: tuple[RoutedCopperUnverifiedContact, ...]
    graph_fingerprint: str
    result_fingerprint: str

    @field_validator(
        "board_layout_snapshot_fingerprint",
        "board_netlist_snapshot_fingerprint",
        "graph_fingerprint",
        "result_fingerprint",
    )
    @classmethod
    def hash_is_valid(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.routed_copper_graph import rederive_routed_copper_graph

        expected = rederive_routed_copper_graph(
            self.board_layout_snapshot_json,
            self.board_netlist_snapshot_json,
            self.terminal_anchors,
            self.exact_filled_zones,
        )
        compared = (
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
            "terminal_anchors",
            "exact_filled_zones",
            "nodes",
            "edges",
            "unknown_zone_reasons",
            "unverified_contacts",
            "graph_fingerprint",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("routed copper graph is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("routed copper graph result fingerprint is stale")
        return self


class DeclaredCopperPathSelection(SemanticIrModel):
    schema_id: Literal["pcbsmith-declared-copper-path-selection"] = (
        "pcbsmith-declared-copper-path-selection"
    )
    schema_version: Literal[1] = 1
    selection_id: str
    graph_fingerprint: str
    net_name: str
    start_anchor_id: str
    end_anchor_id: str
    ordered_edge_ids: tuple[str, ...] | None

    @model_validator(mode="after")
    def selection_is_declared(self) -> Self:
        for name in ("selection_id", "net_name", "start_anchor_id", "end_anchor_id"):
            require_identity(getattr(self, name), name)
        require_sha256(self.graph_fingerprint, "graph_fingerprint")
        if self.start_anchor_id == self.end_anchor_id:
            raise ValueError("declared path endpoints must differ")
        if self.ordered_edge_ids is not None:
            values = tuple(
                require_identity(item, "ordered_edge_ids") for item in self.ordered_edge_ids
            )
            if not values or len(values) != len(set(values)):
                raise ValueError("explicit path edge selection must be nonempty and unique")
            object.__setattr__(self, "ordered_edge_ids", values)
        return self


class CopperRadicalLengthTerm(SemanticIrModel):
    schema_id: Literal["pcbsmith-copper-radical-length-term"] = (
        "pcbsmith-copper-radical-length-term"
    )
    schema_version: Literal[1] = 1
    squarefree_radicand: int = Field(ge=1)
    coefficient_mm: ExactRational


class ResolvedCopperPathResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-resolved-copper-path-result"] = (
        "pcbsmith-resolved-copper-path-result"
    )
    schema_version: Literal[1] = 1
    graph: RoutedCopperGraphResult
    selection: DeclaredCopperPathSelection
    connectivity_state: Literal["connected", "disconnected", "unverified"]
    verification: SemanticVerification
    ordered_edge_ids: tuple[str, ...]
    ordered_node_ids: tuple[str, ...]
    ordered_source_ids: tuple[str, ...]
    via_count: int = Field(ge=0)
    via_source_ids: tuple[str, ...]
    minimum_width_mm: Decimal | None
    neck_edge_ids: tuple[str, ...]
    radical_length_terms: tuple[CopperRadicalLengthTerm, ...]
    exact_rational_planar_length_mm: ExactRational | None
    length_scope: Literal["planar_track_edges_only"] = "planar_track_edges_only"
    unknown_reasons: tuple[str, ...]
    evidence_fingerprint: str
    result_fingerprint: str

    @field_validator("evidence_fingerprint", "result_fingerprint")
    @classmethod
    def result_hash_is_valid(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.routed_copper_graph import rederive_copper_path

        expected = rederive_copper_path(self.graph, self.selection)
        compared = (
            "connectivity_state",
            "verification",
            "ordered_edge_ids",
            "ordered_node_ids",
            "ordered_source_ids",
            "via_count",
            "via_source_ids",
            "minimum_width_mm",
            "neck_edge_ids",
            "radical_length_terms",
            "exact_rational_planar_length_mm",
            "unknown_reasons",
            "evidence_fingerprint",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("resolved copper path is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("resolved copper path result fingerprint is stale")
        return self
