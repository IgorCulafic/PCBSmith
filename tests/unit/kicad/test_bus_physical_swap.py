from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from pcbsmith.bus_allocator import BusAllocationBudget, BusSwapEvent, allocate_bus_lanes
from pcbsmith.bus_geometry import (
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
    certified_keep_in_fingerprint,
)
from pcbsmith.bus_ir import (
    BoundaryMemberRef,
    BusBoundary,
    BusGroup,
    BusLayerPolicy,
    BusMember,
    BusPermutationPolicy,
    BusSwapWindow,
    BusTerminalRef,
    BusViaPolicy,
    CertifiedCorridorSection,
    CertifiedLaneSlot,
    CorridorCapacityCertificate,
)
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist
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
    CertifiedBusSwapRegion,
    bus_physical_swap_board_geometry_fingerprint,
    bus_physical_swap_profile_fingerprint,
    bus_physical_swap_static_obstacle_fingerprint,
    certified_bus_swap_region_fingerprint,
    physical_swap_via_assignment_is_feasible,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

_POLYGON = ((3, 0), (3, 4), (7, 4), (7, 0))


def _member(index: int) -> BusMember:
    member_id = f"m{index}"
    net_name = f"/D{index}"
    return BusMember(
        member_id=member_id,
        net_name=net_name,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net_name,
                component_ref=f"U{index}",
                pad_number="1",
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net_name,
                component_ref=f"J{index}",
                pad_number="1",
                role="sink",
            ),
        ),
        width_mm=0.2,
    )


def _boundary(boundary_id: str, portal_id: str, order: tuple[str, ...]) -> BusBoundary:
    terminal_role = "source" if boundary_id == "entry" else "sink"
    return BusBoundary(
        boundary_id=boundary_id,
        corridor_portal_id=portal_id,
        orientation="forward",
        ordered_members=tuple(
            BoundaryMemberRef(
                member_id=item,
                terminal_ids=(f"{item}:{terminal_role}",) if boundary_id != "middle" else (),
            )
            for item in order
        ),
    )


def _bus(via_policy: BusViaPolicy | None = None) -> BusGroup:
    return BusGroup(
        bus_id="swap-data",
        members=(_member(0), _member(1), _member(2)),
        boundaries=(
            _boundary("entry", "portal:entry", ("m0", "m1", "m2")),
            _boundary("middle", "portal:middle", ("m1", "m0", "m2")),
            _boundary("exit", "portal:exit", ("m1", "m0", "m2")),
        ),
        permutation_policy=BusPermutationPolicy(
            swap_windows=(
                BusSwapWindow(
                    window_id="swap:main",
                    corridor_region_id="section:incoming",
                    allowed_adjacent_pairs=(("m1", "m0"),),
                    allowed_layers=("F.Cu",),
                    maximum_swaps=1,
                ),
            )
        ),
        layer_policy=BusLayerPolicy(
            allowed_layers=("B.Cu", "F.Cu"),
            preferred_layers=("F.Cu",),
            via_policy=via_policy
            or BusViaPolicy(
                mode="independent_bounded",
                maximum_vias_per_member=2,
                maximum_via_count_spread=2,
            ),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )


def _neutral_inputs() -> tuple[BoardLayout, BoardNetlist]:
    components = tuple(
        BoardComponent(
            reference=reference,
            value="connector",
            footprint="Connector_Generic:Conn_01x01",
            uuid_path=f"/{reference}",
        )
        for reference in ("J0", "J1", "J2", "U0", "U1", "U2")
    )
    netlist = BoardNetlist(
        components=components,
        nets=tuple(
            BoardNet(name=f"/D{index}", nodes=((f"U{index}", "1"), (f"J{index}", "1")))
            for index in range(3)
        ),
    )
    return BoardLayout(placements=(), segments=(), vias=(), width_mm=10, height_mm=6), netlist


def _certificate(
    bus: BusGroup,
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    declare_transition: bool = False,
) -> CorridorCapacityCertificate:
    sections = []
    for section_id, entry, exit_, prefix in (
        ("section:incoming", "portal:entry", "portal:middle", "in"),
        ("section:outgoing", "portal:middle", "portal:exit", "out"),
    ):
        sections.append(
            CertifiedCorridorSection(
                section_id=section_id,
                entry_portal_id=entry,
                exit_portal_id=exit_,
                lane_slots=tuple(
                    CertifiedLaneSlot(
                        slot_id=f"slot:{prefix}:{index}",
                        section_id=section_id,
                        layer="F.Cu",
                        order_index=index,
                        centerline_geometry_id=f"geometry:{prefix}:{index}",
                        maximum_track_width_mm=0.3,
                        supported_clearance_domain_ids=("ordinary",),
                    )
                    for index in range(3)
                ),
                swap_window_ids=("swap:main",) if prefix == "in" else (),
                transition_window_ids=("swap:main",)
                if prefix == "in" and declare_transition
                else (),
            )
        )
    return CorridorCapacityCertificate(
        certificate_id="certificate:swap",
        board_geometry_fingerprint=bus_physical_swap_board_geometry_fingerprint(layout),
        static_obstacle_fingerprint=bus_physical_swap_static_obstacle_fingerprint(
            layout, netlist
        ),
        rule_profile_fingerprint=bus_physical_swap_profile_fingerprint(
            DEFAULT_PCB_RULE_PROFILE
        ),
        demand_fingerprint=bus.semantic_fingerprint(),
        corridor_graph_fingerprint="e" * 64,
        grid_mm=1.0,
        sections=tuple(sections),
        exact_capacity_proof_id="exact-swap-capacity-v1",
    )


def _geometry(
    certificate: CorridorCapacityCertificate,
    section_id: str,
    index: int,
) -> CertifiedLaneGeometry:
    incoming = section_id == "section:incoming"
    prefix = "in" if incoming else "out"
    y = 1 + 2 * index
    points = ((0, y), (4, y)) if incoming else ((6, y), (9, y))
    polygon = ((0, 0), (0, 6), (9, 6), (9, 0))
    return CertifiedLaneGeometry(
        centerline_geometry_id=f"geometry:{prefix}:{index}",
        certificate_fingerprint=certificate.semantic_fingerprint(),
        section_id=section_id,
        layer="F.Cu",
        track_width_mm=0.2,
        grid_mm=1.0,
        entry_portal_id="portal:entry" if incoming else "portal:middle",
        exit_portal_id="portal:middle" if incoming else "portal:exit",
        entry_portal_point=points[0],
        exit_portal_point=points[-1],
        points=points,
        keep_in_polygon=polygon,
        keep_in_fingerprint=certified_keep_in_fingerprint(1.0, polygon),
    )


def _graph() -> tuple[
    tuple[tuple[str, int, int], ...],
    tuple[tuple[tuple[str, int, int], tuple[str, int, int]], ...],
    tuple[tuple[int, int], ...],
]:
    cells = tuple((x, y) for x in range(4, 7) for y in range(1, 4))
    nodes = tuple((layer, x, y) for layer in ("F.Cu", "B.Cu") for x, y in cells)
    transitions: list[tuple[tuple[str, int, int], tuple[str, int, int]]] = []
    for layer in ("F.Cu", "B.Cu"):
        for x, y in cells:
            for neighbour in ((x + 1, y), (x, y + 1)):
                if neighbour in cells:
                    transitions.append(((layer, x, y), (layer, *neighbour)))
    vias = ((5, 1), (5, 3))
    transitions.extend((("F.Cu", *cell), ("B.Cu", *cell)) for cell in vias)
    return tuple(sorted(nodes)), tuple(sorted(transitions)), vias


def _region_payload(
    *,
    via_policy: BusViaPolicy | None = None,
    layout: BoardLayout | None = None,
    declare_transition: bool = False,
    policy_updates: dict[str, Any] | None = None,
    event_update: dict[str, Any] | None = None,
    graph_update: dict[str, Any] | None = None,
    portal_update: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default_layout, netlist = _neutral_inputs()
    layout = layout or default_layout
    bus = _bus(via_policy)
    certificate = _certificate(bus, layout, netlist, declare_transition=declare_transition)
    allocation = allocate_bus_lanes(bus, certificate, budget=BusAllocationBudget(max_states=20))
    assert allocation.success and len(allocation.swaps) == 1
    event = allocation.swaps[0].model_copy(update=event_update or {})
    geometries = tuple(
        _geometry(certificate, section_id, index)
        for section_id in ("section:incoming", "section:outgoing")
        for index in range(3)
    )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=1.0,
        geometries=geometries,
    )
    policy_values: dict[str, Any] = {
        "windows": (
            BusPhysicalSwapWindowPolicy(
                window_id="swap:main",
                bridge_layer="B.Cu",
                via_process_id="through-via:default",
            ),
        ),
        "maximum_physical_vias_per_member": 2,
        "maximum_combined_vias_per_member": 2,
        "maximum_combined_via_count_spread": 2,
        "budget": BusPhysicalSwapBudget(
            max_events=1,
            max_candidates_per_event=2,
            max_expansions_per_candidate=30,
        ),
    }
    policy_values.update(policy_updates or {})
    policy = BusPhysicalSwapPolicy(**policy_values)
    geometry_by_id = {item.centerline_geometry_id: item for item in geometries}
    assignments = {(item.section_id, item.member_id): item for item in allocation.assignments}
    slots = {
        (section.section_id, slot.slot_id): slot
        for section in certificate.sections
        for slot in section.lane_slots
    }
    portals = []
    for member_id in ("m0", "m1"):
        incoming_assignment = assignments[("section:incoming", member_id)]
        outgoing_assignment = assignments[("section:outgoing", member_id)]
        incoming = geometry_by_id[
            slots[("section:incoming", incoming_assignment.slot_id)].centerline_geometry_id
        ]
        outgoing = geometry_by_id[
            slots[("section:outgoing", outgoing_assignment.slot_id)].centerline_geometry_id
        ]
        portals.append(
            BusSwapMemberPortalAuthority(
                member_id=member_id,
                incoming_section_id="section:incoming",
                outgoing_section_id="section:outgoing",
                incoming_geometry_id=incoming.centerline_geometry_id,
                outgoing_geometry_id=outgoing.centerline_geometry_id,
                incoming_portal_id=incoming.exit_portal_id,
                outgoing_portal_id=outgoing.entry_portal_id,
                incoming_portal_point=incoming.exit_portal_point,
                outgoing_portal_point=outgoing.entry_portal_point,
            )
        )
    if portal_update:
        portals[0] = portals[0].model_copy(update=portal_update)
    nodes, transitions, vias = _graph()
    graph = {"allowed_nodes": nodes, "allowed_transitions": transitions, "allowed_via_cells": vias}
    graph.update(graph_update or {})
    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    return {
        "region_id": "swap-region:main",
        "layout_snapshot_json": layout_json,
        "netlist_snapshot_json": netlist_json,
        "layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(layout_json),
        "netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(netlist_json),
        "bus": bus,
        "certificate": certificate,
        "allocation": allocation,
        "lane_geometry_registry": registry,
        "rule_profile": DEFAULT_PCB_RULE_PROFILE,
        "swap_event": event,
        "physical_policy": policy,
        "keep_in_polygon": _POLYGON,
        "keep_in_fingerprint": certified_keep_in_fingerprint(1.0, _POLYGON),
        **graph,
        "member_portals": tuple(portals),
        "bridge_layer": "B.Cu",
    }


def _finish(payload: dict[str, Any]) -> CertifiedBusSwapRegion:
    payload = dict(payload)
    payload["allowed_nodes"] = tuple(sorted(payload["allowed_nodes"]))
    payload["allowed_transitions"] = tuple(
        sorted((min(edge), max(edge)) for edge in payload["allowed_transitions"])
    )
    payload["allowed_via_cells"] = tuple(sorted(payload["allowed_via_cells"]))
    payload["member_portals"] = tuple(
        sorted(payload["member_portals"], key=lambda item: item.member_id)
    )
    polygon = payload["keep_in_polygon"]
    rotations = []
    for sequence in (polygon, tuple(reversed(polygon))):
        rotations.extend((*sequence[index:], *sequence[:index]) for index in range(len(sequence)))
    payload["keep_in_polygon"] = min(rotations)
    payload["keep_in_fingerprint"] = certified_keep_in_fingerprint(
        payload["certificate"].grid_mm, payload["keep_in_polygon"]
    )
    json_payload = CertifiedBusSwapRegion.model_construct(
        **payload, region_fingerprint="0" * 64
    ).model_dump(mode="json", exclude={"region_fingerprint"})
    payload["region_fingerprint"] = certified_bus_swap_region_fingerprint(json_payload)
    return CertifiedBusSwapRegion.model_validate(payload)


def test_valid_two_member_declaration_roundtrips_without_physical_success() -> None:
    region = _finish(_region_payload())

    assert region.require_authority() == region
    assert CertifiedBusSwapRegion.model_validate_json(region.model_dump_json()) == region
    assert region.swap_event == region.allocation.swaps[0]
    assert {item.member_id for item in region.member_portals} == {"m0", "m1"}
    assert not (
        {"carrier", "segments", "vias", "claims", "success"}
        & set(CertifiedBusSwapRegion.model_fields)
    )


def test_reversed_canonical_set_inputs_produce_identical_region() -> None:
    original = _finish(_region_payload())
    payload = _region_payload()
    payload["allowed_nodes"] = tuple(reversed(payload["allowed_nodes"]))
    payload["allowed_transitions"] = tuple(reversed(payload["allowed_transitions"]))
    payload["allowed_via_cells"] = tuple(reversed(payload["allowed_via_cells"]))
    payload["member_portals"] = tuple(reversed(payload["member_portals"]))
    payload["keep_in_polygon"] = tuple(reversed(payload["keep_in_polygon"]))

    assert _finish(payload) == original


@pytest.mark.parametrize(
    ("policy_update", "match"),
    [
        (
            {
                "budget": BusPhysicalSwapBudget(
                    max_events=0,
                    max_candidates_per_event=2,
                    max_expansions_per_candidate=30,
                )
            },
            "event budget",
        ),
        (
            {
                "budget": BusPhysicalSwapBudget(
                    max_events=1,
                    max_candidates_per_event=1,
                    max_expansions_per_candidate=30,
                )
            },
            "candidate budget",
        ),
        (
            {
                "budget": BusPhysicalSwapBudget(
                    max_events=1,
                    max_candidates_per_event=2,
                    max_expansions_per_candidate=0,
                )
            },
            "expansion budget",
        ),
        ({"maximum_combined_vias_per_member": 1}, "combined via maximum"),
        ({"maximum_combined_via_count_spread": 1}, "no complete bridge-member"),
    ],
)
def test_zero_or_one_less_policy_budgets_fail_closed(
    policy_update: dict[str, Any], match: str
) -> None:
    with pytest.raises((ValidationError, ValueError), match=match):
        _finish(_region_payload(policy_updates=policy_update))


@pytest.mark.parametrize(
    ("event_update", "match"),
    [
        ({"window_id": "swap:unknown"}, "exact allocation swap event"),
        ({"section_id": "section:outgoing"}, "exact allocation swap event"),
        ({"exit_boundary_id": "exit"}, "exact allocation swap event"),
        ({"order_index": 1}, "exact allocation swap event"),
        ({"first_member_id": "m1", "second_member_id": "m0"}, "exact allocation swap event"),
    ],
)
def test_stale_event_identity_fails_closed(event_update: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _finish(_region_payload(event_update=event_update))


def test_forbidden_and_escape_only_via_policies_reject_semantic_swap() -> None:
    for via_policy in (
        BusViaPolicy(mode="forbidden"),
        BusViaPolicy(mode="escape_only", maximum_vias_per_member=2),
    ):
        with pytest.raises(ValidationError, match="forbids physical corridor crossovers"):
            _finish(_region_payload(via_policy=via_policy))


def test_declared_mode_requires_the_exact_transition_window() -> None:
    policy = BusViaPolicy(
        mode="declared_transition_windows",
        transition_window_ids=("swap:main",),
        maximum_vias_per_member=2,
        maximum_via_count_spread=2,
    )
    with pytest.raises(ValidationError, match="required declared transition window"):
        _finish(_region_payload(via_policy=policy))

    assert _finish(_region_payload(via_policy=policy, declare_transition=True)).require_authority()


def test_same_bridge_and_event_layer_is_rejected() -> None:
    with pytest.raises(ValidationError, match="oppose the event layer"):
        _finish(
            _region_payload(
                policy_updates={
                    "windows": (
                        BusPhysicalSwapWindowPolicy(
                            window_id="swap:main",
                            bridge_layer="F.Cu",
                            via_process_id="through-via:default",
                        ),
                    )
                }
            )
        )


def test_disconnected_graph_and_stale_via_cells_fail_independently() -> None:
    payload = _region_payload()
    transitions = tuple(
        edge
        for edge in payload["allowed_transitions"]
        if edge[0][0] == "F.Cu" or edge[1][0] == "F.Cu"
    )
    with pytest.raises(ValidationError, match="graph must be connected"):
        _finish({**payload, "allowed_transitions": transitions})

    with pytest.raises(ValidationError, match="explicit node on both layers"):
        _finish(_region_payload(graph_update={"allowed_via_cells": ((5, 1), (8, 8))}))


def test_stale_endpoint_geometry_and_portal_point_fail_closed() -> None:
    with pytest.raises(ValidationError, match="portal identity or point is stale"):
        _finish(_region_payload(portal_update={"incoming_geometry_id": "geometry:stale"}))
    with pytest.raises(ValidationError, match="portal identity or point is stale"):
        _finish(_region_payload(portal_update={"incoming_portal_point": (4, 2)}))


def test_opaque_placement_and_raw_graphics_are_unsupported() -> None:
    layout, netlist = _neutral_inputs()
    placed = replace(layout, placements=((netlist.components[0], 1.0),))
    with pytest.raises(ValidationError, match="opaque footprint"):
        _finish(_region_payload(layout=placed))
    graphic = replace(layout, graphics=("(gr_line (start 0 0) (end 1 1))",))
    with pytest.raises(ValidationError, match="raw graphic"):
        _finish(_region_payload(layout=graphic))
    zone = replace(layout, zones=(("/D0", "F.Cu", (1.0, 1.0, 2.0, 2.0)),))
    with pytest.raises(ValidationError, match="unfilled copper zone"):
        _finish(_region_payload(layout=zone))


def test_self_intersecting_keep_in_is_rejected() -> None:
    payload = _region_payload()
    payload["keep_in_polygon"] = ((3, 0), (7, 4), (3, 4), (6, 0))
    with pytest.raises(ValidationError, match="polygon must be simple"):
        _finish(payload)


def test_require_authority_rejects_stale_nested_inputs_and_final_fingerprint() -> None:
    region = _finish(_region_payload())
    stale_certificate = region.certificate.model_copy(
        update={"corridor_graph_fingerprint": "f" * 64}
    )
    tampered = region.model_copy(
        update={
            "certificate": stale_certificate,
            "region_fingerprint": region.region_fingerprint,
        }
    )
    with pytest.raises(ValidationError):
        tampered.require_authority()

    bad_final = region.model_copy(update={"region_fingerprint": "0" * 64})
    with pytest.raises(ValidationError, match="region_fingerprint"):
        bad_final.require_authority()


def test_snapshot_fingerprints_bind_exact_layout_and_netlist() -> None:
    payload = _region_payload()
    payload["layout_snapshot_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="layout snapshot fingerprint"):
        _finish(payload)
    payload = _region_payload()
    payload["netlist_snapshot_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="netlist snapshot fingerprint"):
        _finish(payload)


def test_each_retained_authority_is_cross_bound_not_just_final_hashed() -> None:
    payload = _region_payload()
    payload["bus"] = payload["bus"].model_copy(update={"bus_id": "stale-bus"})
    with pytest.raises(ValidationError, match="bus demand is stale"):
        _finish(payload)

    payload = _region_payload()
    payload["certificate"] = payload["certificate"].model_copy(
        update={"corridor_graph_fingerprint": "f" * 64}
    )
    with pytest.raises(ValidationError, match="allocation certificate authority is stale"):
        _finish(payload)

    payload = _region_payload()
    payload["allocation"] = payload["allocation"].model_copy(
        update={"bus_fingerprint": "0" * 64}
    )
    with pytest.raises(ValidationError, match="allocation_fingerprint"):
        _finish(payload)

    payload = _region_payload()
    payload["lane_geometry_registry"] = payload["lane_geometry_registry"].model_copy(
        update={"allocation_fingerprint": "0" * 64}
    )
    with pytest.raises(ValidationError, match="registry allocation authority is stale"):
        _finish(payload)

    payload = _region_payload()
    payload["rule_profile"] = payload["rule_profile"].model_copy(
        update={"profile_id": "stale-profile"}
    )
    with pytest.raises(ValidationError, match="certificate rule profile is stale"):
        _finish(payload)

    payload = _region_payload()
    changed_layout = replace(_neutral_inputs()[0], width_mm=11)
    changed_layout_json = canonical_board_layout_snapshot_json(changed_layout)
    payload["layout_snapshot_json"] = changed_layout_json
    payload["layout_snapshot_fingerprint"] = board_layout_snapshot_fingerprint(
        changed_layout_json
    )
    with pytest.raises(ValidationError, match="certificate board geometry is stale"):
        _finish(payload)

    payload = _region_payload()
    _, original_netlist = _neutral_inputs()
    changed_netlist = replace(original_netlist, nets=original_netlist.nets[:-1])
    changed_netlist_json = canonical_board_netlist_snapshot_json(changed_netlist)
    payload["netlist_snapshot_json"] = changed_netlist_json
    payload["netlist_snapshot_fingerprint"] = board_netlist_snapshot_fingerprint(
        changed_netlist_json
    )
    with pytest.raises(ValidationError, match="certificate static-obstacle authority is stale"):
        _finish(payload)


def _global_swap_events() -> tuple[BusSwapEvent, ...]:
    pairs = (("m0", "m1"), ("m0", "m2"), ("m0", "m3"), ("m1", "m2"), ("m1", "m3"))
    return tuple(
        BusSwapEvent(
            section_id="section:multi",
            exit_boundary_id="boundary:multi",
            window_id="swap:multi",
            sequence_index=index,
            order_index=0,
            first_member_id=pair[0],
            second_member_id=pair[1],
            layer="F.Cu",
        )
        for index, pair in enumerate(pairs)
    )


def _global_policy(
    *,
    physical_maximum: int,
    combined_maximum: int,
    combined_spread: int,
) -> BusPhysicalSwapPolicy:
    return BusPhysicalSwapPolicy(
        windows=(
            BusPhysicalSwapWindowPolicy(
                window_id="swap:multi",
                bridge_layer="B.Cu",
                via_process_id="through-via:default",
            ),
        ),
        maximum_physical_vias_per_member=physical_maximum,
        maximum_combined_vias_per_member=combined_maximum,
        maximum_combined_via_count_spread=combined_spread,
        budget=BusPhysicalSwapBudget(
            max_events=5,
            max_candidates_per_event=2,
            max_expansions_per_candidate=1,
        ),
    )


def test_multi_event_via_limits_are_globally_not_eventwise_feasible() -> None:
    events = _global_swap_events()
    counts = {f"m{index}": 0 for index in range(4)}
    locally_permitted = _global_policy(
        physical_maximum=2,
        combined_maximum=2,
        combined_spread=2,
    )
    via_policy = BusViaPolicy(
        mode="independent_bounded",
        maximum_vias_per_member=2,
        maximum_via_count_spread=2,
    )

    assert all(
        physical_swap_via_assignment_is_feasible(
            events=(event,),
            semantic_via_counts=counts,
            physical_policy=locally_permitted.model_copy(
                update={
                    "budget": BusPhysicalSwapBudget(
                        max_events=1,
                        max_candidates_per_event=2,
                        max_expansions_per_candidate=1,
                    )
                }
            ),
            bus_via_policy=via_policy,
        )
        for event in events
    )
    assert not physical_swap_via_assignment_is_feasible(
        events=events,
        semantic_via_counts=counts,
        physical_policy=locally_permitted,
        bus_via_policy=via_policy,
    )


def test_global_equality_limits_pass_and_each_one_less_limit_fails() -> None:
    events = _global_swap_events()
    counts = {f"m{index}": 0 for index in range(4)}
    equality = _global_policy(
        physical_maximum=4,
        combined_maximum=4,
        combined_spread=2,
    )
    equality_bus = BusViaPolicy(
        mode="independent_bounded",
        maximum_vias_per_member=4,
        maximum_via_count_spread=2,
    )
    assert physical_swap_via_assignment_is_feasible(
        events=events,
        semantic_via_counts=counts,
        physical_policy=equality,
        bus_via_policy=equality_bus,
    )

    for policy, bus_policy in (
        (
            _global_policy(
                physical_maximum=3,
                combined_maximum=4,
                combined_spread=2,
            ),
            equality_bus,
        ),
        (
            _global_policy(
                physical_maximum=4,
                combined_maximum=4,
                combined_spread=1,
            ),
            equality_bus,
        ),
        (
            equality,
            BusViaPolicy(
                mode="independent_bounded",
                maximum_vias_per_member=3,
                maximum_via_count_spread=2,
            ),
        ),
        (
            equality,
            BusViaPolicy(
                mode="independent_bounded",
                maximum_vias_per_member=4,
                maximum_via_count_spread=1,
            ),
        ),
    ):
        assert not physical_swap_via_assignment_is_feasible(
            events=events,
            semantic_via_counts=counts,
            physical_policy=policy,
            bus_via_policy=bus_policy,
        )

    semantic_two = {member_id: 2 for member_id in counts}
    combined_equality = _global_policy(
        physical_maximum=4,
        combined_maximum=6,
        combined_spread=2,
    )
    bus_six = BusViaPolicy(
        mode="independent_bounded",
        maximum_vias_per_member=6,
        maximum_via_count_spread=2,
    )
    assert physical_swap_via_assignment_is_feasible(
        events=events,
        semantic_via_counts=semantic_two,
        physical_policy=combined_equality,
        bus_via_policy=bus_six,
    )
    assert not physical_swap_via_assignment_is_feasible(
        events=events,
        semantic_via_counts=semantic_two,
        physical_policy=_global_policy(
            physical_maximum=4,
            combined_maximum=5,
            combined_spread=2,
        ),
        bus_via_policy=bus_six,
    )
