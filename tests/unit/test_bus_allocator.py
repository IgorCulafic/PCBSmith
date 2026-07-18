from __future__ import annotations

from typing import Literal

import pytest

from pcbsmith.bus_allocator import (
    BusAllocationBudget,
    BusAllocationFailureReason,
    allocate_bus_lanes,
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


def _member(index: int, *, width_mm: float = 0.2) -> BusMember:
    member_id = f"m{index}"
    net_name = f"/D{index}"
    return BusMember(
        member_id=member_id,
        net_name=net_name,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net_name,
                component_ref="U1",
                pad_number=str(index + 1),
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net_name,
                component_ref="U2",
                pad_number=str(index + 1),
                role="sink",
            ),
        ),
        width_mm=width_mm,
    )


def _boundary(
    boundary_id: str,
    portal_id: str,
    order: tuple[str, ...],
    *,
    orientation: Literal["forward", "reverse"] = "forward",
) -> BusBoundary:
    terminal_role = "source" if boundary_id == "entry" else "sink"
    return BusBoundary(
        boundary_id=boundary_id,
        corridor_portal_id=portal_id,
        orientation=orientation,
        ordered_members=tuple(
            BoundaryMemberRef(
                member_id=member_id,
                terminal_ids=(f"{member_id}:{terminal_role}",),
            )
            for member_id in order
        ),
    )


def _bus(
    *,
    exit_order: tuple[str, ...] = ("m0", "m1", "m2", "m3"),
    exit_orientation: Literal["forward", "reverse"] = "forward",
    allow_reversal: bool = False,
    widths: tuple[float, ...] = (0.2, 0.2, 0.2, 0.2),
    reverse_member_input: bool = False,
) -> BusGroup:
    members = tuple(_member(index, width_mm=width) for index, width in enumerate(widths))
    if reverse_member_input:
        members = tuple(reversed(members))
    return BusGroup(
        bus_id="data",
        members=members,
        boundaries=(
            _boundary("entry", "portal:entry", ("m0", "m1", "m2", "m3")),
            _boundary(
                "exit",
                "portal:exit",
                exit_order,
                orientation=exit_orientation,
            ),
        ),
        permutation_policy=BusPermutationPolicy(allow_whole_bundle_reversal=allow_reversal),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",),
            preferred_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        rule_profile_id="default-two-layer",
    )


def _certificate(
    slot_count: int,
    *,
    maximum_widths: tuple[float, ...] | None = None,
    reverse_clearance_input: bool = False,
) -> CorridorCapacityCertificate:
    widths = maximum_widths or (0.4,) * slot_count
    domains = (
        ("pair:data", "ordinary")
        if reverse_clearance_input
        else (
            "ordinary",
            "pair:data",
        )
    )
    section = CertifiedCorridorSection(
        section_id="section:main",
        entry_portal_id="portal:entry",
        exit_portal_id="portal:exit",
        lane_slots=tuple(
            CertifiedLaneSlot(
                slot_id=f"lane:{index}",
                section_id="section:main",
                layer="F.Cu",
                order_index=index,
                centerline_geometry_id=f"centerline:{index}",
                maximum_track_width_mm=widths[index],
                supported_clearance_domain_ids=domains,
            )
            for index in range(slot_count)
        ),
    )
    return CorridorCapacityCertificate(
        certificate_id="certificate:data",
        board_geometry_fingerprint="a" * 64,
        static_obstacle_fingerprint="b" * 64,
        rule_profile_fingerprint="c" * 64,
        demand_fingerprint="d" * 64,
        corridor_graph_fingerprint="e" * 64,
        grid_mm=0.5,
        sections=(section,),
        exact_capacity_proof_id="capacity-proof-v1",
    )


def test_same_order_four_member_bus_uses_exact_four_slots() -> None:
    result = allocate_bus_lanes(_bus(), _certificate(4))

    assert result.success
    assert result.failure_reason is None
    assert result.state_count == 1
    assert result.reversal_count == 0
    assert {assignment.member_id: assignment.slot_id for assignment in result.assignments} == {
        f"m{index}": f"lane:{index}" for index in range(4)
    }
    assert (
        result.semantic_fingerprint()
        == "3417223856291e6ce0ff43939468d84d18f222070bc94ff5383b57a261c359e1"
    )
    assert (
        result.allocation_fingerprint
        == "34190f2212eedabeae24186cd6a855e55e20585712e7c8a04c3f0c5f27eb4366"
    )


@pytest.mark.parametrize("allowed", [False, True])
def test_whole_bundle_reversal_requires_explicit_policy(allowed: bool) -> None:
    result = allocate_bus_lanes(
        _bus(
            exit_order=("m3", "m2", "m1", "m0"),
            allow_reversal=allowed,
        ),
        _certificate(4),
    )

    assert result.success is allowed
    assert result.reversal_count == 1
    assert result.failure_reason is (
        None if allowed else BusAllocationFailureReason.WHOLE_BUNDLE_REVERSAL_FORBIDDEN
    )


def test_reverse_declared_orientation_normalizes_to_canonical_portal_order() -> None:
    result = allocate_bus_lanes(
        _bus(
            exit_order=("m3", "m2", "m1", "m0"),
            exit_orientation="reverse",
        ),
        _certificate(4),
    )

    assert result.success
    assert result.reversal_count == 0


def test_adjacent_interior_inversion_is_rejected_without_swap_behavior() -> None:
    result = allocate_bus_lanes(
        _bus(exit_order=("m0", "m2", "m1", "m3")),
        _certificate(4),
    )

    assert not result.success
    assert result.failure_reason is BusAllocationFailureReason.INTERIOR_PERMUTATION_UNSUPPORTED
    assert result.assignments == ()


def test_member_tap_deactivation_continues_remaining_order() -> None:
    base = _bus()
    middle = _boundary(
        "middle",
        "portal:middle",
        ("m0", "m1", "m2", "m3"),
    )
    exit_boundary = BusBoundary(
        boundary_id="exit",
        corridor_portal_id="portal:exit",
        orientation="forward",
        ordered_members=tuple(
            BoundaryMemberRef(
                member_id=f"m{index}",
                terminal_ids=(f"m{index}:sink",),
            )
            for index in range(3)
        ),
        inactive_member_ids=("m3",),
    )
    bus = BusGroup.model_validate(
        {
            **base.model_dump(),
            "boundaries": (base.boundaries[0], middle, exit_boundary),
        }
    )
    first = _certificate(4).sections[0].model_copy(update={"exit_portal_id": "portal:middle"})
    second = CertifiedCorridorSection(
        section_id="section:tail",
        entry_portal_id="portal:middle",
        exit_portal_id="portal:exit",
        lane_slots=tuple(
            CertifiedLaneSlot(
                slot_id=f"tail:{index}",
                section_id="section:tail",
                layer="F.Cu",
                order_index=index,
                centerline_geometry_id=f"tail-centerline:{index}",
                maximum_track_width_mm=0.4,
                supported_clearance_domain_ids=("ordinary",),
            )
            for index in range(4)
        ),
    )
    certificate = CorridorCapacityCertificate.model_validate(
        {
            **_certificate(4).model_dump(),
            "sections": (first, second),
        }
    )

    result = allocate_bus_lanes(bus, certificate)

    assert result.success
    assert result.activation_count == 1
    assert result.activations[0].member_id == "m3"
    assert result.activations[0].kind == "deactivate"
    assert result.activations[0].boundary_id == "middle"
    tail_members = {
        item.member_id for item in result.assignments if item.section_id == "section:tail"
    }
    assert tail_members == {"m0", "m1", "m2"}


def test_capacity_n_minus_one_fails_before_lane_search() -> None:
    result = allocate_bus_lanes(_bus(), _certificate(3))

    assert not result.success
    assert result.failure_reason is BusAllocationFailureReason.CAPACITY_INSUFFICIENT
    assert result.state_count == 0


def test_extra_equal_cost_slots_choose_canonical_left_block() -> None:
    result = allocate_bus_lanes(_bus(), _certificate(6))

    assert result.success
    assert result.state_count == 3
    assert {assignment.member_id: assignment.slot_id for assignment in result.assignments} == {
        f"m{index}": f"lane:{index}" for index in range(4)
    }


def test_mixed_member_width_rejects_every_consecutive_block() -> None:
    result = allocate_bus_lanes(
        _bus(widths=(0.2, 0.5, 0.2, 0.2)),
        _certificate(4, maximum_widths=(0.4, 0.4, 0.4, 0.4)),
    )

    assert not result.success
    assert result.failure_reason is BusAllocationFailureReason.NO_COMPATIBLE_LANE_BLOCK


def test_zero_and_one_less_state_budgets_are_typed() -> None:
    zero = allocate_bus_lanes(
        _bus(),
        _certificate(4),
        budget=BusAllocationBudget(max_states=0),
    )
    one_less = allocate_bus_lanes(
        _bus(),
        _certificate(6),
        budget=BusAllocationBudget(max_states=2),
    )

    assert zero.failure_reason is BusAllocationFailureReason.STATE_BUDGET
    assert zero.state_count == 0
    assert one_less.failure_reason is BusAllocationFailureReason.STATE_BUDGET
    assert one_less.state_count == 2


def test_reversed_identity_inputs_and_repeated_runs_pin_fingerprints() -> None:
    first = allocate_bus_lanes(_bus(), _certificate(6))
    repeated = allocate_bus_lanes(
        _bus(reverse_member_input=True),
        _certificate(6, reverse_clearance_input=True),
    )

    assert first == repeated
    assert first.allocation_fingerprint == repeated.allocation_fingerprint
    assert first.semantic_fingerprint() == repeated.semantic_fingerprint()


def _two_section_bus(
    middle_order: tuple[str, ...],
    exit_order: tuple[str, ...],
) -> BusGroup:
    base = _bus(allow_reversal=True)
    return BusGroup.model_validate(
        {
            **base.model_dump(),
            "boundaries": (
                base.boundaries[0],
                _boundary("middle", "portal:middle", middle_order),
                _boundary("exit", "portal:exit", exit_order),
            ),
        }
    )


def _two_section_certificate(
    *,
    first_slot_count: int = 4,
    second_slot_count: int = 4,
) -> CorridorCapacityCertificate:
    base = _certificate(first_slot_count)
    first = base.sections[0].model_copy(update={"exit_portal_id": "portal:middle"})
    second = CertifiedCorridorSection(
        section_id="section:tail",
        entry_portal_id="portal:middle",
        exit_portal_id="portal:exit",
        lane_slots=tuple(
            CertifiedLaneSlot(
                slot_id=f"tail:{index}",
                section_id="section:tail",
                layer="F.Cu",
                order_index=index,
                centerline_geometry_id=f"tail-centerline:{index}",
                maximum_track_width_mm=0.4,
                supported_clearance_domain_ids=("ordinary",),
            )
            for index in range(second_slot_count)
        ),
    )
    return CorridorCapacityCertificate.model_validate(
        {
            **base.model_dump(),
            "sections": (first, second),
        }
    )


def test_reversal_count_tracks_transitions_not_reversed_boundaries() -> None:
    result = allocate_bus_lanes(
        _two_section_bus(
            ("m3", "m2", "m1", "m0"),
            ("m3", "m2", "m1", "m0"),
        ),
        _two_section_certificate(),
    )

    assert result.success
    assert result.reversal_count == 1
    by_section = {
        section_id: tuple(
            assignment.member_id
            for assignment in sorted(
                (item for item in result.assignments if item.section_id == section_id),
                key=lambda item: item.order_index,
            )
        )
        for section_id in ("section:main", "section:tail")
    }
    assert by_section == {
        "section:main": ("m0", "m1", "m2", "m3"),
        "section:tail": ("m3", "m2", "m1", "m0"),
    }


def test_later_section_capacity_failure_precedes_all_state_work() -> None:
    result = allocate_bus_lanes(
        _two_section_bus(
            ("m0", "m1", "m2", "m3"),
            ("m0", "m1", "m2", "m3"),
        ),
        _two_section_certificate(second_slot_count=3),
    )

    assert not result.success
    assert result.failure_reason is BusAllocationFailureReason.CAPACITY_INSUFFICIENT
    assert result.state_count == 0


def test_allocation_fingerprint_binds_certificate_context() -> None:
    bus = _bus()
    certificate = _certificate(4)
    changed_certificate = certificate.model_copy(update={"certificate_id": "certificate:other"})

    first = allocate_bus_lanes(bus, certificate)
    changed = allocate_bus_lanes(bus, changed_certificate)

    assert first.success and changed.success
    assert first.assignments == changed.assignments
    assert first.certificate_fingerprint != changed.certificate_fingerprint
    assert first.allocation_fingerprint != changed.allocation_fingerprint


def test_zero_span_inactive_boundary_remains_a_typed_failure() -> None:
    base = _bus()
    entry = BusBoundary(
        boundary_id="entry",
        corridor_portal_id="portal:entry",
        orientation="forward",
        ordered_members=tuple(
            BoundaryMemberRef(
                member_id=f"m{index}",
                terminal_ids=(f"m{index}:sink", f"m{index}:source"),
            )
            for index in range(4)
        ),
    )
    exit_boundary = BusBoundary(
        boundary_id="exit",
        corridor_portal_id="portal:exit",
        orientation="forward",
        ordered_members=(),
        inactive_member_ids=("m0", "m1", "m2", "m3"),
    )
    bus = BusGroup.model_validate(
        {
            **base.model_dump(),
            "boundaries": (entry, exit_boundary),
        }
    )

    result = allocate_bus_lanes(bus, _certificate(4))

    assert not result.success
    assert result.failure_reason is BusAllocationFailureReason.TAP_OR_ACTIVATION_UNSUPPORTED
    assert result.normalized_boundary_orders[-1] == ()


def _swap_bus(*, reverse_member_input: bool = False) -> BusGroup:
    target = ("m0", "m2", "m1", "m3")
    base = _two_section_bus(target, target)
    members = tuple(reversed(base.members)) if reverse_member_input else base.members
    return BusGroup.model_validate(
        {
            **base.model_dump(),
            "members": members,
            "permutation_policy": BusPermutationPolicy(
                swap_windows=(
                    BusSwapWindow(
                        window_id="swap:main",
                        corridor_region_id="section:main",
                        allowed_adjacent_pairs=(("m1", "m2"),),
                        allowed_layers=("F.Cu",),
                        maximum_swaps=1,
                    ),
                ),
            ),
        }
    )


def _swap_certificate() -> CorridorCapacityCertificate:
    base = _two_section_certificate()
    first = base.sections[0].model_copy(update={"swap_window_ids": ("swap:main",)})
    return CorridorCapacityCertificate.model_validate(
        {**base.model_dump(), "sections": (first, base.sections[1])}
    )


def _transition_bus(via_policy: BusViaPolicy) -> BusGroup:
    order = ("m0", "m1", "m2", "m3")
    base = _two_section_bus(order, order)
    return BusGroup.model_validate(
        {
            **base.model_dump(),
            "layer_policy": BusLayerPolicy(
                allowed_layers=("F.Cu", "B.Cu"),
                preferred_layers=("F.Cu",),
                via_policy=via_policy,
            ),
        }
    )


def _transition_certificate(
    second_layers: tuple[Literal["F.Cu", "B.Cu"], ...],
) -> CorridorCapacityCertificate:
    base = _two_section_certificate(second_slot_count=len(second_layers))
    first = base.sections[0].model_copy(update={"transition_window_ids": ("transition:main",)})
    second = base.sections[1].model_copy(
        update={
            "lane_slots": tuple(
                slot.model_copy(update={"layer": layer})
                for slot, layer in zip(base.sections[1].lane_slots, second_layers, strict=True)
            )
        }
    )
    return CorridorCapacityCertificate.model_validate(
        {**base.model_dump(), "sections": (first, second)}
    )


def test_adjacent_inversion_succeeds_only_in_declared_certified_swap_window() -> None:
    result = allocate_bus_lanes(_swap_bus(), _swap_certificate())

    assert result.success
    assert result.swap_count == 1
    assert result.swaps[0].window_id == "swap:main"
    assert (result.swaps[0].first_member_id, result.swaps[0].second_member_id) == (
        "m1",
        "m2",
    )
    assert result.state_count == 3


def test_allowed_boundary_permutation_is_exact_and_typed() -> None:
    target = ("m2", "m0", "m3", "m1")
    base = _two_section_bus(target, target)
    bus = BusGroup.model_validate(
        {
            **base.model_dump(),
            "permutation_policy": BusPermutationPolicy(
                allowed_boundary_permutations=(("middle", target),)
            ),
        }
    )

    result = allocate_bus_lanes(bus, _two_section_certificate())

    assert result.success
    assert result.permutation_boundary_ids == ("middle",)
    assert result.swap_count == 0


def test_swap_planner_zero_and_one_less_state_budgets_are_typed() -> None:
    zero = allocate_bus_lanes(
        _swap_bus(),
        _swap_certificate(),
        budget=BusAllocationBudget(max_states=0),
    )
    one_less = allocate_bus_lanes(
        _swap_bus(),
        _swap_certificate(),
        budget=BusAllocationBudget(max_states=2),
    )

    assert zero.failure_reason is BusAllocationFailureReason.STATE_BUDGET
    assert zero.state_count == 0
    assert one_less.failure_reason is BusAllocationFailureReason.STATE_BUDGET
    assert one_less.state_count == 2


def test_independent_outlier_layer_transition_respects_via_count_and_spread() -> None:
    bus = _transition_bus(
        BusViaPolicy(
            mode="independent_bounded",
            maximum_vias_per_member=1,
            maximum_via_count_spread=1,
        )
    )
    result = allocate_bus_lanes(
        bus,
        _transition_certificate(("F.Cu", "B.Cu", "F.Cu", "F.Cu")),
    )

    assert result.success
    assert result.layer_transition_count == 1
    assert result.layer_transitions[0].member_id == "m1"
    assert result.layer_transitions[0].window_id == "transition:main"
    assert {item.member_id: item.via_count for item in result.via_counts} == {
        "m0": 0,
        "m1": 1,
        "m2": 0,
        "m3": 0,
    }


def test_independent_transition_rejects_via_count_spread_violation() -> None:
    bus = _transition_bus(
        BusViaPolicy(
            mode="independent_bounded",
            maximum_vias_per_member=1,
            maximum_via_count_spread=0,
        )
    )
    result = allocate_bus_lanes(
        bus,
        _transition_certificate(("F.Cu", "B.Cu", "F.Cu", "F.Cu")),
    )

    assert not result.success
    assert result.failure_reason is BusAllocationFailureReason.VIA_POLICY_INCOMPATIBLE


def test_synchronous_transition_changes_every_active_member() -> None:
    bus = _transition_bus(
        BusViaPolicy(
            mode="synchronous",
            transition_window_ids=("transition:main",),
            maximum_vias_per_member=1,
            maximum_via_count_spread=0,
        )
    )
    result = allocate_bus_lanes(
        bus,
        _transition_certificate(("B.Cu", "B.Cu", "B.Cu", "B.Cu")),
    )

    assert result.success
    assert result.layer_transition_count == 4
    assert {item.member_id for item in result.layer_transitions} == {
        "m0",
        "m1",
        "m2",
        "m3",
    }
    assert {item.via_count for item in result.via_counts} == {1}


def test_forbidden_via_policy_rejects_certified_layer_change() -> None:
    bus = _transition_bus(BusViaPolicy(mode="forbidden"))
    result = allocate_bus_lanes(
        bus,
        _transition_certificate(("B.Cu", "B.Cu", "B.Cu", "B.Cu")),
    )

    assert not result.success
    assert result.failure_reason is BusAllocationFailureReason.VIA_POLICY_INCOMPATIBLE


def test_r4_1b_swaps_are_deterministic_under_reversed_member_input() -> None:
    first = allocate_bus_lanes(_swap_bus(), _swap_certificate())
    repeated = allocate_bus_lanes(_swap_bus(reverse_member_input=True), _swap_certificate())

    assert first == repeated
    assert first.semantic_fingerprint() == repeated.semantic_fingerprint()


def test_late_source_activation_joins_only_following_section() -> None:
    base = _bus()
    entry = _boundary("entry", "portal:entry", ("m0", "m1", "m2"))
    middle = BusBoundary(
        boundary_id="middle",
        corridor_portal_id="portal:middle",
        orientation="forward",
        ordered_members=(
            *(BoundaryMemberRef(member_id=f"m{index}") for index in range(3)),
            BoundaryMemberRef(member_id="m3", terminal_ids=("m3:source",)),
        ),
    )
    exit_boundary = _boundary(
        "exit",
        "portal:exit",
        ("m0", "m1", "m2", "m3"),
    )
    bus = BusGroup.model_validate(
        {
            **base.model_dump(),
            "boundaries": (entry, middle, exit_boundary),
        }
    )

    result = allocate_bus_lanes(bus, _two_section_certificate())

    assert result.success
    assert result.activation_count == 1
    assert result.activations[0].member_id == "m3"
    assert result.activations[0].kind == "activate"
    assert result.activations[0].boundary_id == "middle"
    main_members = {
        item.member_id for item in result.assignments if item.section_id == "section:main"
    }
    tail_members = {
        item.member_id for item in result.assignments if item.section_id == "section:tail"
    }
    assert main_members == {"m0", "m1", "m2"}
    assert tail_members == {"m0", "m1", "m2", "m3"}
