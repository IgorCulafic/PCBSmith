"""End-to-end authority tests for cost-aware replay checked commit."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_candidate as candidate_fixtures
from tests.unit.kicad import test_bus_escape as escape_fixtures
from tests.unit.kicad import test_bus_lcs_cost_physical_realization as cost_physical_fixtures
from tests.unit.kicad import test_bus_replay_checked_commit as checked_fixtures
from tests.unit.kicad import test_bus_transaction as transaction_fixtures

from pcbsmith.bus_allocator import allocate_bus_lanes
from pcbsmith.bus_geometry import (
    CertifiedBusEscapeGraphRegistry,
    CertifiedBusEscapeRegion,
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
    certified_keep_in_fingerprint,
)
from pcbsmith.bus_ir import BusLayerPolicy, BusViaPolicy
from pcbsmith.bus_lcs import BusLcsBoundaryMember
from pcbsmith.bus_lcs_cost_plan import (
    BusLcsCostBudget,
    BusLcsCostPolicy,
    BusLcsMemberOutlierCapability,
    build_bus_lcs_cost_plan_input,
    plan_bus_lcs_cost,
)
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.bus_candidate import BusCandidateBudget
from pcbsmith.kicad.bus_candidate_transaction import ReplayBoundBusRouteBundle
from pcbsmith.kicad.bus_checked_commit import BusExactDisposition, materialize_complete_route_map
from pcbsmith.kicad.bus_escape import BusEscapeBudget
from pcbsmith.kicad.bus_escape_replay import generate_replay_bound_bus_escape_candidate
from pcbsmith.kicad.bus_lcs_cost_physical_realization import (
    BusLcsCostPhysicalBudget,
    validate_bus_lcs_cost_physical_realization,
)
from pcbsmith.kicad.bus_lcs_cost_replay_checked_commit import (
    BusLcsCostReplayCheckedCommitResult,
    BusLcsCostReplayRouteAuthority,
    commit_bus_lcs_cost_replay_exact,
)
from pcbsmith.kicad.bus_lcs_physical_realization import (
    bus_lcs_physical_profile_fingerprint,
)
from pcbsmith.kicad.bus_transaction import bus_route_map_fingerprint
from pcbsmith.kicad.bus_transition import BusTransitionBudget
from pcbsmith.kicad.bus_transition_replay import generate_replay_bound_bus_transition_vias
from pcbsmith.kicad.negotiated_grid import (
    CertifiedEndpointTerminalSource,
    NegotiatedGridRoute,
)
from pcbsmith.kicad.negotiated_resources import NetResourceClaims, OccupancyLedger
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def _boundary(boundary: Any) -> tuple[BusLcsBoundaryMember, ...]:
    return tuple(
        BusLcsBoundaryMember(member_id=item.member_id, active=True)
        for item in boundary.ordered_members
    )


def _authority(
    *,
    claims: tuple[NetResourceClaims, ...] = (),
    physical_claims: tuple[NetResourceClaims, ...] | None = None,
) -> BusLcsCostReplayRouteAuthority:
    source = escape_fixtures._fixture()
    profile = DEFAULT_PCB_RULE_PROFILE
    bus = source.bus.model_copy(
        update={
            "layer_policy": BusLayerPolicy(
                allowed_layers=("F.Cu", "B.Cu"),
                preferred_layers=("F.Cu",),
                via_policy=BusViaPolicy(
                    mode="independent_bounded",
                    maximum_vias_per_member=2,
                    maximum_via_count_spread=2,
                ),
            )
        }
    )
    certificate = source.certificate.model_copy(
        update={
            "rule_profile_fingerprint": bus_lcs_physical_profile_fingerprint(profile)
        }
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success

    certificate_fingerprint = certificate.semantic_fingerprint()
    geometries = tuple(
        CertifiedLaneGeometry.model_validate(
            geometry.model_copy(
                update={"certificate_fingerprint": certificate_fingerprint}
            ).model_dump()
        )
        for geometry in source.lanes.geometries
    )
    lanes = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate_fingerprint,
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=source.lanes.grid_mm,
        geometries=geometries,
    )
    escape_root = {
        "bus_fingerprint": bus.semantic_fingerprint(),
        "certificate_fingerprint": certificate_fingerprint,
        "allocation_fingerprint": allocation.allocation_fingerprint,
        "lane_geometry_registry_fingerprint": lanes.semantic_fingerprint(),
    }
    regions = tuple(
        CertifiedBusEscapeRegion.model_validate(
            region.model_copy(update=escape_root).model_dump()
        )
        for region in source.registry.regions
    )
    registry = CertifiedBusEscapeGraphRegistry(
        **escape_root,
        grid_mm=source.registry.grid_mm,
        regions=regions,
    )
    route_replay = generate_replay_bound_bus_escape_candidate(
        source.layout,
        source.netlist,
        bus,
        certificate,
        allocation,
        lanes,
        registry,
        source.sources,
        OccupancyLedger(claims),
        escape_fixtures.DEFAULT_ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
        profile=profile,
    )
    assert route_replay.generation_result.success
    candidate = route_replay.generation_result.candidate
    assert candidate is not None and candidate.bundle is not None
    route = ReplayBoundBusRouteBundle(
        escape_replay=route_replay,
        bundle=candidate.bundle,
    )

    profile_fingerprint = bus_lcs_physical_profile_fingerprint(profile)
    capabilities = tuple(
        BusLcsMemberOutlierCapability(
            member_id=member.member_id,
            assigned_outlier_layer=None,
            inner_section_ids=(),
            source_transition_window_id=None,
            target_transition_window_id=None,
            source_pad_access_layers=("F.Cu",),
            target_pad_access_layers=("F.Cu",),
            source_transition_cost_units=0,
            target_transition_cost_units=0,
            via_cost_units=0,
            physical_via_count=0,
            required_clearance_domain_ids=("ordinary",),
            rule_profile_fingerprint=profile_fingerprint,
        )
        for member in bus.members
    )
    plan = plan_bus_lcs_cost(
        build_bus_lcs_cost_plan_input(
            bus=bus,
            certificate=certificate,
            rule_profile=profile,
            source_boundary=_boundary(bus.boundaries[0]),
            target_boundary=_boundary(bus.boundaries[-1]),
            outlier_capabilities=capabilities,
            policy=BusLcsCostPolicy(
                base_layer="F.Cu",
                permitted_outlier_layers=("B.Cu",),
                maximum_vias_per_member=2,
                maximum_via_count_spread=2,
            ),
            budget=BusLcsCostBudget(max_dp_cells=4, max_candidates=100),
        )
    )
    assert plan.success
    transition_claims = claims if physical_claims is None else physical_claims
    transition = generate_replay_bound_bus_transition_vias(
        bus,
        certificate,
        allocation,
        lanes,
        OccupancyLedger(transition_claims),
        BusTransitionBudget(max_members=2, max_events=0),
        profile=profile,
    )
    assert transition.generation_result.success
    physical = validate_bus_lcs_cost_physical_realization(
        plan,
        allocation,
        transition,
        tuple(item for _member_id, item in route_replay.generation_result.prefixes_by_member),
        BusLcsCostPhysicalBudget(
            max_assignment_validations=len(allocation.assignments),
            max_member_validations=len(bus.members),
        ),
    )
    assert physical.success
    return BusLcsCostReplayRouteAuthority(
        cost_physical=physical,
        route_authority=route,
    )


def _state(coordinator: Any) -> tuple[object, object, object]:
    return (
        coordinator.ledger.committed_claims(),
        coordinator.ledger.semantic_fingerprint(),
        bus_route_map_fingerprint(coordinator.routes_by_net),
    )


def _transitioned_authority() -> BusLcsCostReplayRouteAuthority:
    fixture, plan = cost_physical_fixtures._authorities()
    shifted_keep_in = tuple(
        (x + 4, y + 4) for x, y in fixture.registry.geometries[0].keep_in_polygon
    )
    shifted_keep_in_fingerprint = certified_keep_in_fingerprint(
        fixture.registry.grid_mm, shifted_keep_in
    )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=fixture.registry.certificate_fingerprint,
        allocation_fingerprint=fixture.registry.allocation_fingerprint,
        grid_mm=fixture.registry.grid_mm,
        geometries=tuple(
            CertifiedLaneGeometry.model_validate(
                geometry.model_copy(
                    update={
                        "entry_portal_point": (
                            geometry.entry_portal_point[0] + 4,
                            geometry.entry_portal_point[1] + 4,
                        ),
                        "exit_portal_point": (
                            geometry.exit_portal_point[0] + 4,
                            geometry.exit_portal_point[1] + 4,
                        ),
                        "points": tuple((x + 4, y + 4) for x, y in geometry.points),
                        "keep_in_polygon": shifted_keep_in,
                        "keep_in_fingerprint": shifted_keep_in_fingerprint,
                    }
                ).model_dump()
            )
            for geometry in fixture.registry.geometries
        ),
    )
    transition = generate_replay_bound_bus_transition_vias(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        registry,
        OccupancyLedger(),
        fixture.transition.replay_input.budget,
        profile=DEFAULT_PCB_RULE_PROFILE,
    )
    assert transition.generation_result.success
    component_refs = tuple(
        reference
        for member_id in ("z", "a", "m")
        for reference in (f"U_{member_id}", f"J_{member_id}")
    )
    components = tuple(
        BoardComponent(
            reference,
            "1k",
            "Resistor_SMD:R_0603_1608Metric",
            f"fixture-{reference.lower()}",
        )
        for reference in component_refs
    )
    by_reference = {item.reference: item for item in components}
    layout = BoardLayout(
        placements=tuple(
            (by_reference[reference], 1.0 if reference.startswith("U_") else 8.0)
            for reference in component_refs
        ),
        segments=(),
        vias=(),
        width_mm=10.0,
        height_mm=8.0,
        parts_row_y_mm=3.0,
        part_y_mm=tuple(
            (reference, 3.0 + 1.0 * ("zam".index(reference[-1])))
            for reference in component_refs
        ),
        part_rotation=tuple(
            (reference, 180.0) for reference in component_refs if reference.startswith("U_")
        ),
    )
    netlist = BoardNetlist(
        components=components,
        nets=tuple(
            BoardNet(
                f"/{member_id.upper()}",
                ((f"U_{member_id}", "1"), (f"J_{member_id}", "1")),
            )
            for member_id in ("z", "a", "m")
        ),
    )
    root = {
        "bus_fingerprint": fixture.bus.semantic_fingerprint(),
        "certificate_fingerprint": fixture.certificate.semantic_fingerprint(),
        "allocation_fingerprint": fixture.allocation.allocation_fingerprint,
        "lane_geometry_registry_fingerprint": registry.semantic_fingerprint(),
        "grid_mm": fixture.certificate.grid_mm,
    }
    regions = []
    sources = {}
    for member_id in ("z", "a", "m"):
        y = 6 + 2 * ("zam".index(member_id))
        net_name = f"/{member_id.upper()}"
        for role, reference, boundary_id, geometry_id, portal_kind, portal_id, points in (
            (
                "source",
                f"U_{member_id}",
                "b0",
                f"line:s0:{member_id}",
                "entry",
                "p0",
                    ((4, y), (5, y)),
            ),
            (
                "sink",
                f"J_{member_id}",
                "b4",
                f"line:s3:{member_id}",
                "exit",
                "p4",
                    ((13, y), (14, y)),
            ),
        ):
            terminal_id = f"{member_id}:{role}"
            regions.append(
                CertifiedBusEscapeRegion(
                    **root,
                    region_id=f"escape:{terminal_id}",
                    member_id=member_id,
                    net_name=net_name,
                    terminal_id=terminal_id,
                    boundary_id=boundary_id,
                    assigned_geometry_id=geometry_id,
                    portal_kind=portal_kind,
                    portal_id=portal_id,
                    portal_point=points[-1] if role == "source" else points[0],
                    layer="F.Cu",
                    allowed_track_nodes=points,
                    allowed_track_transitions=((points[0], points[1]),),
                )
            )
            sources[terminal_id] = CertifiedEndpointTerminalSource(
                component_ref=reference,
                pad_number="1",
                net_name=net_name,
                physical_pad_source_id=f"pad:{reference}:0",
                source_node=("F.Cu", points[0][0] if role == "source" else points[1][0], y),
            )
    escape_registry = CertifiedBusEscapeGraphRegistry(**root, regions=tuple(regions))
    route_replay = generate_replay_bound_bus_escape_candidate(
        layout,
        netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        registry,
        escape_registry,
        sources,
        OccupancyLedger(),
        BusEscapeBudget(
            max_members=3,
            max_terminals=6,
            max_expansions_per_terminal=1,
            max_expansions_per_member=2,
            max_total_expansions=6,
        ),
        BusCandidateBudget(
            max_members=3,
            max_expansions_per_member=10_000,
            max_total_expansions=30_000,
        ),
        transition_budget=transition.replay_input.budget,
        profile=DEFAULT_PCB_RULE_PROFILE,
    )
    assert route_replay.generation_result.success, route_replay.generation_result.model_dump_json(
        indent=2
    )
    candidate = route_replay.generation_result.candidate
    assert candidate is not None and candidate.bundle is not None
    physical = validate_bus_lcs_cost_physical_realization(
        plan,
        fixture.allocation,
        transition,
        tuple(item for _member_id, item in route_replay.generation_result.prefixes_by_member),
        BusLcsCostPhysicalBudget(
            max_assignment_validations=len(fixture.allocation.assignments),
            max_member_validations=len(fixture.bus.members),
        ),
    )
    assert physical.success, physical
    return BusLcsCostReplayRouteAuthority(
        cost_physical=physical,
        route_authority=ReplayBoundBusRouteBundle(
            escape_replay=route_replay,
            bundle=candidate.bundle,
        ),
    )


def test_cost_authority_commits_exact_retained_route_once_and_roundtrips() -> None:
    authority = _authority()
    coordinator = checked_fixtures._coordinator(authority.route_authority)

    result = commit_bus_lcs_cost_replay_exact(
        coordinator,
        authority,
        exact_checker=checked_fixtures._checker(True),
    )

    assert result.checked_result.checked_result.accepted
    assert result.checked_result.checked_result.telemetry.candidate_call_count == 1
    assert coordinator.routes_by_net == authority.route_authority.bundle.by_net()
    assert BusLcsCostReplayCheckedCommitResult.model_validate_json(
        result.model_dump_json()
    ) == result


def test_transitioned_cost_authority_accepts_identical_transition_budget_and_commits() -> None:
    authority = _transitioned_authority()
    physical_transition_input = (
        authority.cost_physical.realization_input.transition_authority.replay_input
    )
    route_input = authority.route_authority.escape_replay.replay_input

    assert route_input.allocation.layer_transitions
    assert route_input.transition_budget == physical_transition_input.budget
    assert any(
        item.transition_events for item in authority.cost_physical.member_authorities
    )
    assert sum(
        len(item.result.vias) for item in authority.route_authority.bundle.member_routes
    ) == 2

    coordinator = checked_fixtures._coordinator(authority.route_authority)
    result = commit_bus_lcs_cost_replay_exact(
        coordinator,
        authority,
        exact_checker=checked_fixtures._checker(True),
    )

    assert result.checked_result.checked_result.accepted
    assert coordinator.routes_by_net == authority.route_authority.bundle.by_net()


@pytest.mark.parametrize("accepted", [False, None])
def test_rejection_and_missing_checker_restore_state(accepted: bool | None) -> None:
    authority = _authority()
    coordinator = checked_fixtures._coordinator(authority.route_authority)
    before = _state(coordinator)

    result = commit_bus_lcs_cost_replay_exact(
        coordinator,
        authority,
        exact_checker=None if accepted is None else checked_fixtures._checker(accepted),
    )

    expected = (
        BusExactDisposition.CHECKER_MISSING
        if accepted is None
        else BusExactDisposition.REJECTED
    )
    assert result.checked_result.checked_result.exact_disposition is expected
    assert _state(coordinator) == before


def test_materializer_exception_rolls_back_without_retry() -> None:
    authority = _authority()
    coordinator = checked_fixtures._coordinator(authority.route_authority)
    before = _state(coordinator)
    calls = 0

    def fail(
        _layout: BoardLayout,
        _routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        nonlocal calls
        calls += 1
        raise RuntimeError("cost materializer failed")

    with pytest.raises(RuntimeError, match="cost materializer failed"):
        commit_bus_lcs_cost_replay_exact(
            coordinator,
            authority,
            exact_checker=checked_fixtures._checker(True),
            materializer=fail,
        )

    assert calls == 1
    assert _state(coordinator) == before


def test_different_initial_occupancy_cannot_cross_cost_and_route_authorities() -> None:
    foreign = transaction_fixtures._route("/FOREIGN", 80).claims

    with pytest.raises(ValueError, match="identical inputs"):
        _authority(claims=(foreign,), physical_claims=())


def test_checked_envelope_rejects_a_different_nested_route() -> None:
    authority = _authority()
    coordinator = checked_fixtures._coordinator(authority.route_authority)
    result = commit_bus_lcs_cost_replay_exact(
        coordinator,
        authority,
        exact_checker=checked_fixtures._checker(True),
    )
    payload = result.model_dump(mode="json")
    payload["checked_result"]["checked_result"]["candidate_result"][
        "expansion_count"
    ] += 1

    with pytest.raises(ValidationError):
        BusLcsCostReplayCheckedCommitResult.model_validate(payload)


def test_existing_materializer_type_remains_compatible() -> None:
    authority = _authority()
    coordinator = checked_fixtures._coordinator(authority.route_authority)
    result = commit_bus_lcs_cost_replay_exact(
        coordinator,
        authority,
        exact_checker=checked_fixtures._checker(True),
        materializer=materialize_complete_route_map,
    )
    assert result.checked_result.checked_result.accepted
