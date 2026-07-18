"""Pure negotiated-congestion kernel for ordinary routes and whole bus bundles.

The kernel owns no geometry search and never mutates the caller's ledger or
route map.  A search callback receives the current private occupancy state and
must return either one complete ordinary route, one complete bus bundle, or a
typed failure.  Bus members are always ripped up and installed together.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, TypeAlias

from pydantic import Field, field_validator, model_validator

from pcbsmith.kicad.bus_transaction import (
    BusRouteBundle,
    bus_route_map_fingerprint,
    negotiated_grid_route_fingerprint,
)
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.routing_ir import ResourceOveruseSummary, RoutingFailureReason, RoutingIrModel

Objective: TypeAlias = tuple[int, int, int, int]


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


class GroupTargetKind(StrEnum):
    ORDINARY = "ordinary"
    BUS = "bus"


class GroupNegotiationTargetRef(RoutingIrModel):
    """Versioned identity and indivisible net ownership for one target."""

    schema_id: str = "pcbsmith-group-negotiation-target"
    schema_version: int = 1
    target_id: str = Field(min_length=1)
    kind: GroupTargetKind
    net_names: tuple[str, ...] = Field(min_length=1)
    bus_fingerprint: str | None = None
    allocation_fingerprint: str | None = None

    @field_validator("bus_fingerprint", "allocation_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def identity_is_coherent(self) -> GroupNegotiationTargetRef:
        if self.schema_id != "pcbsmith-group-negotiation-target" or self.schema_version != 1:
            raise ValueError("unsupported group target schema")
        nets = tuple(sorted(set(self.net_names)))
        if len(nets) != len(self.net_names) or any(not item for item in nets):
            raise ValueError("target net_names must be unique and non-empty")
        if self.kind is GroupTargetKind.ORDINARY:
            if len(nets) != 1:
                raise ValueError("an ordinary target owns exactly one net")
            if self.bus_fingerprint is not None or self.allocation_fingerprint is not None:
                raise ValueError("ordinary targets cannot carry bus binding fingerprints")
        elif self.bus_fingerprint is None or self.allocation_fingerprint is None:
            raise ValueError("bus targets require bus and allocation fingerprints")
        object.__setattr__(self, "net_names", nets)
        return self


class GroupNegotiationBudget(RoutingIrModel):
    """Fixed deterministic work limits for one group-negotiation run."""

    max_passes: int = Field(ge=0)
    max_expansions: int = Field(ge=0)
    max_expansions_per_target: int = Field(ge=0)
    max_stagnant_passes: int = Field(ge=0)


@dataclass(frozen=True)
class GroupCandidateContext:
    """Search input.  ``ledger`` is private to this run and read-only by contract."""

    target: GroupNegotiationTargetRef
    pass_index: int
    attempt_index: int
    ledger: OccupancyLedger
    ledger_fingerprint: str
    history: Mapping[RoutingResourceKey, int]
    present_factor_units: int
    remaining_expansions: int
    maximum_attempt_expansions: int


@dataclass(frozen=True)
class OrdinaryGroupCandidate:
    target: GroupNegotiationTargetRef
    route: NegotiatedGridRoute
    expansion_count: int


@dataclass(frozen=True)
class BusGroupCandidate:
    target: GroupNegotiationTargetRef
    bundle: BusRouteBundle
    expansion_count: int


@dataclass(frozen=True)
class GroupCandidateFailure:
    target: GroupNegotiationTargetRef
    failure_reason: RoutingFailureReason
    expansion_count: int
    failure_code: str

    def __post_init__(self) -> None:
        if not self.failure_code:
            raise ValueError("failure_code must be non-empty")


GroupCandidateOutcome: TypeAlias = (
    OrdinaryGroupCandidate | BusGroupCandidate | GroupCandidateFailure
)


class GroupCandidateSearch(Protocol):
    def __call__(self, context: GroupCandidateContext) -> GroupCandidateOutcome: ...


class GroupAttemptDisposition(StrEnum):
    INSTALLED = "installed"
    FAILED = "failed"


class GroupRunDisposition(StrEnum):
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    BUDGET_EXHAUSTED = "budget_exhausted"


class GroupAttemptTelemetry(RoutingIrModel):
    pass_index: int = Field(ge=0)
    attempt_index: int = Field(ge=0)
    target_id: str = Field(min_length=1)
    target_kind: GroupTargetKind
    net_names: tuple[str, ...] = Field(min_length=1)
    disposition: GroupAttemptDisposition
    expansion_count: int = Field(ge=0)
    candidate_fingerprint: str | None = None
    base_cost_units: int = Field(default=0, ge=0)
    congestion_cost_units: int = Field(default=0, ge=0)
    ledger_before_fingerprint: str
    ledger_after_fingerprint: str
    failure_reason: RoutingFailureReason | None = None
    failure_code: str | None = None

    @field_validator(
        "candidate_fingerprint", "ledger_before_fingerprint", "ledger_after_fingerprint"
    )
    @classmethod
    def attempt_fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> GroupAttemptTelemetry:
        nets = tuple(sorted(set(self.net_names)))
        if nets != self.net_names:
            raise ValueError("attempt net names must be sorted and unique")
        if self.disposition is GroupAttemptDisposition.INSTALLED:
            if self.candidate_fingerprint is None:
                raise ValueError("installed attempts require a candidate fingerprint")
            if self.failure_reason is not None or self.failure_code is not None:
                raise ValueError("installed attempts cannot retain a failure")
        else:
            if self.failure_reason is None or not self.failure_code:
                raise ValueError("failed attempts require a typed failure")
            if self.candidate_fingerprint is not None:
                raise ValueError("failed attempts cannot retain a candidate")
            if self.ledger_before_fingerprint != self.ledger_after_fingerprint:
                raise ValueError("failed attempts must restore exact private occupancy")
        return self


class GroupPassTelemetry(RoutingIrModel):
    pass_index: int = Field(ge=0)
    route_order: tuple[str, ...] = Field(min_length=1)
    attempts: tuple[GroupAttemptTelemetry, ...] = Field(min_length=1)
    unresolved_target_ids: tuple[str, ...] = ()
    resource_overuse: tuple[ResourceOveruseSummary, ...] = ()
    objective: Objective
    history_fingerprint: str
    resource_fingerprint: str
    present_factor_units: int = Field(ge=0)
    expansion_count: int = Field(ge=0)
    stagnant: bool = False

    @field_validator("history_fingerprint", "resource_fingerprint")
    @classmethod
    def pass_fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def summary_is_coherent(self) -> GroupPassTelemetry:
        if len(set(self.route_order)) != len(self.route_order):
            raise ValueError("pass route_order must be unique")
        if tuple(item.attempt_index for item in self.attempts) != tuple(
            range(len(self.attempts))
        ):
            raise ValueError("pass attempt indices must be consecutive")
        if tuple(item.target_id for item in self.attempts) != self.route_order:
            raise ValueError("pass attempts must follow route_order")
        if any(item.pass_index != self.pass_index for item in self.attempts):
            raise ValueError("attempt pass indices must match their pass")
        if self.expansion_count != sum(item.expansion_count for item in self.attempts):
            raise ValueError("pass expansion count must equal attempt work")
        if tuple(sorted(set(self.unresolved_target_ids))) != self.unresolved_target_ids:
            raise ValueError("unresolved target IDs must be sorted and unique")
        if self.objective != _objective(self.resource_overuse, len(self.unresolved_target_ids)):
            raise ValueError("pass objective must match capacity overuse")
        return self


@dataclass(frozen=True)
class GroupNegotiationResult:
    """Final private route state plus versioned deterministic run telemetry."""

    success: bool
    failure_reason: RoutingFailureReason | None
    disposition: GroupRunDisposition
    budget: GroupNegotiationBudget
    baseline_order: tuple[str, ...]
    target_refs: tuple[GroupNegotiationTargetRef, ...]
    passes: tuple[GroupPassTelemetry, ...]
    routes_by_net: tuple[tuple[str, NegotiatedGridRoute], ...]
    bus_bundles: tuple[tuple[str, BusRouteBundle], ...]
    unresolved_target_ids: tuple[str, ...]
    resource_overuse: tuple[ResourceOveruseSummary, ...]
    objective: Objective
    total_expansions: int
    final_ledger_fingerprint: str
    final_route_map_fingerprint: str

    def route_map(self) -> dict[str, NegotiatedGridRoute]:
        return dict(self.routes_by_net)

    def bundle_map(self) -> dict[str, BusRouteBundle]:
        return dict(self.bus_bundles)

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "schema_id": "pcbsmith-group-negotiation-run",
            "schema_version": 1,
            "success": self.success,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "disposition": self.disposition.value,
            "budget": self.budget.model_dump(mode="json"),
            "baseline_order": list(self.baseline_order),
            "targets": [item.model_dump(mode="json") for item in self.target_refs],
            "passes": [item.model_dump(mode="json") for item in self.passes],
            "routes": [
                [name, negotiated_grid_route_fingerprint(route)]
                for name, route in self.routes_by_net
            ],
            "bus_bundles": [
                [target_id, bundle.semantic_fingerprint()]
                for target_id, bundle in self.bus_bundles
            ],
            "unresolved_target_ids": list(self.unresolved_target_ids),
            "resource_overuse": [item.model_dump(mode="json") for item in self.resource_overuse],
            "objective": list(self.objective),
            "total_expansions": self.total_expansions,
            "final_ledger_fingerprint": self.final_ledger_fingerprint,
            "final_route_map_fingerprint": self.final_route_map_fingerprint,
        }

    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.semantic_payload())


def negotiate_route_groups(
    targets: Sequence[GroupNegotiationTargetRef],
    ledger: OccupancyLedger,
    routes_by_net: Mapping[str, NegotiatedGridRoute],
    search: Callable[[GroupCandidateContext], GroupCandidateOutcome],
    *,
    budget: GroupNegotiationBudget,
    baseline_order: Sequence[str] | None = None,
    policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
) -> GroupNegotiationResult:
    """Negotiate ordinary routes and complete bus bundles on a private clone."""

    target_by_id, order, net_to_target = _normalize_targets(targets, baseline_order)
    _validate_initial_state(target_by_id, ledger, routes_by_net)
    original_claims = ledger.committed_claims()
    original_routes = dict(routes_by_net)
    private_ledger = OccupancyLedger(original_claims)
    private_routes = dict(original_routes)
    original_ledger_fingerprint = ledger.semantic_fingerprint()
    original_route_fingerprint = bus_route_map_fingerprint(routes_by_net)
    for net_name in sorted(net_to_target):
        private_ledger.rip_up(net_name)
        private_routes.pop(net_name, None)

    history: dict[RoutingResourceKey, int] = {}
    resource_by_id: dict[str, RoutingResourceKey] = {
        resource.resource_id: resource
        for claims in ledger.committed_claims()
        for resource in claims.resources
    }
    chosen_bundles: dict[str, BusRouteBundle] = {}
    passes: list[GroupPassTelemetry] = []
    total_expansions = 0
    present_factor = policy.present_factor_units
    best_objective: Objective | None = None
    stagnant_count = 0

    if budget.max_passes == 0:
        _ensure_caller_unchanged(
            ledger,
            routes_by_net,
            original_claims,
            original_routes,
            original_ledger_fingerprint,
            original_route_fingerprint,
        )
        return _empty_budget_result(
            budget, order, target_by_id, ledger, routes_by_net
        )

    route_order = order
    while len(passes) < budget.max_passes:
        pass_index = len(passes)
        if pass_index:
            present_factor = _grow_present_factor(present_factor, policy)
        attempts: list[GroupAttemptTelemetry] = []
        pass_failed: RoutingFailureReason | None = None
        for attempt_index, target_id in enumerate(route_order):
            target = target_by_id[target_id]
            before_claims = private_ledger.committed_claims()
            before_routes = dict(private_routes)
            before_bundles = dict(chosen_bundles)
            before_fingerprint = private_ledger.semantic_fingerprint()
            for net_name in target.net_names:
                private_ledger.rip_up(net_name)
                private_routes.pop(net_name, None)
            chosen_bundles.pop(target_id, None)
            search_fingerprint = private_ledger.semantic_fingerprint()
            remaining = budget.max_expansions - total_expansions
            context = GroupCandidateContext(
                target=target,
                pass_index=pass_index,
                attempt_index=attempt_index,
                ledger=private_ledger,
                ledger_fingerprint=search_fingerprint,
                history=dict(history),
                present_factor_units=present_factor,
                remaining_expansions=max(0, remaining),
                maximum_attempt_expansions=min(
                    max(0, remaining), budget.max_expansions_per_target
                ),
            )
            try:
                outcome = search(context)
            except Exception as error:
                _restore_state(private_ledger, private_routes, original_claims, original_routes)
                chosen_bundles.clear()
                _ensure_caller_unchanged(
                    ledger,
                    routes_by_net,
                    original_claims,
                    original_routes,
                    original_ledger_fingerprint,
                    original_route_fingerprint,
                    cause=error,
                )
                raise
            if private_ledger.semantic_fingerprint() != search_fingerprint:
                _restore_state(private_ledger, private_routes, original_claims, original_routes)
                chosen_bundles.clear()
                raise ValueError("group search callback mutated its read-only occupancy ledger")
            try:
                _ensure_caller_unchanged(
                    ledger,
                    routes_by_net,
                    original_claims,
                    original_routes,
                    original_ledger_fingerprint,
                    original_route_fingerprint,
                )
            except Exception:
                _restore_state(private_ledger, private_routes, original_claims, original_routes)
                chosen_bundles.clear()
                raise

            try:
                _validate_outcome(outcome, target)
            except Exception:
                _restore_state(private_ledger, private_routes, original_claims, original_routes)
                chosen_bundles.clear()
                raise
            work = outcome.expansion_count
            if work > budget.max_expansions_per_target or work > (
                budget.max_expansions - total_expansions
            ):
                _restore_state(private_ledger, private_routes, original_claims, original_routes)
                chosen_bundles.clear()
                raise ValueError(
                    f"callback reported {work} expansions beyond its fixed attempt/run budget"
                )
            total_expansions += work
            if isinstance(outcome, GroupCandidateFailure):
                _restore_state(private_ledger, private_routes, before_claims, before_routes)
                chosen_bundles.clear()
                chosen_bundles.update(before_bundles)
                attempts.append(
                    GroupAttemptTelemetry(
                        pass_index=pass_index,
                        attempt_index=attempt_index,
                        target_id=target_id,
                        target_kind=target.kind,
                        net_names=target.net_names,
                        disposition=GroupAttemptDisposition.FAILED,
                        expansion_count=work,
                        ledger_before_fingerprint=before_fingerprint,
                        ledger_after_fingerprint=private_ledger.semantic_fingerprint(),
                        failure_reason=outcome.failure_reason,
                        failure_code=outcome.failure_code,
                    )
                )
                pass_failed = outcome.failure_reason
                break

            candidate_routes, candidate_fingerprint = _candidate_routes(outcome)
            base_cost = sum(
                route.base_cost_units + route.guidance_cost_units
                for route in candidate_routes.values()
            )
            congestion_cost = _candidate_congestion(
                candidate_routes,
                private_ledger,
                history,
                present_factor,
            )
            for net_name in sorted(candidate_routes):
                route = candidate_routes[net_name]
                private_ledger.commit(route.claims)
                private_routes[net_name] = route
                for resource in route.claims.resources:
                    resource_by_id[resource.resource_id] = resource
            if isinstance(outcome, BusGroupCandidate):
                chosen_bundles[target_id] = outcome.bundle
            attempts.append(
                GroupAttemptTelemetry(
                    pass_index=pass_index,
                    attempt_index=attempt_index,
                    target_id=target_id,
                    target_kind=target.kind,
                    net_names=target.net_names,
                    disposition=GroupAttemptDisposition.INSTALLED,
                    expansion_count=work,
                    candidate_fingerprint=candidate_fingerprint,
                    base_cost_units=base_cost,
                    congestion_cost_units=congestion_cost,
                    ledger_before_fingerprint=before_fingerprint,
                    ledger_after_fingerprint=private_ledger.semantic_fingerprint(),
                )
            )

        if pass_failed is not None:
            # The pass record describes the real attempted private state after
            # the failed target's atomic attempt rollback.  Only the final run
            # state is then rolled back to the complete entry snapshot.
            overuse = private_ledger.overuse()
            unresolved = _unresolved_target_ids(target_by_id, private_routes)
            objective = _objective(overuse, len(unresolved))
            route_order_for_pass = tuple(item.target_id for item in attempts)
            pass_record = _make_pass(
                pass_index,
                route_order_for_pass,
                attempts,
                overuse,
                objective,
                history,
                private_ledger,
                present_factor,
                unresolved_target_ids=unresolved,
                stagnant=False,
            )
            passes.append(pass_record)
            _restore_state(private_ledger, private_routes, original_claims, original_routes)
            chosen_bundles.clear()
            return _finish(
                False,
                pass_failed,
                budget,
                order,
                target_by_id,
                passes,
                private_ledger,
                private_routes,
                chosen_bundles,
                total_expansions,
                disposition=GroupRunDisposition.ROLLED_BACK,
            )

        overuse = private_ledger.overuse()
        unresolved = _unresolved_target_ids(target_by_id, private_routes)
        objective = _objective(overuse, len(unresolved))
        stagnant = best_objective is not None and objective >= best_objective
        if best_objective is None or objective < best_objective:
            best_objective = objective
            stagnant_count = 0
        elif stagnant:
            stagnant_count += 1
        _update_history(history, overuse, resource_by_id, policy)
        passes.append(
            _make_pass(
                pass_index,
                route_order,
                attempts,
                overuse,
                objective,
                history,
                private_ledger,
                present_factor,
                unresolved_target_ids=unresolved,
                stagnant=stagnant,
            )
        )
        if not overuse:
            return _finish(
                True, None, budget, order, target_by_id, passes, private_ledger,
                private_routes, chosen_bundles, total_expansions,
                disposition=GroupRunDisposition.COMPLETED,
            )
        if budget.max_stagnant_passes == 0:
            return _finish(
                False, RoutingFailureReason.OVERUSE_REMAINING, budget, order,
                target_by_id, passes, private_ledger, private_routes,
                chosen_bundles, total_expansions,
            )
        if stagnant and stagnant_count >= budget.max_stagnant_passes:
            return _finish(
                False, RoutingFailureReason.STAGNATION, budget, order,
                target_by_id, passes, private_ledger, private_routes,
                chosen_bundles, total_expansions,
            )
        if total_expansions >= budget.max_expansions:
            return _finish(
                False, RoutingFailureReason.EXPANSION_BUDGET, budget, order,
                target_by_id, passes, private_ledger, private_routes,
                chosen_bundles, total_expansions,
            )
        route_order = _reroute_order(overuse, order, target_by_id, net_to_target)

    return _finish(
        False, RoutingFailureReason.PASS_BUDGET, budget, order, target_by_id,
        passes, private_ledger, private_routes, chosen_bundles, total_expansions,
    )


def _normalize_targets(
    targets: Sequence[GroupNegotiationTargetRef],
    baseline_order: Sequence[str] | None,
) -> tuple[
    dict[str, GroupNegotiationTargetRef], tuple[str, ...], dict[str, str]
]:
    if not targets:
        raise ValueError("at least one negotiation target is required")
    by_id: dict[str, GroupNegotiationTargetRef] = {}
    net_to_target: dict[str, str] = {}
    for target in targets:
        if target.target_id in by_id:
            raise ValueError("group target IDs must be unique")
        by_id[target.target_id] = target
        for net_name in target.net_names:
            if net_name in net_to_target:
                raise ValueError("group target member-net sets must be disjoint")
            net_to_target[net_name] = target.target_id
    if baseline_order is None:
        order = tuple(sorted(by_id))
    else:
        order = tuple(baseline_order)
        if len(set(order)) != len(order) or set(order) != set(by_id):
            raise ValueError("baseline_order must contain each target exactly once")
    return by_id, order, net_to_target


def _validate_initial_state(
    targets: Mapping[str, GroupNegotiationTargetRef],
    ledger: OccupancyLedger,
    routes: Mapping[str, NegotiatedGridRoute],
) -> None:
    for target in targets.values():
        present = set(target.net_names).intersection(routes)
        if present and present != set(target.net_names):
            raise ValueError(
                "a warm-start target must have either every member route or no member routes"
            )
    for net_name, route in routes.items():
        if route.result.net_name != net_name or route.claims.net_name != net_name:
            raise ValueError("route-map keys must match complete route ownership")
        if ledger.claims_for(net_name) != route.claims:
            raise ValueError("ledger claims must match the current route map")


def _validate_outcome(
    outcome: GroupCandidateOutcome, target: GroupNegotiationTargetRef
) -> None:
    if outcome.target.semantic_fingerprint() != target.semantic_fingerprint():
        raise ValueError("candidate outcome binds a different group target")
    if not isinstance(outcome.expansion_count, int) or isinstance(
        outcome.expansion_count, bool
    ) or outcome.expansion_count < 0:
        raise ValueError("candidate expansion_count must be a non-negative integer")
    if isinstance(outcome, OrdinaryGroupCandidate):
        if target.kind is not GroupTargetKind.ORDINARY:
            raise ValueError("ordinary candidate returned for a bus target")
        if outcome.route.result.net_name != target.net_names[0]:
            raise ValueError("ordinary candidate owns the wrong net")
    elif isinstance(outcome, BusGroupCandidate):
        if target.kind is not GroupTargetKind.BUS:
            raise ValueError("bus candidate returned for an ordinary target")
        if outcome.bundle.bus.semantic_fingerprint() != target.bus_fingerprint:
            raise ValueError("bus candidate binds the wrong bus")
        if outcome.bundle.allocation.allocation_fingerprint != target.allocation_fingerprint:
            raise ValueError("bus candidate binds the wrong lane allocation")
        if set(outcome.bundle.by_net()) != set(target.net_names):
            raise ValueError("bus candidate must contain every target member exactly once")


def _candidate_routes(
    outcome: OrdinaryGroupCandidate | BusGroupCandidate,
) -> tuple[dict[str, NegotiatedGridRoute], str]:
    if isinstance(outcome, OrdinaryGroupCandidate):
        route = outcome.route
        return {route.result.net_name: route}, negotiated_grid_route_fingerprint(route)
    return outcome.bundle.by_net(), outcome.bundle.semantic_fingerprint()


def _candidate_congestion(
    routes: Mapping[str, NegotiatedGridRoute],
    ledger: OccupancyLedger,
    history: Mapping[RoutingResourceKey, int],
    present_factor: int,
) -> int:
    # A resource used by multiple members of one indivisible bus is charged once
    # as target congestion, while every distinct pairwise-domain key stays distinct.
    resources = {resource for route in routes.values() for resource in route.claims.resources}
    return sum(
        present_factor * max(0, ledger.demand_without(resource, "") + 1 - ledger.capacity)
        + history.get(resource, 0)
        for resource in resources
    )


def _objective(
    overuse: tuple[ResourceOveruseSummary, ...], unresolved_target_count: int = 0
) -> Objective:
    values = tuple(item.overuse_units for item in overuse)
    return (unresolved_target_count, sum(values), len(values), max(values, default=0))


def _update_history(
    history: dict[RoutingResourceKey, int],
    overuse: tuple[ResourceOveruseSummary, ...],
    resource_by_id: Mapping[str, RoutingResourceKey],
    policy: NegotiatedCostPolicy,
) -> None:
    for item in overuse:
        resource = resource_by_id[item.resource_id]
        history[resource] = history.get(resource, 0) + (
            policy.history_increment_units * item.overuse_units
        )


def _history_fingerprint(history: Mapping[RoutingResourceKey, int]) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-group-negotiation-history",
            "schema_version": 1,
            "costs": [
                [resource.resource_id, value]
                for resource, value in sorted(history.items())
                if value > 0
            ],
        }
    )


def _grow_present_factor(current: int, policy: NegotiatedCostPolicy) -> int:
    numerator = current * policy.present_growth_numerator
    return (numerator + policy.present_growth_denominator - 1) // (
        policy.present_growth_denominator
    )


def _reroute_order(
    overuse: tuple[ResourceOveruseSummary, ...],
    baseline: tuple[str, ...],
    targets: Mapping[str, GroupNegotiationTargetRef],
    net_to_target: Mapping[str, str],
) -> tuple[str, ...]:
    # Each overused resource contributes at most one conflict point per target,
    # regardless of how many of that bus's members own it.
    scores = {target_id: 0 for target_id in baseline}
    for item in overuse:
        touched = {net_to_target[net] for net in item.net_names if net in net_to_target}
        for target_id in touched:
            scores[target_id] += item.overuse_units
    rank = {target_id: index for index, target_id in enumerate(baseline)}
    return tuple(
        sorted(
            targets,
            key=lambda target_id: (-scores[target_id], rank[target_id], target_id),
        )
    )


def _restore_state(
    ledger: OccupancyLedger,
    routes: dict[str, NegotiatedGridRoute],
    claims: tuple[NetResourceClaims, ...],
    old_routes: Mapping[str, NegotiatedGridRoute],
) -> None:
    for current in ledger.committed_claims():
        ledger.rip_up(current.net_name)
    for item in claims:
        ledger.restore(item)
    routes.clear()
    routes.update(old_routes)


def _make_pass(
    pass_index: int,
    route_order: tuple[str, ...],
    attempts: Sequence[GroupAttemptTelemetry],
    overuse: tuple[ResourceOveruseSummary, ...],
    objective: Objective,
    history: Mapping[RoutingResourceKey, int],
    ledger: OccupancyLedger,
    present_factor: int,
    *,
    unresolved_target_ids: tuple[str, ...] = (),
    stagnant: bool,
) -> GroupPassTelemetry:
    return GroupPassTelemetry(
        pass_index=pass_index,
        route_order=route_order,
        attempts=tuple(attempts),
        unresolved_target_ids=unresolved_target_ids,
        resource_overuse=overuse,
        objective=objective,
        history_fingerprint=_history_fingerprint(history),
        resource_fingerprint=ledger.semantic_fingerprint(),
        present_factor_units=present_factor,
        expansion_count=sum(item.expansion_count for item in attempts),
        stagnant=stagnant,
    )


def _finish(
    success: bool,
    failure_reason: RoutingFailureReason | None,
    budget: GroupNegotiationBudget,
    order: tuple[str, ...],
    targets: Mapping[str, GroupNegotiationTargetRef],
    passes: Sequence[GroupPassTelemetry],
    ledger: OccupancyLedger,
    routes: Mapping[str, NegotiatedGridRoute],
    bundles: Mapping[str, BusRouteBundle],
    total_expansions: int,
    *,
    disposition: GroupRunDisposition = GroupRunDisposition.BUDGET_EXHAUSTED,
) -> GroupNegotiationResult:
    overuse = ledger.overuse()
    unresolved = _unresolved_target_ids(targets, routes)
    return GroupNegotiationResult(
        success=success,
        failure_reason=failure_reason,
        disposition=disposition,
        budget=budget,
        baseline_order=order,
        target_refs=tuple(targets[target_id] for target_id in sorted(targets)),
        passes=tuple(passes),
        routes_by_net=tuple(sorted(routes.items())),
        bus_bundles=tuple(sorted(bundles.items())),
        unresolved_target_ids=unresolved,
        resource_overuse=overuse,
        objective=_objective(overuse, len(unresolved)),
        total_expansions=total_expansions,
        final_ledger_fingerprint=ledger.semantic_fingerprint(),
        final_route_map_fingerprint=bus_route_map_fingerprint(routes),
    )


def _empty_budget_result(
    budget: GroupNegotiationBudget,
    order: tuple[str, ...],
    targets: Mapping[str, GroupNegotiationTargetRef],
    ledger: OccupancyLedger,
    routes: Mapping[str, NegotiatedGridRoute],
) -> GroupNegotiationResult:
    return GroupNegotiationResult(
        success=False,
        failure_reason=RoutingFailureReason.PASS_BUDGET,
        disposition=GroupRunDisposition.BUDGET_EXHAUSTED,
        budget=budget,
        baseline_order=order,
        target_refs=tuple(targets[target_id] for target_id in sorted(targets)),
        passes=(),
        routes_by_net=tuple(sorted(routes.items())),
        bus_bundles=(),
        unresolved_target_ids=_unresolved_target_ids(targets, routes),
        resource_overuse=ledger.overuse(),
        objective=_objective(
            ledger.overuse(), len(_unresolved_target_ids(targets, routes))
        ),
        total_expansions=0,
        final_ledger_fingerprint=ledger.semantic_fingerprint(),
        final_route_map_fingerprint=bus_route_map_fingerprint(routes),
    )



def _ensure_caller_unchanged(
    ledger: OccupancyLedger,
    routes: Mapping[str, NegotiatedGridRoute],
    original_claims: tuple[NetResourceClaims, ...],
    original_routes: Mapping[str, NegotiatedGridRoute],
    expected_ledger_fingerprint: str,
    expected_route_fingerprint: str,
    *,
    cause: BaseException | None = None,
) -> None:
    try:
        route_changed = bus_route_map_fingerprint(routes) != expected_route_fingerprint
    except Exception:
        route_changed = True
    ledger_changed = ledger.semantic_fingerprint() != expected_ledger_fingerprint
    if not ledger_changed and not route_changed:
        return

    for claims in ledger.committed_claims():
        ledger.rip_up(claims.net_name)
    for claims in original_claims:
        ledger.restore(claims)
    route_restored = not route_changed
    if route_changed and isinstance(routes, MutableMapping):
        routes.clear()
        routes.update(original_routes)
        route_restored = True
    restored = (
        ledger.semantic_fingerprint() == expected_ledger_fingerprint
        and route_restored
        and bus_route_map_fingerprint(routes) == expected_route_fingerprint
    )
    message = "search callback mutated caller-owned ledger or route map"
    if not restored:
        message += "; exact caller route-map restoration was not possible"
    error = RuntimeError(message)
    if cause is None:
        raise error
    raise error from cause



def _unresolved_target_ids(
    targets: Mapping[str, GroupNegotiationTargetRef],
    routes: Mapping[str, NegotiatedGridRoute],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            target_id
            for target_id, target in targets.items()
            if not set(target.net_names).issubset(routes)
        )
    )
