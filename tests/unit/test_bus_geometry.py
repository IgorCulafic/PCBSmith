from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from pcbsmith.bus_allocator import BusLaneAllocationResult, allocate_bus_lanes
from pcbsmith.bus_geometry import (
    CertifiedBusEscapeGraphRegistry,
    CertifiedBusEscapeRegion,
    CertifiedBusTrunkRealization,
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
    RealizedCertifiedTrunk,
    certified_keep_in_fingerprint,
    realize_certified_trunks,
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
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.negotiated_grid import GridClaimDomain, grid_claim_domains_for_net
from pcbsmith.kicad.negotiated_resources import PairwiseClearanceDomain
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

_KEEP_IN = ((-2, -3), (12, -3), (12, 6), (-2, 6))


def _member(member_id: str, net_name: str, width_mm: float = 0.2) -> BusMember:
    return BusMember(
        member_id=member_id,
        net_name=net_name,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net_name,
                component_ref=f"U-{member_id}",
                pad_number="1",
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net_name,
                component_ref=f"J-{member_id}",
                pad_number="1",
                role="sink",
            ),
        ),
        width_mm=width_mm,
    )


def _bus(*, one_member: bool = False) -> BusGroup:
    members = (_member("data0", "/D0"),)
    if not one_member:
        members = (*members, _member("data1", "/D1"))
    refs = tuple(BoundaryMemberRef(member_id=member.member_id) for member in members)
    return BusGroup(
        bus_id="display-data",
        members=members,
        boundaries=(
            BusBoundary(
                boundary_id="entry",
                corridor_portal_id="portal:entry",
                orientation="forward",
                ordered_members=refs,
            ),
            BusBoundary(
                boundary_id="exit",
                corridor_portal_id="portal:exit",
                orientation="forward",
                ordered_members=refs,
            ),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        rule_profile_id="pcbsmith-legacy-default-v1",
    )


def _certificate(bus: BusGroup) -> CorridorCapacityCertificate:
    slots = tuple(
        CertifiedLaneSlot(
            slot_id=f"slot:{index}",
            section_id="trunk",
            layer="F.Cu",
            order_index=index,
            centerline_geometry_id=f"centerline:{member.member_id}",
            maximum_track_width_mm=0.4,
            supported_clearance_domain_ids=("ordinary", "pair:data"),
        )
        for index, member in enumerate(bus.members)
    )
    return CorridorCapacityCertificate(
        certificate_id="certificate:display-data",
        board_geometry_fingerprint="a" * 64,
        static_obstacle_fingerprint="b" * 64,
        rule_profile_fingerprint="c" * 64,
        demand_fingerprint="d" * 64,
        corridor_graph_fingerprint="e" * 64,
        grid_mm=0.5,
        sections=(
            CertifiedCorridorSection(
                section_id="trunk",
                entry_portal_id="portal:entry",
                exit_portal_id="portal:exit",
                lane_slots=slots,
            ),
        ),
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )


def _geometry(
    certificate: CorridorCapacityCertificate,
    member: BusMember,
    points: tuple[tuple[int, int], ...],
    *,
    centerline_geometry_id: str | None = None,
    keep_in: tuple[tuple[int, int], ...] = _KEEP_IN,
) -> CertifiedLaneGeometry:
    return CertifiedLaneGeometry(
        centerline_geometry_id=(centerline_geometry_id or f"centerline:{member.member_id}"),
        certificate_fingerprint=certificate.semantic_fingerprint(),
        section_id="trunk",
        layer="F.Cu",
        track_width_mm=member.width_mm,
        grid_mm=certificate.grid_mm,
        entry_portal_id="portal:entry",
        exit_portal_id="portal:exit",
        entry_portal_point=points[0],
        exit_portal_point=points[-1],
        points=points,
        keep_in_polygon=keep_in,
        keep_in_fingerprint=certified_keep_in_fingerprint(
            certificate.grid_mm,
            keep_in,
        ),
    )


def _fixture(
    *,
    one_member: bool = False,
    points_by_member: dict[str, tuple[tuple[int, int], ...]] | None = None,
    reverse_registry: bool = False,
) -> tuple[
    BusGroup,
    CorridorCapacityCertificate,
    BusLaneAllocationResult,
    CertifiedLaneGeometryRegistry,
]:
    bus = _bus(one_member=one_member)
    certificate = _certificate(bus)
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    defaults = {
        "data0": ((0, 0), (8, 0)),
        "data1": ((0, 2), (8, 2)),
    }
    if points_by_member is not None:
        defaults.update(points_by_member)
    geometries = tuple(
        _geometry(certificate, member, defaults[member.member_id]) for member in bus.members
    )
    if reverse_registry:
        geometries = tuple(reversed(geometries))
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=geometries,
    )
    return bus, certificate, allocation, registry


def _escape_fixture() -> tuple[
    BusGroup,
    CorridorCapacityCertificate,
    BusLaneAllocationResult,
    CertifiedLaneGeometryRegistry,
    CertifiedBusEscapeGraphRegistry,
]:
    original = _bus(one_member=True)
    member = original.members[0]
    boundaries = (
        original.boundaries[0].model_copy(
            update={
                "ordered_members": (
                    BoundaryMemberRef(member_id="data0", terminal_ids=("data0:source",)),
                )
            }
        ),
        original.boundaries[1].model_copy(
            update={
                "ordered_members": (
                    BoundaryMemberRef(member_id="data0", terminal_ids=("data0:sink",)),
                )
            }
        ),
    )
    bus = original.model_copy(update={"boundaries": boundaries})
    certificate = _certificate(bus)
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    geometry = _geometry(certificate, member, ((0, 0), (8, 0)))
    lanes = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=(geometry,),
    )
    common = dict(
        bus_fingerprint=bus.semantic_fingerprint(),
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        lane_geometry_registry_fingerprint=lanes.semantic_fingerprint(),
        member_id="data0",
        net_name="/D0",
        assigned_geometry_id="centerline:data0",
        layer="F.Cu",
        grid_mm=certificate.grid_mm,
    )
    source = CertifiedBusEscapeRegion(
        region_id="escape:source",
        terminal_id="data0:source",
        boundary_id="entry",
        portal_kind="entry",
        portal_id="portal:entry",
        portal_point=(0, 0),
        allowed_track_nodes=((1, 1), (0, 0), (0, 1)),
        allowed_track_transitions=(((0, 1), (1, 1)), ((0, 0), (0, 1))),
        **common,
    )
    sink = CertifiedBusEscapeRegion(
        region_id="escape:sink",
        terminal_id="data0:sink",
        boundary_id="exit",
        portal_kind="exit",
        portal_id="portal:exit",
        portal_point=(8, 0),
        allowed_track_nodes=((8, 0), (8, 1)),
        allowed_track_transitions=(((8, 1), (8, 0)),),
        **common,
    )
    registry = CertifiedBusEscapeGraphRegistry(
        bus_fingerprint=bus.semantic_fingerprint(),
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        lane_geometry_registry_fingerprint=lanes.semantic_fingerprint(),
        grid_mm=certificate.grid_mm,
        regions=(source, sink),
    )
    return bus, certificate, allocation, lanes, registry


def test_escape_graph_authority_is_canonical_bound_and_fingerprinted() -> None:
    bus, certificate, allocation, lanes, registry = _escape_fixture()
    registry.require_authority(bus, certificate, allocation, lanes)
    reversed_regions = tuple(
        region.model_copy(
            update={
                "allowed_track_nodes": tuple(reversed(region.allowed_track_nodes)),
                "allowed_track_transitions": tuple(
                    (b, a) for a, b in reversed(region.allowed_track_transitions)
                ),
            }
        )
        for region in reversed(registry.regions)
    )
    repeated = CertifiedBusEscapeGraphRegistry(
        bus_fingerprint=registry.bus_fingerprint,
        certificate_fingerprint=registry.certificate_fingerprint,
        allocation_fingerprint=registry.allocation_fingerprint,
        lane_geometry_registry_fingerprint=registry.lane_geometry_registry_fingerprint,
        grid_mm=registry.grid_mm,
        regions=reversed_regions,
    )
    assert repeated == registry
    assert (
        registry.semantic_fingerprint()
        == "8b55b88acbe006f1e1fb799dc6eeb388d7010b143e2c217503109cd066514ee7"
    )
    assert (
        registry.regions[0].semantic_fingerprint()
        == "1090225f9eb187352785ca14e0705b9c1c22516e6bd80f6a3c42f8f34c299016"
    )


@pytest.mark.parametrize("mutation", ("via", "disconnected", "duplicate_transition"))
def test_escape_region_rejects_non_same_layer_or_invalid_graph(mutation: str) -> None:
    region = _escape_fixture()[4].regions[0]
    update: dict[str, object]
    if mutation == "via":
        update = {"allowed_via_cells": ((0, 0),)}
    elif mutation == "disconnected":
        update = {"allowed_track_nodes": (*region.allowed_track_nodes, (4, 4))}
    else:
        update = {
            "allowed_track_transitions": (
                *region.allowed_track_transitions,
                region.allowed_track_transitions[0][::-1],
            )
        }
    with pytest.raises(ValidationError):
        CertifiedBusEscapeRegion.model_validate({**region.model_dump(), **update})


def test_escape_registry_rejects_duplicate_and_missing_terminal_coverage() -> None:
    bus, certificate, allocation, lanes, registry = _escape_fixture()
    with pytest.raises(ValidationError, match="one region per member terminal"):
        CertifiedBusEscapeGraphRegistry.model_validate(
            {
                **registry.model_dump(),
                "regions": (
                    registry.regions[0],
                    registry.regions[0].model_copy(update={"region_id": "other"}),
                ),
            }
        )
    missing = registry.model_copy(update={"regions": (registry.regions[0],)})
    with pytest.raises(ValueError, match="exactly cover"):
        missing.require_authority(bus, certificate, allocation, lanes)


@pytest.mark.parametrize(
    "field,value,message",
    (
        ("bus_fingerprint", "f" * 64, "root authority"),
        ("assigned_geometry_id", "foreign-lane", "not assigned"),
        ("portal_point", (7, 0), "portal does not match"),
    ),
)
def test_escape_authority_rejects_stale_or_wrong_lane_binding(
    field: str, value: object, message: str
) -> None:
    bus, certificate, allocation, lanes, registry = _escape_fixture()
    if field == "bus_fingerprint":
        forged = registry.model_copy(update={field: value})
    else:
        changed = registry.regions[0].model_copy(update={field: value})
        forged = registry.model_copy(update={"regions": (changed, registry.regions[1])})
    with pytest.raises(ValueError, match=message):
        forged.require_authority(bus, certificate, allocation, lanes)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("certificate_fingerprint", "f" * 64, "root authority"),
        ("allocation_fingerprint", "f" * 64, "root authority"),
        (
            "lane_geometry_registry_fingerprint",
            "f" * 64,
            "lane geometry registry fingerprint",
        ),
        ("grid_mm", 0.25, "grid does not match"),
    ),
)
def test_escape_authority_rejects_stale_root_bindings(
    field: str, value: object, message: str
) -> None:
    bus, certificate, allocation, lanes, registry = _escape_fixture()
    forged = registry.model_copy(update={field: value})
    with pytest.raises(ValueError, match=message):
        forged.require_authority(bus, certificate, allocation, lanes)


def test_escape_registry_rejects_region_root_lane_registry_disagreement() -> None:
    registry = _escape_fixture()[4]
    payload = registry.model_dump()
    payload["regions"][0]["lane_geometry_registry_fingerprint"] = "f" * 64
    with pytest.raises(ValidationError, match="lane geometry registry fingerprint"):
        CertifiedBusEscapeGraphRegistry.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("bus_fingerprint", "f" * 64, "bus fingerprint is stale"),
        ("certificate_fingerprint", "f" * 64, "certificate fingerprint is stale"),
        ("allocation_fingerprint", "f" * 64, "allocation fingerprint is stale"),
        (
            "lane_geometry_registry_fingerprint",
            "f" * 64,
            "lane geometry registry fingerprint is stale",
        ),
        ("grid_mm", 0.25, "grid does not match its registry"),
    ),
)
def test_escape_authority_revalidates_nested_region_root_bindings(
    field: str, value: object, message: str
) -> None:
    bus, certificate, allocation, lanes, registry = _escape_fixture()
    source = next(region for region in registry.regions if region.region_id == "escape:source")
    changed = source.model_copy(update={field: value})
    forged = registry.model_copy(
        update={
            "regions": tuple(
                changed if region.region_id == source.region_id else region
                for region in registry.regions
            )
        }
    )
    with pytest.raises(ValueError, match=message):
        forged.require_authority(bus, certificate, allocation, lanes)


def test_escape_authority_rejects_semantically_changed_live_lane_registry() -> None:
    bus, certificate, allocation, lanes, registry = _escape_fixture()
    changed_geometry = lanes.geometries[0].model_copy(
        update={"entry_portal_id": "portal:stale"}
    )
    changed_lanes = lanes.model_copy(update={"geometries": (changed_geometry,)})
    with pytest.raises(ValueError, match="lane geometry registry fingerprint"):
        registry.require_authority(bus, certificate, allocation, changed_lanes)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("boundary_id", "exit", "not declared"),
        ("terminal_id", "unknown-terminal", "exactly cover"),
        ("portal_id", "portal:wrong", "portal does not match"),
        ("layer", "B.Cu", "portal does not match"),
    ),
)
def test_escape_authority_rejects_wrong_terminal_boundary_portal_or_layer(
    field: str, value: object, message: str
) -> None:
    bus, certificate, allocation, lanes, registry = _escape_fixture()
    source = next(region for region in registry.regions if region.region_id == "escape:source")
    changed = source.model_copy(update={field: value})
    forged = registry.model_copy(
        update={
            "regions": tuple(
                changed if region.region_id == source.region_id else region
                for region in registry.regions
            )
        }
    )
    with pytest.raises(ValueError, match=message):
        forged.require_authority(bus, certificate, allocation, lanes)


@pytest.mark.parametrize("kind", ("node", "portal"))
def test_escape_region_rejects_negative_node_or_portal(kind: str) -> None:
    region = _escape_fixture()[4].regions[0]
    update: dict[str, object] = {
        "allowed_track_nodes": (*region.allowed_track_nodes, (-1, 0))
    }
    if kind == "portal":
        update["portal_point"] = (-1, 0)
    with pytest.raises(ValidationError, match="must be non-negative"):
        CertifiedBusEscapeRegion.model_validate({**region.model_dump(), **update})


def test_escape_lane_registry_fingerprints_require_lowercase_sha256() -> None:
    registry = _escape_fixture()[4]
    region_payload = registry.regions[0].model_dump()
    region_payload["lane_geometry_registry_fingerprint"] = "A" * 64
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        CertifiedBusEscapeRegion.model_validate(region_payload)

    registry_payload = registry.model_dump()
    registry_payload["lane_geometry_registry_fingerprint"] = "A" * 64
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        CertifiedBusEscapeGraphRegistry.model_validate(registry_payload)


def _realize(
    fixture: tuple[
        BusGroup,
        CorridorCapacityCertificate,
        BusLaneAllocationResult,
        CertifiedLaneGeometryRegistry,
    ],
    **kwargs: object,
) -> CertifiedBusTrunkRealization:
    bus, certificate, allocation, registry = fixture
    return realize_certified_trunks(
        bus,
        certificate,
        allocation,
        registry,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("points", "segment_count", "expected_length_mm"),
    (
        (((0, 0), (8, 0)), 1, 4.0),
        (((0, 0), (4, 0), (4, 4)), 2, 4.0),
        (((0, 0), (3, 0), (5, 2), (5, 5)), 3, 3.0 + math.sqrt(2.0)),
    ),
)
def test_realizes_straight_one_bend_and_multi_bend_centerlines(
    points: tuple[tuple[int, int], ...],
    segment_count: int,
    expected_length_mm: float,
) -> None:
    result = _realize(_fixture(one_member=True, points_by_member={"data0": points}))
    trunk = result.trunks[0]

    assert len(trunk.result.segments) == segment_count
    assert trunk.result.vias == ()
    assert trunk.result.expansion_count == 0
    assert trunk.result.length_mm == pytest.approx(expected_length_mm)
    assert {segment.layer for segment in trunk.result.segments} == {"F.Cu"}
    assert {segment.width_mm for segment in trunk.result.segments} == {0.2}
    assert {resource.domain_id for resource in trunk.claims.resources} == {"ordinary"}


def test_straight_bundle_has_literal_geometry_claim_and_result_fingerprints() -> None:
    result = _realize(_fixture())

    assert tuple(trunk.member_id for trunk in result.trunks) == ("data0", "data1")
    assert result.trunks[0].result.segments == (
        TrackSegment(0.0, 0.0, 4.0, 0.0, "F.Cu", "/D0", 0.2),
    )
    assert result.trunks[1].result.segments == (
        TrackSegment(0.0, 1.0, 4.0, 1.0, "F.Cu", "/D1", 0.2),
    )
    assert (
        result.trunks[0].geometry_fingerprint
        == "3667a89d37849bc4b17166bca1f5fbf769e983ca053da489fcc5e601f0b9a852"
    )
    assert (
        result.trunks[0].claims_fingerprint
        == "003bcd7fb5e0b117913e407a2aaa4b19152726981cb4dd59f40a8abf88ab3195"
    )
    assert (
        result.semantic_fingerprint()
        == "7f50715d306290fc8906027bffc0cf5929d7f5e652491cd158c3b22f5a644bc1"
    )


def test_registry_input_order_is_canonical_and_output_invariant() -> None:
    forward_fixture = _fixture()
    reverse_fixture = _fixture(reverse_registry=True)

    assert forward_fixture[3] == reverse_fixture[3]
    assert _realize(forward_fixture) == _realize(reverse_fixture)


def test_pairwise_domains_are_reconstructed_with_ordinary_claims() -> None:
    domain = PairwiseClearanceDomain(
        domain_id="pair:data",
        profile_id="pcbsmith-legacy-default-v1",
        requirement_id="data-bus-coupling",
        net_low="/D0",
        net_high="/D1",
        minimum_clearance_mm=0.3,
    )

    result = _realize(
        _fixture(points_by_member={"data1": ((0, 4), (8, 4))}),
        pairwise_domains=(domain,),
    )

    for trunk in result.trunks:
        assert {resource.domain_id for resource in trunk.claims.resources} == {
            "ordinary",
            "pair:data",
        }


def test_foreign_member_crossing_is_rejected_by_r2_resource_claims() -> None:
    fixture = _fixture(
        points_by_member={
            "data0": ((0, 0), (8, 0)),
            "data1": ((4, -2), (4, 2)),
        }
    )

    with pytest.raises(ValueError, match="foreign bus members overlap"):
        _realize(fixture)


@pytest.mark.parametrize(
    ("points", "keep_in", "message"),
    (
        (((0, 0), (2, 1)), _KEEP_IN, "horizontal, vertical, or 45-degree"),
        (
            ((0, 0), (8, 0)),
            ((-1, -1), (6, -1), (6, 1), (-1, 1)),
            "leaves its certified keep-in",
        ),
        (((0, 0), (2, 0), (4, 0)), _KEEP_IN, "redundant collinear"),
    ),
)
def test_lane_geometry_rejects_unsupported_or_out_of_keep_in_paths(
    points: tuple[tuple[int, int], ...],
    keep_in: tuple[tuple[int, int], ...],
    message: str,
) -> None:
    bus = _bus(one_member=True)
    certificate = _certificate(bus)

    with pytest.raises(ValidationError, match=message):
        _geometry(certificate, bus.members[0], points, keep_in=keep_in)


def test_lane_geometry_rejects_wrong_portal_point_and_keep_in_fingerprint() -> None:
    bus, certificate, _, registry = _fixture(one_member=True)
    geometry = registry.geometries[0]
    with pytest.raises(ValidationError, match="start at its entry portal point"):
        CertifiedLaneGeometry.model_validate(
            {**geometry.model_dump(), "entry_portal_point": (1, 0)}
        )
    with pytest.raises(ValidationError, match="keep_in_fingerprint"):
        CertifiedLaneGeometry.model_validate(
            {**geometry.model_dump(), "keep_in_fingerprint": "0" * 64}
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda geometry: geometry.model_copy(update={"section_id": "wrong"}),
            "section does not match",
        ),
        (
            lambda geometry: geometry.model_copy(update={"layer": "B.Cu"}),
            "layer does not match",
        ),
        (
            lambda geometry: geometry.model_copy(update={"track_width_mm": 0.3}),
            "width does not match",
        ),
        (
            lambda geometry: geometry.model_copy(update={"entry_portal_id": "wrong"}),
            "portal identities do not match",
        ),
    ),
)
def test_realization_rejects_wrong_geometry_assignment_bindings(
    mutate: Callable[[CertifiedLaneGeometry], CertifiedLaneGeometry],
    message: str,
) -> None:
    bus, certificate, allocation, registry = _fixture(one_member=True)
    changed = mutate(registry.geometries[0])
    changed_registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=(changed,),
    )

    with pytest.raises(ValueError, match=message):
        realize_certified_trunks(
            bus,
            certificate,
            allocation,
            changed_registry,
        )


def test_registry_must_exactly_cover_all_assigned_centerlines() -> None:
    bus, certificate, allocation, registry = _fixture()
    missing = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=(registry.geometries[0],),
    )

    with pytest.raises(ValueError, match="exactly cover"):
        realize_certified_trunks(bus, certificate, allocation, missing)


def test_realization_rejects_stale_certificate_and_allocation_registry_bindings() -> None:
    bus, certificate, allocation, registry = _fixture(one_member=True)
    geometry = registry.geometries[0]
    stale_geometry = geometry.model_copy(update={"certificate_fingerprint": "0" * 64})
    stale_certificate = CertifiedLaneGeometryRegistry(
        certificate_fingerprint="0" * 64,
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=(stale_geometry,),
    )
    stale_allocation = registry.model_copy(update={"allocation_fingerprint": "0" * 64})

    with pytest.raises(ValueError, match="certificate fingerprint is stale"):
        realize_certified_trunks(bus, certificate, allocation, stale_certificate)
    with pytest.raises(ValueError, match="allocation fingerprint is stale"):
        realize_certified_trunks(bus, certificate, allocation, stale_allocation)


def test_explicit_grid_claim_domains_are_only_canonical_assertions() -> None:
    fixture = _fixture(one_member=True)
    with pytest.raises(ValueError, match="exactly cover active bus nets"):
        _realize(fixture, claim_domains_by_net={})
    canonical = grid_claim_domains_for_net(
        "/D0",
        fixture[0].members[0].width_mm,
        DEFAULT_PCB_RULE_PROFILE,
    )
    assert _realize(fixture, claim_domains_by_net={"/D0": canonical}).trunks
    with pytest.raises(ValueError, match="exactly match canonical derived domains"):
        _realize(
            fixture,
            claim_domains_by_net={
                "/D0": (GridClaimDomain("ordinary", 0.0, 0.0),),
            },
        )


def test_realization_rejects_a_different_rule_profile_identity() -> None:
    wrong_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(update={"profile_id": "different-profile"})

    with pytest.raises(ValueError, match="rule profile does not match"):
        _realize(_fixture(one_member=True), profile=wrong_profile)


def test_realization_tracks_late_activation_with_a_following_section() -> None:
    trunk = _member("trunk", "/TRUNK")
    late = _member("late", "/LATE")
    bus = BusGroup(
        bus_id="tapped-trunk",
        members=(trunk, late),
        boundaries=(
            BusBoundary(
                boundary_id="entry",
                corridor_portal_id="portal:entry",
                orientation="forward",
                ordered_members=(BoundaryMemberRef(member_id="trunk"),),
            ),
            BusBoundary(
                boundary_id="middle",
                corridor_portal_id="portal:middle",
                orientation="forward",
                ordered_members=(
                    BoundaryMemberRef(member_id="trunk"),
                    BoundaryMemberRef(member_id="late", terminal_ids=("late:source",)),
                ),
            ),
            BusBoundary(
                boundary_id="exit",
                corridor_portal_id="portal:exit",
                orientation="forward",
                ordered_members=(
                    BoundaryMemberRef(member_id="trunk"),
                    BoundaryMemberRef(member_id="late"),
                ),
            ),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        rule_profile_id="pcbsmith-legacy-default-v1",
    )

    def section(index: int, entry: str, exit_: str, slot_count: int) -> CertifiedCorridorSection:
        section_id = f"section:{index}"
        return CertifiedCorridorSection(
            section_id=section_id,
            entry_portal_id=entry,
            exit_portal_id=exit_,
            lane_slots=tuple(
                CertifiedLaneSlot(
                    slot_id=f"{section_id}:slot:{slot_index}",
                    section_id=section_id,
                    layer="F.Cu",
                    order_index=slot_index,
                    centerline_geometry_id=f"{section_id}:centerline:{slot_index}",
                    maximum_track_width_mm=0.4,
                    supported_clearance_domain_ids=("ordinary",),
                )
                for slot_index in range(slot_count)
            ),
        )

    certificate = CorridorCapacityCertificate(
        certificate_id="certificate:tapped-trunk",
        board_geometry_fingerprint="1" * 64,
        static_obstacle_fingerprint="2" * 64,
        rule_profile_fingerprint="3" * 64,
        demand_fingerprint="4" * 64,
        corridor_graph_fingerprint="5" * 64,
        grid_mm=0.5,
        sections=(
            section(0, "portal:entry", "portal:middle", 1),
            section(1, "portal:middle", "portal:exit", 2),
        ),
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    member_by_id = {member.member_id: member for member in bus.members}
    section_by_id = {item.section_id: item for item in certificate.sections}
    slot_by_key = {
        (item.section_id, slot.slot_id): slot
        for item in certificate.sections
        for slot in item.lane_slots
    }
    geometries = []
    for assignment in allocation.assignments:
        section_record = section_by_id[assignment.section_id]
        slot = slot_by_key[(assignment.section_id, assignment.slot_id)]
        section_index = certificate.sections.index(section_record)
        start_x = section_index * 4
        points = (
            (start_x, assignment.order_index * 2),
            (start_x + 4, assignment.order_index * 2),
        )
        geometries.append(
            CertifiedLaneGeometry(
                centerline_geometry_id=slot.centerline_geometry_id,
                certificate_fingerprint=certificate.semantic_fingerprint(),
                section_id=section_record.section_id,
                layer=slot.layer,
                track_width_mm=member_by_id[assignment.member_id].width_mm,
                grid_mm=certificate.grid_mm,
                entry_portal_id=section_record.entry_portal_id,
                exit_portal_id=section_record.exit_portal_id,
                entry_portal_point=points[0],
                exit_portal_point=points[-1],
                points=points,
                keep_in_polygon=_KEEP_IN,
                keep_in_fingerprint=certified_keep_in_fingerprint(certificate.grid_mm, _KEEP_IN),
            )
        )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=tuple(geometries),
    )
    result = realize_certified_trunks(bus, certificate, allocation, registry)
    assert {
        (assignment.section_id, assignment.member_id) for assignment in allocation.assignments
    } == {
        ("section:0", "trunk"),
        ("section:1", "late"),
        ("section:1", "trunk"),
    }
    assert tuple(trunk.member_id for trunk in result.trunks) == ("late", "trunk")
    assert all(trunk.result.segments for trunk in result.trunks)


def test_realization_rejects_layer_change_without_materialized_transition_via() -> None:
    member = _member("trunk", "/TRUNK")
    ref = BoundaryMemberRef(member_id="trunk")
    bus = BusGroup(
        bus_id="layer-transition",
        members=(member,),
        boundaries=tuple(
            BusBoundary(
                boundary_id=boundary_id,
                corridor_portal_id=f"portal:{boundary_id}",
                orientation="forward",
                ordered_members=(ref,),
            )
            for boundary_id in ("entry", "middle", "exit")
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu", "B.Cu"),
            via_policy=BusViaPolicy(mode="independent_bounded", maximum_vias_per_member=1),
        ),
        rule_profile_id="pcbsmith-legacy-default-v1",
    )

    def section(
        section_id: str,
        layer: str,
        entry: str,
        exit_: str,
        transition_windows: tuple[str, ...] = (),
    ) -> CertifiedCorridorSection:
        return CertifiedCorridorSection(
            section_id=section_id,
            entry_portal_id=entry,
            exit_portal_id=exit_,
            lane_slots=(
                CertifiedLaneSlot(
                    slot_id=f"{section_id}:slot",
                    section_id=section_id,
                    layer=layer,
                    order_index=0,
                    centerline_geometry_id=f"{section_id}:centerline",
                    maximum_track_width_mm=0.4,
                    supported_clearance_domain_ids=("ordinary",),
                ),
            ),
            transition_window_ids=transition_windows,
        )

    certificate = CorridorCapacityCertificate(
        certificate_id="certificate:layer-transition",
        board_geometry_fingerprint="6" * 64,
        static_obstacle_fingerprint="7" * 64,
        rule_profile_fingerprint="8" * 64,
        demand_fingerprint="9" * 64,
        corridor_graph_fingerprint="a" * 64,
        grid_mm=0.5,
        sections=(
            section(
                "section:front",
                "F.Cu",
                "portal:entry",
                "portal:middle",
                ("via-window",),
            ),
            section("section:back", "B.Cu", "portal:middle", "portal:exit"),
        ),
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    geometries = []
    for index, section_record in enumerate(certificate.sections):
        slot = section_record.lane_slots[0]
        points = ((index * 4, 0), ((index + 1) * 4, 0))
        geometries.append(
            CertifiedLaneGeometry(
                centerline_geometry_id=slot.centerline_geometry_id,
                certificate_fingerprint=certificate.semantic_fingerprint(),
                section_id=section_record.section_id,
                layer=slot.layer,
                track_width_mm=member.width_mm,
                grid_mm=certificate.grid_mm,
                entry_portal_id=section_record.entry_portal_id,
                exit_portal_id=section_record.exit_portal_id,
                entry_portal_point=points[0],
                exit_portal_point=points[-1],
                points=points,
                keep_in_polygon=_KEEP_IN,
                keep_in_fingerprint=certified_keep_in_fingerprint(certificate.grid_mm, _KEEP_IN),
            )
        )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=tuple(geometries),
    )
    with pytest.raises(ValueError, match="changes layer without a realized transition via"):
        realize_certified_trunks(bus, certificate, allocation, registry)


@pytest.mark.parametrize(
    ("keep_in", "points", "message"),
    (
        (
            ((0, 0), (4, 4), (0, 4), (4, 0), (6, 0), (6, 6), (0, 6)),
            ((1, 1), (2, 2)),
            "simple and non-self-intersecting",
        ),
        (
            ((0, 0), (6, 0), (6, 6), (4, 6), (4, 2), (2, 2), (2, 6), (0, 6)),
            ((1, 4), (5, 4)),
            "leaves its certified keep-in",
        ),
        (
            ((0, 0), (3, 1), (3, 3), (0, 3)),
            ((1, 1), (2, 1)),
            "keep-in polygon edges must be horizontal, vertical, or 45-degree",
        ),
    ),
)
def test_lane_geometry_rejects_ambiguous_or_escaping_keep_in_geometry(
    keep_in: tuple[tuple[int, int], ...],
    points: tuple[tuple[int, int], ...],
    message: str,
) -> None:
    bus = _bus(one_member=True)
    certificate = _certificate(bus)
    with pytest.raises(ValidationError, match=message):
        _geometry(certificate, bus.members[0], points, keep_in=keep_in)


def test_realized_trunk_fingerprints_are_self_verifying() -> None:
    trunk = _realize(_fixture(one_member=True)).trunks[0]
    common = {
        "member_id": trunk.member_id,
        "centerline_geometry_ids": trunk.centerline_geometry_ids,
        "result": trunk.result,
        "claims": trunk.claims,
    }
    with pytest.raises(ValueError, match="geometry_fingerprint must match"):
        RealizedCertifiedTrunk(
            **common,
            geometry_fingerprint="0" * 64,
            claims_fingerprint=trunk.claims_fingerprint,
        )
    with pytest.raises(ValueError, match="claims_fingerprint must match"):
        RealizedCertifiedTrunk(
            **common,
            geometry_fingerprint=trunk.geometry_fingerprint,
            claims_fingerprint="0" * 64,
        )
