"""Tests for the opt-in replay-bound bus candidate transaction bridge."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_escape_replay as replay_fixtures
from tests.unit.kicad import test_bus_transaction as transaction_fixtures

from pcbsmith.kicad.bus_candidate_transaction import (
    ReplayBoundBusRouteBundle,
    ReplayBoundBusTransactionResult,
    commit_replay_bound_bus_candidate,
)
from pcbsmith.kicad.bus_escape import BusEscapeBudget
from pcbsmith.kicad.bus_escape_replay import BusEscapeReplayResult
from pcbsmith.kicad.bus_transaction import (
    BusRouteBundle,
    BusRouteStateSnapshot,
    BusRouteTransactionCoordinator,
    BusRouteTransactionTelemetry,
    BusTransactionDisposition,
)
from pcbsmith.kicad.negotiated_resources import OccupancyLedger


def _authority() -> ReplayBoundBusRouteBundle:
    replay = replay_fixtures._generate()
    assert replay.generation_result.success
    assert replay.generation_result.candidate is not None
    assert replay.generation_result.candidate.bundle is not None
    return ReplayBoundBusRouteBundle(
        escape_replay=replay,
        bundle=replay.generation_result.candidate.bundle,
    )


def _coordinator(
    authority: ReplayBoundBusRouteBundle,
    *,
    include_foreign: bool = False,
) -> tuple[BusRouteTransactionCoordinator, object | None]:
    routes = {
        member.net_name: transaction_fixtures._route(member.net_name, 90 + index)
        for index, member in enumerate(authority.bundle.bus.members)
    }
    foreign = None
    if include_foreign:
        foreign = transaction_fixtures._route("/FOREIGN", 80)
        routes["/FOREIGN"] = foreign
    ledger = OccupancyLedger(route.claims for route in routes.values())
    return BusRouteTransactionCoordinator(ledger, routes), foreign


def test_successful_real_escape_bundle_commits_and_roundtrips_completely() -> None:
    authority = _authority()
    coordinator, _foreign = _coordinator(authority)

    result = commit_replay_bound_bus_candidate(
        coordinator,
        authority.bundle.bus,
        authority.bundle.allocation,
        authority,
    )

    assert result.telemetry.disposition is BusTransactionDisposition.COMMITTED
    assert coordinator.routes_by_net == authority.bundle.by_net()
    assert ReplayBoundBusRouteBundle.model_validate_json(authority.model_dump_json()) == authority
    assert ReplayBoundBusTransactionResult.model_validate_json(result.model_dump_json()) == result


def test_commit_preserves_foreign_route_and_claim_exactly() -> None:
    authority = _authority()
    coordinator, foreign = _coordinator(authority, include_foreign=True)
    assert foreign is not None
    foreign_claims = coordinator.ledger.claims_for("/FOREIGN")

    result = commit_replay_bound_bus_candidate(
        coordinator,
        authority.bundle.bus,
        authority.bundle.allocation,
        authority,
    )

    assert coordinator.routes_by_net["/FOREIGN"] == foreign
    assert coordinator.ledger.claims_for("/FOREIGN") == foreign_claims
    assert {route.result.net_name for route in result.telemetry.after_state.routes} == {
        *authority.bundle.by_net(),
        "/FOREIGN",
    }


def test_authority_construction_does_not_mutate_replay_or_bundle() -> None:
    replay = replay_fixtures._generate()
    assert replay.generation_result.candidate is not None
    assert replay.generation_result.candidate.bundle is not None
    replay_before = replay.model_dump_json()
    bundle = replay.generation_result.candidate.bundle
    bundle_before = bundle.model_dump_json()

    ReplayBoundBusRouteBundle(escape_replay=replay, bundle=bundle)

    assert replay.model_dump_json() == replay_before
    assert bundle.model_dump_json() == bundle_before


def test_rejects_failed_escape_even_with_a_valid_bundle() -> None:
    successful = _authority()
    failed = replay_fixtures._generate(
        escape_budget=BusEscapeBudget(
            max_members=0,
            max_terminals=4,
            max_expansions_per_terminal=2,
            max_expansions_per_member=4,
            max_total_expansions=8,
        )
    )
    assert not failed.generation_result.success

    with pytest.raises(ValidationError, match="successful escape generation"):
        ReplayBoundBusRouteBundle(escape_replay=failed, bundle=successful.bundle)


def test_rejects_bundle_other_than_nested_candidate() -> None:
    authority = _authority()
    first = authority.bundle.member_routes[0]
    altered_first = replace(first, base_cost_units=first.base_cost_units + 1)
    altered = BusRouteBundle(
        bus=authority.bundle.bus,
        allocation=authority.bundle.allocation,
        member_routes=(altered_first, *authority.bundle.member_routes[1:]),
    )

    with pytest.raises(ValidationError, match="does not equal the nested candidate"):
        ReplayBoundBusRouteBundle(
            escape_replay=authority.escape_replay,
            bundle=altered,
        )


@pytest.mark.parametrize("target", ("prefix", "candidate", "escape"))
def test_rejects_stale_nested_replay_authority(target: str) -> None:
    authority = _authority()
    payload = authority.escape_replay.model_dump(mode="json")
    if target == "prefix":
        payload["generation_result"]["prefixes_by_member"][0][1][
            "prefix_fingerprint"
        ] = "a" * 64
    elif target == "candidate":
        payload["generation_result"]["candidate"]["expansion_count"] += 1
    else:
        payload["generation_result"]["input_fingerprint"] = "a" * 64

    with pytest.raises(ValidationError):
        BusEscapeReplayResult.model_validate(payload)


def test_rejects_wrong_live_bus_before_transaction() -> None:
    authority = _authority()
    coordinator, _foreign = _coordinator(authority)
    wrong_bus = authority.bundle.bus.model_copy(update={"bus_id": "wrong-bus"})

    with pytest.raises(ValueError, match="commit bus"):
        commit_replay_bound_bus_candidate(
            coordinator,
            wrong_bus,
            authority.bundle.allocation,
            authority,
        )
    assert coordinator.last_attempt is None


def test_rejects_wrong_live_allocation_before_transaction() -> None:
    authority = _authority()
    coordinator, _foreign = _coordinator(authority)
    other_bus = transaction_fixtures._bus()
    wrong_allocation = transaction_fixtures._allocation(other_bus)

    with pytest.raises(ValueError, match="commit allocation"):
        commit_replay_bound_bus_candidate(
            coordinator,
            authority.bundle.bus,
            wrong_allocation,
            authority,
        )
    assert coordinator.last_attempt is None


def test_rejects_stale_result_fingerprints() -> None:
    authority = _authority()
    coordinator, _foreign = _coordinator(authority)
    result = commit_replay_bound_bus_candidate(
        coordinator,
        authority.bundle.bus,
        authority.bundle.allocation,
        authority,
    )
    payload = result.model_dump(mode="json")
    payload["candidate_bundle_fingerprint"] = "a" * 64

    with pytest.raises(ValidationError, match="candidate fingerprint is stale"):
        ReplayBoundBusTransactionResult.model_validate(payload)


def test_rejects_internally_reconstructible_after_state_with_wrong_bus_route() -> None:
    authority = _authority()
    coordinator, _foreign = _coordinator(authority, include_foreign=True)
    result = commit_replay_bound_bus_candidate(
        coordinator,
        authority.bundle.bus,
        authority.bundle.allocation,
        authority,
    )
    changed_routes = dict(coordinator.routes_by_net)
    target_net = authority.bundle.member_routes[0].result.net_name
    changed_route = replace(
        changed_routes[target_net],
        base_cost_units=changed_routes[target_net].base_cost_units + 1,
    )
    changed_routes[target_net] = changed_route
    changed_ledger = OccupancyLedger(route.claims for route in changed_routes.values())
    changed_state = BusRouteStateSnapshot.from_state(changed_ledger, changed_routes)
    telemetry_payload = result.telemetry.model_dump(mode="python")
    telemetry_payload.update(
        after_state=changed_state,
        ledger_after_fingerprint=changed_state.ledger_fingerprint,
        route_map_after_fingerprint=changed_state.route_map_fingerprint,
    )
    changed_telemetry = BusRouteTransactionTelemetry.model_validate(telemetry_payload)

    with pytest.raises(ValidationError, match="after-state bus routes"):
        ReplayBoundBusTransactionResult(
            authority=authority,
            telemetry=changed_telemetry,
            bus_fingerprint=result.bus_fingerprint,
            allocation_fingerprint=result.allocation_fingerprint,
            candidate_bundle_fingerprint=result.candidate_bundle_fingerprint,
        )


def test_ordinary_transaction_replace_remains_usable_without_replay_authority() -> None:
    bus, allocation, ledger, routes = transaction_fixtures._state()
    coordinator = BusRouteTransactionCoordinator(ledger, routes)
    replacement = transaction_fixtures._bundle(
        bus,
        allocation,
        transaction_fixtures._route("/A", 21),
        transaction_fixtures._route("/B", 22),
    )

    assert coordinator.replace(bus, allocation, lambda: replacement) == replacement
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.disposition is BusTransactionDisposition.COMMITTED
