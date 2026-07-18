"""Firing tests for generated same-layer certified bus escapes."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_candidate as c2

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    BusLayerTransitionEvent,
    BusMemberViaCount,
    bus_lane_allocation_fingerprint,
)
from pcbsmith.bus_geometry import (
    CertifiedBusEscapeGraphRegistry,
    CertifiedBusEscapeRegion,
    CertifiedLaneGeometryRegistry,
)
from pcbsmith.bus_ir import BusGroup, CorridorCapacityCertificate
from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment
from pcbsmith.kicad.bus_escape import (
    BusEscapeBudget,
    BusEscapeFailureReason,
    BusEscapeGenerationResult,
    generate_certified_bus_escape_candidate,
)
from pcbsmith.kicad.negotiated_grid import CertifiedEndpointTerminalSource
from pcbsmith.kicad.negotiated_resources import OccupancyLedger, RoutingResourceKey

DEFAULT_ESCAPE_BUDGET = BusEscapeBudget(
    max_members=2,
    max_terminals=4,
    max_expansions_per_terminal=2,
    max_expansions_per_member=4,
    max_total_expansions=8,
)


@dataclass(frozen=True)
class EscapeFixture:
    layout: BoardLayout
    netlist: BoardNetlist
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    lanes: CertifiedLaneGeometryRegistry
    registry: CertifiedBusEscapeGraphRegistry
    sources: dict[str, CertifiedEndpointTerminalSource]


def _fixture() -> EscapeFixture:
    bus, certificate, allocation, lanes, _realization = c2._authority()
    layout, netlist = c2._layout_and_netlist()
    root = {
        "bus_fingerprint": bus.semantic_fingerprint(),
        "certificate_fingerprint": certificate.semantic_fingerprint(),
        "allocation_fingerprint": allocation.allocation_fingerprint,
        "lane_geometry_registry_fingerprint": lanes.semantic_fingerprint(),
        "grid_mm": 1.0,
    }
    specifications = (
        ("data0", "/A", "source", "entry", "portal:entry", "centerline:0", 4, (6, 7, 8)),
        ("data0", "/A", "sink", "exit", "portal:exit", "centerline:0", 4, (22, 23, 24)),
        ("data1", "/B", "source", "entry", "portal:entry", "centerline:1", 13, (6, 7, 8)),
        ("data1", "/B", "sink", "exit", "portal:exit", "centerline:1", 13, (22, 23, 24)),
    )
    regions = []
    for member, net, role, portal_kind, portal_id, geometry_id, y, xs in specifications:
        terminal_id = f"{member}:{role}"
        points = tuple((x, y) for x in xs)
        regions.append(
            CertifiedBusEscapeRegion(
                **root,
                region_id=f"escape:{terminal_id}",
                member_id=member,
                net_name=net,
                terminal_id=terminal_id,
                boundary_id=portal_kind,
                assigned_geometry_id=geometry_id,
                portal_kind=portal_kind,
                portal_id=portal_id,
                portal_point=points[-1] if role == "source" else points[0],
                layer="F.Cu",
                allowed_track_nodes=points,
                allowed_track_transitions=tuple(zip(points, points[1:], strict=False)),
            )
        )
    registry = CertifiedBusEscapeGraphRegistry(**root, regions=tuple(regions))
    sources = {
        "data0:source": CertifiedEndpointTerminalSource(
            component_ref="R1",
            pad_number="2",
            net_name="/A",
            physical_pad_source_id="pad:R1:1",
            source_node=("F.Cu", 6, 4),
        ),
        "data0:sink": CertifiedEndpointTerminalSource(
            component_ref="R2",
            pad_number="1",
            net_name="/A",
            physical_pad_source_id="pad:R2:0",
            source_node=("F.Cu", 24, 4),
        ),
        "data1:source": CertifiedEndpointTerminalSource(
            component_ref="R3",
            pad_number="2",
            net_name="/B",
            physical_pad_source_id="pad:R3:1",
            source_node=("F.Cu", 6, 13),
        ),
        "data1:sink": CertifiedEndpointTerminalSource(
            component_ref="R4",
            pad_number="1",
            net_name="/B",
            physical_pad_source_id="pad:R4:0",
            source_node=("F.Cu", 24, 13),
        ),
    }
    return EscapeFixture(
        layout,
        netlist,
        bus,
        certificate,
        allocation,
        lanes,
        registry,
        sources,
    )


def _run(
    fixture: EscapeFixture,
    *,
    layout: BoardLayout | None = None,
    netlist: BoardNetlist | None = None,
    allocation: BusLaneAllocationResult | None = None,
    registry: CertifiedBusEscapeGraphRegistry | None = None,
    sources: dict[str, CertifiedEndpointTerminalSource] | None = None,
    ledger: OccupancyLedger | None = None,
    budget: BusEscapeBudget = DEFAULT_ESCAPE_BUDGET,
    history: dict[RoutingResourceKey, int] | None = None,
    present_factor_units: int = 0,
    hard_forbidden: frozenset[RoutingResourceKey] = frozenset(),
) -> BusEscapeGenerationResult:
    return generate_certified_bus_escape_candidate(
        layout or fixture.layout,
        netlist or fixture.netlist,
        fixture.bus,
        fixture.certificate,
        allocation or fixture.allocation,
        fixture.lanes,
        registry or fixture.registry,
        sources or fixture.sources,
        ledger or OccupancyLedger(),
        budget,
        c2.DEFAULT_BUDGET,
        history=history,
        present_factor_units=present_factor_units,
        hard_forbidden_resources=hard_forbidden,
    )


def _replace_region(
    registry: CertifiedBusEscapeGraphRegistry,
    terminal_id: str,
    **changes: object,
) -> CertifiedBusEscapeGraphRegistry:
    regions = []
    for region in registry.regions:
        payload = region.model_dump()
        if region.terminal_id == terminal_id:
            payload.update(changes)
        regions.append(CertifiedBusEscapeRegion.model_validate(payload))
    root = registry.model_dump(exclude={"regions"})
    return CertifiedBusEscapeGraphRegistry(**root, regions=tuple(regions))


def _reverse_registry(
    registry: CertifiedBusEscapeGraphRegistry,
) -> CertifiedBusEscapeGraphRegistry:
    regions = []
    for region in reversed(registry.regions):
        payload = region.model_dump()
        payload["allowed_track_nodes"] = tuple(reversed(region.allowed_track_nodes))
        payload["allowed_track_transitions"] = tuple(
            (second, first) for first, second in reversed(region.allowed_track_transitions)
        )
        regions.append(CertifiedBusEscapeRegion.model_validate(payload))
    root = registry.model_dump(exclude={"regions"})
    return CertifiedBusEscapeGraphRegistry(**root, regions=tuple(regions))


def test_real_generated_pigtails_prefixes_and_c2_candidate_are_pinned_and_pure() -> None:
    fixture = _fixture()
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    result = _run(fixture, ledger=ledger)

    assert result.success
    assert result.failure_reason is None
    assert result.escape_expansion_count == 8
    assert result.terminal_order == (
        "data0:sink",
        "data0:source",
        "data1:sink",
        "data1:source",
    )
    assert tuple(item.expansion_count for item in result.terminal_telemetry) == (2, 2, 2, 2)
    assert tuple((item.member_id, item.expansion_count) for item in result.member_telemetry) == (
        ("data0", 4),
        ("data1", 4),
    )
    assert tuple((item.terminal_id, item.points) for item in result.pigtails) == (
        ("data0:sink", ((24, 4), (22, 4))),
        ("data0:source", ((6, 4), (8, 4))),
        ("data1:sink", ((24, 13), (22, 13))),
        ("data1:source", ((6, 13), (8, 13))),
    )
    assert tuple(key for key, _prefix in result.prefixes_by_member) == ("data0", "data1")
    assert result.candidate is not None and result.candidate.success
    assert result.candidate.expansion_count == 0
    assert result.candidate.bundle is not None
    assert len(result.candidate.bundle.member_routes) == 2
    assert ledger.semantic_fingerprint() == before
    assert ledger.committed_claims() == ()
    assert result.semantic_fingerprint() == (
        "1ca9c2929e07b8d68758b6d3a9b5592a60e7ca3a289cbaf73a9ad516144bf9fd"
    )
    assert result.input_fingerprint == (
        "bb4ad6be02211d9f45d15afc3d6c16b8acb8b822e69362c824ef60cf4c6d8f6c"
    )
    assert fixture.registry.semantic_fingerprint() == (
        "10d709ff4388f0e72edcddb8e81db39aba07bf265e9b93ad84645565c9a63892"
    )
    assert (
        not {
            "exact_checker",
            "exact_clearance",
            "materialized_board",
            "committed_board",
        }
        & result.model_fields_set
    )


def test_reversed_construction_is_byte_deterministic() -> None:
    fixture = _fixture()
    baseline = _run(fixture)
    reversed_layout = replace(
        fixture.layout,
        placements=tuple(reversed(fixture.layout.placements)),
        part_y_mm=tuple(reversed(fixture.layout.part_y_mm)),
    )
    reversed_netlist = replace(
        fixture.netlist,
        components=tuple(reversed(fixture.netlist.components)),
        nets=tuple(
            replace(net, nodes=tuple(reversed(net.nodes))) for net in reversed(fixture.netlist.nets)
        ),
    )
    reverse = _run(
        fixture,
        layout=reversed_layout,
        netlist=reversed_netlist,
        registry=_reverse_registry(fixture.registry),
        sources=dict(reversed(tuple(fixture.sources.items()))),
    )

    assert reverse.success
    assert baseline.semantic_json() == reverse.semantic_json()
    assert baseline.semantic_fingerprint() == reverse.semantic_fingerprint()


def test_wrong_sources_graph_portal_lane_and_stale_root_fail_typed_and_pure() -> None:
    fixture = _fixture()
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    wrong_sources = dict(fixture.sources)
    wrong_sources["data0:sink"] = replace(
        wrong_sources["data0:sink"],
        component_ref="R9",
    )
    cases = (
        (
            _run(fixture, sources=wrong_sources, ledger=ledger),
            BusEscapeFailureReason.INVALID_SOURCE_BINDING,
        ),
        (
            _run(
                fixture,
                registry=_replace_region(
                    fixture.registry,
                    "data0:source",
                    allowed_track_nodes=((7, 4), (8, 4)),
                    allowed_track_transitions=(((7, 4), (8, 4)),),
                ),
                ledger=ledger,
            ),
            BusEscapeFailureReason.INVALID_SOURCE_BINDING,
        ),
        (
            _run(
                fixture,
                registry=_replace_region(
                    fixture.registry,
                    "data0:sink",
                    portal_point=(23, 4),
                ),
                ledger=ledger,
            ),
            BusEscapeFailureReason.INVALID_ESCAPE_AUTHORITY,
        ),
        (
            _run(
                fixture,
                registry=_replace_region(
                    fixture.registry,
                    "data0:sink",
                    assigned_geometry_id="centerline:1",
                ),
                ledger=ledger,
            ),
            BusEscapeFailureReason.INVALID_ESCAPE_AUTHORITY,
        ),
    )
    stale_regions = []
    for region in fixture.registry.regions:
        payload = region.model_dump()
        payload["bus_fingerprint"] = "0" * 64
        stale_regions.append(CertifiedBusEscapeRegion.model_validate(payload))
    stale_root = fixture.registry.model_dump(exclude={"regions"})
    stale_root["bus_fingerprint"] = "0" * 64
    stale_registry = CertifiedBusEscapeGraphRegistry(
        **stale_root,
        regions=tuple(stale_regions),
    )
    cases += (
        (
            _run(fixture, registry=stale_registry, ledger=ledger),
            BusEscapeFailureReason.INVALID_ESCAPE_AUTHORITY,
        ),
    )

    for result, reason in cases:
        assert not result.success
        assert result.failure_reason is reason
        assert result.candidate is None
        assert result.caller_ledger_before_fingerprint == before
        assert result.caller_ledger_after_fingerprint == before
    assert ledger.semantic_fingerprint() == before


def test_graph_binding_cannot_escape_to_a_cheaper_wrong_lane() -> None:
    fixture = _fixture()
    expensive_correct_edge = RoutingResourceKey(
        "ordinary",
        "F.Cu",
        "edge",
        23,
        4,
        24,
        4,
    )
    result = _run(
        fixture,
        history={expensive_correct_edge: 1_000_000},
        present_factor_units=1,
    )

    assert result.success
    assert tuple((p.member_id, p.portal_point[1]) for p in result.pigtails) == (
        ("data0", 4),
        ("data0", 4),
        ("data1", 13),
        ("data1", 13),
    )
    assert all(len(p.points) == 2 for p in result.pigtails)


@pytest.mark.parametrize("collision_kind", ("static", "hard"))
def test_static_and_hard_resource_collisions_are_typed_and_pure(
    collision_kind: str,
) -> None:
    fixture = _fixture()
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()
    layout = fixture.layout
    hard = frozenset()
    if collision_kind == "static":
        layout = replace(
            layout,
            segments=(TrackSegment(23.0, 3.0, 23.0, 5.0, "F.Cu", "/BLOCK", 0.4),),
        )
    else:
        hard = frozenset((RoutingResourceKey("ordinary", "F.Cu", "edge", 23, 4, 24, 4),))

    result = _run(fixture, layout=layout, ledger=ledger, hard_forbidden=hard)

    assert not result.success
    assert result.failure_reason is BusEscapeFailureReason.ROUTING_ERROR
    assert result.failed_terminal_id == "data0:sink"
    assert result.escape_expansion_count > 0
    assert result.candidate is None
    assert ledger.semantic_fingerprint() == before


def test_late_member_terminal_failure_retains_attempted_work_without_mutation() -> None:
    fixture = _fixture()
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()
    forbidden = RoutingResourceKey("ordinary", "F.Cu", "edge", 6, 13, 7, 13)

    result = _run(
        fixture,
        ledger=ledger,
        hard_forbidden=frozenset((forbidden,)),
    )

    assert not result.success
    assert result.failure_reason is BusEscapeFailureReason.ROUTING_ERROR
    assert result.failed_member_id == "data1"
    assert result.failed_terminal_id == "data1:source"
    assert tuple(item.terminal_id for item in result.terminal_telemetry) == result.terminal_order
    assert tuple(item.routed for item in result.terminal_telemetry) == (
        True,
        True,
        True,
        False,
    )
    assert len(result.pigtails) == 3
    assert tuple(key for key, _prefix in result.prefixes_by_member) == ("data0",)
    assert tuple(item.completed for item in result.member_telemetry) == (True, False)
    assert result.escape_expansion_count == sum(
        item.expansion_count for item in result.terminal_telemetry
    )
    assert result.candidate is None
    assert ledger.semantic_fingerprint() == before


@pytest.mark.parametrize(
    ("budget", "reason", "work"),
    (
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=0,
                max_expansions_per_member=4,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.PER_TERMINAL_EXPANSION_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=1,
                max_expansions_per_member=4,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.PER_TERMINAL_EXPANSION_BUDGET,
            1,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=0,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.PER_MEMBER_EXPANSION_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=3,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.PER_MEMBER_EXPANSION_BUDGET,
            3,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=4,
                max_total_expansions=0,
            ),
            BusEscapeFailureReason.TOTAL_EXPANSION_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=4,
                max_total_expansions=7,
            ),
            BusEscapeFailureReason.TOTAL_EXPANSION_BUDGET,
            7,
        ),
    ),
)
def test_zero_and_one_less_terminal_member_and_total_budgets_report_exact_work(
    budget: BusEscapeBudget,
    reason: BusEscapeFailureReason,
    work: int,
) -> None:
    fixture = _fixture()
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    result = _run(fixture, budget=budget, ledger=ledger)

    assert not result.success
    assert result.failure_reason is reason
    assert result.escape_expansion_count == work
    assert result.terminal_telemetry[-1].expansion_count in (0, 1)
    assert result.terminal_telemetry[-1].routing_failure_reason is not None
    assert result.candidate is None
    assert ledger.semantic_fingerprint() == before


def test_source_at_portal_is_explicitly_unsupported_without_zero_length_copper() -> None:
    fixture = _fixture()
    sources = dict(fixture.sources)
    sources["data0:sink"] = replace(
        sources["data0:sink"],
        source_node=("F.Cu", 22, 4),
    )

    result = _run(fixture, sources=sources)

    assert not result.success
    assert result.failure_reason is BusEscapeFailureReason.SOURCE_AT_PORTAL_UNSUPPORTED
    assert result.failed_terminal_id == "data0:sink"
    assert result.escape_expansion_count == 0
    assert result.pigtails == ()
    assert result.prefixes_by_member == ()
    assert result.candidate is None


def test_transition_event_is_explicitly_rejected_before_escape_authority() -> None:
    fixture = _fixture()
    transition = BusLayerTransitionEvent(
        section_id="trunk",
        boundary_id="exit",
        window_id="window:test",
        member_id="data0",
        from_layer="F.Cu",
        to_layer="B.Cu",
    )
    via_counts = (
        BusMemberViaCount(member_id="data0", via_count=1),
        BusMemberViaCount(member_id="data1", via_count=0),
    )
    fingerprint = bus_lane_allocation_fingerprint(
        bus_fingerprint=fixture.allocation.bus_fingerprint,
        certificate_fingerprint=fixture.allocation.certificate_fingerprint,
        normalized_boundary_orders=fixture.allocation.normalized_boundary_orders,
        assignments=fixture.allocation.assignments,
        activations=fixture.allocation.activations,
        swaps=fixture.allocation.swaps,
        layer_transitions=(transition,),
        via_counts=via_counts,
        permutation_boundary_ids=fixture.allocation.permutation_boundary_ids,
    )
    payload = fixture.allocation.model_dump()
    payload.update(
        {
            "layer_transition_count": 1,
            "layer_transitions": (transition,),
            "via_counts": via_counts,
            "allocation_fingerprint": fingerprint,
        }
    )
    allocation = BusLaneAllocationResult.model_validate(payload)

    result = _run(fixture, allocation=allocation)

    assert not result.success
    assert result.failure_reason is BusEscapeFailureReason.TRANSITION_VIAS_UNSUPPORTED
    assert result.terminal_telemetry == ()
    assert result.pigtails == ()
    assert result.candidate is None


def test_result_revalidates_nested_authority_and_input_fingerprint() -> None:
    result = _run(_fixture())
    assert result.success

    stale_input = json.loads(result.model_dump_json())
    stale_input["input_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="input fingerprint is stale"):
        BusEscapeGenerationResult.model_validate(stale_input)

    stale_pigtail = json.loads(result.model_dump_json())
    stale_pigtail["pigtails"][0]["portal_point"] = (21, 4)
    with pytest.raises(ValidationError):
        BusEscapeGenerationResult.model_validate(stale_pigtail)
