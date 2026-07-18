"""Negotiated corridor allocation with synthetic fine-prefix alternatives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pcbsmith import corridor_allocator as _allocator
from pcbsmith.corridor_allocator import (
    DEFAULT_CORRIDOR_BUDGET,
    DEFAULT_CORRIDOR_COST_POLICY,
)
from pcbsmith.corridor_exchange import (
    CorridorEscapeAlternative,
    CorridorEscapeSelection,
    CorridorExchangeAllocation,
    CorridorExchangeDemand,
    CorridorExchangePlanResult,
)
from pcbsmith.corridor_ir import (
    CorridorAllocation,
    CorridorBudget,
    CorridorCapacityLedger,
    CorridorCell,
    CorridorCostPolicy,
    CorridorDemandClaims,
    CorridorFailureReason,
    CorridorGraph,
    CorridorNetDemand,
    CorridorTerminal,
    CorridorViaPolicy,
)


@dataclass(frozen=True)
class _ValidatedAlternative:
    exchange: CorridorExchangeDemand
    alternative: CorridorEscapeAlternative
    area_demand: CorridorNetDemand
    forbidden_resource_ids: frozenset[str]
    forbidden_prefix_cell_ids: frozenset[str]


def negotiate_corridor_exchange_allocations(
    graph: CorridorGraph,
    exchange_demands: Sequence[CorridorExchangeDemand],
    *,
    ordinary_demands: Sequence[CorridorNetDemand] = (),
    demand_order: Sequence[str] | None = None,
    budget: CorridorBudget = DEFAULT_CORRIDOR_BUDGET,
    cost_policy: CorridorCostPolicy = DEFAULT_CORRIDOR_COST_POLICY,
) -> CorridorExchangePlanResult:
    """Allocate ordinary demands and fine/area alternatives in one negotiated run."""

    exchanges = _canonical_exchanges(exchange_demands)
    validated = _validate_exchanges(graph, exchanges)
    exchange_by_demand = {item.demand.demand_id: item for item in exchanges}
    validated_by_demand: dict[str, tuple[_ValidatedAlternative, ...]] = {}
    for item in validated:
        validated_by_demand.setdefault(item.exchange.demand.demand_id, ())
        validated_by_demand[item.exchange.demand.demand_id] += (item,)

    selected_by_allocation: dict[str, CorridorEscapeSelection] = {}

    def searcher(
        demand: CorridorNetDemand,
        graph_index: _allocator._GraphIndex,
        ledger: CorridorCapacityLedger,
        history: Mapping[str, int],
        present_factor: int,
        expansion_limit: int,
    ) -> _allocator._SearchOutcome:
        alternatives = validated_by_demand.get(demand.demand_id)
        if alternatives is None:
            return _allocator._search_complete_tree(
                demand,
                graph_index,
                ledger,
                history,
                present_factor,
                expansion_limit,
            )
        outcome, selected = _search_exchange_alternatives(
            alternatives,
            graph_index,
            ledger,
            history,
            present_factor,
            expansion_limit,
        )
        selected_by_allocation[outcome.allocation.semantic_fingerprint()] = selected
        return outcome

    demands = (*ordinary_demands, *(item.demand for item in exchanges))
    plan = _allocator._negotiate_corridor_allocations(
        graph,
        demands,
        searcher=cast(_allocator._CompleteTreeSearcher, searcher),
        demand_order=demand_order,
        budget=budget,
        cost_policy=cost_policy,
    )
    bound: list[CorridorExchangeAllocation] = []
    for allocation in plan.allocations:
        exchange = exchange_by_demand.get(allocation.demand_id)
        if exchange is None:
            continue
        selection = selected_by_allocation.get(allocation.semantic_fingerprint())
        if selection is None:
            raise ValueError("final exchange allocation has no bound escape selection")
        bound.append(
            CorridorExchangeAllocation(
                exchange_demand=exchange,
                allocation=allocation,
                selection=selection,
            )
        )
    return CorridorExchangePlanResult(
        plan=plan,
        exchange_demands=exchanges,
        exchange_allocations=tuple(bound),
    )


def _canonical_exchanges(
    exchange_demands: Sequence[CorridorExchangeDemand],
) -> tuple[CorridorExchangeDemand, ...]:
    by_demand: dict[str, CorridorExchangeDemand] = {}
    nets: set[str] = set()
    for exchange in exchange_demands:
        demand_id = exchange.demand.demand_id
        if demand_id in by_demand:
            raise ValueError(f"duplicate exchange demand identity {demand_id!r}")
        if exchange.demand.net_name in nets:
            raise ValueError("one exchange allocation run permits at most one demand per net")
        by_demand[demand_id] = exchange
        nets.add(exchange.demand.net_name)
    return tuple(by_demand[item] for item in sorted(by_demand))


def _validate_exchanges(
    graph: CorridorGraph,
    exchanges: tuple[CorridorExchangeDemand, ...],
) -> tuple[_ValidatedAlternative, ...]:
    cells = {item.cell_id: item for item in graph.cells}
    resources: dict[str, tuple[str, str, str]] = {}
    for portal in graph.portals:
        resources[portal.resource_id] = ("channel", portal.cell_low, portal.cell_high)
    for via in graph.via_portals:
        resources[via.resource_id] = ("via_site", via.front_cell_id, via.back_cell_id)
    result: list[_ValidatedAlternative] = []
    for exchange in exchanges:
        for alternative in exchange.alternatives:
            result.append(_validate_alternative(exchange, alternative, cells, resources))
    return tuple(result)


def _validate_alternative(
    exchange: CorridorExchangeDemand,
    alternative: CorridorEscapeAlternative,
    cells: Mapping[str, CorridorCell],
    resources: Mapping[str, tuple[str, str, str]],
) -> _ValidatedAlternative:
    demand = exchange.demand
    prefix_cells = set(alternative.prefix_cell_ids)
    for cell_id in prefix_cells:
        cell = cells.get(cell_id)
        if cell is None:
            raise ValueError(f"escape alternative references unknown cell {cell_id!r}")
        if not _allocator._cell_allowed(cell, demand):
            raise ValueError(
                "escape prefix cell is forbidden by demand layer or terminal ownership"
            )

    endpoints: list[tuple[str, str]] = []
    prefix_has_via = False
    exchange_endpoints: tuple[str, str] | None = None
    for claim in alternative.prefix_claims:
        resource = resources.get(claim.resource_id)
        if resource is None:
            raise ValueError(
                f"escape alternative references unknown resource {claim.resource_id!r}"
            )
        kind, low, high = resource
        if claim.resource_kind != kind:
            raise ValueError("escape prefix claim kind does not match graph resource")
        if kind == "via_site" and claim.demand_units != 1:
            raise ValueError("escape prefix via claim must consume exactly one site")
        if low not in prefix_cells or high not in prefix_cells:
            raise ValueError("escape prefix claim endpoints must be prefix cells")
        endpoints.append((low, high))
        prefix_has_via = prefix_has_via or kind == "via_site"
        if claim.resource_id == alternative.exchange_portal_id:
            exchange_endpoints = (low, high)

    if exchange_endpoints is None or alternative.area_entry_cell_id not in exchange_endpoints:
        raise ValueError("exchange portal must be incident to the area-entry cell")
    entry = cells[alternative.area_entry_cell_id]
    if entry.layer != alternative.exit_layer:
        raise ValueError("area-entry cell layer must match the declared exit layer")
    if resources[alternative.exchange_portal_id][0] != "channel":
        raise ValueError("exchange portal must be a channel resource")

    if len(endpoints) != len(prefix_cells) - 1 or not _connected(prefix_cells, endpoints):
        raise ValueError("escape prefix claims must form one connected acyclic tree")
    terminal_by_id = {item.terminal_id: item for item in demand.terminals}
    for terminal_id in alternative.fine_terminal_ids:
        terminal = terminal_by_id[terminal_id]
        if not prefix_cells.intersection(terminal.candidate_cell_ids):
            raise ValueError("escape prefix does not cover every fine terminal")
    if demand.via_policy is CorridorViaPolicy.FORBIDDEN and prefix_has_via:
        raise ValueError("via-forbidden demand cannot use a prefix via")

    remaining = tuple(
        item for item in demand.terminals if item.terminal_id not in alternative.fine_terminal_ids
    )
    area_terminal = CorridorTerminal(
        terminal_id=f"exchange:{alternative.alternative_id}",
        candidate_cell_ids=(alternative.area_entry_cell_id,),
    )
    area_via_policy = (
        CorridorViaPolicy.ALLOWED
        if demand.via_policy is CorridorViaPolicy.REQUIRED and prefix_has_via
        else demand.via_policy
    )
    area_demand = CorridorNetDemand.model_validate(
        {
            **demand.model_dump(),
            "terminals": (*remaining, area_terminal),
            "via_policy": area_via_policy,
        }
    )
    return _ValidatedAlternative(
        exchange=exchange,
        alternative=alternative,
        area_demand=area_demand,
        forbidden_resource_ids=frozenset(item.resource_id for item in alternative.prefix_claims),
        forbidden_prefix_cell_ids=frozenset(prefix_cells - {alternative.area_entry_cell_id}),
    )


def _connected(cells: set[str], endpoints: Sequence[tuple[str, str]]) -> bool:
    adjacency: dict[str, set[str]] = {item: set() for item in cells}
    for low, high in endpoints:
        adjacency[low].add(high)
        adjacency[high].add(low)
    seen: set[str] = set()
    pending = [min(cells)]
    while pending:
        cell_id = pending.pop()
        if cell_id in seen:
            continue
        seen.add(cell_id)
        pending.extend(sorted(adjacency[cell_id] - seen, reverse=True))
    return seen == cells


def _search_exchange_alternatives(
    alternatives: tuple[_ValidatedAlternative, ...],
    graph: _allocator._GraphIndex,
    ledger: CorridorCapacityLedger,
    history: Mapping[str, int],
    present_factor: int,
    expansion_limit: int,
) -> tuple[_allocator._SearchOutcome, CorridorEscapeSelection]:
    best: tuple[tuple[Any, ...], _allocator._SearchOutcome, CorridorEscapeSelection] | None = None
    expansions = 0
    for validated in alternatives:
        filtered = _filter_graph(
            graph,
            validated.forbidden_resource_ids,
            validated.forbidden_prefix_cell_ids,
        )
        try:
            area = _allocator._search_complete_tree(
                validated.area_demand,
                filtered,
                ledger,
                history,
                present_factor,
                max(0, expansion_limit - expansions),
            )
        except _allocator._SearchFailure as error:
            expansions += error.expansion_count
            continue
        expansions += area.expansion_count
        combined = _combine(
            validated,
            area,
            ledger,
            history,
            present_factor,
            expansions,
        )
        selection = CorridorEscapeSelection.from_exchange_demand(
            validated.exchange,
            validated.alternative.alternative_id,
        )
        allocation = combined.allocation
        key = (
            allocation.base_cost_units + allocation.congestion_cost_units,
            allocation.congestion_cost_units,
            allocation.base_cost_units,
            validated.alternative.alternative_id,
            tuple(item.resource_id for item in (*allocation.portal_claims, *allocation.via_claims)),
            allocation.cell_ids,
        )
        if best is None or key < best[0]:
            best = (key, combined, selection)
    if best is None:
        reason = (
            CorridorFailureReason.EXPANSION_BUDGET
            if expansions >= expansion_limit
            else CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT
        )
        raise _allocator._SearchFailure(reason, expansions)
    outcome = best[1]
    return (
        _allocator._SearchOutcome(
            allocation=outcome.allocation,
            claims=outcome.claims,
            expansion_count=expansions,
        ),
        best[2],
    )


def _filter_graph(
    graph: _allocator._GraphIndex,
    forbidden_resources: frozenset[str],
    forbidden_cells: frozenset[str],
) -> _allocator._GraphIndex:
    return _allocator._GraphIndex(
        cells=graph.cells,
        adjacency={
            cell_id: (
                ()
                if cell_id in forbidden_cells
                else tuple(
                    edge
                    for edge in edges
                    if edge.resource_id not in forbidden_resources
                    and edge.other_cell_id not in forbidden_cells
                )
            )
            for cell_id, edges in graph.adjacency.items()
        },
        capacities=graph.capacities,
    )


def _combine(
    validated: _ValidatedAlternative,
    area: _allocator._SearchOutcome,
    ledger: CorridorCapacityLedger,
    history: Mapping[str, int],
    present_factor: int,
    expansion_count: int,
) -> _allocator._SearchOutcome:
    alternative = validated.alternative
    area_claims = (*area.allocation.portal_claims, *area.allocation.via_claims)
    area_resource_ids = {item.resource_id for item in area_claims}
    if area_resource_ids & validated.forbidden_resource_ids:
        raise ValueError("area allocation reuses a prefix-owned resource")
    if set(area.allocation.cell_ids) & validated.forbidden_prefix_cell_ids:
        raise ValueError("area allocation re-enters the fine-prefix tree")
    claims = (*alternative.prefix_claims, *area_claims)
    prefix_congestion = sum(
        present_factor * ledger.projected_overuse(validated.area_demand.demand_id, claim)
        + history.get(claim.resource_id, 0)
        for claim in alternative.prefix_claims
    )
    portal_claims = tuple(item for item in claims if item.resource_kind == "channel")
    via_claims = tuple(item for item in claims if item.resource_kind == "via_site")
    allocation = CorridorAllocation(
        demand_id=validated.area_demand.demand_id,
        net_name=validated.area_demand.net_name,
        cell_ids=(*alternative.prefix_cell_ids, *area.allocation.cell_ids),
        portal_claims=portal_claims,
        via_claims=via_claims,
        base_cost_units=alternative.prefix_base_cost_units + area.allocation.base_cost_units,
        congestion_cost_units=prefix_congestion + area.allocation.congestion_cost_units,
    )
    return _allocator._SearchOutcome(
        allocation=allocation,
        claims=CorridorDemandClaims(
            demand_id=allocation.demand_id,
            net_name=allocation.net_name,
            claims=(*allocation.portal_claims, *allocation.via_claims),
        ),
        expansion_count=expansion_count,
    )
