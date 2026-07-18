"""Atomic replacement bridge for replay-bound physical-swap candidates.

The ordinary transaction coordinator remains unchanged.  This adapter derives
all bus and allocation authority from one successful physical-swap candidate,
requires the live replacement boundary to equal the candidate's exact initial
occupancy, and releases only the retained physical-prefix route bundle.

Commitment here is atomic state replacement, not exact-geometry acceptance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.bus_ir import BusGroup
from pcbsmith.kicad.bus_physical_swap_candidate import (
    BusPhysicalSwapCandidateMemberBinding,
    ReplayBoundPhysicalSwapBusCandidate,
)
from pcbsmith.kicad.bus_transaction import (
    BusRouteBundle,
    BusRouteStateSnapshot,
    BusRouteTransactionCoordinator,
    BusRouteTransactionTelemetry,
    BusTransactionDisposition,
)
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import NetResourceClaims, OccupancyLedger
from pcbsmith.routing_ir import RoutingIrModel


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bindings_fingerprint(
    bindings: tuple[BusPhysicalSwapCandidateMemberBinding, ...],
) -> str:
    return _fingerprint([item.model_dump(mode="json") for item in bindings])


class ReplayBoundPhysicalSwapBusRouteBundle(RoutingIrModel):
    """Successful physical candidate retained with its exact route authority."""

    schema_id: Literal["pcbsmith-replay-bound-physical-swap-bus-route-bundle"] = (
        "pcbsmith-replay-bound-physical-swap-bus-route-bundle"
    )
    schema_version: Literal[1] = 1
    candidate: ReplayBoundPhysicalSwapBusCandidate
    bundle: BusRouteBundle
    composition_fingerprint: str
    candidate_result_fingerprint: str
    bundle_fingerprint: str
    member_bindings: tuple[BusPhysicalSwapCandidateMemberBinding, ...]
    member_bindings_fingerprint: str
    authority_fingerprint: str

    @field_validator(
        "composition_fingerprint",
        "candidate_result_fingerprint",
        "bundle_fingerprint",
        "member_bindings_fingerprint",
        "authority_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
            raise ValueError("physical route authority fingerprints must be SHA-256")
        return value

    @field_validator("candidate", mode="before")
    @classmethod
    def candidate_is_json_revalidated(cls, value: Any) -> Any:
        if isinstance(value, ReplayBoundPhysicalSwapBusCandidate):
            return ReplayBoundPhysicalSwapBusCandidate.model_validate_json(value.model_dump_json())
        return value

    @model_validator(mode="after")
    def physical_candidate_and_bundle_are_exact(self) -> Self:
        _validate_route_authority(self)
        return self


def bind_replay_bound_physical_swap_bus_candidate(
    candidate: ReplayBoundPhysicalSwapBusCandidate,
) -> ReplayBoundPhysicalSwapBusRouteBundle:
    """Retain one fully replayed successful physical candidate and bundle."""

    validated = ReplayBoundPhysicalSwapBusCandidate.model_validate_json(candidate.model_dump_json())
    nested = validated.candidate_result
    if not nested.success or nested.bundle is None:
        raise ValueError("physical route authority requires a successful candidate bundle")
    bundle_fp = nested.bundle.semantic_fingerprint()
    bindings_fp = _bindings_fingerprint(validated.member_bindings)
    authority_fp = _route_authority_fingerprint(
        validated,
        bundle_fp,
        bindings_fp,
    )
    return ReplayBoundPhysicalSwapBusRouteBundle.model_construct(
        candidate=validated,
        bundle=nested.bundle,
        composition_fingerprint=validated.composition_fingerprint,
        candidate_result_fingerprint=validated.candidate_result_fingerprint,
        bundle_fingerprint=bundle_fp,
        member_bindings=validated.member_bindings,
        member_bindings_fingerprint=bindings_fp,
        authority_fingerprint=authority_fp,
    )


def _validate_route_authority(
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
) -> None:
    candidate = authority.candidate
    nested = candidate.candidate_result
    if not nested.success or nested.bundle is None:
        raise ValueError("physical route authority requires a successful candidate bundle")
    if nested.bundle != authority.bundle:
        raise ValueError("retained bundle does not equal the physical candidate bundle")
    plan_input = candidate.replay_input.composition.replay_input.plan.replay_input
    if (
        authority.bundle.bus != plan_input.bus
        or authority.bundle.allocation != plan_input.allocation
    ):
        raise ValueError("physical route authority binds a stale bus or allocation")
    if authority.member_bindings != candidate.member_bindings:
        raise ValueError("physical route authority member bindings are stale")
    bundle_fp = authority.bundle.semantic_fingerprint()
    bindings_fp = _bindings_fingerprint(authority.member_bindings)
    expected = _route_authority_fingerprint(candidate, bundle_fp, bindings_fp)
    if (
        authority.composition_fingerprint != candidate.composition_fingerprint
        or authority.candidate_result_fingerprint != candidate.candidate_result_fingerprint
        or authority.bundle_fingerprint != candidate.bundle_fingerprint
        or authority.bundle_fingerprint != bundle_fp
        or authority.member_bindings_fingerprint != bindings_fp
        or authority.authority_fingerprint != expected
    ):
        raise ValueError("physical route authority fingerprint binding is stale")


def _route_authority_fingerprint(
    candidate: ReplayBoundPhysicalSwapBusCandidate,
    bundle_fingerprint: str,
    member_bindings_fingerprint: str,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-physical-swap-route-bundle-authority",
            "schema_version": 1,
            "physical_candidate_fingerprint": candidate.result_fingerprint,
            "composition_fingerprint": candidate.composition_fingerprint,
            "candidate_result_fingerprint": candidate.candidate_result_fingerprint,
            "bundle_fingerprint": bundle_fingerprint,
            "member_bindings_fingerprint": member_bindings_fingerprint,
        }
    )


class ReplayBoundPhysicalSwapBusTransactionResult(RoutingIrModel):
    """Committed ordinary transaction bound to physical-prefix authority."""

    schema_id: Literal["pcbsmith-replay-bound-physical-swap-bus-transaction-result"] = (
        "pcbsmith-replay-bound-physical-swap-bus-transaction-result"
    )
    schema_version: Literal[1] = 1
    authority: ReplayBoundPhysicalSwapBusRouteBundle
    telemetry: BusRouteTransactionTelemetry
    bus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_result_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_bindings_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("authority", mode="before")
    @classmethod
    def authority_is_json_revalidated(cls, value: Any) -> Any:
        if isinstance(value, ReplayBoundPhysicalSwapBusRouteBundle):
            return ReplayBoundPhysicalSwapBusRouteBundle.model_validate_json(
                value.model_dump_json()
            )
        return value

    @field_validator("telemetry", mode="before")
    @classmethod
    def telemetry_is_json_revalidated(cls, value: Any) -> Any:
        if isinstance(value, BusRouteTransactionTelemetry):
            return BusRouteTransactionTelemetry.model_validate_json(value.model_dump_json())
        return value

    @model_validator(mode="after")
    def committed_state_is_exactly_bound(self) -> Self:
        _validate_committed_transaction(self.authority, self.telemetry)
        plan_input = (
            self.authority.candidate.replay_input.composition.replay_input.plan.replay_input
        )
        expected = _transaction_result_fingerprint(self.authority, self.telemetry)
        if (
            self.bus_fingerprint != plan_input.bus.semantic_fingerprint()
            or self.allocation_fingerprint != plan_input.allocation.allocation_fingerprint
            or self.candidate_result_fingerprint != self.authority.candidate_result_fingerprint
            or self.bundle_fingerprint != self.authority.bundle_fingerprint
            or self.member_bindings_fingerprint != self.authority.member_bindings_fingerprint
            or self.result_fingerprint != expected
        ):
            raise ValueError("physical transaction result fingerprint binding is stale")
        return self


def commit_replay_bound_physical_swap_bus_candidate(
    coordinator: BusRouteTransactionCoordinator,
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
) -> ReplayBoundPhysicalSwapBusTransactionResult:
    """Commit one retained physical-swap candidate through ordinary replace."""

    validated = ReplayBoundPhysicalSwapBusRouteBundle.model_validate_json(
        authority.model_dump_json()
    )
    plan_input = validated.candidate.replay_input.composition.replay_input.plan.replay_input
    _require_complete_replacement_boundary(
        coordinator.ledger,
        coordinator.routes_by_net,
        plan_input.bus,
        plan_input.initial_claims,
        plan_input.initial_occupancy_fingerprint,
    )
    calls = 0

    def release_retained_bundle() -> BusRouteBundle:
        nonlocal calls
        calls += 1
        _require_stripped_occupancy(
            coordinator.ledger,
            plan_input.initial_claims,
            plan_input.initial_occupancy_fingerprint,
        )
        return validated.bundle

    committed = coordinator.replace(
        plan_input.bus,
        plan_input.allocation,
        release_retained_bundle,
    )
    if calls != 1 or committed != validated.bundle:
        raise ValueError("physical candidate transaction substituted or retried its callback")
    telemetry = coordinator.last_attempt
    if telemetry is None:
        raise ValueError("physical candidate transaction omitted commit telemetry")
    _validate_committed_transaction(validated, telemetry)
    result_fp = _transaction_result_fingerprint(validated, telemetry)
    return ReplayBoundPhysicalSwapBusTransactionResult.model_construct(
        authority=validated,
        telemetry=telemetry,
        bus_fingerprint=plan_input.bus.semantic_fingerprint(),
        allocation_fingerprint=plan_input.allocation.allocation_fingerprint,
        candidate_result_fingerprint=validated.candidate_result_fingerprint,
        bundle_fingerprint=validated.bundle_fingerprint,
        member_bindings_fingerprint=validated.member_bindings_fingerprint,
        result_fingerprint=result_fp,
    )


def _require_complete_replacement_boundary(
    ledger: OccupancyLedger,
    routes_by_net: Mapping[str, NegotiatedGridRoute],
    bus: BusGroup,
    initial_claims: tuple[NetResourceClaims, ...],
    initial_fingerprint: str,
) -> BusRouteStateSnapshot:
    snapshot = BusRouteStateSnapshot.from_state(ledger, routes_by_net)
    bus_nets = {member.net_name for member in bus.members}
    route_nets = {route.result.net_name for route in snapshot.routes}
    if not bus_nets.issubset(route_nets):
        raise ValueError("physical candidate replacement requires every current bus route")
    stripped_claims = tuple(claim for claim in snapshot.claims if claim.net_name not in bus_nets)
    stripped = OccupancyLedger(stripped_claims)
    if stripped_claims != initial_claims or stripped.semantic_fingerprint() != initial_fingerprint:
        raise ValueError("hypothetically stripped occupancy does not equal physical authority")
    return snapshot


def _require_stripped_occupancy(
    ledger: OccupancyLedger,
    expected_claims: tuple[NetResourceClaims, ...],
    expected_fingerprint: str,
) -> None:
    if (
        ledger.committed_claims() != expected_claims
        or ledger.semantic_fingerprint() != expected_fingerprint
    ):
        raise ValueError("stripped coordinator occupancy does not equal physical authority")


def _validate_committed_transaction(
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
    telemetry: BusRouteTransactionTelemetry,
) -> None:
    _validate_route_authority(authority)
    if telemetry.disposition is not BusTransactionDisposition.COMMITTED:
        raise ValueError("physical transaction result requires a committed transaction")
    plan_input = authority.candidate.replay_input.composition.replay_input.plan.replay_input
    bus = plan_input.bus
    member_nets = {member.net_name for member in bus.members}
    if (
        telemetry.bus_id != bus.bus_id
        or telemetry.bus_fingerprint != bus.semantic_fingerprint()
        or telemetry.allocation_fingerprint != plan_input.allocation.allocation_fingerprint
        or telemetry.candidate_bundle_fingerprint != authority.bundle_fingerprint
    ):
        raise ValueError("physical transaction telemetry binds stale authority")
    before_routes = {route.result.net_name: route for route in telemetry.before_state.routes}
    before_claims = {claim.net_name: claim for claim in telemetry.before_state.claims}
    foreign_routes = {
        net_name: route for net_name, route in before_routes.items() if net_name not in member_nets
    }
    foreign_claims = {
        net_name: claim for net_name, claim in before_claims.items() if net_name not in member_nets
    }
    expected_initial = {claim.net_name: claim for claim in plan_input.initial_claims}
    if foreign_claims != expected_initial or set(foreign_routes) != set(expected_initial):
        raise ValueError("transaction before-state does not strip to physical authority")
    expected_routes = {**foreign_routes, **authority.bundle.by_net()}
    expected_claims = {
        **foreign_claims,
        **{route.result.net_name: route.claims for route in authority.bundle.member_routes},
    }
    after_routes = {route.result.net_name: route for route in telemetry.after_state.routes}
    after_claims = {claim.net_name: claim for claim in telemetry.after_state.claims}
    if after_routes != expected_routes or after_claims != expected_claims:
        raise ValueError("transaction after-state is not the exact physical replacement")
    expected_ledger = OccupancyLedger(tuple(expected_claims.values()))
    expected_state = BusRouteStateSnapshot.from_state(expected_ledger, expected_routes)
    if telemetry.after_state != expected_state:
        raise ValueError("transaction after-state fingerprint is not exactly reconstructible")
    expected_overuse = expected_ledger.overuse()
    if telemetry.capacity_overuse != expected_overuse or expected_overuse:
        raise ValueError("physical transaction overuse telemetry is stale or nonzero")


def _transaction_result_fingerprint(
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
    telemetry: BusRouteTransactionTelemetry,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-physical-swap-bus-transaction-result",
            "schema_version": 1,
            "authority_fingerprint": authority.authority_fingerprint,
            "telemetry_fingerprint": telemetry.semantic_fingerprint(),
            "before_state_fingerprint": telemetry.before_state.semantic_fingerprint(),
            "after_state_fingerprint": telemetry.after_state.semantic_fingerprint(),
        }
    )
