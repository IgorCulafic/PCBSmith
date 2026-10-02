from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Literal

import pytest

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
)
from pcbsmith.kicad.routing_candidate_adapter import (
    native_routing_netlist_fingerprint,
    native_routing_profile_fingerprint,
    native_source_route_objects,
    route_native_candidate,
    stable_route_terminal_object_id,
)
from pcbsmith.routing_ir import (
    DeterministicRoutingConfiguration,
    PartialCandidateStatus,
    ProtectedRouteObjectPolicy,
    RouteClearanceConstraint,
    RouteFailureKind,
    RouteRequest,
    RouteTerminationState,
    RouteTopologyConstraint,
    RouteViaTechnology,
    RouteWidthConstraint,
    RoutingBudget,
    RoutingInputIdentity,
    TargetRouteDomain,
    TargetRouteNet,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

RESISTOR = "Resistor_SMD:R_0603_1608Metric"
BOARD_SHA = "b" * 64
OTHER_SHA = "a" * 64


def _fixture(
    segments: tuple[TrackSegment, ...] = (),
) -> tuple[BoardLayout, BoardNetlist]:
    components = (
        BoardComponent(
            reference="R1",
            value="1k",
            footprint=RESISTOR,
            uuid_path="fixture/r1",
        ),
        BoardComponent(
            reference="R2",
            value="1k",
            footprint=RESISTOR,
            uuid_path="fixture/r2",
        ),
    )
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet(name="/SIG", nodes=(("R1", "2"), ("R2", "1"))),
            BoardNet(name="/A", nodes=(("R1", "1"),)),
            BoardNet(name="/B", nodes=(("R2", "2"),)),
        ),
    )
    layout = BoardLayout(
        placements=((components[0], 5.0), (components[1], 25.0)),
        segments=segments,
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
        part_y_mm=(("R1", 6.0), ("R2", 6.0)),
    )
    return layout, netlist


def _request(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    topology_kind: Literal[
        "any_tree",
        "ordered_path",
        "star",
        "source_to_sinks",
        "paired_bundle",
    ] = "any_tree",
    max_expansions: int = 100_000,
    protected: bool = False,
) -> RouteRequest:
    terminal_ids = tuple(
        stable_route_terminal_object_id(
            net_name="/SIG",
            reference=reference,
            pin=pin,
        )
        for reference, pin in netlist.nets[0].nodes
    )
    source_objects = native_source_route_objects(
        layout,
        source_board_sha256=BOARD_SHA,
    )
    profile = DEFAULT_PCB_RULE_PROFILE
    return RouteRequest(
        request_id="request:native-fixture",
        inputs=RoutingInputIdentity(
            project_sha256=OTHER_SHA,
            board_sha256=BOARD_SHA,
            schematic_sha256="c" * 64,
            netlist_sha256=native_routing_netlist_fingerprint(netlist),
            placement_sha256="d" * 64,
            outline_sha256="e" * 64,
            holes_sha256="f" * 64,
            rules_sha256=native_routing_profile_fingerprint(profile),
            protected_copper_sha256="0" * 64,
        ),
        target_domains=(
            TargetRouteDomain(
                domain_id="domain:ordinary",
                nets=(
                    TargetRouteNet(
                        net_name="/SIG",
                        terminal_object_ids=terminal_ids,
                    ),
                ),
                priority=0,
            ),
        ),
        source_route_objects=source_objects,
        protected_policy=ProtectedRouteObjectPolicy(
            protected_objects=source_objects if protected else (),
        ),
        allowed_layers=("F.Cu", "B.Cu"),
        width_constraints=(
            RouteWidthConstraint(
                constraint_id="constraint:width:sig",
                net_names=("/SIG",),
                minimum_width_mm=0.2,
                preferred_width_mm=0.4,
                maximum_width_mm=0.6,
            ),
        ),
        clearance_constraints=(
            RouteClearanceConstraint(
                constraint_id="constraint:clearance:sig",
                net_names=("/SIG",),
                other_net_names=("/A", "/B"),
                minimum_clearance_mm=0.2,
            ),
        ),
        via_technologies=(
            RouteViaTechnology(
                constraint_id="constraint:via:through",
                technology_id="via:through-default",
                start_layer="F.Cu",
                end_layer="B.Cu",
                diameter_mm=profile.geometry.routing_via_diameter_mm,
                drill_mm=profile.geometry.routing_via_drill_mm,
            ),
        ),
        topology_constraints=(
            RouteTopologyConstraint(
                constraint_id="constraint:topology:sig",
                domain_id="domain:ordinary",
                net_name="/SIG",
                topology_kind=topology_kind,
                ordered_terminal_object_ids=terminal_ids,
            ),
        ),
        budget=RoutingBudget(
            max_passes=4,
            max_expansions=max_expansions,
            max_expansions_per_net=max_expansions,
            max_stagnant_passes=2,
            max_exact_check_rejections=0,
        ),
        deterministic=DeterministicRoutingConfiguration(
            seed=0,
            route_order=("/SIG",),
            tie_break_policy="pcbsmith-native-lexical-v1",
        ),
    )


def _fixed_clock() -> Iterator[float]:
    yield 10.0
    yield 11.0


def test_native_adapter_returns_a_clean_immutable_candidate_delta() -> None:
    layout, netlist = _fixture()
    request = _request(layout, netlist)
    times = _fixed_clock()

    result = route_native_candidate(
        request=request,
        layout=layout,
        netlist=netlist,
        engine_source_commit="fixture",
        clock=lambda: next(times),
    )

    assert result.partial_status is PartialCandidateStatus.COMPLETE
    assert result.termination.state is RouteTerminationState.COMPLETED
    assert result.run_telemetry is not None
    assert result.run_telemetry.success
    assert result.run_telemetry.budget.max_stagnant_passes == request.budget.max_stagnant_passes
    assert result.segment_deltas
    assert not result.via_deltas
    assert all(item.operation.value == "add" for item in result.segment_deltas)
    assert {item.constraint_id for item in result.constraint_consumption} == set(
        request.constraint_ids
    )


def test_native_adapter_is_repeatable_for_identical_inputs_and_evidence_clock() -> None:
    layout, netlist = _fixture()
    request = _request(layout, netlist)

    first_times = _fixed_clock()
    second_times = _fixed_clock()
    first = route_native_candidate(
        request=request,
        layout=layout,
        netlist=netlist,
        engine_source_commit="fixture",
        clock=lambda: next(first_times),
    )
    second = route_native_candidate(
        request=request,
        layout=layout,
        netlist=netlist,
        engine_source_commit="fixture",
        clock=lambda: next(second_times),
    )

    assert first == second
    assert first.semantic_json() == second.semantic_json()
    assert first.semantic_fingerprint() == second.semantic_fingerprint()


def test_native_adapter_preserves_protected_existing_copper() -> None:
    wall = TrackSegment(
        x1=15.0,
        y1=1.0,
        x2=15.0,
        y2=8.0,
        layer="F.Cu",
        net_name="/WALL",
        width_mm=0.4,
    )
    layout, netlist = _fixture((wall,))
    request = _request(layout, netlist, protected=True)
    times = _fixed_clock()

    result = route_native_candidate(
        request=request,
        layout=layout,
        netlist=netlist,
        clock=lambda: next(times),
    )

    assert result.partial_status is PartialCandidateStatus.COMPLETE
    protected_ids = {item.object_id for item in request.protected_policy.protected_objects}
    assert (
        not {
            item.source_object_id
            for item in result.segment_deltas
            if item.source_object_id is not None
        }
        & protected_ids
    )


def test_native_adapter_rejects_unsupported_topology_without_running() -> None:
    layout, netlist = _fixture()
    request = _request(layout, netlist, topology_kind="ordered_path")

    result = route_native_candidate(
        request=request,
        layout=layout,
        netlist=netlist,
    )

    assert result.partial_status is PartialCandidateStatus.FAILED_NO_DELTA
    assert result.termination.state is RouteTerminationState.FAILED
    assert result.run_telemetry is None
    assert result.failures[0].kind is RouteFailureKind.UNSUPPORTED_CONSTRAINT
    assert result.failures[0].constraint_ids == ("constraint:topology:sig",)


def test_native_adapter_retains_budget_exhaustion_evidence() -> None:
    layout, netlist = _fixture()
    request = _request(layout, netlist, max_expansions=0)
    times = _fixed_clock()

    result = route_native_candidate(
        request=request,
        layout=layout,
        netlist=netlist,
        clock=lambda: next(times),
    )

    assert result.partial_status is PartialCandidateStatus.FAILED_NO_DELTA
    assert result.termination.state is RouteTerminationState.BUDGET_EXHAUSTED
    assert result.failures[0].kind is RouteFailureKind.BUDGET_EXHAUSTED
    assert result.run_telemetry is not None
    assert not result.run_telemetry.success


def test_native_adapter_rejects_stale_netlist_rules_and_source_copper() -> None:
    layout, netlist = _fixture()
    request = _request(layout, netlist)

    with pytest.raises(ValueError, match="netlist identity is stale"):
        route_native_candidate(
            request=request.model_copy(
                update={"inputs": request.inputs.model_copy(update={"netlist_sha256": OTHER_SHA})}
            ),
            layout=layout,
            netlist=netlist,
        )
    with pytest.raises(ValueError, match="rule-profile identity is stale"):
        route_native_candidate(
            request=request.model_copy(
                update={"inputs": request.inputs.model_copy(update={"rules_sha256": OTHER_SHA})}
            ),
            layout=layout,
            netlist=netlist,
        )
    changed = replace(
        layout,
        segments=(
            TrackSegment(
                x1=1,
                y1=1,
                x2=2,
                y2=1,
                layer="F.Cu",
                net_name="/A",
            ),
        ),
    )
    with pytest.raises(ValueError, match="source-copper inventory is stale"):
        route_native_candidate(
            request=request,
            layout=changed,
            netlist=netlist,
        )


def test_source_route_object_inventory_is_deterministic_and_typed() -> None:
    segment = TrackSegment(
        x1=1,
        y1=1,
        x2=2,
        y2=1,
        layer="F.Cu",
        net_name="/A",
    )
    layout, _netlist = _fixture((segment,))

    first = native_source_route_objects(
        layout,
        source_board_sha256=BOARD_SHA,
    )
    second = native_source_route_objects(
        layout,
        source_board_sha256=BOARD_SHA,
    )

    assert first == second
    assert first[0].object_kind.value == "segment"
    assert first[0].source_board_sha256 == BOARD_SHA


def test_native_adapter_retains_stagnation_stop_without_retry(monkeypatch):
    from pcbsmith.kicad import astar_router

    layout, netlist = _fixture()
    request = _request(layout, netlist)
    request = request.model_copy(
        update={
            "budget": request.budget.model_copy(update={"max_stagnant_passes": 0}),
        }
    )

    def blocked(*args, **kwargs):
        raise astar_router.RoutingError("synthetic blocked route", expansion_count=1)

    monkeypatch.setattr(astar_router, "route_net", blocked)
    result = route_native_candidate(
        request=request,
        layout=layout,
        netlist=netlist,
        engine_source_commit="fixture",
    )
    assert result.termination.state is RouteTerminationState.BUDGET_EXHAUSTED
    assert result.termination.reason == "stagnation"
    assert result.partial_status is PartialCandidateStatus.FAILED_NO_DELTA
    assert result.run_telemetry.budget.max_stagnant_passes == 0
    assert len(result.run_telemetry.passes) == 1
    assert result.run_telemetry.restart_count == 0


def test_native_serialization_binds_saved_coordinate_precision():
    from decimal import Decimal

    from pcbsmith.kicad.routing_candidate_transaction import apply_declared_route_deltas

    layout, netlist = _fixture()
    request = _request(layout, netlist)
    candidate = route_native_candidate(
        request=request, layout=layout, netlist=netlist, native_serialization=True
    )
    assert candidate.partial_status is PartialCandidateStatus.COMPLETE
    routed = apply_declared_route_deltas(request=request, candidate=candidate, source_layout=layout)
    assert routed.segments
    for segment in routed.segments:
        for value in (segment.x1, segment.y1, segment.x2, segment.y2, segment.width_mm):
            assert Decimal(str(value)) == Decimal(str(value)).quantize(Decimal("0.001"))
    assert routed.placements == layout.placements


def test_native_serialization_rejects_existing_copper():
    layout, netlist = _fixture(
        (TrackSegment(x1=6.0, y1=6.0, x2=7.0, y2=6.0, width_mm=0.4, layer="F.Cu", net_name="/SIG"),)
    )
    with pytest.raises(ValueError, match="unrouted"):
        route_native_candidate(
            request=_request(layout, netlist),
            layout=layout,
            netlist=netlist,
            native_serialization=True,
        )
