"""Replay-bound exact switch-node planar copper-union evidence.

This schema deliberately describes only a restricted projected-area metric.  It
does not establish an area limit, electrical or thermal adequacy, or permission
to mutate copper.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.placement_geometry import ExactPlanarCompound
from pcbsmith.routed_copper_graph_ir import (
    ExactRational,
    RoutedCopperGraphResult,
    fingerprint,
    require_identity,
    require_sha256,
)
from pcbsmith.semantic_ir import SemanticIrModel, SemanticVerification


class SwitchNodeCopperDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-switch-node-copper-declaration"] = (
        "pcbsmith-switch-node-copper-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str
    graph_fingerprint: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    net_names: tuple[str, ...] = Field(min_length=1)
    layers: tuple[Literal["F.Cu", "B.Cu"], ...] = Field(min_length=1)
    complete_pad_authority: bool

    @model_validator(mode="after")
    def declaration_is_canonical(self) -> Self:
        require_identity(self.declaration_id, "declaration_id")
        for name in (
            "graph_fingerprint",
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        nets = tuple(sorted(require_identity(item, "net_names") for item in self.net_names))
        layers = tuple(sorted(self.layers))
        if len(nets) != len(set(nets)) or len(layers) != len(set(layers)):
            raise ValueError("switch-node nets and layers must be unique")
        object.__setattr__(self, "net_names", nets)
        object.__setattr__(self, "layers", layers)
        return self


class ExactPlacedPadCopper(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-placed-pad-copper"] = "pcbsmith-exact-placed-pad-copper"
    schema_version: Literal[1] = 1
    source_id: str
    component_reference: str
    pad_number: str
    net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    graph_fingerprint: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    copper: ExactPlanarCompound

    @model_validator(mode="after")
    def record_is_canonical(self) -> Self:
        for name in ("source_id", "component_reference", "pad_number", "net_name"):
            require_identity(getattr(self, name), name)
        for name in (
            "graph_fingerprint",
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        return self


class ExactCopperRectangle(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-copper-rectangle"] = "pcbsmith-exact-copper-rectangle"
    schema_version: Literal[1] = 1
    min_x_mm: ExactRational
    min_y_mm: ExactRational
    max_x_mm: ExactRational
    max_y_mm: ExactRational

    @model_validator(mode="after")
    def rectangle_has_positive_area(self) -> Self:
        if self.min_x_mm.fraction() >= self.max_x_mm.fraction():
            raise ValueError("exact rectangle x bounds must have positive extent")
        if self.min_y_mm.fraction() >= self.max_y_mm.fraction():
            raise ValueError("exact rectangle y bounds must have positive extent")
        return self


class ExactCopperDisc(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-copper-disc"] = "pcbsmith-exact-copper-disc"
    schema_version: Literal[1] = 1
    center_x_mm: ExactRational
    center_y_mm: ExactRational
    radius_mm: ExactRational

    @model_validator(mode="after")
    def radius_is_positive(self) -> Self:
        if self.radius_mm.fraction() <= 0:
            raise ValueError("exact disc radius must be positive")
        return self


class ExactCopperCapsule(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-copper-capsule"] = "pcbsmith-exact-copper-capsule"
    schema_version: Literal[1] = 1
    start_x_mm: ExactRational
    start_y_mm: ExactRational
    end_x_mm: ExactRational
    end_y_mm: ExactRational
    radius_mm: ExactRational

    @model_validator(mode="after")
    def capsule_is_axis_aligned(self) -> Self:
        start = (self.start_x_mm.fraction(), self.start_y_mm.fraction())
        end = (self.end_x_mm.fraction(), self.end_y_mm.fraction())
        if start >= end:
            raise ValueError("exact capsule endpoints must use canonical order")
        if start[0] != end[0] and start[1] != end[1]:
            raise ValueError("v1 exact capsule must be axis-aligned")
        if self.radius_mm.fraction() <= 0:
            raise ValueError("exact capsule radius must be positive")
        return self


class SwitchNodeCopperPrimitive(SemanticIrModel):
    schema_id: Literal["pcbsmith-switch-node-copper-primitive"] = (
        "pcbsmith-switch-node-copper-primitive"
    )
    schema_version: Literal[1] = 1
    primitive_id: str
    source_id: str
    source_kind: Literal["pad", "track", "via", "exact_filled_zone"]
    net_name: str
    layers: tuple[Literal["F.Cu", "B.Cu"], ...] = Field(min_length=1)
    geometry_kind: Literal["rectangle", "disc", "capsule"]
    rectangle: ExactCopperRectangle | None = None
    disc: ExactCopperDisc | None = None
    capsule: ExactCopperCapsule | None = None
    source_authority_fingerprint: str
    primitive_fingerprint: str

    @model_validator(mode="after")
    def primitive_is_coherent(self) -> Self:
        require_identity(self.primitive_id, "primitive_id")
        require_identity(self.source_id, "source_id")
        require_identity(self.net_name, "net_name")
        require_sha256(self.source_authority_fingerprint, "source_authority_fingerprint")
        require_sha256(self.primitive_fingerprint, "primitive_fingerprint")
        layers = tuple(sorted(self.layers))
        if len(layers) != len(set(layers)):
            raise ValueError("primitive layers must be unique")
        object.__setattr__(self, "layers", layers)
        geometries = {
            "rectangle": self.rectangle,
            "disc": self.disc,
            "capsule": self.capsule,
        }
        if (
            geometries[self.geometry_kind] is None
            or sum(v is not None for v in geometries.values()) != 1
        ):
            raise ValueError("primitive must retain exactly its declared geometry")
        geometry = geometries[self.geometry_kind]
        assert geometry is not None
        expected = fingerprint(
            {"kind": self.geometry_kind, "geometry": geometry.model_dump(mode="json")}
        )
        if self.primitive_fingerprint != expected:
            raise ValueError("primitive geometry fingerprint is stale")
        expected_id = "primitive:" + fingerprint(
            {
                "source_id": self.source_id,
                "source_kind": self.source_kind,
                "net_name": self.net_name,
                "layers": self.layers,
                "source_authority_fingerprint": self.source_authority_fingerprint,
                "primitive_fingerprint": self.primitive_fingerprint,
            }
        )
        if self.primitive_id != expected_id:
            raise ValueError("per-source primitive identity is stale")
        return self


class SwitchNodeCopperUnionWitness(SemanticIrModel):
    schema_id: Literal["pcbsmith-switch-node-copper-union-witness"] = (
        "pcbsmith-switch-node-copper-union-witness"
    )
    schema_version: Literal[1] = 1
    witness_id: str
    layer: Literal["F.Cu", "B.Cu"]
    relation: Literal[
        "rectangle_sweep_member",
        "identical_geometry_deduplicated",
        "curved_primitive_contained_in_rectangle",
        "zero_area_contact_or_disjoint",
    ]
    source_ids: tuple[str, ...] = Field(min_length=1)
    primitive_fingerprints: tuple[str, ...] = Field(min_length=1)
    exact_predicate: str

    @model_validator(mode="after")
    def witness_is_canonical(self) -> Self:
        require_identity(self.witness_id, "witness_id")
        require_identity(self.exact_predicate, "exact_predicate")
        sources = tuple(sorted(require_identity(item, "source_ids") for item in self.source_ids))
        primitives = tuple(sorted(self.primitive_fingerprints))
        if len(sources) != len(set(sources)):
            raise ValueError("witness source identities must be unique")
        for value in primitives:
            require_sha256(value, "primitive_fingerprints")
        object.__setattr__(self, "source_ids", sources)
        object.__setattr__(self, "primitive_fingerprints", primitives)
        return self


class SwitchNodeCopperLayerArea(SemanticIrModel):
    schema_id: Literal["pcbsmith-switch-node-copper-layer-area"] = (
        "pcbsmith-switch-node-copper-layer-area"
    )
    schema_version: Literal[1] = 1
    layer: Literal["F.Cu", "B.Cu"]
    verification: SemanticVerification
    rational_mm2: ExactRational | None
    pi_coefficient_mm2: ExactRational | None
    primitive_ids: tuple[str, ...]
    witness_ids: tuple[str, ...]
    unknown_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def area_is_coherent_and_canonical(self) -> Self:
        primitive_ids = tuple(
            sorted(require_identity(item, "primitive_ids") for item in self.primitive_ids)
        )
        witness_ids = tuple(
            sorted(require_identity(item, "witness_ids") for item in self.witness_ids)
        )
        reasons = tuple(
            sorted(require_identity(item, "unknown_reasons") for item in self.unknown_reasons)
        )
        if len(primitive_ids) != len(set(primitive_ids)) or len(witness_ids) != len(
            set(witness_ids)
        ):
            raise ValueError("per-layer primitive and witness identities must be unique")
        if self.verification is SemanticVerification.EXACT:
            if self.rational_mm2 is None or self.pi_coefficient_mm2 is None or reasons:
                raise ValueError("exact per-layer area requires both coefficients and no unknowns")
        elif self.rational_mm2 is not None or self.pi_coefficient_mm2 is not None or not reasons:
            raise ValueError("unverified per-layer area requires reasons and no numeric result")
        object.__setattr__(self, "primitive_ids", primitive_ids)
        object.__setattr__(self, "witness_ids", witness_ids)
        object.__setattr__(self, "unknown_reasons", reasons)
        return self


class SwitchNodeCopperUnionResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-switch-node-copper-union-result"] = (
        "pcbsmith-switch-node-copper-union-result"
    )
    schema_version: Literal[1] = 1
    graph: RoutedCopperGraphResult
    declaration: SwitchNodeCopperDeclaration
    placed_pad_copper: tuple[ExactPlacedPadCopper, ...]
    primitives: tuple[SwitchNodeCopperPrimitive, ...]
    witnesses: tuple[SwitchNodeCopperUnionWitness, ...]
    per_layer_areas: tuple[SwitchNodeCopperLayerArea, ...]
    verification: SemanticVerification
    rational_mm2: ExactRational | None
    pi_coefficient_mm2: ExactRational | None
    unknown_reasons: tuple[str, ...]
    source_coverage_ids: tuple[str, ...]
    metric_scope: Literal["restricted_exact_per_layer_planar_copper_union_v1"] = (
        "restricted_exact_per_layer_planar_copper_union_v1"
    )
    evidence_fingerprint: str
    result_fingerprint: str

    @field_validator("evidence_fingerprint", "result_fingerprint")
    @classmethod
    def digest_is_valid(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.switch_node_copper import rederive_switch_node_copper_union

        expected = rederive_switch_node_copper_union(
            self.graph, self.declaration, self.placed_pad_copper
        )
        compared = (
            "placed_pad_copper",
            "primitives",
            "witnesses",
            "per_layer_areas",
            "verification",
            "rational_mm2",
            "pi_coefficient_mm2",
            "unknown_reasons",
            "source_coverage_ids",
            "evidence_fingerprint",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("switch-node copper union is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("switch-node copper union result fingerprint is stale")
        return self
