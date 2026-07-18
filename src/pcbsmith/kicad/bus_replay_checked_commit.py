"""Opt-in exact checked commit for one replay-certified bus candidate.

This bridge deliberately leaves :mod:`pcbsmith.kicad.bus_checked_commit`
unchanged.  It supplies that coordinator only with board, bus, allocation, and
candidate authority retained by a successful escape replay, and retains the
ordinary checked result without strengthening its acceptance semantics.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.kicad.bus_candidate import BusCandidateResult
from pcbsmith.kicad.bus_candidate_transaction import ReplayBoundBusRouteBundle
from pcbsmith.kicad.bus_checked_commit import (
    BusCheckedCommitCoordinator,
    BusCheckedCommitResult,
    BusRouteMapMaterializer,
    materialize_complete_route_map,
)
from pcbsmith.kicad.negotiated_board import ExactRouteChecker
from pcbsmith.kicad.negotiated_resources import OccupancyLedger
from pcbsmith.routing_ir import RoutingIrModel


def _revalidate_authority(
    value: ReplayBoundBusRouteBundle,
) -> ReplayBoundBusRouteBundle:
    reconstructed = ReplayBoundBusRouteBundle.model_validate_json(value.model_dump_json())
    if reconstructed != value:
        raise ValueError("replay-bound route authority failed exact JSON reconstruction")
    return reconstructed


def _revalidate_checked_result(value: BusCheckedCommitResult) -> BusCheckedCommitResult:
    reconstructed = BusCheckedCommitResult.model_validate_json(value.model_dump_json())
    if reconstructed != value:
        raise ValueError("checked commit result failed exact JSON reconstruction")
    return reconstructed


class ReplayBoundBusCheckedCommitResult(RoutingIrModel):
    """An ordinary checked result bound to its complete replay authority.

    Acceptance, rejection, and missing-checker meanings are exactly those of
    ``BusCheckedCommitResult``.  This envelope only proves which retained
    replay-certified candidate was supplied to that checked transaction.
    """

    schema_id: Literal["pcbsmith-replay-bound-bus-checked-commit-result"] = (
        "pcbsmith-replay-bound-bus-checked-commit-result"
    )
    schema_version: Literal[1] = 1
    authority: ReplayBoundBusRouteBundle
    checked_result: BusCheckedCommitResult

    @model_validator(mode="after")
    def checked_candidate_is_exactly_replay_bound(self) -> Self:
        authority = _revalidate_authority(self.authority)
        checked = _revalidate_checked_result(self.checked_result)
        generation = authority.escape_replay.generation_result
        candidate = generation.candidate
        if candidate is None or candidate.bundle is None:
            raise ValueError("replay authority does not retain a complete candidate")
        if checked.candidate_result != candidate:
            raise ValueError("checked candidate does not equal the replay candidate")
        if checked.candidate_result.bundle != authority.bundle:
            raise ValueError("checked bundle does not equal the replay-bound bundle")

        replay_input = authority.escape_replay.replay_input
        if (
            authority.bundle.bus != replay_input.bus
            or authority.bundle.allocation != replay_input.allocation
            or checked.telemetry.bus_id != replay_input.bus.bus_id
            or checked.telemetry.bus_fingerprint
            != replay_input.bus.semantic_fingerprint()
            or checked.telemetry.allocation_fingerprint
            != replay_input.allocation.allocation_fingerprint
        ):
            raise ValueError("checked result does not bind the exact replay bus and allocation")

        checked_ran = checked.exact_report is not None
        if checked_ran:
            # BusCheckedCommitResult already reconstructs and binds the complete
            # layout, netlist, report, and evidence.  The replay bridge also
            # requires that exact checked netlist to be its retained netlist.
            if checked.checked_netlist != replay_input.netlist:
                raise ValueError("checked netlist does not equal the replay netlist")
        return self


def _require_complete_coordinator_state(
    coordinator: BusCheckedCommitCoordinator,
) -> None:
    """Reject route/claim shadows before invoking any untrusted callback."""

    route_claims = {}
    for key, route in coordinator.routes_by_net.items():
        if key != route.result.net_name or key != route.claims.net_name:
            raise ValueError("coordinator route-map keys and route claims must agree")
        route_claims[key] = route.claims
    ledger_claims = {claim.net_name: claim for claim in coordinator.ledger.committed_claims()}
    if route_claims != ledger_claims:
        raise ValueError("coordinator route map must exactly represent committed claims")


def commit_replay_bound_bus_exact(
    coordinator: BusCheckedCommitCoordinator,
    authority: ReplayBoundBusRouteBundle,
    *,
    exact_checker: ExactRouteChecker | None,
    materializer: BusRouteMapMaterializer = materialize_complete_route_map,
) -> ReplayBoundBusCheckedCommitResult:
    """Run one replacement-only checked commit from retained replay authority.

    No caller can substitute the static layout, netlist, bus, allocation, or
    candidate.  The coordinator's stripped occupancy must equal the replay's
    complete initial occupancy before the retained candidate is released.
    """

    validated = _revalidate_authority(authority)
    _require_complete_coordinator_state(coordinator)
    replay_input = validated.escape_replay.replay_input
    candidate = validated.escape_replay.generation_result.candidate
    if candidate is None or candidate.bundle is None:
        raise ValueError("replay authority does not retain a complete candidate")

    expected_claims = replay_input.initial_claims
    expected_fingerprint = replay_input.initial_ledger().semantic_fingerprint()

    def exact_retained_candidate(scratch: OccupancyLedger) -> BusCandidateResult:
        # Kept as a nested callback so the existing coordinator remains the
        # single owner of rip-up, callback count, rollback, and no-retry rules.
        if (
            scratch.committed_claims() != expected_claims
            or scratch.semantic_fingerprint() != expected_fingerprint
        ):
            raise ValueError("stripped coordinator occupancy does not equal replay authority")
        return candidate

    # The callback's precise protocol is statically known by the coordinator;
    # the object annotations above keep the closure hostile-input defensive.
    checked = coordinator.commit(
        replay_input.static_layout,
        replay_input.netlist,
        replay_input.bus,
        replay_input.allocation,
        exact_retained_candidate,
        exact_checker=exact_checker,
        materializer=materializer,
    )
    return ReplayBoundBusCheckedCommitResult(
        authority=validated,
        checked_result=checked,
    )
