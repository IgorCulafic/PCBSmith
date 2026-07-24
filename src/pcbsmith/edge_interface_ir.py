"""Replay-bound authority for components intentionally exposed at a board edge."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.connector_zone_ir import outline_edge_id
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    parse_canonical_board_layout_snapshot,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, PlacedCompoundTransform
from pcbsmith.semantic_ir import SemanticDisposition, SemanticIrModel, SemanticVerification


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _identity(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def _sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


class EdgeInterfaceKind(StrEnum):
    CONNECTOR = "connector"
    JACK = "jack"
    ACTUATED_SWITCH = "actuated_switch"
    SOCKET = "socket"
    USER_CONTROL = "user_control"


class EdgeInterfaceFindingKind(StrEnum):
    TRANSFORM_AUTHORITY = "transform_authority"
    RETAINED_MATERIAL = "retained_material"
    PAD_MATERIAL = "pad_material"
    SELECTED_EDGE = "selected_edge"
    OVERHANG_BOUNDS = "overhang_bounds"


class EdgeInterfaceLocalGeometry(SemanticIrModel):
    """Pinned footprint-local regions split by mechanical responsibility."""

    schema_id: Literal["pcbsmith-edge-interface-local-geometry"] = (
        "pcbsmith-edge-interface-local-geometry"
    )
    schema_version: Literal[1] = 1
    installed_footprint_id: str
    component_uuid_path: str
    source_file_sha256: str
    source_binding_id: str
    retained_support_compounds: tuple[ExactPlanarCompound, ...] = Field(min_length=1)
    pad_compounds: tuple[ExactPlanarCompound, ...] = Field(min_length=1)
    overhang_compound: ExactPlanarCompound
    geometry_fingerprint: str

    @model_validator(mode="after")
    def source_and_geometry_are_bound(self) -> Self:
        for name in ("installed_footprint_id", "component_uuid_path", "source_binding_id"):
            _identity(getattr(self, name), name)
        _sha256(self.source_file_sha256, "source_file_sha256")
        _sha256(self.geometry_fingerprint, "geometry_fingerprint")
        payload = self.model_dump(mode="json", exclude={"geometry_fingerprint"})
        if self.geometry_fingerprint != fingerprint(payload):
            raise ValueError("edge-interface geometry fingerprint is stale")
        return self


class EdgeInterfaceDeclaration(SemanticIrModel):
    """One selected-edge exception; ordinary component rules remain unchanged."""

    schema_id: Literal["pcbsmith-edge-interface-declaration"] = (
        "pcbsmith-edge-interface-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str
    reference: str
    interface_kind: EdgeInterfaceKind
    selected_outline_edge_id: str
    board_layout_snapshot_json: str
    board_layout_snapshot_fingerprint: str
    local_geometry: EdgeInterfaceLocalGeometry
    minimum_useful_overhang_mm: float = Field(ge=0)
    maximum_allowed_overhang_mm: float = Field(gt=0)
    minimum_retained_edge_clearance_mm: float = Field(ge=0)
    minimum_pad_edge_clearance_mm: float = Field(ge=0)
    exception_rule_id: str
    retained_rule_id: str
    pad_rule_id: str
    selected_edge_rule_id: str
    overhang_rule_id: str

    @field_validator("board_layout_snapshot_fingerprint")
    @classmethod
    def layout_fingerprint_is_sha256(cls, value: str) -> str:
        return _sha256(value, "board_layout_snapshot_fingerprint")

    @model_validator(mode="after")
    def context_and_thresholds_are_complete(self) -> Self:
        for name in (
            "declaration_id",
            "reference",
            "selected_outline_edge_id",
            "exception_rule_id",
            "retained_rule_id",
            "pad_rule_id",
            "selected_edge_rule_id",
            "overhang_rule_id",
        ):
            _identity(getattr(self, name), name)
        layout = parse_canonical_board_layout_snapshot(self.board_layout_snapshot_json)
        if (
            board_layout_snapshot_fingerprint(self.board_layout_snapshot_json)
            != self.board_layout_snapshot_fingerprint
        ):
            raise ValueError("edge-interface layout fingerprint is stale")
        components = {
            component.reference: component for component, _x_mm in layout.placements
        }
        component = components.get(self.reference)
        if component is None:
            raise ValueError("edge-interface reference is absent from the layout")
        if (
            component.footprint != self.local_geometry.installed_footprint_id
            or component.uuid_path != self.local_geometry.component_uuid_path
        ):
            raise ValueError("edge-interface geometry is bound to another component")
        points = layout.outline or (
            (0.0, 0.0),
            (layout.width_mm, 0.0),
            (layout.width_mm, layout.height_mm),
            (0.0, layout.height_mm),
        )
        edge_ids = {
            outline_edge_id(points[index], points[(index + 1) % len(points)])
            for index in range(len(points))
        }
        if self.selected_outline_edge_id not in edge_ids:
            raise ValueError("selected outline edge is absent from the layout")
        if self.minimum_useful_overhang_mm > self.maximum_allowed_overhang_mm:
            raise ValueError("minimum useful overhang cannot exceed maximum allowed overhang")
        return self


class EdgeInterfacePlacedGeometry(SemanticIrModel):
    schema_id: Literal["pcbsmith-edge-interface-placed-geometry"] = (
        "pcbsmith-edge-interface-placed-geometry"
    )
    schema_version: Literal[1] = 1
    retained_supports: tuple[PlacedCompoundTransform, ...] = Field(min_length=1)
    pads: tuple[PlacedCompoundTransform, ...] = Field(min_length=1)
    overhang: PlacedCompoundTransform


class EdgeInterfaceFinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-edge-interface-finding"] = "pcbsmith-edge-interface-finding"
    schema_version: Literal[1] = 1
    kind: EdgeInterfaceFindingKind
    rule_id: str
    verification: SemanticVerification
    disposition: SemanticDisposition
    selected_edge_id: str | None = None
    other_contact_edge_ids: tuple[str, ...] = ()
    measured_overhang_squared_numerator: int | None = Field(default=None, ge=0)
    measured_overhang_squared_denominator: int | None = Field(default=None, gt=0)
    message: str

    @model_validator(mode="after")
    def finding_is_canonical(self) -> Self:
        _identity(self.rule_id, "rule_id")
        _identity(self.message, "message")
        contacts = tuple(sorted(self.other_contact_edge_ids))
        if len(contacts) != len(set(contacts)):
            raise ValueError("other edge contacts must be unique")
        object.__setattr__(self, "other_contact_edge_ids", contacts)
        pair = (
            self.measured_overhang_squared_numerator,
            self.measured_overhang_squared_denominator,
        )
        if (pair[0] is None) != (pair[1] is None):
            raise ValueError("measured overhang numerator and denominator must appear together")
        return self


class EdgeInterfaceAuthorityResult(SemanticIrModel):
    """Replay-derived grant consumed by placement legalization."""

    schema_id: Literal["pcbsmith-edge-interface-authority-result"] = (
        "pcbsmith-edge-interface-authority-result"
    )
    schema_version: Literal[1] = 1
    declaration: EdgeInterfaceDeclaration
    placed_geometry: EdgeInterfacePlacedGeometry
    findings: tuple[EdgeInterfaceFinding, ...]
    approved: bool
    evidence_fingerprint: str
    result_fingerprint: str

    @field_validator("evidence_fingerprint", "result_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.edge_interface import rederive_edge_interface

        expected = rederive_edge_interface(self.declaration)
        for name in ("placed_geometry", "findings", "approved", "evidence_fingerprint"):
            if getattr(self, name) != expected[name]:
                raise ValueError("edge-interface evidence is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("edge-interface result fingerprint is stale")
        return self
