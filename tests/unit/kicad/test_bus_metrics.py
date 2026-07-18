from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from pcbsmith.bus_allocator import (
    BusActivationEvent,
    BusLaneAllocationResult,
    BusSwapEvent,
    allocate_bus_lanes,
)
from pcbsmith.bus_geometry import (
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
    certified_keep_in_fingerprint,
    realize_certified_trunks,
)
from pcbsmith.bus_ir import (
    BoundaryMemberRef,
    BusBoundary,
    BusCoherencePolicy,
    BusCouplingBudget,
    BusGroup,
    BusLayerPolicy,
    BusMember,
    BusPermutationPolicy,
    BusTerminalRef,
    BusTimingBudget,
    BusViaPolicy,
    CertifiedCorridorSection,
    CertifiedLaneSlot,
    ConstraintAuthority,
    CorridorCapacityCertificate,
)
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.astar_router import RouteResult
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.bus_integration import (
    CertifiedBusMemberPrefix,
    CertifiedBusPigtail,
    compose_member_route_prefix,
)
from pcbsmith.kicad.bus_metrics import (
    BusMetricsDisposition,
    BusMetricsReport,
    BusMetricValidationContext,
    MetricAuthority,
    PropagationDelayModel,
    RuleDisposition,
    _length,
    _measure_order,
    measure_bus_route_bundle,
)
from pcbsmith.kicad.bus_transaction import BusRouteBundle
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import NetResourceClaims
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def _authority() -> ConstraintAuthority:
    condition = "fixture-applicability"
    return ConstraintAuthority(
        enforcement="hard",
        evidence=(
            EvidenceRef(
                kind="test",
                title="fixture",
                locator="line:1",
                source_id="fixture-evidence",
                local_sha256="a" * 64,
                source_status="pinned",
                locator_status="text_verified",
                applicability_status="confirmed",
                required_conditions=(condition,),
            ),
        ),
        applicability_conditions=(condition,),
        validation_method_ids=("exact-metric-v1",),
    )


def _member(member_id: str, net: str) -> BusMember:
    return BusMember(
        member_id=member_id,
        net_name=net,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net,
                component_ref=f"{member_id}S",
                pad_number="1",
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net,
                component_ref=f"{member_id}T",
                pad_number="1",
                role="sink",
            ),
        ),
        width_mm=0.4,
    )


def _fixture(
    *,
    timing_budget: BusTimingBudget | None = None,
    coherence_policy: BusCoherencePolicy | None = None,
    second_source_anchor: tuple[int, int] | None = None,
    propagation_model: PropagationDelayModel | None = None,
    lane_points: tuple[tuple[tuple[int, int], ...], ...] | None = None,
    member_ids: tuple[str, ...] | None = None,
) -> tuple[
    BusRouteBundle,
    CorridorCapacityCertificate,
    CertifiedLaneGeometryRegistry,
    dict[str, CertifiedBusMemberPrefix],
    BusMetricValidationContext,
]:
    points_by_member = lane_points or (
        ((8, 3), (22, 3)),
        ((8, 12), (22, 12)),
    )
    fixed_member_ids = member_ids or tuple(f"data{index}" for index in range(len(points_by_member)))
    if len(fixed_member_ids) != len(points_by_member):
        raise ValueError("member IDs must exactly cover lane geometry")
    members = tuple(
        _member(member_id, ("/A", "/B")[index] if index < 2 else f"/N{index}")
        for index, member_id in enumerate(fixed_member_ids)
    )
    boundaries = tuple(
        BusBoundary(
            boundary_id=name,
            corridor_portal_id=f"portal:{name}",
            orientation="forward",
            ordered_members=tuple(
                BoundaryMemberRef(
                    member_id=member.member_id,
                    terminal_ids=(f"{member.member_id}:{'source' if name == 'entry' else 'sink'}",),
                )
                for member in members
            ),
        )
        for name in ("entry", "exit")
    )
    bus = BusGroup(
        bus_id="metrics-fixture",
        members=members,
        boundaries=boundaries,
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",), via_policy=BusViaPolicy(mode="forbidden")
        ),
        timing_budget=timing_budget,
        coherence_policy=coherence_policy,
        coupling_budget=BusCouplingBudget(
            adjacent_member_clearance_mm=8.6,
            reference_structure_id="reference",
            stackup_id="stackup",
            authority=_authority(),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )
    certificate = CorridorCapacityCertificate(
        certificate_id="metrics-certificate",
        board_geometry_fingerprint="1" * 64,
        static_obstacle_fingerprint="2" * 64,
        rule_profile_fingerprint="3" * 64,
        demand_fingerprint="4" * 64,
        corridor_graph_fingerprint="5" * 64,
        grid_mm=1.0,
        sections=(
            CertifiedCorridorSection(
                section_id="trunk",
                entry_portal_id="portal:entry",
                exit_portal_id="portal:exit",
                lane_slots=tuple(
                    CertifiedLaneSlot(
                        slot_id=f"slot:{index}",
                        section_id="trunk",
                        layer="F.Cu",
                        order_index=index,
                        centerline_geometry_id=f"centerline:{index}",
                        maximum_track_width_mm=0.4,
                        supported_clearance_domain_ids=("ordinary",),
                    )
                    for index in range(len(members))
                ),
            ),
        ),
        exact_capacity_proof_id="fixture-proof",
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success

    keep_in = ((0, 0), (40, 0), (40, 20), (0, 20))
    keep_in_fingerprint = certified_keep_in_fingerprint(1.0, keep_in)
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=1.0,
        geometries=tuple(
            CertifiedLaneGeometry(
                centerline_geometry_id=f"centerline:{index}",
                certificate_fingerprint=certificate.semantic_fingerprint(),
                section_id="trunk",
                layer="F.Cu",
                track_width_mm=0.4,
                grid_mm=1.0,
                entry_portal_id="portal:entry",
                exit_portal_id="portal:exit",
                entry_portal_point=points[0],
                exit_portal_point=points[-1],
                points=points,
                keep_in_polygon=keep_in,
                keep_in_fingerprint=keep_in_fingerprint,
            )
            for index, points in enumerate(points_by_member)
        ),
    )
    realization = realize_certified_trunks(bus, certificate, allocation, registry)
    prefixes: dict[str, CertifiedBusMemberPrefix] = {}
    routes: list[NegotiatedGridRoute] = []
    for index, member in enumerate(members):
        points = points_by_member[index]
        source_anchor = (points[0][0] - 2, points[0][1])
        if index == 1 and second_source_anchor is not None:
            source_anchor = second_source_anchor
        sink_anchor = (points[-1][0] + 2, points[-1][1])
        anchors = {"source": source_anchor, "sink": sink_anchor}
        portals = {"source": points[0], "sink": points[-1]}
        pigtails = tuple(
            CertifiedBusPigtail(
                pigtail_id=f"pigtail:{member.member_id}:{kind}",
                bus_fingerprint=bus.semantic_fingerprint(),
                certificate_fingerprint=certificate.semantic_fingerprint(),
                allocation_fingerprint=allocation.allocation_fingerprint,
                geometry_registry_fingerprint=registry.semantic_fingerprint(),
                member_id=member.member_id,
                net_name=member.net_name,
                terminal_id=f"{member.member_id}:{kind}",
                boundary_id="entry" if kind == "source" else "exit",
                assigned_geometry_id=f"centerline:{index}",
                portal_kind="entry" if kind == "source" else "exit",
                physical_pad_source_id=f"pad:{member.member_id}:{kind}",
                grid_mm=1.0,
                layer="F.Cu",
                pad_anchor_point=anchors[kind],
                portal_point=portals[kind],
                points=(anchors[kind], portals[kind]),
            )
            for kind in ("source", "sink")
        )
        prefix = compose_member_route_prefix(
            bus,
            certificate,
            allocation,
            registry,
            realization,
            member.member_id,
            pigtails,
            (),
            {
                f"{member.member_id}:source": f"pad:{member.member_id}:source",
                f"{member.member_id}:sink": f"pad:{member.member_id}:sink",
            },
        )
        prefixes[member.member_id] = prefix
        length = sum(
            math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1)
            for segment in prefix.prefix.segments
        )
        routes.append(
            NegotiatedGridRoute(
                result=RouteResult(
                    member.net_name,
                    prefix.prefix.segments,
                    prefix.prefix.vias,
                    length,
                ),
                claims=NetResourceClaims(member.net_name, frozenset()),
                base_cost_units=0,
                congestion_cost_units=0,
                prefix_alternative_id=prefix.prefix.alternative_id,
                prefix_fingerprint=prefix.prefix_fingerprint,
            )
        )
    bundle = BusRouteBundle(bus=bus, allocation=allocation, member_routes=tuple(routes))
    context = BusMetricValidationContext(
        confirmed_applicability_conditions=("fixture-applicability",),
        completed_validation_method_ids=("exact-metric-v1",),
        validated_stackup_ids=("stackup",),
        validated_reference_structure_ids=("reference",),
        propagation_models=() if propagation_model is None else (propagation_model,),
        coherence_model_id=(
            "adjacent_pair_length_weighted-v1" if coherence_policy is not None else None
        ),
    )
    return bundle, certificate, registry, prefixes, context


def test_envelope_round_trip_replays_and_context_is_fingerprint_bound() -> None:
    bundle, certificate, registry, prefixes, context = _fixture()
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    assert report.disposition is BusMetricsDisposition.PASS
    assert BusMetricsReport.model_validate_json(report.model_dump_json()) == report
    assert report.inputs.validation_context == context
    assert (
        next(
            item
            for item in report.rules
            if item.rule_id == "bus.coupling.adjacent_member_clearance_mm"
        ).disposition
        is RuleDisposition.PASS
    )


def test_metric_or_report_fingerprint_tamper_is_rejected() -> None:
    bundle, certificate, registry, prefixes, context = _fixture()
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    payload = report.model_dump(mode="json")
    payload["aggregate"]["member_length_spread_mm"] = 1.0
    with pytest.raises(ValidationError, match="complete deterministic replay"):
        BusMetricsReport.model_validate(payload)
    payload = report.model_dump(mode="json")
    payload["report_fingerprint"] = "f" * 64
    with pytest.raises(ValidationError, match="complete deterministic replay"):
        BusMetricsReport.model_validate(payload)


def test_validation_context_tamper_cannot_preserve_hard_pass() -> None:
    bundle, certificate, registry, prefixes, context = _fixture()
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    payload = report.model_dump(mode="json")
    payload["inputs"]["validation_context"]["validated_stackup_ids"] = []
    with pytest.raises(ValidationError, match="complete deterministic replay"):
        BusMetricsReport.model_validate(payload)


@pytest.mark.parametrize(
    ("limit", "expected"),
    ((1.0, RuleDisposition.PASS), (0.0, RuleDisposition.FAIL)),
)
def test_orthogonal_length_spread_equality_and_one_unit_miss(
    limit: float, expected: RuleDisposition
) -> None:
    timing = BusTimingBudget(maximum_length_spread_mm=limit, authority=_authority())
    bundle, certificate, registry, prefixes, context = _fixture(
        timing_budget=timing,
        second_source_anchor=(5, 12),
    )
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    evaluation = next(
        item for item in report.rules if item.rule_id == "bus.timing.maximum_length_spread_mm"
    )
    assert evaluation.disposition is expected
    assert report.aggregate.member_length_spread_witness is not None
    assert report.aggregate.member_length_spread_witness.rational == "1/1"
    assert report.aggregate.member_length_spread_witness.sqrt2 == "0/1"


@pytest.mark.parametrize(
    ("limit", "expected"),
    ((0.8284, RuleDisposition.FAIL), (0.8285, RuleDisposition.PASS)),
)
def test_diagonal_irrational_length_threshold_is_bracketed_exactly(
    limit: float, expected: RuleDisposition
) -> None:
    timing = BusTimingBudget(maximum_length_spread_mm=limit, authority=_authority())
    bundle, certificate, registry, prefixes, context = _fixture(
        timing_budget=timing,
        second_source_anchor=(6, 10),
    )
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    witness = report.aggregate.member_length_spread_witness
    assert witness is not None
    assert (witness.rational, witness.sqrt2) == ("-2/1", "2/1")
    evaluation = next(
        item for item in report.rules if item.rule_id == "bus.timing.maximum_length_spread_mm"
    )
    assert evaluation.disposition is expected


def test_rational_modeled_delay_uses_retained_decimal_evidence() -> None:
    timing = BusTimingBudget(
        maximum_skew_ps=18.0,
        propagation_model_id="fixture-propagation",
        authority=_authority(),
    )
    model = PropagationDelayModel(
        model_id="fixture-propagation",
        delay_ps_per_mm_by_member=(("data0", "1"), ("data1", "2")),
    )
    bundle, certificate, registry, prefixes, context = _fixture(
        timing_budget=timing,
        propagation_model=model,
    )
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    witness = report.aggregate.modeled_delay_spread_witness
    assert witness is not None
    assert (witness.rational, witness.sqrt2, witness.unit) == ("18/1", "0/1", "ps")
    evaluation = next(item for item in report.rules if item.rule_id == "bus.timing.maximum_skew_ps")
    assert evaluation.disposition is RuleDisposition.PASS


def test_perpendicular_translation_is_exact_and_tangential_is_unverified() -> None:
    bundle, certificate, registry, prefixes, context = _fixture()
    perpendicular = measure_bus_route_bundle(
        bundle, certificate, registry, prefixes, context=context
    )
    assert perpendicular.section_pitch[0].authority is MetricAuthority.EXACT

    bundle, certificate, registry, prefixes, context = _fixture(
        lane_points=(((8, 3), (22, 3)), ((24, 3), (38, 3)))
    )
    tangential = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    assert tangential.section_pitch[0].authority is MetricAuthority.UNVERIFIED
    evaluation = next(
        item
        for item in tangential.rules
        if item.rule_id == "bus.coupling.adjacent_member_clearance_mm"
    )
    assert evaluation.disposition is RuleDisposition.HARD_CONSTRAINT_UNVERIFIED


def test_bent_constant_translation_is_unverified() -> None:
    bundle, certificate, registry, prefixes, context = _fixture(
        lane_points=(
            ((8, 3), (15, 3), (15, 8), (22, 8)),
            ((8, 12), (15, 12), (15, 17), (22, 17)),
        )
    )
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    assert report.section_pitch[0].authority is MetricAuthority.UNVERIFIED


def test_exact_grid_reconstruction_uses_ulp_envelope_not_near_grid_tolerance() -> None:
    genuine = _length(
        (TrackSegment(0.0, 0.0, 0.3, 0.0, "F.Cu", "/A", 0.4),),
        0.1,
    )
    near_grid = _length(
        (TrackSegment(0.0, 0.0, 0.30000000005, 0.0, "F.Cu", "/A", 0.4),),
        0.1,
    )
    assert genuine.authority is MetricAuthority.EXACT
    assert near_grid.authority is MetricAuthority.UNVERIFIED


def test_order_mapping_rejects_boundary_section_count_and_portal_mismatch() -> None:
    bundle, certificate, _registry, _prefixes, _context = _fixture()
    extra_section = certificate.sections[0].model_copy(update={"section_id": "extra"})
    wrong_count = certificate.model_copy(
        update={"sections": (*certificate.sections, extra_section)}
    )
    with pytest.raises(ValueError, match="sections plus one"):
        _measure_order(bundle.bus, wrong_count, bundle.allocation)

    wrong_entry = certificate.sections[0].model_copy(update={"entry_portal_id": "portal:missing"})
    wrong_portal = certificate.model_copy(update={"sections": (wrong_entry,)})
    with pytest.raises(ValueError, match="no entry boundary portal"):
        _measure_order(bundle.bus, wrong_portal, bundle.allocation)


def test_swap_allocation_order_is_unverified_without_physical_carriers() -> None:
    bundle, certificate, _registry, _prefixes, _context = _fixture()
    swap = BusSwapEvent(
        section_id="trunk",
        exit_boundary_id="exit",
        window_id="swap-window",
        sequence_index=0,
        order_index=0,
        first_member_id="data0",
        second_member_id="data1",
        layer="F.Cu",
    )
    allocation = bundle.allocation.model_copy(update={"swap_count": 1, "swaps": (swap,)})
    order = _measure_order(bundle.bus, certificate, allocation)
    assert order.authority is MetricAuthority.UNVERIFIED
    assert order.realized_final_exit_order is None
    assert order.physical_swap_count == 0
    assert order.unverified_reasons == ("physical_swap_carriers_absent",)


def _coherence_policy() -> BusCoherencePolicy:
    return BusCoherencePolicy(
        minimum_coherence_fraction=1.0,
        maximum_pitch_deviation_mm=0.0,
        maximum_order_violations=0,
        authority=_authority(),
    )


def test_pairwise_coherence_is_exact_for_fully_supported_adjacent_pair() -> None:
    bundle, certificate, registry, prefixes, context = _fixture(
        coherence_policy=_coherence_policy()
    )
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    assert report.aggregate.pairwise_coherence_fraction == 1.0
    assert report.aggregate.coherence_authority is MetricAuthority.EXACT
    assert report.aggregate.certificate_span_length_mm == 14.0
    evaluation = next(
        item for item in report.rules if item.rule_id == "bus.coherence.minimum_pairwise_fraction"
    )
    assert evaluation.disposition is RuleDisposition.PASS


def test_one_coherent_and_one_unsupported_pair_has_no_exact_fraction() -> None:
    bundle, certificate, registry, prefixes, context = _fixture(
        coherence_policy=_coherence_policy(),
        lane_points=(
            ((8, 3), (22, 3)),
            ((8, 12), (22, 12)),
            ((24, 12), (38, 12)),
        ),
    )
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    assert report.aggregate.pairwise_eligible_length_mm == 28.0
    assert report.aggregate.pairwise_coherent_length_mm == 14.0
    assert report.aggregate.pairwise_coherence_fraction is None
    assert report.aggregate.coherence_authority is MetricAuthority.UNVERIFIED
    evaluation = next(
        item for item in report.rules if item.rule_id == "bus.coherence.minimum_pairwise_fraction"
    )
    assert evaluation.disposition is RuleDisposition.HARD_CONSTRAINT_UNVERIFIED


def test_empty_pairwise_denominator_is_not_applicable() -> None:
    bundle, certificate, registry, prefixes, context = _fixture(
        coherence_policy=_coherence_policy(),
        lane_points=(((8, 3), (22, 3)),),
    )
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    assert report.aggregate.pairwise_eligible_length_witness is None
    assert report.aggregate.pairwise_eligible_length_mm == 0.0
    evaluation = next(
        item for item in report.rules if item.rule_id == "bus.coherence.minimum_pairwise_fraction"
    )
    assert evaluation.disposition is RuleDisposition.NOT_APPLICABLE


@pytest.mark.parametrize("kind", ("activate", "deactivate"))
def test_final_boundary_activation_or_deactivation_order_is_unverified(kind: str) -> None:
    bundle, certificate, _registry, _prefixes, _context = _fixture()
    event = BusActivationEvent(
        boundary_id="exit",
        member_id="data1",
        kind=kind,
        terminal_ids=(f"data1:{'source' if kind == 'activate' else 'sink'}",),
    )
    allocation = bundle.allocation.model_copy(
        update={"activation_count": 1, "activations": (event,)}
    )
    order = _measure_order(bundle.bus, certificate, allocation)
    assert order.authority is MetricAuthority.UNVERIFIED
    assert order.realized_final_exit_order is None
    assert order.unverified_reasons == ("final_boundary_activation_geometry_unreplayed",)


def test_semantic_boundary_permutation_is_not_physical_order_proof() -> None:
    bundle, certificate, _registry, _prefixes, _context = _fixture()
    allocation = bundle.allocation.model_copy(update={"permutation_boundary_ids": ("exit",)})
    order = _measure_order(bundle.bus, certificate, allocation)
    assert order.authority is MetricAuthority.UNVERIFIED
    assert order.realized_final_exit_order is None
    assert order.unverified_reasons == ("physical_boundary_permutation_unreplayed",)


def test_physical_lane_order_drives_all_adjacent_pitch_metrics() -> None:
    bundle, certificate, registry, prefixes, context = _fixture(
        coherence_policy=_coherence_policy(),
        member_ids=("lane_z", "lane_a", "lane_m"),
        lane_points=(
            ((8, 2), (22, 2)),
            ((8, 5), (22, 5)),
            ((8, 15), (22, 15)),
        ),
    )
    report = measure_bus_route_bundle(bundle, certificate, registry, prefixes, context=context)
    section = report.section_pitch[0]
    assert tuple((item.first_member_id, item.second_member_id) for item in section.adjacent) == (
        ("lane_z", "lane_a"),
        ("lane_a", "lane_m"),
    )
    assert section.minimum_pitch_mm == 3.0
    assert section.maximum_pitch_mm == 10.0
    assert section.minimum_edge_clearance_mm == 2.6
    assert report.aggregate.pairwise_eligible_length_mm == 28.0
    assert report.aggregate.pairwise_coherent_length_mm == 28.0
    assert report.aggregate.pairwise_coherence_fraction == 1.0
    clearance = next(
        item for item in report.rules if item.rule_id == "bus.coupling.adjacent_member_clearance_mm"
    )
    assert clearance.disposition is RuleDisposition.FAIL
    assert clearance.measured_value == 2.6


def _membership_change_order_fixture(
    kind: str,
) -> tuple[BusGroup, CorridorCapacityCertificate, BusLaneAllocationResult]:
    bundle, certificate, _registry, _prefixes, _context = _fixture()
    bus = bundle.bus
    data0_entry = next(
        item for item in bus.boundaries[0].ordered_members if item.member_id == "data0"
    )
    if kind == "activate":
        entry = bus.boundaries[0].model_copy(update={"ordered_members": (data0_entry,)})
        middle_members = bus.boundaries[1].ordered_members
        event_boundary_id = "middle"
        event_terminal = "data1:source"
    else:
        entry = bus.boundaries[0]
        middle_members = (data0_entry,)
        event_boundary_id = "entry"
        event_terminal = "data1:sink"
    middle = bus.boundaries[1].model_copy(
        update={
            "boundary_id": "middle",
            "corridor_portal_id": "portal:middle",
            "ordered_members": middle_members,
        }
    )
    final = bus.boundaries[1].model_copy(update={"ordered_members": middle_members})
    changed_bus = bus.model_copy(update={"boundaries": (entry, middle, final)})
    trunk = certificate.sections[0].model_copy(update={"exit_portal_id": "portal:middle"})
    tail = certificate.sections[0].model_copy(
        update={
            "section_id": "tail",
            "entry_portal_id": "portal:middle",
            "exit_portal_id": "portal:exit",
        }
    )
    changed_certificate = certificate.model_copy(update={"sections": (trunk, tail)})
    assignments_by_member = {item.member_id: item for item in bundle.allocation.assignments}
    trunk_assignments = (assignments_by_member["data0"],)
    tail_member_ids = ("data0", "data1") if kind == "activate" else ("data0",)
    tail_assignments = tuple(
        assignments_by_member[member_id].model_copy(update={"section_id": "tail"})
        for member_id in tail_member_ids
    )
    event = BusActivationEvent(
        boundary_id=event_boundary_id,
        member_id="data1",
        kind=kind,
        terminal_ids=(event_terminal,),
    )
    orders = (
        tuple(item.member_id for item in entry.ordered_members),
        tuple(item.member_id for item in middle.ordered_members),
        tuple(item.member_id for item in final.ordered_members),
    )
    allocation = bundle.allocation.model_copy(
        update={
            "normalized_boundary_orders": orders,
            "assignments": (*trunk_assignments, *tail_assignments),
            "activation_count": 1,
            "activations": (event,),
        }
    )
    return changed_bus, changed_certificate, allocation


def test_internal_deactivation_without_complete_boundary_geometry_is_unverified() -> None:
    bus, certificate, allocation = _membership_change_order_fixture("deactivate")
    order = _measure_order(bus, certificate, allocation)
    assert order.authority is MetricAuthority.UNVERIFIED
    assert order.realized_final_exit_order is None
    assert order.unverified_reasons == ("boundary_deactivation_geometry_unreplayed",)


def test_internal_activation_without_complete_boundary_geometry_is_unverified() -> None:
    bus, certificate, allocation = _membership_change_order_fixture("activate")
    incomplete = tuple(
        item
        for item in allocation.assignments
        if not (item.section_id == "tail" and item.member_id == "data1")
    )
    allocation = allocation.model_copy(update={"assignments": incomplete})
    order = _measure_order(bus, certificate, allocation)
    assert order.authority is MetricAuthority.UNVERIFIED
    assert order.realized_final_exit_order is None
    assert order.unverified_reasons == ("boundary_activation_geometry_unreplayed",)


def test_internal_activation_is_exact_when_next_section_reconstructs_complete_order() -> None:
    bus, certificate, allocation = _membership_change_order_fixture("activate")
    order = _measure_order(bus, certificate, allocation)
    assert order.authority is MetricAuthority.EXACT
    assert order.order_violation_count == 0
    assert order.realized_section_entry_orders == (
        ("trunk", "entry", ("data0",)),
        ("tail", "middle", ("data0", "data1")),
    )
    assert order.realized_final_exit_order == ("exit", ("data0", "data1"))
