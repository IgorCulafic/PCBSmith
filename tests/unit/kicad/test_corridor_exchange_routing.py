from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any, cast

import pytest

import pcbsmith.kicad.corridor_exchange_routing as exchange_routing
from pcbsmith.corridor_exchange import CorridorEscapeAlternative
from pcbsmith.corridor_exchange_allocator import negotiate_corridor_exchange_allocations
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
from pcbsmith.kicad.astar_router import RouteResult
from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment
from pcbsmith.kicad.corridor_exchange_routing import (
    CorridorExchangeRoutingReport,
    route_board_corridor_exchange_guided,
)
from pcbsmith.kicad.corridor_planner import (
    CorridorGraphBuildBudget,
    CorridorGraphBuildResult,
    OpaqueGraphicsPolicy,
)
from pcbsmith.kicad.negotiated_board import (
    AppliedRoutePrefixBinding,
    ExactRouteCheckEvidence,
    ExactRouteCheckResult,
    NegotiatedBoardRouteResult,
    board_netlist_fingerprint,
)
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.routing_ir import RoutingBudget, RoutingFailureReason, RoutingRunResult


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


def _cell(cell_id: str, ix: int, *, owner: bool = False) -> CorridorCell:
    return CorridorCell(
        cell_id=cell_id,
        layer="F.Cu",
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
) -> GridRoutePrefix:
    return GridRoutePrefix(
        alternative_id=alternative_id,
        net_name=net_name,
        grid_mm=1.0,
        exit_node=("F.Cu", 1, 0),
        covered_pad_anchors=((source_id, ("F.Cu", 0, 0)),),
        segments=(TrackSegment(0.0, 0.0, 1.0, 0.0, "F.Cu", net_name, 0.4),),
    )


def _exchange_plan(graph: CorridorGraph, prefix: GridRoutePrefix) -> Any:
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
    from pcbsmith.corridor_exchange import CorridorExchangeDemand

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


def _route_result(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    prefix: GridRoutePrefix | None,
    success: bool = True,
    exact: ExactRouteCheckResult | None = None,
) -> NegotiatedBoardRouteResult:
    order = ("SIGNAL",)
    routed = (
        (
            RouteResult(
                net_name="SIGNAL",
                segments=(TrackSegment(0, 0, 2, 0, "F.Cu", "SIGNAL", 0.4),),
                vias=(),
                length_mm=2.0,
                expansion_count=3,
            ),
        )
        if success
        else ()
    )
    run = RoutingRunResult(
        producer="exchange-test",
        budget=RoutingBudget(
            max_passes=1,
            max_expansions=10,
            max_expansions_per_net=10,
            max_stagnant_passes=1,
            max_exact_check_rejections=1,
        ),
        success=success,
        exact_check_accepted=(exact.accepted if exact is not None else None),
        failure_reason=(None if success else RoutingFailureReason.EXPANSION_BUDGET),
        route_order=order,
        unresolved_net_names=(() if success else order),
    )
    bindings = (
        (
            AppliedRoutePrefixBinding(
                net_name=prefix.net_name,
                alternative_id=prefix.alternative_id,
                prefix_fingerprint=prefix.semantic_fingerprint(),
            ),
        )
        if success and prefix is not None
        else ()
    )
    checked_netlist = copy.deepcopy(netlist) if exact is not None else None
    evidence = (
        ExactRouteCheckEvidence.from_exact_check(layout, checked_netlist, exact)
        if exact is not None and checked_netlist is not None
        else None
    )
    return NegotiatedBoardRouteResult(
        layout=layout,
        results=routed,
        order=order,
        run_result=run,
        exact_check=exact,
        prefix_bindings=bindings,
        exact_check_evidence=evidence,
        checked_netlist=checked_netlist,
    )


def _install_route_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    success: bool = True,
    exact_accepted: bool | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_route(
        layout: BoardLayout, _netlist: BoardNetlist, **kwargs: Any
    ) -> NegotiatedBoardRouteResult:
        calls.append(kwargs)
        prefixes = cast(dict[str, GridRoutePrefix] | None, kwargs.get("route_prefixes"))
        prefix = prefixes.get("SIGNAL") if prefixes else None
        checker = cast(
            Callable[[BoardLayout, BoardNetlist], ExactRouteCheckResult] | None,
            kwargs.get("exact_checker"),
        )
        exact = checker(layout, _netlist) if success and checker is not None else None
        if exact_accepted is not None:
            exact = ExactRouteCheckResult(
                exact_accepted, "stub-checker", ("finding-b", "finding-a")
            )
        return _route_result(layout, _netlist, prefix=prefix, success=success, exact=exact)

    monkeypatch.setattr(exchange_routing, "route_board_negotiated", fake_route)
    return calls


def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    graph: CorridorGraph | None = None,
    prefix: GridRoutePrefix | None = None,
    supplied: dict[str, GridRoutePrefix] | None = None,
    current_graph: CorridorGraph | None = None,
    success: bool = True,
    exact_checker: Callable[[BoardLayout, BoardNetlist], ExactRouteCheckResult] | None = None,
    plan_ready: bool = True,
) -> tuple[Any, list[dict[str, Any]]]:
    graph = graph or _graph()
    prefix = prefix or _prefix()
    plan = _exchange_plan(graph, prefix)
    if not plan_ready:
        failed_plan = plan.plan.model_copy(
            update={
                "guidance_ready": False,
                "failure_reason": CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
            }
        )
        plan = plan.model_copy(update={"plan": failed_plan})
    current_graph = current_graph or graph
    monkeypatch.setattr(
        exchange_routing,
        "build_corridor_graph",
        lambda *_args, **_kwargs: _graph_build(current_graph),
    )
    calls = _install_route_stub(monkeypatch, success=success)
    result = route_board_corridor_exchange_guided(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        exchange_plan=plan,
        route_prefixes_by_alternative_id=({"escape-a": prefix} if supplied is None else supplied),
        target_nets=("SIGNAL",),
        grid_mm=1.0,
        exact_checker=exact_checker,
    )
    return result, calls


def test_compatible_exchange_binds_selected_prefix_and_pins_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = _prefix()
    result, calls = _run(monkeypatch, prefix=prefix)

    assert len(calls) == 1
    assert calls[0]["route_prefixes"] == {"SIGNAL": prefix}
    assert set(calls[0]["soft_guides"]) == {"SIGNAL"}
    assert result.report.disposition is CorridorGuidanceDisposition.APPLIED
    assert result.report.selected_prefixes[0].prefix_fingerprint == prefix.semantic_fingerprint()
    assert (
        result.route_result.prefix_bindings[0].prefix_fingerprint == prefix.semantic_fingerprint()
    )
    roundtrip = CorridorExchangeRoutingReport.model_validate_json(result.report.semantic_json())
    assert roundtrip == result.report
    assert (
        result.report.semantic_fingerprint()
        == "10362723f98d03dad87da0028ad729ac0d4bb816c8ca854380265d15f5727b0e"
    )


@pytest.mark.parametrize(
    "supplied",
    (
        {},
        {"escape-a": _prefix(source_id="pad:R9:1")},
        {"escape-a": _prefix(net_name="WRONG")},
    ),
    ids=("missing", "stale-fingerprint", "wrong-net"),
)
def test_missing_stale_or_wrong_prefix_falls_back_honestly(
    monkeypatch: pytest.MonkeyPatch,
    supplied: dict[str, GridRoutePrefix],
) -> None:
    result, calls = _run(monkeypatch, supplied=supplied)

    assert len(calls) == 1
    assert calls[0]["route_prefixes"] is None
    assert calls[0]["soft_guides"] is None
    assert result.report.disposition is CorridorGuidanceDisposition.INCOMPATIBLE
    assert result.report.selected_prefixes == ()
    assert result.report.selected_prefixes_fingerprint is None
    assert result.report.guide_fingerprint is None
    assert (
        result.report.semantic_fingerprint()
        == "de2b3e63d947a569cdc74801b02875651f903849a832d694f7924e8b2e6f7bd0"
    )


def test_current_layout_graph_mismatch_falls_back_without_stale_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run(monkeypatch, current_graph=_graph(layout_character="9"))

    assert len(calls) == 1
    assert calls[0]["route_prefixes"] is None
    assert calls[0]["soft_guides"] is None
    assert result.report.disposition is CorridorGuidanceDisposition.INCOMPATIBLE
    assert result.report.selected_prefixes == ()


def test_non_ready_base_plan_reports_plan_not_ready_without_prefix_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run(monkeypatch, plan_ready=False)

    assert len(calls) == 1
    assert calls[0]["route_prefixes"] is None
    assert calls[0]["soft_guides"] is None
    assert result.report.disposition is CorridorGuidanceDisposition.PLAN_NOT_READY
    assert result.report.selected_prefixes == ()


def test_compatible_area_failure_stays_applied_and_is_not_retried_prefix_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run(monkeypatch, success=False)

    assert len(calls) == 1
    assert set(calls[0]["route_prefixes"]) == {"SIGNAL"}
    assert result.report.disposition is CorridorGuidanceDisposition.APPLIED
    assert result.report.selected_prefixes
    assert not result.route_result.run_result.success
    assert result.route_result.run_result.failure_reason is RoutingFailureReason.EXPANSION_BUDGET
    assert result.route_result.exact_check is None


@pytest.mark.parametrize("accepted", (False, True))
def test_exact_checker_verdict_is_separate_from_applied_exchange_authority(
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool,
) -> None:
    checker_calls = 0

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal checker_calls
        checker_calls += 1
        return ExactRouteCheckResult(accepted, "authority-checker", ("finding-b", "finding-a"))

    result, _calls = _run(monkeypatch, exact_checker=checker)

    assert checker_calls == 1
    assert result.report.disposition is CorridorGuidanceDisposition.APPLIED
    assert result.report.exact_check_accepted is accepted
    assert result.report.exact_check_fingerprint is not None
    assert result.route_result.run_result.success
    assert result.route_result.run_result.accepted is accepted
    assert result.route_result.exact_check_evidence is not None
    assert result.route_result.checked_netlist is not None
    assert result.route_result.checked_netlist == _netlist()
    assert result.route_result.exact_check_evidence.checked_netlist_fingerprint == (
        board_netlist_fingerprint(result.route_result.checked_netlist)
    )


def test_algorithmic_failure_does_not_invoke_exact_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker_calls = 0

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal checker_calls
        checker_calls += 1
        return ExactRouteCheckResult(True, "must-not-run")

    result, _calls = _run(monkeypatch, success=False, exact_checker=checker)

    assert checker_calls == 0
    assert result.report.disposition is CorridorGuidanceDisposition.APPLIED
    assert result.report.exact_check_accepted is None
    assert result.report.exact_check_fingerprint is None
