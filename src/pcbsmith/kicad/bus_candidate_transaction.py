"""Opt-in replay-bound bridge from certified bus candidates to transactions.

The existing transaction coordinator deliberately remains a general atomic
replacement primitive.  This module adds a stricter caller-selected path that
retains the complete escape replay authority and proves that the exact bundle
committed by the transaction is the bundle certified by that replay.

Neither a committed transaction nor this envelope is an exact-geometry
acceptance verdict.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_ir import BusGroup
from pcbsmith.kicad.bus_escape_replay import BusEscapeReplayResult
from pcbsmith.kicad.bus_transaction import (
    BusRouteBundle,
    BusRouteStateSnapshot,
    BusRouteTransactionCoordinator,
    BusRouteTransactionTelemetry,
    BusTransactionDisposition,
)
from pcbsmith.routing_ir import RoutingIrModel


def _revalidate_escape(value: BusEscapeReplayResult) -> BusEscapeReplayResult:
    reconstructed = BusEscapeReplayResult.model_validate_json(value.model_dump_json())
    if reconstructed != value:
        raise ValueError("escape replay authority failed exact JSON reconstruction")
    return reconstructed


def _revalidate_bundle(value: BusRouteBundle) -> BusRouteBundle:
    reconstructed = BusRouteBundle.model_validate_json(value.model_dump_json())
    if reconstructed != value:
        raise ValueError("bus route bundle failed exact JSON reconstruction")
    return reconstructed


def _revalidate_state(value: BusRouteStateSnapshot, boundary: str) -> BusRouteStateSnapshot:
    reconstructed = BusRouteStateSnapshot.model_validate_json(value.model_dump_json())
    if reconstructed != value:
        raise ValueError(f"transaction {boundary} state failed exact JSON reconstruction")
    return reconstructed


class ReplayBoundBusRouteBundle(RoutingIrModel):
    """A successful escape replay bound to its exact complete route bundle."""

    schema_id: Literal["pcbsmith-replay-bound-bus-route-bundle"] = (
        "pcbsmith-replay-bound-bus-route-bundle"
    )
    schema_version: Literal[1] = 1
    escape_replay: BusEscapeReplayResult
    bundle: BusRouteBundle

    @model_validator(mode="after")
    def candidate_and_prefix_authority_is_exact(self) -> Self:
        escape_replay = _revalidate_escape(self.escape_replay)
        bundle = _revalidate_bundle(self.bundle)
        generation = escape_replay.generation_result
        candidate = generation.candidate
        if not generation.success:
            raise ValueError("replay-bound route bundle requires successful escape generation")
        if candidate is None or not candidate.success or candidate.bundle is None:
            raise ValueError("replay-bound route bundle requires a successful nested candidate")
        if candidate.bundle != bundle:
            raise ValueError("retained route bundle does not equal the nested candidate bundle")

        replay_bus = escape_replay.replay_input.bus
        replay_allocation = escape_replay.replay_input.allocation
        if (
            generation.bus_id != replay_bus.bus_id
            or candidate.bus_id != replay_bus.bus_id
            or candidate.bus_fingerprint != replay_bus.semantic_fingerprint()
            or candidate.allocation_fingerprint
            != replay_allocation.allocation_fingerprint
        ):
            raise ValueError("nested candidate does not bind the exact replay bus and allocation")
        if (
            bundle.bus != replay_bus
            or bundle.bus.semantic_fingerprint() != generation.bus_fingerprint
        ):
            raise ValueError("retained route bundle does not bind the exact replay bus")
        if (
            bundle.allocation != replay_allocation
            or bundle.allocation.allocation_fingerprint != generation.allocation_fingerprint
        ):
            raise ValueError("retained route bundle does not bind the exact replay allocation")

        members = {member.member_id: member for member in replay_bus.members}
        prefixes = {member_id: prefix for member_id, prefix in generation.prefixes_by_member}
        if set(prefixes) != set(members):
            raise ValueError("escape generation must retain one certified prefix per bus member")
        routes = bundle.by_net()
        if set(routes) != {member.net_name for member in members.values()}:
            raise ValueError("retained route bundle does not cover the exact bus member nets")
        for member_id, member in members.items():
            prefix = prefixes[member_id]
            route = routes[member.net_name]
            if prefix.member_id != member_id or prefix.net_name != member.net_name:
                raise ValueError("certified prefix member or net correspondence is stale")
            if (
                route.result.net_name != member.net_name
                or route.claims.net_name != member.net_name
                or route.prefix_alternative_id != prefix.prefix.alternative_id
                or route.prefix_fingerprint != prefix.prefix_fingerprint
            ):
                raise ValueError(
                    "bundle route does not bind its member's complete certified prefix"
                )
        return self


class ReplayBoundBusTransactionResult(RoutingIrModel):
    """Committed transaction telemetry bound to one replay-certified bundle.

    This records atomic commitment only.  It makes no exact-acceptance claim.
    """

    schema_id: Literal["pcbsmith-replay-bound-bus-transaction-result"] = (
        "pcbsmith-replay-bound-bus-transaction-result"
    )
    schema_version: Literal[1] = 1
    authority: ReplayBoundBusRouteBundle
    telemetry: BusRouteTransactionTelemetry
    bus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_bundle_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def committed_state_is_exactly_bound(self) -> Self:
        authority = ReplayBoundBusRouteBundle.model_validate_json(
            self.authority.model_dump_json()
        )
        if authority != self.authority:
            raise ValueError("route-bundle authority failed exact JSON reconstruction")
        telemetry = BusRouteTransactionTelemetry.model_validate_json(
            self.telemetry.model_dump_json()
        )
        if telemetry != self.telemetry:
            raise ValueError("transaction telemetry failed exact JSON reconstruction")
        _revalidate_state(telemetry.before_state, "before")
        _revalidate_state(telemetry.after_state, "after")
        if telemetry.disposition is not BusTransactionDisposition.COMMITTED:
            raise ValueError("replay-bound transaction result requires a committed transaction")

        bus = authority.bundle.bus
        allocation = authority.bundle.allocation
        bundle_fingerprint = authority.bundle.semantic_fingerprint()
        if self.bus_fingerprint != bus.semantic_fingerprint():
            raise ValueError("replay-bound transaction bus fingerprint is stale")
        if self.allocation_fingerprint != allocation.allocation_fingerprint:
            raise ValueError("replay-bound transaction allocation fingerprint is stale")
        if self.candidate_bundle_fingerprint != bundle_fingerprint:
            raise ValueError("replay-bound transaction candidate fingerprint is stale")
        if (
            telemetry.bus_id != bus.bus_id
            or telemetry.bus_fingerprint != self.bus_fingerprint
            or telemetry.allocation_fingerprint != self.allocation_fingerprint
            or telemetry.candidate_bundle_fingerprint != self.candidate_bundle_fingerprint
        ):
            raise ValueError("transaction telemetry does not bind the retained authority")

        member_nets = {member.net_name for member in bus.members}
        expected_routes = authority.bundle.by_net()
        after_routes = {
            route.result.net_name: route
            for route in telemetry.after_state.routes
            if route.result.net_name in member_nets
        }
        after_claims = {
            claim.net_name: claim
            for claim in telemetry.after_state.claims
            if claim.net_name in member_nets
        }
        if after_routes != expected_routes:
            raise ValueError("transaction after-state bus routes do not equal the retained bundle")
        if after_claims != {
            net_name: route.claims for net_name, route in expected_routes.items()
        }:
            raise ValueError("transaction after-state bus claims do not equal the retained bundle")
        return self


def commit_replay_bound_bus_candidate(
    coordinator: BusRouteTransactionCoordinator,
    bus: BusGroup,
    allocation: BusLaneAllocationResult,
    authority: ReplayBoundBusRouteBundle,
) -> ReplayBoundBusTransactionResult:
    """Commit exactly one replay-certified bundle through the existing coordinator."""

    validated = ReplayBoundBusRouteBundle.model_validate_json(authority.model_dump_json())
    if validated != authority:
        raise ValueError("route-bundle authority failed exact JSON reconstruction")
    if (
        bus != validated.bundle.bus
        or bus.semantic_fingerprint() != validated.bundle.bus.semantic_fingerprint()
    ):
        raise ValueError("commit bus does not equal the replay-bound bus")
    if allocation != validated.bundle.allocation:
        raise ValueError("commit allocation does not equal the replay-bound allocation")

    committed = coordinator.replace(bus, allocation, lambda: validated.bundle)
    if committed != validated.bundle:
        raise ValueError("transaction returned a bundle other than the replay-bound candidate")
    telemetry = coordinator.last_attempt
    if telemetry is None:
        raise ValueError("transaction coordinator did not retain commit telemetry")
    return ReplayBoundBusTransactionResult(
        authority=validated,
        telemetry=telemetry,
        bus_fingerprint=bus.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        candidate_bundle_fingerprint=validated.bundle.semantic_fingerprint(),
    )
