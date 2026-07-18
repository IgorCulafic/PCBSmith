from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_bus_physical_swap_plan import (
    _build,
    _two_event_regions,
)

from pcbsmith.kicad.bus_integration import (
    CertifiedBusPigtail,
    CertifiedBusTransitionVia,
)
from pcbsmith.kicad.bus_physical_swap_composition import (
    BusPhysicalSwapBoundaryKind,
    BusPhysicalSwapCompositionInput,
    BusPhysicalSwapTerminalSourceBinding,
    CertifiedPhysicalSwapBusMemberPrefix,
    ReplayBoundPhysicalSwapBusPrefixComposition,
    compose_replay_bound_physical_swap_bus_prefixes,
)
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)


@lru_cache(maxsize=1)
def _inputs(
    changed_point_transition: bool = False,
    foreign_claims: bool = False,
):
    regions = _two_event_regions(
        avoid_global_conflict=True,
        changed_point_transition=changed_point_transition,
    )
    ledger = None
    if foreign_claims:
        ledger = OccupancyLedger(
            (
                NetResourceClaims(
                    "/FOREIGN",
                    frozenset({RoutingResourceKey("ordinary", "F.Cu", "cell", 30, 30)}),
                ),
            )
        )
    plan = _build(region=regions[0], regions=regions, ledger=ledger)
    assert plan.outcome.plan is not None
    authority = plan.replay_input
    section_positions = {
        item.section_id: index for index, item in enumerate(authority.certificate.sections)
    }
    slots = {
        (section.section_id, slot.slot_id): slot
        for section in authority.certificate.sections
        for slot in section.lane_slots
    }
    geometry_by_id = {
        item.centerline_geometry_id: item for item in authority.lane_geometry_registry.geometries
    }
    geometries_by_member = {}
    for member in authority.bus.members:
        assignments = tuple(
            sorted(
                (
                    item
                    for item in authority.allocation.assignments
                    if item.member_id == member.member_id
                ),
                key=lambda item: section_positions[item.section_id],
            )
        )
        geometries_by_member[member.member_id] = tuple(
            geometry_by_id[slots[(item.section_id, item.slot_id)].centerline_geometry_id]
            for item in assignments
        )

    root = (
        authority.bus.semantic_fingerprint(),
        authority.certificate.semantic_fingerprint(),
        authority.allocation.allocation_fingerprint,
        authority.lane_geometry_registry.semantic_fingerprint(),
    )
    pigtails = []
    sources = []
    for member in authority.bus.members:
        first = geometries_by_member[member.member_id][0]
        last = geometries_by_member[member.member_id][-1]
        for terminal in member.terminals:
            source_side = terminal.role == "source"
            geometry = first if source_side else last
            portal_kind = "entry" if source_side else "exit"
            portal_point = (
                geometry.entry_portal_point if source_side else geometry.exit_portal_point
            )
            pad_point = (
                (portal_point[0], portal_point[1] - 1)
                if source_side
                else (portal_point[0], portal_point[1] + 1)
            )
            boundary_id = "entry" if source_side else "exit"
            source_id = f"pad:{member.member_id}:{terminal.role}"
            pigtails.append(
                CertifiedBusPigtail(
                    pigtail_id=f"pigtail:{terminal.terminal_id}",
                    bus_fingerprint=root[0],
                    certificate_fingerprint=root[1],
                    allocation_fingerprint=root[2],
                    geometry_registry_fingerprint=root[3],
                    member_id=member.member_id,
                    net_name=member.net_name,
                    terminal_id=terminal.terminal_id,
                    boundary_id=boundary_id,
                    assigned_geometry_id=geometry.centerline_geometry_id,
                    portal_kind=portal_kind,
                    physical_pad_source_id=source_id,
                    grid_mm=authority.certificate.grid_mm,
                    layer=geometry.layer,
                    pad_anchor_point=pad_point,
                    portal_point=portal_point,
                    points=(pad_point, portal_point),
                )
            )
            sources.append(
                BusPhysicalSwapTerminalSourceBinding(
                    member_id=member.member_id,
                    terminal_id=terminal.terminal_id,
                    physical_pad_source_id=source_id,
                )
            )

    transitions = []
    for event in authority.allocation.layer_transitions:
        geometries = geometries_by_member[event.member_id]
        before_index = next(
            index
            for index, geometry in enumerate(geometries)
            if geometry.section_id == event.section_id
        )
        before = geometries[before_index]
        after = geometries[before_index + 1]
        member = next(item for item in authority.bus.members if item.member_id == event.member_id)
        transitions.append(
            CertifiedBusTransitionVia(
                transition_via_id=f"transition:{event.member_id}:{event.section_id}",
                bus_fingerprint=root[0],
                certificate_fingerprint=root[1],
                allocation_fingerprint=root[2],
                geometry_registry_fingerprint=root[3],
                member_id=member.member_id,
                net_name=member.net_name,
                section_id=event.section_id,
                boundary_id=event.boundary_id,
                window_id=event.window_id,
                from_layer=event.from_layer,
                to_layer=event.to_layer,
                before_geometry_id=before.centerline_geometry_id,
                after_geometry_id=after.centerline_geometry_id,
                grid_mm=authority.certificate.grid_mm,
                point=before.exit_portal_point,
            )
        )
    return plan, tuple(pigtails), tuple(transitions), tuple(sources)


@lru_cache(maxsize=1)
def _compose():
    plan, pigtails, transitions, sources = _inputs()
    return compose_replay_bound_physical_swap_bus_prefixes(
        plan=plan,
        pigtails=pigtails,
        transition_vias=transitions,
        terminal_sources=sources,
    )


def test_successive_swap_plan_composes_all_connected_member_prefixes() -> None:
    result = _compose()

    assert tuple(item.member_id for item in result.members) == ("m0", "m1", "m2")
    by_member = {item.member_id: item for item in result.members}
    assert len(by_member["m0"].physical_carrier_fingerprints) == 2
    assert len(by_member["m0"].prefix.vias) == 4
    assert len(by_member["m1"].physical_carrier_fingerprints) == 1
    assert len(by_member["m2"].physical_carrier_fingerprints) == 1
    assert len(by_member["m1"].transition_via_fingerprints) == 1
    assert len(by_member["m2"].transition_via_fingerprints) == 1
    assert by_member["m0"].transition_via_fingerprints == ()
    accepted = result.replay_input.plan.outcome.plan
    assert accepted is not None
    first_m0 = next(
        item for item in accepted.carriers[0].region.member_portals if item.member_id == "m0"
    )
    second_m0 = next(
        item for item in accepted.carriers[1].region.member_portals if item.member_id == "m0"
    )
    assert first_m0.outgoing_geometry_id == by_member["m0"].active_geometry_ids[1]
    assert second_m0.incoming_geometry_id == by_member["m0"].active_geometry_ids[1]
    assert first_m0.outgoing_portal_point != second_m0.incoming_portal_point
    assert {item.kind for member in result.members for item in member.boundary_evidence} == {
        BusPhysicalSwapBoundaryKind.DIRECT,
        BusPhysicalSwapBoundaryKind.SEMANTIC_TRANSITION,
        BusPhysicalSwapBoundaryKind.PHYSICAL_SWAP,
    }
    assert (
        ReplayBoundPhysicalSwapBusPrefixComposition.model_validate_json(result.model_dump_json())
        == result
    )


def test_input_set_order_is_canonical_and_repeat_is_deterministic() -> None:
    plan, pigtails, transitions, sources = _inputs()
    forward = compose_replay_bound_physical_swap_bus_prefixes(
        plan=plan,
        pigtails=pigtails,
        transition_vias=transitions,
        terminal_sources=sources,
    )
    reversed_input = compose_replay_bound_physical_swap_bus_prefixes(
        plan=plan,
        pigtails=tuple(reversed(pigtails)),
        transition_vias=tuple(reversed(transitions)),
        terminal_sources=tuple(reversed(sources)),
    )

    assert forward == reversed_input
    assert forward.result_fingerprint == reversed_input.result_fingerprint
    assert _compose() == forward


def test_failed_plan_and_missing_duplicate_or_unused_inputs_reject() -> None:
    plan, pigtails, transitions, sources = _inputs()
    failed_regions = _two_event_regions()
    failed_plan = _build(region=failed_regions[0], regions=failed_regions)
    assert failed_plan.outcome.plan is None
    with pytest.raises(ValidationError, match="successful built plan"):
        BusPhysicalSwapCompositionInput(
            plan=failed_plan,
            pigtails=pigtails,
            transition_vias=transitions,
            terminal_sources=sources,
        )
    with pytest.raises(ValidationError, match="exactly cover every bus terminal"):
        BusPhysicalSwapCompositionInput(
            plan=plan,
            pigtails=pigtails[:-1],
            transition_vias=transitions,
            terminal_sources=sources,
        )
    with pytest.raises(ValidationError, match="unique by identity and terminal"):
        BusPhysicalSwapCompositionInput(
            plan=plan,
            pigtails=(*pigtails, pigtails[0]),
            transition_vias=transitions,
            terminal_sources=sources,
        )
    with pytest.raises(ValueError, match="lacks its exact transition carrier"):
        compose_replay_bound_physical_swap_bus_prefixes(
            plan=plan,
            pigtails=pigtails,
            transition_vias=(),
            terminal_sources=sources,
        )


def test_swapped_plan_carrier_order_and_transition_carrier_tamper_reject() -> None:
    plan, pigtails, transitions, sources = _inputs()
    assert plan.outcome.plan is not None
    swapped_inner = plan.outcome.plan.model_copy(
        update={"carriers": tuple(reversed(plan.outcome.plan.carriers))}
    )
    swapped_plan = plan.model_copy(
        update={"outcome": plan.outcome.model_copy(update={"plan": swapped_inner})}
    )
    with pytest.raises(ValidationError):
        BusPhysicalSwapCompositionInput(
            plan=swapped_plan,
            pigtails=pigtails,
            transition_vias=transitions,
            terminal_sources=sources,
        )

    wrong_geometry = transitions[0].model_copy(update={"before_geometry_id": "geometry:wrong"})
    with pytest.raises(ValueError, match="owner, geometry, or endpoint"):
        compose_replay_bound_physical_swap_bus_prefixes(
            plan=plan,
            pigtails=pigtails,
            transition_vias=(wrong_geometry, *transitions[1:]),
            terminal_sources=sources,
        )
    duplicate_transition = transitions[0].model_copy(
        update={"transition_via_id": "transition:duplicate"}
    )
    with pytest.raises(ValidationError, match="unique per allocation event"):
        BusPhysicalSwapCompositionInput(
            plan=plan,
            pigtails=pigtails,
            transition_vias=(*transitions, duplicate_transition),
            terminal_sources=sources,
        )
    unused_transition = transitions[0].model_copy(
        update={
            "transition_via_id": "transition:unused",
            "window_id": "transition:unused",
        }
    )
    with pytest.raises(ValueError, match="exactly cover member allocation events"):
        compose_replay_bound_physical_swap_bus_prefixes(
            plan=plan,
            pigtails=pigtails,
            transition_vias=(*transitions, unused_transition),
            terminal_sources=sources,
        )


def test_changed_point_and_changed_layer_boundary_is_unsupported() -> None:
    plan, pigtails, transitions, sources = _inputs(True)

    with pytest.raises(ValueError, match="changed-point changed-layer"):
        compose_replay_bound_physical_swap_bus_prefixes(
            plan=plan,
            pigtails=pigtails,
            transition_vias=transitions,
            terminal_sources=sources,
        )


def test_wrong_terminal_source_or_pigtail_binding_rejects() -> None:
    plan, pigtails, transitions, sources = _inputs()
    wrong_sources = (
        sources[0].model_copy(update={"physical_pad_source_id": "pad:wrong"}),
        *sources[1:],
    )
    with pytest.raises(ValueError, match="pigtail owner, terminal source"):
        compose_replay_bound_physical_swap_bus_prefixes(
            plan=plan,
            pigtails=pigtails,
            transition_vias=transitions,
            terminal_sources=wrong_sources,
        )
    wrong_pigtail = pigtails[0].model_copy(update={"assigned_geometry_id": "wrong"})
    with pytest.raises(ValueError, match="pigtail owner, terminal source"):
        compose_replay_bound_physical_swap_bus_prefixes(
            plan=plan,
            pigtails=(wrong_pigtail, *pigtails[1:]),
            transition_vias=transitions,
            terminal_sources=sources,
        )


def test_boundary_endpoint_geometry_and_carrier_membership_tamper_rejects() -> None:
    result = _compose()
    member = result.members[0]
    physical_index = next(
        index
        for index, item in enumerate(member.boundary_evidence)
        if item.kind is BusPhysicalSwapBoundaryKind.PHYSICAL_SWAP
    )
    original = member.boundary_evidence[physical_index]
    for update in (
        {"before_geometry_id": "geometry:wrong"},
        {
            "after_node": (
                original.after_node[0],
                original.after_node[1] + 1,
                original.after_node[2],
            )
        },
        {"carrier_member_fingerprint": "0" * 64},
    ):
        changed_evidence = list(member.boundary_evidence)
        changed_evidence[physical_index] = original.model_copy(update=update)
        changed_member = member.model_copy(update={"boundary_evidence": tuple(changed_evidence)})
        changed_members = list(result.members)
        changed_members[0] = changed_member
        with pytest.raises(ValidationError):
            ReplayBoundPhysicalSwapBusPrefixComposition.model_validate_json(
                result.model_copy(update={"members": tuple(changed_members)}).model_dump_json()
            )


@pytest.mark.parametrize(
    "field",
    (
        "active_geometry_ids",
        "boundary_evidence",
        "prefix",
        "prefix_fingerprint",
        "composition_fingerprint",
    ),
)
def test_member_geometry_coverage_prefix_and_fingerprints_rederive(field: str) -> None:
    result = _compose()
    member = result.members[0]
    if field == "active_geometry_ids":
        changed: Any = tuple(reversed(member.active_geometry_ids))
    elif field == "boundary_evidence":
        changed = member.boundary_evidence[:-1]
    elif field == "prefix":
        changed_segments = (
            replace(
                member.prefix.segments[0],
                width_mm=member.prefix.segments[0].width_mm + 0.01,
            ),
            *member.prefix.segments[1:],
        )
        changed = member.prefix.__class__(
            alternative_id=member.prefix.alternative_id,
            net_name=member.prefix.net_name,
            grid_mm=member.prefix.grid_mm,
            exit_node=member.prefix.exit_node,
            covered_pad_anchors=member.prefix.covered_pad_anchors,
            segments=changed_segments,
            vias=member.prefix.vias,
        )
    elif field == "prefix_fingerprint":
        changed = "0" * 64
    else:
        changed = "0" * 64
    with pytest.raises((ValidationError, ValueError)):
        CertifiedPhysicalSwapBusMemberPrefix.model_validate_json(
            member.model_copy(update={field: changed}).model_dump_json()
        )


def test_result_coverage_and_fingerprint_tamper_rejects() -> None:
    result = _compose()
    physical = result.coverage.consumed_physical_memberships
    coverage_updates = (
        {"consumed_physical_memberships": physical[:-1]},
        {"consumed_physical_memberships": (*physical, physical[0])},
        {
            "required_physical_memberships": (*physical, "0" * 64),
            "consumed_physical_memberships": (*physical, "0" * 64),
        },
    )
    for update in coverage_updates:
        bad_coverage = result.coverage.model_copy(update=update)
        with pytest.raises(ValidationError):
            ReplayBoundPhysicalSwapBusPrefixComposition.model_validate_json(
                result.model_copy(update={"coverage": bad_coverage}).model_dump_json()
            )
    with pytest.raises(ValidationError, match="result fingerprint"):
        ReplayBoundPhysicalSwapBusPrefixComposition.model_validate_json(
            result.model_copy(update={"result_fingerprint": "0" * 64}).model_dump_json()
        )
