from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import pcbsmith.kicad.corridor_exchange_preparation as preparation
from pcbsmith.corridor_exchange import (
    CorridorEscapeAlternative,
    CorridorExchangeDemand,
    CorridorExchangePlanResult,
)
from pcbsmith.corridor_exchange_allocator import negotiate_corridor_exchange_allocations
from pcbsmith.corridor_exchange_replay_ir import (
    CorridorExchangePreparationReason,
    CorridorExchangePreparationResult,
)
from pcbsmith.corridor_guidance import CorridorGuidanceDisposition
from pcbsmith.corridor_ir import (
    CorridorCell,
    CorridorFailureReason,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPortal,
    CorridorResourceClaim,
    CorridorTerminal,
    CorridorViaPolicy,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment
from pcbsmith.kicad.corridor_exchange_preparation import (
    prepare_corridor_exchange_routing,
)
from pcbsmith.kicad.corridor_planner import (
    CorridorGraphBuildBudget,
    CorridorGraphBuildResult,
    OpaqueGraphicsPolicy,
)
from pcbsmith.kicad.route_prefix import GridRoutePrefix


def _digest(character: str) -> str:
    return character * 64


def _layout(*, width_mm: float = 3.0) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=width_mm,
        height_mm=1.0,
    )


def _netlist() -> BoardNetlist:
    return BoardNetlist(components=(), nets=())


def _cell(
    cell_id: str,
    ix: int,
    *,
    owner: bool = False,
    layer: str = "F.Cu",
) -> CorridorCell:
    return CorridorCell(
        cell_id=cell_id,
        layer=layer,
        ix=ix,
        iy=0,
        bounds_mm=(float(ix), 0.0, float(ix + 1), 1.0),
        terminal_owner_net_names=(("SIGNAL",) if owner else ()),
    )


def _portal(resource_id: str, low: str, high: str) -> CorridorPortal:
    return CorridorPortal(
        resource_id=resource_id,
        layer="F.Cu",
        cell_low=low,
        cell_high=high,
        orientation="vertical_cut",
        guaranteed_span_units=4,
        possible_span_units=4,
        verification=CorridorGeometryVerification.EXACT,
    )


def _graph(*, layout_character: str = "2") -> CorridorGraph:
    return CorridorGraph(
        profile_fingerprint=_digest("1"),
        layout_geometry_fingerprint=_digest(layout_character),
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=(
            _cell("fine", 0, owner=True),
            _cell("entry", 1),
            _cell("ordinary", 2, owner=True),
        ),
        portals=(
            _portal("exchange", "fine", "entry"),
            _portal("area", "entry", "ordinary"),
        ),
    )


def _prefix(
    *,
    alternative_id: str = "escape-a",
    net_name: str = "SIGNAL",
    source_id: str = "pad:R1:1",
    layer: str = "F.Cu",
    exit_ix: int = 1,
) -> GridRoutePrefix:
    return GridRoutePrefix(
        alternative_id=alternative_id,
        net_name=net_name,
        grid_mm=1.0,
        exit_node=(layer, exit_ix, 0),
        covered_pad_anchors=((source_id, (layer, 0, 0)),),
        segments=(
            TrackSegment(
                0.0,
                0.0,
                float(exit_ix),
                0.0,
                layer,
                net_name,
                0.4,
            ),
        ),
    )


def _exchange_plan(
    graph: CorridorGraph,
    prefix: GridRoutePrefix,
) -> CorridorExchangePlanResult:
    demand = CorridorNetDemand(
        demand_id="signal",
        net_name="SIGNAL",
        width_mm=0.4,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id="pad:R1:1", candidate_cell_ids=("fine",)),
            CorridorTerminal(terminal_id="pad:R2:1", candidate_cell_ids=("ordinary",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )
    alternative = CorridorEscapeAlternative(
        alternative_id="escape-a",
        demand_id="signal",
        net_name="SIGNAL",
        fine_terminal_ids=("pad:R1:1",),
        exchange_portal_id="exchange",
        area_entry_cell_id="entry",
        exit_layer="F.Cu",
        prefix_cell_ids=("fine", "entry"),
        prefix_claims=(
            CorridorResourceClaim(
                resource_id="exchange",
                resource_kind="channel",
                demand_units=1,
            ),
        ),
        prefix_base_cost_units=1,
        detailed_prefix_resource_ids=("fine-grid:escape-a",),
        detailed_prefix_fingerprint=prefix.semantic_fingerprint(),
    )
    return negotiate_corridor_exchange_allocations(
        graph,
        (CorridorExchangeDemand(demand=demand, alternatives=(alternative,)),),
    )


def _graph_build(graph: CorridorGraph) -> CorridorGraphBuildResult:
    return CorridorGraphBuildResult(
        complete=True,
        planning_supported=True,
        graph=graph,
        graphics_policy=OpaqueGraphicsPolicy.REJECT_OPAQUE,
        budget=CorridorGraphBuildBudget(),
    )


def _selected_alternative(plan: CorridorExchangePlanResult) -> CorridorEscapeAlternative:
    return plan.exchange_allocations[0].selection.alternative


def _replace_selected_alternative(
    plan: CorridorExchangePlanResult,
    alternative: CorridorEscapeAlternative,
) -> CorridorExchangePlanResult:
    bound = plan.exchange_allocations[0]
    selection = bound.selection.model_copy(update={"alternative": alternative})
    return plan.model_copy(
        update={
            "exchange_allocations": (bound.model_copy(update={"selection": selection}),),
        }
    )


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
    *,
    graph: CorridorGraph | None = None,
    plan: CorridorExchangePlanResult | None = None,
    supplied: Mapping[str, GridRoutePrefix] | None = None,
    **kwargs: Any,
) -> CorridorExchangePreparationResult:
    graph = graph or _graph()
    prefix = _prefix()
    plan = plan or _exchange_plan(graph, prefix)
    monkeypatch.setattr(
        preparation,
        "build_corridor_graph",
        lambda *_args, **_kwargs: _graph_build(graph),
    )
    return prepare_corridor_exchange_routing(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        exchange_plan=plan,
        route_prefixes_by_alternative_id=({"escape-a": prefix} if supplied is None else supplied),
        target_nets=("SIGNAL",),
        grid_mm=1.0,
        **kwargs,
    )


def _assert_reason(
    result: CorridorExchangePreparationResult,
    reason: CorridorExchangePreparationReason,
) -> None:
    assert result.disposition is CorridorGuidanceDisposition.INCOMPATIBLE
    assert result.incompatibility_reason is reason
    assert result.selected_prefixes == ()
    assert result.route_prefixes == ()
    assert result.soft_guides == ()
    assert result.selected_prefixes_fingerprint is None
    assert result.guide_fingerprint is None


def test_applied_preparation_retains_selected_prefix_and_real_projected_guide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = _prefix()
    result = _prepare(monkeypatch, supplied={"escape-a": prefix})

    assert result.disposition is CorridorGuidanceDisposition.APPLIED
    assert result.incompatibility_reason is None
    assert result.selected_prefixes[0].alternative_id == "escape-a"
    assert result.selected_prefixes[0].prefix_fingerprint == prefix.semantic_fingerprint()
    assert result.route_prefixes[0].net_name == "SIGNAL"
    assert result.route_prefixes[0].prefix == prefix
    assert result.soft_guides[0].net_name == "SIGNAL"
    assert ("F.Cu", 1, 0) in result.soft_guides[0].guide.allowed_track_nodes
    assert result.selected_prefixes_fingerprint is not None
    assert result.guide_fingerprint is not None

    roundtrip = CorridorExchangePreparationResult.model_validate_json(result.semantic_json())
    assert roundtrip == result
    assert roundtrip.semantic_fingerprint() == result.semantic_fingerprint()


def test_non_ready_plan_is_retained_without_active_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph()
    plan = _exchange_plan(graph, _prefix())
    failed = plan.plan.model_copy(
        update={
            "guidance_ready": False,
            "failure_reason": CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
        }
    )

    result = _prepare(monkeypatch, graph=graph, plan=plan.model_copy(update={"plan": failed}))

    assert result.disposition is CorridorGuidanceDisposition.PLAN_NOT_READY
    assert result.incompatibility_reason is None
    assert result.route_prefixes == ()
    assert result.soft_guides == ()


def test_plan_graph_mismatch_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _graph()
    plan = _exchange_plan(graph, _prefix())
    mismatched = plan.plan.model_copy(update={"graph_fingerprint": _digest("9")})
    result = _prepare(monkeypatch, graph=graph, plan=plan.model_copy(update={"plan": mismatched}))
    _assert_reason(result, CorridorExchangePreparationReason.PLAN_GRAPH_MISMATCH)


def test_no_exchange_allocation_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _graph()
    allocated = _exchange_plan(graph, _prefix())
    plan = CorridorExchangePlanResult(plan=allocated.plan)
    result = _prepare(monkeypatch, graph=graph, plan=plan)
    _assert_reason(result, CorridorExchangePreparationReason.NO_EXCHANGE_ALLOCATION)


def test_current_graph_build_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preparation,
        "build_corridor_graph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad graph")),
    )
    graph = _graph()
    result = prepare_corridor_exchange_routing(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        exchange_plan=_exchange_plan(graph, _prefix()),
        route_prefixes_by_alternative_id={"escape-a": _prefix()},
        target_nets=("SIGNAL",),
        grid_mm=1.0,
    )
    _assert_reason(result, CorridorExchangePreparationReason.CURRENT_GRAPH_BUILD_FAILURE)


def test_current_graph_unsupported_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preparation,
        "build_corridor_graph",
        lambda *_args, **_kwargs: SimpleNamespace(planning_supported=False),
    )
    graph = _graph()
    result = prepare_corridor_exchange_routing(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        exchange_plan=_exchange_plan(graph, _prefix()),
        route_prefixes_by_alternative_id={"escape-a": _prefix()},
        target_nets=("SIGNAL",),
        grid_mm=1.0,
    )
    _assert_reason(result, CorridorExchangePreparationReason.CURRENT_GRAPH_UNSUPPORTED)


def test_current_graph_mismatch_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _graph()
    monkeypatch.setattr(
        preparation,
        "build_corridor_graph",
        lambda *_args, **_kwargs: _graph_build(_graph(layout_character="9")),
    )
    result = prepare_corridor_exchange_routing(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        exchange_plan=_exchange_plan(graph, _prefix()),
        route_prefixes_by_alternative_id={"escape-a": _prefix()},
        target_nets=("SIGNAL",),
        grid_mm=1.0,
    )
    _assert_reason(result, CorridorExchangePreparationReason.CURRENT_GRAPH_MISMATCH)


@pytest.mark.parametrize(
    ("attribute", "reason"),
    (
        ("build_corridor_route_guide", CorridorExchangePreparationReason.GUIDE_UNAVAILABLE),
        (
            "project_corridor_route_guide",
            CorridorExchangePreparationReason.GUIDE_PROJECTION_FAILURE,
        ),
    ),
)
def test_guide_failures_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    reason: CorridorExchangePreparationReason,
) -> None:
    graph = _graph()
    monkeypatch.setattr(
        preparation,
        "build_corridor_graph",
        lambda *_args, **_kwargs: _graph_build(graph),
    )
    if attribute == "build_corridor_route_guide":
        monkeypatch.setattr(preparation, attribute, lambda *_args, **_kwargs: None)
    else:
        monkeypatch.setattr(
            preparation,
            attribute,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad projection")),
        )
    result = prepare_corridor_exchange_routing(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        exchange_plan=_exchange_plan(graph, _prefix()),
        route_prefixes_by_alternative_id={"escape-a": _prefix()},
        target_nets=("SIGNAL",),
        grid_mm=1.0,
    )
    _assert_reason(result, reason)


def test_duplicate_selected_alternative_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _graph()
    plan = _exchange_plan(graph, _prefix())
    duplicate = plan.model_copy(update={"exchange_allocations": plan.exchange_allocations * 2})
    valid = _prepare(monkeypatch, graph=graph, plan=plan)
    replay_input = valid.preparation_input.model_copy(update={"exchange_plan": duplicate})

    payload = preparation._evaluate_corridor_exchange_preparation(replay_input)

    assert (
        payload["incompatibility_reason"]
        is CorridorExchangePreparationReason.DUPLICATE_SELECTED_ALTERNATIVE
    )


@pytest.mark.parametrize(
    ("supplied", "reason"),
    (
        ({}, CorridorExchangePreparationReason.MISSING_SUPPLIED_PREFIX),
        (
            {"escape-a": _prefix(), "escape-extra": _prefix()},
            CorridorExchangePreparationReason.EXTRA_SUPPLIED_PREFIX,
        ),
        (
            {"escape-a": _prefix(alternative_id="escape-other")},
            CorridorExchangePreparationReason.PREFIX_ALTERNATIVE_MISMATCH,
        ),
        (
            {"escape-a": _prefix(net_name="WRONG")},
            CorridorExchangePreparationReason.PREFIX_NET_MISMATCH,
        ),
        (
            {"escape-a": _prefix(source_id="pad:R9:1")},
            CorridorExchangePreparationReason.PREFIX_FINGERPRINT_MISMATCH,
        ),
    ),
)
def test_supplied_prefix_identity_failures_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    supplied: Mapping[str, GridRoutePrefix],
    reason: CorridorExchangePreparationReason,
) -> None:
    result = _prepare(monkeypatch, supplied=supplied)
    _assert_reason(result, reason)


@pytest.mark.parametrize(
    ("prefix", "alternative_updates", "reason"),
    (
        (
            _prefix(source_id="pad:R9:1"),
            {},
            CorridorExchangePreparationReason.PREFIX_ANCHOR_MISMATCH,
        ),
        (
            _prefix(layer="B.Cu"),
            {},
            CorridorExchangePreparationReason.PREFIX_LAYER_MISMATCH,
        ),
        (
            _prefix(),
            {"area_entry_cell_id": "missing"},
            CorridorExchangePreparationReason.ENTRY_CELL_MISSING,
        ),
        (
            _prefix(layer="B.Cu"),
            {"exit_layer": "B.Cu"},
            CorridorExchangePreparationReason.ENTRY_CELL_WRONG_LAYER,
        ),
        (
            _prefix(exit_ix=3),
            {},
            CorridorExchangePreparationReason.PREFIX_EXIT_OUTSIDE_ENTRY,
        ),
    ),
)
def test_rebound_prefix_geometry_failures_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    prefix: GridRoutePrefix,
    alternative_updates: Mapping[str, object],
    reason: CorridorExchangePreparationReason,
) -> None:
    graph = _graph()
    plan = _exchange_plan(graph, _prefix())
    alternative = _selected_alternative(plan).model_copy(
        update={
            "detailed_prefix_fingerprint": prefix.semantic_fingerprint(),
            **alternative_updates,
        }
    )
    result = _prepare(
        monkeypatch,
        graph=graph,
        plan=_replace_selected_alternative(plan, alternative),
        supplied={"escape-a": prefix},
    )
    _assert_reason(result, reason)


def test_duplicate_prefix_net_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _graph()
    first_prefix = _prefix()
    second_prefix = _prefix(alternative_id="escape-b")
    plan = _exchange_plan(graph, first_prefix)
    first_bound = plan.exchange_allocations[0]
    second_alternative = first_bound.selection.alternative.model_copy(
        update={
            "alternative_id": "escape-b",
            "detailed_prefix_fingerprint": second_prefix.semantic_fingerprint(),
        }
    )
    second_selection = first_bound.selection.model_copy(update={"alternative": second_alternative})
    second_bound = first_bound.model_copy(update={"selection": second_selection})
    duplicate_net_plan = plan.model_copy(
        update={"exchange_allocations": (first_bound, second_bound)}
    )

    valid = _prepare(monkeypatch, graph=graph, plan=plan)
    replay_input = valid.preparation_input.model_copy(
        update={
            "exchange_plan": duplicate_net_plan,
            "supplied_prefixes": tuple(
                preparation.CorridorExchangeSuppliedPrefix(
                    alternative_id=alternative_id,
                    prefix=prefix,
                )
                for alternative_id, prefix in (
                    ("escape-a", first_prefix),
                    ("escape-b", second_prefix),
                )
            ),
        }
    )

    payload = preparation._evaluate_corridor_exchange_preparation(replay_input)

    assert (
        payload["incompatibility_reason"] is CorridorExchangePreparationReason.DUPLICATE_PREFIX_NET
    )


def test_missing_projected_guide_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _graph()
    prefix = _prefix(net_name="UNGUIDED")
    plan = _exchange_plan(graph, _prefix())
    alternative = _selected_alternative(plan).model_copy(
        update={
            "net_name": "UNGUIDED",
            "detailed_prefix_fingerprint": prefix.semantic_fingerprint(),
        }
    )
    result = _prepare(
        monkeypatch,
        graph=graph,
        plan=_replace_selected_alternative(plan, alternative),
        supplied={"escape-a": prefix},
    )
    _assert_reason(result, CorridorExchangePreparationReason.MISSING_PROJECTED_GUIDE)


def test_set_like_inputs_are_canonical_and_reversed_inputs_are_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph()
    monkeypatch.setattr(
        preparation,
        "build_corridor_graph",
        lambda *_args, **_kwargs: _graph_build(graph),
    )
    prefix = _prefix()
    plan = _exchange_plan(graph, prefix)
    groups = (
        (("SIGNAL", "AUX"), ("POWER", "GROUND"), 0.2, ("U2", "U1")),
        (("SIGNAL",), ("QUIET",), 0.3, ()),
    )

    first = prepare_corridor_exchange_routing(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        exchange_plan=plan,
        route_prefixes_by_alternative_id={"escape-a": prefix},
        target_nets=("SIGNAL", "AUX"),
        net_widths={"SIGNAL": 0.4, "AUX": 0.3},
        clearance_groups=groups,
        grid_mm=1.0,
    )
    second = prepare_corridor_exchange_routing(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        exchange_plan=plan,
        route_prefixes_by_alternative_id={"escape-a": prefix},
        target_nets=("AUX", "SIGNAL"),
        net_widths={"AUX": 0.3, "SIGNAL": 0.4},
        clearance_groups=tuple(
            (tuple(reversed(a)), tuple(reversed(b)), value, tuple(reversed(exempt)))
            for a, b, value, exempt in reversed(groups)
        ),
        grid_mm=1.0,
    )

    assert first == second
    assert first.semantic_json() == second.semantic_json()
    assert first.preparation_input.target_nets == ("AUX", "SIGNAL")


def test_caller_collections_are_isolated_and_repeated_runs_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph()
    monkeypatch.setattr(
        preparation,
        "build_corridor_graph",
        lambda *_args, **_kwargs: _graph_build(graph),
    )
    prefix = _prefix()
    plan = _exchange_plan(graph, prefix)
    supplied = {"escape-a": prefix}
    targets = {"SIGNAL"}
    widths = {"SIGNAL": 0.4}
    group_a = {"SIGNAL", "AUX"}
    group_b = {"POWER"}
    exempt = {"U1"}
    groups = [(group_a, group_b, 0.2, exempt)]
    snapshots: list[str] = []

    for _ in range(3):
        result = prepare_corridor_exchange_routing(
            _layout(),
            _netlist(),
            corridor_graph=graph,
            exchange_plan=plan,
            route_prefixes_by_alternative_id=supplied,
            target_nets=targets,
            net_widths=widths,
            clearance_groups=groups,
            grid_mm=1.0,
        )
        snapshots.append(result.semantic_json())

    retained = result.semantic_json()
    supplied.clear()
    targets.add("LATE")
    widths["SIGNAL"] = 9.9
    group_a.add("LATE")
    group_b.clear()
    exempt.add("U9")
    groups.clear()

    assert snapshots == [snapshots[0]] * 3
    assert result.semantic_json() == retained
    assert result.preparation_input.target_nets == ("SIGNAL",)
    assert result.preparation_input.net_widths[0].width_mm == 0.4
    assert result.preparation_input.clearance_groups[0].exempt_component_refs == ("U1",)


def _replace_digest(value: str) -> str:
    return _digest("f") if value != _digest("f") else _digest("e")


def test_every_retained_result_field_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _prepare(monkeypatch)
    payload = result.model_dump(mode="json")
    mutators: dict[str, Callable[[dict[str, Any]], None]] = {
        "schema_id": lambda item: item.__setitem__("schema_id", "wrong"),
        "schema_version": lambda item: item.__setitem__("schema_version", 2),
        "preparation_input": lambda item: item["preparation_input"].__setitem__(
            "off_corridor_penalty_units", 7
        ),
        "disposition": lambda item: item.__setitem__("disposition", "incompatible"),
        "incompatibility_reason": lambda item: item.__setitem__(
            "incompatibility_reason", "guide_unavailable"
        ),
        "selected_prefixes": lambda item: item.__setitem__("selected_prefixes", []),
        "route_prefixes": lambda item: item.__setitem__("route_prefixes", []),
        "soft_guides": lambda item: item.__setitem__("soft_guides", []),
        "graph_fingerprint": lambda item: item.__setitem__(
            "graph_fingerprint", _replace_digest(item["graph_fingerprint"])
        ),
        "exchange_plan_fingerprint": lambda item: item.__setitem__(
            "exchange_plan_fingerprint",
            _replace_digest(item["exchange_plan_fingerprint"]),
        ),
        "supplied_prefixes_fingerprint": lambda item: item.__setitem__(
            "supplied_prefixes_fingerprint",
            _replace_digest(item["supplied_prefixes_fingerprint"]),
        ),
        "selected_prefixes_fingerprint": lambda item: item.__setitem__(
            "selected_prefixes_fingerprint",
            _replace_digest(item["selected_prefixes_fingerprint"]),
        ),
        "guide_fingerprint": lambda item: item.__setitem__(
            "guide_fingerprint", _replace_digest(item["guide_fingerprint"])
        ),
        "preparation_input_fingerprint": lambda item: item.__setitem__(
            "preparation_input_fingerprint",
            _replace_digest(item["preparation_input_fingerprint"]),
        ),
    }
    assert set(mutators) == set(payload)

    for mutate in mutators.values():
        tampered = copy.deepcopy(payload)
        mutate(tampered)
        with pytest.raises(ValidationError, match="corridor exchange preparation|Input should be"):
            CorridorExchangePreparationResult.model_validate(tampered)


def test_every_retained_input_field_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _prepare(
        monkeypatch,
        net_widths={"SIGNAL": 0.4},
        clearance_groups=((("SIGNAL",), ("OTHER",), 0.2, ("U1",)),),
    )
    payload = result.model_dump(mode="json")
    mutators: dict[str, Callable[[dict[str, Any]], None]] = {
        "schema_id": lambda item: item.__setitem__("schema_id", "wrong"),
        "schema_version": lambda item: item.__setitem__("schema_version", 2),
        "algorithm_id": lambda item: item.__setitem__("algorithm_id", "wrong"),
        "layout_snapshot_json": lambda item: item.__setitem__(
            "layout_snapshot_json", item["layout_snapshot_json"] + " "
        ),
        "netlist_snapshot_json": lambda item: item.__setitem__(
            "netlist_snapshot_json", item["netlist_snapshot_json"] + " "
        ),
        "corridor_graph": lambda item: item["corridor_graph"].__setitem__(
            "profile_fingerprint", _digest("9")
        ),
        "exchange_plan": lambda item: item["exchange_plan"]["plan"].__setitem__(
            "graph_fingerprint", _digest("9")
        ),
        "supplied_prefixes": lambda item: item.__setitem__("supplied_prefixes", []),
        "target_nets": lambda item: item.__setitem__("target_nets", ["OTHER"]),
        "net_widths": lambda item: item["net_widths"][0].__setitem__("width_mm", 0.5),
        "profile": lambda item: item["profile"]["geometry"].__setitem__("board_thickness_mm", 2.0),
        "clearance_groups": lambda item: item["clearance_groups"][0].__setitem__(
            "minimum_clearance_mm", 0.3
        ),
        "default_width_mm": lambda item: item.__setitem__("default_width_mm", 0.5),
        "grid_mm": lambda item: item.__setitem__("grid_mm", 0.25),
        "off_corridor_penalty_units": lambda item: item.__setitem__(
            "off_corridor_penalty_units", 7
        ),
    }
    input_payload = payload["preparation_input"]
    assert set(mutators) == set(input_payload)

    for mutate in mutators.values():
        tampered = copy.deepcopy(payload)
        mutate(tampered["preparation_input"])
        with pytest.raises(ValidationError):
            CorridorExchangePreparationResult.model_validate(tampered)
