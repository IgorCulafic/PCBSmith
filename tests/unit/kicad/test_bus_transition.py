"""Firing tests for generated certified bus transition carriers."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_candidate as c2
from tests.unit.kicad import test_bus_integration as c1

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    BusLayerTransitionEvent,
    BusMemberViaCount,
    BusSwapEvent,
    allocate_bus_lanes,
    bus_lane_allocation_fingerprint,
)
from pcbsmith.bus_geometry import (
    CertifiedBusEscapeGraphRegistry,
    CertifiedBusEscapeRegion,
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
    certified_keep_in_fingerprint,
    realize_certified_trunk_subset,
)
from pcbsmith.bus_ir import (
    BoundaryMemberRef,
    BusBoundary,
    BusGroup,
    BusLayerPolicy,
    BusMember,
    BusPermutationPolicy,
    BusTerminalRef,
    BusViaPolicy,
    CertifiedCorridorSection,
    CertifiedLaneSlot,
    CorridorCapacityCertificate,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.bus_escape import (
    BusEscapeBudget,
    BusEscapeFailureReason,
    generate_certified_bus_escape_candidate,
)
from pcbsmith.kicad.bus_transition import (
    BusTransitionBudget,
    BusTransitionFailureReason,
    BusTransitionGenerationResult,
    generate_certified_bus_transition_vias,
)
from pcbsmith.kicad.negotiated_grid import CertifiedEndpointTerminalSource
from pcbsmith.kicad.negotiated_resources import OccupancyLedger, RoutingResourceKey
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

TRACK_WIDTH_MM = 0.4
GRID_MM = 1.0
KEEP_IN = ((0, 0), (30, 0), (30, 17), (0, 17))
TRANSITION_BUDGET = BusTransitionBudget(max_members=2, max_events=2)
ESCAPE_BUDGET = BusEscapeBudget(
    max_members=2,
    max_terminals=4,
    max_expansions_per_terminal=2,
    max_expansions_per_member=4,
    max_total_expansions=8,
)


@dataclass(frozen=True)
class TransitionEscapeFixture:
    layout: BoardLayout
    netlist: BoardNetlist
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    lanes: CertifiedLaneGeometryRegistry
    escapes: CertifiedBusEscapeGraphRegistry
    sources: dict[str, CertifiedEndpointTerminalSource]


def _member(
    member_id: str,
    net_name: str,
    source_ref: str,
    sink_ref: str,
    sink_pad_number: str = "2",
) -> BusMember:
    return BusMember(
        member_id=member_id,
        net_name=net_name,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net_name,
                component_ref=source_ref,
                pad_number="2",
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net_name,
                component_ref=sink_ref,
                pad_number=sink_pad_number,
                role="sink",
            ),
        ),
        width_mm=TRACK_WIDTH_MM,
    )


def _boundary(
    boundary_id: str,
    portal_id: str,
    members: tuple[BusMember, ...],
    role: str | None,
) -> BusBoundary:
    return BusBoundary(
        boundary_id=boundary_id,
        corridor_portal_id=portal_id,
        orientation="forward",
        ordered_members=tuple(
            BoundaryMemberRef(
                member_id=member.member_id,
                terminal_ids=(() if role is None else (f"{member.member_id}:{role}",)),
            )
            for member in members
        ),
    )


def _slot(
    section_id: str,
    index: int,
    layer: str,
) -> CertifiedLaneSlot:
    return CertifiedLaneSlot(
        slot_id=f"slot:{section_id}:{index}",
        section_id=section_id,
        layer=layer,
        order_index=index,
        centerline_geometry_id=f"centerline:{section_id}:{index}",
        maximum_track_width_mm=TRACK_WIDTH_MM,
        supported_clearance_domain_ids=("ordinary",),
    )


def _two_member_fixture(
    *,
    shared_transition_site: bool = False,
    mixed_transition: bool = False,
) -> TransitionEscapeFixture:
    members = (
        _member("data0", "/A", "R1", "R2"),
        _member("data1", "/B", "R3", "R4", "1" if mixed_transition else "2"),
    )
    via_policy = (
        BusViaPolicy(
            mode="independent_bounded",
            maximum_vias_per_member=1,
            maximum_via_count_spread=1,
        )
        if mixed_transition
        else BusViaPolicy(
            mode="synchronous",
            transition_window_ids=("transition:main",),
            maximum_vias_per_member=1,
            maximum_via_count_spread=0,
        )
    )
    bus = BusGroup(
        bus_id="two-member-transition",
        members=tuple(reversed(members)),
        boundaries=(
            _boundary("entry", "portal:entry", members, "source"),
            _boundary("middle", "portal:middle", members, None),
            _boundary("exit", "portal:exit", members, "sink"),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu", "B.Cu"),
            via_policy=via_policy,
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )
    certificate = CorridorCapacityCertificate(
        certificate_id="certificate:two-member-transition",
        board_geometry_fingerprint="1" * 64,
        static_obstacle_fingerprint="2" * 64,
        rule_profile_fingerprint="3" * 64,
        demand_fingerprint="4" * 64,
        corridor_graph_fingerprint="5" * 64,
        grid_mm=GRID_MM,
        sections=(
            CertifiedCorridorSection(
                section_id="front",
                entry_portal_id="portal:entry",
                exit_portal_id="portal:middle",
                lane_slots=(_slot("front", 0, "F.Cu"), _slot("front", 1, "F.Cu")),
                transition_window_ids=("transition:main",),
            ),
            CertifiedCorridorSection(
                section_id="back",
                entry_portal_id="portal:middle",
                exit_portal_id="portal:exit",
                lane_slots=(
                    _slot("back", 0, "B.Cu"),
                    _slot("back", 1, "F.Cu" if mixed_transition else "B.Cu"),
                ),
            ),
        ),
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    assert allocation.layer_transition_count == (1 if mixed_transition else 2)
    keep_in_fingerprint = certified_keep_in_fingerprint(GRID_MM, KEEP_IN)
    geometries = []
    for index, y in enumerate((4, 13)):
        middle = (15, 4) if shared_transition_site else (15, y)
        back_layer = "F.Cu" if mixed_transition and index == 1 else "B.Cu"
        exit_x = 22
        front_points = ((8, y), middle) if middle[1] == y else ((8, y), (8, middle[1]), middle)
        back_points = (
            (middle, (exit_x, y)) if middle[1] == y else (middle, (exit_x, middle[1]), (exit_x, y))
        )
        geometries.extend(
            (
                CertifiedLaneGeometry(
                    centerline_geometry_id=f"centerline:front:{index}",
                    certificate_fingerprint=certificate.semantic_fingerprint(),
                    section_id="front",
                    layer="F.Cu",
                    track_width_mm=TRACK_WIDTH_MM,
                    grid_mm=GRID_MM,
                    entry_portal_id="portal:entry",
                    exit_portal_id="portal:middle",
                    entry_portal_point=(8, y),
                    exit_portal_point=middle,
                    points=front_points,
                    keep_in_polygon=KEEP_IN,
                    keep_in_fingerprint=keep_in_fingerprint,
                ),
                CertifiedLaneGeometry(
                    centerline_geometry_id=f"centerline:back:{index}",
                    certificate_fingerprint=certificate.semantic_fingerprint(),
                    section_id="back",
                    layer=back_layer,
                    track_width_mm=TRACK_WIDTH_MM,
                    grid_mm=GRID_MM,
                    entry_portal_id="portal:middle",
                    exit_portal_id="portal:exit",
                    entry_portal_point=middle,
                    exit_portal_point=(exit_x, y),
                    points=back_points,
                    keep_in_polygon=KEEP_IN,
                    keep_in_fingerprint=keep_in_fingerprint,
                ),
            )
        )
    lanes = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=GRID_MM,
        geometries=tuple(reversed(geometries)),
    )
    sink_anchors = {"data0": 24, "data1": 24}
    escapes = _escape_registry(bus, certificate, allocation, lanes, sink_anchors)
    layout, netlist = c2._layout_and_netlist()
    layout = replace(
        layout,
        part_flip=(("R2",) if mixed_transition else ("R2", "R4")),
    )
    netlist = replace(
        netlist,
        nets=tuple(
            replace(
                net,
                nodes=tuple(
                    (
                        (
                            reference,
                            "1" if mixed_transition and reference == "R4" else "2",
                        )
                        if reference in {"R2", "R4"}
                        else (reference, pad_number)
                    )
                    for reference, pad_number in net.nodes
                ),
            )
            for net in netlist.nets
        ),
    )
    sources = {
        "data0:source": CertifiedEndpointTerminalSource(
            component_ref="R1",
            pad_number="2",
            net_name="/A",
            physical_pad_source_id="pad:R1:1",
            source_node=("F.Cu", 6, 4),
        ),
        "data0:sink": CertifiedEndpointTerminalSource(
            component_ref="R2",
            pad_number="2",
            net_name="/A",
            physical_pad_source_id="pad:R2:1",
            source_node=("B.Cu", 24, 4),
        ),
        "data1:source": CertifiedEndpointTerminalSource(
            component_ref="R3",
            pad_number="2",
            net_name="/B",
            physical_pad_source_id="pad:R3:1",
            source_node=("F.Cu", 6, 13),
        ),
        "data1:sink": CertifiedEndpointTerminalSource(
            component_ref="R4",
            pad_number="1" if mixed_transition else "2",
            net_name="/B",
            physical_pad_source_id=("pad:R4:0" if mixed_transition else "pad:R4:1"),
            source_node=(("F.Cu", 24, 13) if mixed_transition else ("B.Cu", 24, 13)),
        ),
    }
    return TransitionEscapeFixture(
        layout,
        netlist,
        bus,
        certificate,
        allocation,
        lanes,
        escapes,
        sources,
    )


def _escape_registry(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    lanes: CertifiedLaneGeometryRegistry,
    sink_anchor_by_member: dict[str, int],
) -> CertifiedBusEscapeGraphRegistry:
    geometry_by_id = {geometry.centerline_geometry_id: geometry for geometry in lanes.geometries}
    assigned_geometry = {
        (assignment.member_id, assignment.section_id): next(
            slot.centerline_geometry_id
            for section in certificate.sections
            if section.section_id == assignment.section_id
            for slot in section.lane_slots
            if slot.slot_id == assignment.slot_id
        )
        for assignment in allocation.assignments
    }
    root = {
        "bus_fingerprint": bus.semantic_fingerprint(),
        "certificate_fingerprint": certificate.semantic_fingerprint(),
        "allocation_fingerprint": allocation.allocation_fingerprint,
        "lane_geometry_registry_fingerprint": lanes.semantic_fingerprint(),
        "grid_mm": certificate.grid_mm,
    }
    regions = []
    for member in bus.members:
        for role, section_id, boundary_id, portal_kind in (
            ("source", "front", "entry", "entry"),
            ("sink", "back", "exit", "exit"),
        ):
            anchor_x = 6 if role == "source" else sink_anchor_by_member[member.member_id]
            terminal_id = f"{member.member_id}:{role}"
            geometry_id = assigned_geometry[(member.member_id, section_id)]
            geometry = geometry_by_id[geometry_id]
            portal = (
                geometry.entry_portal_point
                if portal_kind == "entry"
                else geometry.exit_portal_point
            )
            y = portal[1]
            xs = (
                tuple(range(anchor_x, portal[0] + 1))
                if anchor_x < portal[0]
                else tuple(range(portal[0], anchor_x + 1))
            )
            points = tuple((x, y) for x in xs)
            regions.append(
                CertifiedBusEscapeRegion(
                    **root,
                    region_id=f"escape:{terminal_id}",
                    member_id=member.member_id,
                    net_name=member.net_name,
                    terminal_id=terminal_id,
                    boundary_id=boundary_id,
                    assigned_geometry_id=geometry_id,
                    portal_kind=portal_kind,
                    portal_id=(
                        geometry.entry_portal_id
                        if portal_kind == "entry"
                        else geometry.exit_portal_id
                    ),
                    portal_point=portal,
                    layer=geometry.layer,
                    allowed_track_nodes=points,
                    allowed_track_transitions=tuple(zip(points, points[1:], strict=False)),
                )
            )
    return CertifiedBusEscapeGraphRegistry(**root, regions=tuple(regions))


def _rebind_registry(
    registry: CertifiedLaneGeometryRegistry,
    allocation: BusLaneAllocationResult,
    *,
    geometries: tuple[CertifiedLaneGeometry, ...] | None = None,
) -> CertifiedLaneGeometryRegistry:
    return CertifiedLaneGeometryRegistry(
        certificate_fingerprint=registry.certificate_fingerprint,
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=registry.grid_mm,
        geometries=registry.geometries if geometries is None else geometries,
    )


def _allocation_with_event(
    allocation: BusLaneAllocationResult,
    event: BusLayerTransitionEvent,
) -> BusLaneAllocationResult:
    member_ids = {item.member_id for item in allocation.via_counts}
    via_counts = tuple(
        BusMemberViaCount(
            member_id=member_id,
            via_count=1 if member_id == event.member_id else 0,
        )
        for member_id in sorted(member_ids | {event.member_id})
    )
    fingerprint = bus_lane_allocation_fingerprint(
        bus_fingerprint=allocation.bus_fingerprint,
        certificate_fingerprint=allocation.certificate_fingerprint,
        normalized_boundary_orders=allocation.normalized_boundary_orders,
        assignments=allocation.assignments,
        activations=allocation.activations,
        swaps=allocation.swaps,
        layer_transitions=(event,),
        via_counts=via_counts,
        permutation_boundary_ids=allocation.permutation_boundary_ids,
    )
    payload = allocation.model_dump()
    payload.update(
        {
            "layer_transition_count": 1,
            "layer_transitions": (event,),
            "via_counts": via_counts,
            "allocation_fingerprint": fingerprint,
        }
    )
    return BusLaneAllocationResult.model_validate(payload)


def test_single_transition_literal_and_pins_are_profile_free_and_pure() -> None:
    fixture, _manual = c1._transition_fixture()
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    result = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        ledger,
        BusTransitionBudget(max_members=1, max_events=1),
    )

    assert result.success
    assert result.event_work_count == 1
    assert len(result.carriers) == 1
    carrier = result.carriers[0]
    assert (
        carrier.member_id,
        carrier.net_name,
        carrier.section_id,
        carrier.boundary_id,
        carrier.window_id,
        carrier.from_layer,
        carrier.to_layer,
        carrier.before_geometry_id,
        carrier.after_geometry_id,
        carrier.point,
    ) == (
        "data0",
        "/D0",
        "front",
        "middle",
        "transition:a",
        "F.Cu",
        "B.Cu",
        "centerline:front",
        "centerline:back",
        (5, 2),
    )
    assert not hasattr(carrier, "size_mm")
    assert not hasattr(carrier, "drill_mm")
    assert ledger.semantic_fingerprint() == before
    assert carrier.semantic_fingerprint() == (
        "ba5820fe3f26fc2f9eb59a749308e535b51bb5baa9fdfa31a65c29223309b777"
    )
    assert result.semantic_fingerprint() == (
        "2850477e7a8efecf0987fd783e68f91fac6db170822ec7bb35a403076210f231"
    )
    assert result.input_fingerprint == (
        "767cb86ff10f5bdb6b3db59aa3a7c23565b9430c7d04414c634455917d0e338d"
    )


def test_synchronous_members_use_distinct_sites_and_reversed_registry_is_stable() -> None:
    fixture = _two_member_fixture()
    baseline = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        OccupancyLedger(),
        TRANSITION_BUDGET,
    )
    reversed_lanes = _rebind_registry(
        fixture.lanes,
        fixture.allocation,
        geometries=tuple(reversed(fixture.lanes.geometries)),
    )
    reverse = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        reversed_lanes,
        OccupancyLedger(),
        TRANSITION_BUDGET,
    )

    assert baseline.success and reverse.success
    assert baseline.semantic_fingerprint() == (
        "0d1a1dc9d92560039464ac9f1a7d6659b3847b99327684b6cae9d130ffaf39d2"
    )
    assert baseline.input_fingerprint == (
        "259cf89c094960fbc54f655163bdaca8fcf0a2d207bacebce8a82ecf6bf7b30c"
    )
    assert tuple(item.semantic_fingerprint() for item in baseline.carriers) == (
        "05611e50f8138fc4999ddecb7ed2ce551b6911ed2370c5aa1c357deaf7b4a1d9",
        "d2b56c4a668664d9a4c2455d1b1c91a1fe461a62cc0ad17710bfb135b4c1a44e",
    )
    assert {(item.member_id, item.point) for item in baseline.carriers} == {
        ("data0", (15, 4)),
        ("data1", (15, 13)),
    }
    assert baseline.semantic_json() == reverse.semantic_json()
    assert baseline.semantic_fingerprint() == reverse.semantic_fingerprint()


def test_no_events_is_a_bounded_empty_success() -> None:
    fixture = c1._straight_fixture()
    result = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        OccupancyLedger(),
        BusTransitionBudget(max_members=0, max_events=0),
    )

    assert result.success
    assert result.event_order == ()
    assert result.telemetry == ()
    assert result.event_work_count == 0
    assert result.carriers == ()


@pytest.mark.parametrize(
    ("budget", "reason"),
    (
        (
            BusTransitionBudget(max_members=0, max_events=1),
            BusTransitionFailureReason.MEMBER_BUDGET,
        ),
        (
            BusTransitionBudget(max_members=1, max_events=0),
            BusTransitionFailureReason.EVENT_BUDGET,
        ),
    ),
)
def test_zero_and_one_less_preflight_budgets_do_no_event_work(
    budget: BusTransitionBudget,
    reason: BusTransitionFailureReason,
) -> None:
    fixture, _manual = c1._transition_fixture()
    result = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        OccupancyLedger(),
        budget,
    )

    assert not result.success
    assert result.failure_reason is reason
    assert result.event_work_count == 0
    assert result.telemetry == ()
    assert result.carriers == ()


def test_swap_events_are_typed_unsupported_without_invented_geometry() -> None:
    fixture, _manual = c1._transition_fixture()
    swap = BusSwapEvent(
        section_id="front",
        exit_boundary_id="middle",
        window_id="swap:undeclared",
        sequence_index=0,
        order_index=0,
        first_member_id="data0",
        second_member_id="foreign",
        layer="F.Cu",
    )
    fingerprint = bus_lane_allocation_fingerprint(
        bus_fingerprint=fixture.allocation.bus_fingerprint,
        certificate_fingerprint=fixture.allocation.certificate_fingerprint,
        normalized_boundary_orders=fixture.allocation.normalized_boundary_orders,
        assignments=fixture.allocation.assignments,
        activations=fixture.allocation.activations,
        swaps=(swap,),
        layer_transitions=fixture.allocation.layer_transitions,
        via_counts=fixture.allocation.via_counts,
        permutation_boundary_ids=fixture.allocation.permutation_boundary_ids,
    )
    payload = fixture.allocation.model_dump()
    payload.update(
        {
            "swap_count": 1,
            "swaps": (swap,),
            "allocation_fingerprint": fingerprint,
        }
    )
    allocation = BusLaneAllocationResult.model_validate(payload)
    registry = _rebind_registry(fixture.registry, allocation)

    result = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        allocation,
        registry,
        OccupancyLedger(),
        BusTransitionBudget(max_members=1, max_events=1),
    )

    assert not result.success
    assert result.failure_reason is BusTransitionFailureReason.SWAP_GEOMETRY_UNSUPPORTED
    assert result.event_work_count == 0
    assert result.telemetry == ()
    assert result.carriers == ()


def test_stale_missing_and_foreign_geometry_are_typed() -> None:
    fixture, _manual = c1._transition_fixture()
    stale = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=fixture.registry.certificate_fingerprint,
        allocation_fingerprint="0" * 64,
        grid_mm=fixture.registry.grid_mm,
        geometries=fixture.registry.geometries,
    )
    missing = _rebind_registry(
        fixture.registry,
        fixture.allocation,
        geometries=(fixture.registry.geometries[0],),
    )
    foreign_payload = fixture.registry.geometries[0].model_dump()
    foreign_payload["centerline_geometry_id"] = "centerline:foreign"
    foreign = CertifiedLaneGeometry.model_validate(foreign_payload)
    extra = _rebind_registry(
        fixture.registry,
        fixture.allocation,
        geometries=(*fixture.registry.geometries, foreign),
    )

    for registry, reason in (
        (stale, BusTransitionFailureReason.INVALID_AUTHORITY),
        (missing, BusTransitionFailureReason.GEOMETRY_BINDING),
        (extra, BusTransitionFailureReason.GEOMETRY_BINDING),
    ):
        result = generate_certified_bus_transition_vias(
            fixture.bus,
            fixture.certificate,
            fixture.allocation,
            registry,
            OccupancyLedger(),
            BusTransitionBudget(max_members=1, max_events=1),
        )
        assert not result.success
        assert result.failure_reason is reason
        assert result.event_work_count == 0


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"member_id": "foreign"}, BusTransitionFailureReason.EVENT_MEMBER_BINDING),
        ({"section_id": "foreign"}, BusTransitionFailureReason.SECTION_BINDING),
        ({"boundary_id": "entry"}, BusTransitionFailureReason.BOUNDARY_BINDING),
        ({"window_id": "foreign"}, BusTransitionFailureReason.WINDOW_BINDING),
        (
            {"from_layer": "B.Cu", "to_layer": "F.Cu"},
            BusTransitionFailureReason.LAYER_BINDING,
        ),
    ),
)
def test_foreign_event_window_layer_section_and_boundary_are_typed(
    changes: dict[str, str],
    reason: BusTransitionFailureReason,
) -> None:
    fixture, _manual = c1._transition_fixture()
    event_payload = fixture.allocation.layer_transitions[0].model_dump()
    event_payload.update(changes)
    event = BusLayerTransitionEvent.model_validate(event_payload)
    allocation = _allocation_with_event(fixture.allocation, event)
    registry = _rebind_registry(fixture.registry, allocation)

    result = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        allocation,
        registry,
        OccupancyLedger(),
        BusTransitionBudget(max_members=1, max_events=1),
    )

    assert not result.success
    assert result.failure_reason is reason
    assert result.event_work_count == 1
    assert result.failed_event_id == result.telemetry[-1].event_id


def test_portal_point_mismatch_is_typed() -> None:
    fixture, _manual = c1._transition_fixture()
    geometries = []
    for geometry in fixture.registry.geometries:
        payload = geometry.model_dump()
        if geometry.centerline_geometry_id == "centerline:back":
            payload["entry_portal_point"] = (6, 2)
            payload["points"] = ((6, 2), (8, 2))
        geometries.append(CertifiedLaneGeometry.model_validate(payload))
    registry = _rebind_registry(
        fixture.registry,
        fixture.allocation,
        geometries=tuple(geometries),
    )

    result = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        registry,
        OccupancyLedger(),
        BusTransitionBudget(max_members=1, max_events=1),
    )

    assert not result.success
    assert result.failure_reason is BusTransitionFailureReason.PORTAL_BINDING
    assert result.event_work_count == 1


def test_same_net_duplicate_transition_site_is_rejected_after_retaining_work() -> None:
    member = c1._member()
    bus = BusGroup(
        bus_id="returning-transition",
        members=(member,),
        boundaries=tuple(
            c1._boundary(boundary, portal, member, terminals)
            for boundary, portal, terminals in (
                ("entry", "portal:entry", ("data0:source",)),
                ("first", "portal:first", ()),
                ("out", "portal:out", ()),
                ("return", "portal:return", ()),
                ("exit", "portal:exit", ("data0:sink",)),
            )
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu", "B.Cu"),
            via_policy=BusViaPolicy(
                mode="independent_bounded",
                maximum_vias_per_member=2,
            ),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )
    sections = (
        ("s0", "F.Cu", "portal:entry", "portal:first", ((2, 2), (5, 2))),
        ("s1", "B.Cu", "portal:first", "portal:out", ((5, 2), (7, 2))),
        ("s2", "B.Cu", "portal:out", "portal:return", ((7, 2), (5, 2))),
        ("s3", "F.Cu", "portal:return", "portal:exit", ((5, 2), (9, 2))),
    )
    certificate = c1._certificate(
        tuple(
            CertifiedCorridorSection(
                section_id=section_id,
                entry_portal_id=entry,
                exit_portal_id=exit_portal,
                lane_slots=(c1._slot(section_id, f"centerline:{section_id}", layer),),
                transition_window_ids=(
                    (f"window:{section_id}",) if section_id in {"s0", "s2"} else ()
                ),
            )
            for section_id, layer, entry, exit_portal, _points in sections
        )
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success and allocation.layer_transition_count == 2
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=tuple(
            c1._geometry(
                certificate,
                f"centerline:{section_id}",
                section_id,
                layer,
                entry,
                exit_portal,
                points,
            )
            for section_id, layer, entry, exit_portal, points in sections
        ),
    )

    result = generate_certified_bus_transition_vias(
        bus,
        certificate,
        allocation,
        registry,
        OccupancyLedger(),
        BusTransitionBudget(max_members=1, max_events=2),
    )

    assert not result.success
    assert result.failure_reason is BusTransitionFailureReason.DUPLICATE_SAME_NET_SITE
    assert result.event_work_count == 2
    assert tuple(item.generated for item in result.telemetry) == (True, False)
    assert len(result.carriers) == 1


def test_nested_json_revalidation_rejects_stale_input_and_carrier() -> None:
    fixture, _manual = c1._transition_fixture()
    result = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        OccupancyLedger(),
        BusTransitionBudget(max_members=1, max_events=1),
    )
    assert result.success

    stale_input = json.loads(result.model_dump_json())
    stale_input["input_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="input fingerprint is stale"):
        BusTransitionGenerationResult.model_validate(stale_input)

    stale_carrier = json.loads(result.model_dump_json())
    stale_carrier["carriers"][0]["point"] = [4, 2]
    with pytest.raises(ValidationError):
        BusTransitionGenerationResult.model_validate(stale_carrier)

    forged = result.model_copy(
        update={"carriers": (result.carriers[0].model_copy(update={"point": (4, 2)}),)}
    )
    with pytest.raises(ValidationError):
        BusTransitionGenerationResult.model_validate_json(forged.model_dump_json())


def test_bus_escape_opt_in_generates_transition_prefixes_and_real_c2_candidate() -> None:
    fixture = _two_member_fixture()
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    result = generate_certified_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.escapes,
        fixture.sources,
        ledger,
        ESCAPE_BUDGET,
        c2.DEFAULT_BUDGET,
        transition_budget=TRANSITION_BUDGET,
    )

    assert result.success
    assert result.semantic_fingerprint() == (
        "a1bca271e6d1064fe3a22eb7cae01b91f7894e7c7d92d9a774c4a80c567bdd92"
    )
    assert result.input_fingerprint == (
        "70c40e739619cf50cf001f0c7e4f4b6e65fd1d16a3c56e7140f52122973c3086"
    )
    assert result.escape_expansion_count == 8
    assert result.candidate is not None and result.candidate.success
    assert result.candidate.semantic_fingerprint() == (
        "5020535b605849b0f36aceb05bb69f360afdc7e7b4e56deeac27e852f27f2d10"
    )
    assert len(result.prefixes_by_member) == 2
    assert {
        (prefix.member_id, prefix.authority_kind, len(prefix.prefix.vias))
        for _member_id, prefix in result.prefixes_by_member
    } == {
        ("data0", "transition_fragments", 1),
        ("data1", "transition_fragments", 1),
    }
    for _member_id, prefix in result.prefixes_by_member:
        via = prefix.prefix.vias[0]
        assert via.size_mm == DEFAULT_PCB_RULE_PROFILE.geometry.routing_via_diameter_mm
        assert via.drill_mm == DEFAULT_PCB_RULE_PROFILE.geometry.routing_via_drill_mm
    assert ledger.semantic_fingerprint() == before


def test_cross_net_shared_transition_site_is_caught_by_downstream_candidate() -> None:
    fixture = _two_member_fixture(shared_transition_site=True)
    carriers = generate_certified_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        OccupancyLedger(),
        TRANSITION_BUDGET,
    )
    assert carriers.success
    assert {item.point for item in carriers.carriers} == {(15, 4)}

    result = generate_certified_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.escapes,
        fixture.sources,
        OccupancyLedger(),
        ESCAPE_BUDGET,
        c2.DEFAULT_BUDGET,
        transition_budget=TRANSITION_BUDGET,
    )

    assert not result.success
    assert result.failure_reason is BusEscapeFailureReason.CANDIDATE_FAILURE
    assert result.candidate is not None and not result.candidate.success


def test_subset_realization_is_canonical_bounded_and_preserves_full_behavior() -> None:
    mixed = _two_member_fixture(mixed_transition=True)
    subset = realize_certified_trunk_subset(
        mixed.bus,
        mixed.certificate,
        mixed.allocation,
        mixed.lanes,
        ("data1",),
    )

    assert tuple(item.member_id for item in subset.trunks) == ("data1",)
    assert subset.semantic_fingerprint() == (
        "0fb45cbd353c45333eb9e1a9784a379754e93ea9f9b515c8e0f08d3907e56435"
    )
    assert subset.trunks[0].geometry_fingerprint == (
        "219a12586835b760aba125c21cad641424f0b7ee814b814ad8331cd0d1708049"
    )
    assert subset.trunks[0].claims_fingerprint == (
        "469d609c0a09a9c46da4640cbc9ba1441a7d023210ee69377a0fc03ff36f4717"
    )
    for invalid in ((), ("unknown",), ("data1", "data1")):
        with pytest.raises(ValueError):
            realize_certified_trunk_subset(
                mixed.bus,
                mixed.certificate,
                mixed.allocation,
                mixed.lanes,
                invalid,
            )

    bus, certificate, allocation, lanes, full = c2._authority()
    repeated = realize_certified_trunk_subset(
        bus,
        certificate,
        allocation,
        lanes,
        ("data0", "data1"),
    )
    assert repeated.semantic_fingerprint() == full.semantic_fingerprint()
    with pytest.raises(ValueError, match="canonical and unique"):
        realize_certified_trunk_subset(
            bus,
            certificate,
            allocation,
            lanes,
            ("data1", "data0"),
        )


def test_mixed_transition_and_same_layer_member_reaches_real_c2_with_pins() -> None:
    fixture = _two_member_fixture(mixed_transition=True)
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    baseline = generate_certified_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.escapes,
        fixture.sources,
        ledger,
        ESCAPE_BUDGET,
        c2.DEFAULT_BUDGET,
        transition_budget=TRANSITION_BUDGET,
    )
    reversed_lanes = _rebind_registry(
        fixture.lanes,
        fixture.allocation,
        geometries=tuple(reversed(fixture.lanes.geometries)),
    )
    reversed_escapes = _escape_registry(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        reversed_lanes,
        {"data0": 24, "data1": 24},
    )
    reverse = generate_certified_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        reversed_lanes,
        reversed_escapes,
        dict(reversed(tuple(fixture.sources.items()))),
        OccupancyLedger(),
        ESCAPE_BUDGET,
        c2.DEFAULT_BUDGET,
        transition_budget=TRANSITION_BUDGET,
    )

    assert baseline.success and reverse.success
    assert baseline.semantic_fingerprint() == (
        "68aa4afa4ef968ef27cd6cf8a41b6d6ede26a7e215e1ba9a0addac0c6b5c6efa"
    )
    assert baseline.input_fingerprint == (
        "766f2585b002987930964c4045ab24ab636979c1e8bdbe7c48df57e21818ad9e"
    )
    assert baseline.semantic_json() == reverse.semantic_json()
    assert {
        (prefix.member_id, prefix.authority_kind, len(prefix.prefix.vias))
        for _member_id, prefix in baseline.prefixes_by_member
    } == {
        ("data0", "transition_fragments", 1),
        ("data1", "same_layer_trunk", 0),
    }
    assert baseline.candidate is not None and baseline.candidate.success
    assert ledger.semantic_fingerprint() == before


@pytest.mark.parametrize(
    "transition_budget",
    (
        BusTransitionBudget(max_members=0, max_events=1),
        BusTransitionBudget(max_members=1, max_events=0),
    ),
)
def test_mixed_transition_zero_and_one_less_budgets_fail_before_escape_work(
    transition_budget: BusTransitionBudget,
) -> None:
    fixture = _two_member_fixture(mixed_transition=True)
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    result = generate_certified_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.escapes,
        fixture.sources,
        ledger,
        ESCAPE_BUDGET,
        c2.DEFAULT_BUDGET,
        transition_budget=transition_budget,
    )

    assert not result.success
    assert result.failure_reason is BusEscapeFailureReason.TRANSITION_CARRIER_GENERATION
    assert result.escape_expansion_count == 0
    assert result.terminal_telemetry == ()
    assert result.pigtails == ()
    assert result.candidate is None
    assert ledger.semantic_fingerprint() == before


def test_mixed_transition_late_terminal_failure_retains_work_and_is_pure() -> None:
    fixture = _two_member_fixture(mixed_transition=True)
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()
    forbidden = RoutingResourceKey(
        "ordinary",
        "F.Cu",
        "edge",
        6,
        13,
        7,
        13,
    )

    result = generate_certified_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.escapes,
        fixture.sources,
        ledger,
        ESCAPE_BUDGET,
        c2.DEFAULT_BUDGET,
        transition_budget=TRANSITION_BUDGET,
        hard_forbidden_resources=(forbidden,),
    )

    assert not result.success
    assert result.failure_reason is BusEscapeFailureReason.ROUTING_ERROR
    assert result.failed_member_id == "data1"
    assert result.failed_terminal_id == "data1:source"
    assert tuple(item.routed for item in result.terminal_telemetry) == (
        True,
        True,
        True,
        False,
    )
    assert len(result.pigtails) == 3
    assert tuple(member_id for member_id, _prefix in result.prefixes_by_member) == ("data0",)
    assert result.candidate is None
    assert ledger.semantic_fingerprint() == before
