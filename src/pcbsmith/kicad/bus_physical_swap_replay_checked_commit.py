"""Exact-checked commit bridge for replay-bound physical-swap candidates.

This adapter leaves the ordinary checked coordinator unchanged.  It derives
every board, bus, allocation, and candidate input from retained physical-swap
replay authority and explicitly binds the materialized physical-prefix copper
to the exact report/evidence retained by the ordinary checked result.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.board_serialization import canonical_board_layout_snapshot_json
from pcbsmith.kicad.bus_candidate import BusCandidateResult
from pcbsmith.kicad.bus_checked_commit import (
    BusCheckedCommitCoordinator,
    BusCheckedCommitResult,
    BusExactDisposition,
    BusRouteMapMaterializer,
    materialize_complete_route_map,
)
from pcbsmith.kicad.bus_physical_swap_candidate_transaction import (
    ReplayBoundPhysicalSwapBusRouteBundle,
    _fingerprint,
    _require_complete_replacement_boundary,
    _require_stripped_occupancy,
    _validate_route_authority,
)
from pcbsmith.kicad.bus_transaction import BusRouteStateSnapshot
from pcbsmith.kicad.negotiated_board import ExactRouteChecker
from pcbsmith.kicad.negotiated_resources import OccupancyLedger
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.routing_ir import RoutingIrModel


class ReplayBoundPhysicalSwapBusCheckedCommitResult(RoutingIrModel):
    """Ordinary checked result bound to exact physical materialization."""

    schema_id: Literal["pcbsmith-replay-bound-physical-swap-bus-checked-commit-result"] = (
        "pcbsmith-replay-bound-physical-swap-bus-checked-commit-result"
    )
    schema_version: Literal[1] = 1
    authority: ReplayBoundPhysicalSwapBusRouteBundle
    checked_result: BusCheckedCommitResult
    before_state: BusRouteStateSnapshot
    after_state: BusRouteStateSnapshot
    authority_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_result_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    materialized_layout_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    result_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("authority", mode="before")
    @classmethod
    def authority_is_json_revalidated(cls, value: Any) -> Any:
        if isinstance(value, ReplayBoundPhysicalSwapBusRouteBundle):
            return ReplayBoundPhysicalSwapBusRouteBundle.model_validate_json(
                value.model_dump_json()
            )
        return value

    @field_validator("checked_result", mode="before")
    @classmethod
    def checked_result_is_json_revalidated(cls, value: Any) -> Any:
        if isinstance(value, BusCheckedCommitResult):
            return BusCheckedCommitResult.model_validate_json(value.model_dump_json())
        return value

    @field_validator("before_state", "after_state", mode="before")
    @classmethod
    def states_are_json_revalidated(cls, value: Any) -> Any:
        if isinstance(value, BusRouteStateSnapshot):
            return BusRouteStateSnapshot.model_validate_json(value.model_dump_json())
        return value

    @model_validator(mode="after")
    def checked_result_is_exactly_physical_replay_bound(self) -> Self:
        materialized_fp = _validate_checked_commit(
            self.authority,
            self.checked_result,
            self.before_state,
            self.after_state,
        )
        expected = _checked_result_fingerprint(
            self.authority,
            self.checked_result,
            self.before_state,
            self.after_state,
            materialized_fp,
        )
        if (
            self.authority_fingerprint != self.authority.authority_fingerprint
            or self.checked_result_fingerprint != self.checked_result.semantic_fingerprint()
            or self.materialized_layout_fingerprint != materialized_fp
            or self.result_fingerprint != expected
        ):
            raise ValueError("physical checked-commit fingerprint binding is stale")
        return self


def commit_replay_bound_physical_swap_bus_exact(
    coordinator: BusCheckedCommitCoordinator,
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
    *,
    exact_checker: ExactRouteChecker | None,
    materializer: BusRouteMapMaterializer = materialize_complete_route_map,
) -> ReplayBoundPhysicalSwapBusCheckedCommitResult:
    """Run one replacement-only exact check from physical replay authority."""

    validated = ReplayBoundPhysicalSwapBusRouteBundle.model_validate_json(
        authority.model_dump_json()
    )
    plan_input = validated.candidate.replay_input.composition.replay_input.plan.replay_input
    before_state = _require_complete_replacement_boundary(
        coordinator.ledger,
        coordinator.routes_by_net,
        plan_input.bus,
        plan_input.initial_claims,
        plan_input.initial_occupancy_fingerprint,
    )
    calls = 0

    def release_retained_candidate(scratch: OccupancyLedger) -> BusCandidateResult:
        nonlocal calls
        calls += 1
        _require_stripped_occupancy(
            scratch,
            plan_input.initial_claims,
            plan_input.initial_occupancy_fingerprint,
        )
        return validated.candidate.candidate_result

    checked = coordinator.commit(
        plan_input.layout,
        plan_input.netlist,
        plan_input.bus,
        plan_input.allocation,
        release_retained_candidate,
        exact_checker=exact_checker,
        materializer=materializer,
    )
    if calls != 1 or checked.candidate_result != validated.candidate.candidate_result:
        raise ValueError("physical checked commit substituted or retried its candidate")
    if coordinator.last_result != checked:
        raise ValueError("physical checked commit did not retain its ordinary result")
    after_state = BusRouteStateSnapshot.from_state(
        coordinator.ledger,
        coordinator.routes_by_net,
    )
    materialized_fp = _validate_checked_commit(
        validated,
        checked,
        before_state,
        after_state,
    )
    result_fp = _checked_result_fingerprint(
        validated,
        checked,
        before_state,
        after_state,
        materialized_fp,
    )
    return ReplayBoundPhysicalSwapBusCheckedCommitResult.model_construct(
        authority=validated,
        checked_result=checked,
        before_state=before_state,
        after_state=after_state,
        authority_fingerprint=validated.authority_fingerprint,
        checked_result_fingerprint=checked.semantic_fingerprint(),
        materialized_layout_fingerprint=materialized_fp,
        result_fingerprint=result_fp,
    )


def _validate_checked_commit(
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
    checked: BusCheckedCommitResult,
    before_state: BusRouteStateSnapshot,
    after_state: BusRouteStateSnapshot,
) -> str | None:
    _validate_route_authority(authority)
    candidate = authority.candidate.candidate_result
    plan_input = authority.candidate.replay_input.composition.replay_input.plan.replay_input
    if checked.candidate_result != candidate or checked.candidate_result.bundle != authority.bundle:
        raise ValueError("checked result does not retain the physical candidate bundle")
    telemetry = checked.telemetry
    if (
        telemetry.bus_id != plan_input.bus.bus_id
        or telemetry.bus_fingerprint != plan_input.bus.semantic_fingerprint()
        or telemetry.allocation_fingerprint != plan_input.allocation.allocation_fingerprint
        or telemetry.candidate_result_fingerprint != authority.candidate_result_fingerprint
        or telemetry.candidate_call_count != 1
    ):
        raise ValueError("checked telemetry does not bind the physical authority")
    if (
        telemetry.ledger_before_fingerprint != before_state.ledger_fingerprint
        or telemetry.route_map_before_fingerprint != before_state.route_map_fingerprint
        or telemetry.ledger_after_fingerprint != after_state.ledger_fingerprint
        or telemetry.route_map_after_fingerprint != after_state.route_map_fingerprint
    ):
        raise ValueError("checked telemetry does not bind retained before/after state")

    member_nets = {member.net_name for member in plan_input.bus.members}
    before_routes = {route.result.net_name: route for route in before_state.routes}
    before_claims = {claim.net_name: claim for claim in before_state.claims}
    foreign_routes = {
        net_name: route for net_name, route in before_routes.items() if net_name not in member_nets
    }
    foreign_claims = {
        net_name: claim for net_name, claim in before_claims.items() if net_name not in member_nets
    }
    expected_initial = {claim.net_name: claim for claim in plan_input.initial_claims}
    if foreign_claims != expected_initial or set(foreign_routes) != set(expected_initial):
        raise ValueError("checked before-state does not strip to physical authority")

    if checked.exact_disposition is BusExactDisposition.ACCEPTED:
        expected_routes = {**foreign_routes, **authority.bundle.by_net()}
        expected_claims = {
            **foreign_claims,
            **{route.result.net_name: route.claims for route in authority.bundle.member_routes},
        }
        expected_after = BusRouteStateSnapshot.from_state(
            OccupancyLedger(tuple(expected_claims.values())),
            expected_routes,
        )
        if after_state != expected_after:
            raise ValueError("accepted physical checked commit retained stale route state")
    elif checked.exact_disposition in {
        BusExactDisposition.REJECTED,
        BusExactDisposition.CHECKER_MISSING,
    }:
        if after_state != before_state:
            raise ValueError("unaccepted physical checked commit did not restore exact state")
    else:
        raise ValueError("successful physical authority produced an invalid checked disposition")

    if checked.exact_disposition is BusExactDisposition.CHECKER_MISSING:
        if (
            checked.materialized_layout is not None
            or checked.checked_netlist is not None
            or checked.exact_check_evidence is not None
        ):
            raise ValueError("checker-missing physical result retained checked authority")
        return None

    layout = checked.materialized_layout
    if layout is None or checked.checked_netlist != plan_input.netlist:
        raise ValueError("checked physical result omitted exact layout or netlist authority")
    provisional_routes = {**foreign_routes, **authority.bundle.by_net()}
    expected_layout = materialize_complete_route_map(plan_input.layout, provisional_routes)
    if canonical_board_layout_snapshot_json(layout) != canonical_board_layout_snapshot_json(
        expected_layout
    ):
        raise ValueError("checked layout is not the exact complete physical route map")
    _require_materialized_physical_prefixes(layout, authority)
    layout_fp = board_layout_fingerprint(layout)
    if (
        checked.exact_check_evidence is None
        or checked.exact_check_evidence.materialized_layout_fingerprint != layout_fp
    ):
        raise ValueError("checked evidence does not bind the physical materialized layout")
    return layout_fp


def _require_materialized_physical_prefixes(
    layout: BoardLayout,
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
) -> None:
    """Bind every retained member identity to exact materialized prefix copper."""

    composition = authority.candidate.replay_input.composition
    members = {item.member_id: item for item in composition.members}
    bindings = {item.member_id: item for item in authority.member_bindings}
    if set(members) != set(bindings):
        raise ValueError("materialized physical bindings do not cover every composition member")
    segment_counts = Counter(_segment_key(item) for item in layout.segments)
    via_counts = Counter(_via_key(item) for item in layout.vias)
    for member_id in sorted(members):
        member = members[member_id]
        binding = bindings[member_id]
        if (
            binding.member_composition_fingerprint != member.composition_fingerprint
            or binding.prefix_alternative_id != member.prefix.alternative_id
            or binding.prefix_fingerprint != member.prefix_fingerprint
        ):
            raise ValueError("materialized member binding is stale")
        required_segments = Counter(_segment_key(item) for item in member.prefix.segments)
        required_vias = Counter(_via_key(item) for item in member.prefix.vias)
        if any(segment_counts[key] < count for key, count in required_segments.items()) or any(
            via_counts[key] < count for key, count in required_vias.items()
        ):
            raise ValueError("materialized layout omits or mutates physical-prefix copper")


def _segment_key(item: Any) -> tuple[Any, ...]:
    return (
        item.x1,
        item.y1,
        item.x2,
        item.y2,
        item.layer,
        item.net_name,
        item.width_mm,
    )


def _via_key(item: Any) -> tuple[Any, ...]:
    return (
        item.x,
        item.y,
        item.net_name,
        item.size_mm,
        item.drill_mm,
        item.front_mask.value,
        item.back_mask.value,
    )


def _checked_result_fingerprint(
    authority: ReplayBoundPhysicalSwapBusRouteBundle,
    checked: BusCheckedCommitResult,
    before_state: BusRouteStateSnapshot,
    after_state: BusRouteStateSnapshot,
    materialized_layout_fingerprint: str | None,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-physical-swap-bus-checked-commit-result",
            "schema_version": 1,
            "authority_fingerprint": authority.authority_fingerprint,
            "checked_result_fingerprint": checked.semantic_fingerprint(),
            "before_state_fingerprint": before_state.semantic_fingerprint(),
            "after_state_fingerprint": after_state.semantic_fingerprint(),
            "materialized_layout_fingerprint": materialized_layout_fingerprint,
        }
    )
