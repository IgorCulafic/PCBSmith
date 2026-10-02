from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.board_failure_classifier import (
    BoardFailureClassification,
    OpenFailureReason,
    TwoLayerFeasibility,
    classify_board_failures,
)
from pcbsmith.kicad.placement_escape_repair import derive_placement_escape_repair_plan


def _item(
    uuid: str,
    semantic: str,
    component: str,
    kind: str,
    layer: str,
) -> dict[str, object]:
    return {
        "uuid": uuid,
        "semantic_item_id": semantic,
        "connected_component_id": component,
        "kind": kind,
        "net_name": "GND",
        "layer": layer,
    }


def _member(uuid: str, description: str, x: float = 1.0) -> dict[str, object]:
    return {"uuid": uuid, "description": description, "pos": {"x": x, "y": 2.0}}


def _audit(
    pad_id: str,
    *,
    current: bool,
    any_rotation: bool,
) -> dict[str, object]:
    return {
        "pad_id": pad_id,
        "required": True,
        "current_legal_candidates": [{"x_mm": 1.0}] if current else [],
        "any_rotation_legal_candidates": [{"x_mm": 1.0}] if any_rotation else [],
    }


def test_every_drc_open_is_reconciled_with_components_and_exact_reason() -> None:
    observation = {
        "items": [
            _item("zone", "zone:gnd", "component:z", "zone", "B.Cu"),
            _item("pad", "pad:U1:1", "component:p", "pad", "F.Cu"),
            _item("track", "track:gnd", "component:t", "track", "B.Cu"),
        ],
        "pad_escape_audits": [_audit("U1.1", current=True, any_rotation=True)],
    }
    drc = {
        "unconnected_items": [
            {"items": [_member("zone", "Zone GND"), _member("zone", "Zone GND")]},
            {
                "items": [
                    _member("pad", "Pad 1 GND", 3.0),
                    _member("track", "Track GND", 4.0),
                ]
            },
        ],
        "violations": [{"type": "clearance", "severity": "error", "items": []}],
    }

    result = classify_board_failures(
        board_sha256="a" * 64,
        drc_sha256="b" * 64,
        drc_payload=drc,
        observation=observation,
    )

    assert result.reconciliation_complete
    assert result.reconciled_unconnected_count == 2
    assert result.opens[0].reason is OpenFailureReason.DISCONNECTED_FILLED_ZONE_ISLANDS
    assert len({item.connected_component_id for item in result.opens[0].endpoints}) == 2
    assert result.opens[1].reason is OpenFailureReason.MISSING_INTERLAYER_TRANSITION
    assert result.placement_gate_passed
    assert result.two_layer_feasibility is TwoLayerFeasibility.FEASIBLE_CURRENT_PLACEMENT


def test_unresolved_uuid_and_missing_escape_fail_closed() -> None:
    result = classify_board_failures(
        board_sha256="a" * 64,
        drc_sha256="b" * 64,
        drc_payload={
            "unconnected_items": [{"items": [_member("absent", "unknown")]}],
            "violations": [],
        },
        observation={
            "items": [],
            "pad_escape_audits": [_audit("U1.1", current=False, any_rotation=False)],
        },
    )

    assert not result.reconciliation_complete
    assert result.opens[0].reason is OpenFailureReason.UNRESOLVED_BOARD_ITEM
    assert not result.placement_gate_passed
    assert result.required_pads_without_current_escape == ("U1.1",)
    assert (
        result.two_layer_feasibility
        is TwoLayerFeasibility.PLACEMENT_TRANSLATION_SIZE_OR_LAYER_CHANGE_REQUIRED
    )


def test_rotation_alternative_is_distinct_from_current_pose_acceptance() -> None:
    result = classify_board_failures(
        board_sha256="a" * 64,
        drc_sha256="b" * 64,
        drc_payload={"unconnected_items": [], "violations": []},
        observation={
            "items": [],
            "pad_escape_audits": [_audit("C1.2", current=False, any_rotation=True)],
        },
    )

    assert result.reconciliation_complete
    assert not result.placement_gate_passed
    assert result.two_layer_feasibility is TwoLayerFeasibility.PLACEMENT_CHANGE_REQUIRED


def test_intrinsic_escape_failure_does_not_claim_more_board_or_layers() -> None:
    observation = {
        "items": [],
        "pad_escape_audits": [_audit("U1.1", current=False, any_rotation=False)],
        "placement_repair_search": {
            "performed": True,
            "source_pose_fingerprint": "c" * 64,
            "policy": {
                "translation_step_mm": 0.5,
                "maximum_translation_steps": 4,
                "allowed_rotation_deg": [0.0, 90.0, 180.0, 270.0],
                "neighbor_limit": 4,
                "proposal_limit": 64,
                "pair_move_limit": 0,
                "automatic_apply_authorized": False,
            },
            "root_cause": "intrinsic_footprint_escape",
            "base_required_pad_count": 1,
            "base_legal_pad_count": 0,
            "base_blocked_pads": ["U1.1"],
            "blocked_references": ["U1"],
            "neighbor_references_considered": ["C1"],
            "evaluated_proposal_count": 11,
            "geometry_rejected_proposal_count": 3,
            "improving_candidates": [],
            "terminal_reason": "no_improving_bounded_placement_candidate",
        },
    }
    plan = derive_placement_escape_repair_plan(
        source_board_sha256="a" * 64, observation=observation
    )

    result = classify_board_failures(
        board_sha256="a" * 64,
        drc_sha256="b" * 64,
        drc_payload={"unconnected_items": [], "violations": []},
        observation=observation,
        repair_plan=plan,
    )

    assert result.two_layer_feasibility is (
        TwoLayerFeasibility.ESCAPE_TECHNOLOGY_OR_FOOTPRINT_CHANGE_REQUIRED
    )
    assert result.bounded_repair_evaluated_proposal_count == 11
    assert result.bounded_repair_candidate_count == 0


def test_classification_rejects_tampered_gate_and_fingerprint() -> None:
    result = classify_board_failures(
        board_sha256="a" * 64,
        drc_sha256="b" * 64,
        drc_payload={"unconnected_items": [], "violations": []},
        observation={
            "items": [],
            "pad_escape_audits": [_audit("C1.2", current=True, any_rotation=True)],
        },
    )
    payload = result.model_dump(mode="json")
    assert BoardFailureClassification.model_validate(deepcopy(payload)) == result
    payload["placement_gate_passed"] = False
    with pytest.raises(ValidationError, match="placement gate disposition is stale"):
        BoardFailureClassification.model_validate(payload)
