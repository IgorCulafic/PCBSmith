from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

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
from pcbsmith.bus_lcs import BusLcsBoundaryMember
from pcbsmith.bus_lcs_cost_plan import (
    BusLcsCostBudget,
    BusLcsCostFailureReason,
    BusLcsCostPlanInput,
    BusLcsCostPlanResult,
    BusLcsCostPolicy,
    BusLcsMemberOutlierCapability,
    build_bus_lcs_cost_plan_input,
    plan_bus_lcs_cost,
)
from pcbsmith.kicad.bus_lcs_physical_realization import (
    bus_lcs_physical_profile_fingerprint,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

MEMBERS = ("a", "b", "c", "d")
PROFILE_FP = bus_lcs_physical_profile_fingerprint(DEFAULT_PCB_RULE_PROFILE)


def _member(member_id: str) -> BusMember:
    net_name = f"/{member_id.upper()}"
    return BusMember(
        member_id=member_id,
        net_name=net_name,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net_name,
                component_ref=f"U_{member_id}",
                pad_number="1",
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net_name,
                component_ref=f"J_{member_id}",
                pad_number="1",
                role="sink",
            ),
        ),
        width_mm=0.2,
    )


def _boundary(
    index: int,
    order: tuple[str, ...],
    *,
    terminal: str | None = None,
) -> BusBoundary:
    return BusBoundary(
        boundary_id=f"b{index}",
        corridor_portal_id=f"p{index}",
        orientation="forward",
        ordered_members=tuple(
            BoundaryMemberRef(
                member_id=member_id,
                terminal_ids=(() if terminal is None else (f"{member_id}:{terminal}",)),
            )
            for member_id in order
        ),
    )


def _bus(source: tuple[str, ...], target: tuple[str, ...]) -> BusGroup:
    return BusGroup(
        bus_id="cost-plan",
        members=tuple(_member(member_id) for member_id in reversed(source)),
        boundaries=(
            _boundary(0, source, terminal="source"),
            _boundary(1, source),
            _boundary(2, source),
            _boundary(3, source),
            _boundary(4, target, terminal="sink"),
        ),
        permutation_policy=BusPermutationPolicy(
            allowed_boundary_permutations=(("b4", target),) if source != target else ()
        ),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu", "B.Cu"),
            preferred_layers=("F.Cu",),
            via_policy=BusViaPolicy(
                mode="independent_bounded",
                maximum_vias_per_member=4,
                maximum_via_count_spread=4,
            ),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )


def _certificate(member_count: int) -> CorridorCapacityCertificate:
    sections = []
    for section_index, section_id in enumerate(("s0", "s1", "s2", "s3")):
        slots = []
        layers = ("F.Cu",) if section_id in {"s0", "s3"} else ("F.Cu", "B.Cu")
        for layer in layers:
            for lane_index in range(member_count):
                order_index = len(slots)
                slots.append(
                    CertifiedLaneSlot(
                        slot_id=f"slot:{section_id}:{layer}:{lane_index}",
                        section_id=section_id,
                        layer=layer,
                        order_index=order_index,
                        centerline_geometry_id=f"line:{section_id}:{layer}:{lane_index}",
                        maximum_track_width_mm=0.3,
                        supported_clearance_domain_ids=("ordinary", "sensitive"),
                    )
                )
        sections.append(
            CertifiedCorridorSection(
                section_id=section_id,
                entry_portal_id=f"p{section_index}",
                exit_portal_id=f"p{section_index + 1}",
                lane_slots=tuple(slots),
                transition_window_ids=(
                    ("window:source",)
                    if section_id == "s0"
                    else (("window:target",) if section_id == "s2" else ())
                ),
            )
        )
    return CorridorCapacityCertificate(
        certificate_id="cost-capacity",
        board_geometry_fingerprint="1" * 64,
        static_obstacle_fingerprint="2" * 64,
        rule_profile_fingerprint=PROFILE_FP,
        demand_fingerprint="3" * 64,
        corridor_graph_fingerprint="4" * 64,
        grid_mm=0.5,
        sections=tuple(sections),
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )


def _capability(
    member_id: str,
    *,
    cost: int = 10,
    vias: int = 2,
    source_window: str | None = "window:source",
    target_window: str | None = "window:target",
    domains: tuple[str, ...] = ("ordinary",),
) -> BusLcsMemberOutlierCapability:
    return BusLcsMemberOutlierCapability(
        member_id=member_id,
        assigned_outlier_layer="B.Cu",
        inner_section_ids=("s1", "s2"),
        source_transition_window_id=source_window,
        target_transition_window_id=target_window,
        source_pad_access_layers=("F.Cu",),
        target_pad_access_layers=("F.Cu",),
        source_transition_cost_units=cost // 2,
        target_transition_cost_units=cost - cost // 2,
        via_cost_units=0,
        physical_via_count=vias,
        required_clearance_domain_ids=domains,
        rule_profile_fingerprint=PROFILE_FP,
    )


def _ordered(order: tuple[str, ...]) -> tuple[BusLcsBoundaryMember, ...]:
    return tuple(BusLcsBoundaryMember(member_id=item, active=True) for item in order)


def _input(
    source: tuple[str, ...] = MEMBERS,
    target: tuple[str, ...] = MEMBERS,
    *,
    capabilities: tuple[BusLcsMemberOutlierCapability, ...] | None = None,
    certificate: CorridorCapacityCertificate | None = None,
    policy: BusLcsCostPolicy | None = None,
    max_dp_cells: int | None = None,
    max_candidates: int = 100_000,
    source_boundary: tuple[BusLcsBoundaryMember, ...] | None = None,
    target_boundary: tuple[BusLcsBoundaryMember, ...] | None = None,
) -> BusLcsCostPlanInput:
    bus = _bus(source, target)
    selected_capabilities = capabilities or tuple(_capability(item) for item in source)
    selected_certificate = certificate or _certificate(len(source))
    selected_policy = policy or BusLcsCostPolicy(
        base_layer="F.Cu",
        permitted_outlier_layers=("B.Cu",),
        maximum_vias_per_member=4,
        maximum_via_count_spread=4,
    )
    return build_bus_lcs_cost_plan_input(
        bus=bus,
        certificate=selected_certificate,
        rule_profile=DEFAULT_PCB_RULE_PROFILE,
        source_boundary=_ordered(source) if source_boundary is None else source_boundary,
        target_boundary=_ordered(target) if target_boundary is None else target_boundary,
        outlier_capabilities=selected_capabilities,
        policy=selected_policy,
        budget=BusLcsCostBudget(
            max_dp_cells=(len(source) * len(target) if max_dp_cells is None else max_dp_cells),
            max_candidates=max_candidates,
        ),
    )


def _stay_ids(result: BusLcsCostPlanResult) -> tuple[str, ...]:
    return tuple(item.member_id for item in result.stay_layer_members)


def _replace_slots(
    certificate: CorridorCapacityCertificate,
    *,
    section_ids: set[str],
    layer: str,
    keep: int | None = None,
    width: float | None = None,
    domains: tuple[str, ...] | None = None,
) -> CorridorCapacityCertificate:
    sections = []
    for section in certificate.sections:
        slots = list(section.lane_slots)
        if section.section_id in section_ids:
            retained = 0
            changed = []
            for slot in slots:
                if slot.layer != layer:
                    changed.append(slot)
                    continue
                if keep is not None and retained >= keep:
                    continue
                retained += 1
                changed.append(
                    slot.model_copy(
                        update={
                            "maximum_track_width_mm": (
                                slot.maximum_track_width_mm if width is None else width
                            ),
                            "supported_clearance_domain_ids": (
                                slot.supported_clearance_domain_ids if domains is None else domains
                            ),
                        }
                    )
                )
            slots = changed
        slots = [slot.model_copy(update={"order_index": index}) for index, slot in enumerate(slots)]
        sections.append(section.model_copy(update={"lane_slots": tuple(slots)}))
    return certificate.model_copy(update={"sections": tuple(sections)})


def test_identical_four_members_plan_only_stationary_base_blocks() -> None:
    result = plan_bus_lcs_cost(_input())

    assert result.success
    assert _stay_ids(result) == MEMBERS
    assert result.outlier_plans == ()
    assert result.dp_cells_evaluated == 16
    assert result.total_outlier_cost_units == 0
    assert all(item.via_count == 0 for item in result.via_counts)
    assert len(result.lane_claims) == 4
    assert result.authority_scope == "cost-aware-layer-planning-only"


def test_one_disordered_member_gets_target_ordered_bound_excursion() -> None:
    result = plan_bus_lcs_cost(_input(target=("a", "c", "d", "b")))

    assert result.success
    assert _stay_ids(result) == ("a", "c", "d")
    assert tuple(item.member_id for item in result.outlier_plans) == ("b",)
    outlier = result.outlier_plans[0]
    assert outlier.source_bracketing_section_id == "s0"
    assert outlier.target_bracketing_section_id == "s2"
    assert outlier.inner_section_ids == ("s1", "s2")


def test_lane_claims_use_each_section_entry_order_not_final_target_order() -> None:
    target = ("a", "c", "d", "b")
    result = plan_bus_lcs_cost(_input(target=target))

    assert result.success
    for section_id in ("s0", "s3"):
        claim = next(item for item in result.lane_claims if item.section_id == section_id)
        assert claim.member_ids == MEMBERS
        assert claim.member_ids != target


def test_physical_cost_overrides_lexical_then_exact_lexical_tie_wins() -> None:
    source = ("a", "b")
    target = ("b", "a")
    cost_result = plan_bus_lcs_cost(
        _input(
            source,
            target,
            capabilities=(_capability("a", cost=1), _capability("b", cost=9)),
        )
    )
    tied = plan_bus_lcs_cost(
        _input(
            source,
            target,
            capabilities=(_capability("a", cost=5), _capability("b", cost=5)),
        )
    )

    assert _stay_ids(cost_result) == ("b",)
    assert tuple(item.member_id for item in cost_result.outlier_plans) == ("a",)
    assert _stay_ids(tied) == ("a",)


def test_lexical_ids_never_replace_physical_order() -> None:
    order = ("z", "a", "m")
    result = plan_bus_lcs_cost(_input(order, order))

    assert _stay_ids(result) == order
    assert tuple(item.source_index for item in result.stay_layer_members) == (0, 1, 2)


def test_member_id_tuple_wins_tie_before_non_alphabetic_physical_indices() -> None:
    source = ("z", "a")
    target = tuple(reversed(source))

    result = plan_bus_lcs_cost(_input(source, target))

    assert _stay_ids(result) == ("a",)
    assert result.stay_layer_members[0].source_index == 1
    assert result.stay_layer_members[0].target_index == 0


def test_missing_active_member_capability_fails_before_any_work() -> None:
    result = plan_bus_lcs_cost(_input(("a", "b"), ("a", "b"), capabilities=(_capability("a"),)))

    assert result.failure_reason is BusLcsCostFailureReason.MEMBER_BINDING
    assert result.dp_cells_evaluated == 0
    assert result.candidates_evaluated == 0


def test_stationary_base_member_must_have_supported_required_domain() -> None:
    capabilities = (
        _capability("a", domains=("high-voltage",)),
        _capability("b"),
    )

    result = plan_bus_lcs_cost(_input(("a", "b"), ("a", "b"), capabilities=capabilities))

    assert result.failure_reason is BusLcsCostFailureReason.LANE_CAPABILITY


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("source_window", BusLcsCostFailureReason.MISSING_SOURCE_TRANSITION),
        ("target_window", BusLcsCostFailureReason.MISSING_TARGET_TRANSITION),
    ],
)
def test_missing_transition_capability_cannot_be_silently_assigned(
    field: str,
    reason: BusLcsCostFailureReason,
) -> None:
    source = ("a", "b")
    target = ("b", "a")
    updates = {field: None}
    capabilities = tuple(_capability(item, **updates) for item in source)

    result = plan_bus_lcs_cost(_input(source, target, capabilities=capabilities))

    assert not result.success
    assert result.failure_reason is reason
    assert result.outlier_plans == ()


@pytest.mark.parametrize(
    ("width", "domains"),
    [(0.1, None), (None, ("sensitive",))],
)
def test_slot_count_does_not_override_width_or_domain_capability(
    width: float | None,
    domains: tuple[str, ...] | None,
) -> None:
    source = ("a", "b")
    target = ("b", "a")
    certificate = _replace_slots(
        _certificate(2),
        section_ids={"s1", "s2"},
        layer="B.Cu",
        width=width,
        domains=domains,
    )
    capabilities = tuple(
        _capability(item, domains=("ordinary",) if domains is not None else ("ordinary",))
        for item in source
    )

    result = plan_bus_lcs_cost(
        _input(source, target, certificate=certificate, capabilities=capabilities)
    )

    assert result.failure_reason is BusLcsCostFailureReason.LANE_CAPABILITY


@pytest.mark.parametrize("layer", ["F.Cu", "B.Cu"])
def test_one_less_base_and_outlier_layer_capacity_fail_independently(layer: str) -> None:
    if layer == "F.Cu":
        source = target = ("a", "b")
        sections = {"s0", "s1", "s2", "s3"}
    else:
        source = ("a", "b")
        target = ("b", "a")
        sections = {"s1", "s2"}
    certificate = _replace_slots(
        _certificate(2), section_ids=sections, layer=layer, keep=0 if layer == "B.Cu" else 1
    )

    result = plan_bus_lcs_cost(_input(source, target, certificate=certificate))

    assert result.failure_reason is BusLcsCostFailureReason.LANE_CAPACITY


@pytest.mark.parametrize(
    "policy_update",
    [{"maximum_vias_per_member": 1}, {"maximum_via_count_spread": 1}],
)
def test_per_member_via_and_spread_limits_fail_independently(
    policy_update: dict[str, int],
) -> None:
    policy = BusLcsCostPolicy(
        base_layer="F.Cu",
        permitted_outlier_layers=("B.Cu",),
        maximum_vias_per_member=4,
        maximum_via_count_spread=4,
    ).model_copy(update=policy_update)

    result = plan_bus_lcs_cost(_input(("a", "b"), ("b", "a"), policy=policy))

    assert result.failure_reason is BusLcsCostFailureReason.VIA_POLICY


@pytest.mark.parametrize(
    "policy_update",
    [{"minimum_stay_count": 2}, {"minimum_stay_fraction": 1.0}],
)
def test_minimum_stay_count_and_fraction_are_both_enforced(
    policy_update: dict[str, int | float],
) -> None:
    policy = BusLcsCostPolicy(
        base_layer="F.Cu",
        permitted_outlier_layers=("B.Cu",),
        maximum_vias_per_member=4,
        maximum_via_count_spread=4,
    ).model_copy(update=policy_update)

    result = plan_bus_lcs_cost(_input(("a", "b"), ("b", "a"), policy=policy))

    assert result.failure_reason is BusLcsCostFailureReason.MINIMUM_STAY
    assert result.stay_count == 1
    assert result.stay_fraction == 0.5


def test_zero_and_one_less_dp_and_candidate_budgets_are_exact() -> None:
    zero_dp = plan_bus_lcs_cost(_input(("a", "b"), ("b", "a"), max_dp_cells=0))
    one_less_dp = plan_bus_lcs_cost(_input(("a", "b"), ("b", "a"), max_dp_cells=3))
    baseline = plan_bus_lcs_cost(_input(("a", "b"), ("b", "a")))
    zero_candidate = plan_bus_lcs_cost(_input(("a", "b"), ("b", "a"), max_candidates=0))
    one_less_candidate = plan_bus_lcs_cost(
        _input(
            ("a", "b"),
            ("b", "a"),
            max_candidates=baseline.candidates_evaluated - 1,
        )
    )

    assert zero_dp.failure_reason is BusLcsCostFailureReason.DP_BUDGET
    assert zero_dp.dp_cells_evaluated == 0
    assert zero_dp.candidates_evaluated == 0
    assert one_less_dp.dp_cells_evaluated == 3
    assert zero_candidate.failure_reason is BusLcsCostFailureReason.CANDIDATE_BUDGET
    assert zero_candidate.candidates_evaluated == 0
    assert one_less_candidate.failure_reason is BusLcsCostFailureReason.CANDIDATE_BUDGET
    assert one_less_candidate.candidates_evaluated == baseline.candidates_evaluated - 1


def test_member_and_activity_mismatch_do_no_work() -> None:
    member_mismatch = plan_bus_lcs_cost(
        _input(
            ("a", "b"),
            ("a", "b"),
            target_boundary=_ordered(("a", "c")),
        )
    )
    activity_mismatch = plan_bus_lcs_cost(
        _input(
            ("a", "b"),
            ("a", "b"),
            target_boundary=(
                BusLcsBoundaryMember(member_id="a", active=True),
                BusLcsBoundaryMember(member_id="b", active=False),
            ),
        )
    )

    assert member_mismatch.failure_reason is BusLcsCostFailureReason.MEMBER_SET_MISMATCH
    assert activity_mismatch.failure_reason is BusLcsCostFailureReason.ACTIVITY_MISMATCH
    assert member_mismatch.dp_cells_evaluated == activity_mismatch.dp_cells_evaluated == 0
    assert member_mismatch.candidates_evaluated == activity_mismatch.candidates_evaluated == 0


def test_reversed_set_like_capabilities_are_deterministic() -> None:
    source = ("a", "b")
    target = ("b", "a")
    capabilities = tuple(_capability(item) for item in source)
    forward = plan_bus_lcs_cost(_input(source, target, capabilities=capabilities))
    reverse = plan_bus_lcs_cost(_input(source, target, capabilities=tuple(reversed(capabilities))))

    assert forward.semantic_json() == reverse.semantic_json()
    assert forward.plan_fingerprint == reverse.plan_fingerprint


def test_json_replay_tamper_and_caller_immutability() -> None:
    plan_input = _input(("a", "b"), ("b", "a"))
    before = plan_input.model_dump_json()
    result = plan_bus_lcs_cost(plan_input)
    restored = BusLcsCostPlanResult.model_validate_json(result.model_dump_json())

    assert restored == result
    assert plan_input.model_dump_json() == before
    payload = json.loads(result.model_dump_json())
    payload["total_outlier_cost_units"] += 1
    with pytest.raises(ValidationError):
        BusLcsCostPlanResult.model_validate(payload)

    input_payload = json.loads(plan_input.model_dump_json())
    input_payload["bus_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError):
        BusLcsCostPlanInput.model_validate(input_payload)
