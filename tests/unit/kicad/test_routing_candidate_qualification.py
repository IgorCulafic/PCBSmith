from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.board_failure_classifier import classify_board_failures
from pcbsmith.kicad.routing_candidate_qualification import (
    RoutingCandidateQualification,
    qualify_routed_candidate,
)


def _observation(identity_suffix: str = "a") -> dict[str, object]:
    return {
        "items": [],
        "pad_escape_audits": [],
        "board_identity": {
            "footprint_pose_fingerprint": identity_suffix * 64,
            "pad_binding_fingerprint": "b" * 64,
            "edge_geometry_fingerprint": "c" * 64,
            "footprint_count": 3,
            "pad_count": 8,
            "edge_item_count": 4,
        },
        "reference_continuity": {
            "disposition": "advisory_discontinuities_observed",
            "exact_pass_authorized": False,
            "automatic_multilayer_pass_prohibited": True,
            "signal_segment_count": 4,
            "findings": [{"kind": "sampled_reference_discontinuity"}],
        },
    }


def _classification(observation: dict[str, object]):
    return classify_board_failures(
        board_sha256="d" * 64,
        drc_sha256="e" * 64,
        drc_payload={"unconnected_items": [], "violations": []},
        observation=observation,
    )


def test_exact_parity_and_manual_burden_remain_distinct_from_release() -> None:
    observation = _observation()
    result = qualify_routed_candidate(
        case_id="RC01",
        placement_source_board_sha256="1" * 64,
        routed_source_board_sha256="2" * 64,
        routed_observed_board_sha256="d" * 64,
        baseline_observation=observation,
        routed_observation=observation,
        classification=_classification(observation),
        route_evidence={
            "routed_board_sha256": "2" * 64,
            "widths": {"report": {"nets": {"VIN": {"narrower_segment_count": 2}}}},
        },
        visual_evidence_status="present_unbound",
    )

    assert result.parity.mismatch_ids == ()
    assert result.manual_repair_burden.unresolved_work_item_count == 3
    assert not result.release_qualified
    assert result.blockers == (
        "reference_continuity_exact_unverified",
        "visual_evidence_not_revision_bound",
    )


def test_pose_parity_change_is_a_protected_identity_blocker() -> None:
    baseline = _observation("a")
    routed = _observation("f")
    result = qualify_routed_candidate(
        case_id="RC02",
        placement_source_board_sha256="1" * 64,
        routed_source_board_sha256="2" * 64,
        routed_observed_board_sha256="d" * 64,
        baseline_observation=baseline,
        routed_observation=routed,
        classification=_classification(routed),
        route_evidence={"routed_board_sha256": "2" * 64},
        visual_evidence_status="absent",
    )

    assert result.parity.mismatch_ids == ("footprint_pose",)
    assert "protected_board_identity_changed" in result.blockers


def test_qualification_fingerprint_tamper_fails_closed() -> None:
    observation = _observation()
    result = qualify_routed_candidate(
        case_id="RC03",
        placement_source_board_sha256="1" * 64,
        routed_source_board_sha256="2" * 64,
        routed_observed_board_sha256="d" * 64,
        baseline_observation=observation,
        routed_observation=observation,
        classification=_classification(observation),
        route_evidence={"routed_board_sha256": "2" * 64},
        visual_evidence_status="absent",
    )
    payload = deepcopy(result.model_dump(mode="json"))
    payload["release_qualified"] = True

    with pytest.raises(ValidationError, match="release qualification disposition is stale"):
        RoutingCandidateQualification.model_validate(payload)

def test_malformed_width_net_mapping_fails_closed() -> None:
    observation = _observation()

    with pytest.raises(TypeError, match="route width report nets must be a mapping"):
        qualify_routed_candidate(
            case_id="RC04",
            placement_source_board_sha256="1" * 64,
            routed_source_board_sha256="2" * 64,
            routed_observed_board_sha256="d" * 64,
            baseline_observation=observation,
            routed_observation=observation,
            classification=_classification(observation),
            route_evidence={
                "routed_board_sha256": "2" * 64,
                "widths": {"report": {"nets": []}},
            },
            visual_evidence_status="absent",
        )


def test_exact_reference_continuity_can_clear_legacy_blocker() -> None:
    observation = _observation()
    observation["reference_continuity"] = {
        "disposition": "exact_geometric_continuity_observed",
        "exact_pass_authorized": True,
        "automatic_multilayer_pass_prohibited": True,
        "signal_segment_count": 4,
        "findings": [],
    }
    result = qualify_routed_candidate(
        case_id="RC-exact-reference",
        placement_source_board_sha256="1" * 64,
        routed_source_board_sha256="2" * 64,
        routed_observed_board_sha256="d" * 64,
        baseline_observation=observation,
        routed_observation=observation,
        classification=_classification(observation),
        route_evidence={"routed_board_sha256": "2" * 64},
        visual_evidence_status="revision_bound",
    )
    assert result.reference_continuity_exact_pass_authorized
    assert "reference_continuity_exact_unverified" not in result.blockers
    assert result.release_qualified