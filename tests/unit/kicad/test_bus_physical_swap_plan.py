from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_bus_physical_swap import (
    _boundary,
    _bus,
    _certificate,
    _finish,
    _geometry,
    _neutral_inputs,
    _region_payload,
)

from pcbsmith.bus_allocator import BusAllocationBudget, allocate_bus_lanes
from pcbsmith.bus_geometry import (
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
    certified_keep_in_fingerprint,
)
from pcbsmith.bus_ir import (
    BusGroup,
    BusLayerPolicy,
    BusPermutationPolicy,
    BusSwapWindow,
    BusViaPolicy,
    CertifiedCorridorSection,
    CertifiedLaneSlot,
    CorridorCapacityCertificate,
)
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.bus_physical_swap import (
    BusPhysicalSwapBudget,
    BusPhysicalSwapPolicy,
    BusPhysicalSwapWindowPolicy,
    BusSwapMemberPortalAuthority,
    bus_physical_swap_board_geometry_fingerprint,
    bus_physical_swap_profile_fingerprint,
    bus_physical_swap_static_obstacle_fingerprint,
)
from pcbsmith.kicad.bus_physical_swap_plan import (
    BusPhysicalSwapPlan,
    BusPhysicalSwapPlanBuildOutcome,
    BusPhysicalSwapPlanDisposition,
    BusPhysicalSwapPlanFailureReason,
    BusPhysicalSwapPlanInput,
    ReplayBoundBusPhysicalSwapPlan,
    build_replay_bound_bus_physical_swap_plan,
)
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    OrdinaryClearanceRequirement,
)


def _one_event(*, carrier_candidates: int = 4):
    region = _finish(
        _region_payload(
            policy_updates={
                "budget": BusPhysicalSwapBudget(
                    max_events=1,
                    max_candidates_per_event=carrier_candidates,
                    max_expansions_per_candidate=100,
                )
            }
        )
    )
    return _build(region=region, regions=(region,))


def _build(
    *,
    region: Any,
    regions: tuple[Any, ...],
    ledger: OccupancyLedger | None = None,
):
    return build_replay_bound_bus_physical_swap_plan(
        layout=region.layout,
        netlist=region.netlist,
        bus=region.bus,
        certificate=region.certificate,
        allocation=region.allocation,
        lane_geometry_registry=region.lane_geometry_registry,
        rule_profile=region.rule_profile,
        physical_policy=region.physical_policy,
        initial_occupancy=ledger or OccupancyLedger(),
        regions=regions,
    )


def _zero_event():
    layout, netlist = _neutral_inputs()
    base = _bus()
    bus = base.model_copy(
        update={
            "boundaries": (
                _boundary("entry", "portal:entry", ("m0", "m1", "m2")),
                _boundary("middle", "portal:middle", ("m0", "m1", "m2")),
                _boundary("exit", "portal:exit", ("m0", "m1", "m2")),
            ),
            "permutation_policy": BusPermutationPolicy(),
        }
    )
    certificate = _certificate(bus, layout, netlist)
    allocation = allocate_bus_lanes(bus, certificate, budget=BusAllocationBudget(max_states=20))
    geometries = tuple(
        _geometry(certificate, section_id, index)
        for section_id in ("section:incoming", "section:outgoing")
        for index in range(3)
    )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=geometries,
    )
    policy = BusPhysicalSwapPolicy(
        windows=(),
        maximum_physical_vias_per_member=2,
        maximum_combined_vias_per_member=2,
        maximum_combined_via_count_spread=2,
        budget=BusPhysicalSwapBudget(
            max_events=0,
            max_candidates_per_event=2,
            max_expansions_per_candidate=1,
        ),
    )
    return build_replay_bound_bus_physical_swap_plan(
        layout=layout,
        netlist=netlist,
        bus=bus,
        certificate=certificate,
        allocation=allocation,
        lane_geometry_registry=registry,
        rule_profile=DEFAULT_PCB_RULE_PROFILE,
        physical_policy=policy,
        initial_occupancy=OccupancyLedger(),
        regions=(),
    )


def _same_section_two_event_authority():
    layout, netlist = _neutral_inputs()
    via_policy = BusViaPolicy(
        mode="independent_bounded",
        maximum_vias_per_member=4,
        maximum_via_count_spread=4,
    )
    base = _bus(via_policy)
    bus = BusGroup(
        bus_id=base.bus_id,
        members=base.members,
        boundaries=(
            _boundary("entry", "portal:entry", ("m0", "m1", "m2")),
            _boundary("middle", "portal:middle", ("m1", "m2", "m0")),
            _boundary("exit", "portal:exit", ("m1", "m2", "m0")),
        ),
        permutation_policy=BusPermutationPolicy(
            swap_windows=(
                BusSwapWindow(
                    window_id="swap:main",
                    corridor_region_id="section:incoming",
                    allowed_adjacent_pairs=(
                        ("m0", "m1"),
                        ("m0", "m2"),
                        ("m1", "m2"),
                    ),
                    allowed_layers=("F.Cu",),
                    maximum_swaps=2,
                ),
            )
        ),
        layer_policy=BusLayerPolicy(
            allowed_layers=("B.Cu", "F.Cu"),
            preferred_layers=("F.Cu",),
            via_policy=via_policy,
        ),
        rule_profile_id=base.rule_profile_id,
    )
    certificate = _certificate(bus, layout, netlist)
    allocation = allocate_bus_lanes(bus, certificate, budget=BusAllocationBudget(max_states=100))
    assert allocation.success and len(allocation.swaps) == 2
    geometries = tuple(
        _geometry(certificate, section_id, index)
        for section_id in ("section:incoming", "section:outgoing")
        for index in range(3)
    )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=geometries,
    )
    policy = BusPhysicalSwapPolicy(
        windows=(
            BusPhysicalSwapWindowPolicy(
                window_id="swap:main",
                bridge_layer="B.Cu",
                via_process_id="through-via:default",
            ),
        ),
        maximum_physical_vias_per_member=4,
        maximum_combined_vias_per_member=4,
        maximum_combined_via_count_spread=4,
        budget=BusPhysicalSwapBudget(
            max_events=2,
            max_candidates_per_event=4,
            max_expansions_per_candidate=300,
        ),
    )
    return layout, netlist, bus, certificate, allocation, registry, policy


def _two_event_regions(
    *,
    avoid_global_conflict: bool = False,
    via_site_conflict: bool = False,
    pairwise_conflict: bool = False,
    changed_point_transition: bool = False,
    physical_maximum: int = 4,
    combined_maximum: int = 4,
    combined_spread: int = 4,
):
    layout, netlist = _neutral_inputs()
    layout = replace(layout, width_mm=16)
    via_policy = BusViaPolicy(
        mode="independent_bounded",
        maximum_vias_per_member=4,
        maximum_via_count_spread=4,
    )
    base = _bus(via_policy)
    bus = BusGroup(
        bus_id=base.bus_id,
        members=base.members,
        boundaries=(
            _boundary("entry", "portal:entry", ("m0", "m1", "m2")),
            _boundary("middle", "portal:first", ("m1", "m0", "m2")).model_copy(
                update={"boundary_id": "middle:first"}
            ),
            _boundary("middle", "portal:second", ("m1", "m2", "m0")).model_copy(
                update={"boundary_id": "middle:second"}
            ),
            _boundary("middle", "portal:following", ("m1", "m2", "m0")).model_copy(
                update={"boundary_id": "middle:following"}
            ),
            _boundary("exit", "portal:exit", ("m1", "m2", "m0")),
        ),
        permutation_policy=BusPermutationPolicy(
            swap_windows=(
                BusSwapWindow(
                    window_id="swap:first",
                    corridor_region_id="section:first",
                    allowed_adjacent_pairs=(("m0", "m1"),),
                    allowed_layers=("F.Cu",),
                    maximum_swaps=1,
                ),
                BusSwapWindow(
                    window_id="swap:second",
                    corridor_region_id="section:second",
                    allowed_adjacent_pairs=(("m0", "m2"),),
                    allowed_layers=("F.Cu",),
                    maximum_swaps=1,
                ),
            )
        ),
        layer_policy=BusLayerPolicy(
            allowed_layers=("B.Cu", "F.Cu"),
            preferred_layers=("F.Cu",),
            via_policy=via_policy,
        ),
        rule_profile_id=base.rule_profile_id,
    )
    profile = DEFAULT_PCB_RULE_PROFILE
    if pairwise_conflict:
        requirement = OrdinaryClearanceRequirement(
            requirement_id="m1-m2-plan-special",
            nets_a=("/D1",),
            nets_b=("/D2",),
            minimum_clearance_mm=1.4,
        )
        profile = profile.model_copy(
            update={
                "fab_spacing": profile.fab_spacing.model_copy(
                    update={"pairwise_clearances": (requirement,)}
                )
            }
        )
    sections = tuple(
        CertifiedCorridorSection(
            section_id=section_id,
            entry_portal_id=entry_portal_id,
            exit_portal_id=exit_portal_id,
            lane_slots=tuple(
                CertifiedLaneSlot(
                    slot_id=f"slot:{prefix}:{index}",
                    section_id=section_id,
                    layer=("B.Cu" if section_id == "section:tail" and index < 2 else "F.Cu"),
                    order_index=index,
                    centerline_geometry_id=f"geometry:{prefix}:{index}",
                    maximum_track_width_mm=0.3,
                    supported_clearance_domain_ids=("ordinary",),
                )
                for index in range(3)
            ),
            swap_window_ids=swap_window_ids,
            transition_window_ids=("transition:tail",) if section_id == "section:following" else (),
        )
        for section_id, entry_portal_id, exit_portal_id, prefix, swap_window_ids in (
            ("section:first", "portal:entry", "portal:first", "first", ("swap:first",)),
            (
                "section:second",
                "portal:first",
                "portal:second",
                "second",
                ("swap:second",),
            ),
            (
                "section:following",
                "portal:second",
                "portal:following",
                "following",
                (),
            ),
            ("section:tail", "portal:following", "portal:exit", "tail", ()),
        )
    )
    certificate = CorridorCapacityCertificate(
        certificate_id="certificate:successive-swaps",
        board_geometry_fingerprint=bus_physical_swap_board_geometry_fingerprint(layout),
        static_obstacle_fingerprint=bus_physical_swap_static_obstacle_fingerprint(layout, netlist),
        rule_profile_fingerprint=bus_physical_swap_profile_fingerprint(profile),
        demand_fingerprint=bus.semantic_fingerprint(),
        corridor_graph_fingerprint="e" * 64,
        grid_mm=1.0,
        sections=sections,
        exact_capacity_proof_id="exact-successive-swap-capacity-v1",
    )
    allocation = allocate_bus_lanes(bus, certificate, budget=BusAllocationBudget(max_states=100))
    assert allocation.success and len(allocation.swaps) == 2, allocation.failure_reason
    second_exit_x = 8 if pairwise_conflict else 10 if avoid_global_conflict else 4
    following_entry_x = second_exit_x + 2
    following_exit_x = 14 if avoid_global_conflict or pairwise_conflict else 9
    polygon = ((0, 0), (0, 6), (15, 6), (15, 0))
    section_geometry = {
        "section:first": ("first", "portal:entry", "portal:first", 0, 4),
        "section:second": (
            "second",
            "portal:first",
            "portal:second",
            6,
            second_exit_x,
        ),
        "section:following": (
            "following",
            "portal:second",
            "portal:following",
            following_entry_x,
            following_exit_x,
        ),
        "section:tail": (
            "tail",
            "portal:following",
            "portal:exit",
            following_exit_x,
            15,
        ),
    }
    geometries = tuple(
        CertifiedLaneGeometry(
            centerline_geometry_id=f"geometry:{prefix}:{index}",
            certificate_fingerprint=certificate.semantic_fingerprint(),
            section_id=section_id,
            layer=("B.Cu" if section_id == "section:tail" and index < 2 else "F.Cu"),
            track_width_mm=0.2,
            grid_mm=1.0,
            entry_portal_id=entry_portal_id,
            exit_portal_id=exit_portal_id,
            entry_portal_point=(
                4
                if section_id == "section:second" and index == 2 and second_exit_x != 4
                else second_exit_x
                if section_id == "section:following" and index == 0
                else entry_x,
                1
                + 2 * index
                + (
                    1
                    if changed_point_transition and section_id == "section:tail" and index < 2
                    else 0
                ),
            ),
            exit_portal_point=(exit_x, 1 + 2 * index),
            points=(
                (
                    4
                    if section_id == "section:second" and index == 2 and second_exit_x != 4
                    else second_exit_x
                    if section_id == "section:following" and index == 0
                    else entry_x,
                    1
                    + 2 * index
                    + (
                        1
                        if changed_point_transition and section_id == "section:tail" and index < 2
                        else 0
                    ),
                ),
                (exit_x, 1 + 2 * index),
            ),
            keep_in_polygon=polygon,
            keep_in_fingerprint=certified_keep_in_fingerprint(1.0, polygon),
        )
        for section_id, (
            prefix,
            entry_portal_id,
            exit_portal_id,
            entry_x,
            exit_x,
        ) in section_geometry.items()
        for index in range(3)
    )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=geometries,
    )
    policy = BusPhysicalSwapPolicy(
        windows=(
            BusPhysicalSwapWindowPolicy(
                window_id="swap:first",
                bridge_layer="B.Cu",
                via_process_id="through-via:default",
            ),
            BusPhysicalSwapWindowPolicy(
                window_id="swap:second",
                bridge_layer="B.Cu",
                via_process_id="through-via:default",
            ),
        ),
        maximum_physical_vias_per_member=physical_maximum,
        maximum_combined_vias_per_member=combined_maximum,
        maximum_combined_via_count_spread=combined_spread,
        budget=BusPhysicalSwapBudget(
            max_events=2,
            max_candidates_per_event=4,
            max_expansions_per_candidate=300,
        ),
    )
    assignments = {(item.section_id, item.member_id): item for item in allocation.assignments}
    slots = {
        (section.section_id, slot.slot_id): slot
        for section in certificate.sections
        for slot in section.lane_slots
    }
    geometry_by_id = {item.centerline_geometry_id: item for item in geometries}
    regions = []
    for event_index, event in enumerate(allocation.swaps):
        incoming_section_index = next(
            index
            for index, section in enumerate(certificate.sections)
            if section.section_id == event.section_id
        )
        incoming_section = certificate.sections[incoming_section_index]
        outgoing_section = certificate.sections[incoming_section_index + 1]
        gap_start_x = 4 if event_index == 0 else second_exit_x
        gap_end_x = 6 if event_index == 0 else following_entry_x
        cells = tuple((x, y) for x in range(gap_start_x, gap_end_x + 1) for y in range(1, 6))
        nodes = tuple((layer, x, y) for layer in ("F.Cu", "B.Cu") for x, y in cells)
        transitions: list[tuple[tuple[str, int, int], tuple[str, int, int]]] = []
        for layer in ("F.Cu", "B.Cu"):
            for x, y in cells:
                for neighbour in ((x + 1, y), (x, y + 1)):
                    if neighbour in cells:
                        transitions.append(((layer, x, y), (layer, *neighbour)))
        event_members = (event.first_member_id, event.second_member_id)
        portals = []
        for member_id in event_members:
            incoming_assignment = assignments[(incoming_section.section_id, member_id)]
            outgoing_assignment = assignments[(outgoing_section.section_id, member_id)]
            incoming = geometry_by_id[
                slots[
                    (incoming_section.section_id, incoming_assignment.slot_id)
                ].centerline_geometry_id
            ]
            outgoing = geometry_by_id[
                slots[
                    (outgoing_section.section_id, outgoing_assignment.slot_id)
                ].centerline_geometry_id
            ]
            portals.append(
                BusSwapMemberPortalAuthority(
                    member_id=member_id,
                    incoming_section_id=incoming_section.section_id,
                    outgoing_section_id=outgoing_section.section_id,
                    incoming_geometry_id=incoming.centerline_geometry_id,
                    outgoing_geometry_id=outgoing.centerline_geometry_id,
                    incoming_portal_id=incoming.exit_portal_id,
                    outgoing_portal_id=outgoing.entry_portal_id,
                    incoming_portal_point=incoming.exit_portal_point,
                    outgoing_portal_point=outgoing.entry_portal_point,
                )
            )
        center_x = gap_start_x + 1
        via_cells = (
            ((center_x, 5), (center_x, 3))
            if via_site_conflict and event_index == 1
            else ((center_x, 1), (center_x, 3))
            if event_index == 0
            else ((center_x, 3), (center_x, 5))
        )
        event_transitions = (
            *transitions,
            *((("F.Cu", *cell), ("B.Cu", *cell)) for cell in via_cells),
        )
        if via_site_conflict and event_index == 1:
            permitted_stub = tuple(sorted((("F.Cu", center_x, 3), ("F.Cu", gap_end_x, 3))))
            event_transitions = tuple(
                edge
                for edge in event_transitions
                if (
                    edge[0][0] != edge[1][0]
                    or edge[0][0] != "F.Cu"
                    or not ({edge[0][1:], edge[1][1:]} & {(center_x, 3), (gap_end_x, 3)})
                    or tuple(sorted(edge)) == permitted_stub
                )
            )
        layout_json = canonical_board_layout_snapshot_json(layout)
        netlist_json = canonical_board_netlist_snapshot_json(netlist)
        payload = {
            "region_id": f"swap-region:{event_index}",
            "layout_snapshot_json": layout_json,
            "netlist_snapshot_json": netlist_json,
            "layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(layout_json),
            "netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(netlist_json),
            "bus": bus,
            "certificate": certificate,
            "allocation": allocation,
            "lane_geometry_registry": registry,
            "rule_profile": profile,
            "swap_event": event,
            "physical_policy": policy,
            "keep_in_polygon": (
                (gap_start_x - 1, 0),
                (gap_start_x - 1, 6),
                (gap_end_x + 1, 6),
                (gap_end_x + 1, 0),
            ),
            "allowed_nodes": nodes,
            "allowed_transitions": event_transitions,
            "allowed_via_cells": via_cells,
            "member_portals": tuple(portals),
            "bridge_layer": "B.Cu",
        }
        regions.append(_finish(payload))
    return tuple(regions)


def test_zero_event_plan_is_coherent_empty_success() -> None:
    result = _zero_event()

    assert result.outcome.disposition is BusPhysicalSwapPlanDisposition.BUILT
    assert result.outcome.plan is not None
    assert result.outcome.plan.carriers == ()
    assert result.outcome.plan.via_accounting
    assert all(item.physical_via_count == 0 for item in result.outcome.plan.via_accounting)
    assert result.outcome.telemetry.declared_event_count == 0
    assert ReplayBoundBusPhysicalSwapPlan.model_validate_json(result.model_dump_json()) == result


def test_schema_v1_rejects_multiple_physical_events_in_one_section() -> None:
    (
        layout,
        netlist,
        bus,
        certificate,
        allocation,
        registry,
        policy,
    ) = _same_section_two_event_authority()
    payload = _region_payload()
    payload.update(
        {
            "bus": bus,
            "certificate": certificate,
            "allocation": allocation,
            "lane_geometry_registry": registry,
            "swap_event": allocation.swaps[0],
            "physical_policy": policy,
        }
    )

    with pytest.raises(ValidationError, match="at most one event per corridor section"):
        _finish(payload)
    with pytest.raises(ValidationError, match="at most one event per corridor section"):
        build_replay_bound_bus_physical_swap_plan(
            layout=layout,
            netlist=netlist,
            bus=bus,
            certificate=certificate,
            allocation=allocation,
            lane_geometry_registry=registry,
            rule_profile=DEFAULT_PCB_RULE_PROFILE,
            physical_policy=policy,
            initial_occupancy=OccupancyLedger(),
            regions=(),
        )


def test_one_event_success_has_exact_counts_claims_and_telemetry() -> None:
    result = _one_event()

    assert result.outcome.plan is not None
    plan = result.outcome.plan
    assert len(plan.carriers) == 1
    by_member = {item.member_id: item for item in plan.via_accounting}
    assert by_member[plan.carriers[0].bridge_member_id].physical_via_count == 2
    assert sum(item.physical_via_count for item in plan.via_accounting) == 2
    assert all(
        item.combined_via_count == item.semantic_via_count + item.physical_via_count
        for item in plan.via_accounting
    )
    assert plan.combined_claims == result.outcome.combined_claims
    assert plan.telemetry.carrier_attempt_count == 1
    assert plan.telemetry.candidate_attempt_count == 4
    assert plan.telemetry.expansion_count > 0


@pytest.mark.parametrize("regions_kind", ["missing", "extra", "duplicate"])
def test_missing_extra_and_duplicate_region_coverage_fail_typed(
    regions_kind: str,
) -> None:
    region = _finish(
        _region_payload(
            policy_updates={
                "budget": BusPhysicalSwapBudget(
                    max_events=1,
                    max_candidates_per_event=4,
                    max_expansions_per_candidate=100,
                )
            }
        )
    )
    regions = () if regions_kind == "missing" else (region, region)
    result = _build(region=region, regions=regions)

    assert result.outcome.plan is None
    assert result.outcome.failure_reason is BusPhysicalSwapPlanFailureReason.INVALID_EVENT_COVERAGE
    assert result.outcome.carrier_results == ()


def test_failed_carrier_fails_whole_plan_without_partial_success() -> None:
    result = _one_event(carrier_candidates=2)

    assert result.outcome.plan is None
    assert (
        result.outcome.failure_reason is BusPhysicalSwapPlanFailureReason.CARRIER_GENERATION_FAILED
    )
    assert len(result.outcome.carrier_results) == 1
    assert result.outcome.telemetry.failed_carrier_count == 1


def test_two_ordered_events_have_exact_coverage_and_cannot_commute() -> None:
    regions = _two_event_regions(avoid_global_conflict=True)
    result = _build(region=regions[0], regions=regions)

    assert result.outcome.plan is not None
    plan = result.outcome.plan
    assert result.outcome.telemetry.declared_event_count == 2
    assert tuple(item.section_id for item in plan.replay_input.allocation.swaps) == (
        "section:first",
        "section:second",
    )
    assert tuple(item.region.swap_event for item in plan.carriers) == (
        plan.replay_input.allocation.swaps
    )
    assert tuple(item.region for item in plan.carriers) == regions
    assert {item.outgoing_section_id for item in regions[0].member_portals} == {"section:second"}
    assert {item.incoming_section_id for item in regions[1].member_portals} == {"section:second"}
    assert ReplayBoundBusPhysicalSwapPlan.model_validate_json(result.model_dump_json()) == result

    reversed_result = _build(region=regions[0], regions=tuple(reversed(regions)))
    assert reversed_result.outcome.plan is None
    assert (
        reversed_result.outcome.failure_reason
        is BusPhysicalSwapPlanFailureReason.INVALID_EVENT_COVERAGE
    )
    assert reversed_result.outcome.carrier_results == ()


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "reordered"])
def test_retained_carrier_coverage_mutations_fail_plan_validation(mutation: str) -> None:
    regions = _two_event_regions(avoid_global_conflict=True)
    result = _build(region=regions[0], regions=regions)
    assert result.outcome.plan is not None
    plan = result.outcome.plan
    results = plan.carrier_results
    changed = {
        "missing": results[:-1],
        "extra": (*results, results[0]),
        "duplicate": (results[0], results[0]),
        "reordered": tuple(reversed(results)),
    }[mutation]

    with pytest.raises(ValidationError):
        BusPhysicalSwapPlan.model_validate_json(
            plan.model_copy(update={"carrier_results": changed}).model_dump_json()
        )


def test_locally_feasible_carriers_can_fail_global_ordinary_conflict() -> None:
    regions = _two_event_regions()
    result = _build(region=regions[0], regions=regions)

    assert all(item.outcome.carrier is not None for item in result.outcome.carrier_results)
    assert result.outcome.plan is None
    assert result.outcome.failure_reason is BusPhysicalSwapPlanFailureReason.CROSS_CARRIER_CONFLICT
    assert result.outcome.combined_resource_overuse
    assert any(
        '"ordinary"' in item.resource_id for item in result.outcome.combined_resource_overuse
    )


def test_cross_carrier_pairwise_conflict_fires_in_its_exact_domain() -> None:
    regions = _two_event_regions(avoid_global_conflict=True, pairwise_conflict=True)
    result = _build(region=regions[0], regions=regions)

    assert result.outcome.failure_reason is BusPhysicalSwapPlanFailureReason.CROSS_CARRIER_CONFLICT
    assert result.outcome.combined_resource_overuse
    assert all(
        "pairwise-clearance-v1:" in item.resource_id
        for item in result.outcome.combined_resource_overuse
    )


def test_cross_carrier_via_site_conflict_fires_between_distinct_bridge_nets() -> None:
    regions = _two_event_regions(via_site_conflict=True)
    result = _build(region=regions[0], regions=regions)

    assert result.outcome.failure_reason is BusPhysicalSwapPlanFailureReason.CROSS_CARRIER_CONFLICT
    via_conflicts = [
        item
        for item in result.outcome.combined_resource_overuse
        if '"via_site"' in item.resource_id
    ]
    assert via_conflicts
    assert via_conflicts[0].net_names == ("/D0", "/D2")


@pytest.mark.parametrize(
    "limits",
    [
        {"physical_maximum": 3},
        {"physical_maximum": 3, "combined_maximum": 3},
        {"combined_spread": 2},
    ],
)
def test_whole_plan_via_maximum_and_spread_one_less_fail(
    limits: dict[str, int],
) -> None:
    regions = _two_event_regions(avoid_global_conflict=True, **limits)
    result = _build(region=regions[0], regions=regions)

    assert result.outcome.plan is None
    assert result.outcome.failure_reason is BusPhysicalSwapPlanFailureReason.CUMULATIVE_VIA_POLICY
    by_member = {item.member_id: item for item in result.outcome.via_accounting}
    assert by_member["m0"].physical_via_count == 4
    assert by_member["m0"].combined_via_count == 4


def test_semantic_counts_are_unchanged_and_exact_totals_are_retained() -> None:
    regions = _two_event_regions(avoid_global_conflict=True)
    result = _build(region=regions[0], regions=regions)
    assert result.outcome.plan is not None
    plan = result.outcome.plan
    semantic = {item.member_id: item.via_count for item in plan.replay_input.allocation.via_counts}

    assert {item.member_id: item.semantic_via_count for item in plan.via_accounting} == semantic
    assert sum(item.physical_via_count for item in plan.via_accounting) == 4
    assert (
        sum(item.combined_via_count for item in plan.via_accounting) == sum(semantic.values()) + 4
    )


def test_repeated_and_reversed_set_like_initial_claims_are_deterministic() -> None:
    region = _finish(
        _region_payload(
            policy_updates={
                "budget": BusPhysicalSwapBudget(
                    max_events=1,
                    max_candidates_per_event=4,
                    max_expansions_per_candidate=100,
                )
            }
        )
    )
    claims = (
        NetResourceClaims("/Z", frozenset()),
        NetResourceClaims("/A", frozenset()),
    )
    first = _build(region=region, regions=(region,), ledger=OccupancyLedger(claims))
    reversed_input = _build(
        region=region,
        regions=(region,),
        ledger=OccupancyLedger(reversed(claims)),
    )

    assert first == reversed_input
    assert first.semantic_fingerprint() == reversed_input.semantic_fingerprint()


def test_extra_policy_window_is_rejected_for_empty_and_nonempty_allocations() -> None:
    empty = _zero_event()
    nonempty = _one_event()
    extra = BusPhysicalSwapWindowPolicy(
        window_id="extra:unmapped",
        bridge_layer="B.Cu",
        via_process_id="through-via:default",
    )
    for result in (empty, nonempty):
        source = result.replay_input
        changed_policy = source.physical_policy.model_copy(
            update={"windows": (*source.physical_policy.windows, extra)}
        )
        with pytest.raises(ValidationError, match="does not map exact swap windows"):
            BusPhysicalSwapPlanInput.model_validate_json(
                source.model_copy(update={"physical_policy": changed_policy}).model_dump_json()
            )


def test_nonempty_region_still_rejects_an_empty_policy_mapping() -> None:
    payload = _region_payload()
    payload["physical_policy"] = payload["physical_policy"].model_copy(update={"windows": ()})

    with pytest.raises(ValidationError, match="map exactly every semantic swap window"):
        _finish(payload)


def test_failed_semantic_allocation_cannot_become_empty_physical_success() -> None:
    layout, netlist = _neutral_inputs()
    base = _bus()
    bus = base.model_copy(
        update={
            "boundaries": (
                _boundary("entry", "portal:entry", ("m0", "m1", "m2")),
                _boundary("middle", "portal:middle", ("m2", "m1", "m0")),
                _boundary("exit", "portal:exit", ("m2", "m1", "m0")),
            )
        }
    )
    certificate = _certificate(bus, layout, netlist)
    allocation = allocate_bus_lanes(bus, certificate, budget=BusAllocationBudget(max_states=20))
    assert not allocation.success
    geometries = tuple(
        _geometry(certificate, section_id, index)
        for section_id in ("section:incoming", "section:outgoing")
        for index in range(3)
    )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=geometries,
    )
    policy = BusPhysicalSwapPolicy(
        windows=(),
        maximum_physical_vias_per_member=2,
        maximum_combined_vias_per_member=2,
        maximum_combined_via_count_spread=2,
        budget=BusPhysicalSwapBudget(
            max_events=0,
            max_candidates_per_event=2,
            max_expansions_per_candidate=1,
        ),
    )

    with pytest.raises(ValidationError, match="successful semantic allocation"):
        build_replay_bound_bus_physical_swap_plan(
            layout=layout,
            netlist=netlist,
            bus=bus,
            certificate=certificate,
            allocation=allocation,
            lane_geometry_registry=registry,
            rule_profile=DEFAULT_PCB_RULE_PROFILE,
            physical_policy=policy,
            initial_occupancy=OccupancyLedger(),
            regions=(),
        )


def test_stale_registry_grid_and_final_fingerprints_fail_replay() -> None:
    result = _one_event()
    source = result.replay_input
    stale_geometries = tuple(
        item.model_copy(
            update={
                "grid_mm": 0.5,
                "keep_in_fingerprint": certified_keep_in_fingerprint(0.5, item.keep_in_polygon),
            }
        )
        for item in source.lane_geometry_registry.geometries
    )
    stale_registry = source.lane_geometry_registry.model_copy(
        update={"grid_mm": 0.5, "geometries": stale_geometries}
    )
    with pytest.raises(ValidationError, match="registry grid"):
        BusPhysicalSwapPlanInput.model_validate_json(
            source.model_copy(update={"lane_geometry_registry": stale_registry}).model_dump_json()
        )

    assert result.outcome.plan is not None
    bad_plan = result.outcome.plan.model_copy(update={"plan_fingerprint": "0" * 64})
    bad_outcome = result.outcome.model_copy(update={"plan": bad_plan})
    with pytest.raises(ValidationError, match="plan fingerprint"):
        ReplayBoundBusPhysicalSwapPlan.model_validate_json(
            result.model_copy(update={"outcome": bad_outcome}).model_dump_json()
        )


@pytest.mark.parametrize(
    "field",
    [
        "carriers",
        "combined_claims",
        "combined_occupancy_fingerprint",
        "via_accounting",
        "telemetry",
    ],
)
def test_each_redundant_successful_plan_field_rederives_independently(
    field: str,
) -> None:
    result = _one_event()
    assert result.outcome.plan is not None
    plan = result.outcome.plan
    if field == "carriers":
        changed: Any = plan.carriers[:-1]
    elif field == "combined_claims":
        claims = list(plan.combined_claims)
        first = claims[0]
        injected = RoutingResourceKey("ordinary", "F.Cu", "cell", 99, 99)
        claims[0] = NetResourceClaims(first.net_name, frozenset((*first.resources, injected)))
        changed = tuple(claims)
    elif field == "combined_occupancy_fingerprint":
        changed = "0" * 64
    elif field == "via_accounting":
        accounting = list(plan.via_accounting)
        first = accounting[0]
        accounting[0] = first.model_copy(
            update={
                "physical_via_count": first.physical_via_count + 1,
                "combined_via_count": first.combined_via_count + 1,
            }
        )
        changed = tuple(accounting)
    else:
        changed = plan.telemetry.model_copy(
            update={"expansion_count": plan.telemetry.expansion_count + 1}
        )

    with pytest.raises(ValidationError):
        BusPhysicalSwapPlan.model_validate_json(
            plan.model_copy(update={field: changed}).model_dump_json()
        )


@pytest.mark.parametrize("tamper", ["failure_reason", "overuse"])
def test_failed_outcome_overuse_and_reason_coherence_rejects_tamper(
    tamper: str,
) -> None:
    regions = _two_event_regions()
    result = _build(region=regions[0], regions=regions)
    assert result.outcome.combined_resource_overuse
    update: dict[str, Any]
    if tamper == "failure_reason":
        update = {"failure_reason": BusPhysicalSwapPlanFailureReason.CARRIER_GENERATION_FAILED}
    else:
        update = {"combined_resource_overuse": ()}

    with pytest.raises(ValidationError, match="cross-carrier failure"):
        BusPhysicalSwapPlanBuildOutcome.model_validate_json(
            result.outcome.model_copy(update=update).model_dump_json()
        )

    bad_outcome = result.outcome.model_copy(update={"outcome_fingerprint": "0" * 64})
    with pytest.raises(ValidationError, match="outcome fingerprint"):
        ReplayBoundBusPhysicalSwapPlan.model_validate_json(
            result.model_copy(update={"outcome": bad_outcome}).model_dump_json()
        )


@pytest.mark.parametrize(
    "authority",
    [
        "bus",
        "certificate",
        "allocation",
        "registry",
        "profile",
        "board",
        "netlist",
        "policy",
        "occupancy",
    ],
)
def test_each_top_level_authority_mutation_fails(authority: str) -> None:
    result = _one_event()
    source = result.replay_input
    changes: dict[str, Any]
    if authority == "bus":
        changes = {"bus": source.bus.model_copy(update={"bus_id": "stale"})}
    elif authority == "certificate":
        changes = {
            "certificate": source.certificate.model_copy(
                update={"corridor_graph_fingerprint": "f" * 64}
            )
        }
    elif authority == "allocation":
        changes = {"allocation": source.allocation.model_copy(update={"bus_fingerprint": "0" * 64})}
    elif authority == "registry":
        changes = {
            "lane_geometry_registry": source.lane_geometry_registry.model_copy(
                update={"allocation_fingerprint": "0" * 64}
            )
        }
    elif authority == "profile":
        changes = {"rule_profile": source.rule_profile.model_copy(update={"profile_id": "stale"})}
    elif authority == "board":
        changed = replace(source.layout, width_mm=11)
        changed_json = canonical_board_layout_snapshot_json(changed)
        changes = {
            "layout_snapshot_json": changed_json,
            "layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(changed_json),
        }
    elif authority == "netlist":
        changed = replace(source.netlist, nets=source.netlist.nets[:-1])
        changed_json = canonical_board_netlist_snapshot_json(changed)
        changes = {
            "netlist_snapshot_json": changed_json,
            "netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(changed_json),
        }
    elif authority == "policy":
        changes = {
            "physical_policy": source.physical_policy.model_copy(
                update={
                    "maximum_combined_via_count_spread": (
                        source.physical_policy.maximum_combined_via_count_spread + 1
                    )
                }
            )
        }
    else:
        changes = {"initial_occupancy_fingerprint": "0" * 64}

    with pytest.raises(ValidationError):
        BusPhysicalSwapPlanInput.model_validate_json(
            source.model_copy(update=changes).model_dump_json()
        )
