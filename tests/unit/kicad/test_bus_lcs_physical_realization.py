from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from pcbsmith.bus_allocator import BusLaneAllocationResult, allocate_bus_lanes
from pcbsmith.bus_geometry import (
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
from pcbsmith.bus_lcs_outliers import BusLcsOutlierPlanInput, plan_bus_lcs_outliers
from pcbsmith.kicad.bus_integration import (
    CertifiedBusMemberPrefix,
    CertifiedBusPigtail,
    compose_member_route_prefix,
)
from pcbsmith.kicad.bus_lcs_physical_realization import (
    BusLcsOutlierLayerBinding,
    BusLcsPhysicalBudget,
    BusLcsPhysicalFailureReason,
    BusLcsPhysicalPolicy,
    BusLcsPhysicalResult,
    bus_lcs_physical_profile_fingerprint,
    validate_bus_lcs_physical_realization,
)
from pcbsmith.kicad.bus_transition import BusTransitionBudget
from pcbsmith.kicad.bus_transition_replay import (
    BusTransitionReplayResult,
    generate_replay_bound_bus_transition_vias,
)
from pcbsmith.kicad.negotiated_resources import OccupancyLedger
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

KEEP_IN = ((0, 0), (12, 0), (12, 8), (0, 8))
MEMBER_IDS = ("z", "a", "m")


@dataclass(frozen=True)
class _Fixture:
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    registry: CertifiedLaneGeometryRegistry
    transition: BusTransitionReplayResult
    prefixes: tuple[CertifiedBusMemberPrefix, ...]
    policy: BusLcsPhysicalPolicy


def _member(member_id: str) -> BusMember:
    net = f"/{member_id.upper()}"
    return BusMember(
        member_id=member_id,
        net_name=net,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net,
                component_ref=f"U_{member_id}",
                pad_number="1",
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net,
                component_ref=f"J_{member_id}",
                pad_number="1",
                role="sink",
            ),
        ),
        width_mm=0.2,
    )


def _boundary(
    boundary_id: str,
    portal_id: str,
    order: tuple[str, ...],
    *,
    terminal_role: str | None = None,
) -> BusBoundary:
    return BusBoundary(
        boundary_id=boundary_id,
        corridor_portal_id=portal_id,
        orientation="forward",
        ordered_members=tuple(
            BoundaryMemberRef(
                member_id=member_id,
                terminal_ids=(() if terminal_role is None else (f"{member_id}:{terminal_role}",)),
            )
            for member_id in order
        ),
    )


def _fixture(
    *,
    outlier: bool = True,
    outlier_member: str = "m",
    source_order: tuple[str, ...] = MEMBER_IDS,
    target_order: tuple[str, ...] | None = None,
) -> _Fixture:
    members = tuple(_member(member_id) for member_id in MEMBER_IDS)
    target = (
        (("z", "m", "a") if target_order is None else target_order) if outlier else source_order
    )
    bus = BusGroup(
        bus_id="lcs-physical",
        members=tuple(reversed(members)),
        boundaries=(
            _boundary("b0", "p0", source_order, terminal_role="source"),
            _boundary("b1", "p1", source_order),
            _boundary("b2", "p2", source_order),
            _boundary("b3", "p3", source_order),
            _boundary("b4", "p4", target, terminal_role="sink"),
        ),
        permutation_policy=BusPermutationPolicy(
            allowed_boundary_permutations=(("b4", target),) if outlier else ()
        ),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu", "B.Cu"),
            preferred_layers=("F.Cu",),
            via_policy=BusViaPolicy(
                mode="independent_bounded",
                maximum_vias_per_member=2,
                maximum_via_count_spread=2,
            ),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )
    layers = {
        section: tuple(
            "B.Cu"
            if outlier and member_id == outlier_member and section in {"s1", "s2"}
            else "F.Cu"
            for member_id in MEMBER_IDS
        )
        for section in ("s0", "s1", "s2", "s3")
    }
    portals = ("p0", "p1", "p2", "p3", "p4")
    sections = []
    for section_index, section_id in enumerate(("s0", "s1", "s2", "s3")):
        slot_member_order = source_order
        sections.append(
            CertifiedCorridorSection(
                section_id=section_id,
                entry_portal_id=portals[section_index],
                exit_portal_id=portals[section_index + 1],
                lane_slots=tuple(
                    CertifiedLaneSlot(
                        slot_id=f"slot:{section_id}:{member_id}",
                        section_id=section_id,
                        layer=layers[section_id][MEMBER_IDS.index(member_id)],
                        order_index=member_index,
                        centerline_geometry_id=f"line:{section_id}:{member_id}",
                        maximum_track_width_mm=0.3,
                        supported_clearance_domain_ids=("ordinary", "sensitive"),
                    )
                    for member_index, member_id in enumerate(slot_member_order)
                ),
                transition_window_ids=(
                    ("window:source",)
                    if section_id == "s0" and outlier
                    else (("window:target",) if section_id == "s2" and outlier else ())
                ),
            )
        )
    certificate = CorridorCapacityCertificate(
        certificate_id="lcs-capacity",
        board_geometry_fingerprint="1" * 64,
        static_obstacle_fingerprint="2" * 64,
        rule_profile_fingerprint=bus_lcs_physical_profile_fingerprint(DEFAULT_PCB_RULE_PROFILE),
        demand_fingerprint="4" * 64,
        corridor_graph_fingerprint="5" * 64,
        grid_mm=0.5,
        sections=tuple(sections),
        reserved_demand_ids=tuple(f"demand:{item}" for item in reversed(MEMBER_IDS)),
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    assert allocation.layer_transition_count == (2 if outlier else 0)
    geometries = []
    x_points = (1, 3, 5, 7, 9)
    keep_in_fp = certified_keep_in_fingerprint(certificate.grid_mm, KEEP_IN)
    for section_index, section_id in enumerate(("s0", "s1", "s2", "s3")):
        for member_index, member_id in enumerate(MEMBER_IDS):
            y = 2 + member_index * 2
            geometries.append(
                CertifiedLaneGeometry(
                    centerline_geometry_id=f"line:{section_id}:{member_id}",
                    certificate_fingerprint=certificate.semantic_fingerprint(),
                    section_id=section_id,
                    layer=layers[section_id][member_index],
                    track_width_mm=0.2,
                    grid_mm=certificate.grid_mm,
                    entry_portal_id=portals[section_index],
                    exit_portal_id=portals[section_index + 1],
                    entry_portal_point=(x_points[section_index], y),
                    exit_portal_point=(x_points[section_index + 1], y),
                    points=(
                        (x_points[section_index], y),
                        (x_points[section_index + 1], y),
                    ),
                    keep_in_polygon=KEEP_IN,
                    keep_in_fingerprint=keep_in_fp,
                )
            )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=tuple(reversed(geometries)),
    )
    transition = generate_replay_bound_bus_transition_vias(
        bus,
        certificate,
        allocation,
        registry,
        OccupancyLedger(),
        BusTransitionBudget(max_members=1 if outlier else 0, max_events=2 if outlier else 0),
    )
    assert transition.generation_result.success, transition.generation_result
    realization = realize_certified_trunk_subset(
        bus,
        certificate,
        allocation,
        registry,
        tuple(sorted(set(MEMBER_IDS) - {outlier_member})) if outlier else tuple(sorted(MEMBER_IDS)),
    )
    prefixes = []
    for member_index, member_id in enumerate(MEMBER_IDS):
        member = next(item for item in bus.members if item.member_id == member_id)
        y = 2 + member_index * 2
        pigtails = (
            CertifiedBusPigtail(
                pigtail_id=f"pigtail:{member_id}:source",
                bus_fingerprint=bus.semantic_fingerprint(),
                certificate_fingerprint=certificate.semantic_fingerprint(),
                allocation_fingerprint=allocation.allocation_fingerprint,
                geometry_registry_fingerprint=registry.semantic_fingerprint(),
                member_id=member_id,
                net_name=member.net_name,
                terminal_id=f"{member_id}:source",
                boundary_id="b0",
                assigned_geometry_id=f"line:s0:{member_id}",
                portal_kind="entry",
                physical_pad_source_id=f"pad:{member_id}:source",
                grid_mm=certificate.grid_mm,
                layer="F.Cu",
                pad_anchor_point=(0, y),
                portal_point=(1, y),
                points=((0, y), (1, y)),
            ),
            CertifiedBusPigtail(
                pigtail_id=f"pigtail:{member_id}:sink",
                bus_fingerprint=bus.semantic_fingerprint(),
                certificate_fingerprint=certificate.semantic_fingerprint(),
                allocation_fingerprint=allocation.allocation_fingerprint,
                geometry_registry_fingerprint=registry.semantic_fingerprint(),
                member_id=member_id,
                net_name=member.net_name,
                terminal_id=f"{member_id}:sink",
                boundary_id="b4",
                assigned_geometry_id=f"line:s3:{member_id}",
                portal_kind="exit",
                physical_pad_source_id=f"pad:{member_id}:sink",
                grid_mm=certificate.grid_mm,
                layer="F.Cu",
                pad_anchor_point=(10, y),
                portal_point=(9, y),
                points=((10, y), (9, y)),
            ),
        )
        carriers = tuple(
            item for item in transition.generation_result.carriers if item.member_id == member_id
        )
        prefixes.append(
            compose_member_route_prefix(
                bus,
                certificate,
                allocation,
                registry,
                None if carriers else realization,
                member_id,
                pigtails,
                carriers,
                {
                    f"{member_id}:source": f"pad:{member_id}:source",
                    f"{member_id}:sink": f"pad:{member_id}:sink",
                },
            )
        )
    policy = BusLcsPhysicalPolicy(
        base_layer="F.Cu",
        outlier_layers=("B.Cu",),
        member_clearance_domains=tuple(
            (item, ("ordinary", "sensitive")) for item in reversed(MEMBER_IDS)
        ),
        outlier_bindings=(
            (
                BusLcsOutlierLayerBinding(
                    member_id=outlier_member,
                    inner_section_ids=("s1", "s2"),
                    source_transition_window_id="window:source",
                    target_transition_window_id="window:target",
                ),
            )
            if outlier
            else ()
        ),
        maximum_vias_per_member=2 if outlier else 0,
        maximum_via_count_spread=2 if outlier else 0,
    )
    return _Fixture(
        bus,
        certificate,
        allocation,
        registry,
        transition,
        tuple(reversed(prefixes)),
        policy,
    )


def _result(
    fixture: _Fixture,
    *,
    source: tuple[str, ...] = MEMBER_IDS,
    target: tuple[str, ...] = ("z", "m", "a"),
    policy: BusLcsPhysicalPolicy | None = None,
    budget: int = 3,
    prefixes: tuple[CertifiedBusMemberPrefix, ...] | None = None,
    certificate: CorridorCapacityCertificate | None = None,
    transition: BusTransitionReplayResult | None = None,
    rule_profile=DEFAULT_PCB_RULE_PROFILE,
):
    sequence = plan_bus_lcs_outliers(
        BusLcsOutlierPlanInput(
            source_member_order=source,
            target_member_order=target,
            max_dp_cells=len(source) * len(target),
        )
    )
    return validate_bus_lcs_physical_realization(
        sequence,
        fixture.bus,
        fixture.certificate if certificate is None else certificate,
        fixture.allocation,
        fixture.transition if transition is None else transition,
        fixture.prefixes if prefixes is None else prefixes,
        rule_profile,
        fixture.policy if policy is None else policy,
        BusLcsPhysicalBudget(max_member_validations=budget),
    )


def test_one_outlier_retains_both_carriers_and_exact_member_authority() -> None:
    fixture = _fixture()
    result = _result(fixture)

    assert result.success
    assert result.member_validation_count == 3
    assert tuple(item.member_id for item in result.member_authorities) == ("z", "m", "a")
    outlier = result.member_authorities[1]
    assert not outlier.stationary
    assert outlier.via_count == 2
    assert len(outlier.transition_events) == len(outlier.transition_carrier_fingerprints) == 2
    assert result.authority_scope == "physical-realization-only"


def test_identical_lexical_nonlexical_order_has_zero_outliers_and_vias() -> None:
    fixture = _fixture(outlier=False)
    result = _result(fixture, target=MEMBER_IDS)

    assert result.success
    assert tuple(item.member_id for item in result.member_authorities) == MEMBER_IDS
    assert all(item.stationary and item.via_count == 0 for item in result.member_authorities)


def test_equal_lcs_choice_is_bound_to_existing_deterministic_selection() -> None:
    fixture = _fixture()
    result = _result(fixture)

    assert tuple(
        item.member_id for item in result.realization_input.sequence_plan.stationary_members
    ) == (
        "z",
        "a",
    )
    assert tuple(
        item.member_id for item in result.realization_input.sequence_plan.outlier_members
    ) == ("m",)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("source_transition_window_id", BusLcsPhysicalFailureReason.MISSING_SOURCE_TRANSITION),
        ("target_transition_window_id", BusLcsPhysicalFailureReason.MISSING_TARGET_TRANSITION),
    ],
)
def test_missing_source_and_target_transition_fail_independently(
    field: str, reason: object
) -> None:
    fixture = _fixture()
    binding = fixture.policy.outlier_bindings[0].model_copy(update={field: "window:missing"})
    policy = fixture.policy.model_copy(update={"outlier_bindings": (binding,)})

    result = _result(fixture, policy=policy)

    assert not result.success
    assert result.failure_reason is reason


def test_width_domain_capability_fails_even_with_enough_slots() -> None:
    fixture = _fixture()
    domains = tuple(
        (member_id, (("high-voltage",) if member_id == "z" else values))
        for member_id, values in fixture.policy.member_clearance_domains
    )
    policy = fixture.policy.model_copy(update={"member_clearance_domains": domains})

    result = _result(fixture, policy=policy)

    assert not result.success
    assert result.failure_reason is BusLcsPhysicalFailureReason.LANE_CAPABILITY


@pytest.mark.parametrize(
    ("update", "reason"),
    [
        ({"maximum_vias_per_member": 1}, BusLcsPhysicalFailureReason.VIA_POLICY),
        ({"maximum_via_count_spread": 1}, BusLcsPhysicalFailureReason.VIA_POLICY),
    ],
)
def test_per_member_via_limit_and_spread_fail_independently(
    update: dict[str, int], reason: object
) -> None:
    fixture = _fixture()

    result = _result(fixture, policy=fixture.policy.model_copy(update=update))

    assert not result.success
    assert result.failure_reason is reason


def test_zero_and_one_less_validation_budget_stop_before_excess_work() -> None:
    fixture = _fixture()
    zero = _result(fixture, budget=0)
    one_less = _result(fixture, budget=2)

    assert zero.failure_reason is BusLcsPhysicalFailureReason.BUDGET
    assert zero.member_validation_count == 0
    assert zero.member_authorities == ()
    assert one_less.failure_reason is BusLcsPhysicalFailureReason.BUDGET
    assert one_less.member_validation_count == 2
    assert len(one_less.member_authorities) == 2


def test_member_order_mismatch_fails_before_validation_work() -> None:
    fixture = _fixture()
    result = _result(fixture, source=("a", "z", "m"))

    assert result.failure_reason is BusLcsPhysicalFailureReason.MEMBER_BINDING
    assert result.member_validation_count == 0


def test_wrong_profile_and_certificate_profile_binding_fail_before_work() -> None:
    fixture = _fixture()
    wrong_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(update={"profile_id": "wrong-profile"})
    wrong_certificate = fixture.certificate.model_copy(
        update={"rule_profile_fingerprint": "0" * 64}
    )

    profile_result = _result(fixture, rule_profile=wrong_profile)
    certificate_result = _result(fixture, certificate=wrong_certificate)

    assert profile_result.failure_reason is BusLcsPhysicalFailureReason.AUTHORITY_BINDING
    assert profile_result.member_validation_count == 0
    assert certificate_result.failure_reason is BusLcsPhysicalFailureReason.AUTHORITY_BINDING
    assert certificate_result.member_validation_count == 0


def test_prefix_tamper_is_rejected_and_input_order_is_set_like() -> None:
    fixture = _fixture()
    reversed_result = _result(fixture, prefixes=tuple(reversed(fixture.prefixes)))
    assert reversed_result.success
    assert reversed_result.semantic_json() == _result(fixture).semantic_json()

    payload = json.loads(fixture.prefixes[0].model_dump_json())
    payload["prefix_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError):
        CertifiedBusMemberPrefix.model_validate(payload)


def test_json_replay_tamper_and_input_immutability() -> None:
    fixture = _fixture()
    before = tuple(item.model_dump_json() for item in fixture.prefixes)
    result = _result(fixture)
    restored = BusLcsPhysicalResult.model_validate_json(result.model_dump_json())

    assert restored == result
    assert tuple(item.model_dump_json() for item in fixture.prefixes) == before
    payload = json.loads(result.model_dump_json())
    payload["member_validation_count"] = 0
    with pytest.raises(ValidationError):
        BusLcsPhysicalResult.model_validate(payload)


def test_transition_tamper_is_rejected_by_nested_replay() -> None:
    fixture = _fixture()
    payload = json.loads(fixture.transition.model_dump_json())
    payload["generation_result"]["carriers"][0]["window_id"] = "window:wrong"

    with pytest.raises(ValidationError):
        BusTransitionReplayResult.model_validate(payload)


def test_transition_profile_tamper_is_rejected_by_nested_replay() -> None:
    fixture = _fixture()
    payload = json.loads(fixture.transition.model_dump_json())
    payload["replay_input"]["profile"]["profile_id"] = "wrong-profile"

    with pytest.raises(ValidationError):
        BusTransitionReplayResult.model_validate(payload)
