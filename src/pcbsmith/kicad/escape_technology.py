"""Fabrication/current-gated decisions for intrinsic fine-pitch escapes."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
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


class EscapeTechnologyKind(StrEnum):
    BASELINE_THROUGH_VIA = "baseline_through_via"
    LOCAL_NECK_DOWN = "local_neck_down"
    FINE_MECHANICAL_THROUGH_VIA = "fine_mechanical_through_via"
    FILLED_CAPPED_VIA_IN_PAD = "filled_capped_via_in_pad"
    MICROVIA = "microvia"
    ALTERNATE_FOOTPRINT_OR_PACKAGE = "alternate_footprint_or_package"


class EscapeTechnologyIntent(SemanticIrModel):
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    kind: EscapeTechnologyKind
    trace_width_mm: float | None = Field(default=None, gt=0)
    copper_clearance_mm: float | None = Field(default=None, gt=0)
    via_diameter_mm: float | None = Field(default=None, gt=0)
    via_drill_mm: float | None = Field(default=None, gt=0)
    supported_copper_layer_counts: tuple[int, ...] = Field(min_length=1)
    manufacturer_process_id: str | None = None
    fabrication_profile_fingerprint: str | None = None
    fabrication_evidence_sha256: tuple[str, ...] = ()
    current_path_record_fingerprint: str | None = None
    current_path_authority: Literal["verified", "unverified"] = "unverified"
    automatic_apply_authorized: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        layers = tuple(sorted(set(self.supported_copper_layer_counts)))
        if any(count < 1 for count in layers):
            raise ValueError("supported copper-layer counts must be positive")
        envelope = (
            self.trace_width_mm,
            self.copper_clearance_mm,
            self.via_diameter_mm,
            self.via_drill_mm,
        )
        geometry_kinds = {
            EscapeTechnologyKind.BASELINE_THROUGH_VIA,
            EscapeTechnologyKind.LOCAL_NECK_DOWN,
            EscapeTechnologyKind.FINE_MECHANICAL_THROUGH_VIA,
        }
        if self.kind in geometry_kinds and any(value is None for value in envelope):
            raise ValueError("routable escape technology requires a complete geometry envelope")
        if self.kind not in geometry_kinds and any(value is not None for value in envelope):
            raise ValueError("non-envelope technology cannot masquerade as a geometry trial")
        if self.via_diameter_mm is not None and self.via_drill_mm is not None:
            if self.via_diameter_mm <= self.via_drill_mm:
                raise ValueError("via diameter must exceed drill diameter")
        for digest in self.fabrication_evidence_sha256:
            _sha256(digest, "fabrication_evidence_sha256")
        if self.fabrication_profile_fingerprint is not None:
            _sha256(self.fabrication_profile_fingerprint, "fabrication_profile_fingerprint")
        if self.current_path_record_fingerprint is not None:
            _sha256(self.current_path_record_fingerprint, "current_path_record_fingerprint")
        object.__setattr__(self, "supported_copper_layer_counts", layers)
        object.__setattr__(
            self, "fabrication_evidence_sha256", tuple(sorted(self.fabrication_evidence_sha256))
        )
        return self


class EscapeGeometryTrial(SemanticIrModel):
    candidate_id: str
    source_board_sha256: str
    required_pad_ids: tuple[str, ...]
    legal_pad_ids: tuple[str, ...]
    blocked_pad_ids: tuple[str, ...]
    observation_sha256: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _sha256(self.source_board_sha256, "source_board_sha256")
        _sha256(self.observation_sha256, "observation_sha256")
        required = tuple(sorted(self.required_pad_ids))
        legal = tuple(sorted(self.legal_pad_ids))
        blocked = tuple(sorted(self.blocked_pad_ids))
        if set(legal) & set(blocked) or set(legal) | set(blocked) != set(required):
            raise ValueError("escape geometry pad accounting is inconsistent")
        object.__setattr__(self, "required_pad_ids", required)
        object.__setattr__(self, "legal_pad_ids", legal)
        object.__setattr__(self, "blocked_pad_ids", blocked)
        return self


class EscapeTechnologyCandidateDecision(SemanticIrModel):
    candidate_id: str
    kind: EscapeTechnologyKind
    geometry_trial: EscapeGeometryTrial | None
    qualified: bool
    blockers: tuple[str, ...]
    automatic_apply_authorized: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        blockers = tuple(sorted(set(self.blockers)))
        if self.qualified != (not blockers):
            raise ValueError("escape-technology candidate disposition is stale")
        object.__setattr__(self, "blockers", blockers)
        return self


class EscapeTechnologyDecision(SemanticIrModel):
    schema_id: Literal["pcbsmith-escape-technology-decision"] = (
        "pcbsmith-escape-technology-decision"
    )
    schema_version: Literal[1] = 1
    case_id: str
    source_board_sha256: str
    copper_layer_count: int = Field(ge=1)
    blocked_pad_ids: tuple[str, ...]
    candidates: tuple[EscapeTechnologyCandidateDecision, ...]
    qualified_candidate_ids: tuple[str, ...]
    disposition: Literal[
        "not_required",
        "qualified_candidate_available",
        "geometry_option_found_evidence_required",
        "no_geometric_option_observed",
    ]
    automatic_apply_authorized: Literal[False] = False
    decision_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _sha256(self.source_board_sha256, "source_board_sha256")
        blocked = tuple(sorted(self.blocked_pad_ids))
        candidates = tuple(sorted(self.candidates, key=lambda item: item.candidate_id))
        qualified = tuple(item.candidate_id for item in candidates if item.qualified)
        if self.qualified_candidate_ids != qualified:
            raise ValueError("qualified escape candidate identities are stale")
        if not blocked:
            expected = "not_required"
        elif qualified:
            expected = "qualified_candidate_available"
        elif any(
            item.geometry_trial and not item.geometry_trial.blocked_pad_ids for item in candidates
        ):
            expected = "geometry_option_found_evidence_required"
        else:
            expected = "no_geometric_option_observed"
        if self.disposition != expected:
            raise ValueError("escape-technology decision disposition is stale")
        payload = self.model_dump(mode="json", exclude={"decision_fingerprint"})
        if self.decision_fingerprint != _fingerprint(payload):
            raise ValueError("escape-technology decision fingerprint is stale")
        object.__setattr__(self, "blocked_pad_ids", blocked)
        object.__setattr__(self, "candidates", candidates)
        return self


def derive_escape_technology_decision(
    *,
    case_id: str,
    source_board_sha256: str,
    copper_layer_count: int,
    blocked_pad_ids: tuple[str, ...],
    intents: tuple[EscapeTechnologyIntent, ...],
    trials: tuple[EscapeGeometryTrial, ...],
) -> EscapeTechnologyDecision:
    """Combine geometry with explicit fabrication and current-path evidence."""

    _sha256(source_board_sha256, "source_board_sha256")
    if len({item.candidate_id for item in intents}) != len(intents):
        raise ValueError("escape-technology candidate identities must be unique")
    trial_by_id = {item.candidate_id: item for item in trials}
    if len(trial_by_id) != len(trials) or not set(trial_by_id).issubset(
        {item.candidate_id for item in intents}
    ):
        raise ValueError("escape geometry trials do not match the candidate policy")
    decisions: list[EscapeTechnologyCandidateDecision] = []
    for intent in intents:
        trial = trial_by_id.get(intent.candidate_id)
        blockers: list[str] = []
        if copper_layer_count not in intent.supported_copper_layer_counts:
            blockers.append("unsupported_on_declared_layer_count")
        if trial is None:
            blockers.append("geometry_unverified")
        elif trial.source_board_sha256 != source_board_sha256:
            blockers.append("geometry_trial_board_hash_mismatch")
        elif trial.blocked_pad_ids:
            blockers.append("blocked_pad_geometry")
        if intent.manufacturer_process_id is None:
            blockers.append("manufacturer_process_undeclared")
        if intent.fabrication_profile_fingerprint is None:
            blockers.append("fabrication_profile_unbound")
        if not intent.fabrication_evidence_sha256:
            blockers.append("fabrication_evidence_unpinned")
        if intent.current_path_authority != "verified":
            blockers.append("current_path_unverified")
        if intent.current_path_record_fingerprint is None:
            blockers.append("current_path_record_unbound")
        decisions.append(
            EscapeTechnologyCandidateDecision(
                candidate_id=intent.candidate_id,
                kind=intent.kind,
                geometry_trial=trial,
                qualified=not blockers,
                blockers=tuple(blockers),
            )
        )
    decisions.sort(key=lambda item: item.candidate_id)
    qualified = tuple(item.candidate_id for item in decisions if item.qualified)
    blocked = tuple(sorted(blocked_pad_ids))
    if not blocked:
        disposition = "not_required"
    elif qualified:
        disposition = "qualified_candidate_available"
    elif any(item.geometry_trial and not item.geometry_trial.blocked_pad_ids for item in decisions):
        disposition = "geometry_option_found_evidence_required"
    else:
        disposition = "no_geometric_option_observed"
    payload: dict[str, object] = {
        "schema_id": "pcbsmith-escape-technology-decision",
        "schema_version": 1,
        "case_id": case_id,
        "source_board_sha256": source_board_sha256,
        "copper_layer_count": copper_layer_count,
        "blocked_pad_ids": list(blocked),
        "candidates": [item.model_dump(mode="json") for item in decisions],
        "qualified_candidate_ids": list(qualified),
        "disposition": disposition,
        "automatic_apply_authorized": False,
    }
    payload["decision_fingerprint"] = _fingerprint(payload)
    return EscapeTechnologyDecision.model_validate(payload)
