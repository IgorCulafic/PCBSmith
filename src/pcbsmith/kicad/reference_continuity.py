"""Typed, fail-closed reference-continuity geometry evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.semantic_ir import SemanticIrModel


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _sha256(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


class ReferenceContinuityEvidence(SemanticIrModel):
    """Exact within a deliberately narrow geometric model.

    The model proves complete centerline coverage of straight signal segments by
    the union of filled reference-net zone contours on the opposite copper layer.
    It does not prove conductor-width support, impedance, return-current density,
    EMC, signal integrity, or thermal adequacy.
    """

    schema_id: Literal["pcbsmith-reference-continuity-evidence"] = (
        "pcbsmith-reference-continuity-evidence"
    )
    schema_version: Literal[1] = 1
    authority: Literal["exact-straight-centerline-geometric-v1"]
    reference_net_names: tuple[str, ...]
    copper_layer_count: int = Field(ge=1)
    signal_segment_count: int = Field(ge=0)
    exact_supported_segment_count: int = Field(ge=0)
    exact_unsupported_segment_count: int = Field(ge=0)
    unsupported_geometry_segment_count: int = Field(ge=0)
    signal_transition_count: int = Field(ge=0)
    transition_without_nearby_reference_via_count: int = Field(ge=0)
    maximum_transition_stitch_distance_mm: float = Field(gt=0)
    exact_pass_authorized: bool
    automatic_multilayer_pass_prohibited: Literal[True] = True
    disposition: Literal[
        "exact_geometric_continuity_observed",
        "exact_geometric_discontinuities_observed",
        "unsupported_stackup_unverified",
        "reference_net_undeclared_unverified",
        "unsupported_track_geometry_unverified",
    ]
    findings: tuple[dict[str, object], ...]
    scope: str
    evidence_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _sha256(self.evidence_fingerprint, "evidence_fingerprint")
        references = tuple(sorted(self.reference_net_names))
        if len(references) != len(set(references)):
            raise ValueError("reference-net identities must be unique")
        if (
            self.exact_supported_segment_count
            + self.exact_unsupported_segment_count
            + self.unsupported_geometry_segment_count
            != self.signal_segment_count
        ):
            raise ValueError("reference-continuity segment accounting is inconsistent")
        expected_pass = (
            self.copper_layer_count == 2
            and bool(references)
            and self.unsupported_geometry_segment_count == 0
            and self.exact_unsupported_segment_count == 0
            and self.transition_without_nearby_reference_via_count == 0
        )
        if self.exact_pass_authorized != expected_pass:
            raise ValueError("exact reference-continuity disposition is stale")
        if expected_pass and self.disposition != "exact_geometric_continuity_observed":
            raise ValueError("exact pass requires the exact continuity disposition")
        if not expected_pass and self.disposition == "exact_geometric_continuity_observed":
            raise ValueError("exact continuity disposition cannot hide blockers")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != _fingerprint(payload):
            raise ValueError("reference-continuity evidence fingerprint is stale")
        object.__setattr__(self, "reference_net_names", references)
        return self


def parse_reference_continuity(
    observation: dict[str, object],
) -> ReferenceContinuityEvidence:
    raw = observation.get("reference_continuity")
    if not isinstance(raw, dict):
        raise TypeError("physical observation lacks reference_continuity")
    return ReferenceContinuityEvidence.model_validate(raw)
