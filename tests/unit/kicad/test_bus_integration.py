from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from pydantic import ValidationError

from pcbsmith.bus_allocator import BusLaneAllocationResult, allocate_bus_lanes
from pcbsmith.bus_geometry import (
    CertifiedBusTrunkRealization,
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
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
from pcbsmith.kicad.bus_integration import (
    CertifiedBusMemberPrefix,
    CertifiedBusPigtail,
    CertifiedBusTransitionVia,
    compose_member_route_prefix,
)
from pcbsmith.mask_geometry import ViaMaskIntent
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

_KEEP_IN = ((0, 0), (12, 0), (12, 4), (0, 4))
_PAD_SOURCES = {
    "data0:source": "physical-pad:source",
    "data0:sink": "physical-pad:sink",
}


@dataclass(frozen=True)
class _Fixture:
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    registry: CertifiedLaneGeometryRegistry
    realization: CertifiedBusTrunkRealization | None


def _member(*, source_role: str = "source") -> BusMember:
    return BusMember(
        member_id="data0",
        net_name="/D0",
        terminals=(
            BusTerminalRef(
                terminal_id="data0:source",
                net_name="/D0",
                component_ref="U1",
                pad_number="1",
                role=source_role,
            ),
            BusTerminalRef(
                terminal_id="data0:sink",
                net_name="/D0",
                component_ref="J1",
                pad_number="1",
                role="sink",
            ),
        ),
        width_mm=0.2,
    )


def _boundary(
    boundary_id: str,
    portal_id: str,
    member: BusMember,
    terminal_ids: tuple[str, ...] = (),
    *,
    active: bool = True,
) -> BusBoundary:
    refs = (
        (BoundaryMemberRef(member_id=member.member_id, terminal_ids=terminal_ids),)
        if active
        else ()
    )
    return BusBoundary(
        boundary_id=boundary_id,
        corridor_portal_id=portal_id,
        orientation="forward",
        ordered_members=refs,
    )


def _slot(
    section_id: str,
    geometry_id: str,
    layer: str,
) -> CertifiedLaneSlot:
    return CertifiedLaneSlot(
        slot_id=f"slot:{section_id}",
        section_id=section_id,
        layer=layer,
        order_index=0,
        centerline_geometry_id=geometry_id,
        maximum_track_width_mm=0.4,
        supported_clearance_domain_ids=("ordinary",),
    )


def _certificate(
    sections: tuple[CertifiedCorridorSection, ...],
) -> CorridorCapacityCertificate:
    return CorridorCapacityCertificate(
        certificate_id="certificate:bus",
        board_geometry_fingerprint="a" * 64,
        static_obstacle_fingerprint="b" * 64,
        rule_profile_fingerprint="c" * 64,
        demand_fingerprint="d" * 64,
        corridor_graph_fingerprint="e" * 64,
        grid_mm=0.5,
        sections=sections,
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )


def _geometry(
    certificate: CorridorCapacityCertificate,
    geometry_id: str,
    section_id: str,
    layer: str,
    entry_portal_id: str,
    exit_portal_id: str,
    points: tuple[tuple[int, int], ...],
) -> CertifiedLaneGeometry:
    return CertifiedLaneGeometry(
        centerline_geometry_id=geometry_id,
        certificate_fingerprint=certificate.semantic_fingerprint(),
        section_id=section_id,
        layer=layer,
        track_width_mm=0.2,
        grid_mm=certificate.grid_mm,
        entry_portal_id=entry_portal_id,
        exit_portal_id=exit_portal_id,
        entry_portal_point=points[0],
        exit_portal_point=points[-1],
        points=points,
        keep_in_polygon=_KEEP_IN,
        keep_in_fingerprint=certified_keep_in_fingerprint(
            certificate.grid_mm,
            _KEEP_IN,
        ),
    )


def _straight_fixture() -> _Fixture:
    member = _member()
    bus = BusGroup(
        bus_id="display-data",
        members=(member,),
        boundaries=(
            _boundary(
                "entry",
                "portal:entry",
                member,
                ("data0:source",),
            ),
            _boundary(
                "exit",
                "portal:exit",
                member,
                ("data0:sink",),
            ),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )
    certificate = _certificate(
        (
            CertifiedCorridorSection(
                section_id="trunk",
                entry_portal_id="portal:entry",
                exit_portal_id="portal:exit",
                lane_slots=(_slot("trunk", "centerline:trunk", "F.Cu"),),
            ),
        )
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=(
            _geometry(
                certificate,
                "centerline:trunk",
                "trunk",
                "F.Cu",
                "portal:entry",
                "portal:exit",
                ((2, 2), (8, 2)),
            ),
        ),
    )
    realization = realize_certified_trunks(bus, certificate, allocation, registry)
    return _Fixture(bus, certificate, allocation, registry, realization)


def _pigtail(
    fixture: _Fixture,
    terminal_id: str,
    boundary_id: str,
    geometry_id: str,
    portal_kind: str,
    layer: str,
    points: tuple[tuple[int, int], ...],
) -> CertifiedBusPigtail:
    return CertifiedBusPigtail(
        pigtail_id=f"pigtail:{terminal_id}",
        bus_fingerprint=fixture.bus.semantic_fingerprint(),
        certificate_fingerprint=fixture.certificate.semantic_fingerprint(),
        allocation_fingerprint=fixture.allocation.allocation_fingerprint,
        geometry_registry_fingerprint=fixture.registry.semantic_fingerprint(),
        member_id="data0",
        net_name="/D0",
        terminal_id=terminal_id,
        boundary_id=boundary_id,
        assigned_geometry_id=geometry_id,
        portal_kind=portal_kind,
        physical_pad_source_id=_PAD_SOURCES[terminal_id],
        grid_mm=fixture.certificate.grid_mm,
        layer=layer,
        pad_anchor_point=points[0],
        portal_point=points[-1],
        points=points,
    )


def _straight_pigtails(
    fixture: _Fixture,
) -> tuple[CertifiedBusPigtail, CertifiedBusPigtail]:
    return (
        _pigtail(
            fixture,
            "data0:source",
            "entry",
            "centerline:trunk",
            "entry",
            "F.Cu",
            ((0, 2), (2, 2)),
        ),
        _pigtail(
            fixture,
            "data0:sink",
            "exit",
            "centerline:trunk",
            "exit",
            "F.Cu",
            ((10, 2), (8, 2)),
        ),
    )


def _compose(
    fixture: _Fixture,
    pigtails: tuple[CertifiedBusPigtail, ...] | None = None,
    transitions: tuple[CertifiedBusTransitionVia, ...] = (),
    pad_sources: dict[str, str] | None = None,
):
    return compose_member_route_prefix(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
        fixture.realization,
        "data0",
        pigtails or _straight_pigtails(fixture),
        transitions,
        pad_sources or _PAD_SOURCES,
    )


def test_straight_all_pad_prefix_is_deterministic_and_literal() -> None:
    fixture = _straight_fixture()
    pigtails = _straight_pigtails(fixture)
    certified = _compose(fixture, pigtails)
    reversed_certified = _compose(fixture, tuple(reversed(pigtails)))
    prefix = certified.prefix

    assert certified == reversed_certified
    certified.require_authority(
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.registry,
    )
    assert certified.net_name == "/D0"
    assert prefix.net_name == "/D0"
    assert prefix.grid_mm == 0.5
    assert prefix.covered_pad_anchors == (
        ("physical-pad:sink", ("F.Cu", 10, 2)),
        ("physical-pad:source", ("F.Cu", 0, 2)),
    )
    assert prefix.vias == ()
    assert prefix.segments == (
        TrackSegment(0.0, 1.0, 1.0, 1.0, "F.Cu", "/D0", 0.2),
        TrackSegment(1.0, 1.0, 4.0, 1.0, "F.Cu", "/D0", 0.2),
        TrackSegment(4.0, 1.0, 5.0, 1.0, "F.Cu", "/D0", 0.2),
    )
    assert certified.schema_id == "pcbsmith-certified-bus-member-prefix"
    assert certified.schema_version == 1
    assert certified.authority_kind == "same_layer_trunk"
    assert certified.authority_claims_fingerprint is not None
    assert certified.active_geometry_ids == ("centerline:trunk",)
    assert certified.terminal_pad_sources == (
        ("data0:sink", "physical-pad:sink"),
        ("data0:source", "physical-pad:source"),
    )
    assert (
        certified.composition_fingerprint
        == "c83d97bc2a1d7785ec218c0e3131272aa8fe4fb15c81066fd70371b2b67388bd"
    )
    assert prefix.alternative_id == (
        "bus-member-prefix:data0:c83d97bc2a1d7785ec218c0e3131272aa8fe4fb15c81066fd70371b2b67388bd"
    )
    assert (
        certified.prefix_fingerprint
        == "51914b45717e9739c3bb98c97606e8c7f137161c1b9e25a2f7104b21a1da455e"
    )
    assert prefix.semantic_fingerprint() == certified.prefix_fingerprint
    assert (
        certified.semantic_fingerprint()
        == "5a9a4283a85ddbabfe37b507c4688738d6ff4dc00220ebeacd195409b75304fe"
    )


def test_pigtail_carrier_is_frozen_versioned_and_rejects_bad_paths() -> None:
    fixture = _straight_fixture()
    pigtail = _straight_pigtails(fixture)[0]

    assert pigtail.schema_id == "pcbsmith-certified-bus-pigtail"
    assert pigtail.schema_version == 1
    with pytest.raises(ValidationError, match="frozen"):
        pigtail.member_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        CertifiedBusPigtail.model_validate({**pigtail.model_dump(), "bus_fingerprint": "A" * 64})
    diagonal = CertifiedBusPigtail.model_validate(
        {
            **pigtail.model_dump(),
            "pad_anchor_point": (0, 0),
            "points": ((0, 0), (2, 2)),
        }
    )
    assert diagonal.points == ((0, 0), (2, 2))
    with pytest.raises(ValidationError, match="horizontal, vertical, or 45-degree"):
        CertifiedBusPigtail.model_validate(
            {
                **pigtail.model_dump(),
                "portal_point": (2, 1),
                "points": ((0, 2), (2, 1)),
            }
        )


def test_certified_wrapper_rejects_forged_authority_identity_and_copper() -> None:
    fixture = _straight_fixture()
    certified = _compose(fixture, _straight_pigtails(fixture))

    with pytest.raises(ValidationError, match="frozen"):
        certified.member_id = "changed"  # type: ignore[misc]
    stale_bus = fixture.bus.model_copy(update={"bus_id": "stale"})
    with pytest.raises(ValueError, match="authority binding is stale"):
        certified.require_authority(
            stale_bus,
            fixture.certificate,
            fixture.allocation,
            fixture.registry,
        )

    reordered = certified.model_dump()
    reordered["pigtail_fingerprints"] = tuple(reversed(reordered["pigtail_fingerprints"]))
    reordered["terminal_pad_sources"] = tuple(reversed(reordered["terminal_pad_sources"]))
    assert CertifiedBusMemberPrefix.model_validate(reordered) == certified

    wrong_geometry = certified.model_dump()
    wrong_geometry["active_geometry_ids"] = ("centerline:forged",)
    with pytest.raises(ValidationError, match="composition fingerprint is invalid"):
        CertifiedBusMemberPrefix.model_validate(wrong_geometry)

    wrong_alternative = certified.model_dump()
    wrong_alternative["prefix"]["alternative_id"] = "bus-member-prefix:data0:forged"
    with pytest.raises(ValidationError, match="alternative identity"):
        CertifiedBusMemberPrefix.model_validate(wrong_alternative)

    wrong_prefix_fingerprint = certified.model_dump()
    wrong_prefix_fingerprint["prefix_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="semantic fingerprint is invalid"):
        CertifiedBusMemberPrefix.model_validate(wrong_prefix_fingerprint)

    changed_copper = certified.model_dump()
    changed_copper["prefix"]["segments"][0]["width_mm"] = 0.3
    with pytest.raises(ValidationError, match="composition fingerprint is invalid"):
        CertifiedBusMemberPrefix.model_validate(changed_copper)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda item: item.model_copy(update={"assigned_geometry_id": "wrong"}),
            "lane not assigned",
        ),
        (
            lambda item: item.model_copy(update={"physical_pad_source_id": "wrong-pad"}),
            "physical pad source",
        ),
        (
            lambda item: item.model_copy(update={"certificate_fingerprint": "0" * 64}),
            "fingerprint binding is stale",
        ),
        (
            lambda item: item.model_copy(update={"portal_point": (3, 2)}),
            "endpoint does not match",
        ),
        (
            lambda item: item.model_copy(update={"layer": "B.Cu"}),
            "layer does not match",
        ),
    ),
)
def test_wrong_lane_pad_or_authority_binding_is_rejected(mutate, message: str) -> None:
    fixture = _straight_fixture()
    source, sink = _straight_pigtails(fixture)

    with pytest.raises(ValueError, match=message):
        _compose(fixture, (mutate(source), sink))


def test_missing_duplicate_extra_pigtails_and_pad_maps_are_rejected() -> None:
    fixture = _straight_fixture()
    source, sink = _straight_pigtails(fixture)
    extra = source.model_copy(
        update={
            "pigtail_id": "extra",
            "terminal_id": "extra-terminal",
            "physical_pad_source_id": "extra-pad",
        }
    )

    with pytest.raises(ValueError, match="exactly cover required terminals"):
        _compose(fixture, (source,))
    with pytest.raises(ValueError, match="unique per terminal"):
        _compose(fixture, (source, source, sink))
    with pytest.raises(ValueError, match="exactly cover required terminals"):
        _compose(fixture, (source, sink, extra))
    with pytest.raises(ValueError, match="exactly cover member terminals"):
        _compose(fixture, (source, sink), pad_sources={"data0:source": "only-pad"})


def _late_activation_fixture() -> _Fixture:
    member = _member(source_role="tap")
    bus = BusGroup(
        bus_id="late-data",
        members=(member,),
        boundaries=(
            _boundary("before", "portal:before", member, active=False),
            _boundary(
                "activate",
                "portal:activate",
                member,
                ("data0:source",),
            ),
            _boundary(
                "finish",
                "portal:finish",
                member,
                ("data0:sink",),
            ),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )
    certificate = _certificate(
        (
            CertifiedCorridorSection(
                section_id="empty",
                entry_portal_id="portal:before",
                exit_portal_id="portal:activate",
                lane_slots=(_slot("empty", "unused", "F.Cu"),),
            ),
            CertifiedCorridorSection(
                section_id="active",
                entry_portal_id="portal:activate",
                exit_portal_id="portal:finish",
                lane_slots=(_slot("active", "centerline:active", "F.Cu"),),
            ),
        )
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    assert tuple(item.section_id for item in allocation.assignments) == ("active",)
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=(
            _geometry(
                certificate,
                "centerline:active",
                "active",
                "F.Cu",
                "portal:activate",
                "portal:finish",
                ((2, 2), (8, 2)),
            ),
        ),
    )
    realization = realize_certified_trunks(bus, certificate, allocation, registry)
    return _Fixture(bus, certificate, allocation, registry, realization)


def test_late_activation_prefix_uses_only_active_assigned_sections() -> None:
    fixture = _late_activation_fixture()
    pigtails = (
        _pigtail(
            fixture,
            "data0:source",
            "activate",
            "centerline:active",
            "entry",
            "F.Cu",
            ((0, 2), (2, 2)),
        ),
        _pigtail(
            fixture,
            "data0:sink",
            "finish",
            "centerline:active",
            "exit",
            "F.Cu",
            ((10, 2), (8, 2)),
        ),
    )

    certified = _compose(fixture, pigtails)

    assert fixture.realization.trunks[0].centerline_geometry_ids == ("centerline:active",)
    assert all("unused" not in str(segment) for segment in certified.prefix.segments)
    assert fixture.allocation.activation_count == 1


def _transition_fixture() -> tuple[_Fixture, CertifiedBusTransitionVia]:
    member = _member()
    bus = BusGroup(
        bus_id="transition-data",
        members=(member,),
        boundaries=(
            _boundary("entry", "portal:entry", member, ("data0:source",)),
            _boundary("middle", "portal:middle", member),
            _boundary("exit", "portal:exit", member, ("data0:sink",)),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu", "B.Cu"),
            via_policy=BusViaPolicy(
                mode="synchronous",
                transition_window_ids=("transition:a",),
                maximum_vias_per_member=1,
                maximum_via_count_spread=0,
            ),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )
    certificate = _certificate(
        (
            CertifiedCorridorSection(
                section_id="front",
                entry_portal_id="portal:entry",
                exit_portal_id="portal:middle",
                lane_slots=(_slot("front", "centerline:front", "F.Cu"),),
                transition_window_ids=("transition:a",),
            ),
            CertifiedCorridorSection(
                section_id="back",
                entry_portal_id="portal:middle",
                exit_portal_id="portal:exit",
                lane_slots=(_slot("back", "centerline:back", "B.Cu"),),
            ),
        )
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    assert allocation.layer_transition_count == 1
    front = _geometry(
        certificate,
        "centerline:front",
        "front",
        "F.Cu",
        "portal:entry",
        "portal:middle",
        ((2, 2), (5, 2)),
    )
    back = _geometry(
        certificate,
        "centerline:back",
        "back",
        "B.Cu",
        "portal:middle",
        "portal:exit",
        ((5, 2), (8, 2)),
    )
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=certificate.grid_mm,
        geometries=(back, front),
    )
    fixture = _Fixture(bus, certificate, allocation, registry, None)
    event = allocation.layer_transitions[0]
    carrier = CertifiedBusTransitionVia(
        transition_via_id="transition-via:data0:middle",
        bus_fingerprint=bus.semantic_fingerprint(),
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        geometry_registry_fingerprint=registry.semantic_fingerprint(),
        member_id="data0",
        net_name="/D0",
        section_id=event.section_id,
        boundary_id=event.boundary_id,
        window_id=event.window_id,
        from_layer=event.from_layer,
        to_layer=event.to_layer,
        before_geometry_id="centerline:front",
        after_geometry_id="centerline:back",
        grid_mm=certificate.grid_mm,
        point=(5, 2),
    )
    return fixture, carrier


def _transition_pigtails(
    fixture: _Fixture,
) -> tuple[CertifiedBusPigtail, CertifiedBusPigtail]:
    return (
        _pigtail(
            fixture,
            "data0:source",
            "entry",
            "centerline:front",
            "entry",
            "F.Cu",
            ((0, 2), (2, 2)),
        ),
        _pigtail(
            fixture,
            "data0:sink",
            "exit",
            "centerline:back",
            "exit",
            "B.Cu",
            ((10, 2), (8, 2)),
        ),
    )


def test_declared_transition_via_is_profile_derived_and_connects_layers() -> None:
    fixture, carrier = _transition_fixture()
    certified = _compose(fixture, _transition_pigtails(fixture), (carrier,))
    prefix = certified.prefix

    assert len(prefix.vias) == 1
    via = prefix.vias[0]
    assert (via.x, via.y, via.net_name) == (2.5, 1.0, "/D0")
    assert via.size_mm == DEFAULT_PCB_RULE_PROFILE.geometry.routing_via_diameter_mm
    assert via.drill_mm == DEFAULT_PCB_RULE_PROFILE.geometry.routing_via_drill_mm
    assert via.front_mask is ViaMaskIntent.INHERIT
    assert via.back_mask is ViaMaskIntent.INHERIT
    assert prefix.segments == (
        TrackSegment(2.5, 1.0, 4.0, 1.0, "B.Cu", "/D0", 0.2),
        TrackSegment(4.0, 1.0, 5.0, 1.0, "B.Cu", "/D0", 0.2),
        TrackSegment(0.0, 1.0, 1.0, 1.0, "F.Cu", "/D0", 0.2),
        TrackSegment(1.0, 1.0, 2.5, 1.0, "F.Cu", "/D0", 0.2),
    )
    assert certified.authority_kind == "transition_fragments"
    assert certified.authority_claims_fingerprint is None
    assert certified.active_geometry_ids == ("centerline:front", "centerline:back")
    assert (
        certified.composition_fingerprint
        == "8de4e785e9f68ef64aac1765de86041fa6af57cad1c05f8a1619a30d5694d331"
    )
    assert prefix.alternative_id == (
        "bus-member-prefix:data0:8de4e785e9f68ef64aac1765de86041fa6af57cad1c05f8a1619a30d5694d331"
    )
    assert (
        certified.prefix_fingerprint
        == "5ecf622f5b2f303f97aff2b23173045efdff4295f7e8def3615abb580029a36a"
    )
    assert (
        certified.semantic_fingerprint()
        == "2a112fe7935f3d8da0f1c5cbdc0d20aaa59e8fc06feb7176667dd326613314fc"
    )
    assert carrier.schema_id == "pcbsmith-certified-bus-transition-via"
    assert carrier.schema_version == 1
    with pytest.raises(ValidationError, match="frozen"):
        carrier.point = (4, 2)  # type: ignore[misc]


def test_trunk_authority_paths_are_explicit() -> None:
    straight = _straight_fixture()
    with pytest.raises(ValueError, match="requires a certified complete trunk"):
        _compose(replace(straight, realization=None))

    transition, carrier = _transition_fixture()
    with pytest.raises(ValueError, match="must use certified section fragments"):
        _compose(
            replace(transition, realization=straight.realization),
            _transition_pigtails(transition),
            (carrier,),
        )


def test_missing_extra_and_wrong_transition_vias_are_rejected() -> None:
    fixture, carrier = _transition_fixture()
    pigtails = _transition_pigtails(fixture)

    with pytest.raises(ValueError, match="exactly cover declared"):
        _compose(fixture, pigtails, ())
    with pytest.raises(ValueError, match="unique per allocation event"):
        _compose(fixture, pigtails, (carrier, carrier))
    with pytest.raises(ValueError, match="shared assigned portal"):
        _compose(fixture, pigtails, (carrier.model_copy(update={"point": (4, 2)}),))

    straight = _straight_fixture()
    with pytest.raises(ValueError, match="forbids corridor transition"):
        _compose(straight, transitions=(carrier,))


@pytest.mark.parametrize("mode", ("forbidden", "escape_only"))
def test_corridor_transition_events_are_rejected_by_non_corridor_via_policies(
    mode: str,
) -> None:
    fixture, carrier = _transition_fixture()
    via_policy = (
        BusViaPolicy(mode="forbidden")
        if mode == "forbidden"
        else BusViaPolicy(
            mode="escape_only",
            maximum_vias_per_member=1,
        )
    )
    layer_policy = fixture.bus.layer_policy.model_copy(
        update={"via_policy": via_policy}
    )
    forbidden_fixture = replace(
        fixture,
        bus=fixture.bus.model_copy(update={"layer_policy": layer_policy}),
    )

    with pytest.raises(ValueError, match="forbids corridor transition"):
        _compose(
            forbidden_fixture,
            _transition_pigtails(fixture),
            (carrier,),
        )
