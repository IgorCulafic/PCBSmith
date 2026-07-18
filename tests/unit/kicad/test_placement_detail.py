from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

import pcbsmith.kicad.negotiated_board as negotiated_board
from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    CorridorGuidanceReport,
)
from pcbsmith.corridor_ir import (
    CorridorBudget,
    CorridorCell,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPlanResult,
    CorridorPortal,
    CorridorTerminal,
)
from pcbsmith.corridor_summary import verify_corridor_plan_summary
from pcbsmith.kicad.astar_router import RouteResult
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNetlist,
    TrackSegment,
)
from pcbsmith.kicad.corridor_planner import (
    CorridorGraphBuildBudget,
    CorridorGraphBuildResult,
    OpaqueGraphicsPolicy,
)
from pcbsmith.kicad.negotiated_board import (
    CorridorGuidedBoardRouteResult,
    NegotiatedBoardRouteResult,
)
from pcbsmith.kicad.negotiated_grid import GridSoftGuide, NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import NetResourceClaims
from pcbsmith.kicad.placement_candidates import generate_placement_candidates
from pcbsmith.kicad.placement_detail import (
    KiCadPlacementR2Evaluator,
    PlacementDetailInput,
    PlacementDetailRun,
    evaluate_placement_details,
)
from pcbsmith.kicad.placement_routability import (
    PlacementProbe,
    bind_component_placement_geometry,
    build_placement_geometry_catalog,
)
from pcbsmith.kicad.placement_surrogates import evaluate_placement_surrogates
from pcbsmith.placement_candidate_ir import (
    PlacementMovePolicy,
    PlacementSurrogateEvidence,
)
from pcbsmith.placement_detail_ir import (
    PlacementDetailBudget,
    PlacementDetailRunResult,
    PlacementDetailSelectionPolicy,
    PlacementDetailState,
    PlacementR2Policy,
    PlacementSelectionReason,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.placement_ir import (
    FootprintPlacementRegion,
    PlacementBudget,
    PlacementLegalizationPolicy,
    PlacementOccupancySpan,
    PlacementRegionVerification,
)
from pcbsmith.placement_surrogate_ir import (
    EscapeRay,
    PlacedTerminalCopper,
    PlacementCorridorEvidence,
    PlacementCorridorState,
)
from pcbsmith.routing_ir import (
    RoutingBudget,
    RoutingFailureReason,
    RoutingRunResult,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _layout() -> BoardLayout:
    component = BoardComponent("U1", "fixture", "fixture:U1", "uuid:U1")
    return BoardLayout(
        placements=((component, 5.0),),
        segments=(
            TrackSegment(0.0, 0.0, 1.0, 0.0, "F.Cu", "A", 0.2),
            TrackSegment(0.0, 1.0, 1.0, 1.0, "F.Cu", "FIXED", 0.3),
        ),
        vias=(),
        width_mm=12.0,
        height_mm=12.0,
        parts_row_y_mm=5.0,
        outline=((0.0, 0.0), (12.0, 0.0), (12.0, 12.0), (0.0, 12.0)),
    )


def _catalog(layout: BoardLayout):
    component = layout.placements[0][0]
    region = FootprintPlacementRegion(
        region_id="U1:body",
        purpose="body",
        occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
        local_compound=_rect(-0.2, -0.2, 0.2, 0.2),
        verification=PlacementRegionVerification.EXACT,
        source_layers=("F.Fab",),
        source_fingerprint=_rect(-0.2, -0.2, 0.2, 0.2).semantic_fingerprint(),
    )
    courtyard = region.model_copy(
        update={
            "region_id": "U1:courtyard",
            "purpose": "courtyard",
            "local_compound": _rect(-0.3, -0.3, 0.3, 0.3),
            "source_layers": ("F.CrtYd",),
            "source_fingerprint": _rect(-0.3, -0.3, 0.3, 0.3).semantic_fingerprint(),
        }
    )
    bound = bind_component_placement_geometry(component, regions=(region, courtyard))
    return build_placement_geometry_catalog(layout, (bound,))


def _budget() -> PlacementBudget:
    return PlacementBudget(
        max_proposals=5,
        max_legalization_evaluations=5,
        max_surrogate_evaluations=5,
        max_corridor_plans=0,
        max_detailed_candidates=0,
        max_exact_checks=0,
        max_r3_geometry_cells_per_candidate=0,
        max_r3_geometry_portals_per_candidate=0,
        max_r3_expansions_per_candidate=0,
        max_r2_passes_per_candidate=0,
        max_r2_expansions_per_candidate=0,
        max_r2_expansions_per_net=0,
        max_r2_stagnant_passes=0,
    )


def _graph(index: int) -> CorridorGraph:
    left = f"cell:{index}:left"
    right = f"cell:{index}:right"
    return CorridorGraph(
        profile_fingerprint="a" * 64,
        layout_geometry_fingerprint=f"{index + 1:064x}",
        coarse_grid_mm=1.0,
        capacity_quantum_mm=0.1,
        cells=(
            CorridorCell(
                cell_id=left,
                layer="F.Cu",
                ix=0,
                iy=0,
                bounds_mm=(0.0, 0.0, 6.0, 12.0),
                terminal_owner_net_names=("A",),
            ),
            CorridorCell(
                cell_id=right,
                layer="F.Cu",
                ix=1,
                iy=0,
                bounds_mm=(6.0, 0.0, 12.0, 12.0),
                terminal_owner_net_names=("A",),
            ),
        ),
        portals=(
            CorridorPortal(
                resource_id=f"portal:{index}",
                layer="F.Cu",
                cell_low=left,
                cell_high=right,
                orientation="vertical_cut",
                guaranteed_span_units=10,
                possible_span_units=10,
                verification=CorridorGeometryVerification.EXACT,
            ),
        ),
    )


def _demand(index: int) -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=f"demand:{index}",
        net_name="A",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        terminals=(
            CorridorTerminal(
                terminal_id=f"terminal:{index}:left", candidate_cell_ids=(f"cell:{index}:left",)
            ),
            CorridorTerminal(
                terminal_id=f"terminal:{index}:right", candidate_cell_ids=(f"cell:{index}:right",)
            ),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )


def _plan(graph: CorridorGraph, index: int, *, failed: bool) -> CorridorPlanResult:
    budget = (
        CorridorBudget(
            max_passes=1, max_expansions=0, max_expansions_per_demand=0, max_stagnant_passes=0
        )
        if failed
        else CorridorBudget(
            max_passes=2, max_expansions=20, max_expansions_per_demand=20, max_stagnant_passes=1
        )
    )
    return negotiate_corridor_allocations(graph, (_demand(index),), budget=budget)


def _corridor(
    graph: CorridorGraph,
    plan: CorridorPlanResult,
    index: int,
) -> PlacementCorridorEvidence:
    verified = verify_corridor_plan_summary(graph, (_demand(index),), plan)
    return PlacementCorridorEvidence(
        state=(
            PlacementCorridorState.READY
            if plan.guidance_ready
            else PlacementCorridorState.UNSUPPORTED
        ),
        verified_summary=verified,
    )


def _terminal(
    terminal_id: str,
    net_name: str,
    x_mm: float,
    *,
    overlap: bool = False,
) -> PlacedTerminalCopper:
    half = 0.15 if overlap else 0.05
    return PlacedTerminalCopper(
        terminal_id=terminal_id,
        source_id=f"source:{terminal_id}:F.Cu",
        component_reference=terminal_id.split(":")[0],
        net_name=net_name,
        layer="F.Cu",
        center_mm=(x_mm, 5.0),
        copper=_rect(x_mm - half, 4.85, x_mm + half, 5.15),
        escape_rays=(EscapeRay(dx=1, dy=0),),
    )


class _Surrogates:
    def __init__(self, modes: tuple[str, ...]) -> None:
        self.modes = modes
        self.results: dict[str, tuple[Any, CorridorGraph | None, CorridorPlanResult | None]] = {}
        self.by_evidence: dict[
            str, tuple[Any, CorridorGraph | None, CorridorPlanResult | None]
        ] = {}
        self.calls = 0

    def __call__(
        self, probe: PlacementProbe, legalization_result: Any
    ) -> PlacementSurrogateEvidence:
        index = self.calls
        self.calls += 1
        mode = self.modes[index]
        graph = None
        plan = None
        corridor = PlacementCorridorEvidence(state=PlacementCorridorState.ABSENT)
        if mode != "absent":
            graph = _graph(index)
            plan = _plan(graph, index, failed=mode == "failed")
            corridor = _corridor(graph, plan, index)
        terminals = (_terminal("U1:1", "A", 5.0),)
        if mode == "dominated":
            terminals = (
                _terminal("U1:1", "A", 5.0, overlap=True),
                _terminal("U2:1", "B", 5.1, overlap=True),
            )
        result = evaluate_placement_surrogates(
            terminals,
            pose_fingerprint=probe.result.telemetry.pose_fingerprint,
            probe_layout_fingerprint=probe.result.telemetry.probe_layout_fingerprint,
            corridor=corridor,
        )
        pose = probe.result.telemetry.pose_fingerprint
        assert legalization_result.telemetry.pose_fingerprint == pose
        self.results[probe.result.telemetry.probe_layout_fingerprint] = (result, graph, plan)
        self.by_evidence[result.semantic_fingerprint()] = (result, graph, plan)
        return PlacementSurrogateEvidence(
            evaluator_id="r5.4-fixture",
            evidence_fingerprint=result.semantic_fingerprint(),
        )


def _inputs(modes: tuple[str, ...]) -> dict[str, PlacementDetailInput]:
    layout = _layout()
    surrogate = _Surrogates(modes)
    search = generate_placement_candidates(
        layout,
        _catalog(layout),
        PlacementMovePolicy(
            movable_references=("U1",),
            translation_step_mm=1.0,
            maximum_translation_steps=1,
            pair_move_limit=0,
            seed=11,
        ),
        PlacementLegalizationPolicy(
            policy_id="r5.4-fixture",
            minimum_body_spacing_mm=0.01,
            minimum_courtyard_spacing_mm=0.0,
            minimum_body_outer_edge_clearance_mm=0.01,
            minimum_body_cutout_clearance_mm=0.01,
            require_courtyard_containment=False,
            minimum_courtyard_outer_edge_clearance_mm=0.0,
        ),
        _budget(),
        target_nets=("A",),
        known_net_names=("A", "FIXED"),
        surrogate_evaluator=surrogate,
    )
    probe_by_pose = {item.result.telemetry.pose_fingerprint: item for item in search.probes}
    out: dict[str, PlacementDetailInput] = {}
    for candidate in search.result.candidates:
        if candidate.surrogate_evidence is None:
            continue
        pose = candidate.legalization_result.telemetry.pose_fingerprint
        result, graph, plan = surrogate.by_evidence[
            candidate.surrogate_evidence.evidence_fingerprint
        ]
        out[candidate.candidate_fingerprint] = PlacementDetailInput(
            candidate=candidate,
            probe=probe_by_pose[pose],
            surrogate=result,
            netlist=BoardNetlist(components=(), nets=()),
            corridor_graph=graph,
            corridor_plan=plan,
        )
    assert len(out) >= 3
    return out


class _FakeR2:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, bool]] = []

    def __call__(
        self,
        source: PlacementDetailInput,
        *,
        use_guidance: bool,
        policy: PlacementR2Policy,
        profile: Any,
    ) -> CorridorGuidedBoardRouteResult:
        del profile
        fingerprint = source.candidate.candidate_fingerprint
        self.calls.append((fingerprint, use_guidance))
        route_budget = RoutingBudget(
            max_passes=policy.max_passes,
            max_expansions=policy.max_expansions,
            max_expansions_per_net=policy.max_expansions_per_net,
            max_stagnant_passes=policy.max_stagnant_passes,
            max_exact_check_rejections=0,
        )
        success = not self.fail
        routing = RoutingRunResult(
            producer="r5.4-fixture",
            budget=route_budget,
            success=success,
            failure_reason=None if success else RoutingFailureReason.UNROUTABLE,
            route_order=policy.target_nets,
            unresolved_net_names=() if success else policy.target_nets,
        )
        fixed_segments = tuple(
            item for item in source.probe.layout.segments if item.net_name not in policy.target_nets
        )
        target = TrackSegment(2.0, 2.0, 3.0, 2.0, "F.Cu", "A", 0.2)
        layout = replace(
            source.probe.layout,
            segments=fixed_segments + (() if self.fail else (target,)),
            vias=tuple(
                item for item in source.probe.layout.vias if item.net_name not in policy.target_nets
            ),
        )
        results = (
            ()
            if self.fail
            else (
                RouteResult(
                    net_name="A",
                    segments=(target,),
                    vias=(),
                    length_mm=1.0,
                ),
            )
        )
        if use_guidance:
            assert source.corridor_graph is not None and source.corridor_plan is not None
            guidance = CorridorGuidanceReport(
                disposition=CorridorGuidanceDisposition.APPLIED,
                plan_fingerprint=source.corridor_plan.semantic_fingerprint(),
                graph_fingerprint=source.corridor_graph.semantic_fingerprint(),
                guide_fingerprint="f" * 64,
                guided_net_names=("A",),
                routing_run_fingerprint=routing.semantic_fingerprint(),
            )
        else:
            guidance = CorridorGuidanceReport(
                disposition=CorridorGuidanceDisposition.ABSENT,
                unguided_net_names=("A",),
                routing_run_fingerprint=routing.semantic_fingerprint(),
            )
        return CorridorGuidedBoardRouteResult(
            route_result=NegotiatedBoardRouteResult(
                layout=layout,
                results=results,
                order=policy.target_nets,
                run_result=routing,
                exact_check=None,
            ),
            guidance=guidance,
        )


def _policy(
    *, quota: int = 0, penalty: int = 0
) -> tuple[PlacementDetailSelectionPolicy, PlacementR2Policy]:
    return (
        PlacementDetailSelectionPolicy(coarse_failure_exploration_quota=quota),
        PlacementR2Policy(
            target_nets=("A",),
            off_corridor_penalty_units=penalty,
            max_passes=4,
            max_expansions=20,
            max_expansions_per_net=10,
            max_stagnant_passes=2,
        ),
    )


def _run(
    inputs: dict[str, PlacementDetailInput],
    *,
    selected: int,
    r3: int = 10,
    r2: int = 10,
    quota: int = 0,
    evaluator: _FakeR2 | None = None,
):
    selection, r2_policy = _policy(quota=quota)
    adapter = evaluator or _FakeR2()
    return evaluate_placement_details(
        inputs,
        selection_policy=selection,
        budget=PlacementDetailBudget(
            max_selected_candidates=selected,
            max_corridor_evaluations=r3,
            max_routing_evaluations=r2,
        ),
        r2_policy=r2_policy,
        r2_evaluator=adapter,
    ), adapter


def test_dominated_candidate_consumes_no_detail_slot() -> None:
    inputs = _inputs(("ready", "dominated", "ready", "ready", "ready"))
    dominated = next(
        key for key, item in inputs.items() if item.surrogate.terminal_clearance_violation_count
    )
    run, adapter = _run(inputs, selected=3)
    assert dominated not in run.result.selected_candidate_fingerprints
    assert len(adapter.calls) == 3


def test_equal_front_prefers_distinct_corridor_allocations() -> None:
    inputs = _inputs(("ready",) * 5)
    run, _adapter = _run(inputs, selected=3)
    chosen = [item for item in run.result.pareto_evidence if item.selected]
    assert len({item.corridor_allocation_fingerprint for item in chosen}) == 3
    assert any(
        item.selection_reason is PlacementSelectionReason.CORRIDOR_DIVERSITY for item in chosen
    )


def test_base_and_coarse_failure_exploration_are_reserved() -> None:
    inputs = _inputs(("ready", "failed", "ready", "ready", "ready"))
    run, _adapter = _run(inputs, selected=2, quota=1)
    selected = [item for item in run.result.pareto_evidence if item.selected]
    assert {item.selection_reason for item in selected} == {
        PlacementSelectionReason.BASE,
        PlacementSelectionReason.COARSE_FAILURE_EXPLORATION,
    }


def test_coarse_failure_routes_unguided_to_routed_unchecked() -> None:
    inputs = _inputs(("failed", "ready", "ready", "ready", "ready"))
    run, adapter = _run(inputs, selected=1, quota=1)
    record = next(item for item in run.result.candidate_records if item.selected)
    assert adapter.calls == [(record.candidate_fingerprint, False)]
    assert record.state is PlacementDetailState.ROUTED_UNCHECKED
    assert record.algorithmic_success and record.zero_overuse and record.routed_unchecked


def test_guidance_is_soft_and_cannot_turn_router_failure_into_success() -> None:
    inputs = _inputs(("ready",) * 5)
    run, adapter = _run(inputs, selected=1, evaluator=_FakeR2(fail=True))
    record = next(item for item in run.result.candidate_records if item.selected)
    assert adapter.calls[0][1]
    assert record.state is PlacementDetailState.ROUTING_FAILED
    assert not record.algorithmic_success


def test_candidate_evaluation_is_independent_of_mapping_order() -> None:
    inputs = _inputs(("ready",) * 5)
    first, _ = _run(inputs, selected=3)
    second, _ = _run(dict(reversed(tuple(inputs.items()))), selected=3)
    assert first.result == second.result
    assert first.routed_layouts == second.routed_layouts


def test_zero_selection_budget_consumes_no_r3_or_r2_work() -> None:
    run, adapter = _run(_inputs(("ready",) * 5), selected=0)
    assert run.result.selected_candidate_fingerprints == ()
    assert run.result.corridor_evaluations_consumed == 0
    assert run.result.routing_evaluations_consumed == 0
    assert adapter.calls == []


def test_zero_and_one_less_r3_budgets_have_exact_states() -> None:
    inputs = _inputs(("ready",) * 5)
    zero, _ = _run(inputs, selected=3, r3=0)
    selected_zero = [item for item in zero.result.candidate_records if item.selected]
    assert {item.state for item in selected_zero} == {
        PlacementDetailState.CORRIDOR_BUDGET_EXHAUSTED
    }
    short, _ = _run(inputs, selected=3, r3=2)
    selected_short = [item for item in short.result.candidate_records if item.selected]
    assert sum(item.r3_evaluations_consumed for item in selected_short) == 2
    assert (
        sum(item.state is PlacementDetailState.CORRIDOR_BUDGET_EXHAUSTED for item in selected_short)
        == 1
    )


def test_zero_and_one_less_r2_budgets_have_exact_states() -> None:
    inputs = _inputs(("ready",) * 5)
    zero, _ = _run(inputs, selected=3, r2=0)
    selected_zero = [item for item in zero.result.candidate_records if item.selected]
    assert {item.state for item in selected_zero} == {PlacementDetailState.ROUTING_BUDGET_EXHAUSTED}
    short, _ = _run(inputs, selected=3, r2=2)
    selected_short = [item for item in short.result.candidate_records if item.selected]
    assert sum(item.r2_evaluations_consumed for item in selected_short) == 2
    assert (
        sum(item.state is PlacementDetailState.ROUTING_BUDGET_EXHAUSTED for item in selected_short)
        == 1
    )


def test_target_copper_is_replaced_non_target_preserved_and_repeat_is_pinned() -> None:
    inputs = _inputs(("ready",) * 5)
    first, _ = _run(inputs, selected=2)
    second, _ = _run(inputs, selected=2)
    assert first.result == second.result
    assert first.result.semantic_fingerprint() == second.result.semantic_fingerprint()
    assert first.result.selected_candidate_fingerprints == (
        "0edb4e28b09d4b6394d0c024a60dc095d22a873a6768eb773c1d62b2246eb37f",
        "aff3935ac1f8f90608239c00d78ff9c33b8d905be82afd968ee811e470fc80f6",
    )
    assert first.result.semantic_fingerprint() == (
        "426d95eb28888c26d831a4621445696357f793f51cd32006ea6f6f37e915f1f2"
    )
    selected_records = tuple(item for item in first.result.candidate_records if item.selected)
    assert tuple(item.corridor_plan_fingerprint for item in selected_records) == (
        "f2153d02a79945ae42ec9a6e51c70536036c58423c6529eb7f8c16f3a59df383",
        "f05cb50db71634cf96bb7946bab74f39f652f1e8a564650aa78a4a5176008217",
    )
    assert tuple(
        item.routing_run.semantic_fingerprint()
        for item in selected_records
        if item.routing_run is not None
    ) == (
        "c8e8f79be19e77f58744dfd2ace0f30ff6d71cd276c92eb9a9217495e0b1750c",
        "c8e8f79be19e77f58744dfd2ace0f30ff6d71cd276c92eb9a9217495e0b1750c",
    )
    assert tuple(item.route_geometry_fingerprint for item in selected_records) == (
        "7203b8e02baeb92f6eec701aae322e4679d0999404aab979fc0ca75b55a76f0a",
        "7203b8e02baeb92f6eec701aae322e4679d0999404aab979fc0ca75b55a76f0a",
    )
    for _candidate, layout in first.routed_layouts:
        assert tuple(item.net_name for item in layout.segments) == ("FIXED", "A")
        assert layout.graphics == ()
    copied = first.result.model_copy(
        update={"routing_evaluations_consumed": first.result.routing_evaluations_consumed + 1}
    )
    with pytest.raises(ValidationError):
        PlacementDetailRunResult.model_validate_json(copied.model_dump_json())
    values = tuple(inputs.values())
    with pytest.raises(ValueError, match="surrogate and candidate pose"):
        PlacementDetailInput(
            candidate=values[0].candidate,
            probe=values[0].probe,
            surrogate=values[1].surrogate,
            netlist=values[0].netlist,
            corridor_graph=values[1].corridor_graph,
            corridor_plan=values[1].corridor_plan,
        )


def test_absent_corridor_evidence_cannot_rank_as_ready_zero_overflow() -> None:
    inputs = _inputs(("absent", "ready", "ready", "ready", "ready"))
    run, _adapter = _run(inputs, selected=1)
    absent = next(
        item
        for item in run.result.pareto_evidence
        if inputs[item.candidate_fingerprint].surrogate.corridor.state
        is PlacementCorridorState.ABSENT
    )
    ready = next(
        item
        for item in run.result.pareto_evidence
        if inputs[item.candidate_fingerprint].surrogate.corridor.state
        is PlacementCorridorState.READY
    )
    assert absent.primary_vector[3] == 1
    assert ready.primary_vector[3] == 0
    assert absent.pareto_front_index > ready.pareto_front_index
    assert absent.dominated_by_candidate_fingerprints


def test_detail_input_rejects_missing_duplicate_and_stale_authority() -> None:
    inputs = _inputs(("ready",) * 5)
    values = tuple(inputs.values())
    first, second = values[:2]
    with pytest.raises(ValueError, match="requires graph and plan"):
        PlacementDetailInput(
            candidate=first.candidate,
            probe=first.probe,
            surrogate=first.surrogate,
            netlist=first.netlist,
            corridor_graph=first.corridor_graph,
            corridor_plan=None,
        )
    with pytest.raises(ValueError, match="graph/plan fingerprints"):
        PlacementDetailInput(
            candidate=first.candidate,
            probe=first.probe,
            surrogate=first.surrogate,
            netlist=first.netlist,
            corridor_graph=second.corridor_graph,
            corridor_plan=second.corridor_plan,
        )
    selection, r2_policy = _policy()
    with pytest.raises(ValueError, match="unique"):
        evaluate_placement_details(
            {first.candidate.candidate_fingerprint: first, "0" * 64: first},
            selection_policy=selection,
            budget=PlacementDetailBudget(
                max_selected_candidates=1,
                max_corridor_evaluations=1,
                max_routing_evaluations=1,
            ),
            r2_policy=r2_policy,
            r2_evaluator=_FakeR2(),
        )


def test_nested_routing_guidance_and_layout_tampering_is_rejected() -> None:
    run, _adapter = _run(_inputs(("ready",) * 5), selected=1)
    record = next(item for item in run.result.candidate_records if item.selected)
    assert record.guidance is not None and record.routing_run is not None
    forged_guidance = record.guidance.model_copy(update={"routing_run_fingerprint": "0" * 64})
    forged_record = record.model_copy(update={"guidance": forged_guidance})
    forged_result = run.result.model_copy(
        update={
            "candidate_records": tuple(
                forged_record if item == record else item for item in run.result.candidate_records
            )
        }
    )
    with pytest.raises(ValidationError, match="guidance"):
        PlacementDetailRunResult.model_validate_json(forged_result.model_dump_json())

    forged_layout_record = record.model_copy(update={"materialized_layout_fingerprint": "0" * 64})
    forged_layout_result = run.result.model_copy(
        update={
            "candidate_records": tuple(
                forged_layout_record if item == record else item
                for item in run.result.candidate_records
            )
        }
    )
    validated = PlacementDetailRunResult.model_validate_json(forged_layout_result.model_dump_json())
    with pytest.raises(ValueError, match="routed layout"):
        PlacementDetailRun(result=validated, routed_layouts=run.routed_layouts)


def _install_production_r2_fixture(
    monkeypatch: pytest.MonkeyPatch,
    graph: CorridorGraph,
) -> list[tuple[int, float]]:
    calls: list[tuple[int, float]] = []
    graph_build = CorridorGraphBuildResult(
        complete=True,
        planning_supported=True,
        graph=graph,
        graphics_policy=OpaqueGraphicsPolicy.REJECT_OPAQUE,
        budget=CorridorGraphBuildBudget(),
    )
    monkeypatch.setattr(
        negotiated_board,
        "build_corridor_graph",
        lambda *_args, **_kwargs: graph_build,
    )
    monkeypatch.setattr(
        negotiated_board,
        "_routable_nets",
        lambda _layout, _netlist, _profile: {"A": 0.2},
    )

    def fake_search(*args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        layout = args[0]
        net_name = args[2]
        guide = kwargs.get("soft_guide")
        assert isinstance(net_name, str)
        assert guide is None or isinstance(guide, GridSoftGuide)
        penalty = 0 if guide is None else guide.off_guide_transition_cost_units
        if penalty == 77:
            y_mm = 3.0
        elif penalty == 99:
            assert any(
                item.net_name == "FIXED" and item.layer == "F.Cu" and item.y1 == 1.0
                for item in layout.segments
            )
            y_mm = 2.0
        else:
            y_mm = 2.0
        calls.append((penalty, y_mm))
        segment = TrackSegment(2.0, y_mm, 3.0, y_mm, "F.Cu", net_name, 0.2)
        return NegotiatedGridRoute(
            result=RouteResult(
                net_name=net_name,
                segments=(segment,),
                vias=(),
                length_mm=1.0,
                expansion_count=1,
            ),
            claims=NetResourceClaims(net_name, frozenset()),
            base_cost_units=1000,
            congestion_cost_units=0,
        )

    monkeypatch.setattr(negotiated_board, "route_net_negotiated_candidate", fake_search)
    return calls


def _production_source() -> PlacementDetailInput:
    return next(iter(_inputs(("ready",) * 5).values()))


def test_production_adapter_zero_penalty_matches_unguided_geometry_and_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _production_source()
    assert source.corridor_graph is not None
    calls = _install_production_r2_fixture(monkeypatch, source.corridor_graph)
    _selection, policy = _policy(penalty=0)
    evaluator = KiCadPlacementR2Evaluator()
    guided = evaluator(source, use_guidance=True, policy=policy, profile=DEFAULT_PCB_RULE_PROFILE)
    unguided = evaluator(
        source, use_guidance=False, policy=policy, profile=DEFAULT_PCB_RULE_PROFILE
    )
    assert guided.route_result.layout == unguided.route_result.layout
    assert guided.route_result.run_result == unguided.route_result.run_result
    assert guided.guidance.disposition is CorridorGuidanceDisposition.APPLIED
    assert unguided.guidance.disposition is CorridorGuidanceDisposition.ABSENT
    assert calls == [(0, 2.0), (0, 2.0)]


def test_production_adapter_guidance_steers_symmetric_legal_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _production_source()
    assert source.corridor_graph is not None
    _install_production_r2_fixture(monkeypatch, source.corridor_graph)
    _selection, guided_policy = _policy(penalty=77)
    _selection, ordinary_policy = _policy(penalty=0)
    evaluator = KiCadPlacementR2Evaluator()
    guided = evaluator(
        source,
        use_guidance=True,
        policy=guided_policy,
        profile=DEFAULT_PCB_RULE_PROFILE,
    )
    ordinary = evaluator(
        source,
        use_guidance=False,
        policy=ordinary_policy,
        profile=DEFAULT_PCB_RULE_PROFILE,
    )
    assert guided.route_result.results[0].segments[0].y1 == 3.0
    assert ordinary.route_result.results[0].segments[0].y1 == 2.0


def test_production_adapter_guidance_cannot_unblock_static_hard_obstacle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _production_source()
    assert source.corridor_graph is not None
    calls = _install_production_r2_fixture(monkeypatch, source.corridor_graph)
    _selection, policy = _policy(penalty=99)
    result = KiCadPlacementR2Evaluator()(
        source,
        use_guidance=True,
        policy=policy,
        profile=DEFAULT_PCB_RULE_PROFILE,
    )
    fixed = tuple(item for item in result.route_result.layout.segments if item.net_name == "FIXED")
    routed = result.route_result.results[0].segments[0]
    assert fixed == (TrackSegment(0.0, 1.0, 1.0, 1.0, "F.Cu", "FIXED", 0.3),)
    assert routed.y1 == 2.0
    assert calls == [(99, 2.0)]
