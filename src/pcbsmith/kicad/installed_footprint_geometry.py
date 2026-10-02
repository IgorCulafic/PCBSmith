"""Source-bound installed-footprint geometry for placement and routing gates.

The legacy footprint library remains useful for rendering, but its convex
hulls are not exact obstacle authority.  This adapter retains canonical source
clauses and exact pad/drill parameters, then derives orthogonally transformed
pad anchors without silently replacing unsupported custom geometry by a box.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.library import ImportedFootprint, load_footprint, rotate_offset, serialize_sexpr
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel, SemanticVerification


class FootprintGeometryRole(StrEnum):
    FAB_BODY = "fab_body"
    COURTYARD = "courtyard"
    RULE_AREA = "rule_area"
    KEEPOUT = "keepout"
    MATING_ENVELOPE = "mating_envelope"
    TOOL_ENVELOPE = "tool_envelope"


class InstalledFootprintTransform(SemanticIrModel):
    anchor_x_mm: float
    anchor_y_mm: float
    rotation_deg: Literal[0, 90, 180, 270]
    side: Literal["front", "back"]


class ExactPadGeometry(SemanticIrModel):
    pad_id: str
    pad_number: str
    source_clause_sha256: str
    shape: str
    kind: str
    layers: tuple[str, ...]
    local_x_mm: float
    local_y_mm: float
    local_rotation_deg: float
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    hole_shape: str | None
    hole_width_mm: float | None = Field(default=None, gt=0)
    hole_height_mm: float | None = Field(default=None, gt=0)
    hole_plating: str | None
    verification: SemanticVerification
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def pad_is_coherent(self) -> Self:
        require_identity(self.pad_id, "pad_id")
        require_sha256(self.source_clause_sha256, "source_clause_sha256")
        require_identity(self.shape, "shape")
        require_identity(self.kind, "kind")
        layers = tuple(sorted(self.layers))
        if len(layers) != len(set(layers)):
            raise ValueError("pad layers must be unique")
        for layer in layers:
            require_identity(layer, "layers")
        object.__setattr__(self, "layers", layers)
        hole_values = (self.hole_shape, self.hole_width_mm, self.hole_height_mm, self.hole_plating)
        if any(value is not None for value in hole_values) and not all(
            value is not None for value in hole_values
        ):
            raise ValueError("drill geometry must be complete or absent")
        if self.verification is SemanticVerification.UNSUPPORTED:
            if self.unsupported_reason is None:
                raise ValueError("unsupported pad geometry requires a reason")
        elif self.unsupported_reason is not None:
            raise ValueError("verified pad geometry cannot retain an unsupported reason")
        return self


class PlacedPadGeometry(SemanticIrModel):
    pad_id: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    side: Literal["front", "back"]
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    verification: SemanticVerification


class FootprintLayerGeometrySource(SemanticIrModel):
    role: FootprintGeometryRole
    source_layers: tuple[str, ...]
    canonical_clauses: tuple[str, ...]
    source_fingerprint: str
    verification: SemanticVerification
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def source_is_coherent(self) -> Self:
        layers = tuple(sorted(self.source_layers))
        object.__setattr__(self, "source_layers", layers)
        require_sha256(self.source_fingerprint, "source_fingerprint")
        expected = fingerprint(
            {"role": self.role.value, "layers": layers, "clauses": self.canonical_clauses}
        )
        if self.source_fingerprint != expected:
            raise ValueError("footprint layer geometry source fingerprint is stale")
        if self.verification is SemanticVerification.UNSUPPORTED:
            if self.unsupported_reason is None:
                raise ValueError("unsupported layer geometry requires a reason")
        elif self.unsupported_reason is not None:
            raise ValueError("verified layer geometry cannot retain an unsupported reason")
        return self


class InstalledFootprintGeometryAuthority(SemanticIrModel):
    schema_id: Literal["pcbsmith-installed-footprint-geometry-authority"] = (
        "pcbsmith-installed-footprint-geometry-authority"
    )
    schema_version: Literal[1] = 1
    installed_footprint_id: str
    component_reference: str
    component_uuid_path: str
    source_path: str
    source_file_sha256: str
    transform: InstalledFootprintTransform
    pads: tuple[ExactPadGeometry, ...] = Field(min_length=1)
    placed_pads: tuple[PlacedPadGeometry, ...] = Field(min_length=1)
    layer_geometry: tuple[FootprintLayerGeometrySource, ...]
    mating_envelope_fingerprint: str | None = None
    tool_envelope_fingerprint: str | None = None
    geometry_fingerprint: str

    @model_validator(mode="after")
    def authority_is_source_bound(self) -> Self:
        for name in ("installed_footprint_id", "component_reference", "component_uuid_path"):
            require_identity(getattr(self, name), name)
        require_identity(self.source_path, "source_path")
        require_sha256(self.source_file_sha256, "source_file_sha256")

        actual_source_sha = hashlib.sha256(Path(self.source_path).read_bytes()).hexdigest()
        if actual_source_sha != self.source_file_sha256:
            raise ValueError("installed footprint source hash is stale")
        pad_ids = tuple(item.pad_id for item in self.pads)
        placed_ids = tuple(item.pad_id for item in self.placed_pads)
        if len(pad_ids) != len(set(pad_ids)) or set(pad_ids) != set(placed_ids):
            raise ValueError("placed pad inventory differs from exact source pad inventory")
        for name in ("mating_envelope_fingerprint", "tool_envelope_fingerprint"):
            value = getattr(self, name)
            if value is not None:
                require_sha256(value, name)
        require_sha256(self.geometry_fingerprint, "geometry_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"geometry_fingerprint"}))
        if self.geometry_fingerprint != expected:
            raise ValueError("installed footprint geometry fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> InstalledFootprintGeometryAuthority:
        provisional = cls.model_construct(**values, geometry_fingerprint="0" * 64)
        return cls(
            **values,
            geometry_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"geometry_fingerprint"})
            ),
        )


def _head(node: object) -> str:
    if not isinstance(node, list) or not node:
        return ""
    value = node[0]
    return value.value if hasattr(value, "value") else str(value)


def _atom(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _children(node: Sequence[object], name: str) -> tuple[list[object], ...]:
    return tuple(child for child in node if isinstance(child, list) and _head(child) == name)


def _layer_names(node: Sequence[object]) -> tuple[str, ...]:
    layers = _children(node, "layer")
    if layers and len(layers[0]) >= 2:
        return (_atom(layers[0][1]),)
    layer_sets = _children(node, "layers")
    if layer_sets:
        return tuple(_atom(item) for item in layer_sets[0][1:] if not isinstance(item, list))
    return ()


def _source_clause_map(imported: ImportedFootprint) -> dict[str, list[str]]:
    by_number: dict[str, list[str]] = {}
    for child in imported.tree:
        if isinstance(child, list) and _head(child) == "pad" and len(child) > 1:
            by_number.setdefault(_atom(child[1]), []).append(serialize_sexpr(child))
    return by_number


def _layer_source(
    imported: ImportedFootprint,
    *,
    role: FootprintGeometryRole,
    layer_names: tuple[str, ...],
    heads: frozenset[str],
) -> FootprintLayerGeometrySource:
    clauses = tuple(
        serialize_sexpr(child)
        for child in imported.tree
        if isinstance(child, list)
        and _head(child) in heads
        and set(_layer_names(child)) & set(layer_names)
    )
    verification = SemanticVerification.EXACT if clauses else SemanticVerification.UNSUPPORTED
    reason = None if clauses else f"source contains no supported {role.value} clauses"
    return FootprintLayerGeometrySource(
        role=role,
        source_layers=layer_names,
        canonical_clauses=clauses,
        source_fingerprint=fingerprint(
            {"role": role.value, "layers": tuple(sorted(layer_names)), "clauses": clauses}
        ),
        verification=verification,
        unsupported_reason=reason,
    )


def build_installed_footprint_geometry_authority(
    footprint_id: str,
    *,
    component_reference: str,
    component_uuid_path: str,
    anchor_x_mm: float,
    anchor_y_mm: float,
    rotation_deg: Literal[0, 90, 180, 270] = 0,
    side: Literal["front", "back"] = "front",
    mating_envelope_fingerprint: str | None = None,
    tool_envelope_fingerprint: str | None = None,
) -> InstalledFootprintGeometryAuthority:
    imported = load_footprint(footprint_id)
    source_sha = hashlib.sha256(imported.source_file.read_bytes()).hexdigest()
    source_clauses = _source_clause_map(imported)
    occurrence: dict[str, int] = {}
    exact_pads: list[ExactPadGeometry] = []
    placed_pads: list[PlacedPadGeometry] = []
    for pad in imported.spec.pads:
        index = occurrence.get(pad.name, 0)
        occurrence[pad.name] = index + 1
        clauses = source_clauses.get(pad.name, [])
        if index >= len(clauses):
            raise ValueError(f"pad {pad.name!r} lacks a source clause")
        clause = clauses[index]
        pad_token = pad.name or "<unnumbered>"
        pad_id = f"{component_uuid_path}:pad:{pad_token}:{index}"
        unsupported = pad.custom_source.unsupported_reason if pad.custom_source else None
        verification = (
            SemanticVerification.UNSUPPORTED
            if unsupported is not None
            else SemanticVerification.EXACT
        )
        hole = pad.hole
        exact_pads.append(
            ExactPadGeometry(
                pad_id=pad_id,
                pad_number=pad.name,
                source_clause_sha256=hashlib.sha256(clause.encode("utf-8")).hexdigest(),
                shape=pad.shape or "unknown",
                kind=pad.kind,
                layers=pad.layers,
                local_x_mm=pad.x_mm,
                local_y_mm=pad.y_mm,
                local_rotation_deg=pad.angle_deg,
                width_mm=pad.width_mm,
                height_mm=pad.height_mm,
                hole_shape=None if hole is None else hole.shape.value,
                hole_width_mm=None if hole is None else hole.width_mm,
                hole_height_mm=None if hole is None else hole.height_mm,
                hole_plating=None if hole is None else hole.plating.value,
                verification=verification,
                unsupported_reason=unsupported,
            )
        )
        local_x = -pad.x_mm if side == "back" else pad.x_mm
        dx, dy = rotate_offset(local_x, pad.y_mm, rotation_deg)
        local_rotation = -pad.angle_deg if side == "back" else pad.angle_deg
        placed_pads.append(
            PlacedPadGeometry(
                pad_id=pad_id,
                x_mm=anchor_x_mm + dx,
                y_mm=anchor_y_mm + dy,
                rotation_deg=(rotation_deg + local_rotation) % 360,
                side=side,
                width_mm=pad.width_mm,
                height_mm=pad.height_mm,
                verification=verification,
            )
        )
    graphics = frozenset({"fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_curve"})
    layer_geometry: tuple[FootprintLayerGeometrySource, ...] = (
        _layer_source(
            imported,
            role=FootprintGeometryRole.FAB_BODY,
            layer_names=("F.Fab",),
            heads=graphics,
        ),
        _layer_source(
            imported,
            role=FootprintGeometryRole.COURTYARD,
            layer_names=("F.CrtYd",),
            heads=graphics,
        ),
    )
    rule_clauses = tuple(
        serialize_sexpr(child)
        for child in imported.tree
        if isinstance(child, list) and _head(child) == "zone"
    )
    if rule_clauses:
        layer_geometry += (
            FootprintLayerGeometrySource(
                role=FootprintGeometryRole.RULE_AREA,
                source_layers=("*.Cu",),
                canonical_clauses=rule_clauses,
                source_fingerprint=fingerprint(
                    {"role": "rule_area", "layers": ("*.Cu",), "clauses": rule_clauses}
                ),
                verification=SemanticVerification.EXACT,
            ),
        )
    values = {
        "installed_footprint_id": footprint_id,
        "component_reference": component_reference,
        "component_uuid_path": component_uuid_path,
        "source_path": str(imported.source_file.resolve()),
        "source_file_sha256": source_sha,
        "transform": InstalledFootprintTransform(
            anchor_x_mm=anchor_x_mm,
            anchor_y_mm=anchor_y_mm,
            rotation_deg=rotation_deg,
            side=side,
        ),
        "pads": tuple(exact_pads),
        "placed_pads": tuple(placed_pads),
        "layer_geometry": layer_geometry,
        "mating_envelope_fingerprint": mating_envelope_fingerprint,
        "tool_envelope_fingerprint": tool_envelope_fingerprint,
    }
    return InstalledFootprintGeometryAuthority.build(**values)


__all__ = [
    "ExactPadGeometry",
    "FootprintGeometryRole",
    "FootprintLayerGeometrySource",
    "InstalledFootprintGeometryAuthority",
    "InstalledFootprintTransform",
    "PlacedPadGeometry",
    "build_installed_footprint_geometry_authority",
]
