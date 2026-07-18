"""Firing tests for replay-bound generated bus transition authority."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_integration as fixtures
from tests.unit.kicad import test_bus_transition as transition_tests

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    BusSwapEvent,
    bus_lane_allocation_fingerprint,
)
from pcbsmith.kicad.bus_transition import BusTransitionBudget, BusTransitionFailureReason
from pcbsmith.kicad.bus_transition_replay import (
    BusTransitionReplayInput,
    BusTransitionReplayResult,
    generate_replay_bound_bus_transition_vias,
)
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)


def _success(claims: tuple[NetResourceClaims, ...] = ()) -> BusTransitionReplayResult:
    fixture, _manual = fixtures._transition_fixture()
    return generate_replay_bound_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        OccupancyLedger(claims),
        BusTransitionBudget(max_members=1, max_events=1),
    )


def test_real_carrier_roundtrip_repeat_and_caller_isolation() -> None:
    fixture, _manual = fixtures._transition_fixture()
    claim = NetResourceClaims(
        "foreign",
        frozenset({RoutingResourceKey("ordinary", "F.Cu", "cell", 29, 29)}),
    )
    ledger = OccupancyLedger((claim,))
    before = ledger.semantic_fingerprint()

    first = generate_replay_bound_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        ledger,
        BusTransitionBudget(max_members=1, max_events=1),
    )
    second = generate_replay_bound_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        OccupancyLedger((claim,)),
        BusTransitionBudget(max_members=1, max_events=1),
    )

    assert first.generation_result.success
    assert len(first.generation_result.carriers) == 1
    assert first == second
    assert BusTransitionReplayResult.model_validate_json(first.model_dump_json()) == first
    assert ledger.semantic_fingerprint() == before
    assert ledger.committed_claims() == (claim,)


def test_claim_and_resource_construction_order_is_set_like() -> None:
    resources = (
        RoutingResourceKey("ordinary", "B.Cu", "cell", 3, 4),
        RoutingResourceKey("ordinary", "F.Cu", "edge", 1, 1, 2, 1),
    )
    a = NetResourceClaims("a", frozenset(resources))
    z = NetResourceClaims("z", frozenset(reversed(resources)))

    forward = _success((a, z))
    reverse = _success((z, a))

    assert forward.semantic_json() == reverse.semantic_json()
    assert tuple(item.net_name for item in forward.replay_input.initial_claims) == ("a", "z")
    with pytest.raises(ValidationError, match="duplicate net claim identities"):
        BusTransitionReplayInput(
            bus=forward.replay_input.bus,
            certificate=forward.replay_input.certificate,
            allocation=forward.replay_input.allocation,
            geometry_registry=forward.replay_input.geometry_registry,
            profile=forward.replay_input.profile,
            budget=forward.replay_input.budget,
            initial_claims=(a, a),
        )


@pytest.mark.parametrize(
    ("budget", "reason"),
    (
        (
            BusTransitionBudget(max_members=0, max_events=1),
            BusTransitionFailureReason.MEMBER_BUDGET,
        ),
        (BusTransitionBudget(max_members=1, max_events=0), BusTransitionFailureReason.EVENT_BUDGET),
    ),
)
def test_zero_and_one_less_budgets_are_replay_bound(
    budget: BusTransitionBudget, reason: BusTransitionFailureReason
) -> None:
    fixture, _manual = fixtures._transition_fixture()
    result = generate_replay_bound_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        OccupancyLedger(),
        budget,
    )
    assert not result.generation_result.success
    assert result.generation_result.failure_reason is reason
    assert result.generation_result.event_work_count == 0


def test_swap_containing_allocation_remains_fail_closed() -> None:
    fixture, _manual = fixtures._transition_fixture()
    swap = BusSwapEvent(
        section_id="front",
        exit_boundary_id="middle",
        window_id="swap:undeclared",
        sequence_index=0,
        order_index=0,
        first_member_id="data0",
        second_member_id="foreign",
        layer="F.Cu",
    )
    allocation_payload = fixture.allocation.model_dump()
    allocation_payload.update(
        swap_count=1,
        swaps=(swap,),
        allocation_fingerprint=bus_lane_allocation_fingerprint(
            bus_fingerprint=fixture.allocation.bus_fingerprint,
            certificate_fingerprint=fixture.allocation.certificate_fingerprint,
            normalized_boundary_orders=fixture.allocation.normalized_boundary_orders,
            assignments=fixture.allocation.assignments,
            activations=fixture.allocation.activations,
            swaps=(swap,),
            layer_transitions=fixture.allocation.layer_transitions,
            via_counts=fixture.allocation.via_counts,
            permutation_boundary_ids=fixture.allocation.permutation_boundary_ids,
        ),
    )
    allocation = BusLaneAllocationResult.model_validate(allocation_payload)
    registry = transition_tests._rebind_registry(fixture.registry, allocation)

    result = generate_replay_bound_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        allocation,
        registry,
        OccupancyLedger(),
        BusTransitionBudget(max_members=1, max_events=1),
    )
    assert result.generation_result.failure_reason is (
        BusTransitionFailureReason.SWAP_GEOMETRY_UNSUPPORTED
    )
    assert result.generation_result.event_work_count == 0


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("replay_input", "bus", "bus_id"), "stale-bus"),
        (("replay_input", "certificate", "certificate_id"), "stale-certificate"),
        (("replay_input", "geometry_registry", "grid_mm"), 2.0),
        (("replay_input", "profile", "profile_id"), "stale-profile"),
        (("replay_input", "budget", "max_events"), 0),
        (("generation_result", "carriers", 0, "point"), [4, 2]),
    ),
)
def test_stale_authority_and_result_tamper_are_rejected(
    path: tuple[str | int, ...], value: object
) -> None:
    payload = json.loads(_success().model_dump_json())
    target: object = payload
    for item in path[:-1]:
        target = target[item]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        BusTransitionReplayResult.model_validate(payload)


def test_claim_tamper_is_rejected_by_replay_binding() -> None:
    payload = json.loads(_success().model_dump_json())
    payload["replay_input"]["initial_claims"] = [
        {
            "net_name": "late",
            "resources": [
                {
                    "domain_id": "ordinary",
                    "layer": "F.Cu",
                    "kind": "cell",
                    "ix0": 1,
                    "iy0": 1,
                    "ix1": 0,
                    "iy1": 0,
                }
            ],
        }
    ]
    with pytest.raises(ValidationError, match="exact replay|occupancy snapshot"):
        BusTransitionReplayResult.model_validate(payload)
