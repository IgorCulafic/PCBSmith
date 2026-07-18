from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

import pcbsmith.kicad.negotiated_board as negotiated_board
from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    CorridorGuidanceReport,
)
from pcbsmith.corridor_ir import (
    CorridorAllocation,
    CorridorBudget,
    CorridorCell,
    CorridorCostPolicy,
    CorridorFailureReason,
    CorridorGraph,
    CorridorPlanResult,
)
from pcbsmith.kicad.astar_router import RouteResult
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.corridor_planner import (
    CorridorGraphBuildBudget,
    CorridorGraphBuildResult,
    OpaqueGraphicsPolicy,
)
from pcbsmith.kicad.negotiated_board import (
    CorridorGuidedBoardRouteResult,
    ExactRouteCheckResult,
    route_board_corridor_guided,
    route_board_negotiated,
)
from pcbsmith.kicad.negotiated_grid import GridSoftGuide, NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import NetResourceClaims
from pcbsmith.routing_ir import RoutingFailureReason


def _digest(character: str) -> str:
    return character * 64


def _layout(*, width_mm: float = 4.0) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=width_mm,
        height_mm=4.0,
    )


def _netlist() -> BoardNetlist:
    return BoardNetlist(components=(), nets=())


def _graph(
    *,
    profile_character: str = "a",
    layout_character: str = "b",
    max_x_mm: float = 4.0,
) -> CorridorGraph:
    return CorridorGraph(
        profile_fingerprint=_digest(profile_character),
        layout_geometry_fingerprint=_digest(layout_character),
        coarse_grid_mm=1.0,
        capacity_quantum_mm=0.1,
        cells=(
            CorridorCell(
                cell_id="cell:a",
                layer="F.Cu",
                ix=0,
                iy=0,
                bounds_mm=(0.0, 0.0, max_x_mm, 4.0),
                terminal_owner_net_names=("A",),
            ),
        ),
    )


def _ready_plan(graph: CorridorGraph) -> CorridorPlanResult:
    allocation = CorridorAllocation(
        demand_id="demand:a",
        net_name="A",
        cell_ids=("cell:a",),
        base_cost_units=0,
        congestion_cost_units=0,
    )
    return CorridorPlanResult(
        guidance_ready=True,
        graph_fingerprint=graph.semantic_fingerprint(),
        demand_fingerprint=_digest("c"),
        cost_policy_fingerprint=CorridorCostPolicy().semantic_fingerprint(),
        baseline_demand_order=("demand:a",),
        allocations=(allocation,),
        budget=CorridorBudget(
            max_passes=0,
            max_expansions=0,
            max_expansions_per_demand=0,
            max_stagnant_passes=0,
        ),
    )


def _failed_plan(graph: CorridorGraph) -> CorridorPlanResult:
    return CorridorPlanResult(
        guidance_ready=False,
        failure_reason=CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
        graph_fingerprint=graph.semantic_fingerprint(),
        demand_fingerprint=_digest("d"),
        cost_policy_fingerprint=CorridorCostPolicy().semantic_fingerprint(),
        budget=CorridorBudget(
            max_passes=0,
            max_expansions=0,
            max_expansions_per_demand=0,
            max_stagnant_passes=0,
        ),
    )


def _install_zero_overuse_search(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, GridSoftGuide | None]]:
    calls: list[tuple[str, GridSoftGuide | None]] = []

    def fake_search(*args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        net_name = cast(str, args[2])
        calls.append((net_name, cast(GridSoftGuide | None, kwargs.get("soft_guide"))))
        return NegotiatedGridRoute(
            result=RouteResult(
                net_name=net_name,
                segments=(),
                vias=(),
                length_mm=0.0,
                expansion_count=0,
            ),
            claims=NetResourceClaims(net_name, frozenset()),
            base_cost_units=0,
            congestion_cost_units=0,
        )

    monkeypatch.setattr(negotiated_board, "route_net_negotiated_candidate", fake_search)
    monkeypatch.setattr(
        negotiated_board,
        "_routable_nets",
        lambda _layout, _netlist, _profile: {"A": 1.0, "B": 2.0},
    )
    return calls


def _install_current_graph_build(
    monkeypatch: pytest.MonkeyPatch,
    graph: CorridorGraph,
) -> None:
    result = CorridorGraphBuildResult(
        complete=True,
        planning_supported=True,
        graph=graph,
        graphics_policy=OpaqueGraphicsPolicy.REJECT_OPAQUE,
        budget=CorridorGraphBuildBudget(),
    )
    monkeypatch.setattr(
        negotiated_board,
        "build_corridor_graph",
        lambda *_args, **_kwargs: result,
    )


def test_absent_plan_is_identical_to_ordinary_negotiated_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_zero_overuse_search(monkeypatch)
    ordinary = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=("A", "B"),
    )
    guided = route_board_corridor_guided(
        _layout(),
        _netlist(),
        target_nets=("A", "B"),
    )

    assert guided.route_result == ordinary
    assert guided.route_result.run_result.semantic_json() == ordinary.run_result.semantic_json()
    assert (
        guided.route_result.run_result.semantic_fingerprint()
        == ordinary.run_result.semantic_fingerprint()
    )
    assert guided.guidance.disposition is CorridorGuidanceDisposition.ABSENT
    assert guided.guidance.guided_net_names == ()
    assert guided.guidance.unguided_net_names == ("A", "B")


def test_nonready_plan_falls_back_and_reports_its_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_zero_overuse_search(monkeypatch)
    graph = _graph()
    plan = _failed_plan(graph)
    ordinary = route_board_negotiated(_layout(), _netlist(), target_nets=("A",))
    result = route_board_corridor_guided(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        corridor_plan=plan,
        off_corridor_penalty_units=100,
        target_nets=("A",),
    )

    assert result.route_result == ordinary
    assert result.guidance.disposition is CorridorGuidanceDisposition.PLAN_NOT_READY
    assert result.guidance.plan_fingerprint == plan.semantic_fingerprint()
    assert result.guidance.plan_failure_reason is CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT
    assert result.guidance.guide_fingerprint is None
    assert result.guidance.unguided_net_names == ("A",)


@pytest.mark.parametrize("missing", ["graph", "plan", "mismatch"])
def test_missing_or_mismatched_plan_graph_falls_back_without_guidance(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    _install_zero_overuse_search(monkeypatch)
    graph = _graph()
    plan = _ready_plan(graph)
    selected_graph = None if missing == "graph" else graph
    selected_plan = None if missing == "plan" else plan
    if missing == "mismatch":
        selected_graph = _graph(profile_character="e")
    ordinary = route_board_negotiated(_layout(), _netlist(), target_nets=("A",))

    result = route_board_corridor_guided(
        _layout(),
        _netlist(),
        corridor_graph=selected_graph,
        corridor_plan=selected_plan,
        off_corridor_penalty_units=100,
        target_nets=("A",),
    )

    assert result.route_result == ordinary
    expected_disposition = (
        CorridorGuidanceDisposition.INCOMPATIBLE
        if missing == "mismatch"
        else CorridorGuidanceDisposition.INCOMPLETE_INPUT
    )
    assert result.guidance.disposition is expected_disposition
    assert result.guidance.guide_fingerprint is None
    assert result.guidance.guided_net_names == ()
    assert result.guidance.unguided_net_names == ("A",)


def test_stale_layout_guidance_falls_back_to_byte_identical_unguided_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_zero_overuse_search(monkeypatch)
    planning_graph = _graph(layout_character="b", max_x_mm=4.0)
    current_graph = _graph(layout_character="e", max_x_mm=5.0)
    _install_current_graph_build(monkeypatch, current_graph)
    modified_layout = _layout(width_mm=5.0)
    ordinary = route_board_negotiated(
        modified_layout,
        _netlist(),
        target_nets=("A",),
    )

    result = route_board_corridor_guided(
        modified_layout,
        _netlist(),
        corridor_graph=planning_graph,
        corridor_plan=_ready_plan(planning_graph),
        off_corridor_penalty_units=100,
        target_nets=("A",),
    )

    assert result.route_result == ordinary
    assert result.route_result.run_result.semantic_json() == ordinary.run_result.semantic_json()
    assert result.guidance.disposition is CorridorGuidanceDisposition.INCOMPATIBLE
    assert result.guidance.graph_fingerprint == planning_graph.semantic_fingerprint()
    assert result.guidance.guide_fingerprint is None
    assert result.guidance.guided_net_names == ()
    assert result.guidance.unguided_net_names == ("A",)


def test_ready_guide_is_applied_only_to_covered_target_nets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_zero_overuse_search(monkeypatch)
    graph = _graph()
    _install_current_graph_build(monkeypatch, graph)
    result = route_board_corridor_guided(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        corridor_plan=_ready_plan(graph),
        off_corridor_penalty_units=77,
        target_nets=("A", "B"),
        grid_mm=1.0,
    )

    assert result.route_result.run_result.success
    assert result.guidance.disposition is CorridorGuidanceDisposition.APPLIED
    assert result.guidance.guide_fingerprint is not None
    assert result.guidance.guided_net_names == ("A",)
    assert result.guidance.unguided_net_names == ("B",)
    assert [name for name, _guide in calls] == ["A", "B"]
    assert calls[0][1] is not None
    assert calls[0][1].off_guide_transition_cost_units == 77
    assert calls[1][1] is None


@pytest.mark.parametrize("accepted", [None, False, True])
def test_exact_checker_authority_is_independent_of_applied_guidance(
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool | None,
) -> None:
    _install_zero_overuse_search(monkeypatch)
    graph = _graph()
    _install_current_graph_build(monkeypatch, graph)
    checker: Callable[[BoardLayout, BoardNetlist], ExactRouteCheckResult] | None = None
    if accepted is not None:

        def exact_checker(
            _layout: BoardLayout,
            _netlist: BoardNetlist,
        ) -> ExactRouteCheckResult:
            return ExactRouteCheckResult(
                accepted=accepted,
                checker_id="authority-test",
                finding_fingerprints=("finding-b", "finding-a"),
            )

        checker = exact_checker

    result = route_board_corridor_guided(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        corridor_plan=_ready_plan(graph),
        target_nets=("A",),
        exact_checker=checker,
    )

    run = result.route_result.run_result
    assert run.success
    assert run.failure_reason is None
    assert run.exact_check_accepted is accepted
    assert run.accepted is (accepted is True)
    if accepted is None:
        assert result.guidance.exact_check_fingerprint is None
    else:
        assert result.guidance.exact_check_fingerprint is not None


def test_algorithmic_failure_never_invokes_exact_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_zero_overuse_search(monkeypatch)
    graph = _graph()
    _install_current_graph_build(monkeypatch, graph)
    checker_calls = 0

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal checker_calls
        checker_calls += 1
        return ExactRouteCheckResult(True, "must-not-run")

    result = route_board_corridor_guided(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        corridor_plan=_ready_plan(graph),
        target_nets=("A",),
        max_passes=0,
        exact_checker=checker,
    )

    assert not result.route_result.run_result.success
    assert result.route_result.run_result.failure_reason is RoutingFailureReason.PASS_BUDGET
    assert result.route_result.exact_check is None
    assert checker_calls == 0
    assert result.guidance.disposition is CorridorGuidanceDisposition.APPLIED
    assert result.guidance.exact_check_fingerprint is None


def test_guidance_report_roundtrip_and_envelope_binding_reject_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_zero_overuse_search(monkeypatch)
    graph = _graph()
    _install_current_graph_build(monkeypatch, graph)
    result = route_board_corridor_guided(
        _layout(),
        _netlist(),
        corridor_graph=graph,
        corridor_plan=_ready_plan(graph),
        target_nets=("A",),
    )
    roundtrip = CorridorGuidanceReport.model_validate_json(result.guidance.semantic_json())

    assert roundtrip == result.guidance
    assert roundtrip.semantic_fingerprint() == result.guidance.semantic_fingerprint()
    tampered = result.guidance.model_copy(update={"routing_run_fingerprint": _digest("f")})
    with pytest.raises(ValueError, match="bind the nested routing run"):
        CorridorGuidedBoardRouteResult(
            route_result=result.route_result,
            guidance=tampered,
        )
