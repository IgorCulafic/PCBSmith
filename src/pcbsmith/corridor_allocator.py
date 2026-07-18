"""Engine-neutral deterministic negotiated allocation over corridor graphs."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pcbsmith.corridor_ir import (
    CorridorAllocation,
    CorridorBudget,
    CorridorCapacityLedger,
    CorridorCell,
    CorridorCostPolicy,
    CorridorDemandAttemptTelemetry,
    CorridorDemandClaims,
    CorridorFailureReason,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPassTelemetry,
    CorridorPlanResult,
    CorridorResourceCapacity,
    CorridorResourceClaim,
    CorridorResourceKind,
    CorridorViaPolicy,
    corridor_allocations_fingerprint,
)
from pcbsmith.routing_ir import ResourceOveruseSummary

DEFAULT_CORRIDOR_BUDGET = CorridorBudget(
    max_passes=16,
    max_expansions=1_000_000,
    max_expansions_per_demand=100_000,
    max_stagnant_passes=8,
)
DEFAULT_CORRIDOR_COST_POLICY = CorridorCostPolicy()


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


@dataclass(frozen=True)
class _Edge:
    other_cell_id: str
    resource_id: str
    resource_kind: CorridorResourceKind
    base_cost_units: int


@dataclass(frozen=True)
class _GraphIndex:
    cells: Mapping[str, CorridorCell]
    adjacency: Mapping[str, tuple[_Edge, ...]]
    capacities: tuple[CorridorResourceCapacity, ...]


@dataclass(frozen=True)
class _SearchOutcome:
    allocation: CorridorAllocation
    claims: CorridorDemandClaims
    expansion_count: int


class _SearchFailure(RuntimeError):
    def __init__(
        self,
        reason: CorridorFailureReason,
        expansion_count: int,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.expansion_count = expansion_count


class _CompleteTreeSearcher(Protocol):
    def __call__(
        self,
        demand: CorridorNetDemand,
        graph: _GraphIndex,
        ledger: CorridorCapacityLedger,
        history: Mapping[str, int],
        present_factor: int,
        expansion_limit: int,
    ) -> _SearchOutcome: ...


def negotiate_corridor_allocations(
    graph: CorridorGraph,
    demands: Sequence[CorridorNetDemand],
    *,
    demand_order: Sequence[str] | None = None,
    budget: CorridorBudget = DEFAULT_CORRIDOR_BUDGET,
    cost_policy: CorridorCostPolicy = DEFAULT_CORRIDOR_COST_POLICY,
) -> CorridorPlanResult:
    """Allocate complete multi-terminal trees against guaranteed capacities."""
    return _negotiate_corridor_allocations(
        graph,
        demands,
        searcher=_search_complete_tree,
        demand_order=demand_order,
        budget=budget,
        cost_policy=cost_policy,
    )


def _negotiate_corridor_allocations(
    graph: CorridorGraph,
    demands: Sequence[CorridorNetDemand],
    *,
    searcher: _CompleteTreeSearcher,
    demand_order: Sequence[str] | None = None,
    budget: CorridorBudget = DEFAULT_CORRIDOR_BUDGET,
    cost_policy: CorridorCostPolicy = DEFAULT_CORRIDOR_COST_POLICY,
) -> CorridorPlanResult:
    normalized = _normalize_demands(demands)
    graph_index = _index_graph(graph, cost_policy)
    order = _baseline_order(normalized, graph_index.cells, demand_order)
    graph_fingerprint = graph.semantic_fingerprint()
    demand_fingerprint = _demand_fingerprint(normalized)
    policy_fingerprint = cost_policy.semantic_fingerprint()
    run_context_fingerprint = _run_context_fingerprint(
        graph_fingerprint,
        demand_fingerprint,
        policy_fingerprint,
        budget.semantic_fingerprint(),
    )

    if not graph.geometry_complete:
        return _preflight_failure(
            CorridorFailureReason.GEOMETRY_BUDGET,
            graph_fingerprint,
            demand_fingerprint,
            policy_fingerprint,
            order,
            budget,
        )
    if any(
        issue.verification is CorridorGeometryVerification.UNSUPPORTED for issue in graph.issues
    ):
        return _preflight_failure(
            CorridorFailureReason.UNSUPPORTED_GEOMETRY,
            graph_fingerprint,
            demand_fingerprint,
            policy_fingerprint,
            order,
            budget,
        )
    unmapped = _unmapped_demands(normalized, graph_index.cells)
    if unmapped:
        return CorridorPlanResult(
            guidance_ready=False,
            failure_reason=CorridorFailureReason.TERMINAL_UNMAPPED,
            graph_fingerprint=graph_fingerprint,
            demand_fingerprint=demand_fingerprint,
            cost_policy_fingerprint=policy_fingerprint,
            baseline_demand_order=order,
            unresolved_demand_ids=order,
            budget=budget,
        )
    if not order:
        return CorridorPlanResult(
            guidance_ready=True,
            graph_fingerprint=graph_fingerprint,
            demand_fingerprint=demand_fingerprint,
            cost_policy_fingerprint=policy_fingerprint,
            baseline_demand_order=(),
            budget=budget,
        )
    if budget.max_passes == 0:
        return _preflight_failure(
            CorridorFailureReason.PASS_BUDGET,
            graph_fingerprint,
            demand_fingerprint,
            policy_fingerprint,
            order,
            budget,
        )

    by_id = {item.demand_id: item for item in normalized}
    ledger = CorridorCapacityLedger(graph_index.capacities)
    history: dict[str, int] = {}
    allocations: dict[str, CorridorAllocation] = {}
    passes: list[CorridorPassTelemetry] = []
    present_factor = cost_policy.present_factor_units
    total_expansions = 0

    initial = _run_pass(
        order,
        by_id,
        graph_index,
        ledger,
        allocations,
        history,
        present_factor,
        budget,
        total_expansions,
        searcher=searcher,
        replace_existing=False,
    )
    total_expansions += initial.expansion_count
    if initial.failure_reason is not None:
        passes.append(
            _make_pass(
                0,
                initial.attempted_order,
                initial.demand_attempts,
                initial.unresolved,
                ledger,
                allocations,
                history,
                present_factor,
                run_context_fingerprint,
                stagnant=False,
            )
        )
        return _finish(
            initial.failure_reason,
            graph_fingerprint,
            demand_fingerprint,
            policy_fingerprint,
            order,
            allocations,
            initial.unresolved,
            ledger,
            passes,
            budget,
        )

    overuse = ledger.overuse()
    _update_history(history, overuse, cost_policy)
    passes.append(
        _make_pass(
            0,
            order,
            initial.demand_attempts,
            (),
            ledger,
            allocations,
            history,
            present_factor,
            run_context_fingerprint,
            stagnant=False,
        )
    )
    if not overuse:
        return _finish(
            None,
            graph_fingerprint,
            demand_fingerprint,
            policy_fingerprint,
            order,
            allocations,
            (),
            ledger,
            passes,
            budget,
        )
    if budget.max_stagnant_passes == 0:
        return _finish(
            CorridorFailureReason.STAGNATION,
            graph_fingerprint,
            demand_fingerprint,
            policy_fingerprint,
            order,
            allocations,
            (),
            ledger,
            passes,
            budget,
        )
    if len(passes) >= budget.max_passes:
        return _finish(
            CorridorFailureReason.PASS_BUDGET,
            graph_fingerprint,
            demand_fingerprint,
            policy_fingerprint,
            order,
            allocations,
            (),
            ledger,
            passes,
            budget,
        )

    best_objective = _objective((), overuse)
    stagnant_count = 0
    baseline_rank = {demand_id: index for index, demand_id in enumerate(order)}
    net_to_demand = {item.net_name: item.demand_id for item in normalized}
    while len(passes) < budget.max_passes:
        present_factor = _grow_present_factor(present_factor, cost_policy)
        reroute_order = _reroute_order(ledger.overuse(), order, baseline_rank, net_to_demand)
        replacement = _run_pass(
            reroute_order,
            by_id,
            graph_index,
            ledger,
            allocations,
            history,
            present_factor,
            budget,
            total_expansions,
            searcher=searcher,
            replace_existing=True,
        )
        total_expansions += replacement.expansion_count
        if replacement.failure_reason is not None:
            passes.append(
                _make_pass(
                    len(passes),
                    replacement.attempted_order,
                    replacement.demand_attempts,
                    replacement.unresolved,
                    ledger,
                    allocations,
                    history,
                    present_factor,
                    run_context_fingerprint,
                    stagnant=False,
                )
            )
            return _finish(
                replacement.failure_reason,
                graph_fingerprint,
                demand_fingerprint,
                policy_fingerprint,
                order,
                allocations,
                replacement.unresolved,
                ledger,
                passes,
                budget,
            )
        overuse = ledger.overuse()
        objective = _objective((), overuse)
        stagnant = objective >= best_objective
        if stagnant:
            stagnant_count += 1
        else:
            best_objective = objective
            stagnant_count = 0
        _update_history(history, overuse, cost_policy)
        passes.append(
            _make_pass(
                len(passes),
                reroute_order,
                replacement.demand_attempts,
                (),
                ledger,
                allocations,
                history,
                present_factor,
                run_context_fingerprint,
                stagnant=stagnant,
            )
        )
        if not overuse:
            return _finish(
                None,
                graph_fingerprint,
                demand_fingerprint,
                policy_fingerprint,
                order,
                allocations,
                (),
                ledger,
                passes,
                budget,
            )
        if stagnant and stagnant_count >= budget.max_stagnant_passes:
            return _finish(
                CorridorFailureReason.STAGNATION,
                graph_fingerprint,
                demand_fingerprint,
                policy_fingerprint,
                order,
                allocations,
                (),
                ledger,
                passes,
                budget,
            )
    return _finish(
        CorridorFailureReason.PASS_BUDGET,
        graph_fingerprint,
        demand_fingerprint,
        policy_fingerprint,
        order,
        allocations,
        (),
        ledger,
        passes,
        budget,
    )


@dataclass(frozen=True)
class _PassRun:
    attempted_order: tuple[str, ...]
    demand_attempts: tuple[CorridorDemandAttemptTelemetry, ...]
    expansion_count: int
    unresolved: tuple[str, ...]
    failure_reason: CorridorFailureReason | None


def _run_pass(
    order: tuple[str, ...],
    demands: Mapping[str, CorridorNetDemand],
    graph: _GraphIndex,
    ledger: CorridorCapacityLedger,
    allocations: dict[str, CorridorAllocation],
    history: Mapping[str, int],
    present_factor: int,
    budget: CorridorBudget,
    total_expansions: int,
    *,
    searcher: _CompleteTreeSearcher,
    replace_existing: bool,
) -> _PassRun:
    attempted: list[str] = []
    demand_attempts: list[CorridorDemandAttemptTelemetry] = []
    used = 0
    for _index, demand_id in enumerate(order):
        attempted.append(demand_id)
        remaining_total = budget.max_expansions - total_expansions - used
        limit = min(budget.max_expansions_per_demand, max(0, remaining_total))
        old_claims = ledger.rip_up(demand_id) if replace_existing else None
        try:
            outcome = searcher(
                demands[demand_id],
                graph,
                ledger,
                history,
                present_factor,
                limit,
            )
            ledger.commit(outcome.claims)
            allocations[demand_id] = outcome.allocation
            used += outcome.expansion_count
            demand_attempts.append(
                CorridorDemandAttemptTelemetry(
                    demand_id=demand_id,
                    expansion_count=outcome.expansion_count,
                )
            )
        except _SearchFailure as error:
            used += error.expansion_count
            demand_attempts.append(
                CorridorDemandAttemptTelemetry(
                    demand_id=demand_id,
                    expansion_count=error.expansion_count,
                )
            )
            if old_claims is not None:
                ledger.restore(old_claims)
            unresolved = tuple(item for item in order if item not in allocations)
            return _PassRun(
                tuple(attempted),
                tuple(demand_attempts),
                used,
                unresolved,
                error.reason,
            )
        except Exception:
            if old_claims is not None:
                ledger.restore(old_claims)
            raise
    return _PassRun(tuple(attempted), tuple(demand_attempts), used, (), None)


def _search_complete_tree(
    demand: CorridorNetDemand,
    graph: _GraphIndex,
    ledger: CorridorCapacityLedger,
    history: Mapping[str, int],
    present_factor: int,
    expansion_limit: int,
) -> _SearchOutcome:
    valid_terminals = tuple(
        tuple(
            cell_id
            for cell_id in terminal.candidate_cell_ids
            if cell_id in graph.cells and _cell_allowed(graph.cells[cell_id], demand)
        )
        for terminal in demand.terminals
    )
    if any(not cells for cells in valid_terminals):
        raise _SearchFailure(CorridorFailureReason.TERMINAL_UNMAPPED, 0)
    best: tuple[tuple[Any, ...], CorridorAllocation, CorridorDemandClaims] | None = None
    expansions = 0
    for seed in valid_terminals[0]:
        partials: tuple[tuple[frozenset[str], tuple[_Edge, ...], bool], ...] = (
            (frozenset((seed,)), (), False),
        )
        complete = True
        for targets in valid_terminals[1:]:
            next_by_via_state: dict[
                bool, tuple[tuple[Any, ...], frozenset[str], tuple[_Edge, ...]]
            ] = {}
            for tree_cells_frozen, tree_edge_values, tree_has_via in partials:
                tree_cells = set(tree_cells_frozen)
                tree_edges = {edge.resource_id: edge for edge in tree_edge_values}
                modes = (
                    ((True, False), (False, True))
                    if demand.via_policy is CorridorViaPolicy.REQUIRED and not tree_has_via
                    else ((False, False),)
                )
                for forbid_via, require_via in modes:
                    try:
                        path_cells, path_edges, used = _connect_terminal(
                            demand,
                            graph,
                            ledger,
                            history,
                            present_factor,
                            tree_cells,
                            frozenset(tree_edges),
                            frozenset(targets),
                            forbid_via=forbid_via,
                            require_via=require_via,
                            expansion_limit=max(0, expansion_limit - expansions),
                        )
                    except _SearchFailure as error:
                        expansions += error.expansion_count
                        continue
                    expansions += used
                    candidate_cells = tree_cells | set(path_cells)
                    candidate_edges = dict(tree_edges)
                    for edge in path_edges:
                        candidate_edges[edge.resource_id] = edge
                    candidate_has_via = tree_has_via or any(
                        edge.resource_kind == "via_site" for edge in path_edges
                    )
                    if len(candidate_edges) != max(0, len(candidate_cells) - 1):
                        raise ValueError("corridor candidate resources must form an acyclic tree")
                    allocation, _claims = _allocation_from_tree(
                        demand, candidate_cells, candidate_edges, ledger, history, present_factor
                    )
                    key = (
                        allocation.base_cost_units + allocation.congestion_cost_units,
                        allocation.congestion_cost_units,
                        allocation.base_cost_units,
                        tuple(
                            item.resource_id
                            for item in (*allocation.portal_claims, *allocation.via_claims)
                        ),
                        allocation.cell_ids,
                    )
                    previous = next_by_via_state.get(candidate_has_via)
                    canonical_edges = tuple(
                        sorted(candidate_edges.values(), key=lambda item: item.resource_id)
                    )
                    if previous is None or key < previous[0]:
                        next_by_via_state[candidate_has_via] = (
                            key,
                            frozenset(candidate_cells),
                            canonical_edges,
                        )
            if not next_by_via_state:
                complete = False
                break
            partials = tuple(
                (cells, edges, has_via)
                for has_via, (_key, cells, edges) in sorted(next_by_via_state.items())
            )
        if not complete:
            continue
        for tree_cells_frozen, tree_edge_values, tree_has_via in partials:
            if demand.via_policy is CorridorViaPolicy.REQUIRED and not tree_has_via:
                continue
            tree_cells = set(tree_cells_frozen)
            tree_edges = {edge.resource_id: edge for edge in tree_edge_values}
            if len(tree_edges) != max(0, len(tree_cells) - 1):
                raise ValueError("corridor allocation resources must form an acyclic tree")
            allocation, claims = _allocation_from_tree(
                demand, tree_cells, tree_edges, ledger, history, present_factor
            )
            key = (
                allocation.base_cost_units + allocation.congestion_cost_units,
                allocation.congestion_cost_units,
                allocation.base_cost_units,
                tuple(
                    item.resource_id for item in (*allocation.portal_claims, *allocation.via_claims)
                ),
                allocation.cell_ids,
            )
            if best is None or key < best[0]:
                best = (key, allocation, claims)
        if expansions >= expansion_limit:
            break
    if best is None:
        reason = (
            CorridorFailureReason.EXPANSION_BUDGET
            if expansions >= expansion_limit
            else CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT
        )
        raise _SearchFailure(reason, expansions)
    return _SearchOutcome(best[1], best[2], expansions)


def _connect_terminal(
    demand: CorridorNetDemand,
    graph: _GraphIndex,
    ledger: CorridorCapacityLedger,
    history: Mapping[str, int],
    present_factor: int,
    tree_cells: set[str],
    tree_resources: frozenset[str],
    targets: frozenset[str],
    *,
    forbid_via: bool,
    require_via: bool,
    expansion_limit: int,
) -> tuple[tuple[str, ...], tuple[_Edge, ...], int]:
    if targets & tree_cells and not require_via:
        return (), (), 0
    if expansion_limit <= 0:
        raise _SearchFailure(CorridorFailureReason.EXPANSION_BUDGET, 0)
    State = tuple[str, bool, frozenset[str], frozenset[str]]
    distances: dict[State, tuple[int, int, int]] = {}
    previous: dict[State, tuple[State, _Edge]] = {}
    heap: list[tuple[int, int, int, str, int, tuple[str, ...], int, State]] = []
    serial = 0
    for cell_id in sorted(tree_cells):
        state: State = (cell_id, False, frozenset(), frozenset((cell_id,)))
        distances[state] = (0, 0, 0)
        heapq.heappush(heap, (0, 0, 0, cell_id, 0, (), serial, state))
        serial += 1
    expansions = 0
    while heap:
        total, congestion, base, cell_id, via_used_int, resource_tuple, _serial, state = (
            heapq.heappop(heap)
        )
        if distances.get(state) != (total, congestion, base):
            continue
        if expansions >= expansion_limit:
            raise _SearchFailure(CorridorFailureReason.EXPANSION_BUDGET, expansions)
        expansions += 1
        via_used = bool(via_used_int)
        if cell_id in targets and (not require_via or via_used):
            path_cells: list[str] = []
            path_edges: list[_Edge] = []
            cursor = state
            while cursor in previous:
                parent, edge = previous[cursor]
                path_cells.append(cursor[0])
                path_edges.append(edge)
                cursor = parent
            path_cells.reverse()
            path_edges.reverse()
            return tuple(path_cells), tuple(path_edges), expansions
        used_resources = state[2]
        visited_cells = state[3]
        for edge in graph.adjacency.get(cell_id, ()):
            if edge.resource_id in tree_resources or edge.resource_id in used_resources:
                continue
            if edge.other_cell_id in tree_cells or edge.other_cell_id in visited_cells:
                continue
            if edge.resource_kind == "via_site" and (
                forbid_via or demand.via_policy is CorridorViaPolicy.FORBIDDEN
            ):
                continue
            other = graph.cells[edge.other_cell_id]
            if not _cell_allowed(other, demand):
                continue
            claim = _claim_for(edge, demand)
            edge_congestion = present_factor * ledger.projected_overuse(
                demand.demand_id, claim
            ) + history.get(edge.resource_id, 0)
            new_base = base + edge.base_cost_units
            new_congestion = congestion + edge_congestion
            new_resources = used_resources | {edge.resource_id}
            new_state: State = (
                edge.other_cell_id,
                via_used or edge.resource_kind == "via_site",
                new_resources,
                visited_cells | {edge.other_cell_id},
            )
            costs = (new_base + new_congestion, new_congestion, new_base)
            if costs >= distances.get(new_state, (math.inf, math.inf, math.inf)):
                continue
            distances[new_state] = costs
            previous[new_state] = (state, edge)
            resource_key = tuple(sorted(new_resources))
            heapq.heappush(
                heap,
                (
                    costs[0],
                    costs[1],
                    costs[2],
                    edge.other_cell_id,
                    int(new_state[1]),
                    resource_key,
                    serial,
                    new_state,
                ),
            )
            serial += 1
    raise _SearchFailure(CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT, expansions)


def _allocation_from_tree(
    demand: CorridorNetDemand,
    cells: set[str],
    edges: Mapping[str, _Edge],
    ledger: CorridorCapacityLedger,
    history: Mapping[str, int],
    present_factor: int,
) -> tuple[CorridorAllocation, CorridorDemandClaims]:
    portal_claims: list[CorridorResourceClaim] = []
    via_claims: list[CorridorResourceClaim] = []
    base = 0
    congestion = 0
    for edge in sorted(edges.values(), key=lambda item: item.resource_id):
        claim = _claim_for(edge, demand)
        if edge.resource_kind == "channel":
            portal_claims.append(claim)
        else:
            via_claims.append(claim)
        base += edge.base_cost_units
        congestion += present_factor * ledger.projected_overuse(
            demand.demand_id, claim
        ) + history.get(edge.resource_id, 0)
    allocation = CorridorAllocation(
        demand_id=demand.demand_id,
        net_name=demand.net_name,
        cell_ids=tuple(cells),
        portal_claims=tuple(portal_claims),
        via_claims=tuple(via_claims),
        base_cost_units=base,
        congestion_cost_units=congestion,
    )
    return allocation, CorridorDemandClaims(
        demand_id=demand.demand_id,
        net_name=demand.net_name,
        claims=(*allocation.portal_claims, *allocation.via_claims),
    )


def _claim_for(edge: _Edge, demand: CorridorNetDemand) -> CorridorResourceClaim:
    return CorridorResourceClaim(
        resource_id=edge.resource_id,
        resource_kind=edge.resource_kind,
        demand_units=(demand.ordinary_span_units if edge.resource_kind == "channel" else 1),
    )


def _normalize_demands(
    demands: Sequence[CorridorNetDemand],
) -> tuple[CorridorNetDemand, ...]:
    by_id: dict[str, CorridorNetDemand] = {}
    net_names: set[str] = set()
    for demand in demands:
        previous = by_id.get(demand.demand_id)
        if previous is not None and previous != demand:
            raise ValueError(f"duplicate demand identity {demand.demand_id!r} has unequal content")
        if demand.net_name in net_names and previous is None:
            raise ValueError("one corridor allocation run permits at most one demand per net")
        by_id[demand.demand_id] = demand
        net_names.add(demand.net_name)
    return tuple(by_id[item] for item in sorted(by_id))


def _index_graph(graph: CorridorGraph, policy: CorridorCostPolicy) -> _GraphIndex:
    cells = {item.cell_id: item for item in graph.cells}
    adjacency: dict[str, list[_Edge]] = {item: [] for item in cells}
    capacities: list[CorridorResourceCapacity] = []
    for portal in graph.portals:
        edge_forward = _Edge(
            portal.cell_high,
            portal.resource_id,
            "channel",
            policy.channel_step_cost_units,
        )
        edge_back = _Edge(
            portal.cell_low,
            portal.resource_id,
            "channel",
            policy.channel_step_cost_units,
        )
        adjacency[portal.cell_low].append(edge_forward)
        adjacency[portal.cell_high].append(edge_back)
        capacities.append(
            CorridorResourceCapacity(
                resource_id=portal.resource_id,
                resource_kind="channel",
                capacity_units=portal.guaranteed_span_units,
            )
        )
    for via_portal in graph.via_portals:
        adjacency[via_portal.front_cell_id].append(
            _Edge(
                via_portal.back_cell_id,
                via_portal.resource_id,
                "via_site",
                policy.via_step_cost_units,
            )
        )
        adjacency[via_portal.back_cell_id].append(
            _Edge(
                via_portal.front_cell_id,
                via_portal.resource_id,
                "via_site",
                policy.via_step_cost_units,
            )
        )
        capacities.append(
            CorridorResourceCapacity(
                resource_id=via_portal.resource_id,
                resource_kind="via_site",
                capacity_units=via_portal.guaranteed_site_count,
            )
        )
    return _GraphIndex(
        cells=cells,
        adjacency={
            cell_id: tuple(
                sorted(
                    edges,
                    key=lambda item: (
                        item.other_cell_id,
                        item.resource_kind,
                        item.resource_id,
                    ),
                )
            )
            for cell_id, edges in adjacency.items()
        },
        capacities=tuple(capacities),
    )


def _baseline_order(
    demands: tuple[CorridorNetDemand, ...],
    cells: Mapping[str, CorridorCell],
    explicit_prefix: Sequence[str] | None,
) -> tuple[str, ...]:
    by_id = {item.demand_id: item for item in demands}
    prefix = tuple(explicit_prefix or ())
    if len(set(prefix)) != len(prefix):
        raise ValueError("demand_order prefix must not contain duplicates")
    unknown = tuple(item for item in prefix if item not in by_id)
    if unknown:
        raise ValueError("demand_order prefix contains unknown demand: " + ", ".join(unknown))
    remaining = sorted(
        (item for item in demands if item.demand_id not in prefix),
        key=lambda item: (
            -item.ordinary_span_units,
            -len(item.terminals),
            _estimated_hpwl(item, cells),
            item.demand_id,
        ),
    )
    return (*prefix, *(item.demand_id for item in remaining))


def _estimated_hpwl(
    demand: CorridorNetDemand,
    cells: Mapping[str, CorridorCell],
) -> float:
    points = [
        (
            (cells[cell_id].bounds_mm[0] + cells[cell_id].bounds_mm[2]) / 2,
            (cells[cell_id].bounds_mm[1] + cells[cell_id].bounds_mm[3]) / 2,
        )
        for terminal in demand.terminals
        for cell_id in terminal.candidate_cell_ids
        if cell_id in cells and _cell_allowed(cells[cell_id], demand)
    ]
    if not points:
        return math.inf
    return (max(point[0] for point in points) - min(point[0] for point in points)) + (
        max(point[1] for point in points) - min(point[1] for point in points)
    )


def _cell_allowed(cell: CorridorCell, demand: CorridorNetDemand) -> bool:
    return cell.layer in demand.allowed_layers and all(
        owner == demand.net_name for owner in cell.terminal_owner_net_names
    )


def _unmapped_demands(
    demands: tuple[CorridorNetDemand, ...],
    cells: Mapping[str, CorridorCell],
) -> tuple[str, ...]:
    result: list[str] = []
    for demand in demands:
        if any(
            not any(
                cell_id in cells and _cell_allowed(cells[cell_id], demand)
                for cell_id in terminal.candidate_cell_ids
            )
            for terminal in demand.terminals
        ):
            result.append(demand.demand_id)
    return tuple(result)


def _demand_fingerprint(demands: tuple[CorridorNetDemand, ...]) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-corridor-demands",
            "schema_version": 1,
            "demands": [item.model_dump(mode="json") for item in demands],
        }
    )


def _run_context_fingerprint(
    graph_fingerprint: str,
    demand_fingerprint: str,
    cost_policy_fingerprint: str,
    budget_fingerprint: str,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-corridor-run-context",
            "schema_version": 1,
            "graph_fingerprint": graph_fingerprint,
            "demand_fingerprint": demand_fingerprint,
            "cost_policy_fingerprint": cost_policy_fingerprint,
            "budget_fingerprint": budget_fingerprint,
        }
    )


def _history_fingerprint(history: Mapping[str, int]) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-corridor-history",
            "schema_version": 1,
            "costs": [[resource_id, value] for resource_id, value in sorted(history.items())],
        }
    )


def _objective(
    unresolved: Sequence[str],
    overuse: tuple[ResourceOveruseSummary, ...],
) -> tuple[int, int, int, int]:
    values = tuple(item.overuse_units for item in overuse)
    return (len(set(unresolved)), sum(values), len(values), max(values, default=0))


def _update_history(
    history: dict[str, int],
    overuse: tuple[ResourceOveruseSummary, ...],
    policy: CorridorCostPolicy,
) -> None:
    for item in overuse:
        history[item.resource_id] = history.get(item.resource_id, 0) + (
            policy.history_increment_units * item.overuse_units
        )


def _reroute_order(
    overuse: tuple[ResourceOveruseSummary, ...],
    baseline: tuple[str, ...],
    rank: Mapping[str, int],
    net_to_demand: Mapping[str, str],
) -> tuple[str, ...]:
    touched = {item: 0 for item in baseline}
    for item in overuse:
        for net_name in item.net_names:
            demand_id = net_to_demand[net_name]
            touched[demand_id] += item.overuse_units
    return tuple(sorted(baseline, key=lambda item: (-touched[item], rank[item], item)))


def _grow_present_factor(current: int, policy: CorridorCostPolicy) -> int:
    numerator = current * policy.present_growth_numerator
    return (numerator + policy.present_growth_denominator - 1) // (
        policy.present_growth_denominator
    )


def _make_pass(
    pass_index: int,
    order: tuple[str, ...],
    demand_attempts: tuple[CorridorDemandAttemptTelemetry, ...],
    unresolved: tuple[str, ...],
    ledger: CorridorCapacityLedger,
    allocations: Mapping[str, CorridorAllocation],
    history: Mapping[str, int],
    present_factor: int,
    run_context_fingerprint: str,
    *,
    stagnant: bool,
) -> CorridorPassTelemetry:
    overuse = ledger.overuse()
    allocation_values = tuple(allocations.values())
    return CorridorPassTelemetry(
        pass_index=pass_index,
        demand_order=order,
        demand_attempts=demand_attempts,
        expansion_count=sum(item.expansion_count for item in demand_attempts),
        unresolved_demand_ids=unresolved,
        resource_overuse=overuse,
        objective=_objective(unresolved, overuse),
        history_fingerprint=_history_fingerprint(history),
        ledger_fingerprint=ledger.semantic_fingerprint(),
        allocation_fingerprint=corridor_allocations_fingerprint(allocation_values),
        run_context_fingerprint=run_context_fingerprint,
        present_factor_units=present_factor,
        stagnant=stagnant,
    )


def _preflight_failure(
    reason: CorridorFailureReason,
    graph_fingerprint: str,
    demand_fingerprint: str,
    policy_fingerprint: str,
    order: tuple[str, ...],
    budget: CorridorBudget,
) -> CorridorPlanResult:
    return CorridorPlanResult(
        guidance_ready=False,
        failure_reason=reason,
        graph_fingerprint=graph_fingerprint,
        demand_fingerprint=demand_fingerprint,
        cost_policy_fingerprint=policy_fingerprint,
        baseline_demand_order=order,
        unresolved_demand_ids=order,
        budget=budget,
    )


def _finish(
    failure_reason: CorridorFailureReason | None,
    graph_fingerprint: str,
    demand_fingerprint: str,
    policy_fingerprint: str,
    order: tuple[str, ...],
    allocations: Mapping[str, CorridorAllocation],
    unresolved: tuple[str, ...],
    ledger: CorridorCapacityLedger,
    passes: Sequence[CorridorPassTelemetry],
    budget: CorridorBudget,
) -> CorridorPlanResult:
    return CorridorPlanResult(
        guidance_ready=failure_reason is None,
        failure_reason=failure_reason,
        graph_fingerprint=graph_fingerprint,
        demand_fingerprint=demand_fingerprint,
        cost_policy_fingerprint=policy_fingerprint,
        baseline_demand_order=order,
        allocations=tuple(allocations.values()),
        unresolved_demand_ids=unresolved,
        resource_overuse=ledger.overuse(),
        passes=tuple(passes),
        budget=budget,
    )
