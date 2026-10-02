"""Fail-closed propagation of one fabrication profile through the board loop."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.routed_copper_graph_ir import require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class FabricationProfilePropagation(SemanticIrModel):
    schema_id: Literal["pcbsmith-fabrication-profile-propagation"] = (
        "pcbsmith-fabrication-profile-propagation"
    )
    schema_version: Literal[1] = 1
    placement_profile_sha256: str
    routing_profile_sha256: str
    kicad_project_profile_sha256: str
    drc_profile_sha256: str
    current_analysis_profile_sha256: str
    manufacturing_profile_sha256: str

    @model_validator(mode="after")
    def one_profile_reaches_every_consumer(self) -> Self:
        fields = (
            "placement_profile_sha256",
            "routing_profile_sha256",
            "kicad_project_profile_sha256",
            "drc_profile_sha256",
            "current_analysis_profile_sha256",
            "manufacturing_profile_sha256",
        )
        values = tuple(require_sha256(getattr(self, name), name) for name in fields)
        if len(set(values)) != 1:
            raise ValueError("fabrication profile mismatch across physical-design consumers")
        return self

    @property
    def profile_sha256(self) -> str:
        return self.placement_profile_sha256


__all__ = ["FabricationProfilePropagation"]
