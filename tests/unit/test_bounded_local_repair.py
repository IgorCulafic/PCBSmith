from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.bounded_local_repair import (
    LocalRepairBudget,
    LocalRepairOutcome,
    LocalRepairRequest,
    LocalRepairResult,
    RepairFindingClass,
    RestartInvalidationReason,
)


def _request() -> LocalRepairRequest:
    return LocalRepairRequest.build(
        request_id="repair-open-u1",
        source_board_sha256="a" * 64,
        source_qualification_fingerprint="b" * 64,
        finding_class=RepairFindingClass.OPEN_ENDPOINT,
        target_finding_ids=("open:U1.4",),
        target_region_mm=(10.0, 10.0, 20.0, 20.0),
        affected_net_names=("SDA",),
        immutable_object_ids=("segment:VIN:1", "footprint:J1"),
        movable_component_references=("U1",),
        rip_authorized_copper_ids=("segment:SDA:3",),
        budget=LocalRepairBudget(
            maximum_displacement_mm=1.0,
            maximum_ripped_segment_count=2,
            maximum_ripped_via_count=1,
            maximum_added_segment_count=4,
            maximum_added_via_count=1,
            maximum_attempt_count=4,
            maximum_elapsed_seconds=15.0,
        ),
    )


def _result(**changes: object) -> LocalRepairResult:
    values: dict[str, object] = {
        "request": _request(),
        "candidate_board_sha256": "c" * 64,
        "outcome": LocalRepairOutcome.ACCEPTED,
        "attempts_used": 1,
        "elapsed_seconds": 2.0,
        "target_findings_removed": ("open:U1.4",),
        "new_finding_ids": (),
        "protected_region_fingerprints_before": {"accepted-power": "d" * 64},
        "protected_region_fingerprints_after": {"accepted-power": "d" * 64},
        "source_unresolved_burden": 2,
        "candidate_unresolved_burden": 1,
        "source_craft_cost": 5,
        "candidate_craft_cost": 4,
        "blocker_ids": (),
    }
    values.update(changes)
    return LocalRepairResult.build(**values)


def test_local_delta_can_publish_only_when_monotonic_and_protected_regions_match() -> None:
    result = _result()
    assert result.publish_authorized
    assert result.protected_region_fingerprints_before == result.protected_region_fingerprints_after


def test_regression_rolls_back_without_mutating_source_authority() -> None:
    result = _result(
        outcome=LocalRepairOutcome.REJECTED_REGRESSION,
        new_finding_ids=("clearance:new",),
        candidate_unresolved_burden=3,
        blocker_ids=("new_drc_finding",),
    )
    assert not result.publish_authorized
    assert result.request.source_board_sha256 == "a" * 64


def test_changed_unrelated_copper_prevents_publication() -> None:
    result = _result(
        outcome=LocalRepairOutcome.REJECTED_REGRESSION,
        protected_region_fingerprints_after={"accepted-power": "e" * 64},
        blocker_ids=("protected_region_changed",),
    )
    assert not result.publish_authorized


@pytest.mark.parametrize(
    "finding_class",
    tuple(RepairFindingClass),
)
def test_every_w8_failure_class_is_representable(finding_class: RepairFindingClass) -> None:
    assert (
        _request().model_copy(update={"finding_class": finding_class}).finding_class
        is finding_class
    )


def test_exhaustion_has_blockers_and_never_silently_restarts() -> None:
    result = _result(
        candidate_board_sha256=None,
        outcome=LocalRepairOutcome.EXHAUSTED,
        attempts_used=4,
        target_findings_removed=(),
        candidate_unresolved_burden=None,
        candidate_craft_cost=None,
        blocker_ids=("bounded_candidates_exhausted",),
    )
    assert not result.publish_authorized
    assert result.restart_invalidation_reason is None


def test_full_restart_requires_one_of_the_closed_typed_reasons() -> None:
    result = _result(
        candidate_board_sha256=None,
        outcome=LocalRepairOutcome.INVALIDATED,
        target_findings_removed=(),
        candidate_unresolved_burden=None,
        candidate_craft_cost=None,
        restart_invalidation_reason=RestartInvalidationReason.OUTLINE_CHANGED,
        blocker_ids=("outline_authority_changed",),
    )
    assert not result.publish_authorized
    assert result.restart_invalidation_reason is RestartInvalidationReason.OUTLINE_CHANGED

    payload = result.model_dump(mode="json")
    payload["restart_invalidation_reason"] = None
    with pytest.raises(ValidationError, match="full restart requires"):
        LocalRepairResult.model_validate(payload)
