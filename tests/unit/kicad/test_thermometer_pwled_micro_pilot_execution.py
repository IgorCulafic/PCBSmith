from __future__ import annotations

import copy
import os
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_guidance import CorridorGuidanceDisposition
from pcbsmith.corridor_ir import CorridorBudget, CorridorFailureReason, CorridorViaPolicy
from pcbsmith.kicad.aggregate_exact_checker import (
    AggregateCheckStatus,
    AggregateSubcheckKind,
    evaluate_stable_aggregate_exact_check,
)
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.board_serialization import (
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.corridor_planner import (
    CorridorGraphBuildBudget,
    CorridorGraphBuildFailure,
    build_corridor_graph,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.negotiated_board import route_board_corridor_guided
from pcbsmith.kicad.placement_readback import verify_placement_kicad_save_roundtrip
from pcbsmith.kicad.placement_serialization import build_placement_serialization_authority
from pcbsmith.kicad.thermometer_pwled_micro_pilot_execution import (
    EXECUTION_SCOPE,
    EXPECTED_ROUTE_SEGMENT_COUNT,
    ThermometerPwledMicroPilotExecution,
    build_thermometer_pwled_micro_pilot_execution,
)
from pcbsmith.placement_ir import PlacementLegalizationOutcome
from pcbsmith.routing_ir import RoutingFailureReason


@pytest.fixture(scope="module")
def execution() -> ThermometerPwledMicroPilotExecution:
    return build_thermometer_pwled_micro_pilot_execution()


def test_execution_is_deterministic_and_json_replayable(
    execution: ThermometerPwledMicroPilotExecution,
) -> None:
    rebuilt = build_thermometer_pwled_micro_pilot_execution()

    assert rebuilt == execution
    assert rebuilt.execution_fingerprint == execution.execution_fingerprint
    assert (
        ThermometerPwledMicroPilotExecution.model_validate_json(execution.model_dump_json())
        == execution
    )


def test_reviewed_move_is_the_only_placement_delta(
    execution: ThermometerPwledMicroPilotExecution,
) -> None:
    base = parse_canonical_board_layout_snapshot(execution.base_layout_snapshot_json)
    probe = parse_canonical_board_layout_snapshot(execution.probe_layout_snapshot_json)
    final = parse_canonical_board_layout_snapshot(execution.final_layout_snapshot_json)
    base_x = {component.reference: x_mm for component, x_mm in base.placements}
    probe_x = {component.reference: x_mm for component, x_mm in probe.placements}
    final_x = {component.reference: x_mm for component, x_mm in final.placements}

    assert execution.reviewed_move.reference == "R17"
    assert execution.reviewed_move.delta_x_mm == -0.5
    assert probe_x == {"D17": base_x["D17"], "R17": base_x["R17"] - 0.5}
    assert final_x == probe_x
    assert execution.probe_result.telemetry.changed_layout_fields == ("placements",)
    assert execution.legalization.outcome is PlacementLegalizationOutcome.LEGAL_EXACT


def test_r3_plan_is_successful_but_not_claimed_as_route_guidance(
    execution: ThermometerPwledMicroPilotExecution,
) -> None:
    assert execution.graph_build.complete
    assert execution.graph_build.planning_supported
    assert len(execution.graph_build.graph.cells) == 56
    assert len(execution.graph_build.graph.portals) == 82
    assert len(execution.graph_build.graph.issues) == 2
    assert len(execution.demands) == 1
    assert execution.demands[0].net_name == "/PWLED"
    assert execution.demands[0].allowed_layers == ("F.Cu",)
    assert execution.demands[0].via_policy is CorridorViaPolicy.FORBIDDEN
    assert execution.corridor_plan.guidance_ready
    assert execution.verified_summary.summary.expansion_count == 202
    assert execution.verified_summary.summary.channel_total_overflow_units == 0
    assert execution.verified_summary.summary.via_total_overflow_units == 0

    assert execution.guidance.disposition is CorridorGuidanceDisposition.INCOMPATIBLE
    assert execution.guidance.guided_net_names == ()
    assert execution.guidance.unguided_net_names == ("/PWLED",)
    assert not execution.r3_guided_routing_claimed


def test_ordinary_r2_fallback_and_offline_aggregate_pass(
    execution: ThermometerPwledMicroPilotExecution,
) -> None:
    assert execution.routing_run.success
    assert execution.routing_run.failure_reason is None
    assert execution.routing_run.unresolved_net_names == ()
    assert execution.routing_run.resource_overuse == ()
    assert sum(route_pass.expansion_count for route_pass in execution.routing_run.passes) == 271
    assert len(execution.route_segments) == EXPECTED_ROUTE_SEGMENT_COUNT
    assert {segment.layer for segment in execution.route_segments} == {"F.Cu"}
    assert {segment.net_name for segment in execution.route_segments} == {"/PWLED"}
    assert execution.route_via_count == 0

    assert execution.aggregate.aggregate_result.accepted
    assert execution.aggregate.policy.design_checks_spec == DesignChecksSpec()
    assert {item.kind for item in execution.aggregate.policy.subchecks} == {
        AggregateSubcheckKind.DESIGN_CHECKS,
        AggregateSubcheckKind.VIRTUAL_DRC,
    }
    assert {item.status for item in execution.aggregate.subchecks} == {AggregateCheckStatus.PASS}


def test_serialization_proves_only_r17_pose_and_pwled_copper_changed(
    execution: ThermometerPwledMicroPilotExecution,
) -> None:
    changed = tuple(item for item in execution.serialization.field_delta_evidence if item.changed)

    assert tuple(item.field_name for item in changed) == ("placements", "segments")
    assert changed[0].affected_references == ("R17",)
    assert changed[0].affected_target_nets == ()
    assert changed[1].affected_references == ()
    assert changed[1].affected_target_nets == ("/PWLED",)
    assert tuple(
        item.reference for item in execution.serialization.component_identity_evidence
    ) == ("D17", "R17")


@pytest.mark.parametrize(
    ("budget", "complete"),
    (
        (CorridorGraphBuildBudget(max_cells=120, max_portals=82), True),
        (CorridorGraphBuildBudget(max_cells=119, max_portals=82), False),
        (CorridorGraphBuildBudget(max_cells=120, max_portals=81), False),
    ),
)
def test_graph_budget_exact_thresholds_and_one_less_fail_closed(
    execution: ThermometerPwledMicroPilotExecution,
    budget: CorridorGraphBuildBudget,
    complete: bool,
) -> None:
    authority = execution.pilot_input.authority
    probe = parse_canonical_board_layout_snapshot(execution.probe_layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(execution.netlist_snapshot_json)

    result = build_corridor_graph(
        probe,
        netlist,
        target_nets=authority.target_net_names,
        net_widths=dict(authority.target_net_widths_mm),
        default_width_mm=authority.r2_policy.default_width_mm,
        profile=authority.profile,
        clearance_groups=(),
        coarse_grid_mm=authority.coarse_grid_mm,
        capacity_quantum_mm=authority.corridor_capacity_quantum_mm,
        graphics_policy=authority.corridor_graphics_policy,
        budget=budget,
    )

    assert result.complete is complete
    assert result.planning_supported is complete
    assert result.failure_reason is (
        None if complete else CorridorGraphBuildFailure.GEOMETRY_BUDGET
    )


@pytest.mark.parametrize(("expansions", "ready"), ((49, True), (48, False)))
def test_corridor_plan_minimum_expansion_threshold_and_one_less(
    execution: ThermometerPwledMicroPilotExecution,
    expansions: int,
    ready: bool,
) -> None:
    authority = execution.pilot_input.authority
    plan = negotiate_corridor_allocations(
        execution.graph_build.graph,
        execution.demands,
        budget=CorridorBudget(
            max_passes=4,
            max_expansions=expansions,
            max_expansions_per_demand=expansions,
            max_stagnant_passes=2,
        ),
        cost_policy=authority.corridor_cost_policy,
    )

    assert plan.guidance_ready is ready
    assert plan.failure_reason is (None if ready else CorridorFailureReason.EXPANSION_BUDGET)


@pytest.mark.parametrize(("expansions", "success"), ((271, True), (270, False)))
def test_r2_minimum_expansion_threshold_and_one_less(
    execution: ThermometerPwledMicroPilotExecution,
    expansions: int,
    success: bool,
) -> None:
    authority = execution.pilot_input.authority
    r2 = authority.r2_policy
    probe = parse_canonical_board_layout_snapshot(execution.probe_layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(execution.netlist_snapshot_json)
    result = route_board_corridor_guided(
        probe,
        netlist,
        corridor_graph=execution.graph_build.graph,
        corridor_plan=execution.corridor_plan,
        off_corridor_penalty_units=r2.off_corridor_penalty_units,
        target_nets=r2.target_nets,
        net_widths=dict(r2.net_widths_mm),
        default_width_mm=r2.default_width_mm,
        profile=authority.profile,
        net_order=r2.net_order,
        grid_mm=r2.grid_mm,
        clearance_groups=(),
        max_passes=r2.max_passes,
        max_expansions=expansions,
        max_expansions_per_net=expansions,
        max_stagnant_passes=r2.max_stagnant_passes,
        cost_policy=authority.negotiated_cost_policy.reconstruct(),
    )

    assert result.route_result.run_result.success is success
    assert result.route_result.run_result.failure_reason is (
        None if success else RoutingFailureReason.EXPANSION_BUDGET
    )


def test_serialization_and_aggregate_reject_out_of_scope_or_bad_geometry(
    execution: ThermometerPwledMicroPilotExecution,
) -> None:
    authority = execution.pilot_input.authority
    base = parse_canonical_board_layout_snapshot(execution.base_layout_snapshot_json)
    final = parse_canonical_board_layout_snapshot(execution.final_layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(execution.netlist_snapshot_json)
    unauthorized = replace(
        final,
        placements=tuple(
            (component, x_mm + (0.5 if component.reference == "D17" else 0.0))
            for component, x_mm in final.placements
        ),
    )
    with pytest.raises(ValueError, match="fixed reference 'D17'"):
        build_placement_serialization_authority(
            base,
            netlist,
            unauthorized,
            authority.target_net_names,
            authority.movable_references,
            profile=authority.profile,
        )

    colliding = replace(
        final,
        segments=final.segments + (TrackSegment(5.0, 3.0, 6.5, 3.0, "F.Cu", "/PWLED", 0.25),),
    )
    rejected = evaluate_stable_aggregate_exact_check(
        colliding,
        netlist,
        execution.aggregate.policy,
        (),
    )
    assert not rejected.aggregate_result.accepted
    by_id = {item.subcheck_id: item.status for item in rejected.subchecks}
    assert by_id["virtual-drc"] is AggregateCheckStatus.FAIL


def test_scope_is_literal_and_all_expansive_claims_are_false(
    execution: ThermometerPwledMicroPilotExecution,
) -> None:
    assert execution.scope == EXECUTION_SCOPE
    assert not execution.full_board_claimed
    assert not execution.full_template_preservation_claimed
    assert not execution.fixed_neighbor_preservation_claimed
    assert not execution.circuit_board_equivalence_claimed
    assert not execution.thermometer_readiness_claimed
    assert not execution.r3_guided_routing_claimed
    assert not execution.routing_superiority_claimed
    assert not execution.reader_schematic_checked
    assert not execution.simulation_checked
    assert not execution.kicad_live_checked


@pytest.mark.skipif(
    os.environ.get("PCBSMITH_PWLED_MICRO_KICAD_GOLDEN") != "1",
    reason=("set PCBSMITH_PWLED_MICRO_KICAD_GOLDEN=1 to exercise the installed KiCad CLI"),
)
def test_live_kicad_save_repeated_save_readback_and_clean_drc_are_separate_evidence(
    execution: ThermometerPwledMicroPilotExecution,
    tmp_path: Path,
) -> None:
    live = verify_placement_kicad_save_roundtrip(
        execution.serialization,
        tmp_path,
        require_drc_pass=True,
    )

    assert live.kicad_cli_version
    assert live.initial_snapshot == live.saved_snapshot
    assert live.saved_board_sha256 == live.repeated_saved_board_sha256
    assert live.drc_status == "passed"
    assert live.drc_findings == ()
    # The optional live result remains external to the offline replay wrapper.
    assert not execution.kicad_live_checked


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("reviewed_move", "delta_x_mm"), 0.0),
        (("route_segments", 0, "x1_mm"), 999.0),
        (("fingerprints", "routing_run"), "0" * 64),
        (("execution_fingerprint",), "0" * 64),
        (("r3_guided_routing_claimed",), True),
    ),
)
def test_tampering_is_rejected(
    execution: ThermometerPwledMicroPilotExecution,
    path: tuple[str | int, ...],
    replacement: object,
) -> None:
    payload = copy.deepcopy(execution.model_dump(mode="json"))
    target: object = payload
    for key in path[:-1]:
        assert isinstance(target, (dict, list))
        target = target[key]  # type: ignore[index]
    assert isinstance(target, (dict, list))
    target[path[-1]] = replacement  # type: ignore[index]

    with pytest.raises(ValidationError):
        ThermometerPwledMicroPilotExecution.model_validate(payload)
