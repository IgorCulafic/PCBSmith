from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.placement_escape_repair import (
    EscapeRepairRootCause,
    EscapeRepairTerminalReason,
    PlacementEscapeRepairPlan,
    derive_placement_escape_repair_plan,
)


def _fp(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _policy() -> dict[str, object]:
    return {
        "translation_step_mm": 0.5,
        "maximum_translation_steps": 4,
        "allowed_rotation_deg": [0.0, 90.0, 180.0, 270.0],
        "neighbor_limit": 4,
        "proposal_limit": 64,
        "pair_move_limit": 0,
        "automatic_apply_authorized": False,
    }


def test_no_improving_intrinsic_search_is_typed_without_layer_claim() -> None:
    observation = {
        "placement_repair_search": {
            "performed": True,
            "source_pose_fingerprint": "a" * 64,
            "policy": _policy(),
            "root_cause": "intrinsic_footprint_escape",
            "base_required_pad_count": 6,
            "base_legal_pad_count": 4,
            "base_blocked_pads": ["U1.17", "U1.1"],
            "blocked_references": ["U1"],
            "neighbor_references_considered": ["R1", "C1"],
            "evaluated_proposal_count": 51,
            "geometry_rejected_proposal_count": 14,
            "improving_candidates": [],
            "terminal_reason": "no_improving_bounded_placement_candidate",
        }
    }

    plan = derive_placement_escape_repair_plan(
        source_board_sha256="b" * 64, observation=observation
    )

    assert plan.root_cause is EscapeRepairRootCause.INTRINSIC_FOOTPRINT_ESCAPE
    assert plan.terminal_reason is (
        EscapeRepairTerminalReason.NO_IMPROVING_BOUNDED_PLACEMENT_CANDIDATE
    )
    assert plan.base_blocked_pads == ("U1.1", "U1.17")
    assert plan.preferred_candidate_id is None
    assert plan.policy is not None and plan.policy.automatic_apply_authorized is False


def test_improving_candidate_binds_clause_and_pad_sets() -> None:
    source_pose = "c" * 64
    clause = {
        "reference": "C1",
        "kind": "translate",
        "delta_x_mm": 1.0,
        "delta_y_mm": 0.0,
    }
    candidate_payload = {
        "source_pose_fingerprint": source_pose,
        "clause": clause,
        "legal_required_pads": ["U1.1", "U1.17"],
        "blocked_required_pads": [],
    }
    fingerprint = _fp(candidate_payload)
    observation = {
        "placement_repair_search": {
            "performed": True,
            "source_pose_fingerprint": source_pose,
            "policy": _policy(),
            "root_cause": "neighbor_placement",
            "base_required_pad_count": 2,
            "base_legal_pad_count": 1,
            "base_blocked_pads": ["U1.17"],
            "blocked_references": ["U1"],
            "neighbor_references_considered": ["C1"],
            "evaluated_proposal_count": 4,
            "geometry_rejected_proposal_count": 1,
            "improving_candidates": [
                {
                    "candidate_id": fingerprint[:12],
                    "candidate_fingerprint": fingerprint,
                    "clause": clause,
                    "legal_required_pads": ["U1.1", "U1.17"],
                    "blocked_required_pads": [],
                    "legal_gain": 1,
                    "unchanged_reference_count": 8,
                }
            ],
            "terminal_reason": "improving_candidate_found",
        }
    }

    plan = derive_placement_escape_repair_plan(
        source_board_sha256="d" * 64, observation=observation
    )

    candidate = plan.candidates[0]
    assert plan.preferred_candidate_id == fingerprint[:12]
    assert candidate.provenance.moved_references == ("C1",)
    assert candidate.legal_required_pads == ("U1.1", "U1.17")
    assert candidate.automatic_apply_authorized is False


def test_candidate_fingerprint_tamper_fails_closed() -> None:
    source_pose = "e" * 64
    clause = {
        "reference": "R1",
        "kind": "translate",
        "delta_x_mm": 0.5,
        "delta_y_mm": 0.0,
    }
    candidate_payload = {
        "source_pose_fingerprint": source_pose,
        "clause": clause,
        "legal_required_pads": ["U1.1"],
        "blocked_required_pads": [],
    }
    fingerprint = _fp(candidate_payload)
    observation = {
        "placement_repair_search": {
            "performed": True,
            "source_pose_fingerprint": source_pose,
            "policy": _policy(),
            "root_cause": "neighbor_placement",
            "base_required_pad_count": 1,
            "base_legal_pad_count": 0,
            "base_blocked_pads": ["U1.1"],
            "evaluated_proposal_count": 1,
            "geometry_rejected_proposal_count": 0,
            "improving_candidates": [
                {
                    "candidate_id": fingerprint[:12],
                    "candidate_fingerprint": fingerprint,
                    "clause": clause,
                    "legal_required_pads": ["U1.1"],
                    "blocked_required_pads": ["tampered"],
                    "legal_gain": 1,
                    "unchanged_reference_count": 2,
                }
            ],
            "terminal_reason": "improving_candidate_found",
        }
    }

    with pytest.raises(ValidationError, match="candidate fingerprint is stale"):
        derive_placement_escape_repair_plan(source_board_sha256="f" * 64, observation=observation)


def test_plan_fingerprint_tamper_fails_closed() -> None:
    observation = {
        "placement_repair_search": {
            "performed": False,
            "terminal_reason": "placement_audit_skipped",
            "improving_candidates": [],
        }
    }
    plan = derive_placement_escape_repair_plan(
        source_board_sha256="1" * 64, observation=observation
    )
    payload = plan.model_dump(mode="json")
    payload["evaluated_proposal_count"] = 1

    with pytest.raises(ValidationError, match="repair plan fingerprint is stale"):
        PlacementEscapeRepairPlan.model_validate(payload)
