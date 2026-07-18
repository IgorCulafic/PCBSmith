from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

import pytest

import pcbsmith.kicad.bus_candidate as bus_candidate
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
from pcbsmith.kicad.astar_router import RouteResult, RoutingError
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.bus_candidate import (
    BusCandidateBudget,
    BusCandidateCallerOveruseMode,
    BusCandidateFailureReason,
    BusCandidatePolicy,
    build_certified_bus_candidate,
    materialize_bus_bundle,
)
from pcbsmith.kicad.bus_integration import (
    CertifiedBusMemberPrefix,
    CertifiedBusPigtail,
    compose_member_route_prefix,
)
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.routing_ir import RoutingFailureReason
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    OrdinaryClearanceRequirement,
)

GRID_MM = 1.0
TRACK_WIDTH_MM = 0.4
RESISTOR = "Resistor_SMD:R_0603_1608Metric"
DEFAULT_BUDGET = BusCandidateBudget(
    max_members=2,
    max_expansions_per_member=10_000,
    max_total_expansions=20_000,
)


def _member(member_id: str, net_name: str, source_ref: str, sink_ref: str) -> BusMember:
    return BusMember(
        member_id=member_id,
        net_name=net_name,
        terminals=(
            BusTerminalRef(
                terminal_id=f"{member_id}:source",
                net_name=net_name,
                component_ref=source_ref,
                pad_number="2",
                role="source",
            ),
            BusTerminalRef(
                terminal_id=f"{member_id}:sink",
                net_name=net_name,
                component_ref=sink_ref,
                pad_number="1",
                role="sink",
            ),
        ),
        width_mm=TRACK_WIDTH_MM,
    )


def _authority() -> tuple[
    BusGroup,
    CorridorCapacityCertificate,
    BusLaneAllocationResult,
    CertifiedLaneGeometryRegistry,
    CertifiedBusTrunkRealization,
]:
    data0 = _member("data0", "/A", "R1", "R2")
    data1 = _member("data1", "/B", "R3", "R4")
    bus = BusGroup(
        bus_id="two-member",
        members=(data1, data0),
        boundaries=(
            BusBoundary(
                boundary_id="entry",
                corridor_portal_id="portal:entry",
                orientation="forward",
                ordered_members=(
                    BoundaryMemberRef(
                        member_id="data0",
                        terminal_ids=("data0:source",),
                    ),
                    BoundaryMemberRef(
                        member_id="data1",
                        terminal_ids=("data1:source",),
                    ),
                ),
            ),
            BusBoundary(
                boundary_id="exit",
                corridor_portal_id="portal:exit",
                orientation="forward",
                ordered_members=(
                    BoundaryMemberRef(member_id="data0", terminal_ids=("data0:sink",)),
                    BoundaryMemberRef(member_id="data1", terminal_ids=("data1:sink",)),
                ),
            ),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        rule_profile_id=DEFAULT_PCB_RULE_PROFILE.profile_id,
    )
    certificate = CorridorCapacityCertificate(
        certificate_id="certificate:two-member",
        board_geometry_fingerprint="a" * 64,
        static_obstacle_fingerprint="b" * 64,
        rule_profile_fingerprint="c" * 64,
        demand_fingerprint="d" * 64,
        corridor_graph_fingerprint="e" * 64,
        grid_mm=GRID_MM,
        sections=(
            CertifiedCorridorSection(
                section_id="trunk",
                entry_portal_id="portal:entry",
                exit_portal_id="portal:exit",
                lane_slots=(
                    CertifiedLaneSlot(
                        slot_id="slot:0",
                        section_id="trunk",
                        layer="F.Cu",
                        order_index=0,
                        centerline_geometry_id="centerline:0",
                        maximum_track_width_mm=TRACK_WIDTH_MM,
                        supported_clearance_domain_ids=("ordinary",),
                    ),
                    CertifiedLaneSlot(
                        slot_id="slot:1",
                        section_id="trunk",
                        layer="F.Cu",
                        order_index=1,
                        centerline_geometry_id="centerline:1",
                        maximum_track_width_mm=TRACK_WIDTH_MM,
                        supported_clearance_domain_ids=("ordinary",),
                    ),
                ),
            ),
        ),
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )
    allocation = allocate_bus_lanes(bus, certificate)
    assert allocation.success
    keep_in = ((0, 0), (30, 0), (30, 17), (0, 17))
    keep_in_fingerprint = certified_keep_in_fingerprint(GRID_MM, keep_in)
    registry = CertifiedLaneGeometryRegistry(
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        grid_mm=GRID_MM,
        geometries=tuple(
            CertifiedLaneGeometry(
                centerline_geometry_id=f"centerline:{index}",
                certificate_fingerprint=certificate.semantic_fingerprint(),
                section_id="trunk",
                layer="F.Cu",
                track_width_mm=TRACK_WIDTH_MM,
                grid_mm=GRID_MM,
                entry_portal_id="portal:entry",
                exit_portal_id="portal:exit",
                entry_portal_point=(8, y),
                exit_portal_point=(22, y),
                points=((8, y), (22, y)),
                keep_in_polygon=keep_in,
                keep_in_fingerprint=keep_in_fingerprint,
            )
            for index, y in enumerate((4, 13))
        ),
    )
    realization = realize_certified_trunks(bus, certificate, allocation, registry)
    return bus, certificate, allocation, registry, realization


def _layout_and_netlist() -> tuple[BoardLayout, BoardNetlist]:
    components = tuple(
        BoardComponent(reference, "1k", RESISTOR, reference.lower())
        for reference in ("R1", "R2", "R3", "R4")
    )
    layout = BoardLayout(
        placements=(
            (components[0], 5.0),
            (components[1], 25.0),
            (components[2], 5.0),
            (components[3], 25.0),
        ),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=18.0,
        parts_row_y_mm=4.0,
        part_y_mm=(("R1", 4.0), ("R2", 4.0), ("R3", 13.0), ("R4", 13.0)),
    )
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet("/A", (("R1", "2"), ("R2", "1"))),
            BoardNet("/B", (("R3", "2"), ("R4", "1"))),
        ),
    )
    return layout, netlist


def _pigtail(
    authority: tuple[
        BusGroup,
        CorridorCapacityCertificate,
        BusLaneAllocationResult,
        CertifiedLaneGeometryRegistry,
        CertifiedBusTrunkRealization,
    ],
    *,
    member_id: str,
    net_name: str,
    terminal_id: str,
    boundary_id: str,
    geometry_id: str,
    portal_kind: str,
    source_id: str,
    points: tuple[tuple[int, int], ...],
) -> CertifiedBusPigtail:
    bus, certificate, allocation, registry, _realization = authority
    return CertifiedBusPigtail(
        pigtail_id=f"pigtail:{terminal_id}",
        bus_fingerprint=bus.semantic_fingerprint(),
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        geometry_registry_fingerprint=registry.semantic_fingerprint(),
        member_id=member_id,
        net_name=net_name,
        terminal_id=terminal_id,
        boundary_id=boundary_id,
        assigned_geometry_id=geometry_id,
        portal_kind=portal_kind,
        physical_pad_source_id=source_id,
        grid_mm=GRID_MM,
        layer="F.Cu",
        pad_anchor_point=points[0],
        portal_point=points[-1],
        points=points,
    )


def _prefixes(
    authority: tuple[
        BusGroup,
        CorridorCapacityCertificate,
        BusLaneAllocationResult,
        CertifiedLaneGeometryRegistry,
        CertifiedBusTrunkRealization,
    ],
    *,
    reverse: bool = False,
) -> dict[str, CertifiedBusMemberPrefix]:
    bus, certificate, allocation, registry, realization = authority
    specifications = (
        ("data0", "/A", 4, "centerline:0", "pad:R1:1", "pad:R2:0"),
        ("data1", "/B", 13, "centerline:1", "pad:R3:1", "pad:R4:0"),
    )
    entries: list[tuple[str, CertifiedBusMemberPrefix]] = []
    for member_id, net_name, y, geometry_id, source_id, sink_id in specifications:
        source_terminal = f"{member_id}:source"
        sink_terminal = f"{member_id}:sink"
        pigtails = (
            _pigtail(
                authority,
                member_id=member_id,
                net_name=net_name,
                terminal_id=source_terminal,
                boundary_id="entry",
                geometry_id=geometry_id,
                portal_kind="entry",
                source_id=source_id,
                points=((6, y), (8, y)),
            ),
            _pigtail(
                authority,
                member_id=member_id,
                net_name=net_name,
                terminal_id=sink_terminal,
                boundary_id="exit",
                geometry_id=geometry_id,
                portal_kind="exit",
                source_id=sink_id,
                points=((24, y), (22, y)),
            ),
        )
        prefix = compose_member_route_prefix(
            bus,
            certificate,
            allocation,
            registry,
            realization,
            member_id,
            pigtails,
            (),
            {source_terminal: source_id, sink_terminal: sink_id},
        )
        entries.append((member_id, prefix))
    return dict(reversed(entries) if reverse else entries)


def _build(
    *,
    ledger: OccupancyLedger | None = None,
    budget: BusCandidateBudget = DEFAULT_BUDGET,
    prefixes: dict[str, CertifiedBusMemberPrefix] | None = None,
    allocation: BusLaneAllocationResult | None = None,
    profile: Any = DEFAULT_PCB_RULE_PROFILE,
    policy: BusCandidatePolicy | None = None,
    present_factor_units: int = 0,
) -> Any:
    authority = _authority()
    bus, certificate, actual_allocation, registry, _realization = authority
    layout, netlist = _layout_and_netlist()
    return build_certified_bus_candidate(
        layout,
        netlist,
        bus,
        certificate,
        actual_allocation if allocation is None else allocation,
        registry,
        _prefixes(authority) if prefixes is None else prefixes,
        OccupancyLedger() if ledger is None else ledger,
        budget,
        policy=BusCandidatePolicy() if policy is None else policy,
        present_factor_units=present_factor_units,
        profile=profile,
    )


def test_zero_expansion_two_member_candidate_pins_bundle_and_result() -> None:
    result = _build()

    assert result.success
    assert result.complete
    assert result.zero_overuse
    assert result.expansion_count == 0
    assert result.route_order == ("data0", "data1")
    assert result.bundle is not None
    assert (
        result.bundle.semantic_fingerprint()
        == "6c64f9422cdaa125a3efb00d48d1bcd8128b82d8776acd8c891fb85ab20cbd89"
    )
    assert (
        result.semantic_fingerprint()
        == "17938fdae242a948c38dec96b7ad223384e784d6bd3e659249270702faa3c227"
    )


def test_foreign_prefix_collision_fails_on_final_overuse_without_mutation() -> None:
    successful = _build()
    assert successful.bundle is not None
    resource = min(successful.bundle.by_net()["/A"].claims.resources)
    ledger = OccupancyLedger((NetResourceClaims("/FOREIGN", frozenset((resource,))),))
    before = ledger.semantic_fingerprint()

    result = _build(ledger=ledger)

    assert not result.success
    assert result.complete
    assert not result.zero_overuse
    assert result.failure_reason is BusCandidateFailureReason.FINAL_OVERUSE
    assert result.bundle is not None
    assert result.resource_overuse
    assert result.resource_overuse[0].net_names == ("/A", "/FOREIGN")
    assert ledger.semantic_fingerprint() == before


def test_strict_and_negotiation_pre_overuse_modes_are_pinned_and_pure() -> None:
    shared = RoutingResourceKey("ordinary", "F.Cu", "cell", 29, 17)
    ledger = OccupancyLedger(
        (
            NetResourceClaims("/FOREIGN1", frozenset((shared,))),
            NetResourceClaims("/FOREIGN2", frozenset((shared,))),
        )
    )
    before = ledger.semantic_fingerprint()

    strict = _build(ledger=ledger)
    negotiation = _build(
        ledger=ledger,
        policy=BusCandidatePolicy(
            caller_overuse_mode=BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION
        ),
    )

    assert not strict.complete
    assert strict.failure_reason is BusCandidateFailureReason.CALLER_OVERUSE
    assert strict.bundle is None
    assert (
        strict.semantic_fingerprint()
        == "d8c20663780478db630970e90bf2f3944491912b9945534bc7e3acc994e43afa"
    )
    assert negotiation.complete
    assert not negotiation.success
    assert negotiation.failure_reason is BusCandidateFailureReason.FINAL_OVERUSE
    assert negotiation.bundle is not None
    assert (
        negotiation.semantic_fingerprint()
        == "2ee9e1679b6ebd77d52d588a502c566715d7d0be21a5d9952380f8095d7e629b"
    )
    assert ledger.semantic_fingerprint() == before


def _install_expanding_router(monkeypatch: pytest.MonkeyPatch, expansions: dict[str, int]) -> None:
    def fake_route(*args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        net_name = args[2]
        needed = expansions[net_name]
        limit = kwargs["max_expansions"]
        if needed > limit:
            raise RoutingError(
                "fixed expansion limit exhausted",
                reason=RoutingFailureReason.EXPANSION_BUDGET,
                expansion_count=limit,
            )
        prefix = kwargs["route_prefix"]
        member_index = 0 if net_name == "/A" else 1
        resource = RoutingResourceKey("ordinary", "F.Cu", "cell", member_index, 0)
        return NegotiatedGridRoute(
            result=RouteResult(
                net_name=net_name,
                segments=prefix.segments,
                vias=prefix.vias,
                length_mm=18.0,
                expansion_count=needed,
            ),
            claims=NetResourceClaims(net_name, frozenset((resource,))),
            base_cost_units=1,
            congestion_cost_units=0,
            prefix_alternative_id=prefix.alternative_id,
            prefix_fingerprint=prefix.semantic_fingerprint(),
        )

    monkeypatch.setattr(bus_candidate, "route_net_negotiated_candidate", fake_route)


@pytest.mark.parametrize("limit", (0, 2))
def test_per_member_zero_and_one_less_budgets_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
) -> None:
    _install_expanding_router(monkeypatch, {"/A": 3, "/B": 3})
    result = _build(
        budget=BusCandidateBudget(
            max_members=2,
            max_expansions_per_member=limit,
            max_total_expansions=20,
        )
    )

    assert not result.success
    assert result.failure_reason is BusCandidateFailureReason.PER_MEMBER_EXPANSION_BUDGET
    assert result.failed_member_id == "data0"
    assert result.expansion_count == limit


@pytest.mark.parametrize("limit", (0, 4))
def test_total_zero_and_one_less_budgets_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
) -> None:
    _install_expanding_router(monkeypatch, {"/A": 2, "/B": 3})
    result = _build(
        budget=BusCandidateBudget(
            max_members=2,
            max_expansions_per_member=10,
            max_total_expansions=limit,
        )
    )

    assert not result.success
    assert result.failure_reason is BusCandidateFailureReason.TOTAL_EXPANSION_BUDGET
    assert result.failed_member_id == ("data0" if limit == 0 else "data1")
    assert result.expansion_count == limit


def test_late_second_member_failure_does_not_mutate_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_expanding_router(monkeypatch, {"/A": 2, "/B": 3})
    layout, _netlist = _layout_and_netlist()
    foreign = RoutingResourceKey("ordinary", "F.Cu", "cell", 29, 17)
    ledger = OccupancyLedger((NetResourceClaims("/FOREIGN", frozenset((foreign,))),))
    ledger_before = ledger.semantic_fingerprint()
    layout_before = repr(layout)

    result = _build(
        ledger=ledger,
        budget=BusCandidateBudget(
            max_members=2,
            max_expansions_per_member=2,
            max_total_expansions=20,
        ),
    )

    assert not result.success
    assert result.failed_member_id == "data1"
    assert len(result.member_telemetry) == 2
    assert result.member_telemetry[0].routed
    assert not result.member_telemetry[1].routed
    assert ledger.semantic_fingerprint() == ledger_before
    assert repr(layout) == layout_before


def test_prefix_keys_and_stale_allocation_are_rejected() -> None:
    authority = _authority()
    prefixes = _prefixes(authority)
    prefixes.pop("data1")
    missing = _build(prefixes=prefixes)
    assert missing.failure_reason is BusCandidateFailureReason.INVALID_PREFIX_COVERAGE

    authority = _authority()
    prefixes = _prefixes(authority)
    prefixes["data0"] = prefixes["data0"].model_copy(update={"net_name": "/B"})
    wrong_net = _build(prefixes=prefixes)
    assert wrong_net.failure_reason is BusCandidateFailureReason.INVALID_PREFIX_COVERAGE

    _bus, _certificate, allocation, _registry, _realization = _authority()
    stale = allocation.model_copy(update={"bus_fingerprint": "f" * 64})
    stale_result = _build(allocation=stale)
    assert stale_result.failure_reason is BusCandidateFailureReason.INVALID_BUS_BINDING


def test_pairwise_domains_are_present_in_complete_final_claims() -> None:
    requirement = OrdinaryClearanceRequirement(
        requirement_id="a-b-special",
        nets_a=("/A",),
        nets_b=("/B",),
        minimum_clearance_mm=1.0,
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"pairwise_clearances": (requirement,)}
            )
        }
    )
    result = _build(profile=profile)

    assert result.success
    assert result.bundle is not None
    for route in result.bundle.member_routes:
        domain_ids = {resource.domain_id for resource in route.claims.resources}
        assert "ordinary" in domain_ids
        assert any(domain_id.startswith("pairwise-clearance-v1:") for domain_id in domain_ids)


def test_prefix_mapping_input_order_does_not_change_result_fingerprint() -> None:
    authority = _authority()
    first = _build(prefixes=_prefixes(authority))
    repeated = _build(prefixes=_prefixes(authority, reverse=True))

    assert first.semantic_fingerprint() == repeated.semantic_fingerprint()
    assert first.bundle is not None and repeated.bundle is not None
    assert first.bundle.semantic_fingerprint() == repeated.bundle.semantic_fingerprint()


def test_materialization_preserves_every_non_route_layout_field_and_rejects_target_copper() -> None:
    result = _build()
    assert result.bundle is not None
    layout, _netlist = _layout_and_netlist()
    static = replace(
        layout,
        segments=(TrackSegment(2.0, 16.0, 3.0, 16.0, "B.Cu", "/FOREIGN"),),
        vias=(ViaSpec(3.0, 16.0, "/FOREIGN"),),
        zones=(("GND", "B.Cu", (0.0, 0.0, 30.0, 18.0)),),
        outline=((0.0, 0.0), (30.0, 0.0), (28.0, 18.0), (0.0, 18.0)),
        graphics=("(gr_text preserved)",),
        part_flip=("R4",),
        hide_references=("R3",),
        part_reference_at=(("R1", (1.0, 2.0, 90.0)),),
    )

    materialized = materialize_bus_bundle(static, result.bundle)

    for field in fields(BoardLayout):
        if field.name not in {"segments", "vias"}:
            assert getattr(materialized, field.name) == getattr(static, field.name)
    assert materialized.segments[: len(static.segments)] == static.segments
    assert materialized.vias[: len(static.vias)] == static.vias
    assert len(materialized.segments) > len(static.segments)

    contaminated = replace(
        static,
        segments=(*static.segments, TrackSegment(1.0, 1.0, 2.0, 1.0, "F.Cu", "/A")),
    )
    with pytest.raises(ValueError, match="already contains target bus copper"):
        materialize_bus_bundle(contaminated, result.bundle)
