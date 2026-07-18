"""Deterministic negotiated-congestion search over candidate resource graphs.

This is the R2.2a proof kernel.  It selects complete candidate routes against
the capacity-one ledger without depending on KiCad grid geometry.  A later grid
adapter may produce the same ``CandidateRoute`` values from A* searches.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.routing_ir import ResourceOveruseSummary, RoutingFailureReason


def _require_non_negative_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _require_positive_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


def _semantic_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_semantic_json(payload).encode("utf-8")).hexdigest()


def _overuse_payload(
    overuse: tuple[ResourceOveruseSummary, ...],
) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in overuse]


@dataclass(frozen=True)
class CandidateRoute:
    """One indivisible route candidate for one net."""

    net_name: str
    candidate_id: str
    base_cost_units: int
    resources: frozenset[RoutingResourceKey]

    def __post_init__(self) -> None:
        if not self.net_name:
            raise ValueError("candidate net_name must be non-empty")
        if not self.candidate_id:
            raise ValueError("candidate_id must be non-empty")
        _require_non_negative_int(self.base_cost_units, "base_cost_units")
        canonical = frozenset(self.resources)
        if not canonical:
            raise ValueError("a candidate route must claim at least one resource")
        if any(not isinstance(item, RoutingResourceKey) for item in canonical):
            raise TypeError("candidate resources must be RoutingResourceKey values")
        object.__setattr__(self, "resources", canonical)

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "net_name": self.net_name,
            "candidate_id": self.candidate_id,
            "base_cost_units": self.base_cost_units,
            "resource_ids": sorted(item.resource_id for item in self.resources),
        }

    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.semantic_payload())


@dataclass(frozen=True)
class NegotiatedCostPolicy:
    """Fixed integer costs; geometry fields are reserved for the grid adapter."""

    length_units_per_grid: int = 1000
    diagonal_length_units: int = 1414
    via_cost_units: int = 5000
    turn_cost_units: int = 100
    present_factor_units: int = 1
    present_growth_numerator: int = 2
    present_growth_denominator: int = 1
    history_increment_units: int = 4

    def __post_init__(self) -> None:
        for field in (
            "length_units_per_grid",
            "diagonal_length_units",
            "via_cost_units",
            "present_growth_numerator",
            "present_growth_denominator",
            "history_increment_units",
        ):
            _require_positive_int(getattr(self, field), field)
        _require_non_negative_int(self.turn_cost_units, "turn_cost_units")
        _require_non_negative_int(self.present_factor_units, "present_factor_units")

    def semantic_payload(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


DEFAULT_NEGOTIATED_COST_POLICY = NegotiatedCostPolicy()


@dataclass(frozen=True)
class ChosenCandidate:
    net_name: str
    candidate_id: str
    base_cost_units: int
    congestion_cost_units: int
    total_cost_units: int
    resource_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.net_name or not self.candidate_id:
            raise ValueError("chosen candidate identities must be non-empty")
        for field in (
            "base_cost_units",
            "congestion_cost_units",
            "total_cost_units",
        ):
            _require_non_negative_int(getattr(self, field), field)
        if self.total_cost_units != (self.base_cost_units + self.congestion_cost_units):
            raise ValueError("total candidate cost must equal base plus congestion")
        if tuple(sorted(set(self.resource_ids))) != self.resource_ids:
            raise ValueError("chosen resource_ids must be sorted and unique")
        if not self.resource_ids:
            raise ValueError("chosen candidate must claim at least one resource")

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "net_name": self.net_name,
            "candidate_id": self.candidate_id,
            "base_cost_units": self.base_cost_units,
            "congestion_cost_units": self.congestion_cost_units,
            "total_cost_units": self.total_cost_units,
            "resource_ids": list(self.resource_ids),
        }


Objective = tuple[int, int, int, int]


@dataclass(frozen=True)
class NegotiatedGraphPass:
    pass_index: int
    route_order: tuple[str, ...]
    chosen_candidates: tuple[ChosenCandidate, ...]
    resource_overuse: tuple[ResourceOveruseSummary, ...]
    objective: Objective
    history_fingerprint: str
    resource_fingerprint: str
    stagnant: bool
    present_factor_units: int

    def __post_init__(self) -> None:
        _require_non_negative_int(self.pass_index, "pass_index")
        _require_non_negative_int(self.present_factor_units, "present_factor_units")
        if not self.route_order or len(set(self.route_order)) != len(self.route_order):
            raise ValueError("pass route_order must contain unique non-empty nets")
        choice_nets = tuple(item.net_name for item in self.chosen_candidates)
        if tuple(sorted(choice_nets)) != choice_nets or len(set(choice_nets)) != len(choice_nets):
            raise ValueError("chosen candidates must be unique and sorted by net")
        if set(self.route_order) != set(choice_nets):
            raise ValueError("pass route_order must contain every chosen net exactly once")
        if len(self.objective) != 4 or any(value < 0 for value in self.objective):
            raise ValueError("routing objective must contain four non-negative values")
        expected = _objective(self.resource_overuse)
        if self.objective != expected:
            raise ValueError("pass objective must match resource overuse")
        for value in (self.history_fingerprint, self.resource_fingerprint):
            if len(value) != 64:
                raise ValueError("pass fingerprints must be SHA-256 hex digests")

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "pass_index": self.pass_index,
            "route_order": list(self.route_order),
            "chosen_candidates": [item.semantic_payload() for item in self.chosen_candidates],
            "resource_overuse": _overuse_payload(self.resource_overuse),
            "objective": list(self.objective),
            "history_fingerprint": self.history_fingerprint,
            "resource_fingerprint": self.resource_fingerprint,
            "stagnant": self.stagnant,
            "present_factor_units": self.present_factor_units,
        }

    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.semantic_payload())


@dataclass(frozen=True)
class NegotiatedGraphResult:
    schema_id: str
    schema_version: int
    success: bool
    failure_reason: RoutingFailureReason | None
    baseline_order: tuple[str, ...]
    chosen_candidates: tuple[ChosenCandidate, ...]
    passes: tuple[NegotiatedGraphPass, ...]
    resource_overuse: tuple[ResourceOveruseSummary, ...]
    objective: Objective
    history_fingerprint: str
    resource_fingerprint: str
    present_factor_units: int
    max_passes: int
    max_stagnant_passes: int
    policy: NegotiatedCostPolicy

    def __post_init__(self) -> None:
        if self.schema_id != "pcbsmith-negotiated-candidate-graph":
            raise ValueError("unexpected negotiated graph schema_id")
        if self.schema_version != 1:
            raise ValueError("unexpected negotiated graph schema_version")
        _require_positive_int(self.max_passes, "max_passes")
        _require_non_negative_int(self.max_stagnant_passes, "max_stagnant_passes")
        if (
            not self.baseline_order
            or len(set(self.baseline_order)) != len(self.baseline_order)
            or any(not net_name for net_name in self.baseline_order)
        ):
            raise ValueError("baseline_order must contain unique non-empty nets")
        if not self.passes or len(self.passes) > self.max_passes:
            raise ValueError("result must contain passes within its fixed budget")
        if tuple(item.pass_index for item in self.passes) != tuple(range(len(self.passes))):
            raise ValueError("pass indices must be consecutive from zero")
        if self.chosen_candidates != self.passes[-1].chosen_candidates:
            raise ValueError("result choices must match the final pass")
        if set(self.baseline_order) != {item.net_name for item in self.chosen_candidates}:
            raise ValueError("result choices must contain every baseline net exactly once")
        if any(set(item.route_order) != set(self.baseline_order) for item in self.passes):
            raise ValueError("every pass must contain exactly the baseline net set")
        if self.resource_overuse != self.passes[-1].resource_overuse:
            raise ValueError("result overuse must match the final pass")
        if self.objective != self.passes[-1].objective:
            raise ValueError("result objective must match the final pass")
        if self.history_fingerprint != self.passes[-1].history_fingerprint:
            raise ValueError("result history must match the final pass")
        if self.resource_fingerprint != self.passes[-1].resource_fingerprint:
            raise ValueError("result resources must match the final pass")
        if self.present_factor_units != self.passes[-1].present_factor_units:
            raise ValueError("result present factor must match the final pass")
        if self.success:
            if self.failure_reason is not None or self.resource_overuse:
                raise ValueError("successful negotiation requires zero overuse")
        elif self.failure_reason is None:
            raise ValueError("failed negotiation requires a typed reason")

    @property
    def assignment(self) -> dict[str, str]:
        return {item.net_name: item.candidate_id for item in self.chosen_candidates}

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "success": self.success,
            "failure_reason": (
                self.failure_reason.value if self.failure_reason is not None else None
            ),
            "baseline_order": list(self.baseline_order),
            "chosen_candidates": [item.semantic_payload() for item in self.chosen_candidates],
            "passes": [item.semantic_payload() for item in self.passes],
            "resource_overuse": _overuse_payload(self.resource_overuse),
            "objective": list(self.objective),
            "history_fingerprint": self.history_fingerprint,
            "resource_fingerprint": self.resource_fingerprint,
            "present_factor_units": self.present_factor_units,
            "max_passes": self.max_passes,
            "max_stagnant_passes": self.max_stagnant_passes,
            "policy": self.policy.semantic_payload(),
        }

    def semantic_json(self) -> str:
        return _semantic_json(self.semantic_payload())

    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.semantic_payload())


def negotiate_candidate_routes(
    candidates: Mapping[str, Iterable[CandidateRoute]],
    *,
    baseline_order: Sequence[str] | None = None,
    max_passes: int = 16,
    max_stagnant_passes: int = 8,
    policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
) -> NegotiatedGraphResult:
    """Negotiate complete candidate routes against capacity-one resources."""
    _require_positive_int(max_passes, "max_passes")
    _require_non_negative_int(max_stagnant_passes, "max_stagnant_passes")
    by_net = _normalize_candidates(candidates)
    order = _normalize_order(by_net, baseline_order)
    rank = {net_name: index for index, net_name in enumerate(order)}
    resource_by_id = {
        resource.resource_id: resource
        for routes in by_net.values()
        for route in routes
        for resource in route.resources
    }

    ledger = OccupancyLedger()
    history: dict[RoutingResourceKey, int] = {}
    choices: dict[str, ChosenCandidate] = {}
    passes: list[NegotiatedGraphPass] = []
    present_factor = policy.present_factor_units

    for net_name in order:
        route, choice = _select_candidate(
            net_name,
            by_net[net_name],
            ledger,
            history,
            present_factor,
        )
        ledger.commit(NetResourceClaims(net_name, route.resources))
        choices[net_name] = choice

    overuse = ledger.overuse()
    objective = _objective(overuse)
    _update_history(history, overuse, resource_by_id, policy)
    passes.append(
        _make_pass(
            0,
            order,
            choices,
            overuse,
            objective,
            history,
            ledger,
            stagnant=False,
            present_factor=present_factor,
        )
    )
    if not overuse:
        return _finish(True, None, order, passes, max_passes, max_stagnant_passes, policy)
    if max_stagnant_passes == 0:
        return _finish(
            False,
            RoutingFailureReason.OVERUSE_REMAINING,
            order,
            passes,
            max_passes,
            max_stagnant_passes,
            policy,
        )
    if len(passes) >= max_passes:
        return _finish(
            False,
            RoutingFailureReason.PASS_BUDGET,
            order,
            passes,
            max_passes,
            max_stagnant_passes,
            policy,
        )

    best_objective = objective
    stagnant_count = 0
    while len(passes) < max_passes:
        present_factor = _grow_present_factor(present_factor, policy)
        reroute_order = _reroute_order(overuse, order, rank)
        for net_name in reroute_order:
            old_claims = ledger.rip_up(net_name)
            try:
                route, choice = _select_candidate(
                    net_name,
                    by_net[net_name],
                    ledger,
                    history,
                    present_factor,
                )
                ledger.commit(NetResourceClaims(net_name, route.resources))
            except Exception:
                ledger.restore(old_claims)
                raise
            choices[net_name] = choice

        overuse = ledger.overuse()
        objective = _objective(overuse)
        stagnant = objective >= best_objective
        if stagnant:
            stagnant_count += 1
        else:
            best_objective = objective
            stagnant_count = 0
        _update_history(history, overuse, resource_by_id, policy)
        passes.append(
            _make_pass(
                len(passes),
                reroute_order,
                choices,
                overuse,
                objective,
                history,
                ledger,
                stagnant=stagnant,
                present_factor=present_factor,
            )
        )
        if not overuse:
            return _finish(
                True,
                None,
                order,
                passes,
                max_passes,
                max_stagnant_passes,
                policy,
            )
        if stagnant and stagnant_count >= max_stagnant_passes:
            return _finish(
                False,
                RoutingFailureReason.STAGNATION,
                order,
                passes,
                max_passes,
                max_stagnant_passes,
                policy,
            )

    return _finish(
        False,
        RoutingFailureReason.PASS_BUDGET,
        order,
        passes,
        max_passes,
        max_stagnant_passes,
        policy,
    )


def _normalize_candidates(
    candidates: Mapping[str, Iterable[CandidateRoute]],
) -> dict[str, tuple[CandidateRoute, ...]]:
    if not candidates:
        raise ValueError("candidate mapping must contain at least one net")
    normalized: dict[str, tuple[CandidateRoute, ...]] = {}
    for net_name, route_items in candidates.items():
        if not net_name:
            raise ValueError("candidate mapping net names must be non-empty")
        routes = tuple(route_items)
        if not routes:
            raise ValueError(f"net {net_name!r} has no route candidates")
        if any(route.net_name != net_name for route in routes):
            raise ValueError(f"candidate ownership mismatch for net {net_name!r}")
        candidate_ids = [route.candidate_id for route in routes]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError(f"net {net_name!r} has duplicate candidate IDs")
        normalized[net_name] = tuple(
            sorted(
                routes,
                key=lambda item: (
                    item.candidate_id,
                    item.base_cost_units,
                    tuple(sorted(resource.resource_id for resource in item.resources)),
                ),
            )
        )
    return normalized


def _normalize_order(
    candidates: Mapping[str, tuple[CandidateRoute, ...]],
    baseline_order: Sequence[str] | None,
) -> tuple[str, ...]:
    if baseline_order is None:
        return tuple(sorted(candidates))
    order = tuple(baseline_order)
    if len(set(order)) != len(order):
        raise ValueError("baseline_order must not contain duplicate nets")
    if set(order) != set(candidates):
        raise ValueError("baseline_order must contain every candidate net exactly once")
    return order


def _select_candidate(
    net_name: str,
    candidates: tuple[CandidateRoute, ...],
    ledger: OccupancyLedger,
    history: Mapping[RoutingResourceKey, int],
    present_factor: int,
) -> tuple[CandidateRoute, ChosenCandidate]:
    owned = ledger.claims_for(net_name).resources
    ranked: list[tuple[tuple[int, int, int, str], CandidateRoute, int]] = []
    for candidate in candidates:
        congestion = sum(
            present_factor * max(0, ledger.demand_without(resource, net_name) + 1 - ledger.capacity)
            + history.get(resource, 0)
            for resource in candidate.resources
            if resource not in owned
        )
        key = (
            candidate.base_cost_units + congestion,
            congestion,
            candidate.base_cost_units,
            candidate.candidate_id,
        )
        ranked.append((key, candidate, congestion))
    _key, selected, congestion = min(ranked, key=lambda item: item[0])
    choice = ChosenCandidate(
        net_name=net_name,
        candidate_id=selected.candidate_id,
        base_cost_units=selected.base_cost_units,
        congestion_cost_units=congestion,
        total_cost_units=selected.base_cost_units + congestion,
        resource_ids=tuple(sorted(item.resource_id for item in selected.resources)),
    )
    return selected, choice


def _objective(overuse: tuple[ResourceOveruseSummary, ...]) -> Objective:
    values = tuple(item.overuse_units for item in overuse)
    return (0, sum(values), len(values), max(values, default=0))


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
            "schema_id": "pcbsmith-negotiated-history",
            "schema_version": 1,
            "costs": [
                [resource.resource_id, value]
                for resource, value in sorted(history.items())
                if value > 0
            ],
        }
    )


def _reroute_order(
    overuse: tuple[ResourceOveruseSummary, ...],
    baseline_order: tuple[str, ...],
    rank: Mapping[str, int],
) -> tuple[str, ...]:
    touched = {net_name: 0 for net_name in baseline_order}
    for item in overuse:
        for net_name in item.net_names:
            touched[net_name] += item.overuse_units
    return tuple(
        sorted(
            baseline_order,
            key=lambda net_name: (-touched[net_name], rank[net_name], net_name),
        )
    )


def _grow_present_factor(current: int, policy: NegotiatedCostPolicy) -> int:
    numerator = current * policy.present_growth_numerator
    return (numerator + policy.present_growth_denominator - 1) // (
        policy.present_growth_denominator
    )


def _make_pass(
    pass_index: int,
    route_order: tuple[str, ...],
    choices: Mapping[str, ChosenCandidate],
    overuse: tuple[ResourceOveruseSummary, ...],
    objective: Objective,
    history: Mapping[RoutingResourceKey, int],
    ledger: OccupancyLedger,
    *,
    stagnant: bool,
    present_factor: int,
) -> NegotiatedGraphPass:
    return NegotiatedGraphPass(
        pass_index=pass_index,
        route_order=route_order,
        chosen_candidates=tuple(choices[name] for name in sorted(choices)),
        resource_overuse=overuse,
        objective=objective,
        history_fingerprint=_history_fingerprint(history),
        resource_fingerprint=ledger.semantic_fingerprint(),
        stagnant=stagnant,
        present_factor_units=present_factor,
    )


def _finish(
    success: bool,
    failure_reason: RoutingFailureReason | None,
    baseline_order: tuple[str, ...],
    passes: list[NegotiatedGraphPass],
    max_passes: int,
    max_stagnant_passes: int,
    policy: NegotiatedCostPolicy,
) -> NegotiatedGraphResult:
    final = passes[-1]
    return NegotiatedGraphResult(
        schema_id="pcbsmith-negotiated-candidate-graph",
        schema_version=1,
        success=success,
        failure_reason=failure_reason,
        baseline_order=baseline_order,
        chosen_candidates=final.chosen_candidates,
        passes=tuple(passes),
        resource_overuse=final.resource_overuse,
        objective=final.objective,
        history_fingerprint=final.history_fingerprint,
        resource_fingerprint=final.resource_fingerprint,
        present_factor_units=final.present_factor_units,
        max_passes=max_passes,
        max_stagnant_passes=max_stagnant_passes,
        policy=policy,
    )
