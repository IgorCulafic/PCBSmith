"""Final, fail-honest binding from corridor exchange plans to detailed R2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.corridor_exchange import CorridorExchangePlanResult
from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    build_corridor_route_guide,
)
from pcbsmith.corridor_ir import CorridorGraph, CorridorIrModel
from pcbsmith.kicad.astar_router import (
    DEFAULT_MAX_BOARD_EXPANSIONS,
    DEFAULT_MAX_EXPANSIONS_PER_NET,
    GRID_MM,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.clearance_domains import ClearanceGroupInput
from pcbsmith.kicad.corridor_guidance import project_corridor_route_guide
from pcbsmith.kicad.corridor_planner import build_corridor_graph
from pcbsmith.kicad.negotiated_board import (
    ExactRouteChecker,
    ExactRouteCheckResult,
    NegotiatedBoardRouteResult,
    route_board_negotiated,
)
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_grid import GridSoftGuide
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

_EPSILON = 1e-9


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


class CorridorExchangeSelectedPrefix(CorridorIrModel):
    """One selected coarse alternative bound to one detailed prefix."""

    schema_id: Literal["pcbsmith-corridor-exchange-selected-prefix"] = (
        "pcbsmith-corridor-exchange-selected-prefix"
    )
    schema_version: Literal[1] = 1
    demand_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    alternative_id: str = Field(min_length=1)
    prefix_fingerprint: str

    @field_validator("prefix_fingerprint")
    @classmethod
    def fingerprint_is_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)


class CorridorExchangeRoutingReport(CorridorIrModel):
    """Versioned authority envelope for one exchange-guided detailed run."""

    schema_id: Literal["pcbsmith-corridor-exchange-routing-report"] = (
        "pcbsmith-corridor-exchange-routing-report"
    )
    schema_version: Literal[1] = 1
    disposition: CorridorGuidanceDisposition
    graph_fingerprint: str
    base_plan_fingerprint: str
    exchange_plan_fingerprint: str
    selected_prefixes: tuple[CorridorExchangeSelectedPrefix, ...] = ()
    selected_prefixes_fingerprint: str | None = None
    guide_fingerprint: str | None = None
    routing_run_fingerprint: str
    exact_check_fingerprint: str | None = None
    exact_check_accepted: bool | None = None

    @field_validator(
        "graph_fingerprint",
        "base_plan_fingerprint",
        "exchange_plan_fingerprint",
        "selected_prefixes_fingerprint",
        "guide_fingerprint",
        "routing_run_fingerprint",
        "exact_check_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def authority_state_is_coherent(self) -> Self:
        selected = tuple(sorted(self.selected_prefixes, key=lambda item: item.demand_id))
        if len({item.demand_id for item in selected}) != len(selected):
            raise ValueError("selected exchange prefixes require unique demand identities")
        if len({item.net_name for item in selected}) != len(selected):
            raise ValueError("selected exchange prefixes require unique net identities")
        if self.disposition is CorridorGuidanceDisposition.APPLIED:
            if not selected:
                raise ValueError("applied exchange routing requires selected prefixes")
            if self.selected_prefixes_fingerprint is None or self.guide_fingerprint is None:
                raise ValueError("applied exchange routing requires prefix and guide fingerprints")
        elif self.disposition in (
            CorridorGuidanceDisposition.INCOMPATIBLE,
            CorridorGuidanceDisposition.PLAN_NOT_READY,
        ):
            if selected or self.selected_prefixes_fingerprint is not None:
                raise ValueError("incompatible exchange routing cannot retain prefix identity")
            if self.guide_fingerprint is not None:
                raise ValueError("incompatible exchange routing cannot retain a guide identity")
        else:
            raise ValueError(
                "exchange routing supports only applied, plan-not-ready, or incompatible "
                "disposition"
            )
        object.__setattr__(self, "selected_prefixes", selected)
        return self


@dataclass(frozen=True)
class CorridorExchangeBoardRouteResult:
    """Detailed board result plus its exchange-specific authority report."""

    route_result: NegotiatedBoardRouteResult
    report: CorridorExchangeRoutingReport

    def __post_init__(self) -> None:
        if (
            self.report.routing_run_fingerprint
            != self.route_result.run_result.semantic_fingerprint()
        ):
            raise ValueError("exchange report must bind the nested routing run")
        if self.report.exact_check_fingerprint != _exact_check_fingerprint(
            self.route_result.exact_check
        ):
            raise ValueError("exchange report must bind the nested exact-check result")
        accepted = (
            self.route_result.exact_check.accepted
            if self.route_result.exact_check is not None
            else None
        )
        if self.report.exact_check_accepted is not accepted:
            raise ValueError("exchange report must preserve exact-check acceptance separately")


@dataclass(frozen=True)
class _PreparedExchangeRouting:
    soft_guides: Mapping[str, GridSoftGuide]
    route_prefixes: Mapping[str, GridRoutePrefix]
    selected_prefixes: tuple[CorridorExchangeSelectedPrefix, ...]
    selected_prefixes_fingerprint: str
    guide_fingerprint: str


def route_board_corridor_exchange_guided(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    corridor_graph: CorridorGraph,
    exchange_plan: CorridorExchangePlanResult,
    route_prefixes_by_alternative_id: Mapping[str, GridRoutePrefix],
    off_corridor_penalty_units: int = 0,
    target_nets: Collection[str] | None = None,
    net_widths: Mapping[str, float] | None = None,
    default_width_mm: float = 0.4,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    net_order: Sequence[str] | None = None,
    grid_mm: float = GRID_MM,
    clearance_groups: Sequence[ClearanceGroupInput] = (),
    max_passes: int = 16,
    max_expansions: int = DEFAULT_MAX_BOARD_EXPANSIONS,
    max_expansions_per_net: int = DEFAULT_MAX_EXPANSIONS_PER_NET,
    max_stagnant_passes: int = 8,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    exact_checker: ExactRouteChecker | None = None,
) -> CorridorExchangeBoardRouteResult:
    """Bind a compatible exchange plan once, otherwise run honest ordinary R2.

    ``fine_terminal_ids`` are an ordered semantic contract in the exchange
    alternative. Detailed prefixes canonicalize their pad anchors by physical
    source ID, so this adapter requires exact set equality while preserving the
    declared order in the exchange-plan fingerprint.
    """
    if (
        not isinstance(off_corridor_penalty_units, int)
        or isinstance(off_corridor_penalty_units, bool)
        or off_corridor_penalty_units < 0
    ):
        raise ValueError("off_corridor_penalty_units must be a non-negative integer")

    prepared = None
    disposition = CorridorGuidanceDisposition.PLAN_NOT_READY
    if exchange_plan.plan.guidance_ready:
        disposition = CorridorGuidanceDisposition.INCOMPATIBLE
        try:
            prepared = _prepare_exchange_routing(
                layout,
                netlist,
                corridor_graph,
                exchange_plan,
                route_prefixes_by_alternative_id,
                off_corridor_penalty_units=off_corridor_penalty_units,
                target_nets=target_nets,
                net_widths=net_widths,
                default_width_mm=default_width_mm,
                profile=profile,
                clearance_groups=clearance_groups,
                grid_mm=grid_mm,
            )
        except (KeyError, ValueError):
            pass
        else:
            disposition = CorridorGuidanceDisposition.APPLIED

    route_result = route_board_negotiated(
        layout,
        netlist,
        target_nets=target_nets,
        net_widths=net_widths,
        default_width_mm=default_width_mm,
        profile=profile,
        net_order=net_order,
        grid_mm=grid_mm,
        clearance_groups=clearance_groups,
        soft_guides=(prepared.soft_guides if prepared is not None else None),
        route_prefixes=(prepared.route_prefixes if prepared is not None else None),
        max_passes=max_passes,
        max_expansions=max_expansions,
        max_expansions_per_net=max_expansions_per_net,
        max_stagnant_passes=max_stagnant_passes,
        cost_policy=cost_policy,
        exact_checker=exact_checker,
    )
    exact_fingerprint = _exact_check_fingerprint(route_result.exact_check)
    report = CorridorExchangeRoutingReport(
        disposition=disposition,
        graph_fingerprint=corridor_graph.semantic_fingerprint(),
        base_plan_fingerprint=exchange_plan.plan.semantic_fingerprint(),
        exchange_plan_fingerprint=exchange_plan.semantic_fingerprint(),
        selected_prefixes=(prepared.selected_prefixes if prepared is not None else ()),
        selected_prefixes_fingerprint=(
            prepared.selected_prefixes_fingerprint if prepared is not None else None
        ),
        guide_fingerprint=(prepared.guide_fingerprint if prepared is not None else None),
        routing_run_fingerprint=route_result.run_result.semantic_fingerprint(),
        exact_check_fingerprint=exact_fingerprint,
        exact_check_accepted=(
            route_result.exact_check.accepted if route_result.exact_check is not None else None
        ),
    )
    return CorridorExchangeBoardRouteResult(route_result=route_result, report=report)


def _prepare_exchange_routing(
    layout: BoardLayout,
    netlist: BoardNetlist,
    graph: CorridorGraph,
    exchange_plan: CorridorExchangePlanResult,
    supplied_prefixes: Mapping[str, GridRoutePrefix],
    *,
    off_corridor_penalty_units: int,
    target_nets: Collection[str] | None,
    net_widths: Mapping[str, float] | None,
    default_width_mm: float,
    profile: PcbRuleProfile,
    clearance_groups: Sequence[ClearanceGroupInput],
    grid_mm: float,
) -> _PreparedExchangeRouting:
    graph_fingerprint = graph.semantic_fingerprint()
    if not exchange_plan.plan.guidance_ready:
        raise ValueError("exchange plan is not guidance-ready")
    if exchange_plan.plan.graph_fingerprint != graph_fingerprint:
        raise ValueError("exchange plan does not bind the supplied graph")
    if not exchange_plan.exchange_allocations:
        raise ValueError("exchange routing requires at least one final exchange allocation")

    current = build_corridor_graph(
        layout,
        netlist,
        target_nets=target_nets,
        net_widths=net_widths,
        default_width_mm=default_width_mm,
        profile=profile,
        clearance_groups=clearance_groups,
        coarse_grid_mm=graph.coarse_grid_mm,
        capacity_quantum_mm=graph.capacity_quantum_mm,
    )
    if not current.planning_supported or current.graph.semantic_fingerprint() != graph_fingerprint:
        raise ValueError("current layout corridor graph is incompatible")

    coarse_guide = build_corridor_route_guide(
        graph,
        exchange_plan.plan,
        off_corridor_penalty_units=off_corridor_penalty_units,
    )
    if coarse_guide is None:
        raise ValueError("exchange base plan cannot produce exact soft guidance")
    projected = project_corridor_route_guide(
        coarse_guide,
        graph,
        layout,
        grid_mm=grid_mm,
    )

    selected_alternative_ids = tuple(
        item.selection.alternative.alternative_id for item in exchange_plan.exchange_allocations
    )
    if len(set(selected_alternative_ids)) != len(selected_alternative_ids):
        raise ValueError("selected alternative identities must be globally unique")
    if set(supplied_prefixes) != set(selected_alternative_ids):
        raise ValueError("supplied detailed prefixes must exactly cover selected alternatives")

    cell_by_id = {cell.cell_id: cell for cell in graph.cells}
    prefixes_by_net: dict[str, GridRoutePrefix] = {}
    selected: list[CorridorExchangeSelectedPrefix] = []
    for bound in exchange_plan.exchange_allocations:
        alternative = bound.selection.alternative
        prefix = supplied_prefixes[alternative.alternative_id]
        fingerprint = prefix.semantic_fingerprint()
        if (
            prefix.alternative_id != alternative.alternative_id
            or prefix.net_name != alternative.net_name
            or fingerprint != alternative.detailed_prefix_fingerprint
        ):
            raise ValueError("detailed prefix identity does not match selected alternative")
        anchor_ids = tuple(source_id for source_id, _node in prefix.covered_pad_anchors)
        if anchor_ids != tuple(sorted(alternative.fine_terminal_ids)):
            raise ValueError("detailed prefix anchors do not equal selected fine terminals")
        if prefix.exit_node[0] != alternative.exit_layer:
            raise ValueError("detailed prefix exit layer does not match selected alternative")
        entry = cell_by_id.get(alternative.area_entry_cell_id)
        if entry is None or entry.layer != alternative.exit_layer:
            raise ValueError("selected area-entry cell is missing or on the wrong layer")
        exit_x = prefix.exit_node[1] * prefix.grid_mm
        exit_y = prefix.exit_node[2] * prefix.grid_mm
        min_x, min_y, max_x, max_y = entry.bounds_mm
        if not (
            min_x - _EPSILON <= exit_x <= max_x + _EPSILON
            and min_y - _EPSILON <= exit_y <= max_y + _EPSILON
        ):
            raise ValueError("detailed prefix exit point is outside selected area-entry cell")
        if prefix.net_name in prefixes_by_net:
            raise ValueError("one detailed run permits at most one selected prefix per net")
        prefixes_by_net[prefix.net_name] = prefix
        selected.append(
            CorridorExchangeSelectedPrefix(
                demand_id=bound.allocation.demand_id,
                net_name=prefix.net_name,
                alternative_id=prefix.alternative_id,
                prefix_fingerprint=fingerprint,
            )
        )

    soft_guides = projected.as_soft_guides()
    if not set(prefixes_by_net).issubset(soft_guides):
        raise ValueError("selected exchange prefix has no projected area guide")
    canonical_selected = tuple(sorted(selected, key=lambda item: item.demand_id))
    selected_fingerprint = _fingerprint(
        {
            "schema_id": "pcbsmith-corridor-exchange-selected-prefixes",
            "schema_version": 1,
            "selected_prefixes": [item.model_dump(mode="json") for item in canonical_selected],
        }
    )
    return _PreparedExchangeRouting(
        soft_guides=soft_guides,
        route_prefixes=prefixes_by_net,
        selected_prefixes=canonical_selected,
        selected_prefixes_fingerprint=selected_fingerprint,
        guide_fingerprint=projected.semantic_fingerprint(),
    )


def _exact_check_fingerprint(result: ExactRouteCheckResult | None) -> str | None:
    if result is None:
        return None
    return _fingerprint(
        {
            "accepted": result.accepted,
            "checker_id": result.checker_id,
            "finding_fingerprints": result.finding_fingerprints,
        }
    )
