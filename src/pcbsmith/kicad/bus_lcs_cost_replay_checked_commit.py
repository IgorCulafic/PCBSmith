"""Exact checked-commit bridge for the cost-aware LCS routing path.

This opt-in envelope closes the authority chain from a replayed cost-aware
physical decision to the already replay-bound escape candidate.  It does not
reimplement routing, transactions, materialization, or exact checking; those
remain owned by their existing replay and checked-commit components.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.kicad.bus_candidate_transaction import ReplayBoundBusRouteBundle
from pcbsmith.kicad.bus_checked_commit import (
    BusCheckedCommitCoordinator,
    BusRouteMapMaterializer,
    materialize_complete_route_map,
)
from pcbsmith.kicad.bus_lcs_cost_physical_realization import BusLcsCostPhysicalResult
from pcbsmith.kicad.bus_replay_checked_commit import (
    ReplayBoundBusCheckedCommitResult,
    commit_replay_bound_bus_exact,
)
from pcbsmith.kicad.negotiated_board import ExactRouteChecker
from pcbsmith.routing_ir import RoutingIrModel


def _revalidate_physical(value: BusLcsCostPhysicalResult) -> BusLcsCostPhysicalResult:
    reconstructed = BusLcsCostPhysicalResult.model_validate_json(value.model_dump_json())
    if reconstructed != value:
        raise ValueError("cost physical authority failed exact JSON reconstruction")
    return reconstructed


def _revalidate_route(value: ReplayBoundBusRouteBundle) -> ReplayBoundBusRouteBundle:
    reconstructed = ReplayBoundBusRouteBundle.model_validate_json(value.model_dump_json())
    if reconstructed != value:
        raise ValueError("route authority failed exact JSON reconstruction")
    return reconstructed


class BusLcsCostReplayRouteAuthority(RoutingIrModel):
    """One successful cost-physical result bound to one exact route replay."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-replay-route-authority"] = (
        "pcbsmith-bus-lcs-cost-replay-route-authority"
    )
    schema_version: Literal[1] = 1
    authority_scope: Literal["cost-physical-to-replay-route-only"] = (
        "cost-physical-to-replay-route-only"
    )
    cost_physical: BusLcsCostPhysicalResult
    route_authority: ReplayBoundBusRouteBundle

    @model_validator(mode="after")
    def authorities_are_exactly_identical(self) -> Self:
        physical = _revalidate_physical(self.cost_physical)
        route = _revalidate_route(self.route_authority)
        if not physical.success:
            raise ValueError("cost route authority requires successful physical validation")

        physical_input = physical.realization_input
        plan_input = physical_input.cost_plan.plan_input
        replay_input = route.escape_replay.replay_input
        if (
            plan_input.bus != replay_input.bus
            or plan_input.certificate != replay_input.certificate
            or plan_input.rule_profile != replay_input.profile
            or physical_input.allocation != replay_input.allocation
            or physical_input.transition_authority.replay_input.bus != replay_input.bus
            or physical_input.transition_authority.replay_input.certificate
            != replay_input.certificate
            or physical_input.transition_authority.replay_input.allocation
            != replay_input.allocation
            or physical_input.transition_authority.replay_input.geometry_registry
            != replay_input.lane_registry
            or physical_input.transition_authority.replay_input.profile
            != replay_input.profile
            or physical_input.transition_authority.replay_input.initial_claims
            != replay_input.initial_claims
        ):
            raise ValueError("cost and route authorities do not retain identical inputs")

        transition_input = physical_input.transition_authority.replay_input
        if replay_input.allocation.layer_transitions and (
            replay_input.transition_budget is None
            or replay_input.transition_budget != transition_input.budget
        ):
            raise ValueError("cost and route transition budgets are not identical")

        physical_prefixes = {item.member_id: item for item in physical_input.prefixes}
        route_prefixes = dict(route.escape_replay.generation_result.prefixes_by_member)
        if physical_prefixes != route_prefixes:
            raise ValueError("route prefixes do not equal cost-validated physical prefixes")

        plan_members = {
            item.member_id for item in physical_input.cost_plan.plan_input.bus.members
        }
        if (
            set(physical_prefixes) != plan_members
            or {item.member_id for item in physical.member_authorities} != plan_members
        ):
            raise ValueError("cost route authority does not cover every bus member")
        return self


class BusLcsCostReplayCheckedCommitResult(RoutingIrModel):
    """Existing checked-commit semantics bound to the complete cost authority."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-replay-checked-commit-result"] = (
        "pcbsmith-bus-lcs-cost-replay-checked-commit-result"
    )
    schema_version: Literal[1] = 1
    authority: BusLcsCostReplayRouteAuthority
    checked_result: ReplayBoundBusCheckedCommitResult

    @model_validator(mode="after")
    def checked_route_is_the_cost_route(self) -> Self:
        authority = BusLcsCostReplayRouteAuthority.model_validate_json(
            self.authority.model_dump_json()
        )
        checked = ReplayBoundBusCheckedCommitResult.model_validate_json(
            self.checked_result.model_dump_json()
        )
        if authority != self.authority or checked != self.checked_result:
            raise ValueError("cost checked result failed exact JSON reconstruction")
        if checked.authority != authority.route_authority:
            raise ValueError("checked route does not equal the cost-bound route authority")
        return self


def commit_bus_lcs_cost_replay_exact(
    coordinator: BusCheckedCommitCoordinator,
    authority: BusLcsCostReplayRouteAuthority,
    *,
    exact_checker: ExactRouteChecker | None,
    materializer: BusRouteMapMaterializer = materialize_complete_route_map,
) -> BusLcsCostReplayCheckedCommitResult:
    """Commit only the route retained by a successful cost-physical replay."""

    validated = BusLcsCostReplayRouteAuthority.model_validate_json(
        authority.model_dump_json()
    )
    if validated != authority:
        raise ValueError("cost route authority failed exact JSON reconstruction")
    checked = commit_replay_bound_bus_exact(
        coordinator,
        validated.route_authority,
        exact_checker=exact_checker,
        materializer=materializer,
    )
    return BusLcsCostReplayCheckedCommitResult(
        authority=validated,
        checked_result=checked,
    )
