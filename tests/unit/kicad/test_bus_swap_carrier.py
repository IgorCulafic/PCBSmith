from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from typing import Any, Literal

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_bus_physical_swap import (
    _finish,
    _neutral_inputs,
    _region_payload,
)

from pcbsmith.bus_allocator import allocate_bus_lanes
from pcbsmith.bus_geometry import CertifiedLaneGeometryRegistry
from pcbsmith.kicad.board import BoardLayout, TrackSegment, ViaSpec
from pcbsmith.kicad.bus_physical_swap import (
    BusPhysicalSwapBudget,
    bus_physical_swap_profile_fingerprint,
)
from pcbsmith.kicad.bus_swap_carrier import (
    BusSwapBoundaryContainmentWitness,
    BusSwapCarrierDisposition,
    BusSwapCarrierFailureReason,
    CertifiedBusSwapCarrier,
    ReplayBoundCertifiedBusSwapCarrier,
    _exact_boundary_witness,
    _static_obstacle_claims,
    generate_certified_bus_swap_carrier,
)
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, OrdinaryClearanceRequirement


def _region(
    *,
    candidates: int = 4,
    expansions: int = 100,
    pairwise: bool | str = False,
    layout: BoardLayout | None = None,
):
    payload = _region_payload(
        layout=layout,
        policy_updates={
            "budget": BusPhysicalSwapBudget(
                max_events=1,
                max_candidates_per_event=candidates,
                max_expansions_per_candidate=expansions,
            )
        }
    )
    if not pairwise:
        return _finish(payload)

    requirement = OrdinaryClearanceRequirement(
        requirement_id="swap-member-special",
        nets_a=("/D0",),
        nets_b=("/FOREIGN",) if pairwise == "foreign" else ("/D1",),
        minimum_clearance_mm=1.4,
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"pairwise_clearances": (requirement,)}
            )
        }
    )
    certificate = payload["certificate"].model_copy(
        update={"rule_profile_fingerprint": bus_physical_swap_profile_fingerprint(profile)}
    )
    allocation = allocate_bus_lanes(
        payload["bus"], certificate, budget=payload["allocation"].budget
    )
    geometries = tuple(
        item.model_copy(
            update={"certificate_fingerprint": certificate.semantic_fingerprint()}
        )
        for item in payload["lane_geometry_registry"].geometries
    )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=geometries,
    )
    payload.update(
        {
            "certificate": certificate,
            "allocation": allocation,
            "lane_geometry_registry": registry,
            "rule_profile": profile,
            "swap_event": allocation.swaps[0],
        }
    )
    return _finish(payload)


def _generate(*, ledger: OccupancyLedger | None = None, **region_options: Any):
    return generate_certified_bus_swap_carrier(
        _region(**region_options), ledger or OccupancyLedger()
    )


def _ordinary_resource(
    result: ReplayBoundCertifiedBusSwapCarrier,
    *,
    member_id: str,
    kind: Literal["track_capsule", "via_circle"],
    layer: str | None = None,
    domain_prefix: str = "ordinary",
) -> RoutingResourceKey:
    assert result.outcome.carrier is not None
    member = next(
        item for item in result.outcome.carrier.members if item.member_id == member_id
    )
    return next(
        item
        for item in sorted(member.claims.resources)
        if item.domain_id.startswith(domain_prefix)
        and item.kind == kind
        and (layer is None or item.layer == layer)
    )


def test_exact_two_via_swap_is_replay_bound_and_roundtrips() -> None:
    result = _generate()

    assert result.outcome.disposition is BusSwapCarrierDisposition.GENERATED
    assert result.outcome.failure_reason is None
    assert result.outcome.carrier is not None
    carrier = result.outcome.carrier
    assert carrier.bridge_member_id == "m0"
    assert carrier.stationary_member_id == "m1"
    assert carrier.via_cells == ((5, 1), (5, 3))
    bridge = next(item for item in carrier.members if item.role == "bridge")
    stationary = next(item for item in carrier.members if item.role == "stationary")
    assert len(bridge.vias) == 2
    assert not stationary.vias
    assert {item.layer for item in bridge.segments} == {"F.Cu", "B.Cu"}
    assert {item.layer for item in stationary.segments} == {"F.Cu"}
    assert carrier.connectivity_evidence.bridge_vertical_transition_count == 2
    assert not carrier.clearance_evidence.capacity_one_conflicts
    assert carrier.path_length.authority.value == "exact"
    assert ReplayBoundCertifiedBusSwapCarrier.model_validate_json(
        result.model_dump_json()
    ) == result


def test_candidate_enumeration_and_selection_are_canonical_and_repeatable() -> None:
    first = _generate()
    repeated = _generate()

    assert first == repeated
    assert first.semantic_fingerprint() == repeated.semantic_fingerprint()
    attempts = first.outcome.attempted_candidates
    assert tuple(
        (item.bridge_member_id, item.via_cells) for item in attempts
    ) == (
        ("m0", ((5, 1), (5, 3))),
        ("m0", ((5, 3), (5, 1))),
        ("m1", ((5, 1), (5, 3))),
        ("m1", ((5, 3), (5, 1))),
    )
    assert all(item.expansion_count <= 100 for item in attempts)


def test_candidate_budget_is_checked_before_any_candidate_work() -> None:
    result = _generate(candidates=3)

    assert result.outcome.disposition is BusSwapCarrierDisposition.FAILED
    assert result.outcome.failure_reason is BusSwapCarrierFailureReason.CANDIDATE_BUDGET
    assert result.outcome.attempted_candidates == ()
    assert result.outcome.carrier is None


def test_one_less_expansion_budget_stops_before_exceeding_limit() -> None:
    equality = _generate(expansions=18)
    one_less = _generate(expansions=17)

    assert equality.outcome.carrier is not None
    assert one_less.outcome.carrier is None
    assert one_less.outcome.failure_reason is BusSwapCarrierFailureReason.EXPANSION_BUDGET
    assert all(
        item.expansion_count <= 17 for item in one_less.outcome.attempted_candidates
    )
    assert any(
        item.expansion_count == 17 for item in one_less.outcome.attempted_candidates
    )


def test_blocked_first_bridge_member_selects_second_member() -> None:
    region = _region(pairwise="foreign")
    baseline = generate_certified_bus_swap_carrier(region, OccupancyLedger())
    blocker = _ordinary_resource(
        baseline,
        member_id="m0",
        kind="edge",
        layer="B.Cu",
        domain_prefix="pairwise-clearance-v1:",
    )
    foreign = NetResourceClaims("/FOREIGN", frozenset((blocker,)))

    result = generate_certified_bus_swap_carrier(
        region, OccupancyLedger((foreign,))
    )

    assert result.initial_claims == (foreign,)
    assert result.outcome.carrier is not None
    assert result.outcome.carrier.bridge_member_id == "m1"
    assert result.outcome.carrier.obstacle_evidence.foreign_net_names == ("/FOREIGN",)


def test_via_site_conflict_blocks_both_choices_with_typed_failure() -> None:
    baseline = _generate()
    blocker = _ordinary_resource(baseline, member_id="m0", kind="via_site")
    result = _generate(
        ledger=OccupancyLedger(
            (NetResourceClaims("/FOREIGN", frozenset((blocker,))),)
        )
    )

    assert result.outcome.carrier is None
    assert result.outcome.failure_reason is BusSwapCarrierFailureReason.RESOURCE_CONFLICT
    built = [item for item in result.outcome.attempted_candidates if item.claims_built]
    assert built
    assert any(blocker.resource_id in item.conflict_resource_ids for item in built)


def test_foreign_copper_cell_conflict_is_capacity_one() -> None:
    baseline = _generate()
    blocker = _ordinary_resource(baseline, member_id="m0", kind="cell")
    result = _generate(
        ledger=OccupancyLedger(
            (NetResourceClaims("/FOREIGN", frozenset((blocker,))),)
        )
    )

    assert result.initial_occupancy_fingerprint != OccupancyLedger().semantic_fingerprint()
    assert result.outcome.carrier is None
    assert result.outcome.failure_reason is BusSwapCarrierFailureReason.RESOURCE_CONFLICT
    assert any(
        blocker.resource_id in item.conflict_resource_ids
        for item in result.outcome.attempted_candidates
    )


def test_foreign_segment_edge_cut_conflict_fires_independently() -> None:
    blockers = frozenset(
        RoutingResourceKey("ordinary", "F.Cu", "edge", 4, y, 5, y)
        for y in range(1, 4)
    )
    result = _generate(
        ledger=OccupancyLedger((NetResourceClaims("/FOREIGN", blockers),))
    )

    assert result.outcome.carrier is None
    assert result.outcome.failure_reason is BusSwapCarrierFailureReason.RESOURCE_CONFLICT
    conflicts = {
        resource_id
        for item in result.outcome.attempted_candidates
        for resource_id in item.conflict_resource_ids
    }
    assert conflicts
    assert all('"edge"' in resource_id for resource_id in conflicts)


def test_pairwise_clearance_claims_fire_independently() -> None:
    result = _generate(pairwise=True)

    assert result.outcome.carrier is None
    assert result.outcome.failure_reason is BusSwapCarrierFailureReason.RESOURCE_CONFLICT
    conflicts = {
        resource_id
        for item in result.outcome.attempted_candidates
        for resource_id in item.conflict_resource_ids
    }
    assert conflicts
    assert any("pairwise-clearance-v1:" in item for item in conflicts)
    assert _generate().outcome.carrier is not None


def test_nonzero_copper_width_fires_keep_in_conflict_independently() -> None:
    payload = _region_payload(
        policy_updates={
            "budget": BusPhysicalSwapBudget(
                max_events=1,
                max_candidates_per_event=4,
                max_expansions_per_candidate=100,
            )
        }
    )
    # Every centerline node remains in/on this polygon, but finite-width tracks
    # and via lands at its boundary cannot be contained by it.
    payload["keep_in_polygon"] = ((4, 1), (4, 3), (6, 3), (6, 1))
    result = generate_certified_bus_swap_carrier(
        _finish(payload), OccupancyLedger()
    )

    assert result.outcome.carrier is None
    assert result.outcome.failure_reason is BusSwapCarrierFailureReason.KEEP_IN_CONFLICT
    keep_in_attempts = [
        item
        for item in result.outcome.attempted_candidates
        if item.failure_reason is BusSwapCarrierFailureReason.KEEP_IN_CONFLICT
    ]
    assert keep_in_attempts
    assert all(item.claims_built for item in keep_in_attempts)


@pytest.mark.parametrize(
    ("kind", "start_x", "end_x", "radius", "equality", "below", "over"),
    [
        ("track_capsule", 0.2, 0.8, 0.1, 0.1, 0.099999, 0.100001),
        ("via_circle", 0.5, 0.5, 0.3, 0.3, 0.299999, 0.300001),
    ],
)
def test_exact_rational_boundary_equality_and_one_decimal_unit_either_side(
    kind: str,
    start_x: float,
    end_x: float,
    radius: float,
    equality: float,
    below: float,
    over: float,
) -> None:
    polygon = ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))

    def witness(y: float) -> BusSwapBoundaryContainmentWitness:
        return _exact_boundary_witness(
            primitive_id=f"m0:{kind}",
            member_id="m0",
            primitive_kind=kind,
            start=(start_x, y),
            end=(end_x, y),
            radius_mm=radius,
            polygon=polygon,
        )

    equal_witness = witness(equality)
    below_witness = witness(below)
    over_witness = witness(over)

    assert equal_witness.passed
    assert not below_witness.passed
    assert over_witness.passed
    assert Fraction(
        equal_witness.centerline_distance_squared_numerator,
        equal_witness.centerline_distance_squared_denominator,
    ) == Fraction(
        equal_witness.required_radius_squared_numerator,
        equal_witness.required_radius_squared_denominator,
    )
    assert BusSwapBoundaryContainmentWitness.model_validate_json(
        equal_witness.model_dump_json()
    ) == equal_witness


def test_exact_containment_witness_and_carrier_evidence_tamper_fail() -> None:
    result = _generate()
    assert result.outcome.carrier is not None
    carrier = result.outcome.carrier
    witness = carrier.containment_evidence.primitive_witnesses[0]

    with pytest.raises(ValidationError, match="disposition differs"):
        BusSwapBoundaryContainmentWitness.model_validate_json(
            witness.model_copy(
                update={"centerline_distance_squared_numerator": 0}
            ).model_dump_json()
        )

    changed_witness = witness.model_copy(
        update={"polygon_edge_index": witness.polygon_edge_index + 1}
    )
    changed_evidence = carrier.containment_evidence.model_copy(
        update={
            "primitive_witnesses": (
                changed_witness,
                *carrier.containment_evidence.primitive_witnesses[1:],
            )
        }
    )
    changed_carrier = carrier.model_copy(
        update={"containment_evidence": changed_evidence}
    )
    changed_outcome = result.outcome.model_copy(update={"carrier": changed_carrier})
    with pytest.raises(ValidationError, match="evidence does not rederive"):
        ReplayBoundCertifiedBusSwapCarrier.model_validate_json(
            result.model_copy(update={"outcome": changed_outcome}).model_dump_json()
        )


def test_caller_ledger_is_not_mutated_and_input_order_is_irrelevant() -> None:
    claims = (
        NetResourceClaims("/Z", frozenset()),
        NetResourceClaims("/A", frozenset()),
    )
    ledger = OccupancyLedger(reversed(claims))
    before = ledger.committed_claims(), ledger.semantic_fingerprint()

    first = _generate(ledger=ledger)
    second = _generate(ledger=OccupancyLedger(claims))

    assert (ledger.committed_claims(), ledger.semantic_fingerprint()) == before
    assert first == second
    assert tuple(item.net_name for item in first.initial_claims) == ("/A", "/Z")


def test_schema_rejects_one_via_same_layer_and_path_tamper() -> None:
    result = _generate()
    assert result.outcome.carrier is not None
    carrier = result.outcome.carrier
    members = list(carrier.members)
    bridge_index = next(index for index, item in enumerate(members) if item.role == "bridge")
    for via_count in (0, 1):
        changed = list(members)
        changed[bridge_index] = changed[bridge_index].model_copy(
            update={"vias": changed[bridge_index].vias[:via_count]}
        )
        with pytest.raises(ValidationError, match="exactly two bridge vias"):
            CertifiedBusSwapCarrier.model_validate_json(
                carrier.model_copy(update={"members": tuple(changed)}).model_dump_json()
            )

    members = list(carrier.members)
    stationary_index = next(
        index for index, item in enumerate(members) if item.role == "stationary"
    )
    path = members[stationary_index].path_nodes
    members[stationary_index] = members[stationary_index].model_copy(
        update={"path_nodes": (path[0], ("B.Cu", *path[0][1:]), *path[1:])}
    )
    with pytest.raises(ValidationError):
        CertifiedBusSwapCarrier.model_validate_json(
            carrier.model_copy(update={"members": tuple(members)}).model_dump_json()
        )


def test_stale_authority_fingerprints_and_outcome_tamper_fail_replay() -> None:
    result = _generate()
    with pytest.raises(ValidationError, match="initial occupancy fingerprint"):
        ReplayBoundCertifiedBusSwapCarrier.model_validate_json(
            result.model_copy(
                update={"initial_occupancy_fingerprint": "0" * 64}
            ).model_dump_json()
        )

    tampered_outcome = result.outcome.model_copy(
        update={"outcome_fingerprint": "0" * 64}
    )
    with pytest.raises(ValidationError, match="outcome fingerprint"):
        ReplayBoundCertifiedBusSwapCarrier.model_validate_json(
            result.model_copy(update={"outcome": tampered_outcome}).model_dump_json()
        )

    stale_region = result.region.model_copy(update={"region_fingerprint": "0" * 64})
    with pytest.raises(ValidationError, match="region_fingerprint"):
        ReplayBoundCertifiedBusSwapCarrier.model_validate_json(
            result.model_copy(update={"region": stale_region}).model_dump_json()
        )


def test_stale_fixed_track_width_authority_fails_before_search() -> None:
    payload = _region_payload()
    registry = payload["lane_geometry_registry"]
    geometries = list(registry.geometries)
    geometries[0] = geometries[0].model_copy(update={"track_width_mm": 0.21})
    payload["lane_geometry_registry"] = registry.model_copy(
        update={"geometries": tuple(geometries)}
    )

    with pytest.raises(ValidationError, match="track width authority"):
        _finish(payload)


def test_initial_occupancy_cannot_shadow_an_event_member() -> None:
    with pytest.raises(ValidationError, match="foreign to the swap-event members"):
        _generate(
            ledger=OccupancyLedger((NetResourceClaims("/D0", frozenset()),))
        )


def test_static_copper_requires_explicit_complete_initial_claim_authority() -> None:
    layout = replace(
        _neutral_inputs()[0],
        segments=(TrackSegment(0, 0, 1, 0, "F.Cu", "/STATIC", 0.2),),
    )
    region = _region(layout=layout)
    missing = generate_certified_bus_swap_carrier(region, OccupancyLedger())

    assert missing.outcome.carrier is None
    assert (
        missing.outcome.failure_reason
        is BusSwapCarrierFailureReason.STATIC_OBSTACLE_AUTHORITY
    )
    assert missing.outcome.attempted_candidates == ()

    required, supported = _static_obstacle_claims(region)
    assert supported and len(required) == 1
    complete = generate_certified_bus_swap_carrier(
        region, OccupancyLedger(required)
    )
    assert complete.outcome.carrier is not None
    obstacle = complete.outcome.carrier.obstacle_evidence
    assert obstacle.required_static_claims == required
    assert obstacle.initial_occupancy_covers_static_copper


def test_unsupported_static_via_geometry_fails_before_candidate_work() -> None:
    layout = replace(
        _neutral_inputs()[0],
        vias=(ViaSpec(1.25, 1.0, "/STATIC", size_mm=0.7, drill_mm=0.3),),
    )
    result = generate_certified_bus_swap_carrier(
        _region(layout=layout), OccupancyLedger()
    )

    assert result.outcome.carrier is None
    assert (
        result.outcome.failure_reason
        is BusSwapCarrierFailureReason.STATIC_OBSTACLE_AUTHORITY
    )
    assert result.outcome.attempted_candidates == ()
