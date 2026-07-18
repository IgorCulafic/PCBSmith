"""Pure replayable preparation for exchange-guided detailed routing.

This is an opt-in companion to the legacy routing wrapper.  It performs no R2
execution and changes no default routing behavior.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from pcbsmith.corridor_exchange import CorridorExchangePlanResult
from pcbsmith.corridor_exchange_replay_ir import (
    CorridorExchangeClearanceGroup,
    CorridorExchangeNetWidth,
    CorridorExchangePreparationInput,
    CorridorExchangePreparationReason,
    CorridorExchangePreparationResult,
    CorridorExchangePreparedGuide,
    CorridorExchangePreparedPrefix,
    CorridorExchangeSelectedPrefix,
    CorridorExchangeSuppliedPrefix,
    semantic_fingerprint,
)
from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    build_corridor_route_guide,
)
from pcbsmith.corridor_ir import CorridorGraph
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.clearance_domains import ClearanceGroupInput
from pcbsmith.kicad.corridor_guidance import project_corridor_route_guide
from pcbsmith.kicad.corridor_planner import build_corridor_graph
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

_EPSILON = 1e-9


def _fingerprint_envelope(schema_id: str, field_name: str, value: Any) -> str:
    return semantic_fingerprint(
        {
            "schema_id": schema_id,
            "schema_version": 1,
            field_name: value,
        }
    )


def _supplied_prefixes_fingerprint(
    supplied: tuple[CorridorExchangeSuppliedPrefix, ...],
) -> str:
    return _fingerprint_envelope(
        "pcbsmith-corridor-exchange-supplied-prefixes",
        "prefixes",
        [
            {
                "alternative_id": item.alternative_id,
                "prefix_fingerprint": item.prefix.semantic_fingerprint(),
            }
            for item in supplied
        ],
    )


def _selected_prefixes_fingerprint(
    selected: tuple[CorridorExchangeSelectedPrefix, ...],
) -> str:
    return _fingerprint_envelope(
        "pcbsmith-corridor-exchange-prepared-prefixes",
        "selected_prefixes",
        [item.model_dump(mode="json") for item in selected],
    )


def _base_payload(preparation_input: CorridorExchangePreparationInput) -> dict[str, Any]:
    return {
        "preparation_input": preparation_input,
        "graph_fingerprint": preparation_input.corridor_graph.semantic_fingerprint(),
        "exchange_plan_fingerprint": preparation_input.exchange_plan.semantic_fingerprint(),
        "supplied_prefixes_fingerprint": _supplied_prefixes_fingerprint(
            preparation_input.supplied_prefixes
        ),
        "preparation_input_fingerprint": preparation_input.semantic_fingerprint(),
    }


def _not_active(
    preparation_input: CorridorExchangePreparationInput,
    disposition: CorridorGuidanceDisposition,
    reason: CorridorExchangePreparationReason | None,
) -> dict[str, Any]:
    return {
        **_base_payload(preparation_input),
        "disposition": disposition,
        "incompatibility_reason": reason,
        "selected_prefixes": (),
        "route_prefixes": (),
        "soft_guides": (),
        "selected_prefixes_fingerprint": None,
        "guide_fingerprint": None,
    }


def _incompatible(
    preparation_input: CorridorExchangePreparationInput,
    reason: CorridorExchangePreparationReason,
) -> dict[str, Any]:
    return _not_active(
        preparation_input,
        CorridorGuidanceDisposition.INCOMPATIBLE,
        reason,
    )


def _evaluate_corridor_exchange_preparation(
    preparation_input: CorridorExchangePreparationInput,
) -> dict[str, Any]:
    """Rerun preparation and return the exact replay payload."""

    graph = preparation_input.corridor_graph
    exchange_plan = preparation_input.exchange_plan
    if not exchange_plan.plan.guidance_ready:
        return _not_active(
            preparation_input,
            CorridorGuidanceDisposition.PLAN_NOT_READY,
            None,
        )
    graph_fingerprint = graph.semantic_fingerprint()
    if exchange_plan.plan.graph_fingerprint != graph_fingerprint:
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.PLAN_GRAPH_MISMATCH,
        )
    if not exchange_plan.exchange_allocations:
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.NO_EXCHANGE_ALLOCATION,
        )

    target_nets = preparation_input.target_nets
    net_widths = {item.net_name: item.width_mm for item in preparation_input.net_widths}
    clearance_groups = tuple(item.as_legacy_tuple() for item in preparation_input.clearance_groups)
    try:
        current = build_corridor_graph(
            preparation_input.layout,
            preparation_input.netlist,
            target_nets=target_nets,
            net_widths=net_widths,
            default_width_mm=preparation_input.default_width_mm,
            profile=preparation_input.profile,
            clearance_groups=clearance_groups,
            coarse_grid_mm=graph.coarse_grid_mm,
            capacity_quantum_mm=graph.capacity_quantum_mm,
        )
    except (KeyError, ValueError):
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.CURRENT_GRAPH_BUILD_FAILURE,
        )
    if not current.planning_supported:
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.CURRENT_GRAPH_UNSUPPORTED,
        )
    if current.graph.semantic_fingerprint() != graph_fingerprint:
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.CURRENT_GRAPH_MISMATCH,
        )

    try:
        coarse_guide = build_corridor_route_guide(
            graph,
            exchange_plan.plan,
            off_corridor_penalty_units=preparation_input.off_corridor_penalty_units,
        )
    except (KeyError, ValueError):
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.GUIDE_UNAVAILABLE,
        )
    if coarse_guide is None:
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.GUIDE_UNAVAILABLE,
        )
    try:
        projected = project_corridor_route_guide(
            coarse_guide,
            graph,
            preparation_input.layout,
            grid_mm=preparation_input.grid_mm,
        )
    except (KeyError, ValueError):
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.GUIDE_PROJECTION_FAILURE,
        )

    selected_alternative_ids = tuple(
        item.selection.alternative.alternative_id for item in exchange_plan.exchange_allocations
    )
    if len(set(selected_alternative_ids)) != len(selected_alternative_ids):
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.DUPLICATE_SELECTED_ALTERNATIVE,
        )
    supplied_ids = {item.alternative_id for item in preparation_input.supplied_prefixes}
    selected_ids = set(selected_alternative_ids)
    if selected_ids - supplied_ids:
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.MISSING_SUPPLIED_PREFIX,
        )
    if supplied_ids - selected_ids:
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.EXTRA_SUPPLIED_PREFIX,
        )

    supplied_by_id = {
        item.alternative_id: item.prefix for item in preparation_input.supplied_prefixes
    }
    cell_by_id = {cell.cell_id: cell for cell in graph.cells}
    prefixes_by_net: dict[str, GridRoutePrefix] = {}
    selected: list[CorridorExchangeSelectedPrefix] = []
    for bound in exchange_plan.exchange_allocations:
        alternative = bound.selection.alternative
        prefix = supplied_by_id[alternative.alternative_id]
        if prefix.alternative_id != alternative.alternative_id:
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.PREFIX_ALTERNATIVE_MISMATCH,
            )
        if prefix.net_name != alternative.net_name:
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.PREFIX_NET_MISMATCH,
            )
        prefix_fingerprint = prefix.semantic_fingerprint()
        if prefix_fingerprint != alternative.detailed_prefix_fingerprint:
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.PREFIX_FINGERPRINT_MISMATCH,
            )
        anchor_ids = tuple(source_id for source_id, _node in prefix.covered_pad_anchors)
        if anchor_ids != tuple(sorted(alternative.fine_terminal_ids)):
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.PREFIX_ANCHOR_MISMATCH,
            )
        if prefix.exit_node[0] != alternative.exit_layer:
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.PREFIX_LAYER_MISMATCH,
            )
        entry = cell_by_id.get(alternative.area_entry_cell_id)
        if entry is None:
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.ENTRY_CELL_MISSING,
            )
        if entry.layer != alternative.exit_layer:
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.ENTRY_CELL_WRONG_LAYER,
            )
        exit_x = prefix.exit_node[1] * prefix.grid_mm
        exit_y = prefix.exit_node[2] * prefix.grid_mm
        min_x, min_y, max_x, max_y = entry.bounds_mm
        if not (
            min_x - _EPSILON <= exit_x <= max_x + _EPSILON
            and min_y - _EPSILON <= exit_y <= max_y + _EPSILON
        ):
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.PREFIX_EXIT_OUTSIDE_ENTRY,
            )
        if prefix.net_name in prefixes_by_net:
            return _incompatible(
                preparation_input,
                CorridorExchangePreparationReason.DUPLICATE_PREFIX_NET,
            )
        prefixes_by_net[prefix.net_name] = prefix
        selected.append(
            CorridorExchangeSelectedPrefix(
                demand_id=bound.allocation.demand_id,
                net_name=prefix.net_name,
                alternative_id=prefix.alternative_id,
                prefix_fingerprint=prefix_fingerprint,
            )
        )

    soft_guides_by_net = projected.as_soft_guides()
    if not set(prefixes_by_net).issubset(soft_guides_by_net):
        return _incompatible(
            preparation_input,
            CorridorExchangePreparationReason.MISSING_PROJECTED_GUIDE,
        )
    canonical_selected = tuple(sorted(selected, key=lambda item: item.demand_id))
    route_prefixes = tuple(
        CorridorExchangePreparedPrefix(net_name=name, prefix=prefixes_by_net[name])
        for name in sorted(prefixes_by_net)
    )
    soft_guides = tuple(
        CorridorExchangePreparedGuide(net_name=name, guide=soft_guides_by_net[name])
        for name in sorted(soft_guides_by_net)
    )
    return {
        **_base_payload(preparation_input),
        "disposition": CorridorGuidanceDisposition.APPLIED,
        "incompatibility_reason": None,
        "selected_prefixes": canonical_selected,
        "route_prefixes": route_prefixes,
        "soft_guides": soft_guides,
        "selected_prefixes_fingerprint": _selected_prefixes_fingerprint(canonical_selected),
        "guide_fingerprint": projected.semantic_fingerprint(),
    }


def prepare_corridor_exchange_routing(
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
    grid_mm: float = 0.5,
    clearance_groups: Sequence[ClearanceGroupInput] = (),
) -> CorridorExchangePreparationResult:
    """Create and immediately replay-check one pure preparation result."""

    typed_groups = tuple(
        CorridorExchangeClearanceGroup(
            nets_a=tuple(nets_a),
            nets_b=tuple(nets_b),
            minimum_clearance_mm=minimum_clearance_mm,
            exempt_component_refs=tuple(exempt),
        )
        for nets_a, nets_b, minimum_clearance_mm, exempt in clearance_groups
    )
    preparation_input = CorridorExchangePreparationInput(
        layout_snapshot_json=canonical_board_layout_snapshot_json(layout),
        netlist_snapshot_json=canonical_board_netlist_snapshot_json(netlist),
        corridor_graph=corridor_graph,
        exchange_plan=exchange_plan,
        supplied_prefixes=tuple(
            CorridorExchangeSuppliedPrefix(alternative_id=key, prefix=value)
            for key, value in route_prefixes_by_alternative_id.items()
        ),
        target_nets=(None if target_nets is None else tuple(target_nets)),
        net_widths=tuple(
            CorridorExchangeNetWidth(net_name=name, width_mm=width)
            for name, width in (net_widths or {}).items()
        ),
        profile=profile,
        clearance_groups=typed_groups,
        default_width_mm=default_width_mm,
        grid_mm=grid_mm,
        off_corridor_penalty_units=off_corridor_penalty_units,
    )
    return CorridorExchangePreparationResult(
        **_evaluate_corridor_exchange_preparation(preparation_input)
    )
