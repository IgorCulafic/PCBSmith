"""Typed evidence for bounded placement repair after pad-escape rejection."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.placement_candidate_ir import (
    PlacementMoveClause,
    PlacementProposalKind,
    PlacementProposalProvenance,
)
from pcbsmith.semantic_ir import SemanticIrModel


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


class EscapeRepairRootCause(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    INTRINSIC_FOOTPRINT_ESCAPE = "intrinsic_footprint_escape"
    NEIGHBOR_PLACEMENT = "neighbor_placement"
    BOARD_EDGE = "board_edge"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class EscapeRepairTerminalReason(StrEnum):
    NOT_REQUIRED = "not_required"
    IMPROVING_CANDIDATE_FOUND = "improving_candidate_found"
    NO_IMPROVING_BOUNDED_PLACEMENT_CANDIDATE = "no_improving_bounded_placement_candidate"
    PLACEMENT_AUDIT_SKIPPED = "placement_audit_skipped"


class PlacementEscapeRepairPolicy(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-escape-repair-policy"] = (
        "pcbsmith-placement-escape-repair-policy"
    )
    schema_version: Literal[1] = 1
    translation_step_mm: float = Field(gt=0)
    maximum_translation_steps: int = Field(ge=0)
    allowed_rotation_deg: tuple[float, ...]
    neighbor_limit: int = Field(ge=0)
    proposal_limit: int = Field(ge=0)
    pair_move_limit: int = Field(ge=0)
    automatic_apply_authorized: Literal[False] = False


class PlacementEscapeRepairCandidate(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-escape-repair-candidate"] = (
        "pcbsmith-placement-escape-repair-candidate"
    )
    schema_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    candidate_fingerprint: str
    source_pose_fingerprint: str
    provenance: PlacementProposalProvenance
    legal_required_pads: tuple[str, ...]
    blocked_required_pads: tuple[str, ...]
    legal_gain: int = Field(gt=0)
    unchanged_reference_count: int = Field(ge=0)
    automatic_apply_authorized: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        fingerprint = _sha256(self.candidate_fingerprint, "candidate_fingerprint")
        _sha256(self.source_pose_fingerprint, "source_pose_fingerprint")
        if self.candidate_id != fingerprint[:12]:
            raise ValueError("candidate id is stale")
        if self.provenance.proposal_kind is not PlacementProposalKind.SINGLE:
            raise ValueError("bounded escape repair currently retains single moves only")
        if len(self.provenance.clauses) != 1:
            raise ValueError("bounded escape repair requires exactly one move clause")
        legal = tuple(sorted(self.legal_required_pads))
        blocked = tuple(sorted(self.blocked_required_pads))
        if set(legal) & set(blocked):
            raise ValueError("a required pad cannot be both legal and blocked")
        clause = self.provenance.clauses[0].model_dump(
            mode="json", exclude_none=True, exclude={"schema_id", "schema_version"}
        )
        payload = {
            "source_pose_fingerprint": self.source_pose_fingerprint,
            "clause": clause,
            "legal_required_pads": list(legal),
            "blocked_required_pads": list(blocked),
        }
        if fingerprint != _fingerprint(payload):
            raise ValueError("candidate fingerprint is stale")
        object.__setattr__(self, "legal_required_pads", legal)
        object.__setattr__(self, "blocked_required_pads", blocked)
        return self


class PlacementEscapeRepairPlan(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-escape-repair-plan"] = (
        "pcbsmith-placement-escape-repair-plan"
    )
    schema_version: Literal[1] = 1
    source_board_sha256: str
    source_pose_fingerprint: str | None = None
    performed: bool
    policy: PlacementEscapeRepairPolicy | None = None
    root_cause: EscapeRepairRootCause
    base_required_pad_count: int = Field(ge=0)
    base_legal_pad_count: int = Field(ge=0)
    base_blocked_pads: tuple[str, ...]
    blocked_references: tuple[str, ...] = ()
    neighbor_references_considered: tuple[str, ...] = ()
    evaluated_proposal_count: int = Field(ge=0)
    geometry_rejected_proposal_count: int = Field(ge=0)
    candidates: tuple[PlacementEscapeRepairCandidate, ...]
    preferred_candidate_id: str | None = None
    terminal_reason: EscapeRepairTerminalReason
    plan_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _sha256(self.source_board_sha256, "source_board_sha256")
        if self.source_pose_fingerprint is not None:
            _sha256(self.source_pose_fingerprint, "source_pose_fingerprint")
        blocked = tuple(sorted(self.base_blocked_pads))
        candidates = tuple(
            sorted(
                self.candidates,
                key=lambda item: (
                    -item.legal_gain,
                    len(item.blocked_required_pads),
                    item.candidate_fingerprint,
                ),
            )
        )
        if self.base_legal_pad_count + len(blocked) != self.base_required_pad_count:
            raise ValueError("base required-pad accounting is inconsistent")
        if self.geometry_rejected_proposal_count > self.evaluated_proposal_count:
            raise ValueError("geometry rejection count exceeds evaluated proposals")
        expected_preferred = candidates[0].candidate_id if candidates else None
        if self.preferred_candidate_id != expected_preferred:
            raise ValueError("preferred candidate is not the deterministic best candidate")
        if self.terminal_reason is EscapeRepairTerminalReason.IMPROVING_CANDIDATE_FOUND:
            if not candidates:
                raise ValueError("improving terminal reason requires a candidate")
        elif candidates:
            raise ValueError("non-improving terminal reason cannot retain candidates")
        if self.performed and self.policy is None:
            raise ValueError("performed repair search requires policy evidence")
        if (
            not self.performed
            and self.terminal_reason is not EscapeRepairTerminalReason.PLACEMENT_AUDIT_SKIPPED
        ):
            raise ValueError("unperformed repair search must be explicitly skipped")
        payload = self.model_dump(mode="json", exclude={"plan_fingerprint"})
        if self.plan_fingerprint != _fingerprint(payload):
            raise ValueError("repair plan fingerprint is stale")
        object.__setattr__(self, "base_blocked_pads", blocked)
        object.__setattr__(self, "candidates", candidates)
        return self


def derive_placement_escape_repair_plan(
    *, source_board_sha256: str, observation: dict[str, object]
) -> PlacementEscapeRepairPlan:
    """Validate and bind one pcbnew bounded-search observation."""

    _sha256(source_board_sha256, "source_board_sha256")
    raw = observation.get("placement_repair_search", {})
    if not isinstance(raw, dict):
        raise TypeError("placement_repair_search must be an object")
    performed = raw.get("performed") is True
    source_pose = str(raw["source_pose_fingerprint"]) if performed else None
    policy = PlacementEscapeRepairPolicy.model_validate(raw["policy"]) if performed else None
    raw_candidates = raw.get("improving_candidates", [])
    if not isinstance(raw_candidates, list):
        raise TypeError("improving_candidates must be a list")
    candidates: list[PlacementEscapeRepairCandidate] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict) or not isinstance(raw_candidate.get("clause"), dict):
            raise TypeError("repair candidate must contain one move clause")
        clause = PlacementMoveClause.model_validate(raw_candidate["clause"])
        provenance = PlacementProposalProvenance(
            proposal_kind=PlacementProposalKind.SINGLE,
            parent_pose_fingerprint=source_pose,
            moved_references=(clause.reference,),
            clauses=(clause,),
        )
        candidates.append(
            PlacementEscapeRepairCandidate(
                candidate_id=str(raw_candidate["candidate_id"]),
                candidate_fingerprint=str(raw_candidate["candidate_fingerprint"]),
                source_pose_fingerprint=source_pose,
                provenance=provenance,
                legal_required_pads=tuple(raw_candidate.get("legal_required_pads", ())),
                blocked_required_pads=tuple(raw_candidate.get("blocked_required_pads", ())),
                legal_gain=int(raw_candidate["legal_gain"]),
                unchanged_reference_count=int(raw_candidate["unchanged_reference_count"]),
            )
        )
    candidates.sort(
        key=lambda item: (
            -item.legal_gain,
            len(item.blocked_required_pads),
            item.candidate_fingerprint,
        )
    )
    payload: dict[str, object] = {
        "schema_id": "pcbsmith-placement-escape-repair-plan",
        "schema_version": 1,
        "source_board_sha256": source_board_sha256,
        "source_pose_fingerprint": source_pose,
        "performed": performed,
        "policy": policy.model_dump(mode="json") if policy else None,
        "root_cause": str(raw.get("root_cause", "unknown" if performed else "unknown")),
        "base_required_pad_count": int(raw.get("base_required_pad_count", 0)),
        "base_legal_pad_count": int(raw.get("base_legal_pad_count", 0)),
        "base_blocked_pads": sorted(str(item) for item in raw.get("base_blocked_pads", [])),
        "blocked_references": sorted(str(item) for item in raw.get("blocked_references", [])),
        "neighbor_references_considered": sorted(
            str(item) for item in raw.get("neighbor_references_considered", [])
        ),
        "evaluated_proposal_count": int(raw.get("evaluated_proposal_count", 0)),
        "geometry_rejected_proposal_count": int(raw.get("geometry_rejected_proposal_count", 0)),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "preferred_candidate_id": candidates[0].candidate_id if candidates else None,
        "terminal_reason": str(raw.get("terminal_reason", "placement_audit_skipped")),
    }
    payload["plan_fingerprint"] = _fingerprint(payload)
    return PlacementEscapeRepairPlan.model_validate(payload)
